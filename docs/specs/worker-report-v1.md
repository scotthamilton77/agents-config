# Spec: `worker-report-v1` — shared core for worker agent reports (agents-config-7bk.19.1)

## Summary

`worker-report-v1` is the shared core that every worker agent's YAML
report inherits: completion status, evidence blocks, escalations,
discovered work, commits, and the file/label conventions that make
reports discoverable from `bd` alone. The contract travels via the
filesystem, not via the worker's stdout — the orchestrator allocates a
target path under the repository root, passes it to the worker as part
of the task spec, and the worker writes the YAML report to that path
before exiting. The orchestrator reads the file once the worker exits
and stamps a forensic audit label on the step-bead.

Three per-agent specs extend this core with agent-specific fields and
expectations:

- [`tdd-red-report-v1.md`](./tdd-red-report-v1.md) — `tdd-red-team`
- [`tdd-green-report-v1.md`](./tdd-green-report-v1.md) — `tdd-green-team`
- [`bug-diagnoser-report-v1.md`](./bug-diagnoser-report-v1.md) — `bug-diagnoser`

This document defines:

1. The shared core schema, field-by-field.
2. The deterministic file-path convention.
3. The audit-label format and policy.
4. Orchestrator behavior on crashed or malformed workers.
5. The worker's write-tool contract (absolute-path `Write`, not Bash
   redirection).
6. The per-agent extension model.

It is documentation only — no JSON-schema enforcement, matching the
existing spec style under `docs/specs/`.

## Quick reference

| | |
|---|---|
| **Report path** | `<repo-root>/.beads/worker-reports/<step-bead-id>/<agent-name>[-iter<N>].yaml` |
| **Audit label** | `worker-audit-<agent-name>[-iter<N>]` — stamped on the step-bead |
| **Required core fields** | `status`, `evidence`, `escalations`, `discovered_work`, `commits` |
| **Orchestrator minimum** | `status` — missing → synthesize a `status: failed` report |
| **Per-agent extensions** | `tdd-red-report-v1`, `tdd-green-report-v1`, `bug-diagnoser-report-v1` |

## Background

PR #28 introduced the per-stage `claude -p` pipeline (bead `7bk.9`).
Post-review, the `bead-implementor` worker agent was found to have four
structural defects (see epic `7bk.19`); two of them — Defect A (leaky
abstraction) and Defect C (no structured report contract) — motivate
this spec directly:

- **Defect A.** The worker called `bd label add`, `bd update --append-notes`,
  and read bead state. Workers should be pure task functions with no
  bead knowledge. The orchestrator owns all bead state transitions.
- **Defect C.** Workers were instructed to "report back what you did"
  with no pinned schema. The orchestrator could not reliably parse
  completion status, evidence, escalations, discovered work, or commits.

