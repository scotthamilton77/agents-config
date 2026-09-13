"""Tests for reading run directories and for the table the report prints."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agentprobe import cli, report
from agentprobe.events import Run, load_runs, parse_decisions, parse_events

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_recorded_run_carries_its_version_team_and_side_files(run2: Run) -> None:
    assert len(run2.events) == 62
    assert run2.version == "2.1.270 (Claude Code)"
    assert run2.team_members == ["team-lead", "alpha"]
    assert run2.lead_md.startswith("team-lead | UPDATE 2")
    assert len(run2.gate_decisions) == 18


def test_a_run_with_nothing_recorded_reads_as_empty(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_text("")
    run = load_runs([tmp_path])[0]
    assert run.events == []
    assert run.version == "unknown"
    assert run.team_members == []


def test_unreadable_lines_are_skipped_rather_than_failing_the_read() -> None:
    assert parse_events('{"payload": {}}\nnot json\n\n["not a record"]\n') != []
    assert len(parse_events('{"payload": {}}\nnot json\n')) == 1
    assert parse_decisions('{"decision": "block"}\nhalf-writ') == [{"decision": "block"}]


def test_a_directory_of_runs_is_read_with_one_argument() -> None:
    assert [run.name for run in load_runs([FIXTURES])] == ["invalid-run", "run2", "run3"]


def test_the_two_recordings_are_valid_and_the_failed_run_is_not() -> None:
    by_name = {run.name: run for run in load_runs([FIXTURES])}
    assert by_name["run2"].valid
    assert by_name["run3"].valid
    invalid = by_name["invalid-run"]
    assert not invalid.valid
    assert invalid.outcome == "instruction-never-typed"
    assert "the instruction was never typed" in invalid.invalid_reason


def test_a_run_directory_with_no_record_of_its_outcome_does_not_count(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_text("")
    run = load_runs([tmp_path])[0]
    assert run.outcome == "unrecorded"
    assert not run.valid
    assert run.invalid_reason == "unrecorded"


def test_the_table_reports_a_rate_per_behaviour_and_the_versions_observed() -> None:
    runs = load_runs([FIXTURES])
    rows = report.aggregate(runs)
    by_name = {row.behaviour: row for row in rows}
    # Three run directories were read and one of them measured nothing, so every
    # denominator is two. A failed run counted as a run would read as a release fixing
    # every behaviour at once.
    assert by_name["phantom-idle"].hits == 2
    assert by_name["phantom-idle"].runs == 2
    assert by_name["phantom-idle"].versions == ["2.1.270 (Claude Code)"]
    assert "idle[24]" in by_name["phantom-idle"].note
    assert by_name["report-file-guard"].hits == 0
    rendered = report.render(rows)
    assert "phantom-idle" in rendered
    assert "2/2" in rendered
    assert "2.1.270 (Claude Code)" in rendered


def test_a_long_note_is_cut_to_one_readable_line() -> None:
    rows = [report.Row("phantom-idle", 1, 1, ["2.1.270"], "x" * 500)]
    rendered = report.render(rows)
    assert "more characters of evidence" in rendered
    assert len(rendered.splitlines()[-1]) < 350


def test_every_behaviour_gets_exactly_one_evidence_line_in_the_tables_order() -> None:
    runs = load_runs([FIXTURES])
    rows = report.aggregate(runs)
    rendered = report.render(rows, report.invalid_runs(runs))
    order = [row.behaviour for row in rows]
    assert len(order) == 8
    table, notes = rendered.split("\n\n")[0], rendered.split("\n\n")[1]
    assert [line.split()[0] for line in table.splitlines()[2:]] == order
    evidence = notes.splitlines()
    assert [line.split(":")[0] for line in evidence] == order
    for behaviour in order:
        assert sum(line.startswith(f"{behaviour}:") for line in evidence) == 1


def test_the_invalid_section_names_the_excluded_run_and_why() -> None:
    runs = load_runs([FIXTURES])
    rendered = report.render(report.aggregate(runs), report.invalid_runs(runs))
    tail = rendered.split("\n\n")[-1].splitlines()
    assert tail[0] == "invalid, excluded from every rate above (1):"
    assert tail[1].strip().startswith("invalid-run: instruction-never-typed:")
    assert "the instruction was never typed" in tail[1]
    assert len(tail) == 2


def test_the_table_says_so_when_nothing_valid_was_read() -> None:
    assert report.render(report.aggregate([])) == "no valid runs read"
    invalid = load_runs([FIXTURES / "invalid-run"])
    rendered = report.render(report.aggregate(invalid), report.invalid_runs(invalid))
    assert rendered.splitlines()[0] == "no valid runs read"
    assert "invalid-run: instruction-never-typed" in rendered


def test_report_measures_and_never_fails(capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["report", str(FIXTURES)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed[0].split() == ["behaviour", "hits/runs", "versions"]
    rates = {line.split()[0]: line.split()[1] for line in printed[2:10]}
    assert rates == {
        "phantom-idle": "2/2",
        "team-lead-reachable": "2/2",
        "main-send-lacks-sender": "2/2",
        "missing-posttooluse": "0/2",
        "child-to-parent-by-name": "2/2",
        "duplicate-arrival": "0/2",
        "gate-phantom-blocks": "2/2",
        "report-file-guard": "0/2",
    }
    assert "invalid, excluded from every rate above (1):" in printed
    assert any("invalid-run: instruction-never-typed" in line for line in printed)


def test_report_tolerates_a_directory_that_is_not_there(capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["report", "/nowhere/at/all"]) == 0
    assert capsys.readouterr().out.strip() == "no valid runs read"


def test_a_dry_run_prints_the_command_and_launches_nothing(tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "the-launching-session")
    assert cli.main(["run", "teammate-child-messaging", "--out", str(tmp_path), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "command: claude --settings" in printed
    assert "the-launching-session" not in printed
    run_dir = tmp_path / "teammate-child-messaging-001"
    assert (run_dir / "prompt.md").exists()
    assert not (run_dir / "events.jsonl").exists()


def test_each_run_gets_its_own_numbered_directory(tmp_path: Path) -> None:
    (tmp_path / "teammate-child-messaging-001").mkdir()
    assert cli._next_run_dir(tmp_path, "teammate-child-messaging").name == "teammate-child-messaging-002"


def test_the_logging_hook_records_the_payload_and_the_session_environment(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import io
    import sys

    from agentprobe import hooklog

    config_dir = tmp_path / "config"
    (config_dir / "teams" / "session-abcdefgh").mkdir(parents=True)
    (config_dir / "teams" / "session-abcdefgh" / "config.json").write_text(
        json.dumps({"members": [{"name": "alpha"}]})
    )
    events = tmp_path / "events.jsonl"
    monkeypatch.setattr(
        os,
        "environ",
        {
            "AGENTPROBE_EVENTS": str(events),
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "CLAUDE_CODE_MESSAGING_TOKEN": "a-real-secret",
            "PATH": "/usr/bin",
        },
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "TeammateIdle",
                    "session_id": "abcdefgh-1111-2222-3333-444444444444",
                    "teammate_name": "alpha",
                }
            )
        ),
    )
    hooklog.main()
    record = json.loads(events.read_text())
    assert record["payload"]["teammate_name"] == "alpha"
    assert record["team"]["members"] == [{"name": "alpha"}]
    assert record["env"]["CLAUDE_CODE_MESSAGING_TOKEN"] == "<redacted>"
    assert "PATH" not in record["env"]


def test_the_logging_hook_survives_junk_and_a_missing_destination(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import io
    import sys

    from agentprobe import hooklog

    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    hooklog.main()  # Writes nothing, because no destination was named.
    assert hooklog.team_snapshot("") is None


def test_a_run_is_stamped_with_a_utc_timestamp() -> None:
    assert cli._timestamp().endswith("Z")


def test_the_console_entry_point_raises_the_exit_status() -> None:
    import pytest

    with pytest.raises(SystemExit) as exit_status:
        cli.entry()
    assert exit_status.value.code == 2  # argparse rejects an invocation with no verb.
