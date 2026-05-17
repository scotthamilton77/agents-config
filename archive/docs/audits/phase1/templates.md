# Phase 1 Audit: Templates
Auditor: audit-templates subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 13 template and configuration files
Note: AGENTS.md vision section is recommendation-only per audit constraints

---

## Drift Check

Both drift checks passed (empty output). All in-scope files match the audit SHA exactly.

---

## Summary

13 files audited. 15 findings across 5 Critical, 4 High, 4 Medium, and 2 Low severity items. No files were modified.

The dominant structural problem is **asymmetric tool coverage**: Codex and Gemini templates receive the shared INSTRUCTIONS.md.template but none of the rules that govern delivery, git safety, and delegation — rules that Claude and OpenCode both get. This silently degrades autonomous behavior for those tools. A secondary problem is **empty extension stubs** (CODEX-EXTENSIONS.md.template, GEMINI-EXTENSIONS.md.template, CLAUDE-EXTENSIONS.md.template) that consume file slots and install-time processing for no delivered guidance. The AGENTS.md vision section contains a `bd list` command that is beads-specific and thus violates bead-concept hygiene for a project-level AGENTS.md visible to all agents including non-beads ones.

---

## Findings

---

F1: Codex and Gemini templates omit all rules (delivery, delegation, git safety, worktrees)
  File: src/user/.codex/AGENTS.md.template:1-9, src/user/.gemini/GEMINI.md.template:1-9
  Category: template
  Severity: High
  Tier: 2
  Issue: The Claude and OpenCode AGENTS.md.template files include `<!-- DYNAMIC-INCLUDE-RULES: delegation,delivery,git-commits,subagents,worktrees -->`, which inlines the five core behavioral rules at install time. The Codex and Gemini equivalents do not include this marker. As a result, Codex and Gemini agents operating under their installed AGENTS.md receive zero guidance on: when authorization is required before merging, how to isolate work in worktrees, heredoc avoidance in git commits, delivery sequencing (worktree → branch → PR), and subagent coordination hygiene. The shared INSTRUCTIONS.md.template covers laws and constraints but explicitly states "Tool-specific extensions define which skills, agents, or commands implement each step" — without the rules, those steps have no implementation.
  Recommendation: Add `<!-- DYNAMIC-INCLUDE-RULES: delegation,delivery,git-commits,subagents,worktrees -->` to both Codex and Gemini AGENTS.md.template files, immediately after the INSTRUCTIONS.md.template include. Before doing so, audit each rule file for Claude-specific constructs (e.g., `codex-routing.md` references `CLAUDE_PLUGIN_ROOT`) and either omit those rules from non-Claude includes or create tool-neutral variants. The delivery.md and git-commits.md rules are tool-neutral and should be included for all tools immediately. The codex-routing.md rule should remain Claude-only.
  Vision-advancement-tier: A
  Vision-advancement: The delivery and delegation rules are the primary enforcement mechanism for commitment #4 (guardrail every completion claim with mechanical evidence) and commitment #1 (frontload judgment); Codex and Gemini agents without these rules will skip the completion gate and delivery sequencing, directly regressing autonomous overnight execution quality.
  Promotion-eligible: yes

---

F2: CLAUDE-EXTENSIONS.md.template is an empty stub with no content
  File: src/user/.claude/CLAUDE-EXTENSIONS.md.template:1-1
  Category: template
  Severity: Medium
  Tier: 2
  Issue: The file contains only the heading `# Claude-Specific Extensions` with no body. The AGENTS.md.template for Claude includes this file via `<!-- DYNAMIC-INCLUDE: src/user/.claude/CLAUDE-EXTENSIONS.md.template -->`, meaning the installed ~/.claude/AGENTS.md will end with a bare heading and no content. The AGENTS.md description in root AGENTS.md correctly documents this as a stub ("content moved to rules/"), but the stub is still processed and installed, contributing a meaningless heading to the live instruction file. From the agent's perspective, this heading with no content is pure noise.
  Recommendation: Either (a) remove the DYNAMIC-INCLUDE reference from CLAUDE-EXTENSIONS.md.template from `src/user/.claude/AGENTS.md.template` and delete the stub file, or (b) populate the stub with at minimum a one-line note explaining that Claude-specific extensions are in the `rules/` directory with the filenames listed, so the heading is informative rather than orphaned. Option (a) is cleaner unless the stub serves as a deliberate extension point for plugin appends.
  Vision-advancement-tier: C
  Vision-advancement: Removes a noise element from the primary Claude instruction entry point, keeping the agent's context window free of content that adds weight without serving execution or judgment.
  Promotion-eligible: no

