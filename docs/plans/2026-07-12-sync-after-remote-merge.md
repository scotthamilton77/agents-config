# Sync After Remote Merge — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Claude skill whose Python script deterministically reconciles local git state after a PR is merged remotely — verify merged, run two data-loss safety gates, fast-forward the base, tear down the branch/worktree at the harness boundary — emitting a JSON envelope; the skill composes with `merge-guard` for the "merge it" path.

**Architecture:** Pure core over value types (enums, dataclasses, dict builder) with git/`gh` confined to boundary functions and a `main(argv)->int` orchestrator, mirroring `gate_triage.py`. The script never merges. The `SKILL.md` handles agent-facing orchestration (compose with `merge-guard`, execute the Claude-native handoff). One rule edit wires it into the completion-gate delivery chain.

**Tech Stack:** Python 3.11+ (stdlib only — `argparse`, `json`, `subprocess`, `pathlib`, `dataclasses`, `enum`); `gh` CLI; git worktrees; pytest via `uv run --with pytest`.

**Spec:** `docs/specs/2026-07-12-sync-after-remote-merge.md`

---

## File Structure

- Create: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py` — the deterministic script (pure core + git/gh boundary + `main`).
- Create: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py` — pytest suite (pure-fn unit tests + `main()` integration tests over real tmp git repos, `gh` faked).
- Create: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.sh` — `uv run --with pytest` wrapper, mirroring `gate_triage_test.sh`.
- Create: `src/user/.claude/skills/sync-after-remote-merge/SKILL.md` — agent orchestration + `merge-guard` composition + trigger surface.
- Modify: `src/user/.agents/rules/completion-gate.md` — add `sync-after-remote-merge` as the terminal link in the HARD STOP delivery chain.

Placement is `src/user/.claude/skills/` (Claude-only): the skill depends on the `ExitWorktree` harness tool and the Skill tool (to invoke `merge-guard`), so it is not portable to the shared `.agents/` tree.

**Module API locked here (type-consistency contract for all tasks):**

```python
class Status(str, Enum):        # OK, HANDOFF, NOT_MERGED, FAILED   (values: "ok","handoff","not_merged","failed")
class Convention(str, Enum):    # NORMAL_REPO, OTHER_AGENT, CLAUDE_NATIVE  (values: "normal-repo","other-agent","claude-native")
class UnrecognizedWorktree(Exception): ...

build_envelope(status, *, steps_completed, failed_step, steps_remaining,
               worktree_convention, main_root, base, branch, pr,
               merge_commit, synced_to, remediation_hint) -> dict
