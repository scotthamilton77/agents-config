"""Golden-master prune parity: bash ``install.sh`` vs Python ``install.py`` --prune / --prune-only.

Both scenarios seed a HOME with retired orphan files — entries that appear on
the bash ``scripts/prune-list`` AND the Python ``packages/installer/installer.toml``
prune list — then run both installers with the prune flag and assert that the
resulting HOME trees reach parity.

The ``*/skills/condition-based-waiting`` and ``*/agents/bead-implementor.md``
globs are present in both lists, so a Claude-tool HOME with those paths under
``.claude/skills/`` and ``.claude/agents/`` produces genuine orphans that both
installers must back up and remove identically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity

pytestmark = pytest.mark.golden_master

_CLAUDE_ARGS = ["--tools=claude", "--plugins=", "--yes"]


def _seed_orphans(home: Path) -> None:
    """Place retired files into the Claude tool tree to act as prune targets."""
    skills = home / ".claude" / "skills"
    agents = home / ".claude" / "agents"
    skills.mkdir(parents=True, exist_ok=True)
    agents.mkdir(parents=True, exist_ok=True)
    (skills / "condition-based-waiting").write_text("# retired skill\n")
    (agents / "bead-implementor.md").write_text("# retired agent\n")


def test_prune_yes_removes_orphans(tmp_path: Path) -> None:
    """--prune --yes: install runs, then orphaned retired files are backed up and
    removed.  Both installers must produce identical homes after the full
    install-then-prune pass."""
    result = run_parity(tmp_path, args=[*_CLAUDE_ARGS, "--prune"], seed=_seed_orphans)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
    # Confirm prune actually fired on the Python side (parity ensures bash matches).
    assert not (result.home_b / ".claude" / "skills" / "condition-based-waiting").exists(), (
        "orphan must be gone after prune"
    )
    assert not (result.home_b / ".claude" / "agents" / "bead-implementor.md").exists(), (
        "orphan must be gone after prune"
    )
    assert (result.home_b / ".claude" / "skills-backup").is_dir(), (
        "expected skills-backup dir — prune must have run"
    )
    assert (result.home_b / ".claude" / "agents-backup").is_dir(), (
        "expected agents-backup dir — prune must have run"
    )


def test_prune_only_removes_orphans(tmp_path: Path) -> None:
    """--prune-only --yes: Phase 7 install is skipped; orphaned retired files are
    backed up and removed.  Both installers must produce identical homes containing
    only the orphan backups (no freshly installed content)."""
    result = run_parity(tmp_path, args=[*_CLAUDE_ARGS, "--prune-only"], seed=_seed_orphans)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
    # Confirm prune actually fired on the Python side (parity ensures bash matches).
    assert not (result.home_b / ".claude" / "skills" / "condition-based-waiting").exists(), (
        "orphan must be gone after prune-only"
    )
    assert not (result.home_b / ".claude" / "agents" / "bead-implementor.md").exists(), (
        "orphan must be gone after prune-only"
    )
    assert (result.home_b / ".claude" / "skills-backup").is_dir(), (
        "expected skills-backup dir — prune must have run"
    )
    assert (result.home_b / ".claude" / "agents-backup").is_dir(), (
        "expected agents-backup dir — prune must have run"
    )
