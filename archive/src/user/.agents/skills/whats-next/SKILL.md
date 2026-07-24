---
name: whats-next
description: Surfaces the right beads work list for the current session. Use when the user asks what work is available, what work is ready, what needs attention, what to work on next, what to brainstorm, what to plan / decompose, or what to implement. Do NOT use for checking a specific bead.
model: sonnet[1m]
---
<!-- FIXME this is bead-based and needs to be refactored to be abstracted from beads (with plugin extensions) -->

# whats-next

Surface the right work list for the current user intent. One skill, five modes.

## Step 0: Determine mode from the user's exact message

**Do this before collecting any data.** Re-read the user's message word-for-word and map intent to a `--mode` value:

| User intent (exact phrasing) | `--mode` value |
|---|---|
| No qualifier — "what's next", "what should I work on" | `all` |
| "what needs attention", "human escalations" (explicit) | `human` |
| "brainstorm", "what's next to brainstorm", "ready to brainstorm" | `brainstorm` |
| "implement", "implementation-ready", "run-queue", "what to implement" | `implementation` |
| "planning", "planning-ready", "needs decomposition" | `planning` |

`all` is the entry mode: it shows all modes: attention items, planning-ready containers, brainstorm-ready, and the implementation queue.

Lock in the mode now. Do not infer intent from prior conversation — the user's exact words are the only signal.

## Step 0b: Detect a topic filter

If the user scopes the request to a topic — "what's next **for the installer**", "anything ready **on the docs**", "implement-ready **CLI** work — derive a single canonical label and pass it as `--label`.

**Reduce the qualifier to its canonical (stemmed/root) label.** Labels in this project use one consistent reduced form of a word-family, so map every surface variant to the root:

| User says (any variant) | Canonical `--label` |
|---|---|
| installer, installation, installing, install | `install` |
| docs, documentation, documenting | `docs` |
| (general rule) | the shortest root the word-family shares |

The filter is a case-insensitive exact match on each bead's own labels — it does not match ancestors or do substring matching, so pass the exact canonical label, not a phrase. If a filtered query returns nothing, say so plainly (don't silently widen to the unfiltered list) and offer to retry without the filter.

No topic in the message → omit `--label` entirely.

## Step 0c: Detect a "show everything" request

The default presentation is the top 10 per section. If the user's message up front asks to see all of it — "show me **everything** that's next", "show **all**", "**full list**" — pass `--limit 0` from the start so nothing is hidden. A follow-up "show more" / "show all" / "show the rest" after a truncated render is the same signal: re-run with `--limit 0`. Otherwise keep the default.

## Step 1: Collect data

Run the helper script with the chosen mode. Default limit is 10 per section. Pass `--limit 0` for the complete, untruncated list. `--label` (Step 0b) restricts every section to beads carrying that label. Examples below:

```bash
python3 "${CLAUDE_SKILL_DIR}/collect.py"                   # all mode (default)
python3 "${CLAUDE_SKILL_DIR}/collect.py" --mode brainstorm
python3 "${CLAUDE_SKILL_DIR}/collect.py" --mode implementation
python3 "${CLAUDE_SKILL_DIR}/collect.py" --mode planning
python3 "${CLAUDE_SKILL_DIR}/collect.py" --mode human
python3 "${CLAUDE_SKILL_DIR}/collect.py" --label install    # only install-labeled beads
python3 "${CLAUDE_SKILL_DIR}/collect.py" --limit 0          # show everything, no truncation
```

The script returns a JSON object whose top-level `mode` field carries the requested mode. Section keys vary per mode — **absent sections are absent from JSON, not empty arrays**:

| `--mode` value | Section keys emitted |
|----------------|----------------------|
| `all` (or omitted) | `human`, `planning_ready`, `brainstorm`, `implementation` |
| `brainstorm` | `brainstorm` only |
| `implementation` | `implementation` only |
| `planning` | `planning_ready` only |
| `human` | `human` only |

