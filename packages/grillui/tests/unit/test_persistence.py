"""Persisting the images, and what happens when persisting fails.

The fold is pure and the persistence step is not, which is the whole reason
these are separate: everything below is about the seam holding when the second
half breaks.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from conftest import SEED_NODE, event, post, seed_node
from fastapi.testclient import TestClient

from grillui.log import IMAGE1_FILE, IMAGE2_FILE, LOG_FILE, SessionLog
from grillui.persistence import project_and_persist
from grillui.projector import fold, to_image1
from grillui.schemas import STATUS_KIND, STATUS_PHASE_ERROR, Image1, Image2

DEADLOCK_TIMEOUT = 5.0


def _answered_board(client: TestClient, epoch: str) -> None:
    """A board with a settled decision, a thread and an unanswered node: enough
    shape that a dropped field would show."""
    seed_node(client, epoch)
    post(
        client,
        epoch,
        event(
            "add-node",
            key="k-n2",
            target="n2",
            short="Format",
            title="Which wire format?",
            prereqs=[SEED_NODE],
            options=[{"id": "a", "text": "JSON lines"}, {"id": "b", "text": "Protobuf"}],
        ),
        event(
            "answer",
            actor="human",
            key="k-answer",
            target=SEED_NODE,
            answer={"option": "a", "text": "append-only log"},
            why="the audit trail is the point",
        ),
        event(
            "thread-created",
            actor="human",
            channel="t1",
            key="k-thread",
            title="Compaction",
            kind="side",
            turns=[{"who": "human", "text": "What about compaction?"}],
        ),
    )


def test_images_rebuilt_from_the_on_disk_log_alone_are_byte_identical_to_the_in_memory_ones(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given a session whose entries are held in one process's memory
    When a second process folds the same session from its log file alone
    Then the two images serialise to identical bytes.

    This is the guarantee that makes the log the recovery source and the image
    files a cache. The two folds are given the same epoch deliberately: the
    epoch is the process's tenure, not the log's content, and a restart mints a
    new one by design. Everything else in the image has to come out of the
    bytes on disk.
    """
    _answered_board(client, log.epoch)

    rebuilt = SessionLog(session_dir)

    assert rebuilt.epoch != log.epoch
    assert fold(log.epoch, rebuilt.entries()).model_dump_json() == (
        fold(log.epoch, log.entries()).model_dump_json()
    )


