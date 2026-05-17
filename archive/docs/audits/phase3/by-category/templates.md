# Phase 3 By-Category: Templates
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the templates category (AGENTS.md.template, CLAUDE.md.template, INSTRUCTIONS.md.template, settings.json.template, extension stubs, and the live root AGENTS.md).

---

F1: Codex and Gemini templates omit all rules (delivery, delegation, git safety, worktrees)
  File: src/user/.codex/AGENTS.md.template:1-9, src/user/.gemini/GEMINI.md.template:1-9
  Category: template
  Severity: High
  Tier: 2
  Issue: Claude and OpenCode AGENTS.md.template files include `<!-- DYNAMIC-INCLUDE-RULES -->` for five core behavioral rules. Codex and Gemini equivalents do not include this marker. As a result, Codex and Gemini agents receive zero guidance on: merge authorization requirements, worktree isolation, git commit heredoc avoidance, delivery sequencing, and subagent coordination hygiene. Phase 2 constraint-aware and quality-gate reviewers both AGREE and reinforce: this removes the completion-gate and delivery implementation path for those tools entirely.
  Recommendation: Add `<!-- DYNAMIC-INCLUDE-RULES: delegation,delivery,git-commits,subagents,worktrees -->` to both Codex and Gemini AGENTS.md.template files, immediately after the INSTRUCTIONS.md.template include. Before doing so, audit each rule file for Claude-specific constructs (e.g., codex-routing.md references CLAUDE_PLUGIN_ROOT) and either omit those rules from non-Claude includes or create tool-neutral variants. The delivery.md and git-commits.md rules are tool-neutral and should be included immediately.
  Vision-advancement-tier: A
  Vision-advancement: Delivery and delegation rules are the primary enforcement mechanism for commitments #4 and #1; Codex and Gemini agents without these rules skip the completion gate and delivery sequencing entirely, directly regressing autonomous overnight execution quality.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE × 2 (constraint-aware:F1, quality-gate:OOS1/D29).
  Sources: phase1/templates.md:F1, phase2/constraint-aware-execution.md:F1, phase2/quality-gate-and-delivery.md:OOS1

---

F2: CLAUDE-EXTENSIONS.md.template is an empty stub — meaningless heading in installed file
  File: src/user/.claude/CLAUDE-EXTENSIONS.md.template:1-1
  Category: template
  Severity: Medium
  Tier: 2
  Issue: Contains only the heading `# Claude-Specific Extensions` with no body. The installed ~/.claude/AGENTS.md ends with a bare heading and no content. AGENTS.md description correctly documents this as a stub, but the stub still processes and installs, contributing a meaningless heading to the live instruction file.
  Recommendation: Either (a) remove the DYNAMIC-INCLUDE reference from Claude AGENTS.md.template and delete the stub file, or (b) populate with at minimum a one-line note: "Claude-specific extensions are in the `rules/` directory: delegation.md, completion-gate.md, delivery.md, git-commits.md, subagents.md, worktrees.md, codex-routing.md." Option (b) makes the heading informative rather than orphaned.
  Vision-advancement-tier: C
  Vision-advancement: Removes a noise element from the primary Claude instruction entry point, keeping the agent's context window free of weight without serving execution.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F2

---

F3: CODEX-EXTENSIONS.md.template and GEMINI-EXTENSIONS.md.template are empty stubs
  File: src/user/.codex/CODEX-EXTENSIONS.md.template:1-1, src/user/.gemini/GEMINI-EXTENSIONS.md.template:1-1
  Category: template
  Severity: Medium
  Tier: 2
  Issue: Both files contain only a bare heading with no body. Unlike the Claude stub (which has the rules/ system as documented rationale), these have no documented rationale and no analog extension mechanism. They install a meaningless heading into Codex and Gemini instruction files.
  Recommendation: Either populate the stubs with actual tool-specific guidance (Codex invocation differences, Gemini tool naming conventions, tool-specific sandbox behaviors) or remove the DYNAMIC-INCLUDE reference and delete the stub files. If they are placeholder extension points for future content, add a one-line comment inside each explaining that intent.
  Vision-advancement-tier: B
  Vision-advancement: Empty stubs for Codex and Gemini are a gap symptom in the vision-85-5-10 cross-tool coverage — cleaning them up or populating them moves toward making the operating ratio achievable on any major AI coding assistant.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F3

