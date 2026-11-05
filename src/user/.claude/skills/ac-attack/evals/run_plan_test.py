#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the executor that turns an evaluation plan into reports.

Run: uv run run_plan_test.py

The transports are replaced by an injected dispatcher that returns output captured from real runs,
so the walk over a plan is observed through the files it leaves and the runs it asks for.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("run_plan", HERE / "run_plan.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_plan"] = module
    spec.loader.exec_module(module)
    return module


run_plan = _load()

OBJECTION = {
    "lens": "what-if",
    "target_ac": "AUD-A7",
    "ground": {"rule": "what-if-missing", "reason": "No criterion pins the failure path."},
    "objection": "The criteria let a retry through.",
    "scenario": {"given": "a refused connection", "when": "the audit runs",
                 "expect": "two requests reach the service"},
}
BLANK_SCENARIO = {**OBJECTION, "scenario": {"given": "", "when": "the audit runs", "expect": "x"}}
EMPTY = json.dumps({"lens": "what-if", "objections": [], "report": "empty"})


def findings(*objections) -> str:
    return json.dumps({"lens": "what-if", "objections": list(objections), "report": "objections"})


class TestReadReport:
    def test_an_empty_report_is_usable(self):
        parsed = run_plan.read_report("what-if", EMPTY)
        assert parsed == {"report": json.loads(EMPTY), "malformed_objections": [], "fault": None}

    def test_a_fenced_report_keeps_its_rule_and_site_citations_verbatim(self):
        parsed = run_plan.read_report("what-if", "```json\n" + findings(OBJECTION) + "\n```\n")
        assert parsed["fault"] is None
        assert parsed["report"]["objections"] == [OBJECTION]

    def test_a_report_with_one_malformed_objection_is_usable_and_names_its_position(self):
        parsed = run_plan.read_report("what-if", findings(BLANK_SCENARIO, OBJECTION))
        assert parsed["fault"] is None
        assert parsed["malformed_objections"] == [1]
        assert parsed["report"]["objections"] == [BLANK_SCENARIO, OBJECTION]

    @pytest.mark.parametrize("text,word", [
        ("", "no JSON report"),
        ("I could not finish.", "no JSON report"),
        (findings(BLANK_SCENARIO), "every objection"),
        (findings({"objection": "no ground"}), "every objection"),
        (json.dumps({"lens": "what-if", "objections": [], "report": "objections"}), "none"),
    ])
    def test_a_missing_or_wholly_malformed_report_is_not_usable(self, text, word):
        parsed = run_plan.read_report("what-if", text)
        assert word in parsed["fault"]


def jsonl(*lines) -> str:
    return "".join(json.dumps(line) + "\n" for line in lines)


CODEX_ROLLOUT = jsonl(
    {"type": "session_meta", "payload": {"id": "01a12df1", "cwd": "/private/tmp/empty"}},
    {"type": "world_state", "payload": {"state": {"agents_md": {}}}},
    {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}},
    {"type": "token_usage_record", "payload": {"thread_id": "01a12df1", "response_id": "resp_04a0"}},
)
OPENROUTER_SESSION = jsonl(
    {"type": "attachment", "cwd": "/private/tmp/empty",
     "attachment": {"type": "instructions", "files": []}},
    {"type": "attachment", "attachment": {"type": "prompt_snapshot", "tools": []}},
    {"type": "assistant", "message": {"id": "msg_u0wD", "model": "moonshotai/kimi-k3",
                                      "content": [{"type": "text", "text": "{}"}]}},
)


