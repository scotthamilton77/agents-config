"""The `parked_stale` block on `ready` and `claim` (S9T1-P1..P6).

D10's rule is that *any* open-new-work interaction shows the stuck work
first. `executor next` is the composed surface; this block is the layer that
makes the rule hold for every caller who never touches the executor -- so it
is always present, computed by reads alone, and fail-closed: a `ready` or
`claim` that cannot compute it errors rather than handing out work beside a
surfacing that quietly failed.

Membership is deliberately WIDER than `work parked`'s `stale` flag:
proven-stale OR unknown-age. A corrupted marker makes an item's age
unprovable, and unprovable must never read as "not stale yet".
"""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import run_cli_with_runner
from tests.fake_backend import FakeBackend, ReadOnlyFakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.park import DEFAULT_STALE_DAYS, PARKED_LABEL, PARKED_MARKER, parked
from workcli.lifecycle.transitions import claim
from workcli.model import Item, QueryFilters
from workcli.verbs.read import ready

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
_STALE_AT = (_NOW - timedelta(days=30)).isoformat()
_FRESH_AT = (_NOW - timedelta(days=1)).isoformat()


def _ready_args(label: str | None = None) -> Namespace:
    return Namespace(label=label, now=lambda: _NOW)


def _claim_args(item_id: str) -> Namespace:
    return Namespace(id=item_id, now=lambda: _NOW)


def _parked_args(stale_days: int = DEFAULT_STALE_DAYS) -> Namespace:
    return Namespace(stale_days=stale_days, now=lambda: _NOW)


def _park(
    backend: FakeBackend,
    item_id: str,
    *,
    parked_at: str,
    reason: str = "ci-failure",
    title: str = "T",
) -> FakeBackend:
    return backend.add(
        item_id,
        title=title,
        status="blocked",
        labels=[PARKED_LABEL],
        notes=f"{PARKED_MARKER} {parked_at} {reason}: CI red",
    )


def _block(data: JsonValue) -> list[JsonValue]:
    assert isinstance(data, dict)
    block = data["parked_stale"]
    assert isinstance(block, list)
    return block


# --- S9T1-P1: the block is present, shaped, and always emitted -------------


def test_ready_carries_the_stale_parked_items_with_their_five_fields():  # S9T1-P1
    backend = ReadOnlyFakeBackend()
    _park(backend, "stuck", parked_at=_STALE_AT, reason="approval-required", title="Old thing")
    backend.add("w1", status="open")

    data = ready(backend, _ready_args())

    assert _block(data) == [
        {
            "id": "stuck",
            "title": "Old thing",
            "reason": "approval-required",
            "category": "human",
            "parked_at": _STALE_AT,
        }
    ]
    # The block rides ALONGSIDE the ready list; it never filters it.
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    assert [item["id"] for item in items if isinstance(item, dict)] == ["w1"]


def test_claim_carries_the_same_block_on_the_item_it_hands_out():  # S9T1-P1
    backend = FakeBackend().add("w1", status="open")
    _park(backend, "stuck", parked_at=_STALE_AT)

    data = claim(backend, _claim_args("w1"))

    assert data == {
        "id": "w1",
        "status": "in_progress",
        "parked_stale": [
            {
                "id": "stuck",
                "title": "T",
                "reason": "ci-failure",
                "category": "machine",
                "parked_at": _STALE_AT,
            }
        ],
    }


def test_the_block_is_present_and_empty_when_nothing_qualifies():  # S9T1-P1 (empty boundary)
    # The absence of stale parked work is a REPORTED FACT, not a missing key:
    # a consumer must never have to tell "none" from "the field wasn't computed".
    backend = FakeBackend().add("w1", status="open")

    assert _block(ready(backend, _ready_args())) == []
    assert _block(claim(backend, _claim_args("w1"))) == []


def test_claim_on_an_already_claimed_item_still_carries_the_block():  # S9T1-P1
    # The idempotent no-op is a SUCCESS envelope, so it owes the surfacing too.
    backend = FakeBackend().add("w1", status="in_progress")
    _park(backend, "stuck", parked_at=_STALE_AT)

    assert len(_block(claim(backend, _claim_args("w1")))) == 1


def test_ready_and_claim_take_no_stale_days_flag():  # S9T1-P1 (D10: no new flags)
    # Tuning lives on `work parked --stale-days`; the block rides S2-D4's
    # default so the surfacing cannot be widened per call site.
    for argv in (["ready", "--stale-days", "90"], ["claim", "w1", "--stale-days", "90"]):
        exit_code, envelope, _ = run_cli_with_runner(argv, ScriptedBdRunner(steps=[]))
        error = envelope["error"]
        assert exit_code == 1
        assert isinstance(error, dict)
        assert error["code"] == str(ErrorCode.USAGE)


