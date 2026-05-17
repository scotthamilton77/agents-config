# Phase 1 Audit: Rules
Auditor: audit-rules subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 10 rule files (6 user-scoped, 4 beads-plugin)

---

## Drift check

Both commands confirmed empty — no drift from audit SHA.

---

## Findings

---

F1: beads.md — parent-chain invariants I1 and I2 are inline shell sequences that should be helper scripts
  File: src/plugins/beads/.claude/rules/beads.md:21-46
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The I1 (claim walk) and I2 (close walk) loops are multi-line deterministic shell sequences embedded in rule prose. Per the Rules Primer best practice, prose-prescribed sequences drift and are harder to maintain than helper scripts. Both sequences are parameterized only by `<id>`, making them ideal helper-script candidates. The sequences also appear verbatim in the FORMULAS_PRIMER.md (which cites them as authoritative), meaning two canonical copies must stay in sync manually. A `bd-walk-parents.sh --mode claim|close <id>` script would unify both occurrences.
  Recommendation: Extract I1 and I2 into a helper script (e.g., `src/plugins/beads/.claude/rules/scripts/bd-walk-parents.sh`) with `--mode claim|close` parameter. The rule prose becomes: "Run `bd-walk-parents.sh --mode claim <id>` before starting work; run `--mode close <id>` after closing." Keep the two-line conceptual statement; remove the inline bash.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment 5 (persist context across compaction and handoff) — helper scripts survive LLM context limits and session resets where prose-embedded sequences can be silently mis-reproduced.
  Promotion-eligible: yes
  Related: F2

---

F2: beads.md — "bd ready" dual-list filter is an inline jq sequence that should be a helper script
  File: src/plugins/beads/.claude/rules/beads.md:63-68
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The "List 2 — Ready to brainstorm" command contains an inline jq expression (`bd ready --json | jq '[.[] | select(.labels | index("implementation-ready") | not)]'`) that is a deterministic filtering operation. The Rules Primer flags inline shell sequences as script candidates. The expression is not obviously readable at a glance, making the rule harder to verify than a named script call.
  Recommendation: Extract to a named helper `bd-ready-to-brainstorm.sh` that wraps the filter. Rule prose references the script name. This also provides a stable location if the jq logic needs to change when `bd ready` adds native label-negation support.
  Vision-advancement-tier: C
  Vision-advancement: Reduces noise and improves clarity by replacing an opaque jq chain with a named, documentable operation.
  Promotion-eligible: yes
  Related: F1

---

F3: beads.md — over-length for a rule; substantial content belongs in a skill
  File: src/plugins/beads/.claude/rules/beads.md:1-88
  Category: rule
  Severity: High
  Tier: 2
  Issue: At 88 lines, beads.md contains: CLI reference (command types, priority enum), multi-step behavioral guidance (I1, I2, I3), workflow orchestration ("bd ready" behavior), usage tables (notes vs comments), and session-separation policy. The Rules Primer states: "If a rule has grown to 5+ steps of methodology, the methodology belongs in a skill." This file contains at least three independent methodologies. Rules are always-loaded constraints — the full bd CLI reference, "Notes vs Comments" table, and "bd ready" dual-list behavior do not need to be in context every session; they are invoked only when actually working with beads. The genuinely normative content (I3 placement policy, session-separation policy, `--json` footgun warning, `dangerouslyDisableSandbox` requirement) could fit in under 20 lines.
  Recommendation: Extract the reference material (CLI types/priority, Notes vs Comments table, "bd ready" dual-list behavior, I1/I2 shell sequences) into a skill or reference file invoked by the beads workflow. The rule retains: (a) the `dangerouslyDisableSandbox` requirement, (b) I3 discovered-work placement policy (normative), (c) session-separation gate (normative), (d) the `--notes` destructive-overwrite footgun warning. Everything else moves to a `beads-reference` skill or supporting REFERENCE.md.
  Vision-advancement-tier: A
  Vision-advancement: Directly advances commitment 4 (guardrail every completion claim) by reducing per-session context load so the always-loaded normative constraints remain prominent and don't get buried under reference material the agent won't need in most sessions.
  Promotion-eligible: yes
  Related: F1, F2

---

