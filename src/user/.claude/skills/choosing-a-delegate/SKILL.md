---
name: choosing-a-delegate
description: Use when handing work to anyone but yourself — a second opinion, an independent review, an adversarial critique, or any task you are about to delegate. Apply whenever you think "find someone to look at this", "get another perspective", "poke holes in it", or "have someone check this before I commit", and whenever a judgement must be independent of whoever produced the work. Not for writing the brief once the delegate is known, and not for vendor CLI setup.
admission:
  provides: The decision of who does delegated work, and standing permission to reach another vendor for it unasked. An orchestrator that is not told this treats a foreign-model dispatch as something the user must request by name, and answers "get me a second opinion" with a larger model from the same vendor as the work under review.
  cost: One description line always-on; the body only when a dispatch is actually in hand. The vendor pointers need revisiting whenever a delegation route is added or retired.
  remove_when: Sessions that were never given this reach cross-vendor on their own judgement when independence is what the task needs.
---

<!--
Source: authored 2026-08-02.
-->

# Choosing a Delegate

Independence comes from a different **vendor**, not a bigger model from the same one.
Two models trained by one lab share the blind spot that let the defect through in the
first place; the second pass agrees with the first and returns clean. A stronger
same-vendor model buys depth, which is a different thing and not a substitute.

## Reaching another vendor is your call

**The user's silence about vendors is not a prohibition.** "Find someone to poke holes
in this" is a request for independence, not a request for a Claude subagent — and
waiting to be told "use codex" before considering a foreign model is not caution, it is
a wrong answer delivered politely.

You do not need permission to *choose the delegate*. You need permission for what the
delegate may **do** — writing files, reaching the network, spending real money against
the user's account. Those are the gates. Who reads the code is your judgement.

## Does this need another vendor?

| The work | Delegate |
|---|---|
| Judging work a model produced — review, critique, "poke holes", adversarial pass | **Another vendor.** The thing being tested is whether a *different* set of blind spots sees it. |
| A second attempt at something that failed once — diagnosis, a stuck bug, a rescue | **Another vendor.** A retry on the same lineage tends to repeat the reasoning that failed. |
| Independent verification of a claim before you act on it | **Another vendor**, when the claim came from a model. |
| Producing work — implementing, refactoring, writing, researching | Native. Vendor diversity buys nothing here; pick on capability and cost. |
| Anything needing the harness's own tools — worktree isolation, file edits under your permission mode | Native. Foreign routes have their own sandboxes and cannot borrow yours. |

When the answer is native, the Agent tool is the substrate and `model` is the whole
capability lever on it — the Agent tool accepts no effort parameter, so do not write a
dispatch or a brief that assumes one.

## Where to go

Each route carries its own current model table. **Open it and read the table; never
infer a model identifier from a skill name, a file name, or memory** — names outlive the
model generations they were named for, and a plausible-looking identifier that no longer
exists fails at dispatch or silently routes somewhere you did not intend.

| Route | Reach it through |
|---|---|
| OpenAI models, via that vendor's own runtime | The Codex delegation skill — **present only when the Codex plugin is installed**. Check your skill list; if it is absent, that route does not exist in this session. |
| Everything else — other vendors, cheaper tiers, a specific named model | The OpenRouter subagent skill, which runs this same harness against another vendor's weights. |
| A stronger or higher-effort perspective on Claude | The Agent tool. Legitimate when your own judgement is strained, but it is depth, not independence. |

If the route you want is absent, say so and offer the one that is present. Do not
substitute a same-vendor delegate and describe it as a second opinion.

## Two things that bite

**A Codex rescue dispatch defaults to write-capable.** Its sandbox permits edits unless
the request explicitly asks for review, diagnosis, or research without changes. When you
want a critique and not a patch, say so in the request text — the default is not the one
you want for a second opinion.

**A review round's transports are already decided.** When a review contract declares a
transport per lens, that declaration is the vendor-diversity plan for the round. This
skill governs dispatch where nothing has declared one; it does not override a round that
has.

## Then write the brief

Choosing the delegate is not the same as briefing it, and a foreign model inherits even
less of your intent than a native subagent does.

REQUIRED SUB-SKILL: Use `instructing-subagents` once you know who is doing the work.
