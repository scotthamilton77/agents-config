"""Tests for the terminal-phase predicates and zero-value bootstrap (§3.1, §2).

The terminal sets are coded decisions (which phases the CLI treats as "done" vs
"absorbing"), so they're pinned here. The bootstrap factory pins the §3.3
zero-value shape so a first `run` invocation starts from a known-good state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.lifecycle import (
    GRAPH_TERMINAL_PHASES,
    TERMINAL_FOR_CLI_PHASES,
    is_graph_terminal,
    is_terminal_for_cli,
)
from prgroom.prsession.enums import ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    SCHEMA_VERSION,
    Identity,
    ReviewItem,
    bootstrap_state,
)

_FIXED = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _sentinel_item() -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.ISSUE_COMMENT,
        identity=Identity(gh_id="x"),
        author="a",
        body_excerpt="b",
        seen_at=_FIXED,
    )


def test_terminal_for_cli_is_the_three_resting_phases() -> None:
    assert (
        frozenset({PRPhase.QUIESCED, PRPhase.HUMAN_GATED, PRPhase.MERGED})
        == TERMINAL_FOR_CLI_PHASES
    )


def test_graph_terminal_is_merged_only() -> None:
    assert frozenset({PRPhase.MERGED}) == GRAPH_TERMINAL_PHASES


def test_is_terminal_for_cli_covers_quiesced_human_gated_merged() -> None:
    assert is_terminal_for_cli(PRPhase.QUIESCED)
    assert is_terminal_for_cli(PRPhase.HUMAN_GATED)
    assert is_terminal_for_cli(PRPhase.MERGED)


def test_is_terminal_for_cli_false_for_active_phases() -> None:
    assert not is_terminal_for_cli(PRPhase.IDLE)
    assert not is_terminal_for_cli(PRPhase.AWAITING_REVIEW)
    assert not is_terminal_for_cli(PRPhase.FIXES_PENDING)


def test_is_graph_terminal_only_merged() -> None:
    assert is_graph_terminal(PRPhase.MERGED)
    for phase in (
        PRPhase.IDLE,
        PRPhase.AWAITING_REVIEW,
        PRPhase.FIXES_PENDING,
        PRPhase.QUIESCED,
        PRPhase.HUMAN_GATED,
    ):
        assert not is_graph_terminal(phase)


def test_bootstrap_state_is_the_zero_value_shape() -> None:
    pr = PRRef(owner="octo", repo="demo", number=7)
    state = bootstrap_state(pr, now=_FIXED)

    assert state.pr == pr
    assert state.schema_version == SCHEMA_VERSION == 1
    assert state.phase == PRPhase.IDLE
    assert state.pr_review_retries_used == 0
    assert state.last_poll_sha == ""
    assert state.last_pushed_head_sha == ""
    assert state.reviewers == {}
    assert state.items == []
    assert state.last_error is None
    assert state.lifecycle_escalation_filed is False
    assert state.human_review_label_added is False
    assert state.last_polled_at == _FIXED
    assert state.last_activity_at == _FIXED
    assert state.quiescence.ci_state == ""
    assert state.quiescence.quiesced_at is None


def test_bootstrap_state_uses_distinct_state_instances_per_call() -> None:
    pr = PRRef(owner="octo", repo="demo", number=7)
    first = bootstrap_state(pr, now=_FIXED)
    second = bootstrap_state(pr, now=_FIXED)
    first.items.append(_sentinel_item())
    assert second.items == []  # mutable defaults are not shared across instances
