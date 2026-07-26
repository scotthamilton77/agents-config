"""`fix_attempted` -- the attempt ledger the fold counts and never caps -- and
`item_enqueued.closure`, the abandoned PR recorded on the parking lot's exit."""

from __future__ import annotations

from typing import Any

from grind.fold import fold
from tests.unit.builders import event, seed_event


def _to_pr_open() -> list[dict[str, Any]]:
    return [
        seed_event(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=7),
    ]


def _attempt(kind: str = "ci-fix", item: str = "wgclw.1") -> dict[str, Any]:
    return event("fix_attempted", item=item, kind=kind)


# -- counting (S9T1-B2) --------------------------------------------------------


def test_two_ci_fix_attempts_fold_to_two_and_a_third_folds_to_three() -> None:
    # grind counts, it never caps: the third attempt is past the default budget
    # of 2 and is still recorded, because refusing it is the decision layer's
    # call and the ledger's job is to stay an honest record of what happened.
    prefix = [*_to_pr_open(), _attempt(), _attempt()]

    two = fold(prefix)
    three = fold([*prefix, _attempt()])

    assert two.items["wgclw.1"].attempts["ci-fix"] == 2
    assert three.items["wgclw.1"].attempts["ci-fix"] == 3
    assert three.anomalies == []


def test_attempt_counts_are_kept_per_kind() -> None:
    state = fold([*_to_pr_open(), _attempt("ci-fix"), _attempt("rebase"), _attempt("ci-fix")])

    assert state.items["wgclw.1"].attempts == {"ci-fix": 2, "rebase": 1}


def test_an_untouched_item_carries_a_zeroed_ledger_rather_than_an_empty_one() -> None:
    # Every kind present at zero: a consumer reads a count, never an absence.
    state = fold([seed_event()])

    assert state.items["wgclw.1"].attempts == {"ci-fix": 0, "rebase": 0}


def test_default_config_carries_the_initial_attempt_budgets() -> None:
    # S9T1-B4: the budgets are caller-tunable config, seeded with D10's initial
    # values. Nothing in this package enforces either number.
    state = fold([seed_event()])

    assert state.config["ci_fix_budget"] == 2
    assert state.config["rebase_budget"] == 1


# -- the anomaly edges (S9T1-B1) -----------------------------------------------


def test_fix_attempted_on_a_parked_item_flags_and_leaves_the_ledger_alone() -> None:
    state = fold(
        [
            *_to_pr_open(),
            _attempt(),
            event("item_parked", item="wgclw.1", reason="ci-failure", note="budget spent"),
            _attempt(),
        ]
    )

    assert state.items["wgclw.1"].attempts["ci-fix"] == 1
    assert any(a.type == "fix_attempted" and "parked" in a.reason for a in state.anomalies)


def test_fix_attempted_on_a_terminal_item_flags_and_leaves_the_ledger_alone() -> None:
    state = fold(
        [*_to_pr_open(), event("item_merged", item="wgclw.1", pr=7, sha="abc"), _attempt()]
    )

    assert state.items["wgclw.1"].attempts["ci-fix"] == 0
    assert any(
        a.type == "fix_attempted" and "illegal from status 'merged'" in a.reason
        for a in state.anomalies
    )


def test_fix_attempted_on_an_absent_item_flags() -> None:
    state = fold([*_to_pr_open(), _attempt(item="does-not-exist")])

    assert any(a.type == "fix_attempted" and "unknown item" in a.reason for a in state.anomalies)


def test_fix_attempted_needs_a_pr_and_reads_the_ref_not_the_status() -> None:
    # An attempt exists only inside a PR cycle. Keyed on the PR ref rather than
    # on status, because `blocked` legally holds an open PR.
    no_pr = fold([seed_event(), event("item_started", item="wgclw.1"), _attempt()])

    assert no_pr.items["wgclw.1"].attempts["ci-fix"] == 0
    assert any(a.type == "fix_attempted" and "no open PR" in a.reason for a in no_pr.anomalies)

    blocked_with_pr = fold(
        [*_to_pr_open(), event("item_blocked", item="wgclw.1", on=["wgclw.2"]), _attempt()]
    )

    assert blocked_with_pr.items["wgclw.1"].attempts["ci-fix"] == 1
    assert blocked_with_pr.anomalies == []


