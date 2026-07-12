# V1 PR-shape prototype — findings log

PROTOTYPE — wipe me (but fold this file's content into the visualization-suite spec first).
Question under test: which visual representation of a multi-axis PR heat map
(complexity × load-bearing × consequence) best directs human review attention?

## Verdicts so far (Scott, round 1)

- **A Estate treemap — STRONG KEEP.** "Really like this, even though it's very crowded."
  Needed: label declutter (long filenames are the main crowding driver); collapsible
  groups (collapse plans/specs/architecture to a solid block colored by rolled-up
  worst-offender heat); default-collapse groups with no PR impact; expand-group-to-
  fill-screen (e.g. just `packages/`) for more detail.
- **B Dependency constellation — CLOSER (round 3): "if it became less cumbersome, it
  would be useful."** Needs better graph rendering + usability; true utility judgment
  requires experience across multiple real PRs, not one specimen. Round-3 asks: stable
  layout (no re-sim on slider drag; pre-settled, non-scrunched start), fresh-measure
  rendering, and a legend explaining node size / edge width / color / ring encodings.
- **C Attention ledger — STRONG KEEP.** "Really cool way of quickly seeing the PR files."
  Wanted: toggle between separated (PR vs context) and mixed single-ranking views;
  per-file link to that file's diff in the PR; drill panel praised.
- **D Impact sonar — RETIRED as a top-level variant (round 3).** Ring-1/ring-2 segment
  positioning carried no readable meaning ("what are io_port.py and place.py doing above
  backup.py?") — angular adjacency implied relationships the data didn't assert. The
  containment question survives as a per-file drill-down concept: click a file anywhere →
  sonar centered on THAT file's blast radius. variant_D.js kept as .retired for reference.

## Design principles extracted (spec input)

1. **Attention bar for narrative content.** Drill-panel "what to check" items must earn
   human attention: anything mechanically catchable (deleted assertions, lint-class
   findings) does not belong — the tool's premise is directing *judgment*, not
   restating automation. (Trigger: test_ownership.py "any deleted assertions?".)
2. **Weighted-average semantics need in-UI explanation.** Slider = share of importance,
   not volume knob; a file weak on an axis cools as that axis gains weight. Confused
   the user in round 1. Candidates: live mix readout, caption, per-file contribution
   breakdown in drill.
3. **History-based centrality is blind to new load-bearing code** — the PR itself
   creates dependencies (namespaces.py scored 0). Centrality must be projected from
   the post-PR graph (changed imports), not the pre-PR graph alone.
4. **Roll-up coloring**: collapsed containers inherit worst-offender (max) heat, so
   hiding detail never hides risk.
5. **Estate scope**: tracked-only (git ls-files) + curated artifact excludes
   (graphify-out, .beads, archive/, locks, generated). A `.vizignore`-style file for
   tracked-but-boring paths is a plausible future config surface.
6. **Intra-file hotspots**: file-level heat is not the floor — users want function/hunk-
   level hotspots inside the drill (mocked in round 2 for namespaces.py, backup.py).
7. **Annotation round-trip (shared-canvas validation)**: user leaves notes on nodes/files
   in the artifact; notes flow back to the agent for processing (PR comments,
   discussion). Mocked in round 2 via localStorage notes + copy-as-JSON button. This is
   the F0 agent-dialog construct in embryo.
8. **Light mode default, dark toggle** (round 2: implemented in shell).
9. **Self-contained artifacts only** — no server dependency; d3 + data inlined.
10. **Layout reflows around attention** (round 3): collapsing a container should shrink
    it and let siblings absorb the space — collapse is an attention-allocation act, not
    just a label-hiding act. Hierarchical: collapse/zoom must work at every container
    depth (packages/prgroom), not only top level.
11. **Shared-canvas hygiene**: variants render into a shared stage; any inline styling
    of the shared element leaks across views (round-3 bug cluster: drawer/resize
    truncations). Shell now hard-resets stage styles between renders — in the real
    system, view modules get a fresh container, never the shared mount point.
12. **Force layouts must be deterministic-feeling**: pre-settle the simulation before
    first paint, never restart it on encoding-only changes (weight sliders), and keep
    user-pinned positions. Every visual encoding needs a legend.
13. **Text legibility beats decoration**: no text-shadows on small labels; pick label
    color by luminance of the underlying fill, per theme.
14. **The annotation layer must escape user content** (surfaced by the HEAVY-gate
    review): any drill panel, tooltip, or notes field that carries paths, story
    text, or saved notes must neutralize that content before it reaches the DOM —
    bind it as data (`textarea.value` / `textContent`) or HTML-escape it before
    interpolating into markup — never emit an unescaped dynamic value into an
    innerHTML string, or a value containing `</textarea>` or HTML breaks the DOM
    (stored self-XSS). The V1 prototype sets the persisted note via `value` and
    HTML-escapes every interpolated path/story field for this reason; the
    requirement only hardens once notes round-trip through agents or render
    non-local data. Corollary: data-out affordances must never fake success — the
    notes Copy button reports success only when the clipboard write resolves, and
    shows a failure state otherwise.
15. **Centrality tuning — exclude self-edges**: gen_data.py's in-degree counts
    intra-file edges (the majority of graph links are self-file), inflating
    "load-bearing" scores for big self-referential files; the coupling map already
    excludes them. The real scoring model must use a consistent edge set.

## V2 round 1 — multi-plan overlay (Scott, round 1)

Mockups: `docs/plans/visualization-suite/prototype-v2/` — A flight-plan lanes,
B territory map, C plan constellation. Five real specimen plans; 10 cross-plan
edges (1 encoded in beads, 9 agent-inferred from specs).

### Variant A — Flight plans: STRONG KEEP
"Already an awesome tool… showing me insights that I had not seen just dealing
with the beads dependency tree." Passed the value test at a glance; provokes
the intended action-question (drill relationships → redefine/resequence work).

Notes for the FUTURE IMPLEMENTATION PHASE (not prototype fixes unless they
noticeably enhance the reaction experience):

1. **Deferred step status too subtle** (outline + 40% opacity). Explore a
   stronger mark, e.g. circle with a symbol inside.
2. **Edge glyph badges vs step circles**: kind badges (circled +/→) get
   visually distracting next to the step circles on the lanes — differentiate
   the two circle populations.
3. **Lane-label chips inconsistent**: every plan should carry a colored circle
   left of its lane label; only two of five rendered one (bug).
4. **Synthesized steps ↔ backlog structure**: the 4–6 steps per plan were
   agent-synthesized waypoints. Compare each step against the real backlog
   under it — the delta is a signal to restructure the beads hierarchy.
   Feature idea: UI-initiated "recommend work-breakdown revision" action.
5. **Materialization slider**: main-area effect (edge translucency) not
   helpful. The substrate-strip accumulation below IS helpful — blocks
   appearing as the guide moves right.
6. **Labeling**: caption the bottom strip rows "regions" and the lane axis
   "plans".
7. **Region drill drawer must track the slider**: content is static while the
   strip accumulates; should update with slider position, show plan colors,
   and render steps after the slider with a "disabled" look.
8. **Step drill too thin**: should list the underlying work items (beads) in a
   hierarchical view beneath that step.
9. **Edge drill needs visual anchors**: mirror the main display's colors and
   kind symbols (plan chips, kind glyph) in the panel to aid the eye.
10. **Edge drill should carry agent recommendations** captured at discovery
    time, especially for inferred edges — e.g. "this slice could be extracted
    from plan X without disrupting its sequencing, as independent work or
    moved earlier in plan Y so the dependency makes sense."
11. **From/to provenance**: the endpoint text is synthesized and reads
    ambiguous; when an edge corresponds to real bead dependency edges, name
    the beads explicitly.

### Variant B — Territory map: KEEP, usability friction to fix before demos
Value confirmed, with a sharper use-case than briefed: contested regions tell
the viewer "where to be more careful — more guardrails, standards, higher
quality bars in those areas." Contested-ness → quality-policy targeting.

PROCESS DIRECTIVE (Scott): usability fixes below marked FIX-SOON get applied
to the prototypes — plus A's usability items — for colleague-demo readiness,
but only AFTER the full A/B/C feedback cycle concludes. Queued, not started.

1. **FIX-SOON — translucent drawer + tooltip**: partially transparent panels
   are hard to read over overlapping text. Make surfaces opaque.
2. **Step names (low-priority experiment)**: synthesized per-plan step/
   milestone NAMES would beat bare order numbers — B could show the selected
   step's name per plan as the slider moves. Open question: what the same
   naming looks like back on the flight-plans view.
3. **Edge-kind badges need a dark border** around the glyph circle to stand
   out over busy backgrounds (applies to A too).
4. **Kind-group containment**: multi-tile groups (SKILLS, DOCS…) need a
   visual grouping affordance — e.g. a darker background wash behind the
   group's tiles, non-contiguous with neighboring groups.
5. **"Contested" is undefined in-UI**: ambiguous between "conflicting" and
   "touching the same files." Define the term visually/in the legend, and
   sharpen the semantics.
6. **Drill drawer must track the slider** (same as A's note 7): steps beyond
   the current step-order position get a disabled look.
7. **Step-status legend appears orphaned**: the "STEP STATUS (DRILL PANEL)"
   key shows marks the main UI never displays. Wire it visibly or drop it.
8. **Agent recommendations for contested regions**, especially multi-plan
   contests — what to do about the contention, not just that it exists.
9. **Meta-directive (Scott)**: don't limit recommendation types to the ones he
   named — the agent has deeper analysis of the codebase/plans/edges and
   should propose its own recommendation taxonomy for the spec (e.g. what an
   agent could recommend per edge kind, per contested region, per step-vs-
   backlog delta).

### Variant C — Plan constellation: UNIQUE VALUE UNPROVEN (V1-constellation pattern)
Drill duplicates what A/B already offer; the one candidate advantage — per-plan
edge in/out counts at a glance — "is that really any more useful than the
other views? I'm not sure." Verdict pending final synthesis; candidate
outcome: retire as top-level or reframe as the at-scale entry view.

1. **FIX-SOON — click/drag interaction confusion**: first click seems to arm
   drag state, second click opens the drawer; switching to another plan
   requires the double-click dance again and the drawer doesn't update on
   first click. Clean separation needed: click = drill, drag = drag, no
   stateful first click.
2. **Liked: draggable cards** — untangling crisscrossing edges by hand works.
3. **Canvas zoom + pan wanted**: five plans is manageable; a real project
   with many plans will crowd — C's plausible niche is exactly that scale.
4. **CROSS-PROTOTYPE — deferred treatment illegible** (third strike, see A
   note 1): PDLC card says "parked (deferred)", step outlines are barely
   dimmer, and the legend's "deferred — outlined, 40% opacity" can't be
   located in the scene. Needs a deliberate, obvious deferred mark everywhere.
5. **Unique-value question (Scott, verbatim spirit)**: with A and B present,
   what does C alone tell me? Unresolved. If it survives, likely as the
   fleet-scale zoom-out / entry view linking into A and B.
6. **Edges lack visible direction** — from/to reads ambiguous on the bundles;
   needs directional affordance (arrowheads, gradient, or animated flow).

### Cross-cutting (all V2 views)

- **Plan-inclusion filter is a first-class control**: every view needs the
  ability to select WHICH plans participate in the diagram, not just visual
  isolation on hover/click. B's legend-chip isolate is the seed treatment;
  A and C lack it entirely. At real scale (20+ plans) inclusion-selection is
  what keeps any of the views legible — pairs with C's zoom/pan note and the
  "C as fleet-scale entry view" hypothesis.
- **Deferred-mark redesign applies across all three views** (A note 1, B note
  7 adjacency, C note 4).

## V2 demo-readiness fix pass (2026-07-12) — applied and verified

All FIX-SOON + queued usability items applied to the three prototypes (briefs:
`prototype-v2/fixpass_common.md` + per-variant `fixpass_A/B/C.md`); playwright-
verified with computed-style evidence, then eyeballed. All three PASS.

- Cross-cutting, all views: deferred mark redesigned (full-opacity outline
  circle + pause glyph; plan-level `❚❚ PARKED` pill + dashed container);
  plan-inclusion filter row (real button toggles + `all` reset); edge-kind
  badges became bordered rounded-rect chips distinct from step circles.
- A: lane-chip bug root cause — dark-mode `recolor()` reinserted swatch dots
  behind opaque lane-row rects; replaced with a full deterministic re-render.
  Slider's main-area translucency removed (substrate accumulation kept);
  `plans`/`regions` captions added.
- B round-2 root cause: `#tooltip`/`#drillPanel` mount at body level, OUTSIDE
  `.viz-root` where all theme vars were scoped — `var(--surface)` resolved to
  transparent. Fixed by widening scope to `:root, .viz-root` (+ dark twins).
  Lesson for F0 spec: theme tokens live on `:root`; overlay elements mounted
  outside the viz container are a standing trap. Also: washes computed from
  live tile positions; contested defined in legend + tooltip names plans;
  drawer tracks slider with `upcoming` tags; status key moved into drawer.
- C: click=drill / drag=drag via 4px threshold; d3.zoom pan/zoom (cards
  excluded from zoom filter); per-kind arrowheads with boundary offset;
  `reset view` relocated into the filter row after round-2 found it fully
  overlapping the `all` button (flow layout = structural non-overlap).
- Verification lessons confirmed again: user sightings during the run (B
  transparency, C half-open drawer, C corner artifact) were all real pre-fix
  states captured mid-race while fixes landed — proven via `Last-Modified`
  moving in lockstep; `cache: 'no-store'` fetch + unique query is the
  decisive stale-vs-real test.
- Residual minors (logged, not fixed): A slider handle covers the step axis
  label when parked exactly on an integer; B kind-group washes are subtle;
  C legend box is large and can overlap the lower-left card at some layouts.

## Fabrication ledger (what's real vs mock in the prototype)

- Real: repo file tree, file sizes, graphify in-degree centrality, PR #238 file list
  and adds/dels, directory-level dependency edges.
- Fabricated: consequence scores (path heuristics + hand tags), complexity scores
  (numstat-scaled, story-tuned), all drill stories, intra-file hotspot scans
  (marked "mock scan" in UI), namespaces.py projected centrality (0.75).
