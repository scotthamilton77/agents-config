# Spec: `bug-diagnoser-report-v1` — report schema for the `bug-diagnoser` agent

## Summary

`bug-diagnoser` performs root-cause analysis for bug-class beads. It is
dispatched in `fix-bug`'s `diagnose` stage, between `preflight` and
`red-tests`. Its worker-report uses the shared
[`worker-report-v1`](./worker-report-v1.md) core PLUS one required
field — `root_cause_note` — that captures the agent's primary
deliverable.

## Schema

The `bug-diagnoser-report-v1` schema is the shared core extended with
`root_cause_note`. Schema-template notation; not copy-paste YAML.

```text
status: complete | needs_human | failed
iteration: 1                       # optional; typically omitted (single-shot)
evidence:                          # typically empty {} for diagnose-only
  tests:                           # OPTIONAL; present if the diagnoser
    command: "..."                 # ran tests to confirm the bug
    exit_code: 1
    skipped: false
    passing: 7
    failing: 1
escalations:
  - reason: "..."
    detail: "..."
discovered_work:
  - title: "..."
    type: bug | task | chore
    priority: 0..4
    detail: "..."
commits: []                        # always empty — diagnoser does not commit
root_cause_note: |                 # REQUIRED — non-empty free text
  Free-text root-cause analysis. Identifies the underlying defect,
  the path from defect to symptom, and the proposed fix direction
  (which may include suggested test cases for tdd-red-team to author).
```

### Field reference (extension)

**`root_cause_note`** — REQUIRED, non-empty free text. The diagnoser's
primary deliverable. The downstream `tdd-red-team` and `tdd-green-team`
dispatches in `fix-bug` read this from the diagnoser's worker-report
file (path is deterministic via the audit-convention) and use it as
input context. An empty or absent `root_cause_note` is malformed; the
orchestrator MUST treat such a report as `status: failed` (synthesizing
if necessary) and escalate.

The note is not structured; the agent decides headings, length, and
phrasing. The minimum content the downstream stages need:

- What the underlying defect is.
- Why the surface symptom (the failing test, the user-reported bug)
  manifests from that defect.
- A proposed fix direction (what production code is likely to change).

A diagnose that cannot identify a root cause MUST set
`status: needs_human` with an escalation describing what is unclear,
rather than emitting a vague `root_cause_note`. The downstream stages
are not equipped to make architectural decisions on the diagnoser's
behalf.

### Required vs optional summary (additive over core)

| Field | Required? | Notes |
|-------|-----------|-------|
| `root_cause_note` | required | non-empty free text |

All shared-core required-vs-optional rules from
[`worker-report-v1`](./worker-report-v1.md) §1.2 apply unchanged.

## Stage-specific expectations

- The agent's task: investigate the failing test or bug-symptom evidence
  attached to the bead and emit a written root-cause analysis. NO
  production-code changes.
- **Expected `commits`: empty list `[]`.** The diagnoser does not commit.
  A non-empty `commits` array from a `bug-diagnoser` dispatch is a
  contract violation; the orchestrator's audit may surface this.
- **Expected `evidence`: typically empty `{}`.** The diagnoser does not
  run build / lint / typecheck gates. If the diagnoser ran tests to
  confirm the bug or narrow the cause, the `tests` block reports the
  FAILING state (`failing > 0`) — that is informational, not a gate.
- **Derived gate roll-up is not meaningful for diagnose.** The
  orchestrator does not gate on the diagnose-stage evidence derivation;
  the relevant signal is `status` plus the presence of a non-empty
  `root_cause_note`.

## Worker-side notes

- The agent receives the bug bead's description, attached failure
  evidence (logs, repro steps, failing-test names), and any prior
  context from the orchestrator's task spec.
- The agent emits the `root_cause_note` via the `Write` tool to the
  orchestrator-supplied report path (per shared core §5).

## Orchestrator handling

- Audit label stamped: `worker-audit-bug-diagnoser`. Single-shot
  dispatch; no iteration counter.
- The orchestrator extracts `root_cause_note` from the report file and
  passes it to subsequent stages' task specs:
  - `red-tests` (tdd-red-team) — to author a test that captures the
    bug.
  - `green-loop` (tdd-green-team) — to inform the production-code fix.
- Path for downstream consumption:
  `<repo-root>/.beads/worker-reports/<step-bead-id>/bug-diagnoser.yaml`.

## Cross-stage handoff

Because the orchestrator passes `root_cause_note` to downstream agents
through the task spec, the downstream agents never need to read the
diagnoser's report file directly. The `bug-diagnoser-report-v1` shape
is the single source of truth for diagnose-stage output; the
orchestrator is the courier.

## Related

- [`worker-report-v1.md`](./worker-report-v1.md) — the shared core
  schema and conventions.
- [`tdd-green-report-v1.md`](./tdd-green-report-v1.md) — the
  downstream agent in `fix-bug` that consumes this report's
  `root_cause_note`.
- `docs/specs/bead-pipeline-architecture.md` — the `diagnose` stage
  description.
