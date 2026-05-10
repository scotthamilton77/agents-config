# Phase 1 Audit: Agents
Auditor: audit-agents subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 7 agent definition files

---

F1: `superpowers:root-cause-tracing` is a deleted skill — broken cross-reference
  File: src/plugins/beads/.agents/agents/bead-implementor.md:31
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: The `skills:` frontmatter field lists `superpowers:root-cause-tracing`. This skill was backed up and removed from the install on 2026-05-03 (`~/.claude/skills-backup/root-cause-tracing.backup-20260503-195302/`). It does not exist in the superpowers plugin (5.1.0) nor in the locally installed skills. The body also references it by name (line 65: "Apply `superpowers:systematic-debugging` and `superpowers:root-cause-tracing`"). When this agent is dispatched, the skill cannot be loaded — the body instruction becomes dead guidance.
  Recommendation: Remove `superpowers:root-cause-tracing` from the `skills:` list. In the body, remove the reference or replace with `superpowers:systematic-debugging` alone (which does exist and covers root cause work). Apply the same fix to `bug-diagnoser.md` (see F2).
  Vision-advancement-tier: A
  Vision-advancement: Broken skill references silently degrade the "guardrail every completion claim with mechanical evidence" commitment (load-bearing commitment 4) — the systematic-debugging stage runs without its contracted methodology, and the agent cannot be held to the quality it advertises.
  Related: F2

---

F2: `superpowers:root-cause-tracing` deleted skill referenced in bug-diagnoser
  File: src/plugins/beads/.agents/agents/bug-diagnoser.md:31
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: `bug-diagnoser.md` lists `superpowers:root-cause-tracing` in `skills:` (line 31) and invokes it by name in the body (line 54: "Apply `superpowers:systematic-debugging` and `superpowers:root-cause-tracing`"). Same deleted-skill issue as F1. The bug-diagnoser is the first stage of the `fix-bug` formula; if its contracted methodology cannot load, root-cause quality degrades silently before any downstream stage (tdd-red-team, tdd-green-team) receives the `root_cause_note` it depends on.
  Recommendation: Remove `superpowers:root-cause-tracing` from `skills:` and from the body invocation line. The `superpowers:systematic-debugging` skill (which exists and is installed) covers the systematic diagnosis process.
  Vision-advancement-tier: A
  Vision-advancement: The fix-bug pipeline is a concrete implementation of "substitute adversarial cross-model review for human review" (load-bearing commitment 3); a broken skill in the diagnose stage undermines the pipeline's ability to operate without human intervention.
  Related: F1

---

F3: Wrong namespace for `writing-unit-tests` and `testing-anti-patterns` in bead-pipeline agents
  File: src/plugins/beads/.agents/agents/bead-implementor.md:28-29, src/plugins/beads/.agents/agents/tdd-red-team.md:30-32, src/plugins/beads/.agents/agents/tdd-green-team.md:33-34
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: Three bead-pipeline agents list `superpowers:writing-unit-tests` and `superpowers:testing-anti-patterns` in their `skills:` frontmatter. These skills are NOT in the superpowers plugin (confirmed: superpowers 5.1.0 has no `writing-unit-tests` or `testing-anti-patterns` directory). They are installed as plain skills from this repo at `~/.claude/skills/writing-unit-tests/` and `~/.claude/skills/testing-anti-patterns/` with names `writing-unit-tests` and `testing-anti-patterns` respectively. The `superpowers:` namespace prefix is incorrect and will cause skill resolution failure — the harness looks for a plugin-namespaced skill that does not exist.
  Recommendation: Replace `superpowers:writing-unit-tests` → `writing-unit-tests` and `superpowers:testing-anti-patterns` → `testing-anti-patterns` in the `skills:` fields of all three files. Body text references use plain names already (e.g. "Apply `superpowers:writing-unit-tests`" in bead-implementor body line 83 — also fix those references to drop the prefix).
  Vision-advancement-tier: A
  Vision-advancement: Correct skill resolution is a prerequisite for the TDD pipeline to enforce "guardrail every completion claim with mechanical evidence" (load-bearing commitment 4) — misnaming skills means the TDD methodology fails to load in the agents responsible for red/green phase discipline.
  Related: F1, F2