class TestRunMetadata:
    def test_a_codex_rollout_yields_the_served_model_response_id_and_isolation_proof(self):
        assert run_plan.codex_metadata(CODEX_ROLLOUT) == {
            "model": "gpt-6.1-sol", "effort": "high", "response_id": "resp_04a0",
            "isolation": {"cwd": "/private/tmp/empty", "agents_md": {}, "agents_md_injections": 0},
        }

    def test_a_codex_rollout_that_loaded_an_instruction_file_shows_it_in_the_proof(self):
        leaked = jsonl(
            {"type": "session_meta", "payload": {"cwd": "/repo"}},
            {"type": "world_state", "payload": {"state": {"agents_md": {"/repo/AGENTS.md": "x"}}}},
            {"type": "response_item", "payload": {"text": "# AGENTS.md instructions for /repo"}},
        )
        assert run_plan.codex_metadata(leaked)["isolation"] == {
            "cwd": "/repo", "agents_md": {"/repo/AGENTS.md": "x"}, "agents_md_injections": 1,
        }

    def test_an_openrouter_session_yields_the_served_model_response_id_and_isolation_proof(self):
        assert run_plan.openrouter_metadata(OPENROUTER_SESSION) == {
            "model": "moonshotai/kimi-k3", "response_id": "msg_u0wD",
            "isolation": {"cwd": "/private/tmp/empty", "tools_declared": [], "tool_use_events": 0,
                          "instruction_files": []},
        }

    def test_an_openrouter_session_that_loaded_house_files_and_tools_shows_them_in_the_proof(self):
        leaked = jsonl(
            {"type": "attachment", "cwd": "/repo", "attachment": {
                "type": "instructions", "files": [{"path": "/repo/AGENTS.md", "content": "x"}]}},
            {"type": "attachment", "attachment": {"type": "prompt_snapshot",
                                                  "tools": [{"name": "Read"}]}},
            {"type": "assistant", "message": {"id": "m", "model": "other", "content": [
                {"type": "tool_use", "name": "Read"}]}},
        )
        assert run_plan.openrouter_metadata(leaked)["isolation"] == {
            "cwd": "/repo", "tools_declared": ["Read"], "tool_use_events": 1,
            "instruction_files": ["/repo/AGENTS.md"],
        }

    def test_a_session_with_no_response_yields_no_model_and_no_response_id(self):
        assert run_plan.codex_metadata("")["response_id"] is None
        assert run_plan.openrouter_metadata("")["model"] is None

    def test_a_session_that_records_no_instruction_files_lists_none(self):
        assert run_plan.openrouter_metadata("")["isolation"]["instruction_files"] == []


RUN_BLOCK = {"model": "gpt-6.1-sol", "effort": "high", "response_id": "resp_1",
             "isolation": {"cwd": "/tmp/empty", "agents_md": {}, "agents_md_injections": 0}}
GOOD = {"output": EMPTY.replace("what-if", "behavioural-outcome"), "stderr": "", "exit": 0,
        "started": "2026-11-05T10:00:00Z", "ended": "2026-11-05T10:01:00Z", "metadata": RUN_BLOCK}
DEAD = {**GOOD, "output": "", "exit": 1, "metadata": {**RUN_BLOCK, "response_id": None}}
USAGE_LIMIT = {**DEAD, "stderr": "[codex] You've hit your usage limit. Try again at 4:24 PM."}


def planned(run_id="C1-control-1", **overrides):
    return {"run_id": run_id, "case": "C1", "document": "control", "lens": "behavioural-outcome",
            "transport": "codex", "model": "gpt-6.1-sol", "effort": "high", **overrides}


@pytest.fixture
def attempt(tmp_path):
    def write(*runs):
        (tmp_path / "plan.json").write_text(json.dumps(
            {"attempt": "a1", "config": {"thresholds": {"pass": 4}}, "runs": list(runs)}))
        return tmp_path / "plan.json"
    return write


