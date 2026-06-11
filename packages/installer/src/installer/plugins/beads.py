from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from installer.plugins.base import PluginRoute


@dataclass(frozen=True, slots=True)
class BeadsPlugin:
    """Specialized `PluginAdapter` for the beads issue tracker.

    Beads is unlike a generic plugin in two ways the protocol now expresses
    additively:

    * **Detection** — beads is present if `bd` is on PATH *or* `~/.beads/`
      exists as a directory. The generic convention checks only the home
      footprint; the PATH probe is beads-specific (a user with `bd` installed
      but no `~/.beads/` yet still wants the formulas).
    * **Destination** — beads' formulas and scripts do not overlay into a tool
      tree. They route to `~/.beads/formulas/` and `~/.beads/scripts/`, the
      latter with the executable bit set. `routes()` returns those bespoke
      destinations; the sync engine reads them without beads-specific code.

    `which` is injected (default `shutil.which`) so the PATH probe is testable
    without depending on whether `bd` happens to be installed on the runner.
    """

    name: str
    source_path: Path
    which: Callable[[str], str | None] = field(default=shutil.which)

    def is_detected(self, home: Path) -> bool:
        return self.which("bd") is not None or (home / ".beads").is_dir()

    def routes(self, home: Path) -> tuple[PluginRoute, ...]:
        beads_src = self.source_path / ".beads"
        beads_dest = home / ".beads"
        return (
            PluginRoute(
                source_dir=beads_src / "formulas",
                dest_dir=beads_dest / "formulas",
                glob="*.toml",
                executable=False,
            ),
            PluginRoute(
                source_dir=beads_src / "scripts",
                dest_dir=beads_dest / "scripts",
                glob="*.sh",
                executable=True,
            ),
        )
