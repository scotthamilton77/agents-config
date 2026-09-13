"""Detectors: pure functions from one recorded run to hit-or-miss plus the evidence.

A detector never judges. It reports whether the behaviour it names was observed in the
run and points at the events that show it, so a rate across runs can be read against a
Claude Code version.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .events import Event, Run

# A teammate idle that follows a different agent's stop this closely is the pairing the
# phantom-idle behaviour is made of. Three seconds is wide enough for the observed 0.3 to
# 0.6 second gap and narrow enough not to reach the teammate's own later stop.
PHANTOM_IDLE_WINDOW_SECONDS = 3.0

# The gate writes decisions with one-second resolution, so a decision and the hook event
# that provoked it can land a second apart in either direction.
GATE_MATCH_TOLERANCE_SECONDS = 2.0

WRITE_GUARD_ERROR = (
    "Subagents should return findings as text, not write report files. "
    "Include this content in your final response instead."
)

GUARDED_BASENAMES = ("report.md", "summary.md", "notes-report.md", "report.txt")


@dataclass(frozen=True)
class Finding:
    """One detector's verdict on one run, with the evidence a reader needs to check it."""

    behaviour: str
    hit: bool
    evidence: str


def _send_messages(run: Run, hook: str) -> list[Event]:
    return [e for e in run.events if e.name == hook and e.tool_name == "SendMessage"]


def _recipient(event: Event) -> str:
    value = event.tool_input.get("to")
    return value if isinstance(value, str) else ""


def _routing_sender(event: Event) -> str:
    routing = event.tool_response.get("routing")
    if not isinstance(routing, dict):
        return ""
    value = routing.get("sender")
    return value if isinstance(value, str) else ""


def _succeeded(event: Event) -> bool:
    return bool(event.tool_response.get("success"))


def _response_message(event: Event) -> str:
    value = event.tool_response.get("message")
    return value if isinstance(value, str) else ""


def phantom_idle(run: Run) -> Finding:
    """A teammate goes idle right after some *other* agent stopped, not after its own turn.

    The teammate is blocked inside a foreground Agent call at that moment, so the idle
    reports a state the teammate is not in.
    """
    stops = [e for e in run.events if e.name == "SubagentStop"]
    hits: list[str] = []
    for idle in (e for e in run.events if e.name == "TeammateIdle"):
        teammate = idle.payload.get("teammate_name")
        if not isinstance(teammate, str) or not teammate:
            continue
        preceding = [s for s in stops if s.t <= idle.t]
        if not preceding:
            continue
        nearest = preceding[-1]
        if idle.t - nearest.t > PHANTOM_IDLE_WINDOW_SECONDS:
            continue
        # An empty agent_type marks one of Claude Code's internal agents, which stop
        # constantly and would pair with anything.
        if not nearest.agent_type or nearest.agent_type == teammate:
            continue
        hits.append(
            f"idle[{idle.index}] {teammate} {idle.t - nearest.t:.2f}s after "
            f"stop[{nearest.index}] of {nearest.agent_type}"
        )
    return Finding(
        "phantom-idle", bool(hits), "; ".join(hits) or "no teammate idle followed another agent's stop"
    )


def team_lead_reachable(run: Run) -> Finding:
    """Whether an agent addressing the alias `team-lead` actually reached the lead."""
    sends = [e for e in _send_messages(run, "PostToolUse") if _recipient(e) == "team-lead"]
    if not sends:
        return Finding("team-lead-reachable", False, "nothing addressed team-lead")
    notes = [f"post[{e.index}] success={_succeeded(e)} {_response_message(e)!r}" for e in sends]
    return Finding("team-lead-reachable", any(_succeeded(e) for e in sends), "; ".join(notes))


def main_send_lacks_sender(run: Run) -> Finding:
    """A send to `main` comes back without routing, so the recipient cannot see who sent it.

    Sends to a named agent carry `routing.sender`; the reply for `main` carries only a
    queued-for-next-turn acknowledgement, which is why the lead's own record of an
    arrival has to guess at the sender.
    """
    hits: list[str] = []
    for event in _send_messages(run, "PostToolUse"):
        if _recipient(event) != "main" or _routing_sender(event):
            continue
        hits.append(
            f"post[{event.index}] agent_id={event.agent_id or '<absent>'} "
            f"agent_type={event.agent_type or '<absent>'} response={_response_message(event)!r}"
        )
    return Finding(
        "main-send-lacks-sender", bool(hits), "; ".join(hits) or "every send to main carried routing.sender"
    )


def missing_posttooluse(run: Run) -> Finding:
    """A SendMessage whose PreToolUse fired and whose PostToolUse never did.

    The tool call either never completed or completed without the hook firing; either way
    the run has no record of what the send returned.
    """
    posts = {e.payload.get("tool_use_id") for e in _send_messages(run, "PostToolUse")}
    hits: list[str] = []
    for event in _send_messages(run, "PreToolUse"):
        tool_use_id = event.payload.get("tool_use_id")
        if tool_use_id in posts:
            continue
        hits.append(f"pre[{event.index}] to={_recipient(event)!r} tool_use_id={tool_use_id}")
    return Finding(
        "missing-posttooluse", bool(hits), "; ".join(hits) or "every SendMessage PreToolUse had a PostToolUse"
    )


