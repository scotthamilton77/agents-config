# Sync After Remote Merge — Two-Phase Rework Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `sync_after_remote_merge.py` from single-phase execute-everything into the spec'd two-phase plan/finish contract, so no destructive git action ever crosses a process-ownership boundary un-gated.

**Architecture:** Plan mode (default) is strictly read-only — verify merge, run gates, hand back ONE shell command. Finish mode (`--finish`) runs from the main root after the caller evacuated via `cd`; it re-gates all mutable state adjacent to each mutation and carries immutable post-merge facts via `--branch-sha`. Spec: `docs/specs/2026-07-12-sync-after-remote-merge.md` (§3.2 is the contract; read it before starting).

**Tech Stack:** Python 3 stdlib only (+ pytest via `uv run --with pytest`). Tests use the existing real-tmp-git-repo fixtures (`main_repo`, `_run_main`) in `sync_after_remote_merge_test.py`.

**Working directory — all commands run from the worktree root:**
`/Users/scott/src/projects/agents-config/.claude/worktrees/sync-after-remote-merge`
(branch `worktree-sync-after-remote-merge`, PR #255). Verify first: `git rev-parse --show-toplevel` must print that path.

**Test command (used throughout):**
```bash
uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -q
```

**File structure (all changes):**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py` — the rework
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py` — extend + update
- Modify: `src/user/.claude/skills/sync-after-remote-merge/SKILL.md` — envelope-reading guidance
- Modify: `project-config.toml` — `gates.test` discovery
- Out of scope: F5 (shared completion-gate rule portability) — deferred continuation per spec §6.

**Existing tests that MUST change (they assert the old single-phase behavior):**
`test_envelope_has_all_stable_keys` (new keys), `test_main_other_agent_full_teardown` (now emits `handoff`, not `ok`), `test_main_claude_native_hands_off` (`steps_remaining` now ends with the finish command), and the `plan_teardown` tests (function replaced by `plan_handoff_steps`/`build_finish_command`). Each task below says exactly what to do with them. Every other existing test stays green untouched.

---

### Task 1: Envelope schema — `phase`, `branch_sha`, `ignored_paths`

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py` (`Status`/enums area + `build_envelope`)
- Test: `src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py`

- [ ] **Step 1: Update the stable-keys test and add a phase test**

Replace the body of `test_envelope_has_all_stable_keys` and add one test after it:

```python
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
```

- [ ] **Step 2: Run to verify failure** — `uv run --with pytest python -m pytest src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.py -q -k envelope`. Expected: FAIL (`Phase` not defined / unexpected keyword).

- [ ] **Step 3: Implement**

Add below `Status`:

```python
class Phase(str, Enum):
    PLAN = "plan"
    FINISH = "finish"
```

Change `build_envelope`'s signature to add `phase: Phase, branch_sha: str | None = None, ignored_paths: list[str] | tuple[str, ...] = ()` (make `phase` the second positional-or-keyword parameter) and add to the returned dict, keeping key order matching the test:

```python
        "status": status.value,
        "phase": phase.value,
        ...
        "branch": branch,
        "branch_sha": branch_sha,
        ...
        "synced_to": synced_to,
        "ignored_paths": list(ignored_paths),
        "remediation_hint": remediation_hint,
```

`_emit` gains the same required `phase` parameter and passes it through: `def _emit(status, phase, **fields)`. Update every existing `_emit(...)` call site in `main()` to pass `phase=Phase.PLAN` for now (finish-mode call sites arrive in Tasks 7–11).

- [ ] **Step 4: Run the full suite** — expected: PASS (all tests).
- [ ] **Step 5: Commit** — `git add -A src/user/.claude/skills/sync-after-remote-merge && git commit -m "feat(sync-after-remote-merge): envelope carries phase, branch_sha, ignored_paths"`

---

### Task 2: Argument errors still emit the JSON envelope

**Files:** same two files.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (`SystemExit` escapes / no JSON on stdout).

- [ ] **Step 3: Implement**

Replace the parser construction in `main()` with an error-raising parser and a phase sniff:

```python
class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would SystemExit; we must envelope instead
        raise _ArgError(message)


def _parse(raw: list[str]) -> argparse.Namespace:
    parser = _Parser(description="Reconcile local git state after a remote merge.")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--finish", action="store_true")
    parser.add_argument("--worktree", default=None)
    parser.add_argument("--branch-sha", dest="branch_sha", default=None)
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--merge-commit", dest="merge_commit", default=None)
    return parser.parse_args(raw)
```

And at the top of `main()`:

```python
def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    phase = Phase.FINISH if "--finish" in raw else Phase.PLAN
    try:
        args = _parse(raw)
    except _ArgError as exc:
        _emit(Status.FAILED, phase,
              failed_step={"name": "args", "cmd": "", "exit_code": 2, "stderr": str(exc)},
              remediation_hint=f"invalid arguments: {exc}")
        return 1
```

(Finish-mode required-argument enforcement lands in Task 7; here only parsing.)

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "fix(sync-after-remote-merge): argument errors emit the failed envelope (Codex P2)"`

---

### Task 3: Preflight resolves the worktree root (F6) + symlinked-root regression

**Files:** same two files.

- [ ] **Step 1: Write the failing test** (append; `tmp_path` is realpath'd by pytest, so build the symlink by hand — `skipTest`-guard is unnecessary since everything stays under `tmp_path`):

```python
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
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL with `UnrecognizedWorktree` surfacing as `failed`/`detect_convention` (the unresolved toplevel doesn't prefix-match the resolved main root).

- [ ] **Step 3: Implement** — in `main()`'s preflight, resolve the toplevel:

```python
        worktree_root = Path(_run_step(["git", "rev-parse", "--show-toplevel"],
                                       "preflight", "not inside a git repository").stdout.strip()).resolve()
```

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "fix(sync-after-remote-merge): resolve worktree root; symlinked-root regression test (F6)"`

---

### Task 4: Detached HEAD aborts in plan preflight

**Files:** same two files.

- [ ] **Step 1: Write the failing test**

```python
def test_detached_head_without_branch_aborts(monkeypatch, main_repo):
    _git(main_repo, "checkout", "--detach")
    rc, env = _run_main(monkeypatch, main_repo, None, [])
    assert rc != 0
    assert env["status"] == "failed"
    assert env["failed_step"]["name"] == "preflight"
    assert "detached" in env["remediation_hint"].lower()
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (the literal branch name `HEAD` flows onward and produces a different failure or a `not_merged`).

- [ ] **Step 3: Implement** — after `head_branch` is read in preflight:

```python
        if head_branch == "HEAD" and not args.branch:
            raise _AbortStep("preflight",
                             "HEAD is detached (no current branch); pass --branch "
                             "explicitly or check out the feature branch first")
```

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "fix(sync-after-remote-merge): detached HEAD aborts plan preflight"`

---

### Task 5: Worktree-gate policy — tracked/untracked/ignored classification

**Files:** same two files.

- [ ] **Step 1: Write the failing tests** (pure-function tests; porcelain `--ignored` marks ignored entries `!!`):

```python
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
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (functions not defined).

- [ ] **Step 3: Implement** (replaces the lone `dirty_paths` for gate use; keep `dirty_paths` deleted — its two call sites move to these):

```python
def classify_status_paths(porcelain: str) -> tuple[list[str], list[str], list[str]]:
    """Split `git status --porcelain --ignored` into (tracked, untracked, ignored)."""
    tracked, untracked, ignored = [], [], []
    for ln in porcelain.splitlines():
        if not ln.strip():
            continue
        prefix, path = ln[:2], ln[3:]
        if prefix == "!!":
            ignored.append(path)
        elif prefix == "??":
            untracked.append(path)
        else:
            tracked.append(path)
    return tracked, untracked, ignored


def blocking_paths(tracked: list[str], untracked: list[str], convention: Convention) -> list[str]:
    """Paths that block teardown. Worktree conventions discard the directory, so
    untracked files block too; a normal repo discards nothing, so only tracked
    modifications block (matching the finish-mode main-root gate)."""
    if convention is Convention.NORMAL_REPO:
        return tracked
    return tracked + untracked
```

Rewire plan-mode gate B in `main()` to use them (status now runs with `--ignored`):

```python
        porcelain = _run_step(["git", "-C", str(worktree_root), "status", "--porcelain", "--ignored"],
                              "safety_gate_worktree", "cannot read worktree status").stdout
        tracked, untracked, ignored_paths = classify_status_paths(porcelain)
        strays = blocking_paths(tracked, untracked, convention)
        if strays:
            raise _AbortStep("safety_gate_worktree",
                             f"worktree is dirty; refusing to discard: {', '.join(strays)}")
        completed.append("safety_gate_worktree")
```

Thread `ignored_paths=ignored_paths` into the subsequent success `_emit` call (and update `test_main_dirty_worktree_aborts` only if it breaks — it should still pass: untracked `stray.txt` in an other-agent worktree still blocks).

- [ ] **Step 4: Run the full suite** — expected: PASS (delete the old `dirty_paths` tests in the same commit; `classify_status_paths` supersedes them).
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): untracked/ignored gate policy per convention (F2 policy)"`

---

### Task 6: Plan mode never mutates — universal handoff with the finish command

This is the pivotal task: it deletes sync/teardown from the plan path.

**Files:** same two files.

- [ ] **Step 1: Rewrite the affected tests**

Replace `test_main_other_agent_full_teardown` with:

```python
def test_main_other_agent_plan_hands_off(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(wt)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "handoff" and env["phase"] == "plan"
    assert env["branch_sha"] == _head(wt)
    assert wt.exists()                                    # nothing removed
    assert len(env["steps_remaining"]) == 1
    cmd = env["steps_remaining"][0]
    assert cmd.startswith(f"cd {env['main_root']} && ")
    for frag in ("--finish", "--worktree", "--branch feature/x",
                 f"--branch-sha {_head(wt)}", "--base main", "--pr 1"):
        assert frag in cmd
    # plan mode must NOT have synced the base either
    assert env["synced_to"] is None


def test_main_claude_native_handoff_orders_exitworktree_first(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    monkeypatch.setattr(m, "detect_convention", lambda w, r: m.Convention.CLAUDE_NATIVE)
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": _head(wt)}, "headRefOid": _head(wt)}
    rc, env = _run_main(monkeypatch, wt, pr, ["--branch", "feature/x"])
    assert rc == 0 and env["status"] == "handoff"
    assert env["steps_remaining"][0] == "ExitWorktree(discard_changes: true)"
    assert "--finish" in env["steps_remaining"][1]
    assert wt.exists()


def test_build_finish_command_quotes_spaced_paths():
    cmd = m.build_finish_command(
        main_root="/My Repos/x", worktree_root="/My Repos/x/.worktrees/f",
        branch="feature/x", branch_sha="abc", base="main", pr=7, merge_commit="def")
    assert cmd.startswith("cd '/My Repos/x' && python3 ")
    assert "--worktree '/My Repos/x/.worktrees/f'" in cmd
    assert "--merge-commit def" in cmd


def test_build_finish_command_omits_null_merge_commit():
    cmd = m.build_finish_command(main_root="/r", worktree_root="/r", branch="b",
                                 branch_sha="abc", base="main", pr=None, merge_commit=None)
    assert "--merge-commit" not in cmd and "--pr" not in cmd


def test_main_normal_repo_plan_hands_off_and_permits_untracked(monkeypatch, main_repo):
    _git(main_repo, "checkout", "-b", "feature/x")
    (main_repo / "g.txt").write_text("feature\n")
    _git(main_repo, "add", "g.txt")
    _git(main_repo, "commit", "-m", "feature work")
    _git(main_repo, "push", "origin", "feature/x")
    sha = _head(main_repo)
    (main_repo / "scratch.txt").write_text("untracked; must not block a normal repo\n")
    pr = {"number": 1, "state": "MERGED", "baseRefName": "main",
          "mergeCommit": {"oid": sha}, "headRefOid": sha}
    rc, env = _run_main(monkeypatch, main_repo, pr, ["--branch", "feature/x"])
    assert rc == 0
    assert env["status"] == "handoff"                      # every convention hands off
    assert env["worktree_convention"] == "normal-repo"
    assert len(env["steps_remaining"]) == 1
    assert "--finish" in env["steps_remaining"][0]
```

Update `test_main_claude_native_hands_off`: delete it (superseded by the ordering test above). Delete the `plan_teardown` unit tests (`plan_teardown` is removed).

- [ ] **Step 2: Run to verify failure** — expected: FAIL (`build_finish_command` undefined; other-agent path still tears down).

- [ ] **Step 3: Implement**

```python
def build_finish_command(*, main_root: str, worktree_root: str, branch: str,
                         branch_sha: str, base: str, pr: int | None,
                         merge_commit: str | None) -> str:
    """The single handed-back command. The leading `cd` is load-bearing: it
    evacuates the calling process from the worktree before anything removes it."""
    argv = ["python3", str(Path(__file__).resolve()), "--finish",
            "--worktree", str(worktree_root), "--branch", branch,
            "--branch-sha", branch_sha, "--base", base]
    if pr is not None:
        argv += ["--pr", str(pr)]
    if merge_commit:
        argv += ["--merge-commit", merge_commit]
    return f"cd {shlex.quote(str(main_root))} && {shlex.join(argv)}"


def plan_handoff_steps(convention: Convention, finish_cmd: str) -> list[str]:
    if convention is Convention.CLAUDE_NATIVE:
        return ["ExitWorktree(discard_changes: true)", finish_cmd]
    return [finish_cmd]
```

In plan-mode `main()`: after gate A passes, record the binding token:

```python
        branch_sha = _run_step(["git", "-C", main_root, "rev-parse", f"refs/heads/{branch}"],
                               "safety_gate_commits", "cannot resolve the branch tip").stdout.strip()
```

Then delete the entire `sync_base` block, the `os.chdir(main_root)`, and the whole teardown block from the plan path, replacing them (after gate B) with:

```python
        finish_cmd = build_finish_command(
            main_root=main_root, worktree_root=str(worktree_root), branch=branch,
            branch_sha=branch_sha, base=base, pr=pr_number, merge_commit=merge_commit)
        _emit(Status.HANDOFF, Phase.PLAN, steps_completed=completed,
              steps_remaining=plan_handoff_steps(convention, finish_cmd),
              worktree_convention=convention, main_root=main_root, base=base,
              branch=branch, branch_sha=branch_sha, pr=pr_number,
              merge_commit=merge_commit, ignored_paths=ignored_paths,
              remediation_hint="read-only checks passed; run each step in steps_remaining in order")
        return 0
```

Also remove `plan_teardown` and the `_AbortStep` handler's `plan_teardown(...)` call (`steps_remaining` on failure is now always `[]` from plan mode — a failed plan run has nothing safe to hand back). Update the handler accordingly.

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): plan mode is read-only, hands back one finish command (F1)"`

---

### Task 7: Finish preflight — identity checks

**Files:** same two files.

- [ ] **Step 1: Write the failing tests** (add a finish-mode runner beside `_run_main`):

```python
def _run_finish(monkeypatch, cwd, argv):
    import contextlib, io
    monkeypatch.chdir(cwd)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main(["--finish", *argv])
    return rc, json.loads(buf.getvalue())


def _finish_args(main_repo, wt, sha, **over):
    a = {"worktree": str(wt), "branch": "feature/x", "branch_sha": sha, "base": "main"}
    a.update(over)
    return ["--worktree", a["worktree"], "--branch", a["branch"],
            "--branch-sha", a["branch_sha"], "--base", a["base"]]


def test_finish_requires_all_args(monkeypatch, main_repo):
    rc, env = _run_finish(monkeypatch, main_repo, ["--worktree", str(main_repo)])
    assert rc != 0 and env["status"] == "failed"
    assert env["failed_step"]["name"] in ("args", "preflight")


def test_finish_refuses_cwd_inside_target_worktree(monkeypatch, main_repo):
    wt = main_repo / ".worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    rc, env = _run_finish(monkeypatch, wt, _finish_args(main_repo, wt, _head(wt)))
    assert rc != 0
    assert env["failed_step"]["name"] == "preflight"
    assert "inside" in env["remediation_hint"]


def test_finish_refuses_relative_worktree_path(monkeypatch, main_repo):
    rc, env = _run_finish(monkeypatch, main_repo,
                          _finish_args(main_repo, ".worktrees/feature-x", "abc"))
    assert rc != 0 and env["failed_step"]["name"] == "preflight"


def test_finish_refuses_foreign_worktree_path(monkeypatch, main_repo, tmp_path):
    rc, env = _run_finish(monkeypatch, main_repo,
                          _finish_args(main_repo, tmp_path / "elsewhere", "abc"))
    assert rc != 0 and env["failed_step"]["name"] in ("preflight", "detect_convention")
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (finish mode not implemented; plan path runs instead).

- [ ] **Step 3: Implement** — route in `main()` after parsing: `if args.finish: return _main_finish(args)`, then extract the current plan body into `_main_plan(args)` unchanged. New:

```python
def _main_finish(args: argparse.Namespace) -> int:
    completed: list[str] = []
    convention: Convention | None = None
    main_root = synced_to = None
    try:
        for name, val in (("--worktree", args.worktree), ("--branch", args.branch),
                          ("--branch-sha", args.branch_sha), ("--base", args.base)):
            if not val:
                raise _AbortStep("preflight", f"--finish requires {name}")
        _require_safe_ref(args.branch, "branch")
        _require_safe_ref(args.base, "base")
        worktree = Path(args.worktree)
        if not worktree.is_absolute():
            raise _AbortStep("preflight", f"--worktree {args.worktree!r} must be absolute")
        toplevel = Path(_run_step(["git", "rev-parse", "--show-toplevel"],
                                  "preflight", "not inside a git repository").stdout.strip()).resolve()
        common = Path(_run_step(["git", "rev-parse", "--git-common-dir"],
                                "preflight", "cannot resolve the git common dir").stdout.strip()).resolve()
        main_root = str(common.parent)
        if toplevel != common.parent:
            raise _AbortStep("preflight",
                             f"finish mode must run from the main checkout {main_root}, "
                             f"not {toplevel} (did the handed-back `cd` run?)")
        convention = detect_convention(worktree, Path(main_root))
        if convention is not Convention.NORMAL_REPO and Path.cwd().resolve().is_relative_to(worktree):
            raise _AbortStep("preflight",
                             f"cwd is inside the worktree {worktree} this command would "
                             f"remove; cd to {main_root} first")
        completed.append("preflight")
        ...  # Tasks 8-11 continue here
```

Give `_main_finish` its own `except UnrecognizedWorktree / _AbortStep / Exception` tail mirroring `_main_plan`'s, with `phase=Phase.FINISH` and `steps_remaining=[]` always. (Worktree existence is deliberately NOT checked here — spec §3.2.2: lexical only; existence is convention-dependent, enforced in Task 8.)

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): finish-mode preflight identity gates"`

---

### Task 8: Finish re-gates the worktree (`regate_worktree`)

**Files:** same two files.

- [ ] **Step 1: Write the failing tests**

```python
def _merged_feature(main_repo, convention_dir=".worktrees"):
    """A merged feature worktree + rewound local main; returns (wt, sha)."""
    wt = main_repo / convention_dir / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    _git(main_repo, "merge", "feature/x")
    _git(main_repo, "push", "origin", "main")
    _git(main_repo, "reset", "--hard", "HEAD~1")
    return wt, _head(wt)


def test_finish_dirty_other_agent_worktree_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    (wt / "late.txt").write_text("appeared after plan\n")   # the F2 TOCTOU
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc != 0
    assert env["failed_step"]["name"] == "regate_worktree"
    assert "late.txt" in json.dumps(env)
    assert wt.exists()


def test_finish_worktree_on_wrong_branch_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    _git(wt, "checkout", "-b", "other-work")
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc != 0 and env["failed_step"]["name"] == "regate_worktree"


def test_finish_claude_native_worktree_still_present_aborts(monkeypatch, main_repo):
    wt = main_repo / ".claude" / "worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    _git(wt, "push", "origin", "feature/x")
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, _head(wt)))
    assert rc != 0
    assert env["failed_step"]["name"] == "regate_worktree"
    assert "ExitWorktree" in env["remediation_hint"]
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (`regate_worktree` step doesn't exist).

- [ ] **Step 3: Implement** — continue `_main_finish` after preflight:

```python
        branch_ref = _run(["git", "-C", main_root, "rev-parse", f"refs/heads/{args.branch}"],
                          check=False)
        branch_oid = branch_ref.stdout.strip() if branch_ref.returncode == 0 else None
        worktree_present = worktree.exists()
        terminal_noop = False
        ignored_paths: list[str] = []
        if convention is Convention.CLAUDE_NATIVE:
            if worktree_present:
                raise _AbortStep("regate_worktree",
                                 f"Claude-native worktree {worktree} still exists; run "
                                 f"ExitWorktree(discard_changes: true) first, then re-run this command")
        elif convention is Convention.OTHER_AGENT and worktree_present:
            wt_head = _run_step(["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
                                "regate_worktree", "cannot read the worktree's branch").stdout.strip()
            if wt_head != args.branch:
                raise _AbortStep("regate_worktree",
                                 f"worktree {worktree} is checked out on {wt_head!r}, not "
                                 f"{args.branch!r}; a recreated worktree must never be removed "
                                 f"on path identity alone")
            porcelain = _run_step(["git", "-C", str(worktree), "status", "--porcelain", "--ignored"],
                                  "regate_worktree", "cannot read worktree status").stdout
            tracked, untracked, ignored_paths = classify_status_paths(porcelain)
            strays = blocking_paths(tracked, untracked, convention)
            if strays:
                raise _AbortStep("regate_worktree",
                                 f"worktree is dirty; refusing to remove: {', '.join(strays)}")
            if branch_oid != args.branch_sha:
                raise _AbortStep("regate_worktree",
                                 f"{args.branch} is at {(branch_oid or 'missing')[:9]}, expected "
                                 f"{args.branch_sha[:9]} (branch moved since plan); re-run the "
                                 f"plan phase")
        if not worktree_present or convention is Convention.NORMAL_REPO:
            if branch_oid is None:
                terminal_noop = True          # prior finish completed teardown (idempotent re-run)
            elif convention is Convention.OTHER_AGENT and branch_oid != args.branch_sha:
                raise _AbortStep("regate_worktree",
                                 f"worktree {worktree} is gone but {args.branch} moved to "
                                 f"{branch_oid[:9]} (expected {args.branch_sha[:9]}); not a "
                                 f"resumable teardown — reconcile by hand")
        completed.append("regate_worktree")
```

- [ ] **Step 4: Run the full suite** — expected: PASS (the happy paths abort later at not-yet-implemented steps; only these gate tests are asserted).
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): finish re-gates the worktree adjacent to teardown (F2)"`

---

### Task 9: Finish gates the main root (F3)

**Files:** same two files.

- [ ] **Step 1: Write the failing tests**

```python
def test_finish_dirty_main_root_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    (main_repo / "f.txt").write_text("local edit\n")       # tracked modification
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc != 0
    assert env["failed_step"]["name"] == "gate_main_root"
    assert "f.txt" in json.dumps(env)


def test_finish_main_root_untracked_is_permitted(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    (main_repo / "scratch.txt").write_text("untracked, must not block\n")
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert env["failed_step"] is None or env["failed_step"]["name"] != "gate_main_root"
```

- [ ] **Step 2: Run to verify failure** — expected: FAIL (no `gate_main_root` step).

- [ ] **Step 3: Implement** — continue `_main_finish`:

```python
        porcelain = _run_step(["git", "-C", main_root, "status", "--porcelain"],
                              "gate_main_root", "cannot read main checkout status").stdout
        tracked, _untracked, _ignored = classify_status_paths(porcelain)
        if tracked:
            raise _AbortStep("gate_main_root",
                             f"main checkout {main_root} has tracked modifications; a branch "
                             f"switch would carry them: {', '.join(tracked)}")
        completed.append("gate_main_root")
```

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): gate the main root before mutating it (F3)"`

---

### Task 10: Finish syncs the base with `git switch` (F4)

**Files:** same two files.

- [ ] **Step 1: Write the failing tests**

```python
def test_finish_base_not_a_local_branch_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    rc, env = _run_finish(monkeypatch, main_repo,
                          _finish_args(main_repo, wt, sha, base="release"))
    assert rc != 0
    assert env["failed_step"]["name"] == "sync_base"
    assert "local" in env["remediation_hint"]


def test_finish_base_dot_is_rejected_not_path_checked_out(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    (main_repo / "f.txt").write_text("would be clobbered by a path checkout\n")
    args = _finish_args(main_repo, wt, sha)
    args[args.index("--base") + 1] = "."
    rc, env = _run_finish(monkeypatch, main_repo, args)
    assert rc != 0
    assert (main_repo / "f.txt").read_text() == "would be clobbered by a path checkout\n"


def test_finish_nonff_base_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    _git(main_repo, "commit", "--allow-empty", "-m", "local divergence")
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc != 0 and env["failed_step"]["name"] == "sync_base"
```

(Note: the `--base .` test passes through `gate_main_root` abort OR `sync_base` abort — both acceptable; the asserted invariant is the file survives.)

- [ ] **Step 2: Run to verify failure** — expected: FAIL (no `sync_base` in finish).

- [ ] **Step 3: Implement** — continue `_main_finish`:

```python
        verify = _run(["git", "-C", main_root, "rev-parse", "--verify", "--quiet",
                       f"refs/heads/{args.base}"], check=False)
        if verify.returncode != 0:
            raise _AbortStep("sync_base",
                             f"base {args.base!r} is not a local branch; create/check out the "
                             f"local base first (this deliberately defeats checkout's remote DWIM)")
        _run_step(["git", "-C", main_root, "switch", args.base], "sync_base",
                  f"cannot switch to base {args.base!r}")
        ff_argv = ["git", "-C", main_root, "pull", "--ff-only"]
        ff = _run(ff_argv, check=False)
        if ff.returncode != 0:
            raise _AbortStep("sync_base",
                             f"could not fast-forward base {args.base!r} (git pull --ff-only "
                             f"failed — local divergence, missing upstream, or network); "
                             f"reconcile by hand",
                             cmd=shlex.join(ff_argv), exit_code=ff.returncode, stderr=ff.stderr)
        synced_to = _run_step(["git", "-C", main_root, "rev-parse", "HEAD"], "sync_base",
                              "cannot read base HEAD after sync").stdout.strip()
        completed.append("sync_base")
```

- [ ] **Step 4: Run the full suite** — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): finish syncs base via git switch after verifying a local branch (F4)"`

