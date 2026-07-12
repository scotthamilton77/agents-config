# Visualization Suite — Grouped Design (F0 Foundations, V1 PR-Shape, V2 Work-Map, V3 Evolution)

**Date:** 2026-07-12
**Status:** Draft (pending review)
**Bead:** agents-config-yf2ov.2 (epic, child of milestone M5)
**Decision:** One suite of regenerated, self-contained HTML visualization artifacts
built on shared foundations (F0): a scene contract every view obeys, a
three-tier provenance model with a fingerprint-keyed staleness funnel, a
deterministic `packages/vizsuite` CLI split from a thin agentic skill, and a
human review queue that promotes accepted inferences into beads. V1 (PR-shape)
and V2 (work-map) are specified to build; V3 (codebase evolution) is
direction-only, gated on its own reaction round.

Evidence corpus: `docs/plans/visualization-suite/` (findings.md — prototype
verdicts and 15 design principles; operationalization-notes.md — the decision
log this spec integrates; spec-judgment-inputs.md — recommendation taxonomy,
contested semantics, scene-contract skeleton; oss-landscape.md — verified
build-vs-buy survey). Prototypes: `prototype/` (V1, 3 reaction rounds),
`prototype-v2/` (V2, reaction round + demo-readiness fix pass, playwright-verified).

## 1. Problem

Three connected capabilities, one premise: **direct scarce human judgment to
where it matters**, instead of making a human derive context line-by-line
(PR review) or bead-by-bead (backlog triage).

1. **V1 — PR shape.** A reviewer should see a PR's shape against the whole
   codebase — complexity hot spots, load-bearing surfaces, blast radius — so
   review is intentional, not sequential.
2. **V2 — Work map.** A planner should see how a fleet of in-flight plans
   interacts — dependencies, overlaps, conflicts, synergies, contested code
   territory — so resequencing/rescoping decisions happen before collisions,
   not after.
3. **V3 — Codebase evolution.** A timeline of code *and* intent (vision,
   architecture, direction) explored interactively with an agent.

Mission fit: the repo's prime directive is reducing human interventions per
merged PR by moving human time upstream. V1 sharpens the review gate
(intentional attention beats line-by-line); V2 moves judgment upstream into
sequencing and scope decisions; both feed the morning-triage moment the
two-shift operating model (M4) depends on.

Validated by prototype reaction rounds: the V2 flight-plan lanes view produced
"insights I had not seen just dealing with the beads dependency tree" on real
plan data — cross-plan structure that the tracker holds but no existing surface
shows. GitHub Projects, OpenProject, and Plane all decline to draw cross-plan
dependency edges at all (oss-landscape.md §3); this is unclaimed territory.

## 2. Scope

**This spec commits:**

- **F0 foundations** (§4–§5): scene contract, provenance tiers, data pipeline,
  sidecar persistence + edge promotion, staleness funnel, recommendation
  engine, annotation round-trip, packaging split.
- **V1 build** (§6): estate treemap + attention ledger + per-file sonar drill,
  with the dependency constellation included under an explicit evaluation
  criterion (§11).
- **V2 build** (§7): flight-plan lanes + territory map. The plan constellation
  is **not** built; it survives as the fleet-scale entry-view hypothesis (§11).
- **V3 direction** (§8): thin — two F0 reservations bake in now; everything
  else waits for V3's own reaction round.

**This spec does not commit** (§12): any live server or polling, V3 build
work, autonomous beads mutation, or replacing graphify/beads surfaces.

## 3. Vocabulary

Load-bearing terms coined by this design. They live here for now; whether they
graduate to a viz-scoped `CONTEXT.md` (making the repo multi-context via
`CONTEXT-MAP.md`) is an open offer to the owner, not a blocker.

- **Artifact** — one self-contained HTML file, generated at a moment in time,
  carrying its scene data inline. The unit of delivery.
- **Scene** — the single inlined JSON object an artifact renders (§4.4).
- **View** — one visualization module over a scene (treemap, lanes, …). An
  artifact hosts one or more views on a shared canvas.
- **Provenance tiers** — Tier 1: deterministic extracts (git, `gh`, beads,
  graphify, scc); Tier 2: agent-inferred facts (edges, step waypoints,
  recommendations, drill stories); Tier 3: human verdicts (accept/reject,
  annotations). Tiers age differently: Tier 1 regenerates at ~zero cost,
  Tier 2 is fingerprint-cached, Tier 3 is never regenerated — only flagged.
- **Edge promotion** — writing an accepted Tier-2 cross-plan edge into beads
  as a real dependency edge. *Naming collision note:* the PDLC glossary
  (`CONTEXT.md`) owns bare **Promote** for Idea → Objective; this design
  always says **edge promotion** and never unqualified "promote."
- **Restamp** — revalidating a Tier-2 fact against a new input fingerprint
  without human review (funnel rungs 2–3, §5.4).
- **Doubt flag** — a funnel verdict that a Tier-2 fact is genuinely in
  question; enters the reassessment queue.
- **Reassessment queue** — the only place Tier-2 uncertainty is allowed to
  consume human attention.
- **Rejection memory** — persisted human rejections and dismissals; a
  rebuild must never re-propose a rejected fact as fresh (§5.3).
- **Fact identity** — every Tier-2 fact's stable id derives from a coarse
  key anchored to beads (the only stable substrate), never to other Tier-2
  artifacts (§5.3). Verdicts, flags, annotations, and rejection memory all
  join on it.
