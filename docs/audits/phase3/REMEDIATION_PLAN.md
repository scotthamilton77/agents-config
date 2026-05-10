# REMEDIATION PLAN — agents-config-il69 Audit

**AUDIT_INPUT_SHA**: af9c1bfc342bf7578ad491cc63dc95b07618c851
**Phase 2 model**: gpt-5.4
**Aggregator model**: claude-sonnet-4-6
**Generated**: 2026-05-10

[USER MARKERS — NEGOTIATED IN CHAT; OPT-OUT MODEL]
```text
  ┌───────────────────┬──────────────────────────────────────────────────────────────────┬─────────────────────────────────┐
  │    Annotation     │                              Effect                              │              Where              │
  ├───────────────────┼──────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ [APPROVED]        │ Assumed default (opt-out model); Apply this Tier 1 findings      │ Under any Tier 1 finding header │
  ├───────────────────┼──────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ [DEMOTE]          │ Convert to Tier 2 (file as follow-up bead, do not apply now)     │ Any tier finding                │
  ├───────────────────┼──────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ [DROP]            │ Discard entirely; record in decisions.md as Type: user-gate-drop │ Any finding                     │
  ├───────────────────┼──────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ [NOTE: <text>]    │ Assume approved, but consider note user added                    │ Any finding                     │
  ├───────────────────┼──────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ [DISCUSS: <text>] │ Pause Tier 1 application until we resolve in chat                │ Any finding                     │
  └───────────────────┴──────────────────────────────────────────────────────────────────┴─────────────────────────────────┘
```
---

## Summary

- Phase 1 findings: 100 (Critical 7, High 24, Medium 38, Low 31)
- Phase 2 findings: 48 + 3 OOS (verdict: 20 AGREE, 22 PARTIAL, 6 DISAGREE)
- Phase 3 accepted findings: 102 (DROPPED: 4, DEFERRED: 1, total audited: 107)
- Tier 1 (mechanical, inline): 41
- Tier 2 (deferred, follow-up beads): 61
- Vision-advancement tier mix: A=52 B=3 C=47 (C-share: 46.1%)

**Note on Tier C cap**: decisions.md §D30 demoted one finding to bring the tier-C share to 29.9% using a 88-finding subset. The by-category outputs, which include promoted Phase 2 findings not counted in the initial D30 analysis, yield 107 total and 46.1% Tier C. Verifiable check #4 reports the actual by-category figure (see Verification Status section). The D30 demotion stands; no additional demotions are proposed here — the by-category files are canonical.

---

## Tier 1 — Mechanical Fixes (apply in this PR after APPROVED marker)

Tier 1 findings are mechanical, inline changes that require no design judgment. All 41 are listed below, grouped by category.

### Category: Agents

#### F1: bead-implementor — deleted skill reference (superpowers:root-cause-tracing)
[NOTE: A recent change merged into main reconciled our references to superpowers skills after a superpowers plugin upgrade; re-assess if this is still valid]
- **File**: `src/plugins/beads/.agents/agents/bead-implementor.md:31,65`
- **Category**: agent
- **Severity**: High
- **Issue**: `skills:` frontmatter and body both reference `superpowers:root-cause-tracing`, a skill backed up and removed from install on 2026-05-03. When dispatched, systematic-debugging stage runs without contracted methodology.
- **Recommendation**: Remove `superpowers:root-cause-tracing` from `skills:` list. In the body (line 65), replace with `superpowers:systematic-debugging`.
- **Source(s)**: phase1/agents.md:F1, phase2/multi-agent-dispatch.md:F6

#### F2: bug-diagnoser — same deleted skill reference
[NOTE: A recent change merged into main reconciled our references to superpowers skills after a superpowers plugin upgrade; re-assess if this is still valid]
- **File**: `src/plugins/beads/.agents/agents/bug-diagnoser.md:31,54`
- **Category**: agent
- **Severity**: High
- **Issue**: Same deleted `superpowers:root-cause-tracing` in `skills:` frontmatter and body. The bug-diagnoser is the first stage of fix-bug; degraded root-cause quality ripples to all downstream stages.
- **Recommendation**: Remove from `skills:` and body invocation; use `superpowers:systematic-debugging`.
- **Source(s)**: phase1/agents.md:F2, phase2/multi-agent-dispatch.md:F6

#### F3: Wrong namespace for writing-unit-tests and testing-anti-patterns in bead-pipeline agents
[NOTE: A recent change merged into main reconciled our references to superpowers skills after a superpowers plugin upgrade; re-assess if this is still valid]
- **File**: `src/plugins/beads/.agents/agents/bead-implementor.md:28-29`, `src/plugins/beads/.agents/agents/tdd-red-team.md:30-32`, `src/plugins/beads/.agents/agents/tdd-green-team.md:33-34`
- **Category**: agent
- **Severity**: High
- **Issue**: Three agents list `superpowers:writing-unit-tests` and `superpowers:testing-anti-patterns` — these are plain repo skills, not superpowers plugin skills. Wrong namespace causes resolution failure.
- **Recommendation**: Replace `superpowers:writing-unit-tests` → `writing-unit-tests` and `superpowers:testing-anti-patterns` → `testing-anti-patterns` in all three files, including body references.
- **Source(s)**: phase1/agents.md:F3, phase2/multi-agent-dispatch.md:F7

