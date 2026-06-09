"""Tests for the failure-tier model and structured-error registry (§3.3, §3.6, §3.7).

These pin *coded decisions*: the tier -> sysexits exit-code mapping, the
signal-aware cancellation code, and the 4-line ``what/why/how`` stderr contract
that both humans and agents parse. The exit codes are a serialization contract
(a scheduler reads them), so they are pinned here at the mapping boundary, not
treated as throwaway literals.
"""

from __future__ import annotations

import pytest

from prgroom.errors import (
    ErrorCode,
    PreconditionError,
    PrgroomError,
    Tier,
    exit_code_for_tier,
)


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        (Tier.PRECONDITION_USER_ERROR, 2),
        (Tier.PRECONDITION_NO_WORK, 0),
        (Tier.PRECONDITION_LOCK_HELD, 75),
        (Tier.RUNTIME_TRANSIENT, 75),
        (Tier.RUNTIME_TERMINAL_USER, 77),
        (Tier.CONTRACT_AUDIT_FAILED, 65),
        (Tier.STATE_CORRUPT, 78),
        (Tier.STATE_SCHEMA_UNKNOWN, 78),
        (Tier.LIFECYCLE_CAP, 0),
    ],
)
def test_exit_code_for_tier_maps_each_tier_to_its_sysexits_code(tier: Tier, expected: int) -> None:
    assert exit_code_for_tier(PrgroomError(tier=tier, code=ErrorCode.STATE_CORRUPT)) == expected


def test_cancelled_sigint_exits_130() -> None:
    err = PrgroomError(
        tier=Tier.RUNTIME_CANCELLED, code=ErrorCode.RUNTIME_CANCELLED_SIGINT, signum=2
    )
    assert exit_code_for_tier(err) == 130


def test_cancelled_sigterm_exits_143() -> None:
    err = PrgroomError(
        tier=Tier.RUNTIME_CANCELLED, code=ErrorCode.RUNTIME_CANCELLED_SIGTERM, signum=15
    )
    assert exit_code_for_tier(err) == 143


def test_unknown_tier_value_fails_loudly_via_exhaustiveness_guard() -> None:
    # §7.6 closed-match safety: a tier the match does not enumerate must hit the
    # `case _:` assert_never guard and raise, never silently return a bogus code.
    # We fabricate an out-of-band tier (bypassing the type system) to prove the
    # guard fires — this is what catches a future Tier member with no arm.
    bogus = PrgroomError(tier="not-a-real-tier", code=ErrorCode.STATE_CORRUPT)  # type: ignore[arg-type]
    with pytest.raises(AssertionError):
        exit_code_for_tier(bogus)


def test_precondition_error_formats_four_line_block() -> None:
    err = PreconditionError(ErrorCode.PRECONDITION_NO_PR_DETECTED)
    rendered = err.render()
    lines = rendered.splitlines()
    assert lines[0] == "error: PRECONDITION_NO_PR_DETECTED"
    assert lines[1].strip().startswith("what:")
    assert lines[2].strip().startswith("why:")
    assert lines[3].strip().startswith("how:")


def test_precondition_error_tier_is_user_error_by_default() -> None:
    err = PreconditionError(ErrorCode.PRECONDITION_NO_PR_DETECTED)
    assert err.tier == Tier.PRECONDITION_USER_ERROR


def test_no_work_precondition_codes_get_no_work_tier() -> None:
    # The "no-work" exception is by explicit enumeration, NOT NO_-prefix match.
    assert PreconditionError(ErrorCode.PRECONDITION_NO_ITEMS).tier == Tier.PRECONDITION_NO_WORK


def test_no_auth_despite_no_substring_is_user_error_not_no_work() -> None:
    # §3.7: PRECONDITION_NO_AUTH has the NO_ substring but is a user error.
    assert PreconditionError(ErrorCode.PRECONDITION_NO_AUTH).tier == Tier.PRECONDITION_USER_ERROR


def test_lock_held_precondition_gets_lock_held_tier() -> None:
    assert PreconditionError(ErrorCode.PRECONDITION_LOCK_HELD).tier == Tier.PRECONDITION_LOCK_HELD


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_registry_code_carries_nonempty_what_why_how(code: ErrorCode) -> None:
    entry = code.registry_entry()
    assert entry.what.strip()
    assert entry.why.strip()
    assert entry.how.strip()


def test_precondition_tier_rejects_a_non_precondition_code() -> None:
    # precondition_tier is resolvable only for PRECONDITION_* codes; calling it
    # on a runtime code is a programming error, surfaced as ValueError.
    with pytest.raises(ValueError, match="not a PRECONDITION"):
        ErrorCode.RUNTIME_GH_TERMINAL.precondition_tier()
