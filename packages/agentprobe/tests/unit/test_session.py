"""Tests for the pure decisions the pseudo-terminal driver makes. No session is launched."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentprobe import session

SYNTHETIC = Path("/probe/run-001")

POST_TRUST_SCREEN = (Path(__file__).parent / "fixtures" / "post-trust-screen.txt").read_text()

TRUST_SCREEN = """
 Do you trust the files in this folder?

   /probe/run-001

 ❯ 1. No, cancel
   2. Yes, I trust this folder
"""

MAIN_SCREEN = """
 ▐ Welcome to Claude Code

 ╭──────────────────────────────────────╮
 │ ❯                                    │
 ╰──────────────────────────────────────╯
   ? for shortcuts
"""


def test_scrub_env_keeps_the_config_dir_and_drops_the_rest() -> None:
    environ = {
        "CLAUDE_CONFIG_DIR": "/home/operator/.claude",
        "CLAUDE_CODE_SESSION_ID": "the-launching-session",
        "CLAUDECODE": "1",
        "CODEX_COMPANION_HOME": "/opt/codex",
        "PATH": "/usr/bin",
    }
    scrubbed = session.scrub_env(environ, Path("/probe/events.jsonl"))
    assert scrubbed["CLAUDE_CONFIG_DIR"] == "/home/operator/.claude"
    assert scrubbed["PATH"] == "/usr/bin"
    assert "CLAUDE_CODE_SESSION_ID" not in scrubbed
    assert "CLAUDECODE" not in scrubbed
    assert "CODEX_COMPANION_HOME" not in scrubbed
    assert scrubbed["AGENTPROBE_EVENTS"] == "/probe/events.jsonl"
    assert scrubbed["TERM"] == "xterm-256color"


def test_trust_dialog_is_recognised_and_the_main_screen_is_not() -> None:
    assert session.awaiting_trust(TRUST_SCREEN)
    assert not session.awaiting_trust(MAIN_SCREEN)


def test_input_is_ready_only_once_the_trust_dialog_is_gone() -> None:
    assert session.input_ready(MAIN_SCREEN)
    assert not session.input_ready(TRUST_SCREEN)


def test_the_main_screen_is_ready_after_trust_although_the_dialog_echo_survives() -> None:
    # Captured from a real session. Accepting the dialog makes the terminal echo the
    # chosen line back, so "Yes, I trust this folder" is still in the driver's buffer long
    # after the dialog itself is gone. An untrusted reading of this screen is blocked by
    # that echo, and a session that reads it that way never types anything at all.
    screen = POST_TRUST_SCREEN
    assert "I trust this folder" in screen
    assert not session.input_ready(screen)
    assert session.input_ready(screen, trusted=True)


def test_input_is_ready_on_the_prompt_glyph_alone() -> None:
    assert session.input_ready("some earlier output\n ❯ ")


def test_typing_waits_for_the_screen_to_settle_after_trust() -> None:
    assert session.trust_settled(None, 1000.0)
    assert not session.trust_settled(1000.0, 1000.0 + session.TRUST_SETTLE_SECONDS - 1)
    assert session.trust_settled(1000.0, 1000.0 + session.TRUST_SETTLE_SECONDS)


def test_prompt_echo_is_read_back_off_a_wrapped_input_line() -> None:
    prompt = Path("/probe/teammate-child-messaging-001/prompt.md")
    wrapped = "│ Read /probe/teammate-child-mess\n│ aging-001/prompt.md and follow it  │"
    assert session.prompt_echoed(wrapped, prompt)


def test_prompt_echo_is_absent_when_the_keystrokes_were_dropped() -> None:
    assert not session.prompt_echoed(MAIN_SCREEN, Path("/probe/run-001/prompt.md"))


def test_the_run_completes_on_a_quiet_log_and_the_leads_done_word() -> None:
    assert session.finish_reason(30.0, "the lead says DONE", 200.0, 25.0) == session.COMPLETED
    assert session.finish_reason(10.0, "the lead says DONE", 200.0, 25.0) is None
    assert session.finish_reason(30.0, "still working", 200.0, 25.0) is None


def test_a_lead_that_never_says_done_ends_the_run_without_completing_it() -> None:
    assert session.finish_reason(80.0, "still working", 200.0, 25.0) == "no-terminal-state"
    # Not before the prompt has had time to produce anything, though.
    assert session.finish_reason(80.0, "still working", 30.0, 25.0) is None


def test_the_instruction_is_submitted_only_once_it_has_echoed_back() -> None:
    prompt = Path("/probe/run-001/prompt.md")
    written: list[bytes] = []
    screens = iter(["", f"❯ Read {prompt} and follow it exactly."])
    assert session.type_instruction(prompt, written.append, lambda: next(screens), lambda _seconds: None)
    assert written[-1] == b"\r"
    assert written.count(b"\r") == 1


def test_an_instruction_that_never_echoes_is_never_submitted() -> None:
    prompt = Path("/probe/run-001/prompt.md")
    written: list[bytes] = []
    assert not session.type_instruction(
        prompt, written.append, lambda: "nothing was typed here", lambda _seconds: None
    )
    assert b"\r" not in written
    assert len(written) == session.ECHO_ATTEMPTS


def test_visible_text_strips_escape_sequences() -> None:
    assert session.visible_text(b"\x1b[2J\x1b[31mhello\x1b[0m") == "hello"


def test_both_scenarios_ship_and_the_run_directory_reaches_the_prompt(tmp_path: Path) -> None:
    assert session.scenario_names() == ["report-file-guard", "teammate-child-messaging"]
    for name in session.scenario_names():
        text = session.scenario_prompt(name, tmp_path)
        assert "{RUN_DIR}" not in text
        assert str(tmp_path) in text


def test_an_unknown_scenario_names_the_ones_that_exist() -> None:
    with pytest.raises(FileNotFoundError, match="teammate-child-messaging"):
        session.scenario_prompt("no-such-scenario", SYNTHETIC)


def test_hook_settings_cover_every_event_the_detectors_read() -> None:
    settings = session.hook_settings()["hooks"]
    assert set(session.HOOK_EVENTS) <= set(settings)
    assert settings["PreToolUse"][0]["matcher"] == "SendMessage|Write"
    assert settings["PostToolUse"][0]["matcher"] == "SendMessage|Agent|Write"
    assert settings["TeammateIdle"][0]["hooks"][0]["command"].endswith("hooklog.py")


def test_prepare_writes_the_run_inputs_and_resolves_the_launch(tmp_path: Path) -> None:
    launch = session.prepare(
        tmp_path / "run-001",
        "teammate-child-messaging",
        {"CLAUDE_CODE_SESSION_ID": "launching", "HOME": "/home/operator"},
        "haiku",
    )
    assert launch.prompt_path.read_text().startswith("You are the lead")
    assert "hooks" in launch.settings_path.read_text()
    assert launch.argv[0] == "claude"
    assert str(launch.settings_path) in launch.argv
    assert "CLAUDE_CODE_SESSION_ID" not in launch.env


def test_describe_prints_the_command_and_the_scrubbed_environment(tmp_path: Path) -> None:
    launch = session.prepare(
        tmp_path / "run-001",
        "report-file-guard",
        {"CLAUDE_CODE_SESSION_ID": "launching", "CLAUDE_CONFIG_DIR": "/home/operator/.claude"},
        "haiku",
    )
    described = launch.describe()
    assert "command: claude --settings" in described
    assert "CLAUDE_CONFIG_DIR=/home/operator/.claude" in described
    assert "CLAUDE_CODE_SESSION_ID" not in described


def test_session_id_is_read_off_the_first_recorded_event(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text('\n{"payload": {"session_id": "abc-123"}}\n')
    assert session.session_id_of(events) == "abc-123"


def test_session_id_is_empty_when_nothing_was_recorded(tmp_path: Path) -> None:
    assert session.session_id_of(tmp_path / "absent.jsonl") == ""
    (tmp_path / "empty.jsonl").write_text("")
    assert session.session_id_of(tmp_path / "empty.jsonl") == ""
