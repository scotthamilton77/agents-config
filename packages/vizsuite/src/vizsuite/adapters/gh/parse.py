"""gh api graphql shape parsing → typed `PrView`.

`gh api graphql` stdout is the reconciler's only contract with the real `gh`
binary; this module turns that raw shape into vizsuite's `PrView` and is the
single place a malformed/failed `gh` response becomes a loud typed
`VizError(ADAPTER_FAILURE)` rather than a silent default (mirrors ``workcli``'s
bd/parse drift discipline). `SubprocessGhRunner.pr_graphql` returns the raw
`GhResult`; the reconciler calls this parser on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vizsuite.adapters.gh.runner import GhResult
from vizsuite.envelope import ErrorCode, VizError


@dataclass(frozen=True)
class PrView:
    base_oid: str
    head_oid: str
    base_ref: str
    changed_files: int
    commit_count: int


@dataclass(frozen=True)
class PrMeta:
    """PR author/review-state/timestamps (spec §4.4, plan slice 5).

    Garnish metadata, not part of the reconciler's drift-critical scalar join
    (`PrView`) — a separate, widened `gh pr view --json` call. `review_state`
    normalizes gh's nullable `reviewDecision` (no review activity yet) to the
    `"NONE"` sentinel rather than `None`, since a null review state here is
    valid data, not a malformed response.
    """

    author: str
    review_state: str
    created_at: str
    updated_at: str
    merged_at: str | None


def _nonzero_exit_error(pr_number: int, result: GhResult, *, source: str) -> VizError:
    return VizError(
        ErrorCode.ADAPTER_FAILURE,
        f"{source} exited nonzero",
        detail={
            "pr_number": pr_number,
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        },
    )


def _shape_error(pr_number: int, stdout: str, *, source: str, reason: str) -> VizError:
    return VizError(
        ErrorCode.ADAPTER_FAILURE,
        f"{source} returned an unparseable or unexpected PR shape",
        detail={"pr_number": pr_number, "reason": reason, "raw_excerpt": stdout[:200]},
    )


def parse_pr_view(result: GhResult, *, pr_number: int) -> PrView:
    """Parse one `gh api graphql` PR response into a `PrView`.

    Every failure mode is a loud typed `VizError(ADAPTER_FAILURE)`, never a silent
    default (spec §6.3's two-source join depends on this response, so a failed or
    drifted second witness must alarm): a nonzero `gh` exit, non-JSON stdout, a
    null/absent pull request (a subscript of `None` → `TypeError`), or any missing
    scalar (`KeyError`) all funnel to the same alarm carrying the PR number.
    """
    source = "gh api graphql"
    if result.returncode != 0:
        raise _nonzero_exit_error(pr_number, result, source=source)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _shape_error(pr_number, result.stdout, source=source, reason="invalid_json") from exc
    try:
        pull_request = payload["data"]["repository"]["pullRequest"]
        return PrView(
            base_oid=pull_request["baseRefOid"],
            head_oid=pull_request["headRefOid"],
            base_ref=pull_request["baseRefName"],
            changed_files=pull_request["changedFiles"],
            commit_count=pull_request["commits"]["totalCount"],
        )
    except (KeyError, TypeError) as exc:
        raise _shape_error(
            pr_number, result.stdout, source=source, reason=type(exc).__name__
        ) from exc


def parse_pr_meta(result: GhResult, *, pr_number: int) -> PrMeta:
    """Parse one `gh pr view --json` response into a `PrMeta`.

    Mirrors `parse_pr_view`'s discipline: a nonzero exit, non-JSON stdout, or a
    missing scalar (`author.login`, `createdAt`, `updatedAt`) is a loud typed
    `VizError(ADAPTER_FAILURE)`, never a silent default. A `null`/absent
    `reviewDecision` is normalized to the `"NONE"` sentinel — valid data for a
    PR with no review activity yet, not a malformed response.
    """
    source = "gh pr view --json"
    if result.returncode != 0:
        raise _nonzero_exit_error(pr_number, result, source=source)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _shape_error(pr_number, result.stdout, source=source, reason="invalid_json") from exc
    try:
        return PrMeta(
            author=payload["author"]["login"],
            review_state=payload.get("reviewDecision") or "NONE",
            created_at=payload["createdAt"],
            updated_at=payload["updatedAt"],
            merged_at=payload.get("mergedAt"),
        )
    except (KeyError, TypeError) as exc:
        raise _shape_error(
            pr_number, result.stdout, source=source, reason=type(exc).__name__
        ) from exc
