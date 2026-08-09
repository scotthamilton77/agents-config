# Tracker operations

Every verb this skill uses against the tracker, plus the three that carry a trap. `work` is the tracker, and there is no setup step: never stand up a parallel set of ticket files beside a tracker that exists — a second copy of what the tracker already holds only drifts. If `work` is not installed, or the project has no tracker, keep the map as a single local markdown file instead, with the same sections ([map-body.md](map-body.md)), and skip every verb below.

| What | How |
|---|---|
| Create the map | `work create epic --title "<destination>" --label wayfinder:map (--parent <id> \| --orphan)`; the map body is `--description`. See [map-body.md](map-body.md). |
| Create a ticket | `work create <noun> --title "<the question>" --parent <map-id> --description "<the question in full>"` |
| The ticket's type | the noun: `spike` for research and prototype, `decision` for a grilling question, `chore` for a task |
| An agent may resolve it alone | `--label wayfinder:afk`; without it, the ticket needs the human |
| Blocking | `work dep add <blocked> <blocker>` — "the first depends on the second", wired in a second pass once both ids exist |
| The ticket frontier | `work list --parent <map-id> --status open` — this map's live tickets, the closed and the claimed already out. The blocked are still in, and `work claim` is what rejects them, so the frontier is whatever claims: startable, which is not the same as answerable. Add `--label wayfinder:afk` for what a session can fan out without the human |
| Claim | `work claim <id>` — refuses a blocked or closed ticket, so startability is enforced rather than assumed. On a ticket already in progress it no-ops instead of refusing, so it is not a lock against a concurrent session |
| Resolve | `work close <id> --disposition "<the answer>"` — records the answer and closes, in one call |
| Link an asset | `work note <id> "<pointer to the branch, file or document>"` |
| Rule out of scope | `work close <id> --disposition "Out of scope: <why>"` |
| Update the map | `work update <map-id> --set-description "<the whole new body>"` |

**`--set-description` replaces.** Re-read the map immediately before you write it back, or a concurrent session's line is lost.

**A ticket is invalidated by closing it with a disposition that says so**, never by deleting it — the facade has no delete, and the record of a route not taken is worth keeping anyway.

**`work ready` is absent from that table on purpose.** It is global and takes no parent, so on a tracker carrying anything besides this effort it returns other work alongside this map's, and a session that takes its first result can claim and close a ticket belonging to something else entirely. Scope with `--parent`; let `claim` reject what is blocked.

If tracks are configured and required, the facade refuses the map's create until you pass `--track <name>`, and the refusal lists the choices. Tickets minted under the map inherit its track and need no flag.

## Labels

Two survive, and only two. `wayfinder:map`, because enumerating maps — `work list --label wayfinder:map` — has no other expression, the container noun being shared with ordinary containers. `wayfinder:afk`, because whether a session may resolve a ticket without the human is the thing a session filters on when it fans out, and no field carries it. Everything else the label scheme once carried is now the noun, which is a first-class field; a label restating a field is duplication.