#### F5: quality-reviewer body — "bead description" bead-tracker terminology
- **File**: `src/user/.agents/agents/quality-reviewer.md:57`
- **Category**: agent
- **Severity**: High
- **Issue**: Shared agent body uses "bead description" — terminology non-beads tools on Codex/Gemini cannot resolve.
- **Recommendation**: Replace "bead description, or step description" with "issue description, or task specification."
- **Source(s)**: phase1/agents.md:F5

#### F10: tech-lead — missing effort field
- **File**: `src/user/.agents/agents/tech-lead.md:32-33`
- **Category**: agent
- **Severity**: Low
- **Issue**: tech-lead frontmatter has no `effort:` field; defaults to medium for an orchestration-heavy agent.
- **Recommendation**: Add `effort: high`.
- **Source(s)**: phase1/agents.md:F10

#### F12: bead-verifier description — imperative phrasing
- **File**: `src/plugins/beads/.agents/agents/bead-verifier.md:3-27`
- **Category**: agent
- **Severity**: Low
- **Issue**: Description begins "PROACTIVELY collect…" — imperative second-person, not third-person trigger contract.
- **Recommendation**: Rewrite opening: "Mechanical verification agent that collects quality-gate evidence at completion gates — runs the project's quality-gate commands and reports raw exit codes plus terse error excerpts."
- **Source(s)**: phase1/agents.md:F12

---

### Category: Commands

#### F3: optimize-my-skill.md uses "5,000 words" threshold — conflicts with SKILLS_PRIMER "500 lines"
- **File**: `src/user/.claude/commands/optimize-my-skill.md:73,100,223`
- **Category**: command
- **Severity**: Medium
- **Issue**: Three occurrences of "Under 5,000 words" where the authoritative SKILLS_PRIMER.md states "under 500 lines." Different units yield materially different size thresholds.
- **Recommendation**: Replace every occurrence of "5,000 words" with "500 lines" (three occurrences).
- **Source(s)**: phase1/commands.md:F3

#### F8: optimize-my-agent.md heading "Agent.md" mismatches functional scope
[NOTE: keep the "optimize my agent" paradigm for consistency with "optimize my skill"]
- **File**: `src/user/.claude/commands/optimize-my-agent.md:1`
- **Category**: command
- **Severity**: Low
- **Issue**: File is named `optimize-my-agent.md` but heading is "# Optimize Agent.md" — inconsistent with each other and with the existing `optimize-agents-md` skill.
- **Recommendation**: Decide actual scope; align title, heading, and body. If targeting agent persona files (frontmatter name/description/model/color), rename heading to "Optimize Agent Definition."
- **Source(s)**: phase1/commands.md:F8

---

### Category: Formulas

#### F2: brainstorm-bead — motivational rationale in claim step
- **File**: `src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:41-51`
- **Category**: formula
- **Severity**: Medium
- **Issue**: `claim` step description contains explanatory motivation ("Brainstorming IS work — the bead's status must reflect that…") — background rationale, not execution instruction.
- **Recommendation**: Remove the motivational sentence; keep "The claim walk marks this bead and all ancestor epics in_progress. Read the `walked=N` output to confirm the chain depth."
- **Source(s)**: phase1/formulas.md:F2

#### F6: fix-bug file header — "cardinal sin" motivational prose
- **File**: `src/plugins/beads/.beads/formulas/fix-bug.formula.toml:1-19`
- **Category**: formula
- **Severity**: Medium
- **Issue**: File-level comment includes "The cardinal sin of bug fixing is patching the symptom." This belongs in a README, not the formula.
- **Recommendation**: Remove the "cardinal sin" sentence. Keep the factual stage-sequence description and "See:" and "Usage:" comments.
- **Source(s)**: phase1/formulas.md:F6

#### F7: implement-feature — stale bead reference in file-level comment
- **File**: `src/plugins/beads/.beads/formulas/implement-feature.formula.toml:12-14`
- **Category**: formula
- **Severity**: Low
- **Issue**: Comment reads "planned for bead 7bk.14" — embedded bead ID is a staleness risk.
- **Recommendation**: Remove bead ID reference; state the limitation plainly or remove the note entirely.
- **Source(s)**: phase1/formulas.md:F7

#### F11: name field mirrors id — undocumented step field
- **File**: `src/plugins/beads/.beads/formulas/implement-feature.formula.toml:47-48`, `src/plugins/beads/.beads/formulas/fix-bug.formula.toml:46-47`
- **Category**: formula
- **Severity**: Medium
- **Issue**: Both formulas set `name = "..."` on every step mirroring `id` exactly; not in FORMULAS_PRIMER. Either document if required by shell driver, or remove.
- **Recommendation**: Confirm `name` requirement. If required, add one file-top comment explaining convention and remove per-step comment. If not required, remove all `name` fields.
- **Source(s)**: phase1/formulas.md:F11

