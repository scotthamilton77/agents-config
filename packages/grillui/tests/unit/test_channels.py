"""The two layers of channel state, and what each one is allowed to move.

Four claims live here.

**The vocabularies are the spec's, spelled the spec's way.** They are written out
literally rather than derived from the module, because a check that read the
names out of the code under test would pass on any renaming -- including the one
that leaves the page speaking a vocabulary the backend no longer does.

**The tables are walked, not sampled.** Every declared pair is stepped and every
undeclared pair is refused. A table is only a contract if being outside it is an
event; a step that fell through to "stay where you were" would turn a state this
model does not have into a plausible-looking indicator.

**One channel's traffic moves one channel.** The reason the split exists at all
is that a thread stalling says nothing about the map, so the check is not that
the stalled channel is stalled -- it is that everything else is exactly where it
was.

**A transport drop is not a protocol event.** The wire going down changes what
every channel says about the wire and nothing about the conversation on it: the
turns are still owed, and pretending otherwise loses the human's place the moment
their network blinks.
"""

from __future__ import annotations

import pytest

from grillui.channels import (
    PROTOCOL_EVENTS,
    PROTOCOL_SEVERITY,
    PROTOCOL_STATES,
    PROTOCOL_TABLE,
    TRANSPORT_EVENTS,
    TRANSPORT_SEVERITY,
    TRANSPORT_STATES,
    TRANSPORT_TABLE,
    Channels,
    ChannelView,
    UndeclaredTransitionError,
    protocol_step,
    transport_step,
    worst,
)

MAP = "map"
THREAD = "t-1"
OTHER = "t-2"


def declared(table: dict[str, dict[str, str]]) -> list[tuple[str, str, str]]:
    return [(state, event, to) for state, moves in table.items() for event, to in moves.items()]


def undeclared(
    table: dict[str, dict[str, str]], states: tuple[str, ...], events: tuple[str, ...]
) -> list[tuple[str, str]]:
    return [
        (state, event) for state in states for event in events if event not in table.get(state, {})
    ]


# ── the vocabularies ──


def test_the_transport_layers_states_are_the_four_the_spec_names() -> None:
    assert list(TRANSPORT_STATES) == ["disconnected", "connecting", "connected", "error"]


def test_a_channels_protocol_states_are_the_five_the_spec_names() -> None:
    assert list(PROTOCOL_STATES) == [
        "idle",
        "sending",
        "awaiting-ack",
        "agent-owes",
        "receiving",
    ]


def test_every_state_in_both_tables_is_one_of_the_declared_states() -> None:
    """The table cannot invent a sixth state by typo.

    Both ends of every row are checked: a destination outside the vocabulary is
    a state nothing renders and nothing can leave, and it would only surface
    when a session happened to reach it.
    """
    for state, _event, to in declared(TRANSPORT_TABLE):
        assert state in TRANSPORT_STATES
        assert to in TRANSPORT_STATES
    for state, _event, to in declared(PROTOCOL_TABLE):
        assert state in PROTOCOL_STATES
        assert to in PROTOCOL_STATES


def test_both_severity_orders_rank_every_state_exactly_once() -> None:
    """Worst-state-wins needs a total order, or the amalgamated indicator has a
    state it cannot compare and picks whichever channel it happened to read
    first."""
    assert sorted(TRANSPORT_SEVERITY) == sorted(TRANSPORT_STATES)
    assert sorted(PROTOCOL_SEVERITY) == sorted(PROTOCOL_STATES)


# ── the tables, walked ──


@pytest.mark.parametrize(("state", "event", "expected"), declared(TRANSPORT_TABLE))
def test_every_declared_transport_transition_steps_where_it_says(
    state: str, event: str, expected: str
) -> None:
    assert transport_step(state, event) == expected


@pytest.mark.parametrize(("state", "event", "expected"), declared(PROTOCOL_TABLE))
def test_every_declared_protocol_transition_steps_where_it_says(
    state: str, event: str, expected: str
) -> None:
    assert protocol_step(state, event) == expected


def test_the_transport_table_is_total_over_its_own_states_and_events() -> None:
    """Whatever the wire does, from wherever it was, there is an answer.

    The transport is the one layer with no unreachable pairs: a request can go
    out, come back, die or be refused from any state the last one left it in. A
    hole here would be a wedged connection indicator at the exact moment the
    human needs it.
    """
    assert undeclared(TRANSPORT_TABLE, TRANSPORT_STATES, TRANSPORT_EVENTS) == []


