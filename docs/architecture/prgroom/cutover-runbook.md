# prgroom cutover runbook

Operational procedures for migrating PR grooming from the legacy skills
(`wait-for-pr-comments` + `reply-and-resolve-pr-threads`) onto the `prgroom`
CLI, and for rolling back if the loop misbehaves. The migration is staged; the
full rationale lives in the dated design proposal
[`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md),
Section 6 ("Migration & cutover"). This runbook is the operator-facing
distillation of §6.4–6.6.

## Why a runbook (the two state stores never collide)

prgroom writes its own session store and never reads the legacy one:

| Tooling | State store |
|---|---|
| prgroom | `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`) |
| legacy skills | `~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json` |

Because neither reads the other, each PR **must be groomed by exactly one —
legacy XOR prgroom**. This is an operator-maintained invariant, not an automatic
guarantee: nothing stops both loops from running against the same PR, which would
risk double-posting. The procedures below exist to preserve it across the cutover.

## Operator preflight (before any prgroom run)

prgroom is not yet deployed by the installer; install it as a uv tool and
verify the entry point:

```bash
uv tool install --from /path/to/agents-config/packages/prgroom prgroom
prgroom --help   # must exit 0
gh auth status   # must show an authenticated github.com login
```

Then, for the PR being groomed:

- **Run from a worktree checked out on the PR's head branch.** The fix agent
  commits into the current worktree, and `push` refuses to act from any other
  branch (`PRECONDITION_WRONG_BRANCH`).
- **Pick the mode by trigger**: a chat/human-initiated session uses
  `prgroom run <owner>/<repo>#<n> --interactive` (returns control between
  cycles); cron/CI supervision uses `--autonomous` (the default — blocks in
  `wait` between cycles). The monitor-pr skill's trigger table is the
  authoritative mode-selection rule; this bullet is its operator summary.
- **One groomer per PR** (the invariant above): confirm the PR has no live
  legacy inventory before pointing prgroom at it, and never invoke the legacy
  skills on a prgroom-groomed PR.
- **Read `status --json`'s `phase`, never the exit code alone** — an exhausted
  retry budget rides on exit 0 with `phase: human-gated`.
- **Inspecting state when a run misbehaves**: the per-PR state file
  (`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`, fallback
  `~/.local/state/prgroom/`) is the ground truth for what the loop believes about
  the PR. Read it lock-free with `prgroom status <ref> --json`; add `--locked`
  only for a strictly-consistent read, and note it **exits 75 under contention**
  rather than blocking — so plain `status --json` is the safe probe while a run
  holds the lock.

## Drain before cutover

Before installing a destructive cutover phase, finish (merge or abandon) every
PR that still has a live legacy inventory:

```bash
ls ~/.claude/state/pr-inventory/ 2>/dev/null   # tolerant of a missing / already-drained dir
```

Each file there is a PR mid-flight under the legacy skills. **Drain — do not
hand over.** The legacy `resolve` step is idempotent (re-resolving a thread is a
server-side no-op), but the legacy `reply` step is **not**: pointing prgroom at a
half-replied legacy PR would double-post. A drained boundary is the clean
handoff. Once the directory is empty, every new PR is prgroom-native from a fresh
session.

## Readiness gate (before retiring the legacy tooling)

Do not burn the legacy rollback anchor until the prgroom loop is trusted. The
gate to advance from the additive phase (monitor-pr coexisting with the intact
legacy skills) to a destructive retirement:

- **≥ 3 real PRs** groomed end-to-end to `quiesced` / `merged`,
- with **no rollback**, and
- **no observed wrong/duplicate reply and no bad thread-resolve**.

Until the gate is met, the legacy skill stays installed and independently
invocable as the rollback anchor.

## Rollback

No auto-rollback — operator judgment. Trigger one when prgroom:

- corrupts or loses its session state,
- posts a wrong or duplicate reply,
- resolves a thread that was not actually fixed,
- ships a fix-agent regression the audit missed, or
- costs measurably more tokens than the skill it replaced (which defeats the goal).

The rollback unit is the phase's git commit:

```bash
git revert <phase-commit>     # restores every file the phase deleted (legacy skill + scripts)
scripts/install.sh            # WITHOUT --prune, so the reverted scripts redeploy
```

`git revert` restores every file the phase deleted, so the legacy chain comes
back whole. prgroom's separate state store is untouched by the revert; a reverted
PR re-grooms under the restored legacy tooling from a drained / fresh state.

> **Run `install.sh` WITHOUT `--prune`.** `--prune` removes deploy outputs that
> are no longer in the source tree — exactly the legacy scripts the revert just
> restored to source. Running it with `--prune` would delete them again.

### Straggler escape hatch

A legacy PR that must be touched after a cutover: `git revert` the phase
temporarily, finish the PR on the restored legacy tooling, then re-apply the
phase. The rollback path doubles as the straggler escape hatch.
