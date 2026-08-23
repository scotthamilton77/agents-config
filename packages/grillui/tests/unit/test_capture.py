"""Ending a session, and what capture leaves behind.

Session end is a human gesture. The tests here pin both halves of that: what the
human's gesture produces, and what an agent's is refused with. The capture core
is exercised through the session directory alone, because that is the only thing
it is allowed to need -- a capture that reached for the process that ran the
session could not be run over last week's grilling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import SpyDriver, apply_all, driven, event, handoff_doc, write_handoff

from grillui.api import create_app
from grillui.capture import ENDED_BY_HUMAN, NOT_FORMALLY_ENDED, capture, default_summary
from grillui.log import LOG_FILE, RESULT_FILE, SessionLog
from grillui.schemas import (
    SESSION_END_KIND,
    STATUS_KIND,
    STATUS_PHASE_ERROR,
    THREAD_FOLD_KIND,
    TerminalResult,
)
from grillui.session import end_session, open_session

from fastapi.testclient import TestClient  # isort: skip


def started(session_dir: Path) -> SessionLog:
    return open_session(session_dir, write_handoff(session_dir, handoff_doc()))


def answer(client: TestClient, epoch: str, node: str = "d1") -> None:
    client.post(
        "/events",
        json={
            "epoch": epoch,
            "events": [
                event(
                    "answer",
                    actor="human",
                    key=f"answer-{node}",
                    target=node,
                    answer={"option": "a", "text": "an append-only log"},
                    why="the audit trail is the point",
                )
            ],
        },
    )


def end(client: TestClient, epoch: str, actor: str = "human", **payload: Any) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = client.post(
        "/events",
        json={
            "epoch": epoch,
            "events": [event(SESSION_END_KIND, actor=actor, key=f"end-{actor}", **payload)],
        },
    ).json()
    return receipts[0]


# ── GUI-D10 / GUI-A28: the human ends the session ──


def test_the_end_session_gesture_appends_a_terminal_entry_and_leaves_a_result(
    session_dir: Path,
) -> None:
    """
    Given a session the human has answered a decision in
    When the human's end-session gesture arrives
    Then the log carries a terminal entry and the directory holds a terminal
         result that validates against its schema.

    The log entry and the result file are both required and they are not the
    same claim: the entry is the record that the session ended, and the result
    is what the main agent is handed.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)

    receipt = end(client, log.epoch, stop_reason="the human called it")

    assert receipt["status"] == "accepted"
    assert log.entries()[-1].kind == SESSION_END_KIND
    result = TerminalResult.model_validate_json(
        (session_dir / RESULT_FILE).read_text(encoding="utf-8")
    )
    assert result.session.id == "grill-1"
    assert result.session.title == "Session store design"
    assert result.session.created == "2026-08-18T09:00:00+00:00"
    assert result.session.ended == log.entries()[-1].timestamp
    assert result.stop_reason == "the human called it"
    assert result.references.log == LOG_FILE
    assert [(item.id, item.answer) for item in result.decisions] == [
        ("d1", "an append-only log"),
        ("d2", None),
    ]
    assert result.decisions[0].rationale == "the audit trail is the point"
    assert [item.id for item in result.open_items] == ["d2"]
    assert result.summary


