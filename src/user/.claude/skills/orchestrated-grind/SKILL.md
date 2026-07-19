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
A run short enough to supervise directly — the dashboard and runtime overhead
only pays off across hours.

## 1. Topology and the roster

```
ROOT (you — reasoning model, medium effort)
├── lane-<name>   (NAMED lieutenant, one per lane)  ─┐
├── lane-<name>   (NAMED lieutenant)                 ├─ each dispatches
├── lane-<name>   (NAMED lieutenant)                ─┘  UNNAMED workers
```

ROOT keeps the board in the **event log** (§5), not in a teammate's head:
there is no bookkeeper role. Rules that are not negotiable:

- **Named agents form a flat roster.** A named agent cannot spawn a named
  child. Lieutenants are named; workers never are.
- **Worker completions notify ROOT, not the lieutenant that dispatched them.**
  This is a runtime fact. When a worker finishes, ROOT relays the essentials to
  the owning lieutenant via SendMessage and re-engages it. A lieutenant left
  un-relayed will sit idle forever holding finished work.
- **Lieutenants park after dispatching.** A bare idle notification means
  *parked*. It never means "done" and never means "stuck." Do not nudge on an
  idle notification alone.
- **A bare idle is not an event — it is the absence of one.** Never let an idle
  *itself* be the trigger for anything. Do not reply to it, do not `SendMessage`
  the parked agent about it, do not narrate it to the human, and **do not log
  it as an event**. Idles are the most frequent
  notification in a long run and the least informative; a run that logs them
  buries the real signals in noise and spends ROOT's scarcest resource —
  context — on the fact that nothing happened. Act on *real* signals instead: a
  worker's completion notification, a watcher ring, a lane report, a handoff.
  The one thing a bare idle may trigger is silence.
- **Silence that outlasts the work is a different thing, and it IS a trigger.**
  Ignoring idles is not ignoring lanes. A lane quiet for materially longer than
  its task should take is the "status that has not moved in a suspiciously long
  time" that §8 sends you to verify — key on the overdue-ness, never on the idle
  count. An idle is a turn boundary a *healthy* lieutenant emits; a dead one may
  emit nothing at all, so idles are the one channel a crashed teammate has
  stopped using. Verify with `gh`/`git`/the tracker and the agent's status, not
  by messaging the lane to ask whether it is alive — a message to a terminated
  agent can silently no-op, and §8's "suspect the tooling before the teammate"
  applies before you conclude the agent died at all.
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
   lanes, what each will claim, and the model/effort you intend per lane. Get
   confirmation before spawning anyone. A grind launched on an unconfirmed
   partition is expensive to unwind once four agents are live.
3. **Seed the runtime with `grind create`.** Compose a seed file — the
   `grind_created` payload — from the confirmed partition: `title`, `repo`
   (owner/name), `mission` (goal + explicit out-of-scope), `protocols` (review
   protocol choice, merge-policy resolution, watcher conventions, session
   grants), `config` (staleness and stalemate thresholds), and `lanes[]` — each
   lane's `id`, `name`, `agent`, `model`, `effort`, and its `queue` of items
   (bead ids, titles, and blocker edges). Run `grind create --file <seed> --dir
   <grind-dir>`. The CLI writes the log, folds, and renders `dashboard.html`;
   open that page in the browser **exactly once**, via the platform opener
   named in §5 (`open` / `start` / `xdg-open` — never browser automation). The
   seed's mission and protocols are what make compaction recovery
   self-contained (§7), so compose them for a fresh reader, not for yourself.
4. **Spawn the lieutenants**, one message each, carrying: the lane's queue, the
   worktree naming convention, the review protocol (§3), the post-merge leg
   (§8), the instruction to report **reviewed-clean** rather than merging, and
   the instruction to **request** a watcher from ROOT rather than arm one (§6).
5. **Keep the log authoritative as the run proceeds.** The seed is the roster
   of record; from here every state change is a `grind log` event (§5) —
   `item_started`, `pr_opened`, `review_round` / `review_verdict`,
   `item_merged`, `item_done`, `item_parked`, `lane_handover`, and the rest.
   There is no separate state file to record or reconcile.

