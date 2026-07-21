# Harness Self-Obstruction — Findings Handoff

**Date:** 2026-07-20
**Author:** Fable 5 (xhigh effort), session `5a052aa7-7b5c-4246-b62d-f1d03e2c7085`, running *inside* the fully-loaded harness (deliberately — its own context window served as evidence)
**Audience:** A fresh Fable session started with minimal/no harness context, for a way-forward dialog with Scott
**Scope:** Findings and rationale only. **No plan or recommendations ranking is included by design** — the way forward is the next session's job, uninfluenced by this harness's memory and rules.
**Companion:** `SAVEPOINTS/LEFT-OFF-NOTES.md` (Scott's symptom list and suspicions, plus the full raw verdicts of three frontier-model audits with their resume handles)

---

## 1. The system under analysis

`agents-config` (~/src/projects/agents-config) is Scott's versioned "discipline layer" for AI coding assistants: agents, skills, rules, commands, and templates installed into user space (`~/.claude/`, `~/.codex/`, etc.) for Claude Code, Codex CLI, Gemini CLI, and OpenCode. Its stated mission: make AI development reliably autonomous by frontloading human judgment (brainstorming/specs), gating completion claims with mechanical evidence, and eventually running implementation on cheap models (milestones M1/M3). Its stated prime directive: **reduce human interventions per merged PR** — a metric it does not currently measure. Key subsystems: a brainstorming→writing-plans→TDD→completion-gate→PR pipeline of prose skills; typed Python packages (`prgroom` PR-grooming CLI, `workcli`, an early `pdlc` orchestrator); a beads work tracker; merge authorization machinery (merge-guard).

## 2. Observed symptoms (Scott, 2026-07-19)

1. Seemingly simple changes take far too long to reach PR stage.
2. PR reviews ping-pong: Codex/Copilot leave comments → agents fix → local review looks clean → push → **another** batch of comments. Cycle repeats, eating time and tokens.
3. The PR reviewers find things ranging from fundamental oversights to doc/code inconsistencies — and the in-house up-front reviewers are not catching them first.

Scott's added suspicions: the harness itself may be degrading model decision/review quality; the brainstorming skill may produce under-specified specs (missing acceptance criteria); plan docs are prescriptive down to literal code and bash (and eat review bandwidth); specs/plans may be too long for models to review well.

## 3. Method and provenance

Three independent frontier audits were run first (full text in LEFT-OFF-NOTES.md): **Fable 5 at medium effort** (2026-07-19), **GPT-5.6**, and **GLM-5.2**. Then this session — Fable 5 at xhigh — cross-examined all three and independently verified the load-bearing claims on disk and against its own live context window.

Provenance tags used below:
- **[V]** — verified directly by this session on 2026-07-20 (command/file cited).
- **[R]** — reported by one of the three audits; carried here with its citation, **not** re-verified by this session.

## 4. Verified evidence base

1. **[V] Two full config trees are deployed and both load into every session.** `/Users/scott/home2/.claude/` (13 rules) and `/Users/scott/.claude/` (15 rules) both exist; the live session context contains both trees' AGENTS.md and rules in full. (`ls` of both `rules/` dirs; direct observation of session context.)
2. **[V] The stale tree is mislabeled with higher authority.** The harness loads `/Users/scott/.claude/` as *"project instructions, checked into the codebase"* (ancestor-directory pickup — repos live under `/Users/scott/src/`), while `home2` loads as user-global. Project-labeled config reads as more authoritative than user config, so conflicts resolve **toward the stale tree**.
3. **[V] The only Codex routing rules live in the stale tree, and they contradict each other.** `claude-to-codex-routing.md` (model roster gpt-5.5 / gpt-5.4-mini) and `codex-routing.md` (roster gpt-5.6-sol / -terra / -luna) coexist in `/Users/scott/.claude/rules/` only; `home2` has neither.
4. **[V] 37 of 67 design specs (55%) contain no acceptance-criteria/acceptance-test language at all** (`grep -liE 'acceptance (criteria|test)'` over `docs/specs/*.md`). The no-AC list **skews recent** — most July 2026 specs (work-facade contract, grind runtime, prgroom preflight, merge-approver, etc.) are on it. This is the current process's steady-state output, not legacy debt.
5. **[V] The brainstorming skill's deep-review path waives its own criterion**: review criteria = "the design's stated goals plus its acceptance criteria (**goals-only when the spec carries none**)" (`src/user/.agents/skills/brainstorming/SKILL.md` ~line 183). The skill's 10-step checklist mandates process ceremony (visual-companion offer, review-depth routing, attention routing) but never mandates falsifiable acceptance criteria as a deliverable.
6. **[V] writing-plans requires implementation-as-markdown**: 2–5 minute steps, "Complete code in every step," "No Placeholders" (actual test code and implementation code embedded in the plan doc), one fresh subagent per task (`src/user/.agents/skills/writing-plans/SKILL.md` ~lines 43–127).
7. **[V] `wait-for-pr-comments` SKILL.md is 1,283 lines** — a prose state machine executed by an LLM interpreter.
8. **[V] Live workflow contradiction**: repo AGENTS.md says prgroom is "installed onto PATH by the installer" and the `monitor-pr` skill (which drives prgroom) is in the active catalog; `completion-gate.md` says "prgroom … is not deployed — wait-for-pr-comments is the active path." All three artifacts load into the same session.
9. **[V] The PDLC readiness gates are stubs**: `packages/pdlc/src/pdlc/orchestrator.py` `_gate_ready()` — "AGENT_WORTHY / DECOMPOSE / EXECUTABLE_READY / MERGING gates are stubbed to pass for the tracer" → `return True`.
10. **[V] WIP cap breached**: `project-config.toml` sets `milestone-wip-cap = 2` (PORT exempt); repo AGENTS.md shows M0, M1, and M3 simultaneously `in_progress`.
11. **[V] The convergence criterion already exists in the target design, unadopted**: `CONTEXT.md` (~lines 300–352) defines Mechanical Findings (blocking, must carry a mechanical artefact) vs Advisory Findings (non-blocking, routed out of the fix loop); "Review exits when a complete round produces zero Mechanical Findings." No live workflow implements this.
12. **[R] Merge-gate injectability**: Scott's own experiment found that prose declaring defects "intentional" caused Codex to stop reporting defects it had previously found (recorded in `docs/specs/2026-07-18-codex-rereview-path-design.md` ~line 98). Bot quiescence is therefore a weaker merge signal than the pipeline treats it as.
13. **[R] Instruction-surface size**: ~43,000 lines of primary config surface incl. ~9,090 lines of skills; deployed Codex AGENTS.md 352 lines vs the repo's own <200-line optimizer target; 27 duplicate skill copies exposed (GPT-5.6 audit).
14. **[R] Churn shape**: typical feature PRs converge in 1–2 review rounds; the worst per-size churn was small **prose/shell changes to the process machinery itself** (`wait-for-pr-comments`, `merge-guard`) (Fable-medium audit, prior session's churn analysis).
15. **[R] quality-gate HEAVY tier**: up to 3 rounds of finder→refuter→fixer; its own file calls the round cap "NOT a clean bill of health"; prgroom's `verify` (fix-quality) subsystem is 0% implemented and `sweep` is a stub (GLM-5.2 and GPT-5.6 audits, corroborated by `packages/prgroom/AGENTS.md`).

## 5. Findings

### F1 — A stale config tree loads into every session with mislabeled seniority
Not merely a doubled instruction floor (~2× the fixed ~7k-word load in every session, every project under `~/src`): the stale `/Users/scott/.claude/` tree presents as *project* config, so where it conflicts with the fresh `home2` tree, the stale copy plausibly wins. It is also the sole source of Codex routing — as a self-contradicting pair (evidence 1–3). The installer deploys but never prunes; the duplication is deploy hygiene, not source. **Rationale for severity:** contradictory instructions don't just cost tokens — when a model observes its rulebook disagreeing with itself, compliance with *all* rules degrades (rule dilution).

### F2 — Reviews have no termination contract; the missing acceptance criteria and the PR ping-pong are the same defect at two distances (the central finding)
An LLM reviewer is a findings generator: given any surface, it emits findings proportional to that surface, indefinitely. Convergence requires a contract to check against; taste is inexhaustible. 55% of specs carry no acceptance language (evidence 4), the brainstorming gate explicitly proceeds "goals-only" (evidence 5), and the gate that would bounce unfalsifiable specs is stubbed to `return True` (evidence 9) while its milestone (M2) sits open. So review rounds "finding a few new things each time" is not hidden-defect discovery — it is the expected output of running an unbounded generator against contract-free material. Acceptance criteria are not merely defect *prevention*; they are the *termination condition* review currently lacks. The target design already contains the fix (Mechanical/Advisory split with a mechanical exit criterion, evidence 11) — designed, documented, unadopted.

### F3 — The plan format manufactures the doc/code-inconsistency findings the reviewers keep raising (a closed loop)
writing-plans embeds complete implementation and test code in markdown (evidence 6) — the implementation written twice, in the one medium with no feedback loops (no compiler, tests, or lint). It drifts from the real code the moment implementation starts teaching, guaranteeing exactly the "inconsistencies across documentation and code" class of finding in symptom 3. The system generates its own review fodder, then spends frontier tokens adjudicating it. Fair counterpoint: full-code plans were meant to let cheap models execute without judgment — but pre-writing the code with a frontier model and having a cheap model retype it is a transcription service, not an execution pipeline. (The repo's own constraint states the principle being violated: "the signature is the decision, the implementation the consequence." Plans embedding bodies promote consequences into decisions and freeze them prematurely.)

### F4 — Two generations of the PR workflow are simultaneously live and mutually contradictory
prgroom (typed, 1,026 tests, 99.5% coverage) vs the 1,283-line prose `wait-for-pr-comments` (evidence 7–8). Every session loads instructions asserting both realities. All three audits independently concluded prgroom is the right architecture and the failure is migration-without-deletion.

### F5 — The harness degrades decision and review quality through three mechanisms
(a) **Attention tax + rule dilution** — the doubled, self-contradicting floor (F1) dilutes attention and discounts the whole rulebook. (b) **Judgment displacement** — per-turn reasoning is consumed by compliance parsing (which skill fires, which rule wins, the "1% chance → MUST invoke" rule against a 70+-skill catalog) instead of the problem; this session attests to it first-hand as the test subject. (c) **Reviewer contamination — the direct answer to "why don't my up-front reviewers catch these?"** In-house gate reviewers load the full house context and review the *change against the plan* (both in-house artifacts, sharing the author's blind spots); Codex/Copilot are the pipeline's only fresh-context reviewers and review the *artifact against the world*. Doc/code inconsistencies are invisible to plan-conformance review when the plan is the inconsistent doc. A `dispatching-bare-subagents` skill exists for exactly this decontamination and is not in the gate path. **Corollary (economics inversion):** the heavier the harness, the more model capability is consumed surviving it — the harness built to enable cheap models (M1/M3) structurally selects for expensive ones.

### F6 — Divergent tools doing convergent jobs
The HEAVY gate's adversarial refuter panels cannot converge by construction (each refuter is incentivized to find a new objection); tests converge by definition. Tuning refuter counts is knob-turning on a non-convergent loop. GLM-5.2's classifier is the cleanest enforcement of the repo's own prime directive: **a finding that cannot be expressed as a failing test drops to advisory** — the cost of writing the test *is* the severity filter. (Sharper than Fable-medium's "severity floor," which still requires judgment to adjudicate severity.)

### F7 — Sequencing inversion
Downstream autonomy (M3 worker fleet) advances while the upstream readiness gate (M2) — the mechanism that would make downstream work convergent — is open and stubbed. Three milestones run against a WIP cap of two (evidence 10). Expensive downstream review is compensating for missing upstream contracts.

### F8 — The merge gate over-trusts LLM quiescence, and quiescence is injectable
Evidence 12. "The bots went quiet" can be manufactured by prose. Merge-eligibility currently weights this signal above its reliability.

### F9 — Unifying synthesis: accretion without deletion
The findings are not siblings; they are offspring of one disease. Duplicate deploy (installer adds, never prunes). Contradictory rules (new rule added, old never removed). Two workflow generations (successor built, predecessor never deleted). Contract-free specs feeding non-terminating reviews (findings added, never resolved-by-contract). Five optimize-the-optimizer meta-skills. Every failure historically produced a permanent global rule; nothing carries a TTL, a scope bound, a budget, or a cutover-with-teardown obligation. **The system has an add operator and no delete operator.** All three audits found instances; naming the missing *decay mechanism* as the disease is this session's synthesis. Implication (not a plan): the remedy category is decay/termination mechanisms, not additional mechanisms.

## 6. Direct answers to Scott's suspicions

- **"Is my harness impeding quality?"** Yes — via F5's three mechanisms. But not uniformly: the discipline core demonstrably works where contracts exist (typed packages, 1–2-round feature-PR convergence, evidence 14). The problem is the growth model (F9), not the existence of discipline.
- **"Is brainstorming self-defeating?"** Not self-defeating — **mis-targeted**: it polices process and placeholders, not falsifiability, and nothing downstream rejects an unfalsifiable spec (F2). The skill's own deep-review escape hatch ("goals-only") is the smoking gun.
- **"Should plans be prescriptive down to code/bash?"** No (F3). Plans should carry decisions — contracts, signatures, invariants, error taxonomy, AC-to-test map, tracer order — not bodies. If cheap executors need prescriptiveness, it belongs in media with feedback loops (compilable stubs, failing tests), not markdown.
- **"Can models review very long specs well?"** No — review quality degrades non-linearly with prose length (reviewers sample; prose lacks anchors), and length is itself often AC-compensation: volume substituting for falsifiable criteria. Long prose also maximizes the findings-generator surface (F2).

## 7. Where the audits diverged (and this session's adjudication)

- **Severity floor (Fable-medium) vs red-test-convertibility (GLM-5.2)** as the review-finding filter: red-test wins — severity adjudication is still judgment; test-convertibility is mechanical.
- **Removing the "1% chance → MUST invoke skill" rule (GPT-5.6):** right, but incomplete — the rule exists because models historically under-trigger skills. Removal must pair with catalog shrinkage and better trigger descriptions, or under-invocation returns. A catalog small enough to need no paranoia rule is the actual fix.
- **prgroom:** unanimous across all four assessments — right architecture, real implementation, must be a *replacement* (finish `verify`, cut over, delete legacy) rather than a second concurrent system.

## 8. Caveats

- **Shared-context convergence bias:** all three audits (and this session) ran under Scott's loaded harness, whose own mission statement ("code over prose, mechanical evidence") primes exactly this diagnosis. Four-model agreement is partly agreement about the repo's own narrative. Mitigation: this session independently verified the load-bearing claims as checkable facts (section 4 [V] items) — the facts hold regardless of framing. GLM-5.2 flagged its own contamination explicitly; the fresh-session dialog this document enables is the correct next control.
- **Not verified by this session:** the 43k-line surface count, 27 duplicate skills (evidence 13), churn statistics (evidence 14), and quality-gate/prgroom internals (evidence 15) — carried from the audits with citations.
- The churn claim that feature PRs converge in 1–2 rounds comes from a prior session's analysis and was not re-derived here.

## 9. Open decision surface for the way-forward dialog

Questions the next session should resolve with Scott — deliberately unranked and unanswered here:

1. **Config homes:** which of `/Users/scott/.claude` vs `home2` is canonical; what does prune-on-install / deploy-receipt hygiene look like; how to prevent ancestor-directory pickup of a user tree as project config.
2. **Falsifiability contract:** what is the minimal mandatory acceptance-criteria artifact for a spec, and where is it enforced — in brainstorming's output contract, in a real (non-stub) readiness gate, or both?
3. **Plan granularity:** what do plans carry (contracts vs bodies), and what do cheap-model executors actually need to succeed?
4. **Review termination:** how and where to adopt the already-designed Mechanical/Advisory split; does the red-test-convertibility classifier govern refuter findings?
5. **prgroom cutover:** scope of the remaining `verify` work; the deletion criteria for `wait-for-pr-comments`, `reply-and-resolve-pr-threads`, and the contradictory `monitor-pr`/completion-gate text.
6. **Decay mechanisms:** rule TTLs/scoping, an instruction-surface budget (add-one-delete-one?), meta-work gate tiering.
7. **Measurement:** how to instrument interventions-per-merged-PR, review rounds, and fix-commits — the prime-directive metric currently measured nowhere.
8. **Sequencing:** does M3 pause until a minimal M2 readiness gate exists; how to honor the WIP cap.

## 10. Pointers

- `SAVEPOINTS/LEFT-OFF-NOTES.md` — symptoms, suspicions, full raw audit verdicts + resume handles (Fable-medium: `--resume 1ab826dc-d57f-4b26-880c-7ba71969a384`; GPT-5.6: `codex resume 019f7c34-b885-7141-9729-02f31045048b`; GLM-5.2: `ccaor --model=z-ai/glm-5.2 --resume c9b729d7-2120-4f54-99be-d552f88160af`)
- Key files: `src/user/.agents/skills/brainstorming/SKILL.md`, `src/user/.agents/skills/writing-plans/SKILL.md`, `src/user/.agents/skills/wait-for-pr-comments/SKILL.md`, `src/user/.agents/rules/completion-gate.md`, `packages/pdlc/src/pdlc/orchestrator.py`, `CONTEXT.md` (Mechanical/Advisory, ~lines 289–352), `project-config.toml` (`[operating-model]`), `docs/specs/2026-07-18-codex-rereview-path-design.md`
- This analysis session (for resume/interrogation): `5a052aa7-7b5c-4246-b62d-f1d03e2c7085`
