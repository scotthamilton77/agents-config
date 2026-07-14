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
over Prose* principle. But determinism of the **decision** and safe execution
of the **mutations** are separable concerns, and the execution side is bounded
by process-ownership constraints that no amount of scripting removes:

- A child process cannot move its caller's working directory. `os.chdir` in
  the script moves only the script. `git worktree remove` succeeds even while
  another process's cwd is inside the worktree (verified empirically: the
  removal exits 0; the squatting process's next git command dies with
  `fatal: Unable to read current working directory`). A script must therefore
  **never remove the directory its caller occupies** — the caller has to
  evacuate first, and only the caller can do that.
- `ExitWorktree` is harness-owned. Claude-native worktree removal (and its
  `discard_changes` decision) cannot be scripted at all.
- A safety gate is only as good as its distance from the trigger it guards.
  A cleanliness check in one process that authorizes a destructive action in
  another process, later, has a time-of-check/time-of-use window. The check
  must run in the **same process as the mutation, immediately before it**.

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
2. **Two-phase execution, split at the process-ownership boundary.** The same
   script runs twice with distinct modes:
   - **Plan mode** (default) runs from the checkout being cleaned up. It is
     strictly read-only: verify the merge, run the safety gates, detect the
     worktree convention, and hand back the exact next steps. It never mutates
     git state.
   - **Finish mode** (`--finish`) runs from the main root — the caller has
     already evacuated the worktree by `cd`-ing there as part of the handed-back
     command. Every gate over **mutable** state (branch tip, worktree
     cleanliness, main-root cleanliness) re-runs in its own process,
     immediately before the mutation it authorizes; gates over **immutable**
     post-merge facts (merge state, containment) are carried across the phase
     boundary by the `branch_sha` binding rather than re-run.
   The agent's execution surface is deliberately minimal: relay one handed-back
   command verbatim (plus the harness-owned `ExitWorktree` call for
   Claude-native worktrees). The agent never composes a git command.
3. **The script never merges.** Merging is `merge-guard`'s exclusive, governed
   responsibility. The skill delivers a one-turn *"merge it"* experience by
   *composing* with `merge-guard`, not by reimplementing merge (no `gh pr
   merge`, no `--admin`, no `--explicit` in this script). This preserves
   `merge-guard`'s separation of authorization from eligibility and its tightly
   gated `--admin` ladder.
4. **JSON envelope output**, matching the house convention for agent-facing
   scripts (`gate_triage.py`, `judge_merge.py`, `whats-next/collect.py`).
5. **Fail loud, lose nothing.** Data-loss safety gates abort before any
   destructive step, and every gate that authorizes a mutation runs in the
   process that performs that mutation. Base sync is fast-forward-only;
   divergence aborts rather than guessing a rebase/merge. Every checkout the
   script mutates — including the main root — is gated, not just the worktree
   being torn down.
6. **Explicit untracked/ignored policy at the discard boundary.** Tracked
   modifications and untracked files block teardown (they are potential work).
   Ignored files never block, but are enumerated in the envelope before any
   discard so nothing vanishes unreported — `git status --porcelain` alone does
   not list them, and a worktree discard destroys them too.
7. **Wired into the completion-gate rule** as the terminal `→ post-merge
   cleanup` link in the delivery chain.

## 3. Design

### 3.1 Components

```
src/user/.claude/skills/sync-after-remote-merge/
├── SKILL.md                       # agent-facing orchestration + composition
├── sync_after_remote_merge.py     # plan + finish modes, emits JSON envelope
└── sync_after_remote_merge_test.py
```

Placement is `src/user/.claude/skills/` (Claude-only): the skill depends on
Claude-specific capabilities — the `ExitWorktree` harness tool and the Skill
tool to invoke `merge-guard`. It is not portable to other tools, so it does not
belong in the shared `src/user/.agents/` tree.

### 3.2 Script contract

The JSON envelope (§3.2.3) is the sole output on every exit path; there is no
human-rendered mode and no `--json` toggle. The agent renders it to prose when
reporting to the user.

