"""Assembling an agent's dispatch context, and recording what it was given.

Dispatch context crosses whole. The grill-master is handed image 2 in full,
byte-complete, and there is no elision path in v1 and no budget that can create
one: a projector that trimmed settled decisions out of a dispatch would lose
human decisions silently, and nothing downstream could tell -- the agent would
simply proceed without a decision the human made minutes earlier.

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

from grillui.projector import fold
from grillui.schemas import MAP_CHANNEL, DispatchContext

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import Image2

DISPATCH_DIR = "dispatches"
GRILL_MASTER = "grill-master"


class DispatchIncompleteError(RuntimeError):
    """A dispatch context that does not carry the whole of its owed projection.

    Raised rather than truncated: an agent given a partial image 2 reasons from
    a board the human did not leave it, and no receipt, log entry or later read
    would reveal which part went missing.
    """

    def __init__(self) -> None:
        super().__init__("dispatch context omits part of image 2; the projection crosses whole")


def assemble(image: Image2, *, agent: str = GRILL_MASTER, channel: str = MAP_CHANNEL) -> str:
    """One dispatch context, serialised, carrying image 2 whole."""
    context = DispatchContext(
        agent=agent, channel=channel, epoch=image.epoch, seq=image.seq, image2=image
    )
    recorded = context.model_dump_json()
    verify_complete(recorded, image)
    return recorded


def verify_complete(recorded: str, image: Image2) -> None:
    """Refuse a context that does not carry image 2 byte for byte.

    Comparing against the image the context was assembled from is what makes
    this a tripwire rather than a restatement: anything that drops, reorders or
    rewrites a field on the way in fails here, including every settled
    decision's id and its answer text, which travel inside those same bytes.
    """
    if image.model_dump_json() not in recorded:
        raise DispatchIncompleteError


def record_dispatch(
    log: SessionLog, *, agent: str = GRILL_MASTER, channel: str = MAP_CHANNEL
) -> Path:
    """Fold at dispatch time, assemble, and record what the agent was given.

    The recorded file is the completeness check's evidence: it is what the
    agent got, not a reconstruction of what it should have got.
    """
    image = fold(log.epoch, log.entries())
    recorded = assemble(image, agent=agent, channel=channel)
    directory = log.directory / DISPATCH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return _claim_and_write(directory, recorded)


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