---

F3: CODEX-EXTENSIONS.md.template and GEMINI-EXTENSIONS.md.template are empty stubs
  File: src/user/.codex/CODEX-EXTENSIONS.md.template:1-1, src/user/.gemini/GEMINI-EXTENSIONS.md.template:1-1
  Category: template
  Severity: Medium
  Tier: 2
  Issue: Both extension files contain only a bare heading (`# Codex-Specific Extensions`, `# Gemini-Specific Extensions`) with no body. These are included at the end of each tool's AGENTS.md.template via DYNAMIC-INCLUDE. Unlike the Claude stub (which at least has the `rules/` system as a documented rationale), these files have no documented rationale and no analog extension mechanism. They install a meaningless heading into the live instruction files for both tools.
  Recommendation: Either populate the stubs with actual tool-specific guidance (e.g., Codex invocation differences, Gemini tool naming conventions, tool-specific sandbox behaviors) or remove the DYNAMIC-INCLUDE reference and delete the stub files. If tool-specific differentiation is genuinely not needed yet, removing the stubs is cleaner than shipping empty headings. If they are placeholder extension points for future content, add a one-line comment inside each explaining that intent, so future authors know the pattern is intentional.
  Vision-advancement-tier: B
  Vision-advancement: Empty stubs for Codex and Gemini are a gap symptom in the vision-85-5-10 cross-tool coverage — cleaning them up or populating them moves toward the stated goal of making the operating ratio achievable on any major AI coding assistant.
  Promotion-eligible: no

---

F4: AGENTS.md vision section contains a bd command — beads hygiene violation
  File: AGENTS.md:27
  Category: template
  Severity: Critical
  Tier: 2
  Issue: Line 27 of the live AGENTS.md reads: `Search current work with: \`bd list --label vision-85-5-10\`.` This is inside the Vision & Mission section (which is out of scope for Tier 1/2 enforcement per audit constraints) but is noted here as a Tier 2 finding since AGENTS.md is the project-level instruction file read by ALL agents working in this repo — including agents that may not have the beads plugin installed. The `bd` command will fail silently or produce a confusing error for any such agent. The Implications sub-section further reads "File beads for harness friction you discover" — this is beads terminology in a project-level instruction visible to all tools. The audit constraint exempts vision-section findings from Tier 1 enforcement; this is flagged as a recommendation-only Tier 2 finding per those constraints.
  Recommendation: Vision section — recommendation only per audit constraints; do not apply as Tier 1. If the vision section is revised in a future cycle, replace the `bd list` example with a label reference (`label: vision-85-5-10`) and move the "File beads for harness friction" implication to a beads-specific note that is conditional on plugin availability, or move it to the beads plugin's rules.
  Vision-advancement-tier: A
  Vision-advancement: Keeping beads commands out of shared project-level instructions directly supports commitment #5 (persist context so work survives agent handoff) by ensuring all agents — including those without beads — can read the project AGENTS.md without encountering commands that fail silently.
  Promotion-eligible: yes

---

