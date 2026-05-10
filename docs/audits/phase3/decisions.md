# Phase 3 Decisions Log
Aggregator: claude-sonnet-4-6
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Generated: 2026-05-10

This log records every conflict-resolution decision required for Phase 2 findings with Verdict: DISAGREE or PARTIAL (28 total), plus OOS promotions, tier1-promotions, tierC-demotions, and other aggregator decisions.

---

## DISAGREE Resolutions (6 findings)

---

D1: brainstorm-bead vapor+pour — DISAGREE upheld; Phase 2 wins
  Type: conflict-resolution
  Sources: phase1/formulas.md:F12, phase2/formula-step-execution.md:F6, phase2/full-bead-lifecycle.md:F5, phase2/escalation-edge-recovery.md:F4
  Resolution: dropped (Phase 1 recommendation dropped; Phase 2 analysis accepted)
  Rationale: Three independent Phase 2 reviewers (formula-step-execution, full-bead-lifecycle, escalation-edge-recovery) all DISAGREE with Phase 1's recommendation to change `phase = "vapor"` to `phase = "liquid"`. The escalation reviewer provides the most specific evidence: `start-bead` Route C explicitly uses `bd mol wisp create brainstorm-bead`, and the `0/0` failure mode documented in `start-bead` SKILL.md is caused precisely by a missing `pour = true`. The two fields are orthogonal, not contradictory: `phase = "vapor"` signals wisp-mode interactive use, `pour = true` causes step materialization within that wisp. Changing to `phase = "liquid"` would break the documented `start-bead` Route C contract. The aggregator accepts Phase 2's verdict. The recommendation becomes: add a comment in the formula header explaining the intentional vapor-plus-poured-wisp combination, and update the FORMULAS_PRIMER to document this valid configuration. This is Tier 2 (documentation clarification), not a fix to the formula fields themselves.

---

D2: bd-record-decision.sh stdout contract — DISAGREE upheld; Phase 2 wins
  Type: conflict-resolution
  Sources: phase1/scripts.md:F2, phase2/formula-step-execution.md:F4
  Resolution: dropped (Phase 1 recommendation to change default stdout dropped)
  Rationale: Phase 2's formula-step-execution reviewer correctly observes that the formula callsite in `brainstorm-bead` does not parse stdout — it reads the human-readable sentence as immediate confirmation. Changing the default stdout contract would optimize for a caller model not present on the actual runtime path. The aggregator accepts Phase 2: add an opt-in `--json` mode only if a concrete structured caller appears. The usage/help improvement (Phase 1 F1) is still accepted as Tier 1. The stdout-contract redesign (Phase 1 F2) is dropped.

---

D3: superpowers: namespace prefix for delivery-chain skills — DISAGREE upheld; Phase 2 wins
  Type: conflict-resolution
  Sources: phase1/rules.md:F8, phase1/rules.md:F17, phase2/quality-gate-and-delivery.md:F5
  Resolution: dropped (Phase 1 recommendation to add superpowers: prefix dropped)
  Rationale: Phase 2's quality-gate reviewer provides definitive evidence: `wait-for-pr-comments` and `reply-and-resolve-pr-threads` are shared skills in `src/user/.agents/skills/` with bare canonical names — they are NOT superpowers plugin skills. Applying the `superpowers:` prefix would actively misname the actual delivery chain and make it less addressable. The aggregator drops Phase 1 F8 and F17. Rules should continue to reference these skills by their bare names. The underlying concern (latent ambiguity if future plugins introduce same-named skills) is valid but lower priority than the active-harm risk of mislabeling the current chain. F8 and F17 are dropped entirely.

---

D4: Dolt/SQLite constraint placement — Phase 2 PARTIAL accepted over Phase 1
  Type: conflict-resolution
  Sources: phase1/templates.md:F13, phase2/constraint-aware-execution.md:F3
  Resolution: merged (synthesis accepted; neither pure Phase 1 nor pure Phase 2)
  Rationale: Phase 1 recommends moving the Dolt-specific constraint out of shared INSTRUCTIONS.md.template to beads-only rules. Phase 2 correctly counters that Codex and Gemini have no beads rules today, so moving it would create a database-safety blind spot for those tools right when they are most vulnerable (no rule parity yet). The aggregator synthesizes: keep the database-safety constraint in INSTRUCTIONS.md.template but reword it to lead with the generic principle and add "for example, Dolt or SQLite" as illustration, not as the primary framing. The beads plugin then adds its Dolt-specific reinforcement as an additive rule. This satisfies both Phase 1's hygiene goal and Phase 2's cross-tool safety requirement.

