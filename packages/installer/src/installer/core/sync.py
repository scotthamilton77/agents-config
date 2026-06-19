"""Minimal single-file sync engine (B.2 + G.1 backup).

Copies one source file to one destination, resolving both ends through a
`ToolAdapter`. The smallest slice of the eventual Phase-7 sync described in
`docs/architecture/installer/installer-design.md`: later stories grow it
to walk a `StagingPlan` and route conflicts through the merge registry.

Path-aware backup (G.1) ports the bash installer's ``backup()``
(`scripts/install.sh:352-388`): before overwriting an existing
destination, the original is copied to a timestamped backup so a failed
write leaves it recoverable. The routing decision and timestamp contract
live in `core/backup.py`, shared with the prune flow (G.4).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

from installer.core.backup import back_up, new_timestamp, valid_timestamp
from installer.core.consent import require_consent
from installer.core.merge.strategies.json_union import merge_settings_bytes
from installer.core.model import Counters, FileKind
from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan
    from installer.plugins.base import PluginRoute
    from installer.tools.base import ToolAdapter


def _effective_content(content: bytes, old: bytes | None, *, kind: FileKind) -> bytes:
    """The bytes to actually write for one item.

    A ``settings.json`` over an existing user file is union-merged into that file
    (bash ``sync_settings_file``) so user values survive; any other kind, or a
    fresh install, writes the staged content unchanged. The caller guarantees an
    existing settings file is valid JSON before this runs (an invalid one is
    skipped with an error — bash ``scripts/install.sh:1299-1304``), so the union
    never has to reconcile unparseable bytes.
    """
    if kind is not FileKind.SETTINGS_JSON or old is None:
        return content
    return merge_settings_bytes(existing=old, incoming=content)


def _is_valid_json(data: bytes) -> bool:
    """Whether ``data`` parses as JSON — the guard bash runs as ``jq empty`` before
    union-merging an existing ``settings.json`` (``scripts/install.sh:1299``)."""
    try:
        json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return True


def _is_unchanged(old: bytes, new: bytes, *, kind: FileKind) -> bool:
    """Settings compare semantically — a reformat is not a change; every other
    file compares byte-for-byte via sha-256.

    For ``SETTINGS_JSON`` both sides are valid JSON when this runs: ``_install_file``
    skips an invalid existing settings file (``_is_valid_json``) before reaching
    here, and ``new`` is always a union-merge result. So the parse cannot fail on
    the guarded path — an unparseable ``old`` would have been skipped upstream."""
    if kind is FileKind.SETTINGS_JSON:
        return bool(json.loads(old) == json.loads(new))
    return _sha256(old) == _sha256(new)


def sync(
    adapter: ToolAdapter,
    relpath: Path,
    *,
    repo_root: Path,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Install one file from the adapter's source tree to its dest tree.

    Resolves ``adapter.source_dir(repo_root) / relpath`` and
    ``adapter.dest_dir(home) / relpath``. Rejects a ``relpath`` that is
    absolute or contains a ``..`` component with `ValueError`, since either
    would let ``Path / relpath`` write outside the adapter tree. Skips when
    the destination
    already holds matching bytes (sha-256); otherwise writes the source
    bytes — unless ``dry_run`` is set, in which case it previews the
    would-be write through ``io`` and touches nothing.

    When overwriting an existing destination (dest present, bytes differ,
    not ``dry_run``), the original is backed up *before* the write so a
    failed write leaves it recoverable (G.1). ``timestamp`` is the
    backup's ``YYYYMMDD-HHMMSS`` suffix; injected so tests assert exact
    backup names, it defaults to the current local time at the call
    boundary. A caller-supplied ``timestamp`` that does not match that
    format is rejected with `ValueError` before any backup is written —
    it is interpolated raw into the backup path, so an unvalidated value
    carrying ``..``/path separators would escape the backup directory.

    Returns a `Counters` with exactly one of created / updated / skipped
    incremented, plus ``backed_up`` when an overwrite was preserved.
    """
    if not is_safe_relpath(relpath):
        raise ValueError(f"relpath escapes the adapter tree: {relpath}")  # noqa: TRY003  # single call-site; subclass not justified

    counters = Counters()
    source = adapter.source_dir(repo_root) / relpath
    dest = adapter.dest_dir(home) / relpath

    content = source.read_bytes()
    dest_exists = dest.is_file()

    if dest_exists and _sha256(dest.read_bytes()) == _sha256(content):
        counters.skipped += 1
        return counters

    if dry_run:
        verb = "update" if dest_exists else "create"
        io.info(f"would {verb} {dest}")
    else:
        if dest_exists:
            ts = timestamp if timestamp is not None else new_timestamp()
            if not valid_timestamp(ts):
                raise ValueError(f"timestamp must be YYYYMMDD-HHMMSS: {ts!r}")  # noqa: TRY003  # single call-site; subclass not justified
            back_up(dest, ts)
            counters.backed_up += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1
    return counters


