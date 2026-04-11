# Codex Routing

When delegating to Codex, always go through the Claude Code Codex plugin — never the raw `codex` binary.

**Invocation (from a skill or subagent):**
```
CODEX_HOME="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex}"
node "$CODEX_HOME/scripts/codex-companion.mjs" task [--model <name|spark>] [--write] < prompt.md
```
`CLAUDE_PLUGIN_ROOT` is only set for plugin-owned code; fall back to the marketplace install path. Omit `--write` for read-only (the sandbox enforces it); add `--write` only when Codex must edit files. Pipe the prompt on stdin — `--prompt-file` works today but lives in the plugin's internal `codex-cli-runtime` contract, so prefer stdin for forward-compat.

**Model selection** (leave `--model` unset to accept the plugin default; set explicitly when a task profile matches):
- Architecture, cross-subsystem, security, final pre-merge pass → `gpt-5.4`
- First-pass triage, diff summary, per-file parallel review, cost-sensitive runs → `gpt-5.4-mini`
- Deeply code-centric, Codex-tuned agentic work → `gpt-5.3-codex-spark` (alias: `spark`)

**Cost:** `mini` ≈ 30% of `gpt-5.4`; `spark` ≈ 70–93% of `gpt-5.4`. Parallelize with `mini`, decide with `gpt-5.4`.

**Prompt format:** follow the plugin's `codex:gpt-5-4-prompting` skill — XML-tagged blocks, one task per run, explicit completion contract.

**Slash commands** (`/codex:review`, `/codex:adversarial-review`, `/codex:rescue`, `/codex:status`, `/codex:result`, `/codex:cancel`) are user-initiated only; the model cannot fire them. Suggest them to the user instead.
