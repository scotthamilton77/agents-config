# Adversarial QA Agent Team — Shared Convergence Discipline Design

**Date:** 2026-07-05
**Status:** Draft (pending review)
**Bead:** agents-config-vaac.2 (epic, M3 — "Adversarial QA agent team")
**Related specs:** `2026-07-03-adversarial-loop-convergence-decision.md` (the authoritative decision record, D1–D15 — this spec realizes it as a design and does not relitigate it); `2026-07-02-completion-gate-routing-design.md` §7 (the interim `quality-gate` behavior the UC2 binding here replaces).
**Decision:** Package the convergence discipline as one shared skill (`adversarial-qa`: rule/primer prose + deterministic Python helpers + three data contracts + per-artifact-class rubrics) with per-loop bindings. All five Phase-2 roles (closure verifier, delta discoverer, evidence verifiers, triage bench, fix wave) are always present as logical steps; only per-role **width** scales via a continuous `scale_hint` (no lean mode, no role collapse, no role skip). Convergence is decided by a deterministic predicate over bench-assigned severities — never by a model. Metrics persist as one self-contained JSON file per review under `.adversarial-qa/reviews/` (sharded, collision-proof names; no shared mutable file). Two bindings are specified in full: `quality-gate.js` (UC2, Workflow path — refuter panels retired for evidence verifiers + rank-anchoring bench, rounds delta-scoped, a Phase-3 certification pass added) and `ralf-review` (UC1, portable serial path at the lean end — closure check added, independence re-scoped to discovery-only, judgment-stop replaced by the predicate). Everything else decomposes into child beads.

## 1. Problem and scope

The evidence is in the decision record and is not repeated here: adversarial finders emit best-N-per-read forever (8 rounds, 2-2-2-2-2-1-2-1 highs, stop condition unreachable), refuter panels refute nothing (0/24 at 3× cost), severity inflates when finders self-assign it, and the one usable signal — fix-class decay — was visible to a human and invisible to the loop.

This spec is the **design half only** of vaac.2. It covers the shared discipline package and two concrete bindings — `quality-gate.js` (the only live UC2 heavy loop) and `ralf-review` (the live UC1 serial loop). Implementation lands post-frontier-window on the M3 cheap-model fleet. UC3 adoptions, the pattern miner, rubric authoring, artifact templates, the brainstorming decision-records requirement, and `ralf-implement` adoption are scoped child beads (§12), not sections of this spec.

## 2. Packaging and file layout

New shared skill directory (portable tree — works on every supported tool):

```
src/user/.agents/skills/adversarial-qa/
├── SKILL.md          # the rule + primer (merge-guard mold): dual-signal semantics,
│                     # lifecycle, round anatomy, CoI matrix, binding instructions
├── assessor.py       # Phase-0 helpers: plan derivation from mechanical facts (UC2),
│                     # readiness-bounce scaffolding (UC1)
├── ledger.py         # findings-ledger operations: add/update/close, fingerprinting,
│                     # status transitions, snapshot emission
├── preclassify.py    # per-round mechanical pre-classifier: diff-surface facts
│                     # (sections/files touched, size, structural markers) — no LLM
├── predicate.py      # the convergence predicate (normative contract, §6) — pure
│                     # data-in/data-out, no model calls
├── metrics.py        # per-round/per-review metrics recording; writes the per-review
│                     # file (§8)
├── fixtures/         # golden predicate vectors (JSON in/out) shared by every
│                     # implementation of the predicate contract
└── rubric/           # per-artifact-class consequence-anchored severity rubrics
    ├── code.md       # UC2 (seeded from quality-gate.js's current severity guidance)
    └── document.md   # UC1 (specs/designs/plans)
```

Naming: the skill is `adversarial-qa` — it names the *discipline*, which has two implementations of one contract (portable serial path and Claude Workflow path, per D14/D15). "Adversarial QA agent team" stays the bead/marquee title; baking "agent team" into the skill name would misdescribe the serial binding. (Considered and rejected: `adversarial-qa-agent-team`, `adversarial-qa-team`.)

