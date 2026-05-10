# Findings for src/plugins/beads/.claude/rules/delivery.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F5: beads/delivery.md — final paragraph uses advisory rather than normative framing
  File: src/plugins/beads/.claude/rules/delivery.md:13-15
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The final paragraph instructs the agent to run `bd show <bead-id>` and `bd mol current <mol-id>` using conditional ("if you arrive at the end... and are uncertain...") framing. Rules should use "always/never" language, not situational prose.
  Recommendation: Reframe as normative: "Never invoke delivery skills as peers of a bead workflow — they run inside molecule steps. Verify step state via `bd mol current <mol-id>` if uncertain." Drop the conditional framing.
  Vision-advancement-tier: C
  Vision-advancement: Tightens normative language and reduces advisory drift in rule prose.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands.
  Sources: phase1/rules.md:F5

---

---

F6: Two delivery.md files — cross-reference anchor fragility under append model
  File: src/user/.claude/rules/delivery.md:1-44, src/plugins/beads/.claude/rules/delivery.md:1-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Plugin delivery.md references "the AUTOMATIC category in core `delivery.md`" which is an implicit order reference in an append model. If append order ever changes, the cross-reference resolves ambiguously.
  Recommendation: Add a `## Core delivery rules` heading to the base delivery.md Action Categories section so the plugin's cross-reference has a stable anchor. Alternatively, normalize the plugin reference to "see the Action Categories section above."
  Vision-advancement-tier: C
  Vision-advancement: Reduces ambiguity risk in the append model, making cross-file references resilient to future ordering changes.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F6

---