- **Dismiss** — the third verdict: declines a *recommendation* without
  asserting it is wrong (reject asserts a *fact* is incorrect). Dismissals
  persist in rejection memory until the recommendation's basis changes.
- **Contested (L1/L2/L3)** — the three-level interaction-risk gradient for
  code regions touched by multiple plans (§7.5).
- **Materialization** — the point in plan-step order at which a fact (edge,
  contention) becomes live; the time axis of V2's slider.

## 4. F0 — Runtime and scene contract

### 4.1 Runtime architecture: shared-canvas hybrid

Artifacts are **self-contained HTML files on disk** — d3 (and d3-dag where
used) inlined, scene JSON inlined, zero runtime fetches. They open by
double-click, detached from any session or server. When a Claude session is
attached, the same artifact becomes interactive *with the agent* (annotation
round-trip, §5.8; live drills). The session **is** the agent; there is no
backend, no localhost server, no file watcher. Rationale: the owner
multitasks with long gaps — a deliverable parked behind a timeout-bound
server is a lost deliverable.

### 4.2 View module interface

Every view obeys one contract:

- `render(container, scene, state) → handle`, with `handle.destroy()`. A view
  receives a **fresh container per render** — never a shared mount point —
  and styles nothing outside it. (Root cause, twice, of cross-view style
  leaks in prototypes.)
- **Deterministic rendering:** layouts pre-settle before first paint (force
  simulations run N ticks synchronously with a fixed seed strategy);
  encoding-only changes (weight sliders, theme toggle) never re-run layout;
  user-pinned positions survive re-encoding.
- **Interaction constants:** click-vs-drag separated by a movement threshold
  (~4 px); overlay surfaces opaque; badges bordered; control rows use flow
  layout, never absolute positioning (structural non-overlap).

### 4.3 Theme tokens

All colors and surfaces resolve via CSS custom properties declared at
**`:root` scope** — overlay elements (tooltips, drill panels) mounted outside
the viz container must still resolve tokens. (Verified failure mode: tokens
scoped to `.viz-root` rendered body-mounted overlays transparent.) Light mode
default with a dark twin; label color chosen by luminance of the underlying
fill, per theme; no text-shadows on small labels.

Palette: the five validated categorical plan hues (slots: blue / aqua /
violet / magenta / orange) plus the edge-kind status colors — both palettes
passed light+dark validation via the dataviz skill's validator; light-mode
aqua/magenta require direct labels (relief rule).

### 4.4 Scene data contract

One inlined JSON scene per artifact: a **shared envelope** plus a per-suite
payload. The envelope is cc.json-inspired (recursive node tree + generic
attribute maps + top-level typed edges + self-describing attribute
descriptors) — adopted as shape, not as standard; no renderer-independent
standard exists (oss-landscape.md §3).

Envelope (all artifacts):

- `schema_version`, `generated_at`, `generator` (CLI version).
- `fingerprints` — the input-hash manifest the scene was built from (§5.4).
- `descriptors` — self-describing attribute metadata (name, unit, direction).
- **Per-fact provenance** on every Tier-2/Tier-3-touched fact:
  `encoded | inferred | accepted | doubted`, plus fingerprint and
  passage-level citations. Drives the solidity encoding and the drill panel's
  evidence section.
- `recommendations[]` — attached to high-signal items only (§5.7), each
  carrying its actionability class.
- **Time reservation (V3):** optional `events[]` (Gource-style minimal
  time-keyed event stream) and snapshot keyframes — reserved now so V3 never
  forces a contract break.

Per-suite payloads: V1 carries the estate tree (nodes = tracked files/dirs,
attributes = heat axes); V2 carries `plans[] / steps[] / regions[] / edges[]`
with the explicit step→bead-ids mapping (§7.2).

**Encoding spine** — exported constants shared by all views, never
re-derived per view:

| Channel | Encoding |
|---|---|
| Provenance | line solidity: encoded/accepted = solid; inferred = dashed |
| Doubted | dashed + a bordered `?` doubt chip beside the kind chip; the drill panel carries the doubt reason |
| Edge kind | color + bordered glyph chip: dependency gray →, overlap amber ≈, conflict red ✕, synergy green + |
| Step status | done = filled; in_progress = filled + ring; open = outlined; deferred = full-opacity outline + pause glyph |
| Plan identity | the five categorical hues, fixed slot order, direct-labeled |
| Deferred plan | `❚❚ PARKED` pill + dashed container |

Never color-alone: every color channel pairs with a glyph, stroke, or label.

### 4.5 Shared affordances (every view)

- **Plan-inclusion filter** (V2-class views): a first-class control row
  selecting *which* plans participate — not merely hover-isolation. At real
  scale (20+ plans) inclusion-selection is what keeps any view legible.
- **Legend completeness:** every encoding present in the scene appears in the
  legend; a legend entry with no visible referent in the scene is a defect.
- **Drill panel pattern:** click any mark → panel with evidence (bead ids,
  passage citations), provenance, and any attached recommendation — mirroring
  scene colors and kind glyphs; Escape closes; where a time slider exists the
  panel tracks it (items beyond the slider get the disabled/upcoming look).
- **Annotation layer:** localStorage persistence + copy-notes-as-JSON button
  (§5.8 baseline). All user or data-derived content is bound as data
  (`textContent` / `textarea.value`) or HTML-escaped — never interpolated
  into innerHTML (stored self-XSS otherwise). Data-out affordances report
  honest success/failure: the copy button confirms only when the clipboard
  write resolves. Notes key on `viz:<repo>:<artifact-kind>:<fact-id>` —
  fact identity, not scene fingerprint — so notes survive artifact
  regeneration; a note whose fact id no longer resolves surfaces as a
  "note from a prior generation," never silently hidden. Artifacts show an
  unprocessed-note count in the header as the round-trip nudge (§5.8;
  residual loss window ledgered in §13).
