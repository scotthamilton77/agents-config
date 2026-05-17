# Phase 3 By-Category: Rules
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the rules category.
Cross-category findings are noted where applicable.

---

F1: beads.md — I1 and I2 parent-chain invariants should become helper scripts (retain rule text)
  File: src/plugins/beads/.claude/rules/beads.md:21-46
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: I1 (claim walk) and I2 (close walk) loops are multi-line deterministic shell sequences embedded in rule prose. Per Rules Primer, prose-prescribed sequences drift and are harder to maintain than helper scripts. Phase 2 constraint-aware and escalation reviewers both give PARTIAL: the shell blocks should become helper scripts, but the invariants (the requirement that these walks must happen) must stay in the always-loaded rule text.
  Recommendation: Extract I1 and I2 shell sequences to a helper script `bd-walk-parents.sh --mode claim|close <id>`. The rule prose becomes: "Run `bd-walk-parents.sh --mode claim <id>` before starting work; run `--mode close <id>` after closing." The requirement stays; the implementation moves. This is also a Tier 3 extraction candidate per audit scope.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment #5 (persist context across compaction and handoff) — helper scripts survive LLM context limits where prose-embedded sequences can be silently mis-reproduced.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D11)
  Rationale: Phase 2 PARTIAL — retain rule text but move implementation to scripts. Aggregator accepts synthesis.
  Sources: phase1/rules.md:F1, phase2/constraint-aware-execution.md:F4, phase2/escalation-edge-recovery.md:F3

---

F2: beads.md — "bd ready" dual-list filter is a script candidate (Tier 3)
  File: src/plugins/beads/.claude/rules/beads.md:63-68
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The "List 2 — Ready to brainstorm" command contains an inline jq expression that is a deterministic filtering operation. The expression is not obviously readable at a glance, making the rule harder to verify than a named script call.
  Recommendation: Extract to a named helper `bd-ready-to-brainstorm.sh` that wraps the filter. Rule prose references the script name. This provides a stable location if the jq logic needs to change when `bd ready` adds native label-negation support. Also a Tier 3 extraction candidate.
  Vision-advancement-tier: C
  Vision-advancement: Reduces noise and improves clarity by replacing an opaque jq chain with a named, documentable operation.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not specifically address; Phase 1 finding stands.
  Sources: phase1/rules.md:F2

---

F3: beads.md over-length — extract reference material, retain normative runtime contract
  File: src/plugins/beads/.claude/rules/beads.md:1-88
  Category: rule
  Severity: High
  Tier: 2
  Issue: At 88 lines, contains CLI reference, multi-step behavioral guidance, workflow orchestration, usage tables, and session-separation policy. Phase 2 has three PARTIAL verdicts: the runtime contract (I1/I2/I3 summaries, `bd human list` precedence, `human` label semantics, `for-bead-*` probe, session-separation gate, `--notes` destructive-overwrite footgun) must remain always-loaded because `implement-bead` and other skills cite it as authority.
  Recommendation: Retain in always-loaded rule: (a) dangerouslyDisableSandbox requirement, (b) I3 discovered-work placement policy, (c) session-separation gate, (d) `--notes` destructive-overwrite footgun, (e) I1/I2 invariant requirements (not shell sequences — those move to helper scripts per F1), (f) `human` label semantics, (g) `for-bead-*` probe pattern. Extract to a `beads-reference` skill or supporting REFERENCE.md: CLI type/priority glossary, Notes-vs-Comments table, "bd ready" dual-list behavior.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail completion claims) by reducing per-session context load so normative constraints remain prominent and are not buried under reference material.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D11)
  Rationale: Phase 2 PARTIAL × 3; aggregator accepts: retain normative runtime contract, extract reference fluff.
  Sources: phase1/rules.md:F3, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F4, phase2/escalation-edge-recovery.md:F3

---

F4: beads-labels.md — keep semantic table, trim operational command examples
  File: src/plugins/beads/.claude/rules/beads-labels.md:1-36
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends collapsing to a two-sentence stub. Four Phase 2 reviewers give PARTIAL: the label semantic table is behaviorally load-bearing (`implementation-readied-session-*` drives Route A gating, `for-bead-*` is the only reliable bead→molecule lookup edge, `human` defines queue visibility, `ralf:*` labels steer dispatch).
  Recommendation: Keep the compact semantic table for behavior-driving labels in the always-loaded rule (at minimum: `brainstormed`, `implementation-ready`, `implementation-readied-session-*`, `for-bead-*`, `human`, `ralf:required`, `ralf:cycles=N`). Move repetitive command examples and inline jq probe to a helper script or reference file. Do NOT reduce to a two-sentence stub.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment #5 (persist context) — label semantics are the persisted control plane that lets later agents interpret molecule state and escalation state correctly.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D12)
  Rationale: Phase 2 PARTIAL × 4; aggregator accepts: keep semantic table, trim examples/commands.
  Sources: phase1/rules.md:F4, phase2/formula-step-execution.md:F2, phase2/constraint-aware-execution.md:F5, phase2/full-bead-lifecycle.md:F3, phase2/escalation-edge-recovery.md:F3