# --- S9T1-P2: reads only ---------------------------------------------------


def test_ready_computes_the_block_without_a_single_mutation():  # S9T1-P2
    # ReadOnlyFakeBackend raises on every mutator: not "no writes were
    # logged", but "no write was reachable at all".
    backend = ReadOnlyFakeBackend()
    _park(backend, "stuck", parked_at=_STALE_AT)

    assert len(_block(ready(backend, _ready_args()))) == 1


def test_ready_bd_call_log_is_two_reads_and_nothing_else():  # S9T1-P2
    empty = BdResult(returncode=0, stdout="[]", stderr="")
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("list",), empty), ScriptedStep(("ready",), empty)]
    )

    exit_code, envelope, _ = run_cli_with_runner(["ready"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"items": [], "parked_stale": []}
    assert runner.calls == [
        ("list", "--json", "--all", "--label", PARKED_LABEL, "--limit", "0"),
        ("ready", "--json", "--limit", "0"),
    ]


def test_claims_write_set_is_unchanged_by_the_block():  # S9T1-P2
    # Pre-block, `claim` issued exactly one mutation: bd's atomic `--claim`.
    # The block joins two reads onto that; the write set must not move.
    empty = BdResult(returncode=0, stdout="[]", stderr="")
    item = BdResult(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "id": "w1",
                    "title": "T",
                    "issue_type": "task",
                    "status": "open",
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
            ScriptedStep(("show",), item),
            ScriptedStep(("ready",), item),
            ScriptedStep(("list",), empty),
            ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr="")),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(["claim", "w1"], runner)

    assert exit_code == 0
    mutations = [call for call in runner.calls if call[0] not in {"show", "list", "ready"}]
    assert mutations == [("update", "w1", "--claim")]


# --- S9T1-P3: the block is the threshold surfacing, not a second report ----


def test_a_recently_parked_item_is_reported_by_parked_but_not_by_the_block():  # S9T1-P3
    backend = ReadOnlyFakeBackend()
    _park(backend, "fresh", parked_at=_FRESH_AT)

    report = parked(backend, _parked_args())

    assert isinstance(report, dict)
    items = report["items"]
    assert isinstance(items, list)
    assert [item["id"] for item in items if isinstance(item, dict)] == ["fresh"]
    assert _block(ready(backend, _ready_args())) == []


@pytest.mark.parametrize(
    ("age", "in_block"),
    [
        (timedelta(days=DEFAULT_STALE_DAYS), False),
        (timedelta(days=DEFAULT_STALE_DAYS, seconds=1), True),
    ],
)
def test_the_threshold_boundary_is_strictly_older_than(age, in_block):  # S9T1-P3 (boundary)
    # Exactly at the threshold is NOT stale -- the block and `work parked`'s
    # `stale` flag agree on the boundary; they differ only on unknown age.
    backend = ReadOnlyFakeBackend()
    _park(backend, "edge", parked_at=(_NOW - age).isoformat())

    assert bool(_block(ready(backend, _ready_args()))) is in_block


# --- S9T1-P4: fail-closed on a failed parked read -------------------------


class _ParkedReadDown(ReadOnlyFakeBackend):
    """The parking-lot query is down; everything else works."""

    def query(self, filters: QueryFilters) -> list[Item]:
        raise WorkError(ErrorCode.BACKEND_DRIFT, f"bd list: unparseable output ({filters.label})")


def test_ready_fails_typed_rather_than_reporting_without_the_block():  # S9T1-P4
    backend = _ParkedReadDown().add("w1", status="open")

    with pytest.raises(WorkError) as excinfo:
        ready(backend, _ready_args())

    # The transport code survives (a caller's retry logic keys on it); the
    # message names which of the verb's reads went down.
    assert excinfo.value.code is ErrorCode.BACKEND_DRIFT
    assert excinfo.value.detail["stage"] == "parked_stale"
    assert "ready" in excinfo.value.message


def test_claim_fails_typed_and_the_item_stays_unclaimed():  # S9T1-P4 (fail-closed)
    # ReadOnlyFakeBackend refuses `claim` outright, so reaching the mutation
    # would surface as an AssertionError rather than this WorkError.
    backend = _ParkedReadDown().add("w1", status="open")

    with pytest.raises(WorkError) as excinfo:
        claim(backend, _claim_args("w1"))

    assert excinfo.value.code is ErrorCode.BACKEND_DRIFT
    assert excinfo.value.detail["stage"] == "parked_stale"
    assert backend.get("w1").status == "open"


