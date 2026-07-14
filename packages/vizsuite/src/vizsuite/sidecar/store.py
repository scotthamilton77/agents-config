"""`.viz/` sidecar store — read/write for the fingerprint manifest plus the
five Tier-2/Tier-3 record files (spec §5.3).

Every writing operation takes the single-writer advisory lock (`.viz/lock`)
and writes temp-file-then-atomic-rename in the same directory, so the
overnight sweep and an on-demand command can never interleave a torn write
(spec test item 16). Lock contention past a bounded retry raises a typed
`VizError(SIDECAR_LOCKED)` — never an unbounded block. Serialization is
deterministic (sorted keys, records sorted by id) so rewriting unchanged
content is byte-stable.

Tier-2 files (`manifest.json`/`edges.json`/`steps.json`/
`recommendations.json`/`flags.json`) expose wholesale-rewrite APIs.
`verdicts.json` is Tier 3 and exposes only `upsert_verdict` — there is
deliberately no `write_verdicts`: nothing but an explicit human verdict may
touch it (spec §5.3: "Tier 3 is only ever invalidated, never silently
deleted").

The sidecar root is injected at construction — never read from `Path.cwd()`
or another module global — mirroring how `Runners` bundles the adapters
`cli.main` injects into every verb handler.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from vizsuite.envelope import ErrorCode, JsonValue, VizError
from vizsuite.sidecar.models import (
    FactRecord,
    FlagRecord,
    Manifest,
    VerdictRecord,
    fact_record_from_json,
    fact_record_to_json,
    flag_record_from_json,
    flag_record_to_json,
    manifest_from_json,
    manifest_to_json,
    verdict_record_from_json,
    verdict_record_to_json,
)

_T = TypeVar("_T")

_LOCK_FILENAME = "lock"
_MANIFEST_FILENAME = "manifest.json"
_EDGES_FILENAME = "edges.json"
_STEPS_FILENAME = "steps.json"
_RECOMMENDATIONS_FILENAME = "recommendations.json"
_FLAGS_FILENAME = "flags.json"
_VERDICTS_FILENAME = "verdicts.json"

# `out/` is `vizsuite.output.ensure_viz_dir`'s concern; the store owns `lock`'s
# entry directly so a sidecar-only workflow (no `viz pr` run yet) still ends up
# with a correct `.gitignore` regardless of which bootstrap ran first.
_GITIGNORE_LINE = "lock"

_DEFAULT_LOCK_TIMEOUT_S = 5.0
_DEFAULT_LOCK_POLL_INTERVAL_S = 0.05

_MALFORMED_EXCEPTIONS = (KeyError, TypeError, ValueError)


class _LockTimeoutError(VizError):
    """Raised when the sidecar lock is still held past the bounded retry window."""

    def __init__(self, lock_path: Path, timeout: float) -> None:
        super().__init__(
            ErrorCode.SIDECAR_LOCKED,
            "could not acquire the sidecar lock before the retry deadline",
            detail={"lock_path": str(lock_path), "timeout_s": timeout},
        )


class _MalformedSidecarFileError(VizError):
    """Raised when a `.viz/*.json` file's content is invalid JSON or the wrong shape."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(
            ErrorCode.SIDECAR_MALFORMED,
            "sidecar file is not valid JSON or does not match its record shape",
            detail={"path": str(path), "reason": reason},
        )


class _NotAnArrayError(TypeError):
    """Raised when a Tier-2 record file's parsed JSON content isn't an array."""

    def __init__(self) -> None:
        super().__init__("expected a JSON array")


