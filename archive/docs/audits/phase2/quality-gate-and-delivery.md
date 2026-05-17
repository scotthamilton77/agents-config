# Phase 2 Review: Quality Gate + Delivery Pipeline
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Agent finishing work — completion gate through PR merge with review-feedback loop
Categories touched: skills (verify/simplify/wait-for-pr/reply-and-resolve/finishing/merge-guard), agents (quality-reviewer, bead-verifier), rules (completion-gate, delivery, delegation)

F1: Consolidating the Skill A/Skill B contract is good, but the launcher docs must keep the chain visible
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:72-99
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:681-828
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:60-70
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 1 is right that the hand-off contract is duplicated and too heavy, but this pipeline depends on agents seeing three facts in the primary SKILL.md without chasing references: Skill A writes the inventory, Skill B is default-on after Phase 7, and Skill A owns inventory cleanup after Skill B returns. If extraction hides those facts behind deep reference chasing, the quality-to-delivery loop becomes brittle.
  Recommendation: Keep the phase map, Phase 8 default-on chain, inventory ownership, and recovery entrypoints in the main SKILL.md files. Extract the detailed schema/recovery prose, but centralize the authoritative guard definitions in one place referenced by both skills.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 by keeping the completion-gate hand-off mechanically legible while still reducing drift in the shared review-response contract.
  Promotion-eligible: yes
  Related: F3, F4
  Phase-1-source: phase1/skills.md:F1, phase1/skills.md:F2
  Verdict: AGREE

F2: Beads leakage should be isolated at the autonomous adapter, not by moving the whole PR-review chain out of shared skills
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:31-36
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:187-193
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:55-58
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:111-119
  Category: skill
  Severity: High
  Tier: 2
  Issue: The `bd`-backed autonomous branches are real shared-namespace leakage, but the core workflow is not beads-specific. `delivery.md` and `merge-guard` both rely on `wait-for-pr-comments` as the default review-feedback loop, and `reply-and-resolve-pr-threads` is the mandatory acknowledgement stage that closes that loop. Moving either skill wholesale into the beads plugin would strand non-beads delivery flows and make the cross-tool review-response pipeline less navigable, not more.
  Recommendation: Keep shared entrypoints for both skills and split only the beads-backed autonomous persistence/escalation behavior (`--bead-id`, `bd label add`, `bd update`) into a beads-aware addendum or adapter section. Interactive/default review handling should remain the canonical shared path.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 by preserving the portable PR-review response loop while isolating only the beads-specific persistence layer that is not universally available.
  Promotion-eligible: yes
  Related: F5
  Phase-1-source: phase1/skills.md:F3, phase1/skills.md:F4
  Verdict: PARTIAL
  Counter-recommendation: Split the autonomous/beads branch from the shared review-response workflow; do not move Skill A or Skill B wholesale into `src/plugins/beads/`.

F3: Skill B should not become “self-contained” by copying the validator it is supposed to share with Skill A
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:62-70
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:681-713
  Category: skill
  Severity: High
  Tier: 2
  Issue: The cross-skill path is brittle, but the dependency itself is genuine. `reply-and-resolve-pr-threads` is the read-side of the inventory contract that `wait-for-pr-comments` writes. Copying or symlinking `validate-inventory.sh` into Skill B's directory would reduce path fragility by introducing contract-ownership fragility: two homes for the same gate.
  Recommendation: Preserve one validator and one contract owner. Fix portability by moving the validator to a shared support location or by introducing a shared root variable for skill-support assets, with both skills calling the same file.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 by keeping one mechanical enforcement point for the inventory contract instead of creating parallel validation surfaces that can drift.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/skills.md:F11
  Verdict: PARTIAL
  Counter-recommendation: Use a shared support path for `validate-inventory.sh`; do not duplicate the validator into Skill B.

