"""The update kinds: what each one is allowed to say, and what it does to the board.

The board is what an agent reasons from next turn, so every claim here is made
against a projected image rather than against a receipt alone: a receipt that
says `accepted` over an update that changed nothing is exactly the silent no-op
the uniform-receipt rule exists to prevent.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import SEED_NODE, apply_all, event, post, seed_node
from fastapi.testclient import TestClient

from grillui.log import SessionLog
from grillui.projector import fold
from grillui.schemas import REASON_UNKNOWN_KIND, REASON_UNKNOWN_NODE, Image1

OPTIONS = [{"id": "a", "text": "Redis"}, {"id": "b", "text": "No cache at all"}]


def decisions(client: TestClient) -> dict[str, Any]:
    """Image 1's decisions, keyed by id."""
    image = client.get("/image1").json()
    Image1.model_validate(image)
    node_map: dict[str, Any] = {node["id"]: node for node in image["decisions"]}
    return node_map


def image1(client: TestClient) -> dict[str, Any]:
    board: dict[str, Any] = client.get("/image1").json()
    return board


def history(client: TestClient, node_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = client.get("/image2").json()["history"].get(node_id, [])
    return entries


def add_node(key: str, **payload: Any) -> dict[str, Any]:
    """An add-node carrying the question, options and prereqs the schema asks
    for, minus whatever the caller overrides."""
    return event(
        "add-node",
        key=key,
        **{
            "title": "Which cache?",
            "body": "Pick a cache, or none.",
            "short": "Cache",
            "prereqs": [],
            "options": OPTIONS,
            **payload,
        },
    )


def settled(client: TestClient, epoch: str, node_id: str, key: str) -> None:
    receipt = post(
        client,
        epoch,
        event(
            "answer",
            actor="human",
            key=key,
            target=node_id,
            answer={"option": "a", "text": "an append-only log"},
            why="the audit trail is the point",
        ),
    )[0]
    assert receipt["status"] == "accepted"


# ── add-node: minting, the echo, and the loop back through the minted id ──


def test_add_node_mints_a_node_id_rather_than_only_accepting_a_pre_baked_one(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node carrying a question, options and prereqs but no id
    When it is submitted
    Then the backend mints an id, echoes the materialised node back in the
         receipt, and the node is on the board and answerable.

    The agent chose the question and not the id, so without the echo its only
    route to the node it just asked for is to read the whole board back and
    guess which one is new.
    """
    receipt = post(client, log.epoch, add_node("mint-1"))[0]

    assert receipt["status"] == "accepted"
    minted = receipt["applied"]["target"]
    assert minted == "n-1"
    assert receipt["node"]["id"] == minted
    assert receipt["node"]["title"] == "Which cache?"
    assert [option["id"] for option in receipt["node"]["options"]] == ["a", "b"]
    assert receipt["node"]["status"] == "open"
    assert image1(client)["frontier"] == [minted]


def test_a_minted_node_is_answerable_and_revisable_in_the_same_session(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a node the backend minted an id for
    When the human answers it and the agent then revises it by that id
    Then both land on the same decision.

    The full loop is the claim: an id that could be minted but not used again
    would be an echo of a node nobody can reach. The revise takes the long way
    round -- it names a decision the human has already answered, so it waits in
    the queue for their gesture, and the minted id has to survive that too.
    """
    minted = post(client, log.epoch, add_node("mint-1"))[0]["node"]["id"]

    answered = post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="answer-1",
            target=minted,
            answer={"option": "a", "text": "Redis"},
            why="the read path is what hurts",
        ),
    )[0]
    revised = post(
        client,
        log.epoch,
        event(
            "revise",
            key="revise-1",
            target=minted,
            title="Which cache, now that the budget is fixed?",
            why="the budget landed",
        ),
    )[0]

    assert [answered["status"], revised["status"]] == ["accepted", "accepted"]
    assert revised["updates"] == [
        {
            "kind": "revise",
            "target": minted,
            "status": "queued",
            "as": "sent",
            "amendments": None,
            "reason": None,
            "detail": None,
            "node": None,
        }
    ]
    assert apply_all(client, log.epoch, minted)["status"] == "accepted"
    node = decisions(client)[minted]
    assert node["title"] == "Which cache, now that the budget is fixed?"
    assert node["status"] == "settled"
    assert node["answer"] == {"option": "a", "text": "Redis"}
    assert [item["kind"] for item in history(client, minted)] == ["add-node", "answer", "revise"]


