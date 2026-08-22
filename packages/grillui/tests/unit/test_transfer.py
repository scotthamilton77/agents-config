"""Transfer to expert: who moves a channel between tiers, and what the move costs.

Five claims are pinned here.

**The recommendation reaches the page as data, not as a decision.** A fast reply
that met one of the escalation conditions says so in the payload the page reads
back off the wire; a reply that met none says nothing there. What is asserted is
the metadata's arrival, never a tier that moved on its own.

**The move is per channel and works in both directions.** Activating transfer
takes the next turn on that one channel to the heavy tier and hands it the
channel's whole accumulated conversation rather than the last message;
deactivating brings the next turn back to the fast tier. Every other channel
stays where the human left it through both switches.

**Who acts on a met condition is the session's escalation policy.** Under the
default, the human: the condition is metadata and the channel does not move.
Under `autonomous` the backend moves that one channel itself, on the lane, and
the heavy turn that follows says the policy is what moved it. The default's log
is what it always was -- neither the phase nor the key appears anywhere in it.

**The policy is standing, and the human still governs.** A return to the fast
tier wins over the transfer that preceded it, and a later reply meeting a
condition escalates the channel again.

**Only a human or the policy moves a channel.** The mode is read off the human's
own turns and off the backend's own lane entry, so an agent reply carrying the
same payload key moves nothing in either direction under either policy. That is
the whole of the agent gate, and it is asserted rather than described.

Nothing here reaches a network or a model: both tiers run against scripted
transports, every turn is joined rather than raced, and every attribution claim
is read back out of the log file's bytes.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest
from conftest import (
    TIMEOUT,
    ScriptedCli,
    ScriptedFast,
    attributions,
    driven,
    replies,
    run_turns,
    seed_node,
)
from fastapi.testclient import TestClient

from grillui.drivers import FastDriver, HeavyDriver
from grillui.escalation import CONDITION_IRREDUCIBLE
from grillui.lane import Lane
from grillui.log import LOG_FILE, SessionLog
from grillui.schemas import (
    EFFORT_KEY,
    FAST_TIER,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    NOTICE_KINDS,
    RECOMMENDATION_KEY,
    STATUS_KIND,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_TRANSFERRED,
    TIER_KEY,
    TRANSFER_FLAG,
    TRANSFER_SOURCE_KEY,
    TRANSFER_SOURCE_POLICY,
    EventSubmission,
)
from grillui.tiers import (
    DEFAULT_HEAVY_EFFORT,
    ESCALATION_POLICIES,
    POLICY_AUTONOMOUS,
    POLICY_GATED,
    TierConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from grillui.schemas import Receipt

NODE = "n1"
MINE = "t-retention"
OTHER = "t-compaction"
AGENTS = frozenset({"grill-master", "thread-agent"})

FAST_MODEL = "vendor/fast-2"
HEAVY_MODEL = "claude-configured"

# How long a turn racing the transfer is given to land. It only has to reach an
# append, so this is generous for what it measures -- and it is paid only when
# the lock does its job and holds the racer off.
RACE_WINDOW = 0.25

# Every line is unique, so "the whole conversation crossed" and "only the last
# message crossed" are told apart by looking for the words in the bytes the
# tier was handed.
FIRST_ASKED = "Does the log survive a crash mid-write?"
FAST_SAID = "It is fsynced before the receipt settles."
ESCALATED_ASKED = "Then weigh the retention window against the archive cost."
HEAVY_SAID = "Thirty days, then archive: the cost curve turns there."
THREAD_OPENED = "How long is a session kept?"
# Two turns that meet the irreducible condition, said differently, so a test
# about escalating twice cannot pass on one turn counted twice.
IRREDUCIBLE_ASKED = "You keep rewording it -- that is not the question."
IRREDUCIBLE_AGAIN = "The trade-off is what I cannot resolve."
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


def both_tiers(policy: str = POLICY_GATED) -> tuple[FastDriver, HeavyDriver, ScriptedCli]:
    """Both real drivers over scripted transports, plus the CLI to read the
    heavy turns back off.

    The shipped drivers rather than stand-ins, so a turn runs the path a session
    runs: the prompt is composed, the reply is read, and the log is written to
    by the code that does it for real.

    The policy is the fast tier's, because it is the fast reply meeting a
    condition that the policy has an opinion about. It defaults to what an
    unconfigured session gets, so every check written before the policy existed
    still states the case it always stated.
    """
    cli = ScriptedCli(reply=HEAVY_SAID)
    return (
        FastDriver(
            TierConfig(fast_model=FAST_MODEL, escalation_policy=policy),
            ScriptedFast(reply=FAST_SAID),
        ),
        HeavyDriver(TierConfig(heavy_model=HEAVY_MODEL), cli),
        cli,
    )


class InterleavingLog(SessionLog):
    """A log that gives one waiting turn its chance the instant a reply lands.

    The hook fires after an agent's own append has returned, which is exactly
    the moment between the reply and the transfer that follows it. A second
    thread let in there is the race the append lock has to close: it finds the
    reply on the record and has to find the transfer too, or it schedules the
    turn the policy just bought against a channel it still reads as fast.

    One shot, and only for an agent's append: the human's own turn goes through
    this same door on its way in, and a hook that fired there would be testing
    the window before the reply rather than the one after it.
    """

    hook: Callable[[], None] | None = None

    def submit(self, batch: Sequence[EventSubmission], epoch: str) -> list[Receipt]:
        receipts = super().submit(batch, epoch)
        if self.hook is not None and any(event.actor in AGENTS for event in batch):
            armed, self.hook = self.hook, None
            armed()
        return receipts


def transfers(log: SessionLog, channel: str) -> list[str]:
    """What the lane said each time the policy moved this one channel.

    The detail rather than the count: the human reading the lane is owed the
    condition that fired, and an entry that only said a transfer happened would
    tell them their money was spent without saying on what.
    """
    return [
        str(entry.payload.get("detail"))
        for entry in log.entries()
        if entry.kind == STATUS_KIND
        and entry.channel == channel
        and entry.payload.get("phase") == STATUS_PHASE_TRANSFERRED
    ]


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
    assert attributions(log) == [
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
    assert attributions(log)[-1] == {
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
    assert attributions(log)[-1] == {"text": FAST_SAID, TIER_KEY: FAST_TIER, MODEL_KEY: FAST_MODEL}


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


@pytest.mark.parametrize("policy", ESCALATION_POLICIES)
def test_an_agent_claiming_a_transfer_moves_no_channel_in_either_direction(
    client: TestClient, log: SessionLog, policy: str
) -> None:
    """
    Given an agent reply carrying the transfer key set true on a fast channel,
    and another carrying it set false on a channel the human escalated
    When the next human turn on each channel is scheduled
    Then the fast channel is still fast and the escalated one is still heavy,
         under either escalation policy.

    Escalation is never the agent's: the mode is read off the human's own turns
    and off the backend's own lane entry, so a model that learned to emit the key
    -- by imitation or by instruction -- moves nothing. A payload key is open
    surface, and an agent that could set this one could spend the human's
    subscription without being asked. The autonomous policy widens who may move a
    channel to the backend and to nobody else, which is why it is run here too:
    a gate loosened by one caller is a gate loosened for the model as well.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers(policy)
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


