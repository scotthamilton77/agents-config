# Fix pass — Variant B (territory map)

Target file: `v2_variant_B.html`. Apply `fixpass_common.md` fixes 1–3, plus:

1. **FIX-SOON — opaque surfaces**: the drill drawer and tooltip are partially
   transparent and hard to read over underlying text. Make both fully opaque:
   background `--surface-1` (light `#fcfcfb` / dark `#1a1a19`), 1px hairline
   border, subtle drop shadow. No translucency, no backdrop-filter reliance.
2. **Kind-group containment**: multi-tile kind groups (SKILLS, DOCS, …) need
   a visual grouping affordance — a rounded-rect background wash behind each
   group's tiles (light `#efeee9`, dark `#232322`), ~6px padding around the
   group's tile extent, with groups clearly non-contiguous (visible page-
   background gap between neighboring washes). The wash sits under tiles and
   must not obscure the contested hatch. Groups packed across shared rows may
   need one wash rect per contiguous run — compute from the live tile
   positions, not hardcoded.
3. **Define "contested" in-UI**: legend entry with the hatch swatch and text
   `contested — 2+ plans claim work in this region`; the tooltip on a
   contested tile names the contesting plans.
4. **Drawer tracks the step slider**: drawer content re-renders when the
   slider moves; steps beyond the current slider position get a disabled
   look (muted ink, desaturated chip, an `upcoming` tag). Steps at or before
   the position render normally.
5. **Step-status legend**: the main legend's orphaned "STEP STATUS (DRILL
   PANEL)" block shows marks the main scene never displays — remove it from
   the main legend and render a compact status key inside the drawer footer
   instead (where the marks actually appear).
6. **aria-hidden warning**: on drawer close, `document.activeElement.blur()`
   (when the focused element is inside the drawer) BEFORE hiding, so the
   console warning stops.
7. **Plan chips → inclusion toggles** (common fix 2): upgrade the existing
   legend-chip isolate into true include/exclude toggles; keep hover
   highlight behavior for included plans. Excluding a plan removes its
   territory strips; a region whose only claims came from excluded plans
   loses its contested hatch accordingly.
8. Do not change: the greedy row-packing layout, tile sizing, edge
   colors/solidity semantics, the step-scrubber mechanics.
