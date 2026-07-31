---
name: clean-up-git
description: Delete stale git worktrees and branches through the gitclean CLI, which proves a merge before sweeping. Invoke when asked to clean up worktrees, prune merged or stale branches, or tidy git cruft. Not for merge conflicts, and not for deleting one branch the user already named.
admission:
  prevents: An agent deleting work nobody authorized during cleanup — either by hand-rolling `git branch --merged`, whose answer is wrong in both directions under a squash-merge workflow, or by naming a target gitclean withheld, which the tool executes without re-checking because a name is meant to be the caller's decision.
  cost: 69 always-on tokens for this description line, measured; the body's 738 are paid only on invoke. Plus one round-trip per disputed target, since the agent must relay a withheld reason and wait rather than deciding for itself.
  remove_when: Two consecutive cleanup sessions in which an agent with this skill unloaded, given only `gitclean --help`, reaches for the tool instead of hand-rolled git AND relays a withheld reason instead of naming the target itself.
---

# Cleaning up worktrees and branches

`gitclean` answers one question — **is this provably merged?** — and reports
everything it could not prove alongside the measurement that stopped it. Run
it, relay what it found, and leave the rest to the user.

## Never hand-roll the analysis

**MUST NOT** decide what is deletable from `git branch --merged`, `git log`,
branch names, or commit dates. Under a squash-merge workflow ancestry is wrong
in both directions: it hides merged branches forever *and* reports live work as
merged.

**MUST NOT** run `git branch -D`, `git worktree remove`, or `git push --delete`
during a cleanup task. `gitclean` re-asks git whether each deletion actually
happened; raw git hands you its own exit code and nothing else.

If `gitclean` is not on PATH, say so and stop. Do not substitute git commands.

## The loop

1. `gitclean --report --format human` — survey; changes nothing.
2. Relay it: what is sweepable, and separately each withheld target **with its
   stated reason**. Never merge those two lists, and never summarize a
   `withheld` line away — it is the product the survey exists to deliver.
3. `gitclean --cleanup --dry-run` — the plan, before any real run.
4. `gitclean --cleanup` — the provably-merged subset.

Read `gitclean --help` for flags and field meanings. Do not restate them here.

## Naming a target is the user's authorization, never yours

A bare `--cleanup` takes only what it proved merged. **Naming a target skips
every one of those checks by design** — nothing is re-derived and no flag is
demanded, because a name is a decision the caller already made.

**MUST NOT** name a target the user did not name. Not to route around a
`withheld` reason, not because the reason looks weak, and not because your own
read of the history convinced you it is safe. Report the reason and stop. If
the user then names it, run it without further argument — that is their call
to make, and they made it.

**MUST NOT** re-run a refused command with the selection unchanged. Every
refusal carries a `remedy` saying what would let it proceed; follow that, or
drop the blocked target and clean the rest.

## Reporting back

- **Exit 0 is a claim, not a result.** State what was deleted and what was
  verified. Never report a cleanup as complete on the exit code alone.
- **Exit 3 means it acted and something surprised it.** Read
  `execution.anomalies` — each carries the failing argv, its exit code, and
  both streams. Diagnose from that; do not re-run to see what happens.
- If `repo.gh_error` is set, merge evidence was git-only and **squash merges
  were invisible to it**. Say so before presenting anything as safe.
- Report `plan.skipped`. A sweep that quietly did less than it was asked reads
  as success.
- Ignored files are counted, not protected. Caches and virtualenvs regenerate;
  a `.env` living only in that worktree does not. Surface the count before
  sweeping, not after.
