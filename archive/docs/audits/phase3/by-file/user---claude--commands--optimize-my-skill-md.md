# Findings for src/user/.claude/commands/optimize-my-skill.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: optimize-my-skill.md is 233 lines — nearly 3× the command lean-body limit
  File: src/user/.claude/commands/optimize-my-skill.md:1-233
  Category: command
  Severity: High
  Tier: 2
  Issue: The COMMANDS_PRIMER defines the lean-body target as under 80 lines. At 233 lines, the command contains the full optimization methodology (Phase 2-5, reference section "What Makes Skills Effective") rather than delegating to the peer `optimize-my-skill` skill. The command re-implements essentially the full skill body inline, violating the lean-delegation pattern.
  Recommendation: Reduce the command to the lean-delegation shape: parse `$ARGUMENTS` (target scope), invoke the `optimize-my-skill` skill, report results. Strip the reference section (lines ~20-233) from the command body and consolidate into the skill file if any content is not already there.
  Vision-advancement-tier: A
  Vision-advancement: Removes inline methodology duplication that undermines commitment #4 (guardrail completion claims with mechanical evidence) — bloated commands cause agents to apply ad-hoc judgment rather than following the canonical skill process.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F1

---

---

F3: optimize-my-skill.md uses "5,000 words" threshold — conflicts with SKILLS_PRIMER "500 lines"
  File: src/user/.claude/commands/optimize-my-skill.md:73,100,223
  Category: command
  Severity: Medium
  Tier: 1
  Issue: The command uses "Under 5,000 words" as the SKILL.md body size threshold at three locations. The authoritative SKILLS_PRIMER.md states the limit as "under 500 lines." Words and lines are not the same unit; 5,000 words is not equivalent to 500 lines. An agent following the command applies a materially different threshold than the primer's stated standard.
  Recommendation: Replace every occurrence of "5,000 words" with "500 lines" (three occurrences at lines 73, 100, 223).
  Vision-advancement-tier: C
  Vision-advancement: Consistent thresholds reduce noise in audit outputs and improve clarity of the command's assessment step.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/commands.md:F3

---

---

F4: optimize-my-skill.md $ARGUMENTS default path ambiguous for user-level installs
  File: src/user/.claude/commands/optimize-my-skill.md:9
  Category: command
  Severity: Medium
  Tier: 2
  Issue: Empty `$ARGUMENTS` defaults to "all skills in `.claude/skills/`" (a project-level path). This command installs user-wide (`~/.claude/commands/`) and runs in arbitrary project contexts where `.claude/skills/` may not exist. Typical location for user-installed skills is `~/.claude/skills/`. Silent failure when invoked with empty args in a project without `.claude/skills/`.
  Recommendation: Update empty-args default to prefer `~/.claude/skills/` for user-scope skills, falling back to `.claude/skills/` if user-level directory has no skills. Add explicit "if empty and no skills found, emit a usage message" clause.
  Vision-advancement-tier: C
  Vision-advancement: Explicit empty-args handling reduces silent failures, directly improving reliability during autonomous run-queue sessions where human course-correction is unavailable.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F4

---
