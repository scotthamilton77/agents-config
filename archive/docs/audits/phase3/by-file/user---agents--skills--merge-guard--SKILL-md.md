# Findings for src/user/.agents/skills/merge-guard/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F19: merge-guard description uses imperative phrasing
  File: src/user/.agents/skills/merge-guard/SKILL.md:3-7
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Description starts with "Proactively use when about to merge a PR" — imperative instruction to the agent, not third-person description of what the skill does.
  Recommendation: Rewrite: "Pre-merge gate that prevents merging while automated reviews (especially Copilot) are pending or review comments have not been triaged. Invoke proactively before any `gh pr merge`, `git merge`, or merge action."
  Vision-advancement-tier: C
  Vision-advancement: Corrects description phrasing so the skill's trigger contract accurately describes behavior.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F19

---

## New findings promoted from Phase 2 (OOS or new)
