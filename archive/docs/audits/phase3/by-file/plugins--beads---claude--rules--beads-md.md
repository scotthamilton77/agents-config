# Findings for src/plugins/beads/.claude/rules/beads.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: beads.md — I1 and I2 parent-chain invariants should become helper scripts (retain rule text)
  File: src/plugins/beads/.claude/rules/beads.md:21-46
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: I1 (claim walk) and I2 (close walk) loops are multi-line deterministic shell sequences embedded in rule prose. Per Rules Primer, prose-prescribed sequences drift and are harder to maintain than helper scripts. Phase 2 constraint-aware and escalation reviewers both give PARTIAL: the shell blocks should become helper scripts, but the invariants (the requirement that these walks must happen) must stay in the always-loaded rule text.
  Recommendation: Extract I1 and I2 shell sequences to a helper script `bd-walk-parents.sh --mode claim|close <id>`. The rule prose becomes: "Run `bd-walk-parents.sh --mode claim <id>` before starting work; run `--mode close <id>` after closing." The requirement stays; the implementation moves. This is also a Tier 3 extraction candidate per audit scope.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment #5 (persist context across compaction and handoff) — helper scripts survive LLM context limits where prose-embedded sequences can be silently mis-reproduced.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D11)
  Rationale: Phase 2 PARTIAL — retain rule text but move implementation to scripts. Aggregator accepts synthesis.
  Sources: phase1/rules.md:F1, phase2/constraint-aware-execution.md:F4, phase2/escalation-edge-recovery.md:F3

---

---

F2: beads.md — "bd ready" dual-list filter is a script candidate (Tier 3)
  File: src/plugins/beads/.claude/rules/beads.md:63-68
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The "List 2 — Ready to brainstorm" command contains an inline jq expression that is a deterministic filtering operation. The expression is not obviously readable at a glance, making the rule harder to verify than a named script call.
  Recommendation: Extract to a named helper `bd-ready-to-brainstorm.sh` that wraps the filter. Rule prose references the script name. This provides a stable location if the jq logic needs to change when `bd ready` adds native label-negation support. Also a Tier 3 extraction candidate.
  Vision-advancement-tier: C
  Vision-advancement: Reduces noise and improves clarity by replacing an opaque jq chain with a named, documentable operation.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not specifically address; Phase 1 finding stands.
  Sources: phase1/rules.md:F2

---

---

F3: beads.md over-length — extract reference material, retain normative runtime contract
  File: src/plugins/beads/.claude/rules/beads.md:1-88
  Category: rule
  Severity: High
  Tier: 2
  Issue: At 88 lines, contains CLI reference, multi-step behavioral guidance, workflow orchestration, usage tables, and session-separation policy. Phase 2 has three PARTIAL verdicts: the runtime contract (I1/I2/I3 summaries, `bd human list` precedence, `human` label semantics, `for-bead-*` probe, session-separation gate, `--notes` destructive-overwrite footgun) must remain always-loaded because `implement-bead` and other skills cite it as authority.
  Recommendation: Retain in always-loaded rule: (a) dangerouslyDisableSandbox requirement, (b) I3 discovered-work placement policy, (c) session-separation gate, (d) `--notes` destructive-overwrite footgun, (e) I1/I2 invariant requirements (not shell sequences — those move to helper scripts per F1), (f) `human` label semantics, (g) `for-bead-*` probe pattern. Extract to a `beads-reference` skill or supporting REFERENCE.md: CLI type/priority glossary, Notes-vs-Comments table, "bd ready" dual-list behavior.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail completion claims) by reducing per-session context load so normative constraints remain prominent and are not buried under reference material.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D11)
  Rationale: Phase 2 PARTIAL × 3; aggregator accepts: retain normative runtime contract, extract reference fluff.
  Sources: phase1/rules.md:F3, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F4, phase2/escalation-edge-recovery.md:F3

---
