# Decision Record: Convergence Criteria for Adversarial QA Loops

**Date:** 2026-07-03
**Status:** Decision record — informs a future convergence-discipline design effort (its own bead lineage under M3). Not itself a spec or plan; no implementation is authorized by this document.
**Origin:** Brainstorm-only spin-off session (handoff `handoff-20260703T095106Z-adversarial-loop-convergence.md`).
**Provenance:** Discovered from bead `agents-config-abn9.38` (completion-gate routing design). The routing spec (`docs/specs/2026-07-02-completion-gate-routing-design.md`, §7) cites this record as the authoritative resolution of its convergence open question; the routing spec itself is *not* expanded to carry this design.

## TL;DR

Replace "reviewer goes quiet" termination with a **dual-signal convergence discipline**: an *acceptance* exit (findings ledger clean at severity floor AND delta-discovery dry in the same round, confirmed by a final certification pass) distinct from a *termination* exit (round cap / stall / budget — an economic backstop that emits a residual-risk report, never a quality claim). The loop is restructured so convergence is **geometric rather than statistical**: initial full-surface review up front, then delta-scoped iterative rounds whose review surface shrinks with the fixes, verified by a memoryful closure verifier and judged by a rubric'd triage bench. Packaged as one shared convergence discipline (rule + primer + contracts + deterministic helpers) with per-loop bindings — not per-loop reinventions, not a monolithic engine.

## Problem (evidence recap)

Field evidence from the parent spec's 8-round adversarial review campaign and the wgclw.14 gate run (PR #209, run `wf_b92cfaa9-d58`):

- **A — adversarial finders never go dry.** High findings per round ran 2,2,2,2,2,1,2,1 with every verdict "needs-attention"; behavior consistent with best-N-per-fresh-read, not draining a finite pool. The coded stop ("zero highs") was unreachable.
- **B — the usable signal wasn't coded.** Fix-*class* decayed visibly (rounds 1–3 design changes → 4–6 coverage-model changes → 7–8 boundary hardening); a human could call the knee (~round 6); the loop measured reviewer output instead.
- **C — refuter panels never refute.** 0 refutations across 24 votes; opinion-poll panels provide no discrimination.
- **D — some reviewers decay naturally.** Copilot: 1 real finding round 1, 0 round 2. Reviewer types have different physics.
- Schema dig: the codex adversarial-review prompt never forbids approval (`approve` is a first-class verdict); best-N-forever is **emergent**, so re-prompting alone will not fix it. Severity is finder-self-assigned, which is where inflation entered (rounds 7–8 defense-in-depth items scored "high").
- 7 of the campaign's 16 findings were enumeration-gap (completeness-shaped) findings with no scope judge to discriminate them — the un-named persona behind the scope creep.

## Core decisions

### D1 — Dual-signal stop semantics
Acceptance ("artifact meets bar X") and termination ("further rounds aren't earning their cost") are separate signals; every exit reports which one fired. Termination-side exits emit an explicit residual-risk statement — never a silent pass.

### D2 — Consumer of the stop decision: phased report → rule
Near-term the loop emits a residual-risk report a human reads at the gate; the metrics contract (D11) is designed from day one so accumulated calibration data can later justify rule-based autonomous proceed decisions (M4). Judgment hardens into rules on evidence, not vibes.

### D3 — Use-case taxonomy
- **UC1 — document review** (specs/designs/plans/requirements): triggered when the author — human+agent or **agent solo** — declares the artifact reviewable. No mechanical acceptance anchor exists for prose.
- **UC2 — code QA** (completion gate / quality-gate / ralf-implement): triggered by a completion claim **or an orchestrator mid-plan checkpoint** (tracer-bullet reviews). Mechanical anchors exist; verify-checklist step 5 remains non-substitutable.
- **UC3 — PR feedback loops** (wait-for-pr-comments / monitor-pr / prgroom): reactive to external reviewers on their own cadence. **Adopt pieces, don't rebuild** (see D13).
- Refuter/verify panels are a *mechanism*, not a use case; they are replaced by the judge layer (D8).

