"""Test double for a specialized ``PluginAdapter`` whose content routes to a
bespoke, non-tool-tree destination.

Stands in for the retired specialized plugin adapter (the only one this
codebase ever shipped) so plugin-route dispatch, receipt, and prune tests keep
exercising the real ``PluginRoute``/``sync_routes`` machinery without
depending on production code that no longer exists. The formulas/scripts
convention below is arbitrary fixture data — these tests pin the machinery's
behaviour, not this class's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from installer.plugins.base import PluginRoute


@dataclass(frozen=True, slots=True)
class RoutedPluginDouble:
    """A plugin adapter with two bespoke routes — a non-executable ``*.toml``
    route and an executable ``*.sh`` route, both under ``home/.<name>/`` —
    mirroring the shape a specialized adapter uses to place content outside
    every tool tree."""

    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:
        return (home / f".{self.name}").is_dir()

    def routes(self, home: Path) -> tuple[PluginRoute, ...]:
        src_root = self.source_path / f".{self.name}"
        dest_root = home / f".{self.name}"
        return (
            PluginRoute(
                source_dir=src_root / "formulas",
                dest_dir=dest_root / "formulas",
                glob="*.toml",
                executable=False,
            ),
            PluginRoute(
                source_dir=src_root / "scripts",
                dest_dir=dest_root / "scripts",
                glob="*.sh",
                executable=True,
            ),
        )
