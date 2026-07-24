"""close-walk atomicity (S2-C).

close + close-walk + note is ONE facade call: a non-milestone parent whose
last open child closes is exhausted and closes with it, recursively, with a
`[work] close-walk` note. Milestones are the boundary -- they never auto-close
on child exhaustion; closing one is always a deliberate, explicit close call.
State-based against `FakeBackend`, driving the real `close` and `deliver`
handlers.
"""

from __future__ import annotations

from argparse import Namespace

from tests.conftest import fake_reader
from tests.fake_backend import FakeBackend
from workcli.lifecycle import DELIVERED_MARKER
from workcli.lifecycle.closewalk import CLOSE_WALK_MARKER
from workcli.lifecycle.deliver import deliver
from workcli.verbs.write import close


def _close(backend: FakeBackend, ids: list[str], disposition: str | None = None):
    return close(backend, Namespace(ids=ids, disposition=disposition))


def test_closing_last_open_child_closes_the_epic_with_a_walk_note():  # S2-C1
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("c1", parent="E", status="closed")
        .add("c2", parent="E", status="open")
    )

    data = _close(backend, ["c2"], disposition="merged PR #7")

    assert backend.get("E").status == "closed"
    assert CLOSE_WALK_MARKER in backend.note_lines("E")
    assert "merged PR #7" in backend.note_lines("c2")
    assert data == {"walked": ["E"]}


def test_walk_recurses_through_exhausted_grandparent():  # S2-C2
    backend = (
        FakeBackend()
        .add("G", type="epic", labels=["shape-epic"])
        .add("E", type="epic", labels=["shape-epic"], parent="G")
        .add("c1", parent="E", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.get("E").status == "closed"
    assert backend.get("G").status == "closed"
    assert CLOSE_WALK_MARKER in backend.note_lines("E")
    assert CLOSE_WALK_MARKER in backend.note_lines("G")
    assert data == {"walked": ["E", "G"]}


def test_walk_stops_at_milestones():  # S2-C3
    backend = (
        FakeBackend()
        .add("M", type="milestone", labels=["shape-milestone"])
        .add("c1", parent="M", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.get("M").status == "open"
    assert backend.note_lines("M") == []
    assert data is None


def test_open_sibling_holds_the_parent_open():  # S2-C4 (inverse)
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("c1", parent="E", status="open")
        .add("c2", parent="E", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.get("E").status == "open"
    assert data is None


def test_already_closed_parent_is_not_reclosed_or_renoted():  # S2-C4 (idempotency)
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"], status="closed")
        .add("c1", parent="E", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.note_lines("E") == []
    assert data is None


def test_sibling_batch_close_walks_the_parent_exactly_once():  # S2-C4 (repeated)
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("c1", parent="E", status="open")
        .add("c2", parent="E", status="open")
    )

    data = _close(backend, ["c1", "c2"])

    assert backend.get("E").status == "closed"
    assert backend.note_lines("E").count(CLOSE_WALK_MARKER) == 1
    assert data == {"walked": ["E"]}


def test_deliver_leaf_triggers_the_same_walk():  # S2-C5
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("L", parent="E", status="in_progress", labels=["shape-feat"])
    )
    args = Namespace(
        id="L", spec=None, pr="42", items=None, trivial=False, read_file=fake_reader({})
    )

    data = deliver(backend, args)

    assert backend.get("L").status == "closed"
    assert any(line.startswith(DELIVERED_MARKER) for line in backend.note_lines("L"))
    assert backend.get("E").status == "closed"
    assert CLOSE_WALK_MARKER in backend.note_lines("E")
    assert data == {"id": "L", "status": "closed", "walked": ["E"]}


def test_deliver_replay_on_closed_leaf_resumes_the_walk():  # S2-C5 (crash replay)
    # Crash window: the leaf closed but the walk never ran. The deliver
    # replay short-circuits the evidence check yet must still settle the
    # parent chain.
    backend = (
        FakeBackend()
        .add("E", type="epic", labels=["shape-epic"])
        .add("L", parent="E", status="closed", labels=["shape-feat"])
    )
    args = Namespace(
        id="L", spec=None, pr=None, items=None, trivial=False, read_file=fake_reader({})
    )

    data = deliver(backend, args)

    assert backend.get("E").status == "closed"
    assert CLOSE_WALK_MARKER in backend.note_lines("E")
    assert data == {"id": "L", "status": "closed", "walked": ["E"]}
