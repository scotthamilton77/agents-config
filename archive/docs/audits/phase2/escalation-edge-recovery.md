# Phase 2 Review: Escalation + Edge-Case Recovery
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Agent hits unexpected state — must navigate escalation/recovery paths
Categories touched: skills (start-bead/implement-bead/bugfix/ralf-*/run-queue/self-improving), formulas, rules

F1: `start-bead` must keep Route Z and replay/burn recovery in the launch path
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:33-94,96-165,275-315
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 1 treats Route Z closed-bead handling and adjacent recovery text as extractable reference material, but these branches are the first unhappy-path decisions after "read the bead": forwarded closed beads, dangling/multiple/cycle `produced-bead-*` chains, suspected unlabeled molecules, the `0/0` wisp-bug burn path, and the explicit stop-at-`implementation-ready` hand-off. If those move behind a secondary reference, the agent loses the recovery rules it needs before it can safely decide whether to resume, re-route, or stop.
  Recommendation: Keep Step 1.5, Step 2's molecule-ambiguity escalation, the `0/0` burn recovery, and the post-brainstorm hand-off stop condition in `SKILL.md`. If trimming is still wanted, extract only the summary routing table and repetitive examples.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by keeping the replay and hand-off contract visible at the exact point where context handoff and compaction failures occur.
  Promotion-eligible: yes
  Related: F4
  Phase-1-source: phase1/skills.md:F17
  Verdict: PARTIAL
  Counter-recommendation: Split out route summaries, not the closed-bead, replay, and burn-recovery branches.

F2: `implement-bead`'s duplicated `formula-*` parsing is not semantically duplicate recovery logic
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:24-49,55-79
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 1 treats the two `formula-*` parsing blocks as equivalent duplication, but they guard different recovery states. Before pour, ambiguity can only label the source bead because no step-bead exists yet. After pour, ambiguity must label both source bead and step-bead and reopen the step before exiting. Collapsing that into one shared "procedure" risks erasing the state-specific flag-human behavior the orchestrator needs when execution is half-materialized.
  Recommendation: If refactored, share only the low-level label-parsing expression. Keep the pre-pour and post-pour escalation branches explicit at their call sites.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 because the dispatcher's recovery behavior depends on whether execution failed before or after step materialization.
  Promotion-eligible: yes
  Related: F9
  Phase-1-source: phase1/skills.md:F6
  Verdict: PARTIAL
  Counter-recommendation: Optimize formatting and readability, but preserve two explicit flag-human branches keyed to the real execution state.

F3: The beads rules must retain the recovery control plane in always-loaded context
  File: src/plugins/beads/.claude/rules/beads.md:20-87
  File: src/plugins/beads/.claude/rules/beads-labels.md:5-35
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 proposes shrinking these rules toward a small normative stub and moving I1/I2, `bd human list` precedence, label semantics, and the `for-bead-<id>` existence probe out of always-loaded rule context. Under escalation conditions, those are not glossary filler; they are the shared recovery contract every bead workflow falls back to when a molecule is ambiguous, a human escalation exists, or discovered work must be placed correctly outside a formula's happy path.
  Recommendation: Trim CLI trivia if desired, but keep inline: I1/I2/I3 summaries, `bd human list` precedence, `human` label semantics, and the exact `for-bead-<id>` `--json` probe pattern. If helper scripts are introduced, the rule should still retain fallback pseudocode and pause semantics.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by keeping the cross-workflow recovery contract loaded even when the agent is recovering outside the original formula that created the state.
  Promotion-eligible: yes
  Related: F8, F9
  Phase-1-source: phase1/rules.md:F3
  Verdict: PARTIAL
  Counter-recommendation: Minimize around recovery invariants, not around line count; the same caution applies to the Phase 1 script-extraction and glossary-collapse proposals.

F4: `brainstorm-bead` intentionally needs both `phase = "vapor"` and `pour = true`
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:18-27
  Category: formula
  Severity: Critical
  Tier: 2
  Issue: Phase 1 reads `phase = "vapor"` and `pour = true` as contradictory. In this workflow they are orthogonal: `phase = "vapor"` advertises wisp-mode interactive brainstorming, while `pour = true` is required so the wisp actually materializes step beads. `start-bead` explicitly documents `0/0 steps complete` as the failure mode when `pour = true` is missing. Applying the Phase 1 fix would recreate the exact recovery bug the skill already warns about.
  Recommendation: Keep the header as-is. Clarify in the formula comment or primer that some wisps intentionally use `pour = true` when they need materialized step beads with ephemeral lifecycle.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by preserving the only configuration that gives brainstorm wisps recoverable step state without turning them into the wrong lifecycle class.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/formulas.md:F12
  Verdict: DISAGREE
  Counter-recommendation: Document the intentional vapor-plus-poured-wisp combination instead of normalizing it away.

