# gitclean

Surveys the current repository's worktrees and branches, sweeps what it can
prove is merged, and reports everything else with the measurement that stopped
it.

```bash
gitclean --report                    # JSON state; changes nothing
gitclean --report --format human     # the same, readable
gitclean --cleanup --dry-run         # what a bare sweep would take
gitclean --cleanup                   # take it
gitclean --cleanup feat/old wt-name  # delete exactly these
```

## One question, asked six ways

`git branch -d` refuses a squash-merged branch, so a `-d`-only cleanup never
cleans anything in a squash-merge workflow. Real merge evidence is required,
and acting on it means `git branch -D` — which owns every deletion decision
outright. So the tool answers the narrowest question that still gets the job
done: **is this provably merged?** It never asks whether anyone still wants the
work, because nothing in a repository measures that.

A bare `--cleanup` takes a target only when all six hold. The first one that
does not is what lands in the target's `withheld` field.

| # | question | answered from |
|---|---|---|
| 1 | is the merge proven? | `merge_evidence` is `pr_merged`, `ancestor`, `patch_equal` or `squash_equal` |
| 2 | is the default branch verified? | `origin/HEAD` or a local `main`/`master` that resolves |
| 3 | is this the trunk? | the default branch, the ref merges are measured against, and either one's counterpart across the remote boundary — by name *and* by commit |
| 4 | is the working tree empty? | a measured zero from `git status`; unknown and `prunable` are not zero |
| 5 | is this a server ref? | server refs are deleted only when named |
| 6 | is this the directory we are running in? | resolved at survey time |

A worktree is judged on **the commit it holds** — its branch's tip when it has
a branch, its detached HEAD when it does not. A commit no ref proves merged has
no proof, whether or not a branch names it.

Naming a target deletes it. Nothing is re-derived, no flag is demanded, and the
reflog is the undo for a local branch. Two things still stop a named deletion:
the worktree this process is running in, and git itself — a checked-out branch,
a dirty or locked worktree. Those refusals arrive verbatim, with the transcript.

## How a merge gets proven

`git branch --merged` is wrong in both directions under a squash-merge
workflow: it calls squash-merged branches unmerged, so cruft accumulates
forever, and it says nothing about a PR closed without merging. Evidence is
resolved in tiers, cheapest conclusive answer first, and the tier that fired is
recorded on the branch:

| `merge_evidence` | how | proof? |
|---|---|---|
| `pr_merged` | gh reports a merged PR whose head contains this tip. The only signal that survives a squash merge intact. | yes |
| `ancestor` | reachable from the base tip. | yes |
| `patch_equal` | every commit's patch-id is already in base (rebase, cherry-pick). | yes |
| `squash_equal` | the branch's tree, replayed as one commit on the merge base, has a patch-id in base. | yes |
| `pr_closed_unmerged` | a human closed the PR without merging. | **no** — reported only |
| `none` | nothing proved a merge. Not the same as "not merged": see `repo.gh_error`, and the row's own `reasons` for a tier that errored rather than answering. | no |

A closed PR says someone stopped wanting the change. It says nothing about
whether the commits exist anywhere else, and they do not — they are still only
on that branch. It is the most useful line in the row for a person deciding
what to name, and it authorises nothing.

Without `gh` on PATH there is no squash signal at all. That is reported in
`repo.gh_error`, never swallowed.

## Safety

- **Cleanup re-surveys before acting.** The report you read may be stale.
- **No `--force` anywhere.** git refuses to remove a worktree holding modified
  or untracked files, a locked worktree, or the main working tree, and each
  refusal knows what that directory holds *right now* rather than when the
  survey read it. Overriding them would mean re-implementing every one of those
  checks in Python. A person who has read git's complaint and still wants the
  tree gone runs one `git worktree remove --force` themselves.
- **A removal that would strand a commit is declined.** git's refusals cover
  *uncommitted* content and know nothing about a commit made inside a worktree
  on no branch: that tree is clean, so git removes it without complaint, and
  the administrative record it deletes is the only thing holding that commit —
  the per-worktree reflog goes with it. So before removing a worktree the tool
  asks git whether any ref contains the commit that tree holds *now* — re-read
  as the deletion happens, not taken from the survey — and declines when none
  does, naming the commit and how to keep it. A commit made in that tree since
  the survey ran is exactly the one at risk, and the surveyed commit it
  replaced would have answered for it. Naming a target authorises deleting a
  checkout; it should not quietly spend a commit.
