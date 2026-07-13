"""Churn extractor — per-file added/deleted sums over the PR's net set.

Symmetric with `extract/estate.py`: takes the `GitRunner` seam and reduces the
PyDriller per-commit modified-file rows (`git.churn_for_commits`) to one
`FileChurn` per path, restricted to the PR's *net* file set so a reverted-only
file (present in the churn union, absent from the net diff) contributes no heat
(plan §3.5). Churn only heats — it is never used to lower a score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vizsuite.adapters.git.runner import GitRunner


@dataclass(frozen=True)
class FileChurn:
    added: int
    deleted: int


def churn(git: GitRunner, commit_oids: Sequence[str], net_files: set[str]) -> dict[str, FileChurn]:
    """Sum per-file line churn across the commit set, restricted to `net_files`.

    Keys by ``new_path`` (falling back to ``old_path`` so a pure delete stays in
    scope); a row whose resolved path is outside `net_files` is dropped — the
    reverted-only exclusion that keeps churn heat honest.
    """
    totals: dict[str, FileChurn] = {}
    for row in git.churn_for_commits(commit_oids):
        path = row.new_path or row.old_path
        if path is None or path not in net_files:
            continue
        prev = totals.get(path, FileChurn(added=0, deleted=0))
        totals[path] = FileChurn(added=prev.added + row.added, deleted=prev.deleted + row.deleted)
    return totals
