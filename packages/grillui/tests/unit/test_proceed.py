"""Proceed with expert: the human sends the expert in on a thread without typing.

Four claims are pinned here.

**The gesture is a text-less human turn, and the expert answers it.** The entry
is a `thread-turn` carrying `proceed: true` and no turn. The expert takes the
turn it asks for whatever the channel's mode, and it is handed the thread so far
and a line saying the human asked it to proceed without adding anything.

**A proceed with nothing to proceed on is refused.** A thread nothing created is
refused as every gesture naming no thread is; a reply already on its way, an
expert that spoke last and a thread set aside are refused as *nothing to proceed
on*. That one rule is also what makes a double press, two windows and a repeat
land once. A failed turn leaves nothing outstanding, so the press works again.

**Only the human engages the expert.** Under either policy a recommendation, a
read request and a policy move leave the expert unengaged until the human
sends or proceeds, and an agent's own proceed moves nothing.

**The gesture never reads as an empty turn.** The projection, a later dispatch
and the capture all carry the thread without a turn that says nothing.

Nothing here reaches a network or a model: both tiers run against scripted
transports, and every turn is joined rather than raced.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

import pytest
from conftest import (
    TIMEOUT,
    ScriptedCli,
    ScriptedFast,
    attributions,
    document,
    run_turns,
    seed_node,
)
from test_transfer import (
    ASKED_TO_READ_REPLY,
    FAST_MODEL,
    FAST_SAID,
    HEAVY_MODEL,
    HEAVY_SAID,
    LATER_ASKED,
    MINE,
    NODE,
    THREAD_OPENED,
    both_tiers,
    conversation,
    human,
    opened,
    prompts,
    said,
    transfers,
    waited_on,
)

from grillui.cli import entry
from grillui.drivers import POLICY_MOVED, FastDriver, HeavyDriver
from grillui.escalation import CONDITION_TOOL_NEED, PROCEED_ASKED, in_expert_mode
from grillui.lane import Lane
from grillui.projector import replay
from grillui.schemas import (
    CHAIN_KEY,
    EFFORT_KEY,
    FAST_TIER,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    PROCEED_FLAG,
    REASON_NOTHING_TO_PROCEED,
    REASON_THREAD_WITHOUT_TURN,
    REASON_UNKNOWN_KIND,
    REASON_UNKNOWN_THREAD,
    TIER_KEY,
    TRANSFER_FLAG,
    TRANSFER_SOURCE_KEY,
    TRANSFER_SOURCE_POLICY,
    EventSubmission,
)
from grillui.tiers import DEFAULT_HEAVY_EFFORT, POLICY_AUTONOMOUS, TierConfig

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from grillui.log import SessionLog


def proceeded(thread: str, key: str, /, **payload: Any) -> EventSubmission:
    """The human pressing *Proceed with expert* with nothing typed."""
    return human("thread-turn", thread, key, **{PROCEED_FLAG: True}, **payload)


def accepted(lane: Lane, *events: EventSubmission) -> list[dict[str, Any]]:
    """Accept a batch that may be refused in part, and wait out what it scheduled."""
    receipts, turns = lane.accept(list(events), lane.log.epoch)
    for turn in turns:
        turn.join(TIMEOUT)
        assert not turn.is_alive(), "a scheduled turn outlived its timeout"
    return [receipt.model_dump() for receipt in receipts]


def humans(log: SessionLog, channel: str) -> list[dict[str, Any]]:
    """What the human put on one channel, as the log holds it."""
    return [
        dict(entry.payload)
        for entry in log.entries()
        if entry.actor == "human" and entry.channel == channel
    ]


def expert_turn(**extra: Any) -> dict[str, Any]:
    """The expert's attribution on a thread, as the scripted seats produce it."""
    return {
        "text": HEAVY_SAID,
        TIER_KEY: HEAVY_TIER,
        MODEL_KEY: HEAVY_MODEL,
        EFFORT_KEY: DEFAULT_HEAVY_EFFORT,
        FOLLOWED_TRANSFER_KEY: True,
        CHAIN_KEY: "chain-1",
        **extra,
    }


