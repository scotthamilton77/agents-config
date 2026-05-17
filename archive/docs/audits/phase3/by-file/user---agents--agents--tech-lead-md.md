# Findings for src/user/.agents/agents/tech-lead.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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
