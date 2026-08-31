"""The appender: what it assigns, what it keeps, and what survives it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from grillui.log import LOG_FILE, CorruptLogError, PayloadRefusedError, SessionLog
from grillui.schemas import (
    APPLY_KIND,
    DISMISS_KIND,
    FOLD_KIND,
    PENDING_KEY,
    EventSubmission,
    batch_payload_problem,
)


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


# ---- the payload gate both client write paths go through ---------------------

# One fold whose sub-update invalidates a decision without saying why: bytes the
# HTTP gate refuses, offered here the way a driver offers them.
WHY_LESS_INVALIDATE: dict[str, Any] = {
    "kind": FOLD_KIND,
    "actor": "grill-master",
    "channel": "map",
    "idempotency_key": "drive-1",
    "payload": {"updates": [{"kind": "invalidate", "target": "d1"}]},
}


def _malformed(**overrides: Any) -> EventSubmission:
    """The malformed fold, with whatever the caller changes about it."""
    return EventSubmission.model_validate({**WHY_LESS_INVALIDATE, **overrides})


def test_a_why_less_invalidate_offered_to_the_appender_is_refused_before_anything_lands(
    log: SessionLog,
) -> None:
    """
    Given a fold whose sub-update invalidates a decision without saying why
    When it is submitted straight to the appender, as a driver submits
    Then the batch is refused for its shape and no entry lands.

    The rationale is what makes an invalidation readable; without this gate the
    malformed proposal would sit in the human's queue, and the human applying it
    would be who finds out.
    """
    with pytest.raises(PayloadRefusedError) as refused:
        log.submit([_malformed()], log.epoch)

    assert refused.value.problem.startswith("event 0: ")
    assert "why" in refused.value.problem
    assert log.entries() == []


def test_both_write_paths_refuse_the_same_bytes_with_the_same_words(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given one malformed fold, offered over the wire and offered to the appender
    When each path judges it
    Then the wire answers 422 and the appender raises, both quoting the one
         problem text, and nothing is appended either way.

    Two seams calling two readers is how they come to disagree; one reader,
    called from both, is what makes the equivalence a property rather than a
    coincidence to be re-checked.
    """
    response = client.post("/events", json={"epoch": log.epoch, "events": [WHY_LESS_INVALIDATE]})
    with pytest.raises(PayloadRefusedError) as refused:
        log.submit([_malformed()], log.epoch)

    spoken = batch_payload_problem([_malformed()])
    assert spoken is not None
    assert response.status_code == 422
    assert response.json()["detail"] == spoken
    assert refused.value.problem == spoken
    assert log.entries() == []


@pytest.mark.parametrize("kind", [APPLY_KIND, DISMISS_KIND])
@pytest.mark.parametrize("named", ["prop-1", [], ["prop-1", 2]])
def test_a_queue_gesture_whose_pending_is_no_usable_list_of_ids_is_refused_at_the_appender(
    kind: str, named: Any, log: SessionLog
) -> None:
    """
    Given an apply or a dismiss whose `pending` is a bare string, an empty list,
         or a list with a non-string in it
    When it is submitted straight to the appender
    Then it is refused naming the field, and nothing is appended.

    No production caller reaches this: the wire gate refuses these bytes and the
    queue-gesture check refuses a non-human actor. It is the appender's own
    contract, pinned here so that the gate cannot quietly narrow to whatever the
    callers of the day happen to send.
    """
    with pytest.raises(PayloadRefusedError) as refused:
        log.submit(
            [
                _malformed(
                    kind=kind,
                    actor="human",
                    idempotency_key="gesture-1",
                    payload={PENDING_KEY: named},
                )
            ],
            log.epoch,
        )

    assert PENDING_KEY in refused.value.problem
    assert log.entries() == []


def test_a_fault_in_a_batchs_second_event_appends_neither_and_receipts_neither(
    log: SessionLog,
) -> None:
    """
    Given a two-event batch whose first event is well-formed and whose second
         carries a payload fault
    When it is submitted
    Then the whole batch is refused before any append: nothing lands, and the
         caller receives no receipt for either event.

    Refusing part-way through would leave an entry in the log that nobody ever
    got a receipt for, which is the one failure the receipt contract exists to
    make impossible.
    """
    good = EventSubmission(
        kind="informational",
        actor="grill-master",
        idempotency_key="ok-1",
        payload={"text": "the budget landed"},
    )

    with pytest.raises(PayloadRefusedError) as refused:
        log.submit([good, _malformed()], log.epoch)

    assert refused.value.problem.startswith("event 1: ")
    assert log.entries() == []
    assert log.seq == 0


def test_a_replayed_key_carrying_a_malformed_body_is_refused_for_its_shape(
    log: SessionLog,
) -> None:
    """
    Given a key that has already landed
    When it is presented again on a body the appender would not take
    Then it is refused for the shape rather than answered as a duplicate.

    The replay answer is what a client's retry is owed, and a retry carries the
    bytes it sent before. Bytes it did not send before are a different write
    wearing a used key, and answering that off the index would tell the sender
    something landed that this log would never have taken.
    """
    _submit(log, "k1", text="one")

    with pytest.raises(PayloadRefusedError):
        log.submit([_malformed(idempotency_key="k1")], log.epoch)

    assert log.seq == 1


def test_a_malformed_batch_carrying_a_stale_epoch_is_refused_for_its_shape(
    log: SessionLog,
) -> None:
    """
    Given a malformed batch presented under an epoch the log does not hold
    When it is submitted
    Then the shape refusal answers, not an epoch-mismatch receipt: the
         vocabulary question is asked before any identity question.
    """
    with pytest.raises(PayloadRefusedError):
        log.submit([_malformed()], "not-the-epoch")

    assert log.entries() == []


def test_a_backend_authored_record_is_judged_by_nothing(log: SessionLog) -> None:
    """
    Given payload bytes the client write paths refuse
    When the backend records them under its own authority
    Then the entry lands: record takes the backend's word and runs no gate.
    """
    entry = log.record(FOLD_KIND, {"updates": [{"kind": "invalidate", "target": "d1"}]})

    assert entry.seq == 1
    assert log.seq == 1
