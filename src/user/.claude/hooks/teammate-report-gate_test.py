#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""Tests for the teammate report gate hook.

Run: uv run teammate-report-gate_test.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GATE_PATH = HERE / "teammate-report-gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("teammate_report_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

CWD = "/Users/x/proj"
SESSION = "sess-1"


@pytest.fixture(autouse=True)
def isolated_state_root(tmp_path, monkeypatch):
    root = tmp_path / "state"
    monkeypatch.setenv("TEAMMATE_REPORT_GATE_STATE_ROOT", str(root))
    return root


def run(payload: dict, monkeypatch) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return gate.main()


def task_completed(name: str | None, cwd: str = CWD, session_id: str = SESSION) -> dict:
    payload = {"hook_event_name": "TaskCompleted", "cwd": cwd, "session_id": session_id}
    if name is not None:
        payload["teammate_name"] = name
    return payload


def teammate_idle(name: str | None, cwd: str = CWD, session_id: str = SESSION) -> dict:
    payload = {"hook_event_name": "TeammateIdle", "cwd": cwd, "session_id": session_id}
    if name is not None:
        payload["teammate_name"] = name
    return payload


def send_message_event(
    message: str, sender: str | None = None, agent_type: str | None = None,
    cwd: str = CWD, session_id: str = SESSION,
) -> dict:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "SendMessage",
        "tool_input": {"message": message},
        "tool_response": {"routing": {"sender": sender}} if sender is not None else {},
        "cwd": cwd, "session_id": session_id,
    }
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return payload


def subagent_stop_event(
    agent_type: str | None = None, last_assistant_message: str = "",
    transcript_path: str = "/tmp/transcript.jsonl", cwd: str = CWD, session_id: str = SESSION,
) -> dict:
    payload = {
        "hook_event_name": "SubagentStop", "last_assistant_message": last_assistant_message,
        "cwd": cwd, "session_id": session_id,
    }
    if agent_type is not None:
        payload["agent_type"] = agent_type
        payload["agent_transcript_path"] = transcript_path
    return payload


def state_dir(root: Path, cwd: str = CWD, session_id: str = SESSION) -> Path:
    return root / gate.project_slug(cwd) / session_id


class TestTaskCompletedGate:
    def test_blocks_then_allows_after_an_update(self, monkeypatch, capsys):
        name = "alpha"
        assert run(task_completed(name), monkeypatch) == 2
        assert "UPDATE" in capsys.readouterr().err
        run(send_message_event("UPDATE 1: working on it", sender=name), monkeypatch)
        assert run(task_completed(name), monkeypatch) == 0

    def test_two_consecutive_blocks_then_gives_up_and_allows(self, monkeypatch):
        name = "beta"
        assert run(task_completed(name), monkeypatch) == 2
        assert run(task_completed(name), monkeypatch) == 2
        assert run(task_completed(name), monkeypatch) == 0

    def test_final_report_satisfies_a_task_completed_with_no_updates(self, monkeypatch):
        name = "gamma"
        run(send_message_event("FINAL REPORT: everything shipped", sender=name), monkeypatch)
        assert run(task_completed(name), monkeypatch) == 0

    def test_missing_teammate_name_is_never_blocked(self, monkeypatch):
        assert run(task_completed(None), monkeypatch) == 0
        assert run(task_completed(None), monkeypatch) == 0
        assert run(task_completed(None), monkeypatch) == 0


class TestTeammateIdleGate:
    def test_blocks_without_final_report_then_allows_after_one(self, monkeypatch, capsys):
        name = "delta"
        assert run(teammate_idle(name), monkeypatch) == 2
        assert "FINAL REPORT" in capsys.readouterr().err
        run(send_message_event("FINAL REPORT: all done here", sender=name), monkeypatch)
        assert run(teammate_idle(name), monkeypatch) == 0

    def test_three_idle_blocks_then_a_marker_is_written_and_idle_allowed(
        self, monkeypatch, isolated_state_root
    ):
        name = "epsilon"
        for _ in range(3):
            assert run(teammate_idle(name), monkeypatch) == 2
        assert run(teammate_idle(name), monkeypatch) == 0
        marker = state_dir(isolated_state_root) / f"{name}.stop-noncompliance.marker"
        assert marker.is_file()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["name"] == name
        assert data["idle_blocks"] == 3

    def test_missing_teammate_name_is_never_blocked(self, monkeypatch):
        assert run(teammate_idle(None), monkeypatch) == 0
        assert run(teammate_idle(None), monkeypatch) == 0
        assert run(teammate_idle(None), monkeypatch) == 0
        assert run(teammate_idle(None), monkeypatch) == 0

    def test_stash_with_final_report_in_last_message_changes_the_wording(
        self, monkeypatch, capsys
    ):
        name = "iota"
        run(subagent_stop_event(agent_type=name, last_assistant_message=(
            "FINAL REPORT: composed here but never sent"
        )), monkeypatch)
        assert run(teammate_idle(name), monkeypatch) == 2
        err = capsys.readouterr().err
        assert "resent" in err.lower()

    def test_without_a_stash_the_reminder_is_generic(self, monkeypatch, capsys):
        name = "kappa"
        assert run(teammate_idle(name), monkeypatch) == 2
        err = capsys.readouterr().err
        assert "does not reach the orchestrator" in err.lower()

    def test_a_stash_lookup_miss_is_fine(self, monkeypatch, capsys):
        name = "lookup-miss"
        assert run(teammate_idle(name), monkeypatch) == 2
        err = capsys.readouterr().err
        assert "does not reach the orchestrator" in err.lower()


