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
- Never git-remove a worktree yourself and never run teardown from inside it;
  relay the handed-back steps verbatim (the `cd` in the finish command is what
  evacuates the shell).
- Never merge from this skill; route "merge it" through `merge-guard`.