#### 3.2.1 Plan mode (default)

Invoked by the agent from the checkout being cleaned up:

```
python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py \
  [--branch <name>] [--base <name>]
```

Arguments are optional and auto-detected: `--branch` defaults to the current
branch; `--base` to the merged PR's `baseRefName`, else the repo default
branch. The PR is always resolved from the branch via `gh` (no `--pr`
override); a branch maps to at most one open/merged PR in this workflow.

Plan mode performs **no mutation of any kind**. Step sequence:

1. **Preflight.** Resolve: the worktree root (`git rev-parse --show-toplevel`,
   **realpath-resolved** — the git-common-dir is already resolved, and an
   unresolved toplevel under a symlinked repo path spells the same directory
   differently, breaking every convention comparison); the main repo root
   (`git rev-parse --git-common-dir` → parent); the current branch; the
   worktree **convention** — Claude-native (`.claude/worktrees/`), other-agent
   (`<repo-root>/.worktrees/` or bare `worktrees/`), or normal repo (toplevel
   equals main root). An unrecognized worktree fails loud. A detached HEAD
   with no explicit `--branch` aborts with a specific message (`--abbrev-ref
   HEAD` yields the literal `HEAD`, which must never flow into later steps).
   In a worktree, an explicit `--branch` that differs from the checked-out
   branch aborts (mismatched checkout); a normal repo legitimately targets a
   merged branch other than HEAD.

2. **Verify merged.** `gh pr view <branch> --json
   number,state,mergedAt,mergeCommit,baseRefName,headRefOid`. If no PR is
   found, or `state != MERGED` (still open or closed-unmerged), emit
   `status: "not_merged"` and stop — a clean, non-error outcome the skill
   interprets (§3.3). `gh pr view` resolves a single PR per branch; detecting
   or arbitrating multiple candidate PRs is out of scope (§4). Never infer
   merge from the user's say-so alone.

3. **Safety gate A — no local commits beyond the merged head.** Containment is
   checked against the PR head GitHub actually merged (`headRefOid`), **not**
   the `mergeCommit`: a squash or rebase merge produces a new commit that does
   not have the branch's commits as ancestors, so a `mergeCommit`-reachability
   check would list every branch commit and always false-abort — and squash is
   this repo's default. `git rev-list <headRefOid>..<branch>` is empty for
   squash/rebase/merge alike when the local branch holds nothing beyond the
   merged head, and lists only genuine local-only commits when it does; a
   non-empty result aborts with `status: "failed"` (the report lists the orphan
   SHAs). A merged PR with no `headRefOid`, or a head SHA not resolvable
   locally, also aborts — the gate is never skipped-yet-marked-complete on a
   destructive path. The gate also records the branch tip
   (`git rev-parse refs/heads/<branch>`) as `branch_sha`, the binding token
   finish mode revalidates.

4. **Safety gate B — clean worktree.** Tracked modifications or untracked
   files in the worktree abort with `status: "failed"`, listing the stray
   paths — a later discard would destroy them. Ignored files
   (`git status --porcelain --ignored`) do **not** block but are reported in
   the envelope's `ignored_paths`, because a worktree discard destroys them too
   and the agent should get to eyeball the list (an `.env` is ignored *and*
   irreplaceable). This gate runs last so the snapshot is as fresh as possible
   at handback.

5. **Emit `status: "handoff"`** — always, for every convention; plan mode has
   no `ok` outcome. `steps_remaining` names the exact calls, in order:
   - Claude-native: `ExitWorktree(discard_changes: true)`, then the finish
     command.
   - Other-agent and normal repo: the finish command only.

   The finish command is fully reconstructed and shell-quoted by plan mode:

   ```
   cd <main_root> && python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py \
     --finish --worktree <worktree_root> --branch <branch> \
     --branch-sha <sha> --base <base> --pr <number> --merge-commit <sha>
   ```

   The leading `cd <main_root>` is load-bearing: it is what evacuates the
   calling process from the worktree before anything removes it.

#### 3.2.2 Finish mode (`--finish`)