class FlakyCli(ScriptedCli):
    """An expert whose first turn fails and whose later turns answer."""

    def __call__(self, argv: list[str], directory: Path, /) -> str:
        if not self.calls:
            self.calls.append(list(argv))
            message = "the expert seat is down"
            raise RuntimeError(message)
        return super().__call__(argv, directory)


class HeldFast(ScriptedFast):
    """A first rung that does not answer until the test lets it."""

    def __init__(self) -> None:
        super().__init__(reply=document(text=FAST_SAID))
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(
        self, *, model: str, system: str, prompt: str, shaped: bool = False
    ) -> tuple[str, int | None]:
        self.started.set()
        self.release.wait(TIMEOUT)
        return super().__call__(model=model, system=system, prompt=prompt, shaped=shaped)


def failing_fast(**_: Any) -> tuple[str, int | None]:
    message = "the first rung is down"
    raise RuntimeError(message)


# ── GUI-A112: the text-less proceed and the turn it buys ──


def test_gui_a112_a_textless_proceed_sends_the_expert_in_over_the_thread_as_it_stands(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread the assistant has answered, on the fast tier
    When the human proceeds with nothing typed, as the page sends it
    Then the log gains one human `thread-turn` carrying `proceed` and
         `transfer` and no turn, the expert composes the next turn, it is handed
         every earlier turn and the line saying the human asked it to proceed,
         and its reply says it followed a transfer the human made.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))

    assert humans(log, MINE)[-1] == {PROCEED_FLAG: True, TRANSFER_FLAG: True}
    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    asked = prompts(cli)
    assert len(asked) == 1
    said_to_the_expert = conversation(asked[0])
    assert f"human: {THREAD_OPENED}" in said_to_the_expert
    assert f"thread-agent: {FAST_SAID}" in said_to_the_expert
    assert said_to_the_expert.strip().endswith(f"human: {PROCEED_ASKED}"), said_to_the_expert
    assert attributions(log)[-1] == expert_turn()


def test_gui_a112_a_proceed_on_a_channel_the_policy_moved_keeps_the_policys_attribution(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session whose thread the policy moved on a read request
    When the human proceeds with nothing typed and no transfer key
    Then the expert composes the turn and its reply names the policy as what
         moved the channel.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers(POLICY_AUTONOMOUS, ASKED_TO_READ_REPLY)
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "proceed"))

    assert humans(log, MINE)[-1] == {PROCEED_FLAG: True}
    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    assert attributions(log)[-1] == expert_turn(**{TRANSFER_SOURCE_KEY: TRANSFER_SOURCE_POLICY})


def test_gui_a112_the_gesture_names_the_expert_whatever_the_channels_mode(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread on the fast tier
    When a proceed arrives carrying no transfer key
    Then the expert still takes the turn, and the channel stays where it was.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "proceed"))

    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    assert len(cli.calls) == 1
    assert not in_expert_mode(log.entries(), MINE)


# ── GUI-A114: a proceed with nothing to proceed on ──


def test_gui_a114_a_proceed_naming_no_thread_is_refused_as_every_such_gesture_is(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    before = len(log.entries())

    receipts = accepted(lane, proceeded("t-nothing", "proceed", **{TRANSFER_FLAG: True}))

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_UNKNOWN_THREAD)
    ]
    assert len(log.entries()) == before
    assert cli.calls == []


def test_gui_a114_a_proceed_on_the_map_is_refused_as_every_thread_gesture_there_is(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    before = len(log.entries())

    receipts = accepted(lane, proceeded(MAP_CHANNEL, "proceed"))

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_UNKNOWN_KIND)
    ]
    assert len(log.entries()) == before
    assert cli.calls == []


def test_gui_a114_a_proceed_while_a_reply_is_outstanding_is_refused_naming_it(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    held = HeldFast()
    cli = ScriptedCli(reply=document(text=HEAVY_SAID))
    lane = Lane(
        log,
        FastDriver(TierConfig(fast_model=FAST_MODEL), held),
        HeavyDriver(TierConfig(heavy_model=HEAVY_MODEL), cli),
    )

    _receipts, turns = lane.accept([opened(MINE, "open-mine", THREAD_OPENED)], log.epoch)
    assert held.started.wait(TIMEOUT)
    before = len(log.entries())
    receipts = accepted(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))
    held.release.set()
    for turn in turns:
        turn.join(TIMEOUT)

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_NOTHING_TO_PROCEED)
    ]
    assert "outstanding" in receipts[0]["detail"]
    assert len([one for one in log.entries()[before:] if one.actor == "human"]) == 0
    assert cli.calls == []


