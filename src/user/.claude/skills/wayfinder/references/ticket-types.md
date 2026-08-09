# Ticket types

Four kinds of ticket. The noun carries the shape; the `wayfinder:afk` label carries whether an agent may resolve it without the human.

| Kind | Noun | Mode | Resolved by |
|---|---|---|---|
| Research | `spike` | AFK | a delegated `research` run |
| Prototype | `spike` | HITL | the `prototype` skill, with the human reacting to what it builds |
| Grilling | `decision` | HITL | conversation — `grilling` and `domain-modeling` |
| Task | `chore` | either | doing the thing |

A HITL ticket only resolves through a live exchange with a human who speaks for themselves. The agent never stands in for the human's side of it — a grilling agent that answers its own questions has broken this. Only AFK tickets carry `wayfinder:afk`, and `work list --parent <map-id> --status open --label wayfinder:afk` is what a session fans out when the human is away.

**Research.** Reading documentation, third-party APIs, or local resources like a knowledge base, to surface a fact a decision waits on. Use when knowledge from outside the current working directory is required. These are the one exception to one-ticket-per-session: fire them in parallel.

**Prototype.** Raise the fidelity of the discussion by making a cheap, rough, concrete artifact to react to — an outline, a rough take, a stub, or UI/logic code. Link the prototype from the ticket as an asset rather than pasting it in — a pasted copy stops tracking the artifact the moment it changes. Use when "how should it look" or "how should it behave" is the key question.

**Grilling.** Conversation. The default case.

**Task.** Manual work that must happen before a _decision_ can be made — nothing to decide, prototype, or research, but the discussion is blocked until it's done. Signing up for a service so its API can be judged, provisioning access, moving data so its shape can be seen. This is the one type that _does_ rather than decides, and it earns its place by unblocking a decision, not by delivering the destination. The agent drives it alone where it can; otherwise it hands the human a precise checklist. Resolved when the work is done, and the answer records what was done plus any resulting facts — where credentials live, new URLs, row counts — that later tickets depend on.

## Spikes split two ways

`spike` covers both research and prototype, because the facade has one investigation noun. The question itself tells them apart: a question settled by *reading* is research, and one settled by *building something to react to* is a prototype. The `wayfinder:afk` label follows from that — research runs unattended, a prototype needs someone to react.
