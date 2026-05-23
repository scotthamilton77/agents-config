from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


@runtime_checkable
class ToolAdapter(Protocol):
    """Tool-specific behaviour the engine consults. One concrete adapter
    per `Tool` enum value; registry-wired."""

    name: str

    def source_dir(self, repo_root: Path) -> Path: ...  # pragma: no cover

    def dest_dir(self, home: Path) -> Path: ...  # pragma: no cover

    def is_detected(self, home: Path) -> bool: ...  # pragma: no cover

    def scoped_namespaces(self) -> tuple[str, ...]: ...  # pragma: no cover

    def should_install_namespace(
        self, namespace: str, source: str
    ) -> bool: ...  # pragma: no cover

    def post_staging_transforms(
        self, plan: StagingPlan, io: IOPort
    ) -> StagingPlan: ...  # pragma: no cover