Determinism lives in the Python helpers; judgment lives in prose contracts (role personas, rubrics) inside `SKILL.md` and `rubric/`. Loops bind; they do not rebuild.

## 3. Data contracts

The three contracts are what make every other part composable (D15). All are JSON; all string/array fields are bounded (the "work lands, report dies" lesson — an oversized report must prioritize, not blow a StructuredOutput retry budget).

### 3.1 Review plan (Assessor output)

| Field | Content |
|---|---|
| `use_case` | `UC1` \| `UC2` |
| `artifact_class` | e.g. `code-change`, `design-spec`, `plan` — selects rubric + fail-closed defaults |
| `lens_roster` | Phase-1a lenses, Phase-1b lenses, invited completeness specialists (each specialist self-gates: "is my expertise needed and missing?") |
| `scale` | `verifier_width` (evidence-verifier parallelism), `bench_votes` (1; 3 only at the largest scale, median-rank merge), `synthesis_effort` |
| `round_cap` | 3–5, scale-derived (§7) |
| `severity_floor` | default `major` — at/above blocks acceptance |
| `rubric_ref` | which `rubric/` file the bench anchors against |
| `acceptance_bindings` | UC2: the mechanical checks that must pass for closure (tests, lint, build) |
| `routing_table` | fix-class → lens-set map used to staff each round's delta discovery |
| `at_cap_policy` | `proceed-with-documented-residuals` \| `park-for-human` — declared up front per artifact class (D10) |
| `budget_reserve` | fraction of budget reserved for certification + reporting |

### 3.2 Findings ledger (per-finding entries)

| Field | Written by | Content |
|---|---|---|
| `fingerprint` | ledger.py | normalized `location:gist` key for mechanical dedup |
| `location` | finder | file/section (+line) actually opened |
| `lens` | finder | the lens that produced it |
| `gist`, `detail`, `suggested_fix` | finder | bounded prose; advisory |
| `severity_claimed` | finder | **advisory only** — no finder field is authoritative severity |
| `severity` | triage bench | authoritative, rank-anchored (§5); the only severity the predicate reads |
| `evidence` | evidence verifier | citation (quoted lines) or repro — never a vote |
| `disposition` | triage bench | `apply-mechanical` \| `flag-human` \| `adjudicate-alternative` \| `out-of-scope` \| `duplicate-of:<fingerprint>` |
| `status` | ledger.py | `open` → `verified` → `disposed` → `closed` \| `residual`; closure verdicts `fixed` / `not-fixed` / `partial` / `fix-created-new-concern` re-open or fork entries |
| `fix_class` | closure verifier | class of the **landed fix** (e.g. design-change, coverage-change, boundary-hardening, mechanical-edit) — routes the next round's lenses |
| `decision_record_ref` | triage bench / fix wave | link when an alternatives-shaped finding was adjudicated |
| `rounds` | ledger.py | `found`, `closed` |

`disposition` and `fix_class` are deliberately distinct: the current `quality-gate.js` conflates them in one `fixClass` field. Disposition is the bench's ruling *about a finding*; fix-class is the closure verifier's classification *of a fix*. The fixer writes neither — it never self-classifies (D6/D8).

### 3.3 Verdict object (every exit, both signals, all phases)

`signal` (`acceptance` | `termination`), `reason` (`clean-at-floor` | `round-cap` | `stall` | `budget` | `certification-second-failure`), `phases_run`, `rounds`, `phase3_bounces`, `ledger_snapshot`, `residuals` (open entries with bench severities), `rejected_alternatives` (adjudicated-away findings with decision-record refs), `metrics` (per-round records, §8), `plan` (the review plan it ran under), `run_id`, `persist_to` (the metrics file path, §8). This formalizes what `quality-gate.js`'s `residualRisk` report already approximates. A termination verdict is a receipt for work stopped, never a quality claim.

