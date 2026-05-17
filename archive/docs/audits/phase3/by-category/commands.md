# Phase 3 By-Category: Commands
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the commands category.
Phase 2 did not produce a dedicated commands reviewer — findings here come from Phase 1 only.

---

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

F2: optimize-my-agent.md is 107 lines — embeds full methodology without a peer skill
  File: src/user/.claude/commands/optimize-my-agent.md:1-107
  Category: command
  Severity: High
  Tier: 2
  Issue: At 107 lines, the command exceeds the 80-line lean-body target and embeds a complete 5-phase optimization workflow, a quality rubric table, a 7-item failure checklist, reference structure template, and common agent types list. No dedicated skill for agent-persona optimization was found in the source tree — the command is doing double duty as both entry point and methodology carrier.
  Recommendation: Extract the 5-phase methodology into a new `optimize-my-agent` skill alongside the existing `optimize-agents-md` skill. The command then becomes a lean delegator: parse `$ARGUMENTS`, invoke the new skill.
  Vision-advancement-tier: A
  Vision-advancement: Extracting the methodology to a skill implements commitment #4 (mechanical evidence guardrails) by ensuring the optimization process is consistently applied via the skill invocation path.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F2

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

F5: optimize-my-agent.md quality rubric axes diverge from AGENTS_PRIMER schema
  File: src/user/.claude/commands/optimize-my-agent.md:18-26,59-99
  Category: command
  Severity: Medium
  Tier: 2
  Issue: The command's Phase 2 quality rubric assesses agent files against six areas: Commands, Testing, Project Structure, Code Style, Git Workflow, and Boundaries. The AGENTS_PRIMER defines quality issues to flag as: over-broad role, no dispatch examples, wrong model tier, body mixing role with task, bead references in shared agents, and unused skills. The two rubrics are entirely non-overlapping — the command's rubric is for a software project's AGENTS.md configuration, not an agent persona .md file.
  Recommendation: Align the rubric with AGENTS_PRIMER.md's quality issues table. Replace the six-area table with: role breadth, description trigger quality, model tier appropriateness, body/task separation, bead hygiene, and unused skills. If this command genuinely targets AGENTS.md configuration files, rename it to avoid collision with `optimize-agents-md`.
  Vision-advancement-tier: A
  Vision-advancement: A rubric aligned with actual agent-file quality criteria strengthens commitment #2 (make AI good at saying "no, not ready") by correctly identifying when agent definitions lack the trigger precision needed for reliable autonomous dispatch.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F5

---

F6: refresh-agents-md.md hard-codes dispatching-parallel-agents skill with no availability fallback
  File: src/user/.claude/commands/refresh-agents-md.md:19
  Category: command
  Severity: Low
  Tier: 2
  Issue: Step 1 instructs to invoke `dispatching-parallel-agents` skill (from obra/superpowers plugin). If the plugin is absent, the command references an unavailable skill and the three subagent tasks silently don't run. No fallback instruction for non-parallel execution.
  Recommendation: Add brief availability check: "If the `dispatching-parallel-agents` skill is available, use it to run the three tasks simultaneously. Otherwise, run them sequentially."
  Vision-advancement-tier: C
  Vision-advancement: Graceful skill-availability fallback reduces hard failures in partially-configured environments, improving portability of the discipline layer.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F6

---

F7: refresh-agents-md.md re-implements optimize-agents-md skill principles inline
  File: src/user/.claude/commands/refresh-agents-md.md:94-102,120-130
  Category: command
  Severity: Medium
  Tier: 2
  Issue: Steps 3b and 3d name the `optimize-agents-md` skill but then immediately enumerate its principles inline in the command body. This is a lean-delegation failure: the command re-implements a condensed version of the skill inline rather than invoking it. Two maintenance surfaces that can diverge over time.
  Recommendation: Replace inline principle enumeration in Steps 3b and 3d with a direct Skill invocation instruction: "Invoke the `optimize-agents-md` skill for this file." The skill carries its own validation checklist.
  Vision-advancement-tier: A
  Vision-advancement: Routing through the canonical skill rather than re-implementing its methodology inline advances commitment #4 (guardrail completion claims) — the skill's validation checklist becomes the authoritative gate.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/commands.md:F7

---

F8: optimize-my-agent.md heading "Agent.md" mismatches functional scope
  File: src/user/.claude/commands/optimize-my-agent.md:1
  Category: command
  Severity: Low
  Tier: 1
  Issue: File is named `optimize-my-agent.md` but heading is "# Optimize Agent.md" (with period and capital M — matching AGENTS.md configuration files). The body begins "analyze and optimize the agent.md file at: $ARGUMENTS." The title and scope are inconsistent with each other and with the existing `optimize-agents-md` skill, creating genuine user confusion.
  Recommendation: Decide actual scope; align title, heading, and body accordingly. If targeting agent persona files (with frontmatter name/description/model/color), rename heading to "Optimize Agent Definition." If targeting AGENTS.md configuration files, rename to avoid collision with `optimize-agents-md`.
  Vision-advancement-tier: C
  Vision-advancement: Removing naming ambiguity ensures agents select the correct optimization tool without trial and error.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/commands.md:F8
