# Phase 1 Audit: Commands
Auditor: audit-commands subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 3 slash command files

---

## Drift check

```
git diff --name-only af9c1bfc342bf7578ad491cc63dc95b07618c851 -- src/user/.claude/commands/
git ls-files --others --exclude-standard -- src/user/.claude/commands/
```

Both commands produced no output. Audit proceeds on clean input.

---

## Files reviewed

| File | Lines |
|------|-------|
| `src/user/.claude/commands/optimize-my-agent.md` | 107 |
| `src/user/.claude/commands/optimize-my-skill.md` | 233 |
| `src/user/.claude/commands/refresh-agents-md.md` | 158 |

---

## Findings

---

F1: optimize-my-skill.md is 233 lines — nearly 3× the command lean-body limit
  File: src/user/.claude/commands/optimize-my-skill.md:1-233
  Category: command
  Severity: High
  Tier: 2
  Issue: The COMMANDS_PRIMER defines the lean-body target as under 80 lines. At 233 lines, optimize-my-skill.md has grown into a full methodology document covering frontmatter schemas, progressive-disclosure tiers, anti-pattern checklists, body-content rubrics, triggering tests, and a reference "what makes skills effective" section. This is methodology that should live in a skill, not inline command prose. Crucially, the `optimize-my-skill` skill already exists (it is the peer of this command: the skill is listed in the available-skills manifest as `optimize-my-skill`). The command re-implements essentially the full skill body inline, violating the lean-delegation pattern.
  Recommendation: Reduce the command to the lean-delegation shape: parse `$ARGUMENTS` (target scope), invoke the `optimize-my-skill` skill, report results. The skill carries the methodology. The command's reference section (Phase 2 through Phase 5, the "Reference: What Makes Skills Effective" section, lines ~20-233) should be stripped from the command body and consolidated into the skill file if any of it is not already there.
  Vision-advancement-tier: A
  Vision-advancement: Removes inline methodology duplication that undermines commitment 4 (guardrail completion claims with mechanical evidence) — bloated commands cause agents to apply ad-hoc judgment rather than following the canonical skill process, weakening the mechanical verification guarantee.
  Promotion-eligible: yes
  Related: F2, F4

---

F2: optimize-my-agent.md is 107 lines — over the lean-body limit and embeds full methodology
  File: src/user/.claude/commands/optimize-my-agent.md:1-107
  Category: command
  Severity: High
  Tier: 2
  Issue: At 107 lines, the command exceeds the 80-line lean-body target and embeds a complete 5-phase optimization workflow (read/understand, assess, identify problems, propose, refine), a quality rubric table for 6 areas, a 7-item failure checklist, a reference structure template, 5 key principles, and a list of "common agent types that work well." This is skill-level content embedded in a command. The `optimize-agents-md` skill already exists and covers AGENTS.md/CLAUDE.md optimization with a comparable (and more authoritative) methodology. However, `optimize-my-agent.md` targets *agent definition files* specifically (the `.md` agent persona files), not AGENTS.md configuration files — this is a distinct scope. No dedicated skill for agent-persona optimization was found in the source tree, which means the methodology has no home other than this command. The command is therefore doing double duty: acting as both the entry point AND the methodology carrier.
  Recommendation: Extract the 5-phase methodology into a new `optimize-my-agent` skill (alongside the existing `optimize-agents-md` skill). The command then becomes a lean delegator: parse `$ARGUMENTS`, invoke the skill. This also removes the 6-area quality rubric (lines 19-25) and the failure checklist (lines 28-35) from the command into the skill body, where progressive disclosure applies.
  Vision-advancement-tier: A
  Vision-advancement: Extracting the methodology to a skill implements commitment 4 (mechanical evidence guardrails) by ensuring the optimization process is consistently applied via the skill invocation path rather than being ad-hoc inlined into each command execution.
  Promotion-eligible: yes
  Related: F1, F5

---

F3: optimize-my-skill.md uses "5,000 words" as the SKILL.md size threshold — conflicts with SKILLS_PRIMER's "500 lines"
  File: src/user/.claude/commands/optimize-my-skill.md:73,100,223
  Category: command
  Severity: Medium
  Tier: 1
  Issue: The command uses "Under 5,000 words" as the SKILL.md body size threshold (lines 73, 100, 223: "Under 5,000 words. If over, flag sections that should move to `references/`"). The authoritative SKILLS_PRIMER.md states the limit as "under **500 lines**." Words and lines are not the same unit, and 5,000 words is not equivalent to 500 lines. An agent following the command will apply a materially different (and larger) threshold than the primer's stated standard, allowing bloated skills to pass audit without being flagged. This is an incoherence within the tool's own quality-enforcement machinery.
  Recommendation: Replace every occurrence of "5,000 words" in optimize-my-skill.md with "500 lines" to align with SKILLS_PRIMER.md. There are three occurrences (lines 73, 100, 223). Also update the folder-structure assessment bullet (line 73) and the anti-patterns checklist entry (line 100) to use "500 lines" consistently.
  Vision-advancement-tier: C
  Vision-advancement: Consistent thresholds reduce noise in audit outputs and improve clarity of the command's assessment step.
  Promotion-eligible: no