def test_fix_attempted_after_the_pr_closes_flags_until_a_new_pr_opens() -> None:
    # `pr_closed` leaves the ref behind for the failure-park rule, so "has a PR
    # ref" is not "has an open PR": an attempt in the gap has nothing to fix,
    # and charging the fresh ledger there would spend the next cycle's budget
    # before that cycle exists.
    closed = [
        *_to_pr_open(),
        event("pr_closed", item="wgclw.1", pr=7, reason="superseded", next="in-progress"),
    ]
    in_the_gap = fold([*closed, _attempt()])

    assert in_the_gap.items["wgclw.1"].attempts["ci-fix"] == 0
    assert any(a.type == "fix_attempted" and "no open PR" in a.reason for a in in_the_gap.anomalies)

    # ... and the next PR restores it: pr_opened builds a fresh, open ref.
    recut = fold([*closed, event("pr_opened", item="wgclw.1", pr=8), _attempt()])

    assert recut.items["wgclw.1"].attempts["ci-fix"] == 1
    assert recut.anomalies == []


def test_a_failure_axis_park_still_accepts_the_closed_ref_the_attempt_gate_refuses() -> None:
    # The two rules read the same field and answer different questions: a park
    # states that this item's PR did not merge, which stays true after it
    # closes. Tightening the attempt gate must not tighten this one.
    state = fold(
        [
            *_to_pr_open(),
            event("pr_closed", item="wgclw.1", pr=7, reason="superseded", next="in-progress"),
            event("item_parked", item="wgclw.1", reason="ci-failure", note="never went green"),
        ]
    )

    parked = state.items["wgclw.1"].parked
    assert parked is not None
    assert parked.reason == "ci-failure"
    assert state.anomalies == []


def test_fix_attempted_with_an_unrecognized_kind_flags_rather_than_miscounting() -> None:
    # The boundary rejects an unknown kind as a command error appending
    # nothing; a hand-edited or replayed log that carries one anyway must not
    # land it in a ledger slot nobody reads.
    state = fold([*_to_pr_open(), _attempt("lint-fix")])

    assert state.items["wgclw.1"].attempts == {"ci-fix": 0, "rebase": 0}
    assert any(
        a.type == "fix_attempted" and "unrecognized attempt kind" in a.reason
        for a in state.anomalies
    )


# -- ledger lifetime is one PR cycle (S9T1-B3) ---------------------------------


def test_pr_closed_resets_the_attempt_ledger() -> None:
    # A new PR must not inherit the spent budget of the one that closed.
    spent = [*_to_pr_open(), _attempt(), _attempt("rebase")]
    assert fold(spent).items["wgclw.1"].attempts == {"ci-fix": 1, "rebase": 1}

    closed = fold(
        [*spent, event("pr_closed", item="wgclw.1", pr=7, reason="superseded", next="in-progress")]
    )

    assert closed.items["wgclw.1"].attempts == {"ci-fix": 0, "rebase": 0}


def test_item_enqueued_resets_the_attempt_ledger() -> None:
    # Leaving the parking lot deliberately grants a fresh window. The park
    # itself does not clear the ledger -- the counts survive to be read there.
    parked = [
        *_to_pr_open(),
        _attempt(),
        _attempt(),
        event("item_parked", item="wgclw.1", reason="ci-failure", note="budget spent"),
    ]
    assert fold(parked).items["wgclw.1"].attempts["ci-fix"] == 2

    enqueued = fold([*parked, event("item_enqueued", item="wgclw.1", lane="lane-a")])

    assert enqueued.items["wgclw.1"].attempts == {"ci-fix": 0, "rebase": 0}


def test_events_inside_the_pr_cycle_leave_the_ledger_unchanged() -> None:
    # Representatives for "no other event resets it": a review round mid-cycle,
    # and the pr_opened that starts the next one.
    after_review = fold(
        [
            *_to_pr_open(),
            _attempt(),
            event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        ]
    )

    assert after_review.items["wgclw.1"].attempts["ci-fix"] == 1

    # pr_opened starts the next cycle but does not itself clear the ledger, so
    # an attempt charged under the new PR is the only thing in it.
    reopened = fold(
        [
            *_to_pr_open(),
            _attempt(),
            event("pr_closed", item="wgclw.1", pr=7, reason="superseded", next="in-progress"),
            event("pr_opened", item="wgclw.1", pr=8),
            _attempt(),
            event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="b1"),
        ]
    )

    assert reopened.items["wgclw.1"].attempts["ci-fix"] == 1


