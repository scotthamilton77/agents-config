# The SDLC Workflow

This is the opinionated loop the discipline layer runs. The shape is always the
same: **frontload human judgment, let the agent execute, gate every completion
claim with evidence.** You spend your time upstream (deciding *what* and *why*)
and at thin verification points; the agent does the implementation and
machine-checkable QA in between.

```
capture → brainstorm → plan → implement (TDD) → completion gate → deliver → merge → persist
  bd     brainstorming  writing-plans  TDD      SKIP/SERIAL/HEAVY  worktree→PR  merge-guard  memory
```

You don't invoke these by hand step by step — the rules and skills fire
automatically as the work moves. What follows is what's happening, and where you
stay in control.

## 0. The always-on contract

Two things run underneath every phase:

- **The laws** (L0–L3): protect the codebase and safety first, obey
  instructions, keep things clear — in that precedence. The agent will push back
  on a request that would cause architectural drift or a bug rather than just
  comply.
- **The decision matrix**: for any unknown, the agent classifies before acting —
  *verify* a fact from the code, *decide* an in-scope choice itself, or
  *escalate* only genuinely balanced architectural trade-offs and conflicting
  directions. This is why a well-configured agent asks you fewer, better
  questions: it decides what it can and escalates what it shouldn't.

## 1. Capture

Durable work is a **bead**. Before code is written for something, it gets filed:

```bash
bd create --title="..." --description="..." --type=feature --priority=P2
```

Beads carry dependencies and survive context compaction, so work resurfaces
intact across sessions and agent handoffs. In-session step tracking is separate
(the agent's own task list) — beads are the cross-session memory of *what needs
doing*.

## 2. Brainstorm — the "no, not ready" gate

Before any creative work, the **`brainstorming`** skill explores intent,
requirements, and design. This is the most important human touchpoint: it's
where you pin down what you actually want. The discipline here is that
under-specified work is **bounced back before implementation** — the agent is
built to say "not ready, here's what's missing" rather than burn an autonomous
run on a guess.

Use **`grill-with-docs`** to stress-test a plan against your project's domain
model and update `CONTEXT.md`/ADRs as decisions crystallize.

## 3. Plan

Once intent is clear, **`writing-plans`** turns it into a concrete multi-step
plan before any code. For multi-step or architectural work the agent plans
first and validates the approach with you. The **tracer-bullet** habit applies:
implement one tiny end-to-end slice through all layers first, confirm the
architecture, then expand.

## 4. Implement — test first

Implementation runs through **`test-driven-development`**: red → green → refactor.
**`writing-unit-tests`** governs test quality — behavior over implementation, a
tautology filter (don't test the language or stdlib), and explicit criteria for
when *not* to test. Coverage has a floor (default 80% line / 70% branch on
changed code) but the floor is a minimum, never an excuse for anti-pattern
tests.

Non-trivial work is isolated in a worktree or branch — never committed straight
to trunk.

## 5. The completion gate — evidence before "done"

Nothing is "done" on the agent's say-so. The **completion gate** sits between "I
think this works" and "this is done," and it **scales to the size of the
change** — routed by the `gate-triage` skill to one of three tiers:

| Tier | When | What runs |
|------|------|-----------|
| **SKIP** | trivially small change (a size bound, not a file-type bound) | mechanical evidence only (step 5) |
| **SERIAL** | the default | `quality-reviewer` → address findings → `simplify` → address findings → `verify-checklist` |
| **HEAVY** | large, critical, or risk-class (security, concurrency, public API, migration, cross-subsystem) | a deeper multi-agent adversarial pass, then evidence |

The final step — **`verify-checklist`** — is non-substitutable at every tier:
tests pass, build succeeds, static analysis clean, **output as proof**. A risk
class (auth, data migration, concurrency, …) escalates the tier automatically;
it never lowers it.

For high-stakes changes, an optional adversarial cross-model pass (RALF or a
Codex review) adds an independent set of eyes — different models have different
blind spots.

## 6. Deliver

Once the gate passes, delivery is automatic up to (but not including) merge:

1. **`using-git-worktrees`** — ensure the work is isolated.
2. **`finishing-a-development-branch`** — commit, branch, push.
3. **Open a PR** with a summary.
4. **`monitor-pr`** (driving the `prgroom` CLI) or **`wait-for-pr-comments`** —
   poll automated review (e.g. Copilot), classify each comment FIX / SKIP /
   ESCALATE, fix the FIX items via per-comment subagents, push, then reply to and
   resolve every thread.

Creating a PR is *not* authorization to merge.

## 7. Merge

The finish line is governed by your `[merge-policy]` (see
[Configuration](./configuration.md#review-and-merge-policy)),
enforced by the **`merge-guard`** skill:

- **`never`** — hands off to you.
- **`explicit`** (default) — waits for your direct "merge it" / "ship it".
- **`rule-based`** — auto-merges only when the named rule *and* the live
  eligibility check both pass.

When in doubt, `merge-guard` treats the PR as *not* authorized. This is a
deliberate risk-asymmetric default: the cost of a wrong merge outweighs the cost
of waiting.

## 8. Persist

Work isn't done until context is preserved:

- **Memories** — non-obvious decisions and corrections are written to durable
  memory (routed to the right scope: repo-specific → the repo's `AGENTS.md`;
  general → user memory).
- **`self-improving-agent`** — every correction becomes a written prevention
  rule, not a vague "I'll do better."
- **`retrospect`** — at session end, reflect on what slowed things down and what
  to change about the setup.
- **Beads** — discovered follow-up work is filed (as a child or a
  provenance-linked orphan) so nothing falls through.

## The payoff

Each pass tightens the loop: judgment stays upstream, execution and verification
run in the background (including overnight), and every "done" is backed by
evidence you can inspect. That's the whole game — see
[Reference](./reference.md) for the piece-by-piece cheat sheet.