Brief every lieutenant with **worktree-absolute paths**. A bare or relative
path makes a worker anchor on the main repo root while its shell sits in a
worktree, and the resulting split-brain is expensive to unwind.

**Resolving the `grind` CLI.** This skill drives the `grind` command. Where
your installer has placed it on PATH, call `grind` directly. Where it is not
yet on PATH, run it from its package with `uv --project <grind-package-dir> run
grind …`, substituting the directory of the grind package. Every `grind …`
invocation below assumes one of these two forms.

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

**The guard's eligibility run IS the verification — do not hand-roll one.**
"Reviewed-clean" is a claim, and §8 says confirm claims before anything
irreversible. Confirm it *with the guard*, not with a hand-assembled sweep of
`gh` calls. `merge-guard` resolves the policy (`resolve_policy.py`) and then
computes the live floor (`check-merge-eligibility.sh`) — CI at the head,
approvals at *that same* head, unresolved threads, sticky requested-changes
verdicts, in-flight and reaction-based review signals, untriaged feedback —
returning `blockers[]`, the `facts` the policy branch reads, and a
**head-pinned merge command**. One gated call subsumes every check ROOT would
otherwise assemble by hand, and unlike a hand-rolled sweep it stays correct as
the blocker set grows.

So verification is **one call, not eight**. ROOT reads the verdict and routes:

| Guard says | ROOT does |
|---|---|
| Eligible, no blockers | Eligibility is established — now take §4's **authorization** branch for the resolved policy. A clean floor is not permission to merge |
| Blockers the lane can clear | The lane's claim was wrong or stale — relay those `blockers[]` to the lane and re-engage it. Do not investigate them yourself |
| Blockers only a human can clear | Straight to the human's docket, with the blocker's `details` quoted. Relaying these to a lane strands the PR — the lane has no way to clear them |
| Error / unknown state | Do not merge. Human's docket |

**Sort the blockers before you route them.** The distinction is whose action
clears the blocker, and it is written into the blocker's own `details` string —
read it rather than guessing from the code. `escalations_pending` ("escalated
thread(s) awaiting a human ruling") and `requested_changes_active` (cleared
only by dismissal or a superseding approval *from the same reviewer*) are
human-clearing by construction; a lane re-engaged on either will spin against a
door it does not hold the key to. Blockers like `unresolved_threads`,
`untriaged_feedback`, or `ci_not_green` are the lane's to clear. A mixed set
splits: the lane's share goes back to the lane, the human's share goes on the
docket, and the PR waits on both.

A hand-rolled pre-check *before* the guard is not extra safety. It is ROOT
spending its scarcest resource to recompute a subset of what the very next
command returns anyway — and recomputing it against a blocker set that is
already out of date.

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

**When a check is a heavy grovel, spend a subagent's context, not ROOT's.**
Reconstructing docket facts with the guard down is exactly the kind of
unavoidable digging that kills a ROOT doing it inline — and so are its
siblings: reading a long CI log, reconciling the ledger against the tracker,
establishing what a reviewer actually saw at some commit. Dispatch an **ad-hoc
ephemeral subagent** — sized to the task rather than to ROOT's tier, briefed to
run the checks and return **only a short verdict block**: each fact with the
command that established it, no transcripts, no diffs, no PR bodies. ROOT pays
a dozen lines of context for work that would otherwise cost it thousands. The
subagent gathers evidence; ROOT still rules on it. This is not delegation of
judgment, it is delegation of *reading*.

**Dispatch it unnamed — this is a deliberate exception to the roster rule, not
an oversight.** §1 and `orchestrating-subagents` have ROOT spawn *named*
teammates, because a teammate is something you address again: relayed to,
re-engaged, rotated, and reconstructed in the compaction handoff (§7). A grovel
subagent is none of those. It answers one question, returns its verdict block,
and terminates — ROOT never sends it a second message, so a name would buy
nothing and cost a roster slot plus a line in every handoff. The roster rule
governs **addressable teammates**; a one-shot that dies on delivery is not one.
Two constraints hold anyway: its completion wakes ROOT (correct — ROOT
dispatched it), and it must spawn nothing itself, since it could not await a
child.

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

## 5. The event log and the dashboard

A grind's entire operational state lives in one append-only **event log**,
managed by the `grind` CLI. ROOT never composes board state in its head and
never hand-edits a state file. The loop is **log → read → act**:

