---
name: retrospect
description: Use when the user wants to reflect on the current session and make future ones better — a retrospective, retro, or post-mortem on how it went. Apply when they ask what slowed things down, wasted tokens, or caused round-trips, or what to improve about the agent's context (CLAUDE.md, AGENTS.md, memories, code or design docs), tool availability and selection, or how they prompt — and when they want what worked reinforced. Triggers on "retrospect", "retro", "post-mortem", "how did this session go", "how could this have gone smoother", "what should I change". Not for a single in-the-moment correction, and not for a retro on a project unrelated to this session.
disable-model-invocation: true
admission:
  provides: The only pass that reads the session transcript for cause. Size and budget instruments measure artifacts; review gates measure a change; neither can see that a round-trip happened because context was buried, a tool went unused, or a request was under-specified. Produces a ranked set of fixes, each routed by root cause and each with a landing site that outlives the session.
  cost: Zero always-on tokens — user-invoked, so the description is absent from the session catalog. On invoke it costs the body plus a pass over the conversation already in context.
  remove_when: Two consecutive retrospectives produce no recommendation that changes a file, a gate, or a memory — the findings are all reinforcement, meaning the upstream causes are already being caught.
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

A recommendation that ends as prose in a chat window is gone at the next session.
Every one has to name where it lands.

## When NOT to use

- A single in-the-moment correction — apply it and move on.
- A retrospective on a project or sprint unrelated to the current session.
- A trivial session with nothing to learn — say so in one line rather than
  manufacturing findings.

## The distinction that makes recommendations correct

Before recommending anything, classify each problem by its **root cause** — because
the right fix differs for each, and the most common failure of a retrospective is
"write another rule" for a problem more rules won't solve.

| Root cause | Signal | Correct fix | Wrong fix |
|---|---|---|---|
| **Context gap** | Needed knowledge was missing, stale, or buried where it wasn't seen | Add, repair, or relocate the context (CLAUDE.md, AGENTS.md, a memory, code or design docs) | Putting the knowledge where it won't be seen at the decision point — right content, wrong home |
| **Compliance failure** | The knowledge already existed and was ignored | A *mechanical* gate (hook, CI check, lint rule, script) that makes the mistake structurally impossible; or strengthen and relocate the existing rule so it's actually seen | Adding a second prose rule that says the same thing — rule bloat that degrades performance |
| **Tooling gap** | No good tool existed for the job, or a better one was available but unused | Add or propose the tool or check; or document the better tool choice | A prose rule telling the agent to do the tool's job by hand from memory |
| **Prompting gap** | The request was under-specified, ambiguous, or missing detail that caused rework | Suggest a concrete prompt pattern *to the user* — framed as their lever, not their fault | Silently absorbing it as an agent rule |

**The dedup test:** before proposing any new rule, skill, or memory, check whether the
lesson is *already* covered by existing context. If it is, the finding is a
compliance failure, not a context gap — recommend enforcement, not duplication.

## Process

### 1. Scope it — honour the user's spotlight

If the user named a focus area when invoking, make it the **spotlight**: analyse it
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
| **Agent context** | Was needed context missing, stale, buried, or present-but-ignored? |
| **Tool availability & selection** | Was the right tool *available*? Was it *chosen*? Would a mechanical check or a missing tool have prevented a problem? |
| **Prompting** | Was the request clear, scoped, and complete up front? What upfront detail or phrasing would have removed a round-trip? |

Efficiency is the cross-cutting lens: most findings surface first as wasted time or
tokens. Trace each waste back to one of the three targets.

### 4. Root-cause and route each finding

For every problem, name the root cause from the table above, then the correct fix.
Run the dedup test before proposing any rule, skill, or memory.

### 5. Mark what went well — and why

Identify practices, skills, or techniques that genuinely worked, and state **why**
each worked, so the user repeats them with confidence. This is reinforcement, not
praise — name only real wins, skip the filler. A retrospective that lists only
problems trains the user away from what was working.

### 6. Prioritise

Score each recommendation by **impact** (time, tokens, and rework it saves) against
**effort** (cost to land it), and sort. Lead with the top item.

### 7. Give every recommendation a landing site

A fix with no home is a fix that does not survive the session. Before presenting it,
say where it lands:

| Fix | Where it lands |
|---|---|
| Context repair | The file actually read at the decision point — the project's AGENTS.md/CLAUDE.md, a code or design doc. Right content in the wrong home is still a miss. |
| A lesson that must outlive this session | Durable memory: one fact per entry, with why it matters and how to apply it. |
| A mechanical gate | A hook, CI check, lint rule, or script — proposed as work to be done, never claimed as done. |
| A new rule, skill, or command | The project's admission bar. State what it prevents or provides, what it costs, and what observation would remove it; default to declining. Run the dedup test first. |
| A prompt pattern | Stated to the user as their lever. Nothing lands in the agent's context. |

Then **offer** to action the approved items. Do not auto-apply; the user decides
what lands.

## Report structure

See [references/deliverable-shape.md](references/deliverable-shape.md) for the
section order, the recommendations table, and a worked example.

## Common mistakes

| Mistake | Fix |
|---|---|
| Recap instead of retrospective | Every finding must yield a fix or a reinforcement, not just a description |
| "Write another rule" for a compliance failure | Recommend a mechanical gate; run the dedup test first |
| A recommendation with no landing site | Name the file, the gate, or the memory — or it did not happen |
| False praise in "what went well" | Name only genuine wins, each with a why — or say "nothing notable" |
| Blaming the user for prompting gaps | Frame prompt findings as the user's lever, neutrally |
| Findings with no priority | Always rank by impact vs effort; lead with the top one |
| Fabricating session detail after compaction | Work only from what's in context; state the gap honestly |
| Spotlight swallows the report | Honour the focus, but still sweep everything else briefly |