F4: beads-labels.md — label reference table is advisory reference, not normative constraint
  File: src/plugins/beads/.claude/rules/beads-labels.md:1-36
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The file is a label glossary and molecule-linkage reference. The label table describes what labels exist and who sets them — useful reference, but not a normative constraint the agent must obey every session. The "Molecule → Bead Linkage" section is an operational protocol (stamp a label after pour/wisp), but it's only relevant when creating molecules, not every session. The `bd ready --label` and inline `jq` filter commands at the bottom are operational sequences. None of this rises to "normative always-applicable constraint" as the Rules Primer defines it. The genuinely normative content is the single obligation: always stamp `for-bead-<bead-id>` immediately after molecule creation.
  Recommendation: Collapse to a two-sentence normative rule: "Always stamp `bd label add <mol-id> for-bead-<bead-id>` immediately after `bd mol pour` or `bd mol wisp create`. Always use `--json` (not tree mode) when filtering by `--type molecule --label`." Move the label glossary table to a `beads-labels-reference.md` file or into the beads skill's REFERENCE.md. Trim the inline jq sequence (same helper-script candidacy as F1/F2).
  Vision-advancement-tier: A
  Vision-advancement: Supports commitment 5 (persist context) by trimming reference material from always-loaded context, keeping the per-session footprint minimal and the normative obligations visible.
  Promotion-eligible: yes
  Related: F1, F2, F3

---

F5: beads/delivery.md — plugin addendum correctly extends but references `bd show <bead-id>` and `bd mol current <mol-id>` as operational lookups every session
  File: src/plugins/beads/.claude/rules/delivery.md:13-15
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The final paragraph instructs the agent to run `bd show <bead-id>` and `bd mol current <mol-id>` when uncertain whether delivery has run. This is procedurally correct, but framing it as a rule clause makes it an always-loaded instruction for a situation that only arises at step-boundary uncertainty. The substance is fine; the vehicle adds marginal cost to every session. No active conflict with user-level delivery.md found — the plugin addendum is purely additive and consistent with base content: delivery runs inside molecule steps, not as a peer workflow.
  Recommendation: Reframe as a brief normative statement: "Never invoke delivery skills as peers of a bead workflow — they run inside molecule steps. Verify step state via `bd mol current <mol-id>` if uncertain." Drop the conditional framing ("if you arrive at the end of a molecule step and are uncertain…") — rules use "always/never", not situational prose.
  Vision-advancement-tier: C
  Vision-advancement: Tightens normative language and reduces advisory drift in rule prose.
  Promotion-eligible: yes

---

F6: Two delivery.md files — duplication and precedence ambiguity
  File: src/user/.claude/rules/delivery.md:1-44 and src/plugins/beads/.claude/rules/delivery.md:1-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Per the RULES_PRIMER install model, same-named rule files are appended (base first, plugins alphabetically). So the installed `~/.claude/rules/delivery.md` = base content + separator + plugin content. The base file governs delivery for ALL non-trivial work; the plugin file governs delivery specifically for bead-tracked work. The split is intentional and the plugin content is additive, not contradictory — this is the correct use of the append model.
  However, the base `delivery.md` references itself in its own guidance: "see `delivery.md` for the action categorization" (line 33, completion-gate.md cross-reference). The plugin `delivery.md` also references "the AUTOMATIC category in core `delivery.md`" (line 13). When both are installed and appended, these cross-references point to the same (now merged) file — which works, but is subtly fragile: the "core" section is implicit order, not an explicit heading. If the append order ever changes, the "AUTOMATIC category" reference could resolve ambiguously.
  Recommendation: Add a `## Core delivery rules` heading to the base `delivery.md` Action Categories section so the plugin's "core `delivery.md`" cross-reference has a stable anchor. Alternatively, label the plugin addendum as `## Beads-aware addendum` (it already has a similar title at line 1) and normalize the cross-reference in the plugin to say "see the Action Categories section above."
  Vision-advancement-tier: C
  Vision-advancement: Reduces ambiguity risk in the append model, making cross-file references resilient to future ordering changes.
  Promotion-eligible: yes
  Related: F5

---

