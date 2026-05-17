# Findings for src/user/.agents/skills/test-review/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F7: test-review uses undocumented frontmatter fields context: fork and agent: general-purpose
  File: src/user/.agents/skills/test-review/SKILL.md:1-8
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Frontmatter contains `context: fork` and `agent: general-purpose` — neither appears in the official Anthropic SKILL.md schema nor in documented project extensions. These fields have no known harness interpretation.
  Recommendation: Determine whether these fields are consumed by any harness or tool. If not, remove them. If `context: fork` is intentional, document the behavior in the Skills Primer.
  Vision-advancement-tier: C
  Vision-advancement: Removes undocumented fields that create false expectations about harness behavior — a clarity improvement.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address this finding; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F7

---
