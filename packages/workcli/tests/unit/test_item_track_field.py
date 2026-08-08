"""Item.track envelope field on all read verbs."""

from __future__ import annotations

import json

import pytest

from tests.conftest import only_item, run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult


def _bd_item(item_id: str, labels: list[str]) -> dict[str, object]:
    """Minimal bd show/list JSON record accepted by adapters/bd/parse.py.

    Mirror the fixture fields used in test_show_normalization.py; extend only
    if parse_items rejects the record (its drift alarm names what's missing).
    """
    return {
        "id": item_id,
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": labels,
    }


def _show_step(item_id: str, labels: list[str]) -> ScriptedStep:
    return ScriptedStep(
        ("show",),
        BdResult(returncode=0, stdout=json.dumps([_bd_item(item_id, labels)]), stderr=""),
    )


def test_show_carries_derived_track() -> None:
    exit_code, envelope, _ = run_cli(
        ["show", "w-1"], [_show_step("w-1", ["track:installer", "planned"])]
    )
    assert exit_code == 0
    assert only_item(envelope["data"])["track"] == "installer"


def test_show_zero_or_multi_track_labels_carry_null() -> None:
    exit_code, envelope, _ = run_cli(["show", "w-1"], [_show_step("w-1", ["track:a", "track:b"])])
    assert exit_code == 0
    assert only_item(envelope["data"])["track"] is None


@pytest.mark.parametrize(
    ("argv", "leading_prefixes", "prefix"),
    [
        (["list"], (), ("list",)),
        # `ready` reads the parking lot first (the parked_stale block), so its
        # own listing is the SECOND bd call.
        (["ready"], (("list",),), ("ready",)),
        # Narrowed to one corpus field so this stays a one-call case like its
        # siblings; the field a match came from has no bearing on the track.
        (["search", "T", "--in", "title"], (), ("search",)),
    ],
)
def test_every_list_shaped_read_verb_carries_track(
    argv: list[str], leading_prefixes: tuple[tuple[str, ...], ...], prefix: tuple[str, ...]
) -> None:
    empty = BdResult(returncode=0, stdout="[]", stderr="")
    step = ScriptedStep(
        prefix,
        BdResult(
            returncode=0,
            stdout=json.dumps([_bd_item("w-1", ["track:prgroom"])]),
            stderr="",
        ),
    )
    steps = [ScriptedStep(leading, empty) for leading in leading_prefixes] + [step]
    exit_code, envelope, _ = run_cli(argv, steps)
    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["track"] == "prgroom"
