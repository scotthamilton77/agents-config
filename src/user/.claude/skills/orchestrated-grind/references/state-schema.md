# state.json schema

`state.json` is the bookkeeper's single source of truth. `dashboard.html` is
generated *from* it — the renderer inlines a copy of the state into the page so
the dashboard works from a `file://` URL with no server.

**The bookkeeper's update cycle:** receive a delta from ROOT → merge it into
`state.json` → re-render `dashboard.html` with the new state inlined → stop.
Never open a browser except on first creation.

**Serialization contract.** State strings carry text from outside the grind —
PR titles, review-comment excerpts, branch names. Serialize with a real JSON
serializer and then escape `</` as `<\/` before splicing the result into the
template's inline `<script>` block. A title containing `</script>` otherwise
closes the block early and whatever follows it executes on open. In Python:
`json.dumps(state, indent=2).replace("</", "<\\/")`.

## Contents

- [Top level](#top-level)
- [Lane](#lane)
- [Queue item](#queue-item)
- [Review](#review)
- [PR reference and link derivation](#pr-reference-and-link-derivation)
- [Event](#event)
- [Ledgers](#ledgers)
- [Parking lot](#parking-lot)
- [Status vocabulary](#status-vocabulary)
- [Worked example](#worked-example)

## Top level

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `title` | string | yes | Dashboard heading, e.g. `"Backlog Grind — Lane Status"` |
| `repo` | string | no | `owner/name` slug used to derive PR URLs |
| `last_generated` | string | yes | ISO-8601 UTC timestamp of the last render |
| `attention` | string[] | yes | Items awaiting the human. Empty array hides the banner. |
| `lanes` | Lane[] | yes | One entry per lane, in display order |
| `merged` | MergedEntry[] | no | Merged-PR ledger |
| `closed` | ClosedEntry[] | no | Items-closed ledger |
| `parking_lot` | ParkingEntry[] | no | Human-gated or later-wave items |

`attention` is the red banner. Put an item there only when the grind cannot
proceed on it without the human — a merge-authority question, a reviewer
stalemate, a scope fork. Routine progress belongs in lane events.

## Lane

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | Stable slug, e.g. `"lane-installer"` |
| `name` | string | yes | Display name, e.g. `"Lane 2 — installer"` |
| `agent` | string | yes | Named teammate that owns the lane |
| `status` | string | yes | Lane-level status (see vocabulary) |
| `activity` | string | no | One line on what the lane is doing right now |
| `queue` | QueueItem[] | yes | The lane's work items, in order |
| `events` | Event[] | no | Append-only log; the dashboard shows the most recent few |

**Lane `status` drives layout.** A lane marked `done` collapses to a narrow
column and yields its width to lanes still working. Set it the moment the
lane's queue empties — an active-width column for a finished lane is wasted
space on a crowded board.

## Queue item

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `item` | string | yes | Short description of the work |
| `status` | string | yes | Item status (see vocabulary) |
| `pr` | PR \| null | no | The pull request, once one exists |
| `review` | Review | no | Review state — present while under review |
| `note` | string | no | Free-text qualifier shown under the item |

## Review

Present on any item under review. This is what produces the round badge.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `kind` | string | yes | `codex` \| `copilot` \| `ralf` \| `human` |
| `round` | number | yes | 1-based round counter; increment per review pass |
| `open_threads` | number | no | Unresolved threads at the moment of the update |
| `stalemate` | boolean | no | `true` once the stalemate rule has been tripped |

Round count is the signal that distinguishes a reviewer earning its keep from a
reviewer looping — a badge reading `codex · round 6` with `stalemate: false`
means six rounds of real defects, which is good news, not bad. Set `stalemate`
only per the stalemate rule: a re-raise round on unchanged code.

## PR reference and link derivation

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `number` | number | yes | PR number |
| `url` | string \| null | no | Explicit URL; overrides derivation |

The renderer resolves a PR link in this order:

1. `pr.url`, if a non-empty string.
2. `https://github.com/<repo>/pull/<number>`, if top-level `repo` is set.
3. No link — the number renders as plain text.

Set `repo` once at bootstrap and leave `url` null everywhere; that keeps the
lieutenants' updates terse and the links correct.

## Event

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `ts` | string | yes | ISO-8601 UTC timestamp |
| `text` | string | yes | One line, past tense, self-contained |

Events are append-only. Write them so they still make sense hours later, to
someone who has not read the preceding thousand lines — no bare pronouns, no
labels coined three events ago without a referent.

## Ledgers

`merged` entries: `{ "pr": 315, "title": "installer PR1", "sha": "ee824b650", "lane": "lane-installer" }`

`closed` entries: `{ "id": "work-item-id", "title": "parse null discipline", "pr": 314 }`

Both are flat lists rendered as tables. `sha` and `pr` are optional but worth
carrying — they are the cheapest way for a post-compaction ROOT to reconstruct
what actually landed.

## Parking lot

`{ "item": "supervised backfill sweep", "note": "needs the human in the room" }`

Parked work is *waiting, not blocked* — items deliberately excluded from this
run. Keeping them visible stops a lieutenant from "helpfully" picking one up.

## Status vocabulary

Both lane `status` and item `status` draw from one vocabulary, so a lane's
badge and its items' badges read consistently:

| Value | Meaning |
|-------|---------|
| `queued` | Not started |
| `in-progress` | Being implemented |
| `pr-open` | PR opened, review not yet started |
| `codex-review` | Under bot review |
| `waiting-human` | On the human's docket |
| `blocked` | Waiting on another item to land |
| `merged` | PR merged, post-merge leg possibly outstanding |
| `done` | Merged and fully torn down |
| `standing-down` | Lane only: queue empty, wrapping up |

Unknown values render with the neutral `queued` styling rather than failing, so
a new status word degrades gracefully instead of breaking the board.

## Worked example

```json
{
  "title": "Backlog Grind — Lane Status",
  "repo": "acme/widgets",
  "last_generated": "2026-07-18T20:11:08Z",
  "attention": [
    "PR #320 reviewer stalemate — 3 rounds on unchanged code, all threads resolved. Merge ruling needed."
  ],
  "lanes": [
    {
      "id": "lane-core",
      "name": "Lane 1 — core",
      "agent": "lane-core",
      "status": "done",
      "activity": "standing down — queue empty",
      "queue": [
        {
          "item": "Slice A (config + track field)",
          "status": "done",
          "pr": { "number": 316, "url": null }
        }
      ],
      "events": [
        { "ts": "2026-07-18T16:38:06Z", "text": "Lane initialized." },
        { "ts": "2026-07-18T17:24:24Z", "text": "PR #316 merged (48104af6) — Slice A landed." }
      ]
    },
    {
      "id": "lane-installer",
      "name": "Lane 2 — installer",
      "agent": "lane-installer",
      "status": "codex-review",
      "activity": "PR #320 round-3 triage (5 threads)",
      "queue": [
        {
          "item": "PR2: deploy/prune decision engines",
          "status": "waiting-human",
          "pr": { "number": 320, "url": null },
          "review": {
            "kind": "codex",
            "round": 3,
            "open_threads": 0,
            "stalemate": true
          },
          "note": "all 14 threads triaged + resolved; reviewer re-raises deferred items"
        }
      ],
      "events": [
        { "ts": "2026-07-18T17:53:46Z", "text": "PR #320 stalemate declared — on the human's docket." }
      ]
    }
  ],
  "merged": [
    { "pr": 316, "title": "Slice A — config + track field", "sha": "48104af6", "lane": "lane-core" }
  ],
  "closed": [
    { "id": "core-slice-a", "title": "track layer Slice A", "pr": 316 }
  ],
  "parking_lot": [
    { "item": "supervised backfill sweep", "note": "needs the human in the room" }
  ]
}
```