def _atomic_write_json(path: Path, payload: JsonValue) -> None:
    """Write `payload` as deterministic JSON via temp-file-then-atomic-rename.

    The temp file is unique per call (pid + monotonic nanoseconds) and lives in
    `path`'s own directory so the final `Path.replace` is an atomic same-
    filesystem rename. A crash between the temp write and the rename leaves an
    inert stray temp file — the canonical `path` is only ever touched by the
    rename itself, so it is never partially written (spec test item 16).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _load_json(path: Path) -> JsonValue | None:
    if not path.exists():
        return None
    try:
        raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _MalformedSidecarFileError(path, str(exc)) from exc
    return raw


def _load_manifest(path: Path) -> Manifest | None:
    raw = _load_json(path)
    if raw is None:
        return None
    try:
        return manifest_from_json(raw)
    except _MALFORMED_EXCEPTIONS as exc:
        raise _MalformedSidecarFileError(path, str(exc)) from exc


def _load_records(path: Path, parse_one: Callable[[JsonValue], _T]) -> tuple[_T, ...]:
    raw = _load_json(path)
    if raw is None:
        return ()
    try:
        if not isinstance(raw, list):
            raise _NotAnArrayError
        return tuple(parse_one(item) for item in raw)
    except _MALFORMED_EXCEPTIONS as exc:
        raise _MalformedSidecarFileError(path, str(exc)) from exc


def _ensure_lock_ignored(viz_dir: Path) -> None:
    """Idempotently ensure `.viz/.gitignore` ignores `lock` (append-if-absent)."""
    viz_dir.mkdir(parents=True, exist_ok=True)
    gitignore = viz_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if _GITIGNORE_LINE not in existing.splitlines():
        prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
        gitignore.write_text(f"{prefix}{_GITIGNORE_LINE}\n", encoding="utf-8")


@dataclass(frozen=True)
class SidecarStore:
    """The `.viz/` sidecar's single entry point. `root` is injected, never `Path.cwd()`.

    `lock_timeout`/`lock_poll_interval` are constructor-level (not per-call
    kwargs) so a caller or test can size the bounded retry once, without
    threading extra parameters through every write method.
    """

    root: Path
    lock_timeout: float = _DEFAULT_LOCK_TIMEOUT_S
    lock_poll_interval: float = _DEFAULT_LOCK_POLL_INTERVAL_S

    @property
    def viz_dir(self) -> Path:
        return self.root / ".viz"

    def _path(self, filename: str) -> Path:
        return self.viz_dir / filename

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self._path(_LOCK_FILENAME)
        _ensure_lock_ignored(self.viz_dir)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                lock_path.open("x", encoding="utf-8").close()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise _LockTimeoutError(lock_path, self.lock_timeout) from None
                time.sleep(self.lock_poll_interval)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    # ---- manifest (Tier-2, wholesale-rewrite) ------------------------------

    def read_manifest(self) -> Manifest | None:
        return _load_manifest(self._path(_MANIFEST_FILENAME))

    def write_manifest(self, manifest: Manifest) -> None:
        with self._locked():
            _atomic_write_json(self._path(_MANIFEST_FILENAME), manifest_to_json(manifest))

    # ---- edges (Tier-2, wholesale-rewrite) ---------------------------------

    def read_edges(self) -> tuple[FactRecord, ...]:
        return _load_records(self._path(_EDGES_FILENAME), fact_record_from_json)

    def write_edges(self, records: Sequence[FactRecord]) -> None:
        with self._locked():
            _write_fact_records(self._path(_EDGES_FILENAME), records)

    # ---- steps (Tier-2, wholesale-rewrite) ---------------------------------

    def read_steps(self) -> tuple[FactRecord, ...]:
        return _load_records(self._path(_STEPS_FILENAME), fact_record_from_json)

    def write_steps(self, records: Sequence[FactRecord]) -> None:
        with self._locked():
            _write_fact_records(self._path(_STEPS_FILENAME), records)

    # ---- recommendations (Tier-2, wholesale-rewrite) -----------------------

    def read_recommendations(self) -> tuple[FactRecord, ...]:
        return _load_records(self._path(_RECOMMENDATIONS_FILENAME), fact_record_from_json)

    def write_recommendations(self, records: Sequence[FactRecord]) -> None:
        with self._locked():
            _write_fact_records(self._path(_RECOMMENDATIONS_FILENAME), records)

    # ---- flags (Tier-2, machine-owned, wholesale-rewrite) ------------------

    def read_flags(self) -> tuple[FlagRecord, ...]:
        return _load_records(self._path(_FLAGS_FILENAME), flag_record_from_json)

    def write_flags(self, records: Sequence[FlagRecord]) -> None:
        with self._locked():
            sorted_records = sorted(records, key=lambda record: record.flag_id)
            _atomic_write_json(
                self._path(_FLAGS_FILENAME),
                [flag_record_to_json(record) for record in sorted_records],
            )

    # ---- verdicts (Tier 3 — append-or-update-single-verdict ONLY) ----------

    def read_verdicts(self) -> tuple[VerdictRecord, ...]:
        return _load_records(self._path(_VERDICTS_FILENAME), verdict_record_from_json)

    def upsert_verdict(self, record: VerdictRecord) -> None:
        """Append a new verdict or update an existing one by `verdict_id`.

        The only public `verdicts.json` mutation — there is deliberately no
        `write_verdicts`: Tier 3 is only ever invalidated, never silently
        rewritten wholesale (spec §5.3). Unrelated verdicts are carried
        through unchanged.
        """
        path = self._path(_VERDICTS_FILENAME)
        with self._locked():
            existing = _load_records(path, verdict_record_from_json)
            by_id = {item.verdict_id: item for item in existing}
            by_id[record.verdict_id] = record
            sorted_records = sorted(by_id.values(), key=lambda item: item.verdict_id)
            _atomic_write_json(path, [verdict_record_to_json(item) for item in sorted_records])


def _write_fact_records(path: Path, records: Sequence[FactRecord]) -> None:
    sorted_records = sorted(records, key=lambda record: record.fact_id)
    _atomic_write_json(path, [fact_record_to_json(record) for record in sorted_records])
