# Findings for src/plugins/beads/.agents/skills/start-bead/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F17: start-bead — keep routing logic inline; trim verbose forensics only
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:1-357
  Category: skill
  Severity: Low
  Tier: 2
  Issue: At 357 lines, approaching 500-line budget. Phase 2 multi-agent (F5) and escalation (F1) reviewers both give PARTIAL: the routing matrix and recovery branches (Route Z, 0/0 burn, post-brainstorm hand-off stop) are the dispatch contract and must stay in SKILL.md.
  Recommendation: Extract only verbose audit-comment templates and repetitive forensic examples to a reference file. Keep Route Z handling, molecule-ambiguity escalation, 0/0 burn recovery, post-brainstorm hand-off stop, and the full route-selection logic in SKILL.md per D16.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 (make AI good at saying "no, not ready"): the routing matrix is the mechanism that bounces under-specified work back.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D16)
  Rationale: Phase 2 PARTIAL from two reviewers; aggregator accepts trim-forensics-only synthesis.
  Sources: phase1/skills.md:F17, phase2/multi-agent-dispatch.md:F5, phase2/escalation-edge-recovery.md:F1

---

---

F21: start-bead can route into implement-bead from a non-orchestrator context
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:3-7,173-190, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:8-10,98
  Category: skill
  Severity: High
  Tier: 2
  Issue: start-bead Route A can invoke implement-bead directly. implement-bead explicitly requires the invoking agent to be the top-level ORCHESTRATOR. start-bead never establishes this precondition. If triggered from a delegated context, it routes into a dispatcher that cannot dispatch.
  Recommendation: Add a preflight rule near the top of start-bead: if this session is not the top-level orchestrator, return the routing decision to the caller rather than invoking implement-bead directly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5: the router must not hand work to a dispatcher that is structurally unable to spawn contracted workers.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F4)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F4

---
