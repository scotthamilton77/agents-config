# Variant B — "Territory map" (spatial-primary)

Stance: the CODEBASE is the scene (V1-unification pressure test: same substrate
as V1's estate treemap, plans as speculative overlays where a PR was a concrete
one). Cross-plan relationships read as contested/shared territory.

## Layout

- Substrate: a coarse tile map of `regions[]` — treemap-ish grid where tile
  size is fixed-ish (equal or lightly weighted; region-level, NOT file-level).
  Tile fill: surface; tile border: gridline; label: region name (ink).
  Group tiles visually by `kind` (packages cluster, skills cluster, rules,
  docs, config/infra) with a subtle group gap + group caption.
- Each plan = a TERRITORY: translucent plan-color wash (18-25% opacity) over
  every region tile its steps touch (union of step surfaces), plus a 2px plan-
  color contour around its territory hull... approximate hull with per-tile
  top-edge ribbons if hull is fiddly: each tile shows up to 5 thin plan-color
  strips along its top edge (one per touching plan) — pick ONE approach and
  execute it cleanly; strips are the safer default.
- Region touched by 2+ plans = CONTESTED: fill gets a light diagonal hatch;
  more plans = denser hatch. Hover a tile → tooltip lists plans + step orders
  touching it.
- TIME: a step scrubber (slider top-center, 1..maxOrder). Territories grow:
  at scrubber position k, a plan's wash covers only regions touched by steps
  with order ≤ k. Edges (below) also gate on materialization ≤ k.
- CROSS-PLAN EDGES: arcs drawn between region-tile centroids — from the
  region most representative of the `from` step to the `to` step's region
  (use first surface of each). Kind color + solidity + midpoint glyph per
  conventions. When both endpoints are the same tile, render a small looped
  arc above the tile.
- Plan isolation: clicking a plan chip in the legend dims all other washes to
  5% and shows only that plan's edges; click again to restore.

## Drill/hover per conventions (tile drill lists plans/steps/stories; edge
drill per conventions). Legend: plan chips (clickable), edge kinds, solidity,
hatch = contested, scrubber explanation line.

## What this variant must make easy (evaluation intent — do not print in UI)

- "Where do plans pile up?" — contested tiles pop at a glance.
- Scrubbing time shows territory expansion and WHEN pile-ups begin.
- Whether V1's substrate really unifies with speculative overlays, or whether
  region-level footprints are too coarse to mean anything.
