# Phase 3 By-Category: Agents
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the agents category.

---

F1: bead-implementor — superpowers:root-cause-tracing is a deleted skill (broken reference)
  File: src/plugins/beads/.agents/agents/bead-implementor.md:31,65
  Category: agent
  Severity: High
  Tier: 1
  Issue: `skills:` frontmatter lists `superpowers:root-cause-tracing`. This skill was backed up and removed from install on 2026-05-03. It does not exist in superpowers 5.1.0 or locally. The body also invokes it by name (line 65). When dispatched, the skill cannot load — the body instruction becomes dead guidance.
  Recommendation: Remove `superpowers:root-cause-tracing` from `skills:` list. In the body, remove the reference or replace with `superpowers:systematic-debugging` alone (which exists and covers root cause work).
  Vision-advancement-tier: A
  Vision-advancement: Broken skill references silently degrade commitment #4 (guardrail every completion claim with mechanical evidence) — the systematic-debugging stage runs without its contracted methodology.
  Resolution: ACCEPTED
  Rationale: Phase 2 multi-agent reviewer AGREE (F6) and escalation reviewer (F7); Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F1, phase2/multi-agent-dispatch.md:F6

---

F2: bug-diagnoser — superpowers:root-cause-tracing deleted skill (broken reference)
  File: src/plugins/beads/.agents/agents/bug-diagnoser.md:31,54
  Category: agent
  Severity: High
  Tier: 1
  Issue: `bug-diagnoser` lists `superpowers:root-cause-tracing` in `skills:` and invokes it in the body. Same deleted-skill issue as F1. The bug-diagnoser is the first stage of the fix-bug formula; if contracted methodology cannot load, root-cause quality degrades before any downstream stage receives the `root_cause_note` it depends on.
  Recommendation: Remove `superpowers:root-cause-tracing` from `skills:` and from body invocation line. `superpowers:systematic-debugging` covers the systematic diagnosis process.
  Vision-advancement-tier: A
  Vision-advancement: The fix-bug pipeline is a concrete implementation of commitment #3 (substitute adversarial cross-model review); a broken skill in the diagnose stage undermines the pipeline's ability to operate without human intervention.
  Resolution: ACCEPTED
  Rationale: Phase 2 multi-agent reviewer AGREE (F6); Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F2, phase2/multi-agent-dispatch.md:F6

---

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

F4: bead-implementor model tier — defer until dispatch topology resolved
  File: src/plugins/beads/.agents/agents/bead-implementor.md:34
  Category: agent
  Severity: Medium
  Tier: 2
  Issue: bead-implementor assigned `model: sonnet` / `effort: medium` while companion tdd-green-team is `model: opus` / `effort: high`. However implement-bead's stage map does not dispatch bead-implementor at all — the canonical dispatches go to bug-diagnoser, tdd-red-team, tdd-green-team. Tuning bead-implementor's model before the topology question is settled hardens a non-canonical path.
  Recommendation: Resolve dispatch topology (F11/F9 — bead-implementor vs dedicated trio) first. Only then revisit model/effort defaults if the agent remains a supported dispatch target.
  Vision-advancement-tier: C
  Vision-advancement: Stabilizing which worker role is actually callable matters more than optimizing a worker the orchestrator should not normally choose.
  Promotion-eligible: yes
  Resolution: DEFERRED (per D5)
  Rationale: Phase 2 DISAGREE — tuning the wrong path is premature. Deferred until F9/F11 (dispatch topology) is resolved.
  Sources: phase1/agents.md:F4, phase2/multi-agent-dispatch.md:F8

---

F5: quality-reviewer body — "bead description" bead-tracker terminology in shared agent
  File: src/user/.agents/agents/quality-reviewer.md:57
  Category: agent
  Severity: High
  Tier: 1
  Issue: quality-reviewer.md is in `src/user/.agents/agents/` (shared across all tools). Body Plan Alignment Analysis (line 57) contains "bead description" and "step description" as concrete plan-source examples. Bead-tracker-specific terminology in shared content; non-beads users on Codex/Gemini encounter a reference to a concept their toolchain doesn't have.
  Recommendation: Replace "bead description, or step description" with "issue description, or task specification." Substance preserved; terminology generalized.
  Vision-advancement-tier: A
  Vision-advancement: Shared agents with tool-specific terminology undermine the mission to ship a portable discipline layer achievable on any major AI coding assistant.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F5

---

F6: quality-reviewer — memory accumulation without eviction policy; keep memory: project
  File: src/user/.agents/agents/quality-reviewer.md:34
  Category: agent
  Severity: Low
  Tier: 2
  Issue: quality-reviewer uses `memory: project` but has no documented eviction policy, retention horizon, or memory schema. Without it, MEMORY.md grows across reviews and may inject stale context. Phase 2 quality-gate reviewer gives PARTIAL: keep `memory: project` because this agent accumulates recurring-pattern context that strengthens the gate across repeated PR cycles.
  Recommendation: Keep `memory: project`. Add a "Memory Protocol" section specifying: what categories to persist (recurring vulnerability patterns, project-specific anti-patterns, prior false-positive corrections), maximum horizon (e.g., 30 reviews), and an eviction rule.
  Vision-advancement-tier: C
  Vision-advancement: A documented memory protocol prevents accumulated stale context from degrading review quality across overnight autonomous runs.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified per D20)
  Rationale: Phase 2 PARTIAL — keep memory but add protocol. Aggregator accepts synthesis.
  Sources: phase1/agents.md:F6, phase2/quality-gate-and-delivery.md:F6

---

