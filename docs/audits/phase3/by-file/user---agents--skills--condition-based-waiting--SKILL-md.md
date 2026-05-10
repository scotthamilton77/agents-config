# Findings for src/user/.agents/skills/condition-based-waiting/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F14: condition-based-waiting uses user-invocable: false — non-standard frontmatter field
  File: src/user/.agents/skills/condition-based-waiting/SKILL.md:3
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Frontmatter contains `user-invocable: false`, not in official Anthropic SKILL.md schema. Same field in testing-anti-patterns/SKILL.md. Undefined behavior — either silently ignored or gates invocation without documentation.
  Recommendation: Document the intended meaning in Skills Primer if intentionally used, or remove and rely on the description to de-prioritize the skill for user invocation.
  Vision-advancement-tier: C
  Vision-advancement: Removes non-standard frontmatter that creates false impressions of harness capability.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F14

---
