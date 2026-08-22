"""What an agent is given, checked against what the backend recorded giving it.

Every assertion about completeness below reads a file the backend wrote under
`dispatches/`. Checking an in-memory context the test itself assembled would
pass just as happily against a recorder that dropped half of it on the way to
disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import event, handoff_doc, post, seed_node
from fastapi.testclient import TestClient

from grillui.dispatch import DISPATCH_DIR, DispatchIncompleteError, record_dispatch, verify_complete
from grillui.log import SessionLog
from grillui.projector import fold, whole_board
from grillui.schemas import (
    MAP_THREAD_KIND,
    SESSION_START_KIND,
    DispatchContext,
    Image2,
    ThreadProjection,
)

ANSWERS = {
    "n1": "an append-only log, because the audit trail is the point",
    "n2": "one JSON object per line",
    "n3": "the session directory, named for the session id",
}


def _settled_board(client: TestClient, epoch: str) -> None:
    """Three decisions, each settled with answer text of its own."""
    for index, (node_id, answer) in enumerate(ANSWERS.items(), start=1):
        seed_node(client, epoch, node_id)
        post(
            client,
            epoch,
            event(
                "answer",
                actor="human",
                key=f"answer-{index}",
                target=node_id,
                answer={"option": "a", "text": answer},
                why=f"settled on {node_id}",
            ),
        )


def _recorded(session_dir: Path) -> list[str]:
    """The dispatch files as the backend left them, in dispatch order."""
    return [
        path.read_text(encoding="utf-8")
        for path in sorted((session_dir / DISPATCH_DIR).glob("*.json"))
    ]


def test_a_recorded_dispatch_carries_image_two_whole_including_every_settled_answer(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given a board with several settled decisions
    When the backend records a grill-master dispatch
    Then the recorded file contains image 2 byte for byte, including every
         settled decision's id and its answer text.

    There is no elision path and no budget that can create one. A dispatch that
    trimmed settled decisions would lose human decisions silently: the agent
    would proceed without a decision the human made minutes earlier, and no
    receipt, log entry or later read would say which one went missing.
    """
    _settled_board(client, log.epoch)
    expected = fold(log.epoch, log.entries())

    record_dispatch(log)

    recorded = _recorded(session_dir)[0]
    assert expected.model_dump_json() in recorded
    for node_id, answer in ANSWERS.items():
        assert node_id in recorded
        assert answer in recorded
    context = DispatchContext.model_validate_json(recorded)
    assert context.agent == "grill-master"
    assert context.image2.model_dump_json() == expected.model_dump_json()
    assert {item.id: item.answer for item in context.image2.settled} == ANSWERS


