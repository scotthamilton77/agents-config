"""Non-interactive consent guard (G.7).

The Python installer makes a destructive run impossible to start without a way to
confirm it: when stdin is not a TTY (no prompt can be answered) and neither
``--yes`` nor ``--dry-run`` waives confirmation, the run hard-fails up front with
a clear error rather than silently overwriting files.

The non-interactive guard is an explicit up-front precondition: a scripted
caller learns immediately that it must pass ``--yes`` rather than discovering
it mid-run when a prompt cannot be answered. ``--yes`` is the intended
scripted-install path; ``--dry-run`` writes nothing, so both waive the guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.core.io_port import IOPort


class ConsentRequiredError(RuntimeError):
    """Raised when a destructive run cannot obtain interactive consent.

    The session is non-interactive and neither ``--yes`` nor ``--dry-run`` was
    supplied, so there is no way to confirm the writes — the run must not
    proceed silently.
    """


def require_consent(io: IOPort, *, dry_run: bool, auto_yes: bool) -> None:
    """Raise ``ConsentRequiredError`` if a destructive run lacks any consent path.

    Returns ``None`` (no-op) when the session is interactive, or when ``dry_run``
    / ``auto_yes`` waives the requirement. Raises only in the genuinely unsafe
    case: non-interactive AND not dry-run AND not auto-yes.
    """
    if io.is_interactive() or dry_run or auto_yes:
        return
    io.err("non-interactive run requires --yes or --dry-run")
    raise ConsentRequiredError("non-interactive run requires --yes or --dry-run")  # noqa: TRY003  # single call-site
