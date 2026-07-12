# Fix pass — Variant C (plan constellation)

Target file: `v2_variant_C.html`. Apply `fixpass_common.md` fixes 1–3, plus:

1. **FIX-SOON — click/drag separation**: currently the first click arms a
   drag state and the second opens the drawer; switching plans needs the
   dance again. Replace with threshold-based separation: pointerdown records
   the position; pointerup with total movement < 4px = CLICK → open/update
   the drawer for that plan immediately (a single click on a different card
   switches the drawer content); movement ≥ 4px = DRAG (card follows
   pointer). No stateful first click, no double-click requirement.
2. **Canvas zoom + pan**: `d3.zoom` on the SVG — wheel zoom (scaleExtent
   [0.4, 4]), drag on the background pans. Disable double-click zoom. Card
   dragging must NOT pan the canvas (stop propagation from card drag).
   Add a small `reset view` button that restores the identity transform.
3. **Edge direction**: edges read ambiguous — add direction. SVG arrowhead
   markers at the target end, colored per edge kind (one marker def per
   kind color), ~7px, with edge endpoints offset to the card boundary so the
   arrowhead is visible rather than buried under the card. Dashed/solid
   provenance rendering unchanged.
4. **Deferred plan treatment**: the parked plan's card gets the common
   deferred-plan treatment — `❚❚ PARKED` pill badge top-right + dashed card
   border, content fully legible (no heavy opacity cut). Deferred steps use
   the common deferred step mark. Update the legend and delete the old
   "outlined, 40% opacity" description.
5. **Dead space**: cards currently start well below the canvas top — tighten
   the initial layout so the card cluster starts ~24px from the top.
6. **Plan-inclusion filter behavior** (common fix 2): excluding a plan hides
   its card and every edge touching it; if the drawer shows that plan, close
   it. Card positions of remaining plans stay put (no relayout).
7. Do not change: card content structure, edge bundling approach, edge
   colors/solidity semantics, drawer content.