F4: completion-gate needs an explicit bridge into delivery, even if delivery owns the longer policy
  File: src/user/.claude/rules/completion-gate.md:19-22
  Category: rule
  Severity: High
  Tier: 2
  Issue: The paragraph Phase 1 wants to trim is not accidental duplication; it is the hand-off contract from checklist steps 1–5 into steps 6–8. In this pipeline, that bridge matters because agents often stop after `verify-checklist` unless the next stage is stated explicitly. Removing the ordered hand-off from `completion-gate.md` would make the `quality-reviewer → simplify → verify-checklist → finishing-a-development-branch → wait-for-pr-comments` chain less discoverable right where the transition happens.
  Recommendation: Keep a concise explicit bridge in `completion-gate.md`: immediate delivery, ordered skills, pause only at merge. Let `delivery.md` own the fuller action-category policy and PR-comment detail.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 by preserving the mechanical transition from “quality gate passed” to “delivery now runs” instead of relying on an agent to remember to open another rule.
  Promotion-eligible: yes
  Related: F5
  Phase-1-source: phase1/rules.md:F7
  Verdict: PARTIAL
  Counter-recommendation: Compress the paragraph, but keep the explicit ordered bridge and the “do not pause before PR creation” hand-off in `completion-gate.md`.

F5: Prefixing the PR-review skills with `superpowers:` would misname the actual chain
  File: src/user/.claude/rules/completion-gate.md:22
  File: src/user/.claude/rules/delivery.md:7-9
  File: src/plugins/beads/.claude/rules/delivery.md:7-11
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:1-15
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:1-10
  Category: rule
  Severity: High
  Tier: 1
  Issue: Phase 1 treats `wait-for-pr-comments` and `reply-and-resolve-pr-threads` as superpowers-plugin skills, but in this repo they are shared skills with bare canonical names. Applying the recommendation blindly would make the central review-response chain less accurate. The beads-aware addendum already appears to carry this stale namespacing assumption.
  Recommendation: Qualify only skills that are actually plugin-scoped. Keep `wait-for-pr-comments` and `reply-and-resolve-pr-threads` on their shared names unless a documented alias mechanism exists.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 by keeping the post-PR review loop addressable through the names that actually own the workflow, instead of redirecting agents to a non-authoritative namespace.
  Related: F2, F4
  Phase-1-source: phase1/rules.md:F8, phase1/rules.md:F17
  Verdict: DISAGREE
  Counter-recommendation: Audit each referenced skill name individually; do not mass-prefix the entire delivery chain with `superpowers:`.

F6: quality-reviewer project memory is useful in this gate, but it needs retention rules
  File: src/user/.agents/agents/quality-reviewer.md:31-35
  File: src/user/.agents/agents/quality-reviewer.md:40-48
  Category: agent
  Severity: Medium
  Tier: 2
  Issue: Phase 1 correctly flags the missing memory protocol, but removing `memory: project` would throw away exactly the sort of recurring-pattern context that strengthens the first stage of the completion gate across repeated PR cycles. This agent is not just a one-off diff scanner; it is the gate that can accumulate project-specific review heuristics, recurring regressions, and prior false-positive corrections.
  Recommendation: Keep `memory: project`, but add a narrow schema and eviction horizon for what is persisted.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by preserving useful cross-session reviewer memory while constraining it so stale context does not poison later gates.
  Promotion-eligible: yes
  Phase-1-source: phase1/agents.md:F6
  Verdict: PARTIAL
  Counter-recommendation: Add a memory protocol instead of removing project memory from the quality-reviewer.

F7: verify-checklist can demote bead-first wording without weakening the gate
  File: src/user/.agents/skills/verify-checklist/SKILL.md:63-65
  File: src/user/.agents/skills/verify-checklist/SKILL.md:91-94
  Category: skill
  Severity: Low
  Tier: 1
  Issue: The bead examples in `verify-checklist` are not part of the load-bearing completion-to-delivery chain. They are just examples in a shared reporting template, so Phase 1's hygiene cleanup does not remove a real dependency.
  Recommendation: Reorder the examples so generic tracking mechanisms come first and beads remain an optional project-specific case.
  Vision-advancement-tier: C
  Vision-advancement: Reduces tool-specific noise in the shared verification report without changing how the quality gate or delivery hand-off actually runs.
  Phase-1-source: phase1/skills.md:F16
  Verdict: AGREE

## Out of scope

OOS1: Codex/Gemini template omission still matters to this pipeline
  File: src/user/.codex/AGENTS.md.template:1-9
  Outside-scope: template category; this review is restricted to skills, agents, and rules
  Observation: The Phase 1 template finding that Codex and Gemini omit the delivery/delegation rules is materially relevant to this use case because it removes the completion-gate and delivery implementation path for those tools entirely.
  Suggested follow-up: Phase 3 should consider promoting phase1/templates.md:F1, or the template-focused Phase 2 reviewer should carry it forward explicitly.
