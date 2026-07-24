# Reference

A scannable index of what ships. For installer flags and pruning semantics, see
the [README](../../README.md#installation).

## Skills by phase

| Phase | Skills |
|-------|--------|
| Brainstorm / design | `grilling`, `grill-with-docs`, `to-spec`, `prototype` |
| Implement | `test-driven-development`¹, `writing-unit-tests`, `bugfix` |
| Test review | `test-review`, `writing-unit-tests` |
| Completion gate | `gate-triage`, `simplify`, `verify-checklist` |
| Delivery | `using-git-worktrees`¹, `finishing-a-development-branch`¹, `monitor-pr`, `wait-for-pr-comments`, `reply-and-resolve-pr-threads` |
| Merge | `merge-guard` |
| Persist / improve | `self-improving-agent`, `retrospect`, `where-does-this-fit`, `whats-next` |
| Orchestration | `orchestrating-subagents` (Claude-only) |
| Meta / authoring | `optimize-agents-md`, `optimize-my-agent`, `optimize-my-skill`, `improve-codebase-architecture` |
| Adversarial (explicit) | `ralf-review`, `ralf-implement` |
| Comms | `caveman` |

¹ Provided by the [superpowers](https://github.com/obra/superpowers) plugin, not this repo.

## Agents

| Agent | Role |
|-------|------|
| `quality-reviewer` | Code quality/security/maintainability review + plan-vs-implementation drift detection |
| `tech-lead` | Orchestrates complex multi-step work across specialized agents and skills (no Write/Edit) |
| `pr-comment-fixer-team` | Fixes a single PR review comment; invoked per-comment by the PR-feedback flow |

## Commands (Claude slash commands)

| Command | Purpose |
|---------|---------|
| `/optimize-my-agent <path>` | Analyze and improve an agent definition file |
| `/optimize-my-skill <path>` | Analyze and improve a skill definition |
| `/refresh-agents-md` | Refresh CLAUDE.md/AGENTS.md files from current repo state |

## Rules (always-on)

**Shared** (`src/user/.agents/rules/`): `completion-gate`, `delegation`,
`subagents`, `worktrees`, `memory-routing`, `user-prompts`, `bash-scripting`.

**Claude-specific** (`src/user/.claude/rules/`): `claude-sandbox`,
`headless-claude`, `orchestrating-subagents`, `worktree-safety`.

Rules encode the always-on contract: the laws (L0–L3), the decision matrix,
delegation routing, subagent right-sizing, worktree safety, and the completion
gate's tier routing.

## Plugins (`src/plugins/`, auto-detected)

| Plugin | Detected when | Installs |
|--------|---------------|----------|
| `beads` | `bd` on PATH or `~/.beads/` exists | bd CLI gotchas + discovered-work rules; routes `~/.beads/` |
| `graphify` | `~/.graphify/` or `graphify` on PATH | graphify discipline rule |
| `codex` | `~/.codex/` or `codex` on PATH | Codex routing rule (Claude-only) |

## Key `settings.json` pieces (Claude)

| Area | What ships |
|------|-----------|
| Permissions | Safe-command allowlist + hardened `deny` (no reading `.env`/SSH keys/`/etc/shadow`, no writing system dirs) |
| Hooks | `PostToolUse`: ruff lint/format on Python edits; PR-push detection to trigger review monitoring |
| Experimental | agent teams, fork-subagents, tool search, auto-background tasks (env vars) |

## `project-config.toml` sections

Placed at your project root; all sections optional. See
[Configuration](./configuration.md#3-set-your-projects-control-surface-project-configtoml).

| Section | Controls |
|---------|----------|
| `[gates]` | build / typecheck / lint / test commands |
| `[coverage]` | coverage applicability + threshold |
| `[completion-gate]` | SKIP/SERIAL/HEAVY tier thresholds |
| `[review-expectations]` | which reviews to wait for (Axis 1) |
| `[merge-policy]` | who may merge — `never` / `explicit` / `rule-based` (Axis 2) |
| `[foreign-cli]` | cross-model (Codex/Gemini) binaries + model selection |

## The capability roadmap

The deeper vision is tracked as milestone beads:

```bash
bd list --type milestone
```

M0 discipline-layer rearchitecture · M1 stabilize + accelerators · M2
brainstorm-readiness gate · M3 worker fleet through PR autonomy · M4 overnight
autonomy · M5 post-MVP. See the repo `AGENTS.md` for the current status table.
