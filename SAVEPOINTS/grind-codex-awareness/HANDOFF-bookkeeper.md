# HANDOFF — Bookkeeper

This file documents the state and conventions for maintaining the grind dashboard.

## Files

- **`state.json`** — Single source of truth for all dashboard data. Machine-read, machine-written.
- **`dashboard.html`** — Rendered from state.json. Inlines the state object (not fetched), so the page works from `file://` with no server.

## State Schema

See `/Users/scott/.claude/skills/orchestrated-grind/references/state-schema.md` for the canonical schema.

Key top-level fields:
- `title` — Dashboard heading
- `repo` — `owner/name` slug for deriving PR URLs
- `last_generated` — ISO-8601 UTC timestamp of the last render
- `attention` — Array of escalations for the human (red banner); empty hides it
- `lanes` — Array of lane objects (eligibility, polling)
- `merged` — Array of merged PRs
- `closed` — Array of closed beads
- `parking_lot` — Array of discovered work (not in any lane queue)
- `caveat` — String describing known issues or constraints (displayed prominently)
- `grind_final` — Boolean; true when grind is halted
- `run_status` — Human-readable status string

## Rendering Process

1. Load `state.json` as a Python dict
2. Serialize with `json.dumps(state, indent=2)`
3. **CRITICAL**: Escape every `<` as `<` to prevent script injection (state carries external text like PR titles)
4. Read the dashboard template from `~/.claude/skills/orchestrated-grind/dashboard-template.html`
5. Find the `const STATE = {...}` block in the template
6. Replace the entire block (opening brace to closing semicolon) with the escaped JSON
7. Write the result to `dashboard.html`

## Update Protocol

When ROOT sends a STATE DELTA:

1. Load `state.json`
2. Apply the delta (merge dicts, append arrays, update timestamps)
3. Serialize and render the dashboard (steps 1–7 above)
4. Reply to ROOT via SendMessage (one line confirming the update)
5. Park (no further action)

## Conventions

- **PR links**: Derive from top-level `repo` slug + PR number, unless a `pr.url` override is set
- **Review badges**: "kind · round N" format (e.g., "codex · round 1"); show open_threads and stalemate flags
- **Lane status**: "done" lane collapses to narrow column; "standing-down" is used for final halt
- **Descopes**: Display as "adjudicated" or "endorsed descope", never as "done as specified"
- **FINAL state**: When halted, the dashboard includes a FINAL notice and both lanes show "standing-down"
- **Caveat section**: Displayed prominently; update only when known issues emerge or resolve

## Discovered Work Count

At grind halt (2026-07-19), the parking_lot contained 8 discovered work items:
1. wgclw.31 (P0) — gate reviews wrong worktree
2. wgclw.32 (P0) — gate refuters fabricate evidence
3. abn9.44.10 (P1) — Phase 9 vs merge floor disagreement
4. abn9.44.13 (P1, DEADLINE 2026-08-01) — reviewer-login identity mismatch (LIVE in merged code)
5. abn9.44.14 (P2) — initial poll freshness gap
6. wgclw.33 (P1) — gate-triage uncommitted changes
7. abn9.44.15 (P2) — TOCTOU window
8. abn9.44.16 (P2) — grind event-log channel

Items assigned to lanes (not in parking_lot):
- abn9.44.9 (P1) — in lane-eligibility queue
- abn9.44.12 (P2, blocked) — in lane-eligibility queue

ROOT's count of 11 differs from this count of 8 + 2 = 10. Verify the actual count by inspecting state.json.

## Final State (2026-07-19)

- **6 PRs merged**: #353, #354, #356, #359, #360, #363
- **6 beads closed**: abn9.44.3, abn9.44.2.9, abn9.44.9, abn9.44.11, m5tkg
- **Both lanes halted**: lane-eligibility in DESIGN HALT on abn9.44.4; lane-polling in directed review on abn9.44.7 (verdict unknown)
- **Dashboard**: Marked FINAL; not a live tracking board going forward
