# Phase 3 By-Category: Skills
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the skills category.
Cross-category reclassifications (findings that target skills but originated in another category) are noted where applicable.

---

F1: wait-for-pr-comments exceeds 500-line body budget — extract to reference files
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:1-828
  Category: skill
  Severity: High
  Tier: 2
  Issue: SKILL.md is 828 lines — 66% over the 500-line progressive-disclosure budget. Schema validation guards, subagent contract, concurrency recovery branch table, and reply templates all inflate the body. Phase 2 quality-gate reviewer agrees on extraction but specifies what must remain: the phase map, Phase 8 default-on chain, inventory ownership statement, and recovery entrypoints.
  Recommendation: Extract to SCHEMA.md (hand-off contract + guard definitions), RECOVERY.md (concurrency recovery branch table), and SUBAGENT-CONTRACT.md (per-comment subagent contract + SHA-discovery procedure). Keep phase map, Phase 8 default-on chain, inventory ownership, and recovery entrypoints in SKILL.md. Add TOC to extracted files >100 lines.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): a 828-line SKILL.md risks partial reads that cause the orchestrator to mis-apply phase contracts mid-run.
  Promotion-eligible: yes
  Resolution: ACCEPTED (synthesis per D10)
  Rationale: Phase 2 AGREE on extraction principle; aggregator synthesizes what stays vs. what moves.
  Sources: phase1/skills.md:F1, phase2/quality-gate-and-delivery.md:F1

---

F2: Schema validation guards duplicated between wait-for-pr-comments and reply-and-resolve-pr-threads
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214, src/user/.agents/skills/wait-for-pr-comments/SKILL.md:683-713
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Nine schema validation guards are reproduced verbatim in both skills. Two copies means any change must be kept in sync manually; guard numbering is already slightly inconsistent.
  Recommendation: Define guards once in a shared SCHEMA.md (per F1) referenced by both SKILL.md files. Each file keeps only the guards that are implementation-specific to its own write/read side.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail completion claims): divergent guard descriptions will eventually cause a mismatch between what the writer enforces and what the reader expects.
  Promotion-eligible: yes
  Resolution: ACCEPTED (merged into D9/D10 synthesis)
  Rationale: Phase 2 F3 (quality-gate) agrees that shared SCHEMA.md is correct; the move-to-shared-path decision (D9) applies.
  Sources: phase1/skills.md:F2, phase2/quality-gate-and-delivery.md:F3

---

F3: wait-for-pr-comments — beads leakage; split shared core from beads-only autonomous mode
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:191,548,557-561
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: Shared skill contains direct `bd` command invocations in the normative execution path (ESCALATE section, DEFER placement logic). Non-beads tools loading this skill will encounter commands they cannot execute, with no fallback defined.
  Recommendation: Keep shared PR-review core (detection, Copilot polling, classification, FIX execution, inventory handoff, interactive mode) in shared namespace. Create beads-plugin addendum or wrapper that owns autonomous mode, `--bead-id`, `bd` escalation filing, and I3-based DEFER placement. Do NOT move the whole skill to `src/plugins/beads/` per D7.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context across agent handoff and overnight runs): autonomous mode failing silently on non-Claude tools breaks overnight PR cycles without any error signal.
  Promotion-eligible: yes
  Resolution: ACCEPTED (split-not-move per D7)
  Rationale: Three Phase 2 reviewers agree on split vs. wholesale move; aggregator accepts synthesis.
  Sources: phase1/skills.md:F3, phase2/full-bead-lifecycle.md:F1, phase2/quality-gate-and-delivery.md:F2

---

F4: reply-and-resolve-pr-threads — same beads leakage; same split-not-move fix
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:111,240-242
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: Autonomous mode recovery prescribes `bd label add <bead-id> human` + `bd update` as the escalation path. `--bead-id` is a first-class parameter of the skill's arg protocol. Non-beads tools receive instructions they cannot execute.
  Recommendation: Mirror D8 split. Keep shared thread-reply/resolution engine; move autonomous recovery persistence and `--bead-id` handling into a beads-specific extension/wrapper.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5: these two skills form the PR review completion gate — silently failing on non-Claude tools breaks autonomous overnight PR cycles.
  Promotion-eligible: yes
  Resolution: ACCEPTED (split-not-move per D8)
  Rationale: Same Phase 2 evidence as F3 above.
  Sources: phase1/skills.md:F4, phase2/full-bead-lifecycle.md:F2, phase2/quality-gate-and-delivery.md:F2

