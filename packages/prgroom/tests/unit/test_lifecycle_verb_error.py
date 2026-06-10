"""Tests for the §3.3 verb-error policy (`handle_verb_error` + `VerbDisposition`).

The policy maps a tier-tagged error to a control-flow disposition (CONTINUE vs
PROPAGATE) and the state mutation each tier mandates. The load-bearing test is the
**Tier enumeration**: every registered :class:`Tier` must have an explicit arm, so
adding a tier without updating this policy fails loudly (Python has no compile-time
match exhaustiveness — this test recovers it).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.lifecycle.verb_error import VerbDisposition, handle_verb_error
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, QuiescenceState

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _state() -> PRGroomingState:
    return PRGroomingState(
        pr=PRRef(owner="octo", repo="demo", number=7),
        phase=PRPhase.FIXES_PENDING,
        round=1,
        last_polled_at=_NOW,
        last_activity_at=_NOW,
        quiescence=QuiescenceState(),
        lifecycle_escalation_filed=True,  # set so we can prove the policy re-arms it
    )


def _err(tier: Tier, code: ErrorCode, *, signum: int = 0) -> PrgroomError:
    return PrgroomError(tier=tier, code=code, signum=signum)


# -- VerbDisposition canonical strings (user-facing boundary) --------------


# -- per-tier behavior -----------------------------------------------------


def test_runtime_transient_propagates_sets_last_error_no_phase_change() -> None:
    state = _state()
    err = _err(Tier.RUNTIME_TRANSIENT, ErrorCode.RUNTIME_GH_TRANSIENT)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.last_error == ErrorCode.RUNTIME_GH_TRANSIENT.value
    assert state.phase == PRPhase.FIXES_PENDING  # no phase change


def test_runtime_terminal_user_gates_human_and_rearms_escalation_flag() -> None:
    state = _state()
    err = _err(Tier.RUNTIME_TERMINAL_USER, ErrorCode.RUNTIME_GH_TERMINAL)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.phase == PRPhase.HUMAN_GATED
    assert state.last_error == ErrorCode.RUNTIME_GH_TERMINAL.value
    assert state.lifecycle_escalation_filed is False


def test_state_corrupt_gates_human_and_propagates() -> None:
    state = _state()
    err = _err(Tier.STATE_CORRUPT, ErrorCode.STATE_CORRUPT)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.phase == PRPhase.HUMAN_GATED
    assert state.last_error == ErrorCode.STATE_CORRUPT.value
    assert state.lifecycle_escalation_filed is False


def test_state_schema_unknown_gates_human_and_propagates() -> None:
    state = _state()
    err = _err(Tier.STATE_SCHEMA_UNKNOWN, ErrorCode.STATE_SCHEMA_UNKNOWN)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.phase == PRPhase.HUMAN_GATED
    assert state.last_error == ErrorCode.STATE_SCHEMA_UNKNOWN.value


def test_contract_audit_failed_continues_without_last_error() -> None:
    state = _state()
    err = _err(Tier.CONTRACT_AUDIT_FAILED, ErrorCode.CONTRACT_FIX_AUDIT_FAILED)
    assert handle_verb_error(err, state) == VerbDisposition.CONTINUE
    assert state.last_error is None  # cause is per-item rationale, not last_error
    assert state.phase == PRPhase.FIXES_PENDING


def test_runtime_cancelled_propagates_without_mutation() -> None:
    state = _state()
    before = state.to_dict()
    err = _err(Tier.RUNTIME_CANCELLED, ErrorCode.RUNTIME_CANCELLED_SIGINT, signum=2)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.to_dict() == before  # no phase, no last_error, no flag change


@pytest.mark.parametrize(
    "tier",
    [
        Tier.PRECONDITION_USER_ERROR,
        Tier.PRECONDITION_NO_WORK,
        Tier.PRECONDITION_LOCK_HELD,
        Tier.LIFECYCLE_CAP,
    ],
)
def test_unmodeled_tiers_propagate_without_mutation(tier: Tier) -> None:
    # Tiers that do not reach handle_verb_error in normal flow still get a defined,
    # safe answer (PROPAGATE, no silent state write) rather than undefined behavior.
    state = _state()
    before = state.to_dict()
    err = _err(tier, ErrorCode.PRECONDITION_NO_PR_DETECTED)
    assert handle_verb_error(err, state) == VerbDisposition.PROPAGATE
    assert state.to_dict() == before


def test_every_tier_member_has_a_defined_disposition() -> None:
    # Exhaustiveness: enumerate every registered Tier; each must yield a
    # VerbDisposition without raising. Catches a new Tier added without a policy arm.
    state = _state()
    for tier in Tier:
        result = handle_verb_error(
            _err(tier, ErrorCode.PRECONDITION_NO_PR_DETECTED, signum=2), state
        )
        assert isinstance(result, VerbDisposition)
