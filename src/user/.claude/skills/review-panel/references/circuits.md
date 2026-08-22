# Sequenced circuits over a mixed target

Read this when the target holds more than one class partition. A single-class
target has the trivial one-circuit plan and none of this applies.

## The circuit plan

Before any round is emitted, produce a **circuit plan** with the staffing
machinery: an ordered grouping of the present class partitions into circuits,
with a rationale, retained beside the staffing records. One guideline generates
the order, and it is a guideline, not a rule — **fix-ripple**: the circuit whose
fixes would invalidate the most other circuits' reviews runs first. Typed-code
before prose, because code fixes ripple into every description of the code while
prose fixes ripple almost nowhere; spec-code before spec prose, the same
ordering one level up. The rationale is what an audit attacks, so it names the
ripple structure of *this* target, not the guideline. Circuit count is an output
of the plan.

Run each circuit's rounds to termination — rounds, checkpoints, sweep, the whole
lifecycle, per class — before the next circuit's lenses read anything. A later
circuit dispatches at the head the earlier circuit's terminal state pinned, so
its lenses review artifacts describing settled work, not mid-flight work.

## Re-arm, and the cap

A later circuit's fix that changes an earlier, terminated circuit's artifacts
re-arms that circuit for a **delta round** scoped since the head it terminated
at — never a full re-run. The mechanical re-arm signal is fresh gate evidence
over that circuit's gate-relevant files: its profile gates ran again at a new
head because its files changed.

**Each circuit gets at most two activations: its initial run and one re-arm.**
A trigger that would start a third activation is not another round — it is a due
checkpoint whose only admissible verdicts are terminate-bounce-upstream and
terminate-escalate-human. Dispatch the trend analyst as for any checkpoint; a
continue verdict from a cap-fired checkpoint is invalid and resolves as
escalate-to-human.

## The churn diagnosis

Every campaign termination that is not terminal-clean carries a **churn
diagnosis** on its terminating checkpoint record: recommendations upstream
(criteria, staffing, class contracts, the spec itself) and/or panel-side (lens
selection, the circuit plan, sequencing) for reducing the churn observed. A
terminate verdict without a diagnosis is invalid, exactly as an uncited verdict
is, and resolves as escalate-to-human. The upstream-defect halt is exempt: its
indictment already names the remediation.

The two-activation cap and the mandatory diagnosis are deliberately temporary
instrumentation: the cap is set low to surface what pushes campaigns toward a
third activation, and the diagnoses are the evidence its eventual re-evaluation
reads. Do not route around either.

## Reviewing spec-code

Spec-code is code authored *as* specification — interface stubs, data shapes,
prototypes pinning a design decision, deliberately failing tests — and it
reviews under its own roster (interface quality, the contract-only boundary,
pinning adequacy), never typed-code's: a production-code lens on specification
code emits true observations that are wrong findings, indefinitely.

Classification carries a declaration burden. Code is typed-code until the
round's records state why the artifact **cannot ship**: not deployed, not
imported by production paths, not gated as product. Record that rationale
before any spec-code round; it is audit-attackable, and a missing one means the
partition reviews as typed-code. The class's precondition gate is parse-level —
the artifact compiles or parses, recorded like any gate execution — and `fixed`
keeps evidence optional, since deliberately red tests can prove no mutation.
