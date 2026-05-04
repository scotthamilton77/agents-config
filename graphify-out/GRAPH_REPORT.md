# Graph Report - /Users/scott/src/projects/agents-config  (2026-05-03)

## Corpus Check
- 63 files · ~66,654 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 243 nodes · 327 edges · 15 communities detected
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 38 edges (avg confidence: 0.85)
- Token cost: 312,162 input · 78,040 output

## Community Hubs (Navigation)
- [[_COMMUNITY_PR Review Automation|PR Review Automation]]
- [[_COMMUNITY_RALF Multi-Agent Refinement|RALF Multi-Agent Refinement]]
- [[_COMMUNITY_Project Config & Beads Workflow|Project Config & Beads Workflow]]
- [[_COMMUNITY_AGENTS.md Curation Commands|AGENTS.md Curation Commands]]
- [[_COMMUNITY_Unit Testing & Mocks|Unit Testing & Mocks]]
- [[_COMMUNITY_Multi-Tool Installer Internals|Multi-Tool Installer Internals]]
- [[_COMMUNITY_PRMerge Formulas & Guards|PR/Merge Formulas & Guards]]
- [[_COMMUNITY_Beads Lifecycle Invariants|Beads Lifecycle Invariants]]
- [[_COMMUNITY_RALF Foreign-Agent Integration|RALF Foreign-Agent Integration]]
- [[_COMMUNITY_Tool-Specific AGENTS.md Templates|Tool-Specific AGENTS.md Templates]]
- [[_COMMUNITY_Shared Persona Templates|Shared Persona Templates]]
- [[_COMMUNITY_Install ↔ Shared AGENTS|Install ↔ Shared AGENTS]]
- [[_COMMUNITY_Verification Before Completion|Verification Before Completion]]
- [[_COMMUNITY_Codex Source README|Codex Source README]]
- [[_COMMUNITY_Gemini Source README|Gemini Source README]]

## God Nodes (most connected - your core abstractions)
1. `ralf-it skill` - 19 edges
2. `wait-for-pr-comments skill` - 17 edges
3. `AGENTS.md (project root)` - 15 edges
4. `scripts/install.sh` - 14 edges
5. `implement-bead skill` - 14 edges
6. `Claude source README` - 12 edges
7. `beads plugin (src/plugins/beads/)` - 11 edges
8. `wait-for-pr-comments skill (Skill A)` - 11 edges
9. `start-bead skill` - 10 edges
10. `completion-gate rule` - 10 edges

## Surprising Connections (you probably didn't know these)
- `implement-bead skill` --semantically_similar_to--> `ralf-implement skill`  [INFERRED] [semantically similar]
  src/plugins/beads/.agents/skills/implement-bead/SKILL.md → docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md
- `beads plugin (src/plugins/beads/)` --references--> `bead-verifier agent (haiku, mechanical evidence)`  [INFERRED]
  AGENTS.md → src/plugins/beads/.agents/agents/bead-verifier.md
- `beads plugin (src/plugins/beads/)` --references--> `merge-and-cleanup formula`  [INFERRED]
  AGENTS.md → src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml
- `CLAUDE.md (project root)` --references--> `AGENTS.md (project root)`  [EXTRACTED]
  CLAUDE.md → AGENTS.md
- `AGENTS.md (project root)` --references--> `scripts/install.sh`  [EXTRACTED]
  AGENTS.md → scripts/install.sh

## Hyperedges (group relationships)
- **Beads Skill Pipeline (create -> start -> implement -> run-queue)** — concept_skill_create_bead, concept_skill_start_bead, concept_skill_implement_bead, concept_skill_run_queue [EXTRACTED 1.00]
- **Beads Formulas (workflow templates)** — concept_formula_brainstorm_bead, concept_formula_implement_feature, concept_formula_fix_bug, concept_formula_merge_and_cleanup [EXTRACTED 1.00]
- **PR Review Lifecycle (Skill A -> Inventory -> Skill B)** — concept_skill_wait_for_pr_comments, concept_handoff_inventory, concept_skill_reply_and_resolve_pr_threads, concept_per_comment_subagent [EXTRACTED 1.00]
- **RALF-IT Iteration Pipeline (implementer + foreign-eyes + fresh-eyes)** — ralf_implementer_prompt, ralf_foreign_eyes_prompt, ralf_fresh_eyes_prompt, ralf_foreign_agent_prompt, skill_ralf_it [EXTRACTED 1.00]
- **PR Review Response Pipeline (poll/classify/fix/reply/resolve)** — skill_wait_for_pr_comments, skill_reply_and_resolve_pr_threads, validate_inventory_sh, write_inventory_sh, pr_inventory_schema [EXTRACTED 1.00]
- **Bead Lifecycle Skill Pipeline** — skill_create_bead, skill_start_bead, skill_implement_bead, skill_run_queue, formula_brainstorm_bead, formula_implement_feature, formula_fix_bug, formula_merge_and_cleanup [EXTRACTED 1.00]
- **Completion Gate Pipeline (review, simplify, verify)** — agent_quality_reviewer, skill_simplify, skill_verify_checklist, rule_completion_gate [EXTRACTED 1.00]
- **Delivery Pipeline (worktree, finish-branch, wait-for-PR, reply-resolve)** — skill_using_git_worktrees, skill_finishing_a_development_branch, skill_wait_for_pr_comments, skill_reply_and_resolve_pr_threads, rule_delivery [EXTRACTED 1.00]
- **Cross-Tool AGENTS.md Template Family (Claude/Codex/Gemini)** — claude_agents_md_template, codex_agents_md_template, gemini_agents_md_template, shared_instructions_md [EXTRACTED 1.00]

