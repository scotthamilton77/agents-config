"""Materialize a PR-head snapshot from `git archive` (plan §3.5, slice 3).

`materialize` extracts the immutable `git archive` tar at the resolved head OID
into a fresh tempdir, so scc scans a snapshot of the *committed* tree — never the
operator's working checkout. A dirty working tree can therefore never leak into
the artifact (the Path-C invariant). A post-extract sanity check requires every
estate path present on disk, else `VizError(ADAPTER_FAILURE)` — guarding
`export-ignore` gitattribute drops in arbitrary target repos (a silently-thin
snapshot is the failure class this guard exists to prevent). The tempdir
self-cleans on any failure; on success the caller tears the returned dir down in
a `finally`.
"""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path
from tempfile import mkdtemp
from typing import cast

from vizsuite.adapters.git.runner import GitRunner
from vizsuite.envelope import ErrorCode, JsonValue, VizError


def _assert_estate_materialized(snapshot: Path, estate_paths: set[str]) -> None:
    """Alarm loudly if any estate path is absent from the extracted snapshot."""
    missing = sorted(path for path in estate_paths if not (snapshot / path).exists())
    if missing:
        raise VizError(
            ErrorCode.ADAPTER_FAILURE,
            "estate paths absent from the materialized snapshot (export-ignore?)",
            detail={
                "missing": cast("list[JsonValue]", missing[:20]),
                "missing_count": len(missing),
            },
        )


def materialize(git: GitRunner, head_oid: str, estate_paths: set[str]) -> Path:
    """Extract the `git archive` tar at `head_oid` to a tempdir; sanity-check the estate.

    Returns the snapshot directory (the caller `shutil.rmtree`s it on the way out).
    Raises `VizError(ADAPTER_FAILURE)` — after removing the tempdir so nothing
    leaks — when any estate path is absent from the extracted snapshot.
    """
    tar_bytes = git.archive_tar(head_oid)
    snapshot = Path(mkdtemp(prefix="vizsuite-snapshot-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
            tar.extractall(snapshot, filter="data")
        _assert_estate_materialized(snapshot, estate_paths)
    except BaseException:
        # Any failure — the sanity alarm, a corrupt tar, an interrupt mid-extract —
        # must not strand the tempdir; clean up, then re-raise unchanged.
        shutil.rmtree(snapshot, ignore_errors=True)
        raise
    return snapshot
