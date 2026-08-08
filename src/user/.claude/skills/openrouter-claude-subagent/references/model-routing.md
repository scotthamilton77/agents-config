# OpenRouter Model Routing Table

Captured **2026-07-25** from `https://openrouter.ai/api/v1/models`, OpenRouter's
public catalog endpoint. That endpoint is authoritative for price, context
length, max output, and which reasoning-effort levels a model accepts, and it
is machine-readable — refresh this table from it rather than reading ten model
pages by hand. Re-verify there before routing anything cost-sensitive:
OpenRouter reprices and retires models without notice, and this table is a
snapshot that starts decaying immediately.

Prices are $/M tokens. Rows are sorted by input price.

| Model ID (`--model` value) | Input $/M | Output $/M | Context | Effort levels accepted | Best for |
|---|---|---|---|---|---|
| `google/gemini-3.1-flash-lite` | $0.25 | $1.50 | 1M / 64K out | `minimal` `low` `medium` `high` | Cheapest tier — high-volume triage, extraction, formatting |
| `moonshotai/kimi-k2.6` | $0.65 | $2.72 | 262K | **none** — reasoning on/off only | Cheapest Kimi tier, general/mechanical |
| `z-ai/glm-5.2` | $0.76 | $2.39 | 1M / 131K out | `high` `xhigh` **only** | Long-horizon agentic coding; cheapest output in its price band |
| `moonshotai/kimi-k2.7-code` | $0.78 | $3.50 | 262K | **none** — reasoning always on | Code-tuned mid-tier, strong cost/perf for implementation |
| `openai/gpt-5.6-luna` | $1.00 | $6.00 | 1.05M / 128K out | `none` `low` `medium` `high` `xhigh` `max` | Cheap high-volume classification / lightweight agentic |
| `google/gemini-3.5-flash` | $1.50 | $9.00 | 1M / 64K out | `minimal` `low` `medium` `high` | Near-Pro coding/reasoning at flash latency |
| `openai/gpt-5.6-terra` | $2.50 | $15.00 | 1.05M / 128K out | `none` `low` `medium` `high` `xhigh` `max` | Balanced everyday coding/agentic — standard implementation |
| `moonshotai/kimi-k3` | $3.00 | $15.00 | 1M | `low` `high` `max` — no `medium`, no `xhigh` | Frontier-tier agentic coding, large repos |
| `anthropic/claude-opus-4.8` | $5.00 | $25.00 | 1M / 128K out | `low` `medium` `high` `xhigh` `max` | Frontier architecture/judgment |
| `openai/gpt-5.6-sol` | $5.00 | $30.00 | 1.05M / 128K out | `none` `low` `medium` `high` `xhigh` `max` | Flagship complex reasoning/coding, cross-subsystem work |

## Reading the effort column

The column lists the discrete levels each model accepts on OpenRouter's
normalized `reasoning.effort` parameter. Two consequences worth internalizing
before dispatch:

- **Not every level exists on every model.** `glm-5.2` accepts only `high` and
  `xhigh`, so there is no cheap low-effort run on it. `kimi-k3` has no
  `medium` and no `xhigh` — a task that wants "high or xhigh" gets `high` or
  `max`, nothing between. Both Kimi mid-tier models accept no level at all;
  reasoning is simply on.
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
| Mechanical / triage | `google/gemini-3.1-flash-lite` | — (already cheapest) | `moonshotai/kimi-k2.6` |
| Standard implementation | `moonshotai/kimi-k2.7-code` | `google/gemini-3.1-flash-lite` or `z-ai/glm-5.2` | `openai/gpt-5.6-terra` or `moonshotai/kimi-k3` |
| Architecture / judgment-heavy | `moonshotai/kimi-k3` | `openai/gpt-5.6-terra` | `openai/gpt-5.6-sol` or `anthropic/claude-opus-4.8` |

`z-ai/glm-5.2` is the cheapest output in its price band and holds a 1M context,
which keeps it useful for long-horizon agentic work. It is not the all-purpose
cheap fallback it looks like: its input price sits within two cents of the Kimi
code tier, and accepting only `high`/`xhigh` means it cannot be run cheaply on
mechanical work. For that, step down to `google/gemini-3.1-flash-lite`.

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
