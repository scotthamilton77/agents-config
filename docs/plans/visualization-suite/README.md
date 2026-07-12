# Visualization Suite — design exploration (agents-config-yf2ov.2)

Working material for the M5 visualization-suite epic: use-case selection, an
interactive V1 (PR-shape) prototype, and the design findings that will feed the
grouped dated spec in `docs/specs/`. The spec is the deliverable; everything
here is the evidence trail behind it.

## Contents

- `findings.md` — the running findings log: per-variant verdicts from
  user-reaction rounds, 15 extracted design principles (spec input), and the
  fabrication ledger (what's real vs mocked in the prototype).
- `HANDOFF.md` — session handoff: decisions made, state, and the next actions
  for a fresh context to continue (V2/V3 brainstorm → grouped spec).
- `prototype/` — the V1 PR-shape heat-map prototype (throwaway by design,
  versioned for continuity of the design conversation):
  - `pr-shape-proto-v3.html` — **the artifact**: fully self-contained (d3 +
    data inlined), just open it in a browser. Three variants — A Estate
    treemap, B Dependency constellation, C Attention ledger — switchable via
    the bottom pill or arrow keys. Light/dark toggle, weight sliders,
    drill-down panels, notes-to-agent affordance.
  - `shell.html` — the contract shell (heat math, drill panel, switcher,
    themes, notes). Variants plug in via `PROTO.registerVariant`.
  - `variant_A.js` / `variant_B.js` / `variant_C.js` — the three live view
    modules. `variant_D.js.retired` — the Impact sonar, retired in round 3
    (ring adjacency implied unasserted relationships); kept for reference.
  - `gen_data.py` — builds `data.json` from real repo bones (git ls-files,
    graphify in-degrees, PR #238 numstat) plus fabricated scores/stories.
    Requires `graphify-out/graph.json` at the repo root.
  - `assemble.py` — inlines data + variants (+ `d3.min.js` if present beside
    it, else the artifact keeps a CDN reference) into one HTML file.

## Regenerating

```bash
python3 prototype/gen_data.py          # writes data.json beside the scripts
python3 prototype/assemble.py out.html # inlines the variant_A–D files that exist
```

Note: paths are derived from the script location (repo root via
`git rev-parse` for `gen_data.py`) — throwaway tooling, not a build system.

## Status

Round 3 delivered 2026-07-11. V1 signal considered sufficient; next phase is
the V2 (work-DAG / multi-plan overlay) and V3 (topical evolution) brainstorm,
then the grouped spec. See `HANDOFF.md`.
