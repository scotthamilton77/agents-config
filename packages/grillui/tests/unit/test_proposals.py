"""What an agent's map update does on arrival, and the two gestures that end it.

One human gesture is what puts a conversational turn's declared impact on the
board. These tests pin the three halves of that: which of an agent's updates may
land by themselves, that the rest are durable and waiting rather than applied,
and that only the human can turn a waiting one into a change.

Every claim about the board is made against the projected image rather than
against a receipt, because a receipt saying `accepted` over an update that
changed nothing is exactly the silent no-op the uniform-receipt rule exists to
prevent -- and the whole point of a proposal is that it is accepted and changes
nothing.

The taxonomy is asserted at *arrival*: the tests that matter most here are the
ones where the same update lands or waits depending only on what the human did
while it was being written.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import (
    SEED_NODE,
    apply_all,
    event,
    post,
    proposed,
    queue_gesture,
    seed_node,
)
from fastapi.testclient import TestClient

from grillui.dispatch import GRILL_MASTER, THREAD_AGENT, record_dispatch
from grillui.log import SessionLog
from grillui.schemas import (
    APPLY_KIND,
    DISMISS_KIND,
    REASON_PENDING_CONFLICT,
    REASON_UNKNOWN_KIND,
    REASON_UNKNOWN_PENDING,
    DispatchContext,
    Image1,
)
from grillui.tiers import BASIS_RULE, HEAVY_TIER, MUTATION_FORMAT_RULE, system_prompt

OPTIONS = [{"id": "a", "text": "Redis"}, {"id": "b", "text": "No cache at all"}]
ANSWER = {"option": "a", "text": "an append-only log"}


def board(client: TestClient) -> dict[str, Any]:
    """Image 1's decisions, keyed by id, validated on the way through."""
    image = client.get("/image1").json()
    Image1.model_validate(image)
    nodes: dict[str, Any] = {node["id"]: node for node in image["decisions"]}
    return nodes


def frontier(client: TestClient) -> list[str]:
    ids: list[str] = client.get("/image1").json()["frontier"]
    return ids


def answered(client: TestClient, epoch: str, node: str = SEED_NODE, key: str = "answered") -> None:
    receipt = post(
        client,
        epoch,
        event("answer", actor="human", key=key, target=node, answer=ANSWER),
    )[0]
    assert receipt["status"] == "accepted"


def proposal(client: TestClient, epoch: str, kind: str, key: str, **payload: Any) -> dict[str, Any]:
    """One map update from the grill-master, on the map channel, as a turn sends
    it -- with no say in whether it lands."""
    return post(client, epoch, event(kind, key=key, **payload))[0]


def settled_node(client: TestClient, epoch: str, node: str = SEED_NODE) -> str:
    """A decision carrying an answer the human gave, which is what the
    overwrite test is drawn against."""
    seed_node(client, epoch, node)
    answered(client, epoch, node, key=f"answered-{node}")
    return node


# ── the queue is not the board ──


def test_a_proposed_invalidate_is_durable_and_the_board_has_not_moved(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an unanswered decision
    When the grill-master invalidates it
    Then the write is accepted and durable, the decision is still open, and the
         invalidation is waiting in the queue naming its target and its kind.

    The claim that carries the whole slice: an agent's declaration reaches the
    log without reaching the board. A test asserting only the receipt would pass
    against the divergence this replaces.
    """
    seed_node(client, log.epoch)

    receipt = proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")

    assert receipt["status"] == "accepted"
    assert log.entries()[-1].kind == "invalidate"
    assert board(client)[SEED_NODE]["status"] == "open"
    assert [
        (item["kind"], item["target"], item["superseded"])
        for item in client.get("/state").json()["image1"]["pending"]
    ] == [("invalidate", SEED_NODE, False)]


def test_the_receipt_says_queued_rather_than_applied(client: TestClient, log: SessionLog) -> None:
    """
    Given an update that waits for the human
    When the grill-master submits it alone
    Then its receipt carries an outcome saying `queued`.

    An `accepted` with nothing else to read is what lets an agent tell a human
    something is on the board when it is not: the next turn would reason from a
    decision it believes it invalidated.
    """
    seed_node(client, log.epoch)

    receipt = proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")

    assert [(one["kind"], one["status"]) for one in receipt["updates"]] == [
        ("invalidate", "queued")
    ]


def test_a_turn_that_proposes_and_speaks_lands_the_prose_and_queues_the_change(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a fold carrying an informational and an invalidate
    When the grill-master submits it
    Then the informational lands and the invalidate waits, each said so in its
         own outcome.

    A turn is one gesture with mixed effects, not an all-or-nothing one: what
    the agent said reaches the human immediately, and what it wants done waits.
    """
    seed_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event(
            "fold",
            key="turn-1",
            updates=[
                {"kind": "informational", "text": "this question is moot now"},
                {"kind": "invalidate", "target": SEED_NODE, "why": "the vendor ships one engine"},
            ],
        ),
    )[0]

    assert [one["status"] for one in receipt["updates"]] == ["applied", "queued"]
    assert board(client)[SEED_NODE]["status"] == "open"
    assert [item["kind"] for item in client.get("/image1").json()["pending"]] == [
        "informational",
        "invalidate",
    ]


