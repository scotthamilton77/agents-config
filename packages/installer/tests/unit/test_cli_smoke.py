"""Smoke tests for installer.cli.main.

Each test pins a CLI-level behaviour contract from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for argparse machinery and exit-code propagation by SystemExit
are absent — they test the stdlib, not coded decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main


def _home_with_claude_settings(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def test_main_help_exits_with_status_zero() -> None:
    """
    When main(["--help"]) is invoked
    Then SystemExit(0) is raised.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_main_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    """
    When main(["--help"]) is invoked
    Then usage text is printed to stdout.
    """
    with pytest.raises(SystemExit):
        main(["--help"])
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "installer" in captured.out


def test_main_no_args_returns_zero_against_hermetic_home_with_settings(
    tmp_path: Path,
) -> None:
    """
    Given a home directory with a file at .claude/settings.json
    When main([], home=that_home) is invoked
    Then it returns 0.
    """
    home = _home_with_claude_settings(tmp_path)
    assert main([], home=home) == 0


def test_main_tools_claude_returns_zero(tmp_path: Path) -> None:
    """
    When main(["--tools=claude"], home=any) is invoked
    Then it returns 0.
    """
    assert main(["--tools=claude"], home=tmp_path) == 0


def test_main_tools_opencode_returns_2_and_writes_unknown_tool_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--tools=opencode"], home=any) is invoked
    Then it returns 2
    And stderr contains "Unknown tool: 'opencode'".
    """
    rc = main(["--tools=opencode"], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "Unknown tool: 'opencode'" in captured.err


def test_main_tools_empty_returns_2_and_writes_usage_error_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--tools="], home=any) is invoked
    Then it returns 2
    And stderr contains "--tools= requires at least one tool".
    """
    rc = main(["--tools="], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "--tools= requires at least one tool" in captured.err


def test_main_tools_foo_returns_2(tmp_path: Path) -> None:
    """
    When main(["--tools=foo"], home=any) is invoked
    Then it returns 2.
    """
    assert main(["--tools=foo"], home=tmp_path) == 2


def test_main_no_args_against_empty_home_returns_zero_with_no_tools(
    tmp_path: Path,
) -> None:
    """
    Given an empty home directory
    When main([], home=that_home) is invoked
    Then it returns 0.

    Pins: empty resolved tools tuple is valid in B.1 — install logic
    comes later (B.2+).
    """
    assert main([], home=tmp_path) == 0
