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
        # describe the OTHER end of the edge directly.
        return DepEdge(
            id=str(entry["id"]),
            type=str(entry["dependency_type"]),
            status=str(entry.get("status", "")),
        )
    # list-shape: raw edge row {issue_id, depends_on_id, type}; no status
    # for the other end is available without a second fetch.
    other_id = entry["depends_on_id"] if entry.get("issue_id") == self_id else entry["issue_id"]
    return DepEdge(id=str(other_id), type=str(entry["type"]), status="")


def _dep_type(entry: dict[str, JsonValue]) -> str:
    dep_type = entry.get("dependency_type", entry.get("type"))
    return str(dep_type)


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

    dependencies = raw.get("dependencies", [])
    dependents = raw.get("dependents", [])
    assert isinstance(dependencies, list)  # noqa: S101 -- narrows JsonValue for mypy
    assert isinstance(dependents, list)  # noqa: S101

    deps = [
        _dep_edge_from_raw(entry, item_id)
        for entry in dependencies
        if isinstance(entry, dict) and _dep_type(entry) != "parent-child"
    ]
    children = [
        str(entry["id"])
        for entry in dependents
        if isinstance(entry, dict) and _dep_type(entry) == "parent-child"
    ]

    return Item(
        id=item_id,
        title=str(raw["title"]),
        type=str(raw["issue_type"]),
        status=str(raw["status"]),
        priority=f"P{priority_raw}",
        labels=[str(label) for label in raw.get("labels", [])],  # type: ignore[union-attr]
        parent=str(raw["parent"]) if raw.get("parent") is not None else None,
        deps=deps,
        children=children,
        description=str(raw.get("description", "")),
        notes=str(raw.get("notes", "")),
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

    Only NOT_FOUND is mapped here in Task 2 -- TYPE_WALL and DEP_CYCLE
    stderr matching land in Task 5 alongside `dep_mutate`, the only calls
    that can actually produce them; wiring those patterns in now would be
    untested, unreachable code (`get`/`batch_get`/`query` never trigger
    them). Anything this function doesn't recognize is the same alarm class
    as an unparseable shape -- the facade's model of bd broke.
    """
    if _NOT_FOUND_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.NOT_FOUND,
            "bd reported no matching issue",
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
