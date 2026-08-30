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

When the frontier empties with no task live or failed, the board enters a **review phase**: the expert enumerates
acceptance criteria and taxonomy rows as entries linked to the decisions they derive from,
and the human disposes of each — accept, or discuss; edit; add. An edit or an addition
re-evaluates the linked decisions; a sufficient challenge reopens one, and the board
returns to the map under its ordinary rules until the frontier empties again. The
completion overlay is offered only when every entry is accepted; the board's End control
stays where it is, behind the unfinished-board guard.

## User stories

1. As the human, I want the session to end with acceptance criteria I have read and accepted, so that what I take away is what the skill would have given me.
2. As the human, I want each criterion and taxonomy row to say which decisions it derives from, so that I can trace a criterion to the choice behind it.
3. As the human, I want to accept or discuss each entry, and never to reject one without a discussion, so that a rejection has a recorded reason.
4. As the human, I want to edit an entry or add one, and have the board tell me which decisions that puts in question, so that criteria and decisions never drift apart.
5. As the human, I want a challenge that undermines a decision to reopen it on the map, so that I can relitigate rather than accept a criterion I no longer believe.
6. As the orchestrator relaying a session, I want the terminal result to carry the accepted criteria with their ids and links, so that a child spec can be written from it.

## The decisions, as settled

**TRV-D1 — A terminal round.** When the frontier empties with no task live or failed and the map is not ended, the expert enumerates acceptance criteria and taxonomy rows as entries on the board, linked to one or more decisions each; the completion overlay is offered only when every entry is accepted. Criteria and taxonomy rows are new record kinds on the log, not decisions. *(session d7(a), free text)*

**TRV-D2 — A gated review with a way back.** Every entry offers accept or discuss; rejection is a conclusion of a discussion, never a control. The human may edit an entry or add one; either starts a re-evaluation task over the linked decisions, and a re-evaluation finding a conflict reopens the decision under the map's ordinary pending rules. *(session d10, free text)*

**TRV-D3 — Per-entry dispositions block completion.** Each entry carries a disposition — `open`, `accepted`, `discussing`, or `rejected` with its thread — and the completion overlay is withheld until every entry is accepted and every re-evaluation and reopened decision is settled. The human's `session-end` gesture is never withheld: it stays behind the unfinished-board guard (`agents-config-9k9.313`), and a session ended that way records every entry's disposition as it stood. *(session d12(a))*

## Implementation decisions

**Entries are log records, and the closed vocabularies grow to hold them.** Three kinds join the event-kind registry as map-channel mutations the fold may carry: `criterion` — a stable id, text, and `derives_from`, one or more decision ids; `taxonomy-row` — its criterion's id, a category from the closed set of five, and either text or a `ruled_out` reason; `disposition` — an entry id and one of `open`, `accepted`, `discussing`, `rejected`. Each gets a payload shape in the gate's registry, and the page's emission registry gains the human's gestures over them: accept is a human `disposition` of `accepted`; discuss is a `thread-created` of the `review` kind, which the projector folds to `discussing`; edit is a human `criterion` or `taxonomy-row` with the same id; add is one with a fresh id. The expert and the human author `criterion` and `taxonomy-row` alike; a record with an existing id supersedes the last. A human's `criterion` without a `derives_from` is refused at the gate, and the page does not offer the add without one; a `disposition` equal to the entry's current one is refused at the gate as a no-op, which is what makes accept idempotent. The projector folds them into a `review` section of the first image, which the second inherits: every entry with its rows, links, disposition and any `waiting` task, and whether the phase is open.

**The enumeration is a grill-master document.** The reply document gains a `review` field carrying criteria with their rows; a document carrying `review` carries no `updates`, and one carrying both is refused. The recording rule that drops a document carrying nothing reads `review` as content: such a document records one fold on the map channel carrying a `criterion` and its `taxonomy-row` records per entry, so the enumeration is on the log whole or refused, never silently absent. The frontier empty with no task live or failed and the map not ended is the trigger; the enumeration is one judgment-class turn of its own class; the phase ends when every entry is accepted. Reopening a decision leaves the phase and returns to it when the frontier empties again; entries survive the round trip, and each entry linked to a decision that changed gets a re-evaluation task when the phase resumes.

**Discussion is a thread of a new kind.** `review` joins the thread kinds; its anchor is an entry id rather than a decision id, and the anchor's validity is read off the review section. The thread dispatch projection gains the review section and the dispatched thread's entry anchor, and a sibling `review` thread is stubbed the way a decision-anchored one is, so the thread's agent holds the entry, its linked decisions and the taxonomy; a rejection is a `disposition` record the fold carries, so a thread's conclusion is the entry's disposition and nothing else may write rejected.

**Re-evaluation is a task in the `review` mode.** A human `criterion` or `taxonomy-row` joins the kinds the lane schedules a turn for, and that turn is one task of the parent spec's shape, mode `review`, targeting the entry and seated on the expert; an edit while one is live for that entry supersedes it. Its document either carries no `updates` — consistent, and the entry's disposition returns to open — or carries `unsettle` or `revise` sub-updates naming linked decisions; each named decision reopens directly, landing on the frontier with history whose `proposed_by` names the task and the entry. A sub-update naming a decision the entry does not derive from is refused at the gate.

**The terminal result carries the review.** `criteria` joins the result's fields: every entry with its id, text, links, rows and disposition, including the ones still open or rejected when the session ended, so the capture step records the phase as it stood rather than the accepted subset.

**Seams.** The end-to-end harness drives the phase with scripted seats and asserts on the log, the page and the result; no new process, service or transport.

## Testing decisions

Drive a board to an empty frontier with scripted seats and assert the entries the log records, their links and dispositions, the page's controls, and the terminal result's criteria section. Prior art: the harness's completion and history scenarios.

## Acceptance criteria

- **TRV-A1** Answering the last frontier decision on a board with no open decision and no task live or failed records one expert turn whose document proposes criteria and taxonomy rows and nothing else, landing on the log as one fold; the same answer with an impact task still live records no enumeration until the task returns; each entry lands with a stable id and at least one linked decision; the completion overlay is not offered while any entry is not accepted.
- **TRV-A2** Each entry offers accept and discuss and no reject control; accepting records a human `disposition` of `accepted`; discussing records a `thread-created` of the `review` kind anchored to the entry and the entry reads `discussing`; that thread's fold may carry a `disposition` of `rejected` with the thread as its reason, and nothing else may write `rejected`. Idempotent: accepting an accepted entry is refused as a no-op and records nothing.
- **TRV-A3** Editing an entry or adding one records one `review` task naming the entry on the expert seat, superseding a live one for the same entry; a document carrying `unsettle` or `revise` on a linked decision reopens exactly the decisions it names, each with history whose `proposed_by` names the task and the entry; a document with no updates leaves the map unchanged and the entry reads `open` again; while the task runs the entry carries `waiting` in the review section and the decisions are untouched; a sub-update naming an unlinked decision is refused; the completion overlay stays withheld until the task returns and any reopened decision is settled. Inverse: a human `criterion` without `derives_from` is refused and the page offers no add without a link.
- **TRV-A4** Reopening a decision from the review phase and settling it again returns the board to the review phase with the surviving entries intact and those linked to the changed decision re-evaluated.
- **TRV-A5** The terminal result's `criteria` section carries every entry with its id, text, linked decisions, taxonomy rows and disposition; a session ended through the unfinished-board guard with an entry still open or rejected records that disposition rather than omitting the entry.
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
