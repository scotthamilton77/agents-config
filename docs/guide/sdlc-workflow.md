# The SDLC Workflow

This is the opinionated loop the discipline layer runs. The shape is always the
same: **frontload human judgment, let the agent execute, gate every completion
claim with evidence.** You spend your time upstream (deciding *what* and *why*)
and at thin verification points; the agent does the implementation and
machine-checkable QA in between.

> **Read the status column before you rely on a phase.** The harness is being
> rebuilt (see the [guide index](./index.md)). The loop below is the intent and
> the destination, and the front half of it works today. The back half — the
> completion gate, PR grooming, merge enforcement — had its implementation
> retired and does not yet have a replacement. Each phase says which it is.

| Phase | What backs it today |
|-------|---------------------|
| 0. Always-on contract | **Ships** — installed as your instruction file |
| 1. Capture | Tooling only; no rule enforces the habit |
| 2. Brainstorm | **Ships** — `grilling`, `grill-with-docs` |
| 3. Plan | **Ships** — `to-spec`, `ac-attack` |
| 4. Implement | **Nothing ships** |
| 5. Review and completion gate | **Partly** — `review-panel`, `review-verdict`; no gate driving them |
| 6. Deliver | **Nothing ships** for the PR loop; `post-merge-cleanup` covers the tail |
| 7. Merge | Contract only — the hard line, with nothing enforcing it |
| 8. Persist | **Partly** — `handoff` |

You don't invoke these by hand step by step — the rules and skills fire
automatically as the work moves. What follows is what's happening, and where you
stay in control.

## 0. The always-on contract — ships

Two things run underneath every phase, and unlike most of what follows they are
installed and loaded on every session:

- **The laws** (L0–L3): protect the codebase and safety first, obey
  instructions, keep things clear — in that precedence. The agent will push back
  on a request that would cause architectural drift or a bug rather than just
  comply.
- **The decision matrix**: for any unknown, the agent classifies before acting —
  *verify* a fact from the code, *decide* an in-scope choice itself, or
  *escalate* only genuinely balanced architectural trade-offs and conflicting
  directions. This is why a well-configured agent asks you fewer, better
  questions: it decides what it can and escalates what it shouldn't.

Alongside them sit the hard lines (no force pushes or blind `git add -A`;
creating a PR is not authorization to merge) and a delegation rule that makes
handing work to a subagent standing policy rather than something to ask about.

## 1. Capture — tooling, not enforcement

