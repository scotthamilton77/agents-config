# Sync After Remote Merge

**Bead:** `agents-config-vaac.7` (M3 — Worker fleet through PR autonomy)
**Status:** draft

## 1. Problem

After a PR is merged remotely (on GitHub, out of band from the local session),
the local workspace is left in a half-finished state: the feature branch still
exists, the worktree is still on disk, and the base branch has not been synced
to include the merge. Scott's recurring instruction — *"clean up and sync
main"* — currently triggers a minute or two of ad-hoc agent reasoning to work
through the same deterministic mechanics every time: confirm the PR actually
merged, fast-forward the base branch, delete the local feature branch, tear
down the worktree. Because it is reasoned fresh each time, steps get skipped
("crumbs left on the table") and the destructive steps (branch deletion,
worktree removal) are done without consistent safety checks.

The mechanics are fully deterministic and belong in code, per this repo's *Code
over Prose* principle. Two facets are genuinely not scriptable and must stay
agent-side: confirming merge state before anything destructive runs, and the
harness-owned `ExitWorktree` call for Claude-native worktrees.

There is also a lifecycle gap. The completion-gate delivery chain runs
`using-git-worktrees → finishing-a-development-branch → PR-review monitoring →
merge` and then stops. Nothing owns the last mile *after* the merge lands. This
work closes that gap.

`finishing-a-development-branch` is not the owner: its four options are a
*pre-merge* decision menu, and a PR does not exist until its Option 2 creates
one. By the time a PR is created, reviewed, and merged remotely, that skill has
long exited. Post-merge reconciliation is a distinct lifecycle phase and gets
its own skill.

## 2. Decisions

1. **New standalone skill `sync-after-remote-merge`** — not folded into
   `finishing-a-development-branch` (wrong lifecycle phase) — with the
   deterministic logic in a Python script beside its `SKILL.md`, deployed to
   `~/.claude/skills/sync-after-remote-merge/`.
2. **The script never merges.** Merging is `merge-guard`'s exclusive, governed
   responsibility. The skill delivers a one-turn *"merge it"* experience by
   *composing* with `merge-guard`, not by reimplementing merge (no `gh pr
   merge`, no `--admin`, no `--explicit` in this script). This preserves
   `merge-guard`'s separation of authorization from eligibility and its tightly
   gated `--admin` ladder.
3. **JSON envelope output**, matching the house convention for agent-facing
   scripts (`gate_triage.py`, `judge_merge.py`, `whats-next/collect.py`).
4. **Fail loud, lose nothing.** Two data-loss safety gates (unmerged local
   commits; dirty worktree) abort before any destructive step. Base sync is
   fast-forward-only; divergence aborts rather than guessing a rebase/merge.
5. **Teardown splits at the harness boundary.** The script performs git-level
   teardown only where it is safe and unblocked; Claude-native worktree removal
   is handed back to the agent as an `ExitWorktree` call.
6. **Wired into the completion-gate rule** as the terminal `→ post-merge
   cleanup` link in the delivery chain.

## 3. Design

### 3.1 Components

```
src/user/.claude/skills/sync-after-remote-merge/
├── SKILL.md                       # agent-facing orchestration + composition
├── sync_after_remote_merge.py     # deterministic reconciliation, emits JSON envelope
└── sync_after_remote_merge_test.py
```

Placement is `src/user/.claude/skills/` (Claude-only): the skill depends on
Claude-specific capabilities — the `ExitWorktree` harness tool and the Skill
tool to invoke `merge-guard`. It is not portable to other tools, so it does not
belong in the shared `src/user/.agents/` tree.

### 3.2 Script contract

Invocation (from the agent, run against the worktree it is cleaning up):

```
python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py \
  [--branch <name>] [--base <name>] [--pr <number>]
```

The JSON envelope (§3.2) is the sole output on every exit path; there is no
human-rendered mode and no `--json` toggle. The agent renders it to prose when
reporting to the user.

