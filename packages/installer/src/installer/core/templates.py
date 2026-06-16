"""DYNAMIC-INCLUDE flattening for instruction templates.

Some tools do not resolve `@`-style includes, so instruction templates carry
inline markers that are flattened into a single self-contained file at install
time. Two directive forms are supported:

File form (B.4)::

    <!-- DYNAMIC-INCLUDE: path/to/file.md -->

A line that is exactly this marker is replaced by the verbatim text of the
referenced file (resolved relative to a base directory). A missing target warns
and leaves the line empty.

ALL-RULES form (C.2)::

    <!-- DYNAMIC-INCLUDE-ALL-RULES -->

A line that is exactly this marker is replaced by all ``*.md`` files in the
caller-supplied ``rules_dir``, sorted lexicographically by filename, joined
with ``\\n---\\n`` between adjacent rules. An absent or empty ``rules_dir``
emits a warning and resolves to the empty string.

The behavioural reference is the bash installer's ``flatten_agents_md``
(``scripts/install.sh``). The named-RULES form (C.3) is deferred; its marker
is not yet recognised and passes through as a non-directive line.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from installer.core.model import AllRulesInclude, FileInclude, IncludeDirective
from installer.core.paths import is_safe_relpath
from installer.core.staging import strip_template_suffix

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan

_FILE_INCLUDE_RE = re.compile(r"^<!-- DYNAMIC-INCLUDE: (.*) -->$")
_ALL_RULES_RE = re.compile(r"^<!-- DYNAMIC-INCLUDE-ALL-RULES -->$")

# Tool-root instruction files the bash installer flattens (install.sh:854):
# ``AGENTS.md.template`` and ``GEMINI.md.template`` — here keyed by their
# ``.template``-stripped dest, which is how the plan stores them.
_FLATTENABLE_DESTS: tuple[Path, ...] = (Path("AGENTS.md"), Path("GEMINI.md"))


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


def flatten_template(
    content: str,
    *,
    base_dir: Path,
    io: IOPort,
    rules_dir: Path | None = None,
) -> str:
    """Flatten DYNAMIC-INCLUDE markers in a template's text.

    Each file-marker line is replaced by the verbatim text of the referenced
    file (read as UTF-8), resolved relative to ``base_dir``. The marker line and
    its own newline are consumed; no separator is injected, so an included file
    without a trailing newline abuts the template's next line — matching
    ``cat file >> output``. A target that is not a regular file emits a warning
    and resolves to the empty string, leaving the marker line empty.

    An ALL-RULES marker line is replaced by all ``*.md`` files in ``rules_dir``,
    sorted lexicographically by filename, joined with ``\\n---\\n`` between
    adjacent rules. An absent or empty ``rules_dir`` emits a warning and resolves
    to the empty string.

    Non-directive lines pass through unchanged, and the template's trailing
    newline is preserved iff the template had one.
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
                out.append(_resolve_all_rules(rules_dir=rules_dir, io=io))
            case _:  # pragma: no cover - exhaustiveness guard for future variants
                assert_never(directive)
    return "".join(out)


def flatten_plan_templates(plan: StagingPlan, *, repo_root: Path, io: IOPort) -> None:
    """Phase 6.5/6.75: flatten the plan's instruction templates, then drop the
    include-only templates they inline.

    Mirrors the bash installer (``scripts/install.sh:849-890``): for each
    flattenable instruction file present in the plan (``AGENTS.md`` /
    ``GEMINI.md``), replace its content with the DYNAMIC-INCLUDE-flattened text —
    file includes resolved from ``repo_root``, ALL-RULES from the plan's own
    staged rules — then remove the include-only templates from the plan so they
    are not also deployed standalone. Mutates ``plan`` in place.
    """
    include_only: set[Path] = set()
    for dest in _FLATTENABLE_DESTS:
        item = plan.items.get(dest)
        if item is None or item.content is None:
            continue
        text = item.content.decode("utf-8")
        include_only |= _file_include_dests(text)
        flattened = _flatten_with_plan_rules(text, plan=plan, repo_root=repo_root, io=io)
        plan.items[dest] = replace(item, content=flattened.encode("utf-8"))
    for dest in include_only:
        plan.items.pop(dest, None)


def _file_include_dests(text: str) -> set[Path]:
    """The dests of the include-only templates referenced by file markers.

    Each marker's basename, ``.template``-stripped, is how the plan stores the
    standalone copy — those are what Phase 6.75 removes.
    """
    dests: set[Path] = set()
    for line in text.splitlines():
        directive = parse_directive(line)
        if isinstance(directive, FileInclude):
            dests.add(strip_template_suffix(Path(directive.path.name)))
    return dests


def _flatten_with_plan_rules(text: str, *, plan: StagingPlan, repo_root: Path, io: IOPort) -> str:
    """Flatten ``text``, sourcing ALL-RULES from the plan's staged ``rules/``.

    The bash installer reads ALL-RULES from the on-disk staging tree; the Python
    installer stages in memory, so when (and only when) the template needs rules
    they are materialised to a temp dir for ``flatten_template`` to read —
    matching ``find $staging/rules -name '*.md' | sort``.
    """
    needs_rules = any(
        isinstance(parse_directive(line), AllRulesInclude) for line in text.splitlines()
    )
    if not needs_rules:
        return flatten_template(text, base_dir=repo_root, io=io, rules_dir=None)
    with tempfile.TemporaryDirectory() as tmp:
        rules_dir = Path(tmp)
        for rel, staged in plan.items.items():
            if staged.namespace == "rules" and staged.content is not None:
                (rules_dir / rel.name).write_bytes(staged.content)
        return flatten_template(text, base_dir=repo_root, io=io, rules_dir=rules_dir)


def _resolve_all_rules(*, rules_dir: Path | None, io: IOPort) -> str:
    """Expand the ALL-RULES directive to the concatenated content of all *.md
    files in ``rules_dir``, sorted lexicographically by filename, joined with
    ``\\n---\\n`` between adjacent rules.

    Mirrors the bash installer's ALL-RULES handler (``scripts/install.sh:730-745``):
    ``find ... | LC_ALL=C sort`` over rule files, cat each, ``printf '\\n---\\n'``
    between them, warn if the collection is empty.
    """
    rule_files: list[Path] = []
    if rules_dir is not None and rules_dir.is_dir():
        rule_files = sorted(p for p in rules_dir.glob("*.md") if p.is_file())
    if not rule_files:
        io.warn(f"DYNAMIC-INCLUDE-ALL-RULES: no rules found in {rules_dir or '(no rules_dir)'}")
        return ""
    return "\n---\n".join(p.read_text(encoding="utf-8") for p in rule_files)


def _resolve_file_include(rel: Path, *, base_dir: Path, io: IOPort) -> str:
    """Read the verbatim text of an included file, or warn and return ''.

    Mirrors the bash ``[[ -f ... ]]`` guard: a missing target *or* a directory
    is non-fatal — it warns and resolves to the empty string.

    Raises ``ValueError`` for absolute paths or paths containing ``..`` —
    either would let ``base_dir / rel`` escape ``base_dir`` (rejected by the
    shared lexical ``is_safe_relpath`` guard, which does not resolve symlinks).
    """
    if not is_safe_relpath(rel):
        raise ValueError(f"DYNAMIC-INCLUDE path escapes base_dir: {rel}")  # noqa: TRY003  # single call-site; subclass not justified
    target = base_dir / rel
    if not target.is_file():
        io.warn(f"DYNAMIC-INCLUDE not found: {rel}")
        return ""
    return target.read_text(encoding="utf-8")
