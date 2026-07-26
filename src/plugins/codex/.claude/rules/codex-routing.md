# Codex Routing

When delegating to Codex, always go through the Claude Code Codex plugin — never the raw `codex` binary.

**Invocation (from a skill or subagent):**
```
CODEX_HOME="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex}"
node "$CODEX_HOME/scripts/codex-companion.mjs" task [--model <name>] [--write] < prompt.md
```
`CLAUDE_PLUGIN_ROOT` is only set for plugin-owned code; fall back to the marketplace install path. Omit `--write` for read-only (the sandbox enforces it); add `--write` only when Codex must edit files. Pipe the prompt on stdin — `--prompt-file` works today but lives in the plugin's internal `codex-cli-runtime` contract, so prefer stdin for forward-compat.

**Flags:** `codex task` accepts `--json`, `-m/--model`, and
`--effort <none|minimal|low|medium|high|xhigh>`, and runs read-only when `--write`
is omitted (the sandbox enforces it). Autonomous callers pipe their prompt on
stdin and depend on these flags; check for such callers before changing them.

**Model selection** (leave `--model` unset to accept the plugin default; set explicitly when a task profile matches):
- Architecture, cross-subsystem, security, final pre-merge pass → `gpt-5.6-sol`
- Standard review, implementation, general default → `gpt-5.6-terra`
- First-pass triage, diff summary, per-file parallel review, cost-sensitive runs → `gpt-5.6-luna`
- Deeply code-centric, Codex-tuned agentic work → `gpt-5.3-codex`

**Prompt best practices:** One task per run, explicit completion contract. For large blocks of context, use a separate file and reference it in the prompt to avoid hitting input token limits.

**Slash commands** (`/codex:review`, `/codex:adversarial-review`, `/codex:rescue`, `/codex:status`, `/codex:result`, `/codex:cancel`) are user-initiated only; the model cannot fire them. Suggest them to the user instead.
