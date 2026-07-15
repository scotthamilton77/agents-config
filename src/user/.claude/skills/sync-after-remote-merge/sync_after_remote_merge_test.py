import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import sync_after_remote_merge as m  # noqa: E402


# --- Task 1: envelope builder ---


def test_envelope_has_all_stable_keys():
    env = m.build_envelope(m.Status.OK, phase=m.Phase.FINISH,
                           steps_completed=["preflight"], base="main")
    assert set(env) == {
        "status", "phase", "steps_completed", "failed_step", "steps_remaining",
        "worktree_convention", "main_root", "base", "branch", "branch_sha",
        "pr", "merge_commit", "synced_to", "ignored_paths", "remediation_hint",
    }
    assert env["status"] == "ok"
    assert env["phase"] == "finish"
    assert env["branch_sha"] is None
    assert env["ignored_paths"] == []


def test_envelope_phase_serialises_to_string():
    env = m.build_envelope(m.Status.HANDOFF, phase=m.Phase.PLAN,
                           branch_sha="abc123", ignored_paths=[".venv/"])
    assert json.loads(json.dumps(env))["phase"] == "plan"
    assert env["branch_sha"] == "abc123"
    assert env["ignored_paths"] == [".venv/"]


def test_envelope_serialises_convention_enum_to_string():
    env = m.build_envelope(m.Status.HANDOFF, phase=m.Phase.PLAN,
                           worktree_convention=m.Convention.CLAUDE_NATIVE)
    assert env["worktree_convention"] == "claude-native"
    assert json.loads(json.dumps(env))["worktree_convention"] == "claude-native"


# --- main(): argument errors still emit the JSON envelope ---


def test_arg_error_emits_failed_envelope():
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(["--branch"])          # missing value → argparse error
    env = json.loads(buf.getvalue())
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "args"
    assert env["phase"] == "plan"


def test_arg_error_in_finish_mode_reports_finish_phase():
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(["--finish", "--bogus-flag"])
    env = json.loads(buf.getvalue())
    assert rc != 0 and env["phase"] == "finish"


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


def test_unrecognised_message_lists_every_checked_convention():
    """The fail-loud message must name all three conventions detect_convention
    actually checks, so the remediation guidance matches the code."""
    main_root = Path("/repo")
    with pytest.raises(m.UnrecognizedWorktree) as ei:
        m.detect_convention(Path("/tmp/elsewhere/x"), main_root)
    msg = str(ei.value)
    assert "/repo/.claude/worktrees" in msg
    assert "/repo/.worktrees" in msg
    assert "/repo/worktrees" in msg


def test_detect_convention_unrelated_worktrees_segment_fails_loud():
    """A `worktrees` path segment NOT anchored under main_root must fail loud,
    never be scripted-removed as OTHER_AGENT (a bare-segment match would)."""
    main_root = Path("/repo")
    wt = Path("/elsewhere/worktrees/feature-x")
    with pytest.raises(m.UnrecognizedWorktree):
        m.detect_convention(wt, main_root)


def test_detect_convention_unrelated_claude_worktrees_segment_fails_loud():
    """Same anchoring for the Claude-native check: a `.claude/worktrees` segment
    outside main_root is not this repo's Claude-native worktree."""
    main_root = Path("/repo")
    wt = Path("/elsewhere/.claude/worktrees/feature-x")
    with pytest.raises(m.UnrecognizedWorktree):
        m.detect_convention(wt, main_root)


# --- gh_pr_view: PR-absence vs hard failure classification ---


def test_run_step_abort_cmd_is_shell_reconstructible(monkeypatch):
    """failed_step.cmd must be a copy-pastable command even when an argument
    (e.g. a path) contains spaces — shlex.join, not a bare space-join."""
    def fake_run(cmd, cwd=None, check=True):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(m, "_run", fake_run)
    with pytest.raises(m._AbortStep) as ei:
        m._run_step(["git", "-C", "/My Repos/x", "status"], "teardown", "hint")
    assert ei.value.failed_step["cmd"] == "git -C '/My Repos/x' status"


