"""Reads `.critical-paths` from a materialized snapshot — the sole I/O boundary
for the consequence axis (spec §6.2).

Kept separate from `extract/consequence.py` so that module stays pure-compute,
matching how the other extractors receive already-read inputs (`complexity`
takes parsed `scc_records`, not a scanner; `churn` takes already-fetched rows).
A missing marker file is valid data (no explicit policy markers) — only an
unreadable *present* file is a loud `VizError(ADAPTER_FAILURE)`, never a silent
default (a silently-empty consequence axis is exactly the failure §6.2 exists
to prevent).
"""

from __future__ import annotations

from pathlib import Path

from vizsuite.envelope import ErrorCode, VizError

CRITICAL_PATHS_FILE = ".critical-paths"


def read_critical_paths(snapshot_dir: Path) -> list[str]:
    """Read `.critical-paths` lines from the snapshot dir (`[]` if absent)."""
    marker_file = snapshot_dir / CRITICAL_PATHS_FILE
    if not marker_file.is_file():
        return []
    try:
        return marker_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise VizError(
            ErrorCode.ADAPTER_FAILURE,
            "could not read .critical-paths from the materialized snapshot",
            detail={"path": str(marker_file), "error": str(exc)},
        ) from exc
