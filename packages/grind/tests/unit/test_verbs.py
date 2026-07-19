"""`grind.verbs`: the four command bodies over `grind.store` + `grind.fold`,
independent of argv/stdout wiring (that's `cli.py`, tested separately)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from grind.envelope import GrindError
from grind.store import events_path, load_events
from grind.verbs import cmd_create, cmd_finish, cmd_log, cmd_status

_NOW = lambda: datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)  # noqa: E731

_SEED = {
    "title": "Widget grind",
    "repo": "acme/widgets",
    "mission": {"goal": "ship widgets"},
    "protocols": {},
    "lanes": [
        {
            "id": "lane-a",
            "name": "Lane A",
            "queue": [{"id": "wgclw.1", "title": "First item"}],
        }
    ],
}


def _seeded(tmp_path: Path) -> Path:
    cmd_create(tmp_path, dict(_SEED), now=_NOW)
    return tmp_path


def _strip_trailing_newline(dir_: Path) -> None:
    """Simulate a crash mid-append: the durable final line lost its newline."""
    path = events_path(dir_)
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")


def _append_unparsable_fragment(dir_: Path) -> None:
    """Simulate a crash mid-append: a truncated final line that won't parse."""
    path = events_path(dir_)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"ts":"tX","type":"pr_ope')  # truncated mid-write, no newline


# -- create -------------------------------------------------------------------


def test_create_writes_first_event_and_returns_state_summary(tmp_path: Path):
    result = cmd_create(tmp_path, dict(_SEED), now=_NOW)

    assert result["ok"] is True
    summary = result["state_summary"]
    assert isinstance(summary, dict)
    assert summary["title"] == "Widget grind"
    events = load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["type"] == "grind_created"
    assert events[0]["ts"] == "2026-07-19T12:00:00Z"


def test_create_refuses_when_events_log_already_nonempty(tmp_path: Path):
    _seeded(tmp_path)

    with pytest.raises(GrindError):
        cmd_create(tmp_path, dict(_SEED), now=_NOW)

    assert len(load_events(tmp_path)) == 1  # nothing appended by the refused call


def test_create_rejects_a_malformed_seed_and_writes_nothing(tmp_path: Path):
    with pytest.raises(GrindError):
        cmd_create(tmp_path, {"title": "missing everything else"}, now=_NOW)

    assert load_events(tmp_path) == []


@pytest.mark.parametrize("reserved_key", ["ts", "type"])
def test_create_rejects_a_seed_carrying_a_reserved_envelope_key(tmp_path: Path, reserved_key: str):
    # The CLI stamps `ts` and `type`; a seed supplying either would overwrite
    # the CLI-controlled envelope via the dict spread. Reject before appending.
    poisoned = dict(_SEED)
    poisoned[reserved_key] = "attacker-controlled"

    with pytest.raises(GrindError):
        cmd_create(tmp_path, poisoned, now=_NOW)

    assert load_events(tmp_path) == []


# -- log ------------------------------------------------------------------


def test_log_appends_folds_and_returns_emit_back_envelope(tmp_path: Path):
    _seeded(tmp_path)

    result = cmd_log(tmp_path, "item_started", {"item": "wgclw.1"}, now=_NOW)

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["anomaly"] is None
    assert result["conditions"] == []
    delta = result["delta"]
    assert isinstance(delta, dict)
    assert delta["entity"] == "wgclw.1"
    assert delta["old_status"] == "queued"
    assert delta["new_status"] == "in-progress"
    assert len(load_events(tmp_path)) == 2
    assert result["torn_tail"] is None  # intact log -> no repair to surface


def test_log_surfaces_torn_tail_repair_when_first_writer_after_crash(tmp_path: Path):
    # A crash left the seed line without its trailing newline; `log` is the
    # first writer after the crash. append_event repairs the tail, then folds
    # a clean log -- so state.anomalies can't carry the torn_tail. The repair
    # rides the envelope's dedicated `torn_tail` field instead (spec "Torn
    # tail": "records a torn_tail anomaly in the command's envelope").
    _seeded(tmp_path)
    _strip_trailing_newline(tmp_path)

    result = cmd_log(tmp_path, "item_started", {"item": "wgclw.1"}, now=_NOW)

    torn = result["torn_tail"]
    assert isinstance(torn, dict)
    assert torn["quarantined"] is False  # complete line, only the newline was lost
    assert "torn_tail" in torn["reason"]
    # The new event still applied normally alongside the repair.
    assert result["applied"] is True
    assert result["anomaly"] is None
    assert len(load_events(tmp_path)) == 2


def test_log_torn_tail_and_event_anomaly_do_not_mask_each_other(tmp_path: Path):
    # Co-occurrence: a quarantined torn-tail fragment AND a well-formed but
    # illegal new event. The event-level anomaly rides `anomaly`; the repair
    # rides `torn_tail`. Neither field masks the other.
    _seeded(tmp_path)
    _append_unparsable_fragment(tmp_path)

    result = cmd_log(tmp_path, "item_merged", {"item": "wgclw.1", "pr": 1, "sha": "abc"}, now=_NOW)

    anomaly = result["anomaly"]
    assert isinstance(anomaly, dict)
    assert anomaly["type"] == "item_merged"  # illegal from queued
    torn = result["torn_tail"]
    assert isinstance(torn, dict)
    assert torn["quarantined"] is True  # the fragment didn't parse
    assert "torn_tail" in torn["reason"]


