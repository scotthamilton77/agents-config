---
name: openrouter-claude-subagent
description: Use when delegating work to an OpenRouter-hosted model (Kimi, GLM, Gemini Flash, GPT-5.6 variants, etc.) while still running it through the Claude Code CLI as the agent harness — spinning up a subagent on a different or cheaper model, routing a task through OpenRouter, launching a nested claude instance against an OpenRouter key, or when the user says "use openrouter", "route this to <model>", "delegate to a cheap model", "spin up a kimi/glm/gemini-flash subagent", "run this through OpenRouter", or asks which OpenRouter model fits a task and what it costs. Not for delegating to Codex, Gemini CLI, or any harness other than a nested claude process.
---

# OpenRouter Claude Subagent

## Overview

Launches Claude Code itself as the agent harness, but repoints its model
traffic at OpenRouter instead of Anthropic — a second `claude` process, in
its own config directory, talking to whatever OpenRouter-hosted model fits
the task. You still get Claude Code's tool-use loop, file editing, and
permission system; only the model backing it changes.

Three decisions this skill makes for you, in order: **which tools the
subagent may use**, **which model**, **what effort/reasoning level**. The
first is a hard safety gate. The other two are judgment calls you can either
make yourself or hand to the calling agent's discretion.

## When to Use

- The user wants a task delegated to an OpenRouter model but still driven by
  Claude Code's tool loop (not a bare API call, not Codex/Gemini CLI).
- The user wants to compare Claude's output against another model's on the
  same task, or wants a cheaper model to burn through mechanical work.
- The user names an OpenRouter vendor or model (Kimi, GLM, Gemini Flash,
  a `vendor/model-id` slug) without further instruction on how to invoke it.

**Not for:** delegating to Codex (use the Codex plugin routing rule) or to
Gemini CLI / OpenCode directly — this skill is specifically the
Claude-Code-as-harness path.

## Core Pattern

Always launch through `scripts/run.js`. Never invoke `claude` directly
against `openrouter.ai` — see **Why the proxy is mandatory** below.

```bash
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "<model_id>" \
  --effort "<low|medium|high|xhigh|max>" \
  --permission-mode dontAsk \
  --allowedTools "<tool>" "<tool>" ... \
  -p "<the task prompt>"
```

Every argument is forwarded to `claude` untouched, and the child's exit code
is propagated, so this is a drop-in substitute for a `claude` invocation.

The launcher owns the whole redirect: it starts the repair proxy in-process
on a kernel-assigned port, points `ANTHROPIC_BASE_URL` at it, sets
`ANTHROPIC_AUTH_TOKEN` from `$OPENROUTER_API_KEY`, forces `ANTHROPIC_API_KEY`
to empty, and gives the nested process its own `CLAUDE_CONFIG_DIR`
(`~/.claude_openrouter`) so it neither collides with nor inherits the parent
session's `~/.claude`. Do not set those four variables yourself — a
half-configured redirect silently bills the wrong account.

Notes on the fixed parts:

- `--permission-mode dontAsk` plus an explicit `--allowedTools` list is what
  makes this non-interactive. Without both, the nested process either hangs
  waiting for a permission prompt no one can answer, or (with no
  `--permission-mode` at all) silently queues every tool call and exits
  having done nothing.
- `$OPENROUTER_API_KEY` must already be set in the environment — this skill
  does not create or store credentials. If it's unset the launcher exits `78`
  and says so; ask the user where to find the key rather than guessing.
- Node is a hard requirement. If `node` is missing, stop and say so — do not
  fall back to a direct `claude` invocation, which fails silently rather than
  loudly (again, see below).
- Before first use in a fresh environment, verify `claude --help` still
  supports `--permission-mode`, `--allowedTools`, and `-p` as documented here
  — CLI flags drift across Claude Code versions.

### Why the proxy is mandatory

Claude Code returns `"result": ""` — with **exit 0, empty stderr, and tokens
billed** — whenever an assistant response ends on a `thinking` or
`redacted_thinking` block, which OpenRouter emits routinely. The answer is
generated and paid for; it just never reaches you. Nothing in the exit status
or the logs tells you this happened.