Durable work belongs in a tracker that outlives the session. This repo uses
[beads](https://github.com/steveyegge/beads) through the `work` CLI, which the
installer puts on your PATH:

```bash
work create --raw --title "..." --description "..." --type feature --priority P2
```

Tracked work carries dependencies and survives context compaction, so it
resurfaces intact across sessions and agent handoffs. In-session step tracking is
separate (the agent's own task list) — the tracker is the cross-session memory of
*what needs doing*.

What is missing is the discipline: no installed rule tells your assistant to file
an item before writing code, claim it, or close it. Ask for it and it happens;
expect it automatically and it will not.

## 2. Brainstorm — the "no, not ready" gate — ships

Before any creative work, the **`grilling`** skill interviews you one question
at a time to explore intent, requirements, and design. This is the most
important human touchpoint: it's where you pin down what you actually want.
The discipline here is that under-specified work is **bounced back before
implementation** — the skill's exit condition is an enumerated set of acceptance
criteria, not a shared feeling that you have discussed it enough.

Use **`grill-with-docs`** to stress-test a plan against your project's domain
model and update `CONTEXT.md`/ADRs as decisions crystallize.

## 3. Plan — ships

Once intent is clear, **`to-spec`** turns the conversation into a concrete,
dated spec — enumerated acceptance criteria and an ordered, criteria-citing
slice list — before any code. It synthesizes rather than interviews, which is
why it follows the grilling rather than replacing it.

Then attack what you wrote. **`ac-attack`** (Claude Code only) runs a panel of
adversarial lenses over the criteria — behaviours that satisfy every stated
criterion and are still wrong, the edge-case taxonomy, obligations no criterion
covers — and every proposal it returns gets adjudicated into the criteria or
rejected on the record. Running it before implementation is the point: once code
exists, review can only check coverage of the cases you already named.

## 4. Implement — nothing ships

This is the largest gap. The test-first and planning skills that governed
implementation — red/green/refactor, unit-test quality, the tautology filter,
the coverage floor — were all retired, and the scaffold-based approach meant to
replace them is not built. There is currently no installed asset that shapes how
your assistant writes code.

The always-on contract still applies (the laws, the decision matrix, the hard
line against committing to the default branch), and it is worth being explicit
with your assistant about testing expectations in the meantime, because nothing
in the configuration is being explicit on your behalf.

## 5. Review and the completion gate — partly ships

Nothing should be "done" on the agent's say-so. Two pieces of the machinery that
enforces that are installed:

- **`review-panel`** (Claude Code only) fans one review round out over a change
  as a panel of single-lens reviewers rather than one reviewer judging
  everything at once. It classifies the target — typed code, spec, or prose —
  and runs the lenses that class declares. It handles re-review after a claimed
  fix, carrying earlier dispositions forward so settled findings are not
  re-litigated.
- **`review-verdict`** defines the typed JSON envelope a round emits, keyed to
  the commit it reviewed: what was looked at, through which lenses, and what is
  still outstanding. It exists so a review result is auditable rather than a
  claim in a chat log.

What does **not** exist is the gate around them. There is no tier router
computing SKIP/SERIAL/HEAVY, no `verify-checklist` step, no evidence
requirement that fires by itself. Review happens when you or your agent invoke
it, and a change can reach a PR without any review round having run. Closing
that gap is one of the open pieces of the rebuild.

## 6. Deliver — nothing ships for the PR loop

Delivery in the intended loop runs: isolate the work in a worktree, commit and
push, open a PR, then poll automated review, classify each comment, fix, push,
reply and resolve. **None of the skills that did that are installed.** The
`prgroom` CLI that grooms a PR deterministically is on your PATH, but the skills
that drove it were retired, so driving it is manual.

Creating a PR is *not* authorization to merge — that one survives, in the
always-on hard lines.

The tail of delivery does ship. Once a PR is merged, **`post-merge-cleanup`**
tells your assistant that `gitclean` exists and is the right way to decide which
branches and worktrees the merge made disposable — a question agents reliably
reason out by hand and reliably fail to reach for a tool for. The
**`/clean-up-git`** slash command drives the same tool interactively: one dated
table pairing each worktree to its branch, every unproven candidate already
investigated, and a stop for your call before anything is deleted.

## 7. Merge — contract only

The finish line is governed by your project's merge policy — in principle. In
practice nothing reads it (see
[Configuration](./configuration.md#3-project-configtoml--mostly-not-wired-up-yet)),
and the `merge-guard` skill that enforced it has been retired.

What remains is the contract itself, in the always-on hard lines: **creating a
PR is not authorization to merge**, and absent an explicit instruction or a
configured rule-based policy, the agent does not merge. When in doubt, treat the
PR as not authorized. This is a deliberate risk-asymmetric default: the cost of a
wrong merge outweighs the cost of waiting. It now rests on the agent honouring a
line in its instructions rather than on a mechanism, which is a weaker guarantee
— worth knowing before you leave a run unattended.

## 8. Persist — partly ships

Work isn't done until context is preserved:

- **`handoff`** compacts the session into a handoff document — the conversation
  plus a working-tree snapshot — so a fresh agent can resume in a new session.
  This ships, and is the main thing standing between an overnight run and a lost
  thread.
- **Memories** — your assistant may have its own memory mechanism; this
  configuration no longer ships a routing rule for it.
- **Retrospectives and self-improvement** — the skills that turned a correction
  into a written prevention rule, and that ran an end-of-session retrospective,
  were retired with no replacement yet.

## Delegation, throughout

Cutting across every phase: delegation is standing policy, not something to ask
permission for. **`choosing-a-delegate`** decides who should look at something
when it must not be whoever produced it, **`instructing-subagents`** governs how
to write the brief, and **`delegating-to-codex`** and
**`openrouter-claude-subagent`** route a run to a non-Anthropic model when
vendor-diverse eyes are the point. All are Claude Code only.

## The payoff

Each pass tightens the loop: judgment stays upstream, execution and verification
run in the background (including overnight), and every "done" is backed by
evidence you can inspect. That is the destination. Today the front half of the
loop — pinning intent, writing a spec, attacking its criteria — is real and
worth using; the back half is being rebuilt, and until it lands the evidence
discipline is yours to enforce rather than the harness's.