1. **log** — every state change ROOT learns of becomes one `grind log <type>
   --json '<payload>'` call. Worker completions, lane reports, watcher rings,
   PRs opened, review rounds and verdicts, merges, parks, discovered work —
   each is a typed event ROOT appends.
2. **read** — the CLI returns an **emit-back envelope** in the same tool
   result: `applied` (false when the event was illegal from the entity's
   current status), the fold `delta` (the entity's old/new status), any
   `anomaly`, and the currently-true **conditions** (facts with evidence). A
   post-compaction ROOT is re-oriented by its first `log` call.
3. **act** — ROOT acts on the delta and conditions, then logs the next event.

`grind` owns `events.jsonl` (the source of truth), `state.json` (a disposable
cache), and `dashboard.html` (a rendered projection), rewriting the latter two
on every `log`. ROOT reads state with `grind status` (a summary plus
conditions) or `grind status --full` (the entire board); it never parses
`state.json` by hand.

**Single writer.** ROOT is the only process that appends. Lieutenants report to
ROOT as they do today, and ROOT logs — they do not run `grind`.

**Anomalies are surfaced, never corrected in place.** An event that is illegal
from an entity's current status still appends; the fold flags it (`applied:
false`, an ERROR observation, a red banner) and reports it in the envelope's
`anomaly` field so ROOT sees it in the same result. ROOT never edits the log,
`state.json`, or the dashboard to "fix" a mistake — the correction is a
**follow-up event**. Payload validation is a different seam: a malformed
payload is a command error (nothing appended), so re-issue it with the shape
corrected.

**Conditions drive proactive orchestration.** A condition states what is true
and carries its evidence; it never says what to do — the move is ROOT's
judgment:

| Condition | What is true | ROOT's usual move |
|---|---|---|
| `item_unblocked` | a blocked item's last blocker edge just resolved | re-engage its lane to start it |
| `stale_item` / `stale_lane` | no event has referenced it past its threshold | verify per §8 (`gh`/`git`/tracker), then unblock, rotate, or let it be |
| `attention_pending` | unresolved human-docket entries exist | work the docket or surface it to the human |
| `blocked_chain` | an item is blocked on something itself stuck | re-scope or park to break the chain |
| `review_stalemate_risk` | the last N review rounds carry the same head SHA | apply §3's stalemate ladder |
| `lane_complete` / `grind_complete` | a lane's / every lane's queue reached `done` | stand the lane down (§ Shutdown) |

Most conditions are recomputed from state and ride **every** `grind log` and
`grind status`, so a level condition is never missed by not watching the right
call. `item_unblocked` is the exception: it fires **once**, in the envelope of
the `log` whose event resolved the item's final blocker edge, and is never
returned by `grind status` — read it when it rides that envelope.

### The dashboard

`grind` re-renders `dashboard.html` from the log on every write, so it is
always current — a self-contained, light-theme page that works from a
`file://` URL with no server. Its contract (per-lane status and progress,
review-round badges, real PR links, the merged and closed ledgers, the red
ATTENTION banner, the auto-refresh and last-generated timestamp, safe
escaping of outside text) belongs to the renderer, not this skill. ROOT never
edits it.

**Open the page in the browser EXACTLY ONCE, when it is first created. Never
on updates.** If the page looks stale to the human, the suspect is the refresh
toggle or a stale tab — the files are ground truth. Check the page's
last-generated timestamp before assuming the runtime is behind.

**Open it with the OS handler, never with browser automation.** The one
permitted mechanism is the platform's own opener, handing the file to whatever
browser the human already uses:

```bash
# macOS
open "<abs-path>/dashboard.html"
# Linux / BSD
xdg-open "<abs-path>/dashboard.html"
# Windows — the "" is the window-title arg, so the path must follow it
start "" "<abs-path>\dashboard.html"
```

Pick the opener from the actual platform rather than guessing — `Darwin` →
`open`, Windows → `start`, otherwise `xdg-open`. Note that `uname` alone does
not identify native Windows (it is absent outside a POSIX shim), so a bare
`uname` branch would fall through to `xdg-open` and fail there. Always pass an
absolute path, quoted — ROOT's cwd is not the human's.

