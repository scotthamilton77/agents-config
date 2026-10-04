---
name: retrospect
description: Use when the user wants to reflect on the current session and make future ones better — a retrospective, retro, or post-mortem on how it went. Apply when they ask what slowed things down, wasted tokens, or caused round-trips, or what to improve about the agent's context (CLAUDE.md, AGENTS.md, memories, code or design docs), tool availability and selection, or how they prompt — and when they want what worked reinforced. Not for a single in-the-moment correction, and not for a retro on a project unrelated to this session.
disable-model-invocation: true
admission:
  provides: The only pass that reads the session transcript for cause. Size and budget instruments measure artifacts; review gates measure a change; neither can see that a round-trip happened because context was buried, a tool went unused, or a request was under-specified. Produces a ranked set of fixes, each routed by root cause and each with a landing site that outlives the session.
  cost: Context footprint only, bounded by the caps content-lint enforces.
  remove_when: Two consecutive retrospectives produce no recommendation that changes a file, a gate, or a memory — the findings are all reinforcement, meaning the upstream causes are already being caught.
---

# Retrospect

**Model floor.** This skill depends on reasoning that smaller models do not sustain.
Before doing anything else, check which model you are running on. If it is Claude
Sonnet or Haiku, or another vendor's comparable mid or small tier, stop. Tell the
user that a retrospective from this model is likely to list symptoms and miss root
causes, and ask them to either switch to a stronger model or confirm that they
accept the risk. Do not start the work until they answer. If another agent
dispatched you and you cannot reach the user, return this message to the dispatcher
instead of proceeding. Once the user has confirmed in this session, do not ask
again.

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

Reconstruct the session from what is actually in context: goal, path, outcome, and
the avoidable cost. Say so if compaction removed part of it. Classify every problem
by root cause and route it to the fix that cause calls for, across agent context,
tooling and prompting, with the user's named focus analysed deepest. Name what
worked and why. Rank the recommendations by impact against effort, lead with the
top one, give each a landing site from the table below, then offer to action the
approved ones.

The avoidable cost is correction round-trips, redundant searches, wrong turns and
token-heavy detours; quantify it where visible. A named focus leads the report, but
it is additive, never exclusive: still sweep every target. Impact is the time,
tokens and rework a recommendation saves; effort is the cost to land it.

Sweep the three improvement targets:

| Target | Ask |
|---|---|
| **Agent context** | Was needed context missing, stale, buried, or present-but-ignored? |
| **Tool availability & selection** | Was the right tool *available*? Was it *chosen*? Would a mechanical check or a missing tool have prevented a problem? |
| **Prompting** | Was the request clear, scoped, and complete up front? What upfront detail or phrasing would have removed a round-trip? |

Efficiency is the cross-cutting lens: most findings surface first as wasted time or
tokens. Trace each waste back to one of the three targets.

What worked is reinforcement, not praise: state **why** each practice worked so the
user repeats it with confidence, and name only real wins. A retrospective that lists
only problems trains the user away from what was working.

A fix with no home is a fix that does not survive the session. Before presenting a
recommendation, say where it lands:

| Fix | Where it lands |
|---|---|
| Context repair | The file actually read at the decision point — the project's AGENTS.md/CLAUDE.md, a code or design doc. Right content in the wrong home is still a miss. |
| A lesson that must outlive this session | Durable memory: one fact per entry, with why it matters and how to apply it. |
| A mechanical gate | A hook, CI check, lint rule, or script — proposed as work to be done, never claimed as done. |
| A new rule, skill, or command | The project's admission bar, where one exists — state what it prevents or provides, what it costs, and what observation would remove it; default to declining. Where no formal gate exists, put the same record in front of the user for a direct decision instead. |
| A prompt pattern | Stated to the user as their lever. Nothing lands in the agent's context. |

Then **offer** to action the approved items. Do not auto-apply; the user decides
what lands.

## Report structure

See [references/deliverable-shape.md](references/deliverable-shape.md) for the
section order, the recommendations table, and a worked example.