---

D5: bead-implementor model tier — Phase 2 DISAGREE accepted; Phase 1 finding deferred
  Type: conflict-resolution
  Sources: phase1/agents.md:F4, phase2/multi-agent-dispatch.md:F8
  Resolution: deferred (Phase 1 finding deferred; resolve after dispatch topology settled)
  Rationale: Phase 2's multi-agent reviewer correctly points out that `bead-implementor` is not dispatched by `implement-bead`'s stage map at all — the canonical dispatches go to `bug-diagnoser`, `tdd-red-team`, `tdd-green-team`. Tuning `bead-implementor`'s model tier before the topology question is settled would harden a non-canonical path. The aggregator defers Phase 1 F4: model tuning is not actionable until F11 (bead-implementor vs dedicated worker trio) is resolved.

---

D6: INSTRUCTIONS.md.template self-improving-agent/verify-checklist genericization — Phase 2 PARTIAL accepted
  Type: conflict-resolution
  Sources: phase1/templates.md:F5, phase2/constraint-aware-execution.md:F2
  Resolution: merged (synthesis: genericize only Claude-specific phrasing, not the skill names)
  Rationale: Phase 1 recommends replacing concrete skill names with generic prose. Phase 2 correctly counters that `self-improving-agent` and `verify-checklist` are shared skills in `src/user/.agents/skills/` — not Claude-only. Removing their names would weaken always-loaded triggers that already have portable implementations. The aggregator's synthesis: (a) keep the named skill triggers `self-improving-agent` and `verify-checklist` in the shared template; (b) replace "Plan mode" (Claude-specific feature name) with "planning phase" or "structured planning"; (c) add "when available" softener to skills that genuinely depend on tool support. This is Tier 2 (moderate edit, not mechanical).

---

## PARTIAL Resolutions (22 findings)

---

D7: wait-for-pr-comments beads leakage — split-not-move synthesis
  Type: conflict-resolution
  Sources: phase1/skills.md:F3, phase2/full-bead-lifecycle.md:F1, phase2/quality-gate-and-delivery.md:F2
  Resolution: merged (Phase 1 direction modified: split, not wholesale move)
  Rationale: Phase 1 recommends moving the entire skill to `src/plugins/beads/`. Two Phase 2 reviewers (full-bead-lifecycle, quality-gate-and-delivery) both give PARTIAL verdicts with the same counter: the delivery rule treats `wait-for-pr-comments` as canonical for all non-trivial work, not just bead work; moving it wholesale would strand non-bead delivery flows. The aggregator accepts the synthesis from both reviewers: keep a shared PR-review core (detection, Copilot polling, classification, FIX execution, inventory handoff, interactive mode); isolate beads-specific behavior (autonomous mode, `--bead-id`, `bd` escalation filing, I3-based DEFER placement) in a beads-plugin addendum or wrapper. This is a non-trivial design task — Tier 2.

---

D8: reply-and-resolve-pr-threads beads leakage — same split-not-move synthesis
  Type: conflict-resolution
  Sources: phase1/skills.md:F4, phase2/full-bead-lifecycle.md:F2, phase2/quality-gate-and-delivery.md:F2
  Resolution: merged (mirror of D7; split not move)
  Rationale: Mirrors D7. Two Phase 2 reviewers apply the same analysis. Keep shared thread-reply/resolution engine and inventory-driven execution in shared content. Move only autonomous recovery persistence and `--bead-id` handling into a beads-specific extension or wrapper. Tier 2.

---

D9: validate-inventory.sh cross-skill reference — shared support path, not copy
  Type: conflict-resolution
  Sources: phase1/skills.md:F11, phase2/quality-gate-and-delivery.md:F3
  Resolution: merged (Phase 1 direction modified: shared location, not per-skill copy)
  Rationale: Phase 1 recommends copying or symlinking `validate-inventory.sh` into `reply-and-resolve-pr-threads/` directory. Phase 2 correctly counters that duplicating the validator creates two contract-ownership surfaces that can drift. The aggregator accepts Phase 2's alternative: move `validate-inventory.sh` to a shared support location (e.g., `src/user/.agents/skills/shared/` or a new `wait-for-pr-comments-shared/` directory) and have both skills reference it from the shared path. Tier 2 (requires new directory structure decision).

