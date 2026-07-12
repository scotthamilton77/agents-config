# V2 multi-plan overlay — shared build conventions (round 1)

Every variant is a SINGLE self-contained HTML file: d3 v7 inlined or CDN
`<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>` (CDN acceptable for
round-1 scratch), data inlined as `const DATA = {...}` from `v2_data.json`.
No fetch(), no localhost dependency, no external CSS. Opens via double-click.

## Question under test (round 1)

Which organization makes CROSS-PLAN relationships and their TIMING legible —
"when does plan A come to depend on / collide with / reinforce plan B, and
where in the codebase?" The viewer decides: resequence, reprioritize, redesign.

## Data contract

`v2_data.json` — shape:
- `plans[]`: {key, label, color_slot (0-4), status, steps[]}
  - `steps[]`: {id, label, order (1-based), status: done|in_progress|open|deferred, surfaces[] (region keys)}
- `regions[]`: {key, label, kind: package|skills|rules|docs|config|infra}
- `edges[]`: {id, from:{plan, step_order}, to:{plan, step_order},
   kind: dependency|overlap|conflict|synergy,
   provenance: encoded|inferred,
   materializes: "<plan>:<step_order>" (the step at which this edge becomes live),
   story (1-2 sentences, WHY), evidence (bead id | spec cite | "agent-inferred")}

## Visual encoding (identical across variants — this is the comparison spine)

Plan identity (categorical, fixed slot order, direct-label everywhere — relief
rule for light-mode aqua/magenta):

| slot | plan | light | dark |
|---|---|---|---|
| 0 | prgroom | #2a78d6 | #3987e5 |
| 1 | workcli | #1baf7a | #199e70 |
| 2 | pdlc | #4a3aa7 | #9085e9 |
| 3 | postfable | #e87ba4 | #d55181 |
| 4 | reviewloop | #eb6834 | #d95926 |

Edge encoding — two ORTHOGONAL channels, never color-alone:
- **provenance → line solidity**: encoded (exists in beads DAG) = solid;
  inferred (agent-read from specs/prose) = dashed (6,4 dash).
- **kind → color + midpoint glyph badge**:
  - dependency: secondary ink (light #52514e / dark #c3c2b7), glyph "→"
  - overlap: #fab219, glyph "≈"
  - conflict: #d03b3b, glyph "✕"
  - synergy: #0ca30c, glyph "+"

Step status: done = filled solid; in_progress = filled + ring; open = outlined;
deferred = outlined + 40% opacity. Never color-alone: pair with a small badge
or stroke treatment.

## Chrome & ink (CSS custom properties on `.viz-root`, light default + `.dark`)

| role | light | dark |
|---|---|---|
| surface | #fcfcfb | #1a1a19 |
| page | #f9f9f7 | #0d0d0d |
| text-primary | #0b0b0b | #ffffff |
| text-secondary | #52514e | #c3c2b7 |
| muted | #898781 | #898781 |
| gridline | #e1e0d9 | #2c2c2a |
| baseline | #c3c2b7 | #383835 |
| border | rgba(11,11,11,.10) | rgba(255,255,255,.10) |

Font: `system-ui, -apple-system, "Segoe UI", sans-serif` everywhere.
`tabular-nums` only in aligned columns.

## Hard requirements (V1 lessons — spec-grade, do not skip)

1. **Legend always present**, explaining BOTH channels (solidity + kind color/
   glyph) and plan colors. Legend text in ink tokens, never series color.
2. **Deterministic layout**: no force-sim jitter on load. If force layout used,
   pre-settle synchronously (run N ticks before first paint) with a fixed seed
   strategy; never restart sim on hover/toggle.
3. **Light mode default, dark toggle** (single button top-right; `.dark` class
   swap on `.viz-root`).
4. **Escape ALL data-derived text** before DOM insertion: use `textContent` /
   d3 `.text()`, never string-interpolated innerHTML with data values.
5. **Drill panel**: click any edge → side panel with story, evidence,
   provenance, materialization step, both endpoints. Click any step → label,
   status, plan, surfaces (region labels), bead/doc evidence. Panel has a
   close button; Escape closes; content is data-bound (escaped).
6. **Hover layer**: tooltips on all marks (edge, step, region). Hit targets
   ≥ 12px even where the mark is thinner (invisible widened hit path).
7. **No console errors.** Verify before declaring done.
8. **One header line** stating the variant name + the round-1 question, and a
   footer line: "Round-1 reaction mockup — data part-real (beads/specs),
   part-authored (inferred edges); see fabrication ledger."

## What round 1 deliberately OMITS

Notes-to-agent affordance (validated in V1, carried by F0), weight sliders,
intra-step detail, real file-level footprints (region-level only).
