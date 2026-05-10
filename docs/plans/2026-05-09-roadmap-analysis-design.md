# Roadmap Analysis — Design Spec

**Date:** 2026-05-09
**Author:** Claude (orchestrator) with Scott (architect)
**Output artifact:** `docs/plans/2026-05-09-roadmap.md` (produced by executing this design)
**Status:** Design approved, awaiting Scott's spec review before transition to writing-plans

---

## 1. Purpose

Produce a strategic roadmap for the agents-config project that:

- Analyzes the current backlog (open + in_progress + closed-30d) to recognize connections, dependencies, and natural sequencing.
- Identifies the fastest path to a working, stable MVP, with milestones ahead of MVP if pre-MVP stabilization is warranted.
- Defines post-MVP releases as **business outcomes coherently meaningful to a user**.
- Recommends cuts, deferrals, and structural changes (dependency edges, parent assignments, labels) where the existing bead structure does not serve roadmap-coherent sequencing.

The roadmap doc is the deliverable. Beadification (restructuring beads to reflect the roadmap) is a separately-gated follow-up phase.

## 2. Audience

- **Primary:** Scott, dogfooding the harness daily as the architect of this project.
- **Secondary:** broader AI-assisted devs who may eventually adopt this configuration.

Each milestone is tagged with a "broader-adopter readiness" label (YES / PARTIAL / NO), but readiness is **not** a gate on advancing milestones — Scott's dogfooding bar is the primary criterion.

## 3. Constraints baked into the analysis

| Constraint | Scott's directive |
|---|---|
| MVP framing | "Let the analysis tell us" — produce 2-3 framing options at synthesis, Scott picks at review |
| Bead scan scope | Open + in_progress + recently closed (last 30 days) |
| Output form | Markdown doc first; beadification only on explicit approval |
| Time horizon | Analysis decides milestone count, capped at 5 |
| In-progress treatment | Honor by default, flag exceptions with rationale |
| Stability bar (pre-MVP) | Active bugs in formulas/molecules + documented contradictions in instructions only. Architectural incompleteness and multi-tool drift are NOT stability blockers. |
| Cut latitude | Sequence + recommend cuts/deferrals with rationale (Scott decides at review) |
| Structural authority | The existing bead structure (deps, parents, labels) is **not sacred**. Forks may propose remove/add/reparent/relabel changes. |

## 4. Method — five-phase pipeline

```
PHASE 1 (parallel forks) → PHASE 2 (checkpoint) → PHASE 3 (synthesis) → PHASE 4 (doc)
                                                                              │
                                                              [Scott reviews] │
                                                                              ▼
                                                       PHASE 5 (deferred, opt-in)
                                                       5a: ralf-review
                                                       5b: staged beadification
```

### Phase 1 — Parallel discovery

Three forks dispatched in a single message, each writing its digest to `/tmp/roadmap-fork-{a,b,c}.md`.

| Fork | Model | Effort | Mission |
|---|---|---|---|
| **A — Inventory & Cluster** | sonnet 4.6 | medium | Thematic clustering by *what beads are trying to achieve*. Flag title/intent mismatch. |
| **B — Dependency Critique** | sonnet 4.6 | high | Walk current edges/parents/labels; **critique them**. Propose REMOVE EDGE / ADD EDGE / REPARENT / SUSPECT LABEL with bead-pair + evidence. |
| **C — Vision Alignment** | sonnet 4.6 | high | Tag each bead load-bearing / multiplier / hygiene / off-thesis vs the 5 commitments in AGENTS.md. Flag label drift on `vision-85-5-10`. |

**Cross-fork rules:**
- Forks do not communicate with each other; independence is a feature.
- Each fork returns a structured digest (≤500 words narrative + as many proposal-table rows as warranted).
- Forks do NOT stream raw bead transcripts back; synthesis happens by reading the digests.
- Anti-pattern (all forks): no bead-id without title; no proposal without bead-pair-or-bead+context evidence.

### Phase 2 — Checkpoint

Single message from orchestrator to Scott, structured:

- Per-fork narrative digest (3-5 sentences).
- Per-fork proposal tables (every flagged bead shown with **id + title + outcome where unclear**, every proposal with one-line rationale).
- Cross-fork tensions section (places where forks disagree, with orchestrator's read of the disagreement).
- Intended synthesis posture (how orchestrator plans to weight cluster vs. dep critique vs. vision alignment).

**No word ceiling** — discipline is one-line rationale per row, not artificial brevity. If checkpoint exceeds ~3000 words, proposal tables split out to `/tmp/roadmap-checkpoint-tables.md` with a one-line preview in the message body.

**Scott's response options:**
1. Green-light → proceed to synthesis
2. Redirect → re-dispatch a fork or fold steer into synthesis
3. Add a lens → extend synthesis brief
4. Pull-back → "show me Fork-X's full digest" → orchestrator surfaces specific findings

### Phase 3 — Synthesis

- **Model:** opus[1m] xhigh effort
- **Inputs:** all three fork digests + Scott's checkpoint feedback
- **Outputs:** drafted milestone definitions, sequencing rationale, cross-fork tension resolutions, cut/defer recommendations, vision-gap acknowledgments, structural-change recommendations queued for beadification

### Phase 4 — Doc

Write `docs/plans/2026-05-09-roadmap.md` with the structure defined in Section 5 below. Self-review pass before handoff.

### Phase 5 (deferred, opt-in)

Only runs after Scott's explicit go following review of the roadmap doc.

**5a — Adversarial review (`ralf-review`):**
- Target: the roadmap doc
- Model: opus xhigh, max 2 cycles
- Criteria:
  1. Sequence soundness (no milestone N depends on milestone N+k content)
  2. DoD verifiability (every DoD criterion mechanically or behaviorally checkable)
  3. Business-outcome coherence (each milestone headline survives "could a user describe this as meaningful?")
  4. Vision-gap honesty (commitments not served by any milestone are explicitly acknowledged)
  5. Cut-rationale strength (each cut withstands contrarian read)
  6. Risk realism (per-milestone risks named, not hand-waved)
- Output: revised doc with diff summary header documenting what changed and why

**5b — Beadification, in stages with per-stage rollback:**
1. Create milestone epics
2. Re-parent in-scope beads (pre-state captured to `/tmp/roadmap-beadify-pre-state.jsonl`)
3. Apply structural changes (REMOVE/ADD edges, REPARENT, SUSPECT LABEL)
4. Apply cut/defer decisions
5. Apply title/intent retitles (only those Scott approved at doc review)
6. Audit pass — regenerate cluster + dep walks, confirm new structure matches doc

**Boundaries on beadification:**
- No description rewrites — descriptions stay Scott's authorship; retitles only.
- Closed beads not touched (other than reopening cut-rollbacks).
- No remote push / dolt sync — that's a session-completion concern.
- Each stage pauses for Scott's continue/stop/rollback decision.

## 5. Roadmap doc structure (`docs/plans/2026-05-09-roadmap.md`)

```
1. Scope & method
2. Vision recap (synthesized through "what this means for the next 3-5 milestones")
3. Where the backlog stands today (cluster shape, vision distribution, structural health)
4. Milestones (analysis-decided count, ≤5)
   For each:
     - User-capability headline
     - Business outcome (1-2 sentences)
     - Broader-adopter readiness: YES / PARTIAL / NO
     - Definition of Done (mechanically or behaviorally verifiable bullets)
     - Beads in scope (id + title + role table)
     - Dependencies on prior milestones
     - Risks & open questions
     - Estimated relative effort: S / M / L / XL
5. Cross-cutting decisions baked into the sequence
6. Recommended cuts and deferrals (id + title + recommendation + rationale)
7. Vision gaps NOT addressed by any milestone
8. Structural changes recommended (separate from milestone work)
9. Open questions for Scott (with options + recommendation + rationale per question)
```

### Schema enforcement

- Every bead reference: **id + title minimum**; outcome added where title is unclear. No naked IDs.
- Every milestone DoD criterion: **mechanically or behaviorally verifiable**. "Feature X exists" is insufficient; "the brainstorm-readiness gate rejects beads missing AC bullets, observable via `bd update --status implementation-ready` returning a refusal" is the bar.
- Every cut/defer recommendation: **one-sentence rationale citing evidence**. "Off-thesis" alone is insufficient.

### Self-review pass (before handoff)

1. Placeholder scan (no TBD, no vague language)
2. DoD verifiability check
3. Bead-reference completeness (no naked IDs)
4. Cut-rationale evidence (each cite specific evidence)
5. Cross-section consistency (milestone N+1 doesn't reference beads cut in section 6)
6. Open-questions discipline (anything decidable from codebase or prior answers gets removed; orchestrator escalated lazily otherwise)

Issues fixed inline; no re-review loop.

### Handoff message format

> "Roadmap drafted at `docs/plans/2026-05-09-roadmap.md`. Highlights: [3-5 bullet headline of milestone shape]. Open questions for you: [count]. Recommended cuts: [count]. Please review when ready — your call on whether to proceed to the optional adversarial-review phase."

Orchestrator does NOT begin Phase 5 without Scott's explicit go.

## 6. Model selection summary

| Role | Model | Effort | Justification |
|---|---|---|---|
| Orchestrator (synthesis, doc, handoff) | opus[1m] | xhigh | 1M context holds 3 fork outputs + brainstorm context + vision docs simultaneously; synthesis is the load-bearing reasoning step |
| Fork-A — Inventory & Cluster | sonnet 4.6 | medium | Thematic clustering is mostly mechanical with light pattern recognition |
| Fork-B — Dependency Critique | sonnet 4.6 | **high** | Critique of existing structure requires cross-bead judgment; Scott explicitly chose to invest in precision over speed |
| Fork-C — Vision Alignment | sonnet 4.6 | high | Judgment-heaviest fork; alignment calls drive load-bearing tagging |
| ralf-review (Phase 5a, deferred) | opus | xhigh | Adversarial pressure-test on the milestone proposal |

## 7. Files & artifacts

| Path | Producer | Consumer |
|---|---|---|
| `/tmp/roadmap-fork-a.md` | Fork-A | Orchestrator (read on demand) |
| `/tmp/roadmap-fork-b.md` | Fork-B | Orchestrator (read on demand) |
| `/tmp/roadmap-fork-c.md` | Fork-C | Orchestrator (read on demand) |
| `/tmp/roadmap-checkpoint-tables.md` | Orchestrator (if checkpoint > 3000w) | Scott |
| `docs/plans/2026-05-09-roadmap.md` | Orchestrator (Phase 4) | Scott (review), ralf-review (Phase 5a) |
| `/tmp/roadmap-beadify-pre-state.jsonl` | Orchestrator (Phase 5b stage 2) | Rollback path |

## 8. Decision log

| Decision | Outcome |
|---|---|
| Multi-agent team vs orchestrated subagents | Orchestrated subagents — roadmap must speak with one voice |
| Visual companion offer | Skipped — most brainstorming questions are conceptual; roadmap output may include mermaid diagrams as needed |
| Word ceiling on checkpoint | Removed — quality of gate > brevity; discipline replaces ceiling |
| Forks trust existing structure | NO — Fork-B has explicit critique license; Forks A & C have analogous license for clusters and labels |
| Description rewrites in beadification | Out of scope — retitles only; descriptions remain Scott's authorship |

## 9. Out of scope for this design

- The contents of the roadmap itself — that is the *output* of executing this design, not the design's responsibility.
- Wall-clock estimates — relative effort only (S / M / L / XL).
- CI/CD or deployment automation for the roadmap doc.
- Dolt/remote push of beadification results — session-completion concern.

## 10. Next step (after Scott's spec review)

Transition to `superpowers:writing-plans` skill to produce the implementation plan that drives execution of Phases 1-4. The plan will:

- Sequence the parallel-fork dispatch as a single Agent-tool call with three sub-invocations.
- Encode the checkpoint message structure as a literal template.
- Specify orchestrator's synthesis prompt for Phase 3.
- Define the doc-writing checkpoints with self-review steps.

Phase 5 gets its own implementation plan, written only after Scott approves the Phase 4 output.