---

F5: implement-bead dense prose — rewrite as decision tables inline, not extraction
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:24,48,56,87
  Category: skill
  Severity: High
  Tier: 2
  Issue: Multiple lines exceed 400-1100 characters of inline prose. Line 48 (1100 chars) encodes type-to-formula routing logic, formula variable shapes, bead linkage stamping, and molecule disambiguation in one paragraph. Dense prose is fragile under agent attention compression.
  Recommendation: Rewrite §1 and §2 dense paragraphs as decision tables and numbered branches. Keep dispatch contract inline in SKILL.md (do NOT move routing algorithm to RESOLUTION.md per D14). Extract only historical rationale and long explanatory parentheticals.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4: the orchestrator cannot reliably follow 1100-character prose encoding 4 interleaved decision branches.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D14)
  Rationale: Phase 2 multi-agent reviewer gives PARTIAL; aggregator accepts inline-table synthesis.
  Sources: phase1/skills.md:F5, phase2/multi-agent-dispatch.md:F2

---

F6: implement-bead formula-label parsing — share expression, keep state-specific branches
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:26-46,58-79
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: 20-line shell snippet for parsing `formula-*` labels appears twice (§1 and §2). However the two blocks guard different recovery states: pre-pour (label source bead only) vs post-pour (label both source bead and step-bead, reopen step).
  Recommendation: Extract the low-level label-parsing shell expression to a single named block. Keep the pre-pour and post-pour escalation branches explicit at their call sites per D15.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): the dispatcher's recovery behavior depends on knowing whether execution failed before or after step materialization.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D15)
  Rationale: Phase 2 escalation reviewer gives PARTIAL; aggregator preserves two explicit flag-human branches.
  Sources: phase1/skills.md:F6, phase2/escalation-edge-recovery.md:F2

---

F7: test-review uses undocumented frontmatter fields context: fork and agent: general-purpose
  File: src/user/.agents/skills/test-review/SKILL.md:1-8
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Frontmatter contains `context: fork` and `agent: general-purpose` — neither appears in the official Anthropic SKILL.md schema nor in documented project extensions. These fields have no known harness interpretation.
  Recommendation: Determine whether these fields are consumed by any harness or tool. If not, remove them. If `context: fork` is intentional, document the behavior in the Skills Primer.
  Vision-advancement-tier: C
  Vision-advancement: Removes undocumented fields that create false expectations about harness behavior — a clarity improvement.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address this finding; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F7

---

F8: simplify skill — external-source drift annotation as invisible HTML comment
  File: src/user/.agents/skills/simplify/SKILL.md:7
  Category: skill
  Severity: Low
  Tier: 1
  Issue: HTML comment `<!-- Source: /simplify slash command... -->` is maintenance metadata invisible in markdown previews and unreadable by agents. No value to agent execution.
  Recommendation: Delete comment and record sync policy in git history, or convert to an explicit `## Maintenance Note` section at the bottom of the file.
  Vision-advancement-tier: C
  Vision-advancement: Removes invisible metadata noise from skill body — an invisible comment adds no signal to agent judgment.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F8

---

F9: simplify skill — bd remember negation in shared content
  File: src/user/.agents/skills/simplify/SKILL.md:57
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: "Do NOT use `bd remember` for this" introduces bead-tracker vocabulary into shared content. A Codex/Gemini agent has no `bd remember`; the sentence is confusing for non-beads tools.
  Recommendation: Replace with tool-agnostic: "Do not use issue-tracker or task-tracking mechanisms for this — use the host's project memory system."
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content, keeping the shared namespace tool-agnostic.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F9

---

