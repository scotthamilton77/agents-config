#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Dispatch the lens runs an evaluation plan names and write one report per dispatch.

Usage: uv run run_plan.py <plan.json>

The plan is a JSON object whose `runs` list names every dispatch: `run_id`, `case`, `document`
(`control` or `defective`), `lens`, `transport`, `model` and `effort`, and `panel_run` where runs
group into a panel. Its other keys belong to the planner and the scorer. Reports land in `reports/`
beside the plan as `<run_id>.<n>.json`, where n counts the run's dispatches.

The executor decides nothing about what a run means: it neither scores nor judges, dispatches only
the runs the plan names, and never commits. A run holding a usable report is skipped, so a restart
resumes. A run with no usable report is repeated at most twice, and each earlier report stays.

Stdout is JSON. Exit 0 once every run holds a usable report or has spent its repeats, 2 on a plan
that cannot be walked, 3 when a transport is down, in which case running it again later resumes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL))

import assemble_record  # noqa: E402
import emit_prompts  # noqa: E402

CASES = HERE / "cases"
DOCUMENTS = ("control", "defective")
MAX_DISPATCHES = 3
REQUIRED_KEYS = ("run_id", "case", "document", "lens", "transport", "model", "effort")
# A provider that did not serve the run is not a lens that failed. The evaluation waits for it, so
# such a death writes no report and spends no repeat. Codex says so with a usage limit or a model at
# capacity, and the launcher's proxy with a line about the upstream: spent credits, a refused
# connection, a timeout or a stream cut short. Only the tail of stderr is read, since Codex echoes
# the whole prompt there and a document may hold these words.
DOWN = re.compile(r"usage limit|at capacity|\[proxy\] (WARNING: )?upstream")
# The launcher exits with this status when it refuses the invocation itself, such as a missing key.
# Another dispatch would be refused the same way, so it stops the walk too.
LAUNCHER_REFUSED = 78
STDERR_TAIL_LINES = 20
# A lens run takes minutes on either transport, so a run past these is dead rather than slow. The
# next dispatch of the run is what recovers it.
CODEX_CAP_SECONDS = 900
OPENROUTER_CAP_SECONDS = 1200
KILL_GRACE_SECONDS = 30
LAUNCHER = ["node", str(SKILL.parent / "openrouter-claude-subagent" / "scripts" / "run.js")]
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_DOWN = 3

Dispatch = Callable[[dict[str, Any], Path], dict[str, Any]]


class PlanRefused(Exception):
    """The plan cannot be walked, and nothing was dispatched."""


class TransportDown(Exception):
    """A transport refused a run for want of capacity, and the walk stopped there."""


def read_report(lens: str, text: str) -> dict[str, Any]:
    """A lens's final message read as a report, with the fault that makes it unusable, if any.

    The report is kept as the lens wrote it, so each objection's rule and site citations reach the
    scorer untouched. A malformed objection stays in place and is named by its position.
    """
    try:
        report = assemble_record.parse_report(lens, text)
    except assemble_record.Refusal as exc:
        reason = "the output holds no JSON report" if exc.code == "unparseable-lens-output" \
            else exc.args[0]
        return {"report": None, "malformed_objections": [], "fault": reason}
    try:
        _, items = assemble_record.report_shape(lens, report)
    except assemble_record.Refusal as exc:
        return {"report": report, "malformed_objections": [], "fault": exc.args[0]}
    malformed = [position for position, item in enumerate(items, 1)
                 if _malformed(lens, position, item)]
    fault = None
    if items and len(malformed) == len(items):
        fault = "every objection in the report is malformed"
    return {"report": report, "malformed_objections": malformed, "fault": fault}


def _malformed(lens: str, position: int, item: Any) -> bool:
    try:
        return assemble_record.normalise(lens, position, item, None, []) is None
    except assemble_record.Refusal:
        return True


def _records(text: str) -> list[dict[str, Any]]:
    """The JSON objects of a transcript, one per line, skipping a line a killed run left cut off."""
    records = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def codex_metadata(rollout: str) -> dict[str, Any]:
    """The model, effort and response ID a Codex transcript records, and its isolation proof."""
    found: dict[str, Any] = {"model": None, "effort": None, "response_id": None}
    isolation: dict[str, Any] = {"cwd": None, "agents_md": None,
                                 "agents_md_injections": rollout.count("AGENTS.md instructions")}
    for record in _records(rollout):
        kind, payload = record.get("type"), record.get("payload") or {}
        if kind == "session_meta":
            isolation["cwd"] = payload.get("cwd")
        elif kind == "world_state":
            isolation["agents_md"] = (payload.get("state") or {}).get("agents_md")
        elif kind == "turn_context":
            found["model"], found["effort"] = payload.get("model"), payload.get("effort")
        elif kind == "token_usage_record":
            found["response_id"] = payload.get("response_id")
    return {**found, "isolation": isolation}


