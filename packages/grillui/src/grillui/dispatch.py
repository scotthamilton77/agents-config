"""Assembling an agent's dispatch context, and recording what it was given.

Dispatch context crosses whole. The grill-master is handed image 2 in full,
byte-complete, and there is no elision path in v1 and no budget that can create
one: a projector that trimmed settled decisions out of a dispatch would lose
human decisions silently, and nothing downstream could tell -- the agent would
simply proceed without a decision the human made minutes earlier.

A thread agent is handed the same board and its own thread's turns, with every
other live thread reduced to a stub. That is not elision: no decision, no
answer and no history is dropped, and what a thread agent is not given is the
running conversation of a thread it is not having. Which agent a dispatch is
for is decided here, from the channel, rather than passed in -- a caller free
to name the agent is a caller free to name the wrong one, and a thread
dispatch labelled `grill-master` is a map mutation waiting to be authored by
the wrong context.

One thread is not about the plan at all: the one anchored to no decision, where
the human asks how the board itself works. Its dispatch carries the reference
material the orchestrator shipped, and no other dispatch does -- an agent
grilling a design has no use for it and would only be paying for it.

That guarantee is worth nothing unasserted, so it is checked on the way out and
the check is what the completeness test reads: every context is recorded under
the session directory's `dispatches/`, one file per dispatch, and a context
that would omit any part of what it owes raises instead of being written. The
omission is treated as data corruption, because that is what it is.

Invoking an agent is not here. This module answers what a dispatch carries, not
when one happens.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from grillui.projector import conclusion_of, fold, project_thread, whole_board
from grillui.schemas import (
    MAP_CHANNEL,
    SESSION_START_KIND,
    DispatchContext,
    ThreadConclusion,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import Image2, LogEntry, SupersedeConflict, ThreadProjection

DISPATCH_DIR = "dispatches"
GRILL_MASTER = "grill-master"
THREAD_AGENT = "thread-agent"


def agent_for(channel: str) -> str:
    """Whose context a channel's turns belong to.

    The map is the grill-master's and every thread is its own agent's, which is
    the whole of the rule: a channel is a context, and the two never merge.
    """
    return GRILL_MASTER if channel == MAP_CHANNEL else THREAD_AGENT


class DispatchIncompleteError(RuntimeError):
    """A dispatch context that does not carry the whole of its owed projection.

    Raised rather than truncated: an agent given a partial image 2 reasons from
    a board the human did not leave it, and no receipt, log entry or later read
    would reveal which part went missing.
    """

    def __init__(self) -> None:
        super().__init__("dispatch context omits part of image 2; the projection crosses whole")


def assemble(
    image: Image2,
    *,
    channel: str = MAP_CHANNEL,
    concluding: str | None = None,
    conflict: SupersedeConflict | None = None,
    reassess: bool = False,
    help_reference: str | None = None,
) -> str:
    """One dispatch context, serialised, carrying the whole of what it owes.

    `concluding` names a thread whose conclusion this dispatch is being sent to
    route. Its text is read out of the same image the context carries, so what
    the grill-master is told the thread concluded and what the board says it
    concluded are one fact folded once.

    `conflict` and `reassess` are the two turns nobody spoke to start: a
    withdrawal the human got in front of, and the map doctor. Each says so in
    the context, because the board alone does not -- a turn left to infer why it
    was called would be inferring it from a board that looks unchanged.

    `help_reference` is the material the orchestrator shipped about driving the
    board. It is the caller's to hand in rather than this module's to look up,
    for the same reason the agent is not: a context is assembled from what it
    was given, and reaching back into the log for one field would give this
    function a second source of truth to disagree with.

    The pending queue rides inside the image either way, which is what makes
    every one of these dispatches carry the queue as of the moment it was folded.
    """
    board = whole_board(image) if channel == MAP_CHANNEL else project_thread(image, channel)
    context = DispatchContext(
        agent=agent_for(channel),
        channel=channel,
        epoch=image.epoch,
        seq=image.seq,
        image2=board,
        conclusion=_conclusion(image, concluding),
        conflict=conflict,
        reassess=reassess,
        help_reference=help_reference,
    )
    recorded = context.model_dump_json()
    # The map dispatch is checked against the source image, not the projection
    # it was assembled through: a projection that dropped a field on the way in
    # would vouch for its own output. A thread dispatch reduces by design, so
    # its own projection is the only whole it owes.
    verify_complete(recorded, image if channel == MAP_CHANNEL else board)
    return recorded


def _conclusion(image: Image2, concluding: str | None) -> ThreadConclusion | None:
    if concluding is None:
        return None
    thread = next((one for one in image.threads if one.id == concluding), None)
    return ThreadConclusion(
        thread=concluding, text="" if thread is None else conclusion_of(thread) or ""
    )


def verify_complete(recorded: str, image: Image2 | ThreadProjection) -> None:
    """Refuse a context that does not carry image 2 byte for byte.

    Comparing against the image the context was assembled from is what makes
    this a tripwire rather than a restatement: anything that drops, reorders or
    rewrites a field on the way in fails here, including every settled
    decision's id and its answer text, which travel inside those same bytes.
    """
    if image.model_dump_json() not in recorded:
        raise DispatchIncompleteError


def record_dispatch(
    log: SessionLog,
    *,
    channel: str = MAP_CHANNEL,
    concluding: str | None = None,
    conflict: SupersedeConflict | None = None,
    reassess: bool = False,
) -> Path:
    """Fold at dispatch time, assemble, and record what the agent was given.

    The recorded file is the completeness check's evidence: it is what the
    agent got, not a reconstruction of what it should have got -- including the
    pending queue, which is folded here and not read from anything cached.
    """
    entries = log.entries()
    image = fold(log.epoch, entries)
    recorded = assemble(
        image,
        channel=channel,
        concluding=concluding,
        conflict=conflict,
        reassess=reassess,
        help_reference=help_reference(entries, image, channel),
    )
    directory = log.directory / DISPATCH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return _claim_and_write(directory, recorded)


def help_reference(entries: Sequence[LogEntry], image: Image2, channel: str) -> str | None:
    """The board's own reference material, for the one channel that is about it.

    A thread anchored to no decision is the human asking about the tool rather
    than about the plan, and it is the only channel this material is handed to:
    on a decision's thread or on the map it would be context spent on a
    question nobody is asking. The material comes out of the log's opening
    entry, like every other thing the briefing said -- the handoff file has no
    authority once the session is under way, so a resumed session and a fresh
    one prime that thread identically.
    """
    if channel == MAP_CHANNEL:
        return None
    thread = next((one for one in image.threads if one.id == channel), None)
    if thread is None or thread.decision is not None:
        return None
    opening = next((entry for entry in entries if entry.kind == SESSION_START_KIND), None)
    reference = None if opening is None else opening.payload.get("help_reference")
    return reference if isinstance(reference, str) and reference else None


def _claim_and_write(directory: Path, recorded: str) -> Path:
    """Dispatches are numbered in the order they were recorded, so the audit
    surface reads in dispatch order. The channel lives inside the file rather
    than in its name, since a thread id is the page's string and not
    necessarily a filename.

    The number is claimed with O_EXCL, so two dispatches racing — thread
    dispatches run concurrently by design — each land on their own file rather
    than one silently overwriting the other's audit record."""
    index = len(list(directory.glob("*.json"))) + 1
    while True:
        path = directory / f"{index:04d}.json"
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            index += 1
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(recorded)
        return path
