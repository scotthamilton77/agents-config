---
name: grill-capture
description: Produce a grilling session's terminal result — what was settled, what is still open and what blocks it, what the threads concluded — from its session directory alone, with nothing serving it. Use when a grilling session ended without a written result, when asked to capture or write up a past session, or when handed a session directory.
admission:
  provides: Produces a grilling session's terminal result (pure-code decision-log projection plus one prose-summary pass) from a session directory alone, with no backend process.
  cost: Reads a session directory whose size scales with the session's log, spends one model pass on the summary, and requires the grillui CLI on PATH.
  remove_when: A grillui capture verb subsumes the skill's whole procedure, or the backend's end-session capture is the only path with a caller.
---

A session directory is everything a grilling left behind, and it is enough on its own: no
process has to have survived, and the session may have been last week's.

## 1. Project the log

```
grillui capture <session-dir>
```

It folds the session's log into the structured result — the session's identity,
`references` to the files beside it, every decision with its answer, status and rationale,
the open items each with the blocker that has to move first, and the threads with their
conclusions — writes that beside the log and prints it.

The projection's fold is code, not judgement: run twice over the same log it produces the
same bytes.
Do not re-derive any part of it by hand, and do not correct it — a disagreement between
this and your reading of the session means you read the session wrong.

Exiting non-zero means there is no session under that path. Find the right directory; do
not invent a result.

## 2. Write the summary

`summary` is the one field the fold does not compose. It goes through a seam, and the
shipped default counts the result rather than reading it — how many decisions settled, how
many were taken out of the flow, how many are open. You are the written alternative: from
the structured result alone, write a short briefing — what the session settled and on what
grounds, what it left open and what each open item is waiting on, and what the threads
concluded.

Bound it to a briefing. It is never a transcript, never a decision-by-decision walk, and
never longer than the structured result it summarises.

Each thread carries the state the human left it in. A parked one is a loose end they may
come back to, so raise it as unfinished; a closed one is a line item they are done with,
so nothing in the summary raises it. A folded one is a line item carrying its conclusion.

## 3. Hand it over

Report the summary and the open items, and give the paths the result references for
everything else.

Leave the transcript where it is. The session's log and its recorded dispatches hold every
turn and every prompt, they are large, and pulling them into the conversation buys nothing
the projection has not already given you. Open one only when the user asks about a
specific thread or challenges a specific answer.
