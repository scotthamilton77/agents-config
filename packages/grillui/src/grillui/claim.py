"""One main window per session, arbitrated here.

Two main windows over one session is not a cosmetic problem: both hold a board,
both answer decisions on it, and the human ends up looking at one window while
the agent is answering what they said in the other. So the backend, which is the
only thing both windows agree on, decides which one is the session's.

**A claim is presented, never assigned.** The window names itself, and the same
name presented again is the same window -- which is what makes a reload free.
The name lives in the window's own session storage, so it survives a reload of
that window and is not there for a second window to find.

**The token names the session, not the tenure.** It is derived from the session
directory rather than minted per process, because the things scoped to it --
read-state markers against log entries -- are as durable as the log is. An epoch
would throw them away on every restart, and the entries they name would still be
there.

**The claim itself is this process's and nothing else's.** It is not written
down, and a restart starts the arbitration over. The claim exists to stop two
*live* windows writing to one *live* backend; a backend that is gone has no
windows to arbitrate between, and a claim on disk would outlive the thing it
described and lock a human out of their own session after a crash.

**Nothing here reaches the log.** Claiming, refusing and taking over append no
entry and are visible in no board: the log is the record of the grilling, and
which window is driving it is not part of that record.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# What the backend answers a presented claim with. Ordered, because the page
# indexes this list rather than restating the words.
#
# `refused` and `superseded` are separate answers because they are separate
# situations, and the human's next move differs: a window that never held the
# session is looking at one somebody else opened, while a superseded window held
# it and was taken over -- it has a board on screen that it must stop showing.
CLAIM_STATES: tuple[str, ...] = ("granted", "refused", "superseded")

GRANTED, REFUSED, SUPERSEDED = CLAIM_STATES

TOKEN_LENGTH = 16


def session_token(directory: Path) -> str:
    """This session's own id, derived rather than stored.

    Derived, because a stored token is a file that can be absent, unwritable or
    left behind by something else, and every one of those is a start-up failure
    for a value that is only ever an identity. The directory already *is* the
    session's identity; this is that identity in a form a storage key can carry.
    """
    return sha256(str(directory.resolve()).encode("utf-8")).hexdigest()[:TOKEN_LENGTH]


class Claim:
    """Which window is this session's, and what to tell the ones that are not.

    One claim, held by at most one name at a time. Every window presents its own
    name on a cadence, so the answer is the same question asked repeatedly rather
    than a session anything has to keep alive with a heartbeat: a window that
    stops asking is not evicted, and a window that is gone is recovered from by
    the human taking over rather than by a timeout guessing on their behalf.
    """

    def __init__(self, directory: Path) -> None:
        self.token = session_token(directory)
        self._holder: str | None = None
        # The names a take-over has displaced. Kept so that a window that lost
        # the session is told it *lost* it rather than that somebody else has
        # it -- the second reads as a mistake, and the first is what happened.
        self._revoked: set[str] = set()

    def present(self, holder: str, *, takeover: bool = False) -> str:
        """One window says who it is; this is what it is told.

        Presenting is idempotent and is both the acquire and the check: the
        holder re-presenting is granted again, which is what a reload and a
        reconnect both are. An unheld session is granted to whoever asks, so a
        restarted backend hands the session back to the window still asking for
        it without the human doing anything.

        A take-over is the human's explicit gesture and is never inferred: it
        displaces the current holder, which is why the alternative -- expiring a
        claim on silence -- is not offered. Silence is what a window that is
        merely slow looks like.
        """
        if self._holder is None or self._holder == holder or takeover:
            if self._holder is not None and self._holder != holder:
                self._revoked.add(self._holder)
            self._revoked.discard(holder)
            self._holder = holder
            return GRANTED
        return SUPERSEDED if holder in self._revoked else REFUSED
