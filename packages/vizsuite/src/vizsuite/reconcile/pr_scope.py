"""PR snapshot resolution + git↔GitHub scalar reconciliation (plan §3.5).

`reconcile` resolves the PR's immutable base/head OIDs and reconciles local git's
authoritative net file/commit *sets* against GitHub's *un-truncated scalar counts*.
Every read is against the immutable object DB (never the operator's checkout), so a
concurrent session mutating the main tree cannot corrupt the artifact. Disagreement
is a loud `RECONCILER_DRIFT`; OIDs still absent after a fetch are `SNAPSHOT_MISMATCH`.
One `gh api graphql` call resolves both the scalar join and the PR-metadata garnish
(`PrView.meta`) — no second gh round trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from vizsuite.adapters.gh.parse import PrMeta, parse_pr_view
from vizsuite.adapters.gh.runner import GhRunner
from vizsuite.adapters.git.runner import GitRunner
from vizsuite.envelope import ErrorCode, JsonValue, VizError
from vizsuite.extract.churn import FileChurn, churn


@dataclass(frozen=True)
class PrScope:
    """The reconciled PR scope handed to the extractors and the scene assembler.

    `files` is the local *net* set (a file added-then-reverted within the PR is
    excluded), each carrying its summed churn; `head_oid` drives every downstream
    immutable-object read (estate at head, scc snapshot). `meta` is the
    author/review-state/timestamps garnish, parsed from the same graphql
    response as the scalar join.
    """

    pr_number: int
    head_oid: str
    base_oid: str
    files: dict[str, FileChurn]
    meta: PrMeta


def reconcile(pr_number: int, *, gh: GhRunner, git: GitRunner) -> PrScope:
    """Resolve OIDs and reconcile local net sets against GitHub's scalar counts."""
    pr = parse_pr_view(gh.pr_graphql(pr_number), pr_number=pr_number)

    # Ensure both immutable OIDs are present locally so every downstream read is
    # against the object DB, not the operator's checkout. `pull/<n>/head` brings the
    # head (forks too); the base tip is never an ancestor of it, so the base ref is
    # fetched separately. Still absent after both fetches ⇒ stale clone / unreachable
    # remote — refuse loudly rather than die on a cryptic later git error.
    head_present = git.cat_object_exists(pr.head_oid)
    if not head_present:
        git.fetch_pr(pr_number)
        head_present = git.cat_object_exists(pr.head_oid)
    base_present = git.cat_object_exists(pr.base_oid)
    if not base_present:
        git.fetch_base(pr.base_ref)
        base_present = git.cat_object_exists(pr.base_oid)
    missing = [
        oid
        for oid, present in ((pr.base_oid, base_present), (pr.head_oid, head_present))
        if not present
    ]
    if missing:
        raise VizError(
            ErrorCode.SNAPSHOT_MISMATCH,
            "PR base/head not present locally after fetch; check network/remote",
            detail={"missing_oids": cast("list[JsonValue]", missing)},
        )

    net_files = set(git.diff_name_only(pr.base_oid, pr.head_oid))
    if len(net_files) != pr.changed_files:
        raise VizError(
            ErrorCode.RECONCILER_DRIFT,
            "local net file count disagrees with GitHub",
            detail={
                "local": len(net_files),
                "github_changed_files": pr.changed_files,
                "note": "criss-cross histories may pick different merge bases",
            },
        )

    commit_oids = git.rev_list(pr.base_oid, pr.head_oid)
    if len(commit_oids) != pr.commit_count:
        raise VizError(
            ErrorCode.RECONCILER_DRIFT,
            "local commit count disagrees with GitHub",
            detail={"local": len(commit_oids), "github_commits": pr.commit_count},
        )

    files = churn(git, commit_oids, net_files)
    return PrScope(
        pr_number=pr_number, head_oid=pr.head_oid, base_oid=pr.base_oid, files=files, meta=pr.meta
    )
