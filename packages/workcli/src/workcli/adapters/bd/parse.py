"""bd JSON shape parsing + the drift alarm.

bd's `--json` stdout is the facade's only contract with the real bd binary;
this module is the single place that turns bd's raw, occasionally
inconsistent shapes into workcli's normalized `Item`/`DepEdge` model. Any
shape bd emits that this module cannot map raises `WorkError(BACKEND_DRIFT)`
-- bd's own model of itself broke, and silently guessing is worse than
alarming loudly (spec test-plan item 9).

Two known shape inconsistencies this module bridges (found capturing the
golden fixtures, not documented anywhere in bd's `--help`):

- `bd show`'s embedded `dependencies[]`/`dependents[]` entries are full
  embedded beads plus a `dependency_type` field (the OTHER bead's `id` and
  `status` are directly present). `bd list`'s embedded `dependencies[]`
  entries are raw edge rows (`issue_id`, `depends_on_id`, `type`) with no
  `status` for the other end at all.
- `bd show` exposes no `children` key; children are recovered by filtering
  `dependents[]` down to `dependency_type == "parent-child"`. `bd list`
  exposes no `dependents` key at all, so query()-sourced Items always have
  `children == []`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import DepEdge, Item

_REQUIRED_ITEM_KEYS = ("id", "title", "issue_type", "status", "priority")

# Confirmed against the real bd binary (decision 14 golden capture): a
# not-found `show` logs this exact wording to stderr per missing id, even
# though the overall process may still exit 0 if other requested ids matched
# (see BdBackend.batch_get's own missing-id reconciliation for that case).
_NOT_FOUND_STDERR_MARKER = "no issue found matching"

# Confirmed by reading bd's own Go source at the installed binary's commit:
# internal/storage/issueops/dependencies.go emits "epics can only block
# other epics, not tasks" / "tasks can only block other tasks, not epics"
# for the cross-type wall, and "adding dependency would create a cycle" for
# the recursive-CTE cycle check. These are a safety net for a wall/cycle the
# verb layer's own pre-check can't see (e.g. a stale read) -- `dep_mutate`'s
# call is what can actually reach them.
_TYPE_WALL_STDERR_MARKER = "can only block"
_DEP_CYCLE_STDERR_MARKER = "would create a cycle"


def _drift(message: str, detail: dict[str, JsonValue]) -> WorkError:
    return WorkError(ErrorCode.BACKEND_DRIFT, message, detail=detail)


def _load_json_array(stdout: str, *, command: str) -> list[Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise _drift(
            f"bd {command} produced non-JSON stdout: {exc}",
            {"reason": "invalid_json", "raw_excerpt": stdout[:200]},
        ) from exc
    if not isinstance(parsed, list):
        raise _drift(
            f"bd {command} produced a non-array JSON payload",
            {"reason": "not_an_array", "raw_type": type(parsed).__name__},
        )
    return parsed


def _dep_edge_from_raw(entry: dict[str, JsonValue], self_id: str) -> DepEdge:
    if "dependency_type" in entry:
        # show-shape: full embedded bead + dependency_type; id/status
        # describe the OTHER end of the edge directly. A drifted bd omitting
        # `id` here must alarm loudly (spec test-plan item 9), not raise a
        # raw KeyError that surfaces as E_INTERNAL.
        if "id" not in entry:
            raise _drift(
                "bd dependency edge (show-shape) is missing required key: id",
                {
                    "reason": "missing_edge_keys",
                    "shape": "show",
                    "missing_keys": cast("list[JsonValue]", ["id"]),
                    "self_id": self_id,
                },
            )
        return DepEdge(
            id=str(entry["id"]),
            type=_dep_type(entry, self_id),
            status=str(entry.get("status", "")),
        )
    # list-shape: raw edge row {issue_id, depends_on_id, type}; no status
    # for the other end is available without a second fetch. Same drift
    # discipline: a missing edge key alarms rather than raising KeyError.
    missing = [key for key in ("issue_id", "depends_on_id", "type") if key not in entry]
    if missing:
        raise _drift(
            f"bd dependency edge (list-shape) is missing required key(s): {', '.join(missing)}",
            {
                "reason": "missing_edge_keys",
                "shape": "list",
                "missing_keys": cast("list[JsonValue]", missing),
                "self_id": self_id,
            },
        )
    other_id = entry["depends_on_id"] if entry.get("issue_id") == self_id else entry["issue_id"]
    return DepEdge(id=str(other_id), type=_dep_type(entry, self_id), status="")


def _dep_type(entry: dict[str, JsonValue], item_id: str) -> str:
    """Return the edge's type, preferring `dependency_type` then `type`.

    Same null-vs-absent discipline as `_list_field`: an explicit JSON `null`
    on whichever key is present is bd model drift and must alarm loudly, not
    silently fall through to the other key or coerce to the literal string
    "None".
    """
    for key in ("dependency_type", "type"):
        if key in entry:
            value = entry[key]
            if value is None:
                raise _drift(
                    f"bd dependency edge's {key} field is null, expected a string",
                    {"reason": "null_field", "field": key, "id": item_id},
                )
            return str(value)
    return str(None)


def _list_field(raw: dict[str, JsonValue], key: str, item_id: str) -> list[Any]:
    """Return `raw[key]` as a list, defaulting an absent key to `[]`.

    An explicit JSON `null` is NOT the same as a missing key: bd emitting
    `null` where the facade's model says the field is an array is itself
    model drift (spec test-plan item 9) -- it must alarm loudly via
    `WorkError(BACKEND_DRIFT)`, never silently coerce to `[]` and never
    raise a raw `AssertionError`/`TypeError` from an unguarded downstream
    `isinstance`/iteration.
    """
    if key not in raw:
        return []
    value = raw[key]
    if value is None:
        raise _drift(
            f"bd item's {key} field is null, expected an array",
            {"reason": "null_field", "field": key, "id": item_id},
        )
    if not isinstance(value, list):
        raise _drift(
            f"bd item's {key} field is not an array",
            {"reason": "unexpected_field_type", "field": key, "id": item_id},
        )
    return value


def _string_field(
    raw: dict[str, JsonValue], key: str, item_id: str, *, default: str | None = None
) -> str:
    """Return `raw[key]` as a `str`, applying the same null-vs-absent discipline

    as `_list_field`: an explicit JSON `null` is bd model drift and must
    alarm via `WorkError(BACKEND_DRIFT)`, never silently coerce to the
    literal string "None". An absent key returns `default` when given
    (callers pass `default=None` -- Python's default -- only for keys whose
    presence is already guaranteed by `_REQUIRED_ITEM_KEYS`).
    """
    if key not in raw:
        if default is not None:
            return default
        raise _drift(
            f"bd item is missing required key: {key}",
            {
                "reason": "missing_required_keys",
                "missing_keys": cast("list[JsonValue]", [key]),
                "id": item_id,
            },
        )
    value = raw[key]
    if value is None:
        raise _drift(
            f"bd item's {key} field is null, expected a string",
            {"reason": "null_field", "field": key, "id": item_id},
        )
    return str(value)


def _string_list_field(raw: dict[str, JsonValue], key: str, item_id: str) -> list[str]:
    """Return `raw[key]` as a `list[str]`, alarming on any non-string element.

    Layers per-element string validation on top of `_list_field` (absent ->
    `[]`, null/non-array -> drift). The normalized contract types this field
    as a `string[]`; a non-string element (a number, an object, ...) is bd
    model drift, not something to silently coerce with `str()` (spec
    test-plan item 9) -- the same discipline `parse_labels` applies to the
    `label list` command.
    """
    values = _list_field(raw, key, item_id)
    for value in values:
        if not isinstance(value, str):
            raise _drift(
                f"bd item's {key} field contains a non-string element",
                {
                    "reason": "non_string_list_element",
                    "field": key,
                    "id": item_id,
                    "raw_type": type(value).__name__,
                },
            )
    return values


def _assert_object_elements(entries: list[Any], *, field: str, item_id: str) -> None:
    """Alarm on any `dependencies`/`dependents` element that isn't a JSON object.

    `_dep_edge_from_raw` requires a mapping; a non-object edge entry (bd
    emitting a bare string/number where every known edge shape is an object)
    was previously filtered out silently by an `isinstance(entry, dict)`
    guard at the call site, dropping the edge and continuing with a
    partially-mangled Item. That is bd shape drift, not something to drop and
    carry on from (spec test-plan item 9) -- same discipline as
    `parse_items`'/`parse_dep_edges`' own `element_not_an_object` check.
    """
    for entry in entries:
        if not isinstance(entry, dict):
            raise _drift(
                f"bd item's {field} entry is not a JSON object",
                {
                    "reason": "element_not_an_object",
                    "field": field,
                    "id": item_id,
                    "raw_type": type(entry).__name__,
                },
            )


def parse_item(raw: dict[str, JsonValue]) -> Item:
    missing = [key for key in _REQUIRED_ITEM_KEYS if key not in raw]
    if missing:
        raise _drift(
            f"bd item is missing required key(s): {', '.join(missing)}",
            {
                "reason": "missing_required_keys",
                "missing_keys": cast("list[JsonValue]", missing),
                "id": raw.get("id"),
            },
        )

    item_id = str(raw["id"])
    priority_raw = raw["priority"]
    if not isinstance(priority_raw, int):
        raise _drift(
            "bd item's priority field is not an integer",
            {"reason": "unexpected_priority_type", "id": item_id, "priority": priority_raw},
        )

    dependencies = _list_field(raw, "dependencies", item_id)
    dependents = _list_field(raw, "dependents", item_id)
    _assert_object_elements(dependencies, field="dependencies", item_id=item_id)
    _assert_object_elements(dependents, field="dependents", item_id=item_id)

    deps = [
        _dep_edge_from_raw(entry, item_id)
        for entry in dependencies
        if _dep_type(entry, item_id) != "parent-child"
    ]
    children = [
        _dep_edge_from_raw(entry, item_id).id
        for entry in dependents
        if _dep_type(entry, item_id) == "parent-child"
    ]

    return Item(
        id=item_id,
        title=str(raw["title"]),
        type=str(raw["issue_type"]),
        status=_string_field(raw, "status", item_id),
        priority=f"P{priority_raw}",
        labels=_string_list_field(raw, "labels", item_id),
        parent=str(raw["parent"]) if raw.get("parent") is not None else None,
        deps=deps,
        children=children,
        description=_string_field(raw, "description", item_id, default=""),
        notes=_string_field(raw, "notes", item_id, default=""),
        created=str(raw["created_at"]) if raw.get("created_at") is not None else None,
        updated=str(raw["updated_at"]) if raw.get("updated_at") is not None else None,
    )


def parse_items(stdout: str, *, command: str = "show") -> list[Item]:
    raw_items = _load_json_array(stdout, command=command)
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise _drift(
                f"bd {command} array element is not a JSON object",
                {"reason": "element_not_an_object", "raw_type": type(raw).__name__},
            )
        items.append(parse_item(raw))
    return items


def parse_created_id(stdout: str, *, command: str = "create") -> str:
    """Extract the new item's id from `bd create --json` output.

    Unlike show/list/ready/search (which emit a JSON array of items), `bd
    create --json` emits a single JSON *object* -- the created issue, with a
    `schema_version` key injected inline (confirmed against the bd source:
    `outputJSON(issue)` in cmd/bd/create.go, legacy non-envelope-mode
    wrapping). `Backend.create`'s contract only needs the new id, so this
    parser is deliberately narrow: a payload that isn't an object, or has no
    non-empty string `id`, is the same alarm class as any other unrecognized
    bd shape.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise _drift(
            f"bd {command} produced non-JSON stdout: {exc}",
            {"reason": "invalid_json", "raw_excerpt": stdout[:200]},
        ) from exc
    if not isinstance(parsed, dict):
        raise _drift(
            f"bd {command} produced a non-object JSON payload",
            {"reason": "not_an_object", "raw_type": type(parsed).__name__},
        )
    item_id = parsed.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise _drift(
            f"bd {command} payload is missing a non-empty string `id`",
            {"reason": "missing_id", "raw_keys": cast("list[JsonValue]", list(parsed.keys()))},
        )
    return item_id