## 4. Phase 0 — Assessor

**UC2:** the Assessor consumes `gate-triage`'s existing facts JSON directly (files, LOC, subsystems, critical-path hits, `scale_hint`) — one measurement, two consumers, no duplicate sizing logic. Phase 0 for UC2 *is* the routing-tier machinery plus plan derivation in `assessor.py`.

**UC1:** no mechanical size anchor exists for prose (D3). The Assessor's readiness bounce is judgment-shaped: target readable, review criteria present, artifact-class expectations met (e.g. a spec class expects decision records once the child bead for artifact templates lands). Bounce output is structured "not reviewable yet — here's what's missing", not a review of an unreviewable artifact. Fail-closed defaults per artifact class guard against self-serving under-review.

**Cross-bead note (unresolved by design):** the UC1 readiness bounce overlaps with `agents-config-owqa` (M2 brainstorm-readiness gate). Whether the Assessor calls owqa's check as a sub-step or the two reconcile another way is decided when M2 lands; this spec only requires that the Assessor's bounce interface (structured missing-items list) be compatible with that future reconciliation.

## 5. Phase 2 — Round anatomy and structural conflict-of-interest enforcement

Five roles per round, in order, always present as logical steps. Width scales continuously via the plan's `scale` block; roles are never collapsed or skipped (rejected alternatives: *role collapse* — merging closure verifier + delta discoverer for small changes — introduces a second scaling axis beyond the proven one; *role skip* — bench judging unverified findings directly — trades away the CoI matrix exactly where corners feel cheapest).

1. **Closure verifier** — *memoryful by design* (verification wants contamination; it audits specific claims, D12). Receives the ledger and the fixed artifact. UC2: reruns the plan's mechanical `acceptance_bindings` first (regression tests close findings cheaply), then verifies the residue. Verdicts each open entry `fixed` / `not-fixed` / `partial` / `fix-created-new-concern`, and assigns each landed fix its `fix_class`.
2. **Delta discoverer** — *memoryless by design*: fresh eyes on the fix diff + blast radius only (prose blast radius: referencing sections, moved term definitions). Never sees the ledger. Its lens set is not fixed: the orchestrator applies the plan's `routing_table` to the closure verifier's fix-classes — a round of mechanical edits does not re-summon the soundness lens.
3. **Evidence verifiers** — per-finding, evidence-shaped: quote the contradicting lines, show the repro. Never a vote. `verifier_width` sets parallelism (one batch verifier at lean width; N-parallel at large).
4. **Triage bench** — one provenance-blind batch judge per round applying the plan's written consequence-anchored rubric. **Ranks before scoring:** first a relative ordering of the round's fresh verified findings, then rank positions map onto the rubric's absolute severity buckets via worked anchor examples. The ordering-then-anchoring sequence is the debiasing mechanism — the campaign's inflation came from scoring findings independently. The bench also rules scope, confirms dedup beyond the mechanical fingerprint pre-pass (semantic duplicates), checks findings against existing decision records (adjudicated-away findings die here), and recommends dispositions. At `bench_votes: 3`, votes merge by median rank position before anchoring.
5. **Fix wave** — applies dispositions. `apply-mechanical` entries are fixed sequentially (concurrent writes clobber); `adjudicate-alternative` entries route to decision-matrix adjudication and a decision record — never silent "fixing"; `flag-human` entries park as residuals.

**Routing facts are mechanical.** A deterministic pre-classifier supplies diff-surface facts (sections/files touched, size, structural markers — no LLM): `preclassify.py` on serial paths, structured-output relay on the Workflow path (§9.3). The closure verifier supplies fix-classes; the plan holds the rules; the orchestrator applies rule(fact). It routes and counts. It never judges.

**The CoI matrix is enforced by structure, not instruction:**

