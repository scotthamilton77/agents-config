# Findings for src/user/.claude/rules/worktrees.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F15: worktrees.md — Override clause ambiguous about when it applies
  File: src/user/.claude/rules/worktrees.md:5-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The rule states "Preferred: Use Claude Code's native EnterWorktree tool" then "Override: The superpowers using-git-worktrees skill defaults to .worktrees/... Disregard that default." The structure doesn't make explicit that the Override only applies when using the skill, not when using EnterWorktree.
  Recommendation: Restructure to make three cases explicit: (1) Using EnterWorktree tool → no override needed; it places worktrees at the correct location. (2) Manually creating worktrees → use `git worktree add .claude/worktrees/<name> -b <branch>`. (3) If superpowers:using-git-worktrees skill suggests .worktrees/ → disregard; use .claude/worktrees/ instead.
  Vision-advancement-tier: C
  Vision-advancement: Eliminates worktree placement confusion that causes agents to retry or escalate unnecessarily on worktree creation failures.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F15

---

---

F16: worktrees.md — EnterWorktree tool reference needs Claude Code scope qualifier
  File: src/user/.claude/rules/worktrees.md:5
  Category: rule
  Severity: Low
  Tier: 1
  Issue: `EnterWorktree` is a Claude Code-only construct. The RULES_PRIMER notes that rules should be "tool-agnostic in spirit" with intent to embed content into other tool AGENTS.md files. The reference reads as a universal recommendation with no qualifier.
  Recommendation: Add a single parenthetical: "Use Claude Code's native `EnterWorktree` tool (Claude Code only) — it places worktrees here automatically."
  Vision-advancement-tier: C
  Vision-advancement: Ensures the rule remains coherent when embedded into Codex or Gemini AGENTS.md files via the future cross-tool embedding pipeline.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F16

---
