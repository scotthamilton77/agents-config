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
    detection_signal: str = "~/.claude/settings.json"

    # exercised by w1qls.2.2 (B.2)
    def source_dir(self, repo_root: Path) -> Path:  # pragma: no cover
        return repo_root / "src" / "user" / ".claude"

    # exercised by w1qls.2.2 (B.2)
    def dest_dir(self, home: Path) -> Path:  # pragma: no cover
        return home / ".claude"

    def is_detected(self, home: Path) -> bool:
        return (home / ".claude" / "settings.json").is_file()

    # exercised by w1qls.3.1 (C.1)
    def scoped_namespaces(self) -> tuple[str, ...]:  # pragma: no cover
        return ("commands", "skills", "agents", "rules")

    # exercised by w1qls.3.1 (C.1)
    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
    ) -> bool:  # pragma: no cover
        return True

    # exercised by w1qls.4.4 (D.4)
    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; ClaudeAdapter accepts uniformly
    ) -> StagingPlan:  # pragma: no cover
        return plan
