---
name: delegating-to-codex
description: Use when work is actually being handed to Codex — "use codex", "have codex review this", "get a second opinion from codex", "rescue this with codex" — when another skill or brief calls for a Codex pass, or when picking the model for a Codex run you are about to dispatch. Not for questions about Codex or its model tiers when nothing is being dispatched, not for Codex CLI setup or auth, and not for OpenRouter models, a nested claude harness, or Gemini CLI.
admission:
  provides: The task-profile-to-model mapping for a Codex run — the one routing decision the Codex plugin declines to make, since its own runtime leaves the model unset unless the caller names one.
  cost: 115 always-on tokens for this description line, measured; the body's 409 are paid only when a Codex dispatch is actually in hand. Replaces a 470-token always-on rule, so the surface it loads into drops by 355. The model table needs a refresh whenever OpenAI reprices, renames, or retires a tier.
  remove_when: The Codex plugin's runtime selects a model by task profile itself, so a caller that names nothing still gets the right tier.
---

<!--
Source: authored 2026-08-01, replacing the codex-routing rule, which failed
re-admission as a rule — conditional delegation guidance charged to every
session whether or not Codex was ever reached for. Content is narrowed to what
the Codex plugin's own deployed surface does not already say; the invocation
recipe and flag contract were dropped because that surface states them, and
stated them differently.
-->

# Delegating to Codex

Reach Codex through the plugin's own runtime — the Codex rescue agent, or the
companion script that agent wraps. Not the raw `codex` binary.

## Which model

A Codex run carries no explicit model by default, and the runtime keeps it that
way unless the caller names one. Naming it is this skill's whole job.

| Task profile | Model |
|---|---|
| Architecture, cross-subsystem, security, final pre-merge pass | `gpt-5.6-sol` |
| Standard review, implementation, general default | `gpt-5.6-terra` |
| First-pass triage, diff summary, per-file parallel review, cost-sensitive runs | `gpt-5.6-luna` |
| Deeply code-centric, Codex-tuned agentic work | `gpt-5.3-codex` |

No profile matching cleanly is itself an answer: leave the model unset and take
the plugin's default rather than forcing a row to fit.

## Where this sits relative to the rescue agent

The rescue agent is the executor. This table is the decision made just before it
runs, so the two compose rather than compete — dispatch the agent as you would
anyway, and let the dispatch carry a model when a profile above matches.

Which one leads depends on who is stuck:

- **Routing a defined task to Codex** — the profile is known, so pick the tier
  here, then dispatch.
- **Reaching for help because the work has stalled** — dispatch first. Let the
  runtime default stand unless the profile is obvious.

## What this skill does not decide

Whether a run may write, what effort it uses, and how the prompt reaches Codex
belong to the plugin runtime's own contract. Follow that contract where it
speaks. This skill adds a model, and nothing else.
