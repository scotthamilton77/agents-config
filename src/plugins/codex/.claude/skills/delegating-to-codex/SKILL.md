---
name: delegating-to-codex
description: Use when a run is being launched on Codex and the model tier still has to be chosen — the user named Codex, or another skill sent a dispatch here. Not for deciding whether to leave Claude in the first place, not for questions about Codex when nothing is being dispatched, not for Codex CLI setup or auth, and not for OpenRouter or Gemini CLI.
admission:
  provides: The task-profile-to-model mapping for a Codex run — the one routing decision the Codex plugin declines to make, since its own runtime leaves the model unset unless the caller names one.
  cost: The model table needs a refresh whenever OpenAI reprices, renames, or retires a tier.
  remove_when: The Codex plugin's runtime selects a model by task profile itself, so a caller that names nothing still gets the right tier.
---

# Delegating to Codex

Reach Codex by dispatching the `codex-rescue` agent through the Agent tool.
This skill addresses the caller. If you *are* the `codex-rescue` agent, the
dispatch has already happened: reach Codex through your own runtime, as your
agent definition says, and do not dispatch another `codex-rescue` — a rescue
agent that dispatches a rescue agent reviews nothing.
That agent comes from the Claude Code plugin `codex`, published by the
`openai-codex` marketplace — `codex@openai-codex` written in full — and not
from the plugin that deployed this skill, which shares the short name and
nothing else. If the agent does not appear as an agent type in the session,
check whether `codex@openai-codex` is installed, and if it is not, stop and
tell the user rather than falling back to the raw `codex` binary, which stays
forbidden either way.
How the agent reaches Codex once dispatched is its own runtime's contract, not
this skill's.

## Which model

A Codex run carries no explicit model by default, and the runtime keeps it that
way unless the caller names one. Naming it, and for a review seat its effort and
tool grant, is this skill's whole job.

Verified **2026-09-17** against OpenAI's model pages (`developers.openai.com/api/docs/models`
and the Codex models page, `learn.chatgpt.com/docs/models`). OpenAI renames and retires tiers without much notice —
re-verify there before routing anything cost-sensitive.

| Task profile | Model |
|---|---|
| Architecture, cross-subsystem, security, final pre-merge pass | `gpt-5.6-sol` |
| Standard review, implementation, general default | `gpt-5.6-terra` |
| First-pass triage, diff summary, per-file parallel review, cost-sensitive runs | `gpt-5.6-luna` |

`gpt-6-astra` sits above sol and is not a row: it is user-blessed only, under the
same sentence the delegation rule applies to Fable — a per-seat blessing or an
explicit ask is the only route to it. `gpt-5.3-codex` is retired; its successor,
`gpt-5.3-codex-spark`, is a text-only near-instant preview and not a review or
implementation tier.

### Review seats

A review-panel or ac-attack lens on the codex transport takes its model, effort and
tool grant from its tier, not from the task profile:

| Seat | Model | Effort | Tools |
|---|---|---|---|
| frontier lens | `gpt-5.6-sol` | `high` | the runtime's read-only sandbox; never `--write` |
| mid lens | `gpt-5.6-terra` | `medium` | the runtime's read-only sandbox; never `--write` |

A lens reads untrusted content, so its run is never write-capable: the dispatch omits
`--write`, and the runtime's sandbox is then read-only.

The OpenRouter seats, the staffing recommender and the trend checkpoint are rows in
the `openrouter-claude-subagent` skill's seat table.

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

## Dispatching the rescue agent

Dispatch `codex-rescue` **unnamed**. A `name` turns it into a teammate with the
orchestration kit; it then reads this skill, follows "dispatch the rescue
agent", and spawns a second copy of itself instead of forwarding. Brief it to
put an explicit Bash `timeout` (about 1,500,000 ms) on the companion call and
never to pass `--wait` — an unknown flag is folded into the Codex prompt, and
an untimed call past the default 120 s is auto-backgrounded where a Bash-only
agent cannot collect it. A result that says it is "waiting for the background
task" is a dead agent, not a pending one.

Never export `CODEX_HOME` pointing at the plugin directory. It is Codex's own
home, where `auth.json` lives; pointed elsewhere, requests go out with no
credential and `401 Missing bearer` from `api.openai.com/v1/responses` is the
fingerprint. Hold the companion path in a variable of another name.

## What this skill does not decide

Whether a run may write and how the prompt reaches Codex belong to the plugin
runtime's own contract. Follow that contract where it speaks. This skill adds a
model — and, for a review seat, its effort and tool grant — and nothing else.
