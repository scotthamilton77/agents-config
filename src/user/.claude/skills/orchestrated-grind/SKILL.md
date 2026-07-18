---
name: orchestrated-grind
description: Use when running a long multi-lane agent grind — several work lanes advancing in parallel under named lieutenant agents, each shipping its own PRs through an autonomous bot-review-and-merge loop. Triggers on "orchestrated grind", "grind plan with lanes", "lieutenant orchestration", "run a multi-lane grind", "overnight grind", "grind the backlog", "run these lanes in parallel overnight", "spin up lanes for this plan", "work this queue while I sleep", or any request to drive a conflict-partitioned plan across parallel agent lanes with a live status dashboard. Also apply when an in-flight grind stalls, a lane goes quiet, or a bot reviewer keeps re-raising the same findings.
---

# Orchestrated Grind

## Overview

A **grind** is a long autonomous run in which several work lanes advance in
parallel, each shipping its own pull requests, while one root orchestrator
acts as a switchboard. It exists to convert a conflict-partitioned plan into
merged PRs with minimal human intervention — the human sets direction, rules
on genuine forks, and sleeps.

**Core principle: the root orchestrator is a switchboard, not a manager.** It
routes messages, verifies ground truth, and merges. It does not implement, does
not relitigate its lieutenants' judgment, and never trusts a report it can
cheaply check itself.

This is a **discipline skill**. The rules below were paid for in a real
overnight run of twelve merged PRs; each one exists because its absence cost
something. Follow them as written.

**REQUIRED BACKGROUND:** You MUST understand `orchestrating-subagents` — it
carries the nesting constraint (a subagent cannot await a child it spawns) that
makes this topology necessary in the first place.

## When to use

- A plan is partitioned into 2–4 lanes that touch mostly-disjoint files.
- The run is long enough that the human will be away for part of it.
- Each lane can produce independently mergeable PRs.
- A bot reviewer (codex, Copilot) reviews pushes automatically.

**When NOT to use.** A single-lane task (dispatch one worker). Work whose
lanes collide constantly on the same files (repartition first, or serialize).
A run short enough to supervise directly — the dashboard and bookkeeper
overhead only pays off across hours.

## 1. Topology — the switchboard

```
ROOT (you, running this skill)
├── lane-<name>   (NAMED lieutenant, one per lane)  ─┐
├── lane-<name>   (NAMED lieutenant)                 ├─ each dispatches
├── lane-<name>   (NAMED lieutenant)                ─┘  UNNAMED workers
└── bookkeeper    (NAMED, owns state.json + dashboard.html)
```

Rules that are not negotiable:

- **Named agents form a flat roster.** A named agent cannot spawn a named
  child. Lieutenants and the bookkeeper are named; workers never are.
- **Worker completions notify ROOT, not the lieutenant that dispatched them.**
  This is a runtime fact. When a worker finishes, ROOT relays the essentials to
  the owning lieutenant via SendMessage and re-engages it. A lieutenant left
  un-relayed will sit idle forever holding finished work.
- **Lieutenants park after dispatching.** A bare idle notification means
  *parked*. It never means "done" and never means "stuck." Do not nudge on an
  idle notification alone.
- **Right-size every worker.** Sonnet for implementation, haiku for mechanical
  work. Never let a worker silently inherit the session model. A dispatch with
  no model and no effort set is the violation, not a neutral default.
- **Two to three plan tasks per worker, maximum.** Workers report in fifteen
  lines or fewer.
- **Worker output still passes the completion gate.** A worker self-gates
  inline on what it can run itself — the package's CI target, its own review
  and simplify pass — but it MUST NOT spawn subagents to do it, because a
  worker cannot reliably await a child (see `orchestrating-subagents`). Any
  gate step needing a separate agent belongs to the **dispatcher**: the worker
  reports DONE, and the *lieutenant* gates the returned work before opening a
  PR. Tests-passed is gate evidence, not the gate.

### Setup sequence

1. **Partition the plan into lanes by file-conflict surface**, not by theme.
   Two lanes that both edit the same module are one lane.
2. **Spawn the bookkeeper first**, with the dashboard template and the state
   schema. It writes the initial `state.json` and `dashboard.html`, and opens
   the page in the browser **exactly once**.
3. **Spawn the lieutenants**, one message each, carrying: the lane's queue, the
   worktree naming convention, the review protocol (§3), the post-merge leg
   (§8), and the instruction to report **reviewed-clean** rather than merging.
