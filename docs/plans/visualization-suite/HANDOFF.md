# HANDOFF — Visualization Suite fablize session (next phase: "how does this actually work" discussion → V3 brainstorm → grouped spec)

For a fresh context resuming work on **agents-config-yf2ov.2** (epic:
"Visualization suite: PR shape, work-DAG, and codebase evolution", child of
milestone M5). Read this file, `findings.md`, and `bd show agents-config-yf2ov.2`
before doing anything. The epic is CLAIMED by the working session — re-claim if
resuming fresh.

## Session type and hard requirements

- This is a **fablize** session (frontier-window spec-fest): the deliverable is a
  **grouped dated design spec** in `docs/specs/`, NOT an implementation. Invoke the
  `fablize` skill's Phase-0 model check — the session must run on **Fable**
  (`claude-fable-5`); stop and tell the user if it isn't.
- Scott multitasks with long gaps between turns: **never park deliverables behind
  a localhost server**. Deliver self-contained HTML files on disk, `open` them,
  send via SendUserFile.
- **Use-cases before architecture**: pin moments/questions/actions and let Scott
  react to prototypes before any runtime/data-model questions.
- Delegation pattern that works: Fable writes judgment (briefs, data stories,
  edge inference, spec text); Sonnet workers (explicit model+effort on every
  dispatch) build D3/HTML mechanics; verify headlessly via playwright.

## Verification lessons (V2 round 1 — reuse these)

- playwright blocks `file://` — serve via scratch `python3 -m http.server 8642`
  from the prototype dir, kill after (`pkill -f "http.server 8642"`).
- **Cache-bust every re-verify** (`?final=2` query) — http.server sends no cache
  headers; a stale page produced two false blockers verbatim.
- playwright clicks target an element's **bbox center** — for curved SVG paths
  that's empty space. Real users click the visible curve/badge; make midpoint
  glyph badges first-class click targets and have verifiers click those.
- Verifier misjudgments to expect: closed panel content still in DOM/a11y tree
  ≠ visible; check computed styles/transforms, not tree presence.
- Palettes validated via the dataviz skill's `validate_palette.js` — plan hues
  (slots: blue/aqua/violet/magenta/orange) and edge-kind status colors both pass
  light+dark; light-mode aqua/magenta need direct labels (relief rule).

## Decisions already made (do not relitigate)

1. **Batch** (approved): F0 shared foundations + V1 PR-shape + V2 work-DAG + V3
   codebase evolution. One grouped spec covering all. At spec-PR merge: mint
   continuations under the still-open epic, release claim, stamp readiness
   labels — in that order.
2. **Runtime architecture (F0, user-approved): shared-canvas hybrid** —
   self-contained HTML artifacts; a lightweight loop makes them interactive with
   the agent when a session is attached. The session IS the agent; no backend.
3. **V1 verdicts** (see findings.md): estate treemap strong keep; attention
   ledger strong keep; constellation = evaluation criterion; impact sonar
   retired to per-file drill.
4. **V2 encoding spine** (validated, keep across views): solidity = provenance
   (solid encoded / dashed inferred); color+glyph = edge kind (gray → dependency,
   amber ≈ overlap, red ✕ conflict, green + synergy); step status filled/ring/
   outline; plan identity on the 5 validated categorical hues.
