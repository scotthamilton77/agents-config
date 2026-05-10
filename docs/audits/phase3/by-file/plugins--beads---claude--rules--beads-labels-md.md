# Findings for src/plugins/beads/.claude/rules/beads-labels.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F4: beads-labels.md — keep semantic table, trim operational command examples
  File: src/plugins/beads/.claude/rules/beads-labels.md:1-36
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends collapsing to a two-sentence stub. Four Phase 2 reviewers give PARTIAL: the label semantic table is behaviorally load-bearing (`implementation-readied-session-*` drives Route A gating, `for-bead-*` is the only reliable bead→molecule lookup edge, `human` defines queue visibility, `ralf:*` labels steer dispatch).
  Recommendation: Keep the compact semantic table for behavior-driving labels in the always-loaded rule (at minimum: `brainstormed`, `implementation-ready`, `implementation-readied-session-*`, `for-bead-*`, `human`, `ralf:required`, `ralf:cycles=N`). Move repetitive command examples and inline jq probe to a helper script or reference file. Do NOT reduce to a two-sentence stub.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment #5 (persist context) — label semantics are the persisted control plane that lets later agents interpret molecule state and escalation state correctly.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D12)
  Rationale: Phase 2 PARTIAL × 4; aggregator accepts: keep semantic table, trim examples/commands.
  Sources: phase1/rules.md:F4, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F5, phase2/full-bead-lifecycle.md:F3, phase2/escalation-edge-recovery.md:F3

---

---

F24: human-label semantics contradict between formulas and rules
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:367-372, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:660-666, src/plugins/beads/.claude/rules/beads-labels.md:10-13
  Category: skill (cross-category: formula + rule)
  Severity: High
  Tier: 1
  Issue: Two formulas say adding `human` label excludes a bead from `bd ready`. The beads-labels.md rule says `human` is only a visibility tag and does NOT gate readiness. An agent following the hand-off path can believe work is safely parked when it may still surface as ready.
  Recommendation: Pick one contract and make every touched file match. If `human` alone is not a readiness gate, the hand-off path must add a real blocking dependency and state this explicitly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): a contradictory parking contract causes resumed work to re-enter the queue before a human resolves it.
  Promotion-eligible: no
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F8 via D25)
  Rationale: Active contradiction between rules and formulas; Tier 1 mechanical fix (pick one contract, update all files).
  Sources: phase2/escalation-edge-recovery.md:F8

---