def test_a_session_ended_without_a_stated_reason_says_the_human_ended_it(
    session_dir: Path,
) -> None:
    """
    Given an end-session gesture carrying no reason
    When the session ends
    Then the result still states how it ended.

    `stop_reason` is a required field of the result, so there is no shape of it
    that says nothing; what a bare gesture means is that the human called it.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())

    end(client, log.epoch)

    result = _result(session_dir)
    assert result.stop_reason == ENDED_BY_HUMAN


def test_a_capture_that_fails_still_leaves_the_terminal_log_entry(session_dir: Path) -> None:
    """
    Given a summarizer that raises
    When the human ends the session
    Then the terminal entry is in the log, the failure is on the status lane,
         the session directory is intact, and no result file is written.

    Capture is downstream of the append, like image persistence: the entry is
    already durable and already has a receipt, so a capture fault costs the
    result file and nothing else. A later capture run over the same directory
    can still produce what this one did not.
    """

    def explode(_result: TerminalResult) -> str:
        fault = "no summarizer today"
        raise RuntimeError(fault)

    log = started(session_dir)
    client = TestClient(create_app(log, SpyDriver(), summarize=explode))
    answer(client, log.epoch)

    receipt = end(client, log.epoch)

    assert receipt["status"] == "accepted"
    assert log.entries()[-1].kind == STATUS_KIND
    assert log.entries()[-1].payload["phase"] == STATUS_PHASE_ERROR
    assert "capture failed" in log.entries()[-1].payload["detail"]
    assert any(entry.kind == SESSION_END_KIND for entry in log.entries())
    assert not (session_dir / RESULT_FILE).exists()
    assert (session_dir / LOG_FILE).exists()


def test_a_session_end_submitted_by_an_agent_is_rejected_and_appends_nothing(
    session_dir: Path,
) -> None:
    """
    Given an agent submitting an end-session event
    When it reaches the backend
    Then it is refused with a typed receipt naming the rule, nothing is
         appended, and no result is written.

    An agent that judges `stop_when` satisfied says so to the human. One that
    could end the session itself would decide, on its own reading of a briefing,
    that the human is finished.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    before = len(log.entries())

    receipt = end(client, log.epoch, actor="grill-master")

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == "unknown event kind"
    assert "human gesture" in receipt["detail"]
    assert len(log.entries()) == before
    assert not (session_dir / RESULT_FILE).exists()


def test_a_session_start_submitted_by_a_client_is_rejected(session_dir: Path) -> None:
    """
    Given a client submitting a session-start event
    When it reaches the backend
    Then it is refused and nothing is appended.

    `session-start` is the entry that strips the handoff of its authority. A
    client that could send one could reseed the board mid-session, over the top
    of every answer the human had given.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    before = len(log.entries())

    receipts = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("session-start", actor="grill-master", key="reseed")],
        },
    ).json()

    assert receipts[0]["status"] == "rejected"
    assert receipts[0]["reason"] == "unknown event kind"
    assert len(log.entries()) == before


# ── GUI-D23: the capture core is pure code over the session directory ──


def test_capture_over_a_fixed_log_is_byte_identical_twice(session_dir: Path) -> None:
    """
    Given a session directory whose log is terminal-ready
    When capture runs twice over it
    Then the two results are byte-identical.

    Everything but the summary is a fold, and the v1 summarizer counts rather
    than composes, so the whole result is a function of the log.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)
    end(client, log.epoch)

    first = capture(session_dir).model_dump_json()
    second = capture(session_dir).model_dump_json()

    assert first == second


def test_a_fresh_reader_pointed_at_the_directory_alone_produces_the_whole_result(
    session_dir: Path,
) -> None:
    """
    Given a finished session and no process serving it
    When capture is pointed at the directory
    Then it produces the same result the backend wrote at end-session.

    Capture reads the session directory and nothing else, which is what makes
    "we grilled this last week, go capture it" the same operation as ending a
    live session.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)
    end(client, log.epoch)
    written = (session_dir / RESULT_FILE).read_text(encoding="utf-8")
    del log, client

    assert capture(session_dir).model_dump_json() == written


def test_capture_reads_the_log_and_not_the_handoff(session_dir: Path) -> None:
    """
    Given a finished session whose handoff file has been edited since
    When capture runs
    Then the session identity is the one the log carries.

    The handoff lost its authority at `session-start`. A capture that re-read it
    would name the session whatever the file says now, which nothing recorded.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    end(client, log.epoch)
    edited = handoff_doc()
    edited["session"]["title"] = "EDITED-TITLE"
    (session_dir / "handoff.json").write_text(json.dumps(edited), encoding="utf-8")

    result = capture(session_dir)

    assert result.session.title == "Session store design"


