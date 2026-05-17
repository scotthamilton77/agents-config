# Spec: `tdd-green-report-v1` — report schema for the `tdd-green-team` agent

## Summary

`tdd-green-team` makes failing tests pass (the green phase of TDD),
iteratively under RALF-IT control. Its worker-report uses the shared
[`worker-report-v1`](./worker-report-v1.md) core with **no additional
fields**. This document defines the agent's stage-specific expectations
and orchestrator interpretation.

## Schema

Identical to `worker-report-v1` core (see
[`worker-report-v1.md`](./worker-report-v1.md) §1). No additional fields,
no removed fields, no structural deviations.

## Stage-specific expectations

- The agent's task: implement production code that makes the failing
  tests (left by `tdd-red-team`, or — in `fix-bug` — the failing test
  written by `tdd-red-team` to capture the bug) pass without breaking
  existing tests.
- **`status: complete` is per-iteration.** It signals only that the
  agent finished its iteration's attempt at making the failing tests
  pass — NOT loop convergence. Convergence
  (`evidence.tests.failing == 0` from the most recent iteration) is
  determined by `ralf-implement` across iterations, not by this agent.
  The agent emits `status: complete` for any iteration that ran to
  completion and recorded its evidence; it does NOT self-bound based
  on whether its own iteration converged.
- **Expected derived gate roll-up on convergence: `pass`** —
  specifically, every present `evidence` block has `exit_code == 0`
  and `skipped == false`. This is the convergence signal that
  `ralf-implement` reads to decide whether to dispatch another
  iteration or advance the pipeline.
- A persistent `fail` derivation across iterations indicates the agent
  has not converged. The formula step owns iteration policy:
  - The formula step's `MAX_ITERATIONS` cap controls when the orchestrator
    stops dispatching.
  - On cap exhaustion, the orchestrator stamps the `human` label and
    files an escalation note.
- `evidence.tests.passing` and `evidence.tests.failing` are required
  and MUST be present whenever a test command runs. The orchestrator's
  green-loop convergence test reads `failing == 0` from the most
  recent iteration.

## Worker-side notes

- Each iteration is a separate dispatch with its own report file:
  `<step-bead-id>/tdd-green-team-iter<N>.yaml`. The iteration counter
  is encoded in the file path and audit label by the orchestrator; the
  worker does not record it inside the YAML body.
- The worker MUST run the full test command as part of its verification
  before commit; the orchestrator does not re-run tests post-dispatch.
- When the test runner exits non-zero before emitting parseable counts
  (e.g., a compile error introduced by the iteration's changes), the
  worker sets `passing: null, failing: null` and captures the runner's
  stderr in `escalations` with `reason: "tests-runner-unparseable"`.
  The orchestrator treats unparseable counts as a `fail` derivation
  for convergence-tracking purposes and continues the loop (or escalates
  on cap).
- In `fix-bug`, the agent's task spec includes the diagnose stage's
  `root_cause_note` (the orchestrator extracts it from the
  `bug-diagnoser` worker-report file before dispatching). The
  `tdd-green-team` worker-report itself does NOT include
  `root_cause_note`.

## Orchestrator handling

- Audit label stamped per iteration:
  `worker-audit-tdd-green-team-iter<N>`. Iteration suffixes
  intentionally grow the label set (forensic trail).
- The orchestrator reads each iteration's report, derives the gate
  roll-up from `evidence`, and decides:
  - `pass` → green-loop converged; advance to the next stage.
  - `fail` → green-loop continues; dispatch iteration N+1 (subject to
    `MAX_ITERATIONS`).
  - `partial` → unusual for green-loop; escalate.
  - `n/a` (empty `evidence`) → indicates a worker that produced no test
    evidence; treated as `fail` for convergence and surfaced via audit.

## Related

- [`worker-report-v1.md`](./worker-report-v1.md) — the shared core
  schema and conventions.
- [`tdd-red-report-v1.md`](./tdd-red-report-v1.md) — the paired
  red-phase agent's spec.
- [`bug-diagnoser-report-v1.md`](./bug-diagnoser-report-v1.md) — the
  upstream stage in `fix-bug` whose `root_cause_note` feeds this
  agent's task spec.
- `docs/specs/bead-pipeline-architecture.md` — the `green-loop` stage
  description.