@pytest.mark.parametrize(
    ("state", "event"), undeclared(PROTOCOL_TABLE, PROTOCOL_STATES, PROTOCOL_EVENTS)
)
def test_every_undeclared_protocol_pair_is_refused(state: str, event: str) -> None:
    """The pairs the table leaves out are contradictions, and they are refused
    rather than absorbed.

    Absorbing them is the failure worth naming: a receipt applied to a channel
    that never sent anything, or bytes leaving one that was not building a
    request, would each leave a channel sitting in a state its own traffic
    cannot explain.
    """
    with pytest.raises(UndeclaredTransitionError):
        protocol_step(state, event)


@pytest.mark.parametrize("layer", ["transport", "protocol"])
def test_an_event_neither_vocabulary_has_a_word_for_is_refused(layer: str) -> None:
    step = transport_step if layer == "transport" else protocol_step
    start = TRANSPORT_STATES[0] if layer == "transport" else PROTOCOL_STATES[0]
    with pytest.raises(UndeclaredTransitionError):
        step(start, "reticulated")


def test_a_state_neither_vocabulary_has_a_word_for_is_refused() -> None:
    with pytest.raises(UndeclaredTransitionError):
        protocol_step("halfway", "submit")


# ── one channel's traffic moves one channel ──


def test_a_thread_stalled_in_awaiting_ack_leaves_the_map_channel_where_it_was() -> None:
    """
    Given a session with the map and two threads open
    When one thread's write goes out and no receipt comes back
    Then that thread is in `awaiting-ack` and every other channel is still idle.

    This is the whole reason the protocol state is per channel. A single
    session-wide "waiting" would have the human reading one thread's stall as
    the board being stuck, and answering nothing while everything else was
    available.
    """
    channels = Channels([MAP, THREAD, OTHER])

    channels.on_channel(THREAD, "submit")
    channels.on_channel(THREAD, "dispatched")

    assert channels.protocol_of(THREAD) == "awaiting-ack"
    assert channels.protocol_of(MAP) == "idle"
    assert channels.protocol_of(OTHER) == "idle"


def test_the_map_channel_waiting_on_the_grill_master_leaves_every_thread_where_it_was() -> None:
    """The same claim from the other end: the map is not a parent channel."""
    channels = Channels([MAP, THREAD, OTHER])
    channels.on_channel(THREAD, "submit")
    channels.on_channel(THREAD, "dispatched")

    channels.on_channel(MAP, "owed")
    channels.on_channel(MAP, "arriving")

    assert channels.protocol_of(MAP) == "receiving"
    assert channels.protocol_of(THREAD) == "awaiting-ack"
    assert channels.protocol_of(OTHER) == "idle"


def test_a_receipt_the_log_got_in_front_of_does_not_walk_the_channel_back() -> None:
    """
    Given a channel whose write is away and whose `composing` has already been
    read
    When that write's receipt finally comes back
    Then the channel is still waiting on the agent.

    The backend writes the lane inside the same lock as the append, so a read
    that lands between the two knows an agent owes this channel a turn before the
    writer's own receipt returns. Treating the receipt as the end of the wait
    would clear the indicator for a reply nobody has had yet.
    """
    channels = Channels([MAP])
    channels.on_channel(MAP, "submit")
    channels.on_channel(MAP, "dispatched")
    channels.on_channel(MAP, "owed")

    channels.on_channel(MAP, "settled")

    assert channels.protocol_of(MAP) == "agent-owes"


def test_a_channel_opened_twice_is_not_reset_to_idle() -> None:
    """A thread the board mentions again has not stopped waiting.

    The board is re-read on every poll, so every open thread is offered to this
    model again each time. If that were a reset, a channel waiting on an agent
    would return to idle roughly once a second and the human would never see the
    wait at all.
    """
    channels = Channels([MAP])
    channels.on_channel(THREAD, "owed")

    channels.open_channel(THREAD)

    assert channels.protocol_of(THREAD) == "agent-owes"


# ── the transport drop ──


def test_a_transport_drop_moves_every_channels_connection_and_no_channels_protocol() -> None:
    """
    Given three channels in three different protocol states
    When the transport drops
    Then every channel reports the new connection state and every protocol state
         is exactly what it was.

    A network blink is not an answer. The turns an agent owed before it are
    still owed after it, and a page that cleared them would tell the human their
    message had been dealt with because their wifi went.
    """
    channels = Channels([MAP, THREAD, OTHER])
    channels.on_transport("open")
    channels.on_transport("reached")
    channels.on_channel(MAP, "owed")
    channels.on_channel(THREAD, "submit")
    channels.on_channel(THREAD, "dispatched")
    before = {view.channel: view.protocol for view in channels.views()}

    channels.on_transport("unreachable")

    assert [view.connection for view in channels.views()] == ["disconnected"] * 3
    assert {view.channel: view.protocol for view in channels.views()} == before
    assert before == {MAP: "agent-owes", THREAD: "awaiting-ack", OTHER: "idle"}


