# gitclean

Surveys the current repository's worktrees and branches, classifies what is
deletable, and deletes only what it can prove is safe.

```bash
gitclean --report                    # JSON state; changes nothing
gitclean --report --format human     # the same, readable
gitclean --cleanup --dry-run         # what a bare sweep would take
gitclean --cleanup                   # take it
gitclean --cleanup feat/old wt-name  # exactly these
gitclean --clean-all --force         # everything not protected, salvaged first
```

## Two verdicts, kept separate

Each deletable target carries both. Collapsing them is what makes hand-rolled
cleanup dangerous — a branch can be abandoned and still hold the only copy of
its commits, and a branch can be active while carrying no risk at all.

| `disposition` | is this still live work? |
|---|---|
| `protected` | the default branch, the checked-out branch, the main worktree, a locked worktree. Never deletable — `--force` does not apply. |
| `safe` | merge proven, or a PR closed it unmerged. |
| `active` | an open PR, a dirty worktree, or activity inside the idle window. |
| `abandoned` | no PR, no merge evidence, idle past the window. Reported for a human decision; never swept automatically. |

| `risk` | would deleting destroy the only copy? |
|---|---|
| `none` | the content survives elsewhere. |
| `recoverable` | unique content; the reflog is the fallback. |
| `data_loss` | uncommitted work, or a remote ref the server keeps no reflog for. |

A bare `--cleanup` takes only `safe` **and** `none`. `--force` overrides `risk`
— salvaging first — and never overrides `protected`.

## How a merge gets proven

`git branch --merged` is wrong in both directions under a squash-merge
workflow: it calls squash-merged branches unmerged, so cruft accumulates
forever, and it says nothing about a PR closed without merging. Evidence is
resolved in tiers, cheapest conclusive answer first, and the tier that fired is
recorded on the branch:

| `merge_evidence` | how |
|---|---|
| `pr_merged` | gh reports a merged PR. The only signal that survives a squash merge intact. |
| `pr_closed_unmerged` | a human closed it without merging — a discard decision, which expires if commits land after the close. |
| `ancestor` | reachable from the base tip. |
| `patch_equal` | every commit's patch-id is already in base (rebase, cherry-pick). |
| `squash_equal` | the branch's tree, replayed as one commit on the merge base, has a patch-id in base. |

Without `gh` on PATH there is no squash signal at all. That is reported in
`repo.gh_error`, never swallowed.

## Safety

- **Cleanup re-surveys before acting.** The report you read may be stale.
- **`--force` salvages before deleting.** Branches become verified `git bundle`
  archives; a dirty worktree's tracked changes become a bundle and its
  untracked files are copied. A bundle that does not verify **aborts that
  deletion**.
- **Every deletion is verified by re-asking git.** A zero exit code is a claim,
  not a fact. A ref that survives becomes an anomaly, not a success line.
- **Anomalies carry the transcript** — argv, exit code, both streams — so a
  reader can remediate without re-running anything.
- **Omissions are named.** An automatic sweep that skips a target reports it
  under `plan.skipped`.

Salvage lands in `<git-common-dir>/gitclean-salvage/<timestamp>/`. Restore a
branch with `git clone <bundle> -b <branch>`.

## Exit codes

| code | meaning |
|---|---|
| 0 | clean |
| 1 | refused (see `refusal.code` and `refusal.remedy`) |
| 2 | unusable (not a repository, bad arguments) |
| 3 | acted, but something surprised us (see `execution.anomalies`) |

## Scope

The current repository only: the cwd's repo, its linked worktrees, and its
local and remote branches. Remote deletions require `--include-remote` —
they affect other people's fetches, open PRs, and CI refs.

## Development

```bash
make ci-gitclean     # the full gate: lint, format, types, coverage, audit, entry
make test-gitclean   # faster inner loop
```
