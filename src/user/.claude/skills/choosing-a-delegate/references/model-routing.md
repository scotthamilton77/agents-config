# Model routing table

Captured **2026-10-03**. This is the one model table for every provider this
harness delegates to. It answers two questions and no other: which model a
provider offers at each tier, and what each model costs and accepts. The
effort a run uses, the tools it is granted, and whether it reads a whole
artifact or a change are the dispatching skill's decisions, made for its own
task from the accepted efforts listed here.

Sources, all re-read on the capture date: OpenRouter's catalog endpoint
`https://openrouter.ai/api/v1/models` for every OpenRouter row's price, context
and accepted efforts, which is machine-readable and authoritative; `agy models`
for the Google ids; the Codex CLI's own model list for the OpenAI ids and their
effort levels; each vendor's published API list price for the Anthropic and
OpenAI rows. Vendors reprice and retire models without notice. Refresh the
whole table from those sources and re-date it; never patch one row from memory.
OpenRouter's listed price for the Kimi and GLM rows is a routed price that
moves from day to day, so those rows are rounded to the cent and are a guide to
rank, not a quote: read the endpoint before any cost-sensitive dispatch.

## Providers

| Provider | Reach it through | Bills |
|---|---|---|
| `anthropic` | The Agent tool, or a Workflow `agent()` call | The Claude subscription |
| `openai` | The Codex delegation skill, present when the Codex plugin is installed | The ChatGPT subscription |
| `google` | The `delegating-to-agy` skill | The Google AI Pro subscription |
| `openrouter` | The `openrouter-claude-subagent` skill, a nested harness on another vendor's weights | The OpenRouter key, metered |

A model family with a subscription provider runs there and nowhere else
unless the user says otherwise for a run: Claude models through `anthropic`,
GPT models through `openai`, Gemini models through `google`. The OpenRouter
launcher refuses every Claude model outright, and it runs a GPT or Gemini
model only on the user's explicit instruction for that run. A spent
subscription quota is a reason to ask, not a reason to reroute.

## Pick by tier

| Tier | `anthropic` | `openai` | `google` | `openrouter` |
|---|---|---|---|---|
| `top` | `fable` | `gpt-6-astra` | | |
| `frontier` | `opus` | `gpt-6.1-sol` | `gemini-3.1-pro` | `moonshotai/kimi-k3` |
| `mid` | `sonnet` | `gpt-5.6-terra` | `gemini-3.8-flash` | `z-ai/glm-5.3` |
| `cheap` | `haiku` | `gpt-6-luna` | `gemini-3.8-flash` | `z-ai/glm-5.3-flash` |

The tiers are the vocabulary every dispatching skill and rule uses. `top` is
a vendor's strongest and most expensive model, spawned only after consulting
the user. `frontier` is judgment over a whole artifact: architecture,
security, cross-subsystem work, a final pre-merge pass, implementation under
a real test gate. `mid` is a walk or a re-read of a change: standard review,
the general default. `cheap` is triage, extraction and cost-sensitive fan-out.
An empty cell means that provider has no model at that tier. Where two tiers
name one model, the dispatching skill's effort is what separates them.

## Models

| Provider | Model (the `model` or `--model` value) | In / Out | Context | Accepted efforts |
|---|---|---|---|---|
| `anthropic` | `fable` (Claude Fable 5.1) | $10.00 / $50.00 | 1M | `low` `medium` `high` `xhigh` `max` |
| `anthropic` | `opus` (Claude Opus 5.5) | $4.00 / $20.00 | 1M | `low` `medium` `high` `xhigh` `max` |
| `anthropic` | `sonnet` (Claude Sonnet 5.5) | $2.00 / $10.00 | 1M | `low` `medium` `high` `xhigh` `max` |
| `anthropic` | `haiku` (Claude Haiku 4.5) | $1.00 / $5.00 | 200K | none |
| `openai` | `gpt-6-astra` | $10.00 / $50.00 | 272K | `low` `medium` `high` `xhigh` `max` `ultra` |
| `openai` | `gpt-6.1-sol` | $2.00 / $10.00 | 272K | `low` `medium` `high` `xhigh` `max` `ultra` |
| `openai` | `gpt-5.6-terra` | $2.00 / $12.00 | 272K | `low` `medium` `high` `xhigh` `max` `ultra` |
| `openai` | `gpt-6-luna` | $0.20 / $1.20 | 272K | `low` `medium` `high` `xhigh` `max` |
| `google` | `gemini-3.1-pro` | subscription | 1M | `low` `high` |
| `google` | `gemini-3.8-flash` | subscription | 1M | `low` `medium` `high` |
| `openrouter` | `moonshotai/kimi-k3` | $0.70 / $10.00 | 1M | `low` `high` `max` |
| `openrouter` | `z-ai/glm-5.3` | $0.22 / $4.40 | 1M | `low` `high` `max` |
| `openrouter` | `moonshotai/kimi-k2.6` | $0.43 / $1.83 | 262K | none: reasoning on or off, no level |
| `openrouter` | `z-ai/glm-5.3-flash` | $0.15 / $0.50 | 1M | `low` `high` `max` |
| `openrouter` | `google/gemini-3.8-flash` | $0.75 / $3.75 | 1M | `low` `medium` `high`; on the user's explicit instruction only |

How an effort reaches each provider is the launcher's business, and each
launcher skill says so: the Agent tool takes no effort and a Workflow
`agent()` call does; Codex takes it in the dispatch; agy takes it as a suffix
on the model id; the OpenRouter launcher takes an `--effort` flag. `ultra` on
OpenAI adds automatic task delegation inside Codex, so it is never the pick
for a run that must read its target itself.

## A model not in this table

It is unverified: its price, context and effort support are unknown here. Look
it up at the source for its provider, say what you found and where, and ask
before using it. If it is to be reused, add its row here and re-date the
table; nothing else records it.