def test_a_supplied_node_id_is_honoured_so_a_seeded_board_keeps_its_own_ids(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node that names its own id
    When it is submitted
    Then that id is what lands, not a minted one.

    A board seeded from a handoff names its decisions itself, and renaming them
    on the way in would break every prereq the handoff wrote.
    """
    receipt = post(client, log.epoch, add_node("seeded-1", target="storage"))[0]

    assert receipt["applied"]["target"] == "storage"
    assert set(decisions(client)) == {"storage"}


# ── invalidate: the block and its justification are one item ──


def test_invalidate_carries_its_rationale_onto_the_decision_it_blocks(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision and a neighbouring one
    When the agent invalidates the first with rationale text and the human
         applies it
    Then the rationale is on the invalidated decision itself, in its status
         record and in its history, and the neighbour carries nothing.

    Shipping the reasoning as a note on a neighbouring node makes the human
    read the block and its justification as two unrelated items. The rationale
    has to survive the queue to reach the board at all, and the history entry
    is attributed to the gesture that caused the change -- the human's apply --
    while the reasoning it carries stays the agent's.
    """
    seed_node(client, log.epoch)
    neighbour = post(client, log.epoch, add_node("mint-1"))[0]["node"]["id"]
    rationale = "the vendor ships one storage engine, so the question is moot"

    receipt = post(
        client, log.epoch, event("invalidate", key="kill-1", target=SEED_NODE, why=rationale)
    )[0]
    applied = apply_all(client, log.epoch, SEED_NODE)

    assert receipt["status"] == "accepted"
    assert applied["status"] == "accepted"
    board = decisions(client)
    assert board[SEED_NODE]["status"] == "invalidated"
    assert board[SEED_NODE]["rationale"] == rationale
    assert history(client, SEED_NODE)[-1] == {
        "seq": applied["seq"],
        "timestamp": history(client, SEED_NODE)[-1]["timestamp"],
        "kind": "invalidate",
        "actor": "human",
        "why": rationale,
    }
    assert board[neighbour]["rationale"] is None
    assert rationale not in str(board[neighbour])


def test_an_invalidate_with_no_rationale_is_refused_and_appends_nothing(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an invalidate carrying no rationale text
    When it is submitted
    Then the batch is refused at the envelope and nothing is appended.

    None of the seven rejection reasons names this fault, and inventing an
    eighth would break every caller switching on the vocabulary -- so it is
    refused the way an unknown envelope field is, before anything lands.
    """
    seed_node(client, log.epoch)
    before = log.seq

    response = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [event("invalidate", key="kill-1", target=SEED_NODE)],
        },
    )

    assert response.status_code == 422
    assert "why" in response.json()["detail"]
    assert log.seq == before


def test_a_batch_is_refused_whole_rather_than_half_appended(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a batch whose first event is well-formed and whose second is not
    When it is submitted
    Then nothing at all is appended.

    Refusing part-way through would leave an entry in the log that no caller
    ever got a receipt for, which is the one outcome the receipt contract is
    built to make impossible.
    """
    seed_node(client, log.epoch)
    before = log.seq

    response = client.post(
        "/events",
        json={
            "epoch": log.epoch,
            "events": [
                event("informational", key="ok-1", text="the budget landed"),
                add_node("bad-1", options=[{"id": "a", "text": "only one"}]),
            ],
        },
    )

    assert response.status_code == 422
    assert "event 1" in response.json()["detail"]
    assert log.seq == before


# ── the rest of the kinds: accepted, and visible on the board ──


def test_revise_replaces_the_fields_it_names_and_leaves_the_others_standing(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision with a title, a body and options
    When a revise names only the options
    Then the options are replaced and the question is untouched.

    A revise says what changed. Reading an absent field as an empty one would
    erase the question the human is answering.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event(
            "revise",
            key="revise-1",
            target=SEED_NODE,
            options=[{"id": "a", "text": "Append-only log"}, {"id": "b", "text": "Event store"}],
            why="the second option was never real",
        ),
    )[0]

    node = decisions(client)[SEED_NODE]
    assert receipt["status"] == "accepted"
    assert [option["text"] for option in node["options"]] == ["Append-only log", "Event store"]
    assert node["title"] == "Which storage?"
    assert node["body"] == "Pick the storage layer."


def test_settle_records_an_answer_the_agent_asserts(client: TestClient, log: SessionLog) -> None:
    """
    Given a decision the human answered in conversation rather than on the board
    When the grill-master settles it
    Then the answer is recorded and the decision leaves the frontier.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event(
            "settle",
            key="settle-1",
            target=SEED_NODE,
            answer={"option": None, "text": "an append-only log, as discussed"},
            why="the human said so in the thread",
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert decisions(client)[SEED_NODE]["status"] == "settled"
    assert image1(client)["settled"] == [
        {"id": SEED_NODE, "answer": "an append-only log, as discussed"}
    ]
    assert image1(client)["frontier"] == []


def test_unsettle_reopens_a_decision_and_makes_everything_resting_on_it_stale(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a settled chain of three decisions, each a prereq of the next
    When the first is unsettled
    Then it is open again and both decisions downstream of it are stale.

    Staleness is transitive because an answer resting on a withdrawn answer is
    exactly as unsupported at one remove as at none. Withdrawing the answer is
    the human's, so the unsettle waits for their gesture before any of it
    happens.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, add_node("mint-2", target="n2", prereqs=[SEED_NODE]))
    post(client, log.epoch, add_node("mint-3", target="n3", prereqs=["n2"]))
    for index, node_id in enumerate((SEED_NODE, "n2", "n3")):
        settled(client, log.epoch, node_id, f"answer-{index}")

    receipt = post(
        client,
        log.epoch,
        event("unsettle", key="unsettle-1", target=SEED_NODE, why="the vendor changed the terms"),
    )[0]
    assert decisions(client)[SEED_NODE]["status"] == "settled"
    applied = apply_all(client, log.epoch, SEED_NODE)

    board = decisions(client)
    assert [receipt["status"], applied["status"]] == ["accepted", "accepted"]
    assert board[SEED_NODE]["status"] == "open"
    assert board[SEED_NODE]["answer"] is None
    assert board[SEED_NODE]["rationale"] == "the vendor changed the terms"
    assert [board["n2"]["status"], board["n3"]["status"]] == ["stale", "stale"]
    assert image1(client)["frontier"] == [SEED_NODE]


def test_resolve_stale_puts_a_stale_decision_back_where_it_was(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision made stale by an unsettling upstream
    When it is resolved
    Then it is settled again, on the answer it still holds.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, add_node("mint-2", target="n2", prereqs=[SEED_NODE]))
    settled(client, log.epoch, SEED_NODE, "answer-1")
    settled(client, log.epoch, "n2", "answer-2")
    post(client, log.epoch, event("unsettle", key="unsettle-1", target=SEED_NODE, why="withdrawn"))

    receipt = post(
        client,
        log.epoch,
        event("resolve-stale", key="resolve-1", target="n2", why="the answer still holds"),
    )[0]

    node = decisions(client)["n2"]
    assert receipt["status"] == "accepted"
    assert node["status"] == "settled"
    assert node["answer"]["text"] == "an append-only log"


def test_an_informational_joins_the_queue_of_what_the_human_has_not_dealt_with(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an informational addressed to the human
    When it is submitted
    Then it is accepted, appears in image 1's pending queue, and changes no
         decision.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event("informational", key="note-1", target=SEED_NODE, text="the budget landed today"),
    )[0]

    assert receipt["status"] == "accepted"
    assert image1(client)["pending"] == [
        {
            "id": "note-1",
            "target": SEED_NODE,
            "kind": "informational",
            "superseded": False,
            "authored_at": receipt["seq"],
        }
    ]
    assert decisions(client)[SEED_NODE]["status"] == "open"


def test_an_informational_about_no_decision_in_particular_still_queues(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an informational anchored to no decision
    When it is submitted
    Then it queues with a null target rather than being dropped.
    """
    post(client, log.epoch, event("informational", key="note-1", text="the vendor called"))

    assert image1(client)["pending"][0]["target"] is None


@pytest.mark.parametrize("blocking", [True, False])
def test_an_elicit_alerts_blocking_flag_decides_whether_it_locks_its_decision(
    blocking: bool, client: TestClient, log: SessionLog
) -> None:
    """
    Given an elicit-alert against an answerable decision
    When it declares itself blocking, and when it does not
    Then the blocking one locks that decision out of the frontier and the
         non-blocking one leaves it answerable, and both queue for the human.

    The pair is the whole claim: a lock asserted for both variants and a lock
    asserted for neither would each pass a one-sided check.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event(
            "elicit-alert",
            key="alert-1",
            target=SEED_NODE,
            text="the licence terms may rule this out entirely",
            blocking=blocking,
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert decisions(client)[SEED_NODE]["locked"] is blocking
    assert image1(client)["frontier"] == ([] if blocking else [SEED_NODE])
    assert [item["kind"] for item in image1(client)["pending"]] == ["elicit-alert"]


def test_a_later_alert_that_does_not_block_lifts_the_lock(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision locked by a blocking alert
    When a later alert on the same decision does not block
    Then the decision is answerable again.

    The lock is the standing state of the most recent alert, so an alert that
    could only ever lock would be a decision nobody can ever answer.
    """
    seed_node(client, log.epoch)
    alert = {"target": SEED_NODE, "text": "the licence terms may rule this out"}
    post(client, log.epoch, event("elicit-alert", key="alert-1", blocking=True, **alert))

    post(
        client,
        log.epoch,
        event("elicit-alert", key="alert-2", blocking=False, target=SEED_NODE, text="terms are ok"),
    )

    assert decisions(client)[SEED_NODE]["locked"] is False
    assert image1(client)["frontier"] == [SEED_NODE]


def test_a_decision_reads_as_fogged_until_the_decision_it_waits_on_settles(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision whose fog lifts on another decision
    When that other decision is answered
    Then the fogged one becomes open and answerable.

    The status is derived from the board rather than asserted by anyone: a
    client that could set `fogged` itself would be asserting state.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, add_node("mint-2", target="n2", fogUntil=SEED_NODE))
    assert decisions(client)["n2"]["status"] == "fogged"

    settled(client, log.epoch, SEED_NODE, "answer-1")

    assert decisions(client)["n2"]["status"] == "open"
    assert image1(client)["frontier"] == ["n2"]


# ── the atomic fold ──


def fold_gesture(key: str, *updates: dict[str, Any], actor: str = "human") -> dict[str, Any]:
    """A fold as the human makes it: their gesture is what puts a turn's
    declared impact on the board."""
    return event("fold", actor=actor, key=key, updates=list(updates))


def test_one_fold_gesture_applies_a_revise_an_add_node_and_an_informational(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given one fold gesture carrying a revise, an add-node and an informational
    When the human submits it
    Then all three land, on one sequence, with a receipt per sub-update saying
         what was applied and whether it was amended.

    This is a conversational turn's declared impact applied as one gesture: the
    human accepted the turn, not three unrelated writes. The actor is what makes
    that true rather than merely said -- an agent submitting the same three
    would be applying its own turn, which is the thing the queue exists to stop.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        fold_gesture(
            "fold-1",
            {
                "kind": "revise",
                "target": SEED_NODE,
                "title": "Which storage, given the retention rule?",
                "why": "retention changes the shape of this",
            },
            {
                "kind": "add-node",
                "title": "How long do we retain?",
                "options": OPTIONS,
                "prereqs": [SEED_NODE],
            },
            {"kind": "informational", "text": "retention is now a decision of its own"},
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert receipt["applied"] == {
        "kind": "fold",
        "target": None,
        "as": "sent",
        "amendments": None,
    }
    assert [one["kind"] for one in receipt["updates"]] == ["revise", "add-node", "informational"]
    assert [one["status"] for one in receipt["updates"]] == ["applied"] * 3
    assert [one["as"] for one in receipt["updates"]] == ["sent"] * 3

    minted = receipt["updates"][1]["target"]
    assert minted == f"n-{receipt['seq']}-1"
    assert receipt["updates"][1]["node"]["title"] == "How long do we retain?"
    board = decisions(client)
    assert board[SEED_NODE]["title"] == "Which storage, given the retention rule?"
    assert board[minted]["prereqs"] == [SEED_NODE]
    assert [item["kind"] for item in image1(client)["pending"]] == ["informational"]


def test_a_fold_whose_one_sub_update_is_refused_applies_none_of_it(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a fold whose second sub-update names a decision that does not exist
    When it is submitted
    Then nothing is appended, the gesture's receipt names that sub-update's own
         reason, and every other sub-update's outcome names the veto.

    All-or-none is what makes the gesture one act. A fold that applied its
    good half would leave the agent's declared impact half-applied with no
    record of which half.
    """
    seed_node(client, log.epoch)
    before = log.seq

    receipt = post(
        client,
        log.epoch,
        fold_gesture(
            "fold-1",
            {"kind": "revise", "target": SEED_NODE, "why": "still fine"},
            {"kind": "invalidate", "target": "no-such-node", "why": "moot"},
            {"kind": "informational", "text": "and a note"},
        ),
    )[0]

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_NODE
    assert [one["status"] for one in receipt["updates"]] == ["vetoed", "rejected", "vetoed"]
    assert receipt["updates"][1]["reason"] == REASON_UNKNOWN_NODE
    assert receipt["updates"][0]["reason"] is None
    assert "sub-update 1" in receipt["updates"][0]["detail"]
    assert log.seq == before
    assert decisions(client)[SEED_NODE]["title"] == "Which storage?"


def test_a_fold_may_not_carry_a_kind_that_is_not_an_impact_on_the_board(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a fold carrying a thread turn
    When it is submitted
    Then it is refused as an unknown kind and nothing is appended.

    A thread turn is a conversation, not a declared impact; a fold that carried
    one would apply a message as though it were a board change.
    """
    seed_node(client, log.epoch)
    before = log.seq

    receipt = post(
        client,
        log.epoch,
        fold_gesture(
            "fold-1",
            {"kind": "thread-turn", "turns": [{"who": "human", "text": "hello"}]},
        ),
    )[0]

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_KIND
    assert receipt["updates"][0]["status"] == "rejected"
    assert log.seq == before


def test_a_sub_update_authored_against_an_older_board_is_applied_as_amended(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a fold whose revise declares the sequence it was authored against
    When the board has moved on by the time the human folds the turn
    Then the update applies to the board as it now is and the receipt says
         `amended`, naming the basis it rewrote.

    An undocumented rewrite makes the agent's next turn reason from a board it
    did not author -- it believes its update landed on the board it saw.
    """
    seed_node(client, log.epoch)
    authored_against = log.seq
    post(client, log.epoch, event("informational", key="note-1", text="something else happened"))

    receipt = post(
        client,
        log.epoch,
        fold_gesture(
            "fold-1",
            {
                "kind": "revise",
                "target": SEED_NODE,
                "why": "sharper",
                "basis": authored_against,
            },
            {"kind": "informational", "text": "and a note", "basis": log.seq},
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert [one["as"] for one in receipt["updates"]] == ["amended", "sent"]
    assert str(authored_against) in receipt["updates"][0]["amendments"]["basis"]
    assert receipt["applied"]["as"] == "amended"
    assert "updates.0.basis" in receipt["applied"]["amendments"]


def test_a_fold_carrying_a_node_its_own_sub_update_minted_is_accepted(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a fold that adds a node under an id it names itself and then revises
         that same node
    When it is submitted
    Then both apply: the node set the gesture is judged against grows as its
         sub-updates are read.
    """
    receipt = post(
        client,
        log.epoch,
        fold_gesture(
            "fold-1",
            add_node("unused", target="retention")["payload"] | {"kind": "add-node"},
            {"kind": "revise", "target": "retention", "short": "Retention", "why": "shorter label"},
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert decisions(client)["retention"]["short"] == "Retention"


# ── determinism, with every kind in the log ──


def test_a_log_carrying_every_update_kind_still_folds_byte_identically(
    client: TestClient, log: SessionLog, session_dir: Any
) -> None:
    """
    Given a log exercising every update kind this protocol carries
    When it is folded twice, and again by a second process from the file alone
    Then all three images are byte-identical.

    Determinism is what makes an image a projection rather than a state: a kind
    that reached for a clock or a random id would pass every field assertion
    here and fail this one.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, add_node("mint-2", target="n2", prereqs=[SEED_NODE]))
    settled(client, log.epoch, SEED_NODE, "answer-1")
    settled(client, log.epoch, "n2", "answer-2")
    post(
        client,
        log.epoch,
        event("unsettle", key="unsettle-1", target=SEED_NODE, why="withdrawn"),
        event("resolve-stale", key="resolve-1", target="n2", why="still holds"),
        event("elicit-alert", key="alert-1", target="n2", text="licence", blocking=True),
        event("informational", key="note-1", text="the vendor called"),
        event("invalidate", key="kill-1", target="n2", why="moot now"),
        fold_gesture(
            "fold-1",
            {"kind": "add-node", "title": "What replaces it?", "options": OPTIONS, "prereqs": []},
            {"kind": "informational", "text": "one node replaced another"},
        ),
        event(
            "thread-created",
            actor="human",
            channel="t1",
            key="thread-1",
            kind="side",
            title="Licensing",
            turns=[{"who": "human", "text": "who owns the licence?"}],
        ),
    )

    first = fold(log.epoch, log.entries()).model_dump_json()
    again = fold(log.epoch, log.entries()).model_dump_json()
    reloaded = SessionLog(session_dir)
    from_disk = fold(log.epoch, reloaded.entries()).model_dump_json()

    assert first == again == from_disk


def test_a_thread_created_and_a_bare_text_reply_are_both_accepted_and_projected(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the page's `turns[]` shape and a backend-authored bare-text reply
    When both are submitted through the write endpoint
    Then both are accepted and both project into the same thread's turn list.

    One reader handles both shapes across the accept path and the projector,
    because a backend written against only one of them passes a scripted check
    and rejects the real page.
    """
    receipts = post(
        client,
        log.epoch,
        event(
            "thread-created",
            actor="human",
            channel="t1",
            key="thread-1",
            kind="side",
            title="Compaction",
            requires_action=True,
            turns=[{"who": "human", "text": "what about compaction?"}],
        ),
        event("thread-turn", actor="backend", channel="t1", key="turn-1", text="it is bounded"),
    )

    assert [receipt["status"] for receipt in receipts] == ["accepted", "accepted"]
    thread = image1(client)["threads"][0]
    assert thread["title"] == "Compaction"
    assert thread["kind"] == "side"
    assert thread["requires_action"] is True
    assert [turn["text"] for turn in thread["turns"]] == [
        "what about compaction?",
        "it is bounded",
    ]
    assert [turn["who"] for turn in thread["turns"]] == ["human", "backend"]


def test_an_explicit_null_id_on_add_node_still_mints_a_node(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node whose target is an explicit null
    When it is accepted
    Then a node is minted anyway -- null asks the backend to mint, and the
    alternative is an accepted receipt materialising nothing, the silent no-op
    the receipt vocabulary exists to forbid.
    """
    receipt = post(client, log.epoch, add_node("null-id", target=None))[0]

    assert receipt["status"] == "accepted"
    minted = receipt["applied"]["target"]
    assert minted == "n-1"
    assert receipt["node"]["id"] == minted
    assert image1(client)["frontier"] == [minted]


def test_a_non_string_add_node_id_is_refused_at_the_envelope(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node whose target is an integer
    When it is submitted
    Then the batch is refused with 422 before anything is appended.
    """
    response = client.post(
        "/events",
        json={"epoch": log.epoch, "events": [add_node("int-id", target=5)]},
    )

    assert response.status_code == 422
    assert log.entries() == []


# ---- GUI-A79 / GUI-A80: an option's downstream pre-mark, and where it stops ----

# One id naming a decision on the board and one naming nothing at all. The
# dangling id is in the fixture rather than beside it: what the board does with
# an id it cannot resolve is the whole question, and a fixture carrying only
# resolvable ids would pass whichever way that went.
PRE_MARK = ["n1", "no-such-decision"]


def marked(image: dict[str, Any], node_id: str) -> list[Any]:
    """What each option of one decision says it would put in question."""
    node_map = {node["id"]: node for node in image["decisions"]}
    return [option.get("puts_in_question") for option in node_map[node_id]["options"]]


def pre_marked(key: str, marks: list[str], **payload: Any) -> dict[str, Any]:
    """An add-node whose first option names what it would put in question."""
    return add_node(
        key,
        options=[
            {"id": "a", "text": "Redis", "puts_in_question": marks},
            {"id": "b", "text": "No cache at all"},
        ],
        **payload,
    )


def test_an_options_pre_mark_reaches_both_images_as_authored(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node whose first option names two decisions it would put in
          question, one of them resolving to no node on the board
    When the node is added
    Then both images carry the pair on that option exactly as authored, and the
         option that named nothing carries nothing.

    The field is the page's to render and nobody else's, so what is asserted is
    that it arrives unread and unedited -- the dangling id included. A backend
    that quietly dropped it would be deciding what the human is warned about.
    """
    seed_node(client, log.epoch)

    receipt = post(client, log.epoch, pre_marked("marked", PRE_MARK, target="n2"))[0]

    assert receipt["status"] == "accepted"
    assert marked(image1(client), "n2") == [PRE_MARK, None]
    assert marked(client.get("/image2").json(), "n2") == [PRE_MARK, None]


def test_a_revise_moves_a_pre_mark_between_options_like_any_other_option_field(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision whose first option carries a pre-mark
    When a revise re-states the options with the mark on the second one instead
    Then the board carries it on the second option and on neither other.

    An option is revised whole, so the mark travels with the option it was
    authored on rather than surviving as a property of the decision.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, pre_marked("marked", PRE_MARK, target="n2"))

    receipt = post(
        client,
        log.epoch,
        event(
            "revise",
            key="revise-mark",
            target="n2",
            options=[
                {"id": "a", "text": "Redis"},
                {"id": "b", "text": "No cache at all", "puts_in_question": ["n1"]},
            ],
            why="the cost lands on the other branch",
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert marked(image1(client), "n2") == [None, ["n1"]]


def test_a_pre_mark_naming_no_decision_is_not_a_rejection_reason(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an add-node every one of whose pre-marked ids resolves to no node
    When it is submitted
    Then it is accepted and the ids stand on the board.

    A dangling prereq strands a decision the frontier can never reach and is
    refused for it; a dangling pre-mark marks nothing, and refusing it would let
    one stale hint reject a whole plan.
    """
    ghosts = ["ghost-1", "ghost-2"]

    receipt = post(client, log.epoch, pre_marked("all-dangling", ghosts, target="n2"))[0]

    assert receipt["status"] == "accepted"
    assert marked(image1(client), "n2") == [ghosts, None]


def test_no_decision_is_moved_by_being_named_in_a_pre_mark(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision pre-marked by an option of another, and that other settled
    When the board is read back
    Then the pre-marked decision is neither invalidated nor stale, and the board
         holds only the statuses the applied updates put on it.

    The only routes to either status are an applied invalidate and an unsettle.
    A pre-mark is a warning about a choice, and a warning that moved the board
    would be an invalidation nobody authored.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, pre_marked("marked", ["n1"], target="n2"))

    settled(client, log.epoch, "n2", "settle-marked")

    node_map = decisions(client)
    assert node_map["n1"]["status"] == "open"
    assert node_map["n2"]["status"] == "settled"
