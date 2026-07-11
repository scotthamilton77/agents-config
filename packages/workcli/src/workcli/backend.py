"""The Backend seam: one protocol per the verb set's primitive needs.

The verb layer owns normalization, typed errors, and retries; adapters own
only backend I/O and concept mapping (spec section 6). v1 ships the bd
adapter (`adapters/bd/backend.py`) alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from workcli.model import CreateFields, DepListing, Item, QueryFilters, SyncResult, UpdateFields

DepOp = Literal["add", "remove"]


@dataclass(frozen=True)
class Capabilities:
    supports_ready: bool
    supports_dep_types: bool
    supports_sync: bool


class Backend(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...  # pragma: no cover
    def get(self, item_id: str) -> Item: ...  # pragma: no cover
    def batch_get(self, ids: Sequence[str]) -> list[Item]:
        """Return items in the same order as `ids` (a duplicated id maps to the same item)."""
        ...  # pragma: no cover

    def create(self, fields: CreateFields) -> str: ...  # returns new item id  # pragma: no cover
    def set_fields(self, item_id: str, fields: UpdateFields) -> None: ...  # pragma: no cover
    def append_note(self, item_id: str, text: str) -> None: ...  # pragma: no cover
    def close(self, ids: Sequence[str]) -> None: ...  # pragma: no cover
    def reopen(self, item_id: str) -> None: ...  # pragma: no cover
    def query(self, filters: QueryFilters) -> list[Item]: ...  # pragma: no cover
    def ready(self, label: str | None) -> list[Item]: ...  # pragma: no cover
    def dep_mutate(
        self, op: DepOp, from_id: str, to_id: str, dep_type: str
    ) -> None: ...  # pragma: no cover
    def dep_list(self, item_id: str) -> DepListing: ...  # pragma: no cover
    def label_mutate(
        self, op: str, item_id: str, labels: Sequence[str]
    ) -> None: ...  # pragma: no cover
    def labels(self, item_id: str) -> list[str]: ...  # pragma: no cover
    def search(self, query: str) -> list[Item]: ...  # pragma: no cover
    def sync(self, pull: bool) -> SyncResult: ...  # pragma: no cover
