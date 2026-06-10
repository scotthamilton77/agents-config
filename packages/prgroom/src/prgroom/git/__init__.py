"""The git adapter package (§3.4). Worktree plumbing via the ``git`` subprocess."""

from __future__ import annotations

from prgroom.git.client import GitCli, GitClient

__all__ = ["GitCli", "GitClient"]