def sync_plan(
    adapter: ToolAdapter,
    plan: StagingPlan,
    *,
    home: Path,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Walk a ``StagingPlan`` and install every item under the adapter's dest root.

    The plan-walking install sync (W1): the in-memory replacement for the bash
    installer's temp-dir-to-home copy. For each item:

    - a FILE item (eager ``content``) is hash-compared against the dest; an
      unchanged dest is skipped, a differing dest is backed up *before* the
      overwrite, and the bytes are written with a deterministic mode bit
      (``0o755`` when ``executable`` else ``0o644``);
    - a DIR item materialises its ``source_path`` tree — backing up then cleanly
      replacing an existing dest — and overlays its ``dir_overrides`` (override
      wins on a name collision).

    ``dry_run`` previews would-be writes through ``io`` and touches nothing.
    ``timestamp`` is the backup suffix (defaults to current local time); a
    caller-supplied value is validated against ``YYYYMMDD-HHMMSS`` before any
    backup is written, since it is interpolated raw into the backup path. A
    ``dest_relpath`` that is absolute or carries a ``..`` component is rejected
    with `ValueError` before *that item* is written — the guard is per-item, not
    a whole-plan precondition. Path containment is **lexical** — like
    ``sync``/``dump``, symlinked dest *parents* are not resolved, so the guard
    is not resolved-path safety. The walk is **non-transactional**: a failure on
    item N leaves items 1..N-1 **already installed** (matching the bash streaming
    installer; no rollback of earlier items). Returns aggregate `Counters`.

    The shared no-TTY guard (`require_consent`) runs once up front: a
    non-interactive run with neither ``auto_yes`` nor ``dry_run`` cannot answer a
    per-item prompt, so it hard-fails before any write rather than silently
    overwriting. ``auto_yes`` auto-accepts every changed-item prompt (still backing
    up first); ``dry_run`` previews without prompting.
    """
    require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
    counters = Counters()
    dest_dir = adapter.dest_dir(home)
    for item in plan.items.values():
        if not is_safe_relpath(item.dest_relpath):
            raise ValueError(f"dest_relpath escapes the dest tree: {item.dest_relpath}")  # noqa: TRY003  # single call-site; subclass not justified
        dest = dest_dir / item.dest_relpath
        content = item.content
        if content is None:
            _install_dir(
                dest,
                item.source_path,
                plan.dir_overrides.get(item.dest_relpath, {}),
                io=io,
                dry_run=dry_run,
                auto_yes=auto_yes,
                timestamp=timestamp,
                counters=counters,
            )
        else:
            _install_file(
                dest,
                content,
                executable=item.executable,
                kind=item.kind,
                io=io,
                dry_run=dry_run,
                auto_yes=auto_yes,
                timestamp=timestamp,
                counters=counters,
            )
    return counters


def sync_routes(
    routes: Iterable[PluginRoute],
    *,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
    timestamp: str | None = None,
) -> Counters:
    """Install every plugin route's globbed files at its dest root.

    The in-memory port of the bash installer's ``stage_and_install_beads``
    (``scripts/install.sh:948-1124``): for each ``PluginRoute``, glob
    ``source_dir`` for the route's pattern (sorted, files only) and install each
    match at ``dest_dir/<name>`` with the route's exec bit, reusing the FILE
    installer's skip / consent / backup contract. A route whose ``source_dir`` is
    absent contributes nothing (bash ``[[ -d ... ]] || continue``,
    ``scripts/install.sh:969,1056``). Unlike the tool-file path, a hash-equal skip
    restores a lost exec bit (``scripts/install.sh:1096``) — route-scoped, since
    bash carries no general executable reconcile.

    The shared no-TTY guard (`require_consent`) runs once up front, mirroring
    ``sync_plan``: a non-interactive run with neither ``auto_yes`` nor ``dry_run``
    hard-fails before any write. ``dest_dir`` is created lazily on the first write
    (the differ ignores empty dirs); ``timestamp`` is the backup suffix. Returns
    aggregate `Counters`.
    """
    require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
    counters = Counters()
    for route in routes:
        if not route.source_dir.is_dir():
            continue
        # ``route.glob`` is a trusted, non-recursive, in-repo adapter pattern
        # (e.g. ``*.toml``/``*.sh`` from ``beads.py``), so the dest needs no
        # ``is_safe_relpath`` guard like the tool path: every match is a direct
        # child of ``source_dir`` and ``src.name`` is a pure basename, so
        # ``dest_dir / src.name`` cannot escape ``dest_dir``. A future recursive
        # (``**``) route would break that invariant — add containment validation
        # before introducing one.
        for src in sorted(route.source_dir.glob(route.glob)):
            if not src.is_file():
                continue
            _install_file(
                route.dest_dir / src.name,
                src.read_bytes(),
                executable=route.executable,
                kind=FileKind.OTHER,
                io=io,
                dry_run=dry_run,
                auto_yes=auto_yes,
                timestamp=timestamp,
                counters=counters,
                restore_exec_on_skip=True,
            )
    return counters


def _install_file(
    dest: Path,
    content: bytes,
    *,
    executable: bool,
    kind: FileKind,
    io: IOPort,
    dry_run: bool,
    auto_yes: bool,
    timestamp: str | None,
    counters: Counters,
    restore_exec_on_skip: bool = False,
) -> None:
    """Install one FILE item: skip an unchanged dest, back up a differing dest
    before the overwrite, and write the bytes with a deterministic mode bit
    (``0o755`` when ``executable`` else ``0o644``). Mutates ``counters``. An
    unchanged-dest skip emits a verbose-gated "X is up to date" line (bash
    ``vok``, scripts/install.sh:1166), silent without ``--verbose``.

    A ``SETTINGS_JSON`` item is union-merged into an existing user file rather
    than overwritten (``_effective_content``), so user values survive an install;
    the change check is then semantic (``_is_unchanged``), so a pure reformat is a
    skip, not a spurious backup-and-rewrite. An existing settings file that is not
    valid JSON is left untouched and reported as an error (it cannot be merged, and
    a blind overwrite would destroy a recoverable hand-edit), counted as a skip —
    bash's ``jq empty`` guard (``scripts/install.sh:1299-1304``).

    A *changed* dest (present, content differs) passes through the consent gate
    (`_consent_to_overwrite`) before any backup or write: an interactive decline
    keeps the existing bytes and counts the item as skipped; ``auto_yes`` accepts
    silently; ``dry_run`` previews without prompting. The gate fires only on an
    existing dest — a first install is not a destructive overwrite.

    ``restore_exec_on_skip`` (default ``False``) opts the *skip* path into
    restoring a lost exec bit without a rewrite — the plugin-route behaviour at
    ``scripts/install.sh:1096``. It is off for tool files because bash carries no
    general executable reconcile (only beads scripts), so enabling it there would
    diverge from the spec; ``sync_routes`` turns it on.

    A dest already occupied by a non-file (a directory) is rejected with
    `ValueError` rather than crashing the walk with a raw ``IsADirectoryError`` —
    matching ``dump``'s type-guard so the CLI surfaces a clean error."""
    if dest.exists() and not dest.is_file():
        raise ValueError(f"dest exists but is not a file: {dest}")  # noqa: TRY003  # single call-site; subclass not justified
    dest_exists = dest.is_file()
    old = dest.read_bytes() if dest_exists else None
    if kind is FileKind.SETTINGS_JSON and old is not None and not _is_valid_json(old):
        # Refuse to touch an unparseable settings.json: union-merge is impossible
        # and a blind overwrite would destroy the user's (recoverable) hand-edit.
        # bash skips with the same guidance (``scripts/install.sh:1299-1304``).
        io.err(f"{dest} contains invalid JSON. Fix it manually or remove it.")
        counters.skipped += 1
        return
    effective = _effective_content(content, old, kind=kind)
    if old is not None and _is_unchanged(old, effective, kind=kind):
        if restore_exec_on_skip and executable and not dry_run and _restore_exec_bit(dest):
            io.info(f"Restored +x on {dest}", verbose=True)
        io.ok(f"{dest} is up to date", verbose=True)
        counters.skipped += 1
        return
    if (
        old is not None
        and not dry_run
        and not _consent_to_overwrite(dest, diff=(old, effective), io=io, auto_yes=auto_yes)
    ):
        io.warn(f"skipped {dest}")
        counters.skipped += 1
        return
    _ensure_parent_dir(dest, dry_run=dry_run)
    if not dry_run:
        if dest_exists:
            _back_up(dest, timestamp, counters)
        dest.write_bytes(effective)
        dest.chmod(0o755 if executable else 0o644)
    _record_write(dest, dest_exists=dest_exists, io=io, dry_run=dry_run, counters=counters)


def _dir_is_unchanged(dest: Path, source_path: Path, overrides: Mapping[Path, bytes]) -> bool:
    """Whether re-materialising ``dest`` from ``source_path`` + ``overrides`` would
    leave its contents byte-identical — the directory idempotency check.

    Mirrors bash ``sync_directory``'s ``src_hash == dest_hash`` "up to date"
    branch (`scripts/install.sh:1230`), whose directory hash folds every file's
    relpath and bytes (`compute_hash`, `scripts/install.sh:402-403`). The
    expected file map is the source tree with ``overrides`` overlaid (override
    wins on a name collision — dump-time semantics), compared against the actual
    dest tree. Bytes are read through symlinks to match ``copytree``'s
    dereferencing; only files participate, so empty dirs are ignored — matching
    the golden-master differ."""
    expected = {
        p.relative_to(source_path): p.read_bytes() for p in source_path.rglob("*") if p.is_file()
    }
    expected.update(overrides)
    actual = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    return expected == actual


def _install_dir(
    dest: Path,
    source_path: Path,
    overrides: Mapping[Path, bytes],
    *,
    io: IOPort,
    dry_run: bool,
    auto_yes: bool,
    timestamp: str | None,
    counters: Counters,
) -> None:
    """Materialise one DIR item: back up then cleanly replace an existing dest,
    copy the ``source_path`` tree, then overlay ``overrides`` (override wins on
    a name collision, matching dump-time semantics). Mutates ``counters``.

    An existing dest whose contents already match (`_dir_is_unchanged`) is left
    untouched and counted as a skip — so a re-install is idempotent and produces
    no spurious backups (bash ``sync_directory``'s "up to date" branch,
    `scripts/install.sh:1230`); the skip emits a verbose-gated "X is up to date"
    line (bash ``vok``, scripts/install.sh:1237), silent without ``--verbose``.
    A changed existing dest passes through the consent gate before the
    backup/replace: an interactive decline keeps the existing tree and counts a
    skip; ``auto_yes`` accepts silently; ``dry_run`` previews without prompting.
    A directory has no ``IOPort`` byte-diff, so the change is surfaced as a
    notice, not a unified diff.

    A missing or non-directory ``source_path``, or a dest already occupied by a
    non-directory (a file), is rejected with `ValueError` rather than crashing
    the walk with a raw ``FileNotFoundError`` / ``NotADirectoryError``. All
    override relpaths are validated **up-front, before any filesystem mutation**,
    so a ``dry_run`` surfaces the same error a real run would and an unsafe
    override never lands after a backup/replace has begun. Symlinks in the source
    tree are dereferenced by ``copytree`` (its default) — a behavioural choice
    flagged for the golden-master parity pass."""
    if not source_path.is_dir():
        raise ValueError(f"DIR item source is not a directory: {source_path}")  # noqa: TRY003  # single call-site; subclass not justified
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"dest exists but is not a directory: {dest}")  # noqa: TRY003  # single call-site; subclass not justified
    for inner in overrides:
        if not is_safe_relpath(inner):
            raise ValueError(f"dir override relpath escapes the dir: {inner}")  # noqa: TRY003  # single call-site; subclass not justified
    dest_exists = dest.exists()
    if dest_exists and _dir_is_unchanged(dest, source_path, overrides):
        io.ok(f"{dest} is up to date", verbose=True)
        counters.skipped += 1
        return
    if (
        dest_exists
        and not dry_run
        and not _consent_to_overwrite(dest, diff=None, io=io, auto_yes=auto_yes)
    ):
        io.warn(f"skipped {dest}")
        counters.skipped += 1
        return
    _ensure_parent_dir(dest, dry_run=dry_run)
    if not dry_run:
        if dest_exists:
            _back_up(dest, timestamp, counters)
            shutil.rmtree(dest)
        shutil.copytree(source_path, dest)
        for inner, inner_content in overrides.items():
            inner_dest = dest / inner
            _ensure_parent_dir(inner_dest, dry_run=dry_run)
            inner_dest.write_bytes(inner_content)
    _record_write(dest, dest_exists=dest_exists, io=io, dry_run=dry_run, counters=counters)


