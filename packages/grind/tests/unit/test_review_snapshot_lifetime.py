"""A review snapshot describes one PR cycle and does not outlive it.

Every projection assertion here addresses the reviewed item by id. A read
positioned by index would land on the second seeded item, which is never
reviewed and whose review is therefore default under any implementation --
an assertion that passes whatever the fold does.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import pytest

from grind.fold import fold
from grind.handoff import handoff_json
from grind.model import ItemReview, State
from grind.render import render_dashboard
from grind.serialize import full_state_json
from tests.unit.builders import event, seed_event

_ITEM = "wgclw.1"

# What `status --full` and the handoff emit for an item carrying no review.
_FULL_DEFAULT_REVIEW = {
    "round": None,
    "kind": None,
    "head_sha": None,
    "detail": None,
    "verdict": None,
    "open_threads": 0,
    "wont_fix_count": 0,
    "stalemate": False,
}
_HANDOFF_DEFAULT_REVIEW = {
    "round": None,
    "kind": None,
    "verdict": None,
    "open_threads": 0,
    "stalemate": False,
}


def _reviewed_pr() -> list[dict[str, Any]]:
    """PR 7 taken to a stalemate verdict -- every snapshot field populated.

    A verdict, not a round alone: `review_round` writes four of the eight
    fields, so the other four (verdict, both counts, the stalemate flag) are
    only ever set here, and they are the ones a later round cannot overwrite.
    """
    return [
        seed_event(),
        event("item_started", item=_ITEM),
        event("pr_opened", item=_ITEM, pr=7),
        event(
            "review_round",
            item=_ITEM,
            kind="codex",
            round=3,
            head_sha="old-head",
            detail="one thread deferred and one wont-fix on the closed PR",
        ),
        event(
            "review_verdict",
            item=_ITEM,
            kind="codex",
            round=3,
            head_sha="old-head",
            verdict="stalemate",
            findings=[{"disposition": "deferred"}, {"disposition": "wont-fix"}],
        ),
    ]


def _parked_reviewed_pr() -> list[dict[str, Any]]:
    """The reviewed PR parked by `item_parked`, which closes no PR: the ref
    survives, so the abandon exit below has a live PR 7 to name."""
    return [
        *_reviewed_pr(),
        event("item_parked", item=_ITEM, reason="bot-declined", note="reviewer declined"),
    ]


def _dashboard_payload(state: State) -> dict[str, Any]:
    html = render_dashboard(state)
    start = html.index("var STATE = ") + len("var STATE = ")
    end = html.index(";\n\nvar KNOWN_STATUSES", start)
    payload: dict[str, Any] = json.loads(html[start:end])
    return payload


def _handoff_item(state: State) -> dict[str, Any]:
    """The item's own handoff row, from a lane roster or the parking lot."""
    payload = handoff_json(state)
    rows: list[dict[str, Any]] = [item for lane in payload["lanes"] for item in lane["items"]]
    rows.extend(payload["parking_lot"])
    return next(row for row in rows if row["id"] == _ITEM)


def _full_item(state: State) -> dict[str, Any]:
    items = full_state_json(state)["items"]
    assert isinstance(items, dict)
    item: dict[str, Any] = items[_ITEM]
    return item


def _assert_no_review_attribution(state: State) -> None:
    """No surface that reads the snapshot still reports the closed PR's review."""
    assert state.items[_ITEM].review == ItemReview()
    assert state.items[_ITEM].round_history == ()
    assert _full_item(state)["review"] == _FULL_DEFAULT_REVIEW
    assert _handoff_item(state)["review"] == _HANDOFF_DEFAULT_REVIEW

    dashboard = _dashboard_payload(state)
    cards = [card for lane in dashboard["lanes"] for card in lane["queue"] if card["id"] == _ITEM]
    if cards:
        assert cards[0]["review"] is None
    else:
        # Parking removes the item from its lane's queue, so the dashboard's
        # only row for it is the parking-lot one -- which carries identity and
        # park fields and no review key at all.
        parked = [row for row in dashboard["parking_lot"] if row["id"] == _ITEM]
        assert parked, "the item is on neither a lane card nor the parking lot"
        assert "review" not in parked[0]