def test_gui_a114_two_proceeds_in_one_batch_leave_one_accepted_and_one_expert_turn(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))

    receipts = accepted(lane, proceeded(MINE, "first"), proceeded(MINE, "second"))

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("accepted", None),
        ("rejected", REASON_NOTHING_TO_PROCEED),
    ]
    assert len(cli.calls) == 1
    assert [one for one in humans(log, MINE) if one.get(PROCEED_FLAG)] == [{PROCEED_FLAG: True}]


def test_gui_a114_two_windows_proceeding_at_once_leave_one_accepted_and_one_expert_turn(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))

    gate = threading.Barrier(2)
    results: list[list[dict[str, Any]]] = []

    def press(key: str) -> None:
        gate.wait(TIMEOUT)
        results.append(accepted(lane, proceeded(MINE, key)))

    windows = [threading.Thread(target=press, args=(key,)) for key in ("left", "right")]
    for window in windows:
        window.start()
    for window in windows:
        window.join(TIMEOUT)

    statuses = sorted(receipt["status"] for result in results for receipt in result)
    assert statuses == ["accepted", "rejected"]
    assert len(cli.calls) == 1


def test_gui_a114_a_repeat_after_the_expert_replied_is_refused(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "first"))

    receipts = accepted(lane, proceeded(MINE, "again"))

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_NOTHING_TO_PROCEED)
    ]
    assert "expert" in receipts[0]["detail"]
    assert len(cli.calls) == 1


@pytest.mark.parametrize("gesture", ["thread-park", "thread-close"])
def test_gui_a114_a_proceed_on_a_set_aside_thread_is_refused_naming_its_state(
    gesture: str, client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, human(gesture, MINE, "aside"))

    receipts = accepted(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_NOTHING_TO_PROCEED)
    ]
    state = "parked" if gesture == "thread-park" else "closed"
    assert state in receipts[0]["detail"]
    assert cli.calls == []
    assert replay(log.epoch, log.entries()).threads[0].state == state


def test_gui_a114_after_a_failed_assistant_turn_the_proceed_is_accepted(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    cli = ScriptedCli(reply=document(text=HEAVY_SAID))
    lane = Lane(
        log,
        FastDriver(TierConfig(fast_model=FAST_MODEL), failing_fast),
        HeavyDriver(TierConfig(heavy_model=HEAVY_MODEL), cli),
    )
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))

    run_turns(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))

    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    assert len(cli.calls) == 1
    assert f"human: {THREAD_OPENED}" in conversation(prompts(cli)[0])


def test_gui_a114_after_a_failed_expert_turn_the_proceed_can_be_pressed_again(
    client: TestClient, log: SessionLog
) -> None:
    seed_node(client, log.epoch, NODE)
    fast, _heavy, _cli = both_tiers()
    cli = FlakyCli(reply=document(text=HEAVY_SAID))
    lane = Lane(log, fast, HeavyDriver(TierConfig(heavy_model=HEAVY_MODEL), cli))
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "first", **{TRANSFER_FLAG: True}))

    run_turns(lane, proceeded(MINE, "again"))

    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER, HEAVY_TIER]
    assert len(cli.calls) == 2
    assert attributions(log)[-1]["text"] == HEAVY_SAID


# ── GUI-A115: only the human engages the expert ──


def test_gui_a115_under_gated_a_read_request_engages_nobody_until_the_human_acts(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given a gated session whose assistant asked to read something
    When the human says the next thing with nothing selected, and then proceeds
    Then the assistant takes the turn they said, nothing named the expert until
         the proceed arrived, and the proceed is what engaged it.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers(said=ASKED_TO_READ_REPLY)
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, said(MINE, "mine-after", LATER_ASKED))
    assert waited_on(log, MINE) == [FAST_TIER, FAST_TIER]
    assert cli.calls == []
    assert transfers(log, MINE) == []

    run_turns(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))
    assert waited_on(log, MINE) == [FAST_TIER, FAST_TIER, HEAVY_TIER]
    assert len(cli.calls) == 1


