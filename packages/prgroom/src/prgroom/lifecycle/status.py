"""The §4.6 ``status --json`` envelope — the stable merge-gate handoff contract.

:func:`build_status` assembles the envelope from the in-memory :class:`PRGroomingState`
plus the derived §4.4 :class:`HumanReview` block. The four ``merge_gates`` bools and
``auto_merge_eligible`` are derived **per-query** and NEVER persisted — a future
merge-gate (``gmxo`` / ``td39``) consumes this shape. Per §4.6's stability commitment:
adding fields is non-breaking; renaming or removing a field is breaking and requires a
version-bumped envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prgroom.lifecycle.quiescence import BLOCKER_DISPOSITIONS
from prgroom.prsession.enums import DispositionKind, PRPhase, ReviewerKind

if TYPE_CHECKING:
    from prgroom.lifecycle.human_review import HumanReview
    from prgroom.prsession.state import PRGroomingState, ReviewItem

JsonObj = dict[str, Any]


def _last_error_clear(state: PRGroomingState) -> bool:
    return state.last_error is None or state.last_error == ""


def _no_blocker_items(state: PRGroomingState) -> bool:
    # §4.6 no_blocker_items screens on the SAME set the §4.1 quiescence predicate
    # uses (BLOCKER_DISPOSITIONS) — one source of truth, never a parallel notion.
    return not any(
        item.disposition is not None and item.disposition.kind in BLOCKER_DISPOSITIONS
        for item in state.items
    )


def _items_summary(state: PRGroomingState) -> JsonObj:
    summary: JsonObj = {kind.value: 0 for kind in DispositionKind}
    for item in state.items:
        if item.disposition is not None:
            summary[item.disposition.kind.value] += 1
    return summary


def _item_row(item: ReviewItem) -> JsonObj:
    # The disposition-contract §3.1 projection — a deliberate subset, not a state
    # dump: body_excerpt, rationale, commits, response_path, gate, escalation_filed,
    # and cluster bookkeeping stay private to the store.
    disposition: JsonObj | None = None
    if item.disposition is not None:
        disposition = {
            "kind": item.disposition.kind.value,
            "decided_at": item.disposition.decided_at.isoformat(),
            "decided_by": item.disposition.decided_by,
        }
    return {
        "kind": item.kind.value,
        "gh_id": item.identity.gh_id,
        "thread_id": item.identity.thread_id,
        "author": item.author,
        "disposition": disposition,
        "replied": item.replied,
        "resolved": item.resolved,
        "posted_reply_ids": list(item.posted_reply_ids),
    }


def _reviewers(state: PRGroomingState) -> list[JsonObj]:
    rows: list[JsonObj] = []
    for login in sorted(state.reviewers):
        r = state.reviewers[login]
        rows.append(
            {
                "login": r.identity,
                "required": r.required,
                "is_bot": r.kind is ReviewerKind.BOT,
                "status": r.status.value,
                "declined_reason": r.declined_reason or "",
            }
        )
    return rows


def build_status(state: PRGroomingState, human_review: HumanReview) -> JsonObj:
    """Build the §4.6 ``status --json`` envelope (pure; never persists).

    ``auto_merge_eligible`` is the AND of the four ``merge_gates`` bools, each derived
    from current state + the live-derived human-review block.
    """
    phase_is_quiesced = state.phase is PRPhase.QUIESCED
    last_error_clear = _last_error_clear(state)
    no_blocker_items = _no_blocker_items(state)
    human_review_satisfied = human_review.satisfied

    auto_merge_eligible = (
        phase_is_quiesced and last_error_clear and no_blocker_items and human_review_satisfied
    )

    quiesced_at = state.quiescence.quiesced_at
    return {
        "pr": state.pr.number,
        "phase": state.phase.value,
        "last_error": state.last_error or "",
        "pr_review_retries_used": state.pr_review_retries_used,
        "reviewers": _reviewers(state),
        "ci_state": state.quiescence.ci_state,
        "items_summary": _items_summary(state),
        "items": [_item_row(item) for item in state.items],
        "last_activity_at": state.last_activity_at.isoformat(),
        "quiesced_at": quiesced_at.isoformat() if quiesced_at is not None else "",
        "merge_gates": {
            "phase_is_quiesced": phase_is_quiesced,
            "last_error_clear": last_error_clear,
            "no_blocker_items": no_blocker_items,
            "human_review_satisfied": human_review_satisfied,
        },
        "human_review": human_review.to_dict(),
        "auto_merge_eligible": auto_merge_eligible,
    }
