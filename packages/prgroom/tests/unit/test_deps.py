"""Tests for the clock/randomness injection seam (§7.6 determinism requirement).

The lifecycle must never reach a stdlib singleton directly: ``datetime.now`` and
any RNG arrive through injected Protocols so the quiescence predicate and the
orchestration are deterministic under test. These tests pin that the seam
*carries* an injected value through to a consumer — behavior, not the Protocol's
shape (mypy --strict already checks the structural fit).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prgroom.deps import Clock, Deps, Randomness, SystemClock, SystemRandomness


class FrozenClock:
    """A test fake Clock. Structurally satisfies the Clock Protocol."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequenceRandomness:
    """A test fake Randomness yielding a fixed token. Structurally satisfies the Protocol."""

    def __init__(self, token: str) -> None:
        self._token = token

    def token_hex(self, n: int = 8) -> str:  # noqa: ARG002  # fixed token for determinism
        return self._token


def _idle_elapsed(clock: Clock, since: datetime, threshold: timedelta) -> bool:
    """Tiny consumer that reaches the clock through the seam (mirrors the §4.1 idle timer)."""
    return clock.now() - since >= threshold


def test_injected_clock_drives_a_consumer_decision() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(base + timedelta(minutes=10))
    assert _idle_elapsed(clock, since=base, threshold=timedelta(minutes=5)) is True


def test_injected_clock_below_threshold_is_not_elapsed() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(base + timedelta(minutes=1))
    assert _idle_elapsed(clock, since=base, threshold=timedelta(minutes=5)) is False


def test_system_clock_returns_timezone_aware_utc() -> None:
    # The seam's real adapter must produce tz-aware UTC; naive datetimes would
    # break the §4 timestamp arithmetic against stored UTC values.
    assert SystemClock().now().tzinfo is UTC


def test_system_randomness_token_is_hex_of_expected_length() -> None:
    token = SystemRandomness().token_hex(8)
    assert len(token) == 16  # token_hex(n) yields 2*n hex chars
    assert all(c in "0123456789abcdef" for c in token)


def test_deps_default_factory_wires_system_adapters() -> None:
    deps = Deps.system()
    assert deps.clock.now().tzinfo is UTC
    assert len(deps.randomness.token_hex(4)) == 8


def test_deps_accepts_injected_fakes() -> None:
    base = datetime(2026, 6, 9, tzinfo=UTC)
    deps: Deps = Deps(clock=FrozenClock(base), randomness=SequenceRandomness("cafe"))
    assert deps.clock.now() == base
    assert deps.randomness.token_hex() == "cafe"


def test_protocol_types_are_importable_for_annotations() -> None:
    # The Protocols exist as nameable types consumers annotate against.
    assert Clock.__name__ == "Clock"
    assert Randomness.__name__ == "Randomness"