def test_an_accepted_batch_leaves_both_images_on_disk_at_the_folded_position(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given a batch of accepted writes
    When it has been submitted
    Then both image files hold the fold of the log as of that batch.

    Persistence is downstream of the fold and this is the only place image I/O
    happens. Writing them after the append rather than before is what keeps the
    receipt honest: the entry is durable whatever the file system then does.
    """
    _answered_board(client, log.epoch)

    written2 = Image2.model_validate_json((session_dir / IMAGE2_FILE).read_text(encoding="utf-8"))
    written1 = Image1.model_validate_json((session_dir / IMAGE1_FILE).read_text(encoding="utf-8"))

    expected = fold(log.epoch, log.entries())
    assert written2.model_dump_json() == expected.model_dump_json()
    assert written1.model_dump_json() == to_image1(expected).model_dump_json()
    assert written2.seq == log.seq
    assert "history" not in (session_dir / IMAGE1_FILE).read_text(encoding="utf-8")


def test_the_image_files_are_never_read_back_when_a_session_loads(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given image files on disk that disagree with the log
    When a fresh process loads the session
    Then the board comes from the log and the image files' content appears
         nowhere in it.

    The image files are derived caches, never a recovery source. A load that
    trusted them would let a half-written cache — the exact artifact the
    failure paths below produce — become the board the human is answering.
    """
    _answered_board(client, log.epoch)
    poison = '{"epoch":"forged","seq":999,"decisions":[{"id":"forged-node"}]}'
    (session_dir / IMAGE1_FILE).write_text(poison, encoding="utf-8")
    (session_dir / IMAGE2_FILE).write_text(poison, encoding="utf-8")

    rebuilt = fold("tenure-2", SessionLog(session_dir).entries())

    assert [node.id for node in rebuilt.decisions] == [SEED_NODE, "n2"]
    assert rebuilt.seq == log.seq
    assert "forged" not in rebuilt.model_dump_json()


def test_an_unwritable_image_leaves_the_log_intact_and_still_takes_the_next_event(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """
    Given an image path that cannot be written — here, one occupied by a
    directory
    When an event is accepted and the persistence step fails on it
    Then the write is still accepted, the failure surfaces on the status lane,
         the log holds every entry, and the next event is accepted too.

    Append and project must not fail together. The appender writes durably
    before any projection runs, so a projection failure is downstream of a
    receipt that has already been given — refusing the next event over it would
    end a grilling because a cache could not be refreshed.
    """
    (session_dir / IMAGE1_FILE).mkdir()

    first = post(client, log.epoch, event("informational", key="k1", text="one"))
    second = post(client, log.epoch, event("informational", key="k2", text="two"))

    assert [receipt["status"] for receipt in first + second] == ["accepted", "accepted"]
    statuses = [entry for entry in log.entries() if entry.kind == STATUS_KIND]
    assert [entry.payload["phase"] for entry in statuses] == [STATUS_PHASE_ERROR] * 2
    assert "IsADirectoryError" in statuses[0].payload["detail"]
    lines = (session_dir / LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(log.entries()) == 4
    assert [entry.payload.get("text") for entry in log.entries() if entry.kind != STATUS_KIND] == [
        "one",
        "two",
    ]


def test_a_fold_that_cannot_complete_surfaces_on_the_status_lane_and_blocks_nothing(
    client: TestClient, log: SessionLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a projector that raises on an entry the appender accepted
    When that entry is written and another follows it
    Then both are accepted, the log holds both, and the failure surfaces as an
         error on the status lane.

    The fold is written to tolerate any log the appender accepted, so this
    forces the failure rather than finding one: the contract under test is that
    the session survives a projector that raises, whatever made it raise. A
    tolerant fold is the first defence and this seam is the second — and only
    the second one still holds when the first is wrong.
    """

    def boom(_epoch: str, _entries: Any) -> Image2:
        raise ValueError("unfoldable")

    monkeypatch.setattr("grillui.persistence.fold", boom)

    first = post(client, log.epoch, event("informational", key="k1", text="one"))
    second = post(client, log.epoch, event("informational", key="k2", text="two"))

    assert [receipt["status"] for receipt in first + second] == ["accepted", "accepted"]
    statuses = [entry for entry in log.entries() if entry.kind == STATUS_KIND]
    assert len(statuses) == 2
    assert statuses[0].payload["phase"] == STATUS_PHASE_ERROR
    assert "unfoldable" in statuses[0].payload["detail"]
    assert statuses[0].actor == "backend"


def test_a_status_emitted_while_the_append_lock_is_held_does_not_deadlock(
    session_dir: Path,
) -> None:
    """
    Given a caller already holding the appender's lock
    When it emits a status entry
    Then the entry lands rather than the session hanging.

    The status lane's job is to make a failure visible in milliseconds, and the
    lane fires from inside the same lock as the append it reports on. On a
    non-re-entrant lock that is a deadlock on precisely the path that exists to
    keep the session alive — and a deadlocked backend looks, from the page,
    exactly like an agent taking a long time.
    """
    log = SessionLog(session_dir)
    landed = threading.Event()

    def emit() -> None:
        with log._lock:  # the same lock an append holds
            log.emit_status(STATUS_PHASE_ERROR, "projection failed")
        landed.set()

    threading.Thread(target=emit, daemon=True).start()

    assert landed.wait(DEADLOCK_TIMEOUT), "emitting a status under the append lock deadlocked"
    assert log.entries()[-1].kind == STATUS_KIND
    assert log.seq == 1


def test_a_dead_status_lane_does_not_turn_acceptance_into_an_error(
    session_dir: Path,
) -> None:
    """
    Given a projection failure whose status report itself fails
    When project_and_persist runs
    Then nothing escapes — the batch was already accepted, and the last
    surface left is the process log, not a 500.
    """
    from unittest.mock import patch

    log = SessionLog(session_dir)
    with (
        patch("grillui.persistence.write_images", side_effect=OSError("disk full")),
        patch.object(log, "emit_status", side_effect=OSError("log unwritable")),
    ):
        project_and_persist(log)
