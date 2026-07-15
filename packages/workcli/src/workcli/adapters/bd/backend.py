"""BdBackend: the `Backend` protocol's bd implementation, over a `BdRunner`.

All `Backend` protocol primitives are wired here: `capabilities`, `get`,
`batch_get`, `query`, `ready`, `search`, `create`, `set_fields`,
`append_note`, `close`, `reopen`, `dep_mutate`, `dep_list`, `label_mutate`,
`labels`, and `sync`.

`ready`/`search` parse through the same `parse_items` the `list`/`show`
adapters use, on the assumption bd emits the same per-item shape for all four
read commands. No golden fixture captures `bd ready`/`bd search` output
specifically (decision 14 only captured `show`/`list`/`dep list`/`label
list`) -- an actual shape difference surfaces as `E_BACKEND_DRIFT` rather than
a silent misparse, same as any other unrecognized bd shape.

`create`'s output shape (a single JSON object, not an array -- see
`adapters/bd/parse.py::parse_created_id`) was confirmed by reading bd's own
source (`outputJSON(issue)` in `cmd/bd/create.go`), never by running a
mutating `bd create` in this repo. `set_fields`/`append_note`/`close`/
`reopen` never pass `--json`: none of them need to parse stdout (they either
return nothing or, for `create`, only the new id), so the only signal that
matters is the exit code and stderr that `map_bd_failure` already handles.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import cast

from workcli.adapters.bd.parse import (
    map_bd_failure,
    parse_created_id,
    parse_dep_edges,
    parse_items,
    parse_labels,
)
from workcli.adapters.bd.retry import run_with_retry
from workcli.adapters.bd.runner import BdRunner
from workcli.backend import Capabilities, DepOp
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import CreateFields, DepListing, Item, QueryFilters, SyncResult, UpdateFields

# Decision 9's exact stderr wording (orchestrator ruling, not a golden capture
# -- `bd dolt` is never run mutating against a real DB in this project): `bd
# dolt commit` with nothing pending, and `bd dolt pull` against a dirty
# working set, are asserted to log these substrings to stderr.
_NOTHING_TO_COMMIT_STDERR_MARKER = "nothing to commit"
_SYNC_BEHIND_STDERR_MARKER = "cannot merge with uncommitted changes"


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
        if not ids:
            return []
        argv = ["show", *ids, "--json"]
        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

        items = parse_items(result.stdout, command="show")

        by_id = {item.id: item for item in items}
        missing = [item_id for item_id in ids if item_id not in by_id]
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
        # bd's own output order for `show a b --json` is never asserted to
        # match argv order -- the `Backend` protocol's contract promises
        # request order regardless (a duplicated requested id maps to the
        # same item at each position), so callers may positionally unpack a
        # `batch_get` result rather than re-searching it by id.
        return [by_id[item_id] for item_id in ids]

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

    def create(self, fields: CreateFields) -> str:
        argv = ["create", "--json", "--title", fields.title]
        if fields.description is not None:
            argv += ["--description", fields.description]
        if fields.type is not None:
            argv += ["--type", fields.type]
        if fields.priority is not None:
            argv += ["--priority", fields.priority]
        if fields.parent is not None:
            # bd copies the parent's CURRENT labels onto a --parent child by
            # default (verified against bd 1.0.3), which leaks transient
            # handles like `creating-spec` onto freshly-minted children. The
            # Backend contract is "the created item carries exactly the
            # requested labels", so every parented create opts out.
            argv += ["--parent", fields.parent, "--no-inherit-labels"]
        if fields.labels:
            argv += ["--labels", ",".join(fields.labels)]
        if fields.acceptance is not None:
            argv += ["--acceptance", fields.acceptance]
        if fields.blocked_by is not None:
            # bare id = "new depends on / blocked by <id>"; bd's `blocks:<id>`
            # form is the REVERSE (new blocks id) -- verified against live bd.
            argv += ["--deps", fields.blocked_by]

        result = run_with_retry(self._runner, argv, sleep=self._sleep, retry_on_timeout=False)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)
        return parse_created_id(result.stdout)

    def _update_and_check(self, argv: list[str], *, retry_on_timeout: bool = True) -> None:
        result = run_with_retry(
            self._runner, argv, sleep=self._sleep, retry_on_timeout=retry_on_timeout
        )
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

    def set_fields(self, item_id: str, fields: UpdateFields) -> None:
        argv = ["update", item_id]
        if fields.title is not None:
            argv += ["--title", fields.title]
        if fields.priority is not None:
            argv += ["--priority", fields.priority]
        if fields.description is not None:
            argv += ["--description", fields.description]

        self._update_and_check(argv)

    def claim(self, item_id: str) -> None:
        self._update_and_check(["update", item_id, "--claim"])

    def set_status(self, item_id: str, status: str) -> None:
        self._update_and_check(["update", item_id, "--status", status])

    def set_type(self, item_id: str, item_type: str) -> None:
        self._update_and_check(["update", item_id, "--type", item_type])

    def set_acceptance(self, item_id: str, text: str) -> None:
        self._update_and_check(["update", item_id, "--acceptance", text])

    def append_note(self, item_id: str, text: str) -> None:
        self._update_and_check(["update", item_id, "--append-notes", text], retry_on_timeout=False)

    def close(self, ids: Sequence[str]) -> None:
        argv = ["close", *ids]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

    def reopen(self, item_id: str) -> None:
        argv = ["reopen", item_id]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

    def dep_mutate(self, op: DepOp, from_id: str, to_id: str, dep_type: str) -> None:
        if op == "add":
            argv = ["dep", "add", from_id, to_id, "--type", dep_type]
        elif op == "remove":
            # bd's own `dep remove` takes no `--type` flag at all (see
            # `bd dep remove --help`).
            argv = ["dep", "remove", from_id, to_id]
        else:
            # A contract violation, not a bd-shape concern: an `op` outside
            # {"add", "remove"} must fail loud here rather than silently
            # falling through to the destructive `dep remove` branch
            # (Finding 2). The cli's E_INTERNAL guard turns this into an
            # envelope at the CLI boundary.
            raise ValueError(f"impossible dep op: {op!r}")

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)

    def dep_list(self, item_id: str) -> DepListing:
        # bd's own `--direction` naming reads backward from intuition:
        # default ("down") = what this item depends on; "up" = what depends
        # on this item (confirmed against `bd dep list --help` and the
        # golden fixtures) -- named for the relationship here, never for
        # bd's own direction word, to kill that ambiguity permanently.
        down_argv = ["dep", "list", item_id, "--json"]
        down_result = run_with_retry(self._runner, down_argv, sleep=self._sleep)
        if down_result.returncode != 0:
            raise map_bd_failure(down_argv, down_result)
        depends_on = parse_dep_edges(down_result.stdout, self_id=item_id, command="dep list")

        up_argv = ["dep", "list", item_id, "--direction", "up", "--json"]
        up_result = run_with_retry(self._runner, up_argv, sleep=self._sleep)
        if up_result.returncode != 0:
            raise map_bd_failure(up_argv, up_result)
        dependents = parse_dep_edges(
            up_result.stdout, self_id=item_id, command="dep list --direction up"
        )

        return DepListing(depends_on=depends_on, dependents=dependents)

    def label_mutate(self, op: str, item_id: str, labels: Sequence[str]) -> None:
        # bd's own `label add`/`label remove` accept exactly one label per
        # invocation -- one bd call per label (orchestrator ruling).
        for one_label in labels:
            argv = ["label", op, item_id, one_label]
            result = run_with_retry(self._runner, argv, sleep=self._sleep)
            if result.returncode != 0:
                raise map_bd_failure(argv, result)

    def labels(self, item_id: str) -> list[str]:
        argv = ["label", "list", item_id, "--json"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(argv, result)
        return parse_labels(result.stdout)

    def sync(self, pull: bool) -> SyncResult:
        if pull:
            argv = ["dolt", "pull"]
            result = run_with_retry(self._runner, argv, sleep=self._sleep)
            if result.returncode != 0:
                if _SYNC_BEHIND_STDERR_MARKER in result.stderr:
                    raise WorkError(
                        ErrorCode.SYNC_BEHIND,
                        "bd dolt pull: local working set has uncommitted changes",
                        detail={"argv": cast("list[JsonValue]", list(argv))},
                    )
                raise map_bd_failure(argv, result)
            return SyncResult(synced=True, mode="pull")

        commit_argv = ["dolt", "commit"]
        commit_result = run_with_retry(self._runner, commit_argv, sleep=self._sleep)
        if (
            commit_result.returncode != 0
            and _NOTHING_TO_COMMIT_STDERR_MARKER not in commit_result.stderr
        ):
            raise map_bd_failure(commit_argv, commit_result)

        push_argv = ["dolt", "push"]
        push_result = run_with_retry(self._runner, push_argv, sleep=self._sleep)
        if push_result.returncode != 0:
            raise map_bd_failure(push_argv, push_result)
        return SyncResult(synced=True, mode="push")