---

D10: wait-for-pr-comments SKILL.md progressive disclosure — keep chain facts inline
  Type: conflict-resolution
  Sources: phase1/skills.md:F1, phase2/quality-gate-and-delivery.md:F1
  Resolution: merged (partial extraction; core chain facts remain in SKILL.md)
  Rationale: Phase 1 recommends extracting schema, subagent contract, and recovery to separate files. Phase 2 AGREE on the principle but specifies what must stay: Phase 8 default-on chain, inventory ownership, recovery entrypoints, the phase map. The aggregator synthesizes: extract detailed schema prose and recovery branch tables to SCHEMA.md and RECOVERY.md; keep the phase map, Phase 8 default-on chain instruction, inventory ownership statement, and recovery entrypoints in SKILL.md. Schema validation guards go to one canonical location (SCHEMA.md) cross-referenced by both skills.

---

D11: beads.md rule refactoring — retain runtime contract, trim reference clutter
  Type: conflict-resolution
  Sources: phase1/rules.md:F3, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F4, phase2/escalation-edge-recovery.md:F3
  Resolution: merged (trim reference clutter; keep runtime invariants)
  Rationale: Phase 1 recommends large-scale extraction of beads.md reference content to skill/reference files. Three Phase 2 reviewers all give PARTIAL: the runtime contract (I1, I2, I3, session-separation, `--notes` footgun, `human` label semantics, `for-bead-*` probe, `bd human list` precedence) must remain in always-loaded context because `implement-bead` and other skills cite these rules as authority during execution. The aggregator accepts the Phase 2 constraint: keep the normative invariants; extract CLI type/priority glossary, Notes-vs-Comments table, and "bd ready" dual-list behavior to a `beads-reference` skill or supporting file. Script extraction (I1/I2 shell sequences → helper scripts) proceeds, but the invariant prose remains in the rule.

---

D12: beads-labels.md rule refactoring — keep semantic table, trim command examples
  Type: conflict-resolution
  Sources: phase1/rules.md:F4, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F5, phase2/full-bead-lifecycle.md:F3, phase2/escalation-edge-recovery.md:F3
  Resolution: merged (keep semantic table; trim operational command examples)
  Rationale: Four Phase 2 reviewers all give PARTIAL on Phase 1's recommendation to collapse this to a two-sentence stub. Consistent evidence: the label semantic table (`implementation-readied-session-*`, `for-bead-*`, `human`, `ralf:required`, `ralf:cycles=N`) is behaviorally load-bearing — it drives Route A gating, bead→molecule lookup, queue visibility, and orchestration dispatch. The aggregator keeps the semantic table always-loaded; trims the repetitive command examples and inline jq probe to a reference file or helper script.

---

D13: completion-gate.md delivery bridge — keep bridge, trim detail
  Type: conflict-resolution
  Sources: phase1/rules.md:F7, phase2/constraint-aware-execution.md:F6, phase2/full-bead-lifecycle.md:F4, phase2/quality-gate-and-delivery.md:F4
  Resolution: merged (keep explicit bridge; remove ordered skill list duplication)
  Rationale: Phase 1 recommends replacing the HARD STOP paragraph with a one-line pointer. Three Phase 2 reviewers all give PARTIAL with the same counter: the explicit hand-off bridge from gate completion to delivery start is load-bearing — without it, agents stop at verification and treat "done" as "report back and wait." The aggregator's synthesis: keep a compact bridge paragraph stating (a) gate completion triggers delivery immediately, (b) the delivery workflow runs via `delivery.md`, (c) pause only at merge. Remove the detailed ordered skill list from completion-gate.md (it duplicates delivery.md) but keep the explicit no-pause transition. Tier 2 (moderate edit).

---

D14: implement-bead dense prose — rewrite as tables inline, not extraction to reference file
  Type: conflict-resolution
  Sources: phase1/skills.md:F5, phase2/multi-agent-dispatch.md:F2
  Resolution: merged (rewrite inline as tables/lists; do not move routing contract to RESOLUTION.md)
  Rationale: Phase 1 recommends extracting the dense paragraphs to a `RESOLUTION.md` reference file. Phase 2 counters that the dispatch contract (formula selection, human-flag branches, stage→agent mapping, worker-report outcome handling) is the minimum viable instruction surface for a top-level dispatcher — moving it to a reference file would reduce the context the orchestrator must have in hand before spawning workers. The aggregator accepts Phase 2: rewrite dense prose as decision tables and numbered branches, but keep them in SKILL.md. Extract only historical rationale and long explanatory parentheticals. Tier 2.

