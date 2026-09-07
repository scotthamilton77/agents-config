"""The read request: a thread seat saying what it would have to read to answer.

Four claims are pinned here.

**The request is a closed key or it is prose.** A well-formed list beside `text`
is a declaring shape on its own, with nothing offered, declared or withdrawn
beside it. Every other shape a seat might write is the turn's prose exactly as
it wrote it -- the same rule the half-shaped offer follows, and the reason the
escalation condition below may be trusted at all.

**The condition is read off the field, never off the prose.** A seat musing
that the code would help is the model's opinion of its own reach, which the
escalation module refuses on principle. A key it either sent or did not is a
request for an input it does not have, and whether it has one is decidable
without asking it.

**The three conditions on the human's own turns come first.** A turn meeting one
of those is escalated on that one, which leaves the capped condition unspent for
a turn that has nothing else to escalate on.

**The request crosses to the seat above.** It is a line in the channel's
conversation, beside the prose it rode in on, so the expert reads what the first
rung asked for rather than inferring it.

Nothing here reaches a network or a model.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from conftest import dispatch_context, event, post, seed_node

from grillui.drivers import declared_updates, record_reply
from grillui.escalation import (
    ASKED_TO_READ,
    CONDITION_IRREDUCIBLE,
    CONDITION_TOOL_NEED,
    Turn,
    recommend,
    turns_of,
)
from grillui.log import LOG_FILE
from grillui.schemas import (
    FAST_TIER,
    MAP_CHANNEL,
    NEEDS_TO_READ_KEY,
    Actor,
    Decision,
    Image2,
    LogEntry,
    Thread,
)
from grillui.tiers import READ_REQUEST_RULE, compose, system_prompt

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from grillui.log import SessionLog

NODE = "n1"
THREAD = "t-retention"
SAID = "That turns on how the log is compacted."
READS = ["src/grillui/log.py", "the vendor's retention note"]

# What a seat writes when it asks well, as the driver reads it back.
ASKING = json.dumps({"text": SAID, NEEDS_TO_READ_KEY: READS})


def board(*dependents: str) -> Image2:
    """A board with one thread anchored to its one decision."""
    return Image2(
        epoch="e1",
        seq=7,
        decisions=[Decision(id=NODE, short="Store", title="Which storage?")]
        + [Decision(id=one, short=one, title=f"{one}?") for one in dependents],
        threads=[Thread(id=THREAD, decision=NODE, kind="user", title="Retention")],
    )


def entry(text: str, actor: Actor = "thread-agent", **payload: Any) -> LogEntry:
    return LogEntry(
        seq=1,
        epoch="e1",
        kind="thread-turn",
        idempotency_key=f"k-{actor}-{len(text)}",
        timestamp="2026-09-07T09:00:00.000+00:00",
        actor=actor,
        channel=THREAD,
        payload={"text": text, **payload},
    )


def open_thread(client: TestClient, epoch: str) -> None:
    receipt = post(
        client,
        epoch,
        event(
            "thread-created",
            actor="human",
            channel=THREAD,
            key=f"open-{THREAD}",
            decision=NODE,
            kind="user",
            title="Retention",
            requires_action=False,
            turns=[{"who": "human", "text": "How long is a session kept?"}],
        ),
    )[0]
    assert receipt["status"] == "accepted"


# ── the field is closed, and rides the object the offer already rides on ──


def test_a_reply_asking_to_read_is_a_declaring_shape_on_its_own() -> None:
    """
    Given a reply carrying `text` and a well-formed list of things to read
    When the driver reads what the turn declared
    Then the prose is the document's text rather than its raw bytes, the list
         comes back beside it, and nothing was declared, withdrawn or offered.

    A seat that cannot answer without reading has nothing to declare and nothing
    to offer, so the request alone has to be a whole turn -- a reader that
    required an offer beside it would publish the JSON to the human verbatim in
    exactly the case the field exists for.
    """
    prose, updates, superseded, proposal, asked = declared_updates(ASKING)

    assert prose == SAID
    assert asked == READS
    assert (updates, superseded, proposal) == ([], [], None)


@pytest.mark.parametrize(
    ("case", "value"),
    [
        ("not a list at all", "src/grillui/log.py"),
        ("a list of nothing", []),
        ("an item that is not a string", ["src/grillui/log.py", 3]),
        ("an item that is empty", ["src/grillui/log.py", "   "]),
        ("an object rather than a list", {"path": "src/grillui/log.py"}),
    ],
)
def test_a_half_shaped_request_is_the_turns_prose_exactly_as_written(case: str, value: Any) -> None:
    """
    Given a reply naming the key in a shape the field does not take
    When the driver reads what the turn declared
    Then the whole reply is the turn's prose, byte for byte, and nothing is
         declared -- the rule the half-shaped offer already follows.

    Guessing at a half-shaped request is how a condition that spends the expert
    seat comes to fire on bytes no seat meant as a request.
    """
    reply = json.dumps({"text": SAID, NEEDS_TO_READ_KEY: value})

    assert declared_updates(reply) == (reply, [], [], None, []), case


def test_the_request_lands_on_the_turns_own_entry_and_the_appender_takes_it(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread agent replying with a request beside its prose
    When the driver records the reply
    Then the appender takes it, the entry is that turn, and the request is on
         the payload under its own key.

    Recorded rather than held in the driver: the condition, the conversation the
    seat above is handed, and the human's own view of what was asked all read
    the log, and a request that lived only in the turn that made it would reach
    none of them after a restart.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch)

    record_reply(log, FAST_TIER, THREAD, ASKING, {"tier": FAST_TIER})

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert written["kind"] == "thread-turn"
    assert written["payload"]["text"] == SAID
    assert written["payload"][NEEDS_TO_READ_KEY] == READS


def test_a_half_shaped_request_reaches_the_log_as_prose_and_not_as_a_key(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread agent naming the key in a shape the field does not take
    When the driver records the reply
    Then the human is shown the bytes the seat wrote, and no key rides the
         payload for a condition to read.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch)
    reply = json.dumps({"text": SAID, NEEDS_TO_READ_KEY: []})

    record_reply(log, FAST_TIER, THREAD, reply, {"tier": FAST_TIER})

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert written["payload"]["text"] == reply
    assert NEEDS_TO_READ_KEY not in written["payload"]


# ── the fourth condition, read in code off the field ──


def test_a_thread_reply_asking_to_read_names_the_capability_condition() -> None:
    """
    Given a thread channel whose seat asked to read two things
    When the turn is judged
    Then the recommendation names the capability condition and its evidence
         names both of them.

    Admissible where a self-assessment is not: the thread seat holds no tool as
    a fact about how it is seated, so what it names here is an input it does not
    have rather than its own opinion of its reach.
    """
    advice = recommend(board(), [Turn(who="human", text="How long?")], THREAD, READS)

    assert advice is not None
    assert advice.condition == CONDITION_TOOL_NEED
    for one in READS:
        assert one in advice.evidence


def test_the_same_request_on_the_map_channel_recommends_nothing() -> None:
    """
    Given the same field on the map channel
    When the turn is judged
    Then no recommendation is made: the map's author writes the board rather
         than reading the project, and the map has its own hand-ups.
    """
    assert recommend(board(), [Turn(who="human", text="How long?")], MAP_CHANNEL, READS) is None


def test_a_reply_asking_nothing_is_judged_on_the_humans_last_turn_as_before() -> None:
    """
    Given a thread reply carrying no request
    When the turn is judged
    Then the answer is whatever the human's own last turn yields today: the
         irreducible condition where they said so, and nothing where they did
         not.
    """
    refused = [Turn(who="human", text="You keep rewording it -- that is not the question.")]
    bland = [Turn(who="human", text="It has to survive a crash mid-write.")]

    advice = recommend(board(), refused, THREAD)

    assert advice is not None
    assert advice.condition == CONDITION_IRREDUCIBLE
    assert recommend(board(), bland, THREAD) is None


def test_the_humans_own_conditions_are_judged_before_the_request() -> None:
    """
    Given a turn meeting one of the human's conditions and carrying a request
    When the turn is judged
    Then it is escalated on the human's condition.

    The channel moves either way, so nothing is lost -- and the condition capped
    at one move per channel is left unspent for a turn that has nothing else to
    escalate on.
    """
    refused = [Turn(who="human", text="The trade-off is what I cannot resolve.")]

    advice = recommend(board(), refused, THREAD, READS)

    assert advice is not None
    assert advice.condition == CONDITION_IRREDUCIBLE


# ── the request crosses to the seat above ──


def test_the_channels_conversation_carries_the_request_on_a_line_of_its_own() -> None:
    """
    Given a thread turn recorded with a request beside its prose
    When the channel's conversation is read
    Then the prose is one turn and the request is another, attributed to the
         seat that made it and naming what it asked to read.
    """
    said = turns_of([entry(SAID, **{NEEDS_TO_READ_KEY: READS})], THREAD)

    assert [one.text for one in said] == [SAID, ASKED_TO_READ + ", ".join(READS)]
    assert {one.who for one in said} == {"thread-agent"}


def test_the_expert_prompt_carries_the_request_beside_the_prose() -> None:
    """
    Given a thread whose last reply asked to read something
    When the prompt for the seat above is composed
    Then the request is a line inside that channel's conversation section,
         worded as the first rung asking, and the prose it rode in on is still
         there.
    """
    entries = [entry(SAID, **{NEEDS_TO_READ_KEY: READS})]

    prompt = compose("{}", dispatch_context(THREAD), entries)

    assert f"thread-agent: {ASKED_TO_READ}{', '.join(READS)}" in prompt
    assert f"thread-agent: {SAID}" in prompt


def test_a_reply_without_the_field_composes_exactly_as_it_did_before() -> None:
    """
    Given the same thread turn recorded with no request, and with one the seat
         half-shaped
    When each prompt is composed
    Then the two are byte-equal: a reply that made no well-formed request adds
         nothing to what the seat above is handed.
    """
    plain = compose("{}", dispatch_context(THREAD), [entry(SAID)])
    half = compose("{}", dispatch_context(THREAD), [entry(SAID, **{NEEDS_TO_READ_KEY: []})])

    assert half == plain
    assert ASKED_TO_READ not in plain


# ── the seat is told ──


@pytest.mark.parametrize("tier", [FAST_TIER, "heavy"])
def test_the_thread_seat_is_told_it_cannot_read_and_how_to_ask(tier: str) -> None:
    """
    Given the thread agent's brief on each tier
    When it is read for what to do when the answer is behind something it cannot
         open
    Then it says the seat cannot read the project, names the key, says to name
         what it would read rather than guess at what it says, and says the
         backend routes the request to a seat that can read.

    A seat told only that the key exists still answers from what it imagines the
    file says, which is the invention this whole path exists to stop.
    """
    brief = system_prompt(tier, "thread-agent")

    assert READ_REQUEST_RULE in brief
    assert "You cannot read this project" in brief
    assert "`needs_to_read` beside `text`" in brief
    assert "do not guess at the content" in brief
    assert "hand this conversation to a seat that can read" in brief
    assert READ_REQUEST_RULE not in system_prompt(tier, "grill-master")
