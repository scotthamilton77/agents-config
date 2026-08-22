"""Transfer to expert: who moves a channel between tiers, and what the move costs.

Three claims are pinned here, and all three are about a gesture that is the
human's alone.

**The recommendation reaches the page as data, not as a decision.** A fast reply
that met one of the escalation conditions says so in the payload the page reads
back off the wire; a reply that met none says nothing there. The control the
human presses is theirs either way, so what is asserted is the metadata's
arrival, never a tier that moved on its own.

**The move is per channel and works in both directions.** Activating transfer
takes the next turn on that one channel to the heavy tier and hands it the
channel's whole accumulated conversation rather than the last message;
deactivating brings the next turn back to the fast tier. Every other channel
stays where the human left it through both switches.

**Only a human moves a channel.** The mode is read off the human's own turns, so
an agent reply carrying the same payload key moves nothing in either direction.
That is the whole of the human gate, and it is asserted rather than described.

Nothing here reaches a network or a model: both tiers run against scripted
transports, every turn is joined rather than raced, and every attribution claim
is read back out of the log file's bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from conftest import ScriptedCli, ScriptedFast, replies, run_turns, seed_node
from fastapi.testclient import TestClient

from grillui.drivers import FastDriver, HeavyDriver
from grillui.escalation import CONDITION_IRREDUCIBLE
from grillui.lane import Lane
from grillui.schemas import (
    EFFORT_KEY,
    FAST_TIER,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    RECOMMENDATION_KEY,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    TIER_KEY,
    TRANSFER_FLAG,
    EventSubmission,
)
from grillui.tiers import DEFAULT_HEAVY_EFFORT, TierConfig

if TYPE_CHECKING:
    from grillui.log import SessionLog

NODE = "n1"
MINE = "t-retention"
OTHER = "t-compaction"
AGENTS = frozenset({"grill-master", "thread-agent"})

FAST_MODEL = "vendor/fast-2"
HEAVY_MODEL = "claude-configured"

# Every line is unique, so "the whole conversation crossed" and "only the last
# message crossed" are told apart by looking for the words in the bytes the
# tier was handed.
FIRST_ASKED = "Does the log survive a crash mid-write?"
FAST_SAID = "It is fsynced before the receipt settles."
ESCALATED_ASKED = "Then weigh the retention window against the archive cost."
HEAVY_SAID = "Thirty days, then archive: the cost curve turns there."
THREAD_OPENED = "How long is a session kept?"
LATER_ASKED = "And what does that cost to store?"


def human(kind: str, channel: str, key: str, /, **payload: Any) -> EventSubmission:
    """One human gesture, straight to the lane: these tests join the turns a
    batch schedules, which the write endpoint does not hand back.

    Positional-only, because a thread gesture's payload carries a `kind` of its
    own and the envelope's must not be shadowed by it."""
    return EventSubmission(
        kind=kind, actor="human", channel=channel, idempotency_key=key, payload=payload
    )


def answered(key: str, text: str, **payload: Any) -> EventSubmission:
    return human("answer", MAP_CHANNEL, key, target=NODE, answer={"text": text}, **payload)


def said(thread: str, key: str, text: str, **payload: Any) -> EventSubmission:
    return human("thread-turn", thread, key, turns=[{"text": text}], **payload)


def opened(thread: str, key: str, text: str, **payload: Any) -> EventSubmission:
    return human(
        "thread-created",
        thread,
        key,
        decision=NODE,
        kind="mandate",
        title="Retention",
        requires_action=True,
        turns=[{"who": "human", "text": text}],
        **payload,
    )


def both_tiers() -> tuple[FastDriver, HeavyDriver, ScriptedCli]:
    """Both real drivers over scripted transports, plus the CLI to read the
    heavy turns back off.

    The shipped drivers rather than stand-ins, so a turn runs the path a session
    runs: the prompt is composed, the reply is read, and the log is written to
    by the code that does it for real.
    """
    cli = ScriptedCli(reply=HEAVY_SAID)
    return (
        FastDriver(TierConfig(fast_model=FAST_MODEL), ScriptedFast(reply=FAST_SAID)),
        HeavyDriver(TierConfig(heavy_model=HEAVY_MODEL), cli),
        cli,
    )


def waited_on(log: SessionLog, channel: str) -> list[str]:
    """Which tier the lane told the human this channel is waiting on, in order.

    Read from the `composing` entries rather than from the drivers, because that
    entry is what the human sees while the turn is in flight -- a lane that
    named one tier and dispatched another would be lying at exactly the moment
    the human is deciding whether the transfer they paid for took.
    """
    return [
        str(entry.payload.get("tier"))
        for entry in log.entries()
        if entry.kind == STATUS_KIND
        and entry.channel == channel
        and entry.payload.get("phase") == STATUS_PHASE_COMPOSING
    ]


