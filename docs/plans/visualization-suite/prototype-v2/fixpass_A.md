# Fix pass — Variant A (flight-plan lanes)

Target file: `v2_variant_A.html`. Apply `fixpass_common.md` fixes 1–3, plus:

1. **BUG — lane-label chips**: every one of the five lanes must render a
   colored circle chip (plan hue) left of its lane label. Currently only two
   of five do. Find why (likely a data/join or overlap issue) and fix so all
   five always render.
2. **Materialization slider**: remove the main-area effect (edge translucency
   modulation as the slider moves) — edges render at full normal opacity
   regardless of slider position. KEEP the substrate-strip accumulation below
   (blocks appearing as the guide moves right) exactly as is, and keep the
   slider guide line.
3. **Captions**: label the lane area's axis `plans` (small muted caption near
   the lane labels) and the bottom substrate strip `regions` (small muted
   caption). Secondary/muted ink, unobtrusive.
4. **Plan-inclusion filter behavior** (common fix 2): excluding a plan hides
   its lane and the remaining lanes reflow upward to close the gap; its
   edges and its substrate-strip contributions disappear too.
5. Do not change: lane ordering, the ordinal shared x-scale, step circle
   sizing/status encoding (except the deferred mark redesign), drill panels'
   content, edge colors/solidity semantics.