def _consent_to_overwrite(
    dest: Path,
    *,
    diff: tuple[bytes, bytes] | None,
    io: IOPort,
    auto_yes: bool,
) -> bool:
    """Decide whether a changed dest may be overwritten — the install consent gate.

    ``auto_yes`` short-circuits to ``True`` without prompting (the scripted-install
    path); the caller still backs up before the write, so ``--yes`` is never a
    data-loss path. Otherwise the change is surfaced and an interactive y/N confirm
    decides: a FILE item (``diff`` carries its old/new bytes) is shown a unified
    diff; a DIR item (``diff`` is ``None`` — a directory tree has no ``IOPort``
    byte-diff primitive) gets a plain 'changed' notice. A decline returns ``False``
    and the caller keeps the existing dest untouched.

    Reached only after `require_consent` has guaranteed the run can prompt when
    ``auto_yes`` is ``False`` — so the session is interactive here by construction.
    """
    if auto_yes:
        return True
    if diff is not None:
        io.show_diff(str(dest), *diff)
    else:
        io.warn(f"{dest} changed (directory will be replaced)")
    return io.confirm(f"Overwrite {dest}?", default=False)


def _record_write(
    dest: Path, *, dest_exists: bool, io: IOPort, dry_run: bool, counters: Counters
) -> None:
    """Preview the would-be write under ``dry_run`` and tally it as a create or
    update. On a real (non-``dry_run``) write, emit a verbose-gated per-item line
    ("Installed X (new)" / "Updated X") so ``--verbose`` yields bash ``vok``
    per-file detail (scripts/install.sh:1158,1180) while a quiet run stays
    silent. Shared by the file and dir installers; mutates ``counters``."""
    if dry_run:
        verb = "update" if dest_exists else "create"
        io.info(f"would {verb} {dest}")
    else:
        io.ok(f"Updated {dest}" if dest_exists else f"Installed {dest} (new)", verbose=True)
    if dest_exists:
        counters.updated += 1
    else:
        counters.created += 1