def parse_dep_edges(stdout: str, *, self_id: str, command: str = "dep list") -> list[DepEdge]:
    """Parse `bd dep list --json`'s flat array into lean `DepEdge`s.

    Unlike `show`/`list` (arrays of full items), `bd dep list --json` emits a
    flat array of edge records: each entry IS the full embedded bead at the
    other end of the edge, plus a top-level `dependency_type` field --
    exactly the `show`-shape branch of `_dep_edge_from_raw` (golden fixtures
    `bd_dep_list_down.json`/`bd_dep_list_up.json` confirm this; bd never
    emits the list-shape raw edge row for this command). A record missing
    `dependency_type` is an unrecognized shape, not a silent guess.
    """
    raw_entries = _load_json_array(stdout, command=command)
    edges = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise _drift(
                f"bd {command} array element is not a JSON object",
                {"reason": "element_not_an_object", "raw_type": type(raw).__name__},
            )
        if "dependency_type" not in raw or "id" not in raw:
            raise _drift(
                f"bd {command} record is missing dependency_type/id",
                {"reason": "missing_required_keys", "raw_keys": cast("list[JsonValue]", list(raw))},
            )
        edges.append(_dep_edge_from_raw(raw, self_id))
    return edges


def parse_labels(stdout: str, *, command: str = "label list") -> list[str]:
    raw_labels = _load_json_array(stdout, command=command)
    for label in raw_labels:
        if not isinstance(label, str):
            raise _drift(
                f"bd {command} array element is not a string",
                {"reason": "label_not_a_string", "raw_type": type(label).__name__},
            )
    return raw_labels


