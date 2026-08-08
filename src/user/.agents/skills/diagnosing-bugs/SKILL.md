---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
admission:
  prevents: An agent reading code to build a theory before it holds a command that goes red on the reported bug, then shipping a fix nothing can falsify — and, when a fix fails, stacking further attempts on a hypothesis space the evidence has already exhausted.
  cost: One model-invoked catalog line and a body paid on invocation, plus a hard stop before hypothesising that spends a loop-building pass even on bugs whose cause turns out to be obvious.
  remove_when: The executor refuses a fix unaccompanied by a named command observed red before the change and green after, so the gate no longer has to be read to be applied.
---

<!--
Amalgam of two upstreams, one Source/Upstream pair each. Keep every key at the
start of its own line: the installer recognises a provenance header by matching
`Source:`/`Upstream:` there, so folding these into bullets or prose would stop
this block being stripped and ship these paths into every downstream install.

  Source: skills/engineering/diagnosing-bugs/
  Upstream: https://github.com/mattpocock/skills @ bda79a3c3ca23d19d9ca483808580b5b4cc3d8e2
  (the six-phase spine, the Phase 1 completion criterion, and the loop-construction
  reference; verified byte-identical to the copy taken on 2026-08-07)

  Source: skills/systematic-debugging/
  Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
  (two patterns only: multi-component boundary instrumentation, and the
  three-failed-fixes architectural escalation)
Last sync: 2026-08-07
Drift policy: selective-amalgamation. This copy is authoritative and diverges
from both upstreams by construction, so a wholesale resync would revert the
graft. Pocock supplies the spine; the two obra patterns are lifted into Phase 3
and Phase 5; the parallel-evidence thread structure of Phase 3 is in-house and
appears in neither upstream. Consult either upstream for pattern lifts only. To
inspect drift, clone each at the SHA above and diff by hand.
-->

# Diagnosing Bugs

A discipline for hard bugs. Skip phases only when explicitly justified. Read `CONTEXT.md` if the project has one, and check ADRs in the area you're touching.

## Redact

This skill has you show commands, outputs and captured artifacts. **Redact every secret first** — write `<REDACTED>` in its place. Build loops against env vars so credentials never enter what you show, and quote only signal-carrying lines out of captured artifacts, which carry auth headers. If the redacted output is not enough, say so and ask.

## Phase 1 — Build a feedback loop

**This is the skill**; everything else is mechanical. A **tight** signal that goes red on _this_ bug finds the cause for you — bisection, hypothesis-testing and instrumentation all just consume it. Without one, staring at code will not save you.

Spend disproportionate effort here. **Be aggressive. Be creative. Refuse to give up.** `references/feedback-loops.md` ranks ten ways to construct a loop, in the order to try them, plus tightening, non-determinism, and what to ask for when no loop is possible.

### Completion criterion — a tight loop that goes red

Phase 1 is done when you can name **one command** — a script path, a test invocation, a curl — that you have **already run at least once** (show it and its output, redacted), and that is:

- [ ] **Red-capable** — it drives the actual bug code path and asserts the **user's exact symptom**, so it goes red on this bug and green once fixed. Not "runs without erroring": it must catch _this specific bug_.
- [ ] **Deterministic** — same verdict every run (flaky bugs: a pinned, high reproduction rate, per the reference).
- [ ] **Fast** — seconds, not minutes.
- [ ] **Agent-runnable** — you can run it unattended; a human enters the loop only through the reference's prompt-and-capture script.

If you catch yourself reading code to build a theory before this command exists, **stop — jumping straight to a hypothesis is the exact failure this skill prevents.** No red-capable command, no Phase 2.

**If you genuinely cannot build one**, say so, list what you tried, and ask for what the reference says to ask for. Never hypothesise without a loop.

## Phase 2 — Reproduce + minimise

Run the loop. Watch it go red.

- [ ] It produces the failure the **user** described, not a different one nearby. Wrong bug, wrong fix.
- [ ] It reproduces across runs (non-deterministic bugs: at a rate high enough to debug against).
- [ ] You captured the exact symptom — error message, wrong output, slow timing — so later phases can check the fix addresses it.

