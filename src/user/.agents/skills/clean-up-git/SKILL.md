---
name: clean-up-git
description: Delete stale git worktrees and branches safely, via the gitclean CLI. Invoke when asked to clean up worktrees, prune merged or stale branches, or tidy git cruft. Not for resolving merge conflicts, not for issue-tracker cleanup, and not for deleting a specific branch the user already named and confirmed.
admission:
  prevents: An agent destroying unmerged or uncommitted work during cleanup — either by hand-rolling `git branch --merged`, which under squash merges both misses real cruft and reports live work as merged, or by re-running with --force after the tool refuses a data-loss deletion.
  cost: About 25 always-on tokens for this description line; the body is paid only on invoke.
  remove_when: Two consecutive cleanup sessions where an agent given only `gitclean --help` chooses the tool over hand-rolled git AND respects a refusal, with this skill unloaded.
---

Cleanup destroys work irreversibly. `gitclean` exists because the checks a
human would run by hand are wrong often enough to lose commits. Your job is to
run it, read it, and **not talk yourself past its refusals**.

## Never hand-roll the analysis

**MUST NOT** decide what is deletable with `git branch --merged`, `git log`,
branch-name patterns, or commit dates. Every one of those is wrong in both
directions under a squash-merge workflow.

**MUST NOT** run `git branch -D`, `git worktree remove`, or
`git push --delete` directly during a cleanup task. `gitclean` verifies every
deletion actually happened; raw git does not.

If `gitclean` is not on PATH, say so and stop. Do not substitute git commands.

## The loop

1. `gitclean --report --format human` — survey. Changes nothing.
2. Show the user what is sweepable now, and separately what is `abandoned` or
   `data_loss`. Never fold those together.
3. `gitclean --cleanup --dry-run` before any real run.
4. `gitclean --cleanup` for the safe subset, or name exact targets by their
   `id` field.

Read `gitclean --help` for flags and field meanings. Do not restate them here.

## --force is the user's decision, never yours

A refusal is a finding, not an obstacle.

**MUST NOT** add `--force`, `--clean-all`, or `--include-remote` because a
previous run failed and the error message mentioned the flag. That reflex is
the single most likely way this task destroys work.

When you hit `E_DATA_LOSS`:

1. Report **which** targets are blocked and why — the refusal lists them.
2. Offer the narrower move first: drop those targets and clean the rest.
3. Only use `--force` when the user, seeing that list, tells you to.

`E_PROTECTED` is not overridable at all. Do not retry it with `--force`; fix
the cause (switch branches, unlock the worktree) or drop it from the selection.

`--clean-all --force` deletes everything not protected. Propose it only if the
user asks to wipe everything, and run `--dry-run` first, every time.

Remote deletions are outward-facing — they break other people's fetches and
open PRs. `--include-remote` needs an explicit ask.

## Reporting back

- Exit 3 means it acted and something surprised it. Read
  `execution.anomalies` — each carries the failing command's argv, exit code,
  and output. Diagnose from that; do not re-run blindly to "see what happens".
- If `repo.gh_error` is set, merge evidence was git-only and **squash merges
  were invisible**. Say so before presenting anything as safe.
- Report `plan.skipped` entries. A sweep that quietly did less than asked reads
  as success.
- If anything was salvaged, give the user the salvage path.

Never report a cleanup as complete on the strength of exit code 0 alone —
state what was deleted and what was verified.