F5: INSTRUCTIONS.md.template references `self-improving-agent` and `verify-checklist` skills by name — tool-specific skill names in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:41, 42
  Category: template
  Severity: High
  Tier: 2
  Issue: The `<orchestration>` block in INSTRUCTIONS.md.template (line 41) says: "After ANY user correction → invoke `self-improving-agent` skill." Line 42 says: "Use `verify-checklist` skill for structured reporting." These are Claude Code skill names from the superpowers plugin (`obra/superpowers`). This shared template is installed to ALL detected tools — Codex, Gemini, OpenCode, and Claude. For tools without the superpowers plugin or without the Skill tool, these instructions are unactionable or actively misleading. Similarly, the `<orchestration>` block references "Plan mode" (line 37) — a Claude Code-specific feature not available in Codex/Gemini/OpenCode. The `<verification-checklist>` block (line 67) correctly uses the pattern "Tool-specific extensions define which skills, agents, or commands implement each step" but the orchestration block above it breaks that abstraction by naming concrete skills.
  Recommendation: In the shared INSTRUCTIONS.md.template, replace concrete skill names with generic process descriptions. For example: "After ANY user correction → record a written rule preventing the same mistake (tool-specific: use the self-improvement skill if available)" and "Verify with evidence before claiming complete (tool-specific: use the verify-checklist skill if available)." Move the concrete skill invocations to the Claude-specific CLAUDE-EXTENSIONS.md.template or rules/. Similarly, replace "Plan mode" with "planning phase" or "structured planning" to avoid Claude-specific jargon in shared content. The `<verification-checklist>` block's framing is correct and should be preserved as the abstraction pattern.
  Vision-advancement-tier: A
  Vision-advancement: Making the shared template truly tool-agnostic directly advances the mission to make the 85/5/10 operating ratio achievable on any major AI coding assistant (commitment: portable discipline layer); Claude-specific skill invocations in shared content mean Codex and Gemini agents silently drop load-bearing verification behaviors.
  Promotion-eligible: yes

---

F6: OpenCode AGENTS.md.template is missing the opening "User-scoped instructions for all projects." subtitle present in Claude and Codex templates
  File: src/user/.opencode/AGENTS.md.template:1-8
  Category: template
  Severity: Low
  Tier: 1
  Issue: The Claude and Codex AGENTS.md.template files begin with `# AGENTS.md` followed by `User-scoped instructions for all projects.` as a subtitle/paragraph. The OpenCode AGENTS.md.template begins with only `# AGENTS.md` and immediately proceeds to DYNAMIC-INCLUDE markers. This is a minor structural inconsistency across tool templates.
  Recommendation: Add the subtitle line `User-scoped instructions for all projects.` between the heading and the first DYNAMIC-INCLUDE marker in src/user/.opencode/AGENTS.md.template, matching the other tool templates.
  Vision-advancement-tier: C
  Vision-advancement: Minor cross-tool template consistency improvement; reduces cognitive friction when maintaining parallel template files.

---