Then shrink the repro to the **smallest scenario that still goes red**, cutting inputs, callers, config, data and steps **one at a time** and re-running after each cut. It shrinks Phase 3's hypothesis space and becomes Phase 5's regression test. Done when **every remaining element is load-bearing** — removing any one turns the loop green. Do not proceed until both are done.

## Phase 3 — Gather evidence in parallel, then hypothesise

**No fix without parallel evidence.** One line of investigation anchors on the first plausible idea; three angles gathered independently catch what one misses.

- **Thread 1 — Git archaeology.** The last ~20 commits touching the affected files: what changed, who changed it, which could have introduced this. The bug arrived with a change, and finding it often reveals the cause outright.
- **Thread 2 — Reproduction.** Already discharged: the red loop from Phases 1–2 *is* this evidence, and the captured symptom is its finding.
- **Thread 3 — Data-flow trace.** Entry point to failure point: what values enter, how they transform, where they could become invalid. If similar working code exists, list every difference from it, however small — do not assume any cannot matter.

Run Threads 1 and 3 independently — in parallel if your harness can, sequentially if not. What matters is that neither steers the other, and that **both return before you rank anything**.

**Multi-layer bugs — instrument the boundaries first.** When the bug spans components (client → gateway → worker), reading source is not enough: extend Thread 3 with the boundary logging in `references/instrumentation.md` and run it once. This is evidence gathering, not Phase 4's prediction-testing — it establishes *which layer* fails before you hypothesise about *why*, so you do not fix the first suspicious component when the break is one boundary earlier.

### Then hypothesise

Generate **3–5 ranked hypotheses** before testing any. Each must be **falsifiable**: "if <X> is the cause, then <changing Y> makes the bug disappear." No prediction means it is a vibe — discard or sharpen it.

An inconclusive thread is a finding, not a gap to fill with speculation; "no relevant changes in the last 20 commits" is an answer. If the threads diverge and no cause emerges, document what each ruled out and escalate.

**Show the ranked list to the user before testing.** They often re-rank it instantly ("we just deployed a change to #3"). Don't block — proceed with your ranking if the user is AFK.

## Phase 4 — Instrument

Each probe must map to a specific prediction from Phase 3. **Change one variable at a time.** Prefer a debugger or REPL over logs; place logs only where they distinguish hypotheses; never "log everything and grep".

**Tag every debug log** with a unique prefix, e.g. `[DEBUG-a4f2]`, so Phase 6's cleanup is one grep: untagged logs survive, tagged logs die.

**Perf branch.** For a performance regression logs are the wrong instrument — measure a baseline, then bisect against it. See `references/instrumentation.md`.

## Phase 5 — Fix + regression test

Write the regression test **before the fix** — but only if a **correct seam** exists: one where the test exercises the real bug pattern as it occurs at the call site. Too shallow a seam — a unit test that cannot replicate the chain that triggered the bug — gives false confidence.

**If no correct seam exists, that itself is the finding** — the architecture is preventing the bug from being locked down. Note it and carry it to Phase 6.

With a correct seam:

1. Turn the minimised repro into a failing test at that seam, and watch it fail.
2. Apply the fix — one focused change at the root cause, nothing bundled in.
3. Watch the test pass, then run the full suite and confirm no regressions.
4. Re-run the Phase 1 loop against the original, un-minimised scenario.

### If the fix doesn't work

Count the fixes attempted on this bug.

- **Fewer than three:** return to Phase 3. The failed fix is new evidence — re-correlate the threads against it and form a new hypothesis. Do **not** stack a second fix on the first.
- **Three or more:** stop and question the architecture. Three failed fixes is an **architectural** signal, not a hypothesis signal — the abstraction is wrong, not the theory. The tells: each fix surfaces shared state or coupling somewhere *different*; each needs "massive refactoring" to land; each creates new symptoms elsewhere; you think "one more attempt should do it".

Escalate before attempt #4 with the failed attempts, the pattern, and the architectural question they raise.

## Phase 6 — Cleanup + post-mortem

Before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop)
- [ ] Regression test passes, or the absent seam is documented
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix)
- [ ] Throwaway prototypes deleted, or moved somewhere marked as debug
- [ ] The correct hypothesis is stated in the commit or PR message, so the next debugger learns

**Then ask what would have prevented this bug.** If the answer is architectural — no good test seam, tangled callers, hidden coupling — raise it as its own work item, **after** the fix is in: you know more now than when you started.