# -- item_enqueued.closure (S9T1-B7) -------------------------------------------


def _parked_with_history() -> list[dict[str, Any]]:
    return [
        *_to_pr_open(),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
        event("item_parked", item="wgclw.1", reason="bot-declined", note="reviewer said no"),
    ]


def test_a_closure_records_the_closed_ledger_entry_and_drops_the_pr() -> None:
    state = fold(
        [
            *_parked_with_history(),
            event(
                "item_enqueued",
                item="wgclw.1",
                lane="lane-a",
                closure={"pr": 7, "reason": "abandoned"},
            ),
        ]
    )

    item = state.items["wgclw.1"]
    assert item.pr is None
    # the review cycle ended with its PR, so the next one starts clean
    assert item.round_history == ()
    assert [(c.item, c.pr, c.reason) for c in state.closed_ledger] == [("wgclw.1", 7, "abandoned")]
    # the park exit itself proceeds unchanged
    assert item.parked is None
    assert item.status == "queued"
    assert "wgclw.1" in state.lanes["lane-a"].item_ids
    assert state.anomalies == []


def test_a_closure_is_optional_and_the_pr_survives_an_exit_without_one() -> None:
    # Redispatch resumes the same PR, so a plain enqueue must not drop the ref.
    state = fold([*_parked_with_history(), event("item_enqueued", item="wgclw.1", lane="lane-a")])

    item = state.items["wgclw.1"]
    assert item.pr is not None
    assert item.pr.number == 7
    assert state.closed_ledger == []


def test_a_closure_naming_another_pr_is_flagged_and_not_applied() -> None:
    # `--pr` is only shape-checked at the boundary, so a mistyped number
    # arrives well-formed. Applying it would write a closure record for a PR
    # this item never had and throw away the live ref the park rule and the
    # attempt gate both read -- while the enqueue itself must still happen.
    state = fold(
        [
            *_parked_with_history(),
            event("item_enqueued", item="wgclw.1", lane="lane-a", closure={"pr": 9}),
        ]
    )

    item = state.items["wgclw.1"]
    assert state.closed_ledger == []
    assert item.pr is not None
    assert item.pr.number == 7
    assert any(
        a.type == "item_enqueued" and "closure names PR 9" in a.reason for a in state.anomalies
    )
    # the exit from the parking lot proceeds regardless
    assert item.parked is None
    assert item.status == "queued"


def test_a_boolean_closure_pr_does_not_pass_for_pr_one() -> None:
    # `bool` is an `int` subclass and `True == 1`, so a hand-edited `"pr": true`
    # would otherwise satisfy both the type check and the match against PR 1 --
    # writing `pr: true` into the ledger and discarding the live ref.
    state = fold(
        [
            seed_event(),
            event("item_started", item="wgclw.1"),
            event("pr_opened", item="wgclw.1", pr=1),
            event("item_parked", item="wgclw.1", reason="bot-declined", note="no"),
            event("item_enqueued", item="wgclw.1", lane="lane-a", closure={"pr": True}),
        ]
    )

    item = state.items["wgclw.1"]
    assert state.closed_ledger == []
    assert item.pr is not None
    assert item.pr.number == 1
    assert any(
        a.type == "item_enqueued" and "closure names PR True" in a.reason for a in state.anomalies
    )


def test_a_closure_on_an_item_holding_no_pr_is_flagged_and_not_applied() -> None:
    state = fold(
        [
            seed_event(),
            event("item_parked", item="wgclw.1", reason="later-wave", note="not yet"),
            event("item_enqueued", item="wgclw.1", lane="lane-a", closure={"pr": 7}),
        ]
    )

    assert state.closed_ledger == []
    assert state.items["wgclw.1"].parked is None
    assert any(
        a.type == "item_enqueued" and "the item holds None" in a.reason for a in state.anomalies
    )


def test_a_closure_reason_is_optional() -> None:
    state = fold(
        [
            *_parked_with_history(),
            event("item_enqueued", item="wgclw.1", lane="lane-a", closure={"pr": 7}),
        ]
    )

    assert state.closed_ledger[0].reason is None
    assert state.items["wgclw.1"].pr is None