F7: settings.json.template hook path is not portable — assumes ~/.claude/skills/ install location
  File: src/user/.claude/settings.json.template:39
  Category: template
  Severity: High
  Tier: 2
  Issue: The PostToolUse hook command (line 39) is: `"~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh"`. This path is hardcoded to the user's home directory and to a specific skill layout. If a user installs skills to a non-standard location, or if the wait-for-pr-comments skill is not installed (e.g., on a new machine where setup is incomplete), the hook will silently fail on every Bash tool use (the `timeout: 5` limits blast radius but every Bash call still incurs hook execution overhead). There is no guard for the script's existence, no fallback, and no documentation of the prerequisite.
  Recommendation: Add a comment block in the hooks section documenting that this hook requires the wait-for-pr-comments skill to be installed. Consider wrapping the hook command in a guard: `"[ -f ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh ] && ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh || true"` so missing scripts don't generate errors. Alternatively, reference the script via `$CLAUDE_SKILLS_ROOT` if the harness exposes that variable, making the path configurable.
  Vision-advancement-tier: A
  Vision-advancement: The wait-for-pr-comments hook is part of the PR review automation pipeline (commitment #3: substitute adversarial cross-model review); a silently-failing hook means that pipeline is disabled without any signal to the operator, directly degrading the automated review gate.
  Promotion-eligible: yes

---

F8: settings.json.template permissions allow list is empty — no baseline tool permissions granted
  File: src/user/.claude/settings.json.template:13-14
  Category: template
  Severity: Medium
  Tier: 2
  Issue: The `permissions.allow` array is empty (`[]`). While the deny list is well-populated with appropriate restrictions (shell destructive ops, sensitive file reads, system binary writes), the empty allow list means every project will start with no pre-approved operations. Agents must obtain permission at runtime for every Bash command, Read, Write, Edit, and MCP call. For autonomous operation (overnight runs, run-queue), repeated permission prompts directly undermine the stated operating model. Common read-only operations (Bash(git:*), Read, Glob, Grep) are universally safe and could be pre-approved in the template.
  Recommendation: Populate the allow list with a baseline set of safe, universally-applicable operations: `Bash(git status)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Read(*)`, `Glob(*)`, `Grep(*)`. These are read-only and do not create security risk. Document in a comment that project-specific additions belong in `<project>/.claude/settings.json`, not in the user-level template. This provides a sensible baseline that reduces friction for autonomous runs without opening security gaps.
  Vision-advancement-tier: A
  Vision-advancement: An empty allow list forces manual permission approval for every read operation, directly breaking the overnight autonomous execution model that is central to the 85/5/10 target ratio; a minimal baseline allow list is a prerequisite for unattended agent runs.
  Promotion-eligible: yes

---

F9: AGENTS.md "File Formats" section agent frontmatter schema is incomplete — missing fields documented elsewhere
  File: AGENTS.md:86-93
  Category: template
  Severity: Medium
  Tier: 1
  Issue: The "File Formats" section documents the agent frontmatter schema as having only `name`, `description`, `model`, and `color` fields. The AGENTS_PRIMER.md documents additional valid fields: `tools`, `disallowedTools`, `skills`, `effort`, `memory`. A developer reading AGENTS.md to author a new agent file would not know these fields exist. This creates a divergence between the project's own reference documentation and the primer that auditors/developers use.
  Recommendation: Expand the agent frontmatter example in AGENTS.md to include the additional fields (at minimum `tools`/`disallowedTools`, `skills`, `effort`, `memory`) with brief comments. Match the format of AGENTS_PRIMER.md's schema table. This is a direct copy-edit from docs/primers/AGENTS_PRIMER.md.
  Vision-advancement-tier: C
  Vision-advancement: Accurate frontmatter documentation reduces the likelihood of agents being authored with missing capability declarations, which degrades dispatch quality and model assignment; accurate schema documentation is a housekeeping improvement.

---

F10: AGENTS.md "File Formats" section skill frontmatter schema is incomplete — missing `allowed-tools` and `model` fields
  File: AGENTS.md:98-101
  Category: template
  Severity: Low
  Tier: 1
  Issue: The skill frontmatter schema in AGENTS.md shows only `name` and `description`. SKILLS_PRIMER.md documents additional valid fields: `license`, `allowed-tools`, `compatibility`, `metadata`, and the project-specific `model` and `effort` fields. The schema in AGENTS.md is sparse compared to what the primer documents.
  Recommendation: Expand the skill frontmatter example in AGENTS.md to at least note that additional optional fields exist (model, effort, allowed-tools) and point to docs/primers/SKILLS_PRIMER.md for the full schema. A two-line note is sufficient.
  Vision-advancement-tier: C
  Vision-advancement: Accurate schema documentation prevents authors from omitting model/effort directives that affect dispatch quality; minor housekeeping improvement.

---

F11: AGENTS.md graphify section instructs agents to run `graphify update .` — potential false affordance for subagents
  File: AGENTS.md:173-177
  Category: template
  Severity: Medium
  Tier: 2
  Issue: The graphify section (lines 173-177) contains the instruction: "After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)." This instruction is appropriate for the main orchestrating agent but is dangerous for subagents — running `graphify update .` from a worktree context could update the graph with partial changes, corrupt the graph state, or interfere with another agent's session. The instruction gives no guidance about whether subagents should run this command. Given that subagents are heavily used in this project (run-queue, quality-reviewer, etc.), this is a latent hazard.
  Recommendation: Add a qualifier to the graphify update instruction: "After modifying code files in this session (orchestrator only — subagents must not run this), run `graphify update .`..." Alternatively, restrict the instruction with a condition that checks whether the session is the primary orchestrator. At minimum, add a comment clarifying that this instruction applies to the main agent session, not to dispatched subagents.
  Vision-advancement-tier: A
  Vision-advancement: Subagent coordination correctness is load-bearing for overnight autonomous execution (commitment #5: persist context so work survives agent handoff); a subagent corrupting the knowledge graph mid-run would break the next orchestrator session's architectural queries.
  Promotion-eligible: yes

---

F12: OpenCode OPENCODE-EXTENSIONS.md.template references `@` includes that OpenCode does not support — then corrects itself
  File: src/user/.opencode/OPENCODE-EXTENSIONS.md.template:5-7
  Category: template
  Severity: Low
  Tier: 2
  Issue: Lines 5-7 state: "This file was dynamically flattened at install time. `@` references in the original source have been resolved and inlined." This comment is describing how the file was generated — but the template itself is the source file in version control. When someone reads this template in the repo, the comment implies that the file they're reading is already a flattened output, which is confusing for contributors. The template is not actually flattened at source; it is the source. The description is accurate for the installed file but misleading for the source template.
  Recommendation: Rewrite the header comment to distinguish source vs. installed context: "When installed, this file is dynamically flattened at install time — `@` references from source templates are resolved and inlined. If you are reading this in the source repository (`src/user/.opencode/`), this is the source template, not the installed output." This makes the file self-explanatory in both contexts.
  Vision-advancement-tier: C
  Vision-advancement: Clarity in source template documentation reduces developer confusion when maintaining the install pipeline; a minor housekeeping improvement.
  Promotion-eligible: no

---

F13: INSTRUCTIONS.md.template `<constraints>` block references Dolt and SQLite databases — beads-adjacent terminology in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:24
  Category: template
  Severity: Critical
  Tier: 2
  Issue: Line 24 of INSTRUCTIONS.md.template reads: "**Database safety**: Never copy Dolt or SQLite databases while WAL is locked; never run DB operations from worktree directories if the DB lives in the main tree." This constraint is directly tied to the beads plugin's use of Dolt as its backing store. The beads plugin stores issue data in a Dolt database; the constraint exists to prevent data corruption when multiple agents access the DB from different worktree paths. However, INSTRUCTIONS.md.template is a shared file installed to ALL detected tools — including Codex, Gemini, and OpenCode on machines that may not have beads installed at all. For users who do not use beads, this constraint is noise (Dolt-specific) and could be confusing. More importantly, for tools without beads, the constraint references a tool that doesn't exist, which adds dead weight.
  Recommendation: Move the Dolt-specific portion of this constraint to the beads plugin's rules (e.g., `src/plugins/beads/.claude/rules/`), which are only installed when beads is detected. The remaining generic portion — "never run DB operations from worktree directories if the DB lives in the main tree" — is tool-agnostic and should stay in INSTRUCTIONS.md.template. The constraint could be split: INSTRUCTIONS.md.template keeps the generic principle; beads/rules adds the Dolt-specific corollary.
  Vision-advancement-tier: A
  Vision-advancement: Removing beads-specific database terminology from the shared template aligns with commitment #5 (persist context so work survives agent handoff) — ensuring non-beads agents don't receive confusing constraints that degrade their ability to follow the instruction file accurately.
  Promotion-eligible: yes

---

F14: INSTRUCTIONS.md.template `<constraints>` block references `context7` — tool-specific dependency in shared content
  File: src/user/.agents/INSTRUCTIONS.md.template:18
  Category: template
  Severity: Critical
  Tier: 1
  Issue: Line 18 reads: "**Dependencies**: If a library version is newer than model training data, look up docs via context7 before using it." `context7` is a specific MCP plugin (`mcp__plugin_context7_context7`). It is available in Claude Code with the plugin installed, but Codex, Gemini, and OpenCode may not have context7 available. Instructing agents on non-Claude tools to "look up docs via context7" will cause confusion or failure when those agents attempt to use a tool that doesn't exist in their environment.
  Recommendation: Replace "look up docs via context7" with a tool-agnostic instruction: "look up current documentation via available documentation tools (e.g., context7 MCP if available, or web search)." This preserves the intent (don't use stale training data for new library versions) while not assuming a specific MCP plugin is present. The Claude-specific invocation pattern can remain in Claude extension files.
  Vision-advancement-tier: A
  Vision-advancement: Removing Claude-specific tool references from the shared constraint template directly advances the mission of making the discipline layer portable to any major AI coding assistant.

---

F15: AGENTS.md "Session Completion" section contains `bd dolt push` — beads command in project AGENTS.md visible to all agents
  File: AGENTS.md:154
  Category: template
  Severity: Critical
  Tier: 2
  Issue: The Session Completion section (inside the `<!-- BEGIN BEADS INTEGRATION -->` block, line 154) contains `bd dolt push` as a mandatory step in the push workflow. The entire Beads Integration block is clearly demarcated with begin/end markers and is appropriate as a beads-managed section. However, the block is in the root AGENTS.md which is read by ALL agents working in this repo — including any agent invoked on a machine without beads installed. A non-beads agent following the "MANDATORY WORKFLOW" will fail at step 4 when it hits `bd dolt push`. The command is inside a `<!-- BEGIN BEADS INTEGRATION -->` block which suggests it was added by the beads plugin, but there is no conditional guard or note that steps 4's `bd dolt push` is beads-specific.
  Recommendation: Add a brief conditional note inside the Session Completion block: "(beads only — skip if beads not installed)" next to the `bd dolt push` line. This is a minimal change that preserves the block's structure while preventing agent confusion. Alternatively, the beads integration block could be structured as a plugin-conditional addendum that agents are told applies only when beads is active. This finding is within the beads-managed block rather than the vision section, so it is fully in scope.
  Vision-advancement-tier: A
  Vision-advancement: Session completion integrity is a prerequisite for reliable overnight autonomous runs (commitment #5: persist context so work survives agent handoff); a non-beads agent failing silently at `bd dolt push` will not push code, stranding work locally — exactly the failure the Session Completion workflow is designed to prevent.
  Promotion-eligible: yes

---

## Finding Index

| ID | Title | Severity | Tier | File |
|----|-------|----------|------|------|
| F1 | Codex and Gemini templates omit all rules | High | 2 | src/user/.codex/AGENTS.md.template, src/user/.gemini/GEMINI.md.template |
| F2 | CLAUDE-EXTENSIONS.md.template is an empty stub | Medium | 2 | src/user/.claude/CLAUDE-EXTENSIONS.md.template |
| F3 | CODEX-EXTENSIONS.md.template and GEMINI-EXTENSIONS.md.template are empty stubs | Medium | 2 | src/user/.codex/CODEX-EXTENSIONS.md.template, src/user/.gemini/GEMINI-EXTENSIONS.md.template |
| F4 | AGENTS.md vision section contains a bd command | Critical | 2 | AGENTS.md:27 |
| F5 | INSTRUCTIONS.md.template references Claude-specific skill names | High | 2 | src/user/.agents/INSTRUCTIONS.md.template:41-42 |
| F6 | OpenCode AGENTS.md.template missing subtitle | Low | 1 | src/user/.opencode/AGENTS.md.template |
| F7 | settings.json.template hook path not portable | High | 2 | src/user/.claude/settings.json.template:39 |
| F8 | settings.json.template allow list is empty | Medium | 2 | src/user/.claude/settings.json.template:13-14 |
| F9 | AGENTS.md agent frontmatter schema incomplete | Medium | 1 | AGENTS.md:86-93 |
| F10 | AGENTS.md skill frontmatter schema incomplete | Low | 1 | AGENTS.md:98-101 |
| F11 | AGENTS.md graphify instruction unsafe for subagents | Medium | 2 | AGENTS.md:173-177 |
| F12 | OPENCODE-EXTENSIONS.md.template self-description confusing | Low | 2 | src/user/.opencode/OPENCODE-EXTENSIONS.md.template:5-7 |
| F13 | INSTRUCTIONS.md.template database constraint is beads-specific | Critical | 2 | src/user/.agents/INSTRUCTIONS.md.template:24 |
| F14 | INSTRUCTIONS.md.template references context7 by name | Critical | 1 | src/user/.agents/INSTRUCTIONS.md.template:18 |
| F15 | AGENTS.md Session Completion has unguarded bd dolt push | Critical | 2 | AGENTS.md:154 |

---

## Vision-Advancement Summary

| Tier A (names specific commitment + mechanism) | F1, F4, F5, F7, F8, F11, F13, F14, F15 |
| Tier B (ties to vision-85-5-10 gap) | F3 |
| Tier C (generic clarity/noise reduction) | F2, F6, F9, F10, F12 |

The highest-impact cluster is **F1 + F5 + F13 + F14** — these together mean that Codex and Gemini agents receive a shared template polluted with Claude-specific and beads-specific references while simultaneously missing the rules that implement the delivery and verification behaviors. Fixing these four findings would materially improve cross-tool autonomous operation.