- **Weight-slider explanation layer** (where sliders exist): sliders are
  share-of-importance, not volume knobs — a file weak on an axis *cools* as
  that axis gains weight. Every slider ships with a live mix readout and a
  per-item contribution breakdown in the drill panel.
- **Timeline scrub affordance** in shared controls wherever the scene carries
  time data (V2 materialization slider today; V3 reservation).

### 4.6 Artifact packaging

Single HTML file, everything inlined. Stable element ids/classes as
verification hooks — build-time verification drives playwright against served
copies with computed-style assertions and cache-busted reloads (the
verification lessons in the corpus are binding on implementation plans).

## 5. F0 — Data pipeline

### 5.1 Stage architecture

```
EXTRACT (Tier 1)  →  INFER (Tier 2)  →  REVIEW (Tier 3)  →  PERSIST  →  ASSEMBLE
git/gh/beads/        edges, steps,       reassessment       sidecar +    scene JSON →
graphify/scc/        recommendations,    queue: accept/     edge         self-contained
PyDriller            drill stories       reject/annotate    promotion    HTML
```

Build-vs-buy is settled by the verified OSS survey: **adopt** PyDriller
(commit-range churn/authorship), scc (per-file complexity/LOC), d3-dag (V2
layout), doit + diskcache (freshness substrate); **borrow shapes** from
cc.json (scene tree), LlamaIndex schema-guided extraction (fixed relation
enum), Graphiti/cognee (per-edge provenance); **build** the three novel
joins — the PR-scoped git+GitHub reconciler, the cross-plan overlay model,
and the human review queue. Two survey sub-claims remain unverified (cc.json
per-file checksum field; doit's md5-vs-mtime dependency check) — implementation
plans must confirm both by reading source before designing on them.

### 5.2 INFER stage constraints

- **Schema-guided extraction:** edge inference is constrained to the fixed
  relation enum `{dependency, overlap, conflict, synergy}` — never free-form
  relation types. Makes review, diffing, and rejection memory tractable.
- **Passage-level citations are mandatory at inference time:** every inferred
  fact records which spec/doc passages it relied on. Funnel rung 2 (§5.4)
  cannot be retrofitted onto a fact whose only provenance is "read spec X."
- **Model routing:** rung-3 doubt checks and step synthesis run on cheap
  models; edge inference on mid-tier; only recommendation synthesis for
  high-signal items warrants a stronger tier. Routed per the model-routing
  policy spec (2026-07-04); no stage assumes frontier availability.

### 5.3 Persistence: sidecar + edge promotion

**Sidecar** — versioned, repo-committed, at `.viz/` in the target repo:

```
.viz/
  manifest.json          # fingerprint manifest: input hashes + prompt/model/schema versions
  edges.json             # Tier 2: inferred cross-plan edges + citations (machine-rewritten)
  steps.json             # Tier 2: synthesized waypoints + step→bead-ids mapping
  recommendations.json   # Tier 2: high-signal recommendations + actionability class
  flags.json             # Tier 2 class, machine-owned: doubt flags + orphaned-verdict flags (the reassessment-queue store)
  verdicts.json          # Tier 3: accept/reject/dismiss verdicts + annotations — written only by `viz verdict`
  out/                   # generated artifacts (gitignored)
```

Tier-2 files are machine-rewritten on rebuild; **`verdicts.json` is written
only by explicit human verdicts** (via `viz verdict`) — no rebuild, sweep,
or cron path writes it, structurally enforcing "Tier 3 is only ever
invalidated, never silently deleted." Machine-raised doubt about a fact, or
a verdict whose subject fact changed or vanished, lands in `flags.json` as a
flag referencing the fact/verdict id; `viz queue` renders flags joined to
their facts and verdicts.

**Fact identity and rejection memory.** Bead ids are the only stable
substrate; **every Tier-2 fact's identity anchors to beads, never to other
Tier-2 artifacts.** An edge's **coarse key** is (from-plan, to-plan, kind,
the sorted bead-id anchor sets its endpoints resolve to via the step→bead
mapping); where an endpoint maps to zero beads, its cited-passage
fingerprint substitutes. The **fact id** is a stable hash of the coarse key;
verdicts, flags, annotations, and rejection memory all join on it.
Synthesized steps carry persistent ids with an explicit reconciliation
contract: on re-synthesis a step inherits its predecessor's id when their
bead-id sets majority-overlap, so a re-synthesis that renumbers or reorders
steps never orphans a verdict (test item 13). Rejection memory matches on
the coarse key: a rebuild that re-derives a rejected fact suppresses it. If
the basis has materially changed since rejection (cited passages differ),
the fact may resurface — but always annotated with its prior rejection,
never as fresh.

**Edge promotion** (accept-time, human-verdict-gated):

| Accepted edge kind | Beads write |
|---|---|
| dependency | real `blocks` edge between the mapped beads; where the type wall forbids (epic↔non-epic), `related-to` + sidecar carries the true kind |
| conflict / overlap / synergy | `related-to` edge for discoverability; the sidecar stays authoritative for kind and evidence (beads cannot express these kinds) |

