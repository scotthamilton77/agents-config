"""The WorkTracker protocol and its in-memory reference adapter.

The protocol is **prescriptive of orchestrator needs** (Law L8): adapters
implement the full four-domain surface — Discovery & state, Lifecycle,
Hierarchy, Spec content — with no capability flags. `InMemoryWorkTracker` is
the reference MVP adapter the tracer binds against; a `bd`-backed adapter
(shelling to Dolt) is a heavier, separately-delivered conformance target. An
in-memory adapter keeps the tracer's integration test fast and tracker-
agnostic, which is the whole point of the abstraction — and matches the
Appendix-A scenario's "mocked WorkTracker (bd-adapter shape)".

Provenance note: the State-Ownership boundary makes provenance canonically
orchestrator-sidecar-owned. The reference adapter still retains
`originating_idea_id` from `create_objective` so the tracer can verify
fingerprint propagation across the promote seam; a `bd` adapter need not.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, TypeAlias, runtime_checkable

# A marker is an opaque discovery token. The in-memory adapter uses a logical
# version counter; other adapters synthesise an equivalent.
Marker: TypeAlias = int


@dataclass(frozen=True, slots=True)
class ObjectiveRecord:
    """The tracker's view of an Objective. `lifecycle_status` is the coarse
    open/in_progress/closed/blocked/deferred projection the tracker owns; the
    fine-grained `lifecycle_stage` is orchestrator-owned and not here."""

    id: str
    parent_id: str | None
    objective_type: str
    title: str
    spec: str
    lifecycle_status: str
    audit_notes: tuple[str, ...] = ()
    terminal_disposition: str | None = None
    originating_idea_id: str | None = None


@runtime_checkable
class WorkTracker(Protocol):
    """The four-domain work-tracker contract the orchestrator depends on."""

    # Domain 1 — Discovery & state
    def discover_since(
        self, marker: Marker | None
    ) -> tuple[list[ObjectiveRecord], Marker]: ...  # pragma: no cover
    def list_all_ids(self) -> list[str]: ...  # pragma: no cover
    def get_objective(self, objective_id: str) -> ObjectiveRecord: ...  # pragma: no cover
    def bulk_get(self, objective_ids: list[str]) -> list[ObjectiveRecord]: ...  # pragma: no cover

    # Domain 2 — Lifecycle
    def set_lifecycle_status(
        self, objective_id: str, status: str, reason: str
    ) -> None: ...  # pragma: no cover
    def set_killed(self, objective_id: str, epitaph: str) -> None: ...  # pragma: no cover
    def set_terminal_disposition(
        self, objective_id: str, disposition: str, reason: str
    ) -> None: ...  # pragma: no cover
    def append_audit_note(self, objective_id: str, text: str) -> None: ...  # pragma: no cover

    # Domain 3 — Hierarchy
    def list_children(self, objective_id: str) -> list[str]: ...  # pragma: no cover
    def walk_parent_chain(self, objective_id: str) -> list[str]: ...  # pragma: no cover
    def reparent(
        self, objective_id: str, new_parent_id: str | None, reason: str
    ) -> None: ...  # pragma: no cover
    def create_objective(  # pragma: no cover
        self,
        *,
        parent_id: str | None,
        objective_type: str,
        title: str,
        body: str,
        originating_idea_id: str | None = None,
        decomposition_of: str | None = None,
    ) -> str: ...

    # Domain 4 — Spec content
    def get_spec(self, objective_id: str) -> str: ...  # pragma: no cover
    def update_spec(
        self, objective_id: str, blob: str, reason: str
    ) -> None: ...  # pragma: no cover


class ObjectiveNotFoundError(LookupError):
    """Raised when an objective id is unknown to the tracker."""


class InMemoryWorkTracker:
    """Reference MVP adapter. Structurally satisfies `WorkTracker`.

    Discovery markers are a logical version counter: every create or mutation
    bumps a global clock and stamps the affected record's version, so
    `discover_since(marker)` returns exactly the records changed since that
    marker. Mutations record an audit note carrying the supplied reason, so
    the audit trail is real rather than discarded.
    """

    def __init__(self) -> None:
        self._records: dict[str, ObjectiveRecord] = {}
        self._versions: dict[str, int] = {}
        self._clock = 0
        self._next_id = 0

    def _require(self, objective_id: str) -> ObjectiveRecord:
        try:
            return self._records[objective_id]
        except KeyError as exc:
            raise ObjectiveNotFoundError(objective_id) from exc

    def _store(self, record: ObjectiveRecord) -> None:
        self._clock += 1
        self._records[record.id] = record
        self._versions[record.id] = self._clock

    # Domain 1 — Discovery & state

    def discover_since(self, marker: Marker | None) -> tuple[list[ObjectiveRecord], Marker]:
        threshold = marker if marker is not None else 0
        changed = [r for oid, r in self._records.items() if self._versions[oid] > threshold]
        new_marker = max(self._versions.values(), default=threshold)
        return changed, new_marker

    def list_all_ids(self) -> list[str]:
        return list(self._records)

    def get_objective(self, objective_id: str) -> ObjectiveRecord:
        return self._require(objective_id)

    def bulk_get(self, objective_ids: list[str]) -> list[ObjectiveRecord]:
        return [self._require(oid) for oid in objective_ids]

    # Domain 2 — Lifecycle

    def set_lifecycle_status(self, objective_id: str, status: str, reason: str) -> None:
        record = self._require(objective_id)
        self._store(
            replace(
                record,
                lifecycle_status=status,
                audit_notes=(*record.audit_notes, f"status={status}: {reason}"),
            )
        )

    def set_killed(self, objective_id: str, epitaph: str) -> None:
        record = self._require(objective_id)
        self._store(
            replace(
                record,
                lifecycle_status="closed",
                terminal_disposition="killed",
                audit_notes=(*record.audit_notes, f"killed: {epitaph}"),
            )
        )

    def set_terminal_disposition(self, objective_id: str, disposition: str, reason: str) -> None:
        record = self._require(objective_id)
        self._store(
            replace(
                record,
                terminal_disposition=disposition,
                audit_notes=(*record.audit_notes, f"disposition={disposition}: {reason}"),
            )
        )

    def append_audit_note(self, objective_id: str, text: str) -> None:
        record = self._require(objective_id)
        self._store(replace(record, audit_notes=(*record.audit_notes, text)))

    # Domain 3 — Hierarchy

    def list_children(self, objective_id: str) -> list[str]:
        return [oid for oid, r in self._records.items() if r.parent_id == objective_id]

    def walk_parent_chain(self, objective_id: str) -> list[str]:
        chain: list[str] = []
        current = self._require(objective_id).parent_id
        while current is not None:
            chain.append(current)
            current = self._require(current).parent_id
        return chain

    def reparent(self, objective_id: str, new_parent_id: str | None, reason: str) -> None:
        record = self._require(objective_id)
        self._store(
            replace(
                record,
                parent_id=new_parent_id,
                audit_notes=(*record.audit_notes, f"reparent->{new_parent_id}: {reason}"),
            )
        )

    def create_objective(
        self,
        *,
        parent_id: str | None,
        objective_type: str,
        title: str,
        body: str,
        originating_idea_id: str | None = None,
        decomposition_of: str | None = None,
    ) -> str:
        self._next_id += 1
        objective_id = f"obj-{self._next_id}"
        notes: tuple[str, ...] = ()
        if decomposition_of is not None:
            notes = (f"decomposition_of={decomposition_of}",)
        self._store(
            ObjectiveRecord(
                id=objective_id,
                parent_id=parent_id,
                objective_type=objective_type,
                title=title,
                spec=body,
                lifecycle_status="open",
                audit_notes=notes,
                originating_idea_id=originating_idea_id,
            )
        )
        return objective_id

    # Domain 4 — Spec content

    def get_spec(self, objective_id: str) -> str:
        return self._require(objective_id).spec

    def update_spec(self, objective_id: str, blob: str, reason: str) -> None:
        record = self._require(objective_id)
        self._store(
            replace(
                record,
                spec=blob,
                audit_notes=(*record.audit_notes, f"spec-updated: {reason}"),
            )
        )