**Browser-automation MCP servers — Playwright, claude-in-chrome, or any
successor — are prohibited for this.** They are the wrong tool in a way that
is not obvious in the moment, which is exactly why an agent reaches for one
when it happens to be loaded: the page they render lives in an automation-owned
browser the human is not looking at, so the dashboard is "opened" and yet never
seen. They also cost a tool round-trip and tokens for what a one-line shell
command does, hold a session open behind the run, and can block on a dialog. If
the opener is unavailable or fails, **say so and print the path** — a human who
can read the path can open the page themselves. Do not fall back to automation.

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

**A watcher detects activity and labels its shape. It never issues a verdict.**
The doorbell answers *has anything happened since I armed?* — and then, on the
way out, reports a **provisional class** so ROOT is not re-deriving "was that a
clean pass or a fresh pile of findings?" by hand on every single ring. That
manual disambiguation was the highest-frequency cost in the reference run.

The class is a **routing hint**. The authoritative verdict still comes from the
review skill (§3), and the lane still consults it on every ring.

| Class | Means | ROOT's usual move |
|---|---|---|
| `FINDINGS` | Reviewer wants changes — a new `CHANGES_REQUESTED`, any new inline comment, or a findings-marker | Re-engage the lane to work them |
| `CLEAN` | Reviewer appears done and satisfied — a new `APPROVED`, a `+1`/`rocket`/`hooray` from a trusted reviewer, or a clean-marker | Re-engage the lane to confirm and report up |
| `IN-FLIGHT` | Review started but has not concluded — an `eyes` reaction from a trusted reviewer | Usually **re-arm**, do not wake the lane |
| `ACTIVITY` | Something else happened, or classification could not run | Treat as a bare doorbell |

**The precedence contract — written down because ties are the whole problem.**
Signals arrive out of order, land in the same polling window, and contradict
each other. So the class is computed from **PR state at ring time**, never from
the order events arrived in, and resolved by one fixed severity order:

> **`FINDINGS` > `CLEAN` > `IN-FLIGHT` > `ACTIVITY`**

- **`FINDINGS` beats `CLEAN`** on cost asymmetry. A false `CLEAN` can carry an
  unaddressed finding toward a merge; a false `FINDINGS` costs one wasted lane
  check. An approving review *alongside* a new inline comment is `FINDINGS`.
- **`CLEAN` beats `IN-FLIGHT`** because `eyes` is a *start* marker. A review
  that starts and finishes inside one window is finished — `eyes`→`+1` nets to
  `CLEAN`, which is exactly what a fast clean pass looks like.
- **Most severe wins, never most recent.** Several new reviews in one window
  resolve to the most severe among them. This is what makes out-of-order
  delivery harmless — no ordering assumption is made anywhere.
- **Re-arming resets everything.** A fresh watcher samples fresh baselines, so
  no class carries across arms and there is no sticky state to go stale.
- **A class is never authorization.** `CLEAN` is not approval and never
  licenses a merge; only `merge-guard` rules on that (§4).

**Classification can never suppress a ring.** It runs *after* the decision to
ring, once, on the way out — every failure path degrades to `ACTIVITY` and
rings anyway. This is the dumbness rule intact: the poll loop itself is still a
plain count comparison, and a classifier that cannot fail closed cannot ghost
the way the reference run's filter-based monitors did.

**Spot-check on re-arm.** A watcher that has been re-armed two or three times
on the same PR without a terminal class is evidence about the *watcher*, not
the reviewer. Before arming yet again, check the PR directly once — `gh pr
view` — because repeated `IN-FLIGHT` or `ACTIVITY` rings are exactly what a
half-broken poller looks like from the outside. Suspect the tooling before the
teammate (§8); one cheap direct look costs less than a third wasted arm.

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
- **The ring is a DOORBELL with a label on it.** On a ring, ROOT routes on the
  class (table above) and the lane consults the review skill for the actual
  verdict. ROOT does not interpret PR state itself beyond that routing — the
  class exists to save ROOT a manual disambiguation, not to license ROOT to
  start reading reviews.