A conflict resolved by accepting a *serialize-with-checkpoint* recommendation
(§5.7) mints a real `blocks` edge — via the recommendation, not the conflict
edge itself. Step-level edges promote to the specific bead pair the
step→bead-ids mapping identifies; the agent proposes the pair, the human
verdict confirms it. Promotion appends an audit note to the target bead
(provenance: agent-inferred-then-accepted, date, fingerprint); the sidecar
ledger — not beads — is authoritative for provenance, since beads edges carry
no metadata. Promotion is idempotent: re-accepting an already-promoted edge
is a no-op, never a duplicate-dependency error.

### 5.4 Staleness funnel

Changed inputs must not automatically demand human attention. Four rungs,
each strictly cheaper than the next; a fact exits at the first rung that
clears it:

1. **Hash check (free):** input fingerprint unchanged → fact reused verbatim.
2. **Provenance-intersection check (free, mechanical):** the diff does not
   intersect the fact's cited passages → auto-restamp against the new
   fingerprint.
3. **Agentic doubt check (cheap model):** claim + cited basis + diff → "does
   this change put the claim in doubt?" No → restamp with an audit note
   (agent-revalidated, date, change hash).
4. **Human reassessment (precious):** only doubt-flagged facts, surfaced as
   the reassessment queue. Doubt flags live in `flags.json` (§5.3), never in
   the Tier-3 file. Tier-3 verdicts attached to a doubted fact are flagged,
   never silently dropped. A doubted fact that was load-bearing for
   downstream accepted verdicts surfaces with its dependents (the cascade
   check, §5.7).

Rungs 1–2 are pure CLI code; rung 3 belongs to the skill/cron; rung 4 is a
queue, not a process.

### 5.5 Regeneration triggers

- **Primary: on-demand command** ("rebuild the map"). Works any time; correct
  without any scheduled machinery having run.
- **Accelerant: overnight sweep** — Tier-1 extraction, funnel rungs 1–3 over
  the sidecar, doubt flags queued for morning review (written to
  `flags.json`; the sweep never touches `verdicts.json`). **Flag-only:** the
  night shift never pre-drafts replacement inferences; re-inference happens
  when a human is at the helm. This dial can be revisited without structural
  change.
- No live polling, no server. Artifacts are regenerated, not refreshed.

### 5.6 Packaging: split by determinism

- **`packages/vizsuite/`** — a uv-managed Python package owning everything
  mechanical: Tier-1 extractors, the git+GitHub PR reconciler, fingerprint
  manifests, funnel rungs 1–2, sidecar read/write, scene assembly, HTML
  templating. CI-gated like its siblings (`make ci-vizsuite`: lint,
  format-check, typecheck, coverage, audit). Runs without any model.
  CLI name **`viz`**; machine verbs emit the JSON-envelope pattern the
  work-facade contract established (stdout envelope, exit mirrors `ok`).
  Verb sketch (implementation plans finalize): `viz pr [<number>]`,
  `viz work`, `viz sweep`, `viz queue`,
  `viz verdict <fact-id> <accept|reject|dismiss>`,
  `viz apply <recommendation-id>`.
- **A thin skill (`viz`)** in the Claude tree (`src/user/.claude/skills/`) —
  placement forced by capability-dependency: it dispatches inference
  subagents and drives the claude-in-chrome annotation enhancement. The
  skill owns: rebuilds (calls the CLI), rung-3 doubt checks, edge/step
  inference, the review-queue accept/reject flow (writes verdicts via the
  CLI, which performs edge promotion), and annotation processing.
- **Overnight cron** invokes the CLI plus a cheap-model headless sweep
  (rung 3), per the headless-dispatch discipline (`--permission-mode dontAsk`
  + explicit `--allowedTools`).

The suite is discipline-layer-generic: it reads beads, `docs/specs`-style
plan docs, and graphify output in whatever repo it runs in; `.viz/` lives in
the target repo. Nothing in this suite is agents-config-specific.

### 5.7 Recommendation engine

**Timing:** recommendations are generated at data-build time (including the
overnight sweep) **only where judgment earns its keep** — conflict and
overlap edges, contested regions, doubt-flagged items, step-vs-backlog
deltas. **Plain means no trigger condition matched:** a dependency edge
whose trigger predicate fires (a resequence condition, a decouple pattern,
a stale-dependency contradiction — table below) joins the build-time
high-signal set like any conflict edge. Untriggered dependency edges carry
evidence only (bead ids, provenance); no canned advice — drill live in an
attached session if wanted. This extends
the attention bar (findings principle 1) to recommendations: anything code
can compute renders as fact, not advice.

**Taxonomy** (organized by trigger surface; the implementation prompt set
derives from this table):

