"""The fold: pure, tolerant, and the same twice."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from grillui.projector import fold, to_image1
from grillui.schemas import Image1, Image2, LogEntry, ThreadTurn

EPOCH = "tenure-1"


def entry(
    seq: int, kind: str, /, *, actor: str = "grill-master", channel: str = "map", **payload: Any
) -> LogEntry:
    return LogEntry(
        seq=seq,
        epoch=EPOCH,
        kind=kind,
        idempotency_key=f"k{seq}",
        timestamp=f"2026-08-18T09:00:0{seq}.000+00:00",
        actor=actor,  # type: ignore[arg-type]
        channel=channel,
        payload=payload,
    )


NODE = entry(
    1,
    "add-node",
    target="n1",
    short="Storage",
    title="Which storage?",
    body="Pick one.",
    prereqs=[],
    options=[
        {"id": "a", "text": "Append-only log", "pcr": ["audit", "size", "compaction"]},
        {"id": "b", "text": "Mutable table", "pcr": ["too", "few"]},
    ],
)


def test_folding_the_same_log_twice_yields_byte_identical_images() -> None:
    """
    Given a fixed log
    When it is folded twice
    Then the two images serialise to identical bytes.

    The fold takes no clock, no randomness and no I/O, which is what makes an
    image rebuilt from disk match one held in memory. A fold that reached for
    `now()` would pass every field-by-field assertion and fail this one.
    """
    entries = [NODE, entry(2, "answer", actor="human", target="n1", answer={"option": "a"})]

    assert fold(EPOCH, entries).model_dump_json() == fold(EPOCH, entries).model_dump_json()


def test_an_answered_node_leaves_the_frontier_and_joins_the_settled_set() -> None:
    """
    Given two nodes where the second depends on the first
    When the first is answered
    Then the first is settled and the second becomes answerable.

    Pins that the frontier is derived from the log rather than asserted by a
    client: nothing tells the backend which decisions are answerable now.
    """
    entries = [
        NODE,
        entry(2, "add-node", target="n2", short="Format", prereqs=["n1"]),
        entry(3, "answer", actor="human", target="n1", answer={"option": "a", "text": "log it"}),
    ]

    image = fold(EPOCH, entries)

    assert [item.id for item in image.settled] == ["n1"]
    assert image.settled[0].answer == "log it"
    assert image.frontier == ["n2"]


def test_a_thread_reads_both_the_turns_array_and_a_bare_text_reply() -> None:
    """
    Given a thread created with a turns[] array and answered with bare text
    When the log is folded
    Then both land in the same turn list, in order.

    One reader handles both shapes on purpose: a backend written against only
    the array form passes a scripted check and drops every backend-authored
    reply on the floor.
    """
    entries = [
        entry(
            1,
            "thread-created",
            actor="human",
            channel="t1",
            title="Compaction",
            kind="side",
            requires_action=True,
            turns=[{"who": "human", "text": "What about compaction?"}],
        ),
        entry(2, "thread-turn", channel="t1", text="It is bounded by one grilling."),
    ]

    thread = fold(EPOCH, entries).threads[0]

    assert thread.title == "Compaction"
    assert thread.requires_action is True
    assert [turn.text for turn in thread.turns] == [
        "What about compaction?",
        "It is bounded by one grilling.",
    ]
    assert [turn.who for turn in thread.turns] == ["human", "grill-master"]


def test_a_payload_the_fold_cannot_read_costs_only_what_it_could_not_read() -> None:
    """
    Given entries whose payloads are missing or of the wrong type
    When the log is folded
    Then the fold completes and yields a schema-valid image.

    The projector must tolerate any log the appender accepted. Raising here
    would take the session down over an entry that is already durably written
    and already acknowledged.
    """
    entries = [
        entry(1, "add-node"),
        entry(2, "add-node", target="n1", options="not-a-list", prereqs="not-a-list"),
        entry(3, "answer", actor="human", target="n1", answer="not-an-object"),
        entry(4, "answer", actor="human", target="ghost", answer={"text": "x"}),
        entry(5, "thread-turn", channel="t1", turns=[{"who": "human"}, "not-an-object"]),
    ]

    image = fold(EPOCH, entries)

    Image2.model_validate(image.model_dump())
    assert [node.id for node in image.decisions] == ["n1"]
    assert image.decisions[0].status == "open"
    assert image.threads[0].turns == []


def test_option_metadata_survives_only_when_it_is_the_shape_it_claims() -> None:
    """
    Given one option with three pcr strings and one with two
    When the log is folded
    Then the well-formed one keeps its metadata and the other carries none.

    The trio is the contract -- what the option buys, costs and forces
    downstream. A two-element list rendered as if it were three would put the
    cost under the heading for the consequence.
    """
    options = fold(EPOCH, [NODE]).decisions[0].options

    assert [option.id for option in options] == ["a", "b"]
    assert options[0].pcr == ["audit", "size", "compaction"]
    assert options[1].pcr is None


def test_image_one_is_image_two_without_its_history() -> None:
    """
    Given an image 2 carrying per-decision history
    When it is reduced to image 1
    Then every other field is preserved and history is gone.

    History is the only field that separates the two, and image 1 is what the
    page reads: shipping the evolution record to a renderer that never asks
    for it is bytes over the wire for nothing.
    """
    image2 = fold(EPOCH, [NODE])

    image1 = to_image1(image2)

    assert isinstance(image1, Image1)
    assert "history" not in image1.model_dump()
    assert image1.model_dump() == image2.model_dump(exclude={"history"})
    assert image2.history["n1"][0].kind == "add-node"


def test_image_two_carries_per_decision_history_and_image_one_does_not() -> None:
    """
    Given a log in which one decision is added, revised and then answered
    When both images are folded from it
    Then image 2 carries that decision's ordered history with the rationale
         each event gave, image 1 carries no history at all, and each image
         validates against its own schema.

    The history is what makes image 2 the reverse handoff: an agent
    reconstituted from it can see why the board reached its current shape, not
    only what shape that is. Folding it from the log is the whole claim --
    history asserted anywhere else would be a second source of truth.
    """
    entries = [
        NODE,
        entry(2, "revise", target="n1", why="the option set was too narrow"),
        entry(
            3,
            "answer",
            actor="human",
            target="n1",
            answer={"option": "a", "text": "log it"},
            why="the audit trail is the point",
        ),
    ]

    image2 = fold(EPOCH, entries)
    image1 = to_image1(image2)

    Image2.model_validate(image2.model_dump())
    Image1.model_validate(image1.model_dump())
    assert "history" not in image1.model_dump()
    assert [(item.seq, item.kind, item.actor) for item in image2.history["n1"]] == [
        (1, "add-node", "grill-master"),
        (2, "revise", "grill-master"),
        (3, "answer", "human"),
    ]
    assert [item.why for item in image2.history["n1"]][1:] == [
        "the option set was too narrow",
        "the audit trail is the point",
    ]


def test_a_turn_naming_an_actor_the_protocol_has_no_name_for_is_attributed_to_the_entry() -> None:
    """
    Given a thread turn whose `who` is not one of the protocol's actors
    When the log is folded
    Then the turn survives, attributed to the entry's own actor.

    The appender judges a thread event on whether it says anything, not on who
    it claims said it, so this entry is accepted and durable. A fold that
    raised on it would take the session down over an entry that already has a
    receipt -- the projector must tolerate any log the appender accepted.
    """
    entries = [
        entry(
            1, "thread-turn", actor="human", channel="t1", turns=[{"who": "martian", "text": "?"}]
        )
    ]

    thread = fold(EPOCH, entries).threads[0]

    assert [turn.who for turn in thread.turns] == ["human"]
    assert [turn.text for turn in thread.turns] == ["?"]


def test_history_is_keyed_only_by_decisions_the_board_actually_has() -> None:
    """
    Given an entry targeting a node id no add-node ever minted
    When the log is folded
    Then history carries the real decision and no key for the phantom one.

    History is keyed by decision id, and image 2 crosses to the grill-master
    whole. A key naming a decision the board does not contain is an invitation
    to reason about a node nobody can answer.
    """
    entries = [NODE, entry(2, "answer", actor="human", target="ghost", answer={"text": "x"})]

    assert set(fold(EPOCH, entries).history) == {"n1"}


def test_requires_action_is_true_only_for_a_real_boolean() -> None:
    """
    Given a thread-created payload carrying the string "false"
    When the fold reads requires_action
    Then the thread does not require action.

    The appender does not validate payload interiors, so a truthy non-boolean
    must not be read as consent.
    """
    entries = [
        entry(1, "thread-created", channel="t1", requires_action="false", turns=[]),
    ]

    assert fold(EPOCH, entries).threads[0].requires_action is False


def test_an_unhashable_who_falls_back_to_the_entrys_actor() -> None:
    """
    Given an accepted thread turn whose who is a dict rather than a string
    When the fold reads it
    Then the turn is attributed to the entry's actor instead of crashing.
    """
    entries = [
        entry(
            1,
            "thread-created",
            actor="human",
            channel="t1",
            turns=[{"who": {"name": "mallory"}, "text": "hi"}],
        ),
    ]

    assert fold(EPOCH, entries).threads[0].turns[0].who == "human"


# ------------------------------------------------------------ GUI-U21/GUI-A62


def test_a_thread_turn_carries_the_tier_that_took_it_into_image_one() -> None:
    """
    Given a thread carrying a fast agent turn, a heavy one, and the human's
    When the fold projects it
    Then each agent turn carries the tier its own entry was attributed to,
    And the human's carries none.

    The page reads the board from this image rather than from log entries it
    was not there for, so a tier dropped here is a label that cannot survive a
    reload -- and a page with nothing to read it from would have only the
    channel's current mode, which relabels every turn taken before a transfer.
    """
    entries = [
        entry(1, "thread-created", actor="human", channel="t1", text="Why this one?"),
        entry(2, "thread-turn", actor="thread-agent", channel="t1", text="Because.", tier="fast"),
        entry(3, "thread-turn", actor="human", channel="t1", turns=[{"text": "Say more."}]),
        entry(4, "thread-turn", actor="thread-agent", channel="t1", text="More.", tier="heavy"),
    ]

    turns = to_image1(fold(EPOCH, entries)).threads[0].turns

    assert [(turn.who, turn.tier) for turn in turns] == [
        ("human", None),
        ("thread-agent", "fast"),
        ("human", None),
        ("thread-agent", "heavy"),
    ]


def test_an_unattributed_turn_has_no_tier_key_at_all() -> None:
    """
    Given a thread carrying the human's turn and an attributed agent turn
    When the image is serialised as the page reads it
    Then the tier is a key on the agent's turn and absent from the human's.

    Absent rather than null, because the field means "this is who answered":
    a null tier on a human turn invites a reader to render something for it.
    """
    entries = [
        entry(1, "thread-created", actor="human", channel="t1", text="Why this one?"),
        entry(2, "thread-turn", actor="thread-agent", channel="t1", text="Because.", tier="fast"),
    ]

    dumped = to_image1(fold(EPOCH, entries)).model_dump()["threads"][0]["turns"]

    assert "tier" not in dumped[0]
    assert dumped[1]["tier"] == "fast"


def test_a_tier_the_log_names_but_this_side_does_not_know_is_dropped() -> None:
    """
    Given an agent turn attributed to a tier that is not one of the two
    When the fold projects it
    Then the turn carries no tier rather than the unrecognised spelling.
    """
    entries = [
        entry(1, "thread-created", actor="human", channel="t1", text="Why this one?"),
        entry(2, "thread-turn", actor="thread-agent", channel="t1", text="Hm.", tier="medium"),
    ]

    assert to_image1(fold(EPOCH, entries)).threads[0].turns[1].tier is None


def test_a_human_turn_inside_an_attributed_entry_takes_no_tier_from_it() -> None:
    """
    Given an entry attributed to a tier that carries a turn the human said
    When the fold projects it
    Then that turn carries no tier.

    The page\'s turn shape lets a client name a `who`, so the attribution is
    gated on who took the turn rather than on what the entry claimed.
    """
    entries = [
        entry(
            1,
            "thread-created",
            actor="thread-agent",
            channel="t1",
            turns=[{"who": "human", "text": "mine"}, {"who": "thread-agent", "text": "theirs"}],
            tier="heavy",
        ),
    ]

    turns = fold(EPOCH, entries).threads[0].turns

    assert [(turn.who, turn.tier) for turn in turns] == [
        ("human", None),
        ("thread-agent", "heavy"),
    ]


@pytest.mark.parametrize("who", ["human", "backend"])
def test_a_turn_no_agent_took_refuses_a_tier(who: str) -> None:
    """
    Given a turn whose actor is not an agent
    When it is built carrying a tier
    Then the type refuses it.

    The invariant belongs to the type, not to the one caller that happens to
    gate it today.
    """
    with pytest.raises(ValidationError):
        ThreadTurn(who=who, text="x", timestamp="t", tier="fast")


def test_a_tier_outside_the_two_is_refused() -> None:
    with pytest.raises(ValidationError):
        ThreadTurn(who="grill-master", text="x", timestamp="t", tier="medium")


# -- What a decision that has left the flow still holds --


def applied(seq: int, *updates: dict[str, Any]) -> LogEntry:
    """The human applying the agent's proposals, which is how one lands."""
    return entry(seq, "apply", actor="human", pending=[], updates=list(updates))


