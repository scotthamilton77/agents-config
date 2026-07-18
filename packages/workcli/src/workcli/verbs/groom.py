"""`work groom --done` / `work groom --status` -- Backlog Grooming state
(track spec §4/§6, criteria 14-15).

Its own module, not `report.py`: `--done` MUTATES state (bd's own
per-item state, on a note field) unlike the read-only aggregations
`lint`/`graph`/`triggers` compute, so it's closer in shape to
`verbs/tracks.py`'s single mutating verb than to the report family.

Persistence mechanism: the `Backend` protocol has no metadata primitive
(only `get`/`append_note`), so state lives as a parseable note line
(`backlog_last_groomed: <iso8601>`) on the designated
`[operating-model].groom-state-bead` -- the spec's named fallback. Notes are
append-only (bd's `--append-notes`, same discipline as `work note`), so
`--done` never edits an existing line; `--status` reads the LAST matching
line, since later appends are newer.
"""

from __future__ import annotations

import re
from argparse import Namespace
from datetime import UTC, datetime

from workcli.backend import Backend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, JsonValue, WorkError

_NOTE_LINE_PATTERN = re.compile(r"^backlog_last_groomed: (\S+)$", re.MULTILINE)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _require_groom_state_bead(config: TrackLayerConfig) -> str:
    """Config gate, checked before any backend I/O (both --done and --status)."""
    if config.groom_state_bead is None:
        raise WorkError(
            ErrorCode.NOT_CONFIGURED,
            "[operating-model].groom-state-bead is not configured; run the backfill "
            "migration (agents-config-jpn0s) to mint it",
            detail={"reason": "invalid"},
        )
    return config.groom_state_bead


def _last_groomed(backend: Backend, groom_state_bead: str) -> str | None:
    """The most recently appended `backlog_last_groomed: <ts>` note line, or
    None when no matching line exists yet (bootstrap: never groomed)."""
    matches = _NOTE_LINE_PATTERN.findall(backend.get(groom_state_bead).notes)
    return matches[-1] if matches else None


def _done(backend: Backend, args: Namespace, groom_state_bead: str) -> JsonValue:
    timestamp = args.now().strftime(_TIMESTAMP_FORMAT)
    backend.append_note(groom_state_bead, f"backlog_last_groomed: {timestamp}")
    return {"backlog_last_groomed": timestamp}


def _status(
    backend: Backend, args: Namespace, config: TrackLayerConfig, groom_state_bead: str
) -> JsonValue:
    last_groomed = _last_groomed(backend, groom_state_bead)
    nag_days = config.backlog_groom_nag_days
    if last_groomed is None:
        # Never groomed = maximally overdue -- a deliberate design decision:
        # bootstrap state should nag, not silently pass, regardless of
        # whether a nag threshold is configured.
        return {
            "backlog_last_groomed": None,
            "days_since": None,
            "nag_days": nag_days,
            "breached": True,
        }
    try:
        parsed = datetime.strptime(last_groomed, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as parse_error:
        # Notes are append-only and raw `bd note`/`bd label` writes stay
        # possible outside `work groom --done` -- a corrupted marker line
        # must fail loud as a typed error here, never crash into E_INTERNAL
        # (which would silently drop the nag rather than surfacing the
        # broken state) (Codex finding).
        raise WorkError(
            ErrorCode.NOT_CONFIGURED,
            f"backlog_last_groomed note on {groom_state_bead} is malformed: "
            f"{last_groomed!r} ({parse_error})",
            detail={"reason": "invalid"},
        ) from parse_error
    days_since = (args.now() - parsed).days
    breached = nag_days is not None and days_since > nag_days  # strict > (criterion 14)
    return {
        "backlog_last_groomed": last_groomed,
        "days_since": days_since,
        "nag_days": nag_days,
        "breached": breached,
    }


def groom(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work groom --done` / `work groom --status`; argparse's
    required mutually-exclusive group guarantees exactly one flag is set."""
    config = args.load_config()
    groom_state_bead = _require_groom_state_bead(config)
    if args.done:
        return _done(backend, args, groom_state_bead)
    return _status(backend, args, config, groom_state_bead)
