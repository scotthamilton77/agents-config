"""Clock and randomness injection seam (§7.6).

The lifecycle reaches for **no** stdlib singleton directly. ``datetime.now(UTC)``
and any RNG arrive through these injected Protocols so the quiescence predicate
and the poll->cluster->fix->push orchestration are deterministic under test.
Concrete adapters (:class:`SystemClock`, :class:`SystemRandomness`) **structurally
satisfy** their Protocol — they do not inherit it; ``mypy --strict`` checks the
fit. Tests inject fakes (a frozen clock, a fixed-token RNG).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Time source. The lifecycle calls :meth:`now` instead of ``datetime.now``."""

    def now(self) -> datetime: ...  # pragma: no cover


@runtime_checkable
class Randomness(Protocol):
    """Randomness source. Used for cluster-id / token generation."""

    def token_hex(self, n: int = 8) -> str: ...  # pragma: no cover


class SystemClock:
    """Real clock. Returns timezone-aware UTC so timestamp arithmetic against
    stored UTC values is correct (§4 resumability invariant)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SystemRandomness:
    """Real randomness, backed by :mod:`secrets`."""

    def token_hex(self, n: int = 8) -> str:
        return secrets.token_hex(n)


@dataclass(frozen=True, slots=True)
class Deps:
    """The injected-dependency bundle handed to the lifecycle.

    Construct with :meth:`system` for production wiring, or pass fakes directly
    in tests. Frozen so a cycle cannot accidentally swap its clock mid-run.
    """

    clock: Clock
    randomness: Randomness

    @classmethod
    def system(cls) -> Deps:
        """Production wiring: the real stdlib-backed adapters."""
        return cls(clock=SystemClock(), randomness=SystemRandomness())
