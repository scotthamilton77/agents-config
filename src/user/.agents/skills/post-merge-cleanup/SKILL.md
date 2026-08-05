---
name: post-merge-cleanup
description: What should be true once a pull request merges — its branch, its worktree and the server's copy gone, and nothing unmerged gone with them — and the tool that proves it before deleting. Use after a merge lands, when a branch's work has shipped, or when asked to tidy up finished work. Not for merge conflicts, and not for deleting one branch the user already named.
admission:
  provides: Knowledge that `gitclean` exists and settles this question in one call. Measured over nine headless trials on a fixture built to break hand-rolled ancestry reasoning, agents reached the correct end state eight times in nine unaided and reached for `gitclean` zero times in nine, with it on PATH throughout. What they lack is not the reasoning, which they reinvented in every trial, but knowing the tool is there — plus the one discipline they did drop, which was describing a worktree they never surveyed.
  cost: One catalog description, always-on, across every tool that installs it. The body is paid only on invoke, and the tool it names is one command.
  remove_when: An agent handed a merged pull request, with this skill unloaded, reaches for `gitclean` unprompted in two consecutive sessions — or `gitclean` stops being installed. The nine-trial baseline that returned zero is the measurement to repeat.
---

# After a merge lands

The end state worth reaching:

- the branch whose work merged is gone, along with the worktree holding it and
  the server's copy
- every branch whose work has **not** merged is still there
- nothing uncommitted, unpushed, or reachable from nowhere else went with them

## Reaching it

`gitclean --report` measures all three in one call and answers the question
nothing else answers reliably: **is this provably merged?** Proof is necessary
and not sufficient. A bare `gitclean --cleanup` takes what it proved *and* what
clears its other measured checks, so a merged branch a worktree still holds, or
one whose tree is dirty, is reported with the reason rather than swept. Each
deletion it does make is verified by re-asking git, not by trusting an exit code.

The copy on the server is held back from that sweep whatever the proof: a ref
there has no reflog, so `gitclean` removes it only when it is named. The end
state above therefore needs a further call naming that ref — after the user has
agreed to it, never bundled into the sweep on their behalf.

After a pull request **you** merged, `gitclean --after-merge <pr>` takes that
one pull request's branch and worktree without asking. It is not a naming and
skips nothing: it applies the same proof and the same checks a bare sweep does,
scoped to what that pull request produced, and reports whatever it will not
take. What authorises it is that the pull request merged — a fact the forge
answers, not one you judged. The server's copy is **not** in its scope; that
still waits to be named.

Reach for it. It is easy not to — it is a CLI on PATH, not a git subcommand, so
nothing in a git session suggests it exists. If it is not installed, say so
rather than substituting `git branch --merged`: under a squash merge that answer
is wrong in both directions, hiding merged branches and reporting live work as
merged.

## The one thing to hold to

**Do not describe a branch or worktree you did not measure.** A row that reads
"just your on-deck branch" about a worktree holding three uncommitted files is
worse than no row at all, because the user answers it — and authorises a
deletion on the strength of a survey that never happened.

So: survey everything you mention, relay each withheld target **with the reason
given**, and say plainly when something was not measured. Naming a target to
`gitclean` skips the checks a bare sweep applies, which makes it the user's
decision to make and never yours to make for them — the one exception being the
pull request you merged, where nothing is skipped and nothing was judged.
