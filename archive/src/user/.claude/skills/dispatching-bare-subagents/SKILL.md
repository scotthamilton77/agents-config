---
name: dispatching-bare-subagents
description: Use when a subagent's answer must NOT be shaped by this session's project/user CLAUDE.md, rules, injected persona, or auto-memory — a control condition, a blind or unbiased second opinion, a semantic-equivalence or synthesis judgment free of house-style bias, testing what a skill description alone would trigger, or checking what the harness's raw system prompt actually contains. Also applies to "bare mode", "minimal context", "virgin context", "clean session", "no persona", "without our rules", "context contamination", or comparing in-repo agent behavior against an unbiased baseline. Not for ordinary subagent dispatch (the Agent tool always inherits full context — see orchestrating-subagents) and not for routing to a different model (see openrouter-claude-subagent) — this is about stripping context, not changing the model.
---

# Dispatching Bare Subagents

## Overview

The in-session Agent/Task tool has no context-stripping knob. Every subagent
it spawns — named or unnamed, `general-purpose` or a custom `.claude/agents/*.md`
role — gets the same assembled system prompt the root session has: project
and user `CLAUDE.md`/`AGENTS.md`, `.claude/rules/*.md`, the skill listing,
MCP tool defs, and any hook-injected content (e.g. a Sidekick persona
injected on `SessionStart`). Confirmed empirically in this repo: a
Task-tool subagent asked to report its persona recited the project's
`<your-persona>` block verbatim and had no awareness of the session's
injected character voice — file-based context propagates, `SessionStart`
hook injections do not, and neither is something you can turn off from
inside the Agent tool.

When a judgment genuinely needs to be free of that — not just free of the
persona, but free of this repo's opinions about SOLID/DRY, its rules, its
memory — the fix isn't a prompt instruction ("ignore your persona"); the
model will still have all of it in context and can leak it. The fix is a
**separate OS process**: `claude --bare`, shelled out via `Bash`, not the
Agent tool.

## When to Use

- A synthesis or semantic-judgment task where house style/persona/rules
  would bias the answer (e.g. "does this docstring actually match the
  code," "are these two error messages semantically equivalent," "grade
  this candidate skill description against near-miss queries").
- A control condition to compare against — "what would a stock Claude
  session say here, before our ruleset touches it."
- Verifying a claim about what the harness's own default system prompt
  contains, unpolluted by this repo's `AGENTS.md`/rules stack.
- Testing a skill's trigger-eval queries (per `writing-skills`) without the
  candidate skill's own description or sibling skills' descriptions already
  loaded into the test session's context.

**Not for:** routine subagent dispatch — use the Agent tool and
`orchestrating-subagents` for nesting concerns; that path *wants* full
context. Not for cheaper/different-model routing with full context intact —
that's `openrouter-claude-subagent`. The two compose (nothing stops
`--bare` plus an OpenRouter key) but solve different problems: this skill
removes context, that one changes the model.

## Core Pattern

```bash
claude --bare \
  --system-prompt "<the only instructions this session should have>" \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" \
  -p "<the task>"
```

Same non-interactive contract as any headless dispatch: `--permission-mode
dontAsk` plus an explicit `--allowedTools` list, or the child hangs waiting
for a prompt no one can answer (see the headless-claude rule). `--bare`
does not relax that requirement — it's orthogonal.

`--bare` skips, by design: hooks, LSP, plugin sync, attribution,
auto-memory, background prefetches, keychain reads, and CLAUDE.md
auto-discovery (confirmed via `claude --help`). It does **not** skip skills
— they "still resolve via /skill-name" if the child process explicitly
invokes one, so a bare session isn't a guarantee against skill-injected
bias unless you also avoid naming skills in the prompt.

Add back only what the task needs, explicitly — nothing is implicit in
`--bare` mode:

| Need | Flag |
|---|---|
| A task-specific system prompt | `--system-prompt "<text>"` or `--system-prompt-file <path>` |
| Append to (not replace) the default prompt | `--append-system-prompt "<text>"` or `-file` variant |
| A specific directory's `CLAUDE.md` | `--add-dir <path>` |
| MCP servers | `--mcp-config <path>` |
| Settings (incl. `apiKeyHelper`) | `--settings <file-or-json>` |
| Custom agent definitions | `--agents <path>` |
| Plugins | `--plugin-dir <path>` |

## Auth Gotcha

`--bare` auth is **strictly `ANTHROPIC_API_KEY`** (or `apiKeyHelper` via
`--settings`) — OAuth and keychain are never read, even if the parent
session is logged in that way. If `ANTHROPIC_API_KEY` isn't set in the
environment, the bare child fails auth even though the exact same terminal
can run a normal `claude` session fine. Check `echo $ANTHROPIC_API_KEY`
before troubleshooting anything else when a `--bare` invocation errors out
on auth. Third-party providers (Bedrock/Vertex/Foundry) use their own
existing credentials and are unaffected.

## Quick Reference

```bash
# Blind semantic-equivalence check, no repo context at all
claude --bare \
  --system-prompt "You judge whether two error messages mean the same thing. Answer only 'equivalent' or 'not equivalent' plus one sentence why." \
  --permission-mode dontAsk \
  --allowedTools "" \
  -p "A: 'connection refused on port 5432'  B: 'could not reach the database'"

# Control-condition read on a file, no project CLAUDE.md/rules loaded
claude --bare \
  --permission-mode dontAsk \
  --allowedTools "Read" \
  -p "Read src/api/handler.py and describe what it does, in plain terms."
```

## Common Mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Using the Agent tool and telling the subagent to "ignore your persona/rules" | It still has them in context and can leak them | Shell out `claude --bare` instead — a real separate process |
| Assuming `--bare` blocks skill invocation | Bias can re-enter if the prompt names a skill | Don't reference skills in a bare judgment prompt |
| Running `--bare` in a shell without `ANTHROPIC_API_KEY` exported | Auth fails even though normal `claude` works fine in the same shell | Export the key or pass `apiKeyHelper` via `--settings` |
| Omitting `--permission-mode dontAsk` / `--allowedTools` | Child hangs or silently no-ops | Always pass both, per the headless-claude rule |
| Reaching for `--bare` for ordinary subagent work | Loses the ruleset/skills/memory that ordinary dispatch is supposed to have | Use the Agent tool; this skill is the exception path, not the default |
