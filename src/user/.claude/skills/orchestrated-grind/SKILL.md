---
name: orchestrated-grind
description: Use when running a long multi-lane agent grind — several work lanes advancing in parallel under named lieutenant agents, each shipping its own PRs through an autonomous bot-review-and-merge loop. Triggers on "orchestrated grind", "grind plan with lanes", "lieutenant orchestration", "run a multi-lane grind", "overnight grind", "grind the backlog", "run these lanes in parallel overnight", "spin up lanes for this plan", "work this queue while I sleep", or any request to drive many PRs' worth of work across parallel, conflict-partitioned agent lanes with a live status dashboard. Also apply when an in-flight grind stalls, a lane goes quiet, a bot reviewer keeps re-raising the same findings, or a long multi-agent run nears compaction and its orchestration state must survive the handoff.
---

# Orchestrated Grind

## Overview

A **grind** is a long autonomous run in which several work lanes advance in
parallel, each shipping its own pull requests, under one root orchestrator. It
exists to convert a conflict-partitioned plan into merged PRs with minimal
human intervention — the human sets direction, rules on genuine forks, and
sleeps.

**Core principle: ROOT is the accountable manager of the lanes.** It holds each
lieutenant to the standard ROOT would apply if it were running that lane
itself, and it is answerable for the quality of what the lanes produce. Its
standing job is to keep lanes from spinning or getting stuck, to keep them
making progress, and to optimize the run's path through the backlog.

Being the manager does **not** mean doing the work twice:

- ROOT does not implement. It delegates, and it chooses *what* to delegate to.
- ROOT does not re-run a lane's quality gate or re-review its diffs. The lane
  owns its gate; ROOT holds it accountable for having one.
- ROOT does not relitigate a lieutenant's judgment call inside its own lane.
- ROOT **does** verify cheaply before anything irreversible, and whenever a
  report and the world appear to disagree (§8).

**Protect ROOT's context window — it is the scarcest resource in the run.**
A ROOT that reads diffs, re-checks routine reports, or implements anything will
exhaust its context and take the whole grind down with it. Delegation is not
just division of labor; it is how ROOT stays alive long enough to finish.

**Run ROOT on a reasoning model at medium effort.** The judgment ROOT actually
exercises — sizing model and effort for every dispatch, reading whether a lane
is stuck or merely parked, deciding what escalates — needs real reasoning
capacity. Cheap models produce a manager who relays instead of managing.
Workers are sized per task (§1); ROOT is not the place to economize.

This is a **discipline skill**. The rules below were paid for in a real
overnight run of twelve merged PRs; each one exists because its absence cost
something. Follow them as written.

**REQUIRED BACKGROUND:** You MUST understand `orchestrating-subagents` — it
carries the nesting constraint (a subagent cannot await a child it spawns) that
shapes this whole topology.

## When to use

- A plan is partitioned into 2–4 lanes that touch mostly-disjoint files.
- The run is long enough that the human will be away for part of it.
- Each lane can produce independently mergeable PRs.
- A bot reviewer (codex, Copilot) reviews pushes automatically.

**When NOT to use.** A single-lane task (dispatch one worker). Work whose
lanes collide constantly on the same files (repartition first, or serialize).
A run short enough to supervise directly — the dashboard and bookkeeper
overhead only pays off across hours.

## 1. Topology and the roster

