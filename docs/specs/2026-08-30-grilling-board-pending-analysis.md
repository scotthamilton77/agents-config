# Grilling board: impact tasks, waiting decisions and the frontier as the lock

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

A decision whose impact is being weighed is **waiting**: off the frontier, not answerable,
named on the board together with what it waits on. Weighing is an **impact task** keyed by
its target decision over the current upstream state, at most one live per target, started
the moment a node goes waiting, superseded rather than queued when upstream moves again.
The expert at medium effort takes every such task, under a brief whose `Backpressure:`
paragraph tells it not to relitigate the map author's structure absent a significant
reason. Its result may change
its own target directly; anything wider is a proposal, which the human's own board
preference may then apply for them where it touches nothing they have answered. Where an option's impact was pre-ruled one hop out before the human clicked, the happy
path costs no wait at all. An impact task that fails holds the lock as a named blocker with
a retry, and a whole-map doctor stays available beside it.

## User stories

1. As the human, I want a decision that a ruling in flight may move to be visibly waiting and unanswerable, so that I never answer on structure about to change.
2. As the human, I want every decision *not* downstream of a ruling in flight to stay answerable, so that one slow judgment does not stop the session.
3. As the human, I want the board to name what a waiting decision waits on — which gesture, which seat, since when — so that a wait is never a mystery.
4. As the human, I want an option carrying no mark to unlock its downstream nodes immediately, so that the paths the map author judged safe cost nothing.
5. As the human, I want any note or free-text answer I write to be judged before its downstream nodes open, so that my own words are weighed and not trusted blindly.
6. As the human, I want the expert, not a cheap seat, to weigh impact, so that the ruling that unlocks a node is the one that reads the board.
7. As the human, I want the result of an impact task to arrive as the target's new shape, so that the node I am about to answer is already correct.
8. As the human, I want anything an impact task proposes beyond its own target — a new decision, a neighbour revised — to reach my inbox as a proposal showing before and after, so that nothing rewrites the map without my applying it.
9. As the human, I want an impact task that errors or times out to show as a named failure on the node with a retry control, so that a dead seat never parks a decision silently.
10. As the human, I want the map doctor available at all times to look at the whole map, so that a broken or inconsistent board can be rescued without me finding the break.
11. As the human, I want the likely rulings on a node's marked neighbours computed before I click, so that the wait is paid in the background.
12. As the human, I want a pre-ruling that the board moved under to be recomputed rather than trusted, so that background work never lands stale.
13. As the human, I want two results that disagree to be merged into one proposal I can read, so that I adjudicate a conflict once rather than reconcile two.
14. As the human, I want a `stands` ruling justified but never flagged as needing my attention, so that unread marks mean something moved.
15. As a map author, I want my `puts_in_question` marks to be the trigger for judgment, so that the marks I write are the contract the board enforces.
16. As the orchestrator relaying a session, I want the log to carry every impact task, its target, its seat and its outcome, so that a session can be replayed and its waits measured.
17. As a map author, I want every agent weighing my board against a settlement told not to relitigate my structure or my rationale absent a significant reason, so that a judgment turn rules on impact instead of redesigning the map.
18. As the human, I want a switch that applies a proposal for me when every part of it touches a decision I have not answered, so that I can trade inbox review for speed on a board I trust.

## The decisions, as settled

Each is a settled decision of the source session, restated as the board's rule. The ledger
ids are what slices and criteria cite.

**PND-D1 — Trigger: an impact task per target, started when the decision goes waiting; the frontier is the lock.** A decision under analysis is an unsettled prerequisite. An impact task is keyed by its target decision and computed over everything settled upstream at the moment it runs; at most one task per target is live; a later upstream answer supersedes the live task for that target rather than queuing behind it. The first race the session named — A then B, both feeding C — closes by construction. *(session d1(a))*

**PND-D2 — Impact: the mark, plus any human note or free answer; an absent mark means safe.** A decision becomes waiting when the human takes an option whose `puts_in_question` names it and it is still live, or when the human's answer on an upstream decision carries a note or is free text. An option with no mark unlocks its downstream nodes immediately. The map author's omission is trusted; the cost is accepted. *(session d2(a))*