@pytest.mark.parametrize("next_status", ["in-progress", "queued"])
def test_pr_closed_back_to_work_ends_review_attribution_in_every_projection(
    next_status: Literal["in-progress", "queued"],
) -> None:
    state = fold(
        [
            *_reviewed_pr(),
            event("pr_closed", item=_ITEM, pr=7, reason="superseded", next=next_status),
        ]
    )

    _assert_no_review_attribution(state)


def test_an_abandon_closure_ends_review_attribution_in_every_projection() -> None:
    state = fold(
        [
            *_parked_reviewed_pr(),
            event(
                "item_enqueued",
                item=_ITEM,
                lane="lane-a",
                closure={"pr": 7, "reason": "abandoned"},
            ),
        ]
    )

    _assert_no_review_attribution(state)


def test_the_ordinary_and_abandon_exits_agree_on_the_snapshot() -> None:
    ordinary = fold(
        [
            *_reviewed_pr(),
            event("pr_closed", item=_ITEM, pr=7, reason="superseded", next="queued"),
        ]
    )
    abandoned = fold(
        [
            *_parked_reviewed_pr(),
            event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 7}),
        ]
    )

    assert ordinary.items[_ITEM].review == abandoned.items[_ITEM].review == ItemReview()
    assert ordinary.items[_ITEM].round_history == abandoned.items[_ITEM].round_history == ()
    assert _full_item(ordinary)["review"] == _full_item(abandoned)["review"]
    assert _handoff_item(ordinary)["review"] == _handoff_item(abandoned)["review"]


def test_pr_closed_to_parked_ends_attribution_and_keeps_the_park_evidence() -> None:
    """The parked route ends the cycle like every other one.

    What explains the park is the typed reason, its note and the closure row --
    not the dead PR's review result, which is what the item would otherwise
    carry back into play.
    """
    state = fold(
        [
            *_reviewed_pr(),
            event("pr_closed", item=_ITEM, pr=7, reason="bot-declined", next="parked"),
        ]
    )

    item = state.items[_ITEM]
    assert item.parked is not None
    assert (item.parked.reason, item.parked.note) == ("bot-declined", "bot-declined")
    assert (item.parked.axis, item.parked.category) == ("failure", "human")
    assert [(entry.pr, entry.reason) for entry in state.closed_ledger] == [(7, "bot-declined")]
    # The ref outlives its PR so the failure-axis park keeps its subject.
    assert item.pr is not None
    assert (item.pr.number, item.pr.closed) == (7, True)
    # The park evidence reaches the reader on the same row the stale review
    # used to ride on.
    assert _handoff_item(state)["parked"]["reason"] == "bot-declined"

    _assert_no_review_attribution(state)


def test_an_enqueue_without_a_closure_keeps_the_surviving_prs_review() -> None:
    """Only a closure ends a cycle. An item parked with its PR still open
    re-enters play on that same PR, and its review is current, not stale."""
    parked = _parked_reviewed_pr()
    preserved = fold([*parked, event("item_enqueued", item=_ITEM, lane="lane-a")])
    ended = fold([*parked, event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 7})])

    assert preserved.items[_ITEM].review == fold(parked).items[_ITEM].review
    assert preserved.items[_ITEM].review.stalemate is True
    assert preserved.items[_ITEM].round_history == fold(parked).items[_ITEM].round_history
    assert preserved.items[_ITEM].pr is not None
    assert ended.items[_ITEM].review == ItemReview()


def test_an_enqueue_without_a_closure_does_not_revive_a_snapshot_already_ended() -> None:
    """`pr_closed(next=parked)` already ended the cycle, so the plain enqueue
    that follows has nothing to preserve -- the route back into active work
    carries no closed PR's verdict with it."""
    state = fold(
        [
            *_reviewed_pr(),
            event("pr_closed", item=_ITEM, pr=7, reason="bot-declined", next="parked"),
            event("item_enqueued", item=_ITEM, lane="lane-a"),
        ]
    )

    assert state.items[_ITEM].status == "queued"
    assert state.items[_ITEM].parked is None
    _assert_no_review_attribution(state)


