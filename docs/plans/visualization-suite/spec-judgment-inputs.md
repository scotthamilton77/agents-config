# Spec judgment inputs — Fable-banked deltas

WORKING NOTE. The three judgment-dense inputs for the grouped spec, authored
on Fable while session context was hot (per the model-split decision: Opus
assembles the spec and implementation plans from this corpus). Companions:
`operationalization-notes.md` (D1–D6), `oss-landscape.md`, `findings.md`.

These are proposals at brainstorm fidelity — the spec's deep-review pass and
Scott's spec review are the acceptance gates. Nothing here is implemented.

---

## Delta 1 — Recommendation taxonomy

Scott's meta-directive: derive recommendation types beyond his three examples
(extract-a-slice-without-disrupting-sequencing, resequence/reprioritize,
guardrails for contested regions). Taxonomy below is organized by **trigger
surface** — the thing whose state warrants advice. Every type obeys the
cross-cutting contract at the end.

### 1.1 Edge-kind triggers

**Dependency edges (gray →):**

- **Resequence** — a dependent step is scheduled before its upstream lands.
  Recommend reordering the downstream plan, or moving the depended-on slice
  earlier in the upstream plan. (Scott's example, generalized to either side
  of the edge.)
- **Decouple** — the dependency exists only through incidental coupling
  (both plans touch a shared helper, neither owns it). Recommend extracting
  the shared piece as its own small work item both plans depend on —
  converts hidden serialization into an explicit, parallel-safe node.
- **Stale-dependency challenge** — an *encoded* beads edge is contradicted
  by current spec content (upstream scope has drifted; the dependency may no
  longer hold). Recommend re-verifying the edge. Deterministic edges rot
  too; trust-checking runs in both directions, not just on inferences.

**Overlap edges (amber ≈):**

- **Merge/absorb** — two plans implement near-identical slices. Recommend
  consolidating into one plan's scope; the other consumes the result.
- **Extract-shared-slice** — the overlap is partial. Recommend extracting
  the common substrate as a standalone item sequenced before both. (Scott's
  extract-slice example, generalized.)
- **Sequence-to-reuse** — one side's output could serve the other if
  reordered. Recommend sequencing so the second plan reuses instead of
  duplicating. Cheaper than merge: no scope surgery, only ordering.

**Conflict edges (red ✕):**

- **Serialize-with-checkpoint** — contradictory approaches to the same
  surface. Recommend explicit ordering plus an integration checkpoint
  between the two plans' passes over the surface.
- **Escalate-design-ruling** — the conflict reflects an unresolved
  architectural disagreement between specs (both cannot be right).
  Recommend a human design ruling before either plan proceeds, citing the
  conflicting passages. This is the spec-vs-spec analog of the constraints'
  "direct conflict on a shared element → halt and surface" rule; the agent
  never picks a winner.
