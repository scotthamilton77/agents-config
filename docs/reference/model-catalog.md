# Model Catalog

**Last updated: 2026-08-09**

Human-readable catalog of the AI model IDs this project routes to, their list
prices, and the use-case tier each one serves. A decision aid for choosing
routing tiers — **not** a runtime source of truth.

> **Prices rot.** List prices here are point-in-time and versioned with the code
> deliberately (they age alongside the routing decisions that cite them). For
> OpenRouter-routed models specifically, a live user-maintained rate override
> exists — `~/.config/agents-config/openrouter-model-registry.json`
> (`input_per_m`/`output_per_m` keys; see the `openrouter-claude-subagent`
> skill) — and takes precedence over this doc for those models. No equivalent
> override exists for the other providers below; when a price here goes stale,
> re-verify against the vendor and update this doc's date.

Prices are USD per million tokens (input / output).

---

## Routing tier map

How task classes map to model tiers. The canonical routing rules live in the
`delegating-to-codex` and `openrouter-claude-subagent` skills and in the prgroom
dispatcher (`packages/prgroom/src/prgroom/agent/dispatcher.py`).

| Use case | OpenAI (Codex) | Anthropic (Claude) | Local / cheap |
|---|---|---|---|
| Mechanical / triage / classify / cluster / finder | `gpt-5.6-luna` | `haiku` (low–high) | `ollama gemma4` |
| Standard review / implement / fix-chain / merge-judge default | `gpt-5.6-terra` | `sonnet` / `opus` | — |
| Architecture / security / cross-subsystem / final pre-merge / deep adversarial review / spec-writer | `gpt-5.6-sol` | `opus` (high/xhigh) | — |
| Deeply code-centric agentic (`--write`) | `gpt-5.3-codex` | — | — |

---

## OpenAI — Codex CLI

Invoked by dispatching the `codex-rescue` agent (see the `delegating-to-codex`
skill for the dispatch route and model choice). The `gpt-5.6-*` variants are
the current review/impl tier; older `5.x` models remain available.

| Model ID | In $/M | Out $/M | Tier / use |
|---|---|---|---|
| `gpt-5.6-luna` | 1.00 | 6.00 | Cheapest. Triage, cluster, classify, finder, diff-summary. |
| `gpt-5.6-terra` | 2.50 | 15.00 | **Default review tier.** Standard review, implement, fix-chain, merge-judge default. |
| `gpt-5.6-sol` | 5.00 | 30.00 | Complex only. Architecture, security, deep adversarial review, spec-writer. |
| `gpt-5.3-codex` | 1.75 | 14.00 | Codex-tuned agentic `--write` coding. Retained. |
| `gpt-5.5` | — | — | Legacy. Superseded by `terra`/`sol`; still available. |
| `gpt-5.4-mini` | — | — | Legacy. Superseded by `luna`; still available. |

Family derivation: the `merge-guard` skill and its `model_family.py` script were
retired and nothing replaced them, so no code in this repository derives a model
family today. The script classified any `gpt-`/`o1`/`o3`/`o4`/`chatgpt` prefix as
`openai`, version-generically; a new `gpt-5.6-*` variant is now classified by
whatever reads this table rather than automatically.

---

## Anthropic — Claude Code CLI

The subscription backbone (billed as subscription until exhausted, then metered
overage via the API sibling).