def test_a_prereq_that_has_been_invalidated_holds_nothing() -> None:
    """
    Given a decision resting on two prereqs, one settled and one invalidated
    When the log is folded
    Then it is on the frontier.

    An invalidated decision never settles, so a frontier reading "settled" as
    the only way through gates its dependents for the rest of the session: the
    board deadlocks and no gesture the human can make finishes it.
    """
    entries = [
        NODE,
        entry(2, "add-node", target="n2", short="Format", prereqs=[]),
        entry(3, "add-node", target="n3", short="Codec", prereqs=["n1", "n2"]),
        entry(4, "answer", actor="human", target="n1", answer={"option": "a"}),
        applied(5, {"kind": "invalidate", "target": "n2", "why": "the export was dropped"}),
    ]

    image = fold(EPOCH, entries)

    assert image.frontier == ["n3"]
    assert [one.status for one in image.decisions if one.id == "n2"] == ["invalidated"]


def test_a_fog_rule_pointing_at_an_invalidated_decision_lifts() -> None:
    """
    Given a decision fogged until another settles, and that other one invalidated
    When the log is folded
    Then the fog is gone and the decision is answerable.

    The same deadlock as the prereq one and the same reason: a decision waiting
    to sharpen once a dead question settles waits forever, and the board can
    never be finished.
    """
    entries = [
        NODE,
        entry(2, "add-node", target="n2", short="Codec", prereqs=[], fogUntil="n1"),
        applied(3, {"kind": "invalidate", "target": "n1", "why": "no store is needed"}),
    ]

    image = fold(EPOCH, entries)

    assert [one.status for one in image.decisions if one.id == "n2"] == ["open"]
    assert image.frontier == ["n2"]


