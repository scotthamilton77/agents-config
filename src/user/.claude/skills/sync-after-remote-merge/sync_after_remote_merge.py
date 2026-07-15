#!/usr/bin/env python3
"""sync_after_remote_merge.py — reconcile local git state after a PR merged remotely.

Pure core over value types; git + `gh` confined to boundary functions (_run,
gh_pr_view). Invoked by the sync-after-remote-merge skill:
  python3 sync_after_remote_merge.py [--branch <b>] [--base <b>]
Emits a JSON envelope on stdout on every exit path. The script NEVER merges.

Exit: 0 for ok/handoff/not_merged; non-zero for failed (a partial-state abort).
"""
from __future__ import annotations

import argparse
import json
import shlex
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


class Phase(str, Enum):
    PLAN = "plan"
    FINISH = "finish"


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
    phase: Phase,
    *,
    steps_completed: list[str] | tuple[str, ...] = (),
    failed_step: dict | None = None,
    steps_remaining: list[str] | tuple[str, ...] = (),
    worktree_convention: Convention | None = None,
    main_root: str | None = None,
    base: str | None = None,
    branch: str | None = None,
    branch_sha: str | None = None,
    pr: int | None = None,
    merge_commit: str | None = None,
    synced_to: str | None = None,
    ignored_paths: list[str] | tuple[str, ...] = (),
    remediation_hint: str | None = None,
) -> dict:
    """Assemble the JSON envelope with a stable key set (null where N/A)."""
    return {
        "status": status.value,
        "phase": phase.value,
        "steps_completed": list(steps_completed),
        "failed_step": failed_step,
        "steps_remaining": list(steps_remaining),
        "worktree_convention": worktree_convention.value if worktree_convention else None,
        "main_root": main_root,
        "base": base,
        "branch": branch,
        "branch_sha": branch_sha,
        "pr": pr,
        "merge_commit": merge_commit,
        "synced_to": synced_to,
        "ignored_paths": list(ignored_paths),
        "remediation_hint": remediation_hint,
    }


def _emit(status: Status, phase: Phase, **fields) -> None:
    """Print one JSON envelope to stdout — the single output surface for main()."""
    print(json.dumps(build_envelope(status, phase, **fields)))


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


def detect_convention(worktree_root: Path, main_root: Path) -> Convention:
    """Which worktree convention (if any) owns teardown of this checkout.

    Claude-native (`.claude/worktrees/`) is checked before the bare-`worktrees`
    rule so a Claude path never falls through to OTHER_AGENT. A worktree under
    no known convention fails loud — the script must never git-remove a checkout
    it does not recognise.
    """
    if worktree_root == main_root:
        return Convention.NORMAL_REPO
    if worktree_root.is_relative_to(main_root / ".claude" / "worktrees"):
        return Convention.CLAUDE_NATIVE
    for wt_dir in (".worktrees", "worktrees"):
        if worktree_root.is_relative_to(main_root / wt_dir):
            return Convention.OTHER_AGENT
    raise UnrecognizedWorktree(
        f"worktree at {worktree_root} is under none of {main_root}/.claude/worktrees/, "
        f"{main_root}/.worktrees/, or {main_root}/worktrees/; tear it down manually"
    )


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


def unmerged_commits(rev_list_output: str) -> list[str]:
    """Parse `git rev-list <ref>..<branch>` output into commit SHAs (empty == none).

    A pure parser over rev-list stdout; the caller chooses the base ref (the
    merged PR head — see safety gate A).
    """
    return [ln.strip() for ln in rev_list_output.splitlines() if ln.strip()]


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


class _AbortStep(Exception):
    """Raised to abort with a named failed_step; carries envelope-ready detail."""

    def __init__(self, name: str, hint: str, *, cmd: str = "", exit_code: int = 1, stderr: str = ""):
        super().__init__(hint)
        self.failed_step = {"name": name, "cmd": cmd, "exit_code": exit_code, "stderr": stderr}
        self.hint = hint