classify_pr(pr_json: dict | None) -> PrState
detect_convention(worktree_root: Path, main_root: Path) -> Convention
dirty_paths(porcelain: str) -> list[str]
unmerged_commits(rev_list_output: str) -> list[str]
plan_teardown(convention, main_root: str, branch: str) -> list[str]
gh_pr_view(branch: str) -> dict | None        # boundary
_run(cmd, cwd=None, check=True) -> subprocess.CompletedProcess  # boundary
main(argv: list[str] | None = None) -> int
```

---

## Task 1: Module scaffold — enums, `PrState`, `build_envelope`

**Files:**
- Create: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

```python
# sync_after_remote_merge_test.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import sync_after_remote_merge as m  # noqa: E402


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'sync_after_remote_merge' has no attribute 'build_envelope'`.

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""sync_after_remote_merge.py — reconcile local git state after a PR merged remotely.

Pure core over value types; git + `gh` confined to boundary functions (_run,
gh_pr_view). Invoked by the sync-after-remote-merge skill:
  python3 sync_after_remote_merge.py [--branch <b>] [--base <b>] [--pr <n>]
Emits a JSON envelope on stdout on every exit path. The script NEVER merges.

Exit: 0 for ok/handoff/not_merged; non-zero for failed (a partial-state abort).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    OK = "ok"
    HANDOFF = "handoff"
    NOT_MERGED = "not_merged"
    FAILED = "failed"


class Convention(str, Enum):
    NORMAL_REPO = "normal-repo"
    OTHER_AGENT = "other-agent"
    CLAUDE_NATIVE = "claude-native"


class UnrecognizedWorktree(Exception):
    """The current worktree is under no convention the script can safely tear down."""


@dataclass(frozen=True)
class PrState:
    merged: bool
    pr: int | None
    merge_commit: str | None
    base: str | None
    head_oid: str | None
    reason: str


def build_envelope(
    status: Status,
    *,
    steps_completed: list[str] | tuple[str, ...] = (),
    failed_step: dict | None = None,
    steps_remaining: list[str] | tuple[str, ...] = (),
    worktree_convention: Convention | None = None,
    main_root: str | None = None,
    base: str | None = None,
    branch: str | None = None,
    pr: int | None = None,
    merge_commit: str | None = None,
    synced_to: str | None = None,
    remediation_hint: str | None = None,
) -> dict:
    """Assemble the JSON envelope with a stable key set (null where N/A)."""
    return {
        "status": status.value,
        "steps_completed": list(steps_completed),
        "failed_step": failed_step,
        "steps_remaining": list(steps_remaining),
        "worktree_convention": worktree_convention.value if worktree_convention else None,
        "main_root": main_root,
        "base": base,
        "branch": branch,
        "pr": pr,
        "merge_commit": merge_commit,
        "synced_to": synced_to,
        "remediation_hint": remediation_hint,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py \
        src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py
git commit -m "feat(sync-after-remote-merge): module scaffold — status/convention enums + envelope builder"
```

---

## Task 2: `classify_pr` — PR-state classification

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k classify_pr -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'classify_pr'`.

- [ ] **Step 3: Write minimal implementation**

Append to `sync_after_remote_merge.py`:

```python
def classify_pr(pr_json: dict | None) -> PrState:
    """Classify the `gh pr view` payload. Only state == 'MERGED' is a merge."""
    if not pr_json:
        return PrState(False, None, None, None, None, "no PR found for branch")
    state = pr_json.get("state")
    number = pr_json.get("number")
    base = pr_json.get("baseRefName")
    if state != "MERGED":
        return PrState(False, number, None, base, None,
                       f"PR #{number} state is {state!r}, not MERGED")
    merge_commit = (pr_json.get("mergeCommit") or {}).get("oid")
    return PrState(True, number, merge_commit, base, pr_json.get("headRefOid"), "merged")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k classify_pr -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/
git commit -m "feat(sync-after-remote-merge): classify_pr — MERGED-only PR-state classification"
```

---

## Task 3: `detect_convention` — worktree convention detection

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k detect_convention -v`
Expected: FAIL — `AttributeError: ... 'detect_convention'`.

- [ ] **Step 3: Write minimal implementation**

Append to `sync_after_remote_merge.py`:

```python
def detect_convention(worktree_root: Path, main_root: Path) -> Convention:
    """Which worktree convention (if any) owns teardown of this checkout.

    Claude-native (`.claude/worktrees/`) is checked before the bare-`worktrees`
    rule so a Claude path never falls through to OTHER_AGENT. A worktree under
    no known convention fails loud — the script must never git-remove a checkout
    it does not recognise.
    """
    if worktree_root == main_root:
        return Convention.NORMAL_REPO
    parts = worktree_root.parts
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return Convention.CLAUDE_NATIVE
    if ".worktrees" in parts or "worktrees" in parts:
        return Convention.OTHER_AGENT
    raise UnrecognizedWorktree(
        f"worktree at {worktree_root} is under neither .claude/worktrees/ nor "
        ".worktrees/; tear it down manually"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k detect_convention -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/
git commit -m "feat(sync-after-remote-merge): detect_convention — three-way worktree detection, fail-loud on unknown"
```

---

