# Findings for src/user/.claude/commands/refresh-agents-md.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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
