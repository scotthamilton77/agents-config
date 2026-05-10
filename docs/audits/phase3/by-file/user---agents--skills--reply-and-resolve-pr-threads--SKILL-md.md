# Findings for src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F2: Schema validation guards duplicated between wait-for-pr-comments and reply-and-resolve-pr-threads
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214, src/user/.agents/skills/wait-for-pr-comments/SKILL.md:683-713
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Nine schema validation guards are reproduced verbatim in both skills. Two copies means any change must be kept in sync manually; guard numbering is already slightly inconsistent.
  Recommendation: Define guards once in a shared SCHEMA.md (per F1) referenced by both SKILL.md files. Each file keeps only the guards that are implementation-specific to its own write/read side.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail completion claims): divergent guard descriptions will eventually cause a mismatch between what the writer enforces and what the reader expects.
  Promotion-eligible: yes
  Resolution: ACCEPTED (merged into D9/D10 synthesis)
  Rationale: Phase 2 F3 (quality-gate) agrees that shared SCHEMA.md is correct; the move-to-shared-path decision (D9) applies.
  Sources: phase1/skills.md:F2, phase2/quality-gate-and-delivery.md:F3

---

---

F4: reply-and-resolve-pr-threads — same beads leakage; same split-not-move fix
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:111,240-242
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: Autonomous mode recovery prescribes `bd label add <bead-id> human` + `bd update` as the escalation path. `--bead-id` is a first-class parameter of the skill's arg protocol. Non-beads tools receive instructions they cannot execute.
  Recommendation: Mirror D8 split. Keep shared thread-reply/resolution engine; move autonomous recovery persistence and `--bead-id` handling into a beads-specific extension/wrapper.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5: these two skills form the PR review completion gate — silently failing on non-Claude tools breaks autonomous overnight PR cycles.
  Promotion-eligible: yes
  Resolution: ACCEPTED (split-not-move per D8)
  Rationale: Same Phase 2 evidence as F3 above.
  Sources: phase1/skills.md:F4, phase2/full-bead-lifecycle.md:F2, phase2/quality-gate-and-delivery.md:F2

---

---

F11: reply-and-resolve-pr-threads — hardcoded cross-skill validate-inventory.sh path
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:65
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 0 schema validation invokes `~/.claude/skills/wait-for-pr-comments/validate-inventory.sh` using a hardcoded path pointing to a different skill's directory. Cross-skill filesystem coupling that breaks if installation prefix changes.
  Recommendation: Move `validate-inventory.sh` to a shared support location (e.g., `src/user/.agents/skills/shared/` or `wait-for-pr-comments-shared/`) and have both skills reference it from the shared path. Do NOT copy or symlink per D9.
  Vision-advancement-tier: C
  Vision-advancement: Removes brittle cross-skill filesystem coupling that will silently break Phase 0 validation if skills are relocated.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D9)
  Rationale: Phase 2 quality-gate reviewer gives PARTIAL; aggregator accepts shared-location synthesis.
  Sources: phase1/skills.md:F11, phase2/quality-gate-and-delivery.md:F3

---
