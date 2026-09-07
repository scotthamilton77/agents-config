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
import threading
from typing import TYPE_CHECKING, Any

import pytest
from conftest import TIMEOUT, dispatch_context, event, post, seed_node

from grillui.dispatch import record_dispatch
from grillui.drivers import FastDriver, declared_updates, record_reply
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
    PROPOSED_ANSWER_KEY,
    RECOMMENDATION_KEY,
    STATUS_KIND,
    STATUS_PHASE_TRANSFERRED,
    Actor,
    Decision,
    Image2,
    LogEntry,
    Thread,
)
from grillui.tiers import (
    POLICY_AUTONOMOUS,
    READ_REQUEST_RULE,
    TierConfig,
    compose,
    system_prompt,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from grillui.log import SessionLog

NODE = "n1"
THREAD = "t-retention"
SAID = "That turns on how the log is compacted."
READS = ["src/grillui/log.py", "the vendor's retention note"]

# What a seat writes when it asks well, as the driver reads it back.
ASKING = json.dumps({"text": SAID, NEEDS_TO_READ_KEY: READS})
OFFER = {"decision": NODE, "option": None, "text": "Thirty days", "because": "the thread said so"}

# A seat saying in prose what the key is for. Every wording a lexical reader
# would reach for is in it, and none of it is a request.
SAID_IN_PROSE = (
    "I would need to read src/grillui/log.py to answer that, and I cannot read it from here."
)

# What the thread seat is told about the request, stated whole. The brief is the
# seat's whole contract for a field read in code, so a reword is a change to
# what the backend will be sent.
READ_REQUEST = (
    "You cannot read this project: no files, no repository, no search, no web. When you cannot "
    "answer without reading something you were not given, say so in your prose and send "
    "`needs_to_read` beside `text`: a list of strings naming what you would have to read, each "
    "a path or a pattern in the project, or a document outside it. Name what you would read, "
    "not what you think it says -- do not guess at the content, and do not answer as though "
    "you had read it. The backend takes the list as a request to hand this conversation to a "
    "seat that can read, and the human is shown what you asked for."
)

# Every shape the field does not take. Each is malformed for one reason, so a
# reader that took any of them would be taking that reason.
MALFORMED: list[tuple[str, Any]] = [
    ("not a list at all", "src/grillui/log.py"),
    ("a list of nothing", []),
    ("an item that is not a string", ["src/grillui/log.py", 3]),
    ("an item that is empty", ["src/grillui/log.py", "   "]),
    ("an object rather than a list", {"path": "src/grillui/log.py"}),
]

# The prompt a thread turn composes when it asked to read, stated whole. A
# literal rather than a second call, so where the request sits is pinned along
# with everything around it: the section it is inside, the line it is on, and
# the turn it follows.
ASKING_PROMPT = (
    "## Briefing\n\n"
    "No briefing was recorded for this session.\n\n"
    "## The board, whole\n\n"
    "{}\n\n"
    f"## This channel ({THREAD})\n\n"
    f"thread-agent: {SAID}\n"
    f"thread-agent: {ASKED_TO_READ}{', '.join(READS)}\n\n"
    "## Your turn\n\n"
    "Answer the last thing the human said, under the rules you were given."
)

# The same prompt where the turn asked for nothing.
NO_FIELD_PROMPT = (
    "## Briefing\n\n"
    "No briefing was recorded for this session.\n\n"
    "## The board, whole\n\n"
    "{}\n\n"
    f"## This channel ({THREAD})\n\n"
    f"thread-agent: {SAID}\n\n"
    "## Your turn\n\n"
    "Answer the last thing the human said, under the rules you were given."
)


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


@pytest.mark.parametrize(("case", "value"), MALFORMED)
@pytest.mark.parametrize("beside", [None, OFFER], ids=["alone", "beside an offer"])
def test_a_half_shaped_request_is_the_turns_prose_exactly_as_written(
    case: str, value: Any, beside: dict[str, Any] | None
) -> None:
    """
    Given a reply naming the key in a shape the field does not take, with and
         without a well-formed offer beside it
    When the driver reads what the turn declared
    Then the whole reply is the turn's prose, byte for byte, and nothing is
         declared.

    Whatever else the object carries goes with it. An object the seat
    half-shaped is a guess, and mining a guess for the parts that happened to
    parse is how a condition that spends the expert seat comes to act on bytes
    no seat meant as a request.
    """
    said: dict[str, Any] = {"text": SAID, NEEDS_TO_READ_KEY: value}
    if beside is not None:
        said[PROPOSED_ANSWER_KEY] = beside
    reply = json.dumps(said)

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


@pytest.mark.parametrize(("case", "value"), MALFORMED)
@pytest.mark.parametrize("beside", [None, OFFER], ids=["alone", "beside an offer"])
def test_a_half_shaped_request_reaches_the_log_as_prose_and_not_as_a_key(
    client: TestClient,
    log: SessionLog,
    case: str,
    value: Any,
    beside: dict[str, Any] | None,
) -> None:
    """
    Given a thread agent naming the key in a shape the field does not take,
         with and without a well-formed offer beside it
    When the driver records the reply
    Then the human is shown the bytes the seat wrote, and neither the request
         nor the offer rides the payload.

    Pinned on the entry rather than on the reader alone: what a condition reads
    and what the human is shown are both this payload, and a reader that
    refused the shape while the writer kept a key would leave them disagreeing.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch)
    said: dict[str, Any] = {"text": SAID, NEEDS_TO_READ_KEY: value}
    if beside is not None:
        said[PROPOSED_ANSWER_KEY] = beside
    reply = json.dumps(said)

    record_reply(log, FAST_TIER, THREAD, reply, {"tier": FAST_TIER})

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert written["payload"]["text"] == reply, case
    assert NEEDS_TO_READ_KEY not in written["payload"], case
    assert PROPOSED_ANSWER_KEY not in written["payload"], case


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
    Then the prompt is the one stated here whole: the request is a line of the
         channel's conversation section, directly under the prose it rode in on.

    Against a literal, because where the line sits is the claim. A request
    somewhere in the prompt is a request the seat above may read as part of the
    briefing or the board, and neither is the conversation it is answering.
    """
    entries = [entry(SAID, **{NEEDS_TO_READ_KEY: READS})]

    assert compose("{}", dispatch_context(THREAD), entries) == ASKING_PROMPT


def test_a_reply_without_the_field_composes_the_prompt_it_always_composed() -> None:
    """
    Given a thread turn recorded with no request, and one with a request the
         seat half-shaped
    When each prompt is composed
    Then both are the prompt this composition has always produced, stated here
         in full.

    Against a literal rather than against another composition: two values from
    the same call agree with each other whatever the call does, so a change to
    the ordinary prompt would move both and be seen by neither.
    """
    plain = compose("{}", dispatch_context(THREAD), [entry(SAID)])
    half = compose("{}", dispatch_context(THREAD), [entry(SAID, **{NEEDS_TO_READ_KEY: []})])

    assert plain == NO_FIELD_PROMPT
    assert half == NO_FIELD_PROMPT


# ── the seat is told ──


@pytest.mark.parametrize("tier", [FAST_TIER, "heavy"])
def test_the_thread_seat_is_told_it_cannot_read_and_how_to_ask(tier: str) -> None:
    """
    Given the thread agent's brief on each tier
    When it is read for what to do when the answer is behind something it cannot
         open
    Then the brief carries the rule stated here whole, exactly once.

    Pinned as bytes rather than as fragments. A seat told only that the key
    exists still answers from what it imagines the file says, so every clause is
    load-bearing and a reword is a change to what the backend will be sent; and
    a rule the brief carried twice is the seat reading the same instruction as
    two, which is how one of them gets treated as the exception to the other.
    """
    brief = system_prompt(tier, "thread-agent")

    assert READ_REQUEST_RULE == READ_REQUEST
    assert brief.count(READ_REQUEST) == 1
    assert READ_REQUEST not in system_prompt(tier, "grill-master")


def transfers(log: SessionLog, channel: str) -> list[str]:
    """What the lane said each time the policy moved this one channel."""
    return [
        str(one.payload.get("detail"))
        for one in log.entries()
        if one.kind == STATUS_KIND
        and one.channel == channel
        and one.payload.get("phase") == STATUS_PHASE_TRANSFERRED
    ]


def test_a_seat_that_says_in_prose_it_would_have_to_read_asks_for_nothing(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session whose thread seat says in prose that it would
         have to read a named path, sending no key
    When the turn is recorded
    Then no recommendation rides its attribution and the lane moves nothing.

    The condition is the seat's request, and a request is a key it either sent
    or did not. A reader that went looking for the words would fire on a seat
    thinking aloud, which is the model's opinion of its own reach -- the one
    thing this module refuses as evidence -- and it would spend the expert seat
    on it.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch)
    driver = FastDriver(
        TierConfig(escalation_policy=POLICY_AUTONOMOUS), lambda **_asked: (SAID_IN_PROSE, None)
    )

    driver.run(log, record_dispatch(log, channel=THREAD))

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert written["payload"]["text"] == SAID_IN_PROSE
    assert RECOMMENDATION_KEY not in written["payload"]
    assert transfers(log, THREAD) == []


def test_two_turns_overlapping_on_one_channel_buy_one_transfer(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session and two first-rung turns on one thread, each
         held at its transport until the other has read the log
    When both replies ask to read and both land
    Then the lane carries one transfer.

    Turns on a channel run on threads of their own, so both read the log before
    either writes. A cap decided against the reading a turn opened with is a cap
    two turns pass together, and the human pays for the expert twice on one
    request.
    """
    seed_node(client, log.epoch, NODE)
    open_thread(client, log.epoch)
    both = threading.Barrier(2, timeout=TIMEOUT)

    def held(**_asked: Any) -> tuple[str, None]:
        """A seat that does not answer until the other turn has read the log."""
        both.wait()
        return ASKING, None

    driver = FastDriver(TierConfig(escalation_policy=POLICY_AUTONOMOUS), held)
    running = [
        threading.Thread(target=driver.run, args=(log, record_dispatch(log, channel=THREAD)))
        for _ in range(2)
    ]
    for one in running:
        one.start()
    for one in running:
        one.join(TIMEOUT)
        assert not one.is_alive(), "a turn outlived its timeout"

    assert transfers(log, THREAD) == [
        "the escalation policy moved this channel to the expert tier: "
        "the seat asked to read something it was not given"
    ]
