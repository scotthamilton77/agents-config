"""``rereview_pr`` — the lock-held ``_rereview`` lifecycle internal (§3.2/§3.4).

After ``_push`` uploads new commits, prior reviews are bound to a superseded SHA;
``_push`` already flipped stale required ``review_found`` reviewers to
``not_requested`` (§3.4). ``_rereview`` then re-asks every required reviewer in
``{not_requested, declined}`` for a fresh review.

GitHub will not re-trigger a bot reviewer (e.g. Copilot) that is already attached to
the PR, so a fresh review needs the "remove + re-add dance": a ``DELETE`` followed
by a ``POST`` against ``pulls/{n}/requested_reviewers`` for each target reviewer.
After re-requesting, the reviewer moves to ``requested`` (stamped at ``now``), which
takes it out of the target set — so a second ``_rereview`` in the same cycle is a
no-op (the §3.3 idempotency contract).

Mirrors the other lock-held internals: works on a deepcopy, never touches the store
(the caller owns ``store.write``), makes no phase change (§3.2 rereview row), and
sets no ``state.last_error``. A no-op (no gh calls, state unchanged) when no required
reviewer is stale.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.prsession.enums import ReviewerStatus

if TYPE_CHECKING:
    from prgroom.deps import Deps
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState

# Required reviewers in these statuses need a fresh ask (§3.4). After ``_push``'s
# flip, stale ``review_found`` reviewers have already moved into ``not_requested``.
_REFRESHABLE = frozenset({ReviewerStatus.NOT_REQUESTED, ReviewerStatus.DECLINED})


def rereview_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
) -> PRGroomingState:
    """Re-request review from every stale required reviewer via the remove/add dance.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state``; returns the copy for the caller to persist. A no-op when no required
    reviewer is in ``{not_requested, declined}``. No phase change (§3.2 rereview
    row), no ``state.last_error``.
    """
    state = copy.deepcopy(state)
    path = f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/requested_reviewers"
    now = deps.clock.now()
    try:
        for reviewer in state.reviewers.values():
            if not (reviewer.required and reviewer.status in _REFRESHABLE):
                continue
            fields = {"reviewers[]": reviewer.identity}
            # DELETE then POST is the dance order; the status flip is applied only
            # after BOTH succeed. A POST failure (or a crash before the caller writes
            # state) leaves the reviewer in the refreshable set, so the next run
            # repeats the whole dance — DELETE is idempotent, so the retry is safe.
            gh.rest("DELETE", path, fields=fields)
            gh.rest("POST", path, fields=fields)
            reviewer.status = ReviewerStatus.REQUESTED
            reviewer.last_request_at = now
    except GhNotFoundError as exc:
        # The PR/repo vanished mid-run (404) — terminal, not a raw traceback.
        raise vanished_pr_terminal(ref) from exc
    return state
