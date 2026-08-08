"""close-walk atomicity (S2-C).

close + close-walk + note is ONE facade call: a non-milestone parent whose
last open child closes is exhausted and closes with it, recursively, with a
`[work] close-walk` note. Milestones are the boundary -- they never auto-close
on child exhaustion; closing one is always a deliberate, explicit close call.
A parent carrying scope of its own is the other boundary: exhausting its
children says nothing about that scope, so the walk holds it and reports why.
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


def test_parent_carrying_scope_of_its_own_is_held_open_though_every_child_closed():
    """
    Given a parent whose shape is a leaf's, with every child closed
    When the last child closes
    Then the parent stays open and the walk reports it as held.

    The completion the walk infers is a claim about the parent, and a parent
    that is not a declared container carries scope of its own that closing
    its children says nothing about.
    """
    backend = (
        FakeBackend()
        .add("P", type="feature", labels=["shape-feat"], acceptance="AC1 the tool ships")
        .add("c1", parent="P", status="closed")
        .add("c2", parent="P", status="open")
    )

    data = _close(backend, ["c2"])

    assert backend.get("P").status == "open"
    assert backend.note_lines("P") == []
    assert [entry["id"] for entry in data["held"]] == ["P"]
    assert "walked" not in data


def test_the_hold_names_the_item_its_criteria_and_the_two_ways_out():
    """
    Given a held parent carrying acceptance criteria
    When the walk reports the hold
    Then the entry carries what the caller needs to act without re-reading it.

    The criteria are the terms the parent's own completion is judged in, so
    they travel with the hold rather than costing a second read.
    """
    backend = (
        FakeBackend()
        .add("P", title="ship the thing", type="feature", labels=["shape-feat"], acceptance="AC1 x")
        .add("c1", parent="P", status="open")
    )

    entry = _close(backend, ["c1"])["held"][0]

    assert set(entry) == {"id", "title", "reason", "acceptance", "resolve"}
    assert entry["id"] == "P"
    assert entry["title"] == "ship the thing"
    assert entry["acceptance"] == "AC1 x"
    assert entry["reason"]
    assert "deliver P" in entry["resolve"] and "close P" in entry["resolve"]


def test_a_parent_whose_own_delivery_is_recorded_still_closes_on_exhaustion():
    """
    Given a leaf-shaped parent whose delivery is recorded but which never closed
    When its last child closes
    Then the walk closes it.

    The delivery marker is the record that the parent's own scope is done, so
    the hold lifts. This is the window `deliver` already replays through: the
    marker is appended before the close, and a crash between the two leaves
    exactly this state.
    """
    backend = (
        FakeBackend()
        .add("P", type="feature", labels=["shape-feat"], notes=f"{DELIVERED_MARKER} 42")
        .add("c1", parent="P", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.get("P").status == "closed"
    assert CLOSE_WALK_MARKER in backend.note_lines("P")
    assert data == {"walked": ["P"]}


def test_a_held_parent_stops_the_walk_below_its_own_parent():
    """
    Given a held parent under an exhausted container
    When the walk reaches the hold
    Then the container above it is neither closed nor reported.

    A held parent is still open, so its own parent is not exhausted -- the
    grandparent is simply not eligible, which is not a refusal to report.
    """
    backend = (
        FakeBackend()
        .add("G", type="epic", labels=["shape-epic"])
        .add("P", type="feature", labels=["shape-feat"], parent="G")
        .add("c1", parent="P", status="open")
    )

    data = _close(backend, ["c1"])

    assert backend.get("G").status == "open"
    assert backend.note_lines("G") == []
    assert [entry["id"] for entry in data["held"]] == ["P"]


def test_a_sibling_batch_reports_one_hold_per_parent():
    """
    Given two children of one held parent, closed in a single call
    When both walks meet the same parent
    Then it is reported held exactly once.

    Same convergence the walked list already has, on the other outcome: a
    caller reading two entries would think two items need attention.
    """
    backend = (
        FakeBackend()
        .add("P", type="feature", labels=["shape-feat"])
        .add("c1", parent="P", status="open")
        .add("c2", parent="P", status="open")
    )

    data = _close(backend, ["c1", "c2"])

    assert [entry["id"] for entry in data["held"]] == ["P"]


def test_naming_a_parent_on_close_is_the_discharge_and_is_never_held():
    """
    Given a parent the walk would hold
    When the caller closes it by name
    Then it closes, unexamined.

    The rule governs what the walk infers, never what a caller states. That
    boundary is what keeps the hold dischargeable in one command.
    """
    backend = FakeBackend().add("P", type="feature", labels=["shape-feat"])

    data = _close(backend, ["P"])

    assert backend.get("P").status == "closed"
    assert data is None


def test_deliver_reaches_the_same_hold_as_close():
    """
    Given a leaf under a parent carrying scope of its own
    When the leaf is delivered rather than closed
    Then the same parent is held, reported the same way.

    Both verbs run one walk; a rule that held on one path and not the other
    would be two rules.
    """
    backend = (
        FakeBackend()
        .add("P", type="feature", labels=["shape-feat"])
        .add("L", parent="P", status="in_progress", labels=["shape-feat"])
    )
    args = Namespace(
        id="L", spec=None, pr="42", items=None, trivial=False, read_file=fake_reader({})
    )

    data = deliver(backend, args)

    assert backend.get("P").status == "open"
    assert data["id"] == "L" and data["status"] == "closed"
    assert [entry["id"] for entry in data["held"]] == ["P"]
    assert "walked" not in data


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