All arguments are optional and auto-detected when omitted:

- `--branch` — feature branch; default: current branch.
- `--base` — base branch; default: the merged PR's `baseRefName`, else the
  repo default branch.
- `--pr` — PR number; default: resolved from the branch via `gh`.

The script is **read-mostly until its safety gates pass**; it performs no
destructive action (branch delete, worktree remove) until merge is confirmed
and both safety gates are clear.

#### Step sequence

1. **Preflight.** Resolve: main repo root (`git rev-parse --git-common-dir`
   → parent); current branch; whether this is a worktree and, if so, its
   **convention** — Claude-native (`.claude/worktrees/`), other-agent
   (`<repo-root>/.worktrees/` or bare `worktrees/`), or normal repo (no
   worktree). All later git operations target the main root via `git -C
   <main_root>`, so removing the current worktree never pulls the ground out
   from under the running command.

2. **Verify merged.** `gh pr view <branch> --json
   number,state,mergedAt,mergeCommit,baseRefName,headRefOid`. If no PR is found,
   or `state != MERGED` (still open, closed-unmerged, or ambiguous/multiple),
   emit `status: "not_merged"` and stop — a clean, non-error outcome the skill
   interprets (§3.3). Never infer merge from the user's say-so alone.

3. **Safety gate A — no local commits beyond the merged head.** Containment is
   checked against the PR head GitHub actually merged (`headRefOid`), **not** the
   `mergeCommit`: a squash or rebase merge produces a new commit that does not
   have the branch's commits as ancestors, so a `mergeCommit`-reachability check
   would list every branch commit and always false-abort — and squash is this
   repo's default. `git rev-list <headRefOid>..<branch>` is empty for
   squash/rebase/merge alike when the local branch holds nothing beyond the
   merged head, and lists only genuine local-only commits when it does; a
   non-empty result aborts with `status: "failed"` (the report lists the orphan
   SHAs) because deleting the branch would lose that work. A merged PR with no
   `headRefOid`, or a head SHA not resolvable locally, also aborts — the gate is
   never skipped-yet-marked-complete on a destructive path.

4. **Safety gate B — clean worktree.** No uncommitted tracked changes and no
   untracked files in the worktree. If dirty, abort with `status: "failed"` and
   list the stray paths — a later `discard_changes` teardown would destroy
   them.

5. **Sync base.** From the main root: check out `<base>`, then `git pull
   --ff-only`. A non-fast-forward result (local base diverged from origin)
   aborts with `status: "failed"`; the script never rebases or merges to force
   it. Record the resulting base SHA as `synced_to`.

6. **Teardown** (convention-dependent):
   - **normal repo** — no worktree; `git -C <main_root> branch -D <branch>`.
     `-D` (not `-d`) because a squash-merge reads as unmerged to `-d`.
   - **other-agent worktree** — `git -C <main_root> worktree remove <path>`
     → `git -C <main_root> branch -D <branch>` → `git -C <main_root> worktree
     prune`. Fully scripted.
   - **Claude-native worktree** — the harness owns removal, and an existing
     worktree blocks `branch -D`. The script performs no teardown here; it emits
     `status: "handoff"` with `steps_remaining` naming the exact agent/harness
     calls: `ExitWorktree(discard_changes: true)` then `git -C <main_root>
     branch -D <branch>`.

7. **Emit envelope** (always, on every exit path).

#### JSON envelope

```json
{
  "status": "ok | handoff | not_merged | failed",
  "steps_completed": ["preflight", "verify_merged", "safety_gate_commits",
                      "safety_gate_worktree", "sync_base", "teardown"],
  "failed_step": {
    "name": "sync_base",
    "cmd": "git -C /main pull --ff-only",
    "exit_code": 1,
    "stderr": "..."
  },
  "steps_remaining": [
    "ExitWorktree(discard_changes: true)",
    "git -C /main branch -D feature/x"
  ],
  "worktree_convention": "claude-native | other-agent | normal-repo",
  "main_root": "/abs/path/to/main",
  "base": "main",
  "branch": "feature/x",
  "pr": 1234,
  "merge_commit": "<sha>",
  "synced_to": "<sha>",
  "remediation_hint": "one-line human-readable summary of the failure and next move"
}
```

