# Findings for src/user/.agents/skills/ralf-review/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F13: ralf-implement and ralf-review do not reference their supporting prompt files
  File: src/user/.agents/skills/ralf-implement/SKILL.md:44-51, src/user/.agents/skills/ralf-review/SKILL.md:40-45
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Both skills have supporting prompt files (foreign-agent-prompt.md, foreign-eyes-prompt.md, fresh-eyes-prompt.md, implementer-prompt.md) that are never referenced from the SKILL.md bodies. Templates go unused unless the agent discovers them by other means. Phase 2 multi-agent and escalation reviewers both AGREE this is a real gap — the prompt files are missing dispatch payload, not dead weight.
  Recommendation: Add explicit prompt-file references at the dispatch branch in both SKILL.md bodies (e.g., "Dispatch with `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md`"). Specify which file is used for each pass (foreign-agent, pure fresh-eyes, implementer).
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 (substitute adversarial cross-model review): adversarial review only works if the reviewer subagent receives prepared prompts — unreferenced supporting files are dead weight.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE from two reviewers (multi-agent:F3, escalation:F6) confirms this is active missing functionality.
  Sources: phase1/skills.md:F13, phase2/multi-agent-dispatch.md:F3, phase2/escalation-edge-recovery.md:F6

---
