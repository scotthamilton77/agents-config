"""Interactive prune flow — confirm and perform orphan deletion.

Takes the orphan list from ``core/prune.py`` and an ``IOPort``, drives the
three-way prompt (all / one-by-one / cancel) and the one-by-one per-item
drill-down, and backs up then deletes every confirmed orphan. ALL prompts route
through the ``IOPort`` so the flow is unit-testable through ``ScriptedIO``.

Deletion is always preceded by a path-aware backup (``core/backup.py``) so
``--yes`` is never a data-loss path.

Guard ordering: the non-interactive guard runs FIRST, before the empty-orphan
fast path, so ``--prune-only`` without auth hard-fails regardless of orphan
count. ``--dry-run`` and ``--yes`` are themselves the authorization, so they
are exempt.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from installer.core.backup import back_up, new_timestamp
from installer.core.model import Counters

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import Orphan

# Three-way prompt answer tokens: ``[a]ll, [o]ne-by-one, [c]ancel``.
_ALL = "a"
_ONE_BY_ONE = "o"
_CANCEL = "c"


def _lstat_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    """Filesystem identity of ``path`` for the prune-boundary TOCTOU recheck.

    Returns ``(st_dev, st_ino, st_mtime_ns, st_ctime_ns, st_size)`` — enough to
    detect an unlink-then-recreate even when the OS recycles the freed inode
    number (the times and size still move). ``st_ctime_ns`` (inode-change time)
    is included specifically because it is NOT settable via ``os.utime``, so an
    adversary who restores a forged ``st_mtime_ns`` on the swapped-in file still
    cannot match the recreation's ctime. ``lstat`` does NOT follow symlinks,
    matching how ``unlink``/``rmtree`` below act on the link itself, never its
    target.

    A genuinely-absent path (or one whose parent component is no longer a
    directory) is ``None`` — the "expected gone" sentinel, distinct from any
    real entry. Any other ``OSError`` (e.g. permission) propagates, consistent
    with the destructive ops below not swallowing real errors.
    """
    try:
        st = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)


class PruneAbortedError(RuntimeError):
    """Raised when a non-interactive ``--prune-only`` run lacks authorization.

    The caller asked for an action (prune-only) with no way to confirm it and
    no ``--yes`` / ``--dry-run`` standing in for consent, so the intent cannot
    be fulfilled.
    """


def run_prune(
    orphans: Sequence[Orphan],
    *,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    prune_only: bool = False,
    timestamp: str | None = None,
    removed: set[Path] | None = None,
    revalidate: Callable[[Orphan], bool] | None = None,
) -> dict[str, Counters]:
    """Confirm and delete orphans; return per-target ``Counters`` of the work done.

    The mapping is keyed by ``Orphan.tool`` — each tool or plugin namespace whose
    orphans were pruned gets its own bucket (pruned / backed_up), so the install
    summary can report a plugin pruned outside the active tool set (AC#19).
    Every no-deletion path (guard skip, empty list, dry-run, cancel) returns an
    empty mapping.

    Guard order:

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

    ``revalidate`` (optional) re-checks ownership at the destructive boundary: it
    is called for each orphan immediately before backup/delete, and a ``False``
    return skips that orphan (left in place, not counted, not added to ``removed``
    so the receipt keeps it). This closes the TOCTOU window between the up-front
    hash/type partition and the actual delete — a file edited or a path replaced
    during the interactive confirm prompt is no longer deleted.
    """
    if not io.is_interactive() and not dry_run and not auto_yes:
        if prune_only:
            io.err("prune-only requires --yes or --dry-run in non-interactive mode")
            raise PruneAbortedError("prune-only requires --yes or --dry-run")  # noqa: TRY003  # single call-site
        io.warn("prune phase requires confirmation, skipping")
        return {}

    if not orphans:
        io.info("No orphans detected.")
        return {}

    _display(orphans, io)

    if dry_run:
        io.info(f"Dry-run: {len(orphans)} orphan(s) listed above; no changes made.")
        return {}

    # Resolve the backup suffix only on paths that may actually delete; the
    # dry-run early-return above never needs it. ``back_up`` validates the value
    # at the filesystem boundary, so no explicit ``valid_timestamp`` check here.
    ts = timestamp if timestamp is not None else new_timestamp()

    if auto_yes:
        return _delete_all(orphans, io=io, timestamp=ts, removed=removed, revalidate=revalidate)

    return _prompt_and_delete(orphans, io=io, timestamp=ts, removed=removed, revalidate=revalidate)


def _prompt_and_delete(
    orphans: Sequence[Orphan],
    *,
    io: IOPort,
    timestamp: str,
    removed: set[Path] | None = None,
    revalidate: Callable[[Orphan], bool] | None = None,
) -> dict[str, Counters]:
    """Three-way prompt then act."""
    choice = io.confirm_three_way(
        "Action? [a]ll, [o]ne-by-one, [c]ancel",
        choices=(_ALL, _ONE_BY_ONE, _CANCEL),
        default=_CANCEL,
    )
    if choice == _ALL:
        return _delete_all(
            orphans, io=io, timestamp=timestamp, removed=removed, revalidate=revalidate
        )
    if choice == _ONE_BY_ONE:
        return _delete_one_by_one(
            orphans, io=io, timestamp=timestamp, removed=removed, revalidate=revalidate
        )
    io.info("Cancelled. No changes made.")
    return {}


def _delete_one_by_one(
    orphans: Sequence[Orphan],
    *,
    io: IOPort,
    timestamp: str,
    removed: set[Path] | None = None,
    revalidate: Callable[[Orphan], bool] | None = None,
) -> dict[str, Counters]:
    """Per-item drill-down.

    A per-item ``quit`` leaves every un-answered orphan in place; an orphan the
    user did not keep (decision ``True``) is deleted. Orphans the user never
    reached (the dict is incomplete on quit) are skipped.
    """
    result = io.confirm_per_item(
        "Delete each orphan? [y/N/q]",
        items=[str(o.path) for o in orphans],
    )
    per_tool: dict[str, Counters] = {}
    for orphan in orphans:
        if result.decisions.get(str(orphan.path)):
            _back_up_and_delete(
                orphan,
                io=io,
                timestamp=timestamp,
                per_tool=per_tool,
                removed=removed,
                revalidate=revalidate,
            )
    if result.quit:
        io.info("Quit per-item loop; remaining orphans left in place.")
    return per_tool


def _delete_all(
    orphans: Sequence[Orphan],
    *,
    io: IOPort,
    timestamp: str,
    removed: set[Path] | None = None,
    revalidate: Callable[[Orphan], bool] | None = None,
) -> dict[str, Counters]:
    """Back up + delete every orphan."""
    per_tool: dict[str, Counters] = {}
    for orphan in orphans:
        _back_up_and_delete(
            orphan,
            io=io,
            timestamp=timestamp,
            per_tool=per_tool,
            removed=removed,
            revalidate=revalidate,
        )
    pruned = sum(c.pruned for c in per_tool.values())
    io.ok(f"Pruned {pruned} orphan(s).")
    return per_tool


def _back_up_and_delete(
    orphan: Orphan,
    *,
    io: IOPort,
    timestamp: str,
    per_tool: dict[str, Counters],
    removed: set[Path] | None = None,
    revalidate: Callable[[Orphan], bool] | None = None,
) -> None:
    """Back up an orphan, then remove it.

    ``revalidate`` (when supplied) re-checks ownership at this destructive boundary:
    if it returns ``False`` the orphan drifted since the up-front scan (edited, or
    replaced by a user-owned file/dir during the confirm prompt), so it is left in
    place — not backed up, not deleted, not counted, and NOT added to ``removed``,
    so the receipt keeps the entry and re-evaluates it next run. This is the TOCTOU
    guard for the interactive confirm window.

    Tallies into the ``per_tool[orphan.tool]`` bucket (created on first sight) so
    pruned/backed_up land under the orphan's own tool or plugin namespace.

    Backup precedes deletion so the original bytes are recoverable even if the
    delete is interrupted — but only when there is something to back up. A broken
    symlink (or a path that vanished mid-run) has nothing recoverable: ``exists()``
    follows the dead link to a missing target and returns False, so ``back_up``
    would fall through to ``copy2``/``copytree`` and raise, aborting the whole run.
    Skip the backup for a broken symlink — ``exists()`` returns False on a dead
    link so ``back_up`` would raise — but still remove the link below (``unlink``
    deletes a broken link unconditionally).

    Under receipt-based pruning an orphan can legitimately already be absent on
    disk (the user manually deleted it since the prior install). Deletion is
    tolerant of that: an already-gone path is a harmless no-op, still counted
    ``pruned`` and recorded in ``removed`` so the receipt drops the entry — the
    desired end state (the path is gone) is already achieved.
    """
    # Snapshot the path's filesystem identity BEFORE revalidate inspects it, so the
    # recheck below spans the whole revalidate window (the residual TOCTOU codex
    # flagged: a path swapped between a passing revalidate and the unlink/rmtree would
    # otherwise be backed up then removed).
    identity_before = _lstat_identity(orphan.path)
    if revalidate is not None and not revalidate(orphan):
        # Drifted since the orphan scan (the TOCTOU window of the confirm prompt):
        # leave it in place, do not back up / delete / count, and do not record it
        # in ``removed`` — the receipt keeps it and re-checks next run.
        io.info(
            f"Skipped {orphan.path.name} — changed since the orphan scan; left in place",
            verbose=True,
        )
        return
    # Re-check identity before any backup or delete. Block ONLY when a *different,
    # still-present* object now sits at the path (``identity_after`` is non-None and
    # differs): that is a real replacement swapped in during the revalidate window, and
    # is now the user's — leave it in place (not backed up, not deleted, not counted,
    # not in ``removed``, so the receipt keeps the entry and re-evaluates it next run).
    #
    # A ``None`` ``identity_after`` means the path simply VANISHED (whether absent from
    # the start, or removed mid-window) — there is no object to protect, so fall through
    # to the no-op delete below and count it pruned. That keeps a vanished orphan
    # consistent with an absent-from-start one (the desired end state — path gone — is
    # achieved) instead of leaving the receipt to re-evaluate a path that is already gone.
    #
    # The recheck precedes the backup deliberately: it keeps ``backed_up`` from ever
    # incrementing without a following prune (preserving ``summary._is_changed``'s
    # invariant that a backup only rides along a real change) and avoids leaving a
    # phantom all-zero ``per_tool`` bucket. The residual backup->unlink window is the
    # irreducible cost of not having handle-relative (openat/unlinkat) ops.
    identity_after = _lstat_identity(orphan.path)
    if identity_after is not None and identity_after != identity_before:
        io.info(
            f"Skipped {orphan.path.name} — replaced since the orphan scan; left in place",
            verbose=True,
        )
        return
    counters = per_tool.setdefault(orphan.tool, Counters())
    if orphan.path.exists():
        dest = back_up(orphan.path, timestamp)
        counters.backed_up += 1
        io.info(f"Backed up {orphan.path.name} -> {dest.parent.name}/{dest.name}", verbose=True)
    # A symlink (to a dir OR a file) is removed with ``unlink``, which deletes
    # the link itself, never its target. ``rmtree`` is reserved for real
    # directories: ``Path.is_dir()`` follows symlinks, so a dir-symlink would
    # otherwise reach ``rmtree`` — which refuses a symlink and raises OSError.
    # ``unlink`` removes the symlink itself; ``rmtree`` handles real directories.
    if orphan.path.is_symlink() or not orphan.path.is_dir():
        # ``missing_ok`` swallows only FileNotFoundError: an already-gone path is
        # a no-op, real errors (e.g. permission) still raise.
        orphan.path.unlink(missing_ok=True)
    elif orphan.path.exists():
        # ``is_dir()`` was True above, but guard the TOCTOU window: only rmtree a
        # dir that is still present. An absent dir is a no-op (we do not silently
        # swallow rmtree errors on a present dir — permission failures still raise).
        shutil.rmtree(orphan.path)
    counters.pruned += 1
    if removed is not None:
        removed.add(orphan.path)


def _display(orphans: Sequence[Orphan], io: IOPort) -> None:
    """Print the orphan list grouped by tool then namespace.

    A blank line then the ``-- … --`` header (``io.header`` does not prepend the
    newline or wrap in dashes, so both are explicit here), a blank line before
    each tool block, and a trailing blank line.
    """
    io.info("")
    io.header(f"-- Orphans detected ({len(orphans)} total) --")
    last_tool = last_ns = ""
    for orphan in orphans:
        if orphan.tool != last_tool:
            io.info("")
            io.header(orphan.tool)
            last_tool = orphan.tool
            last_ns = ""
        if orphan.namespace != last_ns:
            io.info(f"  {orphan.namespace}/")
            last_ns = orphan.namespace
        io.info(f"    [{orphan.kind}] {orphan.path}")
    io.info("")
