"""The board endpoints.

One authority, however many routes reach it. The status check is answered from memory and opens no
file, so a page may ask it as often as it likes whatever the log has grown to;
every other read folds the log the process already holds. The single write route
takes a batch under one epoch and answers with one typed receipt per event, in
submission order -- there is no acknowledgement here that does not say what
happened.

A client presenting a stale epoch is told so rather than served: refused on write
with an `epoch mismatch` receipt naming both epochs, and refused on read with a
409, so it re-reads state instead of guessing.

Beside the board routes sit two controls, and what makes them controls is the
same thing in both cases: they write nothing into the record, and their state is
a property of this process rather than of the log. The map doctor is not a kind
on the write route because that vocabulary is closed and a control that
reassesses everything is not something an agent says. The window claim is not
one either, and for a stronger reason -- which window is driving a session is not
part of the session, and a log that carried it would say something about the
browser in a record that is otherwise only about the grilling.

The surface itself is served from here too, off the package's own bytes. It is
a program this process hands out rather than an asset anything installs, so a
page and the backend it talks to are always the same build -- and the page is
reached on the same origin as the routes it reads, which is what lets it name
them by path alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from grillui.capture import default_summary
from grillui.claim import Claim
from grillui.lane import Lane
from grillui.persistence import project_and_persist
from grillui.projector import fold, to_image1
from grillui.schemas import (
    SESSION_END_KIND,
    BatchWrite,
    ClaimRequest,
    ClaimState,
    DoctorState,
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

PAGE = Path(__file__).parent / "page" / "index.html"


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
    claim = Claim(log.directory)

    def require_epoch(presented: str) -> None:
        if presented != log.epoch:
            raise HTTPException(
                status_code=STALE_EPOCH_STATUS,
                detail=f"server epoch is {log.epoch!r}, presented epoch was {presented!r}",
            )

    @app.get("/", include_in_schema=False)
    def read_page() -> FileResponse:
        """The surface, from this package's own bytes.

        Serving it here rather than shipping it as an installed asset is what
        keeps a page and the protocol it speaks one version: there is no copy
        on disk that a backend restart can leave behind.
        """
        return FileResponse(PAGE, media_type="text/html")

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

    @app.get("/doctor")
    def read_doctor() -> DoctorState:
        """Whether the board is frozen against a reassessment in flight.

        Answered from memory like the status check, because the page asks it to
        decide whether to render its modal rather than to learn anything about
        the board.
        """
        return DoctorState(outstanding=lane.doctor_outstanding)

    @app.post("/doctor")
    def call_doctor() -> DoctorState:
        """Send the grill-master over the whole board and the pending queue.

        `outstanding` is the answer to what the page does next, not whether this
        call dispatched: a call landing while a reassessment is already in
        flight dispatches nothing and still answers true, because the board is
        still frozen. False means nothing is composing at all -- a session with
        no tier attached. The board is the page's to hold immutable while it is
        true: refusing a write here would need a rejection reason, and that
        vocabulary is closed.
        """
        lane.call_doctor()
        return DoctorState(outstanding=lane.doctor_outstanding)

    @app.post("/claim")
    def present_claim(request: ClaimRequest) -> ClaimState:
        """Which window this session belongs to.

        A control, not a board event: it appends nothing, it is in no image, and
        a session's record reads the same whoever was driving it. It is a POST
        rather than a read because presenting a name is what acquires the claim
        -- the same call is the first claim, the reload, the reconnect and the
        take-over, so there is one answer to keep true rather than four.

        Nothing here refuses a write. A window that has been superseded stops
        writing because it is told to and shows the human why; the log does not
        police who wrote to it, and making it do so would put session control
        inside the record it is deliberately outside of.
        """
        return ClaimState(
            token=claim.token,
            state=claim.present(request.holder, takeover=request.takeover),
        )

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
