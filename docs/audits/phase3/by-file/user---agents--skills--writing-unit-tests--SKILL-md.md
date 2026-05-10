# Findings for src/user/.agents/skills/writing-unit-tests/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F15: writing-unit-tests — "follow-up bead" bead-tracker vocabulary in shared content
  File: src/user/.agents/skills/writing-unit-tests/SKILL.md:60,180,197
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Three locations use "follow-up bead" as a rationalization-to-reject pattern. Bead-tracker vocabulary in shared content is confusing for non-beads tools; the underlying principle is tool-agnostic.
  Recommendation: Replace "follow-up bead" with "follow-up ticket" or "deferred issue" at all three locations. Mechanical substitution.
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content — a three-site mechanical fix.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F15

---