Top-level shape:

```json
{
  "mode":           "all",
  "project_prefix": "agents-config",
  "limit":          10,
  "totals": {
    "human":          0,
    "planning_ready": 3,
    "brainstorm":     42,
    "implementation": 6,
    "in_flight":      19
  },
  "human":          [ ...beads ],
  "planning_ready": [ ...beads ],
  "brainstorm":     [ ...beads ],
  "implementation": [ ...beads ],
  "in_flight":      [ ...in-flight beads ]
}
```

Each bead entry (already prefix-stripped and typed-ancestor split):

```json
{
  "id":              "agents-config-ffxh",
  "short_id":        "ffxh",
  "priority":        1,
  "title":           "...",
  "labels":          [...],
  "milestone_col":   "abn9",
  "feature_col":     "vaac",
  "parent_epic_col": "7bk.13",
  "type":            "task"
}
```

- `id` — full bead ID (use for any `bd` operation that needs the canonical ID)
- `short_id` — prefix-stripped ID; **use for display**
- `milestone_col` — nearest `milestone`-type ancestor short_id, or `""`
- `feature_col` — nearest `feature`-type ancestor short_id, or `""`
- `parent_epic_col` — immediate parent short_id (regardless of type), or `""`
- `type` — the bead's `issue_type`

All sections are pre-sorted: **priority ascending (P0 first), then `created_at` ascending**.

`in_flight` is a different kind of section: a cross-cutting audit of every
`in_progress` bead, not one of the four work-queue lists above. It is
**mode-independent** — present in every `--mode` value's output, never gated
or truncated by `--mode` or `--limit` (unlike the four queues, its whole
point is showing every stale claim, not a top-N sample) — matching the
always-present `totals` field. Each entry:

```json
{
  "id":              "agents-config-wgclw.15",
  "short_id":        "wgclw.15",
  "title":           "...",
  "assignee":        "Scott Hamilton",
  "claim_age_days":  1,
  "pr_flagged":      true
}
```

- `assignee` — `""` if unassigned
- `claim_age_days` — whole days since the bead's status transitioned to
  `in_progress`; `null` if bd returned no usable timestamp
- `pr_flagged` — `true` when the bead's notes contain a GitHub PR URL,
  meaning the work may already be merged and the claim just wasn't closed
  out

Sorted **oldest claim first** (largest `claim_age_days` first).

## Step 2: Render sections

Skip any empty queue section (`in_flight` is exempt — it always renders its summary line; see Step 3).

| Section key | Heading |
|---|---|
| `human` | **Needs your attention** |
| `planning_ready` | **Planning-ready** |
| `brainstorm` | **Ready to brainstorm** |
| `implementation` | **Ready to implement** |
| `in_flight` | **In flight (claimed)** |

`all` mode renders attention + planning-ready + brainstorm + implementation queue in that order. `in_flight` renders **last, in every mode** — it's a cross-cutting audit, not one of the mode-selected queues, so it always appears after whatever queue(s) the requested mode surfaced.

## Step 3: Present

If the collected JSON carries a top-level `backlog_grooming_nag` string, prepend it as one dismissible line before any section, labeled unmistakably **Backlog Grooming** so it is never confused with CONTEXT.md's separate Holding-Place Grooming Nag (a different ceremony, a different timestamp) — the two can coexist on this surface once the Holding Place ships. Absent key → render nothing; never fabricate the line.

IDs are already prefix-stripped. Render each list as a 7-column table:

| P | Milestone | Feature | Parent Epic | Bead ID | Type | Title |
|---|-----------|---------|-------------|---------|------|-------|

- **P** — priority digit
- **Milestone** — `milestone_col`; blank if empty
- **Feature** — `feature_col`; blank if empty
- **Parent Epic** — `parent_epic_col`; blank if empty (immediate parent short_id, displayed regardless of type)
- **Bead ID** — `short_id`
- **Type** — `type` field
- **Title** — full bead title, untruncated

