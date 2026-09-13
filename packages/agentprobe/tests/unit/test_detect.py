"""Detector tests against recorded runs. Nothing here launches Claude Code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentprobe import detect
from agentprobe.events import Event, Run

SYNTHETIC = Path("/nowhere/synthetic")


def test_phantom_idle_counts_only_the_idles_that_followed_the_child_stops(run2: Run) -> None:
    finding = detect.phantom_idle(run2)
    assert finding.hit
    idles = [part for part in finding.evidence.split("; ")]
    assert len(idles) == 4, finding.evidence
    assert [part.split("]")[0] for part in idles] == ["idle[24", "idle[30", "idle[32", "idle[36"]
    assert all("of general-purpose" in part for part in idles)


def test_phantom_idle_ignores_the_teammates_own_idles(run2: Run) -> None:
    # The teammate stops twice on its own account, at event 46 and event 54, and an idle
    # follows each. Those are the teammate genuinely finishing a turn, not a phantom.
    evidence = detect.phantom_idle(run2).evidence
    assert "idle[47" not in evidence
    assert "idle[56" not in evidence


def test_phantom_idle_ignores_internal_agents_with_no_agent_type() -> None:
    run = Run(
        SYNTHETIC,
        events=_events(
            [
                {"hook_event_name": "SubagentStop", "agent_type": ""},
                {"hook_event_name": "TeammateIdle", "teammate_name": "alpha"},
            ]
        ),
    )
    assert not detect.phantom_idle(run).hit


def test_phantom_idle_ignores_an_idle_that_arrives_too_late() -> None:
    run = Run(
        SYNTHETIC,
        events=_events(
            [
                {"hook_event_name": "SubagentStop", "agent_type": "general-purpose"},
                {"hook_event_name": "TeammateIdle", "teammate_name": "alpha"},
            ],
            times=[0.0, detect.PHANTOM_IDLE_WINDOW_SECONDS + 1],
        ),
    )
    assert not detect.phantom_idle(run).hit


def test_team_lead_is_reachable_in_the_recording(run2: Run) -> None:
    finding = detect.team_lead_reachable(run2)
    assert finding.hit
    assert "Message sent to team-lead's inbox" in finding.evidence


def test_team_lead_reachable_misses_when_nothing_addressed_it() -> None:
    assert not detect.team_lead_reachable(Run(SYNTHETIC, events=[])).hit


def test_main_send_lacks_sender(run2: Run) -> None:
    finding = detect.main_send_lacks_sender(run2)
    assert finding.hit
    # The sends that came from the child and the teammate carry the agent identity on the
    # hook payload even though the response does not name a sender.
    assert "post[19] agent_id=a023ac22723443253 agent_type=general-purpose" in finding.evidence
    assert "Message queued for the main conversation's next turn." in finding.evidence


def test_every_sendmessage_in_the_recording_had_a_posttooluse(run2: Run) -> None:
    finding = detect.missing_posttooluse(run2)
    assert not finding.hit
    assert finding.evidence == "every SendMessage PreToolUse had a PostToolUse"


def test_missing_posttooluse_names_the_unanswered_call() -> None:
    run = Run(
        SYNTHETIC,
        events=_events(
            [
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "SendMessage",
                    "tool_use_id": "toolu_x",
                    "tool_input": {"to": "alpha"},
                }
            ]
        ),
    )
    finding = detect.missing_posttooluse(run)
    assert finding.hit
    assert "toolu_x" in finding.evidence


def test_child_addresses_its_parent_teammate_by_name_and_resumes_it(run2: Run) -> None:
    finding = detect.child_to_parent_by_name(run2)
    assert finding.hit
    assert "general-purpose -> alpha" in finding.evidence
    assert "Message sent to alpha's inbox" in finding.evidence
    assert "resumed at start[48] agent_id=aalpha-c8267631911921b7" in finding.evidence


def test_no_duplicate_arrivals_in_the_recording(run2: Run) -> None:
    assert not detect.duplicate_arrival(run2).hit


def test_duplicate_arrival_names_both_senders() -> None:
    run = Run(SYNTHETIC, events=[], lead_md="alpha | hello\nteam-lead | hello\n")
    finding = detect.duplicate_arrival(run)
    assert finding.hit
    assert "arrived 2x from alpha, team-lead" in finding.evidence


def test_gate_blocks_coincide_with_the_phantom_idles(run2: Run) -> None:
    finding = detect.gate_phantom_blocks(run2)
    assert finding.hit
    assert finding.evidence.startswith("4 decision(s)")
    assert finding.evidence.count("block for alpha") == 3
    assert "release-noncompliant for alpha" in finding.evidence


def test_gate_phantom_blocks_misses_without_a_decision_log(run2: Run) -> None:
    stripped = Run(run2.directory, events=run2.events, lead_md=run2.lead_md, meta=run2.meta)
    assert not detect.gate_phantom_blocks(stripped).hit


def test_the_guard_is_read_from_what_the_agents_reported(guard_run: Run) -> None:
    # A refused Write produces no hook event at all, not even a PreToolUse: the guard sits
    # above the hook layer. The agents' own reports, which the lead wrote down, are the
    # only record that the attempt happened.
    attempted = [
        e
        for e in guard_run.events
        if e.name == "PreToolUse"
        and e.tool_name == "Write"
        and str(e.tool_input.get("file_path", "")).endswith("/report.md")
    ]
    assert attempted == []
    finding = detect.report_file_guard(guard_run)
    assert finding.hit
    assert "report.md: blocked, refused with the guard wording in 2 report(s)" in finding.evidence
    assert "summary.md: blocked, refused with the guard wording in 2 report(s)" in finding.evidence
    # The guard covers markdown only, so the same stem with another extension goes through.
    assert "report.txt: allowed, written at post[" in finding.evidence
    assert "notes-report.md: allowed, written at post[" in finding.evidence


def test_a_guarded_name_inside_a_longer_name_is_not_mistaken_for_it() -> None:
    run = Run(SYNTHETIC, events=[], lead_md=f"beta | notes-report.md: {detect.WRITE_GUARD_ERROR}")
    finding = detect.report_file_guard(run)
    segments = finding.evidence.split("; ")
    assert "notes-report.md: blocked, refused with the guard wording in 1 report(s)" in segments
    assert not any(segment.startswith("report.md:") for segment in segments)


def test_a_write_that_landed_outweighs_a_report_that_it_did_not() -> None:
    run = Run(
        SYNTHETIC,
        events=_events(
            [
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_use_id": "a",
                    "tool_input": {"file_path": "/run/summary.md"},
                    "tool_response": {"type": "create"},
                }
            ]
        ),
        lead_md=f"beta | summary.md: {detect.WRITE_GUARD_ERROR}",
    )
    finding = detect.report_file_guard(run)
    assert not finding.hit
    assert finding.evidence == "summary.md: allowed, written at post[0]"


def test_report_file_guard_misses_when_no_guarded_name_was_attempted(run2: Run) -> None:
    finding = detect.report_file_guard(run2)
    assert not finding.hit
    assert finding.evidence == "no guarded basename was written or reported on"


def test_detect_all_reports_every_behaviour_once(run2: Run) -> None:
    findings = detect.detect_all(run2)
    assert len(findings) == len(detect.DETECTORS)
    assert [f.behaviour for f in findings] == [
        "phantom-idle",
        "team-lead-reachable",
        "main-send-lacks-sender",
        "missing-posttooluse",
        "child-to-parent-by-name",
        "duplicate-arrival",
        "gate-phantom-blocks",
        "report-file-guard",
    ]


# --- helpers -------------------------------------------------------------------------


def _events(payloads: list[dict[str, Any]], times: list[float] | None = None) -> list[Event]:
    """Build events from bare payloads, one second apart unless times are given."""
    return [
        Event(
            index=i,
            t=times[i] if times else float(i),
            payload=payload,
            env={},
            team={"members": [{"name": "team-lead"}, {"name": "alpha"}]},
        )
        for i, payload in enumerate(payloads)
    ]
