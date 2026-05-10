# Findings for src/user/.gemini/GEMINI.md.template
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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