---

### Task 11: Finish teardown — SHA-bound delete, idempotent terminal state

**Files:** same two files.

- [ ] **Step 1: Write the failing tests**

```python
def test_finish_other_agent_full_teardown(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc == 0
    assert env["status"] == "ok" and env["phase"] == "finish"
    assert not wt.exists()
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" not in branches
    assert env["synced_to"] == subprocess.run(
        ["git", "rev-parse", "main"], cwd=main_repo,
        capture_output=True, text=True).stdout.strip()


def test_finish_branch_moved_since_plan_aborts(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    (wt / "h.txt").write_text("new work\n")
    _git(wt, "add", "h.txt")
    _git(wt, "commit", "-m", "post-plan commit")           # branch tip advances
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc != 0
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" in branches                          # nothing deleted


def test_finish_resumable_partial_teardown(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    _git(main_repo, "worktree", "remove", str(wt))          # simulate prior crash
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc == 0 and env["status"] == "ok"
    branches = subprocess.run(["git", "branch"], cwd=main_repo,
                              capture_output=True, text=True).stdout
    assert "feature/x" not in branches


def test_finish_double_run_is_idempotent_ok(monkeypatch, main_repo):
    wt, sha = _merged_feature(main_repo)
    args = _finish_args(main_repo, wt, sha)
    rc1, _ = _run_finish(monkeypatch, main_repo, args)
    rc2, env2 = _run_finish(monkeypatch, main_repo, args)
    assert rc1 == 0 and rc2 == 0
    assert env2["status"] == "ok"
    assert "already" in env2["remediation_hint"]


def test_finish_claude_native_happy_path_accepts_absent_worktree(monkeypatch, main_repo):
    wt = main_repo / ".claude" / "worktrees" / "feature-x"
    _git(main_repo, "worktree", "add", "-b", "feature/x", str(wt))
    (wt / "g.txt").write_text("feature\n")
    _git(wt, "add", "g.txt")
    _git(wt, "commit", "-m", "feature work")
    _git(wt, "push", "origin", "feature/x")
    sha = _head(wt)
    _git(main_repo, "merge", "feature/x")
    _git(main_repo, "push", "origin", "main")
    _git(main_repo, "reset", "--hard", "HEAD~1")
    _git(main_repo, "worktree", "remove", "--force", str(wt))   # ExitWorktree stand-in
    rc, env = _run_finish(monkeypatch, main_repo, _finish_args(main_repo, wt, sha))
    assert rc == 0 and env["status"] == "ok"


def test_finish_through_symlinked_root_passes_preflight(monkeypatch, main_repo, tmp_path):
    """Spec §5: finish-mode path-equality checks must survive a symlinked repo
    spelling (cwd toplevel vs git-common-dir parent vs --worktree)."""
    wt, sha = _merged_feature(main_repo)
    link = tmp_path / "link-to-repo"
    link.symlink_to(main_repo)
    args = ["--worktree", str(link / ".worktrees" / "feature-x"), "--branch", "feature/x",
            "--branch-sha", sha, "--base", "main"]
    rc, env = _run_finish(monkeypatch, link, args)
    assert rc == 0 and env["status"] == "ok"
    assert not wt.exists()
```

