"""Starting a session from a handoff, resuming one from its log, and the
inversion that separates the two.

Every claim here is asserted against durable state -- the log, the images on
disk, the recorded dispatch bytes -- rather than against the object under test.
That is the point of the inversion: what a running process believes is exactly
what a fresh one must be able to rebuild from files alone, so a test that asked
the process would be asking the wrong witness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import TIMEOUT, SpyDriver, driven, event, handoff_doc, run_turns, write_handoff

from grillui.dispatch import DISPATCH_DIR
from grillui.lane import Lane, close_dead_turns, unclosed_turns
from grillui.log import IMAGE1_FILE, IMAGE2_FILE, LOG_FILE, SessionLog, read_entries
from grillui.persistence import project_and_persist
from grillui.projector import fold, to_image1
from grillui.schemas import (
    MAP_CHANNEL,
    SESSION_START_KIND,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_ERROR,
    STATUS_PHASE_REPLIED,
    EventSubmission,
    Image1,
)
from grillui.session import HandoffRefusedError, open_session

THREAD = "t1"
FIXED_EPOCH = "fixed"


def image1(log: SessionLog) -> Image1:
    return to_image1(fold(log.epoch, log.entries()))


def board_json(log: SessionLog) -> str:
    """The board with the tenure factored out.

    Epoch is whose process wrote the entries, not what the board says, so a
    comparison across a restart has to hold it fixed or it compares process
    identity instead of board content.
    """
    return to_image1(fold(FIXED_EPOCH, log.entries())).model_dump_json()


def on_disk(session_dir: Path) -> dict[str, Any]:
    """Image 1 as the session directory holds it, never as a process holds it."""
    parsed: dict[str, Any] = json.loads((session_dir / IMAGE1_FILE).read_text(encoding="utf-8"))
    return parsed


def untouched(session_dir: Path) -> bool:
    """Nothing of a session exists here."""
    return not session_dir.exists() or not any(
        (session_dir / name).exists() for name in (LOG_FILE, IMAGE1_FILE, IMAGE2_FILE)
    )


# ── GUI-A26: the handoff seeds the board, or is refused naming the field ──


def test_a_conforming_handoff_seeds_every_decision_prereq_and_option_it_names(
    session_dir: Path,
) -> None:
    """
    Given a handoff naming two decisions, one with a prereq, a mandate, talk
         seeds and a fog rule
    When the backend starts a session on it
    Then every decision, prereq and option it named is on the board, carrying
         the optional parts of the node shape it declared.

    The seeding is read back through the fold rather than from the handoff, so
    what is asserted is the board a fresh process would rebuild.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))

    board = image1(log)
    first, second = board.decisions
    assert [node.id for node in board.decisions] == ["d1", "d2"]
    assert first.short == "Store"
    assert first.title == "Which storage?"
    assert first.body == "Pick the storage layer."
    assert [(option.id, option.text) for option in first.options] == [
        ("a", "Append-only log"),
        ("b", "Mutable table"),
    ]
    assert first.options[0].pcr == ["audit", "size", "compaction"]
    assert first.talk == {"why": "Recovery rests on it.", "zoom": "Consider a crash mid-write."}
    assert second.prereqs == ["d1"]
    assert second.mandate is not None
    assert second.mandate["threadId"] == "t-compaction"
    assert second.fog_until == "d1"
    assert second.fog_title == "Settle the store first"


