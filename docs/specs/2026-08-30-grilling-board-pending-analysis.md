# Grilling board: pending analysis, impact tasks and the frontier as the lock

**Date:** 2026-08-30
**Status:** Draft, settled by a grilling session. Amends
`docs/specs/2026-08-18-grilling-ui-v1.md` (the board) and
`docs/specs/2026-08-23-grill-master-role.md` (the grill-master's turn) where each names
what a map turn is and when it runs; changes no code by itself. The terminal review phase
the session also settled is the child spec
`docs/specs/2026-08-30-grilling-board-terminal-review.md`.
**Source:** the 2026-08-27 `grill-with-ui` session *Grilling board: pending analysis, locks
and rounds* (thirteen of thirteen decisions settled, five of them added by the grill-master
during the session) and the 2026-08-25 expert-turn bake-off, both preserved in the
grilling corpus. Tracker: `agents-config-9k9.315`.

## Problem statement

The human answers a decision whose option puts two other decisions in question. The board
sends the expert to rule on them, and for the next minute — 111 seconds in the session that
produced this spec — the board stays fully answerable. The human, seeing nothing waiting,
answers the very decisions the ruling is about to revise. When the ruling lands it
retitles one of them, adds a new one, and marks four more as read-worthy; the human learns
this only from unread marks, and cannot tell what moved from what merely stood.

The `grilling` skill avoids this with stop-the-world rounds: the agent reassesses the whole
map between rounds and keeps an implicit set of acceptance criteria. The human has declined
rounds for the board. What the board lacks is the skill's own frontier rule — *a running
lookup is an unsettled prerequisite, so only the questions downstream of it wait* — applied
to an agent's judgment rather than a fact lookup.

## Solution

A decision whose impact is being weighed is **pending**: off the frontier, not answerable,
named on the board together with what it waits on. Weighing is a **task** keyed by its
target decision over the current upstream state, at most one live per target, started the
moment a node goes pending, superseded rather than queued when upstream moves again. The
expert at medium effort takes every such task. Its result may change its own target
directly; anything wider is a proposal. Where an option's impact was pre-ruled one hop out
before the human clicked, the happy path costs no wait at all. A task that fails holds the
lock as a named blocker with a retry, and a whole-map doctor stays available beside it.

## User stories

1. As the human, I want a decision that a ruling in flight may move to be visibly waiting and unanswerable, so that I never answer on structure about to change.
2. As the human, I want every decision *not* downstream of a ruling in flight to stay answerable, so that one slow judgment does not stop the session.
3. As the human, I want the board to name what a pending node waits on — which gesture, which seat, since when — so that a wait is never a mystery.
4. As the human, I want an option carrying no mark to unlock its downstream nodes immediately, so that the paths the map author judged safe cost nothing.
5. As the human, I want any note or free-text answer I write to be judged before its downstream nodes open, so that my own words are weighed and not trusted blindly.
6. As the human, I want the expert, not a cheap seat, to weigh impact, so that the ruling that unlocks a node is the one that reads the board.
7. As the human, I want the result of a task to arrive as the target's new shape, so that the node I am about to answer is already correct.
8. As the human, I want anything a task proposes beyond its own target — a new decision, a neighbour revised — to reach my inbox as a proposal showing before and after, so that nothing rewrites the map without my applying it.
9. As the human, I want a task that errors or times out to show as a named failure on the node with a retry control, so that a dead seat never parks a decision silently.
10. As the human, I want the map doctor available at all times to look at the whole map, so that a broken or inconsistent board can be rescued without me finding the break.
11. As the human, I want the likely rulings on a node's marked neighbours computed before I click, so that the wait is paid in the background.
12. As the human, I want a pre-ruling that the board moved under to be recomputed rather than trusted, so that background work never lands stale.
13. As the human, I want two results that disagree to be merged into one proposal I can read, so that I adjudicate a conflict once rather than reconcile two.
14. As the human, I want a `stands` ruling justified but never flagged as needing my attention, so that unread marks mean something moved.
15. As a map author, I want my `puts_in_question` marks to be the trigger for judgment, so that the marks I write are the contract the board enforces.
16. As the orchestrator relaying a session, I want the log to carry every task, its target, its seat and its outcome, so that a session can be replayed and its waits measured.

## The decisions, as settled

Each is a settled decision of the source session, restated as the board's rule. The ledger
ids are what slices and criteria cite.

**PND-D1 — Trigger: a task per target, started when the node goes pending; the frontier is the lock.** A pending analysis is an unsettled prerequisite. A task is keyed by its target decision and computed over everything settled upstream at the moment it runs; at most one task per target is live; a later upstream answer supersedes the live task for that target rather than queuing behind it. The first race the session named — A then B, both feeding C — closes by construction. *(session d1(a))*

**PND-D2 — Impact: the mark, plus any human note or free answer; an absent mark means safe.** A node becomes pending when the human takes an option whose `puts_in_question` names it and it is still live, or when the human's answer on an upstream decision carries a note or is free text. An option with no mark unlocks its downstream nodes immediately. The map author's omission is trusted; the cost is accepted. *(session d2(a))*

**PND-D3 — Output: the target changes directly; anything wider is a proposal.** A task's result may revise or invalidate its own target, landing without the human's apply, and the node unlocks in its new shape. An `add-node`, a change to any other decision, or a conflict with a settled answer is a proposal to the inbox. This amends the board's rule that nothing an agent says rewrites the board on its own: the exception is a task's own target, and the history record names the task that changed it. *(session d3(b), taken over the seat's objection)*

**PND-D4 — Seat: the expert at medium effort, for every impact task and for any custom text.** Measured on one turn: cheap seats 7–27s and shallow, the expert 45–61s at every effort and the only one that read the board — at medium already. Custom text on an answer is judged by the expert whether or not the option was marked. *(session d4, free text)*

**PND-D5 — Lock: hard, no release.** A pending node cannot be answered until its task returns. The board names the node, the gesture it waits on, the seat, and how long. View operations stay open. *(session d5(a), the decision as the expert revised it)*

**PND-D6 — Pre-compute: one hop, descendants on a doubt.** For every offered decision, each option's impact on its marked neighbours is pre-ruled in the background. Settling A pre-computes A's opened children; a child opening pre-computes its own. A pre-ruling is stale when its basis sequence is older than the last mutation touching any of its targets, and is recomputed. When a taken option puts B in doubt, B's re-evaluation locks B and covers B's descendant hops as both re-evaluation and pre-compute. *(session d6, free text)*

**PND-D8 — Conflicts: an expert conflict-resolution turn merges disagreeing results into one proposal.** Two results that were independent when started and conflict when combined — two tasks each proposing a new node for the same gap, a pre-ruling correcting an answered node — are merged by one expert turn into a single proposal, with history naming both sources. *(session d8(c))*

**PND-D9 — Failure: holds the lock as a named blocker.** A task that errors, is refused by the appender, or times out leaves its node pending with a failure shown on the node — what failed, on which seat, when — and a manual retry. Nothing unlocks on inaction. *(session d9(b), free text)*

**PND-D11 — Recovery: node retry and the map doctor are separate.** Node retry asks the grill-master to reassess that node and its descendants over the current tree. The map doctor, always available at the top of the board, asks whether anything on the whole map is broken, inconsistent or in need of adjustment. Either may propose structural change. *(session d11, free text)*

**PND-D13 — Doctor contract: subtree retry, whole-map doctor, all structural results human-applied.** Retry is scoped to the failed node's subtree; the doctor to the map; neither applies a structural change itself. *(session d13(a))*

**PND-D14 — A `stands` is justified, never attention-required.** A `stands` ruling still mints its targeted informational with its why; the informational arrives read, and the board shows it only behind the decision's read-notice toggle. *(the session's UI ruling, recorded on `agents-config-9k9.311`)*

The session's d7, d10 and d12 — the terminal round, the review phase and per-entry dispositions — are the child spec's TRV-D1 to TRV-D3.

## Implementation decisions

**The task is a log fact.** A task is recorded on the session log as status entries on the map channel carrying a task id, its target decision id, the gesture's sequence it was started for, and the seat; a task ends with a `replied`, `error` or `superseded` phase carrying the same id. The projector folds these into a per-decision `pending` field on the second image — the task id, what it waits on, the seat, and the start time — and the frontier excludes any decision with a live task. Nothing is kept in process memory that a restarted backend cannot recover from the log; a live task whose process died is an errored task after restart, not a lock.

**Classing extends the judgment set, it does not replace it.** The existing pre-dispatch classing decides the seat for a gesture; PND-D2 extends the obligation it reads so that an upstream answer carrying a note or free text owes a task on each downstream decision it opens, and PND-D4 seats every such task on the expert at medium effort regardless of the channel's configured first rung. The distrust counter and the human's transfer control are untouched.

**Supersession, not a queue.** When a gesture would start a task for a target that already has one live, the live task is marked superseded and its result, if it later arrives, is dropped with a history line saying so. One live task per target is an invariant the lane holds under its append lock.

**Auto-apply is scoped by target, enforced by the projector.** A task result's sub-updates targeting the task's own decision fold directly; every other sub-update takes the existing proposal path. The history record carries `proposed_by` naming the task, so a node the human never touched still says who changed it. A `revise` that supplies no structural field is refused at the document gate (the defect `agents-config-9k9.310`), because under this rule an empty revise would unlock a node claiming to have changed it.

**Pre-rulings are cached task results.** A pre-ruling is a task run ahead of the gesture, recorded as the same log facts with a `pre` marker and the option it was computed for; taking that option with no note consumes the pre-ruling instead of starting a task, and the board unlocks at once. Staleness is a comparison of the pre-ruling's basis sequence against the last mutation touching its targets; a stale pre-ruling is recomputed in the background and never consumed.

**Failure is board-visible.** The failure phase on the map channel folds into the pending field as a named blocker with a retry control; this is the remedy for the two defects that say an unreachable seat and an appender refusal leave no trace (`agents-config-9k9.309`, `agents-config-9k9.306`), delivered here rather than separately.

**The conflict turn is a judgment-class turn.** Two results targeting the same gap raise a conflict; the lane composes one expert turn over both, whose document is a single proposal carrying both sources in its why.

**Seams.** The highest existing seam is the end-to-end harness: scripted seats and a headless browser driving the real launch path, asserting on log bytes and rendered facts. Every criterion below is expressible there. Beneath it, the unit seams already in place — the lane's accept and classing, the projector's fold, the document gate — carry the same facts. One new seam: the pending field on the second image, which the page reads and the harness asserts. No new process, service or transport.

## Testing decisions

A good test drives a gesture through the board and reads the log and the page, never the lane's internals. The end-to-end harness's scripted seats can hold a task open indefinitely, fail it on cue, or answer a pre-computed option, which is what makes lock, supersession, failure and pre-compute testable deterministically; the unit suite pins the same invariants at the lane and projector. Prior art: the harness's distrust and codex-chain scenarios, and the unit suite's classing tests.

## Acceptance criteria

Each names what a red test asserts, on the log's bytes and, where the fact is rendered, on the page.

- **PND-A1** Taking an option whose mark names a live decision records a task on the map channel naming that decision as its target; the second image lists the decision as pending with the task's gesture, seat and start; the frontier excludes it; the page offers no answer control on it while every decision not downstream stays answerable. An option with no mark records no task and leaves every downstream node on the frontier. Inverse: a mark naming a dead or absent decision records nothing. Restart: a fresh backend over the same directory shows the same pending field, and a task whose process did not survive shows as failed, not live.
- **PND-A2** An answer carrying a note or free text records a task on each downstream decision it opens, seated on the expert at medium effort regardless of the map's configured first-rung seat; the same answer with no note and an unmarked option records none.
- **PND-A3** A second gesture whose task targets a decision already pending marks the live task superseded and starts one over the new upstream state; a result arriving for the superseded task is dropped with a history line, never folded; at no sequence do two live tasks share a target. Concurrent: two gestures in one batch targeting the same decision yield exactly one live task.
- **PND-A4** A task result whose sub-update targets its own decision folds directly with history naming the task in `proposed_by`, and the decision returns to the frontier in its new shape; a sub-update targeting any other decision, or adding a node, lands in the inbox as a proposal whose row shows the change before and after. A `revise` supplying no structural field is refused at the document gate and never reaches the inbox.
- **PND-A5** A task that errors, is refused, or times out leaves its decision pending with a failure on the node naming the cause, the seat and the time, and a retry control; pressing retry records a new task scoped to that decision's subtree; nothing unlocks without a result. Idempotent: pressing retry while a retry is live starts nothing.
- **PND-A6** With a pre-ruling recorded for an option, taking that option with no note consumes it — no task starts, the downstream decisions unlock at once, and history credits the pre-ruling; a mutation touching any of its targets after its basis makes it stale, and a stale pre-ruling is never consumed and is recomputed. Settling a decision starts pre-rulings for the options of each decision it opens, and for no deeper decision until its parent opens it.
- **PND-A7** Two results proposing a node for the same gap, or a pre-ruling correcting an answered decision, raise one expert conflict turn whose document is a single proposal carrying both sources; the two originals never reach the inbox separately.
- **PND-A8** The map doctor's document may propose structural change to any decision and applies none; a node retry's document may propose change only within the failed node's subtree, and a sub-update outside it is refused.
- **PND-A9** A `stands` ruling's targeted informational is recorded read: it raises no unread mark on the decision and is shown only behind the decision's read-notice toggle, verified in a browser.
- **PND-A10** The board legend in every thread-agent brief states the pending state and the task that changed a decision, so a thread agent asked why a node is waiting or moved answers from the record.

## Ordered slice list

Each slice is the smallest independently mergeable unit; each cites what discharges it.

- **S1 — The task on the log and the frontier as the lock** (PND-D1, PND-D5; PND-A1, PND-A3): task status entries, the projector's pending field, frontier exclusion, supersession under the append lock, the page's waiting state naming what it waits on, restart recovery.
- **S2 — What goes pending, and on which seat** (PND-D2, PND-D4; PND-A2): the classing extension for notes and free text, expert-at-medium seating for every task.
- **S3 — What a result may touch** (PND-D3; PND-A4): target auto-apply with `proposed_by` naming the task, wider changes as proposals with before/after rows, the empty-revise refusal (`agents-config-9k9.310`).
- **S4 — Failure as a named blocker, and retry** (PND-D9, PND-D11, PND-D13; PND-A5, PND-A8): the failure phase folded into the pending field, the retry control scoped to the subtree, the doctor's whole-map contract; discharges `agents-config-9k9.306` and `agents-config-9k9.309`.
- **S5 — Pre-rulings** (PND-D6; PND-A6): background tasks per offered option, consumption on the click, staleness by basis sequence, descendant re-evaluation on a doubt.
- **S6 — The conflict turn** (PND-D8; PND-A7).
- **S7 — Notices that need no attention, and the legend** (PND-D14; PND-A9, PND-A10): `stands` arrives read; the thread-agent legend names the pending state and task provenance. Folds the notice half of `agents-config-9k9.311`.

The child spec's slices follow S3 and S4.

## Out of scope

- Stop-the-world rounds on the board; the child spec's terminal round is the one round the board owes.
- A soft lock or any release from a pending node (session d5: declined).
- Pre-ruling beyond one hop from an offered decision, and whole-map pre-ruling at creation.
- The board's styling rulings (`agents-config-9k9.312`) and the end-session guard (`agents-config-9k9.313`), which stand on their own.
- The seat configuration and the Codex driver, which stay whatever GUI-D46's replay observation says (`agents-config-9k9.307`).

## Further notes

The bake-off behind PND-D4 is n=1: one timed-out expert turn replayed through twelve seat
configurations. Its conclusion — that effort does not move judgment and the expert model
does — is what the seat choice rests on, and a second session's replay is the cheap way to
check it. The session that produced this spec ran the first-rung seat on every free-text
answer, which is exactly the case PND-D2 and PND-D4 remove; the empty revises it produced
(`agents-config-9k9.310`) are that seat doing the expert's job in the wrong vocabulary.
