---
name: using-git-worktrees
description: Create a git worktree, and find out which workspace you are already standing in before you create anything. Use before starting work that must not touch the branch currently checked out, when a task says to work in an isolated workspace, or when you are unsure whether you are already in one. Not for deleting a worktree or a branch once work has merged — that is post-merge-cleanup.
admission:
  prevents: Isolation being judged by eye and judged wrong. The obvious check — comparing what `git rev-parse --git-dir` and `--git-common-dir` print — reports "already isolated" from any subdirectory of an ordinary checkout, because git prints one absolute and one relative, so the work lands on the branch the user had open. The obvious ignore check, `git check-ignore -q .worktrees`, answers "not ignored" against the conventional `.worktrees/` pattern whenever the directory does not exist yet, which is the state you are in before the first worktree. Both reproduce on git 2.50, the second against this project's own .gitignore.
  cost: One catalog description, always-on, on every tool that installs it. The body and one script run are paid on invoke.
  remove_when: Every supported tool exposes a worktree primitive of its own that reports what it created, so no agent reaches `git worktree add` by hand.
---

<!--
Source: skills/using-git-worktrees/
Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
Last sync: 2026-08-07
Drift policy: rewrite-and-divorce. The step order and the location convention come from upstream; the detection is now a shipped script that corrects two measurements upstream's prose gets wrong, and the consent prompt is deliberately removed. A resync would reintroduce both.
-->

# Using git worktrees

A worktree is a second checkout of one repository, on its own branch, with its
own index and HEAD. It lets work proceed without disturbing whatever the user
has open.

Creating one is cheap. Creating a second one because you could not tell you
were already inside the first is not — nor is deciding you are isolated when
you are not, and committing to the user's branch.

## 1. Survey before you create

Run `scripts/worktree_status.py` from anywhere in the project. It prints where
you are, what git thinks the workspace is, and whether the conventional
directories are ignored. It resolves both git paths before comparing them and
probes ignore rules with a path that answers correctly whether or not the
directory exists — do not re-derive either check by hand, because both are
wrong when taken the obvious way.

| `verdict:` | What it means | What to do |
|---|---|---|
| `linked-worktree` | Already isolated, on the branch reported | Nothing. Work here. Do not nest another. |
| `main-checkout` | An ordinary checkout — the user's workspace | Step 2, if the task needs isolation. |
| `submodule` | Inside a submodule of the project named on `submodule-of:` | Step 2 here isolates **the submodule**, not the project. Move to the superproject first unless the submodule is genuinely the target. |
| `not-a-git-repository` | Nothing to isolate | Say so. Do not `git init`. |

If `branch:` reads `(detached HEAD)`, you are isolated but have nowhere to
commit; create a branch before writing anything.

## 2. Create the worktree

If your harness has its own worktree primitive — a tool or command that creates
one and tells you where it put it — use that instead of this step. It owns
placement and cleanup; going around it leaves state the harness cannot see.

**A new worktree starts from the last commit, not from what is on disk.**
Unstaged edits, staged-but-uncommitted files and untracked files all stay
behind in the checkout you left. Run `git status` first: if the work you are
about to isolate is sitting there uncommitted, commit or stash it, or you will
arrive in the new worktree without it.

Then, and only from a `main-checkout`:

```bash
git worktree list                      # where does this project already put them?
git worktree add <dir>/<branch> -b <branch>
```

**Placement.** Match what `git worktree list` already shows — several agents
may share this project, and one convention is what lets them find each other's
work. Ignore any entry marked `prunable`: its directory is already gone. With
nothing to match, use `.worktrees/<branch>` at the top level.

**The directory must be ignored before anything is created in it**, or the next
`git add` sweeps an entire second checkout into the index. The survey's
`candidate:` lines answer this already. If it reports `ignored=no`, add the
directory to `.gitignore` and commit that first.

**Branch names are exclusive.** One branch can be checked out in one worktree
at a time; `git worktree add` refuses a branch another worktree holds, and
names it. That refusal is information — go to that worktree rather than around
it.

If creation fails on permissions, the sandbox blocked it. Say so and work in
place; do not retry variations.

## 3. Working inside one

**Absolute paths only.** `git worktree add` creates the directory and leaves
you where you were. And because a worktree is a full second copy of the tree,
a relative path like `src/thing.py` is valid in *both* copies: it does not
error, it silently resolves against whichever tree the thing resolving it
happens to be standing in. Build every path from the `toplevel:` the survey
printed, and re-run the survey rather than assuming a `cd` reached everything.

**One committer per worktree.** The index and HEAD are per-worktree, so
separate worktrees never collide — but two things committing in the *same* one
do: the second gets `Unable to create '.git/index.lock': File exists` and
fails. If you delegate work into a worktree, one agent commits there.

**Do not remove a worktree anything is still standing in.** Once the directory
is gone, every command from a process whose working directory was inside it
fails with `Unable to read current working directory`, and the shell stays
broken until something moves it elsewhere. Leave first, then remove.

## What this is not

This skill creates worktrees and works inside them. Removing one, and deleting
the branch it held once that work has merged, is `post-merge-cleanup` — a
different question with a different failure mode, since proving a branch merged
is what makes deleting it safe.