@pytest.mark.parametrize(
    ("declared", "seeded"),
    [
        ({"why": "Recovery rests on it."}, {"why": "Recovery rests on it."}),
        ({"zoom": "Consider a crash mid-write."}, {"zoom": "Consider a crash mid-write."}),
        (
            {"why": "Recovery rests on it.", "zoom": "Consider a crash mid-write."},
            {"why": "Recovery rests on it.", "zoom": "Consider a crash mid-write."},
        ),
        (None, None),
        ({}, None),
    ],
    ids=["why-alone", "zoom-alone", "both", "none-declared", "empty-object"],
)
def test_each_talk_seed_a_handoff_declares_reaches_the_board_on_its_own(
    session_dir: Path, declared: dict[str, str] | None, seeded: dict[str, str] | None
) -> None:
    """
    Given a handoff whose decision declares one seed, both, neither, or an empty
         talk object
    When the backend starts a session on it
    Then it is accepted, and the board carries exactly the seeds declared.

    The two seeds are separate controls on the thread pane, so an author with a
    `why` and no `zoom` has written a complete briefing; refusing it would be
    the backend insisting on prompt text nobody needed. The empty object is the
    other end of the same rule: a talk with no seed in it is no talk, and it
    reaches the board as nothing rather than as a seed set with no seeds.
    """
    document = handoff_doc()
    decision = document["plan"]["decisions"][0]
    if declared is None:
        del decision["talk"]
    else:
        decision["talk"] = declared

    log = open_session(session_dir, write_handoff(session_dir, document))

    assert image1(log).decisions[0].talk == seeded


def test_the_seeded_board_is_reproduced_by_re_folding_the_log_alone(session_dir: Path) -> None:
    """
    Given a session seeded from a handoff
    When the log is folded by a reader that never sees the handoff file
    Then it yields the same board.

    This is the invariant the whole inversion rests on: the briefing is seeded
    through the log, so recovery never has to consult a file the human may have
    edited since.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    (session_dir / "handoff.json").unlink()

    rebuilt = fold("later-tenure", read_entries(session_dir / LOG_FILE))

    assert [node.id for node in rebuilt.decisions] == [node.id for node in image1(log).decisions]
    assert rebuilt.frontier == image1(log).frontier


def test_a_seeded_decision_is_answerable_without_being_added_again(session_dir: Path) -> None:
    """
    Given a board seeded from a handoff
    When the human answers a decision the handoff named
    Then it is accepted and settles.

    The appender judges a write against its own node index, which the seeding
    has to reach. Without it the human's first answer of the session comes back
    as an unknown node id.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    client = driven(log, SpyDriver())

    receipts = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "answer",
                    actor="human",
                    key="a1",
                    target="d1",
                    answer={"option": "a"},
                    why="the audit trail is the point",
                )
            ],
        },
    ).json()

    assert receipts[0]["status"] == "accepted"
    assert [item.id for item in image1(log).settled] == ["d1"]