> **Roster captured 2026-08-09** from the active session's own model
> enumeration (the Claude Code harness's model list). Anthropic renames and
> retires tiers without much notice — re-verify against the harness's current
> model list or console.anthropic.com before routing anything cost-sensitive.

| Name | Model ID | In $/M | Out $/M | Tier / use |
|---|---|---|---|---|
| Opus 5 | `claude-opus-5` | TBD | TBD | Top judgment tier: architecture, impl, final synthesis. |
| Sonnet 5 | `claude-sonnet-5` | TBD | TBD | Standard impl + review. |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | TBD | TBD | Mechanical / cheap fan-out. |
| Fable 5 | `claude-fable-5` | TBD | TBD | Frontier-tier spec closure. |

> **TBD prices unverified.** Current Claude 5-era Anthropic list prices stand
> unverified against the vendor page. Re-verify using the route the roster
> callout above names (console.anthropic.com) and re-date this doc. Do not
> guess.

---

## Gemini / local / OpenRouter (agents-config routing)

| Provider | Model ID | In $/M | Out $/M | Use |
|---|---|---|---|---|
| Gemini CLI | `gemini-3-flash-preview` | 0.50 | — | Foreign-eyes review. |
| Local | `ollama gemma4` | free | free | Cluster/classify baseline (never counts against budget ceiling). |
| OpenRouter | `z-ai/glm-5.2` | 0.76 | 2.39 | Metered peer rung. |

---

## Sidekick persona / creative model pool

Separate domain: the `claude-code-sidekick` project's persona/creative model
roster, sourced from its `llm.defaults.yaml`. OpenRouter-centric cheap models for
persona voice + creative generation, **not** the review/impl routing above.

> **Source-dated 2025-11-09** (upstream `llm.defaults.yaml`). Stale relative to
> this repo — e.g. it lists Opus/Sonnet 4.5, predating Claude 5. Merged
> here verbatim for reference; reconcile on next sidekick sync.

| Provider | Model | In $/M | Out $/M | Context | Notes |
|---|---|---|---|---|---|
| Claude CLI | haiku (4.5) | 1.00 | 5.00 | — | |
| Claude CLI | sonnet (4.5) | 3.00 | 15.00 | — | <200k tokens |
| Claude CLI | opus (4.5) | 5.00 | 25.00 | — | |
| OpenAI API | gpt-4o-mini | 0.15 | 0.60 | — | |
| OpenAI API | gpt-5-mini | 0.25 | 2.00 | — | |
| OpenAI API | gpt-5-nano | 0.05 | 0.40 | — | |
| OpenRouter | deepseek/deepseek-v3.2 | 0.25 | 0.38 | 164k | |
| OpenRouter | google/gemma-3-4b-it | 0.02 | 0.07 | 32k | |
| OpenRouter | google/gemma-3-27b-it | 0.09 | 0.16 | 128k | |
| OpenRouter | google/gemini-2.5-flash-lite | 0.10 | 0.40 | 1000k | |
| OpenRouter | google/gemini-3-flash-preview | 0.50 | 0.00 | 1000k | |
| OpenRouter | mistralai/mistral-small-creative | 0.10 | 0.30 | 131k | |
| OpenRouter | gryphe/mythomax-l2-13b | 0.06 | 0.06 | 4096 | small ctx! |
| OpenRouter | openai/gpt-oss-20b | 0.03 | 0.14 | 128k | |
| OpenRouter | openai/gpt-5-nano | 0.05 | 0.40 | 400k | |
| OpenRouter | openai/gpt-5-chat | 1.25 | 10.00 | 128k | |
| OpenRouter | qwen/qwen3-235b-a22b-2507 | 0.08 | 0.55 | 250k | |
| OpenRouter | x-ai/grok-4 | 3.00 | 15.00 | 256k | |
| OpenRouter | x-ai/grok-4.1-fast | 0.20 | 0.50 | 2M | reasoning switch api |

Active sidekick profiles (from `llm.defaults.yaml`):
- `fast-lite`: `google/gemini-2.5-flash-lite`
- `creative`: `google/gemini-2.5-flash-lite` (temp 1.2)
- `creative-long`: `qwen/qwen3-235b-a22b-2507` (temp 1.2)
- `cheap-fallback`: `x-ai/grok-4.1-fast` (reasoning off; Grok vendor for provider diversity vs. Gemini primary)

---

## Related

- The `delegating-to-codex` skill — use-case → OpenAI model selection.
- The `openrouter-claude-subagent` skill — OpenRouter-hosted model selection and rates.
- `packages/prgroom/src/prgroom/agent/dispatcher.py` — `_DEFAULT_CHAINS`.
- `agents-config-uy5wx` — archive-era, resolvable in the private archive
  repository and not through `work`: proposed consolidating these duplicated
  model IDs into a single source of truth; this catalog is the human-readable
  half of that effort.
