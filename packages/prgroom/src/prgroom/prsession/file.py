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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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


class FileStore:
    """Production Store adapter. Structurally satisfies ``Store``."""

    def __init__(self, *, state_dir: Path | None = None) -> None:
        self._dir = state_dir if state_dir is not None else resolve_state_dir()

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
        if version != SCHEMA_VERSION:
            raise SchemaUnknownError(  # noqa: TRY003  # single call-site; message names the file + version mismatch
                f"{path}: schema_version {version!r} != {SCHEMA_VERSION}"
            )
        return PRGroomingState.from_dict(payload)

    def write(self, ref: PRRef, state: PRGroomingState) -> None:
        data = json.dumps(state.to_dict(), indent=2, sort_keys=True).encode("utf-8")
        write_atomic(self._state_path(ref), data)

    @contextmanager
    def lock(self, ref: PRRef) -> Iterator[None]:
        lock_path = self._lock_path(ref)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

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
    in the body, never by reverse-parsing the filename. Files that aren't
    well-formed prgroom state (unreadable, non-object, or a missing/partial
    ``pr``) are skipped: the dir may hold unrelated JSON.
    """
    try:
        payload = json.loads(path.read_bytes())
        return PRRef.from_dict(payload["pr"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