- The finder's output schema **has no authoritative-severity field** — only `severity_claimed`. Inflation cannot enter through a field that does not exist.
- The closure verifier is a different agent invocation from the fix wave it audits.
- The fixer never self-classifies: `fix_class` is assigned by the next round's closure verifier; `disposition` is assigned by the bench. The fixer's applied/deferred note is data, not judgment.
- The orchestrator is deterministic code; no model call sits in a judging position.

## 6. Convergence predicate and phase transitions

The predicate is a **normative data-in/data-out contract**, implemented by `predicate.py` and evaluated over bench-assigned severities only (`severity_claimed` is invisible to it). No agent is ever asked "are we done?" — that is the question the campaign proved agents answer wrong.

**Inputs:** ledger snapshot (statuses + bench severities), the round record (`novel_verified_at_floor`, `closed_this_round`, `fresh_this_round`), plan (`severity_floor`, `round_cap`), budget state, `phase3_bounces`.
**Output:** `continue` | `advance-to-certification` | `terminate(reason)`.

**Acceptance-side advance** (Phase 2 → Phase 3) requires both, in the same round:

1. Ledger clean at the severity floor — no open blocking/critical/major; a major survives only via explicit decision-matrix adjudication into `residuals`.
2. Delta discovery produced zero novel verified findings at/above floor (novel = post-evidence-verification, post-bench dedup and scope rulings — a deduped or scoped-out raw finding does not block acceptance).

One dry round suffices: delta-scoping makes dryness geometric evidence (the shrinking surface forces decay), not the statistical kind the campaign waited eight rounds for and never got (D7).

**Phase 3 — final certification** flips discovery to certification: a full-fresh pass over the whole artifact — whole-artifact consistency, aggregate scope drift, ledger completeness, residual synthesis. Phase 3 may bounce the artifact back into the loop **once**; a second Phase-3 failure converts to `terminate(certification-second-failure)`. The `phase3_bounces` counter in the verdict object makes the once-only rule mechanically enforceable.

**Golden fixtures:** `fixtures/` ships JSON in/out vectors covering every exit path (clean advance, floor-blocked, novel-blocked, cap, stall, budget, bounce accounting). Every implementation of the contract must satisfy them (§9 for the JS twin).

## 7. Termination protocol

Termination triggers (any one):

- **Round cap** — plan-declared; derived from scale: 3 (lean) / 4 (medium) / 5 (large). An economic backstop, not a quality claim.
- **Stall** — a round that closes nothing and discovers nothing novel while the ledger is non-empty: fixes aren't landing. (`quality-gate.js` already implements exactly this test.)
- **Budget exhaustion** — with `budget_reserve` held back for certification + reporting.

At-cap routing follows the plan's declared `at_cap_policy`: low-stakes artifact classes may `proceed-with-documented-residuals`; everything else parks for a human. Overnight runs park to the morning queue with the verdict object attached. Never block silently; never self-approve. Escalation shape follows the canonical decision matrix.

## 8. Metrics contract and storage

Recorded by `metrics.py` — deterministic, no model calls.

**Per round:** round number; delta surface size; findings raw → verified → novel → dup; per-lens counts; **finder-claimed vs bench-assigned severity pairs** (the inflation measure — the reason `severity_claimed` exists in the ledger at all); fix-class distribution; closure rate; tokens; wall time.
**Per review:** plan, phases run, verdict, residuals, Phase-3 bounces.

**Storage — sharded by review, no shared mutable file.** Each review run writes one self-contained JSON file:

```
.adversarial-qa/reviews/<UTC-timestamp>-<run-id>.json
```

- `run_id` derives from the session/workflow run id, so same-second runs on different machines cannot collide.
- The file carries the whole review record: plan, per-round metrics, verdict object, final ledger snapshot.
- Concurrent worktrees, parallel fleet PRs, and multi-machine work merge without conflict: two branches add two *different* files. This is the property that makes git's own object store safe under concurrency.
- A resumed or Phase-3-bounced run reuses its `run_id` and rewrites its own file — still single-writer.
- The pattern miner (child bead) globs the directory; compaction, if ever needed, is the miner's job.
- Committed, not gitignored: the miner needs cross-review, cross-session, cross-machine data. Configurable via `project-config.toml` if a repo objects.

