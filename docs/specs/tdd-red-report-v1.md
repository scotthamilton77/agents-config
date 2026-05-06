# Spec: `tdd-red-report-v1` — report schema for the `tdd-red-team` agent

## Summary

`tdd-red-team` writes failing tests (the red phase of TDD) for a
feature-class bead's acceptance criteria. Its worker-report uses the
shared [`worker-report-v1`](./worker-report-v1.md) core with **no
additional fields**. This document defines the agent's stage-specific
expectations and orchestrator interpretation.

## Schema

Identical to `worker-report-v1` core (see
[`worker-report-v1.md`](./worker-report-v1.md) §1). No additional fields,
no removed fields, no structural deviations.

## Stage-specific expectations

- The agent's task: add tests that capture an intended behavior NOT YET
  implemented in the codebase. The tests must FAIL when run against the
  current production code.
- **Stage-specific success criterion for `status: complete`:** the
  derived gate roll-up is `fail` — specifically,
  `evidence.tests.failing > 0`. The agent emits `status: complete` ONLY
  when this criterion is satisfied. The orchestrator's outcome rule is
  stage-blind and advances the pipeline on `complete`; the
  stage-specific knowledge that "fail-is-success" for red-tests lives
  here, in this agent's contract, not in the orchestrator.
- If the test command's derived gate would be `pass` (tests passed
  unexpectedly — meaning the new tests didn't actually test anything
  new), the agent MUST emit `status: needs_human` with `escalations[]`
  containing `reason: "red-tests-passed-unexpectedly"`. The agent MUST
  NOT emit `status: complete` in this case.
- The agent's commits MUST contain only test-file additions or
  modifications. No production-code changes are permitted in the red
  phase; production-code changes belong to `tdd-green-team`.
- `evidence.tests.passing` and `evidence.tests.failing` are required
  and MUST be present whenever a test command runs (per the shared
  core's null-permitted carve-out for unparseable runner output).

## Worker-side notes

- Run the test command as part of the worker's verification before
  commit. The act of writing failing tests is incomplete without
  proving they fail.
- The full test runner output should be visible in the commit (e.g.,
  in the commit message body or a referenced log). Do not duplicate
  output into the report.
- Non-test file changes in the same dispatch are a contract violation;
  the orchestrator's audit may surface this to a human.

## Orchestrator handling

- Audit label stamped: `worker-audit-tdd-red-team[-iter<N>]`.
- Single-shot dispatch in `implement-feature`'s `red-tests` stage. No
  iteration counter unless a future formula introduces RALF-IT for the
  red phase.
- On `status: needs_human` or escalation, orchestrator stamps the
  `human` label on the step-bead and stops; the next stage
  (`green-loop`) does not run.

## Related

- [`worker-report-v1.md`](./worker-report-v1.md) — the shared core
  schema and conventions.
- [`tdd-green-report-v1.md`](./tdd-green-report-v1.md) — the
  paired green-phase agent's spec.
- `docs/specs/bead-pipeline-architecture.md` — the `red-tests` stage
  description.
