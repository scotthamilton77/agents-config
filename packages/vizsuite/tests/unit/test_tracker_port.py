"""TrackerPort: the sole beads boundary (spec §5.6 tracker quarantine, §5's
protocol-version handshake).

`TrackerPort` speaks the `work` CLI's JSON-envelope contract
(docs/specs/2026-07-04-work-facade-cli-contract.md) via an injected
`TrackerRunner`, mirroring the gh/git adapter seam. These tests drive it
entirely against `tests.fakes.ScriptedTrackerRunner` — no real subprocess, no
`bd`, ever. `SubprocessTrackerRunner`'s argv/cwd wiring is proven separately by
monkeypatching `subprocess.run` (mirrors `test_adapters_gh_runner.py`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import ScriptedTrackerRunner, tracker_error, tracker_ok, tracker_show_ok
from vizsuite.envelope import ErrorCode, VizError
from vizsuite.tracker.port import (
    BeadRecord,
    DepEdgeRecord,
    SubprocessTrackerRunner,
    TrackerPort,
    TrackerResult,
)

# ── handshake ──────────────────────────────────────────────────────────────


def test_handshake_runs_once_before_first_verb_dispatch():
    runner = ScriptedTrackerRunner(show_results={"x.1": tracker_show_ok("x.1")})
    port = TrackerPort(runner)

    port.read_bead("x.1")

    assert runner.calls[0] == ("--protocol-version",)
    assert runner.calls[1] == ("show", "x.1")


def test_handshake_is_cached_across_multiple_verb_calls():
    runner = ScriptedTrackerRunner(
        show_results={"x.1": tracker_show_ok("x.1"), "x.2": tracker_show_ok("x.2")}
    )
    port = TrackerPort(runner)

    port.read_bead("x.1")
    port.read_bead("x.2")

    assert runner.calls.count(("--protocol-version",)) == 1


def test_handshake_accepts_same_major_different_minor():
    runner = ScriptedTrackerRunner(protocol="1.7", show_results={"x.1": tracker_show_ok("x.1")})
    port = TrackerPort(runner)

    bead = port.read_bead("x.1")

    assert bead.id == "x.1"


def test_handshake_rejects_a_different_major_protocol_version():
    runner = ScriptedTrackerRunner(protocol="2.0", show_results={"x.1": tracker_show_ok("x.1")})
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_PROTOCOL_MISMATCH
    assert exc_info.value.detail["actual_protocol"] == "2.0"
    assert exc_info.value.detail["expected_major"] == "1"
    # the mismatch is caught at the handshake -- `show` is never dispatched
    assert ("show", "x.1") not in runner.calls


def test_handshake_with_missing_protocol_field_is_malformed():
    runner = ScriptedTrackerRunner()
    runner.responses[("--protocol-version",)] = tracker_ok({"nope": "field"})
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


def test_handshake_with_non_string_protocol_field_is_malformed():
    runner = ScriptedTrackerRunner()
    runner.responses[("--protocol-version",)] = tracker_ok({"protocol": 1.0})
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


# ── envelope parsing (shared _run_and_parse path, exercised via read_bead) ──


def test_non_json_stdout_is_malformed_envelope():
    runner = ScriptedTrackerRunner()
    runner.responses[("show", "x.1")] = TrackerResult(returncode=1, stdout="not json", stderr="")
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


def test_envelope_not_an_object_is_malformed():
    runner = ScriptedTrackerRunner()
    runner.responses[("show", "x.1")] = TrackerResult(returncode=0, stdout="42", stderr="")
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


def test_envelope_missing_ok_key_is_malformed():
    runner = ScriptedTrackerRunner()
    stdout = json.dumps({"protocol": "1.0", "data": {}})
    runner.responses[("show", "x.1")] = TrackerResult(returncode=0, stdout=stdout, stderr="")
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


def test_error_envelope_is_backend_error_carrying_facades_own_code():
    runner = ScriptedTrackerRunner()
    runner.responses[("show", "x.1")] = tracker_error(
        "E_NOT_FOUND", "no such item", detail={"id": "x.1"}
    )
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_BACKEND_ERROR
    assert exc_info.value.detail["code"] == "E_NOT_FOUND"
    assert exc_info.value.detail["backend_detail"] == {"id": "x.1"}
    assert "no such item" in exc_info.value.message


# ── read_bead ────────────────────────────────────────────────────────────


def test_read_bead_parses_id_status_labels_deps():
    runner = ScriptedTrackerRunner(
        show_results={
            "x.1": tracker_show_ok(
                "x.1",
                status="in_progress",
                labels=["shape-feat", "planned"],
                deps=[("x.0", "blocks", "closed")],
            )
        }
    )
    port = TrackerPort(runner)

    bead = port.read_bead("x.1")

    assert bead == BeadRecord(
        id="x.1",
        status="in_progress",
        labels=("shape-feat", "planned"),
        deps=(DepEdgeRecord(id="x.0", type="blocks", status="closed"),),
    )


@pytest.mark.parametrize(
    "data",
    [
        "not-an-object",
        {"status": "open", "labels": [], "deps": []},  # missing id
        {"id": "x.1", "labels": [], "deps": []},  # missing status
        {"id": "x.1", "status": "open", "deps": []},  # missing labels
        {"id": "x.1", "status": "open", "labels": []},  # missing deps
        {"id": "x.1", "status": "open", "labels": [], "deps": "nope"},  # deps not a list
        {"id": "x.1", "status": "open", "labels": [], "deps": [123]},  # dep entry not an object
        {
            "id": "x.1",
            "status": "open",
            "labels": [],
            "deps": [{"id": "x.0", "type": "blocks"}],  # dep entry missing status
        },
    ],
)
def test_read_bead_malformed_shapes_raise(data: object):
    runner = ScriptedTrackerRunner()
    runner.show_results["x.1"] = tracker_ok(data)
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.read_bead("x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


# ── add_edge ────────────────────────────────────────────────────────────


def test_add_edge_sends_dep_add_with_type():
    runner = ScriptedTrackerRunner()
    runner.responses[("dep", "add", "x.1", "x.2", "--type", "blocks")] = tracker_ok(None)
    port = TrackerPort(runner)

    port.add_edge("x.1", "x.2", "blocks")

    assert ("dep", "add", "x.1", "x.2", "--type", "blocks") in runner.calls


def test_add_edge_supports_related_to_kind():
    runner = ScriptedTrackerRunner()
    runner.responses[("dep", "add", "x.1", "x.2", "--type", "related-to")] = tracker_ok(None)
    port = TrackerPort(runner)

    port.add_edge("x.1", "x.2", "related-to")

    assert ("dep", "add", "x.1", "x.2", "--type", "related-to") in runner.calls


def test_add_edge_propagates_backend_error_envelope():
    runner = ScriptedTrackerRunner()
    runner.responses[("dep", "add", "x.1", "x.2", "--type", "blocks")] = tracker_error(
        "E_TYPE_WALL", "blocks: epic may not block task"
    )
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.add_edge("x.1", "x.2", "blocks")

    assert exc_info.value.code == ErrorCode.TRACKER_BACKEND_ERROR
    assert exc_info.value.detail["code"] == "E_TYPE_WALL"


# ── append_note ─────────────────────────────────────────────────────────


def test_append_note_sends_note_verb():
    runner = ScriptedTrackerRunner()
    runner.responses[("note", "x.1", "hello")] = tracker_ok(None)
    port = TrackerPort(runner)

    port.append_note("x.1", "hello")

    assert ("note", "x.1", "hello") in runner.calls


# ── mint_bead ───────────────────────────────────────────────────────────


def test_mint_bead_with_parent_returns_new_id():
    runner = ScriptedTrackerRunner()
    runner.responses[("create", "feat", "--title", "New thing", "--parent", "x.1")] = tracker_ok(
        {"id": "x.2"}
    )
    port = TrackerPort(runner)

    new_id = port.mint_bead("feat", "New thing", parent="x.1")

    assert new_id == "x.2"


def test_mint_bead_with_orphan_omits_parent_flag():
    runner = ScriptedTrackerRunner()
    runner.responses[("create", "chore", "--title", "Orphan chore", "--orphan")] = tracker_ok(
        {"id": "x.9"}
    )
    port = TrackerPort(runner)

    new_id = port.mint_bead("chore", "Orphan chore", orphan=True)

    assert new_id == "x.9"


def test_mint_bead_appends_optional_fields_in_order():
    runner = ScriptedTrackerRunner()
    argv = (
        "create",
        "bugfix",
        "--title",
        "Fix it",
        "--parent",
        "x.1",
        "--description",
        "desc",
        "--priority",
        "P1",
        "--acceptance",
        "criteria",
    )
    runner.responses[argv] = tracker_ok({"id": "x.3"})
    port = TrackerPort(runner)

    new_id = port.mint_bead(
        "bugfix",
        "Fix it",
        parent="x.1",
        description="desc",
        priority="P1",
        acceptance="criteria",
    )

    assert new_id == "x.3"
    assert argv in runner.calls


def test_mint_bead_malformed_response_without_id_raises():
    runner = ScriptedTrackerRunner()
    runner.responses[("create", "feat", "--title", "T", "--parent", "x.1")] = tracker_ok({})
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.mint_bead("feat", "T", parent="x.1")

    assert exc_info.value.code == ErrorCode.TRACKER_MALFORMED_ENVELOPE


def test_mint_bead_without_parent_or_orphan_propagates_facades_usage_error():
    runner = ScriptedTrackerRunner()
    runner.responses[("create", "feat", "--title", "T")] = tracker_error(
        "E_USAGE", "create feat: exactly one of --parent or --orphan is required"
    )
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.mint_bead("feat", "T")

    assert exc_info.value.code == ErrorCode.TRACKER_BACKEND_ERROR
    assert exc_info.value.detail["code"] == "E_USAGE"


# ── relabel ─────────────────────────────────────────────────────────────


def test_relabel_add_sends_label_add():
    runner = ScriptedTrackerRunner()
    runner.responses[("label", "add", "x.1", "planned", "spec-ready")] = tracker_ok(None)
    port = TrackerPort(runner)

    port.relabel("x.1", ["planned", "spec-ready"])

    assert ("label", "add", "x.1", "planned", "spec-ready") in runner.calls


def test_relabel_remove_sends_label_remove():
    runner = ScriptedTrackerRunner()
    runner.responses[("label", "remove", "x.1", "planned")] = tracker_ok(None)
    port = TrackerPort(runner)

    port.relabel("x.1", ["planned"], remove=True)

    assert ("label", "remove", "x.1", "planned") in runner.calls


# ── resequence: not supported today (spec §5.7) ─────────────────────────


def test_resequence_raises_not_supported_without_touching_the_runner():
    runner = ScriptedTrackerRunner()
    port = TrackerPort(runner)

    with pytest.raises(VizError) as exc_info:
        port.resequence()

    assert exc_info.value.code == ErrorCode.TRACKER_NOT_SUPPORTED
    # never attempts the handshake either -- a verb with no facade mapping
    # never touches the subprocess boundary at all (spec §5.6).
    assert runner.calls == []


# ── SubprocessTrackerRunner: real `work` subprocess wiring ──────────────


class _RecordingCompletedProcess:
    returncode = 0
    stdout = '{"protocol": "1.0", "ok": true, "data": null, "error": null}'
    stderr = ""


def _record_run(calls: list[dict[str, Any]]) -> Any:
    def _fake_run(argv: list[str], **kwargs: Any) -> _RecordingCompletedProcess:
        calls.append({"argv": argv, **kwargs})
        return _RecordingCompletedProcess()

    return _fake_run


def test_subprocess_runner_runs_work_against_the_injected_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _record_run(calls))

    SubprocessTrackerRunner(repo_root=str(tmp_path)).run(["show", "x.1"])

    assert len(calls) == 1
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["argv"] == ["work", "show", "x.1"]


def test_subprocess_runner_default_repo_root_is_dot(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _record_run(calls))

    SubprocessTrackerRunner().run(["--protocol-version"])

    assert calls[0]["cwd"] == "."
