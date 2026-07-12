# Variant A — "Flight plans" (temporal-primary)

Stance: TIME is the scene. Cross-plan relationships read as arcs between
parallel timelines; "when does A need B" is answered by x-position alone.

## Layout

- One horizontal lane per plan (5 lanes), lane label left (plan color chip +
  name + status), lanes ordered by data order.
- Within a lane: steps as nodes left→right by `order`. X-scale is ORDINAL by
  step order (not calendar time) — equal spacing, shared across lanes so
  step 3 of every plan aligns vertically. Label each node (short step label,
  truncate + full label in tooltip). Connect consecutive steps in a lane with
  a thin baseline-colored link (the plan's internal sequence).
- Step marks: 14px circles, plan color, status treatment per conventions.
- CROSS-PLAN EDGES: arcs between step nodes in different lanes. Arc anchored
  at `from` step and `to` step; kind color + solidity per conventions; glyph
  badge at arc midpoint (small circle, surface fill, glyph char). Edge
  thickness 2px, hover widens hit area.
- A vertical "materialization scrubber" line: draggable vertical guide. As it
  moves right, edges whose `materializes` step is LEFT of the guide render
  full-strength; future edges render at 25% opacity. Default position:
  between "done" and "not-done" frontier (compute: max order where any plan
  has a done step, +0.5). This is the "when does this bite" affordance.
- Below the lanes: a compact SUBSTRATE STRIP — one column per region (region
  label rotated 45° or truncated horizontal). For each plan-step at or left of
  the scrubber, drop a small plan-colored tick into the region columns it
  touches (`surfaces`). Two+ plans ticking the same region → the region column
  header gets an amber underline (shared territory at current scrubber time).
  Clicking a region column → drill listing which plans/steps touch it.

## Drill/hover per conventions. Legend: plan chips, edge kinds, solidity, status.

## What this variant must make easy (evaluation intent — do not print in UI)

- "Plan A step 4 depends on plan B step 2 — and B hasn't started it" should be
  visible in one glance (arc from an outlined node crossing lanes).
- Dragging the scrubber right = watching the future arrive: which edges bite
  next.