---

F4: `bead-implementor` model tier too low for its highest-effort stage
  File: src/plugins/beads/.agents/agents/bead-implementor.md:34
  Category: agent
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: `bead-implementor` is assigned `model: sonnet` and `effort: medium`. However, its `green-loop` stage description explicitly notes "effort:high for iter 1" and the body says the orchestrator overrides effort at dispatch time. The companion `tdd-green-team` agent — which does the same work in the dedicated-worker pipeline — is assigned `model: opus` and `effort: high`. This creates an inconsistency: when the orchestrator dispatches `bead-implementor` for green-loop work, it gets a weaker base model than the specialized `tdd-green-team` worker. The comment "Iteration effort: the orchestrator sets effort via frontmatter override at dispatch time" suggests the model field may also be overridden, but the frontmatter does not document which fields are caller-overridable, leaving the contract ambiguous.
  Recommendation: Either (a) elevate `bead-implementor` to `model: opus` to match `tdd-green-team` since it handles the same green-loop work, or (b) add explicit documentation in the Operating Contract section noting which frontmatter fields (`model`, `effort`) the orchestrator is expected to override at dispatch, and what the fallback defaults mean. The current silence is an undocumented caller contract.
  Vision-advancement-tier: C
  Vision-advancement: Consistent model-tier assignment reduces the risk of under-powered execution in the implementation pipeline, keeping autonomous overnight runs reliable.
  Promotion-eligible: yes

---

F5: `quality-reviewer` body leaks bead-tracker terminology into a shared agent
  File: src/user/.agents/agents/quality-reviewer.md:57
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: `quality-reviewer.md` lives in `src/user/.agents/agents/` — a shared location installed across all detected tools (Claude Code, Codex, Gemini, OpenCode). Its body (line 57, Plan Alignment Analysis) contains "bead description" and "step description" as concrete plan-source examples: "Compare the implementation against the original plan, spec, bead description, or step description." The term "bead description" is bead-tracker-specific terminology. Non-beads users on Codex or Gemini will encounter a reference to a concept their toolchain does not have. This is a bead-concept hygiene violation per the audit dimension and the AGENTS_PRIMER.md specification for shared agents.
  Recommendation: Replace "bead description, or step description" with a tool-agnostic equivalent: "issue description, or task specification". The substance is preserved; the terminology generalizes. Bead-specific examples can remain in `src/plugins/beads/` content only.
  Vision-advancement-tier: A
  Vision-advancement: Shared agents that carry tool-specific terminology undermine the mission commitment to ship a "portable discipline layer … achievable on any major AI coding assistant" — fixing this hygiene violation directly advances portability.
  Related: F6

---

F6: `quality-reviewer` memory accumulation without eviction policy
  File: src/user/.agents/agents/quality-reviewer.md:34
  Category: agent
  Severity: Low
  Tier: 2 (design, deferred)
  Issue: `quality-reviewer` uses `memory: project`, meaning it accumulates a persistent MEMORY.md at `.claude/agent-memory/quality-reviewer/`. Per the AGENTS_PRIMER, memory should be enabled "only for agents that genuinely benefit from cross-session learning." The agent's role (reviewing changed code + plan alignment per dispatch) is largely stateless — each review is scoped to the diff at hand. No eviction policy, retention horizon, or memory schema is documented in the body. Without it, the memory file will grow across reviews and may inject stale context (e.g., past false positives, superseded plan references) into future reviews.
  Recommendation: Either (a) remove `memory: project` if cross-session pattern tracking is not actively used, or (b) add a "## Memory Protocol" section to the body specifying what categories of findings to persist (recurring vulnerability patterns, project-specific anti-patterns), the maximum horizon (e.g., 30 reviews), and an eviction rule.
  Vision-advancement-tier: C
  Vision-advancement: A documented memory protocol prevents accumulated stale context from degrading review quality, maintaining the reliability of the completion gate across overnight autonomous runs.
  Promotion-eligible: no