def openrouter_metadata(session: str) -> dict[str, Any]:
    """The model and response ID a launcher session records, and its isolation proof.

    A run from inside a checkout loads the instruction files above its directory, and an empty tool
    declaration says nothing about that, so the proof lists the files the session loaded.
    """
    found: dict[str, Any] = {"model": None, "response_id": None}
    isolation: dict[str, Any] = {"cwd": None, "tools_declared": None, "tool_use_events": 0,
                                 "instruction_files": []}
    for record in _records(session):
        isolation["cwd"] = record.get("cwd") or isolation["cwd"]
        attachment = record.get("attachment") or {}
        if attachment.get("type") == "instructions":
            isolation["instruction_files"] = [file["path"] for file in attachment.get("files", [])]
        # A session's first snapshot is written before its tools are, and carries no such key.
        elif attachment.get("type") == "prompt_snapshot" and "tools" in attachment:
            isolation["tools_declared"] = [tool["name"] if isinstance(tool, dict) else tool
                                           for tool in attachment["tools"]]
        if record.get("type") == "assistant":
            message = record.get("message") or {}
            found["model"], found["response_id"] = message.get("model"), message.get("id")
            content = message.get("content") or []
            isolation["tool_use_events"] += sum(block.get("type") == "tool_use"
                                                for block in content)
    return {**found, "isolation": isolation}


def load_plan(path: Path) -> list[dict[str, Any]]:
    """The plan's runs, refused whole when any of them could not be dispatched."""
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PlanRefused(f"cannot read the runs of the plan {path}: {exc}") from exc
    lenses = {lens["lens"] for lens in emit_prompts.load_lenses()}
    seen: set[str] = set()
    for run in runs:
        missing = [key for key in REQUIRED_KEYS if key not in run]
        if missing:
            raise PlanRefused(f"run {run.get('run_id')!r} lacks {', '.join(missing)}")
        name = run["run_id"]
        if name in seen:
            raise PlanRefused(f"the plan names run {name!r} twice")
        seen.add(name)
        if run["transport"] not in TRANSPORTS:
            raise PlanRefused(f"run {name!r} names the unknown transport {run['transport']!r}")
        if run["lens"] not in lenses:
            raise PlanRefused(f"run {name!r} names the unknown lens {run['lens']!r}")
        if run["document"] not in DOCUMENTS or not document_of(run).is_file():
            raise PlanRefused(f"run {name!r} names {run['case']}/{run['document']}, "
                              "which the catalogue does not hold")
    return runs


def document_of(run: dict[str, Any]) -> Path:
    return CASES / run["case"] / f"{run['document']}.md"


def emit_prompt(run: dict[str, Any], workspace: Path) -> Path:
    """Emit the run's prompt from a copy of its document under a name that says nothing.

    The emitter prints the document's file name in the prompt, and a lens told it is reading
    `control.md` has been told the answer.
    """
    document = workspace / "document.md"
    document.write_bytes(document_of(run).read_bytes())
    emitted = emit_prompts.emit(argparse.Namespace(spec=str(document), lens=run["lens"],
                                                   out_dir=str(workspace / "prompt")))
    return Path(emitted["prompts"][0])


def _stderr_tail(stderr: str) -> str:
    return "\n".join(stderr.splitlines()[-STDERR_TAIL_LINES:])


def report_of(run: dict[str, Any], number: int, result: dict[str, Any]) -> dict[str, Any]:
    """The report one dispatch leaves: the planned run, the lens's report and the transport's run."""
    parsed = read_report(run["lens"], result["output"])
    metadata = result["metadata"]
    fault = parsed["fault"]
    if fault is None and not metadata.get("response_id"):
        fault = "the transport recorded no response ID"
    if fault is None and not metadata.get("model"):
        fault = "the transport recorded no model"
    report = {
        **run, "attempt": number, "usable": fault is None, "fault": fault,
        "report": parsed["report"], "malformed_objections": parsed["malformed_objections"],
        "run": {"transport": run["transport"], "model": metadata.get("model"),
                "effort": metadata.get("effort", run["effort"]),
                "response_id": metadata.get("response_id"), "started": result["started"],
                "ended": result["ended"], "isolation": metadata.get("isolation")},
    }
    if fault is not None:
        report |= {"raw_output": result["output"], "exit": result["exit"],
                   "stderr_tail": _stderr_tail(result["stderr"])}
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    """Write through a rename, so a run stopped mid-write leaves no half a report to read back."""
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, path)