def test_a_closure_the_fold_refuses_leaves_the_live_snapshot_alone() -> None:
    """A closure naming a PR the item does not hold is recorded and not
    applied, so it ends no cycle: the surviving PR keeps its review."""
    parked = _parked_reviewed_pr()
    refused = fold([*parked, event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 99})])
    applied = fold([*parked, event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 7})])

    assert refused.items[_ITEM].review == fold(parked).items[_ITEM].review
    assert refused.items[_ITEM].round_history == fold(parked).items[_ITEM].round_history
    assert refused.items[_ITEM].pr is not None
    assert any("closure names PR 99" in a.reason for a in refused.anomalies)
    assert applied.items[_ITEM].review == ItemReview()


@pytest.mark.parametrize("exit_route", ["ordinary", "abandon"])
def test_the_next_cycle_records_its_own_review_from_an_empty_snapshot(exit_route: str) -> None:
    """The first round of a new cycle writes round, kind, head_sha and detail
    and nothing else, so a leaked verdict or thread count from the previous
    cycle is visible on the board until a verdict happens to overwrite it.
    This is the state where that leak shows."""
    if exit_route == "ordinary":
        closed = [
            *_reviewed_pr(),
            event("pr_closed", item=_ITEM, pr=7, reason="superseded", next="in-progress"),
        ]
    else:
        closed = [
            *_parked_reviewed_pr(),
            event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 7}),
            event("item_started", item=_ITEM),
        ]

    opened = [
        *closed,
        event("pr_opened", item=_ITEM, pr=8),
        event("review_round", item=_ITEM, kind="human", round=1, head_sha="new-head"),
    ]
    round_state = fold(opened)

    assert round_state.items[_ITEM].review == ItemReview(round=1, kind="human", head_sha="new-head")
    assert round_state.items[_ITEM].round_history == ((1, "new-head", "2026-07-19T00:05:00Z"),)

    verdict_state = fold(
        [
            *opened,
            event(
                "review_verdict",
                item=_ITEM,
                kind="human",
                round=1,
                head_sha="new-head",
                verdict="clean",
                findings=[],
            ),
        ]
    )

    assert verdict_state.items[_ITEM].review == ItemReview(
        round=1, kind="human", head_sha="new-head", verdict="clean"
    )
    assert verdict_state.anomalies == []


@pytest.mark.parametrize("exit_route", ["ordinary", "abandon"])
def test_both_closures_of_a_never_reviewed_pr_are_no_ops(exit_route: str) -> None:
    never_reviewed = [
        seed_event(),
        event("item_started", item=_ITEM),
        event("pr_opened", item=_ITEM, pr=7),
    ]
    if exit_route == "ordinary":
        events = [
            *never_reviewed,
            event("pr_closed", item=_ITEM, pr=7, reason="superseded", next="queued"),
        ]
    else:
        events = [
            *never_reviewed,
            event("item_parked", item=_ITEM, reason="bot-declined"),
            event("item_enqueued", item=_ITEM, lane="lane-a", closure={"pr": 7}),
        ]

    state = fold(events)

    assert state.items[_ITEM].review == ItemReview()
    assert state.items[_ITEM].round_history == ()
    assert state.anomalies == []


def test_item_done_still_clears_the_snapshot() -> None:
    """The merge path keeps its own clearing: a merged item holds its review
    until `item_done`, which is the only place a *merged* cycle's snapshot is
    dropped."""
    merged = [
        *_reviewed_pr(),
        event("item_merged", item=_ITEM, pr=7, sha="old-head"),
    ]

    assert fold(merged).items[_ITEM].review.stalemate is True

    done = fold([*merged, event("item_done", item=_ITEM)])

    assert done.items[_ITEM].status == "done"
    assert done.items[_ITEM].review == ItemReview()
