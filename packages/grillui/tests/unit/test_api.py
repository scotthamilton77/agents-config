"""The board endpoints: what each one costs, and what it is allowed to say."""

from __future__ import annotations

import builtins
import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import SEED_NODE, event, post, seed_node, seeded_log_file
from fastapi.testclient import TestClient

from grillui.api import create_app
from grillui.log import SessionLog
from grillui.schemas import REASON_UNKNOWN_KIND, Image1, Image2

LARGE_LOG = 5000


@pytest.fixture
def opened_paths(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record every path the process opens, by any of the three routes Python
    reaches the filesystem through."""
    recorded: list[str] = []

    def spy(original: Any) -> Any:
        def wrapper(file: Any, *args: Any, **kwargs: Any) -> Any:
            recorded.append(str(file))
            return original(file, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(builtins, "open", spy(builtins.open))
    monkeypatch.setattr(io, "open", spy(io.open))
    monkeypatch.setattr(os, "open", spy(os.open))
    yield recorded


def test_status_reports_epoch_and_sequence_without_opening_any_session_file(
    session_dir: Path, opened_paths: list[str]
) -> None:
    """
    Given a session whose log is already large
    When the status endpoint is called
    Then it answers with the epoch and the current sequence, having opened
         neither the log file nor an image file.

    Pins the cheap check as genuinely cheap: it is answered from memory, so a
    page may ask it as often as it likes whatever the log has grown to. File
    access is instrumented rather than reasoned about, because a read added
    later would otherwise pass this test unchanged.
    """
    seeded_log_file(session_dir, LARGE_LOG)
    client = TestClient(create_app(SessionLog(session_dir)))
    opened_paths.clear()

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["seq"] == LARGE_LOG
    assert response.json()["epoch"]
    touched = [path for path in opened_paths if str(session_dir) in path]
    assert touched == []


def test_a_second_status_call_stays_correct_after_the_log_grows(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a status reading taken before a write
    When an event is appended and status is read again
    Then the sequence has advanced to the appended entry's.

    The negative control for the test above: answering from memory must not
    mean answering from a stale snapshot.
    """
    assert client.get("/status").json()["seq"] == 0

    post(client, log.epoch, event("informational", key="k1", text="hello"))

    assert client.get("/status").json() == {"epoch": log.epoch, "seq": 1}


def test_state_read_returns_the_epoch_sequence_and_image_one(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a session with a node on the board
    When state is read
    Then it carries the epoch, the current sequence and a schema-valid image 1.

    Pins the recovery read: this is what a page or an agent uses after any
    doubt, which is why a reconnect asserts nothing of its own.
    """
    seed_node(client, log.epoch)

    body = client.get("/state").json()

    assert body["epoch"] == log.epoch
    assert body["seq"] == log.seq == 1
    image = Image1.model_validate(body["image1"])
    assert [node.id for node in image.decisions] == [SEED_NODE]


def test_update_read_with_a_stale_epoch_is_refused_with_409(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a cursor read presenting an epoch from an earlier tenure
    When it is issued
    Then the backend answers 409 rather than serving entries.

    The read-side half of the epoch rule: a client on a dead epoch is told so
    instead of being handed data it will interleave wrongly.
    """
    response = client.get("/updates", params={"epoch": f"ended-{log.epoch}", "cursor": 0})

    assert response.status_code == 409
    assert log.epoch in response.json()["detail"]


def test_update_read_returns_only_entries_past_the_cursor(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given three appended entries
    When the log is read from a cursor of one
    Then only the entries after that position come back, with the current
         sequence alongside them.

    Pins that the cursor is a position in the backend's sequence, never a
    client-side counter.
    """
    for index in range(1, 4):
        post(client, log.epoch, event("informational", key=f"k{index}", text=str(index)))

    body = client.get("/updates", params={"epoch": log.epoch, "cursor": 1}).json()

    assert [entry["seq"] for entry in body["entries"]] == [2, 3]
    assert body["seq"] == 3


def test_image_endpoints_return_schema_valid_images_and_only_image_two_has_history(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a board with a node, an answer and a thread turn
    When both image endpoints are read
    Then each validates against its own schema, and history is present on
         image 2 and absent from image 1.

    Pins the one field that separates the two images, over a log where the
    difference is observable rather than vacuous.
    """
    seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="k-answer",
            target=SEED_NODE,
            answer={"option": "a", "text": None},
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

    first = client.get("/image1").json()
    second = client.get("/image2").json()

    Image1.model_validate(first)
    image2 = Image2.model_validate(second)
    assert "history" not in first
    assert [item.kind for item in image2.history[SEED_NODE]] == ["add-node", "answer"]
    assert image2.history[SEED_NODE][-1].why == "the audit trail is the point"
    assert [thread.id for thread in image2.threads] == ["t1"]


def test_a_batch_of_n_events_returns_n_receipts_in_submission_order(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a batch mixing writes that will be accepted with one that will not
    When it is submitted
    Then exactly one receipt comes back per event, in the order they were sent.

    Pins that a rejection inside a batch neither drops its own receipt nor
    shifts the others: the caller joins receipts to events positionally.
    """
    seed_node(client, log.epoch)
    submitted = [
        event("informational", key="k1", text="one"),
        event("teleport-node", key="k2"),
        event("revise", key="k3", target=SEED_NODE),
        event("informational", key="k1", text="replay"),
    ]

    receipts = post(client, log.epoch, *submitted)

    assert [receipt["idempotency_key"] for receipt in receipts] == ["k1", "k2", "k3", "k1"]
    assert [receipt["status"] for receipt in receipts] == [
        "accepted",
        "rejected",
        "accepted",
        "duplicate",
    ]
    assert receipts[1]["reason"] == REASON_UNKNOWN_KIND


def test_an_unrecognised_envelope_field_is_refused_rather_than_ignored(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a submission carrying a field the envelope does not define
    When it is posted
    Then the request is refused and nothing is appended.

    Pins that the envelope is a contract on the bytes: silently dropping an
    unknown field would let a client believe it sent something the backend
    never saw.
    """
    response = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [{"kind": "informational", "actor": "backend", "seq": 12}],
        },
    )

    assert response.status_code == 422
    assert log.entries() == []
