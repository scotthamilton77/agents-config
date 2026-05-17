# Findings for src/user/.claude/rules/subagents.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F14: subagents.md — consequence grounding missing from both constraints
  File: src/user/.claude/rules/subagents.md:1-7
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "verify worktree cleanup and branch locks before proceeding" and "Do not send messages to already-terminated ephemeral agents" are valid normative constraints without consequence clauses ("because X will happen if violated"). Per Rules Primer, authority grounding makes constraints self-explanatory and more resilient to pressure.
  Recommendation: Expand with one-line rationale: "…before proceeding — orphaned worktrees block future `git worktree add` calls with the same name." And: "…check agent status first — sending messages to terminated agents causes silent no-ops or harness errors that look like successful dispatches."
  Vision-advancement-tier: C
  Vision-advancement: Consequence grounding makes constraints self-explanatory, reducing the chance an agent omits the check when it seems inconvenient.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F14

---
