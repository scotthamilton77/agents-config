# Findings for src/user/.agents/skills/merge-guard/check-merge-eligibility.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F5: check-merge-eligibility.sh — positional-only parameters, no named interface
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:1-38
  Category: script
  Severity: High
  Tier: 2
  Issue: All three parameters (`owner/repo`, `pr-number`, `comments-seen`) are positional. Particularly hazardous for `comments-seen` which could easily be transposed with the PR number by an LLM-generated invocation. Incorrect transposition produces misleading eligibility results, potentially allowing an un-reviewed PR to merge. Otherwise has strong error handling and a well-defined JSON stdout contract.
  Recommendation: Add named flags (--repo, --pr, --comments-seen) while preserving the positional fallback for backward compatibility. Add a full usage() block using `cat >&2 <<'EOF' ... EOF` pattern consistent with bd-toolkit scripts. Coordinate with agents-config-2gzy to avoid duplicate refactor passes.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires the merge-guard is invocable without fragile positional ordering.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F5

---

---

F6: check-merge-eligibility.sh — duplicates lib.sh helpers inline
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:55-75
  Category: script
  Severity: Low
  Tier: 1
  Issue: Contains its own `gh_api()` function, `gh auth status` pre-flight check, and `jq` availability check — all already defined in `src/user/.agents/skills/wait-for-pr-comments/lib.sh`. Two implementations that must stay in sync manually.
  Recommendation: Consider promoting lib.sh to a shared location (e.g., `src/user/.agents/skills/shared/lib.sh`) so check-merge-eligibility.sh can source it. If cross-skill sourcing is not desired, at minimum add a comment referencing `wait-for-pr-comments/lib.sh` as the canonical source.
  Vision-advancement-tier: C
  Vision-advancement: Reduces code duplication and drift risk, improving long-term maintainability of the shared GitHub API layer.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/scripts.md:F6

---
