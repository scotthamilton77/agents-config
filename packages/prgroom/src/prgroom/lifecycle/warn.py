"""Shared soft-warning sink for the lifecycle verbs (§3.3).

A one-line ``prgroom:`` stderr notice — the default ``warn`` callback the verb
internals fall back to when a caller injects none. Tests capture warnings by
passing their own callback; production lets them reach stderr. Centralised so the
prefix format lives in exactly one place instead of drifting across verbs.
"""

from __future__ import annotations

import sys


def default_warn(message: str) -> None:
    """Write a one-line ``prgroom:`` soft-warning notice to stderr."""
    sys.stderr.write(f"prgroom: {message}\n")
