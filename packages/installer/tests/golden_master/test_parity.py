"""Golden-master parity scenarios: bash ``install.sh`` vs Python ``install.py``.

Each scenario runs BOTH installers into isolated temp HOME trees and asserts the
results match (JSON semantic, every other file byte-wise, executable bit
included). Marked ``golden_master`` so they stay out of the fast coverage gate;
run them with ``make golden-master-installer``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity

pytestmark = pytest.mark.golden_master


_CLAUDE_ARGS = ["--tools=claude", "--plugins=", "--yes"]


def test_bare_install_single_tool_no_plugins(tmp_path: Path) -> None:
    """Clean HOME, one tool, no plugins — the simplest end-to-end parity check."""
    result = run_parity(tmp_path, args=_CLAUDE_ARGS)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_pre_existing_settings_merge(tmp_path: Path) -> None:
    """A pre-existing user settings.json is union-merged by both installers. The
    bash side uses jq, the Python side json_union — the differ compares JSON
    semantically, so formatting differences never register."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.json").write_text('{"userKey": "keep-me"}\n')

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_user_modified_file_is_backed_up(tmp_path: Path) -> None:
    """A user-modified deployed file is backed up (timestamped) then overwritten;
    both installers place the backup identically (G.1) and the differ normalises
    the timestamp, so parity holds and the backup is actually present."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "CLAUDE.md").write_text("USER LOCAL EDIT\n")

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
    backups = list(result.home_b.glob(".claude/CLAUDE.md.backup-*"))
    assert backups, "expected a timestamped backup of the user-modified CLAUDE.md"


def test_settings_merge_with_overlapping_array(tmp_path: Path) -> None:
    """A user settings.json whose permissions.deny overlaps the template exercises
    array union. bash's jq sorts the merged array; json_union keeps first-seen
    order. The differ compares settings arrays order-insensitively, so element
    parity holds despite the (accepted) order divergence."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.json").write_text('{"permissions": {"deny": ["Custom(user-rule)"]}}')

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_bare_install_codex(tmp_path: Path) -> None:
    """Single-tool parity for Codex — a dot-dir tool with its own templates."""
    result = run_parity(tmp_path, args=["--tools=codex", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


@pytest.mark.xfail(
    strict=True,
    reason="Gemini agent transform must match bash byte-for-byte (inline tools:[...], "
    "surgical edit); the Python port's pyyaml round-trip reformats it. Not yet ported.",
)
def test_bare_install_gemini(tmp_path: Path) -> None:
    """Single-tool parity for Gemini — another dot-dir tool, flat instruction file."""
    result = run_parity(tmp_path, args=["--tools=gemini", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


@pytest.mark.xfail(
    strict=True,
    reason="OpenCode must not install a standalone rules/ namespace (bash inlines rules "
    "into AGENTS.md); the Python adapter still stages rules/ files. Not yet ported.",
)
def test_bare_install_opencode(tmp_path: Path) -> None:
    """Single-tool parity for OpenCode — the XDG (~/.config/opencode) tool that
    skips shared agents/ and flattens rules into AGENTS.md. Confirms the Python
    adapter wrongly installs a standalone rules/ namespace."""
    result = run_parity(tmp_path, args=["--tools=opencode", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


@pytest.mark.xfail(
    strict=True,
    reason="Auto-detect must install Claude unconditionally to match bash; the Python "
    "port requires ~/.claude/settings.json and so detects nothing here. Not yet ported.",
)
def test_autodetect_fresh_home(tmp_path: Path) -> None:
    """No --tools: auto-detect against an empty HOME. Bash treats Claude as
    always-installed; the Python port requires ~/.claude/settings.json to detect
    it, so it detects nothing. That asymmetry guarantees a divergence on any
    host regardless of PATH — no PATH manipulation is needed to keep this xfail
    deterministic. (When this is wired green, tool-detection must be isolated —
    opencode/gemini/codex absent — while bash's required binaries, notably jq,
    stay reachable; a bare PATH=/usr/bin:/bin would starve bash's jq guard.)"""
    result = run_parity(tmp_path, args=["--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_warmup_run_failure_is_surfaced(tmp_path: Path) -> None:
    """A failing warm-up run (repeat>1) must raise, not be silently discarded —
    otherwise a first-run install failure in an idempotency scenario would be
    masked by a later run's exit code. Bogus ``--tools`` makes the warm-up run
    fail fast at argument validation."""
    with pytest.raises(RuntimeError, match="warm-up"):
        run_parity(tmp_path, args=["--tools=bogus-tool", "--plugins=", "--yes"], repeat=2)


@pytest.mark.xfail(
    strict=True,
    reason="Re-install must be idempotent: the Python port re-backs-up directories on "
    "every run, so a second run leaves spurious backups bash does not. Not yet ported.",
)
def test_reinstall_is_idempotent(tmp_path: Path) -> None:
    """Running each installer twice into the same HOME must converge to the same
    tree — no spurious second-run backups. Exercises re-install idempotency
    (Python re-backs-up directories every run)."""
    result = run_parity(tmp_path, args=_CLAUDE_ARGS, repeat=2)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