(For the symlinked `--worktree` to compare equal, finish preflight must `.resolve()` the `--worktree` argument as well as the cwd toplevel — add `worktree = Path(args.worktree).resolve()` right after the absolute-path check in Task 7's preflight when this test goes red.)

- [ ] **Step 2: Run to verify failure** — expected: FAIL (finish never emits `ok`).

- [ ] **Step 3: Implement** — the tail of `_main_finish`:

```python
        if terminal_noop:
            _emit(Status.OK, Phase.FINISH, steps_completed=completed,
                  worktree_convention=convention, main_root=main_root, base=args.base,
                  branch=args.branch, branch_sha=args.branch_sha, pr=args.pr,
                  merge_commit=args.merge_commit, synced_to=synced_to,
                  remediation_hint=f"teardown already complete; base synced to {synced_to[:9]}")
            return 0
        if convention is Convention.OTHER_AGENT and worktree_present:
            _run_step(["git", "-C", main_root, "worktree", "remove", "--", str(worktree)],
                      "teardown", f"cannot remove worktree {worktree}")
        if branch_oid is not None:
            now = _run_step(["git", "-C", main_root, "rev-parse", f"refs/heads/{args.branch}"],
                            "teardown", "cannot re-read the branch tip").stdout.strip()
            if now != args.branch_sha:
                raise _AbortStep("teardown",
                                 f"{args.branch} moved to {now[:9]} (expected "
                                 f"{args.branch_sha[:9]}); refusing to delete")
            _run_step(["git", "-C", main_root, "branch", "-D", args.branch], "teardown",
                      f"cannot delete branch {args.branch}")
        if convention is Convention.OTHER_AGENT:
            _run(["git", "-C", main_root, "worktree", "prune"], check=False)
        completed.append("teardown")
        _emit(Status.OK, Phase.FINISH, steps_completed=completed,
              worktree_convention=convention, main_root=main_root, base=args.base,
              branch=args.branch, branch_sha=args.branch_sha, pr=args.pr,
              merge_commit=args.merge_commit, synced_to=synced_to, ignored_paths=ignored_paths,
              remediation_hint=f"branch deleted, base synced to {synced_to[:9]}")
        return 0
```

Note the moved-branch case is caught twice by design: Task 8's `regate_worktree` tip comparison aborts *before* `worktree remove` (a clean-but-ahead worktree passes the cleanliness check; only the tip comparison catches it), and this teardown re-check is the immediately-adjacent second lock before `branch -D`.

- [ ] **Step 4: Run the full suite** — expected: PASS, all tests.
- [ ] **Step 5: Commit** — `git commit -am "feat(sync-after-remote-merge): finish teardown with SHA-bound delete and idempotent re-entry"`

---

### Task 12: SKILL.md — new envelope-reading guidance

**Files:**
- Modify: `src/user/.claude/skills/sync-after-remote-merge/SKILL.md`

- [ ] **Step 1: Rewrite "The script" and "Reading the envelope"** to match the two-phase contract. Replace those sections with:

```markdown
## The script

Run from the worktree being cleaned up (plan phase — read-only):

    python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py [--branch <b>] [--base <b>]

It verifies the PR merged and runs the data-loss safety gates, then hands back
the exact remaining steps. It performs no mutation in this phase and never
merges. Every exit path — including bad arguments — emits one JSON envelope on
stdout.

### Reading the envelope

- `status: "handoff"` (plan phase) — checks passed. **Run each step in
  `steps_remaining` in order, verbatim**: for a Claude-native worktree that is
  the `ExitWorktree(discard_changes: true)` tool call and then one `cd … &&
  python3 … --finish …` command; otherwise just the finish command. Do not
  compose your own git commands. If `ignored_paths` lists anything that looks
  like configuration or secrets (e.g. `.env`), mention it to the user before
  the ExitWorktree/discard step.
- `status: "ok"` (finish phase) — done: base synced, branch deleted, worktree
  removed where applicable. Report the result from this envelope.
- `status: "not_merged"` — no merged PR for this branch. Do **not** merge on a
  cleanup request; tell the user there is nothing merged to clean up. (If the
  user's instruction was an explicit "merge it", see Composition.)
- `status: "failed"` — a gate or step aborted (the `phase` field says which
  phase). Read `failed_step` and `remediation_hint`, surface them, remediate
  the exact condition, and re-run that phase's command — finish mode is
  re-entrant. Do not force past a gate.
```

And in **Red flags**, replace the worktree bullet with:

```markdown
- Never git-remove a worktree yourself and never run teardown from inside it;
  relay the handed-back steps verbatim (the `cd` in the finish command is what
  evacuates the shell).
```

- [ ] **Step 2: Verify consistency** — `grep -n "handoff\|steps_remaining\|--finish" src/user/.claude/skills/sync-after-remote-merge/SKILL.md` and confirm no stale claims remain (e.g. the old "script synced the base" handoff wording).
- [ ] **Step 3: Commit** — `git commit -am "docs(sync-after-remote-merge): SKILL.md reflects the two-phase envelope contract"`

---

### Task 13: Wire the suite into the repo test gate

**Files:**
- Modify: `project-config.toml` (the `[gates] test` line)

- [ ] **Step 1: Extend discovery** — in `project-config.toml`, change the `test` command's find roots from

```
find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' ...
```

to

```
find src/user/.agents/skills src/user/.claude/skills src/user/.claude/hooks -name '*_test.sh' ...
```

(keep everything else on the line byte-identical).

- [ ] **Step 2: Verify discovery and execution**

```bash
find src/user/.agents/skills src/user/.claude/skills src/user/.claude/hooks -name '*_test.sh' | grep sync-after-remote-merge
bash src/user/.claude/skills/sync-after-remote-merge/sync_after_remote_merge_test.sh
```

Expected: the wrapper is listed, and the suite passes end-to-end via the wrapper.

- [ ] **Step 3: Commit** — `git commit -am "chore(gates): test gate discovers src/user/.claude/skills suites (Codex P2)"`

---

### Task 14: Full verification sweep

- [ ] **Step 1: Full suite** — the test command from the header. Expected: PASS, zero failures, zero skips beyond any pre-existing guarded skips.
- [ ] **Step 2: Lint the touched Python** — `uvx ruff check src/user/.claude/skills/sync-after-remote-merge/ && uvx ruff format --check src/user/.claude/skills/sync-after-remote-merge/` (skill Python is outside the repo ruff gate; hold it to the same bar anyway). Fix anything it reports.
- [ ] **Step 3: Repo gate sanity** — run the `[gates] test` command from `project-config.toml` verbatim; expected: every discovered suite passes, including this one.
- [ ] **Step 4: Commit any residue and push** — `git push` (the PR branch). Manual end-to-end per spec §5 happens naturally after this PR merges: this very worktree (`sync-after-remote-merge`, Claude-native) is the dogfood — run the skill on it and confirm the `handoff` → `ExitWorktree` → finish sequence.
- [ ] **Step 5: PR follow-through** — reply to the four Codex/adversarial findings on PR #255 (F1–F4) pointing at the rework commits; then resume the PR-review monitoring loop per the completion gate.
