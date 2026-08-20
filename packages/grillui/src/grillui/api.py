"""The board endpoints.

Six routes, one authority. The status check is answered from memory and opens no
file, so a page may ask it as often as it likes whatever the log has grown to;
every other read folds the log the process already holds. The single write route
takes a batch under one epoch and answers with one typed receipt per event, in
submission order -- there is no acknowledgement here that does not say what
happened.

A client presenting a stale epoch is told so rather than served: refused on write
with an `epoch mismatch` receipt naming both epochs, and refused on read with a
409, so it re-reads state instead of guessing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException

from grillui.capture import default_summary
from grillui.lane import Lane
from grillui.persistence import project_and_persist
from grillui.projector import fold, to_image1
from grillui.schemas import (
    SESSION_END_KIND,
    BatchWrite,
    Image1,
    Image2,
    Receipt,
    SessionStatus,
    StateRead,
    UpdateRead,
    batch_payload_problem,
)
from grillui.session import end_session

if TYPE_CHECKING:
    from collections.abc import Sequence

    from grillui.capture import Summarizer
    from grillui.lane import TurnDriver
    from grillui.log import SessionLog
    from grillui.schemas import EventSubmission

STALE_EPOCH_STATUS = 409
MALFORMED_PAYLOAD_STATUS = 422


def create_app(
    log: SessionLog,
    driver: TurnDriver | None = None,
    *,
    expert: TurnDriver | None = None,
    summarize: Summarizer = default_summary,
) -> FastAPI:
    """Bind the board endpoints to one session log, and the lane to its tiers.

    The driver is optional because a backend with no tier configured is a real
    state, not a broken one: the board still accepts everything it would
    otherwise, and nothing pretends a reply is coming.

    `expert` is where a channel the human has escalated takes its turns. It is
    the session's tier rather than a channel's: which channels are on it is read
    off the human's own gestures, one channel at a time, so one escalation never
    moves another channel.

    `summarize` is the seam capture writes the terminal result's prose through.
    Its default builds the briefing from the structured parts, so ending a
    session never waits on a model being reachable.
    """
    app = FastAPI(title="grillui session backend")
    lane = Lane(log, driver, expert)

    def require_epoch(presented: str) -> None:
        if presented != log.epoch:
            raise HTTPException(
                status_code=STALE_EPOCH_STATUS,
                detail=f"server epoch is {log.epoch!r}, presented epoch was {presented!r}",
            )

    @app.get("/status")
    def read_status() -> SessionStatus:
        """Epoch and position, and nothing that costs a file read."""
        return SessionStatus(epoch=log.epoch, seq=log.seq)

    @app.get("/state")
    def read_state() -> StateRead:
        """What a page or an agent reads after any doubt, so that reconnecting
        asserts nothing."""
        return StateRead(epoch=log.epoch, seq=log.seq, image1=to_image1(_image(log)))

    @app.get("/updates")
    def read_updates(epoch: str, cursor: int = 0) -> UpdateRead:
        require_epoch(epoch)
        return UpdateRead(epoch=log.epoch, seq=log.seq, entries=log.entries_after(cursor))

    @app.get("/image1")
    def read_image1() -> Image1:
        return to_image1(_image(log))

    @app.get("/image2")
    def read_image2() -> Image2:
        return _image(log)

    @app.post("/events")
    def write_events(batch: BatchWrite) -> list[Receipt]:
        """The receipts are settled before anything is projected: the entries
        they name are durable, so persisting the images is downstream work that
        a caller is never made to wait on the success of. Nor is the caller made
        to wait on an agent -- the lane writes its entries under the same lock as
        the append and schedules the turn elsewhere, so the human's write returns
        at the speed of the disk rather than the speed of a model.

        A payload the closed rejection vocabulary has no word for is refused
        here, before anything is appended and for the batch whole -- the same
        answer an unknown envelope field gets. Refusing part-way through would
        leave entries in the log that no caller ever got a receipt for, which is
        the one failure this protocol is built to make impossible."""
        malformed = batch_payload_problem(batch.events)
        if malformed is not None:
            raise HTTPException(status_code=MALFORMED_PAYLOAD_STATUS, detail=malformed)
        receipts, _turns = lane.accept(batch.events, batch.epoch)
        if any(receipt.status == "accepted" for receipt in receipts):
            project_and_persist(log)
        if _ended(batch.events, receipts):
            # Downstream of the append, like the images: the terminal entry is
            # already durable, so a capture that fails costs the result file
            # and leaves the record of the ending intact.
            end_session(log, summarize=summarize)
        return receipts

    return app


def _ended(events: Sequence[EventSubmission], receipts: Sequence[Receipt]) -> bool:
    """Whether this batch is the one that ended the session.

    Judged on the receipts rather than on the submissions: a `session-end` an
    agent sent is refused, and capturing on it would write a terminal result for
    a session the human has not finished.
    """
    return any(
        event.kind == SESSION_END_KIND and receipt.status == "accepted"
        for event, receipt in zip(events, receipts, strict=True)
    )


def _image(log: SessionLog) -> Image2:
    return fold(log.epoch, log.entries())
