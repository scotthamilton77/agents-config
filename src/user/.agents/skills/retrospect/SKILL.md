---
name: retrospect
description: Use when the user wants to reflect on the current session and make future ones better — a retrospective, retro, or post-mortem on how it went. Apply when they ask what slowed things down, wasted tokens, or caused round-trips, or what to improve about the agent's context (CLAUDE.md, AGENTS.md, memories, code or design docs), tool availability and selection, or how they prompt — and when they want what worked reinforced. Triggers on "retrospect", "retro", "post-mortem", "how did this session go", "how could this have gone smoother", "what should I change". Do NOT use for a single in-the-moment correction (use self-improving-agent) or a retro on a project unrelated to this session.
---

# Retrospect

## Overview

A retrospective turns one session's lived experience into durable improvements to
the *environment* the agent works in — its context, its tools, and how it's
prompted — not a recap of what happened.

Core principle: **most of what slows a session down is fixable upstream.** Every
avoidable round-trip, wasted search, or wrong turn traces to a cause in the agent's
context, its tooling, or the prompt — and each cause has a *different* correct fix.
The job is to find those causes, route each to the right fix, and rank them so the
single highest-leverage change is unmistakable.

The deliverable is a prioritized, actionable **report**. Behavioral lessons that
belong in persistent rules are handed to the `self-improving-agent` skill rather
than re-derived here.

## When to Use

- The user asks to retrospect, run a retro/post-mortem, or review "how this session went."
- The user wants to know what slowed things down, wasted tokens, or caused round-trips.
- The user wants to improve their agent context, tooling, or prompting from this session.
- The end of a substantial session worth learning from.

## When NOT to Use

- A single in-the-moment correction → use `self-improving-agent` directly.
- A retrospective on a project or sprint unrelated to the current session.
- A trivial session with nothing to learn — say so in one line rather than manufacturing findings.

## The Distinction That Makes Recommendations Correct

Before recommending anything, classify each problem by its **root cause** — because
the right fix differs for each, and the most common failure of a retrospective is
"write another rule" for a problem more rules won't solve.

| Root cause | Signal | Correct fix | Wrong fix |
|---|---|---|---|
| **Context gap** | Needed knowledge was missing, stale, or buried where it wasn't seen | Add, repair, or relocate the context (CLAUDE.md, AGENTS.md, a memory, code or design docs) | Putting the knowledge where it won't be seen at the decision point — right content, wrong home |
| **Compliance failure** | The knowledge already existed and was ignored | A *mechanical* gate (hook, CI check, lint rule, script) that makes the mistake structurally impossible; or strengthen/relocate the existing rule so it's actually seen | Adding a second prose rule that says the same thing — rule bloat that degrades performance |
| **Tooling gap** | No good tool existed for the job, or a better one was available but unused | Add or propose the tool or check; or document the better tool choice | A prose rule telling the agent to do the tool's job by hand from memory |
| **Prompting gap** | The request was under-specified, ambiguous, or missing detail that caused rework | Suggest a concrete prompt pattern *to the user* — framed as their lever, not their fault | Silently absorbing it as an agent rule |

**The dedup test:** before proposing any new rule or memory, check whether the
lesson is *already* covered by existing context. If it is, the finding is a
compliance failure, not a context gap — recommend enforcement, not duplication.

## Process

### 1. Scope it — honor the user's spotlight

If the user named a focus area when invoking, make it the **spotlight**: analyze it
deepest and lead the report with it. Still run the full sweep below — the spotlight
is additive, never exclusive. If no focus was given, sweep everything.

### 2. Reconstruct the session

From the actual conversation in context (don't fabricate; if context was compacted,
say so and work from what remains), establish:

- **Goal** — what the user actually wanted.
- **Path** — the route taken to get there.
- **Outcome** — shipped, partial, or abandoned.
- **Cost** — the *avoidable* part: correction round-trips, redundant searches, wrong
  turns, token-heavy detours. Quantify where visible.

### 3. Sweep the three improvement targets

| Target | Ask |
|---|---|
| **Agent context** | Was needed context missing, stale, buried, or present-but-ignored? (CLAUDE.md, AGENTS.md, memories, code docs, design docs) |
| **Tool availability & selection** | Was the right tool *available*? Was it *chosen*? Would a mechanical check or a missing tool have prevented a problem? |
| **Prompting** | Was the request clear, scoped, and complete up front? What upfront detail or phrasing would have removed a round-trip? |

Efficiency is the cross-cutting lens: most findings surface first as wasted time or
tokens. Trace each waste back to one of the three targets.

### 4. Root-cause and route each finding

For every problem, apply the classification table above: name the root cause, then
the correct fix. Run the dedup test before proposing any rule or memory.

### 5. Mark what went well — and why

Identify practices, skills, or techniques that genuinely worked, and state **why**
each worked, so the user repeats them with confidence. This is reinforcement, not
praise — name only real wins, skip the filler. A retrospective that lists only
problems trains the user away from what was working.

### 6. Prioritize and categorize

Rank recommendations so the highest-leverage one is unmistakable. Score each by
**impact** (time, tokens, and rework it saves) against **effort** (cost to land it),
and sort. Lead with the top item.

### 7. Deliver, then offer to apply

Present the report (structure below). Then **offer** to action the approved items —
route behavioral lessons through `self-improving-agent`, apply context edits to the
correct file, and sketch any proposed mechanical checks. Do not auto-apply; the user
decides what lands.

## Report Structure

1. **Bottom line** — outcome, the avoidable cost, and the single
   highest-leverage change (stated up front).
2. **What went well** — wins worth repeating, each with its *why*.
3. **What slowed us down** — findings, each tagged `[target / root-cause]` and traced
   to its cause.
4. **Recommendations** — the prioritized table:

   | Recommendation | Target | Root cause | Impact | Effort | Priority |
   |---|---|---|---|---|---|

5. **Apply?** — the offer to action approved items.

## Example (condensed)

> **Bottom line:** Feature shipped, but three correction round-trips did QA the
> system should have done. Highest-leverage fix: convert the two most-violated prose
> rules into mechanical gates.
>
> **What went well:** The todo list on the multi-step fix — *why:* it externalized
> state so nothing got dropped mid-task. Keep requesting it for anything multi-step.
>
> **What slowed us down:** Skipped the project's AGENTS.md, so a documented "register
> flags in two places" rule was missed `[Agent context / Compliance failure]` — the
> rule existed and was ignored, so more prose won't help.
>
> | Recommendation | Target | Root cause | Impact | Effort | Priority |
> |---|---|---|---|---|---|
> | Pre-edit hook blocking the first edit until AGENTS.md is read | Tool availability & selection | Compliance failure | High | Med | P0 |
> | CI check: a flag must appear in both registration sites | Tool availability & selection | Compliance failure | High | Low | P0 |
> | Record the newly-seen test-tautology pattern in the existing testing guidance | Agent context | Context gap | Med | Low | P1 |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Recap instead of retrospective | Every finding must yield a fix or a reinforcement, not just a description |
| "Write another rule" for a compliance failure | Recommend a mechanical gate; run the dedup test first |
| False praise in "what went well" | Name only genuine wins, each with a why — or say "nothing notable" |
| Blaming the user for prompting gaps | Frame prompt findings as the user's lever, neutrally |
| Findings with no priority | Always rank by impact vs effort; lead with the top one |
| Fabricating session detail after compaction | Work only from what's in context; state the gap honestly |
| Spotlight swallows the report | Honor the focus, but still sweep everything else briefly |
