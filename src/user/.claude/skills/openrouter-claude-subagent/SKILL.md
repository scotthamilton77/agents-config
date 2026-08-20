---
name: openrouter-claude-subagent
description: Use when launching a run on an OpenRouter-hosted model, or when working out which one fits a task and what it costs. Apply when the user names OpenRouter or a model it hosts (Kimi, GLM, Gemini, GPT mini tiers), when another skill sends a dispatch here, or when a model's price, context window, or effort support needs looking up rather than recalling. Not for deciding whether to leave Claude in the first place, not for Codex or Gemini CLI, and not for the Claude models and large GPT tiers this transport refuses. When instructing-subagents' brief mandates a written report file, extend this skill's read-only default with a Write grant scoped to that one path.
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
vendor model id and a request that names no model at all. Two families are refused outright, pin or no pin:
Claude models, which belong in the harness you are already running, and the
large GPT tiers (`gpt-5.5*`, `gpt-5.6*`, `-mini` variants excepted), which have
their own transport. Naming one exits `78` before anything starts, and there is
no rerouting around it — if that transport is down, the task waits.

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

## Step 2 — Model selection

`references/model-routing.md` is the source of truth for pricing, context
window, effort support, and per-bucket defaults. Look the answer up. Picking
from memory routes work to a model that may be repriced or retired, and
re-deriving a "cheapest" pick by hand is how the bias drifts from what the
bucket table already encodes.

1. Classify the task: mechanical/triage, standard implementation, or
   architecture/judgment-heavy.
2. Take that bucket's **Default pick** — unless the user said "cheap" (use
   **Step down**) or "best"/"most capable" (use **Step up**).
3. If the user named a specific `vendor/model-id`, check it against the
   routing table **and** the supplemental registry at
   `~/.config/agents-config/openrouter-model-registry.json`. Listed in
   neither means its price, context, and effort support are all unverified —
   run the Unknown Model Workflow in `references/model-routing.md` rather
   than assuming.
4. State the model and a one-sentence reason (task bucket + price), and ask
   for confirmation — unless the user waived confirmation, in which case
   state the choice and proceed.

## Step 3 — Effort level

| Task shape | Effort |
|---|---|
| Extraction, formatting, mechanical grep-and-summarize | `low` |
| Standard implementation, bug fix, code review | `medium` |
| Architecture, cross-subsystem design, adversarial verification, final synthesis | `high` or `xhigh` |

Use the user's level if they named one. `max` only on an explicit request —
it is the most expensive tier.

Not every model accepts every level. `references/model-routing.md` lists the
levels each one takes — pick from that list, since two of the listed models
accept no level at all, one of those cannot be capped even in principle, and
others are missing the middle of the range. Trust the recorded value rather
than re-verifying at dispatch.

## Example

```bash
# Read-only research on a cheap model — read-only tier, no confirmation needed
node "${CLAUDE_SKILL_DIR}/scripts/run.js" \
  --model "google/gemini-3.5-flash-lite" \
  --effort low \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" \
  -p "Summarize the error-handling pattern used across src/api/*.py"
```

Do not wrap the launcher in a shell to fix quoting. `run.js` spawns `claude`
without one, so aliases cannot shadow the real binary and arguments need no
extra escaping; a shell layer reintroduces both problems.