`scripts/proxy.js` repairs the stream by moving the trailing text block to the
end of the response so it never terminates on reasoning. The repair is
deliberately narrow — block order is otherwise preserved, because the client
replays that order back upstream on the next turn.

The proxy runs **in-process inside the launcher**, on a kernel-assigned port
(`listen(0)`). That is what makes concurrent sessions safe: the kernel hands
out distinct ports atomically, where "pick a port and check if it's free"
races. It also means the listener dies with the launcher under any signal,
including `SIGKILL` — an orphaned proxy squatting a port cannot happen.

## Step 1 — Tool Permissions (safety gate, always runs)

Default to the most restricted tool set that can do the job. This step is
**not** skippable by a "use your judgment" signal from the user — that signal
only affects Step 2 (model) and Step 3 (effort).

| Tier | Tools | Confirmation |
|---|---|---|
| **Read-only** (default) | `Read`, `Grep`, `Glob`, `Bash(git status)`, `Bash(git diff *)`, `Bash(git log *)`, `Bash(ls *)`, `Bash(find *)` | None — always safe to grant |
| **Local write** | `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash(git add *)`, `Bash(git commit *)` | **Ask the user before granting** |
| **Network / exfiltration risk** | `WebFetch`, `WebSearch`, `Bash(curl *)`, `Bash(git push *)`, `Bash(gh *)`, any MCP tool that calls out | **Ask the user before granting** |

Reasoning: a subagent running on someone else's model, with someone else's
weights and someone else's logging, is the wrong place to hand out write or
network access by default — those tools are also exactly how data leaves the
machine. Read-only access to explore and answer questions needs no
confirmation. The moment the task genuinely requires editing files or
reaching the network, say so explicitly and ask:

> This subagent needs `[tool]` to `[reason]`. That gives it the ability to
> [write local files / make outbound network calls]. Proceed?

Grant only the tools the specific task needs — not the whole tier. A task
that edits one file doesn't need `Bash(git commit *)`; a task that reads a
URL doesn't need `WebSearch` too.

## Step 2 — Model Selection

`references/model-routing.md` is the source of truth for pricing, context
window, effort-param support, and per-bucket defaults — that verification
work is already done there, once, when the table was written. Don't
guess at the right model, look the answer up.

Selection procedure:

1. Classify the task: mechanical/triage, standard implementation, or
   architecture/judgment-heavy (same three buckets used elsewhere in this
   repo for subagent model right-sizing).
2. Look up that bucket's row in `references/model-routing.md`'s "Selection
   by task bucket" table and use its **Default pick** column — unless the
   user said "cheap"/"cost-sensitive" (use **Step down**) or "best"/"most
   capable" regardless of cost (use **Step up**).
3. If the user named a specific `vendor/model-id`, check it against
   `references/model-routing.md` **and** the supplemental registry at
   `~/.config/agents-config/openrouter-model-registry.json` (if that file
   exists). If it's recorded in either, use that data. If it's in neither,
   run the **Unknown Model Workflow** below before proceeding.
4. State the model and the one-sentence reason (task bucket + price)
   **and ask for confirmation** — unless the user invoked this skill with an
   explicit "use your judgment" / "don't ask me" signal, in which case state
   the choice and proceed without waiting.

### Unknown Model Workflow

Triggered when a user-named `vendor/model-id` isn't in
`references/model-routing.md` or the supplemental registry:

1. Tell the user plainly: this skill has no pricing/context/effort data on
   that model.
2. Ask them to choose: **(a)** proceed with it as specified, accepting that
   cost and capability are unverified, or **(b)** have you research it now
   (its OpenRouter model page: pricing, context window, whether it honors
   `reasoning.effort`).
3. If they pick research, gather it, then present what you found (and from where) back to
   the user for confirmation before using it — don't silently trust a single
   scraped page for something that affects both cost and tool-grant risk.
   Ask the user for any metadata you weren't able to find (e.g., if the model page doesn't say whether it honors `reasoning.effort`, ask the user to confirm that).
4. Once confirmed, ask whether to persist it for future invocations. If
   yes, create `~/.config/agents-config/` if absent and write/update an
   entry in `openrouter-model-registry.json`, a JSON object keyed by model
   ID:

   ```json
   {
     "vendor/model-id": {
       "input_per_m": 0.00,
       "output_per_m": 0.00,
       "context": "...",
       "effort_param": "confirmed | not confirmed | unknown",
       "best_for": "...",
       "added": "YYYY-MM-DD",
       "source": "user-reported | researched: <url>"
     }
   }
   ```

