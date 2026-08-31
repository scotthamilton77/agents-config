# Grilling board: the terminal review phase — acceptance criteria and the edge-case taxonomy

**Date:** 2026-08-30
**Status:** Draft, settled by a grilling session. Child of
`docs/specs/2026-08-30-grilling-board-pending-analysis.md`; lands after its S3 and S4.
Tracker: `agents-config-9k9.315`.

## Problem statement

The `grilling` skill does not end until the plan's acceptance criteria are enumerated with
stable ids, each red-test-convertible, and each row of the edge-case taxonomy — inverse,
empty or boundary, dependency failure, repeated or concurrent, idempotency — is resolved or
ruled out. The board ends on a prose stop condition the grill-master judges. Its result is
therefore weaker than the skill's, and the readiness gate downstream has nothing to read.

## Solution

When the frontier empties with no impact task live or failed, the board enters a **review
phase**: the expert enumerates acceptance criteria and taxonomy rows as entries linked to
the decisions they derive from, and the human disposes of each — accept, or discuss; edit;
add. A discussion tests the human's rationale for the entry and holds the board while it is
open; an edit or an addition is made in place but blocks on the agent's judgment of its
impact, which opens a discussion where there is any. A sufficient challenge reopens a
linked decision, and the board returns to the map under its ordinary rules until the
frontier empties again. The completion overlay is offered only when every entry is
accepted; the board's End control stays where it is, behind the unfinished-board guard.

## User stories

1. As the human, I want the session to end with acceptance criteria I have read and accepted, so that what I take away is what the skill would have given me.
2. As the human, I want each criterion and taxonomy row to say which decisions it derives from, so that I can trace a criterion to the choice behind it.
3. As the human, I want discussing an entry to be an interactive test of my own rationale, ending in a clarification, an edit or a rejection, and any impact on decisions I have already settled raised in that same discussion, so that I never dispose of an entry on an untested reason or learn its cost somewhere else.
4. As the human, I want an open discussion to hold the board until it is folded, parked or closed, so that nothing moves under a conversation I am in the middle of.
5. As the human, I want my edit or addition made in place but held until the agent has judged its impact on the board and on the other entries — opening a discussion with that explanation where there is impact, and reopening a decision the change undermines — so that I commit, revise or abandon the edit knowing what it costs, and can relitigate rather than accept a criterion I no longer believe.
6. As the orchestrator relaying a session, I want the terminal result to carry the accepted criteria with their ids and links, so that a child spec can be written from it.

## The decisions, as settled

**TRV-D1 — A terminal round.** When the frontier empties with no impact task live or failed and the map is not ended, the expert enumerates acceptance criteria and taxonomy rows as entries on the board, linked to one or more decisions each; the completion overlay is offered only when every entry is accepted. Criteria and taxonomy rows are new record kinds on the log, not decisions. *(session d7(a), free text)*

**TRV-D2 — Discussion is the interactive test, and it holds the board.** Every entry offers accept or discuss; rejection is a conclusion of a discussion, never a control. A discussion is an interactive test of the human's rationale for the entry, and it ends one of three ways: a clarification that leaves the entry standing, an edit to it, or its rejection. Any impact the agent finds on decisions already settled is raised in that same discussion, never as a separate notice, so the criterion and its cost are judged in one place. A discussion ends four ways and no others: its fold carries the entry re-recorded under the same id — a clarification or an edit, which starts a review task as any edit does — together with a `disposition` of `accepted`; or its fold carries a `disposition` of `rejected`; or the human parks it; or the human closes it. Park and close leave the entry `open`. While a discussion is open it is the named holder of every open decision and of every other entry's disposition, which is the board's own lock vocabulary — one hold, one holder the board names — over the review surface; folding, parking or closing it lifts the hold. An edit or an addition is made in place, and its submission blocks until a review task has judged its impact on the board and on the other entries; where there is impact, a discussion opens carrying the agent's explanation, and the human commits, revises or abandons the edit from there. A review task finding a clash reopens the linked decision under the map's ordinary waiting rules, with the same provenance. *(session d10, free text; the owner's review of PR #692 for the discussion's shape and the lock)*

**TRV-D3 — Per-entry dispositions block completion.** Each entry carries a disposition — `open`, `accepted`, `discussing`, or `rejected` with its thread — and the completion overlay is withheld until every entry is accepted, every criterion carries each of the five taxonomy categories as a row or a `ruled_out`, no discussion is open, and every review task and reopened decision is settled. The human's `session-end` gesture is never withheld: it stays behind the unfinished-board guard (`agents-config-9k9.313`), and a session ended that way records every entry's disposition as it stood, an open discussion included. *(session d12(a))*

## Implementation decisions

