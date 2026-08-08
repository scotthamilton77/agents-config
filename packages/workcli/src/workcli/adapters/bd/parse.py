"""bd JSON shape parsing + the drift alarm.

bd's `--json` stdout is the facade's only contract with the real bd binary;
this module is the single place that turns bd's raw, occasionally
inconsistent shapes into workcli's normalized `Item`/`DepEdge` model. Any
shape bd emits that this module cannot map raises `WorkError(BACKEND_DRIFT)`
-- bd's own model of itself broke, and silently guessing is worse than
alarming loudly.

Two known shape inconsistencies this module bridges (found capturing the
golden fixtures, not documented anywhere in bd's `--help`):

- `bd show`'s embedded `dependencies[]`/`dependents[]` entries are full
  embedded beads plus a `dependency_type` field (the OTHER bead's `id` and
  `status` are directly present). `bd list`'s embedded `dependencies[]`
  entries are raw edge rows (`issue_id`, `depends_on_id`, `type`) with no
  `status` for the other end at all.
- `bd show` exposes no `children` key; children are recovered by filtering
  `dependents[]` down to `dependency_type == "parent-child"`.

Which reads can see which relationship is therefore not uniform, and
`_UNKNOWN_RELATIONS` below is where that asymmetry is declared rather than
absorbed.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from workcli.adapters.bd.runner import BdResult
from workcli.adapters.bd.vocabulary import redact
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import DepEdge, Item

# The key every published fragment of backend-authored text travels under.
# Named for what it is: a diagnostic, scrubbed of the backend's identity,
# carrying no contract a consumer may match on. Only the paths where this
# adapter has NO classification of its own populate it -- once a failure has
# a typed code, the code and its message are the whole answer and the raw
# text would add nothing but vocabulary.
_DIAGNOSTIC_KEY = "backend_diagnostic"

_REQUIRED_ITEM_KEYS = ("id", "title", "issue_type", "status", "priority")

# Which relationships each bd read simply cannot answer, captured from bd
# 1.0.3 against an isolated scratch install:
#
#   command   parent   dependencies       dependents
#   show      yes      yes (full beads)   yes
#   list      yes      yes (edge rows)    never emitted
#   ready     yes      yes (edge rows)    never emitted
#   search    never    never              never
#
# Children come from `dependents[]`, so only `show` can report them. `list`
# and `ready` do carry edges, but as raw rows with no status for the far end,
# and an edge without it cannot answer the one question deps are for -- so
# they report no deps rather than edges that look complete and are not.
#
# Keyed on the command rather than sniffed from the payload because bd omits
# any key whose value is empty: a missing `dependents` means "this item has no
# children" under `show` and "this command never says" under the other three,
# and no amount of looking at one payload tells those apart. Reading it as the
# first is how `list` came to report every epic as childless.
_UNKNOWN_RELATIONS: dict[str, frozenset[str]] = {
    "show": frozenset(),
    "list": frozenset({"children", "deps"}),
    "ready": frozenset({"children", "deps"}),
    "search": frozenset({"parent", "deps", "children"}),
}

# Confirmed against the real bd binary, per golden capture: a
# not-found `show` logs this exact wording to stderr per missing id, even
# though the overall process may still exit 0 if other requested ids matched
# (see BdBackend.batch_get's own missing-id reconciliation for that case).
_NOT_FOUND_STDERR_MARKER = "no issue found matching"

# bd's OTHER not-found wording, captured live from `bd update ID --parent
# <missing>` (exit 1, stderr "Error getting parent X: not found: issue X").
# The reparent path never emits the marker above, so without this one a
# typo'd `--set-parent` -- the likeliest mistake anyone makes with that flag
# -- reports E_BACKEND_DRIFT ("bd's model of itself broke") instead of the
# plain missing-item answer it is.
_NOT_FOUND_ALT_STDERR_MARKER = "not found: issue"

# Confirmed by reading bd's own Go source at the installed binary's commit:
# internal/storage/issueops/dependencies.go emits "epics can only block
# other epics, not tasks" / "tasks can only block other tasks, not epics"
# for the cross-type wall, and "adding dependency would create a cycle" for
# the recursive-CTE cycle check. These are a safety net for a wall/cycle the
# verb layer's own pre-check can't see (e.g. a stale read) -- `dep_mutate`'s
# call is what can actually reach them.
_TYPE_WALL_STDERR_MARKER = "can only block"
_DEP_CYCLE_STDERR_MARKER = "would create a cycle"

# Captured live from `bd close` against an item with an open blocker (exit 1,
# stderr `cannot close X: blocked by open issues [Y] (use --force to
# override)`). This is a well-formed refusal, not drift: the backend
# understood the request and declined it, and reporting it through the
# catch-all would tell the caller their tracker is broken when in fact their
# graph is doing its job. The pattern lifts the two facts a caller can act on
# -- which item, and what is holding it -- out of a sentence that also names
# a backend flag the facade does not offer.
_OPEN_BLOCKERS_STDERR_MARKER = "blocked by open issues"
_OPEN_BLOCKERS_PATTERN = re.compile(
    r"cannot close (?P<item>\S+?):\s*blocked by open issues \[(?P<blockers>[^\]]*)\]"
)


# Captured live from bd 1.0.3 against a directory with no install: every
# command this adapter drives refuses with this wording and exit 1, before it
# looks at anything the caller asked for. The backend cannot tell a workspace
# that was never created from one whose database was removed underneath it --
# it emits the same sentence for both -- and neither can this adapter, which
# is why the code below states the absence rather than a cause. The remedy is
# the same either way.
_MISSING_WORKSPACE_STDERR_MARKER = "no beads database found"


def _drift(message: str, detail: dict[str, JsonValue]) -> WorkError:
    return WorkError(ErrorCode.BACKEND_DRIFT, message, detail=detail)


def _load_json_array(stdout: str) -> list[Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise _drift(
            f"the backend's response was not valid JSON: {exc}",
            {"reason": "invalid_json", _DIAGNOSTIC_KEY: redact(stdout[:200])},
        ) from exc
    if not isinstance(parsed, list):
        raise _drift(
            "the backend's response was not the expected JSON array",
            {"reason": "not_an_array", "raw_type": type(parsed).__name__},
        )
    return parsed


def _dep_edge_from_raw(entry: dict[str, JsonValue], self_id: str) -> DepEdge:
    if "dependency_type" in entry:
        # show-shape: full embedded bead + dependency_type; id/status
        # describe the OTHER end of the edge directly. A drifted bd omitting
        # `id` here must alarm loudly, not raise a raw KeyError that surfaces
        # as E_INTERNAL.
        if "id" not in entry:
            raise _drift(
                "the backend returned a dependency edge with no item id",
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
            status=_string_field(entry, "status", self_id, default=""),
        )
    # list-shape: raw edge row {issue_id, depends_on_id, type}; no status
    # for the other end is available without a second fetch. Same drift
    # discipline: a missing edge key alarms rather than raising KeyError.
    missing = [key for key in ("issue_id", "depends_on_id", "type") if key not in entry]
    if missing:
        raise _drift(
            f"the backend returned a dependency edge missing required field(s): "
            f"{', '.join(missing)}",
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
                    f"the backend returned a dependency edge whose {key} field is null, "
                    f"expected a string",
                    {"reason": "null_field", "field": key, "id": item_id},
                )
            return str(value)
    return str(None)


def _list_field(raw: dict[str, JsonValue], key: str, item_id: str) -> list[Any]:
    """Return `raw[key]` as a list, defaulting an absent key to `[]`.

    An explicit JSON `null` is NOT the same as a missing key: bd emitting
    `null` where the facade's model says the field is an array is itself
    model drift -- it must alarm loudly via `WorkError(BACKEND_DRIFT)`,
    never silently coerce to `[]` and never
    raise a raw `AssertionError`/`TypeError` from an unguarded downstream
    `isinstance`/iteration.
    """
    if key not in raw:
        return []
    value = raw[key]
    if value is None:
        raise _drift(
            f"the backend returned an item whose {key} field is null, expected an array",
            {"reason": "null_field", "field": key, "id": item_id},
        )
    if not isinstance(value, list):
        raise _drift(
            f"the backend returned an item whose {key} field is not an array",
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
            f"the backend returned an item missing required field: {key}",
            {
                "reason": "missing_required_keys",
                "missing_keys": cast("list[JsonValue]", [key]),
                "id": item_id,
            },
        )
    value = raw[key]
    if value is None:
        raise _drift(
            f"the backend returned an item whose {key} field is null, expected a string",
            {"reason": "null_field", "field": key, "id": item_id},
        )
    return str(value)


def _optional_string_field(raw: dict[str, JsonValue], key: str, item_id: str) -> str | None:
    """Return `raw[key]` as a `str`, or `None` where the backend reports nothing.

    The opposite discipline to `_string_field`, and for a field the normalized
    model types as optional: absence is an answer here, not a gap. bd omits any
    key whose value is empty, so an absent key, an explicit `null` and `""` are
    one answer arriving three ways -- all normalize to `None`, because
    publishing three spellings of "none" would make every consumer handle each.
    A non-string value is still drift: the model types this as text.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _drift(
            f"the backend returned an item whose {key} field is not a string",
            {"reason": "unexpected_field_type", "field": key, "id": item_id},
        )
    return value or None