---

F4: AGENTS.md vision section contains a bd command — beads hygiene violation (recommendation-only)
  File: AGENTS.md:27
  Category: template
  Severity: Critical
  Tier: 2
  Issue: Line 27 reads: `Search current work with: \`bd list --label vision-85-5-10\`.` This is inside the Vision & Mission section (out of scope for Tier 1/2 enforcement per audit constraints) but AGENTS.md is read by ALL agents in this repo including agents without the beads plugin. `bd` command will fail silently or produce a confusing error for non-beads agents. The Implications subsection also reads "File beads for harness friction you discover" — beads terminology in shared project-level instructions.
  Recommendation: Vision section — recommendation only per audit constraints. If the vision section is revised in a future cycle, replace the `bd list` example with a label reference (`label: vision-85-5-10`) and make "File beads for harness friction" conditional on plugin availability, or move it to the beads plugin's rules.
  Vision-advancement-tier: A
  Vision-advancement: Keeping beads commands out of shared project-level instructions directly supports commitment #5 (persist context) — all agents can read the project AGENTS.md without encountering commands that fail silently.
  Promotion-eligible: yes
  Resolution: ACCEPTED (recommendation-only per audit constraints)
  Rationale: Phase 2 escalation reviewer reinforces via OOS1; Phase 1 finding stands as Tier 2 recommendation-only.
  Sources: phase1/templates.md:F4

---

F5: INSTRUCTIONS.md.template — skill names are shared, not Claude-only; genericize phrasing only
  File: src/user/.agents/INSTRUCTIONS.md.template:41,42
  Category: template
  Severity: High
  Tier: 2
  Issue: Phase 1 recommends replacing `self-improving-agent` and `verify-checklist` skill names with generic prose. Phase 2 constraint-aware reviewer gives PARTIAL (D6): these ARE shared skills in `src/user/.agents/skills/` — not Claude-only. Removing their names would weaken always-loaded triggers that have portable implementations. However "Plan mode" IS Claude-specific.
  Recommendation: Keep the named skill triggers `self-improving-agent` and `verify-checklist`. Replace "Plan mode" (Claude-specific feature name) with "planning phase" or "structured planning". Add "when available" softener to skills that genuinely depend on tool support. This is the D6 synthesis.
  Vision-advancement-tier: A
  Vision-advancement: Making the shared template truly tool-agnostic advances the mission to make the 85/5/10 ratio achievable on any major AI coding assistant; keeping named shared-skill triggers preserves portable implementation of correction capture and completion audit.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D6)
  Rationale: Phase 2 PARTIAL — genericize Claude-specific phrasing only; keep shared skill names.
  Sources: phase1/templates.md:F5, phase2/constraint-aware-execution.md:F2

---

F6: OpenCode AGENTS.md.template missing subtitle
  File: src/user/.opencode/AGENTS.md.template:1-8
  Category: template
  Severity: Low
  Tier: 1
  Issue: Claude and Codex AGENTS.md.template files begin with `# AGENTS.md` followed by `User-scoped instructions for all projects.` as a subtitle. OpenCode template begins with only `# AGENTS.md` and immediately proceeds to DYNAMIC-INCLUDE markers. Minor structural inconsistency.
  Recommendation: Add the subtitle line `User-scoped instructions for all projects.` between the heading and the first DYNAMIC-INCLUDE marker.
  Vision-advancement-tier: C
  Vision-advancement: Minor cross-tool template consistency improvement.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F6

---