def child_to_parent_by_name(run: Run) -> Finding:
    """A subagent addresses its parent teammate by name, and the parent is resumed by it.

    The child is not a team member, so the message reaching the member's inbox and
    waking it is a route the team membership does not describe.
    """
    members = set(run.team_members)
    hits: list[str] = []
    for event in _send_messages(run, "PostToolUse"):
        recipient = _recipient(event)
        sender_type = event.agent_type
        if recipient not in members or not sender_type or sender_type in members:
            continue
        if not _succeeded(event):
            continue
        resumed = next(
            (
                e
                for e in run.events
                if e.name == "SubagentStart" and e.agent_type == recipient and e.index > event.index
            ),
            None,
        )
        if resumed is None:
            continue
        hits.append(
            f"post[{event.index}] {sender_type} -> {recipient} {_response_message(event)!r}, "
            f"resumed at start[{resumed.index}] agent_id={resumed.agent_id}"
        )
    return Finding(
        "child-to-parent-by-name", bool(hits), "; ".join(hits) or "no child send to a team member resumed it"
    )


def _lead_lines(run: Run) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in run.lead_md.splitlines():
        line = raw.strip()
        if not line:
            continue
        sender, separator, text = line.partition("|")
        lines.append((sender.strip(), text.strip()) if separator else ("", line))
    return lines


def duplicate_arrival(run: Run) -> Finding:
    """The same message text lands in the lead's record more than once."""
    counts: dict[str, list[str]] = {}
    for sender, text in _lead_lines(run):
        counts.setdefault(text, []).append(sender or "<no sender>")
    hits = [
        f"{text!r} arrived {len(senders)}x from {', '.join(senders)}"
        for text, senders in counts.items()
        if len(senders) > 1
    ]
    return Finding(
        "duplicate-arrival", bool(hits), "; ".join(hits) or "every line in the lead's record is unique"
    )


def _gate_timestamp(decision: dict[str, object]) -> float | None:
    raw = decision.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def gate_phantom_blocks(run: Run) -> Finding:
    """Report-gate blocks provoked by a phantom idle rather than by a real end of turn.

    Each such block holds a teammate that was never idle, and the run of blocks ends with
    the gate releasing it as noncompliant.
    """
    phantom = phantom_idle(run)
    if not phantom.hit or not run.gate_decisions:
        return Finding(
            "gate-phantom-blocks",
            False,
            "no phantom idle, or no gate decision log in this run",
        )
    idle_times = [
        e.t for e in run.events if e.name == "TeammateIdle" and f"idle[{e.index}]" in phantom.evidence
    ]
    hits: list[str] = []
    for decision in run.gate_decisions:
        if decision.get("decision") not in ("block", "release-noncompliant"):
            continue
        when = _gate_timestamp(decision)
        if when is None:
            continue
        if any(abs(when - t) <= GATE_MATCH_TOLERANCE_SECONDS for t in idle_times):
            hits.append(f"{decision.get('decision')} for {decision.get('name')} at {decision.get('ts')}")
    return Finding(
        "gate-phantom-blocks",
        bool(hits),
        f"{len(hits)} decision(s): " + "; ".join(hits)
        if hits
        else "no gate decision coincided with a phantom idle",
    )


def _basename(path: object) -> str:
    if not isinstance(path, str):
        return ""
    return path.rsplit("/", 1)[-1]


def _mentions(text: str) -> list[tuple[str, str]]:
    """Split an agent's report into what it said about each report-shaped filename.

    An agent lists every attempt on one line, so a mention runs until the next filename is
    named. The boundary before a name keeps `report.md` from matching inside
    `notes-report.md`.
    """
    found: list[tuple[int, str]] = []
    for name in GUARDED_BASENAMES:
        for match in re.finditer(rf"(?<![\w.-]){re.escape(name)}", text):
            found.append((match.start(), name))
    found.sort()
    return [
        (name, text[start : found[i + 1][0] if i + 1 < len(found) else len(text)])
        for i, (start, name) in enumerate(found)
    ]


def report_file_guard(run: Run) -> Finding:
    """Which report-shaped filenames a subagent's Write was refused for.

    The refusal happens above the hook layer: a blocked Write produces no hook event at
    all, not even a PreToolUse. The only record of it is the agent's own account, which
    the scenario has the lead write down. A Write that did land leaves a PostToolUse, and
    that is the harder evidence of the two, so it wins where both exist.
    """
    written = {
        _basename(e.tool_input.get("file_path")): e
        for e in run.events
        if e.name == "PostToolUse" and e.tool_name == "Write"
    }
    notes: list[str] = []
    blocked_any = False
    for name in GUARDED_BASENAMES:
        post = written.get(name)
        if post is not None:
            notes.append(f"{name}: allowed, written at post[{post.index}]")
            continue
        refused = [
            segment
            for mentioned, segment in _mentions(run.lead_md)
            if mentioned == name and WRITE_GUARD_ERROR in segment
        ]
        if refused:
            blocked_any = True
            notes.append(f"{name}: blocked, refused with the guard wording in {len(refused)} report(s)")
    if not notes:
        return Finding("report-file-guard", False, "no guarded basename was written or reported on")
    return Finding("report-file-guard", blocked_any, "; ".join(notes))


DETECTORS: tuple[Callable[[Run], Finding], ...] = (
    phantom_idle,
    team_lead_reachable,
    main_send_lacks_sender,
    missing_posttooluse,
    child_to_parent_by_name,
    duplicate_arrival,
    gate_phantom_blocks,
    report_file_guard,
)


def detect_all(run: Run) -> list[Finding]:
    """Run every detector over one run, in the order they are reported."""
    return [detector(run) for detector in DETECTORS]