def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _run_step(cmd: list[str], name: str, hint: str, *, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a git command whose failure is an expected, nameable abort.

    Non-zero exit raises `_AbortStep` tagged with `name`, so an operational
    failure surfaces as that named step in the envelope rather than falling into
    the generic 'unexpected' bucket. Reserve the plain `_run` (check=True) for
    calls whose failure genuinely is a programming error.
    """
    proc = _run(cmd, cwd=cwd, check=False)
    if proc.returncode != 0:
        raise _AbortStep(name, hint, cmd=shlex.join(cmd), exit_code=proc.returncode, stderr=proc.stderr)
    return proc


def gh_pr_view(branch: str) -> dict | None:
    """Return the PR payload for `branch`, or None when no PR is associated.

    Distinguishes 'no PR found' (→ None → not_merged) from a hard gh failure
    (auth/network → raise, so main reports `failed` rather than a false
    not_merged).
    """
    argv = ["gh", "pr", "view", branch, "--json",
            "number,state,mergedAt,mergeCommit,baseRefName,headRefOid"]
    proc = _run(argv, check=False)
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    err = (proc.stderr or "").lower()
    if "no pull requests found" in err or "no pull request found" in err:
        return None
    raise _AbortStep("verify_merged", f"gh pr view failed: {proc.stderr.strip()}",
                     cmd=shlex.join(argv), exit_code=proc.returncode, stderr=proc.stderr)


def _default_base(main_root: str) -> str:
    """Repo default branch via origin/HEAD, falling back to 'main'."""
    proc = _run(["git", "-C", main_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return "main"


def _require_safe_ref(ref: str, name: str) -> None:
    """Refuse a ref beginning with '-'. Such a value would be parsed by git as an
    option on the destructive teardown/sync commands (checkout, branch -D,
    rev-list) — fail closed rather than pass it through."""
    if ref.startswith("-"):
        raise _AbortStep("invalid_ref",
                         f"{name} {ref!r} begins with '-'; refusing (git option-injection guard)")


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
    if args.finish:
        return _main_finish(args)
    return _main_plan(args)


def _main_plan(args: argparse.Namespace) -> int:
    completed: list[str] = []
    main_root = base = branch = merge_commit = synced_to = None
    convention: Convention | None = None
    pr_number: int | None = None

    try:
        # --- preflight (runs in the worktree's cwd) ---
        worktree_root = Path(_run_step(["git", "rev-parse", "--show-toplevel"],
                                       "preflight", "not inside a git repository").stdout.strip()).resolve()
        common = Path(_run_step(["git", "rev-parse", "--git-common-dir"],
                                "preflight", "cannot resolve the git common dir").stdout.strip()).resolve()
        main_root = str(common.parent)
        head_branch = _run_step(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                "preflight", "cannot resolve current branch").stdout.strip()
        if head_branch == "HEAD" and not args.branch:
            raise _AbortStep("preflight",
                             "HEAD is detached (no current branch); pass --branch "
                             "explicitly or check out the feature branch first")
        branch = args.branch or head_branch
        _require_safe_ref(branch, "branch")
        convention = detect_convention(worktree_root, Path(main_root))
        # In a worktree, gate B (clean check) and teardown (worktree removal) act
        # on THIS checkout, whose branch is head_branch. An explicit --branch that
        # names a different ref would containment-check and delete that ref while
        # removing this worktree — incoherent, so fail closed. Normal repos
        # legitimately delete a merged branch other than HEAD, so the guard is
        # worktree-only.
        if convention in (Convention.OTHER_AGENT, Convention.CLAUDE_NATIVE) and branch != head_branch:
            raise _AbortStep("preflight",
                             f"--branch {branch!r} does not match the worktree's checked-out "
                             f"branch {head_branch!r}; refusing to act on a mismatched checkout")
        completed.append("preflight")

        # --- verify merged ---
        pr_state = classify_pr(gh_pr_view(branch))
        pr_number = pr_state.pr
        base = args.base or pr_state.base or _default_base(main_root)
        _require_safe_ref(base, "base")
        if not pr_state.merged:
            _emit(Status.NOT_MERGED, Phase.PLAN, steps_completed=completed, worktree_convention=convention,
                  main_root=main_root, base=base, branch=branch, pr=pr_number,
                  remediation_hint=pr_state.reason)
            return 0
        merge_commit = pr_state.merge_commit
        completed.append("verify_merged")

        # --- safety gate A: no local commits beyond the merged head ---
        # Containment is checked against the PR head GitHub actually merged
        # (head_oid), NOT the merge commit. A squash or rebase merge produces a
        # new commit that does not have the branch's commits as ancestors, so a
        # merge-commit check would list every branch commit and always
        # false-abort — and squash is this repo's default. `rev-list
        # <head>..<branch>` is empty for squash/rebase/merge alike when the
        # local branch holds nothing beyond the merged head, and lists only
        # genuine local-only commits when it does. A merged PR with no head SHA
        # can't be verified — abort rather than skip the gate and force-delete.
        if not pr_state.head_oid:
            raise _AbortStep("safety_gate_commits",
                             "merged PR reports no head SHA; cannot verify the branch is "
                             "fully merged before deleting it")
        rev_argv = ["git", "-C", main_root, "rev-list", f"{pr_state.head_oid}..{branch}"]
        rev = _run(rev_argv, check=False)
        if rev.returncode != 0:
            raise _AbortStep("safety_gate_commits",
                             f"cannot confirm {branch} is contained in the merged head "
                             f"({pr_state.head_oid[:9]} not resolvable locally)",
                             cmd=shlex.join(rev_argv),
                             exit_code=rev.returncode, stderr=rev.stderr)
        orphans = unmerged_commits(rev.stdout)
        if orphans:
            raise _AbortStep("safety_gate_commits",
                             f"{branch} has {len(orphans)} local commit(s) beyond the merged "
                             f"head (would be lost): {', '.join(s[:9] for s in orphans)}")
        # The immutable post-merge fact the finish phase re-verifies against: the
        # exact branch tip these read-only gates cleared. Bind it into the handed-
        # back command so finish refuses to delete a branch that moved since.
        branch_sha = _run_step(["git", "-C", main_root, "rev-parse", f"refs/heads/{branch}"],
                               "safety_gate_commits", "cannot resolve the branch tip").stdout.strip()
        completed.append("safety_gate_commits")

        # --- safety gate B: clean worktree ---
        porcelain = _run_step(["git", "-C", str(worktree_root), "status", "--porcelain", "--ignored"],
                              "safety_gate_worktree", "cannot read worktree status").stdout
        tracked, untracked, ignored_paths = classify_status_paths(porcelain)
        strays = blocking_paths(tracked, untracked, convention)
        if strays:
            raise _AbortStep("safety_gate_worktree",
                             f"worktree is dirty; refusing to discard: {', '.join(strays)}")
        completed.append("safety_gate_worktree")

        # --- handoff (plan mode is strictly read-only) ---
        # Every convention hands back the single finish command. Nothing above
        # mutated git state; the finish phase re-gates and performs every
        # mutation adjacent to the state it just checked, from the main root.
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

    except UnrecognizedWorktree as exc:
        # A deliberate fail-loud outcome — report it as a named step, not 'unexpected'.
        _emit(Status.FAILED, Phase.PLAN, steps_completed=completed,
              failed_step={"name": "detect_convention", "cmd": "", "exit_code": 1, "stderr": str(exc)},
              worktree_convention=None, main_root=main_root, base=base, branch=branch,
              pr=pr_number, merge_commit=merge_commit, synced_to=synced_to,
              remediation_hint=str(exc))
        return 1
    except _AbortStep as abort:
        # A failed plan run has nothing safe to hand back: the finish command is
        # emitted only once every read-only gate has passed, and plan mode never
        # mutated anything, so there is no partial teardown to resume.
        _emit(Status.FAILED, Phase.PLAN, steps_completed=completed, failed_step=abort.failed_step,
              steps_remaining=[], worktree_convention=convention, main_root=main_root,
              base=base, branch=branch, pr=pr_number, merge_commit=merge_commit,
              synced_to=synced_to, remediation_hint=abort.hint)
        return 1
    except Exception as exc:  # fail closed on any unexpected error
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        one_line = next((ln.strip() for ln in detail.splitlines() if ln.strip()), repr(exc))
        _emit(Status.FAILED, Phase.PLAN, steps_completed=completed,
              failed_step={"name": "unexpected", "cmd": "", "exit_code": 1, "stderr": one_line},
              worktree_convention=convention, main_root=main_root, base=base, branch=branch,
              pr=pr_number, merge_commit=merge_commit, synced_to=synced_to,
              remediation_hint=f"unexpected failure: {one_line}")
        return 1


def _main_finish(args: argparse.Namespace) -> int:
    completed: list[str] = []
    convention: Convention | None = None
    main_root = synced_to = None
    try:
        # --- finish preflight (identity checks only — §3.2.2 step 1) ---
        for name, val in (("--worktree", args.worktree), ("--branch", args.branch),
                          ("--branch-sha", args.branch_sha), ("--base", args.base)):
            if not val:
                raise _AbortStep("preflight", f"--finish requires {name}")
        _require_safe_ref(args.branch, "branch")
        _require_safe_ref(args.base, "base")
        worktree = Path(args.worktree)
        if not worktree.is_absolute():
            raise _AbortStep("preflight", f"--worktree {args.worktree!r} must be absolute")
        worktree = worktree.resolve()
        toplevel = Path(_run_step(["git", "rev-parse", "--show-toplevel"],
                                  "preflight", "not inside a git repository").stdout.strip()).resolve()
        common = Path(_run_step(["git", "rev-parse", "--git-common-dir"],
                                "preflight", "cannot resolve the git common dir").stdout.strip()).resolve()
        main_root = str(common.parent)
        # Convention + the cwd-inside-worktree guard are checked before the
        # cwd-is-the-main-checkout equality: running from inside the target
        # worktree trips BOTH (its toplevel is the worktree, not the main root),
        # and "you are standing in the thing I'm about to remove" is the more
        # specific, more actionable diagnosis, so it wins.
        convention = detect_convention(worktree, Path(main_root))
        if convention is not Convention.NORMAL_REPO and Path.cwd().resolve().is_relative_to(worktree):
            raise _AbortStep("preflight",
                             f"cwd is inside the worktree {worktree} this command would "
                             f"remove; cd to {main_root} first")
        if toplevel != common.parent:
            raise _AbortStep("preflight",
                             f"finish mode must run from the main checkout {main_root}, "
                             f"not {toplevel} (did the handed-back `cd` run?)")
        completed.append("preflight")

        # --- re-gate the worktree (§3.2.2 step 2) ---
        # Every gate over mutable state re-runs here, adjacent to the mutation it
        # authorizes. branch_oid / worktree_present / terminal_noop / ignored_paths
        # are computed at this scope so the later teardown steps can consume them.
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

        # --- gate the main root (§3.2.2 step 3) ---
        porcelain = _run_step(["git", "-C", main_root, "status", "--porcelain"],
                              "gate_main_root", "cannot read main checkout status").stdout
        tracked, _untracked, _ignored = classify_status_paths(porcelain)
        if tracked:
            raise _AbortStep("gate_main_root",
                             f"main checkout {main_root} has tracked modifications; a branch "
                             f"switch would carry them: {', '.join(tracked)}")
        completed.append("gate_main_root")

        # --- sync the base (§3.2.2 step 4, F4) ---
        # Verify the base resolves to a LOCAL branch before switching — this
        # deliberately defeats `git checkout`'s remote-DWIM and path-ambiguity
        # behavior (e.g. `--base .` must never be treated as a path checkout).
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

        # --- teardown (§3.2.2 step 5) ---
        # Idempotent terminal state: a prior finish that already removed the
        # worktree and deleted the branch re-enters here as a clean no-op.
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

    except UnrecognizedWorktree as exc:
        # A deliberate fail-loud outcome — report it as a named step, not 'unexpected'.
        _emit(Status.FAILED, Phase.FINISH, steps_completed=completed,
              failed_step={"name": "detect_convention", "cmd": "", "exit_code": 1, "stderr": str(exc)},
              worktree_convention=None, main_root=main_root, base=args.base, branch=args.branch,
              branch_sha=args.branch_sha, pr=args.pr, merge_commit=args.merge_commit,
              synced_to=synced_to, steps_remaining=[], remediation_hint=str(exc))
        return 1
    except _AbortStep as abort:
        _emit(Status.FAILED, Phase.FINISH, steps_completed=completed, failed_step=abort.failed_step,
              steps_remaining=[], worktree_convention=convention, main_root=main_root,
              base=args.base, branch=args.branch, branch_sha=args.branch_sha, pr=args.pr,
              merge_commit=args.merge_commit, synced_to=synced_to, remediation_hint=abort.hint)
        return 1
    except Exception as exc:  # fail closed on any unexpected error
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        one_line = next((ln.strip() for ln in detail.splitlines() if ln.strip()), repr(exc))
        _emit(Status.FAILED, Phase.FINISH, steps_completed=completed,
              failed_step={"name": "unexpected", "cmd": "", "exit_code": 1, "stderr": one_line},
              steps_remaining=[], worktree_convention=convention, main_root=main_root,
              base=args.base, branch=args.branch, branch_sha=args.branch_sha, pr=args.pr,
              merge_commit=args.merge_commit, synced_to=synced_to,
              remediation_hint=f"unexpected failure: {one_line}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
