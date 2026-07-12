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


# --- Task 2: classify_pr ---


def test_classify_pr_none_is_not_merged():
    st = m.classify_pr(None)
    assert st.merged is False and st.pr is None
    assert "no PR" in st.reason.lower()


def test_classify_pr_open_is_not_merged():
    st = m.classify_pr({"number": 12, "state": "OPEN", "baseRefName": "main"})
    assert st.merged is False and st.pr == 12 and st.base == "main"
    assert "OPEN" in st.reason


def test_classify_pr_closed_unmerged_is_not_merged():
    st = m.classify_pr({"number": 9, "state": "CLOSED", "baseRefName": "main"})
    assert st.merged is False and st.pr == 9


def test_classify_pr_merged_carries_commit_and_head():
    st = m.classify_pr({
        "number": 42, "state": "MERGED", "baseRefName": "main",
        "mergeCommit": {"oid": "abc123"}, "headRefOid": "def456",
    })
    assert st.merged is True
    assert st.pr == 42 and st.base == "main"
    assert st.merge_commit == "abc123" and st.head_oid == "def456"


def test_classify_pr_merged_without_merge_commit_oid():
    st = m.classify_pr({"number": 7, "state": "MERGED", "baseRefName": "main", "mergeCommit": None})
    assert st.merged is True and st.merge_commit is None
