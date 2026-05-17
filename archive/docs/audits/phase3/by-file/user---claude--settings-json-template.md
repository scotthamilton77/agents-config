# Findings for src/user/.claude/settings.json.template
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F7: settings.json.template hook path hardcoded — not portable
  File: src/user/.claude/settings.json.template:39
  Category: template
  Severity: High
  Tier: 2
  Issue: The PostToolUse hook command is `"~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh"`. If a user installs skills to a non-standard location, or if wait-for-pr-comments is not installed, the hook silently fails on every Bash tool use. No guard for script existence, no fallback, no documentation of the prerequisite.
  Recommendation: Add a comment block documenting the prerequisite. Wrap the hook command in a guard: `"[ -f ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh ] && ~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh || true"` so missing scripts don't generate errors. Alternatively, reference the script via `$CLAUDE_SKILLS_ROOT` if the harness exposes that variable.
  Vision-advancement-tier: A
  Vision-advancement: The wait-for-pr-comments hook is part of the PR review automation pipeline (commitment #3); a silently-failing hook disables that pipeline without any signal to the operator.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F7

---

---

F8: settings.json.template permissions allow list is empty — no baseline tool permissions
  File: src/user/.claude/settings.json.template:13-14
  Category: template
  Severity: Medium
  Tier: 2
  Issue: `permissions.allow` array is empty (`[]`). For autonomous operation (overnight runs, run-queue), repeated permission prompts at runtime for universally-safe read-only operations directly undermine the operating model. The deny list is well-populated with appropriate restrictions.
  Recommendation: Populate the allow list with a baseline set of safe, universally-applicable operations: `Bash(git status)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Read(*)`, `Glob(*)`, `Grep(*)`. Document in a comment that project-specific additions belong in `<project>/.claude/settings.json`, not in the user-level template.
  Vision-advancement-tier: A
  Vision-advancement: An empty allow list forces manual permission approval for every read operation, directly breaking the overnight autonomous execution model that is central to the 85/5/10 target ratio.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F8

---