Invoked via the handed-back command, from the main root. All arguments are
required (`--pr` and `--merge-commit` are carried for reporting only, so the
terminal envelope keeps the merge metadata); refs pass the safe-ref guard, and
`--worktree` must be an absolute, existing-repo path. Finish mode trusts plan
mode only for facts that are **immutable once the PR is merged**: the merge
verdict and gate A's containment conclusion, both pinned to `--branch-sha`.
It therefore does **not** re-run `verify_merged` or safety gate A (it never
calls `gh`, and the finish command carries no `headRefOid`) — gate A's
conclusion holds exactly as long as the branch tip still equals
`--branch-sha`, which is revalidated immediately before deletion. Every gate
over **mutable** state — worktree cleanliness, main-root cleanliness, branch
tip — re-runs here, adjacent to the mutation it authorizes. Step sequence:

1. **Finish preflight.** The resolved cwd toplevel must equal the repo's own
   main checkout (its git-common-dir parent must be itself) and must equal the
   main root that `--worktree` belongs to. Re-derive the convention from
   `--worktree` vs the main root (normal repo when they are equal). For the
   two worktree conventions the cwd must additionally not be inside
   `--worktree` — finish mode refuses to run from inside the thing it is about
   to remove. Abort on any mismatch.

2. **Re-gate the worktree** (convention-dependent):
   - **other-agent** — the worktree must be clean, by a fresh gate-B check
     (tracked/untracked abort; ignored listed), and its checked-out branch
     must equal `--branch` — a *different* worktree recreated at the same path
     between phases would be on different work, and path identity alone must
     never authorize a removal. Exception: a worktree that is already **gone**
     while `refs/heads/<branch>` still equals `--branch-sha` is a resumable
     partial teardown (a prior finish run removed the worktree, then failed
     before deleting the branch) — skip the removal and proceed, rather than
     stranding the branch behind a gate no re-run can satisfy.
   - **Claude-native** — the worktree must already be **gone** (`ExitWorktree`
     owns its removal and runs before this command). If it still exists, abort
     with the hint to run the `ExitWorktree` step first.
   - **normal repo** — nothing to check.

3. **Gate the main root.** The main checkout must have no tracked
   modifications (staged or unstaged); otherwise abort. Rationale: `git
   switch` carries non-conflicting local changes across branches, silently
   relocating another live checkout's work into the wrong branch context.
   Untracked files are permitted — a branch switch neither consumes nor
   destroys them, and a collision with incoming files makes git itself abort,
   loudly.

4. **Sync base.** Validate `<base>` resolves as a real local branch
   (`git rev-parse --verify refs/heads/<base>`), then `git switch <base>` —
   `switch` accepts only branches, closing the checkout path-vs-branch
   ambiguity (an accidental `--base .` under `checkout` silently becomes a
   path checkout that can discard dirty tracked changes) — then
   `git pull --ff-only`. The precheck deliberately defeats git's
   create-from-remote DWIM, so a base that exists only as a remote-tracking
   ref aborts; the remediation hint says to create the local base first. A
   non-fast-forward result aborts; the script never rebases or merges to
   force it. Record the resulting base SHA as `synced_to`.

5. **Teardown.**
   - other-agent: `git worktree remove -- <worktree>` (the `--` guards the
     path operand, which the safe-ref guard does not cover) — deliberately
     without `--force`: git's own dirty-worktree refusal is the guard truly
     adjacent to this removal; the step-2 check ran earlier.
   - all conventions: immediately before deletion, re-verify
     `git rev-parse refs/heads/<branch>` still equals `--branch-sha` (abort if
     the branch moved since plan mode), then `git branch -D <branch>`. `-D`
     (not `-d`) because a squash-merge reads as unmerged to `-d`.
   - other-agent: `git worktree prune`.

6. **Emit `status: "ok"`.**

Finish mode is re-entrant: any abort names the failed condition, and the
remediation is to fix that condition and re-run the same command.