Rejected: single append-only `metrics.jsonl` (merge-conflict magnet — two PRs appending to the same tail conflict nearly every time, and parallel worktrees are this design's home workload); `.gitattributes merge=union` on a shared file (misorders lines; one hand-edit breaks the append-only invariant it silently depends on); storing metrics in beads/Dolt (couples a portable discipline to one repo's tracker).

## 9. Binding: `quality-gate.js` — UC2, Workflow path

### 9.1 Role mapping

| Current | Becomes |
|---|---|
| gate-triage + routing tiers | Phase 0 (already exists per D4); `assessor.py` derives the plan from triage facts |
| Round-1 full-surface finder fan-out | Phase 1: 1a (plan-fidelity, placement, approach reassessment) + 1b (soundness + invited specialists) — current lens briefs survive, regrouped |
| Full-surface finder re-runs every round | **Delta discoverer**: rounds 2+ read fix-diff + blast radius only, lens set from `routing_table` × fix-classes |
| Fixer's `applied:true` as closure evidence | **Closure verifier** (new): memoryful; reruns mechanical checks, verifies residue, assigns `fix_class` |
| Majority-vote refuter panels | **Evidence verifiers**: per-finding citation-or-repro; `REFUTER_STANCES` and `verifyFindings` majority logic deleted (0/24 at 3× cost) |
| First-non-refuted-voter severity adjustment | **Triage bench** (new): rank-then-anchor onto `rubric/code.md`; bench severity replaces finder severity everywhere downstream; fingerprint dedup stays as mechanical pre-pass |
| Fix wave with finder-assigned `fixClass` | Fix wave driven by bench `disposition`; sequential apply and the mechanical/semantic bright line survive as `apply-mechanical` vs `flag-human` |
| (absent) | **Phase 3 certification**: full-fresh pass after the predicate advances; bounce-once rule |

### 9.2 `scale_hint` schema change

`refuters` retires. The hint becomes `{finder_dimensions, verifier_width, bench_votes, synthesis_effort, round_cap}` with buckets small `(3,1,1,high,3)` / medium `(4,2,1,high,4)` / large `(6,4,3,xhigh,5)`. `gate_triage.py` and `quality-gate.js` are the only two ends of this wire and change together in one PR — no compat shims.

### 9.3 Harness constraints (Workflow scripts have no filesystem or subprocess access)

- **Predicate:** the JS path cannot call `predicate.py`. `quality-gate.js` keeps an inline JS evaluation (~a dozen lines) conforming to the normative contract of §6. Both implementations carry **boxed sync comments naming each other and the fixtures file** as sync-coupled; the fixtures are tested on the Python side and reviewed against the JS side until a workflow test harness exists. (Considered and rejected: relaying predicate execution through a haiku agent call — a nondeterministic transport wrapped around a deterministic computation, sitting in the loop's exit-decision path; a mis-relayed exit signal is silently wrong. Drift is reviewable in code; a courier's transcription error is not.)
- **Mechanical pre-classifier facts:** the orchestrator cannot run git. Per-round diff facts ride back through bounded structured outputs: `FIX_RESULT` gains a bounded `touched_files` array; the closure verifier returns fix-classes. The JS applies rule(fact) to data returned by agents — determinism preserved, no filesystem needed.
- **Metrics persistence:** the workflow's final act is a haiku/low **writer agent** that persists the verdict object to `.adversarial-qa/reviews/<ts>-<run-id>.json` and returns `{written, path}`. The verdict object is still returned to the caller as the authoritative copy; verify-checklist step 5 checks the file exists as one more line of mechanical evidence. A file write is the opposite risk class from the predicate: low-stakes, verifiable, benign on failure — and code-enforced beats the prose-enforced caller-writes alternative. (Considered and rejected: rewriting the workflow as a Python script wrapped in a skill — relitigates the closed gate-as-workflow decision (agents-config-abn9.38), and trades away resume-from-run-id, shared budget tracking, and fan-out whose output never touches main context; the Python-driven UC2 composition already has a home as the D15 portable serial sibling, built when a real caller appears.)

