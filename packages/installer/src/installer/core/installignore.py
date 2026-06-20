"""Loader for ``.installignore`` — the shared source-file exclusion manifest
consumed by BOTH installers at the staging step.

Unlike ``load_installer_toml`` (a missing file is an inert default), a missing or
unreadable ``.installignore`` is a HARD ERROR: the manifest encodes load-bearing
exclusion policy, so silently treating absence as "exclude nothing" would
re-leak namespace dev-docs identically on both installers — the shared-wrongness
case the golden-master parity oracle cannot see. Fail-fast turns every
missing/wrong-root/absent-in-fixture mode into a loud error.

Grammar (simple subset, identical to the bash matcher in
``scripts/lib/installignore.sh``): one entry per line; ``#`` comment lines and
blank lines ignored; an exact basename matches a file; a trailing-``/`` name
matches a directory. No globs, no ``**``, no negation, no anchoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstallIgnore:
    """Parsed manifest: the set of excluded file basenames and directory names.

    ``excludes`` is the single match primitive both staging and the parity test
    consult; a file is tested against ``basenames``, a directory against
    ``dirnames``, so the same name can never accidentally cross kinds.
    """

    basenames: frozenset[str] = field(default_factory=frozenset)
    dirnames: frozenset[str] = field(default_factory=frozenset)

    def excludes(self, name: str, *, is_dir: bool) -> bool:
        return name in (self.dirnames if is_dir else self.basenames)


def load_installignore(path: Path) -> InstallIgnore:
    """Parse ``.installignore`` at ``path``; return an ``InstallIgnore``.

    Raises ``FileNotFoundError`` when the file is absent (fail-fast — see module
    docstring). A present-but-unreadable file raises naturally from ``read_text``
    (``PermissionError`` / ``OSError``). Both are surfaced cleanly by the CLI as
    exit 2.
    """
    if not path.is_file():
        msg = f".installignore not found at {path}; refusing to install with exclusions disabled"
        raise FileNotFoundError(msg)

    basenames: set[str] = set()
    dirnames: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/"):
            name = line[:-1]
            if name:  # a bare "/" has no directory name; skip it (parity with bash)
                dirnames.add(name)
        else:
            basenames.add(line)
    return InstallIgnore(basenames=frozenset(basenames), dirnames=frozenset(dirnames))