#### F13: fix-bug diagnose step — remove dead superpowers:root-cause-tracing reference
- **File**: `src/plugins/beads/.beads/formulas/fix-bug.formula.toml:134-135`
- **Category**: formula
- **Severity**: Low
- **Issue**: diagnose step lists `superpowers:root-cause-tracing` as preloaded skill. Does not exist.
- **Recommendation**: Remove from preloaded skills list and invocation instruction; reference `superpowers:systematic-debugging` only.
- **Source(s)**: phase1/formulas.md:F13, phase2/formula-step-execution.md:F7

---

### Category: Rules

#### F8: completion-gate.md — unqualified skill names
- **File**: `src/user/.claude/rules/completion-gate.md:22`
- **Category**: rule
- **Severity**: Low
- **Issue**: `wait-for-pr-comments` and `reply-and-resolve-pr-threads` are shared skills (bare canonical names, NOT superpowers:). `using-git-worktrees` and `finishing-a-development-branch` ARE superpowers plugin skills.
- **Recommendation**: Add `superpowers:` prefix only to `using-git-worktrees` and `finishing-a-development-branch`; keep bare names for the two shared skills.
- **Source(s)**: phase1/rules.md:F8, phase2/quality-gate-and-delivery.md:F5

#### F9: delegation.md — advisory phrasing; rewrite as normative
- **File**: `src/user/.claude/rules/delegation.md:9`
- **Category**: rule
- **Severity**: Low
- **Issue**: "Non-trivial work alone is NOT a trigger for `ralf-implement`" reads as correction, not constraint.
- **Recommendation**: Rewrite: "NEVER invoke `ralf-implement` unless the user explicitly requests it with a target, DoD, and context."
- **Source(s)**: phase1/rules.md:F9, phase2/multi-agent-dispatch.md:F13

#### F14: subagents.md — consequence grounding missing
- **File**: `src/user/.claude/rules/subagents.md:1-7`
- **Category**: rule
- **Severity**: Low
- **Issue**: Both constraints lack consequence clauses; rules without grounding are more easily skipped under pressure.
- **Recommendation**: Add rationale: "…before proceeding — orphaned worktrees block future `git worktree add` calls with the same name." And: "…check agent status first — sending messages to terminated agents causes silent no-ops or harness errors that look like successful dispatches."
- **Source(s)**: phase1/rules.md:F14

#### F16: worktrees.md — EnterWorktree needs Claude Code scope qualifier
[NOTE: you should be able to generalize this, e.g. "enter the worktree using applicable agent tool" (rephrase as needed)]
- **File**: `src/user/.claude/rules/worktrees.md:5`
- **Category**: rule
- **Severity**: Low
- **Issue**: `EnterWorktree` is Claude Code-only; rule reads as universal recommendation.
- **Recommendation**: Add parenthetical: "Use Claude Code's native `EnterWorktree` tool (Claude Code only) — it places worktrees here automatically."
- **Source(s)**: phase1/rules.md:F16

#### F17: delivery.md — same unqualified skill name issue
- **File**: `src/user/.claude/rules/delivery.md:7-9`
- **Category**: rule
- **Severity**: Low
- **Issue**: Same as F8 above. `using-git-worktrees` and `finishing-a-development-branch` need `superpowers:` prefix; the two shared skills keep bare names.
- **Recommendation**: Add `superpowers:` prefix only to actually plugin-scoped skills per D3.
- **Source(s)**: phase1/rules.md:F17, phase2/quality-gate-and-delivery.md:F5

---

### Category: Scripts

#### F1: bd-record-decision.sh — usage block inconsistency
- **File**: `src/plugins/beads/.beads/scripts/bd-record-decision.sh:28`
- **Category**: script
- **Severity**: Medium
- **Issue**: `usage()` emits a terse one-liner while all four sibling bd-toolkit scripts emit full `cat >&2 <<'EOF'` blocks.
- **Recommendation**: Replace the one-line echo with a `cat >&2 <<'EOF' ... EOF` block documenting every option, output format, and exit contract. Match style of bd-close-walk.sh's usage block.
- **Source(s)**: phase1/scripts.md:F1

#### F6: check-merge-eligibility.sh — duplicates lib.sh helpers inline
- **File**: `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:55-75`
- **Category**: script
- **Severity**: Low
- **Issue**: Contains its own `gh_api()`, `gh auth status` pre-flight, and `jq` availability check — all already in `wait-for-pr-comments/lib.sh`. Two implementations that must stay in sync.
- **Recommendation**: Consider promoting lib.sh to shared location; at minimum add a comment referencing `wait-for-pr-comments/lib.sh` as canonical source.
- **Source(s)**: phase1/scripts.md:F6

#### F8: poll-ready-beads.sh — missing set -euo pipefail
- **File**: `src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:1`
- **Category**: script
- **Severity**: High
- **Issue**: No `set -e`, `set -u`, or `set -o pipefail`. Failed `bd ready` or `jq` calls continue silently. Active hazard for autonomous background polling.
- **Recommendation**: Add `set -euo pipefail` immediately after shebang. Review `jq ... || echo "0"` fallback on line 22 with pipefail active.
- **Source(s)**: phase1/scripts.md:F8, phase2/full-bead-lifecycle.md:F6

