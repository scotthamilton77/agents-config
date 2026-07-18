"""`work groom --done` / `work groom --status` -- Backlog Grooming state
(track spec §4/§6, criteria 14-15).

State lives on the designated `[operating-model].groom-state-bead` as a
parseable note line (`backlog_last_groomed: <iso8601>`) -- the fallback
mechanism the spec names, since the `Backend` protocol has no metadata
primitive. `--status` never mutates; `--done` appends exactly one note line
per call (bd's append-only note discipline, same as `work note`).
"""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime

import pytest

from tests.conftest import run_cli
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.groom import groom

GROOM_STATE_BEAD = "proj-groom1"


def _config(
    *, nag_days: int | None = 7, groom_state_bead: str | None = GROOM_STATE_BEAD
) -> TrackLayerConfig:
    return TrackLayerConfig(
        names=("alpha",),
        organizing_only=(),
        enforcement="advisory",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        backlog_groom_nag_days=nag_days,
        groom_state_bead=groom_state_bead,
        extraction_max_track_backlog=None,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=None,
    )


def _args(
    *,
    done: bool = False,
    status: bool = False,
    config: TrackLayerConfig | None = None,
    now: datetime = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC),
) -> Namespace:
    resolved_config = config if config is not None else _config()
    return Namespace(done=done, status=status, load_config=lambda: resolved_config, now=lambda: now)


def _backend(*, notes: str = "") -> FakeBackend:
    return FakeBackend().add(GROOM_STATE_BEAD, notes=notes)


# -- config gate --


def test_missing_groom_state_bead_fails_not_configured() -> None:
    with pytest.raises(WorkError) as exc_info:
        groom(_backend(), _args(status=True, config=_config(groom_state_bead=None)))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert "groom-state-bead" in exc_info.value.message
    assert "agents-config-jpn0s" in exc_info.value.message


def test_missing_groom_state_bead_gates_before_any_backend_call() -> None:
    """The config gate runs before backend I/O -- a backend that would raise
    NOT_FOUND for the (unconfigured) bead id must never be reached."""
    backend = FakeBackend()  # empty: any .get() call raises E_NOT_FOUND
    with pytest.raises(WorkError) as exc_info:
        groom(backend, _args(done=True, config=_config(groom_state_bead=None)))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED


# -- --done --


def test_done_appends_note_and_returns_new_timestamp() -> None:
    backend = _backend()
    result = groom(backend, _args(done=True))
    assert result == {"backlog_last_groomed": "2026-07-18T12:00:00Z"}
    assert backend.note_lines(GROOM_STATE_BEAD) == ["backlog_last_groomed: 2026-07-18T12:00:00Z"]