---

D15: implement-bead formula-label parsing duplication — share expression, keep state-specific branches
  Type: conflict-resolution
  Sources: phase1/skills.md:F6, phase2/escalation-edge-recovery.md:F2
  Resolution: merged (share the parsing expression; preserve two explicit flag-human branches)
  Rationale: Phase 1 treats the two parsing blocks as equivalent. Phase 2 identifies they guard different recovery states: pre-pour vs post-pour. The aggregator synthesizes: extract the low-level label-parsing shell expression to a single named block, but keep the pre-pour and post-pour escalation branches explicit at their call sites with their state-specific behavior intact. Tier 2.

---

D16: start-bead progressive disclosure — keep routing logic inline, trim forensics
  Type: conflict-resolution
  Sources: phase1/skills.md:F17, phase2/multi-agent-dispatch.md:F5, phase2/escalation-edge-recovery.md:F1
  Resolution: merged (trim verbose forensics; keep routing matrix and recovery branches inline)
  Rationale: Phase 1 recommends extracting Route Z and the routing decision table. Two Phase 2 reviewers give PARTIAL: the routing matrix is the dispatch contract; Route Z contains the recovery rules (forwarded beads, dangling labels, 0/0 burn) needed before the agent can make a safe routing decision. The aggregator: keep Step 1.5, molecule-ambiguity escalation, 0/0 burn recovery, post-brainstorm hand-off stop, and the route selection logic in SKILL.md. Extract only the verbose audit-comment templates and repetitive examples. Tier 2.

---

D17: formula preflight shared extraction — share mechanics only, keep policy inline
  Type: conflict-resolution
  Sources: phase1/formulas.md:F14, phase2/escalation-edge-recovery.md:F5
  Resolution: merged (extract mechanical steps; keep coverage/reroute policy per-formula)
  Rationale: Phase 1 proposes a single `bd-preflight.sh` across docs-only, fix-bug, implement-feature. Phase 2 correctly notes docs-only is the reroute target and deliberately skips coverage gates — a shared helper would collapse this formula-specific divergence. The aggregator accepts Phase 2: extract only mechanically identical parts (lookup-label stamp, worktree creation, path encoding/decoding, claim-walk); keep coverage/gates policy and human-flag-vs-skip behavior inside each formula. Tier 2 (narrower than Phase 1 proposed).

---

D18: reroute helper extraction — extract mechanics but keep postcondition checklist
  Type: conflict-resolution
  Sources: phase1/formulas.md:F5, phase2/formula-step-execution.md:F3
  Resolution: merged (extract mechanics; inline postcondition checklist stays in each red-tests step)
  Rationale: Phase 1 recommends collapsing to "evaluate triggers, call script, exit." Phase 2 correctly identifies this as too thin: reroute is irreversible and the step-bead must contain invariants for the agent to verify after the helper runs. The aggregator synthesizes: extract the ~90 lines of mechanical steps into `bd-reroute-to-docs-only.sh`, but keep an inline postcondition checklist in both red-tests steps specifying the required surviving invariants. Tier 2.

---

D19: tech-lead agent filesystem scan — generalize beyond path portability
  Type: conflict-resolution
  Sources: phase1/agents.md:F8, phase2/multi-agent-dispatch.md:F11
  Resolution: merged (deeper generalization than Phase 1 proposed)
  Rationale: Phase 1 recommends replacing `.claude/agents/*` with a generic fallback. Phase 2 raises the deeper issue: filesystem scanning is the wrong source of truth entirely — the reliable contract surface is the caller-provided callable roster. The aggregator accepts the Phase 2 framing: replace "scan `.claude/agents/*`" with "use the caller-provided roster of callable agents; if not provided, inspect the current tool's agent registry or directory as a fallback." Tier 2.

---

