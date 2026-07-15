from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from installer.core import namespaces

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class ClaudeAdapter:
    """Adapter for Anthropic's Claude Code. Always detected: auto-detect always
    selects it, even on a fresh machine with no ~/.claude yet."""

    name: str = "claude"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".claude"

    def dest_dir(self, home: Path) -> Path:
        return home / ".claude"

    def is_detected(
        self,
        home: Path,  # noqa: ARG002  # protocol parameter; claude is unconditionally detected
    ) -> bool:
        return True

    def scoped_namespaces(self) -> tuple[str, ...]:
        return namespaces.TOOL_SCOPED

    def project_namespaces(self) -> tuple[str, ...]:
        return ("skills", "agents", "commands")

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
    ) -> StagingPlan:
        return plan
