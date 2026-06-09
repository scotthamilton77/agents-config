"""Store-adapter selector (§2 "Selection at runtime").

Resolves a ``--store`` flag value (or the ``PRGROOM_STORE`` env var, or the
built-in default ``file``) to a concrete :class:`~prgroom.prsession.store.Store`.
Precedence is **flag > env > default** — the flag is consulted first and only
falls through to the env when unset. ``file`` yields the production
:class:`~prgroom.prsession.file.FileStore`; ``bd`` is deferred (v2) and any
unknown name is a user error — both surface as a terminal
``PRECONDITION_STORE_UNAVAILABLE`` (exit 2, rendered 4-line block, no traceback).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.prsession.file import FileStore
from prgroom.prsession.store import Store

ENV_VAR = "PRGROOM_STORE"
DEFAULT_STORE = "file"


class StoreName(StrEnum):
    """The user-facing ``--store`` / ``PRGROOM_STORE`` vocabulary."""

    FILE = "file"
    BD = "bd"


def resolve_store(
    name: str | None,
    *,
    env: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
) -> Store:
    """Resolve a store name to a concrete adapter (flag > env > default ``file``).

    ``name`` is the ``--store`` flag value (``None`` when unset). Falls back to
    ``env[PRGROOM_STORE]`` then the ``file`` default. A **blank** env var is
    treated as unset (POSIX convention, mirroring ``resolve_state_dir``); a blank
    ``--store ''`` flag is, by contrast, an explicit user mistake and errors.
    ``bd`` (deferred) and any unrecognized name raise :class:`PreconditionError`
    tagged ``PRECONDITION_STORE_UNAVAILABLE`` (terminal user-error, exit 2).
    """
    environ = env if env is not None else {}
    resolved = name if name is not None else (environ.get(ENV_VAR) or DEFAULT_STORE)
    if resolved == StoreName.FILE:
        return FileStore(state_dir=state_dir)
    raise PreconditionError(ErrorCode.PRECONDITION_STORE_UNAVAILABLE, detail=resolved)
