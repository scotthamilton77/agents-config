"""One relationship contract, held by every read verb.

`show` is the only bd read whose payload carries all three of parent, deps and
children. `list`/`ready` carry a parent and raw dependency edge rows but no
dependents key at all; `search` carries none of the three. The contract under
test is what the facade does about that: a relationship the source read cannot
express is absent from the item and named in `unknown_relations`, so a
consumer reads "not reported" where it used to read a confident `null`/`[]`
that happened to be false.

The bd payloads driving these tests are golden captures from an isolated
scratch install (bd 1.0.3, off-repo temp dir, never this repository's
tracker): a four-item tree where `shp-23p` is an epic with two children,
`shp-23p.1` is a child that is also blocked by `shp-bdp`, and `shp-23p.2` is a
child carrying labels, a description and notes. Capturing both sides of the
comparison from the real binary is the point -- a hand-written payload would
only prove the facade agrees with whatever this file imagines bd emits.
"""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.conftest import run_cli
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedStep
from workcli.adapters.bd.parse import parse_items
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import JsonValue
from workcli.model import RELATIONSHIP_FIELDS
from workcli.verbs.read import list_, ready, search, show

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_TREE_IDS = ("shp-23p", "shp-23p.1", "shp-23p.2", "shp-bdp")
_PARENT_ID = "shp-23p"  # the epic bd reports two parent-child dependents for