def on_the_wire(client: TestClient, log: SessionLog) -> list[dict[str, Any]]:
    """The agents' spoken turns as the page reads them off the updates surface.

    An agent actor and an attributed payload, both: the lane's own `composing`
    entry names a tier as well, and a board mutation an agent authored carries
    no attribution -- a filter on either half alone would be asserting against
    something other than a reply.
    """
    read = client.get("/updates", params={"epoch": log.epoch, "cursor": 0}).json()
    entries: list[dict[str, Any]] = read["entries"]
    return [
        entry["payload"]
        for entry in entries
        if entry["actor"] in AGENTS and TIER_KEY in entry["payload"]
    ]


def prompts(cli: ScriptedCli) -> list[str]:
    """What each heavy turn was actually asked, out of the argv it was invoked
    with: the prompt is the last argument."""
    return [call[-1] for call in cli.calls]


def conversation(prompt: str) -> str:
    """The channel's own turns out of one prompt, as the composer laid them out.

    Sliced out rather than searched for whole, because the board travels in the
    same prompt and carries the human's answer text inside it. A claim about the
    accumulated conversation that the board could satisfy on its own would pass
    against a composer that sent only the last message.
    """
    marker = "## This channel"
    assert marker in prompt, "the composer's prompt lost its conversation section"
    return prompt.partition(marker)[2].partition("\n## ")[0]


# ── GUI-A33: the recommendation metadata's path to the page ──


def test_a_recommended_reply_carries_its_metadata_on_the_wire_the_page_reads(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a transcript meeting one of the escalation conditions
    When the fast tier answers it
    Then the reply the page reads off the updates surface carries the
         recommendation naming the condition.

    Asserted from the wire rather than from the log in memory: the page has no
    other way to learn that the control should be highlighted, and metadata that
    stops at the process is metadata the human never sees.
    """
    seed_node(client, log.epoch, NODE)
    fast, _heavy, _cli = both_tiers()
    lane = Lane(log, fast)

    run_turns(lane, answered("irreducible", "You keep rewording it -- that is not the question."))

    spoken = on_the_wire(client, log)
    assert [payload[RECOMMENDATION_KEY]["condition"] for payload in spoken] == [
        CONDITION_IRREDUCIBLE
    ]


def test_a_reply_meeting_no_condition_carries_no_metadata_on_the_wire(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a transcript meeting none of the escalation conditions
    When the fast tier answers it
    Then the reply on the updates surface carries no recommendation at all, so
         the page has nothing to highlight the control against.
    """
    seed_node(client, log.epoch, NODE)
    fast, _heavy, _cli = both_tiers()
    lane = Lane(log, fast)

    run_turns(lane, answered("ordinary", FIRST_ASKED))

    spoken = on_the_wire(client, log)
    assert [payload[TIER_KEY] for payload in spoken] == [FAST_TIER]
    assert RECOMMENDATION_KEY not in spoken[0]


# ── GUI-A34: activation forces the next turn, carrying the accumulated thread ──


def test_activating_transfer_takes_the_next_map_turn_to_the_heavy_tier(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a map channel that has already had a turn on the fast tier
    When the human takes their next turn with the transfer activated
    Then that turn composes on the heavy tier, the lane says so before it
         starts, the heavy tier is handed the channel's whole conversation
         rather than the last message, and the log attributes the turn to the
         heavy tier's configured model as one that followed a transfer.

    The whole conversation is the point of the transfer: the human is paying for
    an expert opinion on the discussion so far, and a heavy turn handed only the
    last message would answer a question nobody asked in isolation.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, answered("ordinary", FIRST_ASKED))
    run_turns(lane, answered("escalated", ESCALATED_ASKED, **{TRANSFER_FLAG: True}))

    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER, HEAVY_TIER]
    asked = prompts(cli)
    assert len(asked) == 1
    said_to_the_expert = conversation(asked[0])
    assert FIRST_ASKED in said_to_the_expert
    assert FAST_SAID in said_to_the_expert
    assert ESCALATED_ASKED in said_to_the_expert
    assert replies(log) == [
        {"text": FAST_SAID, TIER_KEY: FAST_TIER, MODEL_KEY: FAST_MODEL},
        {
            "text": HEAVY_SAID,
            TIER_KEY: HEAVY_TIER,
            MODEL_KEY: HEAVY_MODEL,
            EFFORT_KEY: DEFAULT_HEAVY_EFFORT,
            FOLLOWED_TRANSFER_KEY: True,
        },
    ]


