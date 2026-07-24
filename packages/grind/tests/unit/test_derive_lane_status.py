"""Lane status is fully derived from item statuses (spec: "all done -> done;
any in flight -> the most advanced active state"), never asserted directly.
"""

from __future__ import annotations

from grind.derive import lane_status
from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_lane_with_all_items_queued_is_queued() -> None:
    state = fold([seed_event()])

    assert lane_status(state, state.lanes["lane-a"]) == "queued"


def test_lane_status_is_the_most_advanced_active_item() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        # wgclw.2 stays queued.
    ]

    state = fold(events)

    assert lane_status(state, state.lanes["lane-a"]) == "pr-open"


def test_lane_status_is_done_when_every_item_is_done() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a"),
        event("item_done", item="wgclw.1"),
        event("item_started", item="wgclw.2"),
        event("pr_opened", item="wgclw.2", pr=2),
        event("item_merged", item="wgclw.2", pr=2, sha="b"),
        event("item_done", item="wgclw.2"),
    ]

    state = fold(events)

    assert lane_status(state, state.lanes["lane-a"]) == "done"


def test_parked_items_are_excluded_from_lane_status_derivation() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a"),
        event("item_done", item="wgclw.1"),
        event("item_parked", item="wgclw.2", reason="later-wave", note="not yet"),
    ]

    state = fold(events)

    # The only non-parked item in the lane is done.
    assert lane_status(state, state.lanes["lane-a"]) == "done"


def test_lane_standing_down_with_empty_active_queue_reports_standing_down() -> None:
    events = [
        seed_event(),
        event("item_parked", item="wgclw.1", reason="later-wave", note="cut"),
        event("item_parked", item="wgclw.2", reason="later-wave", note="cut"),
        event("lane_standing_down", lane="lane-a"),
    ]

    state = fold(events)

    assert lane_status(state, state.lanes["lane-a"]) == "standing-down"


def test_a_lane_with_one_done_item_and_one_untouched_item_is_not_done() -> None:
    # "all done -> done" requires EVERY item done; a lane that's only partway
    # there reports the most advanced item that ISN'T done yet, not `done`.
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a"),
        event("item_done", item="wgclw.1"),
        # wgclw.2 stays queued.
    ]

    state = fold(events)

    assert lane_status(state, state.lanes["lane-a"]) == "queued"


def test_lane_standing_down_flag_does_not_override_active_work() -> None:
    events = [
        seed_event(),
        event("lane_standing_down", lane="lane-a"),
        event("item_started", item="wgclw.1"),
    ]

    state = fold(events)

    assert lane_status(state, state.lanes["lane-a"]) == "in-progress"
