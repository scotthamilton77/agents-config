---
description: Adjudicate which git worktrees and branches to delete. Presents one dated table with each worktree paired to its branch, every unproven candidate already investigated, and what each deletion would spend — then waits for your call before touching anything.
admission:
  provides: A cleanup a human can decide from consequences instead of git internals. Invoking it produces one dated table — worktrees paired with their branches, the trunk absent unless it has news, each unproven candidate investigated before it is shown, and the cost of each deletion stated on its own row — followed by a stop for ratification. It never deletes anything the operator has not named back.
  cost: One Claude-scoped command. Only its description line is always-on; the body and the investigation are paid solely when someone types it. The investigation is the expensive part — a merge-base diff per candidate carrying no merge proof, plus at most one tracker lookup for each whose name happens to carry an identifier.
  remove_when: Two consecutive cleanups in which the operator makes every keep-or-delete call straight from `gitclean --report --format human` without asking a follow-up question.
---

# /clean-up-git

`gitclean` measures. You decide. This command does the arranging and the digging
in between.

`$ARGUMENTS` is an optional filter on **what the table shows** — a name, a path,
or a fragment of either. Empty shows everything.

> Naming something here does **not** authorize deleting it. `gitclean` treats a
> named target as the caller's decision and skips the checks a bare sweep
> applies. It still refuses an ambiguous name, a branch a worktree holds, and
> the worktree the run is standing in — but the authorization itself only ever
> comes from step 4. Say this back to the user if they appear to have meant
> otherwise.

If `gitclean` is not on PATH, say so and stop.

**MUST NOT** substitute `git branch --merged`, `git log`, branch names, or commit
dates. Under a squash-merge workflow ancestry is wrong in both directions — it
hides merged branches forever *and* reports live work as merged. That failure is
the reason the tool exists.

**MUST NOT** run `git branch -D`, `git worktree remove`, or `git push --delete`.
`gitclean` re-asks git whether each deletion happened; raw git hands you its own
exit code and nothing else.

## 1 — Survey and arrange

`gitclean --report --format json` changes nothing. Build everything below from
that one envelope; do not re-derive any of it with raw git.

**Drop the trunk from the candidates.** The default branch and the worktree
holding it are never junk. `gitclean` withholds them, but the reason it prints
varies with the repository's state and is never a reason to delete them. Give
the trunk one line, and only when it carries news: it moved, it is ahead or
behind, or it is not where the reader will assume. Otherwise say nothing.

**Pair each worktree with its branch, and both with the server's copy.** They
share a timestamp and are one thing with two or three parts. It is also a
correctness fact — git refuses to delete a branch its worktree still holds — so
a reader choosing one has to see the others.

Pair them from the envelope's own relationship fields, never by re-parsing a
name. Remote names may contain slashes, so splitting one silently mis-keys the
row — and the failure looks like a fact, because a lookup that misses returns
nothing, and nothing reads as "never pushed" about a branch that exists
precisely because it was pushed. **Where a counterpart cannot be identified,
the row says so. It does not say there isn't one.**

**Order by last activity, oldest first.** Not by kind, not by evidence tier. It
is the ordering that needs no explanation — but a timestamp is a commit date,
not evidence of abandonment, so let it order the table and never let it justify
a deletion.

## 2 — Investigate anything with no merge proof

Do this **before** presenting, and put the finding in the row. A row reading
"unproven" with no account of what the work was is an unfinished job, not a row.

- If the branch name carries an identifier, look it up in whatever issue tracker
  the project uses, and check whether that item still exists. An id resolving to
  nothing is itself the finding.
- A worktree with no branch has no name to look anything up by. Investigate it
  from the commit it holds instead — and never drop it from the table for want
  of a name, which is how the one candidate nobody can explain goes unshown.
- Diff the branch against **its own merge base**, never against the current
  trunk, where the output drowns in unrelated drift.
- Check whether the files it touches still exist, or have since been retired.
- Compare it against sibling branches for work already folded in elsewhere.

Aim for a finding a human can decide from in one sentence: *"patches three files
that no longer exist"*, *"superseded — two of its three commits re-landed on the
branch you are keeping"*, *"nothing on it yet; branched an hour ago"*.

## 3 — Present

One table, oldest first, one entry per group.

**State consequences, not mechanics.** Never make `squash_equal`, `patch_equal`
or "merge base" load-bearing. Write *"merged as #436 — squashed, so its commits
are not on the trunk by ancestry, which is expected"*. Keep the mechanical term
available for the reader who wants it; never require it.

**Quote what a deletion spends, verbatim from the envelope** — unpushed commits,
an open pull request, ignored files that will not regenerate, uncommitted files
living only there. Summarize the rest if you must; never this. A reader cannot
detect an omission here, and an open PR with 38 commits behind it looks exactly
like a stale branch until someone says so.

**A cost that could not be measured is reported as unmeasured, never dropped.**
`gitclean` says when a count failed rather than guessing zero, and a row that
silently omits what it could not read presents an unknown as a nothing. If the
ignored-file count for a worktree is unreadable, the row says the count is
unknown — because the file that does not regenerate is exactly the one nobody
will miss until it is gone.

**Distinguish "nothing on it yet" from "finished".** A worktree branched an hour
ago sits on the trunk tip, so `gitclean` withholds it — it cannot tell deleting
that from deleting the trunk. The withheld reason therefore talks about the
trunk, which is not what the reader needs to know: nothing on disk says whether
an agent is working there. Say "nothing on it yet" rather than "finished", and
never present a withheld row as one a sweep would have taken.

**Relay every `withheld` reason as given**, and report `plan.skipped` — a sweep
that quietly did less than asked reads as success. If `repo.gh_error` is set,
merge evidence was git-only and squash merges were invisible to it; say so
before presenting anything as safe.

## 4 — Ratify, then act

Stop. Ask which entries go. **MUST NOT** name a target the user did not name —
not to route around a `withheld` reason you find unconvincing, and not because
your own read of the history says it is safe.

Then `gitclean --cleanup --dry-run` with exactly those names, show the plan, and
`gitclean --cleanup` with the same names. **MUST NOT** re-run a refused command
unchanged: every refusal carries a `remedy` saying what would let it proceed.

**A remedy is advice to the user, not authority for you.** Some of them widen
the selection — the refusal for a branch a worktree still holds is remedied by
adding that worktree to the cleanup, and taking that step yourself would delete
a directory nobody named. Where a remedy would add a target the user did not
name, relay it and stop. Otherwise follow it, or drop the blocked target and
clean the rest.

**Exit 0 is a claim, not a result.** State what was deleted and what was
verified. Exit 3 means it acted and something surprised it: read
`execution.anomalies`, which carry the failing argv, the exit code and both
streams. Diagnose from those; do not re-run to see what happens.
