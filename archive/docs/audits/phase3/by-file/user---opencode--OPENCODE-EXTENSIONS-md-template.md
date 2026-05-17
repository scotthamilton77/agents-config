# Findings for src/user/.opencode/OPENCODE-EXTENSIONS.md.template
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F12: OPENCODE-EXTENSIONS.md.template — source vs installed context description confusing
  File: src/user/.opencode/OPENCODE-EXTENSIONS.md.template:5-7
  Category: template
  Severity: Low
  Tier: 2
  Issue: Lines 5-7 state "This file was dynamically flattened at install time." This describes the installed file, but someone reading the template in the source repo sees it as a source template, not a flattened output. The comment is accurate for the installed file but misleading for the source template.
  Recommendation: Rewrite the header comment to distinguish source vs. installed context: "When installed, this file is dynamically flattened at install time... If you are reading this in the source repository (`src/user/.opencode/`), this is the source template, not the installed output."
  Vision-advancement-tier: C
  Vision-advancement: Clarity in source template documentation reduces developer confusion when maintaining the install pipeline.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F12

---
