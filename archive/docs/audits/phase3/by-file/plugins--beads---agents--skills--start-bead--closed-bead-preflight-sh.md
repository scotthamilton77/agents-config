# Findings for src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F7: closed-bead-preflight.sh — intentional mixed positional+flag interface; document explicitly
  File: src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.sh:9-11,30-50
  Category: script
  Severity: Low
  Tier: 2
  Issue: Interface mixes conventions: primary required argument (`target-id`) is positional while optional arguments use `--flag=value` syntax. The design choice is defensible and documented in the header comment. Test suite exercises this interface thoroughly.
  Recommendation: When agents-config-2gzy addresses interface normalization, explicitly evaluate whether `--target <id>` is preferable to the positional convention. If the positional is kept, add a note in the header explaining why it was intentional. Record the decision either way.
  Vision-advancement-tier: C
  Vision-advancement: Interface consistency across the script suite reduces cognitive load on LLM callers and lowers the chance of argument mis-ordering.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F7

---