def test_claim_leaves_the_bd_mutation_log_empty_when_the_parked_read_fails():  # S9T1-P4
    # An error envelope must never hide an item this very call already took.
    item = BdResult(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "id": "w1",
                    "title": "T",
                    "issue_type": "task",
                    "status": "open",
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
            ScriptedStep(("show",), item),
            ScriptedStep(("ready",), item),
            ScriptedStep(("list",), BdResult(returncode=0, stdout="not json", stderr="")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["claim", "w1"], runner)

    error = envelope["error"]
    assert exit_code == 1
    assert isinstance(error, dict)
    assert isinstance(error["detail"], dict)
    assert error["detail"]["stage"] == "parked_stale"
    assert not any(call[0] == "update" for call in runner.calls)


def test_ready_never_issues_its_own_listing_once_the_parked_read_fails():  # S9T1-P4
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("list",), BdResult(returncode=0, stdout="not json", stderr=""))]
    )

    exit_code, envelope, _ = run_cli_with_runner(["ready"], runner)

    assert exit_code == 1
    assert envelope["data"] is None
    assert runner.calls == [("list", "--json", "--all", "--label", PARKED_LABEL, "--limit", "0")]


# --- S9T1-P5: an unreadable marker surfaces, it does not exempt ------------


def test_an_unparseable_marker_surfaces_with_null_reason_and_null_parked_at():  # S9T1-P5
    backend = ReadOnlyFakeBackend()
    backend.add("corrupt", status="blocked", labels=[PARKED_LABEL], notes="hand-written note")

    assert _block(ready(backend, _ready_args())) == [
        {
            "id": "corrupt",
            "title": "T",
            "reason": None,
            "category": None,
            "parked_at": None,
        }
    ]


def test_an_unreadable_timestamp_surfaces_too_though_parked_calls_it_not_stale():  # S9T1-P5
    # The deliberate divergence from S2-B7: `work parked` reports stale=false
    # when the age is unprovable; the block reports the item anyway. Unprovable
    # age must never be the reason an item escapes the surfacing.
    backend = ReadOnlyFakeBackend()
    _park(backend, "corrupt", parked_at="yesterday-ish")

    report = parked(backend, _parked_args())

    assert isinstance(report, dict)
    items = report["items"]
    assert isinstance(items, list)
    row = items[0]
    assert isinstance(row, dict)
    assert row["stale"] is False
    assert row["parked_at"] is None

    assert [
        entry["id"] for entry in _block(ready(backend, _ready_args())) if isinstance(entry, dict)
    ] == ["corrupt"]


def test_a_marker_head_of_the_wrong_shape_surfaces_rather_than_being_exempted():  # S9T1-P5
    # The other malformed-marker shape: a well-formed prefix whose head does
    # not split into exactly (timestamp, code). Both fields degrade to null,
    # and the item is still in the block -- there is no shape of corruption
    # that buys an item its way out of the surfacing.
    backend = ReadOnlyFakeBackend()
    backend.add(
        "corrupt",
        status="blocked",
        labels=[PARKED_LABEL],
        notes=f"{PARKED_MARKER} {_STALE_AT} ci-failure oops: CI red",
    )

    assert _block(ready(backend, _ready_args())) == [
        {
            "id": "corrupt",
            "title": "T",
            "reason": None,
            "category": None,
            "parked_at": None,
        }
    ]


def test_a_corrupt_marker_does_not_crash_the_verb_it_rides_on():  # S9T1-P5
    backend = FakeBackend().add("w1", status="open")
    backend.add("corrupt", status="blocked", labels=[PARKED_LABEL], notes="")

    data = claim(backend, _claim_args("w1"))

    assert isinstance(data, dict)
    assert data["status"] == "in_progress"
    assert len(_block(data)) == 1


# --- S9T1-P6: idempotent read ---------------------------------------------


def test_two_consecutive_ready_calls_return_identical_blocks_and_mutate_nothing():  # S9T1-P6
    backend = ReadOnlyFakeBackend()
    _park(backend, "stuck", parked_at=_STALE_AT)
    _park(backend, "corrupt", parked_at="not-a-date")

    first = ready(backend, _ready_args())
    second = ready(backend, _ready_args())

    assert first == second
    assert len(_block(first)) == 2