#### F9: validate-inventory.sh — non-standard exit codes undocumented
- **File**: `src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh:13-23`
- **Category**: script
- **Severity**: Low
- **Issue**: Exits with 64/65/66 (sysexits.h) but header documents only 0/non-zero.
- **Recommendation**: Add exit-code table to header: `0 — all guards pass; 1 — validation failed; 64 — wrong arg count (EX_USAGE); 65 — jq write failed (EX_DATAERR); 66 — input file not found (EX_NOINPUT)`.
- **Source(s)**: phase1/scripts.md:F9

#### F10: write-inventory.sh — same undocumented exit codes
- **File**: `src/user/.agents/skills/wait-for-pr-comments/write-inventory.sh:27-49`
- **Category**: script
- **Severity**: Low
- **Issue**: Exit codes 64/65 (sysexits.h) not documented in header.
- **Recommendation**: Same pattern as F9 — add exit-code table to header.
- **Source(s)**: phase1/scripts.md:F10

#### F11: poll-copilot-rereview-start.sh — hardcoded polling schedule
- **File**: `src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh:49-71`
- **Category**: script
- **Severity**: Low
- **Issue**: Hardcodes `sleep 20` + `6 × sleep 10` = 80s maximum window. Sibling poll-new-comments.sh accepts configurable intervals.
- **Recommendation**: Extract `INITIAL_SLEEP`, `POLL_INTERVAL`, `POLL_COUNT` as optional named arguments with current values as defaults.
- **Source(s)**: phase1/scripts.md:F11

#### F12: lib.sh — validate_repo and preflight_checks have no doc comments
- **File**: `src/user/.agents/skills/wait-for-pr-comments/lib.sh:17-31`
- **Category**: script
- **Severity**: Low
- **Issue**: Both functions have no doc comments describing exit codes or side effects.
- **Recommendation**: Add: `# validate_repo <owner/repo> — exits 3 if format invalid` and `# preflight_checks — exits 3 if gh auth fails or jq missing`.
- **Source(s)**: phase1/scripts.md:F12

#### F13: detect-pr-push.sh — echo instead of printf for JSON parsing
- **File**: `src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh:10-15`
- **Category**: script
- **Severity**: Low
- **Issue**: `echo "$input" | jq` risks corrupting payloads with `\t` or `\n` escape sequences.
- **Recommendation**: Replace `echo "$input" | jq` with `printf '%s' "$input" | jq` on lines 10, 14, 15.
- **Source(s)**: phase1/scripts.md:F13

#### F14: bd-finalize-create-impl-bead.sh — tr flag-name derivation fragile
- **File**: `src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh:119`
- **Category**: script
- **Severity**: Low
- **Issue**: `tr '[:upper:]_' '[:lower:]-'` character-class positional alignment silently breaks if variable contains a digit or non-alpha char.
- **Recommendation**: Replace with two separate `tr` calls: `tr '[:upper:]' '[:lower:]' | tr '_' '-'`.
- **Source(s)**: phase1/scripts.md:F14

---

### Category: Skills

#### F7: test-review uses undocumented frontmatter fields
- **File**: `src/user/.agents/skills/test-review/SKILL.md:1-8`
- **Category**: skill
- **Severity**: Medium
- **Issue**: Frontmatter contains `context: fork` and `agent: general-purpose` — neither in official Anthropic SKILL.md schema. Unknown harness interpretation.
- **Recommendation**: Determine whether fields are consumed by any harness. If not, remove. If `context: fork` is intentional, document in Skills Primer.
- **Source(s)**: phase1/skills.md:F7

#### F8: simplify skill — invisible HTML comment maintenance metadata
- **File**: `src/user/.agents/skills/simplify/SKILL.md:7`
- **Category**: skill
- **Severity**: Low
- **Issue**: `<!-- Source: /simplify slash command... -->` is invisible in markdown previews and unreadable by agents.
- **Recommendation**: Delete comment; record sync policy in git history, or convert to explicit `## Maintenance Note` section at bottom.
- **Source(s)**: phase1/skills.md:F8

#### F10: wait-for-pr-comments hardcoded ~/.claude/skills/ install path
- **File**: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md:227,244,261,326,354,410,655,672`
- **Category**: skill
- **Severity**: High
- **Issue**: Helper script invocations hardcode `~/.claude/skills/wait-for-pr-comments/` at 8+ locations. Project convention is `${CLAUDE_SKILL_DIR}`.
- **Recommendation**: Replace all `~/.claude/skills/wait-for-pr-comments/` prefixes with `${CLAUDE_SKILL_DIR}/`. Mechanical substitution at 8+ locations.
- **Source(s)**: phase1/skills.md:F10

#### F14: condition-based-waiting — non-standard user-invocable: false frontmatter
[NOTE: A recent change merged into main reconciled our references to superpowers skills after a superpowers plugin upgrade; re-assess if this is still valid]
- **File**: `src/user/.agents/skills/condition-based-waiting/SKILL.md:3`
- **Category**: skill
- **Severity**: Low
- **Issue**: `user-invocable: false` is not in the official Anthropic SKILL.md schema. Same field in testing-anti-patterns/SKILL.md. Undefined behavior.
- **Recommendation**: Document in Skills Primer if intentional; otherwise remove and rely on description to de-prioritize.
- **Source(s)**: phase1/skills.md:F14

#### F15: writing-unit-tests — "follow-up bead" vocabulary in shared content
- **File**: `src/user/.agents/skills/writing-unit-tests/SKILL.md:60,180,197`
- **Category**: skill
- **Severity**: Medium
- **Issue**: Three locations use "follow-up bead" as a rationalization-to-reject pattern. Bead-tracker vocabulary in shared content.
- **Recommendation**: Replace "follow-up bead" with "follow-up ticket" or "deferred issue" at all three locations. Mechanical substitution.
- **Source(s)**: phase1/skills.md:F15

#### F16: verify-checklist — bead:ID privileged in discovered-work table template
[NOTE: Don't even mention "bead:ID" but generalize it to "id in the project's tracking system"]
- **File**: `src/user/.agents/skills/verify-checklist/SKILL.md:65,94`
- **Category**: skill
- **Severity**: Medium
- **Issue**: Line 94 lists `bead:ID` as first item in Discovered Work table template, privileging beads-specific notation.
- **Recommendation**: Reorder to generic first: `issue:#N / memory / backlog / bead:ID`. Replace standalone "create beads, issues, or memory entries" with "record in the project's tracking system (issues, backlog, memory, or beads if available)."
- **Source(s)**: phase1/skills.md:F16, phase2/quality-gate-and-delivery.md:F7