- **Tell the watcher whose reactions to trust.** Pass the repo's reviewer
  identities as `BOT_REVIEWERS`; leave it empty to trust any actor. An empty
  list is the permissive default on purpose — a watcher that ignores an
  unlisted reviewer's approval reintroduces the blind spot the reaction
  counting exists to close.
- **A timeout means "no activity," not "no verdict."** Re-arm, or have the lane
  check directly. Reviewers can signal in ways a count-based poll will not see —
  including a reaction *replaced* within a single polling window, which nets to
  no change in a count. Closing that particular gap would take per-user reaction
  identities diffed across polls, and a clever watcher that dies silently costs
  far more than a dumb one that occasionally makes a lane wait out its timeout.
  The dumbness rule wins here on purpose; the timeout is the backstop.

### The staleness watchdog

A fully-quiet grind emits nothing — the fold can self-report a stale item or
lane only when something invokes it, so the last mile needs an **external**
probe. ROOT arms one the same way it arms a PR watcher: a dumb background timer
loop that runs `grind check` on an interval and rings on staleness.

`grind check --max-age <dur>` folds the log and exits **1** when the grind is
unfinished, unpaused, and its last event is older than the threshold — a paused
or finished grind is quiet on purpose and reports `stale: false`, exit 0. So
the loop is a plain poll on that exit code:

```bash
while sleep 300; do
  grind check --dir "<grind-dir>" --max-age 30m || echo "GRIND STALE — check the board"
done
```

Keep it dumb for the same reason the PR watcher is dumb: a clever watchdog that
dies silently is indistinguishable from a healthy quiet grind. Launch it
**directly** via `run_in_background`, never nested in a wrapper with `&`. The
ring is a doorbell — ROOT (or the human, for a dead ROOT) reads `grind status`
and interprets. Absence of `grind_finished` + a stale log + not paused = a
stalled or crashed grind. ROOT disarms the probe at `grind finish`.

## 7. Compaction safety

The event log **is** the handoff. Mission, protocols, roster, ledgers, the
human docket, and repo quirks are all written to the log *when context was
fresh* — at setup, or the moment each was hit — so a post-compaction ROOT
reconstructs the run by reading folded state, not a file it composed from
degraded memory. There is nothing to write before you need it.

Recovery is one call: **`grind status --full`**. It returns the entire board,
carrying exactly what a handoff needs:

1. **Mission + out-of-scope** — from the seed's `mission`.
2. **Pause state + resume checklist** — from `grind_paused`, if unresumed.
3. **Roster + exact positions** — the seed's `lanes`, `lane_handover` events,
   and every item's derived status.
4. **Merged + closed ledgers** — the fold's projections of `item_merged` /
   `item_done` and `pr_closed`.
5. **The human's docket** — the attention list, with each `waiting-human`
   item's reason.
6. **Operating protocols in force** — from the seed's `protocols`.
7. **Repo quirks and traps** — the `WARN` and `LESSON` observations.

Read it, and resume. This only works if the log is kept complete as you go:
when a quirk bites, log an `observation` (`WARN`/`LESSON`); when the human must
decide, log `item_waiting_human` or `attention_raised`; when you rotate a
lieutenant, log `lane_handover`. State you never logged is state the handoff
cannot show.

## 8. Standing rules from the run

**Verify at the points that matter — not everywhere.** ROOT cannot re-check
every claim without destroying its own context, and it should not: the lane
owns its gate. Spend verification where being wrong is expensive:

- **Before anything irreversible** — above all, before a merge.
- **When a report and the world disagree** — the board says stuck while the PR
  says otherwise, a claim that contradicts your standing order, a status that
  has not moved in a suspiciously long time.
- **When a claim is load-bearing for a decision you are about to make.**

