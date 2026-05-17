# Findings for src/user/.agents/skills/ralf-it/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F12: ralf-it deprecated stub still costs context window; should be deleted
  File: src/user/.agents/skills/ralf-it/SKILL.md:1-16
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: ralf-it is explicitly deprecated, 16 lines, and loads into every agent context at startup. The `model: opus[1m]` on a stub that does nothing is semantically wrong — accidental invocation spins up an expensive model to say "use something else."
  Recommendation: Delete ralf-it/SKILL.md and its directory entirely. The delegation rule already states ralf-implement and ralf-review are opt-in via explicit invocation.
  Vision-advancement-tier: C
  Vision-advancement: Removing a deprecated stub reduces startup context weight on every session.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F12

---