This registry lives outside the repo, under `~/.config/agents-config/`, not
under `references/` — it's runtime state this skill accumulates across
invocations, not versioned skill content. Step 3 (effort) also consults it.

## Step 3 — Effort / Reasoning Level

The `claude` CLI takes a native `--effort <level>` flag (`low`, `medium`,
`high`, `xhigh`, `max` — confirmed via `claude --help`; always pass one, it
is not optional the way it might look in the examples elsewhere in this
skill). If the user specified a level, use it as given. Otherwise pick from
this rubric (same low/medium/high/xhigh shape used for subagent dispatch
generally):

| Task shape | Effort |
|---|---|
| Extraction, formatting, mechanical grep-and-summarize | `low` |
| Standard implementation, bug fix, code review | `medium` |
| Architecture, cross-subsystem design, adversarial verification, final synthesis | `high` or `xhigh` (`max` only if the user asks for it explicitly — it's the most expensive tier) |

Whether `--effort` actually changes the *target* OpenRouter model's behavior
depends on that model honoring OpenRouter's normalized `reasoning.effort`
parameter — not every vendor does. For a model in `references/model-routing.md`
or the supplemental registry, that's already recorded in its "effort param?"
/ `effort_param` field — trust the recorded value, don't re-verify it at
dispatch time. For a model that reached you via the Unknown Model Workflow
without that field confirmed, pass `--effort` anyway (it's free) but don't
assume it's doing anything — model *choice* (Step 2) is your reliable
capability lever until the field gets confirmed and persisted.

## Quick Reference

```bash
# Read-only research subagent on a cheap model, no confirmation needed (read-only tier)
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "google/gemini-3.1-flash-lite" \
  --effort low \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" \
  -p "Summarize the error-handling pattern used across src/api/*.py"

# Implementation subagent on a mid-tier coding model — Edit/Write requires
# user confirmation first (see Step 1)
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "moonshotai/kimi-k2.7-code" \
  --effort medium \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" "Edit" "Write" \
  -p "Implement retry-with-backoff for the HTTP client in src/client.py, per the existing logging conventions in the file"
```

## Common Mistakes

- **Invoking `claude` directly against `openrouter.ai`.** The single worst
  mistake available here: it returns an empty `result` with exit 0 and no
  stderr whenever the response ends on a thinking block, and bills you for the
  answer you didn't get. Always go through `scripts/run.js`.
- **Setting `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY`
  / `CLAUDE_CONFIG_DIR` by hand.** The launcher owns all four. Overriding one
  either bypasses the proxy or points the run at the wrong account.
- **Omitting `--effort`.** It's a real, confirmed CLI flag (`claude --help`)
  — leaving it unset means the harness picks its own default rather than the
  level the task actually calls for. Always set it explicitly, per Step 3.
- **Omitting `--permission-mode dontAsk`.** The nested process has no
  terminal to prompt — it hangs (with `--allowedTools` alone) or exits 0
  having done nothing (with neither flag set).
- **Granting write or network tools by default "to be safe" / "in case it's
  needed."** Backwards — the safe default is read-only; write/network is the
  thing that needs an explicit ask, every time, regardless of task framing.
- **Picking a model from memory instead of checking `references/model-routing.md`
  and the supplemental registry.** Prices and which models exist on
  OpenRouter change; guessing here either overpays or routes a task to a
  model that's been deprecated.
- **Re-deriving a "cheapest model" pick instead of reading the Selection by
  task bucket table.** The trade-off is already encoded there; recomputing
  it ad hoc is how the cheap/best bias drifts from what the table says.
- **Treating an unlisted model as safe to assume things about.** No entry in
  either the table or the registry means no verified pricing, context, or
  effort support — run the Unknown Model Workflow instead of guessing.
- **Wrapping the launcher in a shell to "fix" quoting.** `run.js` spawns
  `claude` without a shell, so aliases and shell functions cannot shadow the
  real binary and arguments need no extra escaping. Adding a shell layer only
  reintroduces both problems.