def test_gh_pr_view_abort_cmd_includes_full_argv(monkeypatch):
    """The gh_pr_view abort must report the real argv (with --json), reconstructed
    via shlex.join, not a lossy hand-built f-string."""
    def fake_run(cmd, cwd=None, check=True):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="server error 500")
    monkeypatch.setattr(m, "_run", fake_run)
    with pytest.raises(m._AbortStep) as ei:
        m.gh_pr_view("feat/x")
    cmd = ei.value.failed_step["cmd"]
    assert cmd.startswith("gh pr view feat/x")
    assert "--json" in cmd


def test_gh_pr_view_no_pr_returns_none(monkeypatch):
    def fake_run(cmd, cwd=None, check=True):
        return subprocess.CompletedProcess(cmd, 1, stdout="",
                                           stderr="no pull requests found for branch feature/x")
    monkeypatch.setattr(m, "_run", fake_run)
    assert m.gh_pr_view("feature/x") is None


def test_gh_pr_view_generic_not_found_raises(monkeypatch):
    """A non-PR 'not found' (repo/auth) must raise so main() reports `failed`,
    not get swallowed into a benign not_merged."""
    def fake_run(cmd, cwd=None, check=True):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="",
            stderr="GraphQL: Could not resolve to a Repository (repository not found)")
    monkeypatch.setattr(m, "_run", fake_run)
    with pytest.raises(m._AbortStep):
        m.gh_pr_view("feature/x")


# --- Task 4: safety-gate parsers ---


def test_classify_paths_splits_tracked_untracked_ignored():
    porcelain = " M src/a.py\n?? new.txt\n!! .venv/\n!! .env\n"
    tracked, untracked, ignored = m.classify_status_paths(porcelain)
    assert tracked == ["src/a.py"]
    assert untracked == ["new.txt"]
    assert ignored == [".venv/", ".env"]


def test_blocking_paths_worktree_conventions_block_untracked():
    assert m.blocking_paths(["a"], ["b"], m.Convention.OTHER_AGENT) == ["a", "b"]
    assert m.blocking_paths(["a"], ["b"], m.Convention.CLAUDE_NATIVE) == ["a", "b"]


def test_blocking_paths_normal_repo_permits_untracked():
    assert m.blocking_paths(["a"], ["b"], m.Convention.NORMAL_REPO) == ["a"]


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


def test_plan_teardown_quotes_shell_significant_paths():
    """main_root / branch are interpolated into a command string the agent runs;
    spaces or shell metacharacters must be quoted, not passed through raw."""
    steps = m.plan_teardown(m.Convention.CLAUDE_NATIVE, "/My Repos/agents", "feat/x y")
    assert steps[1] == "git -C '/My Repos/agents' branch -D 'feat/x y'"


def test_plan_teardown_other_agent_is_scripted_no_remaining():
    assert m.plan_teardown(m.Convention.OTHER_AGENT, "/repo", "feature/x") == []


def test_plan_teardown_normal_repo_is_scripted_no_remaining():
    assert m.plan_teardown(m.Convention.NORMAL_REPO, "/repo", "feature/x") == []