F10: wait-for-pr-comments hardcoded ~/.claude/skills/ install path
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:227,244,261,326,354,410,655,672
  Category: skill
  Severity: High
  Tier: 1
  Issue: Helper script invocations use hardcoded path `~/.claude/skills/wait-for-pr-comments/` at 8+ locations. Project convention is `${CLAUDE_SKILL_DIR}` (as used correctly in merge-guard and run-queue). Hardcoded path breaks if installed to non-standard location.
  Recommendation: Replace all `~/.claude/skills/wait-for-pr-comments/` prefixes with `${CLAUDE_SKILL_DIR}/`. Mechanical substitution at 8+ locations.
  Vision-advancement-tier: C
  Vision-advancement: Removes hardcoded install path that breaks portability — a mechanical correctness fix.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not specifically address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F10

---

F11: reply-and-resolve-pr-threads — hardcoded cross-skill validate-inventory.sh path
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:65
  Category: skill
  Severity: High
  Tier: 2
  Issue: Phase 0 schema validation invokes `~/.claude/skills/wait-for-pr-comments/validate-inventory.sh` using a hardcoded path pointing to a different skill's directory. Cross-skill filesystem coupling that breaks if installation prefix changes.
  Recommendation: Move `validate-inventory.sh` to a shared support location (e.g., `src/user/.agents/skills/shared/` or `wait-for-pr-comments-shared/`) and have both skills reference it from the shared path. Do NOT copy or symlink per D9.
  Vision-advancement-tier: C
  Vision-advancement: Removes brittle cross-skill filesystem coupling that will silently break Phase 0 validation if skills are relocated.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D9)
  Rationale: Phase 2 quality-gate reviewer gives PARTIAL; aggregator accepts shared-location synthesis.
  Sources: phase1/skills.md:F11, phase2/quality-gate-and-delivery.md:F3

---

F12: ralf-it deprecated stub still costs context window; should be deleted
  File: src/user/.agents/skills/ralf-it/SKILL.md:1-16
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: ralf-it is explicitly deprecated, 16 lines, and loads into every agent context at startup. The `model: opus[1m]` on a stub that does nothing is semantically wrong — accidental invocation spins up an expensive model to say "use something else."
  Recommendation: Delete ralf-it/SKILL.md and its directory entirely. The delegation rule already states ralf-implement and ralf-review are opt-in via explicit invocation.
  Vision-advancement-tier: C
  Vision-advancement: Removing a deprecated stub reduces startup context weight on every session.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F12

---

F13: ralf-implement and ralf-review do not reference their supporting prompt files
  File: src/user/.agents/skills/ralf-implement/SKILL.md:44-51, src/user/.agents/skills/ralf-review/SKILL.md:40-45
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Both skills have supporting prompt files (foreign-agent-prompt.md, foreign-eyes-prompt.md, fresh-eyes-prompt.md, implementer-prompt.md) that are never referenced from the SKILL.md bodies. Templates go unused unless the agent discovers them by other means. Phase 2 multi-agent and escalation reviewers both AGREE this is a real gap — the prompt files are missing dispatch payload, not dead weight.
  Recommendation: Add explicit prompt-file references at the dispatch branch in both SKILL.md bodies (e.g., "Dispatch with `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md`"). Specify which file is used for each pass (foreign-agent, pure fresh-eyes, implementer).
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 (substitute adversarial cross-model review): adversarial review only works if the reviewer subagent receives prepared prompts — unreferenced supporting files are dead weight.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE from two reviewers (multi-agent:F3, escalation:F6) confirms this is active missing functionality.
  Sources: phase1/skills.md:F13, phase2/multi-agent-dispatch.md:F3, phase2/escalation-edge-recovery.md:F6

---

F14: condition-based-waiting uses user-invocable: false — non-standard frontmatter field
  File: src/user/.agents/skills/condition-based-waiting/SKILL.md:3
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Frontmatter contains `user-invocable: false`, not in official Anthropic SKILL.md schema. Same field in testing-anti-patterns/SKILL.md. Undefined behavior — either silently ignored or gates invocation without documentation.
  Recommendation: Document the intended meaning in Skills Primer if intentionally used, or remove and rely on the description to de-prioritize the skill for user invocation.
  Vision-advancement-tier: C
  Vision-advancement: Removes non-standard frontmatter that creates false impressions of harness capability.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/skills.md:F14

---