5. **V2 round-1 verdicts** (Scott, detail in findings.md): **A flight-plan
   lanes = STRONG KEEP** ("insights I had not seen in the beads dependency
   tree"). **B territory map = KEEP** with fix-soon usability items; new use
   case surfaced: contested regions → quality-policy targeting (guardrails/
   standards placement). **C constellation = unique value unproven**; candidate
   reframe: fleet-scale (20+ plans) zoom-out entry view — evaluation criterion
   for the spec, not a build item.

## State (files)

- `docs/plans/visualization-suite/prototype-v2/` (COMMITTED to main directly,
  commit `0605b08`, 2026-07-12, Scott-authorized admin bypass — an explicit
  exception to the worktree/PR discipline, not a precedent): `v2_variant_A.html`
  (lanes), `v2_variant_B.html` (territory), `v2_variant_C.html` (constellation)
  — all self-contained, demo-ready post fix pass, playwright-verified with
  computed-style evidence, delivered to Scott 2026-07-12.
  Alongside: `v2_data.json` (5 real specimen plans, 10 cross-plan edges — only
  e1 encoded in beads; 9 agent-inferred), `shared-conventions.md` (encoding
  spine + hard requirements), `brief_A/B/C_*.md`, `shots/`.
- V1 prototype: `prototype/pr-shape-proto-v3.html` + regen scripts (unchanged).
- `findings.md`: V1 verdicts + 15 principles; V2 round-1 verdicts with numbered
  feedback per variant + cross-cutting items. THE source for the fix pass and
  spec inputs.
- Bead `agents-config-yf2ov.2`: claimed, notes updated through V2 round 1.
- Known residuals (logged, minor): B logs an aria-hidden focus warning on panel
  close (blur before hiding); C has dead space above the cards.

## Next actions (in order)

1. **"How does this actually work" discussion** (Scott initiates this in a
   fresh session; do NOT jump to V3 or the spec first). Scott's words:
   "rather than start on the next brainstorm/prototype, I'd like to discuss
   _how_ we might actually make this work." This is the operationalization
   question — moving from reaction mockups with hand-built data to a real,
   repeatable system. Treat it as a brainstorm (one question at a time,
   use-cases before architecture); its conclusions feed the F0 section of
   the grouped spec. The agenda below ("Operationalization questions") is
   the raw material — Scott drives which threads matter.
2. **V3 brainstorm** (lighter, another day): topical-evolution thread —
   likely V2 overlay machinery pointed backward through git history plus
   forward into plans. 1–2 mockups, not a full prototype, unless Scott asks.
3. **Write the grouped spec** — `docs/specs/2026-MM-DD-visualization-suite-design.md`:
   F0 foundations (scene contract, shared-canvas runtime, heat model, drill/
   annotation pattern, encoding spine, + the operationalization decisions
   from action 1) + V1/V2/V3 sections + evaluation criteria +
   `## Continuations` minting child beads with ACs. Then:
   brainstorming-skill user review gate → completion gate → PR → at merge:
   mint continuations, stamp readiness labels, release claim on yf2ov.2.

## Operationalization questions (agenda for next-action 1)

How the prototypes were actually produced this round — the thing to
systematize:

- **Data**: `v2_data.json` was hand-authored by agents in-session — plan
  rosters and statuses pulled from real beads, step waypoints SYNTHESIZED by
  agent judgment (4–6 per plan), cross-plan edges inferred by reading specs
  (9 inferred vs 1 encoded; e1 = qptb4 blocks abn9.40.3 is the only
  beads-encoded cross-plan edge). No pipeline exists; every artifact was a
  bespoke agent work product.
- **Rendering**: agent-written self-contained D3 HTML per variant, verified
  by playwright subagents + human eyeball.

Open "how" threads the discussion should resolve (accumulated evidence in
findings.md):

1. **Data pipeline**: what regenerates plan/step/edge data — a deterministic
   extractor (beads + specs + graphify) plus an agent inference pass for
   edges/steps? Where does inferred-edge provenance live so it survives
   regeneration (a sidecar file? beads edges minted on acceptance?).
2. **Regeneration trigger + freshness**: artifact-per-moment (morning
   triage, on-demand command) vs live polling. Prior lean: regenerated
   artifact, no server (no-fragile-infra constraint).
3. **Packaging**: where does this live — a skill (agent regenerates on
   demand), a `packages/` CLI with an agent step, a command? Placement rule:
   capability-dependency decides shared vs Claude-only tree.
4. **Agent-in-the-loop mode**: shared-canvas hybrid is decided (F0) — but
   the concrete loop (annotation round-trip → agent processes notes → PR
   comments/bead edits; "recommend work-breakdown revision" action) needs a
   mechanism: file watch? paste-back JSON (V1's copy-notes button is the
   embryo)? session-attached local bridge?
5. **Recommendation engine**: edge drills carry agent recommendations
   (Scott's ask + meta-directive to derive my own taxonomy). When are these
   generated — at data-build time (batch, per edge/region) or interactively?
6. **Scale**: 5 plans hand-built; 20+ plans needs the plan-inclusion filter
   (built), C-as-entry-view hypothesis, and a data build that doesn't need a
   frontier model per refresh (cost: this round's data was Fable-judgment-
   heavy).
7. **Step synthesis vs backlog truth**: synthesized steps are a lossy view
   over real beads; the delta is itself a product feature (work-breakdown
   revision) — but the pipeline must keep the mapping step→bead-ids
   explicit, not vibes.

## Synthesis obligations for the spec (from Scott's V2 feedback)

- **Agent-recommendation taxonomy**: Scott's meta-directive — derive MY OWN
  recommendation types beyond his examples (per edge kind, per contested
  region, per step-vs-backlog delta). His examples: extract-a-slice-without-
  disrupting-sequencing; resequence/reprioritize; guardrails for contested
  regions.
- **Step-vs-backlog delta as an instrument**: synthesized step waypoints vs
  real bead hierarchy is a diff; "recommend work-breakdown revision" is a
  UI-initiated action (strongest new spec input).
- **Edge drills carry evidence + recommendations**: name real bead ids when an
  edge maps to actual dependency edges; mirror scene colors/glyphs in panels.
- **Step naming experiment** (low-pri): per-plan synthesized step names instead
  of bare order numbers; open question how it renders in lanes view.
- **Plan-inclusion filter** is F0-level (every view needs it at scale).

## Open questions to carry into V3 / spec

- V2 progression view: live update source (beads polling?) vs regenerated
  artifact per morning-triage moment.
- Weight-slider semantics explanation layer (V1 principle #2) — F0 spec text.
- "Contested" semantics: same-file vs same-region vs same-dependency-chain —
  sharpen before spec (Scott flagged the ambiguity explicitly).