F7: completion-gate.md — mixes normative constraint with delivery orchestration that belongs in delivery.md
  File: src/user/.claude/rules/completion-gate.md:19-23
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Lines 19–23 ("HARD STOP: After this gate, AUTOMATICALLY execute delivery steps…") describe what to do after the completion gate, not what the completion gate itself is. This content duplicates and partially restates `delivery.md`. The completion gate governs quality verification (steps 1–5); delivery governs handoff (steps 6–8). The "HARD STOP" paragraph blurs this boundary by embedding delivery-trigger instructions inside the completion gate rule. This violates the single-purpose principle from the Rules Primer.
  Recommendation: Replace the "HARD STOP" paragraph with a one-line normative pointer: "After this gate passes, execute the delivery workflow immediately — see `delivery.md`." The delivery.md rule already contains the "AUTOMATIC" and "Red flag" guidance; do not duplicate it here. This makes each rule file govern exactly one concern.
  Vision-advancement-tier: A
  Vision-advancement: Tightens the completion gate as a guardrail for commitment 4 (mechanical evidence before completion claims) by keeping it focused solely on verification, removing procedural delivery noise that can obscure the five quality steps.
  Promotion-eligible: yes
  Related: F6

---

F8: completion-gate.md — references `using-git-worktrees` and `finishing-a-development-branch` by short name without qualifying namespace
  File: src/user/.claude/rules/completion-gate.md:22
  Category: rule
  Severity: Low
  Tier: 1
  Issue: The line reads: "Execute IN ORDER, without asking: (1) `using-git-worktrees` if not already in one, (2) `finishing-a-development-branch`, (3) `wait-for-pr-comments`..." These are superpowers-namespaced skills (`superpowers:using-git-worktrees`, `superpowers:finishing-a-development-branch`, `superpowers:wait-for-pr-comments`) but are referenced without the namespace prefix. The delivery.md uses the same unqualified names, so this is consistent — but both are technically imprecise. If skill names collide across plugins, unqualified references will resolve ambiguously.
  Recommendation: If delivery.md is updated to qualify names (which would be a separate finding under delivery.md), update completion-gate.md to match. As a standalone fix: add `superpowers:` prefix to the three skill references in this paragraph.
  Vision-advancement-tier: C
  Vision-advancement: Eliminates silent resolution ambiguity for skill names when multiple plugins are active.
  Related: F7

---

F9: delegation.md — "Non-trivial work alone is NOT a trigger for ralf-implement" is advisory, not normative
  File: src/user/.claude/rules/delegation.md:9
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "Non-trivial work alone is NOT a trigger for `ralf-implement`" is a negation clarification — it reads as a correction to a likely misuse pattern rather than a constraint the agent ALWAYS enforces. The surrounding content is genuinely normative (MANDATORY delegation routing). This one line is more explanatory than prescriptive; its function is to prevent over-eager ralf-implement invocation. The substance is correct and important, but the phrasing is advisory in nature ("alone is NOT a trigger" rather than "NEVER invoke ralf-implement unless…").
  Recommendation: Rewrite as normative: "NEVER invoke `ralf-implement` unless the user explicitly requests it with a target, DoD, and context." This makes the constraint action-oriented and matches the authoritative "always/never" register of the other lines.
  Vision-advancement-tier: C
  Vision-advancement: Sharpens normative language, making the constraint more clearly enforceable.

---

F10: delegation.md — `codex-routing.md` cross-reference is the only inter-rule reference in the set; concrete and valid
  File: src/user/.claude/rules/delegation.md:13
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "see `codex-routing.md`" is a valid cross-reference because there is a concrete dependency — delegation decisions route to Codex, and the routing rules live in that file. No issue with the reference itself. Minor improvement: the reference could use a more specific anchor ("the Model selection section in `codex-routing.md`") since codex-routing.md is short and the entire file is relevant. Current form is acceptable.
  Recommendation: No change required. Optional improvement: "see `codex-routing.md` (Model selection)" to add precision.
  Vision-advancement-tier: C
  Vision-advancement: No change; finding confirms reference hygiene is correct for the delegation→codex-routing dependency.

---