**Entries are review records, a class of their own.** Criteria, taxonomy rows and dispositions are not decisions and not map mutations: they travel on the map channel and the fold may carry them, but they sit outside the map-mutation set and so outside the sole-author gate, which is what lets the human and the expert both author one without the appender's refusal of a non-grill-master mutation coming into it. Three kinds join the event-kind registry as review records: `criterion` — a stable id, text, and `derives_from`, one or more decision ids; `taxonomy-row` — its criterion's id, a category from the closed set of five, and either text or a `ruled_out` reason; `disposition` — an entry id and one of `open`, `accepted`, `discussing`, `rejected`. Each gets a payload shape in the gate's registry, and the page's emission registry gains the human's gestures over them: accept is a human `disposition` of `accepted`; discuss is a `thread-created` of the `review` kind, which the projector folds to `discussing`; edit is a human `criterion` or `taxonomy-row` with the same id; add is one with a fresh id. The expert and the human author `criterion` and `taxonomy-row` alike — permitted because a review record is not a map mutation; a record with an existing id supersedes the last. A human's `criterion` without a `derives_from` is refused at the gate, and the page does not offer the add without one; a `disposition` equal to the entry's current one is refused at the gate as a no-op, which is what makes accept idempotent. The projector folds them into a `review` section of Image 1, which Image 2 inherits: every entry with its rows, links, disposition and any `waiting` task, and whether the phase is open.

**The enumeration is a map document.** The map document gains a `review` field carrying criteria with their rows; a document carrying `review` carries no `updates`, and one carrying both is refused. The recording rule that drops a document carrying nothing reads `review` as content: such a document records one fold on the map channel carrying a `criterion` and its `taxonomy-row` records per entry, so the enumeration is on the log whole or refused, never silently absent. The frontier empty with no impact task live or failed and the map not ended is the trigger; the enumeration is one judgment-class turn of its own class; the phase ends when every entry is accepted. Reopening a decision leaves the phase and returns to it when the frontier empties again; entries survive the round trip, and each entry linked to a decision that changed gets a review task when the phase resumes.

**Discussion is a thread of a new kind.** `review` joins the thread kinds; its anchor is an entry id rather than a decision id, and the anchor's validity is read off the review section. The thread dispatch projection gains the review section and the dispatched thread's entry anchor, and a sibling `review` thread is stubbed the way a decision-anchored one is, so the thread's agent holds the entry, its linked decisions and the taxonomy; a rejection is a `disposition` record the fold carries, so a thread's conclusion is the entry's disposition and nothing else may write rejected. Its agent is briefed to test the human's stated rationale rather than to supply one, and to raise in the thread any settled decision the entry's fate bears on — the same backpressure the parent spec's PND-D15 states for every brief that weighs the board. An open `review` thread holds the board: while one exists, the projector withholds the answer control on every open decision and the disposition controls on every other entry, naming that thread as the holder on each, and the hold lifts when the thread is folded, parked or closed. It is the board's own lock vocabulary — a hold on an open decision with a holder the board names rather than one the human infers — with a thread as the holder alongside a queued proposal, an alert and the parent spec's impact task.

**Re-evaluation is a review task.** A human `criterion` or `taxonomy-row` joins the kinds the lane schedules a turn for, and that turn is one task of the parent spec's shape in its `review` mode — a *review task* — targeting the entry and seated on the expert; an edit while one is live for that entry supersedes it. The record lands in place at once and the entry shows the new text, but the entry carries `waiting` and no disposition may be taken on it until the task returns — the submission blocks on the judgment, which is what keeps the human from accepting an edit whose cost nobody has read. The task judges the edit's impact on the board and on the other entries alike. Its document either carries no `updates` — consistent, and the entry's disposition returns to open — or carries `unsettle` or `revise` sub-updates naming linked decisions; each named decision reopens directly, landing on the frontier with history whose `task` field names the review task and whose `entry` field names the entry; `proposed_by` keeps its own meaning and is unset, because nothing here is a queued update a human applied. Where the document carries any impact at all, the backend opens a `review` thread on the entry seeded with the task's explanation, so the human commits the edit by accepting, revises it with another edit, or abandons it by superseding the record with the previous text; that thread holds the board like any other. A sub-update naming a decision the entry does not derive from is refused at the gate.

**The terminal result carries the review.** `criteria` joins the result's fields: every entry with its id, text, links, rows and disposition, including the ones still open or rejected when the session ended, so the capture step records the phase as it stood rather than the accepted subset.

**Seams.** The end-to-end harness drives the phase with scripted seats and asserts on the log, the page and the result; no new process, service or transport.

## Testing decisions

Drive a board to an empty frontier with scripted seats and assert the entries the log records, their links and dispositions, the page's controls, and the terminal result's criteria section. Prior art: the harness's completion and history scenarios.

## Acceptance criteria

