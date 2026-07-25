# Disposition inventory — archive/src/user/.agents/ (rules, agents, templates)

Disposition inventory from the 2026-07-24 re-admission survey
(`SAVEPOINTS/2026-07-24-archive-readmission-survey.md`), judged against the harness-rework
charter (`docs/specs/2026-07-21-harness-rework-way-forward.md`) with S2–S5 closed and
S6/S8/S9 open. **archive/ is NOT live**: nothing here is a behavioural contract; do not
invoke or follow anything in this tree. This inventory exists so a future admission pass
starts from recorded findings instead of re-surveying. Covers `rules/`, `rules-readmes/`,
`agents/`, and the root templates; `skills/` has its own inventory.

## Scheduled for re-admission (work item minted)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `rules/memory-routing.md` | Routes each durable fact to exactly one home (repo AGENTS.md vs user/native memory) by scope | Bucket A (~120 tokens, passes all four D17 tests); shakedown candidate for the admit-request skill — agents-config-9k9.27; needs only an admission record | D16, D17, AC2, AC3 |
| `rules/subagents.md` | Right-size model/effort per dispatch; context-free reviewer findings are signal not gospel; don't message terminated agents | Split three ways into the subagent-orchestration amalgam — agents-config-9k9.1.12: bullet 1 becomes executor dispatch code/lint, bullet 2 is superseded by D8's Mechanical/Advisory split, bullet 3 joins orchestrating-subagents; nothing survives as a rule | S9, D14, D8 |
| `rules/worktrees.md` | Tool-agnostic worktree conventions: location, one-committer-per-worktree, commit-banner SHA capture, no sibling `git restore`, no copying locked DBs | Merge into the unified worktree skill — agents-config-9k9.1.13 (with Claude `worktree-safety` and `using-git-worktrees`); returns as an on-demand skill, not an always-on rule | S9, D14, D16 |

## Future-slice candidates (no item yet)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `SESSION-PRIMER.md.template` | The "1% rule" skill-invocation discipline with rationalization red-flag table and skill-priority ordering | Weakest candidate: S3-D6 explicitly reserved its discipline for later re-entry but no open slice owns it; content is stale (names the deleted `brainstorming` skill); re-entry keeps the invoke-before-acting rule and discards the table/markup/skill names | S3-D6, D16, D17, S5 |

## Harvest-only (lift ideas/code into slice work; never redeploy the file)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `agents/quality-reviewer.md` | Single-pass reviewer across security/quality/perf/tests with severity ranking | Harvest the review-dimension checklist as raw input to the S6 class-specific code contract; the agent file contradicts D7/D8 on four axes (house rulebook, wrong severity taxonomy, plan-alignment vs deleted plan artifact, re-litigation loop) — see note on agents-config-9k9.17 | S6, D7, D8, D4 |
| `agents/tech-lead.md` | Prose orchestrator: decompose, dispatch, monitor, escalate | Harvest the idle/overdue heuristics ("a bare idle is the absence of an event"; detect dead workers by elapsed time against a missing artifact; probe the world, don't message the agent) into the S9 park/escalate design via the amalgam item agents-config-9k9.1.12; the artifact itself is superseded by D14's executor loop | D14, S9, D11, D12 |

## Stay archived

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `rules/completion-gate.md` | Routes completion gates to SKIP/SERIAL/HEAVY and chains gate→PR→review→merge→sync | Charter names this text for deletion; cites six archived artifacts; its "machine must not stop at PR-created" job belongs to the S9 executor and D9's thin merge vehicle in code | D13, D9, D10, S9, AC1, AC5 |
| `rules/delegation.md` | Routes work classes to skills | Router over a catalog that no longer exists (5 of 6 destinations archived); D18's goal is a catalog small enough to need no router | D18, D16 |
| `rules/bash-scripting.md` + `rules-readmes/bash-scripting-readme.md` | Under `set -e`, side-effecting commands on the RHS of `&&` escape the error trap | Correct but fails D17 universality; the repo's Python-over-Bash principle pushes away from the hazard; better as a shellcheck lint or call-site comment | D17, D16 |
| `rules/user-prompts.md` | AskUserQuestion caps (4 options/4 questions) with prose-list fallback | Misplaced (Claude-only tool in the tool-agnostic tree); belongs inside whichever skill interrogates the user | S5, D16, D17 |
| `agents/pr-comment-fixer-team.md` | Per-comment PR fix worker with JSON report | Dispatched by `wait-for-pr-comments` (AC5 deletion); D9 removes PR comments as a review medium — a human PR comment is an escalation, not work to dispatch | AC5, D9, D13 |
| `INSTRUCTIONS.md.template` | The 154-line shared-instruction "mountain" | Deleted by S4; survivors already extracted into the zero-base (`USER-CORE.md.template`); every remaining line failed the D17 four-part test | S4, D17 |
| `AGENT-PERSONA.md.template` | Agent personality/expertise template | S3-D6: personas are injected dynamically at session start by companion tooling; static copy loses nothing | S3-D6, D17 |
| `USER-PERSONA.md.template` | User description/preferences template | Same — dynamically injected; static copy is redundant surface | S3-D6, D17 |
