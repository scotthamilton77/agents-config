"""FileStore — the production Store adapter (§2).

Persists one PR's state as JSON at ``$XDG_STATE_HOME/prgroom/<slug>.json``
(fallback ``~/.local/state/prgroom/``). Concurrency is ``fcntl.flock(LOCK_EX)``
on a sidecar lock file (kernel-released on process death, so there is no
stale-lock code path — §3.7). Atomicity is a tempfile + ``os.replace`` on the
same filesystem, so a reader always sees either the complete prior file or the
complete new file. Structurally satisfies the
:class:`~prgroom.prsession.store.Store` Protocol.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TypeGuard

from prgroom.errors import lock_held_error
from prgroom.prsession.migrations import MIGRATIONS, Migrator
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import SCHEMA_VERSION, PRGroomingState
from prgroom.prsession.store import (
    SchemaUnknownError,
    StateCorruptError,
    StateNotFoundError,
)


def resolve_state_dir() -> Path:
    """Resolve the state directory: ``$XDG_STATE_HOME/prgroom`` else ``~/.local/state/prgroom``.

    A blank ``XDG_STATE_HOME`` is treated as unset, per POSIX env conventions.
    """
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "prgroom"


def write_atomic(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path`` via a same-dir tempfile + ``os.replace``.

    Readers never observe a partial file: ``os.replace`` is atomic on a single
    filesystem, and the tempfile is a sibling so the rename stays intra-FS.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)  # noqa: PTH105  # os.replace is the canonical atomic-rename primitive; the test patches it directly
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _is_int_version(version: object) -> TypeGuard[int]:
    """True only for a genuine ``int`` schema version.

    ``bool`` subclasses ``int`` (``True == 1``) and ``float`` compares equal
    (``1.0 == 1``), so a naive ``== SCHEMA_VERSION`` gate would silently accept
    ``schema_version: true`` / ``1.0`` as healthy v1 state — and ``bool`` would
    even alias an integer key in the ``MIGRATIONS`` lookup (``hash(True) ==
    hash(1)``). ``type(...) is int`` excludes both, routing malformed versions to
    the migrate-or-reject path instead of masquerading as current.
    """
    return type(version) is int


def _read_lock_pid(lock_path: Path) -> int | None:
    """Best-effort read of the holder pid a lock file carries (§2 contention).

    Returns the pid the live holder wrote, or ``None`` when the file is empty,
    unparseable, or unreadable (a crash between create and pid-write, or a
    pre-existing empty file). ``None`` renders ``(pid unknown)`` rather than
    misattributing contention to the contender's own process.
    """
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


class FileStore:
    """Production Store adapter. Structurally satisfies ``Store``."""

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        migrations: Mapping[int, Migrator] | None = None,
    ) -> None:
        self._dir = state_dir if state_dir is not None else resolve_state_dir()
        self._migrations: Mapping[int, Migrator] = (
            migrations if migrations is not None else MIGRATIONS
        )

    def _state_path(self, ref: PRRef) -> Path:
        return self._dir / f"{ref.slug()}.json"

    def _lock_path(self, ref: PRRef) -> Path:
        return self._dir / f"{ref.slug()}.lock"

    # -- Store protocol --

    def read(self, ref: PRRef) -> PRGroomingState:
        path = self._state_path(ref)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise StateNotFoundError(ref.display()) from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StateCorruptError(f"{path}: {exc}") from exc  # noqa: TRY003  # single call-site; message names the offending file
        version = payload.get("schema_version")
        if not (_is_int_version(version) and version == SCHEMA_VERSION):
            payload = self._migrate(path, raw, version)
        try:
            return PRGroomingState.from_dict(payload)
        except (KeyError, ValueError, TypeError) as exc:
            # Valid JSON whose shape from_dict rejects (e.g. a pre-rename key set
            # carrying the current schema_version) is a parse failure per §3.7.
            raise StateCorruptError(f"{path}: state shape invalid: {exc!r}") from exc  # noqa: TRY003  # single call-site; names the offending file + key

    def _migrate(self, path: Path, raw: bytes, from_version: object) -> dict[str, object]:
        """Apply a registered migrator for ``from_version`` or trip schema-unknown.

        On a registered migrator: run it on the raw bytes, rewrite the file in
        place via ``write_atomic`` (only on success — a raising migrator leaves
        the file byte-identical), then re-parse and return the upgraded payload.
        A raising migrator maps to :class:`StateCorruptError` (its registry
        ``how`` — move aside, rebuild — fits a failed migration). No migrator:
        :class:`SchemaUnknownError` (the §3.7 ``STATE_SCHEMA_UNKNOWN`` path).

        NOTE for the status/locking beads: this rewrites the file in place, so
        ``read`` is no longer side-effect-free once a migrator is registered. The
        lock-free ``status`` reader (§3.3 carve-out) must either migrate in memory
        without writing, or take the lock before a migrating read — do not ship an
        unlocked migrating reader. (Latent today: ``MIGRATIONS`` is empty.)
        """
        migrator = self._migrations.get(from_version) if _is_int_version(from_version) else None
        if migrator is None:
            raise SchemaUnknownError(  # noqa: TRY003  # single call-site; message names the file + version mismatch
                f"{path}: schema_version {from_version!r} != {SCHEMA_VERSION}"
            )
        # Both the migrator call and the parse sit inside the try: a raising OR an
        # invalid-JSON migrator must not corrupt on-disk state.
        try:
            migrated = migrator(raw)
            decoded = json.loads(migrated)
        except Exception as exc:
            raise StateCorruptError(  # noqa: TRY003  # single call-site; names the file + from-version
                f"{path}: migration from {from_version!r} failed: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise StateCorruptError(  # noqa: TRY003  # single call-site; names the file + from-version
                f"{path}: migration from {from_version!r} produced non-object JSON"
            )
        new_version = decoded.get("schema_version")
        if not (_is_int_version(new_version) and new_version == SCHEMA_VERSION):
            raise StateCorruptError(  # noqa: TRY003  # single call-site; names the file + result version
                f"{path}: migration from {from_version!r} did not reach "
                f"schema_version {SCHEMA_VERSION} (got {new_version!r})"
            )
        # Validate-before-commit: write_atomic runs ONLY after the migrated bytes
        # are confirmed parseable, a JSON object, AND at the current schema_version,
        # so a migrator that returns garbage or an unmigrated payload without raising
        # can never overwrite good on-disk state.
        write_atomic(path, migrated)
        parsed: dict[str, object] = decoded
        return parsed

    def write(self, ref: PRRef, state: PRGroomingState) -> None:
        data = json.dumps(state.to_dict(), indent=2, sort_keys=True).encode("utf-8")
        write_atomic(self._state_path(ref), data)

    @contextmanager
    def lock(self, ref: PRRef) -> Iterator[None]:
        """Acquire the per-PR lock non-blocking; raise on a live holder (§2).

        ``flock(LOCK_EX | LOCK_NB)`` fails immediately with :class:`BlockingIOError`
        when another invocation holds the lock — so a second invocation exits 75
        (``PRECONDITION_LOCK_HELD``) naming the holder pid instead of blocking. On a
        clean acquire the holder writes its own pid into the lock file so a future
        contender can name it. Closing the fd in ``finally`` releases the kernel lock.
        """
        lock_path = self._lock_path(ref)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise lock_held_error(ref, pid=_read_lock_pid(lock_path)) from exc
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            os.fsync(fd)
            yield
        finally:
            os.close(fd)  # single exit path — always closes the fd (releases the flock)

    def list_refs(self) -> list[PRRef]:
        if not self._dir.is_dir():
            return []
        refs: list[PRRef] = []
        for path in self._dir.glob("*.json"):
            ref = _ref_from_state_file(path)
            if ref is not None:
                refs.append(ref)
        return refs

    def delete(self, ref: PRRef) -> None:
        self._state_path(ref).unlink(missing_ok=True)


def _ref_from_state_file(path: Path) -> PRRef | None:
    """Recover the authoritative ``pr`` ref from a state file's JSON body.

    The filename slug (``<owner>-<repo>-<n>``) is a *lossy* encoding — both owner
    and repo may contain the ``-`` delimiter — so enumeration reads the
    ``{owner, repo, number}`` object that :meth:`PRGroomingState.to_dict` persists
    in the body, never by reverse-parsing the filename. The gate mirrors
    :meth:`FileStore.read`: the payload must be an object at the current
    ``schema_version`` with a dict ``pr``. Anything else (unreadable, foreign, or
    a partial ``pr``) is skipped — the dir may hold unrelated JSON, and a
    spurious ref would silently mislead ``sweep``.
    """
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("schema_version")
    if not (_is_int_version(version) and version == SCHEMA_VERSION):
        return None
    pr = payload.get("pr")
    if not isinstance(pr, dict):
        return None
    try:
        return PRRef.from_dict(pr)
    except KeyError:
        return None