F11: codex-routing.md — Claude Code-specific invocation script embeds plugin-internal path that could drift
  File: src/user/.claude/rules/codex-routing.md:7-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The invocation block hardcodes the Codex plugin install path (`$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex`). This is a Claude Code marketplace path that is subject to change without notice. The rule acknowledges this partially ("fall back to the marketplace install path") but the hardcoded path is the primary fallback and is not abstracted. If the marketplace reorganizes, all agents following this rule silently break. Additionally, this is a Claude Code-specific rule (`src/user/.claude/rules/`) — the RULES_PRIMER notes that rules in this tree should be "tool-agnostic in spirit" even if Claude-specific in format. This rule is necessarily Claude-specific (it governs the Codex plugin), which is acceptable, but the hardcoded path is a fragility risk.
  Recommendation: Move the resolved path into a settings.json env var (e.g., `CODEX_PLUGIN_HOME`) so agents reference `$CODEX_PLUGIN_HOME` and the path is configured at install time. The rule prose becomes: "Invocation: `node "$CODEX_PLUGIN_HOME/scripts/codex-companion.mjs" task ...`" — stable regardless of marketplace path changes. Alternatively, extract path resolution to a helper script (`scripts/codex-invoke.sh`) that handles fallback logic.
  Vision-advancement-tier: A
  Vision-advancement: Directly advances commitment 5 (persist context across agent handoff and overnight runs) — hardcoded plugin paths that drift cause silent delegation failures in autonomous overnight runs, the exact scenario the vision targets.
  Promotion-eligible: yes

---

F12: codex-routing.md — model names are time-sensitive and will rot
  File: src/user/.claude/rules/codex-routing.md:13-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The model selection table hardcodes `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.3-codex-spark`. The SKILLS_PRIMER explicitly warns: "Avoid time-sensitive information: 'Before August 2025, use the old API' rots." Rules are always-loaded and not versioned — when GPT model names change, this rule will silently route to deprecated models. The cost ratios (mini ≈ 30%, spark ≈ 70–93%) are also time-sensitive. The rule lacks any "check for current model names" escape hatch.
  Recommendation: Abstract model names behind aliases defined in a companion config or settings.json (e.g., `CODEX_MODEL_FULL`, `CODEX_MODEL_MINI`, `CODEX_MODEL_SPARK`) that the install script populates. Alternatively, add a note: "Model names current as of 2026-05; verify against `codex:status` or plugin changelog if encountering 'model not found' errors." At minimum, the cost ratios should be documented as approximate and subject to change.
  Vision-advancement-tier: A
  Vision-advancement: Prevents silent routing failures in autonomous overnight runs (commitment 5) caused by deprecated model names in always-loaded rules that the agent cannot self-correct without a human present.
  Promotion-eligible: yes
  Related: F11

---

F13: git-commits.md — correctly scoped, normative, and actionable; no issues
  File: src/user/.claude/rules/git-commits.md:1-9
  Category: rule
  Severity: Low (informational)
  Tier: 1
  Issue: No substantive issues. The file is 9 lines, single-purpose, normative ("NEVER use heredoc syntax"), consequence-grounded ("heredocs fail with 'can't create temp file'"), and offers three ranked alternatives. This is the model form for a rule file.
  Recommendation: No change required. This file demonstrates the correct pattern: one constraint, one grounding rationale, specific alternatives.
  Vision-advancement-tier: C
  Vision-advancement: Confirms the pattern — concise, normative, consequence-grounded rules lower the failure rate of mechanical operations in autonomous runs.

---

F14: subagents.md — two bullets are adequate constraints but lack consequence grounding
  File: src/user/.claude/rules/subagents.md:1-7
  Category: rule
  Severity: Low
  Tier: 1
  Issue: "After subagent work completes, verify worktree cleanup and branch locks before proceeding" and "Do not send messages to already-terminated ephemeral agents — check agent status first" are valid normative constraints. However, neither has a consequence clause ("because X will happen if violated"). The Rules Primer states: "Authority grounding for hard constraints: state the consequence or reason." Without grounding, agents may de-prioritize these checks when under pressure.
  Recommendation: Expand with one-line rationale per bullet: "…before proceeding — orphaned worktrees block future `git worktree add` calls with the same name." And: "…check agent status first — sending messages to terminated agents causes silent no-ops or harness errors that look like successful dispatches."
  Vision-advancement-tier: C
  Vision-advancement: Consequence grounding makes constraints self-explanatory, reducing the chance an agent omits the check when it seems inconvenient.