```
ROOT (you — reasoning model, medium effort)
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
- **Sizing every dispatch is ROOT's judgment, not a lookup.** ROOT decides the
  model and effort each lane and each worker runs at, from what that task
  actually demands: mechanical work (extraction, file surveys, format
  conversion) goes cheap and low-effort; implementation goes mid-tier;
  judgment-dense work (architecture, adversarial review, final synthesis) goes
  high. Lieutenants apply the same discipline to the workers they dispatch. A
  dispatch that silently inherits the session model is the violation, not a
  neutral default — and a lane quietly running everything at ROOT's tier will
  burn the run's budget without anyone noticing.
- **Two to three plan tasks per worker, maximum.** Workers report in fifteen
  lines or fewer.
- **Keep lieutenants context-conscious.** A lieutenant that runs out of context
  mid-lane strands its queue. ROOT cannot compact a teammate, but it CAN order
  one to drive to a good stopping point — work committed, state reported —
  and then spawn a fresh lieutenant to resume that lane's queue. Do this on
  ROOT's initiative when a lane has been running long, not after the lane
  starts degrading. Lane handover is routine maintenance, not failure.
- **Worker output still passes the completion gate.** A worker self-gates
  inline on what it can run itself — the package's CI target, its own review
  and simplify pass — but it MUST NOT spawn subagents to do it, because a
  worker cannot reliably await a child (see `orchestrating-subagents`). Any
  gate step needing a separate agent belongs to the **dispatcher**: the worker
  reports DONE, and the *lieutenant* gates the returned work before opening a
  PR. Tests-passed is gate evidence, not the gate.

### Setup sequence

1. **Partition the plan into lanes by file-conflict surface**, not by theme.
   Two lanes that both edit the same module are one lane. Partition to minimize
   merge conflict, and prefer small PRs all the way through every lane's plan —
   speed comes from many small landings, never from relaxing quality.
2. **Propose the partition and roster to the human, and wait.** Present the
   lanes, what each will claim, the model/effort you intend per lane, and the
   bookkeeper. Get confirmation before spawning anyone. A grind launched on an
   unconfirmed partition is expensive to unwind once four agents are live.
3. **Spawn the bookkeeper first**, with the dashboard template and the state
   schema. It writes the initial `state.json` and `dashboard.html`, and opens
   the page in the browser **exactly once**.
4. **Spawn the lieutenants**, one message each, carrying: the lane's queue, the
   worktree naming convention, the review protocol (§3), the post-merge leg
   (§8), the instruction to report **reviewed-clean** rather than merging, and
   the instruction to **request** a watcher from ROOT rather than arm one (§6).
5. **Record the roster** — you will need it for the compaction handoff (§7).

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

- **The lane owns the loop for its own PRs**, and drives it to a verdict.
- **Whoever runs the review skill must be able to await the agents it
  dispatches.** A PR-review skill that fixes findings by dispatching a subagent
  per finding creates children whose completions wake ROOT, not the lieutenant
  that spawned them — so a lieutenant running such a skill parks after the
  first fix and never resumes. Resolve this before the grind starts, not
  mid-review: either ROOT runs the review skill for the lane and relays results
  back, or ROOT relays each child completion to the lieutenant and re-engages
  it. Whichever you choose, brief the lieutenants on it explicitly. This is the
  nesting constraint from `orchestrating-subagents` applied to review work, and
  it is the single easiest place in a grind to deadlock a lane.
- **Findings triage** stays the review skill's contract, with one addition: a
  finding whose disposition would change lane scope, cross into another lane's
  files, or need a human ruling is **ESCALATED to ROOT** rather than decided in
  the lane.
- **The lane reports the terminal verdict up** — reviewed-clean, or blocked and
  why. It never merges (§4).
- **If the repo has no usable review skill, ROOT supplies one inline.** The repo
  may have none, or its skill may be undeployed or banned for this run. Settle
  that at setup, not mid-review: ROOT briefs every lane with an explicit verdict
  protocol — how a re-review is requested, what counts as a clean pass, how
  threads get replied to and resolved, and what the terminal verdict looks like.
  A lane improvising its own is how two lanes end up with two different
  definitions of "reviewed-clean," which §4 then merges on.

**Stalemate rule.** A re-raise round on **unchanged code** gets one final
disposition round, then the **do-not-relitigate round** below, and only then
does the lane stop and put the PR on the human's docket via ROOT. Round count
alone is not evidence of a loop; unchanged code under re-raise is. A reviewer
finding *genuine defects* round after round is earning its keep, not looping.

**The do-not-relitigate round — try this before the human docket.** Before
escalating a stalemate, spend **one** more review round that hands the reviewer
the settled dispositions and their evidence, via the review skill's re-review
path. A stalemate earns one evidence-bearing round before it costs the human a
decision.

- Spend it even when you expect the reviewer to hold. In the reference run one
  such round suppressed the settled noise *and* surfaced a genuine remaining
  bug — the outcome the plain escalation path throws away.
- Once. If the reviewer re-raises settled threads *after* being handed the
  dispositions, that is a malfunction (below) or a genuine fork — escalate.

**Reviewer malfunction — diagnose before you escalate.** A reviewer that
re-flags something already fixed is not stalemated with you; it is reviewing the
wrong state. Distinguish the two, because they have different exits:

1. **Verify the fix exists at the commit the reviewer claims it reviewed** —
   `git show <sha>:<path>`. Not at HEAD, and not in the PR diff: if the reviewer
   is reading a stale head, HEAD proves nothing about what it saw. A path that
   is **absent** at that commit is not yet an answer — deleting or renaming the
   file can *be* the fix. On a missing path, check the commit's diff or tree
   before concluding anything, and read step 4 as applying only once you have
   confirmed the flagged code genuinely survives.
2. If the fix **is** there, hand the reviewer that evidence through the review
   skill's reply path — one evidence-forward nudge, not an argument. A
   do-not-relitigate round already spent **is** that nudge; do not spend a
   second one.
3. If the reviewer re-flags the **same** finding a second time against that same
   evidence, stop. It is malfunctioning, further rounds are free tokens spent on
   noise, and the PR goes to ROOT for the human's docket labelled as a
   *malfunction* — which is a different ask of the human than a genuine fork.
4. If the fix is **not** there, the reviewer is right and you have a real
   finding. This is the branch that makes step 1 non-optional.

**When a round cap and a productive reviewer collide, ROOT rules.** A PR-review
skill may cap re-review rounds and escalate past the cap — a sound default
against infinite loops, but it fires on round count, which cannot distinguish a
stuck reviewer from a thorough one. Do not override the cap inside the lane and
do not promise the lane will keep going regardless: the lane escalates to ROOT,
and ROOT — which can see the defect history — decides whether to authorize
further rounds or to put the PR on the human's docket. This is exactly the
judgment call a manager exists to make.

**Drain sweep.** After about four rounds of real defects in one module, the
lane performs ONE inline proactive audit of all changed code against the defect
*classes* found so far — boundary validation, time semantics, ordering and
selection, subprocess trust — fixes everything in a single commit, and then
lets the reviewer see a drained module. Scope-fence the sweep to files the PR
already changes. This is a throughput tactic, not a review protocol: it exists
because a grind cannot afford four more serial round-trips per module.

## 4. Merge authority

**ROOT merges. Lanes never do.** A lane reports its PR reviewed-clean; the
decision to merge is ROOT's, because only ROOT sees the whole board
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

**When the guard itself is broken, the floor does not move.** A grind sometimes
runs with `merge-guard` structurally unavailable — misconfigured, mid-refactor,
missing a credential — and the human grants merge authority for the session
directly instead. That grant replaces the *authorization* the guard would have
resolved; it does not replace the *eligibility* it would have computed.

**Run the canonical eligibility check — do not reconstruct one.** The guard is
more than its policy resolver, so if its eligibility script still runs, run it
and use its verdict even when the authorization half is dead.

**When nothing of the guard runs, ROOT does not merge.** The PR goes to the
human's docket, session grant or not. This is not caution for its own sake: the
canonical check's blocker set is larger than anyone remembers and it *grows* —
requested-changes verdicts, in-flight reviews, pending escalations, untriaged
feedback, blockers contributed by other tooling in the repo. Any list written
here is a snapshot that silently rots, and a hand-rolled floor that looks
complete is more dangerous than an honest handoff, because it authorizes a
merge on a check nobody maintains. So the floor is not reproduced here.

What ROOT owes the human is a **useful docket entry**, not a verdict. Gather
what you can establish cheaply — CI state at the head you would merge, whether
an approval exists at *that same* head, unresolved thread count, and whether any
reviewer has an active requested-changes verdict (sticky and not head-scoped: a
push does not clear it, and another reviewer's approval does not override it).
Report those as **facts you checked, not as clearance**, and name the guard as
inoperable so the human knows the usual gate did not run.

The human then rules on that PR. Their ruling supersedes the floor — merging
with the guard down is a call they are allowed to make and ROOT is not. If the
ruling is to merge, **pin the merge to the head that was checked**, so a lane
pushing in between fails the merge rather than silently retargeting it; that
race is exactly what the guard's head-pinned command exists to close. Record the
ruling with
the merge. Likewise record in the handoff (§7) that the guard was bypassed and
on what authority — a grant nobody wrote down is indistinguishable, later, from
a lane that merged on its own initiative.

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

**ROOT arms every watcher. A lane NEVER arms its own.** This is the same
structural fact stated from the other side, and it is worth stating explicitly
because the inverse looks so reasonable: the lane owns the PR, so surely it
should watch it. It cannot. A lane that arms its own watcher then parks, and a
parked agent cannot hear its own background task complete — the completion wakes
ROOT, which has no idea what the ring was for. The watcher runs, rings into the
void, and the lane looks stuck when nothing is wrong with it. In the reference
run one lane did this three times and every "failure" was this and only this.
Brief lanes to *request* a watcher from ROOT, never to launch one.

**A watcher detects PR *activity*, never a verdict.** It knows nothing about
approval signals, reviewer identity, or clean-pass phrasing — that is the
review skill's job (§3), and duplicating any of it here guarantees drift the
first time a reviewer changes behavior. The watcher answers exactly one
question: *has anything happened on this PR since I armed?*

- **Keep the watcher dumb.** A plain timer loop comparing counts beats a clever
  filter on commit metadata or author fields: clever watchers fail silently and
  a silent watcher is indistinguishable from a quiet PR. In the reference run a
  filter-based monitor ghosted twice before anyone noticed, and both times the
  lane looked stuck when it was the monitor that had died.
- **60-second interval, 30-minute timeout.**
- **Launch DIRECTLY via `run_in_background`.** Never nest the watcher inside a
  wrapper command with `&`. The wrapper exits immediately, the completion
  notification fires for the *wrapper*, and the real watcher is orphaned —
  running, unwatched, and silent.
- **Triggers on a count increase** in reviews, review comments, issue comments,
  or **reactions** against baselines sampled at arm time. Counts, not contents.
- **Count reactions too, including nested ones.** A reviewer can signal entirely
  through a reaction — in the reference run one approval arrived as a lone
  thumbs-up, with no review object and no comment, and a watcher blind to
  reactions slept through it to timeout. Count reactions on the PR body *and* on
  each individual comment and review: a reaction on an existing comment moves
  none of the other counts, so a body-only reaction check has the same blind
  spot in a narrower form. Reactions are a count like any other, so this costs
  the doorbell nothing and keeps it dumb.
- **The ring is a DOORBELL.** On a ring, ROOT re-engages the owning lane and
  the lane consults the review skill for the actual verdict. ROOT does not
  interpret PR state itself.
- **A timeout means "no activity," not "no verdict."** Re-arm, or have the lane
  check directly. Reviewers can signal in ways a count-based poll will not see —
  including a reaction *replaced* within a single polling window, which nets to
  no change in a count. Closing that particular gap would take per-user reaction
  identities diffed across polls, and a clever watcher that dies silently costs
  far more than a dumb one that occasionally makes a lane wait out its timeout.
  The dumbness rule wins here on purpose; the timeout is the backstop.

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

**Verify at the points that matter — not everywhere.** ROOT cannot re-check
every claim without destroying its own context, and it should not: the lane
owns its gate. Spend verification where being wrong is expensive:

- **Before anything irreversible** — above all, before a merge.
- **When a report and the world disagree** — a dashboard that says stuck while
  the PR says otherwise, a claim that contradicts your standing order, a status
  that has not moved in a suspiciously long time.
- **When a claim is load-bearing for a decision you are about to make.**

The checks are cheap and shallow: `gh pr view`, `git log`, a work-item show.
Trust-but-verify at these points caught, in one run: a work item claimed closed
that was still open, a "missing" doc amendment actually inherited from a prior
merge, and a phantom "dropped order" that was mid-execution. Routine progress
reports in between do not need auditing — that is what holding a lieutenant
accountable for its own gate buys you.

**Suspect the tooling before the teammate.** When a lane looks stuck, the
culprit is often a poller or watcher that silently died, not an agent that
stopped working. Check the mechanism, then the agent.

**Do not let the run spin.** Trust in the lanes is not permission to burn
tokens circling a problem no agent can solve. When a lane has gone two rounds
without progress on the same obstacle, ROOT intervenes: change the approach,
re-scope the item, park it, or escalate. Unbounded retrying is the most
expensive failure mode in a long run, and the least visible while it happens.

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

**Escalate to the human ONLY for:** merge-authority grants, genuine scope
forks, and reviewer stalemates or malfunctions that have run out §3's ladder —
a stalemate after its do-not-relitigate round, a malfunction after its one
evidence-forward nudge. The two are different diagnoses with different exits,
not steps in one chain: a confirmed malfunction escalates on its own path
without first spending the stalemate rounds. Everything else is
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
| "Six review rounds is obviously a loop, invoke the stalemate rule." | Rounds of *real defects* are the reviewer working. The rule applies only to re-raises on unchanged code. |
| "Stalemate confirmed — straight to the human's docket." | One do-not-relitigate round first: re-review with every settled disposition and its evidence. It broke four of four in the reference run. |
| "The reviewer keeps re-flagging a fix I know I made — it's stalemated." | Check `git show <sha>:<file>` at the commit it claims it reviewed. A reviewer reading a stale head is malfunctioning, which is a different escalation. |
| "I'll have the lane watch its own PR — it owns it." | A parked lane cannot hear its own watcher ring; the ring wakes ROOT. ROOT owns every watcher. |
| "The watcher's been quiet, so nothing has happened." | Only if it counts reactions. A lone thumbs-up approval is invisible to a reviews-and-comments watcher. |
| "merge-guard is broken and I have a session grant, so I can merge." | The grant replaces authorization, not eligibility. Run the canonical eligibility check if any of it still runs; if none of it does, ROOT does not merge — the PR goes to the human's docket. |
| "I checked CI, approval, and threads myself — that's the floor." | It isn't. The canonical blocker set is larger than anyone remembers and grows over time. Those are facts for the docket entry, not clearance to merge. |
| "The lane says it is fine, and re-checking would cost me context." | Verify anyway before anything irreversible, and whenever report and world disagree. Everywhere else, trust the lane. |
| "I have context to spare, I will just review the diff myself." | You are the manager, not the reviewer. Re-running the lane's gate spends the one resource the run cannot replace. |
| "The lane has retried this four times, it will get there." | Two rounds without progress is ROOT's cue to intervene. Unbounded retrying is the most expensive failure mode in a long run. |
| "This lieutenant has been going for hours and is still answering." | Rotate it at a good stopping point before it degrades, not after. Lane handover is maintenance, not failure. |
| "Sonnet is fine for everything, it saves me deciding." | Sizing each dispatch is your judgment to exercise. A lane running everything at one tier burns budget or botches judgment work. |
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
- You are about to merge without `merge-guard` resolving the policy (§4) — or,
  where the guard is wholly inoperable, at all — that PR belongs on the human's
  docket (§4).
- You are sending a PR to the human's docket as a stalemate without having run
  the do-not-relitigate round (§3).
- You are treating a re-flagged fix as a stalemate without having checked the
  commit the reviewer claims it reviewed (§3).
- A lane is arming its own watcher (§6).
- You are re-opening the dashboard in a browser.
- Your last three actions were implementation work. You are ROOT — you manage,
  decide, and unblock. Hand it to a lane.
- You are reading a diff, or re-running a gate a lane already ran.
- A lane has been circling the same obstacle for two rounds and you have not
  intervened.
- You are dispatching the review skill from a named lieutenant without having
  settled who awaits its children (§3).
- You spawned lanes without the human confirming the partition.

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
