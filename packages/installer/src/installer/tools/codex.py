from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class CodexAdapter:
    """Adapter for OpenAI's Codex CLI. Detected when ~/.codex/ exists."""

    name: str = "codex"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".codex"

    def dest_dir(self, home: Path) -> Path:
        return home / ".codex"

    def is_detected(self, home: Path) -> bool:
        return (home / ".codex").is_dir()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; CodexAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; CodexAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; CodexAdapter accepts uniformly
    ) -> StagingPlan:
        return plan