def test_staleness_does_not_travel_through_an_invalidated_dependent() -> None:
    """
    Given a settled decision resting on an invalidated one, which rests in turn
          on a decision the agent then unsettles
    When the log is folded
    Then the settled decision at the far end is untouched.

    Staleness is an answer resting on a withdrawn one. An invalidated decision
    rests on nothing and supports nothing -- it has left the flow -- so a
    withdrawal on its own prereq says nothing about what was built past it, and
    propagating through it would re-open decisions on the strength of a question
    nobody is asking any more.
    """
    entries = [
        NODE,
        entry(2, "add-node", target="n2", short="Format", prereqs=["n1"]),
        entry(3, "add-node", target="n3", short="Codec", prereqs=["n2"]),
        entry(4, "answer", actor="human", target="n1", answer={"option": "a"}),
        entry(5, "answer", actor="human", target="n3", answer={"option": "a"}),
        applied(6, {"kind": "invalidate", "target": "n2", "why": "the format is fixed by law"}),
        applied(7, {"kind": "unsettle", "target": "n1", "why": "the store question is back"}),
    ]

    statuses = {one.id: one.status for one in fold(EPOCH, entries).decisions}

    assert statuses == {"n1": "open", "n2": "invalidated", "n3": "settled"}


# ------------------------------------------------------------------ GMR-A7
# What §8.6's record says about who proposed a move and what was ruled.