### 9.4 Carried forward unchanged

Untrusted-content fencing (`fence`, the UNTRUSTED block), bounded StructuredOutput schemas, `withRepair`, resume-from-run-id, budget-tail reserve, injection-suspect reporting, sequential mechanical fixes, and the dual-signal exit semantics already shipped. The `interim: true` flag and deferred-discipline comments come out; the workflow name stays `quality-gate`.

### 9.5 Acceptance criteria (UC2 binding)

1. Rounds 2+ prompt discoverers with fix-diff + blast radius only; no full-surface re-read after Phase 1.
2. No majority-vote refutation code remains; every surviving finding carries `evidence`.
3. The ledger's authoritative `severity` is bench-assigned; `severity_claimed` never reaches the predicate; both are recorded per finding (the inflation measure).
4. Closure requires the closure verifier's verdict, not the fixer's `applied:true`; mechanical `acceptance_bindings` run before agent verification.
5. Inline JS predicate passes the shared golden fixtures (validated Python-side; JS reviewed against the same vectors); boxed sync comments present in both files.
6. Phase 3 runs on acceptance advance; a second Phase-3 failure terminates with `certification-second-failure`; `phase3_bounces` recorded.
7. The verdict object is returned to the caller AND persisted by the in-workflow writer; verify-checklist gains the file-existence evidence line.
8. `gate_triage.py` emits the new `scale_hint` fields; both ends land in one PR.
9. All §9.4 hardening survives (grep-level check: fence, bounded schemas, withRepair, resume, budget reserve).

## 10. Binding: `ralf-review` — UC1, portable serial path (lean end)

Station unchanged: inner-methodology only; caller owns fixes and delivery; same required inputs; fail-fast posture retained.

### 10.1 Changes

