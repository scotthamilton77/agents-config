"""Acceptance criteria on the read path -- the text a claim is checked against.

`create --acceptance` always persisted the criteria; no read could return
them, so every read reported a well-formed item with no acceptance key and a
consumer read that as "this item has none".

Two things are pinned here, and the second is what makes the first safe to
build on:

- the text round-trips (create, then show) and arrives from a real payload on
  every read command;
- the key is ALWAYS present on a read item. `null` is the backend's own answer
  -- this item carries no criteria -- while an absent key would mean this read
  never fetched them, and no read is in that state. They are different values,
  so a consumer is never left guessing which one it holds: the same reason the
  relationship fields are dropped-and-declared rather than published empty.

The payloads are golden captures from an isolated scratch install (bd 1.0.3,
off-repo temp dir, never this repository's tracker): two tasks, one created
with `--acceptance` and one without, read back through each of the four
commands the facade's reads are built on.
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
from workcli.adapters.bd.parse import parse_item
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.create import create_noun
from workcli.verbs.read import show

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# The two seeded tasks: `ac-one` was created with `--acceptance`, `ac-none`
# without it.
_WITH_CRITERIA = "acp-gw6"
_WITHOUT_CRITERIA = "acp-wuq"
_CRITERIA = "AC1 show returns this text."

_READ_COMMANDS = ("show", "list", "ready", "search")


def _payload(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _ok(stdout: str) -> BdResult:
    return BdResult(returncode=0, stdout=stdout, stderr="")


# `ready` reads the parked set first; `search` reads one leg per corpus field,
# and only the title leg has a payload here.
_READS = (
    (
        "show",
        ["show", _WITH_CRITERIA, _WITHOUT_CRITERIA],
        [ScriptedStep(("show",), _ok(_payload("bd_show_acceptance.json")))],
    ),
    (
        "list",
        ["list"],
        [ScriptedStep(("list",), _ok(_payload("bd_list_acceptance.json")))],
    ),
    (
        "ready",
        ["ready"],
        [
            ScriptedStep(("list",), _ok("[]")),
            ScriptedStep(("ready",), _ok(_payload("bd_ready_acceptance.json"))),
        ],
    ),
    (
        "search",
        ["search", "ac-"],
        [
            ScriptedStep(("search",), _ok(_payload("bd_search_acceptance.json"))),
            ScriptedStep(("list",), _ok("[]")),
            ScriptedStep(("list",), _ok("[]")),
        ],
    ),
)
_READ_IDS = [read[0] for read in _READS]


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


# -- the round trip, over the in-memory backend -------------------------------


def _unconfigured_track_layer() -> TrackLayerConfig:
    # The track gate is not what this file is about; an unconfigured layer
    # makes it a no-op without inventing a track vocabulary here.
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured",
        detail={"reason": "not-found"},
    )


def _create_args(*, acceptance: str | None) -> Namespace:
    return Namespace(
        noun="chore",
        raw=False,
        title="the created work",
        description=None,
        type=None,
        priority=None,
        parent=None,
        label=[],
        orphan=True,
        spec=None,
        trivial=False,
        acceptance=acceptance,
        track=None,
        load_config=_unconfigured_track_layer,
    )


def _read_args(**overrides: object) -> Namespace:
    base: dict[str, object] = {
        "status": None,
        "label": None,
        "parent": None,
        "type": None,
        "limit": None,
        "track": None,
        "corpus": None,
        "stale_days": 14,
        "now": lambda: datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        "load_config": lambda: None,
    }
    return Namespace(**{**base, **overrides})


def _created(backend: FakeBackend, *, acceptance: str | None) -> str:
    data = create_noun(backend, _create_args(acceptance=acceptance))
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    return new_id


def test_show_returns_the_acceptance_an_item_was_created_with() -> None:
    # The defect in one assertion: the write path stored this text and no read
    # could ever hand it back.
    backend = FakeBackend()
    new_id = _created(backend, acceptance=_CRITERIA)

    shown = show(backend, _read_args(ids=[new_id]))

    assert isinstance(shown, dict)
    assert shown["acceptance"] == _CRITERIA


def test_show_reports_null_for_an_item_created_without_acceptance() -> None:
    backend = FakeBackend()
    new_id = _created(backend, acceptance=None)

    shown = show(backend, _read_args(ids=[new_id]))

    assert isinstance(shown, dict)
    assert "acceptance" in shown, (
        "an absent key means this read did not fetch the criteria; an item that "
        "has none must say so with a value"
    )
    assert shown["acceptance"] is None


# -- every read verb, against real payloads -----------------------------------


@pytest.mark.parametrize(("verb", "argv", "steps"), _READS, ids=_READ_IDS)
def test_every_read_verb_returns_the_acceptance_text(
    verb: str, argv: list[str], steps: list[ScriptedStep]
) -> None:
    reported = _items_by_id(argv, steps)

    assert reported[_WITH_CRITERIA]["acceptance"] == _CRITERIA, (
        f"{verb} does not report the criteria the backend holds for {_WITH_CRITERIA}"
    )


@pytest.mark.parametrize(("verb", "argv", "steps"), _READS, ids=_READ_IDS)
def test_no_read_verb_omits_the_key_for_an_item_that_has_no_criteria(
    verb: str, argv: list[str], steps: list[ScriptedStep]
) -> None:
    # Absent and null are the two answers a consumer must be able to tell
    # apart, and only one of them is ever right here.
    reported = _items_by_id(argv, steps)[_WITHOUT_CRITERIA]

    assert "acceptance" in reported, f"{verb} omits acceptance rather than reporting none"
    assert reported["acceptance"] is None


def test_the_list_shaped_reads_agree_with_show_about_acceptance() -> None:
    # Agreement is the contract, not availability: every read command's payload
    # carries the field, so no read has a reason to differ from `show`.
    show_argv, show_steps = _READS[0][1], _READS[0][2]
    truth = _items_by_id(show_argv, show_steps)

    for verb, argv, steps in _READS[1:]:
        reported = _items_by_id(argv, steps)
        for item_id, item in reported.items():
            assert item["acceptance"] == truth[item_id]["acceptance"], (
                f"{verb} reports acceptance={item['acceptance']!r} for {item_id} "
                f"while show reports {truth[item_id]['acceptance']!r}"
            )


def test_the_captured_payloads_still_carry_acceptance_in_every_read_shape() -> None:
    """The removal condition, made mechanical.

    Both halves of the decision live in these payloads: every read command
    reports the criteria when an item has them, and every one of them OMITS
    the key when the item has none -- which is why an absent key normalizes to
    `null` rather than alarming. If a later backend changes either half, this
    fails, and the right response is to revisit the normalization rather than
    relax the assertion.
    """
    for command in _READ_COMMANDS:
        items = json.loads(_payload(f"bd_{command}_acceptance.json"))
        by_id = {item["id"]: item for item in items}

        assert by_id[_WITH_CRITERIA]["acceptance_criteria"] == _CRITERIA, command
        assert "acceptance_criteria" not in by_id[_WITHOUT_CRITERIA], command


# -- normalization at the parse boundary --------------------------------------


def _raw_item(**overrides: object) -> dict[str, JsonValue]:
    raw: dict[str, JsonValue] = {
        "id": "raw-1",
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
    }
    raw.update(overrides)  # type: ignore[arg-type]
    return raw


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, None, id="absent"),
        pytest.param({"acceptance_criteria": None}, None, id="null"),
        pytest.param({"acceptance_criteria": ""}, None, id="empty-string"),
        pytest.param({"acceptance_criteria": _CRITERIA}, _CRITERIA, id="text"),
    ],
)
def test_the_parser_normalizes_every_backend_spelling_of_no_criteria(
    overrides: dict[str, object], expected: str | None
) -> None:
    # The backend omits any key whose value is empty, so absent, null and ""
    # are one answer arriving three ways. Keeping them apart would publish a
    # distinction with nothing behind it, and each spelling would have to be
    # handled by every consumer.
    item = parse_item(_raw_item(**overrides))

    assert item.acceptance == expected


def test_the_parser_alarms_on_acceptance_that_is_not_text() -> None:
    # The model types the criteria as text, so a non-string is the backend's
    # model of itself breaking -- coercing it would publish "5" as an item's
    # acceptance criteria and lose the only signal that anything was wrong.
    with pytest.raises(WorkError) as exc_info:
        parse_item(_raw_item(acceptance_criteria=5))

    assert exc_info.value.code is ErrorCode.BACKEND_DRIFT
    assert exc_info.value.detail["field"] == "acceptance_criteria"