def test_a_context_missing_any_part_of_image_two_is_refused_rather_than_truncated(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a context from which one settled decision's answer text has been
    dropped
    When it is checked against the image it was assembled from
    Then it is refused as incomplete.

    A dispatch that omits any part of its owed projection must never happen,
    and is treated as data corruption. Truncating instead would produce exactly
    the failure the completeness rule exists to prevent, with no signal
    anywhere.
    """
    _settled_board(client, log.epoch)
    image = fold(log.epoch, log.entries())
    complete = record_dispatch(log).read_text(encoding="utf-8")

    verify_complete(complete, image)

    with pytest.raises(DispatchIncompleteError):
        verify_complete(complete.replace(ANSWERS["n2"], "…"), image)


def test_a_projection_that_loses_a_field_cannot_vouch_for_its_own_output(
    client: TestClient, log: SessionLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a whole-board projection that silently drops part of the image
    When a map dispatch is assembled through it
    Then assembly refuses, because the map context is checked against the
    source image rather than the projection's own output.

    Checked against its own output, a lossy projection passes: the recorded
    bytes match the already-truncated board exactly.
    """
    _settled_board(client, log.epoch)

    def lossy(image: Image2) -> ThreadProjection:
        return whole_board(image.model_copy(update={"settled": []}))

    monkeypatch.setattr("grillui.dispatch.whole_board", lossy)

    with pytest.raises(DispatchIncompleteError):
        record_dispatch(log)


def test_each_dispatch_is_recorded_as_its_own_file_in_dispatch_order(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given two dispatches with a write between them
    When both have been recorded
    Then each has its own file, in order, folded at its own dispatch time.

    One file per dispatch is what makes the completeness check auditable after
    the fact rather than only at the moment of dispatching.
    """
    seed_node(client, log.epoch)
    record_dispatch(log)
    post(client, log.epoch, event("informational", key="k-later", text="later"))

    record_dispatch(log)

    contexts = [DispatchContext.model_validate_json(text) for text in _recorded(session_dir)]
    assert [context.seq for context in contexts] == [1, 2]
    assert [context.channel for context in contexts] == ["map", "map"]


REFERENCE = "The map is the plan. Answering a decision opens whatever waited on it."


def _session_thread(
    client: TestClient,
    epoch: str,
    channel: str,
    decision: str | None,
    kind: str | None = None,
) -> None:
    """One thread, opened the way the page opens one."""
    post(
        client,
        epoch,
        event(
            "thread-created",
            actor="human",
            channel=channel,
            key=f"opened-{channel}",
            turns=[{"who": "human", "text": "How do I park this?"}],
            decision=decision,
            kind=kind or ("help" if decision is None else "user"),
            title="How this board works",
            requires_action=False,
        ),
    )


def _brief(log: SessionLog, **overrides: Any) -> None:
    """The opening entry, as the backend appends it when it reads a handoff."""
    log.record(SESSION_START_KIND, {**handoff_doc(), **overrides})


def test_the_session_scoped_threads_dispatch_carries_the_shipped_reference_material(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a briefing that shipped reference material about the board
    When the backend records a dispatch for the thread anchored to no decision
    Then the recorded context carries that material.

    Asserted against the file the backend wrote rather than against anything
    the page shows: what the agent was handed is what was recorded, and a page
    that displayed the right thing over a context that never carried it would
    leave the agent guessing at the one question it exists to answer.
    """
    _brief(log, help_reference=REFERENCE)
    _session_thread(client, log.epoch, "t-help", None)

    recorded = record_dispatch(log, channel="t-help").read_text(encoding="utf-8")

    context = DispatchContext.model_validate_json(recorded)
    assert context.help_reference == REFERENCE
    assert context.agent == "thread-agent"


def test_no_other_dispatch_carries_the_reference_material(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the same briefing
    When the map's dispatch and a decision's thread dispatch are recorded
    Then neither carries the material.

    Every other agent here is grilling a design. Material about driving the
    board is bytes they pay for and never use, and the map's context is the one
    that already crosses whole.
    """
    _brief(log, help_reference=REFERENCE)
    _session_thread(client, log.epoch, "t-on-d1", "d1")

    on_map = record_dispatch(log).read_text(encoding="utf-8")
    on_decision = record_dispatch(log, channel="t-on-d1").read_text(encoding="utf-8")

    # The thread has to be on the board for its dispatch to mean anything: a
    # channel naming no thread is refused the material for the wrong reason.
    anchored = DispatchContext.model_validate_json(on_decision).image2.threads[0]
    assert anchored.id == "t-on-d1"
    assert anchored.decision == "d1"
    assert DispatchContext.model_validate_json(on_map).help_reference is None
    assert DispatchContext.model_validate_json(on_decision).help_reference is None
    assert REFERENCE not in on_map
    assert REFERENCE not in on_decision


def test_the_map_thread_is_not_given_the_boards_reference_material(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the same briefing and the session-level map thread
    When that thread's dispatch is recorded
    Then it carries no reference material.

    The map thread anchors no decision, like the help thread, and is about the
    plan like every other thread. Handing it the material on the anchor alone
    would prime the agent steering the map with a manual for driving the board
    -- bytes it pays for every turn and never uses.
    """
    _brief(log, help_reference=REFERENCE)
    _session_thread(client, log.epoch, "t-map", None, kind=MAP_THREAD_KIND)

    recorded = record_dispatch(log, channel="t-map").read_text(encoding="utf-8")

    context = DispatchContext.model_validate_json(recorded)
    assert context.image2.threads[0].id == "t-map"
    assert context.image2.threads[0].decision is None
    assert context.help_reference is None
    assert REFERENCE not in recorded


def test_a_briefing_that_shipped_nothing_dispatches_the_session_thread_unprimed(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a briefing carrying no reference material
    When the session-scoped thread's dispatch is recorded
    Then it carries none, and the dispatch is otherwise whole.

    A briefing written by hand is a whole briefing. The material is about the
    tool rather than about the plan, so its absence is a session with no help
    to offer rather than a session that cannot run.
    """
    _brief(log)
    _session_thread(client, log.epoch, "t-help", None)

    recorded = record_dispatch(log, channel="t-help").read_text(encoding="utf-8")

    context = DispatchContext.model_validate_json(recorded)
    assert context.help_reference is None
    assert context.image2.threads[0].decision is None


def test_concurrent_dispatches_never_overwrite_each_other(session_dir: Path) -> None:
    """
    Given many dispatches recorded from concurrent threads
    When they race for the next file number
    Then every dispatch lands on its own file — the O_EXCL claim makes the
    slow loser move on rather than silently replacing the winner's record.
    """
    import threading

    log = SessionLog(session_dir)
    workers = [threading.Thread(target=record_dispatch, args=(log,)) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    recorded = list((session_dir / "dispatches").glob("*.json"))
    assert len(recorded) == 8
