"""Every write is answered by a typed receipt saying what happened.

There is no acknowledgement here that does not say what happened: an
`ok` over a silent no-op is what lets an agent tell a human something is on the
board when it is not. These tests pin all three verdicts and the closed
rejection vocabulary.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import SEED_NODE, event, post, proposed, queue_gesture, seed_node
from fastapi.testclient import TestClient

from grillui.log import SessionLog
from grillui.schemas import (
    APPLY_KIND,
    REASON_EMPTY_ANSWER,
    REASON_EPOCH_MISMATCH,
    REASON_FOREIGN_THREAD,
    REASON_MISSING_KEY,
    REASON_PENDING_CONFLICT,
    REASON_THREAD_MAP_MUTATION,
    REASON_THREAD_WITHOUT_TURN,
    REASON_UNKNOWN_KIND,
    REASON_UNKNOWN_NODE,
    REASON_UNKNOWN_OPTION,
    REASON_UNKNOWN_PENDING,
    REASON_UNKNOWN_THREAD,
    REJECTION_REASONS,
    payload_problem,
)


def stale_epoch(log: SessionLog) -> str:
    """An epoch derived from the live one, so it is guaranteed to differ."""
    return f"ended-{log.epoch}"


def test_first_write_is_accepted_with_its_assigned_sequence_and_applied_object(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a well-formed first write
    When it is submitted under the current epoch
    Then the receipt is `accepted`, carries the sequence the backend assigned,
         and states what was applied and whether it was amended.

    Pins the accepted half of the uniform-receipt rule: the caller learns the
    authoritative sequence from the receipt, never from a counter of its own.
    """
    receipt = post(
        client, log.epoch, event("revise", key="k1", target=seed_node(client, log.epoch))
    )[0]

    assert receipt["status"] == "accepted"
    assert receipt["seq"] == log.seq == 2
    assert receipt["epoch"] == log.epoch
    assert receipt["idempotency_key"] == "k1"
    assert receipt["applied"] == {
        "kind": "revise",
        "target": SEED_NODE,
        "as": "sent",
        "amendments": None,
    }