def test_a_transport_that_comes_back_finds_every_channel_still_owed_what_it_was() -> None:
    """Recovery is the other half of the same claim: nothing was lost, so
    nothing is re-derived on the way back up."""
    channels = Channels([MAP, THREAD])
    channels.on_transport("open")
    channels.on_transport("reached")
    channels.on_channel(MAP, "owed")

    channels.on_transport("unreachable")
    channels.on_transport("open")
    channels.on_transport("reached")

    assert channels.transport == "connected"
    assert channels.protocol_of(MAP) == "agent-owes"


def test_an_endpoint_that_answers_with_a_failure_is_a_different_state_from_silence() -> None:
    """Nothing listening and something listening and broken are different
    problems, and the human is told which one they have."""
    channels = Channels([MAP])
    channels.on_transport("open")

    channels.on_transport("refused")
    assert channels.transport == "error"

    channels.on_transport("unreachable")
    assert channels.transport == "disconnected"


# ── the amalgamated indicator ──


def test_a_thread_in_awaiting_ack_beside_an_idle_map_amalgamates_to_the_thread() -> None:
    """GUI-A41's own arrangement, at the derivation.

    The indicator is one light over however many channels, so what it shows is
    the worst of them. A light showing the map's idle while a thread's write is
    unacknowledged is the failure: it reads as everything being fine.
    """
    channels = Channels([MAP, THREAD])
    channels.on_transport("open")
    channels.on_transport("reached")
    channels.on_channel(THREAD, "submit")
    channels.on_channel(THREAD, "dispatched")

    shown = channels.worst()

    assert shown == ChannelView(channel=THREAD, connection="connected", protocol="awaiting-ack")


def test_the_diagnostic_lists_every_channel_with_both_of_its_layers() -> None:
    """What the expansion is for: the amalgamated light says something is wrong,
    and this says which channel and in which layer."""
    channels = Channels([MAP, THREAD])
    channels.on_transport("open")
    channels.on_transport("reached")
    channels.on_channel(MAP, "owed")

    assert channels.views() == [
        ChannelView(channel=MAP, connection="connected", protocol="agent-owes"),
        ChannelView(channel=THREAD, connection="connected", protocol="idle"),
    ]


def test_a_down_transport_outranks_any_protocol_state_on_any_channel() -> None:
    """The wire is ranked first, so a channel mid-conversation on a dead
    transport shows the dead transport. Nothing that channel was in the middle of
    saying is going to happen until the wire is back."""
    quiet = ChannelView(channel=MAP, connection="disconnected", protocol="idle")
    busy = ChannelView(channel=THREAD, connection="connected", protocol="awaiting-ack")

    assert worst([busy, quiet]) == quiet


def test_worst_of_no_channels_at_all_is_nothing_rather_than_a_guess() -> None:
    assert worst([]) is None


@pytest.mark.parametrize(
    ("worse", "better"),
    [
        ("awaiting-ack", "agent-owes"),
        ("agent-owes", "receiving"),
        ("receiving", "sending"),
        ("sending", "idle"),
    ],
)
def test_the_protocol_severity_order_is_the_one_stated(worse: str, better: str) -> None:
    """Stated pair by pair, so the ordering is a decision rather than whatever
    the list happened to be written in."""
    assert PROTOCOL_SEVERITY.index(worse) > PROTOCOL_SEVERITY.index(better)


@pytest.mark.parametrize(
    ("worse", "better"),
    [("error", "disconnected"), ("disconnected", "connecting"), ("connecting", "connected")],
)
def test_the_transport_severity_order_is_the_one_stated(worse: str, better: str) -> None:
    assert TRANSPORT_SEVERITY.index(worse) > TRANSPORT_SEVERITY.index(better)


def test_a_session_starts_disconnected_with_the_map_channel_idle() -> None:
    """Before anything has been reached, the page has not been told the backend
    is there -- and saying so is the difference between a session starting and a
    session whose backend never came up."""
    channels = Channels()

    assert channels.transport == "disconnected"
    assert channels.views() == [
        ChannelView(channel=MAP, connection="disconnected", protocol="idle")
    ]