def test_capture_over_a_log_with_no_terminal_entry_says_so(session_dir: Path) -> None:
    """
    Given a session that was never formally ended
    When capture runs over it
    Then it produces a complete result whose stop reason says the log carries no
         ending.

    Capture is invocable over any session directory. Reporting an ending nobody
    made would put a terminal claim in the main agent's hands for a grilling
    that is still open.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)

    result = capture(session_dir)

    assert result.stop_reason == NOT_FORMALLY_ENDED
    assert result.session.ended == log.entries()[-1].timestamp
    assert [item.id for item in result.decisions] == ["d1", "d2"]


def test_a_folded_threads_conclusion_reaches_the_result_and_an_open_ones_does_not(
    session_dir: Path,
) -> None:
    """
    Given one thread the human folded and one still open, each with turns
    When capture runs over the session directory
    Then the folded thread's conclusion is the turn its fold applied, and the
         open thread's is null.

    Both halves are needed. A conclusion the result never carries loses what the
    thread was for; a conclusion on a thread that reached none reports a
    decision the session never made.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    for thread, kind, said in (
        ("t-folded", "thread-created", "how long is a session kept?"),
        ("t-folded", "thread-turn", "thirty days, then archive."),
        ("t-open", "thread-created", "and when is it compacted?"),
    ):
        client.post(
            "/events",
            json={
                "epoch": log.epoch,
                "events": [
                    event(
                        kind,
                        actor="human" if kind == "thread-created" else "thread-agent",
                        channel=thread,
                        key=f"{kind}-{thread}-{said[:8]}",
                        title="Retention",
                        turns=[{"text": said}],
                    )
                ],
            },
        )
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event(THREAD_FOLD_KIND, actor="human", channel="t-folded", key="fold-it")],
        },
    )

    result = capture(session_dir)

    assert [(one.id, one.state, one.conclusion) for one in result.threads] == [
        ("t-folded", "folded", "thirty days, then archive."),
        ("t-open", "open", None),
    ]


def test_every_unsettled_decision_carries_the_blocker_that_has_to_move_first(
    session_dir: Path,
) -> None:
    """
    Given a session ended with one decision answered and one fogged behind it
    When capture runs
    Then the open item names what is holding the fogged decision.

    A decision can be blocked several ways at once, and the human reading the
    result needs the reason that actually has to move first rather than a list.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    end(client, log.epoch)

    result = capture(session_dir)

    blockers = {item.id: item.blocker for item in result.open_items}
    assert blockers["d1"] == "answerable and unanswered"
    assert "'d1'" in blockers["d2"]


def test_a_blocked_decision_names_the_block_rather_than_its_prerequisites(
    session_dir: Path,
) -> None:
    """
    Given a session ended with one decision invalidated and one locked by a
         blocking alert
    When capture runs
    Then the locked one is the open item, and it names the lock.

    A locked decision is fogged as well here, and what the human needs is the
    lock: the fog lifts on its own when the prerequisite settles, and the lock
    does not. The invalidated decision is no open item at all -- it came to
    rest when the invalidate landed.

    The invalidation reaches the board the only way an agent's does -- proposed,
    then applied by the human -- because a capture run over a board an agent
    wrote by itself would be reporting a session nobody had.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event("invalidate", key="inv", target="d1", why="the premise moved"),
                event(
                    "elicit-alert",
                    key="alert",
                    target="d2",
                    text="retention policy is unsettled",
                    blocking=True,
                ),
            ],
        },
    )
    apply_all(client, log.epoch)
    end(client, log.epoch)

    blockers = {item.id: item.blocker for item in capture(session_dir).open_items}
    assert "d1" not in blockers, "an invalidated decision was written up as open work"
    assert blockers["d2"] == "locked by a blocking alert"