F7: settings.json.template hook path hardcoded — not portable
  File: src/user/.claude/settings.json.template:39
  Category: template
  Severity: High
  Tier: 2
  Issue: The PostToolUse hook command is `"~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh"`. If a user installs skills to a non-standard location, or if wait-for-pr-comments is not installed, the hook silently fails on every Bash tool use. No guard for script existence, no fallback, no documentation of the prerequisite.
  Recommendation: Add a comment block documenting the prerequisite. Wrap the hook command in a guard: `"[ -f ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh ] && ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh || true"` so missing scripts don't generate errors. Alternatively, reference the script via `$CLAUDE_SKILLS_ROOT` if the harness exposes that variable.
  Vision-advancement-tier: A
  Vision-advancement: The wait-for-pr-comments hook is part of the PR review automation pipeline (commitment #3); a silently-failing hook disables that pipeline without any signal to the operator.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F7

---

F8: settings.json.template permissions allow list is empty — no baseline tool permissions
  File: src/user/.claude/settings.json.template:13-14
  Category: template
  Severity: Medium
  Tier: 2
  Issue: `permissions.allow` array is empty (`[]`). For autonomous operation (overnight runs, run-queue), repeated permission prompts at runtime for universally-safe read-only operations directly undermine the operating model. The deny list is well-populated with appropriate restrictions.
  Recommendation: Populate the allow list with a baseline set of safe, universally-applicable operations: `Bash(git status)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Read(*)`, `Glob(*)`, `Grep(*)`. Document in a comment that project-specific additions belong in `<project>/.claude/settings.json`, not in the user-level template.
  Vision-advancement-tier: A
  Vision-advancement: An empty allow list forces manual permission approval for every read operation, directly breaking the overnight autonomous execution model that is central to the 85/5/10 target ratio.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F8

---

F9: AGENTS.md agent frontmatter schema incomplete — missing fields documented in AGENTS_PRIMER
  File: AGENTS.md:86-93
  Category: template
  Severity: Medium
  Tier: 1
  Issue: "File Formats" section documents agent frontmatter as having only `name`, `description`, `model`, and `color`. AGENTS_PRIMER.md documents additional valid fields: `tools`, `disallowedTools`, `skills`, `effort`, `memory`. Developer reading AGENTS.md to author a new agent would not know these fields exist.
  Recommendation: Expand the agent frontmatter example to include at minimum `tools`/`disallowedTools`, `skills`, `effort`, `memory` with brief comments. Match the format of AGENTS_PRIMER.md's schema table.
  Vision-advancement-tier: C
  Vision-advancement: Accurate frontmatter documentation reduces the likelihood of agents being authored with missing capability declarations.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F9

---

F10: AGENTS.md skill frontmatter schema incomplete — missing allowed-tools and model fields
  File: AGENTS.md:98-101
  Category: template
  Severity: Low
  Tier: 1
  Issue: Skill frontmatter schema in AGENTS.md shows only `name` and `description`. SKILLS_PRIMER.md documents additional valid fields: `license`, `allowed-tools`, `compatibility`, `metadata`, `model`, `effort`.
  Recommendation: Expand the skill frontmatter example to note that additional optional fields exist (model, effort, allowed-tools) and point to docs/primers/SKILLS_PRIMER.md for the full schema.
  Vision-advancement-tier: C
  Vision-advancement: Accurate schema documentation prevents authors from omitting model/effort directives that affect dispatch quality.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F10

---

F11: AGENTS.md graphify section — `graphify update .` unsafe for subagents
  File: AGENTS.md:173-177
  Category: template
  Severity: Medium
  Tier: 2
  Issue: Instruction "After modifying code files in this session, run `graphify update .`" is appropriate for the main orchestrating agent but dangerous for subagents — running from a worktree context could update the graph with partial changes or corrupt graph state. Phase 2 multi-agent reviewer OOS1 reinforces this concern for multi-agent runs.
  Recommendation: Add qualifier: "After modifying code files in this session (orchestrator only — subagents must not run this), run `graphify update .`..." Alternatively, add a condition that checks whether the session is the primary orchestrator.
  Vision-advancement-tier: A
  Vision-advancement: Subagent coordination correctness is load-bearing for overnight autonomous execution (commitment #5); a subagent corrupting the knowledge graph mid-run would break the next orchestrator session's architectural queries.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 OOS1 (multi-agent-dispatch) reinforces Phase 1 finding; aggregator strengthens via D27.
  Sources: phase1/templates.md:F11, phase2/multi-agent-dispatch.md:OOS1

---

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

F13: INSTRUCTIONS.md.template database constraint — genericize wording, keep in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:24
  Category: template
  Severity: Critical
  Tier: 2
  Issue: "Never copy Dolt or SQLite databases while WAL is locked" is beads-plugin-specific terminology in a shared template. Phase 1 recommends moving it to beads-only rules. Phase 2 constraint-aware reviewer gives PARTIAL (D4): Codex and Gemini have no beads rules today — moving the warning would create a database-safety blind spot for those tools.
  Recommendation: Keep the database-safety constraint in INSTRUCTIONS.md.template but reword to lead with the generic principle: "Never copy live databases (such as Dolt or SQLite with WAL enabled) from worktree directories if the database lives in the main tree." The concrete examples (`Dolt or SQLite`) make the abstract rule legible and remain as illustration, not as the primary framing. The beads plugin then adds its Dolt-specific reinforcement as an additive rule per D4.
  Vision-advancement-tier: A
  Vision-advancement: Removes beads-specific database terminology as the framing while preserving the database-safety constraint in the one layer all tools currently load — exactly where overnight autonomous runs need it.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D4)
  Rationale: Phase 2 PARTIAL — reword for portability but don't remove; aggregator accepts synthesis.
  Sources: phase1/templates.md:F13, phase2/constraint-aware-execution.md:F3

---

F14: INSTRUCTIONS.md.template — references context7 by name in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:18
  Category: template
  Severity: Critical
  Tier: 1
  Issue: "look up docs via context7 before using it" — `context7` is a specific MCP plugin available in Claude Code but not necessarily in Codex/Gemini/OpenCode. Non-Claude agents following this instruction will attempt to use a tool that doesn't exist.
  Recommendation: Replace "look up docs via context7 before using it" with "look up current docs via available documentation tools (e.g., context7 MCP if available, or web search) before using it." (Promoted to Tier 1 per D22.)
  Vision-advancement-tier: A
  Vision-advancement: Removing Claude-specific tool references from the shared constraint template directly advances the mission of making the discipline layer portable to any major AI coding assistant.
  Resolution: ACCEPTED (promoted to Tier 1 per D22)
  Rationale: Phase 2 did not specifically address; D22 tier1-promotion confirmed with Before/After snippet.
  Sources: phase1/templates.md:F14

---

F15: AGENTS.md Session Completion section — bd dolt push unguarded in mandatory workflow
  File: AGENTS.md:154
  Category: template
  Severity: Critical
  Tier: 2
  Issue: The Session Completion section contains `bd dolt push` as a mandatory step. The entire block is inside `<!-- BEGIN BEADS INTEGRATION -->` markers, but a non-beads agent following the "MANDATORY WORKFLOW" will fail at step 4 when it hits `bd dolt push` with no conditional guard. Phase 2 constraint-aware reviewer OOS1 reinforces this concern.
  Recommendation: Add a conditional note inside the Session Completion block: "(beads only — skip if beads not installed)" next to the `bd dolt push` line. This is a minimal change that preserves the block's structure while preventing agent confusion.
  Vision-advancement-tier: A
  Vision-advancement: Session completion integrity is a prerequisite for reliable overnight autonomous runs (commitment #5); a non-beads agent failing silently at `bd dolt push` will not push code, stranding work locally.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 OOS1 (constraint-aware) reinforces Phase 1 finding; aggregator strengthens via D28.
  Sources: phase1/templates.md:F15, phase2/constraint-aware-execution.md:OOS1
