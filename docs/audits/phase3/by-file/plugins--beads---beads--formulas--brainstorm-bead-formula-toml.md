# Findings for src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: brainstorm-bead finalize step — extract helper scripts for deterministic shell sequences
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:228-651
  Category: formula
  Severity: High
  Tier: 2
  Issue: The `finalize` step description is ~420 lines of interleaved prose and bash. Steps 1-3 and 5 contain deterministic shell sequences (idempotency probe, children pre-flight check, label-copy filtering, child migration loop, merge-gate creation) that are script candidates. Steps 3c (RALF triage), 3d (formula selection), and 9 (burn + hand-off report) are agent decision points that should remain in prose.
  Recommendation: Extract Steps 1 (idempotency probe), 2 (children pre-flight check), 3f (label-copy filtering), 5a (child migration loop), and 5b (merge-gate + [h]-child creation) into named helper scripts under `~/.beads/scripts/`. Keep agent decision points and step 3h (label assembly, purely declarative) inline. Target: reduce finalize from ~420 lines to under 100.
  Vision-advancement-tier: A
  Vision-advancement: Extracting deterministic orchestration logic from formula prose directly advances commitment #5 (persist context) — shorter, script-backed steps are more compaction-resistant and survive agent handoff with less context-window cost.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not dispute the script extraction direction; Phase 1 finding stands.
  Sources: phase1/formulas.md:F1

---

---

F2: brainstorm-bead — motivational rationale embedded in claim step prose
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:41-51
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: The `claim` step description contains explanatory motivation about why claim-walks are required ("Brainstorming IS work — the bead's status must reflect that…"). This is background rationale, not execution instruction. The action and its DoD are stated without this sentence.
  Recommendation: Remove the motivational sentence. Keep "The claim walk marks this bead and all ancestor epics in_progress. Read the `walked=N` output to confirm the chain depth."
  Vision-advancement-tier: C
  Vision-advancement: Removing background rationale reduces per-step context weight, reducing agent judgment cycles wasted on non-executable content.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/formulas.md:F2

---

---

F3: brainstorm-bead — QUESTION FILTER should stay self-contained in discuss step
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:74-84,104-108
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends replacing the QUESTION FILTER in the discuss step with a back-reference to assess. Phase 2 formula-step-execution reviewer DISAGREE: on the actual runtime path, the discuss step-bead is its own execution prompt. A resumed or compacted session may have the discuss bead in hand without the assess text in active context. Replacing the filter with a back-reference strips the live guardrail the agent needs.
  Recommendation: Keep the QUESTION FILTER fully self-contained in the discuss step per D1/Phase 2. If noise reduction is desired, tighten the wording inside the step itself (e.g., reduce to 3-4 tight lines) rather than pointing back to assess.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitments #1 and #2 (frontload judgment; make AI good at saying "no, not ready") — the executing agent needs the filter in the live step prompt to avoid over-escalating or silently guessing.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified — keep self-contained, tighten wording)
  Rationale: Phase 2 DISAGREE accepted (D1); recommendation becomes "tighten, not cross-reference."
  Sources: phase1/formulas.md:F3, phase2/formula-step-execution.md:F1

---

---

F12: brainstorm-bead — vapor + pour are intentionally orthogonal; add clarifying comment
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:25-26
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: Phase 1 reads `phase = "vapor"` and `pour = true` as contradictory and recommends changing to `phase = "liquid"`. Three Phase 2 reviewers DISAGREE (D1, D23): these fields are orthogonal — `phase = "vapor"` signals wisp-mode interactive use; `pour = true` causes step materialization within that wisp. Changing to `liquid` would break `start-bead` Route C contract.
  Recommendation: Keep `phase = "vapor"` with `pour = true`. Add a comment in the formula header explaining the intentional semantics: "`phase = vapor` → use `bd mol wisp create` (ephemeral lifecycle); `pour = true` → still materializes executable step beads within the wisp." Update FORMULAS_PRIMER to document this valid vapor-plus-poured-wisp configuration.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitments #1 and #5 — preserves brainstorming as an explicit interactive workflow while still materializing state that survives step-to-step handoff.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified — no formula change; add documentation)
  Rationale: Phase 2 DISAGREE × 3 accepted (D1); finding converts to documentation task.
  Sources: phase1/formulas.md:F12, phase2/formula-step-execution.md:F6, phase2/full-bead-lifecycle.md:F5, phase2/escalation-edge-recovery.md:F4

---