4. **Record the roster** — you will need it for the compaction handoff (§7).

Brief every lieutenant with **worktree-absolute paths**. A bare or relative
path makes a worker anchor on the main repo root while its shell sits in a
worktree, and the resulting split-brain is expensive to unwind.

## 2. Message-crossing discipline

This is the single biggest failure mode. Teammate messages deliver at turn
boundaries, so ROOT's orders and a lieutenant's reports routinely cross in
flight. A report that appears to ignore your standing order is almost always
**stale**, not defiant.

**Before acting on any teammate report:**

1. Check whether the report predates your last order to that teammate.
2. Verify current state directly — `gh pr view`, `git log`, `bd show`. Never
   from the report alone.
3. Only then decide whether a nudge is warranted.

**Branch ownership.** When ROOT and a lane might both touch the same branch,
ROOT issues an explicit **OWNERSHIP CHANGE** message (who owns what, effective
immediately) *before* touching anything. If evidence then shows the lane is
already mid-execution — uncommitted edits in its worktree, a push in flight —
ROOT **countermands itself** and hands ownership back. One author per branch at
any moment; a self-countermand is cheap, a mid-air collision is not.

**Turn-handoff texts must be self-contained.** Labels you coined an hour ago
have scrolled out of everyone's view. Open any handoff block with a decoder key
or re-anchor each label inline.

## 3. PR review — delegated, with grind-shaped escalation

**The lane runs the repo's PR-review skill for its own PRs.** Do not
reimplement review-bot mechanics here: verdict signals, re-review dispatch,
clean-pass detection, thread reply-and-resolve, and per-bot quirks all belong
to that skill and change as reviewers change. A grind that carries its own copy
of that protocol will drift from the one the rest of the repo uses.

What this skill governs is only the part the review skill cannot know about —
who runs it, and where a verdict goes:

- **The lane owns the loop for its own PRs**, start to finish. ROOT does not
  run review loops; it has a switchboard to operate.
- **Findings triage** stays the review skill's contract, with one addition: a
  finding whose disposition would change lane scope, cross into another lane's
  files, or need a human ruling is **ESCALATED to ROOT** rather than decided in
  the lane.
- **The lane reports the terminal verdict up** — reviewed-clean, or blocked and
  why. It never merges (§4).

**Stalemate rule.** A re-raise round on **unchanged code** gets one final
disposition round, then the lane stops and puts the PR on the human's docket
via ROOT. Rounds that surface *genuine defects* never trip this rule — six
consecutive rounds of real bugs is the reviewer earning its keep, and the lane
keeps going. Round count alone is not evidence of a loop; unchanged code under
re-raise is.

**Drain sweep.** After about four rounds of real defects in one module, the
lane performs ONE inline proactive audit of all changed code against the defect
*classes* found so far — boundary validation, time semantics, ordering and
selection, subprocess trust — fixes everything in a single commit, and then
lets the reviewer see a drained module. Scope-fence the sweep to files the PR
already changes. This is a throughput tactic, not a review protocol: it exists
because a grind cannot afford four more serial round-trips per module.

## 4. Merge authority

**ROOT merges. Lanes never do.** A lane reports its PR reviewed-clean; the
decision to merge is a switchboard duty, because only ROOT sees the whole board
and the human's standing grants.

**Resolve the repo's merge-authorization policy through `merge-guard` — do not
hardcode one here.** Repositories differ: `never` hands off to the human,
`explicit` (the default) needs an in-session human instruction, and
`rule-based` merges autonomously when its configured rule and eligibility
predicate both hold. `merge-guard` resolves which applies, computes the live
eligibility floor, and hands back the merge command to run — including the
head-commit pinning that stops a push landing between verification and merge.
Assuming a policy is how a grind either merges without authorization in a
`never` repo or stalls every clean PR in a `rule-based` one.

So, per PR: the lane reports reviewed-clean → ROOT invokes `merge-guard` →
ROOT runs the command it hands back, or routes the PR to the human's docket
when the guard says to.

**Verify the lane's claim before invoking the guard.** "Reviewed-clean" is a
report, and §8's standing rule applies to it like any other: confirm it
directly. The guard checks eligibility, not whether your lieutenant was right.

**An honest verdict cannot be manufactured.** If the reviewer will not approve
and you judge its findings unfounded, that is the human's call. Merging around
a reviewer you have decided is wrong is the exact failure this section exists
to prevent.

## 5. The bookkeeper and the dashboard

