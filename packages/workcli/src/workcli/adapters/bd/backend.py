"""BdBackend: the `Backend` protocol's bd implementation, over a `BdRunner`.

Read primitives are wired (`capabilities`, `get`, `batch_get`, `query`,
`ready`, `search`); write/relation/sync primitives (`create`, `set_fields`,
`append_note`, `close`, `reopen`, `dep_mutate`, `dep_list`, `label_mutate`,
`labels`, `sync`) raise `NotImplementedError` below as placeholders, so this
concrete class satisfies the `Backend` Protocol structurally (required for
`cli.py`'s `handler(backend, args)` dispatch to type-check under `mypy
--strict`) ahead of the tasks that give each one a real body.

`ready`/`search` parse through the same `parse_items` the `list`/`show`
adapters use, on the assumption bd emits the same per-item shape for all four
read commands. No golden fixture captures `bd ready`/`bd search` output
specifically (decision 14 only captured `show`/`list`/`dep list`/`label
list`) -- an actual shape difference surfaces as `E_BACKEND_DRIFT` rather than
a silent misparse, same as any other unrecognized bd shape.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import cast

from workcli.adapters.bd.parse import map_bd_failure, parse_items
from workcli.adapters.bd.retry import run_with_retry
from workcli.adapters.bd.runner import BdRunner
from workcli.backend import Capabilities
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import CreateFields, DepListing, Item, QueryFilters, SyncResult, UpdateFields


class BdBackend:
    def __init__(self, runner: BdRunner, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._runner = runner
        self._sleep = sleep

    @property
    def capabilities(self) -> Capabilities:
        # bd has native blocker semantics, typed dep edges, and dolt sync --
        # every capability flag is true.
        return Capabilities(supports_ready=True, supports_dep_types=True, supports_sync=True)

    def get(self, item_id: str) -> Item:
        return self.batch_get([item_id])[0]

    def batch_get(self, ids: Sequence[str]) -> list[Item]:
        argv = ["show", *ids, "--json"]
        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

        items = parse_items(result.stdout, command="show")

        returned_ids = {item.id for item in items}
        missing = [item_id for item_id in ids if item_id not in returned_ids]
        if missing:
            # bd's own quirk (decision 14 golden capture): `bd show a b --json`
            # exits 0 and silently omits any id it couldn't find, logging the
            # miss to stderr instead of failing the call. A partial hit must
            # not read as full success (decision 10 needs `data.items` to
            # match the request one-for-one).
            raise WorkError(
                ErrorCode.NOT_FOUND,
                f"bd show: no such item(s): {', '.join(missing)}",
                detail={"missing": cast("list[JsonValue]", missing)},
            )
        return items

    def query(self, filters: QueryFilters) -> list[Item]:
        argv = ["list", "--json"]
        if filters.status is not None:
            argv += ["--status", filters.status]
        if filters.label is not None:
            argv += ["--label", filters.label]
        if filters.parent is not None:
            argv += ["--parent", filters.parent]
        if filters.type is not None:
            argv += ["--type", filters.type]
        argv += ["--limit", str(filters.limit) if filters.limit is not None else "0"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)
        return parse_items(result.stdout, command="list")

    def ready(self, label: str | None) -> list[Item]:
        argv = ["ready", "--json"]
        if label is not None:
            argv += ["--label", label]
        argv += ["--limit", "0"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)
        return parse_items(result.stdout, command="ready")

    def search(self, query: str) -> list[Item]:
        argv = ["search", query, "--json"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)
        return parse_items(result.stdout, command="search")

    # -- Not yet wired: write verbs (Task 4) and relations/sync (Task 5) --

    def create(self, fields: CreateFields) -> str:  # pragma: no cover -- Task 4
        raise NotImplementedError

    def set_fields(self, item_id: str, fields: UpdateFields) -> None:  # pragma: no cover
        raise NotImplementedError  # Task 4

    def append_note(self, item_id: str, text: str) -> None:  # pragma: no cover
        raise NotImplementedError  # Task 4

    def close(self, ids: Sequence[str]) -> None:  # pragma: no cover -- Task 4
        raise NotImplementedError

    def reopen(self, item_id: str) -> None:  # pragma: no cover -- Task 4
        raise NotImplementedError

    def dep_mutate(
        self, op: str, from_id: str, to_id: str, dep_type: str
    ) -> None:  # pragma: no cover
        raise NotImplementedError  # Task 5

    def dep_list(self, item_id: str) -> DepListing:  # pragma: no cover -- Task 5
        raise NotImplementedError

    def label_mutate(
        self, op: str, item_id: str, labels: Sequence[str]
    ) -> None:  # pragma: no cover
        raise NotImplementedError  # Task 5

    def labels(self, item_id: str) -> list[str]:  # pragma: no cover -- Task 5
        raise NotImplementedError

    def sync(self, pull: bool) -> SyncResult:  # pragma: no cover -- Task 5
        raise NotImplementedError