| Trigger | Recommendation types |
|---|---|
| dependency edge | **resequence** (dependent scheduled before upstream lands — reorder either side); **decouple** (incidental coupling → extract the shared piece as its own parallel-safe item); **stale-dependency challenge** (an *encoded* beads edge contradicted by current spec content — deterministic facts rot too; trust-checking runs both directions) |
| overlap edge | **merge/absorb** (near-identical slices → consolidate); **extract-shared-slice** (partial overlap → common substrate sequenced before both); **sequence-to-reuse** (reorder so the second plan reuses instead of duplicating — cheaper than merge) |
| conflict edge | **serialize-with-checkpoint** (explicit ordering + integration checkpoint); **escalate-design-ruling** (specs assert incompatible intents — the agent drafts the question, never picks the winner; the spec-vs-spec analog of the halt-and-surface constraint); **guardrail** (quality-policy targeting on the conflict zone) |
| synergy edge | **piggyback** (one plan's work makes another's step nearly free — claim it explicitly in ACs or shrink the second step; unclaimed synergy decays into duplicate spend) |
| contested region | **guardrail placement** (keyed to contention level: L1 → rebase discipline, L2 → interface freeze or ownership, L3 → design ruling); **ownership assignment** (one plan owns the region for the window; others rebase — serializes by geography, not time); **interface freeze** (pin the public contract so contenders build against a stable seam); **hot-region decomposition** (3+ plans or repeated generations contesting one region = the region does too much; recommend refactor-first work — contention as architecture signal) |
| step-vs-backlog delta | **backlog gap** (step maps to zero beads → mint them); **orphan work** (beads map to no step → re-synthesize or triage as scope creep; present both readings); **granularity mismatch** (one step maps to a dozen beads, a sibling to one → rebalance); **sequencing contradiction** (bead dependency order contradicts step order → reconcile, citing both) |
| doubt flag | **reassess-inference** (claim + basis + the change, queued); **cascade check** (the doubted fact was load-bearing for downstream verdicts → review dependents together; doubt propagates along promotion lineage) |

**Cross-cutting contract** (every recommendation): evidence-cited (real bead
ids and/or passages; mirrors scene colors/glyphs in the drill); passes the
attention bar; stamped with an **actionability class** — `one-click` (agent
can execute on acceptance: mint bead, add edge, relabel, resequence) or
`ruling-needed` (human design decision; agent drafts the question) — the
class the annotation round-trip dispatches on; and lives the Tier-2
lifecycle (fingerprint-keyed, funnel-checked, dismissals persist in
rejection memory until the basis changes). `one-click` execution goes
through `viz apply`, which is **idempotent per mutation class** (bead
minting keys on the recommendation id; edge adds, relabels, and resequences
converge on target state — replay is a no-op) and appends an audit note to
every touched bead: the edge-promotion contract (§5.3) generalized to all
one-click mutations.

### 5.8 Annotation round-trip

- **Baseline (universal):** every artifact carries the copy-notes-as-JSON
  button. Works in any browser, detached from any session; paste into chat
  completes the round-trip.
- **Enhancement (session-attached):** the agent reads annotations directly
  from the open artifact tab via claude-in-chrome (`javascript_tool` →
  localStorage) on "process my notes."
- Processing dispatches on actionability class: `one-click` acceptances
  execute through the CLI (verdict + edge promotion + bead edits);
  `ruling-needed` items become drafted questions. Notes also feed PR
  comments and work-breakdown revision proposals (§7.3).
- No localhost bridge, no file watcher. File-based ingestion (File System
  Access API) remains a compatible future add-on if unattended note
  processing is ever wanted.

### 5.9 Scale and cost bounds

Five plans were hand-built at Fable-judgment cost; 20+ plans must not need a
frontier model per refresh. The bounds compose: the fingerprint cache (§5.4
rung 1) removes re-inference of unchanged facts; edge promotion (§5.3)
permanently shrinks the dependency-kind Tier-2 surface (promoted edges
become Tier-1 beads reads; other kinds stay sidecar-cached under rung 1);
the flag-only night shift (§5.5) bounds unattended spend;
high-signal-only recommendations (§5.7) bound per-build judgment; the
plan-inclusion filter (§4.5) bounds rendering. The fleet-scale entry-view
hypothesis (§11) is the escape hatch if legibility still degrades.

## 6. V1 — PR-shape artifact

### 6.1 Views