A named `bookkeeper` teammate owns `state.json` as the single source of truth
and regenerates `dashboard.html` from it on every update. ROOT sends terse
deltas — `UPDATE: …` for progress, `ATTENTION: …` for items that need the
human — and the bookkeeper merges them into state and re-renders.

Ship `dashboard-template.html` and `references/state-schema.md` (both beside
this file) to the bookkeeper at spawn.

**Dashboard contract — all of these are requirements, not preferences:**

- **Light theme only.** No dark mode, no toggle. This is an accessibility
  requirement, not a style choice.
- **Lanes** with per-lane status, work queue, and progress.
- **Lane-level status.** A lane whose queue is complete renders `done` and
  **collapses to a narrow column**, yielding width to lanes still working.
- **Review-round badges.** Any item in review shows the review kind and the
  round number (`codex · round 4`). Round count is the signal that separates a
  reviewer earning its keep from a reviewer looping — surface it.
- **Real PR links.** PR numbers link to the actual pull request. The schema
  carries a `repo` slug so the renderer can derive the URL when an explicit one
  is absent.
- **Merged-PR ledger** and **items-closed ledger**.
- **A red ATTENTION banner** listing items awaiting the human. Hidden when
  empty.
- **A 15-second auto-refresh with a visible on/off toggle**, and a
  **last-generated timestamp** visible on the page.
- **Many lanes may overflow the window width.** That is correct behavior —
  scroll horizontally rather than squeezing lanes into illegibility.

**Open the page in the browser EXACTLY ONCE, when it is first created. Never
on updates.** If the page looks stale to the human, the suspect is the refresh
toggle or a stale tab — the files are ground truth. Check `state.json`'s
timestamp before blaming the bookkeeper.

The rendered dashboard **inlines its state** rather than fetching it, so it
works from a `file://` URL with no server. Do not introduce one. Because the
state is spliced into an inline `<script>` block and carries text from outside
the grind (PR titles, review-comment excerpts), the bookkeeper MUST serialize
it with a JSON serializer and escape every `<` as `\u003c` — the serialization
contract in `references/state-schema.md`. A raw splice is a script-injection
hole.

## 6. Watchers — waking a parked lane

Parked lieutenants cannot self-wake, so when a lane is waiting on review
activity ROOT arms one background poll script per awaited PR, from
`scripts/watch-pr.sh.tmpl`.

**A watcher detects PR *activity*, never a verdict.** It knows nothing about
approval signals, reviewer identity, or clean-pass phrasing — that is the
review skill's job (§3), and duplicating any of it here guarantees drift the
first time a reviewer changes behavior. The watcher answers exactly one
question: *has anything happened on this PR since I armed?*

- **60-second interval, 30-minute timeout.**
- **Launch DIRECTLY via `run_in_background`.** Never nest the watcher inside a
  wrapper command with `&`. The wrapper exits immediately, the completion
  notification fires for the *wrapper*, and the real watcher is orphaned —
  running, unwatched, and silent.
- **Triggers on a count increase** in reviews, review comments, or issue
  comments against baselines sampled at arm time. Counts, not contents.
- **The ring is a DOORBELL.** On a ring, ROOT re-engages the owning lane and
  the lane consults the review skill for the actual verdict. ROOT does not
  interpret PR state itself.
- **A timeout means "no activity," not "no verdict."** Re-arm, or have the lane
  check directly. Reviewers can signal in ways a count-based poll will not see.

## 7. Compaction safety

When the session approaches compaction, ROOT writes a **self-contained**
`ORCHESTRATION-STATE.md` handoff to the grind's working directory, so that a
post-compaction ROOT can resume from that one file. It must contain:

1. **Mission** — what the grind is for, and what is explicitly out of scope.
2. **Pause state**, if the human paused: what not to do, and the resume checklist.
3. **Roster** — every named teammate, its model, and its *exact* position:
   what is done, what is in flight, what comes next.
4. **Merged/closed ledger** — counts and identifiers.
5. **The human's docket** — every decision only they can make, each with your
   recommendation.
6. **Operating protocols in force** — enough that behavior reconstructs from
   the file alone (§2 crossing rules, §4 merge authority, §3 review protocol,
   §6 watcher caveats, the post-merge leg).
7. **Repo quirks and traps** — cwd anomalies, other live sessions to avoid
   colliding with, discovered-work items filed during the run.

Write it **before** you need it. A handoff composed after compaction has
already begun is composed from the wrong context.

## 8. Standing rules from the run

