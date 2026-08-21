"""Channel state, in the two layers it actually has.

A channel is one conversational lane between the page and an agent: one for the
map, one per thread. What is true of a channel splits cleanly in two, and
conflating the halves is how a page ends up telling a human that a model is
composing when the wire is down, or that everything is fine when a message never
landed.

**The connection lifecycle belongs to the transport.** `disconnected`,
`connecting`, `connected`, `error` -- one origin, one process, one answer. Every
channel reads the same transport state because there is only one, and that is
why a transport drop moves what every channel reports about the wire and touches
nothing about the conversation on it.

**The protocol state belongs to each channel.** `idle`, `sending`,
`awaiting-ack`, `agent-owes`, `receiving` -- one value per channel, moved only by
that channel's own traffic. A thread whose turn is stuck says nothing about the
map or about any other thread, because no event here is addressed to more than
one channel.

Both layers are total functions of a declared table rather than of branching
code: a pair the table does not name is refused rather than guessed, so a state
this model was never designed to be in surfaces as a raised error at the moment
it happens instead of as a plausible-looking indicator.

The transport table is total on purpose -- whatever the wire does, from wherever
it was, there is an answer -- because a wedged transport layer is indistinguishable
from a working one that has nothing to say. The protocol table is not: the three
pairs it leaves out are contradictions rather than unhandled cases. Bytes cannot
leave a channel that was not building a request, a receipt cannot come back for a
request never sent, and nothing arrives from the log in the middle of a
synchronous send.

The page ships a copy of these tables and steps them the same way. It is a copy
because the page cannot ask the backend what its own wire is doing -- a page that
could would have to be connected to find out it was not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from grillui.schemas import MAP_CHANNEL

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# ── the two vocabularies ──

TRANSPORT_STATES: tuple[str, ...] = ("disconnected", "connecting", "connected", "error")
PROTOCOL_STATES: tuple[str, ...] = ("idle", "sending", "awaiting-ack", "agent-owes", "receiving")

# What moves the transport: a request going out, one that came back, one that
# never got an answer, and one the endpoint answered with a failure the caller
# cannot use. The last two are different states because they are different
# problems -- nothing is listening, against something is listening and broken.
TRANSPORT_EVENTS: tuple[str, ...] = ("open", "reached", "unreachable", "refused")

# What moves one channel: the page starting a write, the bytes leaving, the
# write's receipt (or its failure) coming back, the log saying an agent owes this
# channel a turn, that agent's entries arriving, and the turn ending either way.
PROTOCOL_EVENTS: tuple[str, ...] = (
    "submit",
    "dispatched",
    "settled",
    "owed",
    "arriving",
    "closed",
)

# ── the transition tables ──

TRANSPORT_TABLE: dict[str, dict[str, str]] = {
    "disconnected": {
        "open": "connecting",
        "reached": "connected",
        "unreachable": "disconnected",
        "refused": "error",
    },
    "connecting": {
        "open": "connecting",
        "reached": "connected",
        "unreachable": "disconnected",
        "refused": "error",
    },
    "connected": {
        "open": "connected",
        "reached": "connected",
        "unreachable": "disconnected",
        "refused": "error",
    },
    "error": {
        "open": "connecting",
        "reached": "connected",
        "unreachable": "disconnected",
        "refused": "error",
    },
}

# Two rules shape what is in here beyond the obvious path.
#
# `submit` is declared from every state a gesture can be made in, and a second
# gesture on a channel an agent already owes drops that channel to `sending`
# rather than remembering both. It costs one poll: the new turn's own `composing`
# puts the channel back on `agent-owes`, and until it lands the human is looking
# at the message they just sent rather than at the one before it.
#
# `settled` returns a channel to idle only from the states that were waiting for
# it. A write's receipt can be overtaken -- the backend writes the lane inside
# the same lock as the append, so a read that lands between the two can already
# know an agent owes this channel a turn -- and a receipt applied afterwards must
# not walk that back. The receipt ends one write; it does not end whatever the
# log has since said.
#
# What stays out is what cannot happen. `submit` and `dispatched` are one
# synchronous step apart on the page, so nothing from the log interleaves between
# them: `sending` can only ever be left by dispatching, and no other state can be
# left by it.
PROTOCOL_TABLE: dict[str, dict[str, str]] = {
    "idle": {
        "submit": "sending",
        "settled": "idle",
        "owed": "agent-owes",
        "arriving": "receiving",
        "closed": "idle",
    },
    "sending": {
        "dispatched": "awaiting-ack",
    },
    "awaiting-ack": {
        "submit": "sending",
        "settled": "idle",
        "owed": "agent-owes",
        "arriving": "receiving",
        "closed": "idle",
    },
    "agent-owes": {
        "submit": "sending",
        "settled": "agent-owes",
        "owed": "agent-owes",
        "arriving": "receiving",
        "closed": "idle",
    },
    "receiving": {
        "submit": "sending",
        "settled": "receiving",
        "owed": "agent-owes",
        "arriving": "receiving",
        "closed": "idle",
    },
}

# How bad each state is, worst last. The amalgamated indicator shows the worst
# channel, so this order is what the human is shown when two channels disagree.
#
# On the wire: nothing to report, then trying, then nothing is listening, then
# something is listening and broken.
TRANSPORT_SEVERITY: tuple[str, ...] = ("connected", "connecting", "disconnected", "error")

# On a channel: quiet, then two states that are motion rather than waiting, then
# a wait on an agent, then a write nobody has acknowledged. `awaiting-ack` ranks
# worst because it is the only one that might mean a message was lost; waiting on
# an agent is ordinary, and the human still has to see it.
PROTOCOL_SEVERITY: tuple[str, ...] = (
    "idle",
    "sending",
    "receiving",
    "agent-owes",
    "awaiting-ack",
)


class UndeclaredTransitionError(RuntimeError):
    """A move the table does not name.

    Raised rather than absorbed: the alternative is a channel that quietly stays
    where it was, which renders as a working indicator for a state this model
    does not have.
    """

    def __init__(self, layer: str, state: str, event: str) -> None:
        super().__init__(f"the {layer} layer has no move from {state!r} on {event!r}")


def transport_step(state: str, event: str) -> str:
    """Where the transport goes from here."""
    moves = TRANSPORT_TABLE.get(state, {})
    if event not in moves:
        raise UndeclaredTransitionError("transport", state, event)
    return moves[event]


def protocol_step(state: str, event: str) -> str:
    """Where one channel's protocol state goes from here."""
    moves = PROTOCOL_TABLE.get(state, {})
    if event not in moves:
        raise UndeclaredTransitionError("protocol", state, event)
    return moves[event]


