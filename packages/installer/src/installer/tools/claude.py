from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class ClaudeAdapter:
    """Adapter for Anthropic's Claude Code. Probes ~/.claude/settings.json
    as the detection marker — deliberate divergence from install.sh's
    'always include claude' rule."""

    name: str = "claude"
    detection_signal: str = ".claude/settings.json"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".claude"

    def dest_dir(self, home: Path) -> Path:
        return home / ".claude"

    def is_detected(self, home: Path) -> bool:
        return (home / ".claude" / "settings.json").is_file()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ("commands", "skills", "agents", "rules")

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
    ) -> StagingPlan:  # pragma: no cover
        return plan