Example:

```
| P | Milestone | Feature | Parent Epic | Bead ID | Type    | Title                                        |
|---|-----------|---------|-------------|---------|---------|----------------------------------------------|
| 1 | abn9      | vaac    | 7bk.13      | ffxh    | task    | Audit-trail-required closure for human beads |
| 1 | qn0g      |         | qn0g.1      | owqa    | task    | Add brainstorm-readiness gate                |
| 1 |           |         |             | abn9    | milestone | Milestone M1 — Stabilize and ship          |
| 2 | abn9      |         |             | bf6     | task    | Externalize long bead specs to docs/beads/   |
```

`in_flight` uses its own 5-column table (it carries different fields — no
priority/milestone/type). The `Flag` column holds `⚠ PR` when `pr_flagged`
is `true`, empty otherwise; never interleave annotation lines between table
rows (a bare line inside a markdown table breaks its rendering):

| Bead ID | Title | Assignee | Claim Age (days) | Flag |
|---|---|---|---|---|

When any row is flagged, add one legend line after the table:
`⚠ PR = a PR URL is recorded on the bead — verify the claim is live; candidate for retroactive delivery.`

Example:

```
| Bead ID   | Title                                          | Assignee        | Claim Age (days) | Flag |
|-----------|------------------------------------------------|------------------|-------------------|------|
| 7bk       | Specialized agent fleet (M3 worker fleet)       |                  | 69                |      |
| wgclw.15  | Installer settings.json merge reorders keys     | Scott Hamilton   | 1                 | ⚠ PR |

⚠ PR = a PR URL is recorded on the bead — verify the claim is live; candidate for retroactive delivery.
```

`in_flight` is never subject to `--label` — see the argparse help for why. It is also never subject to `--limit`; every in_progress bead renders, always. This section is an audit, not a work-selection queue, so it renders its own summary line, not the truncation/empty-state lines below: if `totals.in_flight` is `0`, say `No in-progress claims.`; otherwise `N bead(s) currently claimed (in_progress).`

Close with a summary line driven by `totals` (which always carries the full, unfiltered-by-limit count per section). If the displayed count equals the total: `Ready: N beads`. If any section is truncated: name the gap and offer the affordance in plain words, e.g. `Showing top 10 of 42 brainstorm, 3 of 3 planning — say "show all" to see the rest.` When a `--label` filter is active, state it: `Scoped to label "install".` If every section is empty, the empty-state message is mode-specific so it does not falsely point a single-section caller at the human-attention queue:

| `--mode`                | Empty-state line                                                                  |
|-------------------------|-----------------------------------------------------------------------------------|
| `all` (or omitted)      | `All clear — no open beads ready for attention.`                                  |
| `human`                 | `No beads currently flagged for human attention.`                                 |
| `planning`              | `No childless container beads ready for planning.`                                |
| `brainstorm`            | `No beads ready to brainstorm.`                                                   |
| `implementation`        | `No beads ready for implementation.`                                              |

## Red Flags

| Rationalization | Reality |
|---|---|
| "The wording was ambiguous so I used the default `all` mode" | The user's exact words are the signal. Use the intent table; default is the catch-all for absent qualifiers, not ambiguous ones. |
| "I already had context so I inferred intent" | Step 0 says re-read the message. Inference is not re-reading. |
| "They probably meant brainstorm" | Probably is not the same as matching the intent table. |
| "User's stated intent is unwise. Default mode shows everything, so it's safer" | Respect the user's stated intent.  Showing the wrong list is not safer. |
| "Container beads should still appear in impl-ready if labeled" | Container Beads Rule B: structural filter excludes them regardless of label. The migration strips labels; the filter prevents future leaks. |

## NOT For

- `run-queue` autonomous processing — it calls `bd ready --label implementation-ready` directly
- Checking a specific bead — use `bd show <id>`