def test_gui_a115_under_autonomous_the_policy_move_buys_no_turn_until_the_human_acts(
    client: TestClient, log: SessionLog
) -> None:
    """
    Given an autonomous session whose assistant asked to read something
    When the reply lands and the policy moves the thread
    Then nothing is composing and nothing was dispatched after that move, and
         the human's proceed is what starts the expert's turn.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers(POLICY_AUTONOMOUS, ASKED_TO_READ_REPLY)
    lane = Lane(log, fast, heavy)

    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    assert transfers(log, MINE) == [POLICY_MOVED + CONDITION_TOOL_NEED]
    assert waited_on(log, MINE) == [FAST_TIER]
    assert cli.calls == []

    run_turns(lane, proceeded(MINE, "proceed"))
    assert waited_on(log, MINE) == [FAST_TIER, HEAVY_TIER]
    assert len(cli.calls) == 1


@pytest.mark.parametrize("policy", ["gated", POLICY_AUTONOMOUS])
def test_gui_a115_a_proceed_from_anyone_but_the_human_moves_nothing(
    policy: str, client: TestClient, log: SessionLog
) -> None:
    """
    Given a thread on the fast tier, under either policy
    When the thread's agent sends a proceed, with no text and with text
    Then the text-less one is refused, the other is recorded and answered by
         nobody, and the channel is where it was.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, cli = both_tiers(policy)
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))

    agent = {"kind": "thread-turn", "actor": "thread-agent", "channel": MINE}
    receipts = accepted(
        lane,
        EventSubmission(**agent, idempotency_key="bare", payload={PROCEED_FLAG: True}),
        EventSubmission(
            **agent, idempotency_key="said", payload={PROCEED_FLAG: True, "text": "Go on."}
        ),
    )

    assert [(one["status"], one.get("reason")) for one in receipts] == [
        ("rejected", REASON_THREAD_WITHOUT_TURN),
        ("accepted", None),
    ]
    assert waited_on(log, MINE) == [FAST_TIER]
    assert cli.calls == []
    assert not in_expert_mode(log.entries(), MINE)


# ── GUI-A117: the gesture never reads as an empty turn ──


def test_gui_a117_a_textless_proceed_never_reads_as_an_empty_turn(
    client: TestClient, log: SessionLog, session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a thread the human proceeded on, which the expert answered
    When the human returns it to the assistant and says the next thing, and the
         session is later captured from its directory alone
    Then the projection and the assistant's dispatch list the spoken turns and
         the expert's reply and no turn without text, and the capture exits 0
         listing the thread.
    """
    seed_node(client, log.epoch, NODE)
    fast, heavy, _cli = both_tiers()
    lane = Lane(log, fast, heavy)
    run_turns(lane, opened(MINE, "open-mine", THREAD_OPENED))
    run_turns(lane, proceeded(MINE, "proceed", **{TRANSFER_FLAG: True}))
    run_turns(lane, said(MINE, "back", LATER_ASKED, **{TRANSFER_FLAG: False}))

    thread = next(one for one in replay(log.epoch, log.entries()).threads if one.id == MINE)
    assert [turn.text for turn in thread.turns] == [
        THREAD_OPENED,
        FAST_SAID,
        HEAVY_SAID,
        LATER_ASKED,
        FAST_SAID,
    ]

    later = conversation(fast.transport.calls[-1]["prompt"])  # type: ignore[attr-defined]
    # The first line is what is left of the section heading the slice cut at.
    lines = [line for line in later.strip().splitlines()[1:] if line.strip()]
    assert f"thread-agent: {HEAVY_SAID}" in lines
    assert f"human: {LATER_ASKED}" in lines
    assert all(line.partition(": ")[2].strip() for line in lines), lines

    del lane, log
    assert entry(["capture", str(session_dir)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert MINE in [one["id"] for one in result["threads"]]
