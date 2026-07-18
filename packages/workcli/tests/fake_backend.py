"""FakeBackend: an in-memory `Backend` for state-based lifecycle tests.

The recovery contract (deliver/reconcile) is about *state transitions* under
interruption -- which labels, status, children, and notes a bead ends up with
after a crash-and-replay. Asserting that through a scripted argv log
(`ScriptedBdRunner`) tests call-order, not the healed state. This fake models
bead state directly, so a test builds a partially-delivered tree, runs the
recovery, and asserts the final state.

Fidelity choices that matter for recovery correctness:
- `query()`/`ready()`/`search()` return *lean* Items (`children == []`,
  `deps == []`), mirroring bd `list`, which carries no children/dependents key
  (adapters/bd/parse.py). `reconcile` re-`get()`s every candidate precisely
  because of this; the fake preserves that seam, so a regression that trusts a
  query result's children is caught rather than masked.
- `Item` is frozen and carries no `acceptance` field, so `get()` rebuilds a
  fresh snapshot per read, and acceptance -- which bd stores but the normalized
  Item drops -- is exposed for assertions via `acceptance_of()`.

`add()`/`acceptance_of()`/`note_lines()` are test-facing scaffolding, not part
of the `Backend` protocol; structural conformance to `Backend` is enforced by
mypy at every call site that passes a FakeBackend where a Backend is expected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from workcli.backend import Capabilities, DepOp, ReadySupport, SyncSupport
from workcli.envelope import ErrorCode, WorkError
from workcli.model import (
    CreateFields,
    DepEdge,
    DepListing,
    Item,
    QueryFilters,
    SyncResult,
    UpdateFields,
)


@dataclass
class _Rec:
    """Mutable per-item record; `Item` snapshots are rebuilt frozen on read."""

    id: str
    title: str
    type: str
    status: str
    priority: str
    labels: list[str]
    parent: str | None
    description: str
    notes: str
    acceptance: str
    deps: list[DepEdge]


class FakeBackend:
    def __init__(self, *, id_prefix: str = "fake") -> None:
        self._items: dict[str, _Rec] = {}
        self._id_prefix = id_prefix
        self._counter = 0

    # -- test-facing scaffolding (not part of the Backend protocol) --

    def add(
        self,
        item_id: str,
        *,
        title: str = "T",
        type: str = "task",
        status: str = "open",
        priority: str = "P2",
        labels: Sequence[str] | None = None,
        parent: str | None = None,
        description: str = "",
        notes: str = "",
        acceptance: str = "",
        deps: Sequence[DepEdge] | None = None,
    ) -> FakeBackend:
        """Insert an item with an explicit id; returns self for chaining."""
        self._items[item_id] = _Rec(
            id=item_id,
            title=title,
            type=type,
            status=status,
            priority=priority,
            labels=list(labels or []),
            parent=parent,
            description=description,
            notes=notes,
            acceptance=acceptance,
            deps=list(deps or []),
        )
        return self

    def acceptance_of(self, item_id: str) -> str:
        return self._require(item_id).acceptance

    def note_lines(self, item_id: str) -> list[str]:
        return self._require(item_id).notes.splitlines()

    def ids(self) -> list[str]:
        return list(self._items)

    # -- internals --

    def _require(self, item_id: str) -> _Rec:
        if item_id not in self._items:
            raise WorkError(ErrorCode.NOT_FOUND, f"no such item: {item_id}", detail={"id": item_id})
        return self._items[item_id]

    def _children_of(self, item_id: str) -> list[str]:
        return [rec.id for rec in self._items.values() if rec.parent == item_id]

    def _snapshot(self, rec: _Rec, *, lean: bool) -> Item:
        return Item(
            id=rec.id,
            title=rec.title,
            type=rec.type,
            status=rec.status,
            priority=rec.priority,
            labels=list(rec.labels),
            parent=rec.parent,
            deps=[] if lean else list(rec.deps),
            children=[] if lean else self._children_of(rec.id),
            description=rec.description,
            notes=rec.notes,
            created=None,
            updated=None,
        )

    # -- Backend protocol --

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.NATIVE, sync=SyncSupport.NATIVE, supports_dep_write=True
        )

    def get(self, item_id: str) -> Item:
        return self._snapshot(self._require(item_id), lean=False)

    def batch_get(self, ids: Sequence[str]) -> list[Item]:
        return [self.get(item_id) for item_id in ids]

    def create(self, fields: CreateFields) -> str:
        self._counter += 1
        new_id = f"{self._id_prefix}-{self._counter}"
        deps: list[DepEdge] = []
        if fields.blocked_by is not None:
            blocker = self._items.get(fields.blocked_by)
            deps.append(
                DepEdge(
                    id=fields.blocked_by,
                    type="blocks",
                    status=blocker.status if blocker is not None else "open",
                )
            )
        self._items[new_id] = _Rec(
            id=new_id,
            title=fields.title,
            type=fields.type or "task",
            status="open",
            priority=fields.priority or "P2",
            labels=list(fields.labels),
            parent=fields.parent,
            description=fields.description or "",
            notes="",
            acceptance=fields.acceptance or "",
            deps=deps,
        )
        return new_id

    def set_fields(self, item_id: str, fields: UpdateFields) -> None:
        rec = self._require(item_id)
        if fields.title is not None:
            rec.title = fields.title
        if fields.priority is not None:
            rec.priority = fields.priority
        if fields.description is not None:
            rec.description = fields.description

    def claim(self, item_id: str) -> None:
        self._require(item_id).status = "in_progress"

    def set_status(self, item_id: str, status: str) -> None:
        self._require(item_id).status = status

    def set_type(self, item_id: str, item_type: str) -> None:
        self._require(item_id).type = item_type

    def set_acceptance(self, item_id: str, text: str) -> None:
        self._require(item_id).acceptance = text

    def append_note(self, item_id: str, text: str) -> None:
        rec = self._require(item_id)
        rec.notes = f"{rec.notes}\n{text}" if rec.notes else text

    def close(self, ids: Sequence[str]) -> None:
        for item_id in ids:
            self._require(item_id).status = "closed"

    def reopen(self, item_id: str) -> None:
        self._require(item_id).status = "open"

    def query(self, filters: QueryFilters) -> list[Item]:
        out: list[Item] = []
        for rec in self._items.values():
            if filters.status is not None and rec.status != filters.status:
                continue
            if filters.label is not None and filters.label not in rec.labels:
                continue
            if filters.parent is not None and rec.parent != filters.parent:
                continue
            if filters.type is not None and rec.type != filters.type:
                continue
            out.append(self._snapshot(rec, lean=True))
        if filters.limit is not None:
            out = out[: filters.limit]
        return out

    def ready(self, label: str | None) -> list[Item]:
        return [
            self._snapshot(rec, lean=True)
            for rec in self._items.values()
            if rec.status == "open" and (label is None or label in rec.labels)
        ]

    def dep_mutate(self, op: DepOp, from_id: str, to_id: str, dep_type: str) -> None:
        rec = self._require(from_id)
        if op == "add":
            target = self._items.get(to_id)
            rec.deps.append(
                DepEdge(
                    id=to_id,
                    type=dep_type,
                    status=target.status if target is not None else "open",
                )
            )
        else:
            rec.deps = [d for d in rec.deps if not (d.id == to_id and d.type == dep_type)]

    def dep_list(self, item_id: str) -> DepListing:
        rec = self._require(item_id)
        dependents = [
            DepEdge(id=other.id, type=edge.type, status=other.status)
            for other in self._items.values()
            for edge in other.deps
            if edge.id == item_id
        ]
        return DepListing(depends_on=list(rec.deps), dependents=dependents)

    def label_mutate(self, op: str, item_id: str, labels: Sequence[str]) -> None:
        rec = self._require(item_id)
        if op == "add":
            for label in labels:
                if label not in rec.labels:
                    rec.labels.append(label)
        elif op == "remove":
            rec.labels = [label for label in rec.labels if label not in labels]
        else:
            raise WorkError(ErrorCode.USAGE, f"unknown label op: {op}")

    def labels(self, item_id: str) -> list[str]:
        return list(self._require(item_id).labels)

    def search(self, query: str) -> list[Item]:
        return [
            self._snapshot(rec, lean=True) for rec in self._items.values() if query in rec.title
        ]

    def sync(self, pull: bool) -> SyncResult:
        return SyncResult(synced=True, mode="pull" if pull else "push")