def queued(
    seq: int, *updates: dict[str, Any], rulings: list[dict[str, str]] | None = None
) -> LogEntry:
    """A grill-master turn, whole: what it proposes and what it ruled.

    The rulings ride the turn's own entry, which is where the fold has to read
    them from -- by the time the human applies one of these, the gesture on the
    log is the human's and carries nothing but the ids they named.
    """
    return entry(seq, "fold", updates=list(updates), rulings=rulings or [], stop={"met": False})


def landing(seq: int, *ids: str, updates: list[dict[str, Any]]) -> LogEntry:
    """The human's apply, carrying the authoring agent's own bytes.

    The ids and the updates are parallel, because that is what the appender
    materialises: the updates are resolved out of the queue in the order the
    gesture named the ids.
    """
    return entry(seq, "apply", actor="human", pending=list(ids), updates=updates)


KILL = {"kind": "invalidate", "target": "n1", "why": "the vendor ships one engine"}


def test_an_applied_proposal_records_the_agent_that_proposed_it_and_the_verdict_behind_it() -> None:
    """
    Given a grill-master turn that ruled a decision invalid and queued the
         invalidate behind that ruling
    When the human applies it
    Then the decision's history entry is actored to the human's apply and
         carries the agent in `proposed_by` and `invalidate` in `verdict`.

    The gesture that moved the board is the human's, so `actor` is theirs and
    must stay theirs. Without the other two the record cannot say the move was
    an agent's proposal at all, and a thread agent asked why the decision died
    has `prereqs` and a plausible story -- which is the failure the fields
    exist to end.
    """
    entries = [
        NODE,
        queued(2, KILL, rulings=[{"decision": "n1", "ruling": "invalidate", "why": "moot"}]),
        landing(3, "k2#0", updates=[KILL]),
    ]

    recorded = fold(EPOCH, entries).history["n1"][-1]

    assert (recorded.seq, recorded.kind, recorded.actor) == (3, "invalidate", "human")
    assert recorded.proposed_by == "grill-master"
    assert recorded.verdict == "invalidate"
    assert recorded.why == "the vendor ships one engine"


