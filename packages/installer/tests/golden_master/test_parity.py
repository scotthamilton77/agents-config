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
