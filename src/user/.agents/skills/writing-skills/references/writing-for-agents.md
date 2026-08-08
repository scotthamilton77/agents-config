# Writing for Agents — the theory under the rules

Why the rules in `SKILL.md` work, and the levers they leave implicit. Read this
when a rule in the body is not deciding your case: you cannot tell what to
inline and what to disclose, a document is followed unreliably or ignored, a
pointer fires at the wrong time, or you are cutting a document down and need to
know what is safe to cut.

The scope is any document an agent consumes — a skill, an `AGENTS.md` /
`CLAUDE.md`, a doc reached by a pointer. The packaging differs; the writing does
not. The same levers make each one predictable: the agent taking the same
*process* every run, not producing the same output.

## Contents

- [Context pointers](#context-pointers)
- [The two loads](#the-two-loads)
- [Information hierarchy](#information-hierarchy)
- [Steps and completion bounds](#steps-and-completion-bounds)
- [When to split](#when-to-split)
- [Leading words](#leading-words)
- [Pruning](#pruning)

## Context pointers

A **context pointer** is a reference held in the agent's context that names some
out-of-context material and encodes the condition for reaching it. A skill's
description is one; a line in `AGENTS.md` naming a doc is the same object. The
pointer's *wording*, not its target, decides when the agent reaches the material
— and how reliably. A must-have target behind a weakly worded pointer is a
variance bug: sharpen the wording first, and inline the material only if
sharpening fails.

A pointer does two jobs — state what the material is, and list the **branches**
that should trigger reaching it (a branch is a distinct case the document
handles, so different runs take different paths through it). Every word of an
always-loaded pointer costs on every turn, so it earns even harder pruning than
the body:

- **Front-load the leading word** — the pointer is where it does its triggering
  work.
- **One trigger per branch.** Synonyms that rename a single branch are one branch
  written twice; collapse them and keep only genuinely distinct branches.
- **Cut identity the body already carries.**

## The two loads

Every document and pointer you add spends one of two budgets:

- **Context load** — the cost of always-loaded material on the agent's window: an
  `AGENTS.md` line, a skill description, anything sitting in context every turn,
  spending tokens and attention whether or not it fires.
- **Cognitive load** — the cost on the human: which documents exist and when to
  reach for each. The human is the index. Not a cost to minimise — it is the
  price of human agency; spend it where human judgement matters, remove it where
  it does not.

Material reached only through a pointer escapes context load at the price of the
pointer's own line; material with no pointer at all rides entirely on cognitive
load.

## Information hierarchy

A document is built from two content types — **steps** (the ordered actions the
agent performs) and **reference** (definitions, rules, facts consulted on demand)
— that mix freely: all steps (a recipe), all reference (a review's rules, this
file), or both. The core decision is where each piece sits on the **information
hierarchy**, a ladder ranked by how immediately the agent needs the material:

1. **In-file step** — the primary tier: what the agent does, in order.
2. **In-file reference** — consulted on demand. Often a legitimately flat
   peer-set (every rule of a review on one rung) — a fine arrangement, not a
   smell.
3. **Disclosed reference** — pushed out into a separate file, reached by a
   context pointer, loaded only when the pointer fires. Spans a sibling file in
   the same folder through fully external reference that lives anywhere and any
   document can point at.

Push too little down and the top bloats; push too much and you hide material the
agent actually needs. That tension is the whole decision.

**Progressive disclosure** is the move down the ladder — out of the main file and
behind a pointer — so the top stays legible. Not primarily a token optimisation:
it is how the hierarchy is protected. Branching is the cleanest disclosure test:
inline what every branch needs, and push behind a pointer what only some branches
reach. When a document has steps, in-file reference that should be disclosed
buries them and turns attending to them into a coin-flip — a variance lever, not
just a legibility one.

**Co-location** is the within-file companion: where the ladder decides *how far
down* a piece sits, co-location decides *what sits beside it* once there. Keep a
concept's definition, rules, and caveats under one heading rather than scattered,
so reading one part brings its neighbours with it. The test: the document should
read like documentation written for the agent — grouped material reads that way;
scattered material does not. (Distinct from duplication: that repeats one meaning
in two places; scattering fragments one meaning across many.)

**Sprawl** is the failure mode here: a document simply too long, even when every
line is live and unique. Attention thins across the excess, and every extra line
is one more to keep relevant. The cure is the ladder: disclose reference behind
pointers, and split by branch or sequence so each path carries only what it needs.

## Steps and completion bounds

Every step ends on a **completion bound** — the condition that tells the agent the
work is done.

> **Vocabulary.** A completion bound is not a review's *acceptance criteria*.
> Acceptance criteria are the termination condition for a round of review over
> finished work — they decide when reviewing stops. A completion bound is a
> property of one step inside a document you are authoring — it tells the agent
> running that step when to stop working. Same shape, different object; keep the
> names apart, because a document that uses one term for both teaches neither.

Two properties make the bound a lever:

- **Clarity** — can the agent tell done from not-done? A vague bound
  ("understanding reached") invites **premature completion**: ending the step
  before it is genuinely done, attention slipping to *being done*. The visible
  steps still ahead — the **post-completion steps** — supply the pull; the bound's
  clarity is the resistance. Defend in order: **sharpen the bound first** (local
  and cheap); only if it is irreducibly fuzzy *and* you observe the rush, hide the
  later steps by splitting the sequence — and hiding only works across a real
  context boundary (a hand-off or a subagent dispatch; an inline call leaves the
  later steps in context and clears nothing).
- **Demand** — how much it requires. "Every modified model accounted for" forces
  thorough work where "produce a change list" does not. Demand drives **legwork** —
  the digging the agent does within the work, latent in the wording rather than
  written as its own step — and it is not step-bound: "every rule applied" binds a
  body of flat reference just as "every step done" binds a sequence, which is how
  an all-reference document still carries an exhaustiveness bar.

The strongest bounds are both checkable and exhaustive.

## When to split

Splitting one document into two spends one of the two loads, so split only when
the cut earns it:

- **By sequence** — split a run of steps where the post-completion steps tempt the
  agent to rush the one in front of it. Keeping them out of view drives more
  legwork on the current task. Beware the reverse: merging sequences exposes each
  step's later steps to what follows, inviting premature completion.
- **By invocation** — skill-specific; the decision rule is in `SKILL.md`. Split off
  a model-invoked skill when you have a distinct leading word that should trigger
  it on its own — a trigger word you actually use in your prompts — or another
  skill must reach it. You pay context load for the new always-loaded description,
  so that independent reach has to be worth it.

**Routers.** When user-invoked skills multiply past what you can remember, that
piled-up cognitive load is cured by a **router skill**: one user-invoked skill
naming the others and when to reach for each, so the human has one skill to
remember instead of many. It can only hint, never fire them — with no description,
nothing but the human can reach them.

Shared reference that two user-invoked skills both need can live in neither, for
the same reason. Push it to a plain file outside the skill system, or into a
model-invoked reference skill that both can reach.

## Leading words

A **leading word** is a compact concept already living in the model's pretraining
that the agent thinks with while running the document (*lesson*, *fog of war*,
*tracer bullets*). Repeated as a token, never as a sentence, it accumulates a
distributed definition and anchors a whole region of behaviour in the fewest
tokens, by recruiting priors the model already holds. Coining your own works if
you define it clearly, but a made-up word recruits no priors — you pay in
definition tokens what a pretrained word gives free; reach for an existing word
first.

It anchors twice. In the body, *execution*: the agent reaches for the same
behaviour every time the word appears, and inside flat reference it focuses
attention on a class of thing to look for. In a pointer, *invocation*: when the
same word lives in your prompts, your docs, and your codebase, the agent links
that shared language to the material and reaches it more reliably.

Hunt for opportunities to refactor with leading words. A triad spelled out at
three sites, a pointer spending a sentence to gesture at one idea — each is a
passage begging to collapse into a single token:

- "fast, deterministic, low-overhead" → *tight* (a *tight* loop).
- "a loop you believe in" → *red* — a fuzzy gate becomes a binary observable state
  (the loop goes *red* on the bug, or it doesn't).

You win twice: fewer tokens, and a sharper hook for the agent to hang its thinking
on. Assume every document is carrying restatements that leading words retire — go
find them.

**Negation** is the failure mode beside this lever: steering by prohibition drags
the forbidden behaviour into context and makes it *more* available, not less.
*Don't think of an elephant*, and the elephant is all there is; the negation is a
weak modifier the strongly-activated concept overruns, so the ban half-reads as an
instruction to do the thing. Prompt the **positive** — state the target behaviour
("write one-line comments") so the banned one is never spoken. A prohibition earns
its place only as a hard guardrail you cannot phrase positively; even then, pair it
with the positive target so attention lands on what to do.

## Pruning

- Keep each meaning in a **single source of truth**: one authoritative place, so
  changing the behaviour is a one-place edit. **Duplication** — the same meaning in
  more than one place — costs maintenance and tokens, and inflates a meaning's
  prominence on the ladder past its real rank. (The accidental inverse of a leading
  word, which repeats a token on purpose, never the meaning.)
- The **environment** is a source of truth too — `package.json` scripts, config
  files, the directory layout, `--help` output — and a document that restates it is
  a **cache**: a copy of a lookup, earning its load only when the lookup is
  expensive. Cache what the agent cannot find by looking: the unwritten convention,
  the reason behind a choice, the gotcha no config confesses. Leave the one-file,
  one-command lookups to the environment, where they cannot go stale.
- Check every line for **relevance**: does it still bear on what the document
  does? A line loses relevance by never bearing on the task (mere exposition, or a
  branch that should be disclosed) or by going stale as the behaviour or world it
  describes changes. Shorter documents are easier to keep relevant. Without a
  pruning discipline the default fate is **sediment**: stale layers that settle
  because adding feels safe and removing feels risky, until you must core down
  through them to find what is still live.
- Hunt **no-ops** sentence by sentence: an instruction the model already obeys by
  default pays load to say nothing. The test — does it change behaviour versus the
  default? — is model-relative, not reader-relative: two people disagreeing about a
  no-op disagree about the default, and settle it by running the document, not by
  debate. When a sentence fails, delete the whole sentence rather than trim words
  from it. The test also grades leading words: a word too weak to beat the default
  (*be thorough* when the agent is already thorough-ish) is a no-op, and the fix is
  a stronger word (*relentless*), not a different technique.

### Pruning is not disclosure

Both remove lines from the file in front of you, and confusing them is how a
document quietly stops teaching what it used to.

- **Disclosure** moves material down the ladder. Nothing is lost — the content
  travels verbatim into a pointed-to file. This is the answer when a document is
  over its budget.
- **Pruning** deletes. It is the answer when a line fails on its own merits: a
  no-op, a duplicate, a cache of a cheap lookup, a line no longer relevant.

Size pressure is a reason to disclose, never a licence to prune. A cut made to fit
a budget, on a line that would have survived the relevance test, is a silent
capability regression.
