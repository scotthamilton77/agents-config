from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan


class OpenCodeAdapter:
    """Adapter for OpenCode. Two divergences from the dot-dir tools:
    it installs under the XDG config dir (~/.config/opencode/, not ~/.opencode/),
    and it skips the shared agents/ namespace (frontmatter format differs;
    see OPENCODE-EXTENSIONS.md). Detected when opencode is on PATH OR the XDG
    config dir exists — mirrors the bash
    `command -v opencode || [[ -d ~/.config/opencode ]]`."""

    name: str = "opencode"
    detection_signal: str = ".config/opencode"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root / "src" / "user" / ".opencode"

    def dest_dir(self, home: Path) -> Path:
        # XDG config dir, not a dot-dir — mirrors the bash tool_dest_dir()
        # special-case for opencode. NOT $XDG_CONFIG_HOME-aware by design
        # (the bash installer hardcodes ~/.config/opencode); keep parity.
        return home / ".config" / "opencode"

    def is_detected(self, home: Path) -> bool:
        # The dir branch is "the install destination already exists" — derive it
        # from dest_dir() so the XDG path has a single source of truth and
        # detection can't drift from the destination.
        return self.dest_dir(home).is_dir() or shutil.which("opencode") is not None

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(self, namespace: str, source: str) -> bool:
        # Skip the shared agents/ namespace: OpenCode's agent frontmatter format
        # differs from the shared format (see OPENCODE-EXTENSIONS.md). Mirrors the
        # bash installer's Phase 2 `[[ "$tool" != "opencode" ]]` agents guard.
        return not (namespace == "agents" and source == "shared")

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # protocol parameter; OpenCodeAdapter accepts uniformly
    ) -> StagingPlan:  # pragma: no cover
        return plan
