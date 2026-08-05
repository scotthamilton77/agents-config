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
reflog is the undo for a local branch. Three things still stop a named deletion:
the worktree this process is running in; git itself — a checked-out branch, a
dirty or locked worktree — whose refusals arrive verbatim, with the transcript;
and a listing that dropped a row it could not parse, which leaves the run unable
to say the one thing your name matched is the only thing it matches.

A bare name reaches a worktree or a local branch. The copy on a server answers
to its full `<remote>/<ref>` spelling and to nothing shorter, so the name you
just merged is never ambiguous between the two — and a bare name that only a
server ref wears is refused with the full spelling to use, rather than reported
as already gone about a ref that is sitting right there.

Each refusal stops only the name it is about. Whatever else was named and
resolved cleanly is deleted, every refusal lands in `plan.refused` with its own
code and remedy, and the run exits 1 for having raised any — so one mistyped
name costs a correction rather than a whole re-run. **Exit 1 therefore does not
mean nothing happened**: read `execution.deletions` for what did.

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
| `squash_equal` | the branch's tree, replayed as one commit on the merge base, has a patch-id in base. Silent when the branch ends on the tree it started from — see below. | yes |
| `pr_closed_unmerged` | a human closed the PR without merging. | **no** — reported only |
| `none` | nothing proved a merge. Not the same as "not merged": see `repo.gh_error`, and the row's own `reasons` for a tier that errored rather than answering. | no |

A closed PR says someone stopped wanting the change. It says nothing about
whether the commits exist anywhere else, and they do not — they are still only
on that branch. It is the most useful line in the row for a person deciding
what to name, and it authorises nothing.

**A branch that ends on the tree it began from proves nothing here, by
construction.** Work added and then taken off again leaves the tip's tree equal
to the merge base's, so the commit this tier synthesises would carry an empty
diff — and every empty diff has the same patch-id as every other. Base need
only have picked up one empty commit since the fork, which is what a build
retrigger leaves, for `git cherry` to call that a match. So the tier stops
before it asks. The cost is a no-op branch nobody sweeps; the alternative is
deleting a branch whose commits are the only copy of the work they hold.

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
- **Salvage is kept only where there is no reflog** — a ref on the server. It
  becomes a `git bundle` before the delete, and what earns the delete is a
  restore, not an inspection: the bundle is cloned into an empty directory and
  the commit about to be deleted has to come back out of it. `git bundle
  verify` is not that check — it asks whether the archive applies to the
  repository that already holds every object, and says yes both to a bundle
  that clones back empty and, in a shallow clone, to one `git clone` refuses
  outright with `remote did not send all necessary objects`. A salvage that
  does not restore is reported as an anomaly with the transcript, recorded as
  no salvage at all, and aborts its deletion. The cost is unpacking that
  branch's history once more per server ref actually deleted. A local branch
  needs none of this: `branch -D` leaves its commits in the reflog for git's
  configured expiry.
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

**A branch whose name begins with `-` is deleted correctly, and proven merged
by every tier, including squash.** `git branch` will not create such a ref,
but `git update-ref` will and a remote can push one. Every deletion terminates
its argv, so git reads the name as a name. Merge evidence does the same, with
one adjustment: `merge-base` accepts a `--` terminator, but `rev-parse` does
not — it echoes one back as a literal output line instead of consuming it — so
the squash tier's tree lookup instead names the branch by its full ref path,
which never begins with `-`. A squash-merged `-m` is proven and swept the same
as any other name. Naming one on the command line is a separate matter,
because the argument parser claims `-m` as a flag first: select it by its
`id`, `gitclean --cleanup branch:-m`.

## Exit codes

| code | meaning |
|---|---|
| 0 | clean |
| 1 | something was refused (`plan.refused[]`, or `refusal` for a whole-run one) — other named targets may still have been deleted |
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
