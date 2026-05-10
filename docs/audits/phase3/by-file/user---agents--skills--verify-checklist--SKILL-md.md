# Findings for src/user/.agents/skills/verify-checklist/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F16: verify-checklist — bead:ID privileged in discovered-work table template
  File: src/user/.agents/skills/verify-checklist/SKILL.md:65,94
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Line 94 includes `bead:ID` as first item in Discovered Work table template. Phase 2 quality-gate reviewer AGREES: examples are not part of the load-bearing completion-to-delivery chain; hygiene cleanup does not remove a real dependency.
  Recommendation: Reorder to list generic tracking mechanisms first: `issue:#N / memory / backlog / bead:ID`. Replace standalone "create beads, issues, or memory entries" with "record in the project's tracking system (issues, backlog, memory, or beads if available)."
  Vision-advancement-tier: C
  Vision-advancement: Makes the completion-gate verify step tool-agnostic by not privileging beads-specific notation.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (quality-gate:F7).
  Sources: phase1/skills.md:F16, phase2/quality-gate-and-delivery.md:F7

---
