import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import sync_after_remote_merge as m  # noqa: E402


# --- Task 1: envelope builder ---


def test_envelope_has_all_stable_keys():
    env = m.build_envelope(m.Status.OK, steps_completed=["preflight"], base="main")
    assert set(env) == {
        "status", "steps_completed", "failed_step", "steps_remaining",
        "worktree_convention", "main_root", "base", "branch", "pr",
        "merge_commit", "synced_to", "remediation_hint",
    }
    assert env["status"] == "ok"
    assert env["steps_completed"] == ["preflight"]
    assert env["base"] == "main"
    assert env["failed_step"] is None
    assert env["steps_remaining"] == []


def test_envelope_serialises_convention_enum_to_string():
    env = m.build_envelope(m.Status.HANDOFF, worktree_convention=m.Convention.CLAUDE_NATIVE)
    assert env["worktree_convention"] == "claude-native"
    assert json.loads(json.dumps(env))["worktree_convention"] == "claude-native"
