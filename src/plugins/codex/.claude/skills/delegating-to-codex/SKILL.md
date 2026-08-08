---
name: delegating-to-codex
description: Use when a run is being launched on Codex and the model tier still has to be chosen — the user named Codex, or another skill sent a dispatch here. Not for deciding whether to leave Claude in the first place, not for questions about Codex when nothing is being dispatched, not for Codex CLI setup or auth, and not for OpenRouter or Gemini CLI.
admission:
  provides: The task-profile-to-model mapping for a Codex run — the one routing decision the Codex plugin declines to make, since its own runtime leaves the model unset unless the caller names one.
  cost: The model table needs a refresh whenever OpenAI reprices, renames, or retires a tier.
  remove_when: The Codex plugin's runtime selects a model by task profile itself, so a caller that names nothing still gets the right tier.
---

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
