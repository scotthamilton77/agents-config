---
name: openrouter-claude-subagent
description: Use when launching a run on an OpenRouter-hosted model, or when working out which one fits a task and what it costs. Apply when the user names OpenRouter or a model it hosts (Kimi, GLM, Gemini, GPT mini tiers), when another skill sends a dispatch here, or when a model's price, context window, or effort support needs looking up rather than recalling. Not for deciding whether to leave Claude in the first place, not for Codex, and not for the Claude models this launcher refuses. A GPT or Gemini model runs here only on the user's explicit instruction; their own launchers are the Codex and agy skills. When instructing-subagents' brief mandates a written report file, extend this skill's read-only default with a Write grant scoped to that one path.
admission:
  provides: A nested Claude Code harness whose model traffic is repointed at a non-Anthropic model, plus the stream repair that makes the reply actually arrive — so a task runs on another vendor's weights while keeping this harness's tool loop, permission system, and file editing.
  cost: A local proxy process for the life of each nested run, and an OpenRouter API key the user must supply and pay against. Node must be installed, and the model routing table needs a refresh whenever OpenRouter reprices or retires a model.
  remove_when: The review tooling can address models from more than one vendor natively, so a caller can name a non-Anthropic model without a nested harness and a repair proxy in between.
---

# OpenRouter Claude Subagent

Runs Claude Code itself as the harness with its model traffic repointed at
OpenRouter: a second `claude` process, in its own config directory, backed by
whatever OpenRouter-hosted model fits the task. Same tool loop, same file
editing, same permission system — different weights.

Three decisions, in this order: **which tools** the subagent may use, **which
model**, **what effort level**. The first is a safety gate you always make.
The other two can be handed to the calling agent's discretion.

## Launch

```bash
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "<model_id>" \
  --effort "<low|medium|high|xhigh|max>" \
  --permission-mode dontAsk \
  --allowedTools "<tool>" "<tool>" ... \
  -p "<the task prompt>"
```

Never invoke `claude` directly against `openrouter.ai`. It returns an empty
result with exit 0, no stderr, and the tokens billed — you pay for an answer
that never arrives. `run.js` is the only supported entry point: it starts the
repair proxy, owns every variable that decides where the traffic goes,
forwards the rest of argv untouched, and propagates the child's exit code.

The launcher refuses to start without all four flags above, and exits `78`
when `$OPENROUTER_API_KEY` is unset — this skill neither creates nor stores
credentials, so ask the user where to find the key rather than guessing. Node
is a hard requirement; if it is missing, stop and say so rather than falling
back to a direct invocation.

**The run is pinned to `--model`.** The subagent may delegate further, and
every run it starts answers on that same model — the aliases are redirected, so
a dispatch that names `sonnet`, or an agent type whose own model is one of those
aliases, still lands there. Anything outside that vocabulary is refused with an
error explaining the alternative, including an agent type pinned to a specific
vendor model id and a request that names no model at all. Claude models are
refused outright, pin or no pin: they belong in the harness you are already
running. The launcher also refuses the GPT-5.5, GPT-5.6 and GPT-6 tiers, the
`-mini` variants of 5.5 and 5.6 excepted. A GPT or Gemini model runs on this
launcher only when the user has explicitly instructed it for the run at hand;
each has its own subscription launcher, and a spent quota or a dead launcher
there is a reason to ask the user, never to reroute on your own.

`references/proxy-contract.md` covers what the proxy repairs, why the tool
grant is limited to what you pass, and what to re-verify when the Claude Code
CLI changes.

## Step 1 — Tool permissions (safety gate, always runs)

Grant the most restricted set that can do the job — the specific tools, not
the whole tier. A task that edits one file does not need `Bash(git commit *)`.
A "use your judgment" signal from the user applies to Steps 2 and 3 only; it
never waives this step.

