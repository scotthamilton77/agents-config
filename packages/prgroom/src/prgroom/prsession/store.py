"""The prsession.Store Protocol and its error types (§2).

Store persists a single PR's grooming session state. The Protocol is
deliberately a typed key-value store with locking — NOT a tracker (no
change-detection, no event-emission, no CAS predicates). Concrete adapters
(:class:`~prgroom.prsession.file.FileStore`, the test-only
:class:`~prgroom.prsession.memory.InMemoryStore`) **structurally satisfy** this
Protocol; they do not inherit it. ``mypy --strict`` checks the fit, exactly as
``pdlc``'s ``InMemoryWorkTracker`` satisfies ``WorkTracker``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState


class StateNotFoundError(LookupError):
    """Raised by :meth:`Store.read` when no state exists for the given PR (§2, §7.6)."""


class StateCorruptError(ValueError):
    """Raised when persisted state fails to parse (maps to STATE_CORRUPT, §3.7)."""


class SchemaUnknownError(ValueError):
    """Raised when persisted ``schema_version`` is unrecognized (STATE_SCHEMA_UNKNOWN, §3.7)."""


@runtime_checkable
class Store(Protocol):
    """The per-PR state-persistence contract (§2)."""

    def read(self, ref: PRRef) -> PRGroomingState: ...  # pragma: no cover

    def write(self, ref: PRRef, state: PRGroomingState) -> None: ...  # pragma: no cover

    def lock(self, ref: PRRef) -> AbstractContextManager[None]: ...  # pragma: no cover

    def list_refs(self) -> list[PRRef]: ...  # pragma: no cover

    def delete(self, ref: PRRef) -> None: ...  # pragma: no cover