def test_an_escalated_thread_hands_the_heavy_tier_its_own_accumulated_turns(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a side thread that has already been discussed on the fast tier
    When the human escalates it
    Then the heavy turn is handed that thread's turns from the beginning, and
         its reply is attributed to the heavy tier on that thread's channel.

    The same claim as the map's, made on a thread channel because the tier is a
    property of the channel: a transfer that only worked where the grill-master
    speaks would leave every thread stuck on the fast tier.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, said(MINE, "escalate-mine", LATER_ASKED, **{TRANSFER_FLAG: True}))

    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    asked = prompts(cli)
    assert len(asked) == 1
    said_to_the_expert = conversation(asked[0])
    assert THREAD_OPENED in said_to_the_expert
    assert FAST_SAID in said_to_the_expert
    assert LATER_ASKED in said_to_the_expert
    assert replies(log)[-1] == {
        "text": HEAVY_SAID,
        TIER_KEY: HEAVY_TIER,
        MODEL_KEY: HEAVY_MODEL,
        EFFORT_KEY: DEFAULT_HEAVY_EFFORT,
        FOLLOWED_TRANSFER_KEY: True,
    }


# ── GUI-A35 (backend half): the move back, and the channels it leaves alone ──


def test_deactivating_transfer_returns_the_next_turn_to_the_fast_tier(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a map channel the human moved to the heavy tier
    When they take their next turn with the transfer deactivated
    Then that turn composes on the fast tier and the log attributes it to the
         fast tier's configured model, with nothing claiming it followed a
         transfer.

    The way back is the same gesture as the way up, on the human's own turn.
    A channel that could only be escalated would make the expensive tier a
    one-way door and bill the rest of the session to it.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, answered("escalated", ESCALATED_ASKED, **{TRANSFER_FLAG: True}))
    run_turns(lane, answered("returned", FIRST_ASKED, **{TRANSFER_FLAG: False}))

    assert waited_on(log, MAP_CHANNEL) == [HEAVY_TIER, FAST_TIER]
    assert replies(log)[-1] == {"text": FAST_SAID, TIER_KEY: FAST_TIER, MODEL_KEY: FAST_MODEL}


def test_one_channels_switches_leave_every_other_channel_where_it_was(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given two side threads and the map, with one thread escalated
    When the map is escalated and then returned to the fast tier
    Then the escalated thread is still on the heavy tier, the other thread has
         been on the fast tier throughout, and only the map moved twice.

    Per-channel independence in both directions. A session-wide tier would move
    every channel on one escalation -- and, worse, bring every channel back down
    when the human returned one of them.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, opened(OTHER, "open-other", "When is the log compacted?"))
    run_turns(lane, said(MINE, "escalate-mine", LATER_ASKED, **{TRANSFER_FLAG: True}))
    run_turns(lane, answered("map-up", ESCALATED_ASKED, **{TRANSFER_FLAG: True}))
    run_turns(lane, said(OTHER, "other-again", "And on restart?"))
    run_turns(lane, answered("map-down", FIRST_ASKED, **{TRANSFER_FLAG: False}))
    run_turns(lane, said(MINE, "mine-again", "Say more."))

    assert waited_on(log, MAP_CHANNEL) == [HEAVY_TIER, FAST_TIER]
    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER, HEAVY_TIER]
    assert waited_on(log, OTHER) == [FAST_TIER, FAST_TIER]


# ── GUI-D11: escalation is the human's gesture and nobody else's ──


def test_an_agent_claiming_a_transfer_moves_no_channel_in_either_direction(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an agent reply carrying the transfer key set true on a fast channel,
    and another carrying it set false on a channel the human escalated
    When the next human turn on each channel is scheduled
    Then the fast channel is still fast and the escalated one is still heavy.

    Escalation is human-gated: the mode is read off the human's own turns, so a
    model that learned to emit the key -- by imitation or by instruction -- moves
    nothing. A payload key is open surface, and an agent that could set this one
    could spend the human's subscription without being asked.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, said(MINE, "escalate-mine", LATER_ASKED, **{TRANSFER_FLAG: True}))

    log.submit(
        [
            EventSubmission(
                kind="informational",
                actor="grill-master",
                channel=MAP_CHANNEL,
                idempotency_key="agent-claims-up",
                payload={"text": "Taking this to the expert.", TRANSFER_FLAG: True},
            ),
            EventSubmission(
                kind="thread-turn",
                actor="thread-agent",
                channel=MINE,
                idempotency_key="agent-claims-down",
                payload={"turns": [{"text": "Back to the fast tier."}], TRANSFER_FLAG: False},
            ),
        ],
        log.epoch,
    )
    run_turns(lane, answered("map-after", FIRST_ASKED))
    run_turns(lane, said(MINE, "mine-after", "Say more."))

    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER]
    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER, HEAVY_TIER]