def test_a_board_whose_rest_was_invalidated_is_written_up_with_nothing_open(
    session_dir: Path,
) -> None:
    """
    Given a session ended with one decision answered and the rest invalidated
         by proposals the human applied
    When capture runs
    Then it reports no open items and counts the invalidated ones as set aside.

    This is the board a whole session can end on: one answer that killed the
    questions under it, and nothing anybody still has to move. Reporting the
    killed ones as left open would send the human back to a board that is
    finished, and would disagree with the page, which announces that board as
    complete.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("invalidate", key="inv", target="d2", why="the answer killed it")],
        },
    )
    apply_all(client, log.epoch)
    end(client, log.epoch)

    result = capture(session_dir)

    assert [one.status for one in result.decisions] == ["settled", "invalidated"]
    assert result.open_items == []
    assert "1 of 2 decisions settled, 1 set aside, 0 left open" in result.summary


def test_a_decision_the_human_never_got_to_says_a_change_is_waiting_on_it(
    session_dir: Path,
) -> None:
    """
    Given a session ended with a proposed change still in the queue
    When capture runs
    Then that decision's blocker says a change is waiting, not that an alert
         locked it.

    A lock has two sources and they send the reader different places: an alert
    is a warning somebody wrote, and a queued change is a gesture nobody made.
    Reporting the second as the first sends them looking for a warning that was
    never sent.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("invalidate", key="inv", target="d1", why="the premise moved")],
        },
    )
    end(client, log.epoch)

    blockers = {item.id: item.blocker for item in capture(session_dir).open_items}
    assert blockers["d1"] == "a proposed change is waiting on it"


def test_a_decision_left_resting_on_a_withdrawn_answer_says_so(session_dir: Path) -> None:
    """
    Given a session where an answer was withdrawn under a decision built on it
    When capture runs
    Then the dependent decision's blocker names the withdrawal.

    Stale is not the same as unanswered: the answer is still there, and what is
    missing is the ground it stood on.

    Withdrawing an answer is never the agent's to do on its own, so the
    unsettle reaches the board through the human's apply -- which is also the
    only way this session's staleness could ever have happened.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    answer(client, log.epoch)
    answer(client, log.epoch, node="d2")
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("unsettle", key="uns", target="d1", why="the cost changed")],
        },
    )
    apply_all(client, log.epoch)
    end(client, log.epoch)

    blockers = {item.id: item.blocker for item in capture(session_dir).open_items}
    assert blockers["d2"] == "rests on an answer that was withdrawn"
    assert blockers["d1"] == "answerable and unanswered"


def test_the_default_summary_is_a_briefing_and_not_a_transcript(session_dir: Path) -> None:
    """
    Given a session with a thread the human spoke in
    When the default summarizer writes the summary
    Then it counts the structured parts and carries no turn text.

    The v1 default holds the seam open without making the result depend on a
    model being reachable, and the field is bounded to a briefing either way.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="human",
                    channel="t1",
                    key="t-1",
                    kind="side",
                    title="Durability",
                    turns=[{"who": "human", "text": "durability is the point"}],
                )
            ],
        },
    )
    answer(client, log.epoch)
    end(client, log.epoch)

    result = capture(session_dir)

    assert result.summary == default_summary(result.model_copy(update={"summary": ""}))
    assert "1 of 2 decisions settled" in result.summary
    assert "1 side threads" in result.summary
    assert "durability is the point" not in result.summary


