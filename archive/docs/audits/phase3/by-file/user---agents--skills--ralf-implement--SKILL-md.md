# Findings for src/user/.agents/skills/ralf-implement/SKILL.md
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

---

F20: implement-bead and ralf-implement describe incompatible orchestration contracts
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:87-90,136-144, src/user/.agents/skills/ralf-implement/SKILL.md:11-53
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: implement-bead treats ralf-implement as a beads-aware loop controller that receives typed worker inputs and returns an aggregate verdict compatible with step-bead closeout. ralf-implement defines no such contract — it implements directly in the working copy, runs completion-gate steps, and never mentions worker-report-v1, iteration audit labels, or aggregate return shapes. Two different orchestration models on the same seam.
  Recommendation: Choose one contract and encode it explicitly. Either make ralf-implement beads-aware by adding a formal caller contract for doer_subagent_type, worktree/report-path inputs, worker-report-v1 ingestion, and aggregate verdict output; or introduce a beads-specific adapter skill that owns the worker-report contract end to end.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context across agent handoff): the current seam cannot reliably hand off iteration state because each side believes a different contract exists.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F1)
  Rationale: Phase 2 multi-agent reviewer finds this a Critical gap not covered by Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F1

---