def test_log_rejects_a_malformed_payload_and_appends_nothing(tmp_path: Path):
    _seeded(tmp_path)

    with pytest.raises(GrindError):
        cmd_log(tmp_path, "pr_opened", {"item": "wgclw.1", "pr": "not-an-int"}, now=_NOW)

    assert len(load_events(tmp_path)) == 1  # only the seed event


@pytest.mark.parametrize("reserved_key", ["ts", "type"])
def test_log_rejects_a_payload_carrying_a_reserved_envelope_key(tmp_path: Path, reserved_key: str):
    # The codex-flagged smuggle: a valid `observation` payload carrying
    # `type=grind_finished` would, via the dict spread, persist and apply a
    # grind_finished event -- prematurely terminal -- while reporting success.
    # Reserved envelope keys are rejected before anything is appended.
    _seeded(tmp_path)
    poisoned = {"level": "INFO", "message": "x", reserved_key: "grind_finished"}

    with pytest.raises(GrindError):
        cmd_log(tmp_path, "observation", poisoned, now=_NOW)

    assert len(load_events(tmp_path)) == 1  # only the seed event


def test_log_rejects_grind_created_in_a_fresh_dir_and_appends_nothing(tmp_path: Path):
    # Codex-flagged: in a fresh --dir, `grind log grind_created --json <seed>`
    # would fold as the first, valid creation event -- bypassing the CLI
    # contract that creation goes through `create` only (spec CLI table:
    # "creation goes through create, never through grind log grind_created").
    # The reserved-key guard does not catch this: the event *type* is the verb
    # argument, not a payload key. Reject it as a command error regardless of
    # directory state.
    with pytest.raises(GrindError):
        cmd_log(tmp_path, "grind_created", dict(_SEED), now=_NOW)

    assert load_events(tmp_path) == []  # nothing appended by the refused call


def test_log_rejects_grind_created_mid_run_and_appends_nothing(tmp_path: Path):
    _seeded(tmp_path)

    with pytest.raises(GrindError):
        cmd_log(tmp_path, "grind_created", dict(_SEED), now=_NOW)

    assert len(load_events(tmp_path)) == 1  # only the seed event


def test_log_accepts_a_well_formed_but_illegal_event_as_an_anomaly(tmp_path: Path):
    _seeded(tmp_path)
    # item is still `queued`; item_merged is illegal from `queued` per the
    # transition table -- well-formed shape, illegal transition.

    result = cmd_log(tmp_path, "item_merged", {"item": "wgclw.1", "pr": 1, "sha": "abc"}, now=_NOW)

    assert result["ok"] is True
    assert result["applied"] is False
    anomaly = result["anomaly"]
    assert isinstance(anomaly, dict)
    assert anomaly["type"] == "item_merged"
    assert anomaly["item"] == "wgclw.1"
    assert result["delta"] is None
    assert len(load_events(tmp_path)) == 2  # anomalous events still append


def test_log_delta_is_none_when_no_status_changed(tmp_path: Path):
    _seeded(tmp_path)

    result = cmd_log(tmp_path, "observation", {"level": "INFO", "message": "fyi"}, now=_NOW)

    assert result["applied"] is True
    assert result["delta"] is None


def test_log_rewrites_state_json_after_append(tmp_path: Path):
    _seeded(tmp_path)

    cmd_log(tmp_path, "item_started", {"item": "wgclw.1"}, now=_NOW)

    import json

    state_json = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state_json["items"]["wgclw.1"]["status"] == "in-progress"


# -- status ---------------------------------------------------------------


def test_status_default_returns_summary(tmp_path: Path):
    _seeded(tmp_path)

    result = cmd_status(tmp_path, full=False)

    assert result["ok"] is True
    assert "state_summary" in result
    assert "state" not in result


def test_status_full_returns_entire_state(tmp_path: Path):
    _seeded(tmp_path)

    result = cmd_status(tmp_path, full=True)

    assert result["ok"] is True
    state = result["state"]
    assert isinstance(state, dict)
    assert "items" in state


# -- finish -----------------------------------------------------------------


def test_finish_appends_grind_finished_and_returns_summary(tmp_path: Path):
    _seeded(tmp_path)

    result = cmd_finish(tmp_path, "shipped it", now=_NOW)

    assert result["ok"] is True
    events = load_events(tmp_path)
    assert events[-1]["type"] == "grind_finished"
    assert events[-1]["summary"] == "shipped it"
    summary = result["state_summary"]
    assert isinstance(summary, dict)
    assert summary["finished"] is True
    assert result["torn_tail"] is None  # intact log -> no repair to surface


def test_finish_surfaces_torn_tail_repair_when_first_writer_after_crash(tmp_path: Path):
    # `finish` is the first writer after a crash: it must surface the repair
    # too, not just `log` (spec "Torn tail" applies to the write path uniformly).
    _seeded(tmp_path)
    _strip_trailing_newline(tmp_path)

    result = cmd_finish(tmp_path, "shipped it", now=_NOW)

    torn = result["torn_tail"]
    assert isinstance(torn, dict)
    assert torn["quarantined"] is False
    assert "torn_tail" in torn["reason"]


def test_finish_rejects_missing_summary(tmp_path: Path):
    _seeded(tmp_path)

    with pytest.raises(GrindError):
        cmd_finish(tmp_path, "", now=_NOW)
