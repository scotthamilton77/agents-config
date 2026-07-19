# Grind dashboard renderer — design

**Bead:** `agents-config-wgclw.30.3`
**Status:** accepted — visual design chosen (UX §9); implementation proceeds under `.30.3`

Companion to the event-sourced grind runtime spec (same date), which defines
the event log, fold, and `grind` CLI this renderer projects from. This spec is
split out so the visual design could be explored through UI prototypes before
implementation; the contract below is settled, and the chosen look is
recorded in UX §9.

## Problem

`dashboard.html` is currently rendered by the `bookkeeper` agent from a
hand-merged `state.json` — a model doing a script's job. The runtime spec
retires the bookkeeper; this spec defines its replacement: `grind render`, a
deterministic projection from the folded state to a single self-contained
HTML file. The current template also has known UX defects, catalogued below
from human review of the `.44.2` grind dashboard — a renderer that merely
reproduces the current template does **not** satisfy this spec.

## Contract (settled)

Carried over from the current dashboard contract, unchanged:

- **Light theme only.** No dark mode, no toggle. Accessibility requirement.
- **Self-contained `file://` page** — state inlined, no server, no fetches.
- **Serialization contract**: state is spliced into an inline `<script>`
  block via a real JSON serializer with every `<` escaped as `\u003c` (the
  existing rule from the grind state schema — a raw splice is a
  script-injection hole; text originates outside the grind).
- **Real PR links** derived from the grind's `repo` slug (explicit `url`
  overrides; no slug → plain-text number).
- **15-second auto-refresh with a visible on/off toggle** (persisted in
  `localStorage`) and a **visible last-generated timestamp** — the `ts` of the
  last folded event, so the board reads as fresh as its log, never fresher.
- **Red ATTENTION banner**, hidden when empty.
- **Horizontal scroll on overflow** — never squeeze lanes into illegibility.
- **Unknown status values degrade** to neutral styling, never break the board.

New, from the runtime spec:

- The renderer is a **pure function of folded state** — same state, same
  bytes. No wall-clock reads at all: `last_generated` is the `ts` of the last
  folded event, not a render-time clock, so repeated renders of the same log
  are byte-identical — this is what makes the CI smoke test a byte-comparison.
- Renders the **pause banner** (`grind_paused`), the **lessons panel**
  (LESSON observations), and **anomaly surfacing** (ERROR observations reach
  the ATTENTION banner via the fold — the renderer just draws the list).

## UX requirements (settled — from human review of the .44.2 dashboard)

1. **Lane collapse/expand**: a persistent per-lane toggle on **every** lane —
   not only done ones — with collapse state persisted in `localStorage`
   alongside the refresh preference. (Auto-collapse of `done` lanes remains
   the default initial state.)
2. **Collapsed lane anatomy**: status icon + work-item id + title + PR#.
   Drop item notes and the agent/activity line. Collapsed width ≈ **50% of
   expanded** — the current 210px column overflows its own padding and pushes
   content out of bounds.
3. **Status icons for all nine status values** (queued, in-progress, pr-open,
   in-review, merged, done, blocked, waiting-human, standing-down), since any
   lane can now be collapsed and icons become the only status signal.
4. **Parking-lot kind chips**: each entry renders its kind
   (discovered-work / human-gated / later-wave / deferred) as a visually
   distinct chip.
5. **Lessons-learned panel**, fed by LESSON-level observations.
6. **Drop the Merged and Closed panels entirely** — the event log is the
   ledger; replay supersedes their compaction-recovery role.
7. **Review thread pill reads as a full label** ("1 open thread", not
   "1 open"), with a `title`-attribute tooltip carrying `review.detail`.
8. **Review round badge hides at `done`** — a high round count survives as a
   LESSON, not a badge on finished work.
9. **Chosen visual design — "Control Room"**: column-per-lane kanban board,
   icon-forward status (large glyphs, colored column-top strips, small text
   pills), control-room density, with the parking lot / lessons / observation
   log docked as a panel strip beneath the board — and a **mission line in
   the header**: the topbar carries `state.mission` as a muted full-width
   line under the title row. Reference prototype:
   `docs/prototypes/grind-dashboard/variation-a.html` (mission header
   included); shared fixture: `docs/prototypes/grind-dashboard/fixture-state.json`.

## Input

The renderer consumes the fold's `State` (runtime spec) — it never reads
`events.jsonl`. Fields it draws from: grind header (title, repo, mission,
pause),
lanes with derived statuses and queues, per-item review state (kind, round,
derived `open_threads` / `wont_fix_count`, stalemate flag, `detail`),
parking lot with kinds, attention list, lessons, `last_generated`.

Review counts and item statuses arrive **pre-derived** — the renderer
computes nothing about the domain, it only lays out typed fields. Any place
the current template parses prose out of a note is a defect to delete.

## Prototypes

Three radically different single-file variations live at
`docs/prototypes/grind-dashboard/` (chooser: `index.html`; per-variation
design theses: `README.md`), all rendering the shared `fixture-state.json`.
The chosen design is UX §9's Control Room (variation A, mission header
included); the other variations are retained for reference.

The **fixture state** is built once and shared by the prototypes and the CI
smoke test: all nine statuses represented, every parking kind, an active
review with findings, a stalemate, a paused banner variant, ≥6 lanes (to
exercise overflow), long titles, and a `</script>`-bearing title (to prove
the serialization contract).

## Testing

- **CI smoke test** (gates `.30.3`): render the fixture state; assert output
  is byte-stable across two runs, contains no unescaped `<` inside the state
  block, and renders every status icon, kind chip, and panel the UX section
  requires (string/DOM-level assertions, not screenshots).
- Renderer unit tests: PR-link derivation order; unknown-status degradation;
  empty-state edges (no lanes, empty attention, no lessons).

## Continuations

- none beyond the existing bead — `agents-config-wgclw.30.3` implements this
  spec; the chosen visual design is recorded in UX §9 and referenced from
  `docs/prototypes/grind-dashboard/`.
