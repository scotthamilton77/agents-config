"""Read one recorded probe run off disk and expose it as plain data.

Everything above this module is a pure function of a `Run`, which is what lets the
detectors be tested against recordings instead of against a live Claude Code session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .session import COMPLETED


@dataclass(frozen=True)
class Event:
    """One hook payload as the logging hook recorded it, with its position in the run."""

    index: int
    t: float
    payload: dict[str, Any]
    env: dict[str, str]
    team: dict[str, Any] | None

    @property
    def name(self) -> str:
        """Return the hook event name, or the empty string when the payload omits it."""
        value = self.payload.get("hook_event_name")
        return value if isinstance(value, str) else ""

    @property
    def tool_name(self) -> str:
        value = self.payload.get("tool_name")
        return value if isinstance(value, str) else ""

    @property
    def agent_id(self) -> str:
        value = self.payload.get("agent_id")
        return value if isinstance(value, str) else ""

    @property
    def agent_type(self) -> str:
        value = self.payload.get("agent_type")
        return value if isinstance(value, str) else ""

    @property
    def tool_input(self) -> dict[str, Any]:
        value = self.payload.get("tool_input")
        return value if isinstance(value, dict) else {}

    @property
    def tool_response(self) -> dict[str, Any]:
        value = self.payload.get("tool_response")
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class Run:
    """One recorded session: its events, whatever its lead wrote, and its side records."""

    directory: Path
    events: list[Event]
    lead_md: str = ""
    gate_decisions: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    driver_log: str = ""

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def version(self) -> str:
        """Return the Claude Code version string recorded for this run, or a placeholder."""
        value = self.meta.get("claude_version")
        return value if isinstance(value, str) and value else "unknown"

    @property
    def outcome(self) -> str:
        """Return how the run ended, or a marker for a directory that never recorded one."""
        value = self.meta.get("outcome")
        return value if isinstance(value, str) and value else "unrecorded"

    @property
    def valid(self) -> bool:
        """Whether this run measured anything.

        A run whose driver gave up before typing, or whose lead never reached its terminal
        state, did not run the scenario. Counting it as a run in which no behaviour
        appeared would read as a release having fixed something.
        """
        return self.outcome == COMPLETED

    @property
    def invalid_reason(self) -> str:
        """Return why this run does not count, in the driver's own words where it has them.

        The driver's closing note only repeats the outcome, so the line before it is the
        one that says what actually went wrong.
        """
        told = (
            line.strip()
            for line in reversed(self.driver_log.splitlines())
            if line.strip() and "session closed" not in line
        )
        last = next(told, "")
        return f"{self.outcome}: {last}" if last else self.outcome

    @property
    def team_members(self) -> list[str]:
        """Return the member names of the last team snapshot any hook captured.

        The snapshot grows as members join, so the last one is the only complete
        membership list in the recording. A member's `agentType` in that file is the
        subagent type it was spawned as, not its name, which is why only names are
        taken from here.
        """
        names: list[str] = []
        for event in reversed(self.events):
            if not event.team:
                continue
            members = event.team.get("members")
            if not isinstance(members, list):
                continue
            for member in members:
                if isinstance(member, dict) and isinstance(member.get("name"), str):
                    names.append(member["name"])
            break
        return names


def parse_events(text: str) -> list[Event]:
    """Parse the logging hook's JSONL, skipping blank lines and unreadable records."""
    events: list[Event] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        env = record.get("env")
        team = record.get("team")
        events.append(
            Event(
                index=len(events),
                t=float(record.get("t", 0.0)),
                payload=payload if isinstance(payload, dict) else {},
                env=env if isinstance(env, dict) else {},
                team=team if isinstance(team, dict) else None,
            )
        )
    return events


def parse_decisions(text: str) -> list[dict[str, Any]]:
    """Parse the report gate's decision log, skipping lines it has half-written."""
    decisions: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            decisions.append(record)
    return decisions


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_run(directory: Path) -> Run:
    """Load one run directory. Missing optional files leave their fields empty."""
    meta_text = _read(directory / "meta.json")
    try:
        meta = json.loads(meta_text) if meta_text.strip() else {}
    except json.JSONDecodeError:
        meta = {}
    return Run(
        directory=directory,
        events=parse_events(_read(directory / "events.jsonl")),
        lead_md=_read(directory / "lead.md"),
        gate_decisions=parse_decisions(_read(directory / "decisions.jsonl")),
        meta=meta if isinstance(meta, dict) else {},
        driver_log=_read(directory / "claude.err"),
    )


def load_runs(roots: list[Path]) -> list[Run]:
    """Load every run directory under the given paths.

    A path that holds an `events.jsonl` is itself a run; otherwise its immediate
    subdirectories that hold one are, which is how a `--out` directory of several runs
    is read with a single argument.
    """
    runs: list[Run] = []
    for root in roots:
        if (root / "events.jsonl").exists():
            runs.append(load_run(root))
            continue
        for child in sorted(p for p in root.iterdir() if p.is_dir()):
            if (child / "events.jsonl").exists():
                runs.append(load_run(child))
    return runs