## Task 4: Safety gates — `dirty_paths` and `unmerged_commits`

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k "dirty_paths or unmerged_commits" -v`
Expected: FAIL — attributes not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `sync_after_remote_merge.py`:

```python
def dirty_paths(porcelain: str) -> list[str]:
    """Parse `git status --porcelain` into changed/untracked paths (XY-prefix stripped)."""
    return [ln[3:] for ln in porcelain.splitlines() if ln.strip()]


def unmerged_commits(rev_list_output: str) -> list[str]:
    """Commit SHAs on the branch not reachable from the merge commit (empty == fully merged).

    Fed by `git -C <main> rev-list <merge_commit>..<branch>`.
    """
    return [ln.strip() for ln in rev_list_output.splitlines() if ln.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k "dirty_paths or unmerged_commits" -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/
git commit -m "feat(sync-after-remote-merge): safety-gate parsers — dirty_paths + unmerged_commits"
```

---

## Task 5: `plan_teardown` — handoff-vs-scripted teardown

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k plan_teardown -v`
Expected: FAIL — `'plan_teardown'` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `sync_after_remote_merge.py`:

```python
def plan_teardown(convention: Convention, main_root: str, branch: str) -> list[str]:
    """Teardown steps the AGENT must run after the script.

    Claude-native worktrees are harness-owned: the script cannot git-remove them
    (and the live worktree blocks `branch -D`), so it hands back the exact
    ExitWorktree + branch-delete calls. NORMAL_REPO and OTHER_AGENT teardown is
    executed by the script itself, so nothing remains for the agent.
    """
    if convention is Convention.CLAUDE_NATIVE:
        return [
            "ExitWorktree(discard_changes: true)",
            f"git -C {main_root} branch -D {branch}",
        ]
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k plan_teardown -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/
git commit -m "feat(sync-after-remote-merge): plan_teardown — Claude-native handoff vs scripted removal"
```

---

## Task 6: Boundary functions + `main()` orchestration

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py`
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Write the failing test**

Add a shared git-repo fixture and integration tests. These build a real main repo + worktree and fake only `gh_pr_view`.

```python
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


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
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(m, "gh_pr_view", lambda branch: pr_json)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(argv)
    return rc, json.loads(buf.getvalue())


def test_main_not_merged_when_no_pr(monkeypatch, main_repo):
    _git(main_repo, "checkout", "-b", "feature/x")
    rc, env = _run_main(monkeypatch, main_repo, None, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "not_merged"
    assert "verify_merged" not in env["steps_completed"] or env["merge_commit"] is None


def test_main_dirty_worktree_aborts(monkeypatch, main_repo):
    # Simulate an other-agent worktree so teardown would otherwise be scripted.
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "stray.txt").write_text("uncommitted\n")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(main_repo)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "safety_gate_worktree"
    assert "stray.txt" in env["remediation_hint"] or "stray.txt" in json.dumps(env)


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
    # Reset local main back so the script has to pull the merge.
    _git(main_repo, "reset", "--hard", "HEAD~1")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": merge_oid}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "ok"
    assert env["worktree_convention"] == "other-agent"
    assert env["steps_remaining"] == []
    # Branch gone, worktree gone, main synced.
    branches = subprocess.run(["git", "branch"], cwd=main_repo, capture_output=True, text=True).stdout
    assert "feature/x" not in branches
    assert not wt.exists()


def test_main_claude_native_hands_off(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"  # real worktree location
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    # Force the Claude-native branch of teardown regardless of the real path.
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


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -k main_ -v`
Expected: FAIL — `main` / `gh_pr_view` not defined.

- [ ] **Step 3: Write minimal implementation**

Append the boundary + orchestrator to `sync_after_remote_merge.py`:

```python
class _AbortStep(Exception):
    """Raised to abort with a named failed_step; carries envelope-ready detail."""

    def __init__(self, name: str, hint: str, *, cmd: str = "", exit_code: int = 1, stderr: str = ""):
        super().__init__(hint)
        self.failed_step = {"name": name, "cmd": cmd, "exit_code": exit_code, "stderr": stderr}
        self.hint = hint


def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def gh_pr_view(branch: str) -> dict | None:
    """Return the PR payload for `branch`, or None when no PR is associated.

    Distinguishes 'no PR found' (→ None → not_merged) from a hard gh failure
    (auth/network → raise, so main reports `failed` rather than a false
    not_merged).
    """
    proc = _run(
        ["gh", "pr", "view", branch, "--json",
         "number,state,mergedAt,mergeCommit,baseRefName,headRefOid"],
        check=False,
    )
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    err = (proc.stderr or "").lower()
    if "no pull requests found" in err or "no pull request found" in err or "not found" in err:
        return None
    raise _AbortStep("verify_merged", f"gh pr view failed: {proc.stderr.strip()}",
                     cmd=f"gh pr view {branch}", exit_code=proc.returncode, stderr=proc.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile local git state after a remote merge.")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--pr", default=None)  # accepted for symmetry; PR is resolved from branch
    args = parser.parse_args(argv)

    completed: list[str] = []
    main_root = base = branch = merge_commit = synced_to = None
    convention: Convention | None = None
    pr_number: int | None = None

    try:
        # --- preflight ---
        worktree_root = Path(_run(["git", "rev-parse", "--show-toplevel"]).stdout.strip())
        common = Path(_run(["git", "rev-parse", "--git-common-dir"]).stdout.strip()).resolve()
        main_root = str(common.parent)
        branch = args.branch or _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        convention = detect_convention(worktree_root, Path(main_root))
        completed.append("preflight")

        # --- verify merged ---
        pr_state = classify_pr(gh_pr_view(branch))
        pr_number = pr_state.pr
        base = args.base or pr_state.base or _default_base(main_root)
        if not pr_state.merged:
            print(json.dumps(build_envelope(
                Status.NOT_MERGED, steps_completed=completed, worktree_convention=convention,
                main_root=main_root, base=base, branch=branch, pr=pr_number,
                remediation_hint=pr_state.reason)))
            return 0
        merge_commit = pr_state.merge_commit
        completed.append("verify_merged")

        # Make the merge commit available locally for the containment check.
        _run(["git", "-C", main_root, "fetch", "origin", base], check=False)

        # --- safety gate A: no unmerged local commits ---
        if merge_commit:
            rev = _run(["git", "-C", main_root, "rev-list", f"{merge_commit}..{branch}"], check=False)
            orphans = unmerged_commits(rev.stdout) if rev.returncode == 0 else None
            if orphans is None:
                raise _AbortStep("safety_gate_commits",
                                 f"cannot confirm {branch} is contained in the merge "
                                 f"({merge_commit[:9]} not resolvable locally)",
                                 cmd=f"git rev-list {merge_commit}..{branch}")
            if orphans:
                raise _AbortStep("safety_gate_commits",
                                 f"{branch} has {len(orphans)} commit(s) not in the merge "
                                 f"(would be lost): {', '.join(s[:9] for s in orphans)}")
        completed.append("safety_gate_commits")

        # --- safety gate B: clean worktree ---
        strays = dirty_paths(_run(["git", "-C", str(worktree_root), "status", "--porcelain"]).stdout)
        if strays:
            raise _AbortStep("safety_gate_worktree",
                             f"worktree is dirty; refusing to discard: {', '.join(strays)}")
        completed.append("safety_gate_worktree")

        # --- sync base (fast-forward only) ---
        _run(["git", "-C", main_root, "checkout", base])
        ff = _run(["git", "-C", main_root, "pull", "--ff-only"], check=False)
        if ff.returncode != 0:
            raise _AbortStep("sync_base",
                             f"base {base!r} is not fast-forwardable (local diverged); sync by hand",
                             cmd="git pull --ff-only", exit_code=ff.returncode, stderr=ff.stderr)
        synced_to = _run(["git", "-C", main_root, "rev-parse", "HEAD"]).stdout.strip()
        completed.append("sync_base")

        # --- teardown ---
        remaining = plan_teardown(convention, main_root, branch)
        if convention is Convention.CLAUDE_NATIVE:
            print(json.dumps(build_envelope(
                Status.HANDOFF, steps_completed=completed, steps_remaining=remaining,
                worktree_convention=convention, main_root=main_root, base=base, branch=branch,
                pr=pr_number, merge_commit=merge_commit, synced_to=synced_to,
                remediation_hint="sync done; finish teardown via the two steps in steps_remaining")))
            return 0
        if convention is Convention.OTHER_AGENT:
            _run(["git", "-C", main_root, "worktree", "remove", str(worktree_root)])
        _run(["git", "-C", main_root, "branch", "-D", branch])
        if convention is Convention.OTHER_AGENT:
            _run(["git", "-C", main_root, "worktree", "prune"], check=False)
        completed.append("teardown")

        print(json.dumps(build_envelope(
            Status.OK, steps_completed=completed, worktree_convention=convention,
            main_root=main_root, base=base, branch=branch, pr=pr_number,
            merge_commit=merge_commit, synced_to=synced_to,
            remediation_hint="branch deleted, worktree removed, base synced")))
        return 0

    except _AbortStep as abort:
        remaining = plan_teardown(convention, main_root or "", branch or "") if convention else []
        print(json.dumps(build_envelope(
            Status.FAILED, steps_completed=completed, failed_step=abort.failed_step,
            steps_remaining=remaining, worktree_convention=convention, main_root=main_root,
            base=base, branch=branch, pr=pr_number, merge_commit=merge_commit,
            synced_to=synced_to, remediation_hint=abort.hint)))
        return 1
    except Exception as exc:  # fail closed on any unexpected error
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        one_line = next((ln.strip() for ln in detail.splitlines() if ln.strip()), repr(exc))
        print(json.dumps(build_envelope(
            Status.FAILED, steps_completed=completed,
            failed_step={"name": "unexpected", "cmd": "", "exit_code": 1, "stderr": one_line},
            worktree_convention=convention, main_root=main_root, base=base, branch=branch,
            pr=pr_number, merge_commit=merge_commit, synced_to=synced_to,
            remediation_hint=f"unexpected failure: {one_line}")))
        return 1


def _default_base(main_root: str) -> str:
    """Repo default branch via origin/HEAD, falling back to 'main'."""
    proc = _run(["git", "-C", main_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return "main"


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -v`
Expected: PASS (all unit + integration tests green).

- [ ] **Step 5: Add the test-runner wrapper and commit**

Create `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.sh`:

```bash
#!/usr/bin/env bash
# Smoke-runs the sync-after-remote-merge pytest suite via uv (stdlib-only + pytest).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --with pytest python -m pytest "$HERE/sync_after_remote_merge_test.py" -v
```

```bash
chmod +x src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.sh
git add src/user/.claude/skills/sync-after-remote-merge/
git commit -m "feat(sync-after-remote-merge): boundary + main() orchestrator with fail-loud envelopes + test wrapper"
```

---

## Task 7: `SKILL.md` — agent orchestration and `merge-guard` composition

**Files:**
- Create: `src/user/.claude/skills/sync-after-remote-merge/SKILL.md`

No test (documentation asset). Verified by reading against the spec §3.3.

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: sync-after-remote-merge
description: Use after a PR has been merged remotely (on GitHub) to clean up and sync the local workspace — "clean up and sync main", "the PR merged, tidy up", "sync main after the merge", "tear down the worktree". Verifies the merge, runs data-loss safety gates, fast-forwards the base branch, and tears down the feature branch and worktree. Also the post-merge step of "merge it" (composes with merge-guard). Do NOT use to decide how to integrate unmerged work — that is finishing-a-development-branch.
---

# Sync After Remote Merge

Reconciles local git state once a PR is **already merged remotely**. This is the
last mile of the delivery chain, after `merge`. It does NOT merge — merging is
`merge-guard`'s job (see Composition below).

**Announce at start:** "I'm using the sync-after-remote-merge skill to clean up and sync."

## When to use

- The user says "clean up and sync main", "tidy up after the merge", "the PR's
  merged, sync main", or asks to tear down the worktree after a merge.
- As the automatic post-merge step in the completion-gate delivery chain.

Do NOT use it to choose merge/PR/keep/discard for *unmerged* work — that is
`finishing-a-development-branch`, which runs before a PR exists.

## The script

Run from the worktree being cleaned up:

    python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py [--branch <b>] [--base <b>]

It verifies the PR merged, runs two data-loss safety gates (no unmerged local
commits; clean worktree), fast-forwards the base, and tears down. It emits a
JSON envelope on stdout and never merges.

### Reading the envelope

- `status: "ok"` — done: branch deleted, worktree removed (other-agent/normal
  repo), base synced. Report the result.
- `status: "handoff"` — Claude-native worktree. The script synced the base but
  cannot remove a harness-owned worktree. **Run each step in `steps_remaining`
  in order**: first the `ExitWorktree(discard_changes: true)` tool call, then the
  `git -C <main_root> branch -D <branch>` shell command. Then report done.
- `status: "not_merged"` — no merged PR for this branch. Do **not** merge on a
  cleanup request; tell the user there is nothing merged to clean up. (If the
  user's instruction was an explicit "merge it", see Composition.)
- `status: "failed"` — a safety gate or step aborted. Read `failed_step` and
  `remediation_hint`, surface them to the user, and remediate the exact
  condition (dirty worktree → deal with the listed strays; unmerged commits →
  preserve them; non-fast-forward base → reconcile by hand). Do not force past a
  gate.

## Composition — the "merge it" path

If the PR is **not yet merged** and the user gave an explicit merge instruction
("merge it", "ship it", "go ahead and merge"), do not treat `not_merged` as the
end:

1. Invoke `merge-guard` — the single governed merge door. It resolves the
   repo's merge-authorization policy, checks the eligibility floor, and merges
   only if authorized and eligible (including its own tightly-gated `--admin`
   ladder where genuinely warranted).
2. Only if `merge-guard` confirms the merge, run this skill's script to clean up.
3. If `merge-guard` declines or hands off to a human, stop — do not clean up.

This skill never runs `gh pr merge` and has no merge flags. It composes with
`merge-guard`; it does not reimplement merging.

## Red flags

- Never infer a merge from the user's say-so — the script confirms via `gh`.
- Never force past a `failed` safety gate; nothing merged should cost local work.
- Never git-remove a Claude-native worktree; complete the `handoff` steps.
- Never merge from this skill; route "merge it" through `merge-guard`.
```

- [ ] **Step 2: Verify against the spec**

Read `SKILL.md` against spec §3.3: description carries the trigger surface; the four envelope statuses are handled; the Claude-native handoff runs `ExitWorktree` then `branch -D`; composition routes "merge it" through `merge-guard`; no repo-internal file paths in the body (only the deployed `~/.claude/skills/...` runtime path). Fix inline if any are missing.

- [ ] **Step 3: Commit**

```bash
git add src/user/.claude/skills/sync-after-remote-merge/SKILL.md
git commit -m "docs(sync-after-remote-merge): SKILL.md — orchestration, envelope handling, merge-guard composition"
```

---

## Task 8: Wire into the completion-gate rule

**Files:**
- Modify: `src/user/.agents/rules/completion-gate.md` (the HARD STOP delivery-chain sentence)

No test (prose rule). Verified by reading the amended chain.

- [ ] **Step 1: Locate the exact chain sentence**

Run: `grep -n "you pause only at the merge step" src/user/.agents/rules/completion-gate.md`
Expected: one match inside the HARD STOP paragraph. The current text reads:
`… The automatic scope runs all the way through PR-review monitoring; you pause only at the merge step. Merging follows the repo's merge-authorization policy via merge-guard …`

- [ ] **Step 2: Insert the post-merge cleanup link**

Edit the sentence that begins `In order:` to append the cleanup step, and add a clause after the merge sentence. Change:

`In order: \`using-git-worktrees\` (if not already isolated) → \`finishing-a-development-branch\` (create the PR) → **PR-review monitoring** → merge.`

to:

`In order: \`using-git-worktrees\` (if not already isolated) → \`finishing-a-development-branch\` (create the PR) → **PR-review monitoring** → merge → \`sync-after-remote-merge\` (reconcile local state).`

Then, immediately after the existing sentence ending `… a repo may have opted into \`rule-based\`.`, append:

`Once the merge lands, run \`sync-after-remote-merge\` to reconcile local state — fast-forward the base, and tear down the feature branch and worktree — closing the delivery chain's last mile; on a Claude-native worktree, complete its \`handoff\` by running the \`ExitWorktree\` + \`branch -D\` steps it returns.`

- [ ] **Step 3: Verify the amended chain**

Run: `grep -n "sync-after-remote-merge" src/user/.agents/rules/completion-gate.md`
Expected: two matches (chain arrow + the appended sentence). Re-read the paragraph to confirm it flows and the merge-authorization wording is untouched.

- [ ] **Step 4: Commit**

```bash
git add src/user/.agents/rules/completion-gate.md
git commit -m "feat(completion-gate): wire sync-after-remote-merge as the post-merge last-mile link"
```

---

## Task 9: End-to-end verification (manual)

**Files:** none (verification task).

The spec mandates a real end-to-end run, not just unit tests, before this is called done.

- [ ] **Step 1: Full suite green**

Run: `bash src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.sh`
Expected: all tests pass.

- [ ] **Step 2: Real merged-PR dry exercise (Claude-native handoff path)**

In this actual worktree (`.claude/worktrees/sync-after-remote-merge`), after this
work's own PR is merged, run the script against it and confirm it returns
`status: "handoff"` with the two `steps_remaining`, that the base fast-forwards,
and that the worktree is left intact for the `ExitWorktree` handoff. Capture the
emitted envelope as evidence. (This doubles as the delivery cleanup for this very
branch — dogfooding the skill.)

- [ ] **Step 3: Record evidence**

Paste the passing test summary and the real-run envelope into the completion
report / PR description as the mechanical evidence for `agents-config-vaac.7`.

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §2.1 standalone skill + Python script + tests → Tasks 1–7. ✓
- §2.2 never merges / composes with merge-guard → Task 6 (no merge code), Task 7 (composition). ✓
- §2.3 JSON envelope, house style → Task 1 `build_envelope`, Task 6 all exit paths. ✓
- §2.4 two data-loss safety gates + ff-only → Task 4 parsers, Task 6 gates A/B + `--ff-only` abort. ✓
- §2.5 teardown split at harness boundary → Task 5 `plan_teardown`, Task 6 convention switch. ✓
- §2.6 completion-gate wiring → Task 8. ✓
- §3.2 step sequence + envelope keys → Tasks 1, 6. ✓
- §3.2 unrecognised worktree fails loud → Task 3. ✓
- §5 unit + manual e2e + deployed-test guard → Tasks 1–6 (no repo-internal paths in tests → no skipTest guard needed), Task 9. ✓

**Placeholder scan:** none — every code/step is complete and runnable.

**Type consistency:** `Status`/`Convention` values, `PrState` fields, `build_envelope` keys, and `plan_teardown` output are identical across Tasks 1–8. `gh_pr_view`/`detect_convention` are monkeypatch points used consistently in Task 6 tests.

**Spec refinements adopted (code supersets spec, no conflict):** `failed_step` is always present as a stable key (null unless `failed`), rather than omitted; an unrecognised worktree location is an explicit `failed` abort. Both are documented in Tasks 3 and 6.