def test_second_done_call_appends_a_new_line_not_a_replace() -> None:
    backend = _backend(notes="backlog_last_groomed: 2026-07-01T00:00:00Z")
    groom(
        backend,
        _args(done=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert backend.note_lines(GROOM_STATE_BEAD) == [
        "backlog_last_groomed: 2026-07-01T00:00:00Z",
        "backlog_last_groomed: 2026-07-18T12:00:00Z",
    ]


# -- --status --


def test_status_never_groomed_is_breached_with_no_timestamp() -> None:
    result = groom(_backend(), _args(status=True))
    assert result == {
        "backlog_last_groomed": None,
        "days_since": None,
        "nag_days": 7,
        "breached": True,
    }


def test_status_not_yet_breached() -> None:
    backend = _backend(notes="backlog_last_groomed: 2026-07-14T12:00:00Z")
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result == {
        "backlog_last_groomed": "2026-07-14T12:00:00Z",
        "days_since": 4,
        "nag_days": 7,
        "breached": False,
    }


def test_status_exactly_on_boundary_is_not_breached() -> None:
    # Strict greater-than (criterion 14): days_since == nag_days is NOT breached.
    backend = _backend(notes="backlog_last_groomed: 2026-07-11T12:00:00Z")
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["days_since"] == 7
    assert result["breached"] is False


def test_status_one_day_past_boundary_is_breached() -> None:
    backend = _backend(notes="backlog_last_groomed: 2026-07-10T12:00:00Z")
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["days_since"] == 8
    assert result["breached"] is True


def test_status_unconfigured_nag_days_never_breaches_when_groomed() -> None:
    backend = _backend(notes="backlog_last_groomed: 2020-01-01T00:00:00Z")
    result = groom(backend, _args(status=True, config=_config(nag_days=None)))
    assert result["nag_days"] is None
    assert result["breached"] is False


def test_status_unconfigured_nag_days_still_breaches_when_never_groomed() -> None:
    # Bootstrap case (never groomed) is maximally overdue regardless of
    # whether a nag threshold is configured.
    result = groom(_backend(), _args(status=True, config=_config(nag_days=None)))
    assert result["breached"] is True


def test_status_takes_the_last_of_multiple_note_lines() -> None:
    notes = "\n".join(
        [
            "backlog_last_groomed: 2026-06-01T00:00:00Z",
            "unrelated note",
            "backlog_last_groomed: 2026-07-17T00:00:00Z",
        ]
    )
    backend = _backend(notes=notes)
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["backlog_last_groomed"] == "2026-07-17T00:00:00Z"


def test_status_selects_newest_timestamp_not_physically_last_line() -> None:
    # REGRESSION PIN (Codex finding, round 4): concurrent `--done` calls can
    # append out of chronological order -- a process that computed an
    # earlier timestamp can stall before append_note and write it AFTER a
    # later completion already appended a newer one. Selection must be by
    # parsed timestamp value, never by note-append position.
    notes = "\n".join(
        [
            "backlog_last_groomed: 2026-07-17T00:00:00Z",  # newer, appended FIRST
            "backlog_last_groomed: 2026-06-01T00:00:00Z",  # older, appended LAST
        ]
    )
    backend = _backend(notes=notes)
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["backlog_last_groomed"] == "2026-07-17T00:00:00Z"


def test_status_ignores_non_matching_note_lines() -> None:
    backend = _backend(notes="some other note\nbacklog_last_groomed: 2026-07-17T00:00:00Z\nmore")
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["backlog_last_groomed"] == "2026-07-17T00:00:00Z"


def test_status_malformed_timestamp_fails_loud_not_e_internal() -> None:
    # REGRESSION PIN (Codex finding): notes stay append-only and raw bd
    # writes remain possible outside `work groom --done`, so a corrupted
    # marker (`\S+` matches non-timestamp garbage too) must surface as a
    # typed E_NOT_CONFIGURED naming the bad value, never crash into
    # E_INTERNAL and silently drop the nag. This is the ALL-INVALID case --
    # the only marker in history is malformed, so no trustworthy answer
    # exists anywhere.
    backend = _backend(notes="backlog_last_groomed: not-a-timestamp")
    with pytest.raises(WorkError) as exc_info:
        groom(backend, _args(status=True))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert "not-a-timestamp" in exc_info.value.message
    assert GROOM_STATE_BEAD in exc_info.value.message


def test_status_skips_malformed_line_when_a_valid_marker_exists() -> None:
    # REGRESSION PIN (round 4 refinement): notes are append-only -- a bad
    # line written months ago can never be deleted -- so a single corrupted
    # candidate coexisting with later VALID markers must not permanently
    # brick --status. Only the all-invalid case (above) is fail-loud.
    notes = "\n".join(
        [
            "backlog_last_groomed: not-a-timestamp",  # old corpse, never cleaned up
            "backlog_last_groomed: 2026-07-17T00:00:00Z",  # a later, valid groom
        ]
    )
    backend = _backend(notes=notes)
    result = groom(
        backend,
        _args(status=True, now=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)),
    )
    assert result["backlog_last_groomed"] == "2026-07-17T00:00:00Z"
    assert result["breached"] is False


# -- round-3 Codex finding: clock skew across dolt-synced machines --
# backlog_last_groomed is synced via dolt (spec §6); a marker written from a
# fast-clocked machine can land slightly in the future. <=24h is ordinary
# NTP drift and clamps to days_since=0; beyond that is invalid state.


def test_status_small_future_skew_clamps_to_zero_not_breached() -> None:
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    # 23h59m in the future -- inside the 24h tolerance.
    backend = _backend(notes="backlog_last_groomed: 2026-07-19T11:59:00Z")
    result = groom(backend, _args(status=True, now=now))
    assert result["days_since"] == 0
    assert result["breached"] is False


def test_status_gross_future_skew_is_invalid_state() -> None:
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    # 24h01m in the future -- one minute past the tolerance.
    backend = _backend(notes="backlog_last_groomed: 2026-07-19T12:01:00Z")
    with pytest.raises(WorkError) as exc_info:
        groom(backend, _args(status=True, now=now))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert GROOM_STATE_BEAD in exc_info.value.message


# -- criterion 15: immediately after --done, --status reports not-breached --


def test_done_then_status_is_immediately_not_breached() -> None:
    backend = _backend()
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    groom(backend, _args(done=True, now=now))
    result = groom(backend, _args(status=True, now=now))
    assert result["breached"] is False
    assert result["days_since"] == 0


# -- CLI wiring: mutually exclusive --done/--status, verb dispatch end-to-end --


def _raw_bead(item_id: str, *, notes: str = "") -> dict[str, object]:
    return {
        "id": item_id,
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": [],
        "parent": None,
        "notes": notes,
        "dependencies": [],
        "dependents": [],
    }


def test_cli_requires_exactly_one_of_done_or_status() -> None:
    exit_code, envelope, _ = run_cli(["groom"], steps=[])
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_cli_rejects_both_done_and_status() -> None:
    exit_code, envelope, _ = run_cli(["groom", "--done", "--status"], steps=[])
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)


def test_cli_status_end_to_end() -> None:
    exit_code, envelope, _ = run_cli(
        ["groom", "--status"],
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(
                    returncode=0,
                    stdout=json.dumps(
                        [
                            _raw_bead(
                                GROOM_STATE_BEAD, notes="backlog_last_groomed: 2026-07-10T12:00:00Z"
                            )
                        ]
                    ),
                    stderr="",
                ),
            )
        ],
        config_loader=lambda _explicit_path: _config(),
        now=lambda: datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert exit_code == 0
    assert envelope["data"] == {
        "backlog_last_groomed": "2026-07-10T12:00:00Z",
        "days_since": 8,
        "nag_days": 7,
        "breached": True,
    }


def test_cli_done_end_to_end() -> None:
    exit_code, envelope, _ = run_cli(
        ["groom", "--done"],
        steps=[ScriptedStep(("update",), BdResult(returncode=0, stdout="", stderr=""))],
        config_loader=lambda _explicit_path: _config(),
        now=lambda: datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert exit_code == 0
    assert envelope["data"] == {"backlog_last_groomed": "2026-07-18T12:00:00Z"}


def test_cli_not_configured_when_groom_state_bead_blank() -> None:
    exit_code, envelope, _ = run_cli(
        ["groom", "--status"],
        steps=[],
        config_loader=lambda _explicit_path: _config(groom_state_bead=None),
    )
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.NOT_CONFIGURED)
