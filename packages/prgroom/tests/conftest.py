"""Shared fixtures for the prgroom test suite.

These provide the common building blocks (a frozen clock fake, a sample PRRef,
an in-memory Store) so individual tests don't re-roll them. Tests that need a
bespoke clock time or PR still construct their own — these are conveniences, not
mandates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.deps import Deps
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef

FIXED_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


class FrozenClock:
    """A deterministic Clock fake. Structurally satisfies the Clock Protocol."""

    def __init__(self, now: datetime = FIXED_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FixedRandomness:
    """A deterministic Randomness fake yielding a constant token."""

    def __init__(self, token: str = "0123456789abcdef") -> None:  # noqa: S107  # deterministic hex token for a test fake, not a secret
        self._token = token

    def token_hex(self, n: int = 8) -> str:  # noqa: ARG002  # fixed token for determinism
        return self._token


@pytest.fixture
def fixed_now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def deps() -> Deps:
    """Deps wired with deterministic fakes (frozen clock + fixed randomness)."""
    return Deps(clock=FrozenClock(), randomness=FixedRandomness())


@pytest.fixture
def pr_ref() -> PRRef:
    return PRRef(owner="octo", repo="demo", number=7)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()
