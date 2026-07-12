# Variant C — "Plan constellation" (relational-primary)

Stance: PLANS are the scene; the codebase appears only on demand. Cross-plan
relationships read as a typed graph between plan super-nodes; best for "which
plans relate at all, and how much" triage.

## Layout

- 5 plan super-nodes: rounded-rect cards (~200×120), plan-color 3px border +
  very light plan-color fill wash, title + status line in ink. Positioned by a
  PRE-SETTLED force layout (run the sim to convergence synchronously before
  first paint; then fixed — no live sim). Draggable cards (drag re-pins;
  edges follow).
- INSIDE each card: the plan's step sequence as a mini strip — small squares
  in a row (status treatment per conventions), step order left→right. Hover a
  square → step tooltip. This is a miniature, not a full DAG — legibility
  over completeness.
- CROSS-PLAN EDGES between cards: BUNDLED per plan-pair — one visual link per
  (pair, kind) combination, thickness = ln(1+count)*2.5px capped 8px. Kind
  color + solidity per conventions (if a bundle mixes encoded+inferred, render
  dashed and note "mixed" in drill). Midpoint glyph badge + count label
  ("→ 3"). Curved links; separate parallel bundles of different kinds with
  distinct curvature offsets so they never overlap.
- Edge ANCHORING carries timing: each bundle's endpoint attaches to the card
  edge NEAR the mini-strip square of the earliest involved step (approximate:
  left third = early steps, right third = late steps). A small tick connects
  bundle endpoint to that square. This is C's answer to "when" — imperfect by
  design; the drill carries exact steps.
- Click a bundle → drill panel lists EVERY underlying edge: story, evidence,
  provenance, from-step → to-step, materialization, and the REGIONS that edge
  flows through (region labels as chips). This is the only place the codebase
  appears.
- Click a card → plan drill: scope line, step list with statuses, total
  in/out edge counts by kind.

## Legend: plan chips, edge kinds, solidity, bundle-thickness note, status
treatments. Drill/hover per conventions.

## What this variant must make easy (evaluation intent — do not print in UI)

- Instant triage: which plan-pairs have relationships at all; where conflict
  red shows up.
- Whether losing the codebase substrate from the main scene hurts — that is
  the question C exists to ask.
