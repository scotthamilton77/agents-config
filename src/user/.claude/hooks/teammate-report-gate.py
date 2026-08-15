#!/usr/bin/env python3
"""Teammate lifecycle hook: gate task completion and idle exit on a delivered report.

A named teammate agent that composes its final report as a plain assistant
message delivers nothing — only an explicit call to the SendMessage tool
transmits content to the orchestrator, and the automatic idle notification
carries no report of its own. Left ungated, a teammate can mark its work done
and go idle having never sent anything the orchestrator can read.

This hook watches the teammate lifecycle for events that carry a non-empty
``teammate_name`` — TaskCompleted and TeammateIdle — and blocks each one until
either a progress update or a final report has been observed going out
through the SendMessage tool. TaskCompleted additionally passes once any
update has been seen since the last completion, on the theory that a teammate
mid-series of tasks is still reporting as it goes. Both blocks give up after a
short bounded number of retries rather than wedging the teammate forever.
Every other event — including both events without a ``teammate_name``, which
covers classic auto-returning subagents, workflow subagents, and main
sessions by construction — passes through untouched.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT_DEFAULT = Path("/tmp/claude/teammate-report-gate")

DEFAULT_STATE = {
    "updates_seen": 0,
    "completed_count": 0,
    "task_blocks": 0,
    "idle_blocks": 0,
    "final_delivered": False,
}

TASK_BLOCK_LIMIT = 2
IDLE_BLOCK_LIMIT = 3

NAME_RE = re.compile(r"[^A-Za-z0-9._-]")
SLUG_RE = re.compile(r"[^A-Za-z0-9]")
UPDATE_RE = re.compile(r"^\s*UPDATE\b", re.IGNORECASE)
# Anchored, but tolerant of leading markdown decoration ("**FINAL REPORT:**",
# "# FINAL REPORT") — a mid-sentence mention must not count as delivery.
FINAL_RE = re.compile(r"^[\s*_#>~`-]*FINAL REPORT\b", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def state_root() -> Path:
    override = os.environ.get("TEAMMATE_REPORT_GATE_STATE_ROOT")
    return Path(override) if override else STATE_ROOT_DEFAULT


def project_slug(cwd: str) -> str:
    return SLUG_RE.sub("-", cwd)


def safe_name(name: str) -> str:
    return NAME_RE.sub("_", name)


def state_dir(payload: dict) -> Path:
    cwd = str(payload.get("cwd") or "")
    session_id = str(payload.get("session_id") or "")
    return state_root() / project_slug(cwd) / session_id


def load_state(path: Path) -> dict:
    if not path.is_file():
        return dict(DEFAULT_STATE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)
    if not isinstance(data, dict):
        return dict(DEFAULT_STATE)
    return {
        "updates_seen": int(data.get("updates_seen", 0) or 0),
        "completed_count": int(data.get("completed_count", 0) or 0),
        "task_blocks": int(data.get("task_blocks", 0) or 0),
        "idle_blocks": int(data.get("idle_blocks", 0) or 0),
        "final_delivered": bool(data.get("final_delivered", False)),
    }


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def log_decision(directory: Path, event: str, name: str | None, decision: str, **extra) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    record = {"ts": now(), "event": event, "name": name, "decision": decision, **extra}
    with (directory / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def is_update(text: str) -> bool:
    return bool(UPDATE_RE.match(text or ""))


def is_final_report(text: str) -> bool:
    return bool(FINAL_RE.match(text or ""))


def read_stash(directory: Path, name: str) -> dict | None:
    path = directory / f"{safe_name(name)}.stop.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sender_from_response(payload: dict) -> str | None:
    tool_response = payload.get("tool_response")
    routing = tool_response.get("routing") if isinstance(tool_response, dict) else None
    if isinstance(routing, dict):
        sender = routing.get("sender")
        if isinstance(sender, str) and sender.strip():
            return sender.strip()
    agent_type = payload.get("agent_type")
    if isinstance(agent_type, str) and agent_type.strip():
        return agent_type.strip()
    return None


def message_from_input(payload: dict) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("message", "content"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def handle_post_tool_use(payload: dict) -> int:
    if payload.get("tool_name") != "SendMessage":
        return 0
    name = sender_from_response(payload)
    if name is None:
        return 0
    message = message_from_input(payload)
    if message is None:
        return 0
    directory = state_dir(payload)
    state_path = directory / f"{safe_name(name)}.json"
    state = load_state(state_path)
    # The UPDATE prefix wins: a progress message that merely mentions the final
    # report ("UPDATE 3: final report next") must not disarm the idle gate.
    if is_update(message):
        state["updates_seen"] += 1
        save_state(state_path, state)
        log_decision(directory, "PostToolUse", name, "update-observed",
                     updates_seen=state["updates_seen"])
    elif is_final_report(message):
        state["final_delivered"] = True
        state["idle_blocks"] = 0
        save_state(state_path, state)
        log_decision(directory, "PostToolUse", name, "final-report-observed")
    return 0


def handle_subagent_stop(payload: dict) -> int:
    agent_type = payload.get("agent_type")
    transcript_path = payload.get("agent_transcript_path")
    if not (isinstance(agent_type, str) and agent_type.strip()) or not transcript_path:
        return 0
    name = agent_type.strip()
    last_message = payload.get("last_assistant_message", "") or ""
    final_in_last = "final report" in last_message.lower()
    directory = state_dir(payload)
    stash_path = directory / f"{safe_name(name)}.stop.json"
    directory.mkdir(parents=True, exist_ok=True)
    stash_path.write_text(
        json.dumps({"transcript_path": transcript_path, "final_in_last_message": final_in_last}),
        encoding="utf-8",
    )
    log_decision(directory, "SubagentStop", name, "stashed", final_in_last_message=final_in_last)
    return 0


def handle_task_completed(payload: dict, name: str) -> int:
    directory = state_dir(payload)
    state_path = directory / f"{safe_name(name)}.json"
    state = load_state(state_path)
    if state["final_delivered"] or state["updates_seen"] > state["completed_count"]:
        state["completed_count"] += 1
        state["task_blocks"] = 0
        save_state(state_path, state)
        log_decision(directory, "TaskCompleted", name, "allow")
        return 0
    if state["task_blocks"] >= TASK_BLOCK_LIMIT:
        state["completed_count"] += 1
        state["task_blocks"] = 0
        save_state(state_path, state)
        log_decision(directory, "TaskCompleted", name, "allow-give-up")
        return 0
    state["task_blocks"] += 1
    save_state(state_path, state)
    log_decision(directory, "TaskCompleted", name, "block", task_blocks=state["task_blocks"])
    sys.stderr.write(
        f"send a progress update now by calling the SendMessage tool with a message beginning "
        f"'UPDATE {state['updates_seen'] + 1}:' — or, if this was the last task, send the full "
        "'FINAL REPORT:' message instead — then mark the task complete again.\n"
    )
    return 2


def handle_teammate_idle(payload: dict, name: str) -> int:
    directory = state_dir(payload)
    state_path = directory / f"{safe_name(name)}.json"
    state = load_state(state_path)
    if state["final_delivered"]:
        state["idle_blocks"] = 0
        save_state(state_path, state)
        log_decision(directory, "TeammateIdle", name, "allow")
        return 0
    stash = read_stash(directory, name)
    if state["idle_blocks"] >= IDLE_BLOCK_LIMIT:
        marker_path = directory / f"{safe_name(name)}.stop-noncompliance.marker"
        directory.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps({
                "ts": now(),
                "name": name,
                "idle_blocks": state["idle_blocks"],
                "transcript_path": (stash or {}).get("transcript_path"),
                "note": "the gate released the idle without a recognized FINAL REPORT — check "
                        "the agent's transcript for a stranded report",
            }),
            encoding="utf-8",
        )
        log_decision(directory, "TeammateIdle", name, "release-noncompliant",
                     idle_blocks=state["idle_blocks"])
        return 0
    state["idle_blocks"] += 1
    save_state(state_path, state)
    log_decision(directory, "TeammateIdle", name, "block", idle_blocks=state["idle_blocks"])
    if stash is not None and stash.get("final_in_last_message"):
        sys.stderr.write(
            "the composed report was not transmitted and must be resent: call the SendMessage "
            "tool addressed to your orchestrator with a message beginning 'FINAL REPORT:'.\n"
        )
    else:
        sys.stderr.write(
            "your composed text does NOT reach the orchestrator on its own — deliver the report "
            "now by calling the SendMessage tool addressed to your orchestrator with a message "
            "beginning 'FINAL REPORT:'.\n"
        )
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    event = payload.get("hook_event_name")
    if event == "PostToolUse":
        return handle_post_tool_use(payload)
    if event == "SubagentStop":
        return handle_subagent_stop(payload)

    name = payload.get("teammate_name")
    if not (isinstance(name, str) and name.strip()):
        return 0
    name = name.strip()

    if event == "TaskCompleted":
        return handle_task_completed(payload, name)
    if event == "TeammateIdle":
        return handle_teammate_idle(payload, name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
