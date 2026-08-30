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

When the frontier empties, the board enters a **review phase**: the expert enumerates
acceptance criteria and taxonomy rows as entries linked to the decisions they derive from,
and the human disposes of each — accept, or discuss; edit; add. An edit or an addition
re-evaluates the linked decisions; a sufficient challenge reopens one, and the board
returns to the map under its ordinary rules until the frontier empties again. End is
offered only when every entry is accepted.

## User stories

1. As the human, I want the session to end with acceptance criteria I have read and accepted, so that what I take away is what the skill would have given me.
2. As the human, I want each criterion and taxonomy row to say which decisions it derives from, so that I can trace a criterion to the choice behind it.
3. As the human, I want to accept or discuss each entry, and never to reject one without a discussion, so that a rejection has a recorded reason.
4. As the human, I want to edit an entry or add one, and have the board tell me which decisions that puts in question, so that criteria and decisions never drift apart.
5. As the human, I want a challenge that undermines a decision to reopen it on the map, so that I can relitigate rather than accept a criterion I no longer believe.
6. As the orchestrator relaying a session, I want the terminal result to carry the accepted criteria with their ids and links, so that a child spec can be written from it.

## The decisions, as settled

**TRV-D1 — A terminal round.** When the frontier empties and the map is not ended, the expert enumerates acceptance criteria and taxonomy rows as entries on the board, linked to one or more decisions each; End is offered only when every entry is accepted. Criteria and taxonomy rows are new record kinds on the log, not decisions. *(session d7(a), free text)*

**TRV-D2 — A gated review with a way back.** Every entry offers accept or discuss; rejection is a conclusion of a discussion, never a control. The human may edit an entry or add one; either starts a re-evaluation task over the linked decisions, and a re-evaluation finding a conflict reopens the decision under the map's ordinary pending rules. *(session d10, free text)*

**TRV-D3 — Per-entry dispositions block completion.** Each entry carries a disposition — open, accepted, under discussion, rejected with its thread — and completion is blocked until every entry is accepted and every re-evaluation and reopened decision is settled. *(session d12(a))*

## Implementation decisions

**Entries are log records.** A criterion and a taxonomy row are record kinds carrying a stable id, text, the decision ids they derive from, and a disposition; the projector folds them into a `review` section of the second image. A taxonomy row belongs to a criterion and names its category. Ids are stable across edits: an edit is a new record superseding the last by id.

**The review phase is a board state.** The frontier empty and the map not ended is the trigger; the expert's enumeration is one judgment-class turn whose document proposes entries and nothing else; the phase ends when every entry is accepted. Reopening a decision leaves the phase and returns to it when the frontier empties again; entries survive the round trip and are re-evaluated where their linked decisions changed.

**Discussion is a thread.** Discuss opens a thread anchored to the entry, kinded for it, whose agent holds the entry, its linked decisions and the taxonomy; a rejection is that thread's conclusion, folded to the entry's disposition.

**Re-evaluation is a task.** An edit or an addition records a task over the linked decisions, seated on the expert, whose result is either "consistent" or one or more reopen proposals; a reopen lands the decision back on the frontier with a history line naming the entry that caused it.

**Seams.** The end-to-end harness drives the phase with scripted seats; the terminal result gains a `criteria` section the capture step already knows how to write.

## Testing decisions

Drive a board to an empty frontier with scripted seats and assert the entries the log records, their links and dispositions, the page's controls, and the terminal result's criteria section. Prior art: the harness's completion and history scenarios.

## Acceptance criteria

- **TRV-A1** Answering the last frontier decision on a board with no open decision records one expert turn whose document proposes criteria and taxonomy rows and nothing else; each entry lands with a stable id and at least one linked decision; the completion overlay is not offered while any entry is not accepted.
- **TRV-A2** Each entry offers accept and discuss and no reject control; accepting records the disposition; discussing opens a thread anchored to the entry whose fold may record a rejection with the thread as its reason. Idempotent: accepting an accepted entry records nothing.
- **TRV-A3** Editing an entry or adding one records a task over its linked decisions on the expert seat; a result finding a conflict reopens the decision on the frontier with history naming the entry; a result finding none leaves the map unchanged; End stays unoffered until the task returns and any reopened decision is settled.
- **TRV-A4** Reopening a decision from the review phase and settling it again returns the board to the review phase with the surviving entries intact and those linked to the changed decision re-evaluated.
- **TRV-A5** The terminal result carries every accepted criterion with its id, text, linked decisions and taxonomy rows, and no rejected one; a session ended with an entry still open records that in the result rather than omitting the entry.
- **TRV-A6** Every taxonomy category — inverse, empty or boundary, dependency failure, repeated or concurrent, idempotency — is either present as a row on each criterion or recorded as ruled out with a reason; a criterion missing a category with no ruling blocks completion.

## Ordered slice list

- **T1 — Entries on the log and the review phase** (TRV-D1; TRV-A1, TRV-A6): the record kinds, the projector's review section, the trigger, the enumeration turn, the completion gate.
- **T2 — Dispositions and discussion** (TRV-D3, TRV-D2; TRV-A2, TRV-A5): accept and discuss, the entry-anchored thread, rejection by fold, the terminal result's criteria section.
- **T3 — Edit, add and reopen** (TRV-D2; TRV-A3, TRV-A4): the re-evaluation task, reopen with provenance, the round trip back to the phase.

## Out of scope

- Enumerating criteria during the session as each decision settles (session d7(c): declined).
- An expert adjudicator that reopens decisions without the human (session d10(c), d12(c): declined).
- The readiness gate that consumes the criteria downstream; this spec only produces them.

## Further notes

The session's own answer to d7 asked for "a phase two of the grill-with-ui flow" and for the
human to be able to relitigate decisions from it; TRV-D2's reopen is that path, and it
reuses the parent spec's pending rules rather than adding a second lock.