- **Guardrail** — the conflict zone gets quality-policy targeting (extra
  review depth, standards placement). (Scott's example; see also 1.2.)

**Synergy edges (green +):**

- **Piggyback** — one plan's work makes another plan's step nearly free.
  Recommend claiming the win explicitly: fold the step into the first plan's
  acceptance criteria, or shrink/drop the second plan's step. Unclaimed
  synergy decays into duplicate spend.

### 1.2 Contested-region triggers (levels per Delta 2)

- **Guardrail placement** — raise the quality bar for the region while
  contention lasts: deeper review tier, tighter coverage floor, standards
  doc. (Scott's example.) Keyed to contention level: L1 → rebase-discipline
  awareness; L2 → interface freeze or ownership; L3 → design ruling.
- **Ownership assignment** — name one plan the region's owner for the
  contention window; the others rebase on the owner's changes. Serializes by
  geography instead of by time — plans stay parallel everywhere else.
- **Interface freeze** — pin the region's public contract for the window so
  contenders build against a stable seam. Drops contention from file-level
  to contract-level.
- **Hot-region decomposition** — a region contested by 3+ plans, or
  contested across successive planning generations, is structural feedback:
  the region does too much. Recommend a refactor-first work item ahead of
  the contending plans. Contention as architecture signal, not just
  scheduling noise.

### 1.3 Step-vs-backlog delta triggers

These four compose the "recommend work-breakdown revision" UI action:

- **Backlog gap** — a synthesized step maps to zero beads. The narrative
  asserts work the tracker doesn't hold. Recommend minting beads under the
  plan for it.
- **Orphan work** — beads under the plan map to no step. Either the step
  synthesis is incomplete (re-synthesize) or the work is scope creep
  (recommend triage). Present both readings; the delta itself doesn't decide.
- **Granularity mismatch** — one step maps to a dozen beads while a sibling
  maps to one. Decomposition smell; recommend rebalancing the breakdown.
- **Sequencing contradiction** — bead dependency order contradicts step
  order. Narrative and tracker disagree about time; one is wrong. Recommend
  reconciling, citing both orderings.

### 1.4 Doubt-flag triggers (D2 rung 4)

- **Reassess-inference** — the standard flag: claim + cited basis + the
  change that raised doubt, queued for human verdict.
- **Cascade check** — the doubted fact was load-bearing for downstream
  accepted verdicts (e.g. a promoted edge whose acceptance rationale cited
  it). Recommend reviewing the dependents together: doubt propagates along
  the promotion lineage, and re-validating one node at a time hides the
  blast radius.

### 1.5 Cross-cutting contract (every recommendation type)

1. **Evidence-cited** — names real bead ids and/or spec passages; mirrors
   scene colors/glyphs in the drill panel (findings V2-A notes 9–11).
2. **Attention bar** (findings principle #1) — nothing mechanically
   derivable gets phrased as advice; if code can compute it, it renders as
   fact, not recommendation.
3. **Actionability class** — every recommendation is stamped either
   `one-click` (agent can execute on acceptance: mint bead, add edge,
   relabel) or `ruling-needed` (human design decision; agent
   drafts the question, not the answer). This split is what the annotation
   round-trip (D5) dispatches on.
4. **Tier-2 lifecycle** — recommendations are inferred facts: fingerprint-
   keyed, funnel-checked (D2), regenerated only when inputs change, subject
   to rejection memory like edges (a dismissed recommendation stays
   dismissed until its basis changes).

## Delta 2 — "Contested" semantics

Scott flagged the ambiguity: conflicting vs merely touching the same files.
Resolution: **contested is a three-level gradient of interaction risk**, each
level differently detectable and differently actionable. A region's badge
shows the highest level present; the legend defines all three.

- **L1 Co-located** — two or more plans' predicted touch-sets intersect on
  files/regions. Weakest signal: co-location is not interference (different
  functions in one file coexist fine). Detection: mechanical, given
  touch-sets.
- **L2 Coupled** — touch-sets don't intersect, but sit in a tight dependency
  neighborhood (graphify: same community, direct import edges, high
  co-change coupling). One plan's change ripples into the other's ground.
  Detection: mechanical from the code graph, given touch-sets.
- **L3 Contradictory** — plans assert incompatible intents for the same
  element (one refactors an interface away, the other builds on it).
  Detection: Tier-2 inference from spec passages; never mechanical. L3 is
  the territorial projection of a conflict (✕) edge.

Honesty note on "mechanical": touch-set *prediction* is itself Tier-1 only
where beads/specs name concrete surfaces; for prose-only plans it is Tier-2
inference. L1/L2 are mechanical *given* touch-sets — the provenance of the
touch-set carries through to the provenance of the contention claim (a
region can be "L1 (inferred touch-set)" — solidity encoding applies).

**Temporal dimension**: contention has a window — it exists only where the
plans' active phases overlap, derived from step positions vs current
progress. Contested-now renders differently from contested-eventually, and
the materialization slider (V2-B) already provides the time axis: region
contention state must track the slider, same as the drill drawer does.

Guardrail-recommendation mapping (see 1.2): L1 → awareness/rebase
discipline; L2 → interface freeze or ownership assignment; L3 →
escalate-design-ruling. Hot-region decomposition triggers on repeated or
many-plan contention at any level.

## Delta 3 — F0 scene contract (skeleton)

The contract every view module obeys. Distilled from findings principles
(#8, #11–14) and the V2 fix-pass root causes; Opus expands to full spec
text, keeping every named rule.

**View module interface**
- A view is `render(container, scene, state) → handle` with
  `handle.destroy()`; it receives a **fresh container**, never a shared
  mount point (principle #11), and styles nothing outside it.
- Deterministic rendering: pre-settled layouts before first paint; no
  re-simulation on encoding-only changes; user-pinned positions kept
  (principle #12).
- Interaction constants: click=drill vs drag=drag separated by movement
  threshold (~4px, C fix); overlays opaque; badges bordered; flow layout
  over absolute positioning for control rows (structural non-overlap).

**Theme tokens**
- All colors/surfaces via CSS custom properties declared at `:root` scope —
  overlay elements mounted outside the viz container must still resolve
  tokens (V2-B round-2 root cause). Light default + dark twin (principle
  #8); label color chosen by luminance of underlying fill per theme
  (principle #13).
- Palette: the 5 validated categorical plan hues + edge-kind status colors
  (both passed light+dark via the dataviz validator); direct labels where
  the relief rule demands.

**Scene data contract**
- One inlined JSON scene object per artifact. Shape: cc.json-inspired
  (node tree + generic attributes maps + top-level typed edges + self-
  describing attribute descriptors) with viz-suite extensions:
  - per-fact **provenance** on two independent axes — source/verdict
    (`encoded | inferred | accepted`) and freshness (`fresh | doubted`) —
    plus fingerprint + passage citations; drives the solidity encoding and
    the drill panel's evidence section;
  - plan identity, step waypoints, and the explicit step→bead-id mapping;
  - recommendations attached to high-signal items only (D6), each with
    actionability class;
  - **time reservation (V3)**: an optional time-keyed event-stream section
    (Gource-style minimal events) and snapshot keyframes — reserved now so
    V3 never forces a contract break.
- Encoding spine as exported constants shared by all views: solidity =
  provenance, color+glyph = edge kind, fill/ring/outline = step status,
  categorical hues = plan identity.

**Shared affordances (every view)**
- Plan-inclusion filter row (F0-level control at scale); legend covering
  every encoding in the scene (principle #12); deferred/parked mark standard
  (fix-pass design: outline circle + pause glyph, `❚❚ PARKED` pill).
- Drill panel pattern: evidence (bead ids, passages) + provenance + any
  recommendation, mirroring scene colors/glyphs; tracks the time slider
  where one exists (upcoming items get the disabled look).
- Annotation layer: localStorage persistence + copy-notes-as-JSON button
  (D5 baseline); all user/dynamic content escaped or bound as data — never
  interpolated into innerHTML (principle #14); data-out affordances report
  honest success/failure.
- Timeline scrub affordance in the shared controls where the scene carries
  time data (V2 materialization slider generalized; V3 reservation).

**Artifact packaging**
- Single self-contained HTML: d3 (+ d3-dag where used) inlined, scene JSON
  inlined, zero runtime fetches (principle #9). Stable element ids/classes
  as verification hooks (playwright computed-style assertions;
  cache-bust discipline per HANDOFF verification lessons).
