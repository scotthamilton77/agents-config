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
import os
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


def dirty_paths(porcelain: str) -> list[str]:
    """Parse `git status --porcelain` into changed/untracked paths (XY-prefix stripped)."""
    return [ln[3:] for ln in porcelain.splitlines() if ln.strip()]


def unmerged_commits(rev_list_output: str) -> list[str]:
    """Commit SHAs on the branch not reachable from the merge commit (empty == fully merged).

    Fed by `git -C <main> rev-list <merge_commit>..<branch>`.
    """
    return [ln.strip() for ln in rev_list_output.splitlines() if ln.strip()]


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


def _default_base(main_root: str) -> str:
    """Repo default branch via origin/HEAD, falling back to 'main'."""
    proc = _run(["git", "-C", main_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return "main"


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
        # --- preflight (runs in the worktree's cwd) ---
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

        # Leave the worktree before any destructive teardown so the script's own
        # cwd is never inside a worktree it is about to remove.
        os.chdir(main_root)

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


if __name__ == "__main__":
    sys.exit(main())
