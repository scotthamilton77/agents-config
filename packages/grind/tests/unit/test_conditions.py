"""`conditions(state, now)` -- the level-condition engine, and the transition
condition `item_unblocked` derived from a fold delta."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from grind.conditions import IMPERATIVE_VERBS, conditions, item_unblocked_conditions
from grind.fold import fold
from tests.unit.builders import event, seed_event

_T0 = "2026-07-19T00:00:00Z"


def _names(items: list[dict[str, object]]) -> set[str]:
    return {c["condition"] for c in items}  # type: ignore[misc]


def _by_name(items: list[dict[str, object]], name: str) -> list[dict[str, object]]:
    return [c for c in items if c["condition"] == name]


# -- lane_complete / grind_complete ------------------------------------------


def _two_item_lane_seed() -> dict[str, object]:
    return {
        "ts": _T0,
        "type": "grind_created",
        "title": "Widget grind",
        "repo": "acme/widgets",
        "mission": {},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "name": "Lane A",
                "queue": [{"id": "wgclw.1", "title": "First"}],
            }
        ],
    }


def test_lane_complete_fires_when_last_item_in_lane_reaches_done() -> None:
    events = [
        _two_item_lane_seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_done", item="wgclw.1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    lane_conditions = _by_name(result, "lane_complete")
    assert len(lane_conditions) == 1
    assert lane_conditions[0]["lane"] == "lane-a"


def test_grind_complete_fires_only_when_every_lane_is_complete() -> None:
    events = [
        _two_item_lane_seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_done", item="wgclw.1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "grind_complete" in _names(result)


def test_grind_complete_absent_while_any_lane_incomplete() -> None:
    state = fold([seed_event()])  # two lanes' worth of queued items, untouched

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "grind_complete" not in _names(result)
    assert "lane_complete" not in _names(result)


# -- stale_item / stale_lane --------------------------------------------------


def test_stale_item_fires_past_threshold_and_not_before() -> None:
    seed = _two_item_lane_seed()
    seed["config"] = {"stale_item_after": "45m"}
    state = fold([seed])

    just_under = conditions(state, datetime(2026, 7, 19, 0, 44, 59, tzinfo=UTC))
    just_over = conditions(state, datetime(2026, 7, 19, 0, 45, 1, tzinfo=UTC))

    assert "stale_item" not in _names(just_under)
    stale = _by_name(just_over, "stale_item")
    assert len(stale) == 1
    assert stale[0]["item"] == "wgclw.1"


def test_stale_item_excludes_terminal_and_parked_items() -> None:
    seed = _two_item_lane_seed()
    seed["config"] = {"stale_item_after": "45m"}
    events = [
        seed,
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_done", item="wgclw.1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC))

    assert "stale_item" not in _names(result)


def test_stale_lane_considers_events_on_items_currently_assigned() -> None:
    seed = _two_item_lane_seed()
    seed["config"] = {"stale_lane_after": "30m"}
    events = [
        seed,
        event("item_started", item="wgclw.1", ts="2026-07-19T00:20:00Z"),
    ]
    state = fold(events)

    # 25 min after the last item reference: under threshold.
    under = conditions(state, datetime(2026, 7, 19, 0, 45, 0, tzinfo=UTC))
    # 31 min after: over threshold.
    over = conditions(state, datetime(2026, 7, 19, 0, 51, 0, tzinfo=UTC))

    assert "stale_lane" not in _names(under)
    stale = _by_name(over, "stale_lane")
    assert len(stale) == 1
    assert stale[0]["lane"] == "lane-a"


# -- attention_pending ---------------------------------------------------------


def test_attention_pending_fires_with_count_and_oldest_age() -> None:
    events = [
        _two_item_lane_seed(),
        event(
            "item_waiting_human",
            item="wgclw.1",
            why="need a human decision",
            ts="2026-07-19T00:10:00Z",
        ),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 20, 0, tzinfo=UTC))

    pending = _by_name(result, "attention_pending")
    assert len(pending) == 1
    assert pending[0]["count"] == 1
    assert pending[0]["oldest_age_seconds"] == 600


def test_attention_pending_absent_when_no_attention() -> None:
    state = fold([_two_item_lane_seed()])

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "attention_pending" not in _names(result)


# -- blocked_chain --------------------------------------------------------------


def test_blocked_chain_reports_ordered_item_list() -> None:
    seed = {
        "ts": _T0,
        "type": "grind_created",
        "title": "t",
        "repo": "r",
        "mission": {},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "queue": [
                    {"id": "wgclw.1", "title": "root"},
                    {"id": "wgclw.2", "title": "mid", "on": ["wgclw.3"]},
                    {"id": "wgclw.3", "title": "leaf", "on": ["wgclw.4"]},
                    {"id": "wgclw.4", "title": "unresolved leaf blocker"},
                ],
            }
        ],
    }
    events = [seed, event("item_blocked", item="wgclw.1", on=["wgclw.2"])]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    chains = _by_name(result, "blocked_chain")
    assert any(
        c["item"] == "wgclw.1" and c["chain"] == ["wgclw.1", "wgclw.2", "wgclw.3"] for c in chains
    )


def test_blocked_chain_absent_when_blocker_is_not_itself_blocked() -> None:
    seed = _two_item_lane_seed()
    seed["lanes"][0]["queue"].append({"id": "wgclw.2", "title": "Second"})  # type: ignore[index]
    state = fold([seed, event("item_blocked", item="wgclw.1", on=["wgclw.2"])])

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "blocked_chain" not in _names(result)


# -- review_stalemate_risk -----------------------------------------------------


def _to_pr_open() -> list[dict[str, object]]:
    return [
        _two_item_lane_seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
    ]


def test_review_stalemate_risk_fires_after_n_distinct_rounds_same_sha() -> None:
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    risk = _by_name(result, "review_stalemate_risk")
    assert len(risk) == 1
    assert risk[0] == {
        "condition": "review_stalemate_risk",
        "item": "wgclw.1",
        "round": 3,
        "head_sha": "a1",
        "since": "2026-07-19T00:05:00Z",
    }


def test_review_stalemate_risk_resets_on_changed_head_sha() -> None:
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="b2"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="b2"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_review_stalemate_risk_not_fired_before_n_distinct_rounds() -> None:
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_review_stalemate_risk_ignores_late_earlier_round_duplicate() -> None:
    # Two distinct rounds on the same SHA, then a valid late verdict for the
    # earlier round: last-event-wins must update round 1 in place, not append a
    # third entry that fakes a three-distinct-round stalemate.
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event(
            "review_verdict",
            item="wgclw.1",
            kind="codex",
            round=1,
            head_sha="a1",
            verdict="clean",
            findings=[],
        ),
    ]
    state = fold(events)

    assert state.items["wgclw.1"].round_history == (
        (1, "a1", "2026-07-19T00:05:00Z"),
        (2, "a1", "2026-07-19T00:05:00Z"),
    )

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


# -- item_unblocked (transition) ------------------------------------------------


def test_item_unblocked_fires_once_on_the_resolving_append() -> None:
    seed = {
        "ts": _T0,
        "type": "grind_created",
        "title": "t",
        "repo": "r",
        "mission": {},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "queue": [
                    {"id": "wgclw.1", "title": "blocker"},
                    {"id": "wgclw.2", "title": "blocked", "on": ["wgclw.1"]},
                ],
            }
        ],
    }
    prefix = [
        seed,
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
    ]
    before = fold(prefix)
    merged_event = event("item_merged", item="wgclw.1", pr=1, sha="abc")
    after = fold([*prefix, merged_event])

    result = item_unblocked_conditions(before, after)

    assert result == [{"condition": "item_unblocked", "item": "wgclw.2"}]


def test_item_unblocked_absent_when_nothing_resolves() -> None:
    prefix = [_two_item_lane_seed(), event("item_started", item="wgclw.1")]
    before = fold(prefix)
    after = fold([*prefix, event("pr_opened", item="wgclw.1", pr=1)])

    result = item_unblocked_conditions(before, after)

    assert result == []


def test_item_unblocked_not_recomputed_from_state_alone() -> None:
    # Immediately after the unblock, and on every later fold, the resulting
    # state is indistinguishable from an item queued with no edges -- so a
    # second call comparing the *same* after-state to itself must be silent.
    seed = {
        "ts": _T0,
        "type": "grind_created",
        "title": "t",
        "repo": "r",
        "mission": {},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "queue": [
                    {"id": "wgclw.1", "title": "blocker"},
                    {"id": "wgclw.2", "title": "blocked", "on": ["wgclw.1"]},
                ],
            }
        ],
    }
    prefix = [
        seed,
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
    ]
    after = fold(prefix)

    assert item_unblocked_conditions(after, after) == []


def _blocked_pair_seed() -> dict[str, object]:
    """A two-item lane where `wgclw.2` is blocked on the unfinished `wgclw.1`."""
    return {
        "ts": _T0,
        "type": "grind_created",
        "title": "t",
        "repo": "r",
        "mission": {},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "queue": [
                    {"id": "wgclw.1", "title": "blocker"},
                    {"id": "wgclw.2", "title": "blocked", "on": ["wgclw.1"]},
                ],
            }
        ],
    }


def test_item_unblocked_absent_when_blocked_item_goes_waiting_human() -> None:
    # A blocked item can legally fold to waiting-human (parked for a human)
    # without its blocker edge resolving -- its blocked_on stays unresolved and
    # it is not startable, so this departure must NOT fire item_unblocked.
    prefix = [_blocked_pair_seed()]
    before = fold(prefix)
    assert before.items["wgclw.2"].status == "blocked"
    after = fold([*prefix, event("item_waiting_human", item="wgclw.2", why="need a human")])
    assert after.items["wgclw.2"].status == "waiting-human"
    assert after.items["wgclw.2"].blocked_on == ("wgclw.1",)

    assert item_unblocked_conditions(before, after) == []


def test_item_unblocked_absent_when_blocked_item_is_parked() -> None:
    # Parking a blocked item leaves its status blocked and its edges unresolved;
    # it never becomes startable, so no item_unblocked fires.
    prefix = [_blocked_pair_seed()]
    before = fold(prefix)
    after = fold([*prefix, event("item_parked", item="wgclw.2", note="later wave")])
    assert after.items["wgclw.2"].parked is not None
    assert after.items["wgclw.2"].blocked_on == ("wgclw.1",)

    assert item_unblocked_conditions(before, after) == []


def test_item_unblocked_fires_when_final_edge_resolves_to_queued() -> None:
    # The genuine case: the blocker reaches merged, the fold returns the item to
    # queued, and item_unblocked fires exactly once.
    prefix = [
        _blocked_pair_seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
    ]
    before = fold(prefix)
    after = fold([*prefix, event("item_merged", item="wgclw.1", pr=1, sha="abc")])
    assert after.items["wgclw.2"].status == "queued"

    assert item_unblocked_conditions(before, after) == [
        {"condition": "item_unblocked", "item": "wgclw.2"}
    ]


# -- HARD SEAM ------------------------------------------------------------------


def test_condition_names_are_never_imperative() -> None:
    """Facts, not orchestration policy (spec HARD SEAM): a condition name never
    reads as a command like "nudge" or "escalate"."""
    seed = _two_item_lane_seed()
    events = [
        seed,
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=1),
        event("item_merged", item="wgclw.1", pr=1, sha="abc"),
        event("item_done", item="wgclw.1"),
    ]
    state = fold(events)
    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))
    all_names = _names(result) | {"item_unblocked"}  # transition condition, named statically

    for name in all_names:
        first_word = re.split(r"[_\s]", name)[0]
        assert first_word not in IMPERATIVE_VERBS, f"{name!r} reads as an imperative"


def test_duration_threshold_over_int_digit_limit_falls_back_to_default() -> None:
    # past ~4300 digits int() raises ValueError before timedelta's OverflowError;
    # both are advisory-config noise, never an internal error
    events = [
        *_to_pr_open(),
    ]
    state = fold(events)
    state.config = {"stale_item_after": "9" * 5000 + "d"}

    result = conditions(state, datetime(2026, 7, 19, 0, 51, 0, tzinfo=UTC))

    assert "stale_item" in _names(result)


def test_duration_threshold_overflow_falls_back_to_default() -> None:
    # A regex-valid but astronomically large threshold overflows timedelta;
    # advisory config falls back to the default instead of erroring the verb.
    events = [
        *_to_pr_open(),
    ]
    state = fold(events)
    state.config = {"stale_item_after": "999999999999999999999d"}

    result = conditions(state, datetime(2026, 7, 19, 0, 51, 0, tzinfo=UTC))

    # default stale_item_after is 45m; at +51m past the last event the item is
    # stale under the fallback, proving the overflowing value was ignored
    assert "stale_item" in _names(result)


def test_review_stalemate_risk_not_fired_for_completed_item() -> None:
    # round_history survives merge/done, but a finished item has no live
    # review cycle to be stalled -- the risk must not follow it around.
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a1"),
        event("item_merged", item="wgclw.1", sha="m1"),
        event("item_done", item="wgclw.1"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_boolean_stalemate_threshold_falls_back_to_default() -> None:
    # bool is an int subtype; `true` must not read as a threshold of 1
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    ]
    state = fold(events)
    state.config = {"stalemate_risk_round": True}

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_stalemate_history_resets_when_pr_closes() -> None:
    # pr_closed ends the review cycle: a fresh pr_opened must not inherit the
    # closed PR's rounds and fire a stalemate before any new round occurs.
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a1"),
        event("pr_closed", item="wgclw.1", pr=1, next="queued", reason="superseded"),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=2),
    ]
    state = fold(events)

    assert state.items["wgclw.1"].round_history == ()

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_stalemate_risk_carries_window_start_as_since() -> None:
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a1"),
    ]
    state = fold(events)

    risk = _by_name(
        conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC)), "review_stalemate_risk"
    )

    assert risk[0]["since"] == "2026-07-19T00:05:00Z"


def test_stalemate_risk_excluded_for_parked_item() -> None:
    # parking preserves the item's status (e.g. waiting-human) and its
    # round_history; a parked item is out of the active queue, not stalled
    events = [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="a1"),
        event("review_round", item="wgclw.1", kind="codex", round=3, head_sha="a1"),
        event("item_waiting_human", item="wgclw.1", why="stalemate"),
        event("item_parked", item="wgclw.1", reason="deferred"),
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 0, 5, 0, tzinfo=UTC))

    assert "review_stalemate_risk" not in _names(result)


def test_staleness_suppressed_while_paused_or_finished() -> None:
    # a paused or finished grind is quiet on purpose -- same exemption
    # `grind check` applies; staleness measures unexpected silence only
    base = [
        _two_item_lane_seed(),
        event("item_started", item="wgclw.1"),
    ]
    late = datetime(2026, 7, 19, 6, 0, 0, tzinfo=UTC)

    running = fold(base)
    assert "stale_item" in _names(conditions(running, late))

    paused = fold([*base, event("grind_paused", reason="lunch")])
    names = _names(conditions(paused, late))
    assert "stale_item" not in names and "stale_lane" not in names


def test_malformed_recorded_ts_is_unavailable_not_a_crash() -> None:
    # the fold accepts structural garbage: a non-ISO ts can be recorded as an
    # item's last reference; conditions() must skip it, never raise
    events = [
        _two_item_lane_seed(),
        {"ts": "not-a-timestamp", "type": "item_started", "item": "wgclw.1"},
    ]
    state = fold(events)

    result = conditions(state, datetime(2026, 7, 19, 6, 0, 0, tzinfo=UTC))

    assert all(c["item"] != "wgclw.1" for c in _by_name(result, "stale_item"))