class TestObservers:
    def test_posttooluse_never_exits_nonzero(self, monkeypatch):
        assert run(send_message_event("just some chatter", sender="mu"), monkeypatch) == 0
        assert run(
            {"hook_event_name": "PostToolUse", "tool_name": "OtherTool",
             "cwd": CWD, "session_id": SESSION}, monkeypatch
        ) == 0

    def test_subagentstop_never_exits_nonzero_anonymous_or_typed(self, monkeypatch):
        assert run(subagent_stop_event(), monkeypatch) == 0
        assert run(subagent_stop_event(agent_type="nu"), monkeypatch) == 0

    def test_posttooluse_credits_routing_sender_over_agent_type(self, monkeypatch):
        payload = send_message_event(
            "FINAL REPORT: shipped it", sender="alpha", agent_type="some-type"
        )
        assert run(payload, monkeypatch) == 0
        assert run(teammate_idle("alpha"), monkeypatch) == 0

    def test_an_update_mentioning_the_final_report_is_not_a_final_report(self, monkeypatch):
        assert run(send_message_event("UPDATE 3: nearly done, final report next", sender="a"),
                   monkeypatch) == 0
        assert run(teammate_idle("a"), monkeypatch) == 2

    def test_updated_prefix_is_not_an_update(self, monkeypatch):
        assert run(send_message_event("UPDATED the files as asked", sender="b"),
                   monkeypatch) == 0
        assert run(task_completed("b"), monkeypatch) == 2

    def test_a_mid_sentence_final_report_mention_does_not_disarm_the_idle_gate(
        self, monkeypatch,
    ):
        assert run(send_message_event("Should the final report include the appendix?",
                                      sender="c"), monkeypatch) == 0
        assert run(teammate_idle("c"), monkeypatch) == 2

    def test_a_decorated_final_report_marker_still_counts(self, monkeypatch):
        assert run(send_message_event("**FINAL REPORT:** all tasks done", sender="d"),
                   monkeypatch) == 0
        assert run(teammate_idle("d"), monkeypatch) == 0

    def test_posttooluse_falls_back_to_agent_type_when_no_routing_sender(self, monkeypatch):
        payload = send_message_event("FINAL REPORT: shipped it", agent_type="xi")
        assert run(payload, monkeypatch) == 0
        assert run(teammate_idle("xi"), monkeypatch) == 0

    def test_posttooluse_with_neither_sender_nor_agent_type_is_a_no_op(self, monkeypatch):
        payload = send_message_event("FINAL REPORT: shipped it")
        assert run(payload, monkeypatch) == 0


class TestStatePlacement:
    def test_project_slug_matches_the_projects_directory_convention(self):
        assert gate.project_slug("/Users/x/proj") == "-Users-x-proj"

    def test_state_file_lands_under_slugged_cwd_and_session_id(
        self, monkeypatch, isolated_state_root
    ):
        name = "theta"
        run(task_completed(name), monkeypatch)
        assert (state_dir(isolated_state_root) / f"{name}.json").is_file()


class TestMalformedInput:
    def test_unparseable_stdin_exits_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
        assert gate.main() == 0

    def test_a_json_scalar_is_not_a_payload(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("42"))
        assert gate.main() == 0


class TestNoPlanningJargon:
    def test_the_deployed_hook_carries_no_planning_jargon(self):
        jargon = re.compile(
            r"\bD[0-9]|\bAC[0-9]|\bslice\b|\bcharter\b|\bmilestone\b|\bagents-config-9k9",
            re.IGNORECASE,
        )
        hits = [
            line for line in GATE_PATH.read_text(encoding="utf-8").splitlines()
            if jargon.search(line)
        ]
        assert not hits, hits


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
