"""What an agent is given, checked against what the backend recorded giving it.

Every assertion about completeness below reads a file the backend wrote under
`dispatches/`. Checking an in-memory context the test itself assembled would
pass just as happily against a recorder that dropped half of it on the way to
disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import event, post, seed_node
from fastapi.testclient import TestClient

from grillui.dispatch import DISPATCH_DIR, DispatchIncompleteError, record_dispatch, verify_complete
from grillui.log import SessionLog
from grillui.projector import fold
from grillui.schemas import DispatchContext

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
