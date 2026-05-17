# Findings for src/user/.agents/skills/simplify/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F8: simplify skill — external-source drift annotation as invisible HTML comment
  File: src/user/.agents/skills/simplify/SKILL.md:7
  Category: skill
  Severity: Low
  Tier: 1
  Issue: HTML comment `<!-- Source: /simplify slash command... -->` is maintenance metadata invisible in markdown previews and unreadable by agents. No value to agent execution.
  Recommendation: Delete comment and record sync policy in git history, or convert to an explicit `## Maintenance Note` section at the bottom of the file.
  Vision-advancement-tier: C
  Vision-advancement: Removes invisible metadata noise from skill body — an invisible comment adds no signal to agent judgment.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F8

---

---

F9: simplify skill — bd remember negation in shared content
  File: src/user/.agents/skills/simplify/SKILL.md:57
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: "Do NOT use `bd remember` for this" introduces bead-tracker vocabulary into shared content. A Codex/Gemini agent has no `bd remember`; the sentence is confusing for non-beads tools.
  Recommendation: Replace with tool-agnostic: "Do not use issue-tracker or task-tracking mechanisms for this — use the host's project memory system."
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content, keeping the shared namespace tool-agnostic.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F9

---
