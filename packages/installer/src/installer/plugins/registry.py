from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from installer.plugins.base import PluginAdapter
from installer.plugins.beads import BeadsPlugin
from installer.plugins.generic import GenericPluginAdapter

# name -> factory for plugins needing behaviour the generic adapter cannot
# express. A factory is `(name, source_path) -> PluginAdapter` — a concrete
# class whose __init__ matches that shape satisfies it (typing it as
# `type[PluginAdapter]` would wrongly imply instantiating the Protocol).
_SPECIALIZED: dict[str, Callable[[str, Path], PluginAdapter]] = {"beads": BeadsPlugin}


class UnknownPluginError(ValueError):
    """Raised when a `--plugins=` element names a plugin absent from the
    discovered set. Structured attrs (.name, .valid) so callers and tests
    assert on data, not the message string."""

    def __init__(self, name: str, valid: tuple[str, ...]) -> None:
        super().__init__(f"Unknown plugin: {name!r} (valid: {', '.join(valid)})")
        self.name = name
        self.valid = valid


def discover(
    plugins_root: Path,
    *,
    specialized: Mapping[str, Callable[[str, Path], PluginAdapter]] = _SPECIALIZED,
) -> dict[str, PluginAdapter]:
    """Discover plugins by scanning the direct subdirectories of
    `plugins_root`. Non-directory entries (e.g. `AGENTS.md`) and `.`/`_`-
    prefixed directories are skipped. Each plugin gets a `GenericPluginAdapter`
    unless its name is in `specialized`. Returns a name-keyed mapping; entries
    are sorted by name for deterministic downstream ordering."""
    discovered: dict[str, PluginAdapter] = {}
    for entry in sorted(plugins_root.iterdir()):
        name = entry.name
        if not entry.is_dir() or name.startswith((".", "_")):
            continue
        factory: Callable[[str, Path], PluginAdapter] = specialized.get(name, GenericPluginAdapter)
        discovered[name] = factory(name, entry)
    return discovered