def test_a_summarizer_plugged_into_the_seam_writes_the_prose(session_dir: Path) -> None:
    """
    Given a summarizer of the caller's own
    When capture runs through it
    Then its prose is the result's summary and nothing else changes.

    The seam is where the single agent pass plugs in. What it may write is the
    summary; every other field is code over the log, so a summarizer cannot
    change what the session decided.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    end(client, log.epoch)
    structural = capture(session_dir).model_dump(exclude={"summary"})

    result = capture(session_dir, summarize=lambda one: f"briefing for {one.session.id}")

    assert result.summary == "briefing for grill-1"
    assert result.model_dump(exclude={"summary"}) == structural


def test_end_session_returns_the_path_it_wrote(session_dir: Path) -> None:
    """
    Given a session ended out of band
    When end_session runs
    Then it returns the result path it wrote.

    The path is what the launching agent is handed alongside the result, so it
    is returned rather than implied by convention.
    """
    log = started(session_dir)

    written = end_session(log)

    assert written == session_dir / RESULT_FILE


def _result(session_dir: Path) -> TerminalResult:
    return TerminalResult.model_validate_json(
        (session_dir / RESULT_FILE).read_text(encoding="utf-8")
    )


def test_a_thread_anchored_to_no_decision_reaches_the_result_like_any_other(
    session_dir: Path,
) -> None:
    """
    Given a session-scoped thread — one whose anchor decision is null — that
    the human parked
    When capture runs over the session directory
    Then it is a line item in the result beside the threads that sit on
         decisions, and the decisions are untouched by it.

    A thread with no anchor is where the human asked how the board works. The
    result reports what the session's threads were, so it reports this one too;
    what it must not do is treat an unanchored thread as an unanswered
    question, or drop it because there is no decision to hang it under.
    """
    log = started(session_dir)
    client = driven(log, SpyDriver())
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event(
                    "thread-created",
                    actor="human",
                    channel="t-help",
                    key="opened-help",
                    decision=None,
                    kind="help",
                    title="How this board works",
                    turns=[{"text": "How do I park a thread?"}],
                )
            ],
        },
    )
    client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("thread-park", actor="human", channel="t-help", key="park-help")],
        },
    )

    result = capture(session_dir)

    assert ("t-help", "How this board works", "parked", None) in [
        (one.id, one.title, one.state, one.conclusion) for one in result.threads
    ]
    assert [one.id for one in result.open_items] == ["d1", "d2"]


# ── GUI-D29 / GUI-A55: what the end of a session makes of each gesture ──

PARKED_THREAD = "t-backups"
CLOSED_THREAD = "t-naming"
PARKED_TITLE = "What backs the directory up"
CLOSED_TITLE = "What the files are called"


def lifecycle_session(session_dir: Path) -> None:
    """One session carrying one parked thread and one closed one, ended by the
    human -- so the live result and a capture run are reading one log."""
    log = started(session_dir)
    client = driven(log, SpyDriver())
    for channel, title, gesture in (
        (PARKED_THREAD, PARKED_TITLE, "thread-park"),
        (CLOSED_THREAD, CLOSED_TITLE, "thread-close"),
    ):
        client.post(
            "/events",
            json={
                "epoch": log.epoch,
                "events": [
                    event(
                        "thread-created",
                        actor="human",
                        channel=channel,
                        key=f"opened-{channel}",
                        decision="d1",
                        kind="user",
                        title=title,
                        turns=[{"text": f"About {title.lower()}?"}],
                    )
                ],
            },
        )
        client.post(
            "/events",
            json={
                "epoch": log.epoch,
                "events": [
                    event(gesture, actor="human", channel=channel, key=f"{gesture}-{channel}")
                ],
            },
        )
    assert end(client, log.epoch)["status"] == "accepted"


def read_live(session_dir: Path) -> TerminalResult:
    """What the backend wrote when the human ended the session."""
    return _result(session_dir)


def read_captured(session_dir: Path) -> TerminalResult:
    """The same directory, folded again by a run nothing is serving."""
    return capture(session_dir)


@pytest.mark.parametrize("read", [read_live, read_captured], ids=["live", "capture"])
def test_a_parked_thread_is_a_loose_end_and_a_closed_one_is_a_line_item(
    read: Any, session_dir: Path
) -> None:
    """
    Given one session in which the human parked one thread and closed another
    When the terminal result is read -- from the live end-session write, and
         from a capture run over the same directory
    Then both threads are line items carrying the state their gesture set, the
         parked one is raised as still open, and nothing raises the closed one.

    Asserted the same way through both readers because it is one claim: the
    result an agent is handed as the session ends and the result a capture
    produces next week have to say the same thing about what the human
    finished with. A closed thread that came back as unfinished business would
    hand them the work they had just declared done.
    """
    lifecycle_session(session_dir)

    result = read(session_dir)

    states = {one.id: one.state for one in result.threads}
    assert states == {PARKED_THREAD: "parked", CLOSED_THREAD: "closed"}, states
    # The closed thread is on the record and nowhere else: not among the open
    # items, and not in the prose that says what is still unfinished.
    named_open = {one.id for one in result.open_items} | {one.blocker for one in result.open_items}
    assert CLOSED_THREAD not in named_open and CLOSED_TITLE not in named_open
    assert CLOSED_TITLE not in result.summary and CLOSED_THREAD not in result.summary
    assert PARKED_TITLE in result.summary, "the parked thread was not raised as a loose end"
