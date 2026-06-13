"""Smoke tests for installer.cli.main.

Each test pins a CLI-level behaviour contract from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for argparse machinery and exit-code propagation by SystemExit
are absent — they test the stdlib, not coded decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main
from installer.core.io_port import ScriptedIO
from installer.core.model import Tool
from installer.tools import registry


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


def test_main_tools_unregistered_returns_2_and_writes_unknown_tool_to_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a Tool enum value whose adapter is absent from the registry
    When main(["--tools=<that>"], home=any) is invoked
    Then it returns 2
    And stderr contains "Unknown tool: '<that>'".

    Pins: the CLI rejects an enum value that has no registered adapter
    (registry-is-truth). Every Tool now has an adapter, so the unregistered
    case is simulated by removing one entry.
    """
    reduced = {t: a for t, a in registry._REGISTRY.items() if t is not Tool.OPENCODE}
    monkeypatch.setattr(registry, "_REGISTRY", reduced)
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


def test_main_no_args_against_empty_home_returns_2_with_detection_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given an empty home directory (no agent tools detectable)
    When main([], home=that_home) is invoked
    Then it returns 2
    And stderr names the failure ("no agent tools detected")
    And stderr lists each known tool by name
    And stderr lists each tool's detection signal
    And stderr names the home directory that was probed
    And stderr suggests the --tools= escape hatch.

    Pins: empty auto-detect must NOT silently succeed — see Codex
    adversarial review of PR #86 (2026-05-23). Forces operators to
    either install a recognized tool or pass --tools= explicitly.
    """
    rc = main([], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "no agent tools detected" in captured.err
    assert "claude" in captured.err
    assert "settings.json" in captured.err
    assert str(tmp_path) in captured.err
    assert "--tools=" in captured.err


# ── G.5 / G.7: prune flags + --yes wiring ──


def test_prune_and_prune_only_together_is_mutually_exclusive_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--prune", "--prune-only"]) is invoked
    Then argparse exits 2 (mutually exclusive group rejects both).

    Pins: --prune and --prune-only cannot be combined (installer-design.md G.5).
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--prune", "--prune-only"], home=tmp_path)
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "not allowed with" in captured.err


def test_prune_only_against_empty_source_prunes_unstaged_dest_entry(tmp_path: Path) -> None:
    """
    Given a home with a claude skills/ entry matching the bundled prune list and
    an empty source repo (nothing staged), under --prune-only --yes
    When main runs (non-interactive io)
    Then the unstaged, retired entry is removed.

    Pins: --prune-only scans + prunes against the in-memory plan without an
    install half, and --yes waives the non-interactive guard.
    """
    home = _home_with_claude_settings(tmp_path)
    # "*/skills/ralf-it" is in the bundled installer.toml prune list.
    retired = home / ".claude" / "skills" / "ralf-it"
    retired.mkdir(parents=True)
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()

    rc = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=empty_repo,
    )

    assert rc == 0
    assert not retired.exists()


def test_prune_only_non_interactive_without_yes_fails(tmp_path: Path) -> None:
    """
    Given --prune-only with a matching orphan, a non-interactive io, and no --yes
    When main runs
    Then it returns a non-zero status (the prune flow's hard-fail guard).
    """
    home = _home_with_claude_settings(tmp_path)
    (home / ".claude" / "skills" / "ralf-it").mkdir(parents=True)
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()

    rc = main(
        ["--prune-only", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=empty_repo,
    )

    assert rc != 0


def test_plain_prune_non_interactive_without_yes_fails_on_consent_guard(tmp_path: Path) -> None:
    """
    Given plain --prune (not --prune-only), a non-interactive io, and no --yes
    When main runs
    Then it returns non-zero — the consent guard refuses a destructive run that
    cannot prompt (G.7), before any orphan scan.
    """
    home = _home_with_claude_settings(tmp_path)
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()

    rc = main(
        ["--prune", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=empty_repo,
    )

    assert rc != 0