## Communities (16 total, 4 thin omitted)

### Community 0 - "PR Review Automation"
Cohesion: 0.06
Nodes (36): bead-verifier agent (haiku, mechanical evidence), already_addressed SHA-discovery procedure, FIX/SKIP/ESCALATE Classification, refresh-agents-md command, Completion Gate (review/simplify/verify), Concurrency Recovery Branch (--resume mode), Default-on Skill A → Skill B chain, detect-pr-push.sh PostToolUse hook (+28 more)

### Community 1 - "RALF Multi-Agent Refinement"
Cohesion: 0.07
Nodes (35): quality-reviewer agent, tech-lead agent, Bugfix Three Threads (git/test/dataflow), codex-companion.mjs, Claude Code Codex plugin, Completion Gate (review/simplify/verify), Gemini CLI, Iron Law: No Fix Without Parallel Evidence (+27 more)

### Community 2 - "Project Config & Beads Workflow"
Cohesion: 0.09
Nodes (32): AGENTS.md (project root), Project Purpose: multi-tool agents-config, Repository Structure (src/user, src/plugins), Session Completion Workflow, CLAUDE.md (project root), bd command (beads CLI), beads plugin (src/plugins/beads/), Claude-specific content (src/user/.claude/) (+24 more)

### Community 3 - "AGENTS.md Curation Commands"
Cohesion: 0.1
Nodes (26): Claude source README, /optimize-my-agent command, /optimize-my-skill command, /refresh-agents-md command, Action Categories (Automatic vs Authorized), Template Install Model (.template suffix), PR Comments Audit (top-level + inline), Progressive Disclosure (skill levels) (+18 more)

### Community 4 - "Unit Testing & Mocks"
Cohesion: 0.1
Nodes (24): Anti-Pattern: Incomplete Mocks, Anti-Pattern: Testing Mock Behavior, Anti-Pattern: Mocking Without Understanding, Anti-Pattern: Test-Only Production Methods, Iron Laws of Unit Testing, Mocks Are A Smell, Refactoring For Testability, Test Refusal Criteria (+16 more)

### Community 5 - "Multi-Tool Installer Internals"
Cohesion: 0.15
Nodes (17): classify_file() function, Collision resolution (rules append, commands fatal, settings union-merge), scripts/install.sh, jq union merge for settings.json, Multi-Tool Install Architecture, Plugin auto-detection (sentinel: bd on PATH or ~/.beads/), plugin_enabled() helper, --plugins= flag (+9 more)

### Community 6 - "PR/Merge Formulas & Guards"
Cohesion: 0.15
Nodes (17): detect-pr-push.sh hook, fix-bug formula, implement-feature formula, merge-and-cleanup formula, check-merge-eligibility.sh, Mode-aware ESCALATE (interactive vs autonomous), Per-Comment Subagent Contract, Beads-aware Delivery Addendum (+9 more)

### Community 7 - "Beads Lifecycle Invariants"
Cohesion: 0.19
Nodes (14): bd CLI command, Bead Lifecycle and Labels, I1 Claim Walk (walk up on start), I2 Close Walk (walk up on close), I3 Discovered-Work Placement (sibling test), brainstorm-bead formula, Molecule to Bead Linkage Convention (for-bead label), Parent-Chain Invariants (+6 more)

### Community 8 - "RALF Foreign-Agent Integration"
Cohesion: 0.21
Nodes (13): Codex CLI (codex exec -s read-only), foreign-agent-prompt.md template, foreign-eyes-prompt.md template, Foreign-Eyes Subagent, Gemini CLI (gemini -p approval-mode plan), Graceful degradation to pure fresh-eyes, ralf:cycles=N bead label, .ralf/{session_id}/ artifact directory (+5 more)

### Community 9 - "Tool-Specific AGENTS.md Templates"
Cohesion: 0.36
Nodes (10): Claude AGENTS.md template, CLAUDE-EXTENSIONS.md template, Claude CLAUDE.md template, Codex AGENTS.md template, CODEX-EXTENSIONS.md template, Collision Rules (unique vs append vs union-merge), Gemini AGENTS.md template, GEMINI-EXTENSIONS.md template (+2 more)

### Community 11 - "Shared Persona Templates"
Cohesion: 0.5
Nodes (4): AGENT-PERSONA.md.template, INSTRUCTIONS.md.template, Shared README (src/user/.agents), USER-PERSONA.md.template

## Knowledge Gaps
- **114 isolated node(s):** `CLAUDE.md (project root)`, `Project Purpose: multi-tool agents-config`, `Repository Structure (src/user, src/plugins)`, `Session Completion Workflow`, `Shared content (src/user/.agents/)` (+109 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Claude source README` connect `AGENTS.md Curation Commands` to `Tool-Specific AGENTS.md Templates`, `Unit Testing & Mocks`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `ralf-it skill` connect `RALF Multi-Agent Refinement` to `Unit Testing & Mocks`, `PR/Merge Formulas & Guards`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `delegation rule` connect `Unit Testing & Mocks` to `RALF Multi-Agent Refinement`, `AGENTS.md Curation Commands`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `implement-bead skill` (e.g. with `beads plugin (src/plugins/beads/)` and `ralf-implement skill`) actually correct?**
  _`implement-bead skill` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `CLAUDE.md (project root)`, `Project Purpose: multi-tool agents-config`, `Repository Structure (src/user, src/plugins)` to the rest of the system?**
  _114 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `PR Review Automation` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Should `RALF Multi-Agent Refinement` be split into smaller, more focused modules?**
  _Cohesion score 0.07 - nodes in this community are weakly interconnected._