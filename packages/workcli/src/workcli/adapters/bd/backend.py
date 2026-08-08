"""BdBackend: the `Backend` protocol's bd implementation, over a `BdRunner`.

All `Backend` protocol primitives are wired here: `capabilities`, `get`,
`batch_get`, `query`, `ready`, `search`, `create`, `set_fields`,
`append_note`, `close`, `reopen`, `dep_mutate`, `dep_list`, `label_mutate`,
`labels`, and `sync`.

`ready`/`search` parse through the same `parse_items` the `list`/`show`
adapters use, on the assumption bd emits the same per-item shape for all four
read commands. No golden fixture captures `bd ready`/`bd search` output
specifically -- only `show`/`list`/`dep list`/`label list` were golden-
captured -- an actual shape difference surfaces as `E_BACKEND_DRIFT` rather
than a silent misparse, same as any other unrecognized bd shape.

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
from workcli.backend import Capabilities, DepOp, ReadySupport, SyncSupport
from workcli.envelope import ErrorCode, JsonValue, StepProgress, WorkError, with_progress
from workcli.model import (
    SEARCH_FIELDS,
    CreateFields,
    DepListing,
    Item,
    QueryFilters,
    SearchFilters,
    SyncResult,
    UpdateFields,
)

# The backend's substring filter for each searchable field other than the
# title, which has a command of its own (see `BdBackend._search_legs`).
_TEXT_FILTER_FLAGS = {"description": "--desc-contains", "notes": "--notes-contains"}

# Every leg of one search is parsed at the disclosure the weakest leg can
# support, so a single result set never mixes disclosure levels: a consumer
# reading `unknown_relations` off the first item would otherwise generalize
# it to the rest and take an unknown parent for an absent one. The leg that
# reads titles reports no relationship at all, so it sets the floor.
_SEARCH_DISCLOSURE = "search"

# Exact stderr wording per an orchestrator ruling, not a golden capture
# -- `bd dolt` is never run mutating against a real DB in this project. `bd
# dolt commit` with nothing pending, and `bd dolt pull` against a dirty
# working set, are asserted to log these substrings to stderr.
_NOTHING_TO_COMMIT_STDERR_MARKER = "nothing to commit"
_SYNC_BEHIND_STDERR_MARKER = "cannot merge with uncommitted changes"

# Speculative markers, not a golden capture -- and unlike
# _NOTHING_TO_COMMIT_STDERR_MARKER above, live-verified as currently
# unreachable: `bd label add`/`bd label remove` (bd 1.0.3, confirmed by
# running both commands twice against a scratch issue) exit 0 unconditionally
# on a repeat add/remove, with no stderr at all -- bd is already idempotent
# here without this adapter's help. This branch stays as defense-in-depth for
# a future bd version that starts erroring on a no-op label mutation (the
# contract hardening spec, "Multi-step mutation partial-progress", rule 1,
# requires the seam to absorb that outcome as success if it ever appears);
# the exact wording is a guess until a real error is captured.
_LABEL_ALREADY_PRESENT_STDERR_MARKER = "already has label"
_LABEL_ABSENT_STDERR_MARKER = "does not have label"


class BdBackend:
    def __init__(self, runner: BdRunner, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._runner = runner
        self._sleep = sleep

    @property
    def capabilities(self) -> Capabilities:
        # bd has native blocker semantics, typed dep edges, and dolt sync --
        # every capability is at its native corner.
        return Capabilities(
            ready=ReadySupport.NATIVE, sync=SyncSupport.NATIVE, supports_dep_write=True
        )

    def get(self, item_id: str) -> Item:
        return self.batch_get([item_id])[0]

    def batch_get(self, ids: Sequence[str]) -> list[Item]:
        if not ids:
            return []
        argv = ["show", *ids, "--json"]
        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(result)

        items = parse_items(result.stdout, command="show")

        by_id = {item.id: item for item in items}
        missing = [item_id for item_id in ids if item_id not in by_id]
        if missing:
            # bd's own quirk, per golden capture: `bd show a b --json`
            # exits 0 and silently omits any id it couldn't find, logging the
            # miss to stderr instead of failing the call. A partial hit must
            # not read as full success -- `data.items` must match the
            # request one-for-one.
            raise WorkError(
                ErrorCode.NOT_FOUND,
                f"no such item(s): {', '.join(missing)}",
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
        # The seam's "every status" is the absent filter; bd's listing spells
        # it as a flag of its own, exactly as the description/notes search
        # legs already ask for it.
        argv += ["--all"] if filters.status is None else ["--status", filters.status]
        if filters.label is not None:
            argv += ["--label", filters.label]
        if filters.parent is not None:
            argv += ["--parent", filters.parent]
        if filters.type is not None:
            argv += ["--type", filters.type]
        argv += ["--limit", str(filters.limit) if filters.limit is not None else "0"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(result)
        return parse_items(result.stdout, command="list")

    def ready(self, label: str | None) -> list[Item]:
        argv = ["ready", "--json"]
        if label is not None:
            argv += ["--label", label]
        argv += ["--limit", "0"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(result)
        return parse_items(result.stdout, command="ready")

    def _search_legs(self, filters: SearchFilters) -> list[list[str]]:
        """One backend read per requested field, in `SEARCH_FIELDS` order.

        The backend has no single call that answers "title OR description":
        its text filters intersect with its text query rather than union
        with it, and the query itself only ever reads titles (and ids).
        Composing the union is therefore this adapter's job -- a backend
        that could answer it in one call would implement `search` in one.
        Every leg is asked unbounded: the caller's bound belongs to the
        merged set, and a bound applied here would clip each field's matches
        before they were merged.
        """
        legs: list[list[str]] = []
        for field in SEARCH_FIELDS:
            if field not in filters.corpus:
                continue
            if field == "title":
                # The text-query command, which also matches on id -- which
                # is why this leg leads: an exact id is the sharpest thing a
                # caller can type. Its own default drops closed items, so
                # every status has to be asked for by name.
                leg = ["search", filters.query, "--json"]
                leg += ["--status", filters.status if filters.status is not None else "all"]
            else:
                # The listing command carries a substring filter per text
                # field, and spells "every status" as its own flag.
                leg = ["list", "--json", _TEXT_FILTER_FLAGS[field], filters.query]
                leg += ["--all"] if filters.status is None else ["--status", filters.status]
            legs.append([*leg, "--limit", "0"])
        return legs

    def search(self, filters: SearchFilters) -> list[Item]:
        merged: dict[str, Item] = {}
        for argv in self._search_legs(filters):
            result = run_with_retry(self._runner, argv, sleep=self._sleep)
            if result.returncode != 0:
                raise map_bd_failure(result)
            for item in parse_items(result.stdout, command=_SEARCH_DISCLOSURE):
                # First field to match sets an item's rank; a later leg
                # re-reporting it changes nothing.
                merged.setdefault(item.id, item)
        return list(merged.values())

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
            raise map_bd_failure(result)
        return parse_created_id(result.stdout)

    def _update_and_check(self, argv: list[str], *, retry_on_timeout: bool = True) -> None:
        result = run_with_retry(
            self._runner, argv, sleep=self._sleep, retry_on_timeout=retry_on_timeout
        )
        if result.returncode != 0:
            raise map_bd_failure(result)

    def set_fields(self, item_id: str, fields: UpdateFields) -> None:
        argv = ["update", item_id]
        if fields.title is not None:
            argv += ["--title", fields.title]
        if fields.priority is not None:
            argv += ["--priority", fields.priority]
        if fields.description is not None:
            argv += ["--description", fields.description]
        if fields.parent is not None:
            # bd's own reparent, verified against bd 1.0.3 to REPLACE: after
            # `update C --parent B`, C's only parent-child edge is to B, the
            # edge to the old parent is gone from both ends' `dep list`, and
            # the `parent` scalar agrees. One call, so no window exists in
            # which the item carries two parents.
            argv += ["--parent", fields.parent]

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
            raise map_bd_failure(result)

    def reopen(self, item_id: str) -> None:
        argv = ["reopen", item_id]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(result)

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
            raise map_bd_failure(result)

    def dep_list(self, item_id: str) -> DepListing:
        # bd's own `--direction` naming reads backward from intuition:
        # default ("down") = what this item depends on; "up" = what depends
        # on this item (confirmed against `bd dep list --help` and the
        # golden fixtures) -- named for the relationship here, never for
        # bd's own direction word, to kill that ambiguity permanently.
        down_argv = ["dep", "list", item_id, "--json"]
        down_result = run_with_retry(self._runner, down_argv, sleep=self._sleep)
        if down_result.returncode != 0:
            raise map_bd_failure(down_result)
        depends_on = parse_dep_edges(down_result.stdout, self_id=item_id, direction="depends-on")

        up_argv = ["dep", "list", item_id, "--direction", "up", "--json"]
        up_result = run_with_retry(self._runner, up_argv, sleep=self._sleep)
        if up_result.returncode != 0:
            raise map_bd_failure(up_result)
        dependents = parse_dep_edges(up_result.stdout, self_id=item_id, direction="dependents")

        return DepListing(depends_on=depends_on, dependents=dependents)

    def label_mutate(self, op: str, item_id: str, labels: Sequence[str]) -> None:
        # bd's own `label add`/`label remove` accept exactly one label per
        # invocation -- one bd call per label (orchestrator ruling). A
        # mid-sequence failure is wrapped with the labels already applied so
        # far (StepProgress) UNLESS nothing applied yet (the first label
        # failing stays a plain, unwrapped WorkError -- "absence means
        # atomic").
        idempotent_marker = (
            _LABEL_ALREADY_PRESENT_STDERR_MARKER if op == "add" else _LABEL_ABSENT_STDERR_MARKER
        )
        applied: list[str] = []
        for index, one_label in enumerate(labels):
            argv = ["label", op, item_id, one_label]

            def progress(
                err: WorkError, *, one_label: str = one_label, index: int = index
            ) -> WorkError:
                if not applied:
                    return err
                return with_progress(
                    err,
                    StepProgress(
                        operation="label_mutate",
                        steps_total=len(labels),
                        completed=tuple(applied),
                        failed=one_label,
                        remaining=tuple(labels[index + 1 :]),
                    ),
                )

            # `run_with_retry` itself raises `WorkError` on retry exhaustion
            # (E_TIMEOUT/E_LOCK_CONTENTION) rather than returning a result --
            # that path needs the same partial-progress wrap as a mapped
            # non-zero exit, or labels already applied before it go unreported.
            try:
                result = run_with_retry(self._runner, argv, sleep=self._sleep)
            except WorkError as exc:
                raise progress(exc) from exc
            if result.returncode != 0 and idempotent_marker not in result.stderr:
                raise progress(map_bd_failure(result))
            applied.append(one_label)

    def labels(self, item_id: str) -> list[str]:
        argv = ["label", "list", item_id, "--json"]

        result = run_with_retry(self._runner, argv, sleep=self._sleep)
        if result.returncode != 0:
            raise map_bd_failure(result)
        return parse_labels(result.stdout)

    def sync(self, pull: bool) -> SyncResult:
        if pull:
            argv = ["dolt", "pull"]
            result = run_with_retry(self._runner, argv, sleep=self._sleep)
            if result.returncode != 0:
                if _SYNC_BEHIND_STDERR_MARKER in result.stderr:
                    raise WorkError(
                        ErrorCode.SYNC_BEHIND,
                        "cannot pull: the local working copy has uncommitted changes; "
                        "sync them first",
                    )
                raise map_bd_failure(result)
            return SyncResult(synced=True, mode="pull")

        commit_argv = ["dolt", "commit"]
        commit_result = run_with_retry(self._runner, commit_argv, sleep=self._sleep)
        if (
            commit_result.returncode != 0
            and _NOTHING_TO_COMMIT_STDERR_MARKER not in commit_result.stderr
        ):
            raise map_bd_failure(commit_result)

        def push_progress(err: WorkError) -> WorkError:
            return with_progress(
                err,
                StepProgress(
                    operation="sync",
                    steps_total=2,
                    completed=("commit",),
                    failed="push",
                    remaining=(),
                ),
            )

        push_argv = ["dolt", "push"]
        # As above: `run_with_retry` raising WorkError on retry exhaustion
        # needs the same partial-progress wrap -- the commit already
        # succeeded by the time push is attempted.
        try:
            push_result = run_with_retry(self._runner, push_argv, sleep=self._sleep)
        except WorkError as exc:
            raise push_progress(exc) from exc
        if push_result.returncode != 0:
            err = push_progress(map_bd_failure(push_result))
            raise err
        return SyncResult(synced=True, mode="push")
