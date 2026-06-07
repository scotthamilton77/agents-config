from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PluginAdapter(Protocol):
    """Plugin-specific behaviour the engine consults. Unlike `ToolAdapter`,
    plugins are not enumerated — they are discovered by scanning a plugins
    root and registered by name string, so the registry knows each plugin's
    source directory at discovery time and the adapter carries it as
    `source_path` rather than reconstructing it from `repo_root`.

    F.1 needs exactly these three members. Namespace routing, destinations,
    and chmod are out of scope: the F.2 overlay reuses the *tool* adapter's
    namespace rules, and beads' `~/.beads/` destination + `chmod +x` are F.4
    concerns on a future specialized adapter. They are added to this protocol
    additively when a consumer exists."""

    name: str
    # Absolute path to the plugin's source tree, set by the registry at
    # discovery time (e.g. `<repo>/src/plugins/beads`).
    source_path: Path

    def is_detected(self, home: Path) -> bool: ...  # pragma: no cover
