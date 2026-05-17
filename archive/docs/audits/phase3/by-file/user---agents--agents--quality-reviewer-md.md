# Findings for src/user/.agents/agents/quality-reviewer.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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
