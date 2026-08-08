---
name: wayfinder
description: Chart work too big for one agent session as a map of decision questions on the tracker, then resolve them one at a time until the way to the destination is clear. Use when the destination is fogged and what to decide comes before what to build — a ticket here is resolved by answering it. Work whose decisions are already made and only needs slicing into build tickets goes to `to-tickets` instead.
disable-model-invocation: true
admission:
  provides: A durable map on the tracker for an effort larger than one agent session — the destination, the open decisions, their blocking edges, and what has been decided so far — so a fresh session orients from the tracker instead of from the previous session's context.
  cost: Per effort, one container plus one tracker item per decision, and a standing rule of one ticket resolved per session.
  remove_when: A session's context reliably spans a whole effort, so the decisions and their order no longer need an artifact to outlive it.
---

<!--
Source: skills/engineering/wayfinder/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: local-fork — setup command and local-markdown fallback removed, tracker model rewritten onto work verbs, label scheme reduced to two, map body, frontier-section rules, ticket types and tracker operations split into references/; do not re-sync
-->

# Wayfinder

A loose idea has arrived — too big for one agent session, and wrapped in fog: the way from here to the **destination** isn't visible yet. Wayfinding is about finding that way, not charging at the destination. This skill charts the way as a **shared map** on the tracker, then works its **decision tickets** — questions whose resolution is a decision, not slices of a build to execute — one at a time until the route is clear.

The destination varies per effort, and naming it is the first act of charting — it shapes every ticket. It might be a spec to hand off and iterate on, a decision to lock before planning starts, or a change made in place like a data-structure migration. The map is domain-agnostic — engineering work, course content, whatever fits the shape.

## Plan, don't do

Wayfinder is **planning** by default: each ticket resolves a decision, and the map is done when the way is clear — nothing left to decide before someone goes and does the thing. The pull to just do the work is usually the signal you've reached the edge of the map and it's time to hand off. An effort can override this in its **Notes** — carrying execution into the map itself — but absent that, produce decisions, not deliverables.

Handing off is the normal ending. When the map is clear, the build slices that follow are `to-tickets`' job, not this one.

## Refer by name

Every map and ticket is a work item, so it has a **name** — its title. In everything the human reads — narration, the map's Decisions-so-far — refer to it by that name, never by a bare id. A wall of ids is illegible; names read at a glance. The id doesn't vanish — a name wraps its link — but it rides _inside_ the name, never stands in for it.

## The map on the tracker

The map is a single container item labelled `wayfinder:map` — the canonical artifact. Its tickets are its children.

The map is an **index**, not a store. It lists the decisions made and points at the tickets that hold their detail; a decision lives in exactly one place — its ticket — so the map never restates it, only gists it and links. What goes in its body is [references/map-body.md](references/map-body.md).

Every verb — minting the map and its tickets, wiring blocking edges, walking the frontier, claiming, resolving, writing the map back — is in [references/tracker-operations.md](references/tracker-operations.md). Read it before touching the tracker: two of those calls carry a trap, and one query that looks exactly right returns work belonging to other efforts.

## Tickets

Each ticket is a **child of the map**; its id is its identity. Its description is the question, sized to one agent session:

```markdown
## Question

<the decision or investigation this ticket resolves>
```

Every ticket is either **HITL** — human in the loop, worked _with_ a human who speaks for themselves — or **AFK**, driven by the agent alone. A HITL ticket only resolves through that live exchange; the agent never stands in for the human's side of it (a grilling agent that answers its own questions has broken this). AFK tickets carry `wayfinder:afk`. For which of the four kinds of ticket is which, and how each resolves, see [references/ticket-types.md](references/ticket-types.md).

The answer isn't part of the description — it is recorded on resolution, as the closing disposition. Assets created while resolving a ticket are linked by note, not pasted in.

## Fog of war

The map is _deliberately_ incomplete: don't chart what you can't yet see. Beyond the live tickets lies the **fog of war** — decisions and investigations you can tell are coming but can't yet pin down, because they hang on questions still open. Resolving a ticket clears the fog ahead of it, graduating whatever's now specifiable into fresh tickets — one at a time, until the way to the destination is clear and no tickets remain.

Fog is in scope and merely unsharp, so it lives in the map's **Not yet specified** section; the test for putting something there is whether you can state the question precisely now, _not_ whether you can answer it. Work you've consciously ruled beyond the destination is a different thing — **out of scope**, never fog — and it never graduates. Both sections, and how to rule an existing ticket out of scope, are in [references/map-body.md](references/map-body.md).

## Invocation

Two modes. Either way, **never resolve more than one ticket per session** — with the exception of research tickets.

### Chart the map

User invokes with a loose idea.

1. **Name the destination.** Run a `grilling` and `domain-modeling` session to pin down what this map is finding its way to — the spec, decision, or change. The destination fixes the scope, so it's settled first.
2. **Map the frontier.** Grill again, **breadth-first** this time: fan out across the whole space rather than deep on any one thread, surfacing the open decisions and the first steps takeable now. **If this surfaces no fog** — the way to the destination is already clear, the whole journey small enough for one session — you don't need a map. Stop and ask the user how they'd like to proceed.
3. **Create the map**, with Destination and Notes filled in, Decisions-so-far empty, and the fog sketched into **Not yet specified**.
4. **Create the tickets you can specify now** as children of the map, then wire blocking edges in a **second pass** — items need ids before they can reference each other. Wiring sorts them into the ticket frontier and the blocked; everything you can't yet specify stays in the fog.
5. **Fire the research subagents.** For each research ticket you just created, delegate a `research` run to resolve it in parallel, and note the resulting artifact's location back onto the ticket.
6. Stop — charting is one session's work; it hand-resolves nothing.

### Work through the map

User invokes with a map. A ticket is **optional** — without one, you pick the next decision, not the user.

1. Load the **map** — the low-res view, not every ticket body.
2. Choose the ticket. If the user named one, **claim it** before any work. Otherwise walk this map's open tickets — `work list --parent <map-id> --status open` — claiming each in turn until one is accepted; a refusal means that ticket is still blocked, so move to the next.
3. Resolve it — **zoom as needed**: fetch the full body of any related or closed ticket on demand; invoke the skills the map's `## Notes` block names. If in doubt, use `grilling` and `domain-modeling`.
4. Record the resolution: close the ticket with the answer as its disposition, then append a one-line gist and link to the map's Decisions-so-far.
5. Add newly-surfaced tickets (create, then wire); graduate any fog the answer has made specifiable, clearing each graduated patch from **Not yet specified** so it lives only as its new ticket. If the answer reveals a ticket — this one or another — sits beyond the destination, rule it out of scope rather than resolving it on the route. If the decision invalidates other parts of the map, close those tickets with a disposition saying why.

The user may run unblocked tickets in parallel, so expect other sessions to be editing the tracker concurrently.
