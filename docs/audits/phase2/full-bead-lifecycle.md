# Phase 2 Review: Full Bead Lifecycle
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Agent driving a bead from create → brainstorm → implement → deliver → merge
Categories touched: skills (lifecycle), formulas, scripts, rules

F1: `wait-for-pr-comments` should be split by mode, not exiled from shared delivery
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:67-68, 187-192, 545-562
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 1 is right that autonomous mode is bead-coupled here: `--mode autonomous --bead-id` is formula-driven, ESCALATE persistence writes to `bd`, and DEFER placement applies bead rule I3. But moving the entire skill to the beads plugin would break the non-bead PR lifecycle, because the shared delivery rule treats `wait-for-pr-comments` as the canonical review-automation step for all non-trivial work, not just bead-tracked work.
  Recommendation: Keep a shared PR-review core and split the bead-specific behavior. The shared skill should retain PR detection, Copilot polling, classification, FIX execution, inventory handoff, and interactive mode. A beads-plugin addendum or wrapper should own autonomous mode, `--bead-id`, `bd` escalation filing, and I3-based DEFER placement.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 by preserving the generic automated PR review loop across tools, while confining bead-specific persistence mechanics to the plugin path that actually provides them.
  Promotion-eligible: yes
  Related: F2, F4
  Phase-1-source: phase1/skills.md:F3
  Verdict: PARTIAL
  Counter-recommendation: Do not move the whole skill to `src/plugins/beads/`; split shared interactive/core behavior from beads-only autonomous persistence behavior.

F2: `reply-and-resolve-pr-threads` has the same split-brain problem as Skill A
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:45-46, 58-70, 111, 185-188, 240-242
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 1 correctly identifies bead-coupled autonomous recovery in this shared skill: standalone mode is explicitly deferred to bead follow-up work, and autonomous recovery persists via `bd`. But this skill is also the public thread-reply/resolution engine chained from shared delivery. Moving it wholesale into the beads plugin would make the generic PR closeout path vestigial for non-bead users.
  Recommendation: Mirror the split recommended for Skill A. Keep the shared thread-reply/resolution engine and inventory-driven execution in shared content. Move only autonomous recovery persistence and `--bead-id` handling into a beads-specific extension or wrapper invoked by bead formulas and bead-aware delivery.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 by keeping reviewer-facing thread closure portable across tools, instead of tying the entire closeout stage to one tracker implementation.
  Promotion-eligible: yes
  Related: F1, F4
  Phase-1-source: phase1/skills.md:F4
  Verdict: PARTIAL
  Counter-recommendation: Preserve the shared reply/resolve engine; isolate only the autonomous bead-recovery path inside the beads plugin.

F3: `beads-labels.md` is a lifecycle contract, not a disposable glossary
  File: src/plugins/beads/.claude/rules/beads-labels.md:5-13, 22-34
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 understates how load-bearing this rule is. The table is not mere reference fluff: `implementation-readied-session-<sid>` drives `start-bead` Route A handoff gating, `for-bead-<bead-id>` is the only reliable bead→molecule lookup edge, `human` defines queue visibility semantics, and `ralf:*` labels steer orchestration behavior. Collapsing this to a two-sentence stub would leave the lifecycle navigable only if every agent re-discovers the contract from scattered skills and formulas.
  Recommendation: Trim command examples if desired, but keep the contract table itself always loaded for beads users. At minimum preserve the semantics for `implementation-readied-session-*`, `for-bead-*`, `human`, `ralf:required`, and `ralf:cycles=N` in the rule body.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 because these labels are the persisted state handoff between brainstorm, start, implement, queue, and merge flows; hiding that contract behind ad hoc reads weakens cross-session continuity.
  Promotion-eligible: yes
  Related: F1, F5
  Phase-1-source: phase1/rules.md:F4
  Verdict: PARTIAL
  Counter-recommendation: Slim the rule, but do not demote the label contract to a reference-only artifact.

F4: completion-gate should lose duplication, not lose the delivery handoff
  File: src/user/.claude/rules/completion-gate.md:19-22
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Phase 1 is right that the numbered delivery sequence duplicates `delivery.md`. But the hard-stop handoff from “verification passed” to “delivery begins now” is the seam between implement and deliver. If completion-gate becomes silent on that transition, the full lifecycle becomes easier to stall after verification, especially in subagent-heavy runs where “done” often gets misread as “report back and wait.”
  Recommendation: Keep the mandatory handoff sentence in `completion-gate.md`, but remove the detailed ordered list and point to `delivery.md` for execution order. The rule should still say, explicitly, that passing the gate triggers delivery immediately and that authorization is needed only at merge.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 by preserving the mechanical link between verification evidence and the next required action, instead of leaving delivery as an implicit follow-on that agents can forget.
  Promotion-eligible: yes
  Related: F1, F2
  Phase-1-source: phase1/rules.md:F7
  Verdict: PARTIAL
  Counter-recommendation: Remove only the duplicated detail, not the explicit “completion gate hands off to delivery” rule.

F5: `brainstorm-bead` is not contradictory; `phase = "vapor"` and `pour = true` are both intentional
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:18-26; src/plugins/beads/.agents/skills/start-bead/SKILL.md:249-281
  Category: formula
  Severity: High
  Tier: 2
  Issue: Phase 1 misreads the lifecycle semantics here. `start-bead` Route C explicitly uses `bd mol wisp create brainstorm-bead`, so `phase = "vapor"` is correct. The same route also documents that a `0/0` wisp means the formula is missing `pour = true`, because the brainstorm workflow still needs child step-beads to materialize even though the runtime container is a wisp. Changing this formula to `liquid`, or removing `pour = true`, would break the intended brainstorm handoff model rather than fix it.
  Recommendation: Keep the formula as `phase = "vapor"` with `pour = true`. Clarify the semantics in the formula comment or FORMULAS_PRIMER: `phase` expresses wisp-vs-pour recommendation, while `pour = true` still controls whether executable child steps materialize for that runtime.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitments #1 and #5 by preserving brainstorming as an explicit interactive workflow while still materializing state that survives step-to-step handoff into later lifecycle stages.
  Promotion-eligible: yes
  Related: F3, F4
  Phase-1-source: phase1/formulas.md:F12
  Verdict: DISAGREE
  Counter-recommendation: Clarify the runtime semantics instead of changing the formula mode or removing step materialization.

F6: `poll-ready-beads.sh` is exactly the kind of lifecycle fragility Phase 1 should promote
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:1-30
  Category: script
  Severity: High
  Tier: 2
  Issue: Phase 1 is correct that this script is too flimsy for the queue’s idle-state backbone. `run-queue` depends on it to sleep, wake, and resume implementation autonomously. Positional-only input, mixed JSON/prose stdout, and missing shell safety mean a bad invocation or parse mismatch can stall the queue or produce nonsense exactly when no human is watching.
  Recommendation: Implement the Phase 1 script fixes as a bundle: add a named `--max-minutes` flag and `--help`, add `set -euo pipefail`, keep machine-readable stdout only, and move timeout/interruption diagnostics to stderr. If callers need a timeout payload, emit a JSON sentinel rather than prose.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 because the queue can only make reliable completion and readiness decisions if its polling primitive has a deterministic interface and fail-loud behavior.
  Promotion-eligible: yes
  Related: F1, F3
  Phase-1-source: phase1/scripts.md:F3
  Verdict: AGREE
  Counter-recommendation: None.