def test_only_the_unfogged_frontier_is_answerable_at_the_start(session_dir: Path) -> None:
    """
    Given a handoff whose second decision is fogged behind the first
    When the session starts
    Then only the first decision is on the frontier.

    The fog rule is derived from the seeded board rather than asserted by the
    handoff, which is what keeps the status one fact instead of two.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))

    board = image1(log)
    assert board.frontier == ["d1"]
    assert [node.status for node in board.decisions] == ["open", "fogged"]


@pytest.mark.parametrize(
    ("drop", "named"),
    [
        (("impetus",), "impetus"),
        (("context",), "context"),
        (("constraints",), "constraints"),
        (("grilling_brief", "stop_when"), "stop_when"),
        (("grilling_brief", "posture"), "posture"),
        (("session", "id"), "id"),
        (("plan", "statement"), "statement"),
        (("plan", "decisions", 0, "body"), "body"),
        (("plan", "decisions", 0, "prereqs"), "prereqs"),
    ],
)
def test_a_handoff_missing_a_required_field_is_refused_naming_it(
    session_dir: Path, tmp_path: Path, drop: tuple[Any, ...], named: str
) -> None:
    """
    Given a handoff with one required field removed
    When the backend is started against it
    Then it refuses, names the missing field, and initialises no session
         directory.

    Naming the field is the difference between a fixable refusal and one that
    sends the author back to diff their file against a schema. Refusing before
    anything is created matters just as much: a directory holding an empty log
    would be read as a session, and the next start would find the log empty,
    read the handoff again, and accept the briefing it had already refused.
    """
    document = handoff_doc()
    _remove(document, drop)
    path = write_handoff(tmp_path / "briefing", document)

    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir, path)

    assert named in str(refusal.value)
    assert untouched(session_dir)


@pytest.mark.parametrize(
    ("where", "name"),
    [
        ((), "resume_from"),
        (("session",), "owner"),
        (("grilling_brief",), "temperature"),
        (("plan", "decisions", 0), "status"),
    ],
)
def test_a_handoff_carrying_an_unknown_field_is_refused_naming_it(
    session_dir: Path, tmp_path: Path, where: tuple[Any, ...], name: str
) -> None:
    """
    Given a handoff carrying a field this protocol does not define
    When the backend is started against it
    Then it refuses naming that field, and initialises no session directory.

    The handoff is closed at every level, unlike an event payload. It is written
    once and read once, so a field the backend silently ignored is a briefing
    the author believes was delivered and was not -- and `status` on a decision
    is the sharp case: it is a real field of the board, which the handoff has no
    authority to assert.
    """
    document = handoff_doc()
    _at(document, where)[name] = "something"
    path = write_handoff(tmp_path / "briefing", document)

    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir, path)

    assert name in str(refusal.value)
    assert untouched(session_dir)


def test_a_prereq_resolving_to_no_node_is_refused_naming_it(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a handoff whose decision names a prereq no decision provides
    When the backend is started against it
    Then it refuses naming that prereq, and initialises no session directory.

    A dangling prereq is silent in a running session rather than loud: the
    decision simply never becomes answerable, and the human sees a board that
    never opens up with nothing saying why.
    """
    document = handoff_doc()
    document["plan"]["decisions"][1]["prereqs"] = ["d0"]
    path = write_handoff(tmp_path / "briefing", document)

    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir, path)

    assert "d0" in str(refusal.value)
    assert "prereqs" in str(refusal.value)
    assert untouched(session_dir)


def test_a_prereq_cycle_is_refused(session_dir: Path, tmp_path: Path) -> None:
    """
    Given a handoff whose decisions depend on each other
    When the backend is started against it
    Then it refuses naming the decisions in the cycle.

    Same failure mode as a dangling prereq and the same silence: every decision
    in the cycle waits on the others forever.
    """
    document = handoff_doc()
    document["plan"]["decisions"][0]["prereqs"] = ["d2"]
    path = write_handoff(tmp_path / "briefing", document)

    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir, path)

    assert "d1" in str(refusal.value)
    assert "d2" in str(refusal.value)
    assert untouched(session_dir)


def test_two_decisions_sharing_an_id_are_refused(session_dir: Path, tmp_path: Path) -> None:
    """
    Given a handoff whose two decisions carry the same id
    When the backend is started against it
    Then it refuses naming the id.

    Ids are unique within the plan because everything downstream keys on them:
    a duplicate would silently seed one node and lose the other's question.
    """
    document = handoff_doc()
    document["plan"]["decisions"][1]["id"] = "d1"
    path = write_handoff(tmp_path / "briefing", document)

    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir, path)

    assert "d1" in str(refusal.value)
    assert untouched(session_dir)


def test_a_refusal_leaves_no_log_in_a_directory_that_already_existed(session_dir: Path) -> None:
    """
    Given a session directory that already holds only a bad handoff
    When the backend is started against it
    Then no log and no image file is written.

    The directory may pre-exist because the handoff is inside it. What must not
    exist afterwards is a session: a log file is what makes the directory one.
    """
    document = handoff_doc()
    del document["grilling_brief"]["stop_when"]
    write_handoff(session_dir, document)

    with pytest.raises(HandoffRefusedError):
        open_session(session_dir)

    assert untouched(session_dir)


def test_a_new_session_with_no_handoff_at_all_is_refused(session_dir: Path) -> None:
    """
    Given an empty session directory and no handoff
    When the backend is started against it
    Then it refuses, naming the file it looked for.

    A session with no briefing has no board and, worse, no `stop_when`: an agent
    asked to find weaknesses finds them indefinitely, so the termination
    condition is briefed rather than discovered.
    """
    with pytest.raises(HandoffRefusedError) as refusal:
        open_session(session_dir)

    assert "handoff.json" in str(refusal.value)
    assert untouched(session_dir)