---

F5: beads/delivery.md — final paragraph uses advisory rather than normative framing
  File: src/plugins/beads/.claude/rules/delivery.md:13-15
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The final paragraph instructs the agent to run `bd show <bead-id>` and `bd mol current <mol-id>` using conditional ("if you arrive at the end... and are uncertain...") framing. Rules should use "always/never" language, not situational prose.
  Recommendation: Reframe as normative: "Never invoke delivery skills as peers of a bead workflow — they run inside molecule steps. Verify step state via `bd mol current <mol-id>` if uncertain." Drop the conditional framing.
  Vision-advancement-tier: C
  Vision-advancement: Tightens normative language and reduces advisory drift in rule prose.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands.
  Sources: phase1/rules.md:F5

---

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

F7: completion-gate.md — keep delivery bridge, remove ordered list duplication
  File: src/user/.claude/rules/completion-gate.md:19-23
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends replacing the HARD STOP paragraph with a one-line pointer. Three Phase 2 reviewers give PARTIAL: the explicit no-pause transition from gate completion to delivery start is load-bearing — agents stop at verification and treat "done" as "report back and wait" without it.
  Recommendation: Keep a compact bridge paragraph stating: (a) gate completion triggers delivery immediately, (b) delivery workflow runs via delivery.md, (c) pause only at merge. Remove the detailed ordered skill list (it duplicates delivery.md) but keep the explicit no-pause transition per D13.
  Vision-advancement-tier: A
  Vision-advancement: Tightens completion gate as a guardrail for commitment #4 (mechanical evidence before completion claims) by preserving the mechanical link between verification evidence and the next required action.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D13)
  Rationale: Phase 2 PARTIAL × 3; aggregator accepts compress-not-remove synthesis.
  Sources: phase1/rules.md:F7, phase2/constraint-aware-execution.md:F6, phase2/full-bead-lifecycle.md:F4, phase2/quality-gate-and-delivery.md:F4

---

F8: completion-gate.md — unqualified skill names (wait-for-pr-comments etc. are not superpowers: skills)
  File: src/user/.claude/rules/completion-gate.md:22
  Category: rule
  Severity: Low
  Tier: 1
  Issue: Skills referenced as `using-git-worktrees`, `finishing-a-development-branch`, `wait-for-pr-comments` without namespace qualifier. However per D3, Phase 2 establishes that `wait-for-pr-comments` and `reply-and-resolve-pr-threads` are NOT superpowers plugin skills — they are shared skills with bare canonical names. Adding `superpowers:` would be actively wrong.
  Recommendation: For `using-git-worktrees` and `finishing-a-development-branch` (which ARE superpowers plugin skills), add `superpowers:` prefix. For `wait-for-pr-comments` and `reply-and-resolve-pr-threads`, keep bare names — they are canonically shared skills.
  Vision-advancement-tier: C
  Vision-advancement: Eliminates silent resolution ambiguity for plugin-scoped skills; preserves correct bare names for shared skills.
  Resolution: ACCEPTED (modified per D3)
  Rationale: Phase 2 DISAGREE on mass-prefixing; aggregator accepts: qualify only actually plugin-scoped skills.
  Sources: phase1/rules.md:F8, phase2/quality-gate-and-delivery.md:F5

---

F9: delegation.md — "Non-trivial work alone is NOT a trigger" is advisory; rewrite as normative
  File: src/user/.claude/rules/delegation.md:9
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "Non-trivial work alone is NOT a trigger for `ralf-implement`" reads as a correction to a misuse pattern rather than a constraint the agent always enforces. Phase 2 multi-agent reviewer AGREE: this should be an explicit hard gate to prevent coordinators from silently stacking orchestration layers.
  Recommendation: Rewrite as normative: "NEVER invoke `ralf-implement` unless the user explicitly requests it with a target, DoD, and context."
  Vision-advancement-tier: C
  Vision-advancement: Sharpens normative language, making the constraint clearly enforceable.
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (multi-agent:F13).
  Sources: phase1/rules.md:F9, phase2/multi-agent-dispatch.md:F13

---

F10: delegation.md — codex-routing.md cross-reference is valid (informational)
  File: src/user/.claude/rules/delegation.md:13
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "see `codex-routing.md`" is a valid cross-reference. No substantive issue; optional precision improvement: "see `codex-routing.md` (Model selection)."
  Recommendation: No change required. Optional improvement: add "(Model selection)" precision anchor.
  Vision-advancement-tier: C
  Vision-advancement: No change; finding confirms reference hygiene is correct.
  Resolution: DROPPED
  Rationale: No action required — informational finding with no defect. Dropped to reduce noise.
  Sources: phase1/rules.md:F10

---

