# Fix pass — common spec (demo readiness)

Context: the three V2 prototypes (`v2_variant_A.html`, `v2_variant_B.html`,
`v2_variant_C.html`) passed a user reaction round and are being demoed to a
colleague. This pass applies usability fixes from that feedback. Each builder
edits ONE variant file in place. Do not touch `v2_data.json`,
`shared-conventions.md`, or the other variants' files. Read
`shared-conventions.md` first — its encoding spine and hard requirements still
bind. Keep diffs minimal; do not reformat wholesale.

## Cross-cutting fix 1 — deferred mark redesign

The old treatment (outline + 40% opacity) is illegible. Replace everywhere a
deferred step or plan renders:

- **Deferred step**: full-opacity circle, 1.5px outline in the plan hue,
  transparent fill, with a pause glyph centered inside — two short vertical
  bars (each ~1.2px wide, ~5px tall, 2px apart) in secondary ink
  (`--text-secondary`). NO opacity dimming. Same size as other step circles.
- **Deferred plan** (whole-plan level, where applicable): a small pill badge
  reading `❚❚ PARKED` — muted background (`--gridline`-ish), secondary ink,
  fully readable — plus a dashed border on the plan's container. No heavy
  opacity cut; content stays legible.
- Update the legend: swatch showing the new mark, label `deferred (parked)`.
  Remove any stale "40% opacity" legend text.

## Cross-cutting fix 2 — plan-inclusion filter

Every view gets a first-class control choosing WHICH plans participate:

- A control row directly above the canvas, captioned `plans:` — one toggle
  chip per plan: colored dot (plan hue) + plan name. Included = filled chip
  (subtle plan-tinted background). Excluded = gray outline chip, dot grayed.
  Click toggles. An `all` reset link at the row's end. Use real `<button>`
  elements (keyboard accessible, `aria-pressed`).
- Excluding a plan removes it from the scene: its marks disappear AND every
  cross-plan edge touching it disappears. Per-variant behavior is in the
  variant brief. Re-including restores deterministically.
- If the drill panel is showing content for an excluded plan, close it.
- If the variant already has plan chips (B), upgrade them in place rather
  than adding a second row.

## Cross-cutting fix 3 — edge-kind badge chips

Edge midpoint glyph badges currently read as circles and get confused with
step circles. Replace the badge form in ALL variants:

- Rounded rect ~18×14, rx 4, fill = the edge-kind color, stroke 1.25px
  `rgba(11,11,11,0.55)` light / `rgba(255,255,255,0.55)` dark, glyph
  (→ / ≈ / ✕ / +) white bold ~9px centered.
- PRESERVE the enlarged invisible click target (≥18px, `pointer-events: all`)
  and all existing badge click handlers — playwright and users click the
  badge, not the curve.
- Update legends to show the chip form.

## Hard requirements (unchanged from shared-conventions.md)

- Self-contained file; d3 via CDN acceptable; no other network deps.
- Escape ALL data-derived text (names, stories, evidence, paths) before DOM
  interpolation — `textContent` or an HTML-escape helper, never raw
  innerHTML interpolation.
- Both themes must keep working: theme toggles by applying/removing `.dark`
  on `document.documentElement` and `body`; all colors flow through CSS
  custom properties.
- Every visual encoding appears in a legend. Legends must reflect every
  change this pass makes (new deferred mark, chip badges, filter chips).
- Deterministic layout — no randomness, no re-simulation on encoding-only
  changes.
- Zero console errors on load and during the interactions in your brief.

## Return format

Return ONLY a JSON object:
`{"variant": "A|B|C", "changes": ["..."], "legend_updated": true, "risks": ["..."]}`