| Tier | Tools | Confirmation |
|---|---|---|
| **Read-only** (default) | `Read`, `Grep`, `Glob`, `Bash(git status)`, `Bash(git diff *)`, `Bash(git log *)`, `Bash(ls *)`, `Bash(find *)` | None — always safe to grant |
| **Local write** | `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash(git add *)`, `Bash(git commit *)` | **Ask the user before granting** |
| **Network / exfiltration risk** | `WebFetch`, `WebSearch`, `Bash(curl *)`, `Bash(git push *)`, `Bash(gh *)`, any MCP tool that calls out | **Ask the user before granting** |

A subagent running on another vendor's model, weights, and logging is the
wrong place to hand out write or network access by default — those tools are
also exactly how data leaves the machine. Granting them "to be safe" or "in
case it's needed" is backwards. When the task genuinely requires one, say so
and ask:

> This subagent needs `[tool]` to `[reason]`. That gives it the ability to
> [write local files / make outbound network calls]. Proceed?

A mandated report file is granted as `Edit(<path>)`. `Edit` rules cover every
file-editing tool; a `Write(<path>)` grant is not matched, so the reviewer
cannot write its report and the verdict survives only in the run log's tail.

## Step 2 — Model selection

The `choosing-a-delegate` skill's model routing table is the one source for
the model each provider offers at each tier, and for every model's price,
context window and accepted effort levels; its `openrouter` rows are the
models this launcher runs. Look the answer up there. Picking from memory
routes work to a model that may be repriced or retired, and re-deriving a
"cheapest" pick by hand is how the bias drifts from what the table encodes.

1. Classify the task by the table's tiers.
2. Take that tier's `openrouter` model, unless the user said "cheap" (one
   tier down) or "best"/"most capable" (one tier up).
3. A Gemini or GPT model is never your pick on this launcher. It runs here
   only when the user explicitly instructed it for this run, and the Gemini
   row exists for that case.
4. A user-named `vendor/model-id` absent from the table is unverified: look it
   up in the catalog endpoint the table names, say what you found and where,
   and ask before using it.
5. State the model and a one-sentence reason (task profile + price), and ask
   for confirmation — unless the user waived confirmation, in which case
   state the choice and proceed.

Pass the bare model id. A context-window suffix such as `[1m]` is refused by
the run's own model pin (`403 … decision=deny-pin`); `CLAUDE_CODE_MAX_CONTEXT_TOKENS`
is the lever when the clamp matters.

## Step 3 — Effort level

| Task shape | Effort |
|---|---|
| Extraction, formatting, mechanical grep-and-summarize | `low` |
| Standard implementation, bug fix, code review | `medium` |
| Architecture, cross-subsystem design, adversarial verification, final synthesis | `high` or `xhigh` |

Use the user's level if they named one. `max` only on an explicit request —
it is the most expensive tier.

Not every model accepts every level, and the routing table's accepted-efforts
column bounds the choice: pick from the row's list. Where the row does not
list the level this grid names, pass the next listed level up, so `medium` on
a row listing `low` `high` `max` becomes `high`. The flag reaches OpenRouter
through its Anthropic-compatible endpoint as a thinking budget, so a level a
row does not list still bounds the model's thinking; treat the model as the
reliable control and the level as a hint.

Two constraints on this launcher's rows hold today and override the grid:

- A whole-artifact single-pass read on `moonshotai/kimi-k3` runs at `low`,
  never `high` or `max`, and is granted no tools when the prompt carries the
  text. At the higher levels its thinking outlasts the stream and the run ends
  inside a thinking block with no report. Delta reads run `high`.
- `z-ai/glm-5.3` returns thinking-only turns on a whole-document single pass
  until the request times out, so it takes delta and walk work, never a
  whole-artifact read.

The launcher pins no sampling parameter, and neither should a prompt or a
wrapper: the Kimi rows refuse a temperature, and Google says to leave Gemini's
at its default.

## Example

```bash
# Read-only research on a cheap model — read-only tier, no confirmation needed
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "z-ai/glm-5.3-flash" \
  --effort low \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" \
  -p "Summarize the error-handling pattern used across src/api/*.py"
```

Do not wrap the launcher in a shell to fix quoting. `run.js` spawns `claude`
without one, so aliases cannot shadow the real binary and arguments need no
extra escaping; a shell layer reintroduces both problems.