def test_a_handoff_that_is_not_json_is_refused(session_dir: Path, tmp_path: Path) -> None:
    """
    Given a handoff file that is not valid JSON
    When the backend is started against it
    Then it refuses, and initialises no session directory.
    """
    path = tmp_path / "briefing" / "handoff.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(HandoffRefusedError):
        open_session(session_dir, path)

    assert untouched(session_dir)


def test_a_handoff_that_is_not_text_at_all_is_refused(session_dir: Path, tmp_path: Path) -> None:
    """
    Given a handoff file that is not decodable text
    When the backend is started against it
    Then it refuses rather than raising out of the read.

    The handoff is a trust boundary: whatever is on the other side of it, the
    backend's answer is a refusal naming the file, not a traceback.
    """
    path = tmp_path / "briefing" / "handoff.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe not text")

    with pytest.raises(HandoffRefusedError):
        open_session(session_dir, path)

    assert untouched(session_dir)


def test_a_log_of_nothing_but_a_torn_line_seeds_from_the_handoff(session_dir: Path) -> None:
    """
    Given a log file holding only half a JSON line — a crash during the very
    first append
    When the backend is started against it with a valid handoff
    Then it seeds from the handoff rather than resuming an empty board.

    Resumability is judged by parsing, not by file size: the log reader forgives
    and drops a torn final line, so a file of nothing else holds no entry and no
    board — treating it as resumable would silently skip the briefing.
    """
    handoff_path = write_handoff(session_dir, handoff_doc())
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / LOG_FILE).write_text('{"seq": 1, "epo', encoding="utf-8")

    log = open_session(session_dir, handoff_path)

    entries = read_entries(session_dir / LOG_FILE)
    assert [entry.kind for entry in entries] == [SESSION_START_KIND]
    assert image1(log).decisions


# ── GUI-D7 / GUI-A27: after session-start the handoff has no authority ──


def test_a_backend_whose_log_is_non_empty_ignores_an_edited_handoff(session_dir: Path) -> None:
    """
    Given a session started from a handoff and then answered
    When the handoff file is edited and the backend is restarted against the
         same directory
    Then no board content changes, and the edited text is nowhere in the board.

    The check is ordered the way the backend's is: the log is consulted before
    the handoff, so there is no path on which a resumed session reads a file
    that was edited under it.
    """
    handoff = write_handoff(session_dir, handoff_doc())
    first = open_session(session_dir, handoff)
    client = driven(first, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": first.epoch,
            "events": [
                event("answer", actor="human", key="a1", target="d1", answer={"option": "a"})
            ],
        },
    )
    before = board_json(first)

    edited = handoff_doc()
    edited["plan"]["decisions"][0]["title"] = "EDITED-QUESTION"
    edited["plan"]["decisions"].append(
        {
            "id": "d3",
            "short": "EDITED-NODE",
            "title": "EDITED-NODE",
            "prereqs": [],
            "body": "EDITED-NODE",
            "options": [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}],
        }
    )
    handoff.write_text(json.dumps(edited), encoding="utf-8")
    second = open_session(session_dir, handoff)

    assert board_json(second) == before
    assert "EDITED" not in (session_dir / LOG_FILE).read_text(encoding="utf-8")
    assert "EDITED" not in json.dumps(on_disk(session_dir))
    assert len([entry for entry in second.entries() if entry.kind == SESSION_START_KIND]) == 1


