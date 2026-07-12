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
    assert "no pr" in st.reason.lower()


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


# --- Task 3: detect_convention ---


def test_detect_convention_normal_repo():
    root = Path("/repo")
    assert m.detect_convention(root, root) is m.Convention.NORMAL_REPO


def test_detect_convention_claude_native():
    main_root = Path("/repo")
    wt = Path("/repo/.claude/worktrees/feature-x")
    assert m.detect_convention(wt, main_root) is m.Convention.CLAUDE_NATIVE


def test_detect_convention_other_agent_dot_worktrees():
    main_root = Path("/repo")
    wt = Path("/repo/.worktrees/feature-x")
    assert m.detect_convention(wt, main_root) is m.Convention.OTHER_AGENT


def test_detect_convention_other_agent_bare_worktrees():
    main_root = Path("/repo")
    wt = Path("/repo/worktrees/feature-x")
    assert m.detect_convention(wt, main_root) is m.Convention.OTHER_AGENT


def test_detect_convention_unrecognised_raises():
    main_root = Path("/repo")
    wt = Path("/tmp/somewhere/else")
    with pytest.raises(m.UnrecognizedWorktree):
        m.detect_convention(wt, main_root)


# --- Task 4: safety-gate parsers ---


def test_dirty_paths_parses_porcelain():
    porcelain = " M src/a.py\n?? stray.txt\nA  added.py\n"
    assert m.dirty_paths(porcelain) == ["src/a.py", "stray.txt", "added.py"]


def test_dirty_paths_clean_is_empty():
    assert m.dirty_paths("") == []
    assert m.dirty_paths("\n\n") == []


def test_unmerged_commits_lists_orphans():
    assert m.unmerged_commits("abc\ndef\n") == ["abc", "def"]


def test_unmerged_commits_empty_means_fully_contained():
    assert m.unmerged_commits("") == []
    assert m.unmerged_commits("\n") == []


# --- Task 5: plan_teardown ---


def test_plan_teardown_claude_native_returns_handoff_steps():
    steps = m.plan_teardown(m.Convention.CLAUDE_NATIVE, "/repo", "feature/x")
    assert steps == [
        "ExitWorktree(discard_changes: true)",
        "git -C /repo branch -D feature/x",
    ]


def test_plan_teardown_other_agent_is_scripted_no_remaining():
    assert m.plan_teardown(m.Convention.OTHER_AGENT, "/repo", "feature/x") == []


def test_plan_teardown_normal_repo_is_scripted_no_remaining():
    assert m.plan_teardown(m.Convention.NORMAL_REPO, "/repo", "feature/x") == []
