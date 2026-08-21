---
name: grill-with-ui
description: Run a grilling session on an interactive board the human drives in their browser — assemble the handoff, launch the session backend, hand over the URL, and return the session's terminal result when it ends. Use when the user asks to grill something in the UI, on the board, or in a browser session. Grilling in the conversation itself is `grilling` instead.
admission:
  provides: Runs a grilling session in the interactive board UI — assembles the handoff from the conversation or a named work item, launches the session backend, hands the human the URL, and returns the terminal result with file references when the session ends.
  cost: Launches a long-running local backend the human drives in a browser, spends model turns on the session's two agent tiers, leaves a session directory on disk, and requires the grillui CLI on PATH.
  remove_when: Launching grillui directly assembles the handoff and returns the terminal result itself, leaving this skill nothing to add over one command.
---

The backend runs the grilling. You write its briefing, start it, hand the human the URL,
and step aside until it exits — then you relay what it decided.

`grillui --version` first. If the command is not there, say so and run `grilling` in the
conversation instead; nothing here works without it.

## 1. Brief the session

Everything the session's agents get, they get from one JSON file, read once at start.
Write it from the conversation, or from the work item the user named — never ask them to
fill it in.

```json
{
  "handoff_version": 1,
  "session": {"id": "store-design", "title": "Session store design",
              "created": "2026-08-21T09:00:00+00:00", "author": "main agent"},
  "impetus": "one paragraph: why this is being grilled now",
  "context": "what the grill-master cannot infer from the plan",
  "constraints": ["what it must not propose"],
  "grilling_brief": {"posture": "how hard to push, and on what axis",
                     "stop_when": "the condition that ends the session"},
  "plan": {
    "statement": "one sentence: what is being designed",
    "decisions": [
      {"id": "d1", "short": "Store", "title": "Which storage layer?", "prereqs": [],
       "body": "the question as the human will read it",
       "options": [{"id": "a", "text": "your recommendation"},
                   {"id": "b", "text": "the alternative worth arguing"}]}
    ]
  },
  "help_reference": "<the whole text of references/help.md>"
}
```

`session.title` is what the board's header says, so name the session the way the human
would. `help_reference` is the contents of `references/help.md`, copied in whole: it is
what backs the board's Help control, and the human's side thread there is answered by an
agent primed with it. Ship it every time — without it the control is not offered at all,
and the human has nobody to ask how the board works.

Two to three options per decision, labelled `a`, `b`, `c` in order, the first one your
recommendation. Every id in `prereqs` names another decision in the same plan, and the
graph may not cycle. `stop_when` is the load-bearing field: an agent asked to find
weaknesses finds them indefinitely, so a session without a stated ending never has one.

Put the file in a fresh directory named for the session — that directory *is* the session,
and everything it produces stays there.

## 2. Launch it and get out of the way

```
grillui serve <session-dir> --handoff <session-dir>/handoff.json
```

It prints the session URL, opens the human's browser at it, and serves the board on
loopback only. Put that URL in your reply too — the browser may not have opened. A refused
briefing exits non-zero naming the field that is wrong: fix that field and re-run.

Then wait. The command returns when the human ends the session, and that is the only thing
you are waiting for. Do not poll the backend, do not tail the log, do not ask the human
whether they are done.

## 3. What the human is looking at

Answer questions about it without reading any file:

- A **map** of the plan's decisions, each opening into its question with the labelled
  options and a free-text note; answering one settles it and opens whatever waited on it.
- **Threads** beside the map for side discussions, each with its own agent. A thread is
  folded back into the map when it concludes, parked as a loose end the human may come
  back to, or closed because they are done with it. Nothing is taken away by any of the
  three, and a closed thread opens again if the human says something in it.
- A **transfer-to-expert** control per channel, moving that conversation from the fast
  agent to the heavy one; it highlights when the agent recommends escalating.
- A **pending queue** of changes the agents propose to the map: the human applies or
  dismisses each. Nothing an agent says rewrites the board on its own.
- **Help**, upper right — a side thread on the session rather than on any decision,
  answered by an agent holding the reference material you shipped. That is where "why is
  this blocking me" goes, so you do not have to answer it from here.
- **End session** — the only way the session ends. It writes the terminal result, stops
  the backend, and returns you your command.

## 4. Relay the result

Stdout is the terminal result: the session's identity, `references` to the files it left
behind, every decision with its answer and status, the open items each with the blocker
that has to move first, the threads with their conclusions, and a summary.

Each thread carries the state the human left it in. A parked one is still open to them, so
report it with what is unfinished; a closed one is a line item and never anything they
still owe. Do not hand back work they declared done.

Report the summary, what was settled, and what is still open with why. Point at the
session directory for the rest, and leave it there — the log and the recorded dispatches
are the transcript, and pulling them into the conversation spends your context on the
grilling you stepped out of. Read a thread only when the user asks about that thread.

If the command died without printing a result, the session directory still holds
everything: run `grill-capture` against it.