def test_the_edited_handoff_text_appears_in_no_recorded_dispatch(session_dir: Path) -> None:
    """
    Given a resumed session whose handoff file was edited while it was down
    When a human turn dispatches an agent
    Then the recorded dispatch carries none of the edited text.

    Asserted against the dispatch file's own bytes, because that file is what
    the agent was actually given. A backend that re-read the handoff would put
    the human's own board and an edited briefing in front of the agent at once,
    and nothing downstream could tell which one it reasoned from.
    """
    handoff = write_handoff(session_dir, handoff_doc())
    open_session(session_dir, handoff)
    edited = handoff_doc()
    edited["impetus"] = "EDITED-IMPETUS"
    edited["plan"]["decisions"][0]["title"] = "EDITED-QUESTION"
    handoff.write_text(json.dumps(edited), encoding="utf-8")

    log = open_session(session_dir, handoff)
    driver = SpyDriver()
    client = driven(log, driver)
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event("answer", actor="human", key="a1", target="d1", answer={"option": "a"})
            ],
        },
    )
    assert driver.started.wait(TIMEOUT)

    recorded = [path.read_text(encoding="utf-8") for path in _dispatches(session_dir)]
    assert recorded
    assert all("EDITED" not in text for text in recorded)
    assert all("Which storage?" in text for text in recorded)


# ── GUI-D9 / GUI-A5: resume from file state alone ──


def test_restart_mints_a_new_epoch_on_a_continuing_sequence_with_the_board_intact(
    session_dir: Path,
) -> None:
    """
    Given a session with a settled answer and a thread with turns in it
    When the process is replaced by one opened against the same directory
    Then the epoch is new, the sequence continues, and the settled answers, the
         frontier and the thread history are unchanged.

    The successor process is a genuinely fresh reader: it holds nothing of the
    first, so everything it reproduces came off the disk.
    """
    first = _busy_session(session_dir)
    before = image1(first)
    seq_before = first.seq

    second = open_session(session_dir)

    after = image1(second)
    assert second.epoch != first.epoch
    assert second.seq == seq_before
    assert [(item.id, item.answer) for item in after.settled] == [
        (item.id, item.answer) for item in before.settled
    ]
    assert after.frontier == before.frontier
    assert [(turn.who, turn.text) for turn in after.threads[0].turns] == [
        (turn.who, turn.text) for turn in before.threads[0].turns
    ]


def test_the_session_a_restart_resumes_has_no_turn_still_writing_into_it(
    session_dir: Path,
) -> None:
    """
    Given the busy session the restart cases are measured against
    When it is handed back
    Then every turn its lane announced has already closed, and the sequence is
         the whole of what the directory holds.

    A restart is a directory the previous process has finished with. Every turn
    writes a `replied` entry of its own, from its own thread, after the batch
    that scheduled it returned -- so a turn still announced and not yet closed
    is an entry still to land. Read the sequence with one of those outstanding
    and the number is a moment, not a position: the next entry arrives two
    ahead of it rather than one, and the restart takes the blame for a write
    the previous tenure had not finished making.
    """
    log = _busy_session(session_dir)

    entries = log.entries()
    phases = [entry.payload["phase"] for entry in entries if entry.kind == STATUS_KIND]
    assert phases.count(STATUS_PHASE_COMPOSING) == 2
    assert phases.count(STATUS_PHASE_REPLIED) == phases.count(STATUS_PHASE_COMPOSING)
    assert log.seq == len(entries)


def test_a_restart_closes_out_the_turn_the_dead_tenure_never_answered(
    session_dir: Path,
) -> None:
    """
    Given a session whose log ends with a turn announced and never answered,
         the way a backend killed mid-turn leaves it
    When a successor process is opened against that directory
    Then no channel is still owed a reply, and the turn is on the lane as
         failed, named for the epoch that died holding it.

    The turn was a thread inside the process that is gone, so nobody is
    composing and no `replied` is ever coming. Left announced, the channel
    reads as waiting for the rest of the session and the human watches a clock
    that only counts up.
    """
    first = _busy_session(session_dir)
    first.emit_status(
        STATUS_PHASE_COMPOSING, "the 'fast' tier is composing a reply", MAP_CHANNEL, tier="fast"
    )
    assert MAP_CHANNEL in unclosed_turns(first.entries())

    second = open_session(session_dir)

    assert unclosed_turns(second.entries()) == {}
    closing = second.entries()[-1]
    assert closing.kind == STATUS_KIND
    assert closing.channel == MAP_CHANNEL
    assert closing.payload["phase"] == STATUS_PHASE_ERROR
    assert first.epoch in closing.payload["detail"]
    assert "fast" in closing.payload["detail"]