#### F18: run-queue description — second person imperative
- **File**: `src/plugins/beads/.agents/skills/run-queue/SKILL.md:1-8`
- **Category**: skill
- **Severity**: Low
- **Issue**: Description contains "do NOT mix with brainstorming sessions" — second-person imperative, not third-person trigger contract.
- **Recommendation**: Rewrite: "…Runs in a dedicated session; must not be mixed with interactive brainstorming sessions."
- **Source(s)**: phase1/skills.md:F18

#### F19: merge-guard description — imperative phrasing
- **File**: `src/user/.agents/skills/merge-guard/SKILL.md:3-7`
- **Category**: skill
- **Severity**: Low
- **Issue**: Description starts with "Proactively use when about to merge a PR" — imperative instruction to agent, not third-person trigger description.
- **Recommendation**: Rewrite: "Pre-merge gate that prevents merging while automated reviews (especially Copilot) are pending or review comments have not been triaged. Invoke proactively before any `gh pr merge`, `git merge`, or merge action."
- **Source(s)**: phase1/skills.md:F19

#### F23: bugfix skill — fallback ladder dead-ends on deleted skill
[NOTE: A recent change merged into main reconciled our references to superpowers skills after a superpowers plugin upgrade; re-assess if this is still valid]
- **File**: `src/user/.agents/skills/bugfix/SKILL.md:117-120`
- **Category**: skill
- **Severity**: High
- **Issue**: When three-thread synthesis cannot identify root cause, skill tells agent to escalate via `superpowers:root-cause-tracing`. This skill is deleted. The "don't guess, escalate" path is broken.
- **Recommendation**: Replace with an existing path: `superpowers:systematic-debugging`, `condition-based-waiting`, or an explicit stop-and-surface protocol.
- **Source(s)**: phase2/escalation-edge-recovery.md:F7

#### F24: human-label semantics contradict between formulas and rules
[NOTE: Pretty sure bd ready will report on human-labeled beads; one must filter to either list only human or not-human beads]
- **File**: `src/plugins/beads/.beads/formulas/docs-only.formula.toml:367-372`, `src/plugins/beads/.beads/formulas/implement-feature.formula.toml:660-666`, `src/plugins/beads/.claude/rules/beads-labels.md:10-13`
- **Category**: skill (cross-category: formula + rule)
- **Severity**: High
- **Issue**: Two formulas say `human` label excludes a bead from `bd ready`. The beads-labels.md rule says `human` is only a visibility tag and does NOT gate readiness. Active contradiction: work can be parked with `human` but still surface as ready.
- **Recommendation**: Pick one contract and update all touched files. If `human` alone is not a readiness gate, the hand-off path must add a real blocking dependency.
- **Source(s)**: phase2/escalation-edge-recovery.md:F8

---

### Category: Templates

#### F6: OpenCode AGENTS.md.template missing subtitle
[DROP: The subtitle would only be useful for human readers.]
- **File**: `src/user/.opencode/AGENTS.md.template:1-8`
- **Category**: template
- **Severity**: Low
- **Issue**: Missing subtitle line present in Claude/Codex equivalents.
- **Recommendation**: Add `User-scoped instructions for all projects.` between heading and first DYNAMIC-INCLUDE marker.
- **Source(s)**: phase1/templates.md:F6

#### F9: AGENTS.md agent frontmatter schema incomplete
- **File**: `AGENTS.md:86-93`
- **Category**: template
- **Severity**: Medium
- **Issue**: "File Formats" documents only `name`, `description`, `model`, `color`. AGENTS_PRIMER.md documents additional valid fields: `tools`, `disallowedTools`, `skills`, `effort`, `memory`.
- **Recommendation**: Expand agent frontmatter example to include `tools`/`disallowedTools`, `skills`, `effort`, `memory` with brief comments.
- **Source(s)**: phase1/templates.md:F9