# --- Task 6: boundary + main() orchestration (real tmp git repos; gh faked) ---


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def main_repo(tmp_path):
    """A real git repo with one commit on `main`, plus an origin it can pull from."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True, text=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                   capture_output=True, text=True)
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "origin", "main")
    return repo


def _run_main(monkeypatch, cwd, pr_json, argv):
    import contextlib
    import io
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(m, "gh_pr_view", lambda branch: pr_json)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(argv)
    return rc, json.loads(buf.getvalue())


def test_main_not_merged_when_no_pr(monkeypatch, main_repo):
    _git(main_repo, "checkout", "-b", "feature/x")
    rc, env = _run_main(monkeypatch, main_repo, None, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "not_merged"
    assert "verify_merged" not in env["steps_completed"]
    assert env["merge_commit"] is None


def test_main_dirty_worktree_aborts(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "stray.txt").write_text("uncommitted\n")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "safety_gate_worktree"
    assert "stray.txt" in json.dumps(env)


def test_main_other_agent_full_teardown(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    # Merge on the "remote": fast-forward main to the feature commit, push.
    _git(main_repo, "merge", "feature/x")
    _git(main_repo, "push", "origin", "main")
    merge_oid = _head(main_repo)
    _git(main_repo, "checkout", "main")
    # Rewind local main so the script has to pull the merge.
    _git(main_repo, "reset", "--hard", "HEAD~1")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": merge_oid}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "ok"
    assert env["worktree_convention"] == "other-agent"
    assert env["steps_remaining"] == []
    assert env["synced_to"] == merge_oid
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" not in branches
    assert not wt.exists()


def test_main_claude_native_hands_off(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    # Force the Claude-native teardown branch regardless of the real path.
    monkeypatch.setattr(m, "detect_convention", lambda w, r: m.Convention.CLAUDE_NATIVE)
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "handoff"
    assert env["steps_remaining"] == [
        "ExitWorktree(discard_changes: true)",
        f"git -C {env['main_root']} branch -D feature/x",
    ]
    assert wt.exists()  # script did NOT remove a Claude-native worktree


def test_main_squash_merge_succeeds(monkeypatch, main_repo):
    """The primary case: a squash merge (repo default). The squash commit does
    NOT have the branch commits as ancestors, so a merge_commit-based
    containment check would false-abort. Gate A must key off the merged head."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    head_f = _head(wt)  # the PR head GitHub merged
    # Squash-merge on the "remote": a brand-new commit on main, parent == base,
    # feature's commit is NOT an ancestor.
    _git(main_repo, "merge", "--squash", "feature/x")
    _git(main_repo, "commit", "-m", "squash: feature work")
    _git(main_repo, "push", "origin", "main")
    squash_oid = _head(main_repo)
    # Rewind local main so the script must pull the squash commit.
    _git(main_repo, "reset", "--hard", "HEAD~1")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": squash_oid}, "headRefOid": head_f}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "ok"
    assert env["synced_to"] == squash_oid
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" not in branches
    assert not wt.exists()


def test_main_local_commit_beyond_merged_head_aborts(monkeypatch, main_repo):
    """A local commit made AFTER the merged head would be lost by branch -D —
    gate A must abort and name the orphan."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    head_f = _head(wt)  # what was merged
    _git(main_repo, "merge", "--squash", "feature/x")
    _git(main_repo, "commit", "-m", "squash: feature work")
    _git(main_repo, "push", "origin", "main")
    squash_oid = _head(main_repo)
    # A local commit beyond the merged head (never pushed / merged).
    (wt / "h.txt").write_text("extra local work\n")
    _git(wt, "add", "h.txt")
    _git(wt, "commit", "-m", "extra local work")
    orphan = _head(wt)
    _git(main_repo, "reset", "--hard", "HEAD~1")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": squash_oid}, "headRefOid": head_f}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "safety_gate_commits"
    assert orphan[:9] in json.dumps(env)
    assert wt.exists()  # nothing torn down


def test_main_merged_pr_without_head_oid_aborts(monkeypatch, main_repo):
    """A MERGED PR with no head SHA can't be containment-checked; abort rather
    than skip the gate and force-delete."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": None}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "safety_gate_commits"
    assert "head" in env["remediation_hint"].lower()
    assert wt.exists()


def test_main_branch_mismatch_in_worktree_aborts(monkeypatch, main_repo):
    """In a worktree, an explicit --branch differing from the checked-out branch
    is refused: gate B and teardown act on THIS checkout, so containment-checking
    and deleting a different ref (while removing this worktree) is incoherent."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "some-other-branch"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "preflight"
    assert "some-other-branch" in json.dumps(env)
    assert wt.exists()


def test_main_branch_mismatch_in_normal_repo_is_allowed(monkeypatch, main_repo):
    """Normal repo: deleting a merged branch other than the checked-out one is
    the normal workflow, so the worktree-only branch-match guard must NOT fire."""
    (main_repo / "g.txt").write_text("feature\n")
    _git(main_repo, "checkout", "-b", "feature/x")
    _git(main_repo, "add", "g.txt")
    _git(main_repo, "commit", "-m", "feature")
    _git(main_repo, "push", "origin", "feature/x")
    head_f = _head(main_repo)
    _git(main_repo, "checkout", "main")
    _git(main_repo, "merge", "--squash", "feature/x")
    _git(main_repo, "commit", "-m", "squash: feature")
    _git(main_repo, "push", "origin", "main")
    squash_oid = _head(main_repo)
    _git(main_repo, "reset", "--hard", "HEAD~1")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": squash_oid}, "headRefOid": head_f}
    rc, env = _run_main(monkeypatch, main_repo, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "ok"
    assert env["worktree_convention"] == "normal-repo"
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" not in branches


def test_main_rejects_dash_leading_branch(monkeypatch, main_repo):
    """A ref beginning with '-' would be parsed by git as an option on the
    destructive teardown/sync commands — refuse it before any git runs."""
    rc, env = _run_main(monkeypatch, main_repo, None, ["--branch=-x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "invalid_ref"


def test_main_dirty_claude_native_failure_omits_discard_handoff(monkeypatch, main_repo):
    """On a dirty-worktree abort the failure envelope must NOT hand back
    ExitWorktree(discard_changes: true) — that would destroy the changes the
    gate is protecting. Teardown steps are offered only once the gate passes."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "stray.txt").write_text("uncommitted\n")
    monkeypatch.setattr(m, "detect_convention", lambda w, r: m.Convention.CLAUDE_NATIVE)
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "safety_gate_worktree"
    assert env["steps_remaining"] == []


