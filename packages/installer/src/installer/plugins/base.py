from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PluginRoute:
    """One bespoke source→destination route for a plugin whose content does
    NOT overlay into a tool tree.

    Generic plugins have no routes — their content installs through the
    per-tool namespace overlay (F.2). A specialized adapter like beads, whose
    formulas and scripts land outside any tool tree (`~/.beads/`), declares its
    destinations here so the sync engine can place files without embedding
    plugin-specific knowledge.

    `source_dir` and `dest_dir` are absolute (the adapter joins `source_path`
    and `home` respectively). `glob` selects the files to route from
    `source_dir` (e.g. `*.toml`). `executable` requests the 0o755 mode bit on
    each written file — beads scripts need it, formulas do not."""

    source_dir: Path
    dest_dir: Path
    glob: str
    executable: bool


@runtime_checkable
class PluginAdapter(Protocol):
    """Plugin-specific behaviour the engine consults. Unlike `ToolAdapter`,
    plugins are not enumerated — they are discovered by scanning a plugins
    root and registered by name string, so the registry knows each plugin's
    source directory at discovery time and the adapter carries it as
    `source_path` rather than reconstructing it from `repo_root`.

    `name` / `source_path` / `is_detected` are the F.1 core. `routes` was added
    additively in F.4 for plugins (beads) whose content lands at a bespoke
    destination outside any tool tree. Namespace overlay into tool trees stays
    a separate concern (F.2): it reuses the *tool* adapter's namespace rules and
    does not flow through `routes`."""

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

    # Bespoke source→destination routes for content that does NOT overlay into
    # a tool tree. Empty for generic plugins; beads returns its `~/.beads/`
    # formulas and scripts routes. `home` is injected so destinations resolve
    # against the caller's home (critical under test).
    def routes(self, home: Path) -> tuple[PluginRoute, ...]: ...  # pragma: no cover
