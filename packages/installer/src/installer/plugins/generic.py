from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GenericPluginAdapter:
    """Default `PluginAdapter` for a discovered plugin with no specialized
    class. Auto-detects on its home footprint: `~/.<name>/` present as a
    directory. A specialized adapter (e.g. beads in F.4) overrides
    `is_detected` to add probes the generic convention cannot express, such
    as `shutil.which("bd")`."""

    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:
        return (home / f".{self.name}").is_dir()