def test_replayed_key_returns_duplicate_naming_the_original_sequence(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an idempotency key that already landed
    When it is re-posted with a different body
    Then the receipt is `duplicate` naming the sequence it landed at, and
         nothing is appended.

    Pins that the key, not the body, is what identifies a write: a retry whose
    payload drifted must not become a second entry.
    """
    seed_node(client, log.epoch)
    first = post(client, log.epoch, event("informational", key="k1", text="original"))[0]
    assert first["status"] == "accepted"

    second = post(client, log.epoch, event("revise", key="k1", target=SEED_NODE, why="different"))[
        0
    ]

    assert second == {
        "status": "duplicate",
        "idempotency_key": "k1",
        "epoch": log.epoch,
        "seq": first["seq"],
    }
    assert log.seq == first["seq"]
    assert log.entries()[-1].payload == {"text": "original"}


def test_stale_epoch_write_is_refused_naming_both_epochs(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a client whose epoch belongs to an earlier tenure
    When it writes
    Then the receipt is `epoch mismatch`, names the server epoch and the
         presented one, and nothing is appended.

    Pins the self-healing path: the client is told which epoch is current, so
    it re-reads state instead of guessing.
    """
    stale = stale_epoch(log)

    receipt = post(client, stale, event("informational", key="k1", text="hello"))[0]

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_EPOCH_MISMATCH
    assert log.epoch in receipt["detail"]
    assert stale in receipt["detail"]
    assert receipt["epoch"] == log.epoch
    assert log.entries() == []


def _refuse_missing_key(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(client, log.epoch, event("informational", key=None, text="unkeyed"))[0]


def _refuse_stale_epoch(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(client, stale_epoch(log), event("informational", key="k1", text="hello"))[0]


def _refuse_unknown_kind(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(client, log.epoch, event("teleport-node", key="k1"))[0]


def _refuse_unknown_node(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(client, log.epoch, event("revise", key="k1", target="no-such-node"))[0]


def _refuse_empty_answer(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="k1",
            target=SEED_NODE,
            answer={"option": None, "text": None},
        ),
    )[0]


def _refuse_unknown_option(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="k1",
            target=SEED_NODE,
            answer={"option": "z", "text": None},
        ),
    )[0]


def _refuse_thread_without_turn(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(client, log.epoch, event("thread-turn", actor="human", channel="t1", key="k1"))[0]


def _refuse_thread_map_mutation(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event("revise", actor="thread-agent", channel="t1", key="k1", target=SEED_NODE),
    )[0]


def _refuse_unknown_thread(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event("thread-fold", actor="human", channel="no-such-thread", key="k1", impact=[]),
    )[0]


def _open_a_thread_on_another_decision(client: TestClient, log: SessionLog) -> None:
    """A thread anchored to a decision that is not the one about to be answered."""
    seed_node(client, log.epoch, "n2")
    post(
        client,
        log.epoch,
        event(
            "thread-created",
            actor="human",
            channel="t-elsewhere",
            key="opened",
            decision="n2",
            turns=[{"who": "human", "text": "Say more about compaction."}],
        ),
    )


def _refuse_foreign_thread(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="k1",
            target=SEED_NODE,
            answer={"text": "an append-only log"},
            from_thread="t-elsewhere",
        ),
    )[0]


def _refuse_unknown_pending(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return queue_gesture(client, log.epoch, APPLY_KIND, "no-such-proposal#0", key="k1")


def _leave_a_conflicted_proposal(client: TestClient, log: SessionLog) -> None:
    """Put the board where a proposal and the human disagree: the agent proposes
    an invalidation, and the human answers that decision while it waits."""
    post(client, log.epoch, event("invalidate", key="proposal", target=SEED_NODE, why="moot"))
    post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="answered-around-it",
            target=SEED_NODE,
            answer={"text": "an append-only log"},
        ),
    )


def _refuse_pending_conflict(client: TestClient, log: SessionLog) -> dict[str, Any]:
    return queue_gesture(client, log.epoch, APPLY_KIND, *proposed(client, SEED_NODE), key="k1")


# What a refusal needs on the board before it can be provoked, kept out of the
# refusal itself so the "nothing was appended" claim stays exact: setup lands
# before the log is snapshotted, and the refused write is the only thing after.
SETUPS: dict[str, Callable[[TestClient, SessionLog], None]] = {
    REASON_PENDING_CONFLICT: _leave_a_conflicted_proposal,
    REASON_FOREIGN_THREAD: _open_a_thread_on_another_decision,
}


REFUSALS: dict[str, Callable[[TestClient, SessionLog], dict[str, Any]]] = {
    REASON_MISSING_KEY: _refuse_missing_key,
    REASON_EPOCH_MISMATCH: _refuse_stale_epoch,
    REASON_UNKNOWN_KIND: _refuse_unknown_kind,
    REASON_UNKNOWN_NODE: _refuse_unknown_node,
    REASON_EMPTY_ANSWER: _refuse_empty_answer,
    REASON_UNKNOWN_OPTION: _refuse_unknown_option,
    REASON_THREAD_WITHOUT_TURN: _refuse_thread_without_turn,
    REASON_THREAD_MAP_MUTATION: _refuse_thread_map_mutation,
    REASON_UNKNOWN_PENDING: _refuse_unknown_pending,
    REASON_UNKNOWN_THREAD: _refuse_unknown_thread,
    REASON_FOREIGN_THREAD: _refuse_foreign_thread,
    REASON_PENDING_CONFLICT: _refuse_pending_conflict,
}


@pytest.mark.parametrize("reason", sorted(REJECTION_REASONS))
def test_each_rejection_reason_produces_exactly_that_typed_receipt(
    reason: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given a write that violates exactly one rule
    When it is submitted
    Then the receipt is `rejected` naming that reason with a detail, and the
         rejected event appears nowhere in the log.

    The parametrisation is driven by the reason vocabulary itself, so a reason
    added without a case for it turns this suite red rather than shipping
    untested.
    """
    seed_node(client, log.epoch)
    if reason in SETUPS:
        SETUPS[reason](client, log)
    accepted_so_far = [entry.kind for entry in log.entries()]

    receipt = REFUSALS[reason](client, log)

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == reason
    assert receipt["detail"]
    assert receipt["epoch"] == log.epoch
    assert [entry.kind for entry in log.entries()] == accepted_so_far


def test_a_missing_key_receipt_carries_a_null_key_rather_than_inventing_one(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a submission with no idempotency key
    When it is refused
    Then the receipt's `idempotency_key` is null.

    Pins the one case where the echoed key is null: a receipt that invented a
    key would let a client believe it had sent one.
    """
    receipt = _refuse_missing_key(client, log)

    assert receipt["idempotency_key"] is None
    assert receipt["reason"] == REASON_MISSING_KEY


def test_a_map_mutation_on_the_map_channel_from_the_grill_master_is_accepted(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the same mutation the thread-agent case is refused for
    When the grill-master submits it on the map channel
    Then it is accepted.

    The negative control for the sole-author rule: without it, a refusal that
    fired for the wrong reason would still look correct.
    """
    seed_node(client, log.epoch)

    receipt = post(client, log.epoch, event("revise", key="k1", target=SEED_NODE))[0]

    assert receipt["status"] == "accepted"


def board_decision(client: TestClient, node_id: str = SEED_NODE) -> dict[str, Any]:
    """One decision as image 1 states it -- what the human and the next agent
    read, rather than what a receipt claimed."""
    image = client.get("/image1").json()
    return next(node for node in image["decisions"] if node["id"] == node_id)


def test_an_answer_naming_an_option_the_decision_does_not_offer_leaves_the_board_open(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision offering the options `a` and `b`
    When an answer names option `z`
    Then the receipt names the unknown-option reason and both the id sent and
         the ids offered, nothing is appended, and the decision is still open
         with no answer against it.

    The empty-answer refusal does not reach this one: the answer carries an
    option, so without a check of its own the board settles onto a choice the
    page cannot render, and image 1 shows a decision answered with nothing.
    """
    seed_node(client, log.epoch)
    before = log.entries()

    receipt = _refuse_unknown_option(client, log)

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_OPTION
    assert "'z'" in receipt["detail"]
    assert "'a'" in receipt["detail"]
    assert "'b'" in receipt["detail"]
    assert log.entries() == before
    assert board_decision(client)["status"] == "open"
    assert board_decision(client)["answer"] is None


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"option": "b", "text": None}, id="an-option-the-decision-offers"),
        pytest.param({"option": None, "text": "neither of those"}, id="text-alone"),
    ],
)
def test_an_answer_the_decision_can_carry_is_still_accepted(
    answer: dict[str, Any], client: TestClient, log: SessionLog
) -> None:
    """
    Given the decision the unknown-option refusal is provoked against
    When the answer names an offered option, or carries text alone
    Then it is accepted and the decision settles.

    The negative control for the option check: a refusal that fired for every
    answer would look as correct as one that fired for the right one, and
    answering in prose -- how a human says none of the options fits -- would
    stop working.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event("answer", actor="human", key="k1", target=SEED_NODE, answer=answer),
    )[0]

    assert receipt["status"] == "accepted", receipt
    assert board_decision(client)["status"] == "settled"


def test_a_settle_without_an_answer_is_still_refused_with_the_typed_receipt(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an agent settling a decision over the wire and carrying no answer
    When it is submitted
    Then the envelope shape takes it -- a settle is only required to name its
         target -- and the receipt refuses it with the typed empty-answer
         reason, exactly as before.

    The requirement that a settle carry a nested `answer` is enforced at the
    document gate, where the seat still has its retry. Moving it into the
    envelope shape instead would turn this receipt into a raised payload fault,
    which the rejection vocabulary has no word for and the page cannot show.
    """
    seed_node(client, log.epoch)

    assert payload_problem("settle", {"target": SEED_NODE}) is None
    receipt = post(client, log.epoch, event("settle", key="k1", target=SEED_NODE))[0]

    assert receipt["status"] == "rejected", receipt
    assert receipt["reason"] == REASON_EMPTY_ANSWER, receipt


