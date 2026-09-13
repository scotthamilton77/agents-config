"""Writing the images to disk: the only step in the projection path that does I/O.

The replay is pure, so it has nothing to fail on. Everything that can fail lives
here, downstream of it, and the whole point of the split is that a failure here
reaches neither the log nor the next event: the entry is already durable and
already has a receipt by the time anything is projected.

The files this writes are derived caches. Nothing reads them back -- a rebuild
replays the log again -- so a stale or missing image costs a rewrite, never a lost
decision.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from grillui.log import IMAGE1_FILE, IMAGE2_FILE
from grillui.projector import replay, to_image1
from grillui.schemas import STATUS_PHASE_DOWNSTREAM_FAILED

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import Image2


def write_images(directory: Path, image: Image2) -> None:
    """Persist both images for one replayed position."""
    (directory / IMAGE2_FILE).write_text(image.model_dump_json(), encoding="utf-8")
    (directory / IMAGE1_FILE).write_text(to_image1(image).model_dump_json(), encoding="utf-8")


def project_and_persist(log: SessionLog) -> None:
    """Replay the log and write the images, at batch granularity after an append.

    Every failure is caught, whatever it is. A projection error surfaces on the
    status lane as a downstream failure and leaves the log intact; it never takes the
    session down and never blocks acceptance of the next event. Narrowing this
    to the exception types known today would mean the first unforeseen one ends
    a grilling the human is in the middle of.
    """
    try:
        write_images(log.directory, replay(log.epoch, log.entries()))
    except Exception as error:
        report_failure(log, "projection failed", error)


def report_failure(log: SessionLog, what: str, error: Exception) -> None:
    """Surface a downstream failure on the status lane without raising.

    Every failure downstream of an accepted append routes through here: the
    entry is already durable and its receipt already computed, so nothing may
    escape and turn acceptance into a 500. It is said in the phase that closes
    no turn, because this failure is owed to no turn and can land while one is
    running. The lane itself can be down -- a full
    disk takes the log with it -- and stderr is the last surface left.
    """
    try:
        log.emit_status(STATUS_PHASE_DOWNSTREAM_FAILED, f"{what}: {error!r}")
    except Exception:
        _LOGGER.error("status lane unavailable while reporting %s %r", what, error, exc_info=True)
