# The map body

The whole map at low resolution, loaded once per session. It goes in the map item's description, and is rewritten in place as the effort advances.

Open tickets are **not** listed here — they are the map's open children, found by query: `work list --parent <map-id> --status open`. Listing them in the body would mean maintaining a second copy that goes stale the moment a ticket closes.

```markdown
## Destination

<what reaching the end of this map looks like — the spec, decision, or change this effort is finding its way to. One or two lines; every session orients to it before choosing a ticket.>

## Notes

<domain; skills every session should consult; standing preferences for this effort>

## Decisions so far

<!-- the index — one line per closed ticket: enough to judge relevance, then follow the link for the detail the ticket holds -->

- [<closed ticket title>](<link or id>) — <one-line gist of the answer>

## Not yet specified

<!-- in-scope fog you can't ticket yet; graduates as the frontier advances -->

## Out of scope

<!-- work ruled beyond the destination; closed, never graduates -->
```

## Not yet specified

The dim view: the suspected question, the area to revisit later. It's the undiscovered frontier _toward_ the destination — everything here is in scope, just not sharp enough to ticket. Write as loosely or as fully as the view allows; it doubles as a signpost for collaborators reading where the effort is headed.

**Fog or ticket?** The test is whether you can state the question precisely now — _not_ whether you can answer it now.

- **Ticket when** the question is already sharp — even if it's blocked and you can't act on it yet.
- **Not yet specified when** you can't yet phrase it that sharply. Don't pre-slice the fog into ticket-sized pieces: it's coarser than a ticket, and one patch may graduate into several tickets, or none, once the frontier reaches it.

This section excludes what's already decided, what's already a live ticket, and what's out of scope. Clear a patch from here as it graduates, so it lives only as its new tickets.

## Out of scope

Fog only ever gathers _toward_ the destination. The destination fixes the scope, so work beyond it is **out of scope** — it isn't fog, and it doesn't belong in **Not yet specified**. Scope, not sharpness, lands it here, and it never graduates: the frontier stops at the destination, so it returns only if the destination is redrawn, and then as a fresh effort rather than a resumption.

Ruling something out of scope is a scoping act, not a step on the route. When a ticket that already exists turns out to sit past the destination — mis-scoped in while charting, or exposed by a resolution — close it with a disposition saying so and leave one line here: the gist plus why, linking the closed ticket. It stays out of **Decisions so far**, which records the route actually walked.

## Writing it back

`work update <map-id> --set-description "<body>"` **replaces** the description; there is no append. So the sequence is always read, edit, write:

1. `work show <map-id>` and take the current description.
2. Make your edit to it.
3. Write the whole edited body back.

Do that immediately before writing, not at the start of the session. Other sessions may be working the same map in parallel, and a body composed against a stale read silently drops whatever they added in between.