**Verify every factual lane claim cheaply before relying on it.** `bd show`,
`git show`, `gh pr view`. Trust-but-verify caught, in one run: a work item
claimed closed that was still open, a "missing" doc amendment that had actually
been inherited from a prior merge, and a phantom "dropped order" that was
mid-execution.

**Ask the right verification question.** To check "is X documented," inspect
the branch's **final state**, not the PR diff — a rebase can inherit the text,
leaving the diff empty and the claim true.

**Protocol-version collisions.** When two lanes both need a protocol or version
bump, ROOT sequences them explicitly: first-merged takes N, the second rebases
to N+1 and amends the living contract spec's literals. Whether a spec is living
or frozen is settled by **git history** — did prior bumps amend it? — not by a
date in its filename.

**Post-merge leg, per PR** (the lieutenant's job):

1. Leave the worktree first — an agent must not remove the worktree its own
   shell is anchored in. Exit it, then tear down from the main tree.
2. Remove the worktree; `git branch -D` the branch (a squash-merge reads as
   unmerged, so `-d` will refuse).
3. Fast-forward main.
4. Add a tracker note recording the PR number and merge SHA.
5. Close the work item if complete, recording any endorsed descope in the
   close note.
6. Check the parent epic — but **do not auto-close it**.
7. Sync the tracker.

**No agent removes a worktree it occupies — and none removes a worktree
another agent occupies.** Removing an occupied worktree leaves that agent on a
stale inode, where writes go somewhere other than where it thinks. If teardown
cannot be done safely from outside, defer it and record it in the handoff for a
main-tree owner to finish.

**Escalate to the human ONLY for:** merge-authority grants, reviewer
stalemates and malfunctions, and genuine scope forks. Everything else is
decide-in-scope or verify-facts — decide it.

**Workers self-flag deviations** — TDD compromises, fixture fixes, plan drift —
in their reports. Lieutenants verify rather than relitigate. Honesty is never
punished; a worker that hides a compromise costs far more than one that admits it.

## Rationalization table

| Excuse | Reality |
|--------|---------|
| "The lieutenant is idle, so it's stuck — I'll nudge it." | Bare idle means parked. Verify with `gh`/`git` before nudging. |
| "The lane reported reviewed-clean, so I can merge." | A lane report is a claim, not eligibility. Verify it, then let `merge-guard` resolve authority. |
| "The watcher fired, so the reviewer approved." | The watcher is a doorbell. Its filters flake. Re-verify directly. |
| "The findings are clearly unfounded, I'll just merge." | An honest verdict cannot be manufactured. Human docket. |
| "This report contradicts my order — the lane ignored me." | It almost certainly crossed in flight. Check timestamps first. |
| "Six review rounds is obviously a loop, invoke the stalemate rule." | Six rounds of *real defects* is the reviewer working. The rule applies only to re-raises on unchanged code. |
| "I'll wrap the watcher in a helper script with `&`, it's tidier." | The wrapper exits, the notification fires for it, the watcher is orphaned. Launch directly. |
| "I'll write the compaction handoff when compaction is close." | By then you are composing from degraded context. Write it early. |
| "The dashboard looks stale, I'll re-open it in the browser." | Open exactly once. Check `state.json`'s timestamp instead. |
| "Both lanes need the version bump, they'll sort it out." | They will collide. ROOT sequences version bumps explicitly. |

## Red flags — stop and re-verify

- You are about to merge based on something a lane or a watcher told you.
- You are about to nudge a teammate without having run a `gh`/`git`/tracker
  check first.
- You are about to touch a branch a lane might be mid-push on.
- You are about to spawn a named agent *from* a named agent.
- You are dispatching a worker without setting model and effort.
- You are writing review-bot mechanics into this skill instead of delegating
  to the repo's PR-review skill (§3).
- You are about to merge without `merge-guard` resolving the policy (§4).
- You are re-opening the dashboard in a browser.
- Your last three actions were implementation work. You are ROOT — you route,
  verify, and merge. Hand it to a lane.

## Shutdown

1. **Stand down each lane** as its queue empties: confirm the post-merge leg is
   complete for every merged PR, then release the lieutenant.
2. **Reconcile the ledger** — merged PRs and closed items — against the tracker
   directly, not against the dashboard.
3. **Post a final bookkeeper update** so the dashboard's last state is truthful.
4. **Write the final `ORCHESTRATION-STATE.md`**, including everything left on
   the human's docket and every PR still open.
5. **Report to the human**: what merged, what is on their docket and why, and
   what remains parked.