- **Phase 0** grows out of the existing fail-fast validation: a lean readiness bounce (target readable, criteria present, artifact-class expectations met) returning a structured missing-items list instead of a doomed review.
- **Cycle 1 = Phase 1** full read: consistency, soundness, scope — and alternatives run here **once**, route to decision-matrix adjudication with a decision record, and are dead thereafter absent new evidence (D5: the never-draining lens stays out of the loop).
- **Cycles 2+ = lean Phase-2 rounds, all five roles at width 1:**
  - A memoryful **closure check** against the prior ledger opens the cycle — currently absent entirely (today's fresh reviewer may or may not re-find an unfixed issue, which is no closure signal at all).
  - The fresh-eyes reviewer becomes the **delta discoverer**, scoped to changes-since-last-cycle plus prose blast radius. Independence re-scopes to discovery-only (D12 — an already-decided amendment): the closure check is deliberately contaminated; the discoverer stays fresh.
  - One **batch evidence-verifier** checks citations for all findings.
  - A **single-pass bench** ranks-then-anchors onto `rubric/document.md`; reviewer severity demotes to `severity_claimed`.
  - The **fix wave is the caller's turn**, recorded as dispositions in the ledger.
- **The predicate replaces the judgment-stop.** "Findings are non-significant ⇒ converge" is exactly the soft call D9 exists to kill; `predicate.py` evaluates the ledger instead. Acceptance triggers a lean Phase 3 (full-fresh certification read — cheap on a single document; bounce-once applies).
- **Score labels survive as a compat view**, mapped from the verdict object: acceptance → `PASS`; termination with no blocking/critical open and majors trending down → `PASS_WITH_RESERVATIONS`; other terminations → `FAIL`. The verdict object rides alongside as the authoritative record.
- **Cycle cap default 2 → 3** (the old cap priced full-surface re-reads; delta rounds are cheaper; 3 is the record's lean floor). Caller override `1..20` retained.
- **Role-tiered model/effort** replaces the flat `opus[1m]/xhigh` single reviewer: discoverer and evidence-verifier run cheaper; the bench keeps the high-judgment tier.
- **Metrics:** `metrics.py` writes the per-review file directly — the serial path has a filesystem.

Implementation note (plumbing, not architecture): helpers resolve relative to the installed `adversarial-qa` skill root per tool; do not hardcode `~/.claude/`.

### 10.2 Acceptance criteria (UC1 binding)

1. An unreviewable target bounces at Phase 0 with a structured missing-items list; no review spend.
2. Cycle 2+ transcripts show the closure check running before delta discovery, with the prior ledger visible to the closure check and invisible to the discoverer.
3. Alternatives-shaped findings appear at most once, with a decision-record ref; they do not recur in later cycles.
4. Report severities are bench-assigned; `severity_claimed` recorded alongside.
5. Convergence decisions trace to `predicate.py` output, not prose judgment; fixtures pass.
6. Legacy score labels present and mapped per §10.1; verdict object emitted.
7. Per-review metrics file written under `.adversarial-qa/reviews/`.

## 11. Composability

Per D15, extraction happens when a real caller appears — no reusability theater. The contracts (§3) and helpers (§2) are first-class from day one. Likely early extractions, in order of expected demand: the Assessor as a standalone readiness check (sibling of the M2 gate — see §4 cross-bead note), the certification pass alone (legacy/externally-reviewed docs), single-round invocation (ad-hoc "run one bench round on this"). None are built in this effort.

## 12. Follow-up decomposition (child beads of vaac.2)

Implementation beads for the work specified here:

1. **Core discipline package** — §2 skill dir, §3 contracts, `predicate.py` + fixtures, `ledger.py`, `metrics.py`, `assessor.py`, seed rubrics. Everything else depends on this.
2. **`quality-gate.js` UC2 binding** — §9, including the `gate_triage.py` scale_hint change (one PR).
3. **`ralf-review` UC1 binding** — §10.

Candidates carried from the decision record (filed as scoped beads, specs deferred):

4. **Brainstorming skill: decision-records requirement** (consider `bd decision` machinery).
5. **Pattern miner + project review profile** — after metrics accumulate; schema ships in bead 1.
6. **Artifact templates with review-anchor sections** — makes UC1 Phase-0 readiness partly mechanical.
7. **`ralf-implement` predicate adoption** — the UC2-serial sibling of §10.
8. **UC3 adoptions** — stall detection + dual-signal terminal reporting in prgroom envelope mapping (adopt, don't rebuild, D13).
9. **Per-artifact-class rubric authoring** — beyond the two seed rubrics; consequence-anchored severity definitions per class.

## Out of scope

- The pattern miner implementation (needs data that does not exist yet).
- UC3 rebuild — UC3 keeps its field-proven skeleton and adopts pieces only (D13).
- A portable serial UC2 composition (Python-driven full lifecycle) — named as the D15 sibling of the Workflow path; built when a real caller appears.
- Panel mechanisms of any kind — they may earn their way back only via measured bench mis-calibration in the metrics (D8), not nervousness.
- Autonomous proceed decisions at termination exits — D2's phased report→rule ratchet; near-term a human reads the verdict at the gate.

## Residual risks

- **JS/Python predicate drift** — two implementations of one contract. Mitigated by golden fixtures (Python-tested), boxed sync comments in both files, and the contract's deliberate smallness; accepted explicitly in review.
- **No workflow test harness** — the JS twin is review-verified against fixtures, not machine-verified, until one exists.
- **Bench calibration is unproven** — the rank-anchoring design targets the measured inflation failure, but no calibration data exists until the metrics accumulate; D2's ratchet depends on running it.
- **Rubric quality is load-bearing** — a weak consequence-anchored rubric weakens the bench; seed rubrics (bead 1) are drafts until field-tested; full authoring is bead 9.
- **owqa overlap** (§4) — deliberately unresolved; the Assessor's bounce interface is the compatibility contract.
