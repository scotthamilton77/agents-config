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


def _shape_error(pr_number: int, stdout: str, *, reason: str) -> VizError:
    return VizError(
        ErrorCode.ADAPTER_FAILURE,
        "gh api graphql returned an unparseable or unexpected PR shape",
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
    if result.returncode != 0:
        raise VizError(
            ErrorCode.ADAPTER_FAILURE,
            "gh api graphql exited nonzero",
            detail={
                "pr_number": pr_number,
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _shape_error(pr_number, result.stdout, reason="invalid_json") from exc
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
        raise _shape_error(pr_number, result.stdout, reason=type(exc).__name__) from exc
