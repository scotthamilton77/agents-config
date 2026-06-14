"""Shared gh-error -> tagged-error mappings for the lifecycle verbs (§3.6/§3.7).

A mid-run 404 on a *required* gh read (head-oid/name, PR resource, comment/review,
reviewer-request) means the PR or repo vanished — a blind retry won't bring it
back, so it is terminal. Several verbs (`_poll`, `_push`, `_rereview`) need the
identical mapping, so it lives here once. The startup precondition that owns
``PRECONDITION_REPO_UNREACHABLE`` (a repo that was never reachable) is a separate,
out-of-verb concern; this maps the *disappeared-while-we-worked* case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prgroom.errors import ErrorCode, PrgroomError, Tier

if TYPE_CHECKING:
    from prgroom.prsession.pr_ref import PRRef


def vanished_pr_terminal(ref: PRRef) -> PrgroomError:
    """Map a 404 on a required PR/repo read to terminal ``RUNTIME_GH_TERMINAL``."""
    return PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER,
        code=ErrorCode.RUNTIME_GH_TERMINAL,
        detail=f"PR resource not found: {ref.display()}",
    )
