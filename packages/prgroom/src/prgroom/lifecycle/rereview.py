"""``rereview_pr`` — the lock-held ``_rereview`` lifecycle internal (§3.2/§3.4).

After ``_push`` uploads new commits, prior reviews are bound to a superseded SHA;
``_push`` already flipped stale required ``review_found`` reviewers to
``not_requested`` (§3.4). ``_rereview`` then re-asks every required reviewer that
:func:`~prgroom.lifecycle.predicates.reviewer_needs_refresh` admits — the
invalidated ones plus declines that were not a deliberate withdrawal.

GitHub will not re-trigger a bot reviewer (e.g. Copilot) that is already attached to
the PR, so a fresh review needs the "remove + re-add dance": a ``DELETE`` followed
by a ``POST`` against ``pulls/{n}/requested_reviewers`` for each target reviewer.
After re-requesting, the reviewer moves to ``requested`` (stamped at ``now``), which
takes it out of the target set — so a second ``_rereview`` in the same cycle is a
no-op (the §3.3 idempotency contract).

Mirrors the other lock-held internals: works on a deepcopy, never touches the store
(the caller owns ``store.write``), makes no phase change (§3.2 rereview row), and
sets no ``state.last_error``. When no required reviewer is stale it makes no gh
calls, but still advances the rereviewed-SHA stamp (the guard gated entry).
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.predicates import reviewer_needs_refresh
from prgroom.prsession.enums import ReviewerStatus

if TYPE_CHECKING:
    from prgroom.deps import Deps
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState


def rereview_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
) -> PRGroomingState:
    """Re-request review from every stale required reviewer via the remove/add dance.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state``; returns the copy for the caller to persist. Makes no gh calls when no
    required reviewer needs a refresh (see
    :func:`~prgroom.lifecycle.predicates.reviewer_needs_refresh`), but still advances
    the rereviewed-SHA stamp (the guard gated entry). No phase change (§3.2 rereview
    row), no ``state.last_error``.
    """
    state = copy.deepcopy(state)
    path = f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/requested_reviewers"
    now = deps.clock.now()
    try:
        for reviewer in state.reviewers.values():
            if not (reviewer.required and reviewer_needs_refresh(reviewer)):
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
            # This fresh re-request is awaiting its first engagement: drop the stamp of
            # the review a push invalidated (or a prior decline's engagement). The
            # review-start timeout only fires while last_review_at is None, so leaving a
            # stale stamp here would wedge the re-requested reviewer at REQUESTED forever
            # when the wanted fresh review never lands. Clear both (as the reconcile-side
            # re-request resets do) — with last_review_at None the reactivation freshness
            # test has no boundary to disambiguate, so the id is dead here too.
            reviewer.last_review_at = None
            reviewer.last_review_id = None
        # Reviewers will now see the invalidated HEAD; stamp it so
        # ``push_awaiting_rereview`` flips false. After the loop (a mid-loop POST
        # failure raises and discards the deepcopy, leaving the stamp un-advanced).
        state.last_rereviewed_sha = state.last_review_invalidated_sha
    except GhNotFoundError as exc:
        # The PR/repo vanished mid-run (404) — terminal, not a raw traceback.
        raise vanished_pr_terminal(ref) from exc
    return state
