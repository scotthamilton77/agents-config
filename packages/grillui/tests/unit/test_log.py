"""The appender: what it assigns, what it keeps, and what survives it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from grillui.log import LOG_FILE, CorruptLogError, SessionLog
from grillui.schemas import EventSubmission


def _submit(log: SessionLog, key: str, **payload: object) -> Any:
    return log.submit(
        [
            EventSubmission(
                kind="informational", actor="grill-master", idempotency_key=key, payload=payload
            )
        ],
        log.epoch,
    )[0]


def test_restart_mints_a_new_epoch_on_a_continuing_sequence(session_dir: Path) -> None:
    """
    Given a session directory a process has already written to
    When a second process is stood up against the same directory
    Then it mints a different epoch and its next entry continues the sequence
         the directory had reached.

    The session directory is the session's identity; the epoch identifies one
    process's tenure over it and the sequence identifies the position. A
    sequence that reset on restart would let two entries share a position, and
    every client join keyed on it would silently pair the wrong pair.
    """
    first = SessionLog(session_dir)
    for index in range(1, 4):
        _submit(first, f"k{index}", text=str(index))
    assert first.seq == 3

    second = SessionLog(session_dir)

    assert second.epoch != first.epoch
    assert second.seq == 3
    assert [entry.payload["text"] for entry in second.entries()] == ["1", "2", "3"]
    assert _submit(second, "k4", text="4").seq == 4


def test_a_key_seen_before_the_restart_is_still_a_duplicate_after_it(
    session_dir: Path,
) -> None:
    """
    Given a key that landed under an earlier tenure
    When it is replayed against a fresh process on the same directory
    Then it is answered as a duplicate naming where it landed.

    The idempotency index is a property of the session, not of the process, so
    a client retrying across a restart must not double-append.
    """
    first = SessionLog(session_dir)
    _submit(first, "k1", text="once")

    second = SessionLog(session_dir)
    receipt = _submit(second, "k1", text="again")

    assert receipt.status == "duplicate"
    assert receipt.seq == 1
    assert second.seq == 1


def test_each_accepted_entry_is_one_durable_json_line(session_dir: Path) -> None:
    """
    Given two accepted writes
    When the log file is read back off disk
    Then it holds one JSON object per line carrying the backend-assigned
         sequence, epoch and timestamp.

    Pins the on-disk shape the recovery path depends on: the log is the single
    source of truth, so its bytes are the contract, not an implementation
    detail of this process.
    """
    log = SessionLog(session_dir)
    _submit(log, "k1", text="one")
    _submit(log, "k2", text="two")

    lines = (session_dir / LOG_FILE).read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    entries = [json.loads(line) for line in lines]
    assert [entry["seq"] for entry in entries] == [1, 2]
    assert {entry["epoch"] for entry in entries} == {log.epoch}
    assert all(entry["timestamp"].endswith("+00:00") for entry in entries)
    assert all(entry["idempotency_key"] for entry in entries)


def test_a_directory_that_does_not_exist_yet_is_created(tmp_path: Path) -> None:
    """
    Given a session directory that has never been used
    When a process is stood up against it
    Then the directory exists and the session starts at sequence zero.

    A first launch and a resume take the same path; the log's emptiness, not a
    flag, is what distinguishes them.
    """
    directory = tmp_path / "nested" / "session"

    log = SessionLog(directory)

    assert directory.is_dir()
    assert log.seq == 0
    assert log.entries() == []


def test_blank_lines_in_the_log_are_skipped_on_load(session_dir: Path) -> None:
    """
    Given a log file whose final write left a trailing blank line
    When a process loads it
    Then the blank contributes no entry.

    A log truncated at a line boundary is the ordinary shape after a kill; it
    must not become a parse failure that keeps the session from resuming.
    """
    session_dir.mkdir(parents=True)
    first = SessionLog(session_dir)
    _submit(first, "k1", text="one")
    path = session_dir / LOG_FILE
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

    second = SessionLog(session_dir)

    assert second.seq == 1
    assert len(second.entries()) == 1


def test_a_torn_final_line_is_dropped_and_the_session_resumes(session_dir: Path) -> None:
    """
    Given a log whose final line is half a JSON object — a crash between
    write and fsync
    When a process loads it
    Then the intact entries load and the torn line contributes nothing.

    The event the torn line held has no receipt anywhere, so dropping it loses
    nothing a client will not retry under its own idempotency key.
    """
    session_dir.mkdir(parents=True)
    first = SessionLog(session_dir)
    _submit(first, "k1", text="one")
    _submit(first, "k2", text="two")
    path = session_dir / LOG_FILE
    path.write_text(path.read_text(encoding="utf-8") + '{"seq": 3, "epo', encoding="utf-8")

    second = SessionLog(session_dir)

    assert second.seq == 2
    assert len(second.entries()) == 2


def test_appending_after_a_torn_line_does_not_corrupt_the_log(session_dir: Path) -> None:
    """
    Given a log whose final line was torn by a crash
    When the next tenure loads it and appends a new entry
    Then a third load reads every intact entry, because the torn bytes were
    removed from disk when the tenure was claimed.

    Appends are append-mode writes: torn bytes left in place would sit in front
    of the next entry, either fusing with it into one unreadable line or
    becoming interior corruption a later load refuses.
    """
    session_dir.mkdir(parents=True)
    first = SessionLog(session_dir)
    _submit(first, "k1", text="one")
    path = session_dir / LOG_FILE
    path.write_text(path.read_text(encoding="utf-8") + '{"seq": 2, "epo', encoding="utf-8")

    second = SessionLog(session_dir)
    _submit(second, "k2", text="two")
    third = SessionLog(session_dir)

    assert third.seq == 2
    assert [entry.seq for entry in third.entries()] == [1, 2]


def test_a_malformed_interior_line_refuses_to_load(session_dir: Path) -> None:
    """
    Given a log corrupted before its end
    When a process loads it
    Then loading fails naming the line, rather than silently dropping an
    entry a client holds a receipt for.
    """
    session_dir.mkdir(parents=True)
    first = SessionLog(session_dir)
    _submit(first, "k1", text="one")
    path = session_dir / LOG_FILE
    intact = path.read_text(encoding="utf-8")
    path.write_text("not json\n" + intact, encoding="utf-8")

    with pytest.raises(CorruptLogError, match="line 1"):
        SessionLog(session_dir)