- **TRV-A1** Answering the last frontier decision on a board with no open decision and no impact task live or failed records one expert turn whose document proposes criteria and taxonomy rows and nothing else, landing on the log as one fold; the same answer with an impact task still live records no enumeration until the task returns; each entry lands with a stable id and at least one linked decision; the completion overlay is not offered while any entry is not accepted.
- **TRV-A2** Each entry offers accept and discuss and no reject control; accepting records a human `disposition` of `accepted`; discussing records a `thread-created` of the `review` kind anchored to the entry and the entry reads `discussing`. The discussion ends exactly four ways and the log shows which: a fold carrying the entry re-recorded under its own id plus a `disposition` of `accepted`, which also records a review task; a fold carrying a `disposition` of `rejected` with the thread as its reason; a park; a close — the last two leaving the entry `open`. Nothing but a fold may write `rejected`. While the thread is open no decision offers an answer control and no other entry offers a disposition control, each naming that thread as the holder, and folding, parking or closing it lifts the hold. Its agent's dispatch record carries a paragraph beginning `Backpressure:` and names the entry the thread anchors, and where the entry bears on a settled decision the thread is where that is raised — no separate notice is minted for it. Idempotent: accepting an accepted entry is refused as a no-op and records nothing.
- **TRV-A3** Editing an entry or adding one records the entry's new text in place and one review task naming the entry on the expert seat, superseding a live one for the same entry; while the task runs the entry carries `waiting` in the review section, offers no disposition control, and the decisions are untouched. A document carrying `unsettle` or `revise` on a linked decision reopens exactly the decisions it names, each with history whose `task` field names the review task and whose `entry` field names the entry, and opens a `review` thread on the entry seeded with the task's explanation, which locks the board until the human commits by accepting, revises with a further edit, or abandons by restoring the previous text; a document with no updates opens no thread, leaves the map unchanged and the entry reads `open` again. A sub-update naming an unlinked decision is refused; the completion overlay stays withheld until the task returns, any thread it opened is folded, parked or closed, and any reopened decision is settled. Inverse: a human `criterion` without `derives_from` is refused and the page offers no add without a link.
- **TRV-A4** Reopening a decision from the review phase and settling it again returns the board to the review phase with the surviving entries intact and, for each entry linked to a decision that changed in the round trip, one review task recorded naming that entry when the phase resumes; an entry linked only to unchanged decisions records none.
- **TRV-A5** The terminal result's `criteria` section carries every entry with its id, text, linked decisions, taxonomy rows and disposition; a session ended through the unfinished-board guard with an entry still open or rejected records that disposition rather than omitting the entry.
- **TRV-A6** Every taxonomy category — inverse, empty or boundary, dependency failure, repeated or concurrent, idempotency — is either present as a row on each criterion or recorded as ruled out with a reason; a criterion missing a category with no ruling blocks completion.
- **TRV-A7** A fresh backend over the same directory, started while the review phase is open, shows the same review section — every entry with its rows, links and disposition; a review task live at the kill shows as failed, not live; an open `review` thread is still open and still the named holder of every open decision and every other entry's disposition; a decision the phase reopened is still on the frontier; the completion overlay's withholding is unchanged.
- **TRV-A8** An accept racing the entry's review-task return lands in an order the log makes total: either the accept is refused because the entry is `waiting`, or it lands after the task's outcome — at no sequence is an edit accepted whose judgment nobody read. Two disposition gestures on one entry in one batch land exactly one, the second refused as the gate's no-op. The race is driven, not hoped for: the racing pair is held to arrive together, as the lane's transfer races are.

## Ordered slice list

- **T1 — Entries on the log and the review phase** (TRV-D1; TRV-A1, TRV-A6): the record kinds, the projector's review section, the trigger, the enumeration turn, the completion gate.
- **T2 — Dispositions and discussion** (TRV-D3, TRV-D2; TRV-A2, TRV-A5): accept and discuss, the entry-anchored thread, rejection by fold, the terminal result's criteria section.
- **T3 — Edit, add and reopen** (TRV-D2; TRV-A3, TRV-A4, TRV-A7, TRV-A8): the review task, the blocking submission and its discussion, reopen with provenance, the round trip back to the phase, restart recovery of the open phase, and the accept-versus-return race made total.

## Out of scope

- Enumerating criteria during the session as each decision settles (session d7(c): declined).
- An expert adjudicator that reopens decisions without the human (session d10(c), d12(c): declined).
- The readiness gate that consumes the criteria downstream; this spec only produces them.

## Further notes

The session's own answer to d7 asked for "a phase two of the grill-with-ui flow" and for the
human to be able to relitigate decisions from it; TRV-D2's reopen is that path, and it
reuses the parent spec's waiting rules rather than adding a second lock.

## Evidence

How each criterion above is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser is dischargeable by `test:` only where the test drives a
real browser over the real launch path — the end-to-end suite (`make e2e-grillui`)
qualifies; a unit test that never renders the page proves something else, and a
hand probe stays `probe:`.

- TRV-A1 | open
- TRV-A2 | open
- TRV-A3 | open
- TRV-A4 | open
- TRV-A5 | open
- TRV-A6 | open
- TRV-A7 | open
- TRV-A8 | open