def test_a_turn_the_current_tenure_is_taking_is_not_closed_out(session_dir: Path) -> None:
    """
    Given a turn in flight under this process's own epoch
    When the dead-turn sweep runs
    Then the turn is left announced, and the driver closes the lane itself when
         it finishes.

    A live turn is the one case the sweep must not touch. Closing it would tell
    the human their reply failed while the tier composing it is still working,
    and the `replied` that follows would reopen a channel the lane had already
    reported closed.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    driver = SpyDriver(hold=True, reply="What does compaction cost you?")
    _, turns = Lane(log, driver).accept(
        [
            EventSubmission(
                kind="answer",
                actor="human",
                channel=MAP_CHANNEL,
                idempotency_key="a1",
                payload={"target": "d1", "answer": {"option": "a"}},
            )
        ],
        log.epoch,
    )
    assert driver.started.wait(TIMEOUT)

    close_dead_turns(log)

    assert MAP_CHANNEL in unclosed_turns(log.entries())
    assert not any(
        entry.payload.get("phase") == STATUS_PHASE_ERROR
        for entry in log.entries()
        if entry.kind == STATUS_KIND
    )
    driver.release.set()
    for turn in turns:
        turn.join(TIMEOUT)
        assert not turn.is_alive(), "a scheduled turn outlived its timeout"
    assert unclosed_turns(log.entries()) == {}


def test_a_restart_closes_out_every_channel_the_dead_tenure_left_announced(
    session_dir: Path,
) -> None:
    """
    Given a dead tenure that left a turn announced on the map and on a thread
         at once
    When a successor process is opened against that directory
    Then both channels are closed out, each naming the epoch that died holding
         it and the tier that was taking it, and nothing is left owed.

    Threads take their turns concurrently with each other and with the map, so
    a kill lands on however many were in flight. A sweep that closed the one
    channel it happened to reach first would leave the rest counting up, and a
    thread is exactly where a human is least likely to notice a clock that
    never stops.
    """
    first = _busy_session(session_dir)
    first.emit_status(
        STATUS_PHASE_COMPOSING, "the 'fast' tier is composing a reply", MAP_CHANNEL, tier="fast"
    )
    first.emit_status(
        STATUS_PHASE_COMPOSING, "the 'heavy' tier is composing a reply", THREAD, tier="heavy"
    )
    assert set(unclosed_turns(first.entries())) == {MAP_CHANNEL, THREAD}

    second = open_session(session_dir)

    assert unclosed_turns(second.entries()) == {}
    closing = {
        entry.channel: entry
        for entry in second.entries()
        if entry.kind == STATUS_KIND and entry.payload["phase"] == STATUS_PHASE_ERROR
    }
    assert set(closing) == {MAP_CHANNEL, THREAD}
    for channel, tier in ((MAP_CHANNEL, "fast"), (THREAD, "heavy")):
        detail = closing[channel].payload["detail"]
        assert first.epoch in detail
        assert tier in detail


def test_a_channel_announced_again_after_its_last_turn_closed_reads_as_owed(
    session_dir: Path,
) -> None:
    """
    Given a channel whose turn was announced and closed, and which was then
         announced again
    When the lane is read for what it owes
    Then the channel is owed, against the second announcement rather than the
         first.

    A channel takes one turn after another all session. A reading that asked
    only whether the channel had ever been closed would call a live turn
    finished -- and the sweep, believing it, would close out a turn a tier is
    still taking.
    """
    log = SessionLog(session_dir)
    log.emit_status(
        STATUS_PHASE_COMPOSING, "the 'fast' tier is composing", MAP_CHANNEL, tier="fast"
    )
    log.emit_status(STATUS_PHASE_REPLIED, "the 'fast' tier's turn is over", MAP_CHANNEL)
    reopened = log.emit_status(
        STATUS_PHASE_COMPOSING, "the 'fast' tier is composing", MAP_CHANNEL, tier="fast"
    )

    assert unclosed_turns(log.entries()) == {MAP_CHANNEL: reopened}


def test_the_next_entry_after_a_restart_continues_the_sequence(session_dir: Path) -> None:
    """
    Given a restarted session
    When the next event is accepted
    Then it lands at the sequence after the one the directory had reached, under
         the new epoch.

    Sequence is the position in the session and epoch is whose tenure wrote it;
    a restart that reset either would make two entries indistinguishable.
    """
    first = _busy_session(session_dir)
    reached = first.seq

    second = open_session(session_dir)
    client = driven(second, SpyDriver())
    receipt = client.post(
        "/events",
        json={
            "epoch": second.epoch,
            "events": [event("informational", key="after-restart", text="still here")],
        },
    ).json()[0]

    assert receipt["seq"] == reached + 1
    assert receipt["epoch"] == second.epoch


def test_deleting_the_image_files_before_a_restart_changes_nothing(session_dir: Path) -> None:
    """
    Given a session whose image files are deleted while the process is down
    When it is restarted
    Then the images are rebuilt from the log, identical to what the previous
         process held.

    The image files are derived caches, never a recovery source. A restart that
    read one would resume from whatever the last successful write happened to
    hold, which is not the same thing as the log.
    """
    first = _busy_session(session_dir)
    before = board_json(first)
    (session_dir / IMAGE1_FILE).unlink()
    (session_dir / IMAGE2_FILE).unlink()

    second = open_session(session_dir)

    assert (session_dir / IMAGE1_FILE).exists()
    assert (session_dir / IMAGE2_FILE).exists()
    assert board_json(second) == before


def test_an_image_file_left_from_a_previous_tenure_is_discarded_and_rebuilt(
    session_dir: Path,
) -> None:
    """
    Given a session whose image file on disk says something the log does not
    When it is restarted
    Then the file is overwritten by the fold of the log.

    A stale image is more dangerous than a missing one: it is readable, so
    anything that trusted it would resume a board nobody ever answered.
    """
    _busy_session(session_dir)
    (session_dir / IMAGE1_FILE).write_text('{"epoch": "stale", "seq": 999}', encoding="utf-8")

    second = open_session(session_dir)

    assert on_disk(session_dir)["epoch"] == second.epoch
    assert on_disk(session_dir)["seq"] == second.seq


def test_the_first_dispatch_after_a_restart_carries_the_turns_from_before_it(
    session_dir: Path,
) -> None:
    """
    Given a session whose thread carried turns before the process was replaced
    When the human speaks in that thread after the restart
    Then the recorded dispatch carries those earlier turns verbatim.

    Asserted against the dispatch file's bytes. The agent is reconstituted from
    image 2 rather than from process memory, which is the whole reason a restart
    costs a cold-start turn and not the session's history.
    """
    _busy_session(session_dir)

    second = open_session(session_dir)
    driver = SpyDriver()
    client = driven(second, driver)
    client.post(
        "/events",
        json={
            "epoch": second.epoch,
            "events": [
                event(
                    "thread-turn",
                    actor="human",
                    channel=THREAD,
                    key="after-restart",
                    turns=[{"who": "human", "text": "picking this back up"}],
                )
            ],
        },
    )
    assert driver.started.wait(TIMEOUT)

    recorded = _dispatches(session_dir)[-1].read_text(encoding="utf-8")
    assert "durability is the point" in recorded
    assert "an append-only log" in recorded


# ── GUI-D6 / GUI-A52: the page may arrive late and leave early ──


def test_a_backend_launched_with_no_page_starts_the_session_and_persists_its_images(
    session_dir: Path,
) -> None:
    """
    Given a handoff and nothing else -- no page, no request
    When the backend opens the session
    Then the board is on disk in both images before anyone asks for it.

    The browser is a viewer. A backend whose board only existed once somebody
    looked would lose the session to a page that never arrived.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))

    assert (session_dir / IMAGE2_FILE).exists()
    assert on_disk(session_dir)["epoch"] == log.epoch
    assert [node["id"] for node in on_disk(session_dir)["decisions"]] == ["d1", "d2"]


