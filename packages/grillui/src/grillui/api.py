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

from grillui.projector import fold, to_image1
from grillui.schemas import (
    BatchWrite,
    Image1,
    Image2,
    Receipt,
    SessionStatus,
    StateRead,
    UpdateRead,
)

if TYPE_CHECKING:
    from grillui.log import SessionLog

STALE_EPOCH_STATUS = 409


def create_app(log: SessionLog) -> FastAPI:
    """Bind the board endpoints to one session log."""
    app = FastAPI(title="grillui session backend")

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
        return log.submit(batch.events, batch.epoch)

    return app


def _image(log: SessionLog) -> Image2:
    return fold(log.epoch, log.entries())
