"""The gh adapter package (§1, §3). GitHub access via the ``gh`` subprocess."""

from __future__ import annotations

from prgroom.gh.client import GhCli, GhClient, GhNotFoundError

__all__ = ["GhCli", "GhClient", "GhNotFoundError"]
