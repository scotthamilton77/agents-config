"""Smoke tests for installer.cli.main.

Each test pins a CLI-level behaviour contract from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for argparse machinery and exit-code propagation by SystemExit
are absent — they test the stdlib, not coded decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main
from installer.core.model import Tool
from installer.tools import registry


def _home_with_claude_settings(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def _hermetic_repo(tmp_path: Path) -> Path:
    """A minimal source repo: one shared template so a Claude plan is
    non-empty, plus empty tool-root dirs the adapters expect."""
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"shared laws\n")
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    return repo


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


def test_dump_stage_materialises_plan_and_returns_zero(tmp_path: Path) -> None:
    """
    Given a hermetic source repo and a Claude install signal in home
    When main(["--dump-stage=<out>", "--tools=claude"], repo_root=repo) runs
    Then it returns 0
    And the staged shared template lands at <out>/claude/INSTRUCTIONS.md.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"

    rc = main(
        [f"--dump-stage={out}", "--tools=claude"],
        home=tmp_path,
        repo_root=repo,
    )

    assert rc == 0
    assert (out / "claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"


def test_dump_stage_writes_nothing_under_home(tmp_path: Path) -> None:
    """
    Given a home with a Claude detection signal but no installed config tree
    When main runs in --dump-stage mode
    Then the only thing under .claude is the detection signal that was already
    there — the dump touches no install destination.
    """
    repo = _hermetic_repo(tmp_path)
    home = _home_with_claude_settings(tmp_path)
    out = tmp_path / "dump"

    main([f"--dump-stage={out}", "--tools=claude"], home=home, repo_root=repo)

    under_claude = sorted(p.name for p in (home / ".claude").iterdir())
    assert under_claude == ["settings.json"]


def test_dump_stage_prints_dump_path_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main runs in --dump-stage mode
    Then the dump path is printed to stdout (operator-facing breadcrumb).

    Whitespace is collapsed before the substring check: rich's Console
    soft-wraps long lines at the detected terminal width (80 under capsys), so
    a long temp path is split across physical lines. That wrapping is a
    rendering artifact of console width — an injectable concern, per the
    io_port suite's width=120 Console — not part of the "path is printed"
    contract.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"

    main([f"--dump-stage={out}", "--tools=claude"], home=tmp_path, repo_root=repo)

    printed = "".join(capsys.readouterr().out.split())
    assert "".join(str(out).split()) in printed


def test_dump_stage_non_empty_target_returns_2_with_stderr_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a --dump-stage target that already holds files
    When main runs in --dump-stage mode
    Then it returns 2 (not an uncaught traceback)
    And stderr names the not-empty target.

    Pins: the debug flag fails cleanly on a dirty target rather than crashing,
    consistent with the CLI's other return-2 error paths.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"
    out.mkdir()
    (out / "stale.txt").write_bytes(b"old\n")

    rc = main([f"--dump-stage={out}", "--tools=claude"], home=tmp_path, repo_root=repo)

    assert rc == 2
    assert "not empty" in capsys.readouterr().err