---

F7: `tech-lead` description missing `<example>` blocks — weak dispatch signal
  File: src/user/.agents/agents/tech-lead.md:3-31
  Category: agent
  Severity: High
  Tier: 2 (design, deferred)
  Issue: The `tech-lead` description field contains three `<example>` blocks — but they are in the frontmatter description, which is correct structure. However, examining the actual examples closely: all three examples have the same shape ("complex task → dispatch tech-lead") without differentiating when to use tech-lead versus dispatching specialized agents directly. None of the examples show what tech-lead does NOT handle (e.g., single-agent tasks, tasks already decomposed by the caller). More critically, the description opens with "PROACTIVELY use this agent when you need to orchestrate complex development tasks" — the word "PROACTIVELY" is all-caps emphasis typically reserved for always-triggered behaviors, but the agent is situational (multi-agent coordination). This ambiguity may cause over-triggering: the orchestrating agent might dispatch tech-lead for tasks that don't need a second layer of orchestration.
  Recommendation: Add a "Do NOT dispatch when:" clause to the description listing single-agent tasks, tasks where the caller already has a decomposition plan, or tasks already routed to the bead pipeline. This sharpens the dispatch signal and prevents nested orchestration overhead.
  Vision-advancement-tier: B
  Vision-advancement: Sharp dispatch boundaries reduce unnecessary orchestration overhead, directly contributing to the vision-85-5-10 gap of tighter idea-to-shippable cycle time.
  Promotion-eligible: yes

---

F8: `tech-lead` body references Claude-specific path `.claude/agents/*`
  File: src/user/.agents/agents/tech-lead.md:43, 118
  Category: agent
  Severity: Medium
  Tier: 1 (mechanical, inline)
  Issue: The tech-lead body instructs the agent to scan `.claude/agents/*` to discover team members (lines 43 and 118: "Scan .claude/agents/\* to understand available team members" and "You must work only with available agents in .claude/agents/\*"). This is a Claude Code-specific path convention. `tech-lead.md` is in `src/user/.agents/agents/` — shared across all tools. Codex, Gemini, and OpenCode store agents at different paths (e.g., Codex uses `.codex/agents/`, Gemini may differ). The hardcoded path will produce wrong results or empty scans on non-Claude tools.
  Recommendation: Generalize to "Scan the available agents directory for this tool (e.g., `.claude/agents/` for Claude Code)" or parameterize with a note that the path is tool-dependent. Alternatively, move `tech-lead` to `src/user/.claude/agents/` if it is Claude-specific in practice.
  Vision-advancement-tier: A
  Vision-advancement: A shared agent that hardcodes a Claude-specific path blocks portability to Codex and Gemini, directly regressing the mission to make the discipline layer achievable on any major AI coding assistant.
  Related: F5

---

F9: `tech-lead` missing `disallowedTools` for a code-free orchestrator
  File: src/user/.agents/agents/tech-lead.md:115-116
  Category: agent
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: The tech-lead body explicitly states "You do not write code yourself — all implementation is delegated" and "You cannot create new agents, only coordinate existing ones." These constraints exist in prose but are not enforced at the tool level. The frontmatter has no `tools:` or `disallowedTools:` field. Without tool-level enforcement, a tech-lead instance could inadvertently use Write or Edit tools, making direct code changes that should have been delegated. Per the AGENTS_PRIMER, `disallowedTools` is "recommended only when explicit prohibitions are necessary."
  Recommendation: Add `disallowedTools: Write, Edit` to the frontmatter. This mechanically enforces the prose constraint at the dispatch boundary, making "no code writing" a contract rather than a suggestion.
  Vision-advancement-tier: C
  Vision-advancement: Enforcing the orchestration-only boundary mechanically prevents scope creep that would undermine clean agent separation and the reliability of the parallel-execution model.
  Promotion-eligible: yes

---

