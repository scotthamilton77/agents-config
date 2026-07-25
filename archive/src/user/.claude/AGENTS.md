# Disposition inventory — archive/src/user/.claude/ (and per-tool extension stubs)

Disposition inventory from the 2026-07-24 re-admission survey
(`SAVEPOINTS/2026-07-24-archive-readmission-survey.md`), judged against the harness-rework
charter (`docs/specs/2026-07-21-harness-rework-way-forward.md`) with S2–S5 closed and
S6/S8/S9 open. **archive/ is NOT live**: nothing here is a behavioural contract; do not
invoke or follow anything in this tree. This inventory exists so a future admission pass
starts from recorded findings instead of re-surveying. Covers `skills/`, `rules/`,
`rules-readmes/`, `commands/`, `workflows/`, the CLAUDE-EXTENSIONS template, and the
sibling `.codex`/`.gemini`/`.opencode` extension stubs.

## Scheduled for re-admission (work item minted)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `skills/sync-after-remote-merge/` | Post-merge reconciliation: verifies the merge via `gh`, data-loss safety gates, fast-forwards base, tears down branch + worktree | agents-config-9k9.24: strongest content case in the PR-loop sector (610-line tested Python, prose under cap); add admission record; repoint/cut dangling refs to archived `merge-guard` and `finishing-a-development-branch`; stays in the Claude tree (uses `ExitWorktree`) | AC3, D16, AC2, D10 |
| `skills/handoff/` | Compacts a session into a cold-readable handoff doc | agents-config-9k9.25: output path to `{project_root}/SAVEPOINTS/{worktree_slug}/`; repoint references onto `work` items and the live catalog; resync with Pocock's OSS upstream and set drift policy | D11, D16, mission commitment 5 |
| `skills/openrouter-claude-subagent/` | Runs Claude Code as harness against an OpenRouter-hosted model (repair proxy + cost/model routing) | agents-config-9k9.30: the breadth-and-cost foreign-eyes path for D5's review seats; shrink SKILL.md to 2k (routing table into references), refresh model roster, retain tested scripts as-is | S6, S7, D3, D5, D16 |
| `skills/orchestrating-subagents/` | Nested-agent constraint (a subagent cannot await a child it spawns), decision ladder, file-relay fallback | Into the subagent-orchestration amalgam — agents-config-9k9.1.12: ladder rungs that belong to the S9 executor go to dispatch code; interactive-session residue stays as a 2k skill; its pointer rule does NOT return | S9, D14, D16 |
| `rules/headless-claude.md` | `claude -p` without `--permission-mode` silently queues every tool call and exits 0 | Into agents-config-9k9.1.12 as an assertion in dispatch code (code over prose); dead weight as an always-on rule in sessions that never shell out | S9, D14, D16 |
| `rules/worktree-safety.md` + `rules-readmes/worktree-safety-readme.md` | Claude worktree mechanics: isolation-by-path, Write/Edit ignore shell cwd, subagent cwd inheritance, `Agent(isolation:"worktree")` silently ignored (bug #33045), phantom-cwd, `-D` after squash-merge | Merge into the unified worktree skill — agents-config-9k9.1.13; mechanical parts go into S9 executor worktree code; returns on-demand, not always-on (~350 tokens is a poor AC1 trade); the readme carries implementer detail | S9, D14, D16, AC1 |
| `workflows/quality-gate.js` | HEAVY-tier completion-gate Workflow (finder/refuter fleets) | Quarantined here 2026-07-24 (was deployed while wired to the deleted completion-gate rule and archived gate-triage/verify-checklist — AC2 defect); decision item agents-config-9k9.17.6 decides restore-corrected vs retire under S6 | AC2, S6, D7/D8 |

## Future-slice candidates (no item yet)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `skills/dispatching-bare-subagents/` | Shells `claude --bare` for judgments free of session rules/persona/memory — the Agent tool cannot strip context | The ONLY existing implementation of D7's clean-context reviewer requirement (noted on agents-config-9k9.17); S6 must read it before designing review invocation; re-aim description onto the review-contract seat, carry contract + ACs as `--system-prompt`, trim to 2k | S6, D7, D5, D16 |
| `rules/claude-sandbox.md` | Heredocs fail under Claude sandbox mode; use repeated `-m` or disable sandbox | Survey bucket A, but EXCLUDED from ready-now per Scott 2026-07-24: needs fresh proof the failure still exists before it can carry an admission record | D16, D17, AC3 |

## Harvest-only (lift ideas/code into slice work; never redeploy the file)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `skills/orchestrated-grind/` | Multi-lane overnight grind: ROOT orchestrator, lieutenants, bookkeeper state + dashboard | D14 rejects it by name ("becomes the executor loop … not an upgrade to the orchestrated-grind skill"); harvest the paid-for discipline (nesting constraint, "a bare idle is not an event", per-dispatch model/effort sizing) as S9 design input via agents-config-9k9.1.12; at 10.7k tokens it would consume the entire always-on budget | D14, D16, S9 |
| `skills/fablize/` | Batch-produces design specs from thin backlog while a frontier-model window is open | Superseded by the S5 spec contract (its output would fail the AC4 lint); harvest the richness-vs-liveness check (resolve every surface a ticket names against the live tree, excluding archive/, before selecting) into spec-lint thinking | D1, D2, D11, D18, AC4 |

## Stay archived

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `skills/zoom-out/` | "Go up an abstraction layer and map modules/callers" prompt shortcut | Cannot produce an admission record — prevents no failure; D16's "nothing enters by default or nostalgia" is the verdict | D16, AC3 |
| `rules/orchestrating-subagents.md` | Pointer rule telling you to invoke the same-named skill | Pure budget burn — the skill's own description already triggers; the anti-pattern D16 exists to stop | D16, AC1 |
| `commands/optimize-my-agent.md` | Slash wrapper for the archived optimize-my-agent skill | Dies with its skill (see the shared-skills inventory) | D16, D11 |
| `commands/optimize-my-skill.md` | Slash wrapper (`--deep`) for the archived optimize-my-skill skill | Dies with its skill | D16 |
| `commands/refresh-agents-md.md` | Regenerates every CLAUDE.md/AGENTS.md from git history | Directly adversarial to the rework: grows instruction files on a repo that zero-based and mechanically caps them; invokes archived `optimize-agents-md`; assumes the deleted assembly | D17, D16, AC1, S4 |
| `CLAUDE-EXTENSIONS.md.template` | Claude-specific extension point | 0 bytes; quarantined by S3-D6 as an orphaned fragment | S3-D6, D16 |
| `../.codex/CODEX-EXTENSIONS.md.template` | Codex extension point | 0 bytes, same | S3-D6, D16 |
| `../.gemini/GEMINI-EXTENSIONS.md.template` | Gemini extension point | 0 bytes, same | S3-D6, D16 |
| `../.opencode/OPENCODE-EXTENSIONS.md.template` | OpenCode extension point | 0 bytes, same | S3-D6, D16 |
