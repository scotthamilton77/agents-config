"""Writing the images to disk: the only step in the projection path that does I/O.

The fold is pure, so it has nothing to fail on. Everything that can fail lives
here, downstream of it, and the whole point of the split is that a failure here
reaches neither the log nor the next event: the entry is already durable and
already has a receipt by the time anything is projected.

The files this writes are derived caches. Nothing reads them back -- a rebuild
re-folds the log -- so a stale or missing image costs a rewrite, never a lost
decision.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from grillui.log import IMAGE1_FILE, IMAGE2_FILE
from grillui.projector import fold, to_image1
from grillui.schemas import STATUS_PHASE_ERROR

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog
    from grillui.schemas import Image2


def write_images(directory: Path, image: Image2) -> None:
    """Persist both images for one folded position."""
    (directory / IMAGE2_FILE).write_text(image.model_dump_json(), encoding="utf-8")
    (directory / IMAGE1_FILE).write_text(to_image1(image).model_dump_json(), encoding="utf-8")


def project_and_persist(log: SessionLog) -> None:
    """Fold the log and write the images, at batch granularity after an append.

    Every failure is caught, whatever it is. A projection error surfaces as an
    error on the status lane and leaves the log intact; it never takes the
    session down and never blocks acceptance of the next event. Narrowing this
    to the exception types known today would mean the first unforeseen one ends
    a grilling the human is in the middle of.
    """
    try:
        write_images(log.directory, fold(log.epoch, log.entries()))
    except Exception as error:
        try:
            log.emit_status(STATUS_PHASE_ERROR, f"projection failed: {error!r}")
        except Exception:
            # The lane itself can be down (disk full takes the log with it).
            # The batch is already accepted and its receipts already computed,
            # so nothing may escape here and turn acceptance into a 500 --
            # stderr is the last surface left.
            _LOGGER.error(
                "status lane unavailable while reporting projection failure %r",
                error,
                exc_info=True,
            )
