from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class GeminiAdapter:
    """Adapter for Google's Gemini CLI. Probes ~/.gemini/ as a directory —
    mirrors the bash installer's [[ -d "$HOME/.gemini" ]] detection."""

    name: str = "gemini"
    detection_signal: str = ".gemini"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".gemini"

    def dest_dir(self, home: Path) -> Path:
        return home / ".gemini"

    def is_detected(self, home: Path) -> bool:
        return (home / ".gemini").is_dir()

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
        source: str,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
    ) -> bool:
        return True

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; GeminiAdapter accepts uniformly
    ) -> StagingPlan:  # pragma: no cover
        return plan