The checks are cheap and shallow: `gh pr view`, `git log`, a work-item show.
Anything deeper than that goes to an ad-hoc ephemeral subagent (§4), and
anything touching merge eligibility goes to the guard's own gated check (§4) —
never to a sweep ROOT assembles itself.
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
| "I won't nudge, but I'll log the idle so the dashboard is complete." | An idle is the absence of an event. Logging it buries real signals and spends context proving nothing happened. Record state changes, not silence. |
| "I'll just acknowledge the idle so the lane knows I'm here." | The lane is parked and cannot use the reassurance. The reply costs two turns of context and changes nothing. |
| "Five idles in a row means something is wrong." | Five idles is one fact repeated: the lane is parked. Only `gh`/`git`/`bd` can tell you whether that is correct. |
| "I ignore idles, so a crashed lieutenant is invisible to me." | Backwards — a crashed lane emits no idle at all. Silence past the work's expected duration is the signal; check status and artifacts, not the idle stream. |
| "The lane's been quiet far too long — I'll message it and see if it answers." | A terminated agent can no-op the message and look fine. Ask the world (`gh`/`git`/tracker/agent status), not the agent. |
| "The lane reported reviewed-clean, so I can merge." | A lane report is a claim, not eligibility. Invoke `merge-guard`: its eligibility run verifies the claim, and its policy resolution — a separate axis — decides whether merging is authorized at all. Clean is not permission. |
| "I'll sanity-check CI and threads myself before invoking the guard." | The guard computes that and more, on the next command. A pre-check is ROOT's context spent recomputing a stale subset. One gated call, not eight. |
| "This grovel is unavoidable, so I'll just read it all inline." | Unavoidable for *someone*, not for ROOT. Ad-hoc ephemeral subagent, verdict block only. |
| "The watcher fired, so the reviewer approved." | The watcher is a doorbell. Its filters flake. Re-verify directly. |
| "The ring said `class=CLEAN`, so the PR is approved and I can merge." | The class is a provisional routing hint, not a verdict and not authorization. The lane confirms via the review skill; `merge-guard` rules on merging. |
| "Findings and an approval both landed — the approval is newer, so it's clean." | Most severe wins, never most recent. That is `FINDINGS`. |
| "It rang `IN-FLIGHT` again — I'll just re-arm a third time." | Two or three inconclusive arms is evidence about the watcher. Spot-check the PR directly first. |
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
| "I'll write the compaction handoff when compaction is close." | There is nothing to hand-write — the log is the handoff. Recover with `grind status --full`. |
| "The fold flagged my event as an anomaly — I'll fix the log." | Never hand-edit the log, `state.json`, or the dashboard. The correction is a follow-up event. |
| "I already know the board state, I'll skip the status call." | You are events behind after any gap. Read the emit-back envelope or `grind status`; don't reconstruct the board from memory. |
| "The dashboard looks stale, I'll re-open it in the browser." | Open exactly once. `grind` re-renders on every write; check the page's last-generated timestamp instead. |
| "Playwright is already loaded, I'll open the dashboard with it." | It renders into an automation browser the human never sees — opened, yet unseen. The platform opener (§5), or print the path. |
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
- You are re-opening the dashboard in a browser, or reaching for a
  browser-automation tool to open it at all (§5).
- You are about to reply to, narrate, or log a bare idle notification (§1).
- You are about to hand-edit the event log, `state.json`, or the dashboard to
  correct a mistake instead of logging a follow-up event (§5).
- You are composing board state from memory instead of reading the emit-back
  envelope or `grind status` (§5).
- Your last three actions were implementation work. You are ROOT — you manage,
  decide, and unblock. Hand it to a lane.
- You are reading a diff, or re-running a gate a lane already ran.
- You are assembling `gh` calls to verify a PR's mergeability by hand instead
  of letting the guard's eligibility check do it (§4).
- You are reading a long log, ledger, or history inline rather than handing it
  to an ad-hoc ephemeral subagent for a verdict block (§4).
- A lane has been circling the same obstacle for two rounds and you have not
  intervened.
- You are dispatching the review skill from a named lieutenant without having
  settled who awaits its children (§3).
- You spawned lanes without the human confirming the partition.

## Shutdown

1. **Stand down each lane** as its queue empties: confirm the post-merge leg is
   complete for every merged PR, log `lane_standing_down`, then release the
   lieutenant.
2. **Reconcile the ledger** — the fold's merged and closed projections — against
   the tracker directly.
3. **Run `grind finish --summary <text>`.** The final fold and render make the
   dashboard's last state truthful and mark the grind terminal; disarm the
   staleness watchdog probe (§6).
4. **The handoff is the log.** Everything left on the human's docket and every
   still-open PR is already there — surface it from `grind status --full`, do
   not re-transcribe it into a file.
5. **Report to the human**: what merged, what is on their docket and why, and
   what remains parked.