**PND-D3 — Output: the target changes directly; anything wider is a proposal.** An impact task's result may revise or invalidate its own target, landing without the human's apply, and the node unlocks in its new shape. A retry re-runs the failed task in its own mode and its result folds exactly as the first run's would have; only the doctor is outside this rule. An `add-node`, a change to any other decision, or a clash with a settled answer is a proposal to the inbox; PND-D16 governs only whether the page applies that proposal for the human. This amends the board's rule that nothing an agent says rewrites the board on its own: the exception is a task's own target, and the history record names the task that changed it. *(session d3(b), taken over the seat's objection)*

**PND-D4 — Seat: the expert at medium effort, for every impact task and for any custom text.** Measured on one turn: cheap seats 7–27s and shallow, the expert 45–61s at every effort and the only one that read the board — at medium already. Custom text on an answer is judged by the expert whether or not the option was marked. The task turns' effort is configuration's own, defaulting to medium; the transferred expert's own effort setting keeps its meaning and never reseats a task. *(session d4, free text)*

**PND-D5 — Lock: hard, no release.** A waiting decision cannot be answered until its impact task returns. The board names the decision, the gesture it waits on, the seat, and how long. View operations stay open. A waiting decision is a hold with a named holder — the impact task weighing it — and so extends the board's lock vocabulary rather than the queue's: the holder is a task rather than a queued proposal or an alert, and the board names it the way it names any other holder. *Waiting* is the word for this state everywhere — this spec's prose, the log, the projections and the board's own legend — because *pending* names the human's queue of what to act on, and a waiting decision is the opposite: one nobody may act on. *(session d5(a), the decision as the expert revised it)*

**PND-D6 — Pre-compute: one hop, descendants on a doubt.** For every offered decision, each option's impact on its marked neighbours is pre-ruled in the background. Settling A pre-computes A's opened children; a child opening pre-computes its own. A pre-ruling's basis is the log sequence at which it was computed; it is stale when any later landed change — an answer, an applied proposal, or a fold that changed the node — touches its target, the decision whose option it was computed for, or an ancestor of either, and is then recomputed; a proposal still queued touches nothing until it is applied. When a taken option puts B in doubt, B's re-evaluation locks B and covers B's descendant hops as both re-evaluation and pre-compute. *(session d6, free text)*

**PND-D8 — Result conflicts: an expert conflict-resolution turn merges disagreeing results into one proposal.** Two results that were independent when started and clash when combined — two tasks each proposing a new node with the same prerequisite set, a pre-ruling still in flight whose target was answered before its result arrived — are in **result conflict**, and one expert turn merges them into a single proposal, with history naming both sources. A result conflict is recorded as a `status` entry on the map channel whose payload carries a `result_conflict` object naming both source tasks — no new event kind, because the kind registry is closed — and it is not the board's existing *conflict*, which is an author withdrawing a queue entry the human had already acted on and is handed back to that author; nor is it the refusal of a document whose board moved under it. Three mechanisms, three names. A pre-ruling that is cached and unconsumed when its basis goes stale is PND-D6's case — recomputed in the background, never a conflict; only a result already arrived against a committed answer is merged. *(session d8(c))*

**PND-D9 — Failure: holds the lock as a named blocker.** An impact task that errors, is refused by the appender, or times out leaves its decision waiting with a failure shown on the node — what failed, on which seat, when — and a manual retry. Nothing unlocks on inaction. *(session d9(b), free text)*

**PND-D11 — Recovery: node retry and the map doctor are separate.** Node retry asks the grill-master to reassess that node and its descendants over the current tree. The map doctor, always available at the top of the board, asks whether anything on the whole map is broken, inconsistent or in need of adjustment. Either may propose structural change. *(session d11, free text)*

**PND-D13 — Doctor contract: subtree retry, whole-map doctor, all structural results human-applied.** Retry is scoped to the failed node's subtree; the doctor to the map; neither lands a structural change beyond the task's own target: a retry's result folds to its target exactly as the first run would have, and everything wider in its subtree queues as a proposal; every update in the doctor's document queues, including the kinds an ordinary map turn lands directly. *(session d13(a), read with PND-D3)*

**PND-D14 — A `stands` is justified, never attention-required.** A `stands` ruling still mints its targeted informational with its why; the informational arrives read, and the board shows it only behind the decision's read-notice toggle — amending GUI-D45 and §8.10 of the grill-master role spec, which raise it like any other notice. *(the session's UI ruling, recorded on `agents-config-9k9.311`)*

