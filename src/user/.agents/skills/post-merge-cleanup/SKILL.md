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

`gitclean --report` measures all three in one call and answers the only question
that decides a deletion: **is this provably merged?** `gitclean --cleanup` then
takes the subset it proved, and re-asks git whether each deletion actually
happened rather than trusting an exit code.

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
decision to make and never yours to make for them.
