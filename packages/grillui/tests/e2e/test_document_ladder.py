"""What happens to a grill-master turn that is not the map document (GMR-A2).

The ladder is one retry on the seat that failed, then one rung up, then the
human is told -- and at no point are the bytes that failed shown to them as
prose. That last part is the whole point of refusing rather than recording: a
reply the board could not read is not made readable by printing it, and a human
handed a model's raw JSON has been given the backend's problem to solve.

The retry is worth taking only because it quotes the fault. A seat told it was
wrong guesses at a second shape; a seat told `rulings` was missing supplies it,
which is why the fault text is asserted inside the second prompt rather than the
retry merely being counted.

Two valid documents walk the same ground for different reasons: one that carries
nothing at all appends no entry, and one that withdraws with nothing to ride on
is refused before it gets that far.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from conftest import decision, document, handoff, lane, notices, option, turn

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Page

# A clerical answer, so the turn starts on the first rung and the whole ladder
# is walked. A decision whose option pre-marks a live one is classed before a
# model is called and starts at the expert instead, which is a different case.
PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]

# A plan whose answer leaves decisions the board is still offering, which is
# what obliges a ruling on each of them.
MARKED = [
    decision(
        "d1",
        "Which storage?",
        options=[option("a", "Append-only log", ["d2", "d3"]), option("b", "Table")],
    ),
    decision("d2", "How is it compacted?"),
    decision("d3", "What is retained?"),
]

# What a model sends when it has lost the shape. Distinctive enough that its
# absence from the log and from the page is a real assertion.
PROSE = "I think the append-only log is fine, honestly."
MISSING_RULINGS = json.dumps(
    {"text": "The store is settled.", "updates": [], "supersedes": [], "stop": {"met": False}}
)


def answer(page: Page, node: str, chosen: str = "a") -> None:
    page.click(f'#col-{node} [data-act="pick"][data-opt="{chosen}"]')


def test_a_reply_that_is_not_the_document_is_retried_once_then_handed_up_then_said(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a first-rung seat that answers in prose and then in an object missing
         a key, and an expert that does the same
    When the human answers a decision
    Then the first seat was asked twice with the second ask quoting the fault,
         the turn was handed up to the expert, which was also asked twice, the
         human is told that nothing was taken from the turn, the lane closes on
         an error naming the seat the ladder ended on -- and not one byte of
         either refused reply is anywhere in the log or on the page.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(PROSE), turn(MISSING_RULINGS))
    session.script_claude(turn(PROSE), turn(MISSING_RULINGS))
    page = board(session)

    answer(page, "d1")
    session.settled()

    # One retry on the seat that failed, and the retry quotes the key.
    codex = session.codex_calls()
    assert len(codex) == 2, f"the first rung was asked {len(codex)} times"
    assert "Your last reply was refused" not in codex[0]["prompt"], "the first ask was a retry"
    assert "Your last reply was refused" in codex[1]["prompt"], codex[1]["prompt"][-400:]
    assert "the reply was prose, not the map document" in codex[1]["prompt"]

    # Then one rung up, where the same two asks happen and the fault named is
    # that seat's own -- the second reply's, not the first seat's.
    claude = session.claude_calls()
    assert len(claude) == 2, f"the expert was asked {len(claude)} times"
    assert "rulings" in claude[1]["prompt"], claude[1]["prompt"][-400:]

    # The human is told, once, and told about the seat the ladder ended on.
    said = notices(session.entries())
    assert any("'heavy' tier answered in a shape the board cannot read" in one for one in said), (
        said
    )
    phases = lane(session.entries(), "map")
    assert phases[-1][0] == "error", phases
    detail = [
        one.payload["detail"]
        for one in session.entries()
        if one.kind == "status" and one.payload.get("phase") == "error"
    ]
    assert "'heavy' tier failed" in detail[-1], detail[-1]

    # Nothing the seats actually said reached the human, by either route.
    written = (session.directory / "log.jsonl").read_text(encoding="utf-8")
    assert PROSE not in written, "the refused bytes were recorded"
    assert "The store is settled." not in written, "the refused document's prose was recorded"
    assert PROSE not in page.locator("#shell").inner_text(), "the refused bytes were rendered"


def test_a_withdrawal_with_nothing_to_ride_on_is_a_document_problem_and_walks_the_ladder(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a seat whose turn withdraws a queue item and gives nothing to record
         the withdrawal on
    When the human answers a decision
    Then the turn is refused as a document problem naming `supersedes`, retried
         on the same seat with that fault quoted, and handed up like any other.

    A withdrawal rides on an entry, so a turn that withdrew and said nothing has
    no entry to put it on and the gesture is lost. It is caught where the seat
    still has its retry, because adding a line of `text` is exactly the fix a
    seat can make.
    """
    session = launcher(handoff=handoff(PLAN))
    bare = document(text="", supersedes=["n-1"])
    session.script_codex(turn(bare), turn(bare))
    session.script_claude(turn(bare), turn(bare))
    page = board(session)

    answer(page, "d1")
    session.settled()

    codex = session.codex_calls()
    assert len(codex) == 2, codex
    assert "supersedes: a withdrawal needs" in codex[1]["prompt"], codex[1]["prompt"][-300:]
    assert len(session.claude_calls()) == 2, session.claude_calls()
    assert lane(session.entries(), "map")[-1][0] == "error"


def test_a_valid_document_carrying_nothing_appends_nothing_and_leaves_the_obligation_standing(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an answer whose option puts two live decisions in question, and a seat
         whose document is valid and entirely empty
    When the human answers it
    Then the turn appends no entry at all -- no notice, no proposal, no ruling --
         the board is still offering both decisions, and the human is told by
         name which ones went unruled.

    Appending nothing is right: every entry shape here holds content, and
    inventing some would put words in the agent's mouth. What the turn owed is
    then decided by the coverage check rather than by the turn having failed.
    """
    session = launcher(handoff=handoff(MARKED))
    empty = document(text="")
    session.script_claude(turn(empty))
    page = board(session)

    answer(page, "d1")
    session.settled()

    # The gesture is classed before a model is called, so it is the expert seat
    # that takes it and the first rung records no turn at all.
    assert not session.codex_calls(), "a first-rung turn was recorded for a classed gesture"
    assert len(session.claude_calls()) == 1, session.claude_calls()
    assert [one for one in session.entries() if one.actor == "grill-master"] == []

    # Both decisions are named back to the human, and both are still offered.
    said = notices(session.entries())
    unmet = [one for one in said if "not ruled on" in one]
    assert len(unmet) == 1, said
    assert "d2" in unmet[0] and "d3" in unmet[0], unmet[0]
    offered = {one["id"]: one["status"] for one in session.board()["decisions"]}
    assert offered["d2"] == "open" and offered["d3"] == "open", offered
