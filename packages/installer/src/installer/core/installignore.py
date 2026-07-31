"""Loader for ``.installignore`` — the shared source-file exclusion manifest
consumed by the Python installer at the staging step.

Unlike ``load_installer_toml`` (a missing file is an inert default), a missing or
unreadable ``.installignore`` is a HARD ERROR: the manifest encodes load-bearing
exclusion policy, so silently treating absence as "exclude nothing" would
re-leak namespace dev-docs identically across every install. Fail-fast turns
every missing/wrong-root/absent-in-fixture mode into a loud error.

Grammar (see the ``.installignore`` header for the canonical spec): one
pattern per line; ``#`` comments and blank lines are ignored. A trailing
``/`` marks a DIRECTORY pattern (matched against directory names only);
without it, the pattern is a FILE pattern (matched against file basenames
only). A leading ``/`` ANCHORS the pattern to the direct children of a
staged namespace subdirectory — the only scope this manifest reaches without
it; an unanchored pattern matches at any depth, including inside a DIR
item's own interior (a skill's nested ``scripts/`` subdir, for instance).
``*``, ``?`` and ``[...]`` make a pattern a glob, matched with
``fnmatch.fnmatchcase`` against a single path component (case-sensitive); a
name with none of those characters matches exactly. A ``/`` anywhere other
than the leading or trailing position is a parse error. No ``**``, no
negation.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

_GLOB_CHARS = frozenset("*?[")


@dataclass(frozen=True, slots=True)
class _Pattern:
    """One parsed manifest line: matches a single path component of the
    stated kind (file vs directory) at the stated scope (anchored-only vs
    any depth), either literally or as an ``fnmatch`` glob."""

    text: str
    is_dir: bool
    anchored: bool
    is_glob: bool

    def matches(self, name: str) -> bool:
        return fnmatch.fnmatchcase(name, self.text) if self.is_glob else name == self.text


@dataclass(frozen=True, slots=True)
class InstallIgnore:
    """Parsed manifest: the ordered set of exclusion patterns.

    ``excludes`` is the single match primitive every consumer (namespace
    staging, the DIR-item copy filter, the DIR idempotency check) shares, so
    the anchored/any-depth and file/dir distinctions can never be applied
    inconsistently across call sites.
    """

    patterns: tuple[_Pattern, ...] = field(default_factory=tuple)

    def excludes(self, name: str, *, is_dir: bool, at_root: bool) -> bool:
        """Whether ``name`` (a bare path component, no path separators) is
        excluded.

        ``is_dir`` selects file-pattern vs directory-pattern candidates.
        ``at_root`` is True only when ``name`` is a direct child of a staged
        namespace subdirectory — the sole scope an anchored (leading-``/``)
        pattern reaches. An unanchored pattern matches regardless of
        ``at_root``, since "any depth" includes the root.
        """
        return any(
            p.is_dir == is_dir and (at_root or not p.anchored) and p.matches(name)
            for p in self.patterns
        )


def load_installignore(path: Path) -> InstallIgnore:
    """Parse ``.installignore`` at ``path``; return an ``InstallIgnore``.

    Raises ``FileNotFoundError`` when the file is absent (fail-fast — see module
    docstring). A present-but-unreadable file raises naturally from ``read_text``
    (``PermissionError`` / ``OSError``); a non-UTF-8 file raises
    ``UnicodeDecodeError`` (a ``ValueError``, not an ``OSError``). The CLI catches
    both ``OSError`` and ``UnicodeDecodeError`` and surfaces them as exit 2.
    Raises ``ValueError`` when a line's ``/`` is not purely leading/trailing —
    a parse error, not a silently-ignored partial match.
    """
    if not path.is_file():
        msg = f".installignore not found at {path}; refusing to install with exclusions disabled"
        raise FileNotFoundError(msg)

    patterns: list[_Pattern] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        anchored = line.startswith("/")
        if anchored:
            line = line[1:]
        is_dir = line.endswith("/")
        if is_dir:
            line = line[:-1]
        if not line:
            # A degenerate "/" (or "//") line has no name to match; skip it —
            # parity with the loader's historical bare-slash tolerance.
            continue
        if "/" in line:
            raise ValueError(  # noqa: TRY003  # single call-site; subclass not justified
                f".installignore:{lineno}: '/' only allowed as leading/trailing: {raw!r}"
            )
        is_glob = not _GLOB_CHARS.isdisjoint(line)
        patterns.append(_Pattern(text=line, is_dir=is_dir, anchored=anchored, is_glob=is_glob))
    return InstallIgnore(patterns=tuple(patterns))