`worker-report-v1` is the contract that closes both defects. The shared
core defines what every agent must emit; per-agent specs add the
agent-specific output shape (e.g. `bug-diagnoser`'s `root_cause_note`).
This split removes conditional fields from any single agent's prompt —
each agent has exactly one concrete schema to follow, reducing
hallucination surface.

## 1. Shared core schema

The example below shows the shared core. It uses schema-template
notation (pipe-separated alternatives, range syntax for `priority`) —
it is **not** copy-paste YAML. See §1.1 for the full field reference,
including allowed enum values.

```text
status: complete | needs_human | failed
iteration: 1                       # optional; orchestrator-supplied for RALF-IT
                                   # loops, omitted for single-shot dispatches
evidence:
  tests:
    command: "..."
    exit_code: 0                   # null when skipped: true
    skipped: false
    passing: 42                    # null permitted only when runner exited
    failing: 0                     # non-zero before emitting parseable counts
  build:     { command: "...", exit_code: 0, skipped: false }
  lint:      { command: "...", exit_code: 0, skipped: false }
  typecheck: { command: "...", exit_code: 0, skipped: false }
escalations:
  - reason: "one-line reason human needed"
    detail: "why this can't be resolved by the worker"
discovered_work:
  - title: "summary of found issue"
    type: bug | task | chore
    priority: 0..4
    detail: "optional context"
    # NOTE: no parent_hint or relation field — orchestrator decides placement
commits:
  - "0123456789abcdef0123456789abcdef01234567"  # full 40-char SHA
```

Per-agent specs MAY add further required fields (e.g.,
`bug-diagnoser-report-v1` adds `root_cause_note`). Per-agent specs MUST
NOT remove or restructure the core fields above.

### 1.1 Field reference

**`status`** — terminal verdict for the dispatch.

| Value | Meaning |
|-------|---------|
| `complete` | Worker finished its task. The orchestrator inspects `evidence` (and the derived gate roll-up — see below) to decide whether to advance, loop again, or stop. |
| `needs_human` | Worker hit a condition only a human can resolve. Orchestrator stamps the `human` label on the step-bead and stops. |
| `failed` | Worker could not complete (e.g., tools unavailable, target missing). Distinct from `complete` with a failing derived gate. |

**`iteration`** — orchestrator-supplied iteration number for RALF-IT
loops. Omitted on single-shot dispatches. The formula step owns the
loop; the orchestrator merely passes the current count through to the
worker so it lands in the report and the audit label.

**`evidence`** — machine-verifiable artifacts the worker produced. Each
block (`tests`, `build`, `lint`, `typecheck`) is optional at the block
level; absence means the agent did not run that kind of check. When a
block IS present, all listed sub-fields are required.

Within a present block:

- `command` (string), `exit_code` (int or null), `skipped` (bool) —
  required.
- `skipped: true` means the gate was intentionally skipped (e.g., no
  project lint configured); `exit_code` is `null` when skipped.
- For the `tests` block only: `passing` (int or null), `failing` (int
  or null) are required. `null` is permitted only when the runner exited
  non-zero before emitting parseable counts (e.g., compile error,
  missing fixtures). The runner's stderr in that case goes into
  `escalations` with `reason: "tests-runner-unparseable"`.

The full test runner / build / lint / typecheck output should be
visible in the worker's commit. The report carries only structured
counts and outcomes — not duplicated raw output.

**Gate-status derivation.** `worker-report-v1` does NOT include a
`gate_status` field. The orchestrator derives the rolled-up verdict
from the evidence blocks, which removes the conflict surface where a
self-reported `gate_status` could disagree with the underlying counts:

| Derived | When |
|---------|------|
| `pass` | Every present block has `skipped == false` AND `exit_code == 0` |
| `fail` | At least one present block has `skipped == false` AND `exit_code != 0` |
| `partial` | At least one present block has `skipped == true`, AND no present block satisfies the `fail` rule |
| `n/a` | `evidence` is `{}` (e.g., synthetic crash report, diagnose-only dispatch) |

The `skipped == false` clause in the `fail` and `pass` rules ensures
that skipped blocks (which carry `exit_code: null`) are not interpreted
as either pass or fail — they participate only in the `partial` rule.

**`escalations`** — list of issues the worker is asking the orchestrator
to surface. Empty list when there are none. Each item is a one-line
`reason` plus a longer `detail`. Setting `status: needs_human` without
populating `escalations` is malformed.

**`discovered_work`** — work the worker noticed during its dispatch but
did NOT do. This is the worker's contribution to the orchestrator's
discovered-work bookkeeping.

Whether a `discovered_work` item is filed as a sibling of the source
bead or as an orphan with a `discovered-from` edge is decided by the
orchestrator, not the worker. The worker MUST NOT emit a `parent_hint`,
`relation`, or any other placement directive. The orchestrator applies
the sibling test (see `src/plugins/beads/.claude/rules/beads.md` I3) to
decide placement. The default — when no sibling fit is obvious — is the
orphan + `discovered-from` form.

**`commits`** — list of full 40-char SHAs the worker produced during
the dispatch. Abbreviated SHAs are malformed. Empty list when the
worker made no commits (e.g., a diagnose-only dispatch). Commit
messages are queryable via `git log <sha>` and are intentionally NOT
duplicated into the report.

### 1.2 Required vs optional summary

| Field | Required? | Notes |
|-------|-----------|-------|
| `status` | required | |
| `evidence` | required | inner blocks optional — present only when command ran or was skipped |
| `escalations` | required | `[]` when empty |
| `discovered_work` | required | `[]` when empty |
| `commits` | required | `[]` when empty |
| `iteration` | optional | omit on single-shot dispatches |

Per-agent specs may add further required or optional fields above the
core. Within a present `evidence` block, all listed sub-fields are
required. An omitted top-level required field is malformed.

### 1.3 Per-agent extensions

| Agent | Schema | Adds |
|-------|--------|------|
| `tdd-red-team` | [`tdd-red-report-v1`](./tdd-red-report-v1.md) | (no additional fields; agent-specific expectations only) |
| `tdd-green-team` | [`tdd-green-report-v1`](./tdd-green-report-v1.md) | (no additional fields; agent-specific expectations only) |
| `bug-diagnoser` | [`bug-diagnoser-report-v1`](./bug-diagnoser-report-v1.md) | `root_cause_note` (required) |

Per-agent specs describe:

- Any additional required fields beyond the core.
- Any structural deviations from the core (none currently).
- Stage-specific orchestrator expectations (e.g., red-team expects the
  derived gate roll-up to be `fail`, green-team expects `pass`).

The core defines the structure that lets the orchestrator parse and
audit any worker's report uniformly. Per-agent specs prevent each
worker agent from carrying conditional logic ("am I a diagnoser? then
also emit X") in its prompt — every agent has exactly one concrete
schema.

## 2. File-based audit convention

The orchestrator chooses where the worker writes its report. The path
follows a single deterministic convention so that anyone with a
step-bead id can locate the report from the filesystem alone:

```
<repo-root>/.beads/worker-reports/<step-bead-id>/<agent-name>[-iter<N>].yaml
```

| Component | Source | Notes |
|-----------|--------|-------|
| `<repo-root>` | `dirname $(git rev-parse --path-format=absolute --git-common-dir)` | `--show-toplevel` returns the *worktree* root inside a feature worktree; `--git-common-dir` resolves the shared `.git` dir, and `dirname` gives the main repo root. |
| `<step-bead-id>` | The step-bead the orchestrator was dispatched for | E.g. `agents-config-7bk.19.1.r3`. |
| `<agent-name>` | The dispatched worker's role name | E.g. `tdd-red-team`, `tdd-green-team`, `bug-diagnoser`. |
| `[-iter<N>]` | RALF-IT iteration counter, supplied by the formula step | Appended only when an iteration counter applies. Single-shot dispatches omit the suffix entirely. |

**Outside any worktree.** The path lives under the main repository root,
not under a feature worktree. Reports must survive worktree cleanup so
the audit trail is intact even after the worktree that produced them is
removed.

**Orchestrator-supplied, not worker-derived.** The worker does not
compute its own report path. The orchestrator passes the absolute path
to the worker as part of the task spec, the worker writes the file, and
the orchestrator reads it after the worker exits. This keeps the worker
bead-agnostic (Defect A) and gives the orchestrator a single point of
control over the path scheme.

## 3. Audit label

After the worker exits — whether it completed normally, crashed, or
emitted a malformed file — the orchestrator stamps a label on the
**step-bead** (not the source-bead, not the molecule):

```
worker-audit-<agent-name>[-iter<N>]
```

Examples: `worker-audit-tdd-red-team`,
`worker-audit-tdd-green-team-iter2`,
`worker-audit-bug-diagnoser`.

The `worker-audit-` prefix is a stable namespace: filtering with
`bd label list <step-bead-id>` and a "starts-with `worker-audit-`"
match returns every audit label without enumerating agent names. The
content after the prefix may evolve over future spec versions; the
prefix is the durable retrieval handle.

The label is a boolean-style marker, dash-separated. The full report
path is fully recoverable from the label and the step-bead id via the
§2 convention; embedding the path in the label was considered and
rejected to avoid shell-quoting and character-set friction.

### 3.1 Audit-label policy

These labels are **forensic-only**:

- **Append-only.** Labels are added, never removed.
- **Not garbage-collected.** Labels persist for the lifetime of the
  step-bead in the bd database.
- **Not used for `bd ready --label` filtering.** The pipeline's routing
  decisions key off other labels (`implementation-ready`, `human`,
  formula-name labels, etc.); audit labels exist purely to make worker
  reports retrievable after the fact.
- **Iteration suffixes intentionally grow the label set.** A RALF-IT
  loop that runs three iterations leaves three iteration-suffixed
  labels on the step-bead. This is the desired forensic trail, not a
  bug.
- **Not designed for full programmatic parsing.** Agent names and the
  label format both use hyphens; the boundary between agent-name and
  `-iter<N>` is ambiguous to a regex. The stable `worker-audit-`
  prefix supports namespace filtering ("starts with"), but parsing the
  agent name + iteration out of the suffix is not a supported use case.
  If structured retrieval beyond namespace filtering is needed, add a
  separate stable companion label (e.g. `worker-reported`) rather than
  parsing audit labels.

## 4. Malformed and crashed-worker handling

Two failure modes are routine and must not derail the pipeline:

1. **Crashed worker.** The worker exits non-zero, OR exits zero but
   never writes the report file at the orchestrator-supplied path.
2. **Malformed report.** The file exists but cannot be parsed as YAML,
   or it parses but is missing a required field the orchestrator must
   read.

In both cases the orchestrator **synthesizes** a `status: failed`
worker-report, writes it to the orchestrator-supplied path, and stamps
the audit label. The synthetic report has:

```yaml
status: failed
evidence: {}
escalations:
  - reason: "Worker crashed"   # or "Worker emitted malformed report" for parse failures
    detail: |
      <full diagnostic context: worker process exit code, stderr tail,
       parse error, and — for malformed — the raw bytes of the file
       the worker wrote>
discovered_work: []
commits: []
```

The `evidence` block is empty (`{}`) because the orchestrator does not
know which commands the worker attempted before crashing; the derived
gate roll-up is `n/a` (see §1.1). The worker's process exit code
belongs in `escalations.detail`, not in an `evidence.tests.exit_code`
field — conflating the two would misrepresent what the test runner
(if any) returned.

The synthetic report contains only shared-core fields. Per-agent
extensions (e.g. `bug-diagnoser`'s `root_cause_note`) are NOT included
in the synthetic shape — agent-specific output is impossible to
fabricate post-crash, and downstream consumers must treat
`status: failed` as a signal that the agent's specific deliverables are
unavailable.

The synthetic report's existence on disk plus the audit label on the
step-bead together guarantee the failure is visible to anyone running
`bd show <step-bead-id>` followed by a glance at the report directory.

### 4.1 Required-field minimum for the orchestrator

For a report to be considered well-formed, the orchestrator MUST be
able to read at minimum:

- `status`

`status` missing — or unparseable as YAML — triggers the synthesis
path. Other required fields (§1.2 and per-agent extensions) are
contract obligations enforced by review, not by the runtime: the
orchestrator survives an incomplete report; full compliance is a review
concern.

### 4.2 Out of scope: orchestrator self-crash

If the orchestrator itself crashes after the worker has exited but
before the report is read or the audit label stamped, the step-bead is
left in a "worker ran but no audit label" limbo. Detecting and
recovering from this case is **out of scope for `worker-report-v1`**
and for epic `7bk.19`; it should be filed as a follow-up bead if it
becomes a real-world problem.

## 5. Worker write-tool contract

Workers MUST emit their report using the `Write` tool with an absolute
path — NOT Bash redirection (`echo ... > path` or here-docs).

The reason is sandbox-mechanical: `claude -p` subagents launched inside
a feature worktree may run with CWD or sandbox constraints that block
Bash redirection to paths outside the worktree. The report path lives
under the main repository root (§2), which is outside the worktree, so
Bash-redirection writes can fail silently or be denied. The `Write`
tool resolves the absolute path through Claude Code's filesystem layer,
which honors the sandbox's allow-list rather than the shell's CWD.

A tracer-bullet test under `scripts/smoke/` will be added by bead
`7bk.19.5` to exercise this contract end-to-end: a synthetic worker
dispatched inside a worktree writes a report to the main-tree path and
the test asserts the file appears.

## 6. Related work

- **Epic `7bk.19`** — the parent redesign of the worker agent layer.
- **`tdd-red-report-v1`**, **`tdd-green-report-v1`**,
  **`bug-diagnoser-report-v1`** — per-agent extensions of this core.
- **`7bk.19.2`** — creates the three worker agents that emit the
  per-agent reports.
- **`7bk.19.3`** — rewrites the `implement-bead` orchestrator to
  allocate the report path, parse the report, derive the gate roll-up,
  stamp the audit label, and synthesize on crash/malformation.
- **`7bk.19.4`** — wires `implement-feature.formula.toml` and
  `fix-bug.formula.toml` to dispatch the new worker agents with
  explicit stage and iteration arguments.
- **`7bk.19.5`** — updates `docs/specs/bead-pipeline-architecture.md` to
  reference these contracts from the relevant stage descriptions, and
  adds the smoke / tracer-bullet that proves the §5 write-tool
  contract holds in practice.
- **`docs/specs/bead-pipeline-architecture.md`** — the canonical
  pipeline architecture; these contracts are the per-stage state-out
  artifacts referenced there.
- **`src/plugins/beads/.claude/rules/beads.md`** — the I3 sibling-test
  rule that governs how the orchestrator places `discovered_work` items.
