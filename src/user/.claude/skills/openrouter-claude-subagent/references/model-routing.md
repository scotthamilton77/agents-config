# OpenRouter Model Routing Table

Captured **2026-08-20** from `https://openrouter.ai/api/v1/models`, OpenRouter's
public catalog endpoint. That endpoint is authoritative for price, context
length, max output, and which reasoning-effort levels a model accepts, and it
is machine-readable — refresh this table from it rather than reading ten model
pages by hand. Re-verify there before routing anything cost-sensitive:
OpenRouter reprices and retires models without notice, and this table is a
snapshot that starts decaying immediately.

This launcher also denies two model families outright, independent of price:
Claude models, and non-`-mini` `gpt-5.5`/`gpt-5.6` tiers (`scripts/proxy.js`'s
`DENIED_MODEL_PREFIXES` — see `references/proxy-contract.md`'s Denylist
section). Both run properly through other transports, so the table below
omits them entirely: every row here is a model this launcher can actually
start.

Prices are $/M tokens. Rows are sorted by input price.

| Model ID (`--model` value) | Input $/M | Output $/M | Context | Effort levels accepted | Best for |
|---|---|---|---|---|---|
| `google/gemini-3.5-flash-lite` | $0.30 | $2.50 | 1M / 64K out | `minimal` `low` `medium` `high` | Cheapest input of any row — high-volume triage, extraction, formatting |
| `google/gemini-3.7-flash` | $0.375 | $1.875 | 1M / 64K out | `low` `medium` `high` — no `minimal` | Cheapest output of any row, and it still caps its reasoning; fast agentic coding |
| `moonshotai/kimi-k2.7-code` | $0.71 | $3.50 | 262K | **none** — reasoning always on, **cannot be capped** | Code-tuned mid-tier, strong cost/perf for implementation |
| `moonshotai/kimi-k2.6` | $0.95 | $4.00 | 262K | **none** — reasoning on/off only | General/mechanical Kimi tier; the one Kimi whose thinking can be switched off |
| `z-ai/glm-5.3` | $1.40 | $4.40 | 1M / 131K out | `low` `high` `max` — no `medium`, no `xhigh` | Long-horizon agentic coding and judgment work at 1M context |
| `moonshotai/kimi-k3` | $3.00 | $15.00 | 1M | `low` `high` `max` — no `medium`, no `xhigh` | Frontier-tier agentic coding, large repos |

## Reading the effort column

The column lists the discrete levels each model accepts on OpenRouter's
normalized `reasoning.effort` parameter. Two consequences worth internalizing
before dispatch:

- **Not every level exists on every model.** `glm-5.3` and `kimi-k3` both run
  `low`/`high`/`max` with no `medium` and no `xhigh` — a task that wants "high
  or xhigh" gets `high` or `max`, nothing between. Both Kimi mid-tier models
  accept no level at all.
- **One of those cannot be capped at all.** `kimi-k2.7-code` reasons
  mandatorily and takes no effort level, so its thinking can only be endured,
  never bounded. Give an uncappable model a long whole-artifact task behind a
  streaming idle deadline — a full-document review, a large-diff pass — and
  the stream can end inside a thinking block having delivered no message at
  all. That is a property of the model class rather than of one row, so it
  recurs as the table turns over: route long single-pass work to a model whose
  effort you can set, and re-check this column before trusting a model that
  reads as `none`. `kimi-k2.6` reads as `none` too but differs where it
  matters — its reasoning is optional, so it can be switched off outright.
- **The mapping from the CLI to that parameter is unverified.** The Claude
  Code CLI's `--effort` flag travels through OpenRouter's Anthropic-compatible
  skin, which speaks the Messages API's thinking budget rather than
  `reasoning.effort` directly. What this table records is what the *model*
  accepts, not proof that a given `--effort` value arrives as that level. Where
  the effort lever matters to an outcome, treat model choice as the reliable
  control and the effort level as a hint.

## Selection by task bucket

| Bucket | Default pick | Step down (user said "cheap") | Step up (user said "best"/"most capable") |
|---|---|---|---|
| Mechanical / triage | `google/gemini-3.5-flash-lite` | — cheapest input is already here; take `google/gemini-3.7-flash` instead when the output dominates | `moonshotai/kimi-k2.6` |
| Standard implementation | `moonshotai/kimi-k2.7-code` | `google/gemini-3.5-flash-lite` | `moonshotai/kimi-k3` |
| Architecture / judgment-heavy | `z-ai/glm-5.3` | `google/gemini-3.7-flash` | `moonshotai/kimi-k3` |

## Anthropic-compatibility mechanics

`https://openrouter.ai/api` exposes an Anthropic Messages API–compatible
endpoint (OpenRouter's "Anthropic Skin"), which is what lets
`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` route a stock Claude Code process
through it. Compatibility is not complete: responses that end on a reasoning
block break the client, which is why this skill routes through the local repair
proxy rather than pointing at OpenRouter directly (see `proxy-contract.md`).
Model IDs are OpenRouter's normal `vendor/model-slug` form — no extra prefixing
beyond what is in this table.

## Supplemental registry

This table is the versioned, source-controlled baseline. A model a user names
that isn't listed here may still be recorded in
`~/.config/agents-config/openrouter-model-registry.json` — a runtime registry
the workflow below reads and writes. Check both before concluding a model is
unverified.

The registry lives outside the repo because it is runtime state this skill
accumulates across invocations, not versioned skill content. It is a JSON
object keyed by model ID:

```json
{
  "vendor/model-id": {
    "input_per_m": 0.00,
    "output_per_m": 0.00,
    "context": "...",
    "supported_efforts": ["low", "high"],
    "best_for": "...",
    "added": "YYYY-MM-DD",
    "source": "user-reported | catalog | researched: <url>"
  }
}
```

An entry written before 2026-07-25 may carry `effort_param` instead, whose
`confirmed` value means only that the model reasons — not which levels it
takes. Treat that as levels-unknown and re-read it from the catalog when it
matters.

## Unknown Model Workflow

Triggered when a user-named `vendor/model-id` appears in neither the table
above nor the supplemental registry.

1. Tell the user plainly: this skill has no pricing, context, or effort data
   on that model.
2. Ask them to choose — **(a)** proceed with it as specified, accepting that
   cost and capability are unverified, or **(b)** look it up now in the catalog
   endpoint, which carries `pricing`, `context_length`, `top_provider`, and
   `reasoning.supported_efforts` for every listed model.
3. Present what you found *and from where* for confirmation before using it.
   If the model is absent from the catalog entirely, say so — that means
   OpenRouter does not serve it, and no amount of further searching will
   change the dispatch outcome.
4. Once confirmed, ask whether to persist it for future invocations. If yes,
   create `~/.config/agents-config/` if absent and write or update the entry
   using the schema above.
