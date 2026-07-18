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
`--done` never edits an existing line; `--status` selects the marker with
the latest PARSED timestamp, not the physically last line -- concurrent
`--done` calls can append out of chronological order.
"""

from __future__ import annotations

import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta

from workcli.backend import Backend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, JsonValue, WorkError

_NOTE_LINE_PATTERN = re.compile(r"^backlog_last_groomed: (\S+)$", re.MULTILINE)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# backlog_last_groomed is dolt-synced across machines (spec §6): ordinary
# NTP drift on a fast clock can leave a freshly-written marker slightly in
# the future, and treating that as invalid would fail a groom that just
# happened. A marker further in the future than this isn't drift -- it's
# invalid state (clock misconfiguration or a bad raw write) -- and is
# rejected the same way a malformed marker is (Codex finding, round 3).
_FUTURE_SKEW_TOLERANCE = timedelta(hours=24)


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


def _latest_marker(backend: Backend, groom_state_bead: str) -> tuple[str, datetime] | None:
    """The `backlog_last_groomed: <ts>` marker with the LATEST parsed
    timestamp, or None when no matching line exists yet (bootstrap: never
    groomed). Selected by parsed value, not append/physical-last position:
    concurrent `--done` calls can append out of chronological order (one
    process computes its timestamp, stalls before `append_note`, and appends
    after a later completion already wrote a newer one) -- trusting note
    order in that case would regress the persisted reset time and could fire
    the nag prematurely (Codex finding, round 4).

    Unparsable lines are SKIPPED, not fatal, as long as at least one valid
    marker exists elsewhere in history: notes are append-only, so a corrupted
    line can never be deleted, and hard-failing on the first bad candidate
    would brick `--status` forever even after a hundred valid `--done`
    appends. Fail-loud (round 1) governs the case where no trustworthy
    answer exists at all -- it doesn't demand refusing a trustworthy answer
    because a corpse is also in the room (round 4 refinement)."""
    matches = _NOTE_LINE_PATTERN.findall(backend.get(groom_state_bead).notes)
    if not matches:
        return None
    parsed_markers: list[tuple[str, datetime]] = []
    invalid: list[tuple[str, str]] = []
    for raw in matches:
        try:
            parsed_markers.append(
                (raw, datetime.strptime(raw, _TIMESTAMP_FORMAT).replace(tzinfo=UTC))
            )
        except ValueError as parse_error:
            invalid.append((raw, str(parse_error)))
    if parsed_markers:
        return max(parsed_markers, key=lambda marker: marker[1])
    # Every candidate failed to parse: unlike a single corrupted line among
    # valid ones, there is no trustworthy answer anywhere in history.
    raw, problem = invalid[0]
    raise _invalid_marker(groom_state_bead, raw, problem)


def _invalid_marker(groom_state_bead: str, last_groomed: str, problem: str) -> WorkError:
    """Notes are append-only and raw `bd note`/`bd label` writes stay possible
    outside `work groom --done` -- any marker this module cannot trust must
    fail loud as a typed error here, never crash into E_INTERNAL (which would
    silently drop the nag rather than surfacing the broken state)."""
    return WorkError(
        ErrorCode.NOT_CONFIGURED,
        f"backlog_last_groomed note on {groom_state_bead} is malformed: "
        f"{last_groomed!r} ({problem})",
        detail={"reason": "invalid"},
    )


def _done(backend: Backend, args: Namespace, groom_state_bead: str) -> JsonValue:
    timestamp = args.now().strftime(_TIMESTAMP_FORMAT)
    backend.append_note(groom_state_bead, f"backlog_last_groomed: {timestamp}")
    return {"backlog_last_groomed": timestamp}


def _status(
    backend: Backend, args: Namespace, config: TrackLayerConfig, groom_state_bead: str
) -> JsonValue:
    latest = _latest_marker(backend, groom_state_bead)
    nag_days = config.backlog_groom_nag_days
    if latest is None:
        # Never groomed = maximally overdue -- a deliberate design decision:
        # bootstrap state should nag, not silently pass, regardless of
        # whether a nag threshold is configured.
        return {
            "backlog_last_groomed": None,
            "days_since": None,
            "nag_days": nag_days,
            "breached": True,
        }
    last_groomed, parsed = latest
    now = args.now()
    elapsed = now - parsed
    if elapsed < -_FUTURE_SKEW_TOLERANCE:
        # Further in the future than ordinary clock drift explains -- not a
        # slightly-fast machine, invalid state (round 3 Codex finding).
        raise _invalid_marker(
            groom_state_bead, last_groomed, f"timestamp is {-elapsed} in the future"
        )
    # A small future skew (<= tolerance) is ordinary NTP drift on a fast
    # clock across dolt-synced machines: clamp to 0 rather than raising, so
    # an honest cross-machine groom never falsely reports breached=True.
    days_since = max((now - parsed).days, 0)
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