### D4 — Review lifecycle (UC1/UC2)
- **Phase 0 — Assessor.** Decides whether review is needed and emits the **review plan**: lens roster, invited specialists, depth, round caps, rubric selection, acceptance bindings, adjudication authority, fix-class → lens routing table. Includes the readiness bounce ("not reviewable yet — here's what's missing"). Fail-closed defaults per artifact class guard against self-serving under-review (the code-tier analog is the parent spec's SKIP guardrails). For UC2, Phase 0 already exists as the parent spec's routing tiers.
- **Phase 1a — Conceptual stabilization.** Settle the shape before spending on depth. UC1: consistency + alternatives + scope-overreach. UC2: plan-fidelity + materialization-informed approach reassessment + placement/belonging (does this code live where it should; domain fidelity; duplication; promote-to-utility).
- **Phase 1b — Deep review.** Soundness, context-impact, and invited completeness specialists (security, test-quality, scalability, performance, …), each self-gating on "is my expertise needed here, and is it missing?"
- **Phase 2 — Iterative loop.** Delta-scoped rounds (D5–D7).
- **Phase 3 — Final certification.** The question flips from discovery to certification: full-fresh pass covering whole-artifact consistency, aggregate scope drift, ledger completeness, residual-risk synthesis. Emits the dual-signal verdict.
- Cost shape: heavy → light per round → medium (the campaign's failure shape was heavy ×8).

### D5 — Lens physics (why the campaign never converged)
Lenses have different drain characteristics and must not be run as one undifferentiated reviewer:
- **Consistency** drains; loops fine.
- **Soundness / context-impact** semi-drain; re-enter the loop only when a fix changes design structure / system touchpoints (fix-class routing).
- **Alternatives/optimality never drains** — it is bounded by *adjudication*, not dryness: each alternative is adopted or rejected-with-rationale via the canonical decision matrix, recorded in decision records, and dead forever absent new evidence. Runs in Phase 1a only; excluded from the loop. In UC2, bounded optimality = the simplify axes; approach-level alternatives live upstream in UC1.
- **Completeness** proposes additions; **scope** disposes of them (bidirectional guardrail: doc overreach AND reviewer scope-creep). One generates, one discriminates — never fused into one agent.

### D6 — Round anatomy (Phase 2)
Per round, in order:
1. **Closure verifier** (memoryful by design): receives ledger + fixed artifact; per-finding verdict fixed / not-fixed / partial / fix-created-new-concern; also assigns the judgment-level **fix-class** per finding. UC2 runs mechanical checks first (regression tests close findings); the agent verifies the residue.
2. **Delta discoverer** (memoryless by design): fresh eyes on fix diff + blast radius only (prose blast radius: referencing sections, moved term definitions); never sees the ledger. Lens set routed by plan's routing table applied to fix-classes.
3. **Evidence verifiers** (per-finding, parallel): validity by citation or repro, never by vote.
4. **Triage bench** (one batch judge): provenance-blind; written consequence-anchored rubric; **ranks before scoring** severity; scope rulings; dedup vs seen-fingerprints and decision records; disposition recommendations.
5. **Fix wave**: fixer applies dispositions; alternatives-shaped findings route to decision-matrix adjudication instead of "fixing."

Routing responsibility split: the **plan** holds the rules; the facts come from a **deterministic mechanical pre-classifier** (diff surface: sections/files touched, size, structural markers — no LLM) plus the closure verifier's fix-class judgments; the **orchestrator applies rule(fact)** — it routes and counts, never judges. The fixer never self-classifies its fix.

### D7 — Delta-scoping + full final
Iterative rounds review only the change surface; Phase 3 is the deliberate full-fresh read that catches emergent whole-artifact issues. This starves the best-N generator structurally — shrinking deltas mean shrinking surface mean findings that decay because they must. Phase 3 may bounce the artifact back into the loop **once**; a second Phase-3 failure converts to termination-side exit (bounds oscillation).

### D8 — Judge layer (replaces refuter panels)
- Validity is **evidence-shaped and per-finding** ("quote the contradicting lines", "show the repro") — the campaign's verify-before-acting practice, which went 16/16. Opinion-poll refuter panels are retired (wgclw.14: 0/24, no discrimination, 3× the cost).
- Severity, scope, and dedup are **comparative, batch-shaped** — a single triage bench per round with rank-anchoring; severity is never the finder's own score.
- Conflict-of-interest matrix: no agent wears two hats in one round — finder never scores own severity, fixer never verifies/classifies own fix, orchestrator never judges.
- Panels may earn their way back only via measured bench mis-calibration (metrics contract), not nervousness.

### D9 — Convergence predicate
**Acceptance-side exit** (loop → Phase 3), both in the same round:
1. Ledger clean at the plan's severity floor (default: no open blocking/critical/major; a major survives only via explicit decision-matrix adjudication into residuals).
2. Delta discovery produced zero novel verified findings at/above floor (novel = post-verification, post-bench dedup/scope).
One dry round suffices because the surface shrinks structurally (dry-on-a-delta is geometric evidence, not the statistical kind the campaign lacked).

**Termination-side exit** (any one): round cap from the plan (default small, 3–5 — a backstop, not a quality claim); **stall** (a round that closes nothing and discovers nothing novel while the ledger is non-empty — fixes aren't landing); budget exhaustion.

Every exit emits a verdict object: which signal fired, ledger state, residuals with bench severities, rejected-alternatives ledger, round metrics.

### D10 — At-cap / termination protocol
Routes by the plan's declared policy: low-stakes artifact classes may proceed-with-documented-residuals; everything else parks for human decision. Overnight runs park to the morning queue with the report attached — never block silently, never self-approve. Escalation shape follows the canonical decision matrix (the campaign's ad-hoc "human authorizes an extension" becomes a policy the plan declares up front).

### D11 — Metrics contract + learning loop
Recorded per round by deterministic scripts: round number; delta surface size; findings raw → verified → novel → dup; per-lens counts; **finder-claimed vs bench-scored severity** (the inflation measure); fix-class distribution; closure rate; tokens; wall time; exit signal. Per review: plan, phases run, verdict, residuals, Phase-3 bounces.
Accumulated metrics + ledgers feed a periodic **pattern miner** that distills a durable **project review profile** ("enumeration-gap findings recur → invite completeness specialist by default"; "lens X: zero verified-real in 12 reviews → drop it"), consumed by the Phase-0 assessor. **Schema ships now; miner is a follow-up bead** (needs data to mine). This is the report→rule ratchet made mechanical.

### D12 — Independence invariant re-scoped
Independence is a **discovery** virtue, not a review-wide one. The closure verifier is memoryful on purpose (verification wants contamination — it audits specific claims); the delta discoverer stays strictly memoryless. ralf's blanket "prior findings never injected" invariant is amended to discovery-only.

### D13 — UC3: adopt, don't rebuild
UC3 keeps its field-proven state-machine skeleton (prgroom phases, thread lifecycle, round cap) and adopts: dual-signal exit reporting in terminal states, **stall detection** for the documented re-classification infinite-loop hazard (the cap never fires without a new external review), metrics fields mapped onto prgroom's envelope, and formal recognition of FIX/SKIP/ESCALATE classification as a triage-bench instance (rubric vocabulary aligned).

### D14 — Packaging: shared discipline + per-loop bindings (Approach A)
One shared artifact set (rule + primer in the merge-guard mold): dual-signal semantics, lifecycle, round anatomy, predicate, conflict-of-interest matrix, metrics contract. Determinism in helper scripts (ledger ops, predicate evaluation, dedup fingerprinting, pre-classifier, metrics recording); judgment in prose contracts (personas, rubrics). Loops bind, not rebuild.
**Rejected:** B — per-loop implementations with shared vocabulary only (the repo already ran this experiment: three drifting termination mechanisms); C — one monolithic orchestration engine (couples UC1/UC2 to the Claude-only Workflow harness against the portability pillar; churns working UC3; front-loads build before calibration data exists).

### D15 — Composability requirement
Parts that make sense to compose must be reusable outside the loops; no reusability theater. Tiers:
- **Roles/personas** (specialist finders with self-gate, evidence verifier, triage bench) — usable in any loop, ad-hoc reviews, UC3 triage.
- **Data contracts** (review plan, findings ledger, decision records, verdict object, metrics) — first-class from day one; they are what makes everything else composable.
- **Deterministic helpers** (scripts).
- **Phase invocables** — each phase independently callable (assessor alone; single round; certification pass alone), extracted **when a real caller appears**, not pre-built. Likely early extractions: assessor (sibling of the M2 brainstorm-readiness gate), certification pass (legacy/externally-reviewed docs).
- **Lifecycle compositions** — full UC1/UC2 flows; serial skill path (portable) and Workflow-script path (Claude opt-in) as two implementations of one contract, per the parent bead's principle.

## Handoff open questions → resolutions

1. **Architectural-delta / fix-class novelty** — adopted as the *router* and part of the convergence evidence, not a standalone stop metric. Judged by the closure verifier + mechanical pre-classifier against the plan's routing table (D6), never by the fixer.
2. **Capped rounds + severity triage at cap** — cap retained as economic backstop only (D9); at-cap protocol becomes declared plan policy instead of ad-hoc human extension (D10).
3. **Cross-round recurrence dedup** — retained as bench input (seen-fingerprints), but it is *not* the termination measure; delta-scoping makes termination geometric instead (D7).
4. **Independent severity re-scoring** — adopted: the triage bench with rank-anchoring; finder severity is never authoritative (D8).
5. **Calibration probes** — **deferred/rejected for v1** (cost + contamination); observational calibration via the metrics contract instead (D11).
6. **Cost-per-confirmed-finding curve** — subsumed: budget exhaustion + stall detection cover the economic stop; no curve-fitting needed at current scale (D9).
7. **Reviewer-type taxonomy** — adopted as the persona-physics table (generator / decayer / deterministic gate / panel); stop conditions are typed by persona; the adversarial framing is not "fixed" by re-prompting (emergent behavior) but by restructuring what the reviewer is asked to look at (delta-scoping, certification flip) (D5, D7).
8. **Refuter calibration** — resolved by retiring opinion-poll refuters for evidence-based verification + rubric'd bench (D8). The wgclw.14 0/24 result is thereby moot rather than answered.
9. **Placement** — shared primitive + per-loop bindings (D14); UC3 adopts pieces only (D13).
10. **Metrics contract** — defined (D11).

## Follow-up bead candidates

Enumerated here for the convergence-discipline design effort to decompose when its spec is written (not filed as separate beads now — the effort owns one lineage-root epic until then):

1. **Brainstorming skill: decision-records requirement** — brainstorm-produced docs carry decision records; review augments them (kills relitigation at both ends). Consider `bd decision` as machinery.
2. **Pattern miner + project review profile** — after metrics accumulate; schema ships with the main work.
3. **Artifact templates with review-anchor sections** (specs, designs, PRs, PR replies, reviews) — scope charter, decision records, assumptions sections make Phase-0 readiness partly mechanical and give scope/alternatives lenses their anchors. Keep thin; machine-checkable conformance.
4. **ralf-review / ralf-implement amendments** — adopt the predicate; re-scope independence to discovery-only (D12).
5. **UC3 adoptions** — stall detection + dual-signal terminal reporting in wait-for-pr-comments / prgroom envelope mapping (D13).
6. **Per-artifact-class rubric authoring** — consequence-anchored severity definitions the bench applies.

## Disposition (originating session, 2026-07-03)

The originating session (abn9.38) considered this record and made a placement decision:

- **abn9.38 stays narrow.** The routing spec (`2026-07-02-completion-gate-routing-design.md`) is *not* expanded to own this discipline. Its §7 is amended only to state the convergence decision at a high level and point here as authoritative — keeping the routing spec about routing, per the "don't amplify pre-work that may not survive implementation" principle.
- **This discipline gets its own bead lineage** (a design-effort epic under M3, `discovered-from` abn9.38). The full D4–D14 design is not built as part of abn9.38; it earns its own brainstorm → spec → plan → implementation cycle. The six follow-up candidates above are decomposed there, not filed now.
- **One critique carried forward from the originating session** (for the future spec to resolve, not settled here): tier-gate the convergence loop itself. Even the minimum viable Phase-2 round is five roles; a small change should not convene the full bench. The Phase-0 assessor's plan is the natural place to scale the roster down — confirm it can go genuinely lean at the small end, the same lesson the routing tiers apply, recursively.
