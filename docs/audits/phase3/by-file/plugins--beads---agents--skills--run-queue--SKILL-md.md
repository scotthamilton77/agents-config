# Findings for src/plugins/beads/.agents/skills/run-queue/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F18: run-queue description written in second person
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:1-8
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Description contains "do NOT mix with brainstorming sessions" — second-person imperative, not third-person trigger contract as required by Skills Primer.
  Recommendation: Rewrite: "…Runs in a dedicated session; must not be mixed with interactive brainstorming sessions."
  Vision-advancement-tier: C
  Vision-advancement: Corrects description phrasing to match the third-person trigger contract required by the skills invocation model.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F18

---

---

F22: run-queue announces PR artifacts not exposed by implement-bead's contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:86-104, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:136-140
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: run-queue promises PR number on completion, but implement-bead does not provide progress callbacks or PR metadata. Queue orchestration announces richer status than its downstream dispatcher returns.
  Recommendation: Make run-queue outcome-driven. After implement-bead returns, inspect bead/molecule state and report only mechanically observable artifacts. Mention PR number only if a delivery step explicitly provides one.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4: queue orchestration should only announce artifacts it can prove.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F12)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F12

---

---

F25: run-queue resolves implement-bead escalations too loosely — misses dual-bead human-flag contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:117-133, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:55-79,124-140
  Category: skill
  Severity: High
  Tier: 2
  Issue: run-queue resolves escalations by appending guidance and removing `human` from one bead ID. implement-bead stamps both source bead and step-bead on most recovery paths; some pauses require step reopen. Clearing one label ad hoc can requeue half-recovered work or leave a parked molecule in inconsistent state.
  Recommendation: Add a paired-resolution procedure to run-queue: identify whether escalation belongs to source bead, step-bead, or both; clear labels symmetrically only after underlying block is fixed; then re-check `bd mol current <mol-id>` and step notes before resuming queue.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): resume behavior must be deterministic after parked molecule is handed back from human review.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F9 via D26)
  Rationale: Genuine gap not in Phase 1; Phase 2 AGREE.
  Sources: phase2/escalation-edge-recovery.md:F9

---
