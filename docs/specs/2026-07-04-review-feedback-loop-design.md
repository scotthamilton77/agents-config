# Review Feedback Loop — Defect Router & Trust Calibration — Design Spec

**Date:** 2026-07-04
**Status:** Draft — for discussion (no implementation committed)
**Scope:** Close the downstream review bottleneck by converting human review from
open-ended manual QA into a measured feedback loop that (a) routes every
human-caught defect to a permanent guard, (b) drives the human-visible defect
rate down over time, and (c) provides a principled, per-category off-ramp from
full review to statistical sampling. Ties the downstream review bottleneck to
the upstream spec-readiness gate.
**Relation to milestones:** Serves **M3** (worker fleet → PR autonomy) and
**M4** (overnight autonomy); spec-ambiguity routing feeds **M2**
(brainstorm-readiness gate).
**Relation to the five load-bearing commitments:** This spec adds the *router*
that connects human review to commitments **#2** (say "not ready"), **#3**
(adversarial cross-model review), and **#4** (mechanical evidence). Those
commitments already define the *destinations*; what is missing is the reflex
that forces every human catch into one of them instead of being silently
patched.

---

## 1. Problem

As the human is taken out of the implementation loop, the binding constraint
moves to review. The operator reports the load-bearing symptom directly: *"I
can't NOT review as long as I keep catching stuff."* Review today is
open-ended, uncalibrated, and unbounded — and it does not compound.

Three defects in the current arrangement:

1. **No ratchet.** Every defect the human catches is *fixed*, but nothing about
   catching it changes what reaches the human next batch. The full attention
   cost is paid every time, indefinitely. The defect *rate* never falls because
   nothing converts a catch into a permanent guard.
2. **No measurement.** There is no defect taxonomy, no per-batch rate, and no
   trend. The question "should I still be reviewing category X?" is therefore
   unanswerable, so the human rationally defaults to reviewing everything.
3. **No attention model.** Human catch-rate degrades with volume of code
   reviewed, amplified by the quality (or lack) of the review UX. The current
   flow presents raw diffs at uniform priority, maximizing the volume that
   reaches the human's eyes and minimizing signal density.

The missing feedback edge is **not** reviewer→code. It is
**caught-defect → permanent guard**. That edge is the only mechanism that
shrinks volume-reaching-the-human over time, and volume is the term the human's
attention constraint is most sensitive to.

## 2. Design stance (and the counterargument to the naive goal)

**Efficiency of review is a lagging output, not the thing to attack directly.**
The naive goal — "make review faster / review less" — trades a *known* defect
rate for an *unknown* escape rate by fiat. That is strictly worse. The human's
continued catching is the correct signal that trust is not yet warranted;
you cannot *decide* to trust, you can only earn calibration with data.

Consequently the exit from review is a measurement problem, not a discipline
problem, and the sequencing is forced:

> **instrument → route every catch → risk-triage what reaches the human →
> sample-not-zero as the steady state.**

**The steady state is never zero review.** The human catch is the ground-truth
eval for the AI reviewer. Going to zero destroys the only signal that tells us
whether the adversarial reviewer is still good or has silently drifted.
The asymptote is *statistical sampling*, not absence.

## 3. Instrumentation (prerequisite — do this first)

Before optimizing review, measure it. On every human catch, log a structured
record:

| Field | Values |
|---|---|
| `category` | `mechanical` / `spec-ambiguity` / `model-judgment` / `novel` (see §4) |
| `severity` | `blocker` / `major` / `minor` |
| `caught_by` | `human` / `adversarial-review` / `gate` (for escape analysis) |
| `recurred` | pointer to prior record of same class, if any |
| `disposition` | guard written / routed upstream / reviewer-prompt updated / fixed-only |

Cost is a few seconds per catch. Output is the curve that makes "should I still
review category X?" answerable: a per-category defect rate and its trend, plus
an **escape rate** (defects that reached the human that a gate or the
adversarial reviewer *should* have caught). Without this, everything downstream
is guesswork.

*Confidence: high. This is measurement theory — an escape rate you do not count
cannot be managed.*

## 4. The defect router (the core mechanism)

**Rule: no human-caught defect may be "just fixed."** Each catch must be
classified and routed to an artifact that prevents its *class* from reaching the
human unreviewed again. Four destinations — which are exactly the downstream
homes the architecture already names:

1. **`mechanical` — mechanically checkable** → becomes a lint rule, test, or
   completion-gate check (**commitment #4**). Once written, that class never
   reaches the human again unless the gate is green and wrong — itself a rarer,
   catchable event.
2. **`spec-ambiguity` — reasonable-but-wrong because the spec underspecified
   it** → routes *upstream* into the brainstorm-readiness / spec gate
   (**commitments #1, #2**, **M2**). A large fraction of what is caught
   downstream is an upstream defect wearing a code costume; this is the explicit
   link between the two bottlenecks.
3. **`model-judgment` — judgment error, not mechanizable** → becomes a line in
   the adversarial reviewer's checklist/prompt (**commitment #3**). The cheap
   reviewer is taught to catch what the human just caught.
4. **`novel` — genuinely one-off** → fix, no guard. This bucket must stay
   non-empty (see §7 goodhart) and is what the persistent sampling in §6 exists
   to surface.

The discipline is the *forced classification*. The router is the feedback cycle
that was missing.

*Confidence: moderate that this bends the rate down materially — it depends on
the defect mix. If most catches are `model-judgment` errors that resist both
mechanization and reviewer-prompting, the ratchet slips and a different answer
is needed. The §3 histogram is the falsification test: it tells us whether this
approach applies to* these *defects before we over-invest.*

### 4.1 Guard-cost threshold

Writing a guard per catch is not free. Guard when the class **recurs** or is
**high-severity**; otherwise fix-and-log. The log's `recurred` field is what
tells us when a supposed "one-off" has quietly become a recurring class that now
earns a guard. This keeps the ratchet Pareto-efficient rather than
bureaucratic.

## 5. Attention-protecting review UX

Two levers on the constraint `attention ∝ 1/volume × UX`: reduce the volume that
reaches the human, and raise the signal density / UX of the remainder.

- **Reviewer-first, not code-first.** The human reads the adversarial reviewer's
  findings *as annotations on the diff* and confirms/rejects each, rather than
  cold-reading syntax. Confirming a flagged concern is a far cheaper cognitive
  act than discovering it. The confirm/reject stream is *free labeled eval data*
  for the reviewer (feeds §6).
- **Risk-rank, then review in priority order and stop at a threshold.** The
  reviewer emits a per-change risk score; the human reviews highest-risk first
  and stops when the marginal catch rate drops below a set line. This
  operationalizes the attention curve instead of fighting it.
- **Narrative diffs.** The agent must explain what changed and why, mapped to the
  acceptance criteria, so the human checks intent-vs-implementation rather than
  reconstructing intent from code.
- **Small, semantically chunked PRs.** Volume-per-unit is the term attention is
  most sensitive to.

## 6. Calibration off-ramp (per category)

Define the exit quantitatively and per-category, not as an all-or-nothing "do I
trust the model" decision:

> When gates + adversarial review clear **N consecutive batches with zero
> human-caught escapes in category C**, downgrade C to **spot-sampling**.
> Any subsequent escape in C re-escalates C to full review and the counter
> resets.

This is principled, reversible, and per-class. The value of `N` and the sampling
rate are tuned from the §3 data; the numbers below are illustrative only.

*Confidence on specific thresholds: low — placeholders pending real defect-rate
data. Confidence on the shape (per-category, escape-triggered re-escalation):
high.*

**Why sampling never reaches zero:** the human catch is the reviewer's
ground-truth eval. Permanent risk-weighted + random sampling keeps the
escape-rate estimate alive and detects reviewer drift. Steady state is a small
asymptote, not absence.

## 7. Failure modes to design against

- **Goodhart.** Guarding only what is caught over-optimizes against *known*
  classes and blinds the system to *novel* ones. The permanent sampling of
  clean-looking changes (§6, bucket `novel` in §4) is the countermeasure; it
  must not be optimized away in the name of efficiency.
- **Guard cost / bureaucracy.** Mitigated by the recurrence/severity threshold
  (§4.1). If writing guards becomes slower than the review it saves, the router
  is miscalibrated — watch the ratio.
- **Reviewer capture.** If the human only ever confirms/rejects the reviewer's
  pre-flagged concerns (§5), the human stops finding what the reviewer never
  raised. Random sampling of *unflagged* changes is required to keep the
  reviewer honest — this is the same mechanism as goodhart mitigation.
- **Silent gate lies.** A green gate that is wrong produces an escape with
  `caught_by = human` on a `mechanical` class that should never have reached the
  human. Track these specifically; they indicate a broken guard, not a new
  defect class.

## 8. Open questions

1. **Defect mix.** What is the actual category histogram? Determines whether the
   ratchet pays off (§4) or stalls on `model-judgment`.
2. **Instrumentation surface.** Where does the catch-log live and how is logging
   made near-frictionless? (beads records? a `bd`-adjacent capture? a
   commit-trailer convention?) Friction here kills the whole loop.
3. **Reviewer-prompt update mechanism.** How does a `model-judgment` catch
   mechanically append to the adversarial reviewer's checklist without unbounded
   prompt growth / drift?
4. **Ownership of the off-ramp state.** Where does per-category calibration state
   (counter `N`, current sampling rate) persist, and who/what re-escalates on
   escape?

## 9. Non-goals

- Not proposing to *reduce* review by fiat or set a blanket "trust threshold."
- Not replacing the adversarial reviewer — this spec *feeds* it.
- Not specifying the instrumentation storage format (open question §8.2).
- No installer or `src/**` changes are committed by this spec; it is a
  discussion artifact.

## 10. Suggested first step

Implement **§3 instrumentation only**, for two to four weeks, with zero change to
review behavior. The resulting category histogram is the empirical basis for
whether — and where — the §4 router and §6 off-ramp are worth building. Measure
before optimizing.
