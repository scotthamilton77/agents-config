"""park / redispatch / abandon / parked (S2-B).

Parked = status `blocked` + `parked` label + a timestamped typed marker, one
facade call; the un-park verbs walk back to `open` with distinct recorded
intent; `parked` is a read-only staleness report -- the machine never acts
on a parked item. State-based on `FakeBackend`; `_ReadOnlyFakeBackend` proves
the report's zero-writes contract by raising on every mutator.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tests.fake_backend import FakeBackend
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.park import (
    ABANDONED_MARKER,
    PARKED_LABEL,
    PARKED_MARKER,
    REASONS,
    REDISPATCHED_MARKER,
    abandon,
    park,
    parked,
    redispatch,
)
from workcli.lifecycle.transitions import claim
from workcli.model import CreateFields, UpdateFields

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
_ISO = _NOW.isoformat()


def _park_args(item_id: str, reason: str, note: str | None = None) -> Namespace:
    return Namespace(id=item_id, reason=reason, note=note, now=lambda: _NOW)


def _id_args(item_id: str) -> Namespace:
    return Namespace(id=item_id, now=lambda: _NOW)


def _parked_args(stale_days: int = 7) -> Namespace:
    return Namespace(stale_days=stale_days, now=lambda: _NOW)


def _parked_item(backend: FakeBackend, item_id: str, *, parked_at: str, reason: str) -> None:
    backend.add(
        item_id,
        status="blocked",
        labels=[PARKED_LABEL],
        notes=f"{PARKED_MARKER} {parked_at} {reason}: CI red",
    )


class _ReadOnlyFakeBackend(FakeBackend):
    """Raises on every mutator: the `parked` report reports, never acts."""

    def _refuse(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("parked report must never mutate the backend")

    def create(self, fields: CreateFields) -> str:
        self._refuse(fields)
        raise AssertionError  # unreachable; keeps the signature's return type honest

    def set_fields(self, item_id: str, fields: UpdateFields) -> None:
        self._refuse(item_id, fields)

    def claim(self, item_id: str) -> None:
        self._refuse(item_id)

    def set_status(self, item_id: str, status: str) -> None:
        self._refuse(item_id, status)

    def set_type(self, item_id: str, item_type: str) -> None:
        self._refuse(item_id, item_type)

    def set_acceptance(self, item_id: str, text: str) -> None:
        self._refuse(item_id, text)

    def append_note(self, item_id: str, text: str) -> None:
        self._refuse(item_id, text)

    def close(self, ids: Sequence[str]) -> None:
        self._refuse(ids)

    def reopen(self, item_id: str) -> None:
        self._refuse(item_id)

    def label_mutate(self, op: str, item_id: str, labels: Sequence[str]) -> None:
        self._refuse(op, item_id, labels)


def test_park_sets_blocked_plus_label_plus_typed_marker():  # S2-B1
    backend = FakeBackend().add("w1", status="in_progress")

    data = park(backend, _park_args("w1", "ci-failure", note="flaky job"))

    item = backend.get("w1")
    assert item.status == "blocked"
    assert PARKED_LABEL in item.labels
    assert backend.note_lines("w1") == [f"{PARKED_MARKER} {_ISO} ci-failure: flaky job"]
    assert data == {"id": "w1", "status": "parked", "reason": "ci-failure", "category": "machine"}


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("ci-failure", "machine"),
        ("merge-conflict", "machine"),
        ("approval-required", "human"),
        ("bot-declined", "human"),
        ("budget-exhausted", "human"),
    ],
)
def test_vocabulary_codes_map_to_their_d10_category(reason: str, category: str):  # S2-B2
    assert REASONS[reason] == category
    backend = FakeBackend().add("w1", status="in_progress")

    data = park(backend, _park_args("w1", reason))

    assert isinstance(data, dict)
    assert data["category"] == category


def test_park_unknown_reason_is_usage_error_before_any_backend_call():  # S2-B2 (inverse)
    backend = _ReadOnlyFakeBackend()  # any touch -- even a read's mutation -- would raise

    with pytest.raises(WorkError) as excinfo:
        park(backend, _park_args("w1", "vibes"))

    assert excinfo.value.code is ErrorCode.USAGE
    for code in REASONS:
        assert code in excinfo.value.message


def test_park_closed_item_is_usage_error():  # S2-B3 (inverse)
    backend = FakeBackend().add("w1", status="closed")

    with pytest.raises(WorkError) as excinfo:
        park(backend, _park_args("w1", "ci-failure"))

    assert excinfo.value.code is ErrorCode.USAGE


def test_repark_is_an_idempotent_noop_reporting_the_existing_stint():  # S2-B3
    backend = FakeBackend()
    _parked_item(backend, "w1", parked_at=_ISO, reason="merge-conflict")

    data = park(backend, _park_args("w1", "ci-failure"))

    # No second marker; the existing stint's reason wins over the new code.
    assert backend.note_lines("w1") == [f"{PARKED_MARKER} {_ISO} merge-conflict: CI red"]
    assert data == {
        "id": "w1",
        "status": "parked",
        "reason": "merge-conflict",
        "category": "machine",
    }


def test_parked_item_is_not_claimable():  # S2-B4
    backend = FakeBackend().add("w1", status="in_progress")
    park(backend, _park_args("w1", "approval-required"))

    with pytest.raises(WorkError) as excinfo:
        claim(backend, Namespace(id="w1"))

    assert excinfo.value.code is ErrorCode.NOT_CLAIMABLE
    assert "parked" in excinfo.value.message


def test_redispatch_walks_parked_back_to_open_with_a_marker():  # S2-B5
    backend = FakeBackend()
    _parked_item(backend, "w1", parked_at=_ISO, reason="ci-failure")

    data = redispatch(backend, _id_args("w1"))

    item = backend.get("w1")
    assert item.status == "open"
    assert PARKED_LABEL not in item.labels
    assert f"{REDISPATCHED_MARKER} {_ISO}" in backend.note_lines("w1")
    assert data == {"id": "w1", "status": "open"}


def test_redispatch_open_unparked_item_is_a_noop():  # S2-B5 (idempotency)
    backend = FakeBackend().add("w1", status="open")

    data = redispatch(backend, _id_args("w1"))

    assert data == {"id": "w1", "status": "open"}
    assert backend.note_lines("w1") == []


def test_redispatch_closed_item_is_usage_error():  # S2-B5 (inverse)
    backend = FakeBackend().add("w1", status="closed")

    with pytest.raises(WorkError) as excinfo:
        redispatch(backend, _id_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE


def test_redispatch_in_progress_unparked_item_is_usage_error():  # S2-B5 (inverse)
    backend = FakeBackend().add("w1", status="in_progress")

    with pytest.raises(WorkError) as excinfo:
        redispatch(backend, _id_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE


def test_abandon_records_its_own_distinct_intent():  # S2-B6
    backend = FakeBackend()
    _parked_item(backend, "w1", parked_at=_ISO, reason="bot-declined")

    data = abandon(backend, _id_args("w1"))

    item = backend.get("w1")
    assert item.status == "open"
    assert PARKED_LABEL not in item.labels
    assert f"{ABANDONED_MARKER} {_ISO}" in backend.note_lines("w1")
    assert data == {"id": "w1", "status": "open"}


def test_parked_report_lists_reason_category_staleness_read_only():  # S2-B7
    backend = _ReadOnlyFakeBackend()
    _parked_item(
        backend,
        "old",
        parked_at=datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        reason="ci-failure",
    )
    _parked_item(
        backend,
        "new",
        parked_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC).isoformat(),
        reason="approval-required",
    )
    backend.add("unrelated", status="open")

    data = parked(backend, _parked_args(stale_days=7))

    assert data == {
        "items": [
            {
                "id": "old",
                "title": "T",
                "reason": "ci-failure",
                "category": "machine",
                "parked_at": "2026-07-10T12:00:00+00:00",
                "stale": True,
            },
            {
                "id": "new",
                "title": "T",
                "reason": "approval-required",
                "category": "human",
                "parked_at": "2026-07-21T12:00:00+00:00",
                "stale": False,
            },
        ],
        "stale_days": 7,
    }


def test_parked_report_degrades_an_unparseable_marker_to_nulls():  # S2-B7 (dep failure)
    backend = _ReadOnlyFakeBackend()
    backend.add("w1", status="blocked", labels=[PARKED_LABEL], notes="hand-written note")

    data = parked(backend, _parked_args())

    assert data == {
        "items": [
            {
                "id": "w1",
                "title": "T",
                "reason": None,
                "category": None,
                "parked_at": None,
                "stale": False,
            }
        ],
        "stale_days": 7,
    }


# --- CLI wiring (argparse surface + envelope) --------------------------------


def test_cli_park_wires_status_label_and_marker_in_order():
    import json as _json

    from tests.conftest import run_cli_with_runner
    from tests.fakes import ScriptedBdRunner, ScriptedStep
    from workcli.adapters.bd.runner import BdResult

    ok = BdResult(returncode=0, stdout="", stderr="")
    show = BdResult(
        returncode=0,
        stdout=_json.dumps(
            [
                {
                    "id": "w1",
                    "title": "T",
                    "issue_type": "task",
                    "status": "in_progress",
                    "priority": 2,
                    "labels": [],
                    "parent": None,
                    "dependencies": [],
                    "dependents": [],
                }
            ]
        ),
        stderr="",
    )
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), show),
            ScriptedStep(("update", "w1", "--status", "blocked"), ok),
            ScriptedStep(("label", "add", "w1", PARKED_LABEL), ok),
            ScriptedStep(("update", "w1", "--append-notes"), ok),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["park", "w1", "--reason", "ci-failure", "--note", "flaky"], runner
    )

    assert exit_code == 0
    assert envelope["data"] == {
        "id": "w1",
        "status": "parked",
        "reason": "ci-failure",
        "category": "machine",
    }
    assert [call[:2] for call in runner.calls] == [
        ("show", "w1"),
        ("update", "w1"),
        ("label", "add"),
        ("update", "w1"),
    ]


def test_cli_parked_with_no_parked_items_is_an_empty_report():
    from tests.conftest import run_cli
    from tests.fakes import ScriptedStep
    from workcli.adapters.bd.runner import BdResult

    exit_code, envelope, _ = run_cli(
        ["parked"],
        steps=[
            ScriptedStep(
                ("list", "--json", "--label", PARKED_LABEL),
                BdResult(returncode=0, stdout="[]", stderr=""),
            )
        ],
    )

    assert exit_code == 0
    assert envelope["data"] == {"items": [], "stale_days": 7}


# --- unpark crash-window replays (Codex P2 on PR #371) -----------------------


def test_unpark_replay_after_marker_but_before_label_drop_converges():
    # Crash window: status open + marker appended, `parked` handle still on.
    # The replay must drop the handle without minting a second marker.
    backend = FakeBackend().add(
        "w1",
        status="open",
        labels=[PARKED_LABEL],
        notes=(f"{PARKED_MARKER} {_ISO} ci-failure: CI red\n{REDISPATCHED_MARKER} {_ISO}"),
    )

    data = redispatch(backend, _id_args("w1"))

    item = backend.get("w1")
    assert PARKED_LABEL not in item.labels
    lines = backend.note_lines("w1")
    assert sum(1 for line in lines if line.startswith(REDISPATCHED_MARKER)) == 1
    assert data == {"id": "w1", "status": "open"}


def test_unpark_replay_after_status_only_still_records_the_marker():
    # Crash window: status flipped open, marker never appended, handle on.
    backend = FakeBackend().add(
        "w1",
        status="open",
        labels=[PARKED_LABEL],
        notes=f"{PARKED_MARKER} {_ISO} bot-declined: nope",
    )

    data = abandon(backend, _id_args("w1"))

    item = backend.get("w1")
    assert PARKED_LABEL not in item.labels
    assert f"{ABANDONED_MARKER} {_ISO}" in backend.note_lines("w1")
    assert data == {"id": "w1", "status": "open"}


def test_prior_cycle_unpark_marker_does_not_suppress_the_current_one():
    # park -> redispatch -> park -> redispatch: the second unpark must record
    # its own marker even though an older one exists before the last park.
    early = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC).isoformat()
    backend = FakeBackend().add(
        "w1",
        status="blocked",
        labels=[PARKED_LABEL],
        notes=(
            f"{PARKED_MARKER} {early} ci-failure: first stint\n"
            f"{REDISPATCHED_MARKER} {early}\n"
            f"{PARKED_MARKER} {_ISO} merge-conflict: second stint"
        ),
    )

    redispatch(backend, _id_args("w1"))

    lines = backend.note_lines("w1")
    assert sum(1 for line in lines if line.startswith(REDISPATCHED_MARKER)) == 2