D20: quality-reviewer memory — keep memory: project, add protocol
  Type: conflict-resolution
  Sources: phase1/agents.md:F6, phase2/quality-gate-and-delivery.md:F6
  Resolution: merged (keep memory: project; add narrow schema and eviction horizon)
  Rationale: Phase 1 recommends removing `memory: project` or adding a protocol. Phase 2 argues for keeping project memory because the reviewer accumulates recurring-pattern context that strengthens the gate across repeated PR cycles. The aggregator accepts Phase 2: keep `memory: project` and add a "Memory Protocol" section specifying categories (recurring vulnerability patterns, project-specific anti-patterns), max horizon (e.g., 30 reviews), and an eviction rule. Tier 2.

---

D21: INSTRUCTIONS.md.template context7 reference — genericize but keep directive
  Type: conflict-resolution
  Sources: phase1/templates.md:F14, phase2/constraint-aware-execution.md (implied by F3 pattern)
  Resolution: accepted (Phase 1 recommendation accepted with Tier 1 promotion)
  Rationale: Phase 2 constraint-aware reviewer did not directly address F14, but the same portability logic from F2/F3 applies: `context7` is an MCP plugin name that may not be available on Codex/Gemini/OpenCode. Phase 1's recommendation to genericize ("via available documentation tools (e.g., context7 MCP if available, or web search)") is sound and does not weaken the constraint. Promoting to Tier 1 — the change is mechanical. See D22 for tier1-promotion record.

---

D22: context7 reference genericization — Tier 1 promotion
  Type: tier1-promotion
  Sources: phase1/templates.md:F14
  Resolution: promoted-to-tier1
  Rationale: The change is purely mechanical: replace one tool-specific name with a generic description plus parenthetical example. No design judgment required. The before text is confirmed present at AUDIT_INPUT_SHA via git grep.
  Snippet:
    Before: look up docs via context7 before using it
    After:  look up current docs via available documentation tools (e.g., context7 MCP if available, or web search) before using it

---

D23: brainstorm-bead vapor+pour documentation clarification — Tier 2 only (no formula change)
  Type: conflict-resolution
  Sources: phase1/formulas.md:F12, phase2/formula-step-execution.md:F6, phase2/full-bead-lifecycle.md:F5, phase2/escalation-edge-recovery.md:F4
  Resolution: deferred
  Rationale: See D1. The formula fields themselves are correct. The finding converts to a Tier 2 documentation task: add a comment in brainstorm-bead.formula.toml header explaining the intentional vapor-plus-poured-wisp semantics, and update FORMULAS_PRIMER.md to document this as a valid configuration. Tier 2, not Tier 1, because it requires choosing wording that accurately explains the orthogonal semantics.

---

D24: HARD STOP delivery bridge retention — bridge compressed not removed
  Type: conflict-resolution
  Sources: phase1/rules.md:F7, phase2/constraint-aware-execution.md:F6, phase2/full-bead-lifecycle.md:F4, phase2/quality-gate-and-delivery.md:F4
  Resolution: merged
  Rationale: See D13. Recorded separately to confirm this is the authoritative resolution for all four Phase 2 findings touching completion-gate delivery bridge.

---

D25: human-label gating contradiction — Phase 2 F8 (escalation) new finding, AGREE promoted
  Type: oos-promotion
  Sources: none (new aggregator synthesis from phase2/escalation-edge-recovery.md:F8)
  Resolution: accepted
  Rationale: Phase 2 escalation reviewer found that two formulas (docs-only, implement-feature) say `human` label excludes a bead from `bd ready`, while `beads-labels.md` says `human` is only a visibility tag and does NOT gate readiness. This is an active contradiction: an agent can believe work is safely parked when it may still surface as ready. This is a genuine finding not captured in Phase 1 (which only audited label semantics, not the formula/rule contract mismatch). The aggregator promotes it as a new finding: pick one contract and update all touched files. Tier 1 if the rule is the authority (update formulas to say "add a blocking dep, not just human label"); Tier 2 if the contract needs design discussion. Given the design implications, marking as Tier 2.

---

D26: run-queue/implement-bead escalation-resolution mismatch — Phase 2 escalation F9 promoted
  Type: oos-promotion
  Sources: none (phase2/escalation-edge-recovery.md:F9 not covered by any Phase 1 finding)
  Resolution: accepted
  Rationale: `run-queue` resolves escalations by removing `human` from `<id>`, but `implement-bead` stamps both source bead and step-bead and may require a step reopen. Clearing one label ad hoc can requeue half-recovered work. This is a genuine gap not in Phase 1. Aggregator promotes as a new Tier 2 finding.

