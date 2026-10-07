"""The map doctor proposes; the human applies.

The doctor is the grill-master sent over the whole board to say what no longer
holds. Every structural change its document carries waits in the inbox for the
human -- the kinds an ordinary map turn lands at once included, a new decision
among them -- because a whole-map reassessment is exactly the turn whose reach
nobody bought.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from conftest import TIMEOUT, SpyDriver, document, run_turns

from grillui.drivers import HeavyDriver
from grillui.lane import Lane
from grillui.projector import replay
from grillui.schemas import APPLY_KIND, FOLD_KIND, EventSubmission
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog

PLAIN = [{"id": "a", "text": "Yes"}, {"id": "c", "text": "No"}]
RETITLED = "Which d2, given the store?"
ADDED = {
    "kind": "add-node",
    "target": "d9",
    "short": "d9",
    "title": "Who reads the log?",
    "body": "Decide.",
    "prereqs": [],
    "options": PLAIN,
    "why": "nothing asks it",
}


def _seed(log: SessionLog) -> None:
    for node in ("d1", "d2"):
        receipt = log.submit(
            [
                EventSubmission(
                    kind="add-node",
                    actor="grill-master",
                    idempotency_key=f"seed-{node}",
                    payload={
                        "target": node,
                        "short": node,
                        "title": f"Which {node}?",
                        "body": "Decide.",
                        "prereqs": [],
                        "options": PLAIN,
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


@dataclass
class OneReplyCli:
    """A `claude` CLI that answers every call with one document."""

    reply: str
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str], _directory: Path, /) -> str:
        self.calls.append(list(argv))
        return json.dumps({"session_id": "chain-1", "result": self.reply})


def _doctor(log: SessionLog, reply: str) -> tuple[Lane, OneReplyCli]:
    cli = OneReplyCli(reply)
    lane = Lane(log, SpyDriver(), HeavyDriver(TierConfig.from_env({}), cli))
    turn = lane.call_doctor()
    assert turn is not None
    turn.join(TIMEOUT)
    assert not turn.is_alive()
    return lane, cli


def _queued(log: SessionLog) -> dict[tuple[str, str | None], str]:
    return {
        (one.kind, one.target): one.id
        for one in replay(log.epoch, log.entries()).pending
        if one.kind != "informational"
    }


def _node(log: SessionLog, node_id: str) -> Any:
    return next(
        (one for one in replay(log.epoch, log.entries()).decisions if one.id == node_id), None
    )


def test_pnd_a8_the_doctors_document_lands_nothing_directly_an_add_node_included(
    log: SessionLog,
) -> None:
    """
    Given a board with two unanswered decisions
    When the doctor's document adds a decision and revises an unanswered one
    Then neither lands: both wait in the inbox, the board is unchanged, and the
         entry the turn landed as says it was the doctor's.

    An ordinary map turn lands both of these at once. The doctor's does not,
    because nobody asked for its changes one by one.
    """
    _seed(log)
    revise = {"kind": "revise", "target": "d2", "title": RETITLED, "why": "the store moved it"}

    _doctor(log, document("Reassessed.", updates=[ADDED, revise]))

    assert _node(log, "d9") is None, "the doctor's add-node landed"
    assert _node(log, "d2").title == "Which d2?", "the doctor's revise landed"
    assert set(_queued(log)) == {("add-node", "d9"), ("revise", "d2")}
    landed = [one for one in log.entries() if one.actor == "grill-master" and one.kind == FOLD_KIND]
    assert landed[-1].payload.get("reassess") is True


def test_pnd_a8_the_human_applying_the_doctors_proposal_lands_it(log: SessionLog) -> None:
    """
    Given the doctor's add-node waiting in the inbox
    When the human applies it
    Then the decision is on the board.
    """
    _seed(log)
    _doctor(log, document("Reassessed.", updates=[ADDED]))
    pending = _queued(log)[("add-node", "d9")]

    run_turns(
        Lane(log),
        EventSubmission(
            kind=APPLY_KIND,
            actor="human",
            idempotency_key="apply-d9",
            payload={"pending": [pending]},
        ),
    )

    assert _node(log, "d9") is not None


def test_pnd_a8_an_entry_recorded_before_the_marker_replays_as_it_did(log: SessionLog) -> None:
    """
    Given a grill-master entry carrying an add-node and no doctor marker, as
          every entry written before the marker existed does
    When the log is replayed
    Then the add-node lands, exactly as it always did.
    """
    _seed(log)
    receipt = log.submit(
        [
            EventSubmission(
                kind=FOLD_KIND,
                actor="grill-master",
                idempotency_key="old-turn",
                payload={"updates": [{"kind": "informational", "text": "Added."}, ADDED]},
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted"

    assert _node(log, "d9") is not None
    assert ("add-node", "d9") not in _queued(log)


def test_pnd_a8_the_doctor_is_told_every_change_it_sends_waits(log: SessionLog) -> None:
    """
    Given a board
    When the doctor is called
    Then its brief says every change it sends waits for the human, so it is
         not told a new decision lands at once.
    """
    _seed(log)
    _, cli = _doctor(log, document("Reassessed."))

    assert "waits for the human" in cli.calls[0][-1]