---

F15: worktrees.md — Override clause potentially contradicts the `EnterWorktree` tool's behavior
  File: src/user/.claude/rules/worktrees.md:5-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: The rule states: "Preferred: Use Claude Code's native `EnterWorktree` tool — it places worktrees here automatically." Then: "Override: The superpowers `using-git-worktrees` skill defaults to `.worktrees/` at the project root. Disregard that default." This creates a potential confusion: if `EnterWorktree` places worktrees correctly, why does the Override clause exist as a second instruction? The file doesn't clarify when the Override applies vs. when the Preferred path is used. An agent reading this could conclude: (a) always use EnterWorktree, OR (b) always use manual `git worktree add`, OR (c) use EnterWorktree normally but override the skill's default path if using the skill. The intent is (c), but the structure doesn't make it explicit.
  Recommendation: Restructure to make the three cases explicit: "1. Using the EnterWorktree tool → no override needed; it places worktrees at the correct location. 2. Manually creating worktrees → use `git worktree add .claude/worktrees/<name> -b <branch>`. 3. If the `superpowers:using-git-worktrees` skill suggests `.worktrees/` → disregard; use `.claude/worktrees/` instead." This eliminates ambiguity without adding length.
  Vision-advancement-tier: C
  Vision-advancement: Eliminates worktree placement confusion that causes agents to retry or escalate unnecessarily on worktree creation failures.
  Promotion-eligible: yes

---

F16: worktrees.md — Claude Code-specific tool name (`EnterWorktree`) in a rule that should be tool-agnostic in spirit
  File: src/user/.claude/rules/worktrees.md:5
  Category: rule
  Severity: Low
  Tier: 1
  Issue: The RULES_PRIMER notes that rules in `src/user/.claude/rules/` should be "tool-agnostic in spirit" with intent to embed content into other tool AGENTS.md files. `EnterWorktree` is a Claude Code-only construct; the reference is legitimate in this Claude-specific rule file, but the rule should note its scope. Currently it reads as a universal recommendation with no qualifier.
  Recommendation: Add a single parenthetical: "Use Claude Code's native `EnterWorktree` tool (Claude Code only) — it places worktrees here automatically." This scopes the recommendation for cross-tool readers and future embedding. No structural change needed.
  Vision-advancement-tier: C
  Vision-advancement: Ensures the rule remains coherent when embedded into Codex or Gemini AGENTS.md files via the future cross-tool embedding pipeline.
  Related: F15

---

F17: delivery.md (user) — skill names unqualified throughout; potential resolution ambiguity
  File: src/user/.claude/rules/delivery.md:7-9
  Category: rule
  Severity: Low
  Tier: 1
  Issue: Skills are referenced as `using-git-worktrees`, `finishing-a-development-branch`, `wait-for-pr-comments`, `reply-and-resolve-pr-threads` without the `superpowers:` namespace qualifier. The superpowers plugin provides these skills; without the qualifier, if a name collision exists in another plugin, resolution is ambiguous. This is consistent with completion-gate.md (F8) and beads/delivery.md — the whole rule set uses unqualified names. The impact is currently low because the superpowers plugin is the only source of these names, but it's a latent fragility.
  Recommendation: Qualify all superpowers skill references with the `superpowers:` namespace prefix throughout delivery.md: `superpowers:using-git-worktrees`, `superpowers:finishing-a-development-branch`, etc. Coordinate with completion-gate.md (F8) and beads/delivery.md (F5) to apply consistently.
  Vision-advancement-tier: C
  Vision-advancement: Prevents silent skill dispatch failures if future plugins introduce same-named skills, which would disrupt autonomous overnight delivery pipelines.
  Related: F8

---