**Accepted residual risk (Claude-native only):** between plan mode's gate B and
the agent's `ExitWorktree(discard_changes: true)` there is an irreducible
one-turn window in which a new file could appear and be discarded unverified —
the harness owns the removal, so no script check can sit adjacent to it. Gate B
running last in plan mode minimizes the window, and `ignored_paths` ensures the
already-known-invisible files are surfaced rather than silently destroyed. The
window is documented, not load-bearing: everything finish mode later deletes is
re-gated at trigger time.

#### 3.2.3 JSON envelope

```json
{
  "status": "handoff | ok | not_merged | failed",
  "phase": "plan | finish",
  "steps_completed": ["preflight", "verify_merged", "safety_gate_commits",
                      "safety_gate_worktree", "gate_main_root", "sync_base",
                      "teardown"],
  "failed_step": {
    "name": "sync_base",
    "cmd": "git -C /main pull --ff-only",
    "exit_code": 1,
    "stderr": "..."
  },
  "steps_remaining": [
    "ExitWorktree(discard_changes: true)",
    "cd /main && python3 ~/.claude/skills/sync-after-remote-merge/sync_after_remote_merge.py --finish --worktree /main/.claude/worktrees/x --branch feature/x --branch-sha <sha> --base main --pr 1234 --merge-commit <sha>"
  ],
  "worktree_convention": "claude-native | other-agent | normal-repo",
  "main_root": "/abs/path/to/main",
  "base": "main",
  "branch": "feature/x",
  "branch_sha": "<sha>",
  "pr": 1234,
  "merge_commit": "<sha>",
  "synced_to": "<sha>",
  "ignored_paths": [".venv/", ".env"],
  "remediation_hint": "one-line human-readable summary of the outcome and next move"
}
```

- `status: "handoff"` is plan mode's only success outcome; `status: "ok"` is
  finish mode's. `not_merged` and `failed` can come from either phase (`phase`
  says which).
- `steps_completed` names are per-phase (the example shows the union): plan
  populates from `preflight`, `verify_merged`, `safety_gate_commits`,
  `safety_gate_worktree`; finish from `preflight`, `regate_worktree`,
  `gate_main_root`, `sync_base`, `teardown`. `preflight` means each phase's
  own preflight; `safety_gate_commits` never appears in a finish envelope.
- `failed_step` is present only when `status == "failed"`; `steps_remaining`
  is populated for `handoff` and may be populated for `failed` (what was not
  attempted).
- Exit code: `0` for `handoff` / `ok` / `not_merged`; non-zero for `failed`.

### 3.3 Skill orchestration (`SKILL.md`)

The skill decides *whether the script runs at all* and handles the two entry
phrasings:

- **"clean up and sync main" / "tidy up after the merge"** (PR already merged)
  → run the script (plan mode). On `handoff`, run each step in
  `steps_remaining` **in order, verbatim** — for Claude-native that is the
  `ExitWorktree` tool call then the finish command; otherwise just the finish
  command. The finish command's own envelope (`ok` or `failed`) is the final
  word. On `not_merged`, report that there is nothing merged to clean up (do
  **not** merge on this phrasing).
- **"merge it"** on an unmerged PR → this is an explicit merge instruction.
  Invoke `merge-guard` first (the single governed merge door: policy
  resolution, eligibility floor, and — only when genuinely warranted — its own
  gated `--admin`). Only on `merge-guard` confirming the merge, run the cleanup
  script. If `merge-guard` declines or hands off to a human, cleanup does not
  run.

On a `failed` envelope from either phase, surface `failed_step` and
`remediation_hint`, remediate the exact condition, and re-run that phase's
command. Never force past a gate. If `ignored_paths` contains anything that
looks like configuration or secrets (e.g. `.env`), mention it to the user
before running the discard step.

The skill's description carries the trigger surface: *"clean up and sync main",
"the PR merged, tidy up", "sync main after a remote merge", "tear down the
worktree after merge"* — so the phrasing reliably selects this skill.

The skill references `merge-guard` and `ExitWorktree` by name/concept, never by
repo-internal file path (installed assets must survive flattening into other
projects).

### 3.4 Completion-gate wiring

