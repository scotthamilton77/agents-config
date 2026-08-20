"""The fold: pure, tolerant, and the same twice."""

from __future__ import annotations

from typing import Any

from grillui.projector import fold, to_image1
from grillui.schemas import Image1, Image2, LogEntry

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
