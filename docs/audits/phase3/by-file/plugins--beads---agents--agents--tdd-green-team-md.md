# Findings for src/plugins/beads/.agents/agents/tdd-green-team.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F3: Wrong namespace for writing-unit-tests and testing-anti-patterns in bead-pipeline agents
  File: src/plugins/beads/.agents/agents/bead-implementor.md:28-29, src/plugins/beads/.agents/agents/tdd-red-team.md:30-32, src/plugins/beads/.agents/agents/tdd-green-team.md:33-34
  Category: agent
  Severity: High
  Tier: 1
  Issue: Three agents list `superpowers:writing-unit-tests` and `superpowers:testing-anti-patterns` in `skills:` frontmatter. These skills are NOT in the superpowers plugin (confirmed: superpowers 5.1.0 has no writing-unit-tests or testing-anti-patterns directory). They are plain skills from this repo installed at `~/.claude/skills/`. The `superpowers:` namespace prefix is incorrect and will cause skill resolution failure.
  Recommendation: Replace `superpowers:writing-unit-tests` → `writing-unit-tests` and `superpowers:testing-anti-patterns` → `testing-anti-patterns` in all three files. Also fix body text references that use the wrong namespace prefix.
  Vision-advancement-tier: A
  Vision-advancement: Correct skill resolution is a prerequisite for the TDD pipeline to enforce commitment #4 (guardrail every completion claim with mechanical evidence) — misnaming skills means TDD methodology fails to load.
  Resolution: ACCEPTED
  Rationale: Phase 2 multi-agent reviewer AGREE (F7); Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F3, phase2/multi-agent-dispatch.md:F7

---
