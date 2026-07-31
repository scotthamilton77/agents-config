---
name: dispatching-subagents
description: Use when handing work to a subagent. Apply whenever you are about to write a brief for delegated work, split a task across agents, or choose which substrate — a native subagent or workflow, an OpenRouter-hosted model, Codex — should run a delegated task; and whenever a delegated agent built the wrong thing, went idle without delivering its report, or argued with a brief.
admission:
  prevents: Delegated work that costs more than it saves — briefs that encode the dispatcher's wrong mechanism into the agent's implementation, contradictory briefs implemented instead of challenged, finished judgement lost to a delivery step that silently failed, and dispatches routed to a frontier model out of habit because no substrate comparison was ever made.
  cost: Every dispatch carries a constraints-and-ownership section, a refusal clause and a report path.
  remove_when: A run of delegated fixes shows no defect traceable to a prescribed mechanism and no report lost to an idle notification.
---

<!--
Source: authored 2026-07-27.
-->

A dispatch fails in two ways: the brief smuggles in the dispatcher's assumptions, or it gives the
agent's answer nowhere to land. Everything here guards one of those two.

Nothing here covers how many agents to use, how to batch the work, or where to put a barrier. Your
own judgement is reliable on those.

## Writing a dispatch

A brief carries four things and one prohibition.

**The defect as observed** — what breaks, and how you know. Include the repro.

**The constraints** — what must still be true when the agent is done, including the things your fix
must not break in passing. This is where the thinking goes that you would otherwise have spent on
prescribing a fix.

**Ownership** — which files are the agent's, what is off-limits, and any sibling that already
answers the same question. Check for that sibling by asking the filesystem, not by reasoning about
what probably exists; if you cannot look yourself, make finding it the agent's first instruction.

**A landing place for the answer.** Name a path the agent *writes* its report to, then separately
command delivery: *send this as your final message; do not end your turn without it.* A "Return
format" block describes an artifact and commands no action — agents finish, go idle, and deliver
nothing while holding a good report. Code survives that; judgement does not. If you do not know the
agent's working root, tell it how to resolve its own and to echo the resolved path back.

**Never the mechanism** — see below.

Also: require a test, not a demonstration. Manual verification protects this commit; only a test
protects the next one. And tell the agent to refuse a brief it cannot honour — stop and report when
the brief is ambiguous, self-contradictory, or rests on a premise the code does not support. Add
*assume there is an error in my framing.* Briefs demanding "all suites green" while forbidding the
edit that greens them are the normal case, not an exotic one.

## Where defect ends and mechanism begins

The boundary is not "did I name a solution." It is: **diagnosis is a noun phrase; mechanism is a
verb phrase about the code.** State what is true and what must become true, and stop at the verb.

> ✅ "Cache keys are built from endpoint plus params. Two tenants issuing the same query collide on
> one entry. No tenant may read another's; same-tenant caching must keep working."
> ❌ "...so add the tenant id to the key."

The first sentence of the bad version is identical to the good one. Only the imperative is new —
and it is the imperative that does the damage, because it forecloses the agent's ability to
disagree with your diagnosis. *Add the tenant id* rules out "this endpoint should not be cached at
all" and rules out the tenant-scoped cache client sitting one file over. Every observed instance of
a prescribed mechanism shipping a defect had this shape: the reasoning was implemented faithfully
and the reasoning was wrong.

Watch for `add`, `wrap`, `gate`, `move`, `fold`, `use X here`. **The one exception is removal** —
prescribe a deletion, and say plainly that it is the one place you are prescribing.

## Choosing the substrate

The native Agent tool is the default. Prefer a workflow over hand-assembled dispatches when stages
chain or the return is structured and numerous — a captured return value cannot be silently dropped
by an idle agent. Two substrates run a dispatch on other vendors' weights, and each states when it
earns its keep in its own frontmatter or rule:

- **`openrouter-claude-subagent`** — a nested claude on an OpenRouter-hosted model, for work that
  does not need a frontier model and for opinions that must not share one vendor's blind spots.
- **The Codex plugin** — work routed to an OpenAI model through the Codex companion runtime; its
  routing rule carries the model table and the invocation contract.

## Red flags

- You are about to write an imperative verb about the code, and the fix is not a deletion.
- The brief tells the agent what to report and never tells it to send anything.
- An agent went idle and you are about to re-run its work rather than read its file.