- **Salvage is kept only where there is no reflog** — a ref on the server.
  It becomes a verified `git bundle` before the delete, and a bundle that will
  not verify aborts that deletion. A local branch needs none: `branch -D`
  leaves its commits in the reflog for git's configured expiry.
- **Remote deletes are leased.** Every verdict about a remote branch comes from
  your local `refs/remotes` cache. The delete carries `--force-with-lease`, so
  if the server moved since your last fetch it is rejected rather than taking
  commits nobody surveyed.
- **Every deletion is verified by re-asking git.** A zero exit code is a claim,
  not a fact. A ref that survives becomes an anomaly, not a success line.
- **Anomalies carry the transcript** — argv, exit code, both streams — so a
  reader can remediate without re-running anything.
- **Omissions are named.** A target the sweep selected and then dropped is
  reported under `plan.skipped`; a target that never entered the sweep carries
  its own `withheld`.
- **A question git did not answer is stated on the row it concerns.** Counts
  come back `null` rather than `0`, and the target's `reasons` say which probe
  went unasked — a tier that errored, a working tree that would not stat, a PR
  list that came back short. The top-level `warnings` still collect them, but a
  reader deciding what to name is looking at the row, and there "not measured"
  has to read differently from "measured zero".

A repository whose default branch cannot be identified — no published
`origin/HEAD`, no `main`, no `master` — sweeps nothing at all, because the run
cannot tell the trunk from cruft. Naming targets still works. Publish it with
`git remote set-head origin -a`.

## Trades worth knowing

**Ignored files are reported, not protected.** They are counted per worktree
and named in its `reasons`, but they do not keep it out of the sweep. In
practice ignored content is build detritus — caches, virtualenvs, coverage data
— and treating it as work at risk would put a manual triage in front of every
cleanup. The accepted cost: sweeping an **already-merged** worktree deletes a
`.env` that lives only there. The count appears in the report first.

**A branch parked exactly on the trunk's commit is left alone.** The trunk is
matched by commit as well as by name, because `main` and `origin/main` are
different strings for the same thing. The cost is an occasional branch nobody
swept; the alternative is deleting the trunk, which merge evidence alone would
authorise — `main` is an ancestor of `origin/main`.

**`--report` writes one loose object.** Proving a squash merge means
synthesising the equivalent single commit with `git commit-tree` and asking
`git cherry` about that. The object is unreachable, touches no ref, and `git
gc` collects it. Suppressing it in report mode would make `--report` and
`--cleanup` disagree about what is merged, which is worse than a stray blob.

**A branch whose name begins with `-` is deleted correctly, but proven merged
only some of the way.** `git branch` will not create such a ref, but `git
update-ref` will and a remote can push one. Every deletion terminates its argv,
so git reads the name as a name — a `-m` branch that ancestry or patch-id
proves merged is swept, and one named outright is deleted and its server copy
bundled. The squash tier is the gap: it asks `merge-base` and `rev-parse` for
the branch without a terminator, git rejects the name as a switch, and the
probe gives up. A squash-merged `-m` therefore reads as unproven and stays in
the report — the safe direction, and the wrong answer. Naming one on the
command line is a separate matter, because the argument parser claims `-m` as a
flag first: select it by its `id`, `gitclean --cleanup branch:-m`.

## Exit codes

| code | meaning |
|---|---|
| 0 | clean |
| 1 | refused (see `refusal.code` and `refusal.remedy`) |
| 2 | unusable (not a repository, bad arguments) |
| 3 | acted, but something surprised us (see `execution.anomalies`) |

## Scope

The current repository only: the cwd's repo, its linked worktrees, and its
local and remote branches. What merges are measured against is discovered, not
supplied — a caller who could point it elsewhere could measure the trunk
against something that contains it and hand it to the sweep.

## Development

```bash
make ci-gitclean     # the full gate: lint, format, types, coverage, audit, entry
make test-gitclean   # faster inner loop
```