| View | Disposition | Core interaction |
|---|---|---|
| **Estate treemap** | build | whole-codebase treemap, heat = weighted axis mix; collapse/expand at every container depth; expand-group-to-fill-screen |
| **Attention ledger** | build | ranked what-to-review-first list; toggle between separated (PR vs context) and mixed single-ranking views; per-file link to that file's diff in the PR |
| **File sonar** | build (as drill, not top-level) | click any file anywhere → blast-radius rings centered on *that* file (the containment question survives; top-level sonar retired — angular adjacency implied relationships the data didn't assert) |
| **Dependency constellation** | build, evaluation-gated (§11) | PR files + context graph; stable pre-settled layout, full legend, no re-sim on slider drag |

Treemap requirements from the reaction rounds: label declutter (long
filenames are the crowding driver); collapsible groups where a collapsed
container inherits **worst-offender (max) heat** — hiding detail never hides
risk; groups with no PR impact default-collapsed; collapse *reflows* — the
collapsed container shrinks and siblings absorb the space (collapse is an
attention-allocation act), hierarchically at every depth.

### 6.2 Heat model

Three axes, each 0–1 per file, combined by user-weighted average (slider
semantics per §4.5):

- **Complexity** — Tier 1: normalized scc complexity/LOC as the estate-wide
  baseline; PR-touched files receive a churn-scaled boost (PyDriller,
  merge-base..head). Context files never score below their scc baseline —
  churn only heats, never cools. Replaces the prototype's fabricated scores.
- **Load-bearing** — Tier 1: graph centrality from graphify, with two
  binding corrections: (a) **projected post-PR centrality** — computed on
  the dependency graph *as the PR leaves it* (changed imports included),
  because history-based centrality scores brand-new load-bearing code at
  zero; (b) **consistent edge set** — intra-file self-edges excluded from
  in-degree (they inflate big self-referential files; the coupling view
  already excludes them).
- **Consequence** — Tier 1: seeded from the repo's `.critical-paths`
  markers (the same file the completion gate's triage reads — one source of
  truth for "load-bearing by policy") plus path-class heuristics (gate
  policy files, security-adjacent paths, public contracts). Replaces the
  prototype's hand tags. Tier-2 enrichment (narrative consequence stories)
  is per-PR garnish, not the scoring input.

Estate scope: tracked files only (`git ls-files`) minus curated artifact
excludes (generated output, lockfiles, archives). A `.vizignore`-style
config surface is future work, not v1.

Drill panels carry per-file "what to check" stories (Tier-2, per-PR) subject
to the attention bar: anything mechanically catchable (deleted assertions,
lint-class findings) does not belong — the tool directs judgment, not
restated automation. Intra-file hotspot detail (function/hunk-level, PR
files only) ships in the V1 file drill as Tier-2 per-PR garnish on the same
bar.

### 6.3 V1 data build

V1 is nearly all Tier 1, rebuilt whole per PR — no sidecar dependency, no
staleness funnel in the critical path. The one genuinely novel join is the
**PR-scoped git+GitHub reconciler** (no OSS tool joins churn/coupling with
PR membership): PyDriller walks `merge-base..head`, `gh` supplies PR file
list and metadata, joined by commit-sha membership; disagreement between the
two sources is a loud drift error, not a silent union. Per-PR Tier-2 garnish
(drill stories, hotspot narratives) regenerates with the artifact.

V1 is the pipeline's tracer bullet: it exercises EXTRACT → ASSEMBLE, the
scene envelope, the artifact contract, and build-time playwright
verification, all without the inference/review machinery V2 needs.

## 7. V2 — Work-map artifact

### 7.1 Views

| View | Disposition | Verdict basis |
|---|---|---|
| **A — Flight-plan lanes** | build | strong keep: temporal lanes per plan, cross-plan edges, materialization slider with substrate accumulation ("insights I had not seen in the beads dependency tree") |
| **B — Territory map** | build | keep: spatial code-territory tiles, plan footprints, contested regions → quality-policy targeting |
| **C — Plan constellation** | **not built**; fleet-scale entry-view hypothesis (§11) | unique value over A+B unproven at 5-plan scale |

Requirements carried from the reaction rounds and fix pass (binding on
implementation): the deferred-mark standard and edge-kind chips of §4.4;
lane-label plan chips on every lane; `plans` / `regions` axis captions;
region and step drill drawers **track the slider** (items beyond it get the
upcoming/disabled look); step drill lists the underlying beads
hierarchically; edge drill mirrors plan chips and kind glyphs and names real
bead ids when an edge maps to encoded dependency edges; B's kind-group tiles
get a containment wash; the step-status key lives in the drawer it
describes. Step *naming* (synthesized names replacing bare order numbers) is
a low-priority experiment (§11).

### 7.2 Data model

`plans[]` (key, label, hue slot, status, steps[]) / `steps[]` (id, label,
1-based order, status, surfaces → region keys, **bead_ids[]**) / `regions[]`
(key, label, kind) / `edges[]` (id, endpoints as plan:step, kind, provenance,
materialization step, story, evidence). The **step→bead-ids mapping is
explicit and mandatory** — synthesized steps are a lossy narrative view over
real beads, and the mapping is what keeps the loss honest (and makes §7.3's
delta computable). Step ids are persistent across re-synthesis per the §5.3
reconciliation contract. Plan inclusion at build time uses the
plan-inclusion filter's persisted selection.

### 7.3 Step synthesis and the delta instrument

Steps are Tier-2 waypoints (4–6 per plan) synthesized from the plan's spec
and its bead subtree. The **step-vs-backlog delta** — synthesized narrative
vs actual bead hierarchy — is itself a product feature, not an error to
hide: the four delta triggers (§5.7: backlog gap, orphan work, granularity
mismatch, sequencing contradiction) compose the UI-initiated **"recommend
work-breakdown revision"** action. The user invokes it from a plan or step
drill; the agent responds with delta-cited recommendations whose `one-click`
members (mint beads, add edges, resequence) execute through the annotation
round-trip on acceptance. Delta *computation* is deterministic CLI code over
`steps.json` and the bead subtree; the skill adds only the narrative
recommendation layer on top.

### 7.4 Edge inference and review

Cross-plan edges are inferred per §5.2 (fixed enum, passage citations),
persisted per §5.3, aged per §5.4. Proposed edges render dashed (inferred)
until a human verdict lands; accepted edges render solid and promote into
beads. The review queue is the deliberate bottleneck: nothing mutates beads
without a Tier-3 verdict. Specimen reality check that sized this design:
of 10 real cross-plan edges identified across 5 plans, exactly 1 was encoded
in beads — the inference surface is ~90% of the value at current encoding
discipline, and edge promotion is what ratchets that percentage down.

### 7.5 Contested semantics

Three levels of interaction risk; a region badges the **highest level
present**, the legend defines all three:

- **L1 Co-located** — plans' predicted touch-sets intersect on files/regions.
  Weakest signal: co-location is not interference. Mechanical given
  touch-sets.
- **L2 Coupled** — touch-sets disjoint but in a tight dependency
  neighborhood (same graphify community, direct import edges, high co-change
  coupling). One plan's change ripples into the other's ground. Mechanical
  from the code graph, given touch-sets.
- **L3 Contradictory** — plans assert incompatible intents for the same
  element. Tier-2 inference from spec passages, never mechanical; L3 is the
  territorial projection of a conflict edge.

Honesty rule: touch-set *prediction* is Tier 1 only where beads/specs name
concrete surfaces; for prose-only plans it is Tier-2 inference, and the
touch-set's provenance carries through to the contention claim (a region can
be "L1 (inferred touch-set)" — solidity encoding applies).

