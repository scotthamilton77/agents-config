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

    # Read-only members (declared as properties) so a frozen dataclass adapter
    # — `GenericPluginAdapter`, and any future specialized adapter — structurally
    # satisfies this protocol. A plain `name: str` annotation is a *settable*
    # protocol member, which a `frozen=True` dataclass cannot match under
    # mypy --strict ("expected settable variable, got read-only attribute").
    @property
    def name(self) -> str: ...  # pragma: no cover

    # Absolute path to the plugin's source tree, set by the registry at
    # discovery time (e.g. `<repo>/src/plugins/beads`).
    @property
    def source_path(self) -> Path: ...  # pragma: no cover

    def is_detected(self, home: Path) -> bool: ...  # pragma: no cover
