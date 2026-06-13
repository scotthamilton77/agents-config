"""Interactive prune flow — confirm and perform orphan deletion.

Port of the bash ``prune_orphans`` (``scripts/install.sh:1602-1687``). Takes the
orphan list from ``core/prune.py`` and an ``IOPort``, drives the three-way
prompt (all / one-by-one / cancel) and the one-by-one per-item drill-down, and
backs up then deletes every confirmed orphan. ALL prompts route through the
``IOPort`` so the flow is unit-testable through ``ScriptedIO``.

Deletion is always preceded by a path-aware backup (``core/backup.py``) so
``--yes`` is never a data-loss path — the bash ``_delete_orphan`` likewise calls
``backup`` before ``rm -rf`` (``scripts/install.sh:1580-1588``).

Guard ordering mirrors the bash function exactly: the non-interactive guard runs
FIRST, before the empty-orphan fast path, so ``--prune-only`` without auth
hard-fails regardless of orphan count (``scripts/install.sh:1602-1615``).
``--dry-run`` and ``--yes`` are themselves the authorization, so they are exempt.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from installer.core.backup import back_up, new_timestamp
from installer.core.model import Counters

if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.io_port import IOPort
    from installer.core.model import Orphan

# Three-way prompt answer tokens (bash ``[a]ll, [o]ne-by-one, [c]ancel``).
_ALL = "a"
_ONE_BY_ONE = "o"
_CANCEL = "c"


class PruneAbortedError(RuntimeError):
    """Raised when a non-interactive ``--prune-only`` run lacks authorization.

    Mirrors the bash hard-fail (``scripts/install.sh:1608-1610``): the caller
    asked for an action (prune-only) with no way to confirm it and no ``--yes``
    / ``--dry-run`` standing in for consent, so the intent cannot be fulfilled.
    """


def run_prune(
    orphans: Sequence[Orphan],
    *,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    prune_only: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Confirm and delete orphans; return a ``Counters`` of the work done.

    Guard order (bash ``prune_orphans``):

    1. **Non-interactive guard first.** When the session is non-interactive and
       neither ``dry_run`` nor ``auto_yes`` supplies consent: a ``prune_only``
       run raises ``PruneAbortedError`` (action demanded, no auth); a plain
       ``--prune`` run warns and returns having deleted nothing.
    2. **Empty fast path.** No orphans -> return immediately.
    3. **Display** the orphan list.
    4. **dry_run** -> display only, no deletes.
    5. **auto_yes** -> back up + delete every orphan, no prompt.
    6. **Interactive** -> three-way prompt; ``all`` deletes everything,
       ``one-by-one`` drills down per item (``quit`` stops the rest), ``cancel``
       deletes nothing.

    ``timestamp`` is the ``YYYYMMDD-HHMMSS`` backup suffix; injected so tests
    assert exact backup names, it defaults to the current local time. It is only
    resolved on paths that may delete, so a ``dry_run`` never computes one; on a
    deleting path a malformed value raises ``ValueError`` from ``back_up`` (the
    validation boundary) before any backup is written.
    """
    if not io.is_interactive() and not dry_run and not auto_yes:
        if prune_only:
            io.err("prune-only requires --yes or --dry-run in non-interactive mode")
            raise PruneAbortedError("prune-only requires --yes or --dry-run")  # noqa: TRY003  # single call-site
        io.warn("prune phase requires confirmation, skipping")
        return Counters()

    if not orphans:
        io.info("No orphans detected.")
        return Counters()

    _display(orphans, io)

    if dry_run:
        io.info(f"Dry-run: {len(orphans)} orphan(s) listed above; no changes made.")
        return Counters()

    # Resolve the backup suffix only on paths that may actually delete; the
    # dry-run early-return above never needs it. ``back_up`` validates the value
    # at the filesystem boundary, so no explicit ``valid_timestamp`` check here.
    ts = timestamp if timestamp is not None else new_timestamp()

    if auto_yes:
        return _delete_all(orphans, io=io, timestamp=ts)

    return _prompt_and_delete(orphans, io=io, timestamp=ts)