def _payload(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _ok(stdout: str) -> BdResult:
    return BdResult(returncode=0, stdout=stdout, stderr="")


_SHOW_STEPS = [ScriptedStep(("show",), _ok(_payload("bd_show_shape.json")))]
_SEARCH_STEPS = [ScriptedStep(("search",), _ok(_payload("bd_search_shape.json")))]
_LIST_STEPS = [ScriptedStep(("list",), _ok(_payload("bd_list_shape.json")))]
# `ready` reads the parked set first (one `bd list --label parked`); no seeded
# item carries the label, so the empty reply short-circuits the re-read.
_READY_STEPS = [
    ScriptedStep(("list",), _ok("[]")),
    ScriptedStep(("ready",), _ok(_payload("bd_ready_shape.json"))),
]

_LIST_SHAPED_READS = (
    ("search", ["search", "shape"], _SEARCH_STEPS),
    ("list", ["list"], _LIST_STEPS),
    ("ready", ["ready"], _READY_STEPS),
)


def _items_by_id(argv: list[str], steps: list[ScriptedStep]) -> dict[str, dict[str, JsonValue]]:
    exit_code, envelope, _ = run_cli(argv, steps)

    assert exit_code == 0, envelope
    data = envelope["data"]
    assert isinstance(data, dict)
    rows = data["items"]
    assert isinstance(rows, list)
    by_id: dict[str, dict[str, JsonValue]] = {}
    for row in rows:
        assert isinstance(row, dict)
        by_id[str(row["id"])] = row
    return by_id


def _shown() -> dict[str, dict[str, JsonValue]]:
    return _items_by_id(["show", *_TREE_IDS], _SHOW_STEPS)


def _assert_agrees_with_show(
    reported: dict[str, JsonValue], truth: dict[str, JsonValue], *, verb: str
) -> None:
    """The whole contract, applied identically to whichever verb reported it.

    Every relationship field is either present and equal to what `show` says,
    or absent and declared unknown. There is no third case -- and it is the
    third case, a field present but silently unpopulated, that this pins out
    of existence.
    """
    declared = reported["unknown_relations"]
    assert isinstance(declared, list)
    assert declared == sorted(declared), f"{verb}: unknown_relations is unordered: {declared!r}"
    assert set(declared) <= set(RELATIONSHIP_FIELDS), (
        f"{verb}: unknown_relations names a field outside the relationship set: {declared!r}"
    )
    for field in RELATIONSHIP_FIELDS:
        if field in declared:
            assert field not in reported, (
                f"{verb}: {field} is declared unknown yet still reported as "
                f"{reported[field]!r} -- an undeclared value is exactly what a "
                "consumer cannot distinguish from truth"
            )
            continue
        assert field in reported, f"{verb}: {field} is neither reported nor declared unknown"
        assert reported[field] == truth[field], (
            f"{verb}: reports {field}={reported[field]!r} for {reported['id']!r} "
            f"while show reports {truth[field]!r}"
        )


@pytest.mark.parametrize(
    ("verb", "argv", "steps"), _LIST_SHAPED_READS, ids=[read[0] for read in _LIST_SHAPED_READS]
)
def test_every_read_verb_agrees_with_show_about_the_same_item(
    verb: str, argv: list[str], steps: list[ScriptedStep]
) -> None:
    truth = _shown()

    reported = _items_by_id(argv, steps)

    assert reported, f"{verb}: the golden payload reported no items at all"
    for item_id, item in reported.items():
        _assert_agrees_with_show(item, truth[item_id], verb=verb)


def test_show_still_reports_all_three_relationships() -> None:
    # The surface that was already telling the truth; the contract must cost it
    # nothing. `shp-23p` is the epic, so this also pins that a real child set
    # still arrives as a child set.
    parent = _shown()[_PARENT_ID]

    assert parent["unknown_relations"] == []
    assert parent["children"] == ["shp-23p.1", "shp-23p.2"]
    assert parent["parent"] is None
    assert parent["deps"] == []


@pytest.mark.parametrize(
    ("argv", "steps"),
    [(argv, steps) for _, argv, steps in _LIST_SHAPED_READS],
    ids=[read[0] for read in _LIST_SHAPED_READS],
)
def test_no_read_verb_reports_an_empty_child_set_for_an_item_that_has_children(
    argv: list[str], steps: list[ScriptedStep]
) -> None:
    # The defect in one assertion: `shp-23p` has two children, and every one of
    # these reads used to answer `children: []` for it.
    item = _items_by_id(argv, steps)[_PARENT_ID]

    assert "children" not in item
    assert "children" in item["unknown_relations"]


def test_the_three_list_shaped_reads_declare_exactly_what_their_payloads_lack() -> None:
    # The per-verb pin behind the shared invariant: one verb quietly widening
    # or narrowing what it claims to know fails here even if it stays
    # self-consistent.
    declared = {
        verb: _items_by_id(argv, steps)[_PARENT_ID]["unknown_relations"]
        for verb, argv, steps in _LIST_SHAPED_READS
    }

    assert declared == {
        "search": ["children", "deps", "parent"],
        "list": ["children", "deps"],
        "ready": ["children", "deps"],
    }


def test_the_captured_bd_payloads_still_lack_the_keys_the_contract_assumes() -> None:
    """The removal condition, made mechanical.

    Every field declared unknown is declared unknown because bd's payload has
    no key for it. If a later bd starts emitting one, this fails -- and the
    right response is to report the field rather than to relax the assertion.
    """
    search_items = json.loads(_payload("bd_search_shape.json"))
    list_items = json.loads(_payload("bd_list_shape.json"))
    ready_items = json.loads(_payload("bd_ready_shape.json"))
    show_items = json.loads(_payload("bd_show_shape.json"))

    for item in search_items:
        assert {"parent", "dependencies", "dependents"} & set(item) == set()
    for item in (*list_items, *ready_items):
        # No dependents key at all -- children are unrecoverable here.
        assert "dependents" not in item
        # Edges arrive as raw rows: a far-end id and a type, never its status.
        for edge in item.get("dependencies", []):
            assert "status" not in edge
        # Parent, by contrast, is right there -- which is why these two report
        # it and `search` does not.
        assert "parent" in item or item["id"] not in {"shp-23p.1", "shp-23p.2"}
    assert any("dependents" in item for item in show_items)
    assert all("status" in edge for item in show_items for edge in item.get("dependencies", []))


# -- the same contract at the verb layer, over the in-memory Backend ----------


def _tree() -> FakeBackend:
    backend = FakeBackend()
    backend.add("p-1", title="the container")
    backend.add("c-1", title="the child", parent="p-1")
    return backend


def _read_args(**overrides: object) -> Namespace:
    base: dict[str, object] = {
        "status": None,
        "label": None,
        "parent": None,
        "type": None,
        "limit": None,
        "track": None,
        "stale_days": 14,
        "now": lambda: datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        "load_config": lambda: None,
    }
    return Namespace(**{**base, **overrides})


def _one(data: JsonValue, item_id: str) -> dict[str, JsonValue]:
    assert isinstance(data, dict)
    rows = data["items"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        if row["id"] == item_id:
            return row
    raise AssertionError(f"{item_id} missing from {rows!r}")


@pytest.mark.parametrize("verb", ["search", "list", "ready"])
def test_the_in_memory_backend_holds_the_same_contract_as_bd(verb: str) -> None:
    # The fake models each read's payload, not its own complete state, so a
    # verb-level regression that trusts a search result's parent fails here
    # without a real bd anywhere near it.
    backend = _tree()
    shown = show(backend, _read_args(ids=["c-1"]))
    assert isinstance(shown, dict)
    reads = {
        "search": lambda: search(backend, _read_args(query="child")),
        "list": lambda: list_(backend, _read_args()),
        "ready": lambda: ready(backend, _read_args(label=None)),
    }

    reported = _one(reads[verb](), "c-1")

    _assert_agrees_with_show(reported, shown, verb=verb)


@pytest.mark.parametrize("command", ["show", "search", "list", "ready"])
def test_a_parsed_item_never_holds_a_relationship_it_declares_unknown(command: str) -> None:
    # The envelope drops a declared field, but `Item` is also read directly
    # inside this package. `bd list`/`ready` DO emit dependency rows -- with no
    # status on the far end -- so a parser that only declared, without emptying,
    # left half-truth edges on the dataclass for any in-package caller that never
    # consults `unknown_relations`. Pin both halves at the parse boundary.
    items = parse_items(_payload(f"bd_{command}_shape.json"), command=command)
    assert items, f"bd_{command}_shape.json carries no items"

    empty_for = {"parent": None, "deps": [], "children": []}
    for item in items:
        for field in RELATIONSHIP_FIELDS:
            if field in item.unknown_relations:
                assert getattr(item, field) == empty_for[field], (
                    f"{command} declares {field!r} unknown for {item.id} "
                    f"but the Item still carries {getattr(item, field)!r}"
                )