class Fake:
    """A dispatcher answering each dispatch from a script of captured results, in order."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, run, prompt):
        self.calls.append(run["run_id"])
        return self.results.pop(0)


def reports(plan):
    return {path.name: json.loads(path.read_text())
            for path in sorted((plan.parent / "reports").glob("*.json"))}


class TestExecute:
    def test_each_planned_run_gets_one_report_with_the_scorer_fields(self, attempt):
        plan = attempt(planned("r1"), planned("r2", panel_run=2))
        fake = Fake(GOOD, GOOD)
        summary = run_plan.execute(plan, fake)
        assert fake.calls == ["r1", "r2"]
        assert summary == {"dispatched": ["r1", "r2"], "skipped": [], "pending": []}
        written = reports(plan)
        assert sorted(written) == ["r1.1.json", "r2.1.json"]
        assert written["r2.1.json"] == {
            **planned("r2", panel_run=2), "attempt": 1, "usable": True, "fault": None,
            "report": json.loads(GOOD["output"]), "malformed_objections": [],
            "run": {"transport": "codex", "model": "gpt-6.1-sol", "effort": "high",
                    "response_id": "resp_1", "started": GOOD["started"], "ended": GOOD["ended"],
                    "isolation": RUN_BLOCK["isolation"]},
        }

    def test_the_model_recorded_is_the_transports_and_never_the_plans(self, attempt):
        plan = attempt(planned("r1"))
        served = {**GOOD, "metadata": {**RUN_BLOCK, "model": "gpt-5-served"}}
        run_plan.execute(plan, Fake(served))
        assert reports(plan)["r1.1.json"]["run"]["model"] == "gpt-5-served"

    def test_a_run_with_no_usable_report_is_repeated_twice_and_every_report_stays(self, attempt):
        plan = attempt(planned("r1"))
        fake = Fake(DEAD, DEAD, GOOD)
        summary = run_plan.execute(plan, fake)
        written = reports(plan)
        assert fake.calls == ["r1", "r1", "r1"]
        assert sorted(written) == ["r1.1.json", "r1.2.json", "r1.3.json"]
        assert [written[f"r1.{n}.json"]["usable"] for n in (1, 2, 3)] == [False, False, True]
        assert summary["pending"] == []

    def test_a_third_unusable_report_leaves_the_run_pending_with_no_fourth_dispatch(self, attempt):
        plan = attempt(planned("r1"))
        fake = Fake(DEAD, DEAD, DEAD, GOOD)
        summary = run_plan.execute(plan, fake)
        assert fake.calls == ["r1", "r1", "r1"]
        assert summary["pending"] == ["r1"]
        assert reports(plan)["r1.3.json"]["fault"]

    def test_an_unusable_report_keeps_the_raw_output_for_the_reader(self, attempt):
        plan = attempt(planned("r1"))
        run_plan.execute(plan, Fake({**DEAD, "output": "half a thought"}, GOOD))
        assert reports(plan)["r1.1.json"]["raw_output"] == "half a thought"

    def test_a_report_with_no_response_id_is_not_usable(self, attempt):
        plan = attempt(planned("r1"))
        nameless = {**GOOD, "metadata": {**RUN_BLOCK, "response_id": None}}
        run_plan.execute(plan, Fake(nameless, GOOD))
        assert reports(plan)["r1.1.json"]["usable"] is False
        assert "response ID" in reports(plan)["r1.1.json"]["fault"]

    def test_a_restart_dispatches_no_run_holding_a_usable_report(self, attempt):
        plan = attempt(planned("r1"), planned("r2"), planned("r3"))
        run_plan.execute(plan, Fake(GOOD, DEAD, DEAD, DEAD, GOOD))
        fake = Fake()
        summary = run_plan.execute(plan, fake)
        assert fake.calls == []
        assert summary == {"dispatched": [], "skipped": ["r1", "r3"], "pending": ["r2"]}

    def test_a_restart_counts_the_repeats_an_earlier_process_spent(self, attempt):
        plan = attempt(planned("r1"))
        (plan.parent / "reports").mkdir()
        (plan.parent / "reports" / "r1.1.json").write_text(json.dumps({"usable": False}))
        (plan.parent / "reports" / "r1.2.json").write_text(json.dumps({"usable": False}))
        fake = Fake(DEAD, GOOD)
        run_plan.execute(plan, fake)
        assert fake.calls == ["r1"]
        assert "r1.4.json" not in reports(plan)

    def test_a_report_the_plan_does_not_name_causes_no_dispatch(self, attempt):
        plan = attempt(planned("r1"))
        (plan.parent / "reports").mkdir()
        (plan.parent / "reports" / "stray.1.json").write_text(json.dumps({"usable": False}))
        fake = Fake(GOOD)
        run_plan.execute(plan, fake)
        assert fake.calls == ["r1"]

    def test_a_down_transport_stops_the_walk_and_spends_no_repeat(self, attempt):
        plan = attempt(planned("r1"), planned("r2"), planned("r3"))
        fake = Fake(GOOD, USAGE_LIMIT, GOOD)
        with pytest.raises(run_plan.TransportDown, match="usage limit"):
            run_plan.execute(plan, fake)
        assert fake.calls == ["r1", "r2"]
        assert sorted(reports(plan)) == ["r1.1.json"]

    def test_a_clean_exit_that_mentions_a_limit_is_a_finished_run(self, attempt):
        plan = attempt(planned("r1"))
        run_plan.execute(plan, Fake({**GOOD, "stderr": "you are near your usage limit"}))
        assert reports(plan)["r1.1.json"]["usable"] is True

    def test_a_prompt_echo_holding_the_limit_words_is_not_a_down_transport(self, attempt):
        plan = attempt(planned("r1"))
        echoed = "the usage limit is in this document\n" + "more of the prompt\n" * 50
        fake = Fake({**DEAD, "stderr": echoed}, GOOD)
        run_plan.execute(plan, fake)
        assert fake.calls == ["r1", "r1"]
        assert reports(plan)["r1.1.json"]["usable"] is False

    def test_a_report_with_no_served_model_is_not_usable(self, attempt):
        plan = attempt(planned("r1"))
        unnamed = {**GOOD, "metadata": {**RUN_BLOCK, "model": None}}
        run_plan.execute(plan, Fake(unnamed, GOOD))
        assert "model" in reports(plan)["r1.1.json"]["fault"]

    def test_the_effort_recorded_is_the_transports_when_it_reports_one(self, attempt):
        plan = attempt(planned("r1"))
        run_plan.execute(plan, Fake({**GOOD, "metadata": {**RUN_BLOCK, "effort": "medium"}}))
        assert reports(plan)["r1.1.json"]["run"]["effort"] == "medium"

    @pytest.mark.parametrize("runs,word", [
        ([planned("r1"), planned("r1")], "twice"),
        ([planned("r1", transport="carrier-pigeon")], "transport"),
        ([planned("r1", case="C999")], "C999"),
        ([planned("r1", document="draft")], "draft"),
        ([{"run_id": "r1"}], "case"),
        ([planned("r1", lens="telepathy")], "telepathy"),
    ])
    def test_a_plan_that_cannot_be_walked_is_refused_before_any_dispatch(self, attempt, runs, word):
        plan = attempt(*runs)
        fake = Fake(GOOD, GOOD)
        with pytest.raises(run_plan.PlanRefused, match=word):
            run_plan.execute(plan, fake)
        assert fake.calls == []
        assert not (plan.parent / "reports").exists()

    def test_a_prompt_never_names_which_twin_it_holds(self, attempt):
        seen = {}

        def capture(run, prompt):
            seen[run["document"]] = prompt.read_text()
            return GOOD

        plan = attempt(planned("r1"), planned("r2", document="defective"))
        run_plan.execute(plan, capture)
        for text in seen.values():
            assert "control.md" not in text and "defective.md" not in text
        assert seen["control"] != seen["defective"]
        assert "Path: document.md" in seen["control"]


FAKE_HEAD = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
cwd = os.getcwd()
record = {"args": sys.argv[1:], "cwd": cwd, "cwd_holds": os.listdir(cwd),
          "stdin": sys.stdin.read()}
"""
FAKE_CODEX = FAKE_HEAD + """
home = Path(os.environ["CODEX_HOME"])
record["home"] = str(home)
record["home_holds"] = os.listdir(home)
Path(os.environ["FAKE_RECORD"]).write_text(json.dumps(record))
sessions = home / "sessions" / "2026"
sessions.mkdir(parents=True)
(sessions / "rollout-1-thread.jsonl").write_text(os.environ["FAKE_TRANSCRIPT"])
print(os.environ["FAKE_OUTPUT"])
"""
FAKE_LAUNCHER = FAKE_HEAD + """
Path(os.environ["FAKE_RECORD"]).write_text(json.dumps(record))
session = sys.argv[sys.argv.index("--session-id") + 1]
folder = Path(os.environ["CLAUDE_CONFIG_DIR_OPENROUTER"]) / "projects" / "some-project"
folder.mkdir(parents=True)
(folder / f"{session}.jsonl").write_text(os.environ["FAKE_TRANSCRIPT"])
print(os.environ["FAKE_OUTPUT"])
"""


def executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.fixture
def transport(tmp_path, monkeypatch):
    """Fake transports on the real command lines, each recording what it was launched with."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable(binaries / "codex", FAKE_CODEX)
    launcher = executable(binaries / "launcher", FAKE_LAUNCHER)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{binaries}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_RECORD", str(tmp_path / "record.json"))
    monkeypatch.setenv("FAKE_OUTPUT", EMPTY)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR_OPENROUTER", str(tmp_path / "or"))
    monkeypatch.setattr(run_plan, "LAUNCHER", [str(launcher)])
    prompt = tmp_path / "prompt.md"
    prompt.write_text("the prompt")

    def launched():
        return json.loads((tmp_path / "record.json").read_text())

    return prompt, launched


class TestDispatchers:
    def test_codex_runs_the_plans_model_and_effort_on_the_prompt_alone(self, transport, monkeypatch):
        prompt, launched = transport
        monkeypatch.setenv("FAKE_TRANSCRIPT", CODEX_ROLLOUT)
        run = planned(model="gpt-test", effort="medium")
        result = run_plan.dispatch_codex(run, prompt)
        seen = launched()
        assert seen["args"][:2] == ["exec", "-m"] and seen["args"][2] == "gpt-test"
        assert "model_reasoning_effort=medium" in seen["args"]
        assert "project_doc_max_bytes=0" in seen["args"]
        assert seen["stdin"] == "the prompt"
        assert result["output"].strip() == EMPTY
        assert result["exit"] == 0
        assert result["metadata"]["response_id"] == "resp_04a0"

    def test_codex_starts_in_an_empty_directory_under_a_home_holding_only_the_auth_file(
            self, transport, monkeypatch):
        prompt, launched = transport
        monkeypatch.setenv("FAKE_TRANSCRIPT", CODEX_ROLLOUT)
        run_plan.dispatch_codex(planned(), prompt)
        seen = launched()
        assert seen["cwd_holds"] == []
        assert seen["home_holds"] == ["auth.json"]
        assert HERE not in Path(seen["cwd"]).parents

    def test_codex_leaves_no_copy_of_the_auth_file_behind(self, transport, monkeypatch):
        prompt, launched = transport
        monkeypatch.setenv("FAKE_TRANSCRIPT", CODEX_ROLLOUT)
        run_plan.dispatch_codex(planned(), prompt)
        assert not Path(launched()["home"]).exists()

    def test_the_launcher_runs_the_plans_model_from_an_empty_directory_with_no_tools(
            self, transport, monkeypatch):
        prompt, launched = transport
        monkeypatch.setenv("FAKE_TRANSCRIPT", OPENROUTER_SESSION)
        run = planned(transport="openrouter", model="vendor/model", effort="low")
        result = run_plan.dispatch_openrouter(run, prompt)
        seen, args = launched(), launched()["args"]
        assert args[args.index("--model") + 1] == "vendor/model"
        assert args[args.index("--effort") + 1] == "low"
        assert args[args.index("--tools") + 1] == ""
        assert "--allowedTools=" in args
        assert args[args.index("-p") + 1] == "the prompt"
        assert seen["cwd_holds"] == []
        assert HERE not in Path(seen["cwd"]).parents
        assert result["output"].strip() == EMPTY
        assert result["metadata"]["response_id"] == "msg_u0wD"

    def test_a_dispatch_that_leaves_no_transcript_yields_no_response_id(self, transport, monkeypatch):
        prompt, _ = transport
        monkeypatch.setenv("FAKE_TRANSCRIPT", "")
        assert run_plan.dispatch_codex(planned(), prompt)["metadata"]["response_id"] is None


class TestCap:
    def test_a_run_that_ignores_the_term_signal_is_killed_with_its_children(self, tmp_path):
        pids = tmp_path / "pids"
        script = f"trap '' TERM; sleep 30 & echo $$ $! > {pids}; wait; sleep 30"
        result = run_plan.run_capped(["sh", "-c", script], tmp_path, dict(os.environ), None,
                                     cap=0.5, grace=0.2)
        assert result["exit"] != 0
        assert "cap" in result["stderr"]
        for pid in map(int, pids.read_text().split()):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)

    def test_a_run_at_the_cap_gets_the_term_signal_first(self, tmp_path):
        script = "trap 'echo closing; exit 0' TERM; sleep 30 & wait"
        result = run_plan.run_capped(["sh", "-c", script], tmp_path, dict(os.environ), None,
                                     cap=0.5, grace=5)
        assert "closing" in result["output"]

    def test_a_run_inside_its_cap_returns_its_output_and_status(self, tmp_path):
        result = run_plan.run_capped(["sh", "-c", "echo out; echo err >&2; exit 4"], tmp_path,
                                     dict(os.environ), None, cap=30)
        assert (result["output"], result["stderr"], result["exit"]) == ("out\n", "err\n", 4)
        assert result["started"].endswith("Z") and result["ended"].endswith("Z")


class TestCommandLine:
    def test_a_finished_walk_exits_zero_and_prints_its_summary(self, attempt, monkeypatch, capsys):
        plan = attempt(planned("r1"))
        monkeypatch.setitem(run_plan.TRANSPORTS, "codex", Fake(GOOD))
        assert run_plan.main([str(plan)]) == 0
        assert json.loads(capsys.readouterr().out)["dispatched"] == ["r1"]

    def test_a_refused_plan_exits_two_and_names_the_fault(self, attempt, capsys):
        plan = attempt(planned("r1", case="C999"))
        assert run_plan.main([str(plan)]) == 2
        assert "C999" in json.loads(capsys.readouterr().out)["refused"]

    def test_a_down_transport_exits_three_and_quotes_the_transport(self, attempt, monkeypatch, capsys):
        plan = attempt(planned("r1"))
        monkeypatch.setitem(run_plan.TRANSPORTS, "codex", Fake(USAGE_LIMIT))
        assert run_plan.main([str(plan)]) == 3
        assert "try again at 4:24" in json.loads(capsys.readouterr().out)["down"].lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