F7: tech-lead — description missing negative dispatch triggers ("Do NOT dispatch when:")
  File: src/user/.agents/agents/tech-lead.md:3-31
  Category: agent
  Severity: High
  Tier: 2
  Issue: Three examples all teach one reflex: "complex task → dispatch tech-lead." None show when NOT to add another orchestration layer. In this repo, bead pipeline already has first-class routers (start-bead, implement-bead, run-queue). Without negative triggers, the orchestrator can spawn an orchestrator that then tries to rediscover a routing decision the system already made. Phase 2 multi-agent reviewer AGREE.
  Recommendation: Add "Do NOT dispatch when:" clause covering: work already routed to start-bead/implement-bead/run-queue; tasks already decomposed by caller; single-worker tasks. Add at least one negative example so the anti-trigger is part of the dispatch signal.
  Vision-advancement-tier: B
  Vision-advancement: Sharp dispatch boundaries reduce unnecessary orchestration overhead, contributing to the vision-85-5-10 gap of tighter idea-to-shippable cycle time.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (multi-agent:F10).
  Sources: phase1/agents.md:F7, phase2/multi-agent-dispatch.md:F10

---

F8: tech-lead body — hardcoded .claude/agents/* path; use caller-provided callable roster
  File: src/user/.agents/agents/tech-lead.md:43,118
  Category: agent
  Severity: Medium
  Tier: 2
  Issue: tech-lead instructs the agent to scan `.claude/agents/*` to discover team members — a Claude Code-specific path. tech-lead.md is in shared content. Codex, Gemini, OpenCode store agents at different paths. Phase 2 multi-agent reviewer gives PARTIAL: the deeper problem is that filesystem scanning is the wrong source of truth entirely — the reliable contract surface is the caller-provided callable roster.
  Recommendation: Replace "scan `.claude/agents/*`" with "use the caller-provided roster of callable agents and tool limits; if the caller does not provide one, inspect the current tool's agent registry or documented agent directory as a fallback" per D19. `.claude/agents/*` should appear only as a Claude-specific example.
  Vision-advancement-tier: A
  Vision-advancement: A shared agent that hardcodes a Claude-specific path blocks portability to Codex and Gemini, directly regressing the mission to make the discipline layer achievable on any major AI coding assistant.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D19)
  Rationale: Phase 2 PARTIAL — deeper generalization accepted.
  Sources: phase1/agents.md:F8, phase2/multi-agent-dispatch.md:F11

---

F9: tech-lead — missing disallowedTools for code-free orchestrator
  File: src/user/.agents/agents/tech-lead.md:115-116
  Category: agent
  Severity: Medium
  Tier: 2
  Issue: tech-lead body explicitly states "You do not write code yourself" but frontmatter has no `tools:` or `disallowedTools:` field. Without tool-level enforcement, a tech-lead instance could inadvertently use Write or Edit tools.
  Recommendation: Add `disallowedTools: Write, Edit` to the frontmatter. Mechanically enforces the prose constraint at the dispatch boundary.
  Vision-advancement-tier: C
  Vision-advancement: Enforcing the orchestration-only boundary mechanically prevents scope creep that undermines clean agent separation.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands.
  Sources: phase1/agents.md:F9

---

F10: tech-lead — missing effort field
  File: src/user/.agents/agents/tech-lead.md:32-33
  Category: agent
  Severity: Low
  Tier: 1
  Issue: tech-lead frontmatter has `model: sonnet` and `color: pink` but no `effort:` field. For an orchestration agent managing complex multi-component tasks, leaving effort unset defaults to medium, which is likely under-powered.
  Recommendation: Add `effort: high` to the frontmatter. Strategic planning and orchestration benefit from higher reasoning effort.
  Vision-advancement-tier: C
  Vision-advancement: Appropriate effort configuration ensures the orchestration layer reasons thoroughly, reducing miscoordination frequency.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F10

---

F11: bead-implementor vs dedicated worker trio — ambiguous parallel dispatch paths
  File: src/plugins/beads/.agents/agents/bead-implementor.md:25-36
  Category: agent
  Severity: High
  Tier: 2
  Issue: bead-implementor still presents itself as the worker for diagnose, red-tests, and green-loop, but implement-bead's actual stage map dispatches bug-diagnoser, tdd-red-team, tdd-green-team. Two incompatible packages for the same stages: one appends notes and mutates tracker state, the other writes typed YAML reports. Phase 2 multi-agent reviewer AGREE: this is not documentation drift — it's two different contracts.
  Recommendation: Declare the dedicated worker trio canonical and mark bead-implementor deprecated, fallback-only, or removed from normal discovery. If backward compatibility required, add explicit "dispatch only when..." clause so orchestrator never has to guess.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): handoff reliability collapses when two workers claim the same stage but emit different outputs and operate on different state surfaces.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (multi-agent:F9).
  Sources: phase1/agents.md:F11, phase2/multi-agent-dispatch.md:F9

---

F12: bead-verifier description — imperative phrasing instead of third-person trigger contract
  File: src/plugins/beads/.agents/agents/bead-verifier.md:3-27
  Category: agent
  Severity: Low
  Tier: 1
  Issue: Description begins "PROACTIVELY collect mechanical verification evidence…" — imperative/second-person framing of a dispatch trigger, not third-person description of what the agent does.
  Recommendation: Rewrite opening to third-person: "Mechanical verification agent that collects quality-gate evidence at completion gates — runs the project's quality-gate commands (tests, build, lint, typecheck, etc.) and reports raw exit codes plus terse error excerpts."
  Vision-advancement-tier: C
  Vision-advancement: Correct description framing ensures reliable dispatch-trigger matching, preventing the orchestrator from bypassing the verification step.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F12