Add `sync-after-remote-merge` to the completion-gate rule's HARD STOP delivery
chain as the terminal link after `merge`, closing the last-mile gap:
`… → merge → sync-after-remote-merge`. It runs only when a merge actually
landed — on the `explicit`/`never` policy paths where no merge happens, the
chain ends at the merge step (§3.3 gates cleanup on `merge-guard` confirming).
Edit the source rule under `src/user/.agents/rules/`.

## 4. Non-goals

- **Merging.** No `gh pr merge`, no `--admin`, no `--explicit`. Merge is
  `merge-guard`'s job; the skill composes with it.
- **Beads / Dolt sync.** The session-close flow owns `bd dolt push` / `git
  push`; this script does not touch the work tracker.
- **PR creation** and the four-option finish menu — that is
  `finishing-a-development-branch`.
- **Non-fast-forward reconciliation.** Divergence aborts loud; the script never
  rebases or merges to force a sync.
- **Multi-PR / stacked-branch resolution.** `gh pr view` resolves one PR per
  branch; the script does not detect or arbitrate multiple candidate PRs for
  the same branch.
- **Shared-rule portability.** The completion-gate rule lives in the shared
  tree and already references Claude-only capabilities; whether those
  references (including this skill's) should become tool-conditional is a
  rule-wide decision tracked separately (§6), not part of this skill.

## 5. Verification

- **Unit (`sync_after_remote_merge_test.py`)** over the pure logic with `git`
  and `gh` faked: envelope construction per `status`/`phase`;
  worktree-convention detection for all three cases; PR-state classification
  (merged / open / closed-unmerged / none / ambiguous → correct status);
  safety gate A (unmerged local commits detected; missing/unresolvable
  `headRefOid` aborts); safety gate B (tracked-dirty and untracked abort;
  ignored files reported in `ignored_paths` without blocking); plan mode emits
  `handoff` for **every** convention with the correct ordered
  `steps_remaining` and a correctly quoted finish command; detached-HEAD
  abort; finish-mode gates — wrong-repo / inside-the-worktree cwd abort,
  branch moved from `--branch-sha` abort, Claude-native worktree-still-present
  abort, **dirty other-agent worktree abort** (the F2 TOCTOU the fresh re-gate
  exists to catch), other-agent worktree on the wrong branch abort, resumable
  partial teardown (worktree gone, branch still at `--branch-sha` → proceeds
  to branch delete), dirty main root abort; base not a local branch aborts;
  ff-only sync abort on divergence.
- **Symlinked-root regression test.** pytest's `tmp_path` is already
  realpath'd, so path-comparison bugs never fire in-suite; at least one test
  must construct a genuinely symlinked repo root and assert both plan-mode
  convention detection **and** finish-mode's path-equality preflight (cwd
  toplevel vs main root vs `--worktree`) classify correctly.
- **Integration: dirty main root.** A real two-checkout fixture where the main
  checkout has tracked modifications; finish mode must abort without touching
  it.
- **Manual end-to-end** against a real merged PR in a real worktree (both a
  Claude-native worktree exercising the `handoff` + finish path and, if
  feasible, an other-agent worktree exercising scripted teardown) before the
  work is declared done — per this repo's workflow-verification standard.
- Deployed-test guard: the `_test.py` ships to `~/.claude/skills/`, so any
  repo-internal path in the test must be `skipTest`-guarded (skill Python is
  not in the ruff gate).

## 6. Continuations

- **Shared completion-gate rule portability** — the shared rule mandates
  Claude-only capabilities (`Workflow(...)`, `wait-for-pr-comments`, and now
  this skill); decide whether such references become tool-conditional. File as
  its own bead; pre-existing pattern, deliberately not fixed here.

## Review feedback

- **Codex adversarial review of PR #255 (2026-07-13)** found four
  destructive-boundary defects in the single-phase design (script removes the
  caller's cwd; discard authorized by a stale gate; main checkout mutated
  ungated; `checkout` path-vs-branch ambiguity) plus a symlink
  misclassification (Copilot). The two-phase plan/finish contract in §2–§3 is
  the redesign that resolves them.
