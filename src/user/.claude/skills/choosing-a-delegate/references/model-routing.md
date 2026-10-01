# Model routing table

Captured **2026-10-01**. This is the one model table for every route this
harness delegates to. A launcher skill filters it by its own route and carries
no table of its own; the review panel picks a lens model from its tier column.
Each family lists its routes in preference order: the subscription route first,
the metered one as the fallback once the subscription's quota is spent or its
route is down.

Sources, all re-read on the capture date: OpenRouter's catalog endpoint
`https://openrouter.ai/api/v1/models` for every OpenRouter row's price, context
and accepted efforts, which is machine-readable and authoritative; `agy models`
for the agy ids; the Codex CLI's own model list for the Codex ids and their
effort levels; each vendor's published API list price for the native and Codex
rows. Vendors reprice and retire models without notice. Refresh the whole table
from those sources and re-date it; never patch one row from memory. OpenRouter's
listed price for the Kimi and GLM rows is a routed price that moves from day to
day, so those rows are rounded to the cent and are a guide to rank, not a quote:
read the endpoint before any cost-sensitive dispatch.

Prices are USD per million tokens, input / output. The tier column is the
vocabulary the delegation rule and the review panel's staffing use: `top` is
a vendor's strongest and most expensive seat and is spawned only after
consulting the user,
`frontier` is a whole-artifact judgment seat, `mid` is a walk or a delta
re-read, `cheap` is triage and extraction.

## Routes

| Route | Reach it through | Bills |
|---|---|---|
| `native` | The Agent tool, or a Workflow `agent()` call | The Claude subscription |
| `codex` | The Codex delegation skill, present when the Codex plugin is installed | The ChatGPT subscription |
| `agy` | The `delegating-to-agy` skill | The Google AI Pro subscription |
| `openrouter` | The `openrouter-claude-subagent` skill | The OpenRouter key, metered |

The OpenRouter launcher refuses every Claude model and every GPT-5.5, GPT-5.6
and GPT-6 tier outright, the `-mini` variants of 5.5 and 5.6 excepted: those
families have a subscription route above, so one arriving there is a misroute.

## Pick by task profile

| Task profile | Tier | `native` | `codex` | `agy` | `openrouter` |
|---|---|---|---|---|---|
| Architecture, cross-subsystem, security, whole-artifact lens, final pre-merge pass, implementation under a real test gate | `frontier` | `opus` | `gpt-6.1-sol` at `xhigh` | `gemini-3.1-pro-high` | `moonshotai/kimi-k3` |
| Standard review, delta re-review, general default | `mid` | `sonnet` | `gpt-6.1-sol` at `medium` | `gemini-3.8-flash-high`, or `-medium` for a delta re-read | `z-ai/glm-5.3` |
| Triage, extraction, diff summary, cost-sensitive fan-out | `cheap` | `haiku` | `gpt-6-luna` | `gemini-3.8-flash-low` | `z-ai/glm-5.3-flash` |

"Cheap" from the user moves one row down; "best" or "most capable" moves one
row up. Above the `frontier` row sit `fable` and `gpt-6-astra`, and either is
spawned only after consulting the user. A Gemini seat takes the `agy` column; the `openrouter` Gemini row below
exists only as that column's fallback and is never a profile's pick.

## Anthropic, route `native`

| Model (`model` value) | In / Out | Context | Efforts | Tier |
|---|---|---|---|---|
| `fable` (Claude Fable 5.1) | $10.00 / $50.00 | 1M | `low` `medium` `high` `xhigh` `max` | `top` |
| `opus` (Claude Opus 5.5) | $4.00 / $20.00 | 1M | `low` `medium` `high` `xhigh` `max` | `frontier` |
| `sonnet` (Claude Sonnet 5.5) | $2.00 / $10.00 | 1M | `low` `medium` `high` `xhigh` `max` | `mid` |
| `haiku` (Claude Haiku 4.5) | $1.00 / $5.00 | 200K | none | `cheap` |

The Agent tool pins only the model; effort is set on a Workflow `agent()` call
or in an agent definition's front matter.

## OpenAI, route `codex`

| Model (`--model` value) | In / Out | Context | Efforts | Tier |
|---|---|---|---|---|
| `gpt-6-astra` | $10.00 / $50.00 | 272K | `low` `medium` `high` `xhigh` `max` `ultra` | `top` |
| `gpt-6.1-sol` | $2.00 / $10.00 | 272K | `low` `medium` `high` `xhigh` `max` `ultra` | `frontier` at `xhigh`, `mid` at `medium`; Codex's default |
| `gpt-6-luna` | $0.20 / $1.20 | 272K | `low` `medium` `high` `xhigh` `max` | `cheap` |

`ultra` adds automatic task delegation inside Codex and is never the pick for a
review lens, which must read the target itself.

## Google, routes `agy` then `openrouter`

| agy id (`--model` value) | OpenRouter fallback | Tier |
|---|---|---|
| `gemini-3.1-pro-high` | none listed; escalate to another vendor's `frontier` row | `frontier` |
| `gemini-3.8-flash-high` | `google/gemini-3.8-flash` at `--effort high` | `mid` |
| `gemini-3.8-flash-medium` | `google/gemini-3.8-flash` at `--effort medium` | `mid`, delta re-read |
| `gemini-3.8-flash-low` | `google/gemini-3.8-flash` at `--effort low` | `cheap` |

On agy the effort rides in the id's suffix, and agy refuses an `--effort` flag
that conflicts with it, so the launcher defines none: pick the id with the
level you want. Flash carries `-low`, `-medium` and `-high`; Pro carries `-low`
and `-high` only. agy bills the subscription, so its rows carry no price.

## OpenRouter, route `openrouter`

| Model ID (`--model` value) | In / Out | Context | Efforts | Tier |
|---|---|---|---|---|
| `moonshotai/kimi-k3` | $0.70 / $10.00 | 1M | `low` `high` `max` | `frontier` |
| `z-ai/glm-5.3` | $0.22 / $4.40 | 1M | `low` `high` `max` | `mid` |
| `moonshotai/kimi-k2.6` | $0.43 / $1.83 | 262K | none: reasoning on or off, no level | `mid`, when thinking must be off |
| `z-ai/glm-5.3-flash` | $0.15 / $0.50 | 1M | `low` `high` `max` | `cheap` |
| `google/gemini-3.8-flash` | $0.75 / $3.75 | 1M | `low` `medium` `high` | agy fallback only |

Three constraints on these rows hold today and bound the pick:

- A whole-artifact single-pass lens runs `moonshotai/kimi-k3` at `low`, never
  `high` or `max`: at those levels its thinking outlasts the stream and the run
  ends inside a thinking block with no report. Delta reads run `high`.
- `z-ai/glm-5.3` returns thinking-only turns on a whole-document single pass
  until the request times out, so it takes delta and walk work, not a
  whole-artifact read.
- The launcher's `--effort` reaches OpenRouter through its Anthropic-compatible
  endpoint as a thinking budget, so a level a row does not list still bounds
  the model's thinking. Treat the model as the reliable control and the level
  as a hint.

## A model not in this table

It is unverified: its price, context and effort support are unknown here. Look
it up at the source for its route, say what you found and where, and ask
before using it. If it is to be reused, add its row here under the route's
section and re-date the table; nothing else records it.
