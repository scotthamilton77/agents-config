"""item_blocked / derived unblocking, including cascading chains."""

from __future__ import annotations

from grind.fold import fold
from tests.unit.builders import event, seed_event


def test_item_blocked_moves_queued_item_to_blocked() -> None:
    events = [seed_event(), event("item_blocked", item="wgclw.2", on=["wgclw.1"])]

    state = fold(events)

    item = state.items["wgclw.2"]
    assert item.status == "blocked"
    assert item.blocked_on == ("wgclw.1",)


def test_item_unblocks_to_queued_when_all_edges_resolve_via_merge() -> None:
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a1"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "queued"


def test_unblocking_via_done_resolves_every_item_blocked_on_the_same_target() -> None:
    # Both wgclw.2 and disc-1 are blocked on wgclw.1 -- one merge/done should
    # unblock the whole fan-out in the same fold pass.
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            description="second dependent",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="found while working",
        ),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_blocked", item="disc-1", on=["wgclw.1"]),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a1"),
        event("item_done", item="wgclw.1"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "queued"
    assert state.items["disc-1"].status == "queued"


def test_a_linear_chain_does_not_skip_cascade() -> None:
    # wgclw.2 is blocked on wgclw.1; disc-1 is blocked on wgclw.2 (not on wgclw.1
    # directly). Unblocking wgclw.2 only moves IT to `queued` -- it never reaches
    # merged/done, so disc-1's edge on wgclw.2 stays unresolved (spec: "an edge
    # resolves only when its target reaches merged/done").
    events = [
        seed_event(),
        event(
            "discovered_work",
            item="disc-1",
            description="chained blocker",
            source="lane-a",
            disposition="enqueued",
            lane="lane-a",
            rationale="found while working",
        ),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_blocked", item="disc-1", on=["wgclw.2"]),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="a1"),
        event("item_done", item="wgclw.1"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "queued"
    assert state.items["disc-1"].status == "blocked"


def test_pr_closed_target_does_not_resolve_the_edge() -> None:
    # Per spec: "a pr_closed target stays unresolved -- parked or reworked work is unfinished."
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("pr_closed", item="wgclw.1", pr=1, reason="abandoned", next="queued"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "blocked"


def test_later_item_blocked_replaces_the_full_edge_set() -> None:
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.1"]),
        event("item_blocked", item="wgclw.2", on=["wgclw.1", "does-not-exist"], note="re-scoped"),
    ]

    state = fold(events)

    item = state.items["wgclw.2"]
    assert item.blocked_on == ("wgclw.1", "does-not-exist")
    assert item.blocked_note == "re-scoped"
    assert item.status == "blocked"


def test_item_waiting_human_is_legal_from_blocked() -> None:
    # Table row `blocked`, column `waiting_human` = "waiting-human": a human can be
    # asked to intervene on a dependency that isn't resolving on its own.
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.9"]),
        event("item_waiting_human", item="wgclw.2", why="stuck dependency"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "waiting-human"


def test_item_resumed_with_unresolved_edges_folds_to_blocked_not_in_progress() -> None:
    # Derived-blocked takes precedence over resume.
    events = [
        seed_event(),
        event("item_blocked", item="wgclw.2", on=["wgclw.9"]),
        event("item_waiting_human", item="wgclw.2", why="stuck dependency"),
        event("item_resumed", item="wgclw.2", ruling="keep waiting"),
    ]

    state = fold(events)

    assert state.items["wgclw.2"].status == "blocked"


def test_item_resumed_with_no_unresolved_edges_returns_to_in_progress() -> None:
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("item_waiting_human", item="wgclw.1", why="need a decision"),
        event("item_resumed", item="wgclw.1", ruling="proceed"),
    ]

    state = fold(events)

    assert state.items["wgclw.1"].status == "in-progress"
    assert not any(a.item == "wgclw.1" and a.auto for a in state.attention)


def test_item_resumed_preserves_unrelated_error_attention_on_the_same_item() -> None:
    # Resume clears only the waiting-human attention entry, not an unrelated
    # ERROR observation's attention that happens to share the item (spec:
    # item_resumed "clears the item's auto-raised attention entry" -- the one
    # raised by item_waiting_human, not every auto alert for the item).
    events = [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("observation", level="ERROR", message="CI is red", item="wgclw.1"),
        event("item_waiting_human", item="wgclw.1", why="need a decision"),
        event("item_resumed", item="wgclw.1", ruling="proceed"),
    ]

    state = fold(events)

    texts = [a.text for a in state.attention if a.item == "wgclw.1"]
    assert "CI is red" in texts
    assert "need a decision" not in texts