def test_a_page_arriving_late_gets_the_full_board_from_the_state_read(session_dir: Path) -> None:
    """
    Given a session that has been answered before any page connected
    When a page reads state for the first time
    Then it gets the whole board, settled answers included.

    The state read is what a page uses after any doubt, which is what lets a
    reconnect assert nothing of its own.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    client = driven(log, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "answer",
                    actor="human",
                    key="a1",
                    target="d1",
                    answer={"text": "an append-only log"},
                )
            ],
        },
    )

    state = client.get("/state").json()

    assert state["epoch"] == log.epoch
    assert [node["id"] for node in state["image1"]["decisions"]] == ["d1", "d2"]
    assert state["image1"]["settled"] == [{"id": "d1", "answer": "an append-only log"}]
    assert state["image1"]["frontier"] == ["d2"]


def test_a_page_leaving_while_a_turn_is_in_flight_stops_nothing(session_dir: Path) -> None:
    """
    Given a turn still in flight when the page goes away
    When the turn finishes
    Then its reply is in the log, and a later state read renders it.

    The backend owns the session, not the browser. A page that owned the board
    could not survive the browser leaving, and the human would come back to a
    turn that was silently abandoned.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    driver = SpyDriver(hold=True, reply="What does compaction cost you?")
    client = driven(log, driver)
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event("answer", actor="human", key="a1", target="d1", answer={"option": "a"})
            ],
        },
    )
    assert driver.started.wait(TIMEOUT)

    client.close()
    driver.release.set()
    assert driver.finished.wait(TIMEOUT)

    assert any(entry.payload.get("text") == driver.reply for entry in log.entries())
    returning = driven(log, driver)
    pending = returning.get("/state").json()["image1"]["pending"]
    assert [item["kind"] for item in pending] == ["informational"]