- `failed_step` is present only when `status == "failed"`.
- `steps_remaining` is populated for `handoff` (the teardown calls) and may be
  populated for `failed` (what was not attempted).
- Exit code: `0` for `ok` / `handoff` / `not_merged`; non-zero for `failed`.
- `status: "handoff"` is the normal Claude-native success outcome — not an
  error. The script did its half; the agent finishes the two harness steps.

### 3.3 Skill orchestration (`SKILL.md`)

The skill decides *whether the script runs at all* and handles the two entry
phrasings:

- **"clean up and sync main" / "tidy up after the merge"** (PR already merged)
  → run the script directly. On `handoff`, perform the named `ExitWorktree`
  call, then the `branch -D`. On `not_merged`, report that there is nothing
  merged to clean up (do **not** merge on this phrasing).
- **"merge it"** on an unmerged PR → this is an explicit merge instruction.
  Invoke `merge-guard` first (the single governed merge door: policy
  resolution, eligibility floor, and — only when genuinely warranted — its own
  gated `--admin`). Only on `merge-guard` confirming the merge, run the cleanup
  script. If `merge-guard` declines or hands off to a human, cleanup does not
  run.

The skill's description carries the trigger surface: *"clean up and sync main",
"the PR merged, tidy up", "sync main after a remote merge", "tear down the
worktree after merge"* — so the phrasing reliably selects this skill.

The skill references `merge-guard` and `ExitWorktree` by name/concept, never by
repo-internal file path (installed assets must survive flattening into other
projects).

### 3.4 Completion-gate wiring

Add `sync-after-remote-merge` to the completion-gate rule's HARD STOP delivery
chain as the terminal link after `merge`, closing the last-mile gap:
`… → merge → sync-after-remote-merge`. Edit the source rule under
`src/user/.agents/rules/`.

## 4. Non-goals

- **Merging.** No `gh pr merge`, no `--admin`, no `--explicit`. Merge is
  `merge-guard`'s job; the skill composes with it.
- **Beads / Dolt sync.** The session-close flow owns `bd dolt push` / `git
  push`; this script does not touch the work tracker.
- **PR creation** and the four-option finish menu — that is
  `finishing-a-development-branch`.
- **Non-fast-forward reconciliation.** Divergence aborts loud; the script never
  rebases or merges to force a sync.
- **Multi-PR / stacked-branch resolution.** Ambiguous PR state (multiple
  candidate PRs for a branch) is a `not_merged`/abort, handed to the agent.

## 5. Verification

- **Unit (`sync_after_remote_merge_test.py`)** over the pure logic with `git`
  and `gh` faked: envelope construction per `status`; worktree-convention
  detection for all three cases; PR-state classification (merged / open /
  closed-unmerged / none / ambiguous → correct status); safety gate A (unmerged
  local commits detected); safety gate B (dirty worktree detected); ff-only
  sync abort on divergence; correct `steps_remaining` for the Claude-native
  handoff.
- **Manual end-to-end** against a real merged PR in a real worktree (both a
  Claude-native worktree exercising the `handoff` path and, if feasible, an
  other-agent worktree exercising full scripted teardown) before the work is
  declared done — per this repo's workflow-verification standard.
- Deployed-test guard: the `_test.py` ships to `~/.claude/skills/`, so any
  repo-internal path in the test must be `skipTest`-guarded (skill Python is not
  in the ruff gate).

## 6. Continuations

- none — this spec plus its implementation (script, skill, tests,
  completion-gate wiring) is the deliverable of `agents-config-vaac.7`.
