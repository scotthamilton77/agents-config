"""``resolve_escalated_pr`` — human reclassification of one escalated item (§3.2)."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.errors import BlockingErrorCodes, ErrorCode, PreconditionError
from prgroom.prsession.enums import DispositionKind, PRPhase
from prgroom.prsession.state import Disposition

if TYPE_CHECKING:
    from datetime import datetime

    from prgroom.prsession.state import PRGroomingState, ReviewItem

_BLOCKING_VALUES = frozenset(c.value for c in BlockingErrorCodes)


def _find_escalated(state: PRGroomingState, item_id: str) -> ReviewItem:
    """Resolve ``item_id`` (``gh_id`` or ``kind:gh_id``) to one escalated item, fail-safe."""
    kind: str | None = None
    gh_id = item_id
    if ":" in item_id:
        kind, gh_id = item_id.split(":", 1)

    def _matches(it: ReviewItem) -> bool:
        return it.identity.gh_id == gh_id and (kind is None or it.kind.value == kind)

    matches = [it for it in state.items if _matches(it)]
    if len(matches) != 1:
        raise PreconditionError(
            ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED,
            detail=f"{item_id!r} matched {len(matches)} items; disambiguate with kind:gh_id",
        )
    item = matches[0]
    if item.disposition is None or item.disposition.kind is not DispositionKind.ESCALATED:
        raise PreconditionError(
            ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED, detail=f"{item_id!r} is not escalated"
        )
    return item


def resolve_escalated_pr(
    state: PRGroomingState,
    *,
    item_id: str,
    as_disposition: DispositionKind,
    rationale: str,
    commits: list[str],
    decided_by: str,
    now: datetime,
) -> PRGroomingState:
    """Flip one escalated item to a terminal disposition; maybe release human-gated (§3.2).

    Works on a deepcopy, caller persists once. Never clears budget/state-corrupt/failed
    gating, never increments ``pr_review_retries_used``. Re-runnable.
    """
    state = copy.deepcopy(state)
    if as_disposition is DispositionKind.FIXED and not commits:
        raise PreconditionError(
            ErrorCode.PRECONDITION_FIXED_NEEDS_COMMITS, detail="--as fixed requires --commits"
        )
    if not any(
        it.disposition is not None and it.disposition.kind is DispositionKind.ESCALATED
        for it in state.items
    ):
        raise PreconditionError(ErrorCode.PRECONDITION_NO_ESCALATIONS, detail=state.pr.display())

    item = _find_escalated(state, item_id)
    item.disposition = Disposition(
        kind=as_disposition,
        decided_at=now,
        decided_by=decided_by,
        rationale=rationale,
        commits=list(commits),
    )

    if state.phase is PRPhase.HUMAN_GATED and _can_release(state):
        state.phase = PRPhase.FIXES_PENDING
    return state


def _can_release(state: PRGroomingState) -> bool:
    no_escalated = not any(
        it.disposition is not None and it.disposition.kind is DispositionKind.ESCALATED
        for it in state.items
    )
    no_failed = not any(
        it.disposition is not None and it.disposition.kind is DispositionKind.FAILED
        for it in state.items
    )
    not_blocked = state.last_error is None or state.last_error not in _BLOCKING_VALUES
    return no_escalated and no_failed and not_blocked