def test_a_queued_proposal_is_no_history_until_the_human_lands_it() -> None:
    """
    Given the same turn, with nothing applied after it
    When the log is folded
    Then the decision's history ends at the add-node.

    A proposal has not happened to a decision yet, so recording a proposer for
    it would put a move on the record that the human can still refuse.
    """
    entries = [
        NODE,
        queued(2, KILL, rulings=[{"decision": "n1", "ruling": "invalidate", "why": "moot"}]),
    ]

    assert [one.kind for one in fold(EPOCH, entries).history["n1"]] == ["add-node"]


def test_a_stands_ruling_records_its_verdict_and_the_why_it_was_credited_on() -> None:
    """
    Given a turn that ruled a decision standing, which mints the notice that
         says so and moves nothing
    When the log is folded
    Then that decision's history entry carries `stands` and the ruling's own
         reasoning.

    A `stands` verdict has no update behind it -- the decision goes on being
    offered, which is the point -- so the ruling's `why` is the whole of what
    was decided. Left off, the record says a notice arrived and not that the
    question survived a challenge, which is the one thing a reader wants.
    """
    entries = [
        NODE,
        entry(
            2,
            "informational",
            target="n1",
            text="n1 stands: the audit requirement is unchanged",
            rulings=[{"decision": "n1", "ruling": "stands", "why": "the audit need is unchanged"}],
            stop={"met": False},
        ),
    ]

    recorded = fold(EPOCH, entries).history["n1"][-1]

    assert recorded.verdict == "stands"
    assert recorded.why == "the audit need is unchanged"
    assert recorded.proposed_by is None, "nobody applied anything"


def test_a_move_the_human_made_themselves_carries_neither_field() -> None:
    """
    Given the human answering a decision directly
    When the log is folded
    Then its history entry carries no proposer and no verdict, and the keys are
         absent from the serialised record rather than null.

    Absent is the record saying nothing happened, and null would be the record
    saying it forgot. A reader that cannot tell those apart is one that will
    fill in the difference, which is the inference the legend forbids.
    """
    entries = [
        NODE,
        entry(
            2,
            "answer",
            actor="human",
            target="n1",
            answer={"option": "a"},
            why="the audit trail is the point",
        ),
    ]

    image = fold(EPOCH, entries)
    recorded = image.history["n1"][-1]

    assert (recorded.proposed_by, recorded.verdict) == (None, None)
    dumped = image.model_dump()["history"]["n1"][-1]
    assert "proposed_by" not in dumped and "verdict" not in dumped
    assert set(dumped) == {"seq", "timestamp", "kind", "actor", "why"}