F15: writing-unit-tests — "follow-up bead" bead-tracker vocabulary in shared content
  File: src/user/.agents/skills/writing-unit-tests/SKILL.md:60,180,197
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Three locations use "follow-up bead" as a rationalization-to-reject pattern. Bead-tracker vocabulary in shared content is confusing for non-beads tools; the underlying principle is tool-agnostic.
  Recommendation: Replace "follow-up bead" with "follow-up ticket" or "deferred issue" at all three locations. Mechanical substitution.
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content — a three-site mechanical fix.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F15

---

F16: verify-checklist — bead:ID privileged in discovered-work table template
  File: src/user/.agents/skills/verify-checklist/SKILL.md:65,94
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Line 94 includes `bead:ID` as first item in Discovered Work table template. Phase 2 quality-gate reviewer AGREES: examples are not part of the load-bearing completion-to-delivery chain; hygiene cleanup does not remove a real dependency.
  Recommendation: Reorder to list generic tracking mechanisms first: `issue:#N / memory / backlog / bead:ID`. Replace standalone "create beads, issues, or memory entries" with "record in the project's tracking system (issues, backlog, memory, or beads if available)."
  Vision-advancement-tier: C
  Vision-advancement: Makes the completion-gate verify step tool-agnostic by not privileging beads-specific notation.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (quality-gate:F7).
  Sources: phase1/skills.md:F16, phase2/quality-gate-and-delivery.md:F7

---

F17: start-bead — keep routing logic inline; trim verbose forensics only
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:1-357
  Category: skill
  Severity: Low
  Tier: 2
  Issue: At 357 lines, approaching 500-line budget. Phase 2 multi-agent (F5) and escalation (F1) reviewers both give PARTIAL: the routing matrix and recovery branches (Route Z, 0/0 burn, post-brainstorm hand-off stop) are the dispatch contract and must stay in SKILL.md.
  Recommendation: Extract only verbose audit-comment templates and repetitive forensic examples to a reference file. Keep Route Z handling, molecule-ambiguity escalation, 0/0 burn recovery, post-brainstorm hand-off stop, and the full route-selection logic in SKILL.md per D16.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 (make AI good at saying "no, not ready"): the routing matrix is the mechanism that bounces under-specified work back.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D16)
  Rationale: Phase 2 PARTIAL from two reviewers; aggregator accepts trim-forensics-only synthesis.
  Sources: phase1/skills.md:F17, phase2/multi-agent-dispatch.md:F5, phase2/escalation-edge-recovery.md:F1

---

F18: run-queue description written in second person
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:1-8
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Description contains "do NOT mix with brainstorming sessions" — second-person imperative, not third-person trigger contract as required by Skills Primer.
  Recommendation: Rewrite: "…Runs in a dedicated session; must not be mixed with interactive brainstorming sessions."
  Vision-advancement-tier: C
  Vision-advancement: Corrects description phrasing to match the third-person trigger contract required by the skills invocation model.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F18

---

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

F20: implement-bead and ralf-implement describe incompatible orchestration contracts
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:87-90,136-144, src/user/.agents/skills/ralf-implement/SKILL.md:11-53
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: implement-bead treats ralf-implement as a beads-aware loop controller that receives typed worker inputs and returns an aggregate verdict compatible with step-bead closeout. ralf-implement defines no such contract — it implements directly in the working copy, runs completion-gate steps, and never mentions worker-report-v1, iteration audit labels, or aggregate return shapes. Two different orchestration models on the same seam.
  Recommendation: Choose one contract and encode it explicitly. Either make ralf-implement beads-aware by adding a formal caller contract for doer_subagent_type, worktree/report-path inputs, worker-report-v1 ingestion, and aggregate verdict output; or introduce a beads-specific adapter skill that owns the worker-report contract end to end.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context across agent handoff): the current seam cannot reliably hand off iteration state because each side believes a different contract exists.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F1)
  Rationale: Phase 2 multi-agent reviewer finds this a Critical gap not covered by Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F1

---

