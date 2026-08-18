# The handoff file — v1

A grilling session starts because some other agent decided it should. That agent
holds all the context: why this plan exists, what the human already ruled out,
what the grilling is allowed to touch. The backend that runs the session holds
none of it, and is a fresh process with a fresh context.

The handoff file is the whole of what crosses that gap. One JSON file, written
once, read once at session start. After that the backend's event log is the
source of truth and the handoff is history.

This inverts round 4. There, the page owned the board and an agent attached to a
mail slot to watch it. Here, a main agent writes `handoff.json`, starts
`backend.py` pointed at it, and walks away; the backend mints its own grillers
and the browser is a viewer that arrives late and can leave early.

## Shape

```jsonc
{
  "handoff_version": 1,
  "session": {
    "id":      "spike5-overnight",       // directory name, log filename, epoch scope
    "title":   "Overnight build pipeline",
    "created": "2026-08-18T12:00:00Z",
    "author":  "main agent (Claude Code session)"
  },

  "impetus":  "...",   // why we are grilling THIS, NOW — one paragraph
  "context":  "...",   // what the griller cannot infer from the tree
  "constraints": [ "..." ],  // what the griller must not do

  "grilling_brief": {
    "posture":   "...",  // how hard to push, and on what axis
    "stop_when": "..."   // the session's own termination condition
  },

  "plan": {
    "statement": "...",       // one sentence: what is being designed
    "decisions": [ /* the design tree */ ]
  }
}
```

A decision is the round-1..4 node shape, unchanged, so a handoff and the
prototype board are the same data:

```jsonc
{
  "id": "D1",
  "short": "Work-item source",              // map label
  "title": "Where the night's work comes from",
  "prereqs": [],                            // ids that must settle before this defogs
  "body": "The question, as the human will read it.",
  "options": [
    { "id": "a",
      "text": "The answer, in the human's voice.",
      "pcr": [ "what it buys", "what it costs", "what it forces downstream" ] }
  ]
}
```

`options[0]` is the recommendation. `pcr` is optional; the griller may add or
revise options mid-session, and those revisions live in the event log, never
back in this file.

## The four fields that carry the weight

Everything above `plan` exists because a fresh griller reading only a decision
tree grills the wrong thing. Each field answers a failure the tree alone invites:

| Field | Without it, the griller… |
|-------|--------------------------|
| `impetus` | treats every decision as equally live, and spends the session on the one the human settled last week |
| `context` | re-derives constraints the human already knows, out loud, as questions |
| `constraints` | proposes the option that was explicitly rejected upstream |
| `grilling_brief.posture` | picks an intensity at random — deferential when it should push, combative when the human wants speed |
| `grilling_brief.stop_when` | never stops; an LLM asked to find weaknesses finds them indefinitely |

`stop_when` is the same termination problem an adversarial review round has: a
findings generator pointed at any surface emits findings in proportion to that
surface. The handoff has to name the condition that ends the session, because
the griller will not discover one.

## What v1 deliberately leaves out

- **No transcript.** The handoff is a briefing, not a conversation dump. If the
  upstream discussion matters, it belongs in `context` as conclusions.
- **No agent/model selection.** Which tier answers which turn is a runtime
  decision the backend makes (and re-makes, when a griller escalates itself).
- **No UI state.** Panel layout, what is collapsed, what has been read — the
  page owns those, and they do not survive into a new session anyway.
- **No resume pointer.** Resuming is not a handoff. A restarted backend reads
  its own event log; the handoff is only consulted when the log is empty.

## Lifecycle

```
main agent  ──writes──▶  handoff.json
                              │
                              ▼
                   backend.py --session <dir>
                              │
                    log.jsonl empty?
                     ├── yes → seed the board from handoff.plan, append `session-start`
                     └── no  → ignore handoff.plan entirely, replay the log
                              │
                              ▼
                  image1.json / image2.json   ← what grillers actually read
```

The one-way rule: after `session-start` is in the log, `handoff.json` has no
further authority. Editing it mid-session changes nothing, and the backend will
not notice. That is what makes restart-resume safe — there is exactly one source
of truth after the first second, and it is the log.