F18: delivery.md (user) — inline `gh` command block is a script candidate
  File: src/user/.claude/rules/delivery.md:39-42
  Category: rule
  Severity: Low
  Tier: 2
  Issue: The "PR comments" section includes an inline two-command block (`gh pr view` and `gh api repos/...`) as a reminder to check both comment types. This is a deterministic sequence that could be a helper script (`scripts/gh-pr-all-comments.sh <pr>` or similar). The block is short enough that it's borderline — two commands is not egregious — but per the Rules Primer's inline-sequence guidance, even short sequences are better as named scripts. More practically, the GitHub API path `/repos/<owner>/<repo>/pulls/<pr>/comments` is a template that requires variable substitution; as prose it's a reminder to construct the right URL, not an executable command, which reduces its actionability.
  Recommendation: Convert to a helper script `scripts/gh-pr-review-comments.sh <pr-number>` that detects `<owner>/<repo>` from `git remote` and runs both commands. The rule prose becomes: "Run `gh-pr-review-comments.sh <pr>` to collect both top-level and inline comments before marking review complete." Alternatively, accept the current form given the short length; this is a Low severity finding.
  Vision-advancement-tier: C
  Vision-advancement: Minor improvement to autonomous PR review pipeline reliability; named script eliminates the URL-template ambiguity.
  Promotion-eligible: yes
  Related: F1

---

## Summary

### Critical findings
None.

### High severity
- **F3** — beads.md is over-length and embeds reference material that should be in a skill; always-loaded context burden dilutes the normative constraints.

### Medium severity
- **F1** — I1/I2 inline shell sequences should be helper scripts (also Tier 3 extraction candidates per scope note)
- **F4** — beads-labels.md is a reference glossary masquerading as a rule
- **F6** — delivery.md dual-file cross-reference fragility under the append model
- **F7** — completion-gate.md mixes quality-gate with delivery orchestration
- **F11** — codex-routing.md hardcoded plugin path will drift
- **F12** — codex-routing.md model names are time-sensitive and will rot
- **F15** — worktrees.md Override clause is ambiguous about when it applies

### Low severity
- **F2** — beads.md jq filter is a script candidate
- **F5** — beads/delivery.md final paragraph uses advisory rather than normative framing
- **F8** — completion-gate.md unqualified skill names
- **F9** — delegation.md one line is advisory rather than normative
- **F10** — delegation.md cross-reference is valid (informational)
- **F13** — git-commits.md is exemplary (informational)
- **F14** — subagents.md lacks consequence grounding
- **F16** — worktrees.md `EnterWorktree` reference needs Claude Code scope qualifier
- **F17** — delivery.md unqualified skill names (consistent with F8)
- **F18** — delivery.md inline gh command block is a script candidate

### Tier 3 extraction candidates (bd-sequence scope)
Per the audit scope, the following are flagged as Tier 3 extraction candidates — inline `bd` command sequences not yet extracted by formula 7bk.27:
- **F1** — I1 claim-walk loop (beads.md:25-33) — pattern: walk parent chain upward, set `in_progress`
- **F1** — I2 close-walk loop (beads.md:37-45) — pattern: walk parent chain upward, close empty ancestors; identical structure to `children-check` pattern
- **F2** — `bd ready --json | jq '[.[] | select(.labels | index("implementation-ready") | not)]'` (beads.md:65) — pattern: `label-copy-filter` (filter out labeled items from ready list)

All three are Tier 2 (parameter design requires judgment) per the scope specification.

### Cross-cutting observations

1. **Rules-vs-skills boundary**: beads.md (F3) and beads-labels.md (F4) are the clearest misclassifications — they are reference documents installed as always-loaded rules. The other eight files are genuinely normative in intent, with findings concentrated on prose quality (consequence grounding, normative language, inline sequences) rather than fundamental misclassification.

2. **Delivery split is sound**: The two delivery.md files (user + plugin) follow the append model correctly. The plugin content is additive, not contradictory. The fragility (F6) is mechanical — a heading anchor would resolve it.

3. **Codex-routing.md time-sensitivity**: Both F11 and F12 are latent failures for autonomous overnight runs — the exact scenario the vision targets. These are the highest-priority Tier 2 findings in the user-scoped set.

4. **git-commits.md and delegation.md are strong**: Both are concise, normative, and appropriately scoped. git-commits.md (F13) is the model form. delegation.md has one advisory phrase (F9) but is otherwise well-formed.

5. **No bead hygiene violations in src/user/ files**: The user-scoped rules (`src/user/.claude/rules/`) contain no `bd` commands or bead tracker terminology. The bead-specific content is correctly confined to `src/plugins/beads/.claude/rules/`.
