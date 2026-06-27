"""Single-writer advisory lock for the install -> prune -> receipt-write section.

An exclusive, non-blocking ``fcntl.flock`` over a lock file. A second concurrent
installer fails fast with ``ReceiptLockBusy`` instead of interleaving writes and
corrupting the receipt. flock is per open-file-description, so even two runs in
one process (the test) conflict.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class ReceiptLockBusy(RuntimeError):  # noqa: N818  # "Busy" is the contract name imported by callers/tests; an Error suffix would misname the condition
    """Another installer holds the lock; this run cannot safely proceed."""


@contextmanager
def receipt_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``lock_path`` for the duration.

    Non-blocking: if another process (or open fd) already holds it, raise
    ``ReceiptLockBusy`` immediately rather than waiting. The lock file is created
    if absent and never removed (its presence is harmless; the lock is the flock
    state, not the file)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("w")  # fd must outlive the yield; closed in finally
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ReceiptLockBusy("another install is in progress") from exc  # noqa: TRY003  # single call-site; message is the contract
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
