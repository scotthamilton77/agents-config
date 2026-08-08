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

## Writing it back

`work update <map-id> --set-description "<body>"` **replaces** the description; there is no append. So the sequence is always read, edit, write:

1. `work show <map-id>` and take the current description.
2. Make your edit to it.
3. Write the whole edited body back.

Do that immediately before writing, not at the start of the session. Other sessions may be working the same map in parallel, and a body composed against a stale read silently drops whatever they added in between.
