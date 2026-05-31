"""DYNAMIC-INCLUDE flattening for instruction templates.

Some tools do not resolve `@`-style includes, so instruction templates carry
inline markers that are flattened into a single self-contained file at install
time. B.4 implements the **file form**::

    <!-- DYNAMIC-INCLUDE: path/to/file.md -->

A line that is exactly this marker is replaced by the verbatim text of the
referenced file (resolved relative to a base directory). A missing target warns
and leaves the line empty. The behavioural reference is the bash installer's
``flatten_agents_md`` (``scripts/install.sh``).

`parse_directive` also recognises the ALL-RULES form so directive recognition is
complete, but *resolving* ALL-RULES is deferred to story C.2; `flatten_template`
raises `NotImplementedError` if it encounters one rather than silently emitting a
literal marker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from installer.core.model import AllRulesInclude, FileInclude, IncludeDirective

if TYPE_CHECKING:
    from installer.core.io_port import IOPort

_FILE_INCLUDE_RE = re.compile(r"^<!-- DYNAMIC-INCLUDE: (.*) -->$")
_ALL_RULES_RE = re.compile(r"^<!-- DYNAMIC-INCLUDE-ALL-RULES -->$")
_ALL_RULES_DEFERRED = "DYNAMIC-INCLUDE-ALL-RULES resolution lands in story C.2"


def parse_directive(line: str) -> IncludeDirective | None:
    """Recognise a DYNAMIC-INCLUDE directive on a single line.

    The line must match a marker form exactly — no leading or trailing
    whitespace — mirroring the anchored ``^...$`` patterns in the bash
    installer. A file marker with an empty path is rejected, matching the bash
    ``-n`` guard. Returns the matching directive dataclass, or None for any
    line that is not a directive (including the deferred named-RULES form).
    """
    stripped = line.rstrip("\n")
    file_match = _FILE_INCLUDE_RE.match(stripped)
    if file_match is not None and file_match.group(1):
        return FileInclude(path=Path(file_match.group(1)))
    if _ALL_RULES_RE.match(stripped) is not None:
        return AllRulesInclude()
    return None


def flatten_template(content: str, *, base_dir: Path, io: IOPort) -> str:
    """Flatten DYNAMIC-INCLUDE file markers in a template's text.

    Each file-marker line is replaced by the verbatim text of the referenced
    file (read as UTF-8), resolved relative to ``base_dir``. The marker line and
    its own newline are consumed; no separator is injected, so an included file
    without a trailing newline abuts the template's next line — matching
    ``cat file >> output``. A target that is not a regular file emits a warning
    and resolves to the empty string, leaving the marker line empty.
    Non-directive lines pass through unchanged, and the template's trailing
    newline is preserved iff the template had one.

    ALL-RULES resolution is deferred to story C.2.
    """
    out: list[str] = []
    for line in content.splitlines(keepends=True):
        directive = parse_directive(line)
        if directive is None:
            out.append(line)
            continue
        match directive:
            case FileInclude(path=rel):
                out.append(_resolve_file_include(rel, base_dir=base_dir, io=io))
            case AllRulesInclude():
                raise NotImplementedError(_ALL_RULES_DEFERRED)
            case _:  # pragma: no cover - exhaustiveness guard for future variants
                assert_never(directive)
    return "".join(out)


def _resolve_file_include(rel: Path, *, base_dir: Path, io: IOPort) -> str:
    """Read the verbatim text of an included file, or warn and return ''.

    Mirrors the bash ``[[ -f ... ]]`` guard: a missing target *or* a directory
    is non-fatal — it warns and resolves to the empty string.
    """
    target = base_dir / rel
    if not target.is_file():
        io.warn(f"DYNAMIC-INCLUDE not found: {rel}")
        return ""
    return target.read_text(encoding="utf-8")