#### F10: AGENTS.md skill frontmatter schema incomplete
- **File**: `AGENTS.md:98-101`
- **Category**: template
- **Severity**: Low
- **Issue**: Skill frontmatter schema shows only `name` and `description`. SKILLS_PRIMER documents additional valid fields.
- **Recommendation**: Note that additional optional fields exist (model, effort, allowed-tools) and point to docs/primers/SKILLS_PRIMER.md.
- **Source(s)**: phase1/templates.md:F10

#### F14: INSTRUCTIONS.md.template — context7 hardcoded in shared template
- **File**: `src/user/.agents/INSTRUCTIONS.md.template:18`
- **Category**: template
- **Severity**: Critical
- **Promotion**: tier1-promotion (D22)
- **Issue**: "look up docs via context7 before using it" — context7 is Claude Code-specific. Non-Claude agents will attempt to use a tool that doesn't exist.
- **Recommendation**: Replace with "look up current docs via available documentation tools (e.g., context7 MCP if available, or web search) before using it."
- **Before**: `look up docs via context7 before using it`
- **After**: `look up current docs via available documentation tools (e.g., context7 MCP if available, or web search) before using it`
- **Source(s)**: phase1/templates.md:F14

---

## Tier 2 — Deferred (file as follow-up beads, parented to agents-config-acmh)