F21: start-bead can route into implement-bead from a non-orchestrator context
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:3-7,173-190, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:8-10,98
  Category: skill
  Severity: High
  Tier: 2
  Issue: start-bead Route A can invoke implement-bead directly. implement-bead explicitly requires the invoking agent to be the top-level ORCHESTRATOR. start-bead never establishes this precondition. If triggered from a delegated context, it routes into a dispatcher that cannot dispatch.
  Recommendation: Add a preflight rule near the top of start-bead: if this session is not the top-level orchestrator, return the routing decision to the caller rather than invoking implement-bead directly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5: the router must not hand work to a dispatcher that is structurally unable to spawn contracted workers.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F4)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F4

---

F22: run-queue announces PR artifacts not exposed by implement-bead's contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:86-104, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:136-140
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: run-queue promises PR number on completion, but implement-bead does not provide progress callbacks or PR metadata. Queue orchestration announces richer status than its downstream dispatcher returns.
  Recommendation: Make run-queue outcome-driven. After implement-bead returns, inspect bead/molecule state and report only mechanically observable artifacts. Mention PR number only if a delivery step explicitly provides one.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4: queue orchestration should only announce artifacts it can prove.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F12)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F12

---

F23: bugfix skill — fallback ladder dead-ends on deleted superpowers:root-cause-tracing
  File: src/user/.agents/skills/bugfix/SKILL.md:117-120
  Category: skill
  Severity: High
  Tier: 1
  Issue: When three-thread synthesis cannot identify root cause, the skill tells the agent to escalate via `superpowers:root-cause-tracing`. This skill is deleted. The "don't guess, escalate" path is broken exactly when methodology is supposed to stop speculative fixes.
  Recommendation: Replace with an existing path: `superpowers:systematic-debugging`, `condition-based-waiting`, or an explicit stop-and-surface protocol that reports missing evidence to the user.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 (make AI good at saying "no, not ready"): the skill's escalation path must be actually executable.
  Promotion-eligible: no
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F7)
  Rationale: Phase 2 AGREE verdict. Tier 1 — mechanical fix (remove dead reference, add working alternative).
  Sources: phase2/escalation-edge-recovery.md:F7

---

F24: human-label semantics contradict between formulas and rules
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:367-372, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:660-666, src/plugins/beads/.claude/rules/beads-labels.md:10-13
  Category: skill (cross-category: formula + rule)
  Severity: High
  Tier: 1
  Issue: Two formulas say adding `human` label excludes a bead from `bd ready`. The beads-labels.md rule says `human` is only a visibility tag and does NOT gate readiness. An agent following the hand-off path can believe work is safely parked when it may still surface as ready.
  Recommendation: Pick one contract and make every touched file match. If `human` alone is not a readiness gate, the hand-off path must add a real blocking dependency and state this explicitly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): a contradictory parking contract causes resumed work to re-enter the queue before a human resolves it.
  Promotion-eligible: no
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F8 via D25)
  Rationale: Active contradiction between rules and formulas; Tier 1 mechanical fix (pick one contract, update all files).
  Sources: phase2/escalation-edge-recovery.md:F8

---

F25: run-queue resolves implement-bead escalations too loosely — misses dual-bead human-flag contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:117-133, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:55-79,124-140
  Category: skill
  Severity: High
  Tier: 2
  Issue: run-queue resolves escalations by appending guidance and removing `human` from one bead ID. implement-bead stamps both source bead and step-bead on most recovery paths; some pauses require step reopen. Clearing one label ad hoc can requeue half-recovered work or leave a parked molecule in inconsistent state.
  Recommendation: Add a paired-resolution procedure to run-queue: identify whether escalation belongs to source bead, step-bead, or both; clear labels symmetrically only after underlying block is fixed; then re-check `bd mol current <mol-id>` and step notes before resuming queue.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): resume behavior must be deterministic after parked molecule is handed back from human review.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F9 via D26)
  Rationale: Genuine gap not in Phase 1; Phase 2 AGREE.
  Sources: phase2/escalation-edge-recovery.md:F9

---

## Cross-Category References (findings in this file that also touch other categories)

- F24 (human-label semantics): canonical entry here (skill); cross-referenced in formulas.md by-category and rules.md by-category
- F20 (implement-bead/ralf-implement contract): cross-referenced in agents.md by-category (ralf-implement is also relevant to agents via dispatch contract)