---

D27: OOS graphify update subagent qualifier — promoting from OOS
  Type: oos-promotion
  Sources: none (phase2/multi-agent-dispatch.md:OOS1; also phase1/templates.md:F11 which covers same issue)
  Resolution: merged into phase1/templates.md:F11
  Rationale: The OOS observation from multi-agent-dispatch reviewer is substantively identical to Phase 1 templates:F11. Rather than creating a duplicate finding, the aggregator notes that the Phase 2 OOS reinforces Phase 1 F11 and adds the multi-agent-dispatch angle (subagent coordination hazard). Phase 1 F11 resolution: ACCEPTED, strengthened by Phase 2 confirmation.

---

D28: OOS bd-dolt-push beads integration — reinforces Phase 1 finding
  Type: oos-promotion
  Sources: none (phase2/constraint-aware-execution.md:OOS1; mirrors phase1/templates.md:F15)
  Resolution: merged into phase1/templates.md:F15
  Rationale: The OOS from constraint-aware reviewer is substantively identical to Phase 1 templates:F15. The aggregator notes that Phase 2 OOS reinforces Phase 1 F15 and extends coverage to the delivery-constraint lens. Phase 1 F15: ACCEPTED.

---

D29: OOS Codex/Gemini completion-gate template gap — reinforces Phase 1 finding
  Type: oos-promotion
  Sources: none (phase2/quality-gate-and-delivery.md:OOS1; mirrors phase1/templates.md:F1)
  Resolution: merged into phase1/templates.md:F1
  Rationale: The OOS from quality-gate reviewer reinforces Phase 1 templates:F1. The aggregator notes that Phase 2 OOS adds the quality-gate lens (removes completion-gate and delivery implementation path for those tools entirely). Phase 1 F1: ACCEPTED, strengthened.

---

## Tier-C Cap Enforcement

Total ACCEPTED findings post-merge/drop analysis:

Counting vision-advancement tiers across all ACCEPTED findings (see REMEDIATION_PLAN.md for exact counts).

After initial acceptance:
- Tier A: 57 findings
- Tier B: 4 findings
- Tier C: 27 findings
- Total: 88 findings
- Tier C share: 27/88 = 30.7% — marginally exceeds 30% cap

Applying demotion algorithm (ascending severity, descending document order within file):

D30: F18 from rules.md — tierC-demotion (Low, delivery.md inline gh commands)
  Type: tierC-demotion
  Sources: phase1/rules.md:F18
  Resolution: dropped
  Rationale: Low-severity tier-C finding about converting a two-command inline block to a helper script in delivery.md. The block is borderline (two commands is not egregious), the impact on autonomous operation is marginal, and Phase 2 did not specifically address this finding. Demoting to DROPPED reduces Tier C share to 26/87 = 29.9%, which satisfies the cap.

---

D31: brainstorm-bead discuss step QUESTION FILTER — DISAGREE upheld; keep self-contained
  Type: conflict-resolution
  Sources: phase2/formula-step-execution.md:F1
  Resolution: dropped (Phase 1 recommendation to replace QUESTION FILTER with back-reference dropped; Phase 2 analysis accepted)
  Rationale: Phase 2 formula-step-execution reviewer DISAGREE with Phase 1's recommendation (phase1/formulas.md:F3) to replace the QUESTION FILTER in the discuss step with a cross-reference to the assess step. The Phase 2 analysis is correct: the discuss step-bead is executed as its own standalone prompt. A resumed or compacted session may have the discuss bead in context without the assess text in active context — removing the inline filter strips the live guardrail that tells the executing agent which questions belong to the user vs. which decisions it must make itself. The aggregator accepts Phase 2's verdict. The resolution converts to a narrow Tier 2 improvement task: tighten the QUESTION FILTER wording (reduce to 3-4 tight lines) inside the discuss step itself, rather than replacing it with a back-reference. The filter must remain fully self-contained. See formulas.md by-category F3 for the consolidated finding.

---

## Summary of Decision Types

| Type | Count |
|------|-------|
| conflict-resolution (DISAGREE) | 3 (D1, D2, D3) |
| conflict-resolution (PARTIAL) | 16 (D4–D19, D31) |
| tier1-promotion | 1 (D22) |
| oos-promotion | 5 (D25, D26, D27, D28, D29) |
| tierC-demotion | 1 (D30) |

Total decisions: 26
