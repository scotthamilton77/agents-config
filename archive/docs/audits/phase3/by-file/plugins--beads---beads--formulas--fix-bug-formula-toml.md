# Findings for src/plugins/beads/.beads/formulas/fix-bug.formula.toml
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F4: worktree-path encoding/decoding — extract to two helper scripts
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:116-122, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:100-102,139-142, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:100-106,139-141
  Category: formula
  Severity: High
  Tier: 2
  Issue: The worktree-path label encoding/decoding procedure (`_ → _u`, `/ → __`) appears in prose form in at least five locations across three formula files. If the bijection changes, five prose locations must be updated in sync.
  Recommendation: Extract encoding and decoding into two helper scripts: `bd-worktree-path-encode.sh <path>` and `bd-worktree-path-decode.sh <encoded>`. Each preflight step reduces to a single script call; each consuming step reduces to `<path>=$(bd-worktree-path-decode.sh <label>)`. Flag for the scripts audit scope.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating five copies of a fragile bijection into one canonical helper advances commitment #4 (guardrail completion claims) — a shared script can be tested once, whereas five prose copies cannot.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not dispute extraction; Phase 1 finding stands.
  Sources: phase1/formulas.md:F4

---

---

F5: fix-bug and implement-feature reroute protocol — extract mechanics, keep postcondition checklist
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:237-318, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:188-284
  Category: formula
  Severity: High
  Tier: 2
  Issue: Both red-tests steps contain a near-identical Reroute Protocol (steps 1-11). Phase 2 formula-step-execution reviewer gives PARTIAL: reroute is irreversible; the step-bead must retain a postcondition checklist so the agent can verify what the helper preserved.
  Recommendation: Extract the mechanical steps 2-11 into `bd-reroute-to-docs-only.sh`. Keep in each red-tests step: (a) trigger evaluation logic (A, B, A+B as applicable per formula), (b) an inline postcondition checklist specifying the required surviving invariants and what must be verified before considering reroute complete per D18.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (context persists through compaction and handoff) — a single tested script is more reliable than two prose copies that can silently diverge.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified per D18)
  Rationale: Phase 2 PARTIAL — extract mechanics but keep postcondition checklist inline.
  Sources: phase1/formulas.md:F5, phase2/formula-step-execution.md:F3

---

---

F6: fix-bug file header contains pure motivational prose
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:1-19
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: File-level comment includes "The cardinal sin of bug fixing is patching the symptom." This is motivational framing that belongs in a README or spec document, not in a formula file. The `diagnose` step description already enforces the hard gate.
  Recommendation: Remove the "cardinal sin" motivational sentence. Keep the factual stage-sequence description and the "See:" and "Usage:" comments, which are actionable references.
  Vision-advancement-tier: C
  Vision-advancement: Removing non-actionable motivational prose from formula headers reduces maintenance cognitive load.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/formulas.md:F6

---

---

F11: name field mirrors id throughout implement-feature and fix-bug — undocumented step field
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:47-48, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:46-47
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: Both formulas set `name = "..."` on every step, mirroring `id` exactly. The FORMULAS_PRIMER does not list `name` as a valid step field. In-file comment says it "is accepted by bd... and serves as the stage-role identifier used by the shell driver." If load-bearing for the shell driver, this should be documented once at file top; if not load-bearing, it is noise. Also affects docs-only.formula.toml.
  Recommendation: Confirm whether `name` is required by the shell driver. If required, add one top-level file comment explaining the convention and remove the per-step comment from every step. If not required, remove all `name` fields.
  Vision-advancement-tier: C
  Vision-advancement: Removing redundant undocumented fields reduces per-step noise and makes formulas easier to audit and maintain.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/formulas.md:F11

---

---

F13: fix-bug diagnose step — remove superpowers:root-cause-tracing dead skill reference
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:134-135
  Category: formula
  Severity: Low
  Tier: 1
  Issue: diagnose step lists `superpowers:root-cause-tracing` as a preloaded skill. This skill does not exist in the known skill inventory (confirmed deleted). The step promises a root-cause workflow the agent cannot actually load.
  Recommendation: Remove `superpowers:root-cause-tracing` from the preloaded skills list and from the invocation instruction. Reference `superpowers:systematic-debugging` only (which covers root-cause work).
  Vision-advancement-tier: C
  Vision-advancement: Removing references to non-existent skills prevents silent degradation in skill invocation.
  Resolution: ACCEPTED
  Rationale: Phase 2 formula-step-execution reviewer AGREE (F7); phase2/multi-agent-dispatch.md AGREE (F6).
  Sources: phase1/formulas.md:F13, phase2/formula-step-execution.md:F7

---

---

F14: preflight spec validation logic duplicated across docs-only, fix-bug, implement-feature — extract mechanics only
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:50-93, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:50-114, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:51-116
  Category: formula
  Severity: High
  Tier: 2
  Issue: The preflight step shares large blocks of near-identical logic. However Phase 2 escalation reviewer gives PARTIAL (D17): docs-only is the reroute target and deliberately skips coverage gates; fix-bug and implement-feature inspect coverage and park with a human flag on missing report-location. A single shared helper would collapse these divergent escalation rules.
  Recommendation: Extract only mechanically identical parts: `for-bead-<mol-id>` label stamp, worktree creation + path encoding, `worktree-path-*` label stamp, claim-walk. Keep coverage/gates policy and corresponding human-flag-vs-skip behavior inside each formula. This is a narrower extraction than Phase 1 proposed per D17.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating shared mechanics into one tested helper advances commitment #4 (guardrail completion claims) while preserving formula-specific "not ready, stop here" behavior.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified per D17)
  Rationale: Phase 2 PARTIAL — share mechanics, keep policy inline per formula.
  Sources: phase1/formulas.md:F14, phase2/escalation-edge-recovery.md:F5

---