def test_a_ruling_with_no_update_behind_it_credits_no_other_update_on_that_decision() -> None:
    """
    Given a turn that ruled a decision invalid but queued a revise against it
         instead
    When the human applies that revise
    Then the revise's history entry carries no verdict.

    A verdict that queued nothing produced no move, and crediting the word to
    whatever update happened to name the same decision is how the record comes
    to say a decision was ruled dead that is sitting on the board revised. The
    proposer still rides: an agent did author the change.
    """
    revise = {"kind": "revise", "target": "n1", "why": "the option set was too narrow"}
    entries = [
        NODE,
        entry(2, "answer", actor="human", target="n1", answer={"option": "a"}),
        queued(3, revise, rulings=[{"decision": "n1", "ruling": "invalidate", "why": "moot"}]),
        landing(4, "k3#0", updates=[revise]),
    ]

    recorded = fold(EPOCH, entries).history["n1"][-1]

    assert recorded.kind == "revise"
    assert recorded.verdict is None
    assert recorded.proposed_by == "grill-master"


def test_one_apply_landing_two_proposals_gives_each_decision_its_own_verdict() -> None:
    """
    Given one turn ruling two decisions differently and queueing the change
         behind each
    When the human applies both in one gesture
    Then each decision's history carries the verdict that was ruled on it.

    The apply names its ids in order and the updates are resolved in that same
    order, so the pairing is positional. A reader that took the gesture's first
    id for every sub-update would record the second decision as having been
    ruled something nobody said about it -- and the record would be wrong in
    exactly the confident way a thread agent quotes.
    """
    second = {"kind": "revise", "target": "n2", "why": "the third option was missing"}
    entries = [
        NODE,
        entry(2, "add-node", target="n2", short="Format", prereqs=[]),
        entry(3, "answer", actor="human", target="n2", answer={"option": "a"}),
        queued(
            4,
            KILL,
            second,
            rulings=[
                {"decision": "n1", "ruling": "invalidate", "why": "moot"},
                {"decision": "n2", "ruling": "revise", "why": "narrow"},
            ],
        ),
        landing(5, "k4#0", "k4#1", updates=[KILL, second]),
    ]

    history = fold(EPOCH, entries).history

    assert history["n1"][-1].verdict == "invalidate"
    assert history["n2"][-1].verdict == "revise"
    assert {history["n1"][-1].proposed_by, history["n2"][-1].proposed_by} == {"grill-master"}


def test_a_history_entry_written_before_these_fields_existed_still_folds() -> None:
    """
    Given a log whose entries carry no rulings and no queue gesture at all
    When it is folded
    Then every history entry validates and carries neither field.

    The fields are optional because the logs that predate them are still logs:
    a fold that required a proposer would refuse to read a session recorded
    yesterday, and the reverse handoff is the one artifact that must survive
    the format moving under it.
    """
    entries = [
        NODE,
        entry(2, "revise", target="n1", why="the option set was too narrow"),
        entry(3, "answer", actor="human", target="n1", answer={"option": "a"}, why="audit"),
    ]

    image = fold(EPOCH, entries)

    Image2.model_validate(image.model_dump())
    assert [(one.proposed_by, one.verdict) for one in image.history["n1"]] == [(None, None)] * 3


def test_a_ruling_word_outside_the_closed_three_names_no_verdict() -> None:
    """
    Given a log whose turn ruled a decision with a word that is not one of the
         three verdicts, against an update of that same name
    When it is folded
    Then the image builds and that decision's history carries no verdict.

    The fold is a pure read of whatever the log holds, and the verdict
    vocabulary is closed. Matching a ruling to an update by name alone would
    put a word into the record that image 2 cannot be built from -- so the
    reverse handoff would fail to serialise on a log the board otherwise reads
    perfectly well.
    """
    entries = [
        NODE,
        queued(
            2,
            {"kind": "settle", "target": "n1", "why": "the vendor decided"},
            rulings=[{"decision": "n1", "ruling": "settle", "why": "not a verdict"}],
        ),
    ]

    image = fold(EPOCH, entries)
    recorded = image.history["n1"][-1]

    Image2.model_validate(image.model_dump())
    assert recorded.kind == "settle"
    assert recorded.verdict is None
    assert recorded.why == "the vendor decided"