def test_main_unrecognised_worktree_is_named_not_unexpected(monkeypatch, main_repo):
    """UnrecognizedWorktree is a deliberate fail-loud outcome; it must surface as
    a named 'detect_convention' step, not fall into the generic 'unexpected'."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))

    def _raise(w, r):
        raise m.UnrecognizedWorktree("worktree at /x is under no known convention")

    monkeypatch.setattr(m, "detect_convention", _raise)
    rc, env = _run_main(monkeypatch, wt, None, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "detect_convention"


def test_main_gate_a_unresolvable_head_cmd_is_reconstructible(monkeypatch, main_repo):
    """When gate A's rev-list fails (head not resolvable locally), failed_step.cmd
    must be the actual command run — including -C <main_root> — via shlex.join."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": "0" * 40}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["failed_step"]["name"] == "safety_gate_commits"
    cmd = env["failed_step"]["cmd"]
    assert "-C" in cmd and env["main_root"] in cmd and "rev-list" in cmd


def test_main_sync_base_nonff_cmd_is_reconstructible(monkeypatch, main_repo):
    """A non-fast-forward pull aborts sync_base; failed_step.cmd must include the
    -C <main_root> actually used, reconstructed via shlex.join."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    head_f = _head(wt)
    _git(main_repo, "merge", "--squash", "feature/x")
    _git(main_repo, "commit", "-m", "squash: feature work")
    _git(main_repo, "push", "origin", "main")
    # Diverge local main from origin so `git pull --ff-only` fails.
    _git(main_repo, "checkout", "main")
    _git(main_repo, "reset", "--hard", "HEAD~1")
    (main_repo / "local-only.txt").write_text("diverge\n")
    _git(main_repo, "add", "local-only.txt")
    _git(main_repo, "commit", "-m", "local divergence")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": head_f}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["failed_step"]["name"] == "sync_base"
    cmd = env["failed_step"]["cmd"]
    assert "-C" in cmd and env["main_root"] in cmd and "--ff-only" in cmd


def test_main_operational_git_failure_is_named_step(monkeypatch, main_repo):
    """A failing operational git call (checkout of a base that doesn't exist)
    must surface as a named 'sync_base' step, not the generic 'unexpected'."""
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "no-such-base",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "sync_base"
    assert env["failed_step"]["name"] != "unexpected"


# --- Task 3: preflight resolves the worktree root (F6) ---


def test_symlinked_repo_root_still_classifies_convention(monkeypatch, main_repo, tmp_path):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    link = tmp_path / "link-to-repo"
    link.symlink_to(main_repo)
    # Enter the worktree THROUGH the symlink so --show-toplevel reports a
    # symlinked spelling while --git-common-dir resolves the real one.
    rc, env = _run_main(monkeypatch, link / ".worktrees" / "feature-x", None,
                        ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "not_merged"          # got past detect_convention
    assert env["worktree_convention"] == "other-agent"


# --- Task 4: detached HEAD aborts in plan preflight ---


def test_detached_head_without_branch_aborts(monkeypatch, main_repo):
    _git(main_repo, "checkout", "--detach")
    rc, env = _run_main(monkeypatch, main_repo, None, [])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "preflight"
    assert "detached" in env["remediation_hint"].lower()