---

F4: optimize-my-skill.md's $ARGUMENTS default is ambiguous for user-level installs
  File: src/user/.claude/commands/optimize-my-skill.md:9
  Category: command
  Severity: Medium
  Tier: 2
  Issue: The command documents three forms for `$ARGUMENTS`: skill name, directory path, or empty (defaulting to "all skills in `.claude/skills/`"). However, the COMMANDS_PRIMER emphasizes that commands must handle empty args gracefully with an explicit default. The stated default path `.claude/skills/` is a project-level path. This command installs user-wide (`~/.claude/commands/`), meaning it runs in arbitrary project contexts where `.claude/skills/` may not exist or may be the wrong scope. The more typical location for user-installed skills is `~/.claude/skills/`. The ambiguity could cause silent failures (no SKILL.md files found, no output, user confused) when the command is invoked with empty `$ARGUMENTS` in a project that lacks `.claude/skills/`.
  Recommendation: Update the empty-args default documentation and behavior to prefer `~/.claude/skills/` for user-scope skills, falling back to `.claude/skills/` if the user-level directory has no skills or if the user is in a project with a local skill directory. Add an explicit "if empty and no skills found at default path, emit a usage message" clause.
  Vision-advancement-tier: C
  Vision-advancement: Explicit empty-args handling reduces silent failures, which directly improves agent reliability during autonomous run-queue sessions where human course-correction is unavailable.
  Promotion-eligible: yes
  Related: F1

---

F5: optimize-my-agent.md applies a quality rubric that diverges from the AGENTS_PRIMER schema
  File: src/user/.claude/commands/optimize-my-agent.md:18-26, 59-99
  Category: command
  Severity: Medium
  Tier: 2
  Issue: The command's Phase 2 quality rubric assesses agent files against six areas: Commands, Testing, Project Structure, Code Style, Git Workflow, and Boundaries. The AGENTS_PRIMER defines quality issues to flag as: over-broad role, no dispatch examples, wrong model tier, body mixing role with task, bead references in shared agents, and unused skills in the `skills:` field. The two rubrics are entirely non-overlapping. The command's rubric reads as a general software-project AGENTS.md review (checking for build commands, test commands, stack versions) rather than an agent-definition-file review (checking dispatch trigger quality, model assignment, role scope). This means the command produces structurally incorrect assessments — flagging "Missing executable commands" on an agent persona file that correctly has no commands, or praising "Git Workflow" as a quality axis for an agent file that should never contain git workflow information.
  Recommendation: Align the command's quality rubric with AGENTS_PRIMER.md's quality issues table. Replace the six-area table (lines 18-26) with the primer's axes: role breadth, description trigger quality, model tier appropriateness, body/task separation, bead hygiene, and unused skills. The current rubric appears designed for AGENTS.md configuration files (the territory of `optimize-agents-md`) — not for agent persona `.md` files in `agents/`. If this command is genuinely intended for AGENTS.md/CLAUDE.md files rather than agent definitions, it should be renamed to eliminate the naming ambiguity with the `optimize-agents-md` skill.
  Vision-advancement-tier: A
  Vision-advancement: A rubric aligned with actual agent-file quality criteria strengthens commitment 2 (make AI good at saying "no, not ready") by ensuring the optimization command correctly identifies when agent definitions lack the trigger precision needed for reliable autonomous dispatch.
  Promotion-eligible: yes
  Related: F2

---

F6: refresh-agents-md.md hard-codes `dispatching-parallel-agents` skill invocation in Step 1 without checking availability
  File: src/user/.claude/commands/refresh-agents-md.md:19
  Category: command
  Severity: Low
  Tier: 2
  Issue: Step 1 instructs: "Invoke the `dispatching-parallel-agents` skill to run these three tasks simultaneously." The `dispatching-parallel-agents` skill is provided by the `obra/superpowers` plugin, which is listed in AGENTS.md as a prerequisite but is not guaranteed to be present in every installation. If the plugin is absent, the command references an unavailable skill — the three subagent tasks (git analysis, file inventory, directory discovery) simply do not run and the command silently degrades. The command has no fallback instruction for non-parallel execution when the skill is unavailable.
  Recommendation: Add a brief availability check before Step 1: "If the `dispatching-parallel-agents` skill is available, use it to run the three tasks simultaneously. Otherwise, run them sequentially." This makes the command resilient across installations without the superpowers plugin.
  Vision-advancement-tier: C
  Vision-advancement: Graceful skill-availability fallback reduces hard failures in partially-configured environments, improving portability of the discipline layer across tool installations.
  Promotion-eligible: yes
  Related:

---

F7: refresh-agents-md.md references `optimize-agents-md` skill principles inline rather than invoking the skill
  File: src/user/.claude/commands/refresh-agents-md.md:94-102, 120-130
  Category: command
  Severity: Medium
  Tier: 2
  Issue: Steps 3b and 3d both reference "Apply the `optimize-agents-md` skill principles" and then immediately enumerate those principles inline in the command body (eliminate ruthlessly, transform weak to strong, progressive disclosure, <200 lines, validation checklist). This is a partial lean-delegation failure: the command names the skill but then re-implements a condensed version of it inline rather than invoking it via the Skill tool. This creates two maintenance surfaces — the skill's methodology can evolve while the command's inline summary remains stale, producing contradictory guidance over time.
  Recommendation: Replace the inline principle enumeration in Steps 3b and 3d with a direct Skill invocation instruction: "Invoke the `optimize-agents-md` skill for this file." The skill carries its own validation checklist; the command does not need to repeat it. The only command-level guidance needed is "process files in hierarchy order" (already in Step 3) and "present diff before writing" (Step 3e), which are control-flow concerns, not methodology.
  Vision-advancement-tier: A
  Vision-advancement: Routing through the canonical skill rather than re-implementing its methodology inline advances commitment 4 (guardrail every completion claim with mechanical evidence) — the skill's validation checklist becomes the authoritative gate rather than an evolving inline paraphrase.
  Promotion-eligible: yes
  Related: F1, F2

---

F8: optimize-my-agent.md title mismatches its functional scope
  File: src/user/.claude/commands/optimize-my-agent.md:1
  Category: command
  Severity: Low
  Tier: 1
  Issue: The command file is named `optimize-my-agent.md` and installs as `/optimize-my-agent`. The `# Optimize Agent.md` heading at line 1 uses "Agent.md" (with a period and capital M) — matching the pattern of AGENTS.md configuration files. However, the body begins "Your task is to analyze and optimize the agent.md file at: $ARGUMENTS" and the quality rubric (Commands, Testing, Project Structure, Code Style, Git Workflow, Boundaries — see F5) treats the target as a software project's configuration, not an agent persona definition. The title and scope are inconsistent with each other and with the existing `optimize-agents-md` skill, creating genuine user confusion about which tool to reach for.
  Recommendation: Decide the actual scope of this command, then align the title, heading, and body accordingly. If the command targets agent persona files (the `agents/*.md` files with frontmatter `name`/`description`/`model`/`color`), rename the heading to "Optimize Agent Definition" and align the rubric (see F5). If it targets AGENTS.md configuration files, rename it to avoid collision with `optimize-agents-md`.
  Vision-advancement-tier: C
  Vision-advancement: Removing naming ambiguity ensures agents select the correct optimization tool without trial and error, reducing friction in the harness-refinement loop.
  Promotion-eligible: no
  Related: F2, F5

---

## Summary table

| ID | File | Severity | Tier | Title |
|----|------|----------|------|-------|
| F1 | optimize-my-skill.md | High | 2 | 233-line command body — lean-delegation violation |
| F2 | optimize-my-agent.md | High | 2 | 107-line command body embeds full methodology without a skill |
| F3 | optimize-my-skill.md | Medium | 1 | "5,000 words" threshold conflicts with SKILLS_PRIMER "500 lines" |
| F4 | optimize-my-skill.md | Medium | 2 | Empty-$ARGUMENTS default path ambiguous for user-scoped install |
| F5 | optimize-my-agent.md | Medium | 2 | Quality rubric axes diverge from AGENTS_PRIMER schema |
| F6 | refresh-agents-md.md | Low | 2 | Hard-coded skill dependency with no availability fallback |
| F7 | refresh-agents-md.md | Medium | 2 | Skill principles re-implemented inline rather than delegated |
| F8 | optimize-my-agent.md | Low | 1 | Title/heading "Agent.md" mismatches functional scope |

**8 findings total.** 2 High / 4 Medium / 2 Low. 2 Tier 1 (mechanical) / 6 Tier 2 (judgment, deferred).