NEW_OPTIONS = [{"id": "c", "text": "A second log"}, {"id": "d", "text": "No store at all"}]


def answer_with(client: TestClient, log: SessionLog, option: str, key: str) -> dict[str, Any]:
    return post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key=key,
            target=SEED_NODE,
            answer={"option": option, "text": None},
        ),
    )[0]


def test_a_revise_waiting_on_the_human_does_not_change_which_options_an_answer_may_name(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a settled decision offering `a` and `b`, and an agent's revise
          offering `c` and `d` that is waiting in the queue
    When the human answers while it waits, and again after applying it
    Then the options an answer may name are the ones image 1 shows: `a` and `b`
         while the proposal waits, `c` and `d` once it lands.

    The option check reads the board, not the log. An appender that took the
    proposal's bytes as they arrived would refuse the option the human is
    looking at and accept one only the agent has seen -- and a proposal the
    human dismisses would change what the board accepts having changed nothing
    the board shows.
    """
    seed_node(client, log.epoch)
    assert answer_with(client, log, "b", "settling")["status"] == "accepted"
    post(client, log.epoch, event("revise", key="proposal", target=SEED_NODE, options=NEW_OPTIONS))
    assert proposed(client, SEED_NODE), "the revise must be waiting, not landed"
    assert [option["id"] for option in board_decision(client)["options"]] == ["a", "b"]

    assert answer_with(client, log, "a", "while-it-waits")["status"] == "accepted"
    refused = answer_with(client, log, "c", "not-offered-yet")
    assert refused["status"] == "rejected"
    assert refused["reason"] == REASON_UNKNOWN_OPTION

    # Those answers moved the board under the waiting proposal, so it is now in
    # conflict and the agent sends it again -- the queue's own rule, not this
    # test working around one.
    post(client, log.epoch, event("revise", key="again", target=SEED_NODE, options=NEW_OPTIONS))
    queue_gesture(client, log.epoch, APPLY_KIND, proposed(client, SEED_NODE)[-1], key="applying")

    assert [option["id"] for option in board_decision(client)["options"]] == ["c", "d"]
    assert answer_with(client, log, "c", "now-offered")["status"] == "accepted"
    stale = answer_with(client, log, "a", "no-longer-offered")
    assert stale["status"] == "rejected"
    assert stale["reason"] == REASON_UNKNOWN_OPTION


def test_the_rejection_vocabulary_is_exactly_these_twelve_reasons() -> None:
    """
    Given the closed set of reasons a receipt may name
    When it is read
    Then it is exactly these twelve, and a payload fault is not among them.

    A payload the vocabulary has no word for is refused whole, before anything
    lands, rather than by minting a thirteenth reason every caller switching on
    this set would then have to learn.
    """
    vocabulary = {
        REASON_MISSING_KEY,
        REASON_EPOCH_MISMATCH,
        REASON_UNKNOWN_KIND,
        REASON_UNKNOWN_NODE,
        REASON_EMPTY_ANSWER,
        REASON_THREAD_WITHOUT_TURN,
        REASON_THREAD_MAP_MUTATION,
        REASON_UNKNOWN_PENDING,
        REASON_PENDING_CONFLICT,
        REASON_UNKNOWN_THREAD,
        REASON_FOREIGN_THREAD,
        REASON_UNKNOWN_OPTION,
    }

    assert vocabulary == REJECTION_REASONS
