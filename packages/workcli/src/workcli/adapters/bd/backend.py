"""BdBackend: the `Backend` protocol's bd implementation, over a `BdRunner`.

Task 2 wires the read primitives only (`capabilities`, `get`, `batch_get`,
`query`); write/relation/sync primitives land in Tasks 3-5, alongside the
verbs that are their only callers.
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
from workcli.model import Item, QueryFilters


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