**Temporal dimension:** a plan's **active span** is [first non-done step,
last non-done step] in step order, deferred steps excluded. A region's
contention window is the overlap of the contending plans' active spans
restricted to their region-touching steps; **contested-now** means the
window includes the plans' current frontiers (first non-done steps),
**contested-eventually** means it opens only at a future slider position.
Region contention state tracks the materialization slider exactly as the
drill drawers do. Guardrail recommendations key to level (§5.7).

## 8. V3 — Codebase evolution (direction only)

Direction: a timeline of the codebase's history in code *and* intent —
vision, architecture, and direction shifts — explored interactively with an
agent to surface patterns and lessons. No mockups, no data model, no view
designs in this spec: V3 gets its own reaction round before any build
(continuation, §14), because every V1/V2 view that skipped reaction rounds
would have shipped wrong.

Two F0 reservations bake in now so V3 never forces rework: the scene
contract's optional time-keyed event stream + snapshot keyframes (§4.4,
Gource's 5-field log as the adapter-friendly intermediate shape), and the
timeline-scrub affordance in shared controls (§4.5).

## 9. Security considerations

- **Stored self-XSS:** the annotation layer persists and re-renders user
  text, and drill panels render repo-derived strings. Binding rule (§4.5):
  data-bound or escaped, never innerHTML interpolation. Hardens further once
  notes round-trip through agents or artifacts render non-local data.
- **Mutation authority:** beads mutations (edge promotion, `one-click`
  executions) happen only on explicit human acceptance recorded as a Tier-3
  verdict. The overnight sweep is read-only + flag-only by construction.
- **Headless surface:** the cron sweep runs under fail-closed headless
  dispatch (explicit allowed-tools), and touches only `.viz/` Tier-2 files
  including `flags.json` (the flag queue); it never writes `verdicts.json`.
- Artifacts inline repo content and open locally; they are not published
  surfaces. Sharing one externally shares its embedded data — worth a
  one-line notice in artifact footers.

## 10. Test plan (behavioral contracts)

`packages/vizsuite` unit tests use fakes (scripted `bd`/`gh`/git fixtures),
no live services; artifact rendering is verified per-build by the skill's
playwright pass, not CI.

1. **Rung-1 reuse:** unchanged input fingerprints → inference layer never
   invoked (fake records zero calls); scene facts carry prior fingerprints.
   CLI-side assertion: the rung-3 queue stays empty and Tier-2 files are
   byte-stable.
2. **Rung-2 restamp:** diff outside a fact's cited passages → fact
   restamped, no model call; diff intersecting citations → fact queued for
   rung 3.
3. **Rejection memory:** a rejected edge re-derived with unchanged basis is
   suppressed; with changed basis it surfaces annotated with the prior
   rejection — never as fresh.
4. **Tier-3 preservation:** a full rebuild rewrites `edges.json` while
   `verdicts.json` is byte-identical; a verdict whose subject fact changed
   produces an orphaned-verdict flag in `flags.json`, and the verdict itself
   stays present and untouched.
5. **Promotion mapping:** accepted dependency edge between type-wall-legal
   beads mints `blocks`; epic↔task falls back to `related-to` with sidecar
   kind intact; re-accepting an already-promoted edge is a no-op.
6. **Assembly determinism:** same scene + template → byte-identical HTML
   modulo the build-stamp field.
7. **Escaping:** hostile fixture strings (`</textarea>`, `<script>`,
   `"><img onerror…`) in paths, stories, and notes render inert (asserted at
   the templating/escaping unit boundary).
8. **Schema gate:** the assembler rejects a scene whose Tier-2 facts lack
   provenance or citations — loud typed error, no silent default.
9. **Step-mapping integrity:** every synthesized step carries an explicit
   `bead_ids` list (empty ⇒ reported as backlog-gap delta); beads under a
   plan mapped by no step are reported as orphan-work delta — both surfaced,
   neither silently absorbed.
10. **Centrality corrections:** a fixture where self-edges would flip the
    load-bearing ranking scores correctly with them excluded; a fixture PR
    introducing new imports scores the new hub non-zero (projected
    centrality).
11. **Reconciler drift alarm:** PR file list disagreeing with the commit-walk
    file set → typed drift error, not a silent union.
12. **Envelope invariants:** machine verbs emit the JSON envelope on stdout
    with exit code mirroring `ok`, success and failure both.
13. **Identity survives re-synthesis:** a step re-synthesis that changes
    step count and order preserves step ids by bead-set overlap; every
    prior verdict still joins to its fact; a rejected edge whose endpoints
    renumbered stays suppressed.
14. **Apply idempotency:** replaying `viz apply` for each one-click
    mutation class (mint bead, add edge, relabel, resequence) is a no-op
    the second time — no duplicate beads, edges, or notes.
15. **Contested computation:** fixtures assert L1/L2 level assignment from
    touch-sets and the code graph, the badge-highest-level rule, touch-set
    provenance carry-through to the contention claim, and contested-now vs
    contested-eventually window derivation per §7.5.

## 11. Evaluation criteria (decisions this spec defers to evidence)