# ── GUI-A71: with no policy configured, a met condition waits for the human ──


def test_a_session_with_no_policy_configured_leaves_a_met_condition_to_the_human(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a session configured with no escalation policy
    When a fast reply meets one of the conditions
    Then the reply carries its recommendation, the lane records no transfer, the
         next turn on that channel is taken by the fast tier, and neither the
         phase nor the source key appears anywhere in the log's bytes.

    The last clause is the whole of the default's promise. A session that never
    asked for autonomous escalation writes the log it wrote before the policy
    existed, so a reader -- the human, the capture pass, anything downstream --
    sees no trace of a feature nobody turned on.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, answered("irreducible", IRREDUCIBLE_ASKED))
    run_turns(lane, answered("after", FIRST_ASKED))

    assert [payload.get(RECOMMENDATION_KEY, {}).get("condition") for payload in replies(log)] == [
        CONDITION_IRREDUCIBLE,
        None,
    ]
    assert transfers(log, MAP_CHANNEL) == []
    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER, FAST_TIER]
    written = (log.directory / LOG_FILE).read_text(encoding="utf-8")
    assert STATUS_PHASE_TRANSFERRED not in written
    assert TRANSFER_SOURCE_KEY not in written


# ── GUI-A72: under `autonomous`, the met condition moves that one channel ──


def test_under_the_autonomous_policy_a_met_condition_takes_that_channel_to_the_expert(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session with a side thread already talking to the fast
         tier about something that meets no condition
    When a fast reply on the map meets one
    Then the next map turn composes on the heavy tier and is handed the map's
         whole accumulated conversation rather than the last message, while the
         thread's next turn is still fast.

    Three claims in one session because they are one claim: the policy moves a
    channel, and a channel is not the session. A transfer that also moved the
    thread would spend the heavy tier's money on every conversation the human
    happened to have open.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers(POLICY_AUTONOMOUS)
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, answered("irreducible", IRREDUCIBLE_ASKED))
    run_turns(lane, answered("after", ESCALATED_ASKED))
    run_turns(lane, said(MINE, "mine-after", "Say more."))

    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER, HEAVY_TIER]
    assert waited_on(log, MINE) == [FAST_TIER, FAST_TIER]
    assert transfers(log, MINE) == []
    asked = prompts(cli)
    assert len(asked) == 1
    said_to_the_expert = conversation(asked[0])
    assert IRREDUCIBLE_ASKED in said_to_the_expert
    assert FAST_SAID in said_to_the_expert
    assert ESCALATED_ASKED in said_to_the_expert


# ── GUI-A73: the escalation is attributed, and the human's is not ──