# ── the taxonomy, drawn at arrival against the board ──


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("add-node", {"title": "Which cache?", "options": OPTIONS, "target": "n-cache"}),
        ("revise", {"target": SEED_NODE, "title": "Which storage, restated?"}),
        ("settle", {"target": SEED_NODE, "answer": ANSWER}),
    ],
)
def test_an_update_that_overwrites_nothing_lands_on_arrival(
    kind: str, payload: dict[str, Any], client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision nobody has answered
    When the grill-master sends an update against it
    Then the update lands immediately.

    The negative control for the whole queue: a rule that queued everything
    would pass every waiting test and stop the session dead.
    """
    seed_node(client, log.epoch)

    receipt = proposal(client, log.epoch, kind, "k1", **payload)

    assert receipt["status"] == "accepted"
    assert receipt["updates"] is None
    assert client.get("/image1").json()["pending"] == []


@pytest.mark.parametrize("kind", ["revise", "settle"])
def test_an_update_over_an_answered_decision_waits_for_the_human(
    kind: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision the human has answered
    When the grill-master revises or re-settles it
    Then the update waits in the queue and the answer stands.

    This is the line the taxonomy is drawn at: not what the update is called,
    but whether applying it would overwrite something the human decided.
    """
    settled_node(client, log.epoch)

    proposal(
        client, log.epoch, kind, "k1", target=SEED_NODE, title="restated", answer=ANSWER, why="new"
    )

    assert board(client)[SEED_NODE]["answer"] == ANSWER
    assert board(client)[SEED_NODE]["title"] != "restated"
    assert [item["kind"] for item in client.get("/image1").json()["pending"]] == [kind]


@pytest.mark.parametrize("kind", ["invalidate", "unsettle"])
def test_undermining_a_decision_waits_even_when_nobody_has_answered_it(
    kind: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision with no answer on it
    When the grill-master invalidates or unsettles it
    Then the update waits anyway.

    These two are never automatic. The point of withdrawing a decision is that
    somebody committed to it, so the agent taking it back by itself is the one
    move the human most needs to see before it happens -- and an unanswered
    decision today is one the human may answer a second before the update lands.
    """
    seed_node(client, log.epoch)

    proposal(client, log.epoch, kind, "k1", target=SEED_NODE, why="the premise moved")

    assert board(client)[SEED_NODE]["status"] == "open"
    assert [item["kind"] for item in client.get("/image1").json()["pending"]] == [kind]


def test_the_same_revise_lands_or_waits_by_what_the_human_did_in_between(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given two identical revises on two identical decisions
    When the human answers one of them between the two
    Then the first lands and the second waits.

    The taxonomy is decided at arrival, never at authoring: the board may move
    under an update while it is in flight, and an agent that classified its own
    updates would be classifying them against a board that no longer exists.
    """
    seed_node(client, log.epoch, "n-early")
    seed_node(client, log.epoch, "n-late")

    first = proposal(client, log.epoch, "revise", "r1", target="n-early", title="restated early")
    answered(client, log.epoch, "n-late")
    second = proposal(client, log.epoch, "revise", "r2", target="n-late", title="restated late")

    assert [first["updates"], [one["status"] for one in second["updates"]]] == [None, ["queued"]]
    assert board(client)["n-early"]["title"] == "restated early"
    assert board(client)["n-late"]["title"] != "restated late"


def test_the_humans_own_fold_applies_whatever_it_carries(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given the update that waits when an agent sends it
    When the human sends the same update themselves
    Then it lands.

    The actor is the whole of the rule about who may change the board. Without
    this control a queue that swallowed every invalidate would look identical.
    """
    settled_node(client, log.epoch)

    receipt = post(
        client,
        log.epoch,
        event(
            "invalidate", actor="human", key="k1", target=SEED_NODE, why="I have changed my mind"
        ),
    )[0]

    assert receipt["status"] == "accepted"
    assert board(client)[SEED_NODE]["status"] == "invalidated"
    assert client.get("/image1").json()["pending"] == []


# ── the lock a waiting change takes ──


def test_a_queued_proposal_takes_its_decision_off_the_frontier(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an answerable decision
    When the grill-master proposes a change to it
    Then the decision is locked and off the frontier.

    Nobody should be answering a question that has a change waiting on it: the
    human would be deciding something the agent has just said is in question.
    """
    seed_node(client, log.epoch)
    assert frontier(client) == [SEED_NODE]

    proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")

    assert board(client)[SEED_NODE]["locked"] is True
    assert frontier(client) == []


@pytest.mark.parametrize("gesture", [APPLY_KIND, DISMISS_KIND])
def test_either_gesture_clears_the_queue_entry_and_the_lock(
    gesture: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given a decision locked by a queued proposal
    When the human applies or dismisses it
    Then the entry leaves the queue and the lock goes with it.

    A lock outliving the thing that took it is a decision nobody can answer for
    the rest of the session.
    """
    seed_node(client, log.epoch)
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    seed_node(client, log.epoch, "n-other")
    proposal(client, log.epoch, "invalidate", "kill-1", target="n-other", why="moot")
    assert board(client)["n-other"]["locked"] is True

    receipt = queue_gesture(client, log.epoch, gesture, *proposed(client, "n-other"))

    assert receipt["status"] == "accepted"
    assert client.get("/image1").json()["pending"] == []
    assert board(client)["n-other"]["locked"] is False


def test_a_withdrawn_proposal_stops_locking_without_leaving_the_queue(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a queued proposal its author has superseded
    When the board is folded
    Then the entry is still in the queue, marked, and no longer locks anything.

    The queue is what the next dispatch tells the agent the human is looking at,
    so a withdrawal says so in place rather than vanishing -- but a change
    nobody intends to make any more must not go on holding a decision shut.
    """
    seed_node(client, log.epoch)
    proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")
    waiting = proposed(client, SEED_NODE)
    assert board(client)[SEED_NODE]["locked"] is True

    post(client, log.epoch, event("informational", key="k2", text="never mind", supersedes=waiting))

    assert [item["superseded"] for item in client.get("/image1").json()["pending"]] == [True, False]
    assert board(client)[SEED_NODE]["locked"] is False
    assert frontier(client) == [SEED_NODE]


# ── the human's apply ──


def test_the_apply_gesture_lands_the_turns_whole_impact_with_a_receipt_for_each(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a turn that proposed changes to two decisions
    When the human applies both in one gesture
    Then both land on one sequence, each with its own outcome in the receipt.

    One gesture, one entry, one sequence: there is no state in which half of a
    turn's declared impact is on the board.
    """
    settled_node(client, log.epoch)
    settled_node(client, log.epoch, "n-other")
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    proposal(client, log.epoch, "invalidate", "kill-1", target="n-other", why="moot")

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, *proposed(client))

    assert receipt["status"] == "accepted"
    assert [(one["kind"], one["target"], one["status"]) for one in receipt["updates"]] == [
        ("revise", SEED_NODE, "applied"),
        ("invalidate", "n-other", "applied"),
    ]
    assert board(client)[SEED_NODE]["title"] == "restated"
    assert board(client)["n-other"]["status"] == "invalidated"
    assert log.entries()[-1].seq == receipt["seq"]


def test_an_apply_puts_the_authoring_agents_own_bytes_on_the_board(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a queued proposal
    When the human applies it
    Then the update the log records is the one the agent wrote.

    The gesture names the proposal by id and carries no update content, so
    applying is the human choosing *that* a change lands and never choosing
    what it says -- which is what keeps the grill-master the sole author of map
    mutations through a gesture it did not make.
    """
    settled_node(client, log.epoch)
    proposal(
        client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated", why="the cost moved"
    )

    queue_gesture(client, log.epoch, APPLY_KIND, *proposed(client))

    applied = log.entries()[-1]
    assert applied.actor == "human"
    assert applied.payload["updates"] == [
        {
            "kind": "revise",
            "target": SEED_NODE,
            "title": "restated",
            "why": "the cost moved",
        }
    ]


def test_an_apply_from_the_grill_master_is_refused_and_changes_nothing(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a proposal the grill-master authored
    When the grill-master tries to apply it
    Then the write is refused and the proposal is still waiting.

    An agent applying its own proposals is the agent's gesture on the board
    again by a longer route, which is the divergence this whole queue exists to
    close. An agent that has changed its mind supersedes instead.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")

    receipt = queue_gesture(
        client, log.epoch, APPLY_KIND, *proposed(client), actor="grill-master", key="k1"
    )

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_KIND
    assert board(client)[SEED_NODE]["status"] == "settled"
    assert len(proposed(client)) == 1


def test_an_apply_naming_a_proposal_that_is_already_gone_is_refused(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a proposal the human has already applied
    When they apply it again under a fresh key
    Then the write is refused naming the unknown proposal.

    A second click is not a second change. Answering it `accepted` would tell
    them something landed twice when nothing landed at all.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")
    waiting = proposed(client)
    assert queue_gesture(client, log.epoch, APPLY_KIND, *waiting)["status"] == "accepted"

    again = queue_gesture(client, log.epoch, APPLY_KIND, *waiting)

    assert again["status"] == "rejected"
    assert again["reason"] == REASON_UNKNOWN_PENDING


def test_an_apply_of_a_proposal_the_human_moved_under_is_a_conflict(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a queued proposal whose decision the human has changed since
    When they apply it
    Then it is refused as a conflict, the board keeps their change, and the
         proposal is still waiting.

    Neither the page nor the backend resolves this: applying it silently would
    overwrite the answer the human gave while the change was waiting, on a rule
    nobody wrote. It stays queued, and what to do about it is a conversation.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    waiting = proposed(client)
    answered(client, log.epoch, key="second-thoughts")

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, *waiting)

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_PENDING_CONFLICT
    assert board(client)[SEED_NODE]["title"] != "restated"
    assert proposed(client) == waiting


def test_an_apply_is_refused_whole_when_one_of_its_proposals_conflicts(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given two waiting proposals, one of which the board moved under
    When the human applies both in one gesture
    Then neither lands.

    The gesture applies whole or not at all, so a conflict in one half cannot
    leave the other half on a board the human never agreed to.
    """
    settled_node(client, log.epoch)
    settled_node(client, log.epoch, "n-other")
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    proposal(client, log.epoch, "invalidate", "kill-1", target="n-other", why="moot")
    waiting = proposed(client)
    answered(client, log.epoch, key="second-thoughts")

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, *waiting)

    assert receipt["status"] == "rejected"
    assert board(client)["n-other"]["status"] == "settled"
    assert proposed(client) == waiting


def test_an_apply_says_when_the_board_moved_under_the_update_it_landed(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a proposal authored against an earlier sequence
    When the human applies it after the board has advanced elsewhere
    Then the receipt states that it was amended, naming the two sequences.

    A proposal waits, and the board does not wait with it. An undocumented
    rewrite makes the agent's next turn reason from a board it did not author.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated", basis=1)
    seed_node(client, log.epoch, "n-later")

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, *proposed(client, SEED_NODE))

    assert receipt["updates"][0]["as"] == "amended"
    assert "authored against seq 1" in receipt["updates"][0]["amendments"]["basis"]


# ── the human's dismiss ──


def test_a_dismissed_proposal_never_reaches_the_board(client: TestClient, log: SessionLog) -> None:
    """
    Given a queued proposal
    When the human dismisses it
    Then nothing on the board changed and the queue is empty.

    The discussion talked the agent out of it: there is no half-way outcome
    where a dismissed change leaves a mark.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "invalidate", "kill-1", target=SEED_NODE, why="moot")

    receipt = queue_gesture(client, log.epoch, DISMISS_KIND, *proposed(client))

    assert receipt["status"] == "accepted"
    assert board(client)[SEED_NODE]["status"] == "settled"
    assert board(client)[SEED_NODE]["answer"] == ANSWER
    assert client.get("/image1").json()["pending"] == []


def test_a_conflicted_proposal_may_still_be_dismissed(client: TestClient, log: SessionLog) -> None:
    """
    Given a proposal the board moved under
    When the human dismisses it rather than applying it
    Then the dismissal is accepted.

    Refusing this would be the one way out of a conflict closed off: a change
    that can never land and can never be cleared holds its decision shut for the
    rest of the session.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    waiting = proposed(client)
    answered(client, log.epoch, key="second-thoughts")

    receipt = queue_gesture(client, log.epoch, DISMISS_KIND, *waiting)

    assert receipt["status"] == "accepted"
    assert proposed(client) == []


def test_a_dismiss_naming_nothing_in_the_queue_is_refused(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an id no proposal has
    When the human dismisses it
    Then the write is refused naming the unknown proposal.

    Same rule as the apply: an acknowledgement over a no-op tells the human
    they dealt with something they did not.
    """
    seed_node(client, log.epoch)

    receipt = queue_gesture(client, log.epoch, DISMISS_KIND, "no-such-proposal#0")

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_PENDING


def test_a_notice_is_not_something_to_apply(client: TestClient, log: SessionLog) -> None:
    """
    Given an informational waiting in the queue
    When the human tries to apply it
    Then the write is refused.

    Both live in the queue and only one is a change. Applying a notice would be
    a gesture with nothing behind it, answered `accepted` all the same.
    """
    seed_node(client, log.epoch)
    post(client, log.epoch, event("informational", key="note-1", text="worth knowing"))
    notice_id = client.get("/image1").json()["pending"][0]["id"]

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, notice_id)

    assert receipt["status"] == "rejected"
    assert receipt["reason"] == REASON_UNKNOWN_PENDING


# ── what the agent is told it is looking at ──


def test_the_dispatched_queue_carries_the_proposals_the_human_has_not_applied(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a proposal waiting and one already applied
    When a grill-master dispatch is recorded
    Then only the waiting one is in the queue those bytes carry.

    Asserted against the recorded dispatch rather than an image the test folded
    for itself: what the agent was told the human is looking at is exactly those
    bytes, and a queue still naming an applied change would have it reason about
    a decision twice.
    """
    settled_node(client, log.epoch)
    settled_node(client, log.epoch, "n-other")
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    proposal(client, log.epoch, "invalidate", "kill-1", target="n-other", why="moot")
    apply_all(client, log.epoch, SEED_NODE)

    recorded = record_dispatch(log).read_text(encoding="utf-8")

    dispatched = DispatchContext.model_validate_json(recorded).image2.pending
    assert [(item.kind, item.target, item.id) for item in dispatched] == [
        ("invalidate", "n-other", "kill-1")
    ]


# ── what the grill-master is told about proposing ──


def test_the_grill_masters_standing_brief_says_a_proposal_is_not_a_change() -> None:
    """
    Given the grill-master's system prompt
    Then it says that sending an update is not making the change, and names the
         two kinds that always wait.

    A turn that believed its updates had landed would tell the human a decision
    was settled that is sitting in their queue, and the human has no way to tell
    that claim from a true one.
    """
    brief = system_prompt(HEAVY_TIER, GRILL_MASTER)

    assert MUTATION_FORMAT_RULE in brief
    assert BASIS_RULE in brief
    assert "Sending an update is not making the change" in MUTATION_FORMAT_RULE
    assert "`unsettle`" in MUTATION_FORMAT_RULE
    assert "`invalidate`" in MUTATION_FORMAT_RULE


def test_a_thread_agent_is_never_told_the_proposal_contract() -> None:
    """
    Given a thread agent's system prompt
    Then it carries neither the update format nor the basis rule.

    A thread agent's map update is refused by the appender, so telling it the
    shape would be inviting the refusal -- and a queue it cannot write into is
    not its to reason about proposing to.
    """
    brief = system_prompt(HEAVY_TIER, THREAD_AGENT)

    assert MUTATION_FORMAT_RULE not in brief
    assert BASIS_RULE not in brief


def test_a_receipt_claims_only_its_own_queue_entries_when_keys_share_a_prefix(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a queued proposal whose client-chosen key extends another turn's key
    When the shorter-keyed turn submits an update that lands on arrival
    Then its receipt says applied, claiming nothing from the other turn's queue.

    Keys are the clients' to choose, so ownership of a queue entry is exact key
    or key#N -- never a prefix match that would let "k1" answer for "k1a".
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "invalidate", "k1a", target=SEED_NODE, why="moot")

    receipt = proposal(
        client, log.epoch, "add-node", "k1", title="Which cache?", options=OPTIONS, target="n-new"
    )

    assert receipt["status"] == "accepted"
    assert receipt["updates"] is None
    assert proposed(client) == ["k1a"]


def test_an_apply_naming_the_same_proposal_twice_materialises_it_once(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given one queued proposal
    When the human's apply names its id twice
    Then the gesture carries the update once and the board moves once.

    A repeated id is a page bug, not a request to apply the change twice --
    materialising both copies would double the history the agent reasons from.
    """
    settled_node(client, log.epoch)
    proposal(client, log.epoch, "revise", "r1", target=SEED_NODE, title="restated")
    waiting = proposed(client)

    receipt = queue_gesture(client, log.epoch, APPLY_KIND, waiting[0], waiting[0])

    assert receipt["status"] == "accepted"
    assert len(log.entries()[-1].payload["updates"]) == 1
    assert len([one for one in receipt["updates"]]) == 1
