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
    and it skips the shared agents/ namespace (OpenCode's agent frontmatter uses
    provider-prefixed model IDs plus mode:/permission: keys, unlike the shared
    format). Detected when opencode is on PATH OR the XDG config dir
    (~/.config/opencode) exists."""

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

    def project_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(self, namespace: str, source: str) -> bool:
        # Skip the shared agents/ namespace: OpenCode's agent frontmatter format
        # differs from the shared format (provider-prefixed model IDs plus
        # mode:/permission: keys).
        return not (namespace == "agents" and source == "shared")

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; OpenCode has no transform
    ) -> StagingPlan:
        """No-op. OpenCode DOES get a standalone rules/ destination — the
        shared rules/ namespace stages into ~/.config/opencode/rules/ the
        same as every other tool (build_plan Phase 2, namespaces.SHARED;
        should_install_namespace only excludes the shared agents/ namespace
        here) — it is just empty today because the shared source has no rule
        files yet. The loose rules/ drop that would apply once it isn't is
        not OpenCode-specific either: flatten_plan_templates drops a plan's
        standalone rules/ items only when its instruction file carries the
        DYNAMIC-INCLUDE-ALL-RULES marker, and that runs earlier in
        stage_and_transform. No current template carries that marker,
        including OpenCode's, so nothing is dropped for any tool today.
        Kept as a no-op only to satisfy the ToolAdapter protocol."""
        return plan