def execute(plan: Path, dispatch: Dispatch | None = None) -> dict[str, list[str]]:
    """Walk the plan's runs in order, dispatching what still lacks a usable report."""
    runs = load_plan(plan)
    reports = plan.parent / "reports"
    reports.mkdir(exist_ok=True)
    summary: dict[str, list[str]] = {"dispatched": [], "skipped": [], "pending": []}
    for run in runs:
        name = run["run_id"]
        paths = [reports / f"{name}.{n}.json" for n in range(1, MAX_DISPATCHES + 1)]
        held = [path for path in paths if path.exists()]
        if any(json.loads(path.read_text(encoding="utf-8")).get("usable") for path in held):
            summary["skipped"].append(name)
            continue
        usable = False
        for number in range(len(held) + 1, MAX_DISPATCHES + 1):
            with tempfile.TemporaryDirectory() as workspace:
                prompt = emit_prompt(run, Path(workspace))
                result = (dispatch or TRANSPORTS[run["transport"]])(run, prompt)
            tail = _stderr_tail(result["stderr"])
            if result["exit"] == LAUNCHER_REFUSED or (result["exit"] != 0 and DOWN.search(tail)):
                raise TransportDown(f"{run['transport']} is down at run {name!r}: {tail}")
            report = report_of(run, number, result)
            _write_report(reports / f"{name}.{number}.json", report)
            if name not in summary["dispatched"]:
                summary["dispatched"].append(name)
            usable = report["usable"]
            if usable:
                break
        if not usable:
            summary["pending"].append(name)
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_capped(command: list[str], cwd: Path, env: dict[str, str], stdin: Path | None, cap: float,
               grace: float = KILL_GRACE_SECONDS) -> dict[str, Any]:
    """Run one command in its own process group, and kill the whole group at the cap.

    A launcher can survive the term signal, so the kill signal always follows it, and it goes to
    the group because the launcher's children outlive a signal sent to the launcher alone. The
    group runs in a session of its own, so an interrupt at the terminal never reaches it, and the
    executor stops it the same way when it is itself interrupted. Output goes to files, since a
    pipe a surviving child still holds would block the read past the cap.
    """
    started = _now()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, \
            (open(stdin, "rb") if stdin else open(os.devnull, "rb")) as source:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=source, stdout=out, stderr=err,
                                   start_new_session=True)
        capped = False
        try:
            process.wait(timeout=cap)
        except subprocess.TimeoutExpired:
            capped = True
            _stop(process, grace)
        except BaseException:
            _stop(process, grace)
            raise
        out.seek(0)
        err.seek(0)
        output = out.read().decode("utf-8", errors="replace")
        stderr = err.read().decode("utf-8", errors="replace")
    if capped:
        stderr += f"\nkilled at the cap of {cap} seconds\n"
    return {"output": output, "stderr": stderr, "exit": process.returncode, "started": started,
            "ended": _now()}


def _stop(process: subprocess.Popen, grace: float) -> None:
    """Ask the process group to end, give it the grace period, then kill whatever is left."""
    for sent in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sent)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    process.wait()


def exit_on_term() -> None:
    """Make the term signal end the executor through its cleanup, as an interrupt does."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))


def dispatch_codex(run: dict[str, Any], prompt: Path) -> dict[str, Any]:
    """One Codex run that reads its prompt and nothing else.

    It starts in an empty directory under a private home holding only the auth file, with project
    instruction files disabled. The Codex companion cannot give such a run: it walks up to the
    workspace root, and Codex loads the user-level instruction file from any directory. The private
    home goes when the run ends, so no copy of the auth file outlives it.
    """
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
        shutil.copy(Path.home() / ".codex" / "auth.json", home)
        result = run_capped(
            ["codex", "exec", "-m", run["model"], "-c", f"model_reasoning_effort={run['effort']}",
             "-c", "project_doc_max_bytes=0", "--skip-git-repo-check", "-"],
            Path(cwd), {**os.environ, "CODEX_HOME": home}, prompt, CODEX_CAP_SECONDS)
        rollout = next(Path(home).rglob("rollout-*.jsonl"), None)
        transcript = rollout.read_text(encoding="utf-8", errors="replace") if rollout else ""
    return {**result, "metadata": codex_metadata(transcript)}


def dispatch_openrouter(run: dict[str, Any], prompt: Path) -> dict[str, Any]:
    """One launcher run that reads its prompt and nothing else.

    It starts in an empty directory outside any checkout, because the client loads every
    instruction file on the way up from its directory. `--tools ""` empties the tool declaration,
    which an empty allowed-tools list alone leaves in place.
    """
    session = str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as cwd:
        result = run_capped(
            [*LAUNCHER, "--model", run["model"], "--effort", run["effort"],
             "--permission-mode", "dontAsk", "--allowedTools=", "--tools", "",
             "--session-id", session, "-p", prompt.read_text(encoding="utf-8")],
            Path(cwd), dict(os.environ), None, OPENROUTER_CAP_SECONDS)
    config = os.environ.get("CLAUDE_CONFIG_DIR_OPENROUTER") or Path.home() / ".claude_openrouter"
    transcript = next(Path(config).glob(f"projects/*/{session}.jsonl"), None)
    text = transcript.read_text(encoding="utf-8", errors="replace") if transcript else ""
    return {**result, "metadata": openrouter_metadata(text)}


TRANSPORTS: dict[str, Dispatch] = {"codex": dispatch_codex, "openrouter": dispatch_openrouter}


def main(argv: list[str]) -> int:
    """Walk the plan on the command line, print the outcome as JSON and exit with its status."""
    parser = argparse.ArgumentParser(description="Dispatch the runs an evaluation plan names.")
    parser.add_argument("plan", type=Path)
    plan = parser.parse_args(argv).plan
    exit_on_term()
    try:
        outcome, status = execute(plan), EXIT_OK
    except PlanRefused as exc:
        outcome, status = {"refused": str(exc)}, EXIT_REFUSED
    except TransportDown as exc:
        outcome, status = {"down": str(exc)}, EXIT_DOWN
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
