---
name: dispatching-subagents
description: Use when handing work to a subagent or running repeated rounds of adversarial review over a change. Apply whenever you are about to write a brief for delegated work, split a task across agents, dispatch a fix and re-review it, or decide whether to run another round or stop — and whenever a delegated agent built the wrong thing, went idle without delivering its report, argued with a brief, a review re-raises findings already settled, or rounds keep finding defects and you cannot tell whether the change or your own earlier fixes are producing them. Not for validating a single round's verdict artifact.
admission:
  prevents: Delegated work that costs more than it saves — briefs that encode the dispatcher's wrong mechanism into the agent's implementation, contradictory briefs implemented instead of challenged, finished judgement lost to a delivery step that silently failed, and review loops that stop on a round number while severity is still climbing.
  cost: Every dispatch carries a constraints-and-ownership section, a refusal clause and a report path; every review round carries a refutation list and an origin tag per finding.
  remove_when: A run of delegated fixes shows no defect traceable to a prescribed mechanism, no report lost to an idle notification, and two loops in a row terminate on a measured stop signal rather than a judgement call.
---

<!--
Source: authored 2026-07-27; body rewritten 2026-07-31 against a two-arm test of three dispatch
scenarios. Scope is set by that test, not by intuition — baseline agents unaided already choose
sound agent counts, batch splits, barrier placement and model tiers, so all of that is omitted
deliberately. Model and effort selection lives in the delegation rule, not here.
Placement: Claude-dependent (subagent orchestration, workflow fan-out), so it lives in the Claude
tree rather than the shared one.
Not run through admit-request: added on explicit user instruction, the same path the delegation
rule took; the record above is authored, not gate-issued.
-->

Delegation fails in two unrelated ways. A single dispatch fails because the brief smuggled in the
dispatcher's assumptions, or gave the agent's answer nowhere to land. A loop of dispatches fails
because nobody fixed the stop condition before fatigue supplied one.

**Writing one dispatch?** The first two sections are the whole skill for you. Stop there.
**Running rounds over one artifact?** Read on — a loop is dispatches plus a termination rule, and
the termination rule is the half that gets improvised.

Nothing here covers how many agents to use, how to batch the work, or where to put a barrier. Your
own judgement is reliable on those. It is not reliable on what follows.

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

## Running rounds

**Fix the threat model and restate it every round**, or each round re-argues what counts as a
threat and reviewers file work already ruled out.

**Carry a refutation list forward.** Every round's brief lists what previous rounds refuted and
why. Highest-leverage instruction in the loop; it is what stops round-over-round churn.

**Tag every finding by origin — pre-existing, or induced by round N of this loop — from round
one.** Invented late it yields a handful of data points; specified early it draws a curve. You
cannot read the stop table without it.

**Prefer a workflow over hand-assembled dispatches when stages chain or the return is structured
and numerous** — a captured return value cannot be silently dropped by an idle agent. A single
parallel fan-out over disjoint files does not need one; reach for a workflow when you would
otherwise be collating by hand across rounds.

## Stopping

Raw finding count is the wrong instrument. It stays flat while the loop is still productive,
because every round finds something real, so "findings dried up" never arrives — an unaided
stopping rule reliably invents a round cap instead, which is the thing to resist.

**Read this off the current round's serious findings only.** Minor findings never gate the stop;
they are the noise the count-based instinct latches onto. Earlier rounds' tags are history, not
input. If you cannot tell whether a finding is serious, it is. If the serious ones are untagged you
cannot read the table, and that is the answer: run the round.

| Serious findings this round | The next round |
| --- | --- |
| None | Stop — provided this round was itself scoped to the newest diff. If it was not, run that one first. |
| Any induced by a recent round | Scope it to the newest diff. Guards written to close a fail-open are the least-reviewed code in the tree, including the ones you endorsed in writing. |
| All pre-existing | Keep the sweep broad. The artifact still has depth. |

The table sets *what the next round looks like*, not merely whether to run one — which is why a
mixed round needs no tie-break. One induced serious finding decides the scope. The newest diff is
everything that changed since the previous round, not only the parts you consider risky.

## Red flags

Writing a dispatch:

- You are about to write an imperative verb about the code, and the fix is not a deletion.
- The brief tells the agent what to report and never tells it to send anything.
- An agent went idle and you are about to re-run its work rather than read its file.

Running a loop:

- You are ending it because you have done enough rounds, because the budget ran out, or because the
  count stopped rising. Those are the same failure wearing three hats — none is a stop signal.
- A finding you already refuted is back, and no round brief lists the refutation.
