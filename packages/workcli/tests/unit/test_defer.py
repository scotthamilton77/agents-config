"""defer / undefer -- setting an idea aside, and picking it back up.

Deferred = the backend's `deferred` status and nothing else: no label, no
reason vocabulary, no staleness clock. The state is what tells an idea from
an obstruction, so these tests hold two lines above all others -- a deferred
item is absent from `ready` and from both parked surfaces, and a read
envelope tells it from a parked item without any note being read.

Idempotency is pinned on `park`/`redispatch`'s own terms: state is read
first, an already-applied transition returns without writing, and a replay
after a crash between the two writes converges on one marker rather than
minting a second.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime

import pytest

from tests.fake_backend import FakeBackend, ReadOnlyFakeBackend
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.defer import (
    DEFERRED_MARKER,
    DEFERRED_STATUS,
    REPAIR_TEXT,
    UNDEFERRED_MARKER,
    defer,
    undefer,
)
from workcli.lifecycle.park import PARKED_LABEL, park, parked
from workcli.lifecycle.transitions import claim
from workcli.verbs.read import list_, ready, show
from workcli.verbs.write import close

_NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
_ISO = _NOW.isoformat()
_LONG_AGO = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat()


def _defer_args(item_id: str, note: str | None = None) -> Namespace:
    return Namespace(id=item_id, note=note, now=lambda: _NOW)


def _id_args(item_id: str) -> Namespace:
    return Namespace(id=item_id, now=lambda: _NOW)


def _park_args(item_id: str, reason: str) -> Namespace:
    return Namespace(id=item_id, reason=reason, note=None, now=lambda: _NOW)


def _ready_args() -> Namespace:
    return Namespace(label=None, now=lambda: _NOW)


def _parked_args() -> Namespace:
    return Namespace(stale_days=7, now=lambda: _NOW)


# --- AC1: the two transitions -----------------------------------------------


def test_defer_moves_an_open_item_to_deferred_and_records_a_marker():
    backend = FakeBackend().add("w1", status="open")

    data = defer(backend, _defer_args("w1", note="nobody has picked this up"))

    item = backend.get("w1")
    assert item.status == DEFERRED_STATUS
    # No label and no reason code: the status carries the whole state, which
    # is what keeps a deferral out of every surface keyed on the park handle.
    assert item.labels == []
    assert backend.note_lines("w1") == [f"{DEFERRED_MARKER} {_ISO}: nobody has picked this up"]
    assert data == {"id": "w1", "status": "deferred"}


def test_defer_without_a_note_records_a_bare_timestamped_marker():
    backend = FakeBackend().add("w1", status="open")

    defer(backend, _defer_args("w1"))

    assert backend.note_lines("w1") == [f"{DEFERRED_MARKER} {_ISO}"]


def test_defer_accepts_a_claimed_item():
    """Setting down work already in hand is a deferral like any other.

    `release` is the verb for handing a claim back, and requiring it first
    would make "not now" a two-call sequence for the one case where the
    caller has most obviously decided it.
    """
    backend = FakeBackend().add("w1", status="in_progress")

    data = defer(backend, _defer_args("w1"))

    assert backend.get("w1").status == DEFERRED_STATUS
    assert data == {"id": "w1", "status": "deferred"}


def test_undefer_returns_a_deferred_item_to_open_with_its_own_marker():
    backend = FakeBackend().add("w1", status="open")
    defer(backend, _defer_args("w1"))

    data = undefer(backend, _id_args("w1"))

    assert backend.get("w1").status == "open"
    assert backend.note_lines("w1") == [
        f"{DEFERRED_MARKER} {_ISO}",
        f"{UNDEFERRED_MARKER} {_ISO}",
    ]
    assert data == {"id": "w1", "status": "open"}


# --- AC2: out of `ready`, and no nag on either parked surface ----------------


def test_a_deferred_item_leaves_the_ready_queue():
    backend = FakeBackend().add("w1", status="open").add("w2", status="open")
    before = ready(backend, _ready_args())
    assert isinstance(before, dict)
    assert {row["id"] for row in before["items"]} == {"w1", "w2"}

    defer(backend, _defer_args("w1"))

    after = ready(backend, _ready_args())
    assert isinstance(after, dict)
    assert {row["id"] for row in after["items"]} == {"w2"}


def test_a_deferred_item_raises_no_staleness_nag_on_either_parked_surface():
    backend = FakeBackend().add("w1", status="open")

    defer(backend, _defer_args("w1"))

    assert parked(backend, _parked_args()) == {"items": [], "stale_days": 7}
    block = ready(backend, _ready_args())
    assert isinstance(block, dict)
    assert block["parked_stale"] == []


def test_an_ancient_deferral_still_raises_no_nag():
    """The nag is what a park earns and a deferral does not.

    A park ages into a report because an obstruction left alone is a fact
    someone must act on. An idea nobody has started is not decaying, so no
    amount of elapsed time turns a deferral into something to surface -- and
    both parked surfaces read the park handle, which a deferral never sets.
    """
    backend = ReadOnlyFakeBackend().add(
        "w1", status=DEFERRED_STATUS, notes=f"{DEFERRED_MARKER} {_LONG_AGO}"
    )

    assert parked(backend, _parked_args()) == {"items": [], "stale_days": 7}
    block = ready(backend, _ready_args())
    assert isinstance(block, dict)
    assert block["parked_stale"] == []


# --- AC3: legible apart in a read envelope, with no prose parsed -------------


def test_a_read_envelope_tells_a_deferred_item_from_a_parked_one():
    backend = FakeBackend().add("idea", status="open").add("stuck", status="in_progress")

    defer(backend, _defer_args("idea"))
    park(backend, _park_args("stuck", "ci-failure"))

    idea = show(backend, Namespace(ids=["idea"]))
    stuck = show(backend, Namespace(ids=["stuck"]))
    assert isinstance(idea, dict)
    assert isinstance(stuck, dict)
    assert idea["status"] == "deferred"
    assert stuck["status"] == "blocked"
    assert PARKED_LABEL not in idea["labels"]
    assert PARKED_LABEL in stuck["labels"]


def test_the_two_states_stay_legible_apart_with_every_note_removed():
    """AC3's actual bar: a reader parses no prose to tell them apart.

    The park family records its reason in a note marker, so a check that
    read one would be reading the very prose this criterion rules out.
    Both items here carry no notes at all, and the envelope still answers.
    """
    backend = ReadOnlyFakeBackend()
    backend.add("idea", status=DEFERRED_STATUS, notes="")
    backend.add("stuck", status="blocked", labels=[PARKED_LABEL], notes="")

    idea = show(backend, Namespace(ids=["idea"]))
    stuck = show(backend, Namespace(ids=["stuck"]))

    assert isinstance(idea, dict)
    assert isinstance(stuck, dict)
    assert idea["notes"] == stuck["notes"] == ""
    assert idea["status"] != stuck["status"]
    assert (idea["status"], PARKED_LABEL in idea["labels"]) == ("deferred", False)
    assert (stuck["status"], PARKED_LABEL in stuck["labels"]) == ("blocked", True)


# --- AC4: idempotent on replay, on park's own terms --------------------------


def test_defer_replay_is_a_noop_that_writes_nothing():
    """A lost response makes the caller re-issue `defer`; the replay writes nothing.

    Run against a backend that raises on every mutator, so "returned before
    writing" is proven rather than inferred from a state comparison.
    """
    backend = FakeBackend().add("w1", status="open")
    first = defer(backend, _defer_args("w1"))
    settled = backend.get("w1")
    replay_backend = ReadOnlyFakeBackend().add(
        "w1", status=settled.status, labels=settled.labels, notes=settled.notes
    )

    second = defer(replay_backend, _defer_args("w1"))

    assert first == second == {"id": "w1", "status": "deferred"}
    assert replay_backend.note_lines("w1") == [f"{DEFERRED_MARKER} {_ISO}"]


def test_defer_replay_repairs_the_marker_a_crashed_defer_never_wrote():
    """The status lands first, so a crash between the two writes loses the marker.

    The status then short-circuits every later defer, which makes this branch
    the only one that can ever mint it. The repaired marker says so in its
    free text: the instant it carries is the repairing call's, because the
    crashed call's is unrecoverable.
    """
    backend = FakeBackend().add("w1", status=DEFERRED_STATUS)

    data = defer(backend, _defer_args("w1", note="nobody has picked this up"))

    assert backend.note_lines("w1") == [
        f"{DEFERRED_MARKER} {_ISO}: {REPAIR_TEXT}; nobody has picked this up"
    ]
    assert data == {"id": "w1", "status": "deferred"}


def test_undefer_replay_is_a_noop_that_writes_nothing():
    backend = FakeBackend().add("w1", status="open")
    defer(backend, _defer_args("w1"))
    first = undefer(backend, _id_args("w1"))
    settled = backend.get("w1")
    replay_backend = ReadOnlyFakeBackend().add(
        "w1", status=settled.status, labels=settled.labels, notes=settled.notes
    )

    second = undefer(replay_backend, _id_args("w1"))

    assert first == second == {"id": "w1", "status": "open"}
    lines = replay_backend.note_lines("w1")
    assert sum(1 for line in lines if line.startswith(UNDEFERRED_MARKER)) == 1


def test_undefer_replays_after_a_crash_between_its_two_writes_without_a_second_marker():
    """`undefer` mints its marker first, so the crash window keeps the item deferred.

    That is the point of the ordering: the status is the handle a replay
    re-enters on, so a replay reaches this path again rather than the
    already-open no-op, and the transition never ends up unrecorded. The
    dedup guard is what stops it minting a second, later-stamped marker.
    """
    backend = FakeBackend().add(
        "w1",
        status=DEFERRED_STATUS,
        notes=f"{DEFERRED_MARKER} {_LONG_AGO}\n{UNDEFERRED_MARKER} {_LONG_AGO}",
    )

    data = undefer(backend, _id_args("w1"))

    assert backend.get("w1").status == "open"
    assert backend.note_lines("w1") == [
        f"{DEFERRED_MARKER} {_LONG_AGO}",
        f"{UNDEFERRED_MARKER} {_LONG_AGO}",
    ]
    assert data == {"id": "w1", "status": "open"}


def test_a_second_deferral_after_an_undefer_records_a_fresh_stint():
    """Marker history accumulates; the last one is the current stint.

    A re-deferred item must not be read as still carrying its first stint,
    and the un-defer marker in between is what makes the second defer mint
    rather than short-circuit.
    """
    backend = FakeBackend().add(
        "w1",
        status="open",
        notes=f"{DEFERRED_MARKER} {_LONG_AGO}\n{UNDEFERRED_MARKER} {_LONG_AGO}",
    )

    defer(backend, _defer_args("w1"))

    assert backend.note_lines("w1") == [
        f"{DEFERRED_MARKER} {_LONG_AGO}",
        f"{UNDEFERRED_MARKER} {_LONG_AGO}",
        f"{DEFERRED_MARKER} {_ISO}",
    ]


def test_undefer_on_an_open_item_is_an_idempotent_noop():
    backend = ReadOnlyFakeBackend().add("w1", status="open")

    data = undefer(backend, _id_args("w1"))

    assert data == {"id": "w1", "status": "open"}
    assert backend.note_lines("w1") == []


# --- refusals ---------------------------------------------------------------


def test_defer_refuses_a_closed_item():
    backend = FakeBackend().add("w1", status="closed")

    with pytest.raises(WorkError) as excinfo:
        defer(backend, _defer_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE


def test_defer_refuses_a_parked_item_and_names_the_verbs_that_clear_it():
    """The two axes are different claims, and one item may not hold both.

    Overwriting `blocked` with `deferred` under a `parked` label would leave
    an item the parked report still lists and a read envelope calls deferred
    -- exactly the ambiguity the separate status exists to remove.
    """
    backend = FakeBackend().add("w1", status="in_progress")
    park(backend, _park_args("w1", "ci-failure"))

    with pytest.raises(WorkError) as excinfo:
        defer(backend, _defer_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE
    assert "redispatch" in excinfo.value.message
    assert "abandon" in excinfo.value.message
    # Refused before writing: the park is intact.
    item = backend.get("w1")
    assert item.status == "blocked"
    assert PARKED_LABEL in item.labels


def test_undefer_refuses_a_closed_item():
    backend = FakeBackend().add("w1", status="closed")

    with pytest.raises(WorkError) as excinfo:
        undefer(backend, _id_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE


def test_undefer_refuses_an_item_that_was_never_deferred():
    backend = FakeBackend().add("w1", status="in_progress")

    with pytest.raises(WorkError) as excinfo:
        undefer(backend, _id_args("w1"))

    assert excinfo.value.code is ErrorCode.USAGE
    assert "in_progress" in excinfo.value.message


def test_a_deferred_item_is_not_claimable_and_the_refusal_names_undefer():
    """The generic refusal would name a cause a deferred item does not have.

    Without this branch the item falls through to "blocked by an open
    dependency", sending its caller to look for a blocker that does not
    exist -- the same reason the parked branch beside it was written.
    """
    backend = FakeBackend().add("w1", status="open")
    defer(backend, _defer_args("w1"))

    with pytest.raises(WorkError) as excinfo:
        claim(backend, _id_args("w1"))

    assert excinfo.value.code is ErrorCode.NOT_CLAIMABLE
    assert "deferred" in excinfo.value.message
    assert "undefer" in excinfo.value.message


# --- the close-walk: a deferred child is not a closed one -------------------


def test_a_deferred_sibling_holds_its_parent_open_in_the_close_walk():
    """Setting an idea aside is not finishing it, and the walk must not read it so.

    The walk closes a parent whose children are exhausted. A deferred child
    is live work nobody has started, so the parent is not exhausted and must
    stay open -- reading `deferred` as "does not count" would auto-close a
    container with real work still in it, on the strength of a decision to
    postpone.

    It stops on the not-yet-exhausted branch, not the held one: `held` is for
    a parent whose children ARE all closed and whose own scope is unfinished,
    which is a different claim and would misreport this parent as looking
    finished.
    """
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("idea", parent="E", status="open")
        .add("work", parent="E", status="open")
    )
    defer(backend, _defer_args("idea"))

    data = close(backend, Namespace(ids=["work"], disposition=None))

    assert backend.get("E").status == "open"
    assert data is None  # neither walked nor held: nothing to report


def test_undeferring_the_last_child_then_closing_it_lets_the_walk_through():
    """The inverse, so the hold above is the deferral's doing and not the fixture's."""
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("idea", parent="E", status="open")
        .add("work", parent="E", status="closed")
    )
    defer(backend, _defer_args("idea"))
    undefer(backend, _id_args("idea"))

    data = close(backend, Namespace(ids=["idea"], disposition=None))

    assert backend.get("E").status == "closed"
    assert data == {"walked": ["E"]}


# --- CLI wiring (argparse surface, envelope, and mutation order) ------------


def _show_step(status: str, labels: list[str], notes: str):
    import json as _json

    from tests.fakes import ScriptedStep
    from workcli.adapters.bd.runner import BdResult

    return ScriptedStep(
        ("show",),
        BdResult(
            returncode=0,
            stdout=_json.dumps(
                [
                    {
                        "id": "w1",
                        "title": "T",
                        "issue_type": "task",
                        "status": status,
                        "priority": 2,
                        "labels": labels,
                        "parent": None,
                        "notes": notes,
                        "dependencies": [],
                        "dependents": [],
                    }
                ]
            ),
            stderr="",
        ),
    )


def test_cli_defer_wires_the_status_before_the_marker():
    from tests.conftest import run_cli_with_runner
    from tests.fakes import ScriptedBdRunner, ScriptedStep
    from workcli.adapters.bd.runner import BdResult

    ok = BdResult(returncode=0, stdout="", stderr="")
    runner = ScriptedBdRunner(
        steps=[
            _show_step("open", [], ""),
            ScriptedStep(("update", "w1", "--status", DEFERRED_STATUS), ok),
            ScriptedStep(("update", "w1", "--append-notes"), ok),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["defer", "w1", "--note", "later"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "w1", "status": "deferred"}
    assert [call[:2] for call in runner.calls] == [
        ("show", "w1"),
        ("update", "w1"),
        ("update", "w1"),
    ]


def test_cli_undefer_records_the_marker_before_clearing_the_status():
    from tests.conftest import run_cli_with_runner
    from tests.fakes import ScriptedBdRunner, ScriptedStep
    from workcli.adapters.bd.runner import BdResult

    ok = BdResult(returncode=0, stdout="", stderr="")
    runner = ScriptedBdRunner(
        steps=[
            _show_step(DEFERRED_STATUS, [], f"{DEFERRED_MARKER} {_LONG_AGO}"),
            ScriptedStep(("update", "w1", "--append-notes"), ok),
            ScriptedStep(("update", "w1", "--status", "open"), ok),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["undefer", "w1"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"id": "w1", "status": "open"}
    assert [call[:2] for call in runner.calls] == [
        ("show", "w1"),
        ("update", "w1"),
        ("update", "w1"),
    ]


def test_a_deferred_item_is_still_listed():
    """Deferring takes an item out of the work queue, not out of the tracker.

    `ready` answers "what may I pick up"; `list` answers "what exists". An
    idea set aside has to stay findable, or setting it aside becomes a way
    to lose it -- so a filter that also hid it from `list` would satisfy the
    ready criterion by breaking the thing the state is for.
    """
    backend = FakeBackend().add("w1", status="open")
    defer(backend, _defer_args("w1"))

    listed = list_(
        backend,
        Namespace(status=None, label=None, parent=None, type=None, limit=None, track=None),
    )

    assert isinstance(listed, dict)
    assert [row["id"] for row in listed["items"]] == ["w1"]
    assert listed["items"][0]["status"] == "deferred"