F10: `tech-lead` missing `effort` field
  File: src/user/.agents/agents/tech-lead.md:32-33
  Category: agent
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: The `tech-lead` frontmatter has `model: sonnet` and `color: pink` but no `effort:` field. Given that tech-lead performs strategic decomposition, dependency mapping, and multi-agent coordination — tasks requiring thorough reasoning — leaving `effort` unset means it defaults to whatever the harness default is (typically `medium`). For an orchestration agent managing complex multi-component tasks, `effort: high` is more appropriate, consistent with how `tdd-green-team`, `bug-diagnoser`, and `tdd-red-team` are configured for their demanding roles.
  Recommendation: Add `effort: high` to the frontmatter. Strategic planning and orchestration coordination benefit from higher reasoning effort.
  Vision-advancement-tier: C
  Vision-advancement: Appropriate effort configuration ensures the orchestration layer reasons thoroughly, reducing the frequency of miscoordination that would require human escalation and inflate the 5% troubleshooting ratio.

---

F11: `bead-implementor` `skills:` field lists `superpowers:root-cause-tracing` used in diagnose stage only — partial overlap with dedicated `bug-diagnoser`
  File: src/plugins/beads/.agents/agents/bead-implementor.md:25-36
  Category: agent
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: `bead-implementor` is documented as handling three stages: `diagnose`, `red-tests`, and `green-loop`. However, the pipeline now has dedicated worker agents (`bug-diagnoser`, `tdd-red-team`, `tdd-green-team`) that each own one of these stages with a tighter contract, a typed YAML report schema, and appropriate model selection. The `bead-implementor`'s three-stage design appears to be a pre-specialization version of the pipeline. Its `diagnose` stage duplicates `bug-diagnoser`'s role; its `red-tests` stage duplicates `tdd-red-team`; its `green-loop` stage duplicates `tdd-green-team`. This creates two parallel dispatch paths with overlapping responsibilities and no documented routing rule indicating when to use `bead-implementor` vs. the dedicated agents.
  Recommendation: Audit the `implement-bead` skill to determine which dispatch path is canonical. If dedicated agents (`bug-diagnoser`, `tdd-red-team`, `tdd-green-team`) are the current pipeline, document `bead-implementor` as deprecated or narrow its scope to a simplified single-stage fallback for cases where the dedicated pipeline is not available. If `bead-implementor` is the canonical path, remove or mark the dedicated agents accordingly.
  Vision-advancement-tier: A
  Vision-advancement: Eliminating ambiguous parallel dispatch paths is essential for reliable autonomous operation (load-bearing commitment 5 — persist context so work survives agent handoff); when two agents claim ownership of the same stage, overnight runs risk wrong-agent selection with no human present to correct it.
  Promotion-eligible: yes
  Related: F4

---

F12: `bead-verifier` description written in first-person fragments — weak third-person trigger contract
  File: src/plugins/beads/.agents/agents/bead-verifier.md:3-27
  Category: agent
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: The `bead-verifier` description begins "PROACTIVELY collect mechanical verification evidence…" — this is imperative/second-person framing of a dispatch trigger, not a third-person description of what the agent does. Per the AGENTS_PRIMER, the description serves as both a dispatch signal for the orchestrator and role framing for the agent. The SKILLS_PRIMER (which sets the precedent for description framing across this project) requires third-person: "Processes…", "Collects…", "Runs…" — not "collect". While this is a skill-primer standard, the AGENTS_PRIMER similarly emphasizes "observable situations, not abstract capabilities" and "Works: Description that starts with 'Use this agent when…'" — the current framing is a command to the agent, not a description of its capabilities.
  Recommendation: Rewrite the opening to third-person: e.g., "Mechanical verification agent that collects quality-gate evidence at completion gates — runs the project's quality-gate commands (tests, build, lint, typecheck, etc.) and reports raw exit codes plus terse error excerpts. Haiku-speed, evidence-only; makes no judgment calls." The examples that follow are well-formed and need no change.
  Vision-advancement-tier: C
  Vision-advancement: Correct description framing ensures reliable dispatch-trigger matching, preventing the orchestrator from bypassing the verification step and weakening the "guardrail every completion claim" commitment.