def _back_up(target: Path, timestamp: str | None, counters: Counters) -> None:
    """Back up ``target`` (file or dir) before an overwrite, resolving and
    validating the timestamp at the boundary (raw-interpolated into the backup
    path, so the validation is the path-traversal guard). Mutates ``counters``."""
    ts = timestamp if timestamp is not None else new_timestamp()
    if not valid_timestamp(ts):
        raise ValueError(f"timestamp must be YYYYMMDD-HHMMSS: {ts!r}")  # noqa: TRY003  # single call-site; subclass not justified
    back_up(target, ts)
    counters.backed_up += 1


def _ensure_parent_dir(target: Path, *, dry_run: bool) -> None:
    """Validate ``target``'s parent chain and, unless ``dry_run``, create it.

    Raises `ValueError` if the first existing ancestor of ``target`` is a regular
    file (a file where a directory must go) — a **non-mutating** check, so a
    ``dry_run`` preview fails in exactly the cases a real install would while only
    a real run creates the directories. Converts what would otherwise be a raw
    ``FileExistsError`` / ``NotADirectoryError`` from ``mkdir`` into a clean error,
    consistent with the engine's other filesystem type-mismatch guards."""
    for ancestor in target.parents:
        if ancestor.exists():
            if not ancestor.is_dir():
                raise ValueError(f"parent path is not a directory: {ancestor}")  # noqa: TRY003  # single call-site; subclass not justified
            break
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)


def _restore_exec_bit(dest: Path) -> bool:
    """Restore a lost exec bit on a hash-equal dest without a full rewrite.
    Route-scoped port of ``scripts/install.sh:1096`` (``[[ -x ]] || chmod +x``):
    fires only when no exec bit is set, and then *adds* the exec bits to the
    existing mode (``mode | 0o111``) rather than forcing ``0o755`` — so a
    user-tightened file (e.g. ``0o600``) gains exec without widening its
    read/write bits, mirroring ``chmod +x``. The any-exec-bit gate matches the
    differ's executability definition (``_diff.py::_is_executable``). Returns
    ``True`` when the mode was changed (so the caller can announce the repair
    under ``--verbose``, mirroring bash ``vinfo "Restored +x ..."``,
    scripts/install.sh:1096), ``False`` when the exec bit was already set."""
    mode = dest.stat().st_mode
    if mode & 0o111:
        return False
    dest.chmod(mode | 0o111)
    return True


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