- **V1 dependency constellation:** after ≥3 real PRs reviewed with the
  artifact, does it change what the reviewer does versus treemap+ledger
  alone? Keep on yes; retire to the sonar's fate on no. (Its round-3 verdict
  was "if it became less cumbersome, useful" — cumbersomeness is fixed;
  utility is the open question.)
- **V2 plan constellation as fleet-scale entry view:** re-evaluate when the
  active-plan count reaches ~10+ or when A/B legibility degrades despite the
  inclusion filter. Hypothesis: C is the zoom-out entry view that links into
  A and B, not a peer view. Requires its own reaction round before build.
- **Step-naming experiment (low-priority):** synthesized per-plan step names
  replacing bare order numbers in B's drawer and A's axis; judged in the V2
  build's reaction round.
- **Suite-level success:** V2 — at least one sequencing/scope/guardrail
  decision per planning week traceable to the map; V1 — review attention
  measurably shifts to flagged surfaces (proxy for the prime-directive
  metric, interventions per merged PR). Crude counters beat no counters;
  implementation plans wire the measurement.

## 12. Out of scope

- Any server, daemon, live polling, or file watcher (no-fragile-infra).
- V3 build work of any kind (direction + reservations only, §8).
- Autonomous beads mutation — no inference result touches beads without a
  Tier-3 verdict.
- Replacing graphify, beads CLI surfaces, or the explain-diff skill
  (integration with explain-diff is a plausible follow-up, not this spec).
- `.vizignore` config surface (future).
- A standalone web app or hosted anything.

## 13. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` package `packages/vizsuite/`, CLI `viz`, skill `viz` in the
  Claude tree — names trivially changeable at implementation.
- `ASSUMPTION:` sidecar at `.viz/` with the §5.3 file split; artifacts under
  `.viz/out/` gitignored.
- `ASSUMPTION:` edge-promotion mapping (§5.3) — dependency→`blocks` with
  `related-to` type-wall fallback; overlap/conflict/synergy→`related-to` +
  sidecar-authoritative kind. Refines the promotion decision via its own
  "everything beads cannot express lives in the sidecar" clause.
- `ASSUMPTION:` consequence axis seeded from `.critical-paths` (§6.2) —
  shares the completion gate's source of truth rather than inventing a
  second consequence registry.
- `ASSUMPTION:` rejection-memory identity = coarse key (endpoints + kind)
  with basis-change resurface-annotated semantics (§5.3).
- `ASSUMPTION:` V1 ships first as the pipeline tracer bullet (§6.3); V2's
  inference/review machinery lands second.
- `ASSUMPTION:` machine verbs adopt the work-facade JSON-envelope pattern.
- `ASSUMPTION:` viz vocabulary stays in this spec; multi-context
  `CONTEXT-MAP.md` promotion is offered, not assumed.
- `ASSUMPTION:` bead-anchored fact identity (§5.3) — steps inherit ids by
  bead-set majority-overlap on re-synthesis; endpoint identity falls back
  to passage fingerprints only where a step maps to zero beads.
- `ASSUMPTION:` annotation durability — a note not yet round-tripped lives
  only in browser localStorage; the unprocessed-note banner (§4.5) is the
  mitigation and the residual loss window is accepted.

## Continuations

- feat: `packages/vizsuite` scaffold + V1 data build — Tier-1 extractors
  (PyDriller, scc, graphify, `gh`), the PR-scoped git+GitHub reconciler,
  scene envelope + assembly to self-contained HTML, `viz pr` — AC: test-plan
  items 6–8, 10–12 pass under `make ci-vizsuite`; the two unverified OSS
  sub-claims (cc.json checksum, doit hash mechanism) confirmed from source
  and recorded in the implementation plan.
- feat: V1 PR-shape views — estate treemap (collapse/reflow, worst-offender
  roll-up, label declutter), attention ledger (separated/mixed toggle, diff
  links), file-sonar drill with intra-file hotspot listing (PR files),
  constellation (evaluation-gated), heat model per §6.2 with slider
  explanation layer — AC: playwright-verified against ≥2 real PRs; §6.1
  requirements demonstrated.
- feat: sidecar + staleness funnel + review queue (CLI side) — `.viz/`
  read/write incl. `flags.json`, fingerprint manifest, rungs 1–2, verdict
  recording, edge promotion with type-wall mapping, `viz apply` mutation
  classes — AC: test-plan items 1–5, 9, 13–14 pass.
- feat: `viz` skill — rebuild driving, rung-3 doubt checks, edge/step
  inference (fixed enum + passage citations), review-queue flow, annotation
  round-trip incl. claude-in-chrome enhancement — AC: end-to-end on this
  repo: infer → review → verdict → promotion visible in beads; rejection
  memory honored across a rebuild.
- feat: V2 work-map artifact — lanes + territory views per §7 requirements,
  materialization slider with slider-tracking drills, contested L1–L3
  badging with temporal window — AC: playwright-verified; test-plan item 15
  passes; reaction round with the owner recorded; step-naming experiment
  included and judged.
- chore: overnight sweep cron recipe — CLI rungs 1–2 + headless cheap-model
  rung 3, flag-only, fail-closed tool allowlist — AC: a scheduled run
  produces a morning queue report with zero beads writes.
- eval: V1 constellation verdict — run ≥3 real PRs through the artifact,
  record keep/retire per §11 — AC: verdict recorded in the epic; view
  retired or promoted accordingly.
- design: V3 reaction round — mockup round for codebase-evolution views
  gated on V1/V2 shipping; produces V3's own dated spec — AC: reaction
  verdicts recorded; scene-contract time reservation validated or amended.