### Category: Agents (5 findings)
[NOTE: tech-lead should not be an agent, but rather a skill.  Let's create a separate bead to tackle "sillizing" the tech-lead, starting with whether this is redundant with superpowers:dispatching-parallel-agents, or whether they two should be used together]

Major themes: Dispatch topology for bead-pipeline worker agents is unresolved (bead-implementor vs dedicated trio). tech-lead orchestration contract needs tightening (negative dispatch triggers, caller-provided agent roster, tool enforcement).

- F4: bead-implementor model tier — DEFERRED until dispatch topology resolved (F11 prerequisite)
- F6: quality-reviewer memory accumulation without eviction policy — add Memory Protocol section
- F7: tech-lead description missing negative dispatch triggers ("Do NOT dispatch when:")
- F8: tech-lead body hardcoded .claude/agents/* path — use caller-provided callable roster
- F9: tech-lead missing disallowedTools for code-free orchestrator
- F11: bead-implementor vs dedicated worker trio — declare dedicated trio canonical, deprecate bead-implementor

### Category: Commands (6 findings)

Major themes: Commands exceed lean-body target by 2-3×, embedding full methodology instead of delegating to peer skills. Scope confusion between agent-persona files vs AGENTS.md configuration files.

- F1: optimize-my-skill.md 233 lines — reduce to lean-delegation shape, strip inline methodology
- F2: optimize-my-agent.md 107 lines — extract 5-phase methodology into new optimize-my-agent skill
- F4: optimize-my-skill.md $ARGUMENTS default path ambiguous for user-level installs
- F5: optimize-my-agent.md quality rubric axes diverge from AGENTS_PRIMER schema
- F6: refresh-agents-md.md hard-codes dispatching-parallel-agents with no availability fallback
- F7: refresh-agents-md.md re-implements optimize-agents-md skill principles inline

### Category: Formulas (10 findings)
[NOTE: there's also a question to ask for each formula: what in here should be translated into one or more skills, and let the formula reference the skill?  For instance the merge-and-cleanup formula is something that I often find myself wishing was also a skill I could invoke ad-hoc.]

Major themes: Large multi-step formulas contain deterministic shell sequences that should be helper scripts. Historical motivation language appears in formula headers and step prose. Reroute protocol is duplicated across formulas.

- F1: brainstorm-bead finalize step — extract helper scripts for deterministic shell sequences (~420 lines → <100)
- F3: brainstorm-bead QUESTION FILTER — keep self-contained in discuss step, tighten to 3-4 lines
- F4: worktree-path encoding/decoding — extract to two helper scripts (bd-worktree-path-encode.sh, bd-worktree-path-decode.sh)
- F5: fix-bug and implement-feature reroute protocol — extract mechanics to bd-reroute-to-docs-only.sh, keep postcondition checklist
- F8: merge-and-cleanup file header — replace historical motivation with purpose statement
- F9: merge-and-cleanup merge-authorization step — remove historical incident rationale sentence
- F10: merge-and-cleanup cleanup step — extract inline merge-gate detection shell to bd-find-merge-gate-child.sh
- F12: brainstorm-bead vapor+pour — add clarifying comment; no formula change
- F14: preflight spec validation duplicated — extract mechanics only (claim-walk, label stamp, worktree creation); keep policy per-formula
- F15: merge-and-cleanup check-pr-comments — delegate cleanly to wait-for-pr-comments skill

### Category: Rules (10 findings)

Major themes: Two rule files (beads.md, beads-labels.md) contain reference material that should move to opt-in reference files, while normative runtime contracts must stay always-loaded. Cross-reference anchors are fragile. codex-routing.md hardcodes drifting plugin paths and model names.

- F1: beads.md I1/I2 parent-chain invariants — extract shell sequences to bd-walk-parents.sh; retain invariant requirements in rule
- F2: beads.md "bd ready" dual-list filter — extract jq expression to bd-ready-to-brainstorm.sh
- F3: beads.md over-length — extract CLI glossary and non-normative tables; retain runtime contract
- F4: beads-labels.md — keep semantic table; trim repetitive command examples to reference file
- F5: beads/delivery.md — reframe final paragraph as normative (never/always language)
- F6: Two delivery.md files — add `## Core delivery rules` heading as stable anchor for cross-reference
- F7: completion-gate.md — keep compact delivery bridge paragraph; remove duplicated ordered skill list
- F11: codex-routing.md — hardcoded plugin install path → move to settings.json env var or helper script
- F12: codex-routing.md — hardcoded model names will rot → abstract behind aliases; add "current as of" datestamp
- F15: worktrees.md — restructure Override clause to make three cases explicit

### Category: Scripts (4 findings)

Major themes: poll-ready-beads.sh is the queue's idle-state backbone and has multiple active hazards for autonomous overnight use (positional params, no set -e, stdout contamination).

- F3: poll-ready-beads.sh — add --max-minutes named flag, --help, non-integer guard; fix shebang to /usr/bin/env bash
- F4: poll-ready-beads.sh — move timeout message to stderr; emit JSON sentinel on exit 1
- F5: check-merge-eligibility.sh — add named flags (--repo, --pr, --comments-seen); add usage() block
- F7: closed-bead-preflight.sh — evaluate intentional mixed positional+flag interface; document decision

### Category: Skills (15 findings)
[NOTE: we're going to replace the run-queue skill with a script-orchestrated process; we can defer all run-queue modifications or even just delete the skill now.]

Major themes: wait-for-pr-comments/reply-and-resolve-pr-threads have beads leakage into shared skill content (Critical). implement-bead has contract mismatch with ralf-implement. ralf-implement/ralf-review don't reference their supporting prompt files. Several deprecated/deleted references remain.

- F1: wait-for-pr-comments 828 lines — extract to SCHEMA.md, RECOVERY.md, SUBAGENT-CONTRACT.md; keep phase map inline
- F2: Schema validation guards duplicated — define once in shared SCHEMA.md referenced by both skills
- F3: wait-for-pr-comments beads leakage — split shared PR-review core from beads-only autonomous mode
- F4: reply-and-resolve-pr-threads beads leakage — mirror F3 split
- F5: implement-bead dense prose — rewrite §1 and §2 as decision tables inline
- F6: implement-bead formula-label parsing — extract parsing expression; keep two state-specific branches
- F9: simplify skill — replace "bd remember" with tool-agnostic alternative
- F11: reply-and-resolve-pr-threads — move validate-inventory.sh to shared location; update both cross-skill references
- F12: ralf-it deprecated stub — delete entirely; 16 lines loading into every session is wasteful
- F13: ralf-implement and ralf-review — add explicit prompt-file references at dispatch branches
- F17: start-bead — trim verbose forensics; keep routing matrix and recovery branches inline
- F20: implement-bead and ralf-implement describe incompatible orchestration contracts — choose one and encode explicitly
- F21: start-bead can route into implement-bead from non-orchestrator context — add preflight orchestrator check
- F22: run-queue announces PR artifacts not exposed by implement-bead's contract — make outcome-driven
- F25: run-queue resolves implement-bead escalations too loosely — add paired-resolution procedure

### Category: Templates (11 findings)
[NOTE: the templates can and should be empty when there's nothing; we can violate "markdown" standards here, e.g. it's not necessary to have a header, or content, etc.; empty template files are fine - no need to remove them.]
[DROP F8 (settings.json.template permissions allow list empty)]
[NOTE: file references here are ambiguous as there are multiple AGENTS.md files or INSTRUCTIONS.md files - make sure you don't lose path context when filing beads]

Major themes: Codex and Gemini templates are missing all behavioral rules (Critical gap). Several stub files install meaningless headings. settings.json.template has a silently-failing hook and an empty allow list.

- F1: Codex and Gemini templates missing all rules — add DYNAMIC-INCLUDE-RULES marker with tool-neutral rules first (delivery.md, git-commits.md)
- F2: CLAUDE-EXTENSIONS.md.template empty stub — populate with at least one informative line, or remove
- F3: CODEX-EXTENSIONS.md.template and GEMINI-EXTENSIONS.md.template empty stubs — populate or remove
- F4: AGENTS.md vision section bd command — recommendation-only; future cycle: replace with label reference
- F5: INSTRUCTIONS.md.template skill names — keep named shared skills; replace "Plan mode" with "planning phase"
- F7: settings.json.template hook path hardcoded — add existence guard before invocation
- F8: settings.json.template permissions allow list empty — populate with baseline read-only operations
- F11: AGENTS.md graphify section — add "(orchestrator only — subagents must not run this)" qualifier
- F12: OPENCODE-EXTENSIONS.md.template — rewrite header to distinguish source vs installed context
- F13: INSTRUCTIONS.md.template database constraint — reword to lead with generic principle; keep Dolt/SQLite as examples
- F15: AGENTS.md Session Completion bd dolt push — add "(beads only — skip if beads not installed)" conditional note

---

## Tier 3 — bd-Sequence Extractions (file as a separate follow-up bead)

The audit specifically tasked extraction of deterministic shell sequences from formula prose and rule files into named helper scripts. This is a non-trivial scope that warrants a dedicated bead.

**Targeted extractions** (in priority order):

1. **`bd-walk-parents.sh --mode claim|close <id>`** — I1 (claim walk) and I2 (close walk) shell sequences from beads.md F1. These are the most frequently executed sequences across the whole runtime.

2. **`bd-finalize-children-check.sh`** — children pre-flight check from brainstorm-bead finalize step F1. The "children-check" pattern: enumerate child beads, verify none are in_progress before finalize proceeds.

3. **`label-copy-filter` helper** — label-copy filtering logic from brainstorm-bead finalize step F1. The "label-copy-filter" pattern: copy labels from source bead to implementation bead, stripping session markers and meta-labels.

4. **`bd-worktree-path-encode.sh <path>` / `bd-worktree-path-decode.sh <encoded>`** — worktree path encoding/decoding appearing in five locations across three formulas (F4). Bijection (`_ → _u`, `/ → __`) in one canonical script eliminates five drift-prone prose copies.

5. **`bd-reroute-to-docs-only.sh`** — reroute protocol mechanics from fix-bug and implement-feature red-tests steps (F5). Extract steps 2-11; keep inline postcondition checklist.

6. **`bd-find-merge-gate-child.sh --bead-id <id>`** — merge-gate detection loop from merge-and-cleanup cleanup step (F10). ~15 lines of deterministic bash for iterating children and checking labels.

7. **`bd-ready-to-brainstorm.sh`** — jq filter for "List 2" in beads.md F2.

**Not in this bead's scope**: dep-migration extraction (brainstorm-bead §3 inbound dep retargeting) is owned by `agents-config-wmjy`. Do not duplicate that work here.

---

## Adjacency Notifications

### agents-config-2gzy (refactor skill helper scripts to named parameters)
[NOTE: "Share these findings with the bead's executor..." - share proactively by updating the bead's description or append comments/notes]

The following script findings directly overlap with agents-config-2gzy's scope. Share these findings with the bead's executor before beginning work to avoid duplicate refactor passes:

Priority order (from scripts.md by-category adjacency section):
1. **F3 + F4 + F8** (`poll-ready-beads.sh`): positional param, missing `set -euo pipefail`, stdout contamination on timeout path. **Highest risk** — active hazard for autonomous overnight runs.
2. **F5** (`check-merge-eligibility.sh`): positional params for a three-argument script where arg-ordering errors bypass the merge gate.
3. **F1** (`bd-record-decision.sh`): usage block inconsistency. Can be addressed in the same commit as 2gzy work or independently.
4. **F7** (`closed-bead-preflight.sh`): intentional interface asymmetry — evaluate and document the decision; do not necessarily change the interface.

### agents-config-wmjy (brainstorm-bead §3 inbound dep retargeting)
[NOTE: "Confirm with wmjy..." - share proactively by updating the bead's description or append comments/notes]

dep-migration extraction is wmjy's responsibility. This audit's Tier 3 scope (see above) explicitly excludes that work. Confirm with wmjy that the child migration loop in brainstorm-bead finalize step is handled. This audit produces no overlapping work.

---

## Cross-Category Reclassifications

The following findings in one content-type category have primary effect on a different content type:

- **skills.md F24** (human-label semantics contradiction): finding is canonical in the skills category but its primary change targets `beads-labels.md` (rules category) and two formula files (`docs-only.formula.toml`, `implement-feature.formula.toml`). Executor must update all three file types together.

- **skills.md F20** (implement-bead/ralf-implement contract mismatch): finding is canonical in the skills category but the resolution touches ralf-implement (skills/shared) and potentially implement-bead's dispatch contract (skills/plugin). If a beads-specific adapter skill is introduced, it crosses the shared ↔ plugin category boundary.

- **templates.md F1** (Codex/Gemini missing rules): finding is in templates but the primary work is in the rule files — each rule must be audited for Claude-specific constructs before inclusion in Codex/Gemini templates. `delivery.md` and `git-commits.md` are tool-neutral and safe to include immediately; `codex-routing.md` is Claude-specific and must be excluded.

---

## Verification Status

- [x] Verifiable check 1: every Phase 2 DISAGREE/PARTIAL has decisions.md entry — **PASS** (gap check script returns `missing: 0` after D31 appended)
- [x] Verifiable check 2: every Tier 2→Tier 1 promotion has Snippet block — **PASS** (D22 contains Before/After snippet; only one tier1-promotion in decisions.md)
- [x] Verifiable check 3: every Tier-C demotion has Type+Rationale — **PASS** (D30 has `Type: tierC-demotion` and full Rationale)
- [ ] Verifiable check 4: tier-C share ≤ 30% — **FAIL (46.1%)** — Actual post-demotion count across all by-category outputs: 47 Tier-C / 102 accepted = 46.1%. The D30 demotion was computed on a 88-finding subset from the initial aggregator pass that did not include Phase 2-promoted findings (F15 formulas, F20–F25 skills). The by-category files are canonical; the cap analysis in decisions.md used an incomplete finding set. Additional demotions would be needed to bring the actual by-category Tier-C share to ≤ 30%, but this would require demoting 19 more findings and would materially change the audit's coverage of vision-advancement goals. Recommend: accept the 46.1% figure as the accurate final state and waive the cap for this audit cycle given the Phase 2 scope expansion.
