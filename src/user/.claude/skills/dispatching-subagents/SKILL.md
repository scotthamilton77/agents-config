---
name: dispatching-subagents
description: Use when handing work to a subagent or running repeated rounds of adversarial review over a change. Apply whenever you are about to write a brief for delegated work, split a task across agents, dispatch a fix and re-review it, or decide whether to run another round or stop — and whenever a delegated agent built the wrong thing, went idle without delivering its report, argued with a brief, a review re-raises findings already settled, or rounds keep finding defects and you cannot tell whether the change or your own earlier fixes are producing them. Not for validating a single round's verdict artifact.
admission:
  prevents: Delegated work that costs more than it saves — briefs that encode the dispatcher's wrong mechanism into the agent's implementation, contradictory briefs implemented instead of challenged, finished judgement lost to a delivery step that silently failed, and review loops that stop on a round number while severity is still climbing.
  cost: Every dispatch carries a constraints-and-ownership section, a refusal clause and a report path; every review round carries a refutation list and an origin tag per finding.
  remove_when: A run of delegated fixes shows no defect traceable to a prescribed mechanism, no report lost to an idle notification, and two loops in a row terminate on a measured stop signal rather than a judgement call.
---

<!--
Source: authored 2026-07-27 from an eight-round adversarial review of a shipped skill; every rule
below is a failure observed in that run, not a precaution.
Placement: Claude-dependent (subagent orchestration, workflow fan-out, model/effort tiers), so it
lives in the Claude tree rather than the shared one.
Not run through admit-request: added on explicit user instruction, the same path the delegation
rule took; the record above is authored, not gate-issued.
-->

A subagent inherits none of your intent and every one of your mistakes. Both halves are expensive.
Briefs that named the fix shipped a fail-open three rounds running; finished reports were lost
because nothing ever told the agent to send them.

## Before you write the brief

**Look for a sibling that already solves it.** The correct answer to "are these two names one
file?" — ask the filesystem, never compare spellings — was already implemented one file away when
a dispatch told an agent to fold case instead. Neither the dispatcher nor the agent looked. If a
neighbouring file answers the same question, name it in the brief.

## What goes in a brief

**State the defect and the constraints. Never the mechanism.**

This is the rule that cost the most to learn. Say what breaks, how it was observed, what must stay
true afterwards, and what the agent owns. Then stop. Every time a dispatch prescribed *how* to
fix something, the agent implemented that reasoning faithfully and the reasoning was wrong —
"fold case here, permissiveness is the right direction" opened a hole letting one document's
record close a round over a different document; "gate the refusal on whether this is the attacked
revision" put the exemption under the control of a field the record's own author writes. The round
those dispatches switched to defect-plus-constraints, the agents produced better designs *and*
caught the errors in the framing.

Prescribe a mechanism only when the fix is **removal**, and say plainly that it is the one place
you are prescribing.

**Tell it to refuse a brief it cannot honour.** Every dispatch says: stop and report rather than
implement when the brief is ambiguous, self-contradictory, or rests on a premise the code does not
support — and say so plainly if the framing of the defect looks wrong. Add *assume there is an
error in my framing*. That sentence measurably changes behaviour; it is why three of the
dispatcher's own errors were caught by agents instead of by the next review round. A brief
demanding "all suites green" while forbidding the edit that greens them is the normal case, not an
exotic one.

**Command the report, and give it somewhere to land.** Six agents in one session finished, went
idle, and delivered nothing — while holding good reports, two of which arrived in full the moment
they were asked again. Only delivery failed. Every dispatch ended with a numbered "Return format"
block, which describes an artifact and commands no action. So do both:

- an explicit imperative — *send this as your final message; do not end your turn without it*;
- a path the agent **writes** the report to, so an empty idle notification costs a file read.

Recovering code from a diff works. Recovering judgement does not — one agent's audit of claims
that had quietly gone stale was its round's most valuable output and existed nowhere else.

Where the work fans out and the return is structured, prefer a workflow whose captured return
value cannot be dropped over a dispatch whose report depends on a delivery step that can fail.

**Write every path the way the agent must type it.** If the work happens in a worktree, give
worktree-absolute paths and tell it to anchor on its own root. A relative path list invites an
agent to edit one tree and run commands in another.

**Require a test, not a demonstration.** Manual verification protects this commit; only a test
protects the next one. A fix confirmed by hand on a purpose-built case shipped with a suite that
stayed green when its guard was replaced by a weaker check.

## Running rounds

**Fix the threat model and restate it in every round.** Without it each round re-argues what
counts as a threat, and reviewers file work that was already ruled out.

**Carry a refutation list forward.** Every round's brief lists what previous rounds refuted and
why. This is the single highest-leverage instruction in the loop — it is what stopped
round-over-round churn.

**Tag every finding by origin: pre-existing, or induced by round N of this loop.** Specify it from
round one. Invented late, it yielded two data points out of eight; specified early it would have
drawn a curve.

**Stop on the split, not the count.** Raw finding count is the wrong instrument: across eight
rounds it stayed flat near fifteen and never fell, because every round found something real, so
"findings dried up" never arrived. The split is the signal, read alongside severity:

| Reading | What it means |
| --- | --- |
| Mostly induced, low severity | The loop is measuring its own patch rate. Stop. |
| Mostly induced, still surfacing serious defects | The newest fixes are themselves unreviewed. Keep going. |
| Mostly pre-existing | The artifact still has depth. Keep going. |

A count that falls while severity climbs is a loop about to stop on the wrong signal.

**Scope the final round to the newest diff.** Guards written to close a fail-open are the
least-reviewed code in the tree. A final round scoped to the last few hundred lines found three
fail-opens, all in guards written the round before — one of them a mechanism the dispatcher had
endorsed in writing.

## Red flags

- You are about to write "use X here" in a brief, and the fix is not a deletion.
- The brief tells the agent what to report and never tells it to send anything.
- An agent went idle and you are about to re-run its work rather than read its file.
- You are ending the loop because you have done enough rounds.
- A finding you already refuted is back, and no round brief lists the refutation.