F5: Shared preflight extraction cannot flatten the reroute semantics of `docs-only`
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:58-60
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:67-87
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:68-87
  Category: formula
  Severity: High
  Tier: 2
  Issue: Phase 1 proposes one shared `bd-preflight.sh` across `docs-only`, `fix-bug`, and `implement-feature`. That is too coarse for the unhappy path. `docs-only` is the reroute target precisely because coverage/gates may be absent, so it explicitly says not to inspect them. `fix-bug` and `implement-feature` do inspect them and park the molecule with a human flag on missing report-location. A single helper invites a parameter soup refactor that can silently collapse those divergent escalation rules.
  Recommendation: Extract only the mechanically identical parts: lookup-label stamp, worktree creation, path encoding/decoding, and claim-walk. Keep coverage/gates policy and the corresponding human-flag vs skip behavior inside each formula.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 by preserving the formula-specific "not ready, stop here" behavior instead of generalizing it into a helper that may guess wrong.
  Promotion-eligible: yes
  Related: F8
  Phase-1-source: phase1/formulas.md:F14
  Verdict: PARTIAL
  Counter-recommendation: Share mechanics only; keep refusal, parking, and reroute policy inline per formula.

F6: `ralf-implement` and `ralf-review` should explicitly point to their shipped prompt files
  File: src/user/.agents/skills/ralf-implement/SKILL.md:41-53
  File: src/user/.agents/skills/ralf-review/SKILL.md:40-47
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: The skills describe foreign-eyes and fresh-eyes cycles, plus degraded fallback, but never tell the caller to use the prompt files shipped beside the skill. In degraded or retried review paths, that forces the caller to improvise the adversarial prompt instead of using the prepared one.
  Recommendation: Add explicit prompt-file references at the dispatch step in both skills, including which file is used for foreign-agent and pure fresh-eyes fallback.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 because adversarial cross-model review only survives tool failure cleanly if the caller has deterministic prompt artifacts to fall back to.
  Promotion-eligible: yes
  Related: F2
  Phase-1-source: phase1/skills.md:F13
  Verdict: AGREE

F7: `bugfix`'s fallback ladder dead-ends on a deleted skill
  File: src/user/.agents/skills/bugfix/SKILL.md:117-120
  Category: skill
  Severity: High
  Tier: 1
  Issue: When the three-thread synthesis still cannot identify a root cause, the skill tells the agent to escalate via `superpowers:root-cause-tracing`. Phase 1 already established elsewhere that this skill is deleted. The explicit "don't guess, escalate" path is therefore broken exactly when the methodology is supposed to stop speculative fixes.
  Recommendation: Replace the deleted fallback with an existing path such as `superpowers:systematic-debugging`, `condition-based-waiting`, or an explicit stop-and-surface protocol that reports the missing evidence to the user.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 by keeping the skill's "not ready, escalate instead of guessing" path actually executable.
  Related: F6
  Verdict: AGREE

F8: `human`-label gating semantics contradict between formulas and rules
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:367-372
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:660-666
  File: src/plugins/beads/.claude/rules/beads-labels.md:10-13
  Category: formula
  Severity: High
  Tier: 1
  Issue: Two formulas say adding `human` excludes a bead from `bd ready`, while the rules say `human` is only a visibility tag and does not gate readiness. An agent following the hand-off path can therefore believe work is safely parked when it may still surface as ready unless some separate blocking mechanism exists.
  Recommendation: Pick one contract and make every touched file match. If `human` alone is not a readiness gate, the hand-off path must add a real blocker and say so. If it is intended to gate readiness, update the rule and every queue/escalation consumer to rely on that explicitly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by eliminating a contradictory parking contract that can cause resumed work to re-enter the queue before a human actually resolves it.
  Related: F3, F5, F9
  Verdict: AGREE

F9: `run-queue` resolves escalations too loosely for `implement-bead`'s dual-bead human-flag contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:117-133
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:55-79,124-140
  Category: skill
  Severity: High
  Tier: 2
  Issue: `run-queue` says to resolve an escalation by appending guidance and removing `human` from `<id>`. `implement-bead` deliberately stamps both the source bead and the step-bead on most recovery paths, and some pauses also require a step reopen or current-step recheck. Clearing one label ad hoc can requeue half-recovered work or leave a parked molecule in an inconsistent state.
  Recommendation: Add a paired-resolution procedure: identify whether the escalation belongs to source bead, step-bead, or both; clear labels symmetrically only after the underlying block is fixed; then re-check `bd mol current <mol-id>` and step notes before resuming the queue.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 by making resume behavior deterministic after a parked molecule is handed back from human review.
  Promotion-eligible: yes
  Related: F2, F3, F8
  Verdict: AGREE
