# OpenRouter Model Routing Table

Prices are $/M tokens on OpenRouter, captured 2026-07-18. **Verify current
pricing at `openrouter.ai/<model-id>` before routing anything cost-sensitive**
— OpenRouter repricing and model churn happen without notice, and this table
will drift.

| Model ID (`--model` value) | Input $/M | Output $/M | Context | Effort param? | Best for |
|---|---|---|---|---|---|
| `google/gemini-3.1-flash-lite` | $0.25 | $1.50 | 1M | confirmed | Cheapest tier — high-volume triage, extraction, formatting |
| `z-ai/glm-5.2` | $0.30 | $0.94 | 1.05M / 131K out | confirmed (reasoning model) | Very cheap long-horizon agentic coding |
| `moonshotai/kimi-k2.6` | $0.66 | $3.41 | 262k | confirmed | Cheapest Kimi tier, general/mechanical |
| `moonshotai/kimi-k2.7-code` | $0.72 | $3.50 | 262k | confirmed | Code-tuned mid-tier, strong cost/perf for implementation |
| `google/gemini-3.5-flash` | $1.50 | $9.00 | 1M | confirmed | Near-Pro coding/reasoning at flash latency |
| `openai/gpt-5.6-luna` | $1.00 | $6.00 | 1.05M | confirmed | Cheap high-volume classification / lightweight agentic |
| `openai/gpt-5.6-terra` | $2.50 | $15.00 | 1.05M | confirmed | Balanced everyday coding/agentic — standard implementation |
| `moonshotai/kimi-k3` | $3.00 | $15.00 | 1.05M | confirmed (via `reasoning`) | Frontier-tier agentic coding, large repos |
| `anthropic/claude-opus-4.8` | $5.00 | $25.00 | 1M | confirmed (native thinking) | Frontier architecture/judgment |
| `openai/gpt-5.6-sol` | $5.00 | $30.00 | 1.05M | confirmed | Flagship complex reasoning/coding, cross-subsystem work |

## Selection by task bucket

| Bucket | Default pick | Step down (user said "cheap") | Step up (user said "best"/"most capable") |
|---|---|---|---|
| Mechanical / triage | `google/gemini-3.1-flash-lite` | — (already cheapest) | `moonshotai/kimi-k2.6` |
| Standard implementation | `moonshotai/kimi-k2.7-code` | `google/gemini-3.1-flash-lite` or `z-ai/glm-5.2` | `openai/gpt-5.6-terra` or `moonshotai/kimi-k3` |
| Architecture / judgment-heavy | `moonshotai/kimi-k3` | `openai/gpt-5.6-terra` | `openai/gpt-5.6-sol` or `anthropic/claude-opus-4.8` |

`z-ai/glm-5.2` is a good universal fallback when the task is agentic
(multi-step, tool-using) but still cost-sensitive — cheaper than the Kimi
code tier at a similar context window, with confirmed reasoning support.

## Anthropic-compatibility mechanics

`https://openrouter.ai/api` exposes an Anthropic Messages API–compatible
endpoint (OpenRouter's "Anthropic Skin"), which is what lets
`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` route a stock Claude Code
process through it with no local proxy. Model IDs are OpenRouter's normal
`vendor/model-slug` form — no extra prefixing needed beyond what's in this
table. OpenRouter also normalizes a `reasoning.effort` parameter
(`none`/`minimal`/`low`/`medium`/`high`/`xhigh`, internally mapped to a
token-budget ratio of `max_tokens`) across providers that support it, but not
every provider honors it — some silently drop reasoning tokens.

Sources checked 2026-07-18: OpenRouter's Claude Code integration cookbook,
each model's own OpenRouter page, and the OpenRouter reasoning-tokens guide.

## Supplemental registry

This table is the versioned, source-controlled baseline. A model a user
names that isn't listed here may still be recorded in
`~/.config/agents-config/openrouter-model-registry.json` — a runtime
registry SKILL.md's Unknown Model Workflow reads and writes. Check both
before concluding a model is unverified; see SKILL.md for the registry's
schema and update procedure.