def _prompt_and_delete(orphans: Sequence[Orphan], *, io: IOPort, timestamp: str) -> Counters:
    """Three-way prompt then act (bash interactive branch, install.sh:1636-1686)."""
    choice = io.confirm_three_way(
        "Action? [a]ll, [o]ne-by-one, [c]ancel",
        choices=(_ALL, _ONE_BY_ONE, _CANCEL),
        default=_CANCEL,
    )
    if choice == _ALL:
        return _delete_all(orphans, io=io, timestamp=timestamp)
    if choice == _ONE_BY_ONE:
        return _delete_one_by_one(orphans, io=io, timestamp=timestamp)
    io.info("Cancelled. No changes made.")
    return Counters()


def _delete_one_by_one(orphans: Sequence[Orphan], *, io: IOPort, timestamp: str) -> Counters:
    """Per-item drill-down (bash ``o|O`` branch, install.sh:1650-1676).

    A per-item ``quit`` leaves every un-answered orphan in place; an orphan the
    user did not keep (decision ``True``) is deleted. Orphans the user never
    reached (the dict is incomplete on quit) are skipped.
    """
    result = io.confirm_per_item(
        "Delete each orphan? [y/N/q]",
        items=[str(o.path) for o in orphans],
    )
    counters = Counters()
    for orphan in orphans:
        if result.decisions.get(str(orphan.path)):
            _back_up_and_delete(orphan, io=io, timestamp=timestamp, counters=counters)
    if result.quit:
        io.info("Quit per-item loop; remaining orphans left in place.")
    return counters


def _delete_all(orphans: Sequence[Orphan], *, io: IOPort, timestamp: str) -> Counters:
    """Back up + delete every orphan (bash ``_delete_all_orphans``, install.sh:1592-1600)."""
    counters = Counters()
    for orphan in orphans:
        _back_up_and_delete(orphan, io=io, timestamp=timestamp, counters=counters)
    io.ok(f"Pruned {counters.pruned} orphan(s).")
    return counters


def _back_up_and_delete(orphan: Orphan, *, io: IOPort, timestamp: str, counters: Counters) -> None:
    """Back up an orphan, then remove it (bash ``_delete_orphan``, install.sh:1580-1588).

    Backup ALWAYS precedes deletion so the original bytes are recoverable even
    if the delete is interrupted.
    """
    dest = back_up(orphan.path, timestamp)
    counters.backed_up += 1
    io.info(f"Backed up {orphan.path.name} -> {dest.parent.name}/{dest.name}", verbose=True)
    # A symlink (to a dir OR a file) is removed with ``unlink``, which deletes
    # the link itself, never its target. ``rmtree`` is reserved for real
    # directories: ``Path.is_dir()`` follows symlinks, so a dir-symlink would
    # otherwise reach ``rmtree`` — which refuses a symlink and raises OSError.
    # The bash original used ``rm -rf``, which handles symlinks fine; this keeps
    # port parity.
    if orphan.path.is_symlink() or not orphan.path.is_dir():
        orphan.path.unlink()
    else:
        shutil.rmtree(orphan.path)
    counters.pruned += 1


def _display(orphans: Sequence[Orphan], io: IOPort) -> None:
    """Print the orphan list grouped by tool then namespace (bash ``_display_orphans``)."""
    io.header(f"Orphans detected ({len(orphans)} total)")
    last_tool = last_ns = ""
    for orphan in orphans:
        if orphan.tool != last_tool:
            io.header(orphan.tool)
            last_tool = orphan.tool
            last_ns = ""
        if orphan.namespace != last_ns:
            io.info(f"  {orphan.namespace}/")
            last_ns = orphan.namespace
        io.info(f"    [{orphan.kind}] {orphan.path}")