def test_a_policy_escalation_is_named_on_the_lane_and_on_the_turn_it_bought(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session
    When the policy escalates the map and the human escalates a thread by hand
    Then the lane carries a backend-authored transfer entry on the map naming the
         condition, the heavy map turn carries `transfer_source: "policy"` beside
         a `followed_transfer` flag of the shape it always had, the heavy thread
         turn the human asked for carries no source at all, and the move appends
         nothing the human is notified about.

    The two halves are asserted in one session on purpose: the source key is
    evidence only if its absence means something, and the human's own transfer is
    what absence has to keep meaning.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers(POLICY_AUTONOMOUS)
    lane = Lane(log, fast, heavy)

    run_turns(lane, answered("irreducible", IRREDUCIBLE_ASKED))
    run_turns(lane, answered("after", ESCALATED_ASKED))
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, said(MINE, "escalate-mine", LATER_ASKED, **{TRANSFER_FLAG: True}))

    assert transfers(log, MAP_CHANNEL) == [
        f"the escalation policy moved this channel to the expert tier: {CONDITION_IRREDUCIBLE}"
    ]
    heavy_turns = [payload for payload in attributions(log) if payload[TIER_KEY] == HEAVY_TIER]
    assert heavy_turns == [
        {
            "text": HEAVY_SAID,
            TIER_KEY: HEAVY_TIER,
            MODEL_KEY: HEAVY_MODEL,
            EFFORT_KEY: DEFAULT_HEAVY_EFFORT,
            FOLLOWED_TRANSFER_KEY: True,
            TRANSFER_SOURCE_KEY: TRANSFER_SOURCE_POLICY,
        },
        {
            "text": HEAVY_SAID,
            TIER_KEY: HEAVY_TIER,
            MODEL_KEY: HEAVY_MODEL,
            EFFORT_KEY: DEFAULT_HEAVY_EFFORT,
            FOLLOWED_TRANSFER_KEY: True,
        },
    ]
    authored = {entry.kind for entry in log.entries() if entry.actor == "backend"}
    assert authored == {STATUS_KIND}
    assert not authored & NOTICE_KINDS


# ── GUI-A74: the human still governs, and the policy is standing ──


def test_the_human_takes_a_policy_transfer_back_and_a_later_condition_escalates_again(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a map channel the policy moved to the heavy tier
    When the human sends it back to the fast tier, and a later fast reply meets a
         condition
    Then their return takes the next turn, the channel escalates a second time,
         and the lane names both transfers.

    The policy is standing rather than one-shot, and the human's gesture is not
    overruled by it. Either half failing alone is a session the human cannot
    steer: one that ignores their way back, or one that escalates once and never
    again.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers(POLICY_AUTONOMOUS)
    lane = Lane(log, fast, heavy)

    run_turns(lane, answered("irreducible", IRREDUCIBLE_ASKED))
    run_turns(lane, answered("returned", FIRST_ASKED, **{TRANSFER_FLAG: False}))
    run_turns(lane, answered("irreducible-again", IRREDUCIBLE_AGAIN))
    run_turns(lane, answered("after", ESCALATED_ASKED))

    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER, FAST_TIER, FAST_TIER, HEAVY_TIER]
    assert len(transfers(log, MAP_CHANNEL)) == 2


def test_a_human_turn_arriving_the_instant_the_reply_lands_still_goes_to_the_expert(
    session_dir: Path,
) -> None:
    """
    Given an autonomous session whose fast reply meets a condition
    When a human turn is accepted in the same instant that reply is appended
    Then it is still composed by the heavy tier.

    The reply and the transfer are two appends, and a turn accepted between them
    reads a channel that is still fast -- so the human pays for an escalation and
    the very next turn, the one they were escalated for, is answered by the tier
    they were moved off. The lane already solves this for its own paired entries
    by holding the append lock across both, and that is what is being asserted
    here rather than a lucky ordering: the racing turn is let in at the one
    moment that can go wrong, and has to come out heavy anyway.
    """
    log = InterleavingLog(session_dir)
    seed_node(driven(log, None), log.epoch, NODE)
    fast, heavy, _cli = both_tiers(POLICY_AUTONOMOUS)
    lane = Lane(log, fast, heavy)
    racing: list[threading.Thread] = []

    def race() -> None:
        """The next human turn, taken from a thread of its own so it contends
        for the append lock rather than re-entering it."""
        _receipts, scheduled = lane.accept([answered("raced", ESCALATED_ASKED)], log.epoch)
        racing.extend(scheduled)

    def interleave() -> None:
        runner = threading.Thread(target=race, name="raced-turn")
        racing.append(runner)
        runner.start()
        # Long enough that a driver holding no lock really would let the turn
        # through, so the unguarded version fails here rather than by timing.
        runner.join(RACE_WINDOW)

    log.hook = interleave
    run_turns(lane, answered("irreducible", IRREDUCIBLE_ASKED))
    for thread in racing:
        thread.join(TIMEOUT)
        assert not thread.is_alive(), "a raced turn outlived its timeout"

    assert waited_on(log, MAP_CHANNEL) == [FAST_TIER, HEAVY_TIER]
    assert len(transfers(log, MAP_CHANNEL)) == 1
