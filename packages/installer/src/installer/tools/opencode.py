from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class OpenCodeAdapter:
    """Adapter for OpenCode. Two divergences from the dot-dir tools:
    it installs under the XDG config dir (~/.config/opencode/, not ~/.opencode/),
    and it skips the shared agents/ namespace (frontmatter format differs;
    see OPENCODE-EXTENSIONS.md). Detected when opencode is on PATH OR the XDG
    config dir (~/.config/opencode) exists."""

    name: str = "opencode"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".opencode"

    def dest_dir(self, home: Path) -> Path:
        # XDG config dir, not a dot-dir. NOT $XDG_CONFIG_HOME-aware by design
        # (hardcoded to ~/.config/opencode to match the install destination).
        return home / ".config" / "opencode"

    def is_detected(self, home: Path) -> bool:
        # The dir branch is "the install destination already exists" — derive it
        # from dest_dir() so the XDG path has a single source of truth and
        # detection can't drift from the destination.
        return self.dest_dir(home).is_dir() or which("opencode") is not None

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(self, namespace: str, source: str) -> bool:
        # Skip the shared agents/ namespace: OpenCode's agent frontmatter format
        # differs from the shared format (see OPENCODE-EXTENSIONS.md).
        return not (namespace == "agents" and source == "shared")

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; OpenCode mutates only the plan
    ) -> StagingPlan:
        """Drop staged rules/ items before sync: OpenCode has no standalone rules/
        destination. The rules are inlined into the flat AGENTS.md by the
        DYNAMIC-INCLUDE-ALL-RULES flatten — which runs earlier in
        stage_and_transform and sources them from these same staged items — so
        dropping them here prevents a second standalone deploy of the same
        content."""
        for relpath in [rp for rp, item in plan.items.items() if item.namespace == "rules"]:
            del plan.items[relpath]
        return plan