@dataclass(frozen=True)
class ChannelView:
    """One channel as the diagnostic surface shows it: both layers, named.

    The connection is the transport's, so every view carries the same one. That
    is the claim rather than an omission -- a page reaches one backend over one
    origin, and a per-channel connection state would be four names for one fact.
    """

    channel: str
    connection: str
    protocol: str

    @property
    def severity(self) -> tuple[int, int]:
        return (
            TRANSPORT_SEVERITY.index(self.connection),
            PROTOCOL_SEVERITY.index(self.protocol),
        )


def worst(views: Iterable[ChannelView]) -> ChannelView | None:
    """The channel the amalgamated indicator shows.

    Worst-state-wins across every channel, the wire ranked before the
    conversation: a transport that is down is the human's problem whatever any
    channel was in the middle of saying.
    """
    ranked = sorted(views, key=lambda view: view.severity)
    return ranked[-1] if ranked else None


class Channels:
    """Every channel's state, in one place, moved one channel at a time.

    The map channel exists from the start because the board is always a
    conversation someone could be having; thread channels are opened as the
    session grows one.
    """

    def __init__(self, channels: Sequence[str] = (MAP_CHANNEL,)) -> None:
        self.transport = TRANSPORT_STATES[0]
        self._protocol: dict[str, str] = {}
        for channel in channels:
            self.open_channel(channel)

    def open_channel(self, channel: str) -> None:
        """Note a channel, idle. Opening one that is already known is not a
        reset: a thread the board mentions again has not stopped waiting."""
        self._protocol.setdefault(channel, PROTOCOL_STATES[0])

    def protocol_of(self, channel: str) -> str:
        return self._protocol.get(channel, PROTOCOL_STATES[0])

    def on_transport(self, event: str) -> None:
        """The wire moved. Every channel reports the new connection state and no
        channel's protocol state moves, because nothing was said."""
        self.transport = transport_step(self.transport, event)

    def on_channel(self, channel: str, event: str) -> None:
        """One channel's own traffic, addressed to it alone."""
        self.open_channel(channel)
        self._protocol[channel] = protocol_step(self._protocol[channel], event)

    def views(self) -> list[ChannelView]:
        """Every channel, both layers, map first and threads in the order they
        were opened -- which is the order the diagnostic lists them in."""
        return [
            ChannelView(channel=channel, connection=self.transport, protocol=protocol)
            for channel, protocol in self._protocol.items()
        ]

    def worst(self) -> ChannelView | None:
        return worst(self.views())