def _string_list_field(raw: dict[str, JsonValue], key: str, item_id: str) -> list[str]:
    """Return `raw[key]` as a `list[str]`, alarming on any non-string element.

    Layers per-element string validation on top of `_list_field` (absent ->
    `[]`, null/non-array -> drift). The normalized contract types this field
    as a `string[]`; a non-string element (a number, an object, ...) is bd
    model drift, not something to silently coerce with `str()` -- the same
    discipline `parse_labels` applies to the `label list` command.
    """
    values = _list_field(raw, key, item_id)
    for value in values:
        if not isinstance(value, str):
            raise _drift(
                f"the backend returned an item whose {key} field contains a non-string element",
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
    carry on from -- same discipline as `parse_items`'/`parse_dep_edges`'
    own `element_not_an_object` check.
    """
    for entry in entries:
        if not isinstance(entry, dict):
            raise _drift(
                f"the backend returned an item whose {field} entry is not a JSON object",
                {
                    "reason": "element_not_an_object",
                    "field": field,
                    "id": item_id,
                    "raw_type": type(entry).__name__,
                },
            )


def parse_item(raw: dict[str, JsonValue], *, unknown: frozenset[str] = frozenset()) -> Item:
    missing = [key for key in _REQUIRED_ITEM_KEYS if key not in raw]
    if missing:
        raise _drift(
            f"the backend returned an item missing required field(s): {', '.join(missing)}",
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
            "the backend returned an item whose priority field is not an integer",
            {"reason": "unexpected_priority_type", "id": item_id, "priority": priority_raw},
        )

    dependencies = _list_field(raw, "dependencies", item_id)
    dependents = _list_field(raw, "dependents", item_id)
    _assert_object_elements(dependencies, field="dependencies", item_id=item_id)
    _assert_object_elements(dependents, field="dependents", item_id=item_id)

    # A declared-unknown relationship is emptied here, not merely dropped by the
    # verb layer. `bd list`/`ready` DO carry dependency rows, but with no status
    # on the far end -- an edge that cannot say whether it still blocks. Keeping
    # those on the Item would leave partial data for any in-package caller that
    # reads `Item.deps` without consulting `unknown_relations`, which is the same
    # half-truth one layer below the envelope.
    deps = (
        []
        if "deps" in unknown
        else [
            _dep_edge_from_raw(entry, item_id)
            for entry in dependencies
            if _dep_type(entry, item_id) != "parent-child"
        ]
    )
    children = (
        []
        if "children" in unknown
        else [
            _dep_edge_from_raw(entry, item_id).id
            for entry in dependents
            if _dep_type(entry, item_id) == "parent-child"
        ]
    )

    return Item(
        id=item_id,
        title=_string_field(raw, "title", item_id),
        type=_string_field(raw, "issue_type", item_id),
        status=_string_field(raw, "status", item_id),
        priority=f"P{priority_raw}",
        labels=_string_list_field(raw, "labels", item_id),
        parent=(None if "parent" in unknown or raw.get("parent") is None else str(raw["parent"])),
        deps=deps,
        children=children,
        description=_string_field(raw, "description", item_id, default=""),
        notes=_string_field(raw, "notes", item_id, default=""),
        created=str(raw["created_at"]) if raw.get("created_at") is not None else None,
        updated=str(raw["updated_at"]) if raw.get("updated_at") is not None else None,
        # Every read command carries this field (captured from bd 1.0.3
        # against an isolated scratch install: show, list, ready and search
        # all report it), so no read has to declare it unavailable the way
        # the relationships below are declared -- see `_UNKNOWN_RELATIONS`.
        acceptance=_optional_string_field(raw, "acceptance_criteria", item_id),
        # An unanswerable relationship is empty here AND travels declared, so
        # neither layer can mistake it for an answer: in-package callers reading
        # the Item see nothing to misread, and the verb layer drops the field
        # rather than publishing the empty as a result.
        unknown_relations=unknown,
    )


def parse_items(stdout: str, *, command: str = "show") -> list[Item]:
    raw_items = _load_json_array(stdout)
    unknown = _UNKNOWN_RELATIONS[command]
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise _drift(
                "the backend's response contains an element that is not a JSON object",
                {"reason": "element_not_an_object", "raw_type": type(raw).__name__},
            )
        items.append(parse_item(raw, unknown=unknown))
    return items


def parse_created_id(stdout: str) -> str:
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
            f"the backend's response to a create was not valid JSON: {exc}",
            {"reason": "invalid_json", _DIAGNOSTIC_KEY: redact(stdout[:200])},
        ) from exc
    if not isinstance(parsed, dict):
        raise _drift(
            "the backend's response to a create was not a JSON object",
            {"reason": "not_an_object", "raw_type": type(parsed).__name__},
        )
    item_id = parsed.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise _drift(
            "the backend's response to a create carries no item id",
            {"reason": "missing_id", "raw_keys": cast("list[JsonValue]", list(parsed.keys()))},
        )
    return item_id


def parse_dep_edges(stdout: str, *, self_id: str, direction: str = "depends-on") -> list[DepEdge]:
    """Parse `bd dep list --json`'s flat array into lean `DepEdge`s.

    Unlike `show`/`list` (arrays of full items), `bd dep list --json` emits a
    flat array of edge records: each entry IS the full embedded bead at the
    other end of the edge, plus a top-level `dependency_type` field --
    exactly the `show`-shape branch of `_dep_edge_from_raw` (golden fixtures
    `bd_dep_list_down.json`/`bd_dep_list_up.json` confirm this; bd never
    emits the list-shape raw edge row for this command). A record missing
    `dependency_type` is an unrecognized shape, not a silent guess.
    """
    raw_entries = _load_json_array(stdout)
    edges = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise _drift(
                f"the backend's {direction} listing contains an element that is not a JSON object",
                {"reason": "element_not_an_object", "raw_type": type(raw).__name__},
            )
        if "dependency_type" not in raw or "id" not in raw:
            raise _drift(
                f"the backend's {direction} listing has a record missing its edge type or item id",
                {"reason": "missing_required_keys", "raw_keys": cast("list[JsonValue]", list(raw))},
            )
        edges.append(_dep_edge_from_raw(raw, self_id))
    return edges


def parse_labels(stdout: str) -> list[str]:
    raw_labels = _load_json_array(stdout)
    for label in raw_labels:
        if not isinstance(label, str):
            raise _drift(
                "the backend's label listing contains an element that is not a string",
                {"reason": "label_not_a_string", "raw_type": type(label).__name__},
            )
    return raw_labels


def _open_blockers_failure(stderr: str) -> WorkError:
    """The backend's close-time blocker refusal, restated in facade terms.

    The backend's own sentence ends with the flag that would override the
    refusal. That flag is not the facade's to offer, so the advice here names
    what a caller can actually do through the seam instead.
    """
    match = _OPEN_BLOCKERS_PATTERN.search(stderr)
    if match is None:
        # The marker matched but the sentence around it did not: the refusal
        # is still real and still not drift, it just cannot be itemised.
        return WorkError(
            ErrorCode.OPEN_BLOCKERS,
            "cannot close an item while the items blocking it are still open; "
            "close or unblock them first",
        )
    item_id = match.group("item")
    blockers = [blocker for blocker in re.split(r"[,\s]+", match.group("blockers")) if blocker]
    return WorkError(
        ErrorCode.OPEN_BLOCKERS,
        f"cannot close {item_id} while the items blocking it are still open "
        f"({', '.join(blockers)}); close or unblock them first",
        detail={"id": item_id, "blocked_by": cast("list[JsonValue]", blockers)},
    )


def map_bd_failure(result: BdResult) -> WorkError:
    """Translate a nonzero bd exit into a typed error.

    Two classes come out of here, and the difference decides what travels.
    A *classified* failure -- NO_WORKSPACE, NOT_FOUND, OPEN_BLOCKERS,
    TYPE_WALL, DEP_CYCLE -- means this adapter understood what bd said, so the
    typed code and a message in the facade's own words are the complete
    answer; bd's sentence would add nothing but bd's vocabulary, and is
    dropped. An *unclassified* failure is the drift alarm, and there the
    sentence is the only content there is -- so it travels, scrubbed of bd's
    identity.

    TYPE_WALL/DEP_CYCLE are a fallback safety net only: `dep`'s verb layer
    pre-checks the type wall via two `Backend.get` reads before ever calling
    `dep_mutate`, so a live bd instance should never actually surface these
    to this function -- but a pre-check race (a stale read) is still a bd
    failure, not a crash.

    This function cannot see the argv that produced `result`, and that is the
    point rather than an oversight: a command line the caller cannot run
    without knowing the backend is not a diagnostic, it is a disclosure, and
    the surest way not to publish one is not to be holding it.
    """
    # First, because it is the failure that precedes every other one: with no
    # workspace to read, nothing the caller asked for was ever attempted, and
    # the answer is about their configuration rather than about their request.
    if _MISSING_WORKSPACE_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.NO_WORKSPACE,
            "no tracker workspace is configured for this directory; create one here, "
            "or run from a directory that already has one",
        )
    if _NOT_FOUND_STDERR_MARKER in result.stderr or _NOT_FOUND_ALT_STDERR_MARKER in result.stderr:
        return WorkError(ErrorCode.NOT_FOUND, "no item matches the requested id")
    if _OPEN_BLOCKERS_STDERR_MARKER in result.stderr:
        return _open_blockers_failure(result.stderr)
    if _TYPE_WALL_STDERR_MARKER in result.stderr:
        return WorkError(ErrorCode.TYPE_WALL, "the backend rejected a cross-type dependency")
    if _DEP_CYCLE_STDERR_MARKER in result.stderr:
        return WorkError(
            ErrorCode.DEP_CYCLE, "the backend rejected a dependency that would create a cycle"
        )
    return _drift(
        f"the backend failed with exit status {result.returncode} in a way this adapter does "
        f"not recognize; detail.{_DIAGNOSTIC_KEY} carries what it reported",
        {
            "returncode": result.returncode,
            _DIAGNOSTIC_KEY: redact(result.stderr[:500].strip()),
        },
    )