F11: codex-routing.md — hardcoded plugin install path will drift
  File: src/user/.claude/rules/codex-routing.md:7-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Invocation block hardcodes `$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex` — a Claude Code marketplace path subject to change without notice. If the marketplace reorganizes, all agents following this rule silently break.
  Recommendation: Move the resolved path into a settings.json env var (e.g., `CODEX_PLUGIN_HOME`) so agents reference `$CODEX_PLUGIN_HOME` and the path is configured at install time. Alternatively, extract path resolution to a helper script `scripts/codex-invoke.sh` that handles fallback logic.
  Vision-advancement-tier: A
  Vision-advancement: Directly advances commitment #5 (persist context across agent handoff and overnight runs) — hardcoded plugin paths that drift cause silent delegation failures in autonomous overnight runs.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F11

---

F12: codex-routing.md — model names are time-sensitive and will rot
  File: src/user/.claude/rules/codex-routing.md:13-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Model selection table hardcodes `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex-spark`. Rules are always-loaded; when model names change, this rule will silently route to deprecated models. Cost ratios are also time-sensitive.
  Recommendation: Abstract model names behind aliases defined in a companion config or settings.json (`CODEX_MODEL_FULL`, `CODEX_MODEL_MINI`, `CODEX_MODEL_SPARK`). At minimum, add a note: "Model names current as of 2026-05; verify against `codex:status` or plugin changelog if encountering 'model not found' errors."
  Vision-advancement-tier: A
  Vision-advancement: Prevents silent routing failures in autonomous overnight runs caused by deprecated model names in always-loaded rules.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F12

---

F13: git-commits.md — exemplary rule; no issues (informational)
  File: src/user/.claude/rules/git-commits.md:1-9
  Category: rule
  Severity: Low
  Tier: 1
  Issue: No substantive issues. 9 lines, single-purpose, normative ("NEVER use heredoc syntax"), consequence-grounded, three ranked alternatives. Model form for a rule file.
  Recommendation: No change required. Reference as the target form for other rule files.
  Vision-advancement-tier: C
  Vision-advancement: Confirms the pattern — concise, normative, consequence-grounded rules lower the failure rate of mechanical operations in autonomous runs.
  Resolution: DROPPED
  Rationale: Informational finding; no defect. Dropped to reduce noise.
  Sources: phase1/rules.md:F13

---

F14: subagents.md — consequence grounding missing from both constraints
  File: src/user/.claude/rules/subagents.md:1-7
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "verify worktree cleanup and branch locks before proceeding" and "Do not send messages to already-terminated ephemeral agents" are valid normative constraints without consequence clauses ("because X will happen if violated"). Per Rules Primer, authority grounding makes constraints self-explanatory and more resilient to pressure.
  Recommendation: Expand with one-line rationale: "…before proceeding — orphaned worktrees block future `git worktree add` calls with the same name." And: "…check agent status first — sending messages to terminated agents causes silent no-ops or harness errors that look like successful dispatches."
  Vision-advancement-tier: C
  Vision-advancement: Consequence grounding makes constraints self-explanatory, reducing the chance an agent omits the check when it seems inconvenient.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F14

---

F15: worktrees.md — Override clause ambiguous about when it applies
  File: src/user/.claude/rules/worktrees.md:5-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The rule states "Preferred: Use Claude Code's native EnterWorktree tool" then "Override: The superpowers using-git-worktrees skill defaults to .worktrees/... Disregard that default." The structure doesn't make explicit that the Override only applies when using the skill, not when using EnterWorktree.
  Recommendation: Restructure to make three cases explicit: (1) Using EnterWorktree tool → no override needed; it places worktrees at the correct location. (2) Manually creating worktrees → use `git worktree add .claude/worktrees/<name> -b <branch>`. (3) If superpowers:using-git-worktrees skill suggests .worktrees/ → disregard; use .claude/worktrees/ instead.
  Vision-advancement-tier: C
  Vision-advancement: Eliminates worktree placement confusion that causes agents to retry or escalate unnecessarily on worktree creation failures.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F15

---

F16: worktrees.md — EnterWorktree tool reference needs Claude Code scope qualifier
  File: src/user/.claude/rules/worktrees.md:5
  Category: rule
  Severity: Low
  Tier: 1
  Issue: `EnterWorktree` is a Claude Code-only construct. The RULES_PRIMER notes that rules should be "tool-agnostic in spirit" with intent to embed content into other tool AGENTS.md files. The reference reads as a universal recommendation with no qualifier.
  Recommendation: Add a single parenthetical: "Use Claude Code's native `EnterWorktree` tool (Claude Code only) — it places worktrees here automatically."
  Vision-advancement-tier: C
  Vision-advancement: Ensures the rule remains coherent when embedded into Codex or Gemini AGENTS.md files via the future cross-tool embedding pipeline.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F16

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

## Cross-Category References

- F24 (human-label semantics contradiction): canonical entry in skills.md by-category; this file's F4 (beads-labels.md) is related — label semantic contract must match across rules and formulas
- F7 (completion-gate delivery bridge): related to delivery.md by-file which captures the same finding from the delivery-rule perspective