**PND-D15 — Every brief that weighs the board states its backpressure against relitigating the map.** An agent asked to weigh the board against a settlement — an impact task, a review task, a node retry, the doctor, the result-conflict turn — carries in its own brief a paragraph headed exactly `Backpressure:`, saying that the map author's structure and rationale stand unless the agent has a significant reason to move them and that the reason belongs in the ruling it writes. The brief is where the rule lives, because no gate can read whether a ruling relitigated or judged. The heading is the marker a test reads; the prompt-audit spike `agents-config-9k9.314` settles what the paragraph says. This spec fixes the marker, not the sentence. *(owner's review of PR #692, recorded on `agents-config-9k9.315`)*

**PND-D16 — A browser-local preference auto-applies qualifying proposals; default off.** The board carries a persisted preference, held in the browser and never on the log, that decides what the *page* does with a proposal on arrival rather than what the projector does with a document: where every sub-update of an arriving proposal targets a decision the human has not answered, the page records an ordinary human `apply` on it, whose payload carries a marker saying the preference made the gesture. The projector's scoping rule is untouched and takes no parameter, so one log yields one Image 1 whatever any browser's setting is; what a later reader sees is an apply, whose it was, and that it was automatic. It defaults off, so a board nobody has configured behaves exactly as PND-D3 states. The preference extends to an `invalidate` of an unanswered decision, which is the human's standing consent recorded as their own apply, and never to an `unsettle`, which targets an answered decision by definition: it amends the projector's rule that undermining a decision is the human's call for unanswered decisions only, and only through the human's own recorded apply. *(owner's review of PR #692, recorded on `agents-config-9k9.315`)*

The session's d7, d10 and d12 — the terminal round, the review phase and per-entry dispositions — are the child spec's TRV-D1 to TRV-D3; the PND ledger skips D7, D10 and D12 so its numbering mirrors the session's, and no PND-D7, PND-D10 or PND-D12 exists to cite.

## Implementation decisions

**The impact task is a log fact.** A task is recorded on the session log as `status` entries on the map channel whose payload gains a `tasks` list, one task per target the turn carries: each task's id, its target, the sequence of the gesture it was started for, its basis sequence, its mode (`impact`, `review`), the option it was pre-computed for where it was, the id of the failed task it retries where it is a retry, and the seat. A task's target is a decision id in the `impact` mode and a review-entry id in the `review` mode. Ids are derived — the starting sequence and the target, plus the option for a pre-ruling — so a restarted backend recomputes the same id from the same log. The closed phase set gains `superseded`. The channel's status pairing is unchanged — one `composing`, one `replied` or `error` closing the turn — and a task ends on the turn's closing entry, whose `tasks` list carries each task's outcome; a task superseded mid-run is closed instead by the superseding turn's `accepted` entry naming it. Pre-ruling turns run on a channel of their own, so the map channel's pairing never sees a background turn. The projector folds a decision-targeted task into a per-decision `waiting` field on Image 1, which Image 2 inherits and the page reads — the task id, what it waits on, the seat, and the start time — and the frontier excludes any decision with a live task; an entry-targeted task folds into that entry's own `waiting` in the review section the child spec defines. Nothing is kept in process memory that a restarted backend cannot recover from the log; a live task whose process died is an errored task after restart, not a lock.

**The task is the judgment-class turn's obligation, made per target.** A marked answer already dispatches one expert grill-master turn owing a ruling on every decision it names; that turn is the task carrier, not a second dispatch. One gesture composes one turn; the turn carries one task per target it names, and its document must still rule on each; when one of those tasks is superseded while the turn runs, only that target's ruling is dropped, with a history line, and the reply's other rulings fold. An answer carrying a note or free text joins the judgment classes as a class of its own and owes a task on each downstream decision it opens.

**Classing extends the judgment set, it does not replace it.** The existing pre-dispatch classing decides the seat for a gesture; PND-D4 seats every turn carrying a task on the expert at medium effort regardless of the channel's configured first rung. The distrust counter and the human's transfer control are untouched.

**Supersession, not a queue.** When a gesture would start a task for a target that already has one live, the live task is marked superseded and its result, if it later arrives, is dropped with a history line saying so. One live task per target is an invariant the lane holds under its append lock.

**What a document may land depends on the task's mode, enforced by the projector.** An `impact` task's sub-updates targeting its own decision fold directly and every other sub-update queues as a proposal; PND-D16 changes what the page does with that proposal, never what the projector does with the document. A retry is the failed task's mode again over the current upstream state, and its result lands under that mode's rule; a sub-update outside the failed node's subtree is refused at the document gate. Retry is offered only while the failed task is the latest for its target — an upstream answer landing after the failure supersedes the failed task with a fresh one, and the control goes with it. A pre-ruling that fails is background work with no lock and no control: it is never consumed, and the click starts a task. The doctor's turn and the result-conflict turn carry no task: the doctor keeps its existing whole-board freeze while it is outstanding, the result-conflict turn holds nothing, and every sub-update of either queues, the doctor's over the whole map, the result-conflict turn's as one proposal. The history record carries a `task` field naming the impact task that landed the change; `proposed_by` keeps its own meaning — the agent whose queued update a human's apply landed — so a decision the human never touched still says what changed it without the two provenances being confused. A `revise` that supplies no structural field is refused at the document gate (the defect `agents-config-9k9.310`), because under this rule an empty revise would unlock a node claiming to have changed it.

**The wider auto-apply is page behaviour, not a projector parameter.** The preference is `localStorage` on the board and reaches no other surface: the backend learns of it only through the applies it produces, and the log never carries the setting itself. When a proposal arrives and every one of its sub-updates targets a decision with no answer of record, the page emits the same `apply` gesture it would have emitted had the human pressed the control, with `by_preference: true` on the payload — the one optional key the apply payload gains beside `pending`, so a reader can tell a pressed apply from a preference's; a proposal with any sub-update on an answered decision — settled or stale — or any `unsettle` waits in the inbox as it does today. The qualifying test is the page's, taken against the Image 1 it is rendering, so a decision answered while the task ran leaves its proposal waiting. `add-node` is unaffected: a new decision overwrites nothing and already lands. Turning the preference off changes nothing already applied, because what landed is an apply on the log like any other.

**Backpressure is a marked paragraph in the brief, not a check.** Every dispatch that carries a task, plus the doctor's and the result-conflict turn's, opens a paragraph with the literal heading `Backpressure:`. The heading exists so the requirement has an oracle: the fact a gate would want — whether a ruling relitigated or judged — is not legible from any document, but the presence of the paragraph is legible from the dispatch record. `agents-config-9k9.314` audits and changes what the paragraph says; the heading is this spec's, and PND-A11 asserts only that.

**Pre-rulings are cached task results.** A pre-ruling is an `impact` task run ahead of the gesture, recorded as the same log facts with its `option` field naming the option it was computed for — the field's presence is the whole marker; taking that option with no note consumes the pre-ruling instead of starting a task, and the board unlocks at once. Staleness is PND-D6's rule over the pre-ruling's basis sequence; the staleness check and the consumption are one step inside the lane's accept of the answer gesture, under the append lock, so no mutation can land between them; a stale pre-ruling is recomputed in the background and never consumed.

**Failure is board-visible.** A task's `error` phase folds into its decision's `waiting` field as a named blocker with a retry control — a waiting decision, never a queue item, so the page and the legend cannot mistake "retry this analysis" for "apply this proposal"; with PND-A13's trace for turns carrying no task, this remedies the board-visibility and dropped-obligation arms of the two defects that say an unreachable seat and an appender refusal leave no trace (`agents-config-9k9.309`, `agents-config-9k9.306`); the appender's automatic fault-quoting retry stays `agents-config-9k9.306`'s own.

**The result-conflict turn is a judgment-class turn.** Two results are in result conflict when both are live and independent when started — neither's basis includes the other's result — and either both add a node with the same prerequisite set — the decision model has prerequisites, not parents — both carry a sub-update targeting one decision, or one is a pre-ruling whose result arrived after its target was answered — a pre-ruling still cached and merely stale recomputes under PND-D6 and never enters a conflict. The lane records the conflict first — the `status` entry whose `result_conflict` names both tasks — and then composes one expert turn over both, whose document is a single proposal carrying both sources in its why.

**Seams.** The highest existing seam is the end-to-end harness: scripted seats and a headless browser driving the real launch path, asserting on log bytes and rendered facts. Every criterion below is expressible there. Beneath it, the unit seams already in place — the lane's accept and classing, the projector's fold, the document gate — carry the same facts. One new seam: the `waiting` field on Image 1, which the page reads and the harness asserts. No new process, service or transport.

## Testing decisions

A good test drives a gesture through the board and reads the log and the page, never the lane's internals. The end-to-end harness's scripted seats fail a turn on cue today and script only output and exit; holding a task open until the test releases it, and running one into a timeout, take a shim directive the harness does not yet have — a turn that blocks until the test signals it, under a configurable turn timeout — which lands inside S4's scope, where the failure and timeout arms first need it. With it, lock, supersession, failure and pre-compute are testable deterministically; the unit suite pins the same invariants at the lane and projector. Prior art: the harness's distrust and codex-chain scenarios, and the unit suite's classing tests.

## Acceptance criteria

Each names what a red test asserts, on the log's bytes and, where the fact is rendered, on the page.

- **PND-A1** Taking an option whose mark names a live decision records an impact task on the map channel naming that decision as its target, carrying a basis sequence equal to the log sequence at the gesture that started it; Image 1 lists the decision as `waiting` with the task's gesture, seat and start; the frontier excludes it; the page offers no answer control on it while its view operations — history, threads, notices — stay readable and every decision not downstream stays answerable. An option with no mark records no task and leaves every downstream node on the frontier. Inverse: a mark naming a dead or absent decision records nothing. Restart: a fresh backend over the same directory shows the same `waiting` field, and a task whose process did not survive shows as failed, not live.
- **PND-A2** An answer carrying a note or free text records a task on each downstream decision it opens, seated on the expert seat at the task effort the configuration resolves — `medium` on a session with no task-effort setting, and never the value of `GRILLUI_HEAVY_EFFORT`, whatever it is set to; the turn's attribution records that effort, which is what the test reads. The same answer with no note and an unmarked option records none. One gesture composes one turn however many targets it names — one `status` entry listing one task per target — and a marked answer records exactly one expert turn, never two.
- **PND-A3** A second gesture whose task targets a decision already waiting marks the live task superseded and starts one over the new upstream state; a result arriving for the superseded task is dropped with a history line, never folded, while the same reply's rulings on its other, still-live targets fold; at no sequence do two live tasks share a target. Concurrent: two gestures in one batch targeting the same decision yield exactly one live task.
- **PND-A4** An impact task result whose sub-update targets its own decision folds directly with history whose `task` field names the impact task and whose `proposed_by` is unset, and the decision returns to the frontier in its new shape; a sub-update targeting any other decision, or adding a node, lands in the inbox as a proposal whose row shows the change before and after. A `revise` supplying none of the structural fields — `short`, `title`, `body`, `prereqs`, `options` — is refused at the document gate and never reaches the inbox, and a `revise` supplying only `prereqs` is a structural change, not the refused case.
- **PND-A5** An impact task that errors, is refused, or times out leaves its decision waiting with a failure on the node naming the cause, the seat and the time, and a retry control; pressing retry records a task in the failed task's mode naming the failed task, over the current upstream state and scoped to that decision's subtree, whose result folds exactly as the first run's would have; nothing unlocks without a result; the control is absent once an upstream answer has superseded the failed task, and absent on a failed pre-ruling. Idempotent: pressing retry while a retry is live starts nothing.
- **PND-A6** With a pre-ruling recorded for an option, taking that option with no note consumes it — no task starts, the downstream decisions unlock at once, and history credits the pre-ruling; a landed change after its basis touching its target, the decision it was computed for, or an ancestor of either makes it stale, and a proposal merely queued does not, and a stale pre-ruling is never consumed and is recomputed; a mutation submitted in the same batch as the consuming answer lands before or after the consume, never between the check and it. Settling a decision starts pre-rulings for the options of each decision it opens, and for no deeper decision until its parent opens it.
- **PND-A7** Two live results independent when started that add a node with the same prerequisite set or both target one decision, or a pre-ruling whose result arrives after its target was answered, record one `status` entry whose `result_conflict` names both sources and raise one expert turn over it whose document is a single proposal carrying both sources; the two originals never reach the inbox separately. Inverse: an author superseding its own queue entry the human had already acted on still records the board's existing supersede conflict and is handed back to that author, not merged. Second inverse: a pre-ruling stale and unconsumed when its target moves records a recompute and no `result_conflict`.
- **PND-A8** The map doctor's document may propose structural change to any decision and lands none directly, an `add-node` included; a node retry's document may propose change only within the failed node's subtree, and a sub-update outside it is refused at the document gate.
- **PND-A9** A `stands` ruling's targeted informational is recorded read: it raises no unread mark on the decision and is shown only behind the decision's read-notice toggle, verified in a browser.
- **PND-A10** The brief composed for a thread agent — the tier layer's composition, which the dispatch record preserves — contains, for each waiting decision, that decision's id together with its task's id and seat, and, for each decision an impact task changed, a history line naming that task's id; a brief composed while a decision waits that names neither fails the test.
- **PND-A11** Every impact-task dispatch record contains a paragraph beginning `Backpressure:`, as does every review-task, retry, doctor and result-conflict dispatch; a dispatch composed without that heading fails the test. Inverse: a dispatch for a clerical turn, which weighs nothing against a settlement, does not carry one.
- **PND-A12** With the preference off — the default on a board with no stored setting — a proposal whose sub-updates all target unanswered decisions waits in the inbox. With it on, the same proposal is followed on the log by an `apply` whose payload carries `by_preference: true`, and lands. A proposal touching an answered decision, or carrying an `unsettle`, waits either way. Purity: replaying one log yields the same Image 1 whatever the browser's setting, because the setting appears nowhere in it — only the applies do.
- **PND-A13** Any turn's seat failure — an unreachable seat, a timeout, or an appender refusal after the ladder is spent, on a turn carrying a task or not — records an entry the page renders as a trace naming the seat and the cause; an obligation the failed turn was carrying — a ruling owed on a marked decision, a mootness obligation, a thread turn's owed reply — is either handed up to the expert seat or recorded unmet on the log, never silently dropped. Inverse: a turn that succeeds records no failure trace.
- **PND-A14** Pre-ruling turns announce, tier and close on a channel of their own: while a pre-ruling runs, the map channel carries no `composing` for it, and the map channel's one-`composing`-one-closing pairing is undisturbed by any number of background turns; a restart while a pre-ruling runs closes out the background channel's announced turn without touching the map channel's pairing. Inverse: the click-started task a missing pre-ruling leaves runs on the map channel like any judgment turn.
- **PND-A15** A task superseded mid-run is closed by the superseding turn's `accepted` entry naming it, and its phase reads `superseded` thereafter — never live, `composing` or failed; the map channel's status pairing stays one `composing` and one closing entry per turn throughout. Restart: a fresh backend after a supersession shows the task `superseded`, not errored. Inverse: a task that ran to its own reply is closed by its turn's closing entry, and no `accepted` entry names it.

## Ordered slice list

Each slice is the smallest independently mergeable unit; each cites what discharges it.

- **S1 — The task on the log and the frontier as the lock** (PND-D1, PND-D5; PND-A1, PND-A3, PND-A15): task status entries, the projector's `waiting` field, frontier exclusion with view operations open, supersession under the append lock and the superseding turn's close of the superseded task, the page's waiting state naming what it waits on, restart recovery.
- **S2 — What goes waiting, and on which seat** (PND-D2, PND-D4, PND-D15; PND-A2, PND-A11): the classing extension for notes and free text, expert-at-medium seating for every task, the backpressure statement in every brief that weighs the board (`agents-config-9k9.314` audits its wording).
- **S3 — What a result may touch** (PND-D3, PND-D16; PND-A4, PND-A12): target auto-apply with the history `task` field naming the impact task, wider changes as proposals whose before and after the inbox's own row renderer shows (`agents-config-9k9.311`), the empty-revise refusal (`agents-config-9k9.310`), the browser-local preference applying a qualifying proposal for the human.
- **S4 — Failure as a named blocker, and retry** (PND-D9, PND-D11, PND-D13; PND-A5, PND-A8, PND-A13): the failure phase folded into the `waiting` field, the failure trace and obligation hand-up for every turn, the retry control scoped to the subtree, the shim's hold-open and timeout directive, the doctor's whole-map contract; remedies `agents-config-9k9.309`'s board-visibility and dropped-obligation arms and `agents-config-9k9.306`'s visibility arm — what remains open on each bug, including 309's applied-invalidate condition, is stated in that item's own acceptance.
- **S5 — Pre-rulings** (PND-D6; PND-A6, PND-A14): background tasks per offered option on a channel of their own, consumption on the click, staleness by basis sequence, descendant re-evaluation on a doubt.
- **S6 — The conflict turn** (PND-D8; PND-A7).
- **S7 — Notices that need no attention, and the legend** (PND-D14; PND-A9, PND-A10): `stands` arrives read; the thread-agent legend names the waiting state and task provenance. Folds the notice half of `agents-config-9k9.311`.

The child spec's slices follow S3 and S4.

## Continuations

One item per slice, both specs' slices together, so the design child's delivery reconciles
the implementation placeholder against the children already filed under
`agents-config-9k9.315`.

- feat: grillui S1: the task on the log and the frontier as the lock (PND-D1, PND-D5; PND-A1, PND-A3, PND-A15) — AC: PND-A1, PND-A3, PND-A15; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S2: what goes waiting, and on which seat (PND-D2, PND-D4, PND-D15; PND-A2, PND-A11) — AC: PND-A2, PND-A11; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S3: what a result may touch (PND-D3, PND-D16; PND-A4, PND-A12) — AC: PND-A4, PND-A12, and an impact-task sub-update targeting another decision landing in the inbox as a proposal whose row shows before and after through the inbox's own row renderer (agents-config-9k9.311); agents-config-9k9.310 closes; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S4: failure as a named blocker, retry, and the doctor's contract (PND-D9, PND-D11, PND-D13; PND-A5, PND-A8, PND-A13) — AC: PND-A5, PND-A8, PND-A13; agents-config-9k9.309's board-visibility and dropped-obligation arms discharge and agents-config-9k9.306 narrows to its fault-quoting-retry arm, each bug's residue ruled at the item; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S5: pre-rulings — one hop, consumed on the click, stale by basis (PND-D6; PND-A6, PND-A14) — AC: PND-A6, PND-A14; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S6: the conflict-resolution turn (PND-D8; PND-A7) — AC: PND-A7; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui S7: notices that need no attention, and the legend (PND-D14; PND-A9, PND-A10) — AC: PND-A9 observed in a browser, PND-A10; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui T1: criteria and taxonomy entries on the log, and the review phase (TRV-D1; TRV-A1, TRV-A6) — AC: TRV-A1, TRV-A6; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui T2: dispositions, discussion and the result's criteria section (TRV-D3, TRV-D2; TRV-A2, TRV-A5) — AC: TRV-A2, TRV-A5; make ci-grillui and make e2e-grillui exit 0.
- feat: grillui T3: edit, add and reopen (TRV-D2; TRV-A3, TRV-A4, TRV-A7, TRV-A8) — AC: TRV-A3, TRV-A4, TRV-A7, TRV-A8; make ci-grillui and make e2e-grillui exit 0.

## Out of scope

- Stop-the-world rounds on the board; the child spec's terminal round is the one round the board owes.
- A soft lock or any release from a waiting decision (session d5: declined).
- Pre-ruling beyond one hop from an offered decision, and whole-map pre-ruling at creation.
- The board's styling rulings (`agents-config-9k9.312`) and the end-session guard (`agents-config-9k9.313`), which stand on their own.
- The seat configuration and the Codex driver, which stay whatever GUI-D46's replay observation says (`agents-config-9k9.307`).

## Further notes

PND-D4 rests on an n=1 bake-off; a second session's replay is the cheap check on it. A
first-rung seat on a free-text answer produces empty revises (`agents-config-9k9.310`):
that seat doing the expert's job in the wrong vocabulary, which PND-D2 and PND-D4 remove.

## Evidence

How each criterion above is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser is dischargeable by `test:` only where the test drives a
real browser over the real launch path — the end-to-end suite (`make e2e-grillui`)
qualifies; a unit test that never renders the page proves something else, and a
hand probe stays `probe:`.

- PND-A1 | open
- PND-A2 | open
- PND-A3 | open
- PND-A4 | open
- PND-A5 | open
- PND-A6 | open
- PND-A7 | open
- PND-A8 | open
- PND-A9 | open
- PND-A10 | open
- PND-A11 | open
- PND-A12 | open
- PND-A13 | open
- PND-A14 | open
- PND-A15 | open
