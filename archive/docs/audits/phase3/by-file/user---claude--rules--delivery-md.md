# Findings for src/user/.claude/rules/delivery.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F6: Two delivery.md files — cross-reference anchor fragility under append model
  File: src/user/.claude/rules/delivery.md:1-44, src/plugins/beads/.claude/rules/delivery.md:1-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Plugin delivery.md references "the AUTOMATIC category in core `delivery.md`" which is an implicit order reference in an append model. If append order ever changes, the cross-reference resolves ambiguously.
  Recommendation: Add a `## Core delivery rules` heading to the base delivery.md Action Categories section so the plugin's cross-reference has a stable anchor. Alternatively, normalize the plugin reference to "see the Action Categories section above."
  Vision-advancement-tier: C
  Vision-advancement: Reduces ambiguity risk in the append model, making cross-file references resilient to future ordering changes.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F6

---

---

F17: delivery.md — unqualified skill names for actually-shared skills (keep bare names)
  File: src/user/.claude/rules/delivery.md:7-9
  Category: rule
  Severity: Low
  Tier: 1
  Issue: Skills referenced without namespace qualifier. Phase 2 establishes (D3) that `wait-for-pr-comments` and `reply-and-resolve-pr-threads` are shared skills with bare canonical names — adding `superpowers:` would be wrong. `using-git-worktrees` and `finishing-a-development-branch` are genuinely superpowers-plugin skills.
  Recommendation: Add `superpowers:` prefix only to `using-git-worktrees` and `finishing-a-development-branch`. Keep `wait-for-pr-comments` and `reply-and-resolve-pr-threads` with bare names.
  Vision-advancement-tier: C
  Vision-advancement: Prevents silent skill dispatch failures by using accurate namespacing for each skill's actual provenance.
  Resolution: ACCEPTED (modified per D3)
  Rationale: Phase 2 DISAGREE on mass-prefixing; aggregator qualifies only actually plugin-scoped skills.
  Sources: phase1/rules.md:F17, phase2/quality-gate-and-delivery.md:F5

---

---

F18: delivery.md — inline gh command block is a script candidate
  File: src/user/.claude/rules/delivery.md:39-42
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The "PR comments" section includes an inline two-command block as a reminder to check both comment types. The GitHub API path is a template requiring variable substitution; as prose it is a reminder, not an executable command.
  Recommendation: Convert to a helper script `scripts/gh-pr-review-comments.sh <pr-number>` that detects `<owner>/<repo>` from `git remote` and runs both commands. Alternatively, accept the current form given the short length.
  Vision-advancement-tier: C
  Vision-advancement: Minor improvement to autonomous PR review pipeline reliability; named script eliminates the URL-template ambiguity.
  Promotion-eligible: yes
  Resolution: DROPPED (per D30)
  Rationale: Tier-C cap enforcement: Low-severity tier-C finding dropped to bring Tier C share to ≤30%. The two-command block is borderline and the impact on autonomous operation is marginal.
  Sources: phase1/rules.md:F18

---