def _busy_session(session_dir: Path) -> SessionLog:
    """A session with a settled answer and a thread that has been spoken in,
    handed back with no turn still writing into it.

    The state a restart has to reproduce: one decision the human answered, and
    one conversation with turns in it.

    The turns are waited out rather than left running, which is why this goes
    through the lane rather than posting and walking away. Each human gesture
    schedules a turn on a thread of its own, and that thread closes itself with
    a `replied` entry after the batch that scheduled it has already returned --
    so a helper that handed back mid-flight would hand back a sequence that
    moves on its own. A restart measured against it reads a position the
    directory had not reached, and blames the resume path for the difference.
    """
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    run_turns(
        Lane(log, SpyDriver()),
        EventSubmission(
            kind="answer",
            actor="human",
            channel=MAP_CHANNEL,
            idempotency_key="a1",
            payload={
                "target": "d1",
                "answer": {"option": "a", "text": "an append-only log"},
                "why": "the audit trail is the point",
            },
        ),
        EventSubmission(
            kind="thread-created",
            actor="human",
            channel=THREAD,
            idempotency_key="t-1",
            payload={
                "kind": "side",
                "title": "Durability",
                "turns": [{"who": "human", "text": "durability is the point"}],
            },
        ),
    )
    project_and_persist(log)
    return log


def _dispatches(session_dir: Path) -> list[Path]:
    return sorted((session_dir / DISPATCH_DIR).glob("*.json"))


def _at(document: dict[str, Any], path: tuple[Any, ...]) -> Any:
    node: Any = document
    for step in path:
        node = node[step]
    return node


def _remove(document: dict[str, Any], path: tuple[Any, ...]) -> None:
    del _at(document, path[:-1])[path[-1]]
