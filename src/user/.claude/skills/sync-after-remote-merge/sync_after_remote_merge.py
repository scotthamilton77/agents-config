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