def map_bd_failure(argv: Sequence[str], result: BdResult) -> WorkError:
    """Translate a nonzero bd exit into a typed error (decision 4).

    NOT_FOUND, TYPE_WALL, and DEP_CYCLE are mapped here; anything this
    function doesn't recognize is the same alarm class as an unparseable
    shape -- the facade's model of bd broke. TYPE_WALL/DEP_CYCLE are a
    fallback safety net only: `dep`'s verb layer pre-checks the type wall
    via two `Backend.get` reads before ever calling `dep_mutate`, so a live
    bd instance should never actually surface these to this function -- but
    a pre-check race (a stale read) is still a bd failure, not a crash.
    """
    if _NOT_FOUND_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.NOT_FOUND,
            "bd reported no matching issue",
            detail={"argv": list(argv), "stderr": result.stderr.strip()},
        )
    if _TYPE_WALL_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.TYPE_WALL,
            "bd rejected a cross-type dependency",
            detail={"argv": list(argv), "stderr": result.stderr.strip()},
        )
    if _DEP_CYCLE_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.DEP_CYCLE,
            "bd rejected a dependency that would create a cycle",
            detail={"argv": list(argv), "stderr": result.stderr.strip()},
        )
    return _drift(
        f"bd exited {result.returncode} with an unrecognized failure",
        {
            "argv": cast("list[JsonValue]", list(argv)),
            "returncode": result.returncode,
            "stderr": result.stderr[:500],
        },
    )
