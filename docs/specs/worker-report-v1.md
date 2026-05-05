# Spec: `worker-report-v1` — pinned schema and audit-label convention (agents-config-7bk.19.1)

## Summary

`worker-report-v1` is the pinned YAML contract that every worker agent
(`tdd-red-team`, `tdd-green-team`, `bug-diagnoser`) returns to the
`implement-bead` orchestrator after a single dispatch. The contract
travels via the filesystem, not via the worker's stdout: the orchestrator
allocates a target path under the repository root, passes that path to
the worker as part of the task spec, and the worker writes the YAML
report to the path before exiting. The orchestrator reads the file once
the worker exits and stamps a forensic audit label on the step-bead so
the report is discoverable from `bd` alone.

This document defines:

1. The YAML schema, field-by-field.
2. The deterministic file-path convention.
3. The audit-label format and policy.
4. Orchestrator behavior on crashed or malformed workers.
5. The worker's write-tool contract (absolute-path `Write`, not Bash
   redirection).

It is documentation only — no JSON-schema enforcement, matching the
existing spec style under `docs/specs/`.

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

`worker-report-v1` is the contract that closes both defects: workers
emit a structured file at a path the orchestrator chose, and the
orchestrator — not the worker — translates that file into bead state.

## 1. Schema

A worker-report is a YAML document with the following shape. The example
below is canonical: every field shown is part of the contract, optional
fields are annotated, and nothing else is permitted at the top level.

```yaml
status: complete | needs_human | failed
iteration: 1                       # optional; orchestrator-supplied for RALF-IT
                                   # loops, omitted for single-shot dispatches
evidence:
  tests:
    command: "..."
    exit_code: 0
    passing: 42                    # required for green-loop convergence tracking
    failing: 0                     # required for green-loop convergence tracking
    output_excerpt: "..."
  build:     { command: "...", exit_code: 0 }
  lint:      { command: "...", exit_code: 0 }
  typecheck: { command: "...", exit_code: 0 }
gate_status: pass | fail | partial  # rolled-up gate verdict for orchestrator
                                    # decision-making
root_cause_note: |                  # optional; required for bug-diagnoser,
                                    # optional for others. tdd-green-team in
                                    # fix-bug receives this from the prior
                                    # diagnose dispatch.
  Free-text root-cause analysis.
escalations:
  - reason: "one-line reason human needed"
    detail: "why this can't be resolved by the worker"
discovered_work:
  - title: "summary of found issue"
    type: bug | task | chore
    priority: 0..4
    detail: "optional context"
    # NOTE: no parent_hint or relation field. The orchestrator owns
    # placement per beads.md I3 (sibling test). Default is a
    # discovered-from edge to the source bead.
commits:
  - sha: "full 40-char sha"
    message: "one-line commit message"
```

### 1.1 Field reference

**`status`** — terminal verdict for the dispatch.

| Value | Meaning |
|-------|---------|
| `complete` | Worker finished its task. The orchestrator inspects `evidence` / `gate_status` to decide whether to advance, loop again, or stop. |
| `needs_human` | Worker hit a condition only a human can resolve. Orchestrator stamps the `human` label on the step-bead and stops. |
| `failed` | Worker could not complete (e.g., tools unavailable, target missing). Distinct from `complete + gate_status: fail`. |

**`iteration`** — orchestrator-supplied iteration number for RALF-IT
loops. Omitted on single-shot dispatches. The formula step owns the
loop; the orchestrator merely passes the current count through to the
worker so it lands in the report and the audit label.

**`evidence`** — machine-verifiable artifacts the worker produced.

- `evidence.tests.passing` and `evidence.tests.failing` are **required**
  whenever a test command runs, because `green-loop` convergence is
  measured by them. A worker that ran no tests omits the `tests` block
  entirely. When the test runner exits non-zero before emitting parseable
  counts (e.g., compile error, missing fixtures), set `passing: null,
  failing: null` and capture the runner's stderr in `output_excerpt`.
- `evidence.tests.output_excerpt` is a tail of test runner output,
  capped to roughly 4KB. The full output should be visible in the
  worker's commit, not duplicated into the report.
- `build`, `lint`, `typecheck` blocks are each present only when the
  worker ran the corresponding command. Missing blocks mean "did not
  run", not "ran and passed".

**`gate_status`** — rolled-up verdict across all evidence blocks,
computed by the worker. Decoupled from `status` because a worker can
finish (`status: complete`) with a failing gate (`gate_status: fail`) —
that is the normal state during a `red-tests` dispatch.

| Value | Meaning |
|-------|---------|
| `pass` | All evidence blocks present in the report exited 0. |
| `fail` | At least one evidence block exited non-zero. |
| `partial` | Some required gates were intentionally skipped (e.g., no project lint configured). |

**`root_cause_note`** — free-text root-cause analysis. **Required for
`bug-diagnoser`**, optional for the TDD agents. In `fix-bug`, the
`tdd-green-team` dispatch reads the diagnose stage's note from its
prior worker-report and may carry it forward in its own report; this
preserves the audit trail across stages.

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

**`commits`** — SHAs of commits the worker produced during the dispatch.
Full 40-char SHAs only; abbreviated SHAs are malformed. The
`message` field is the commit's first line, for human scanning. Empty
list when the worker made no commits (e.g., a diagnose-only dispatch).

### 1.2 Required vs optional summary

Top-level **required** fields: `status`, `evidence`, `gate_status`,
`escalations`, `discovered_work`, `commits`.

Top-level **optional** fields: `iteration`, `root_cause_note`.

Within `evidence`, the `tests` / `build` / `lint` / `typecheck` blocks
are individually optional, present only when the worker ran the
corresponding command. Within a block, all listed sub-fields are
required when the block is present.

Empty-list-valued required fields (`escalations`, `discovered_work`,
`commits`) are written as `[]`. An omitted required field is malformed
(see §4).

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
**step-bead** (not the source bead, not the molecule):

```
worker-report-<agent-name>[-iter<N>]
```

Examples: `worker-report-tdd-red-team`,
`worker-report-tdd-green-team-iter2`,
`worker-report-bug-diagnoser`.

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

If filterability becomes useful later, a separate stable label (e.g.
`worker-reported`) can be added as a sibling without disturbing the
iteration-stamped audit labels.

Note: agent names contain hyphens (`tdd-red-team`, `bug-diagnoser`), and
the label format is also dash-separated, so the boundary between the
agent-name segment and the `-iter<N>` suffix is not unambiguous to a
regex parser. Audit labels are not designed to be parsed
programmatically — the forensic-only, no-routing-filter policy means
the boundary is never a runtime concern. If structured retrieval becomes
necessary, use the stable companion label approach above rather than
parsing audit labels.

## 4. Malformed and crashed-worker handling

Two failure modes are routine and must not derail the pipeline:

1. **Crashed worker.** The worker exits non-zero, OR exits zero but
   never writes the report file at the orchestrator-supplied path.
2. **Malformed report.** The file exists but cannot be parsed as YAML,
   or it parses but is missing a required field the orchestrator must
   read.

In both cases the orchestrator **synthesizes** a worker-report on the
worker's behalf, writes that synthetic report to the same path the
worker was supposed to write, and stamps the audit label as if the
worker had succeeded. The synthetic report has:

```yaml
status: failed
gate_status: fail
evidence: {}
escalations:
  - reason: "Worker crashed" | "Worker emitted malformed report"
    detail: |
      <full diagnostic context: worker process exit code, stderr tail,
       parse error, and — for malformed — the raw bytes of the file
       the worker wrote>
discovered_work: []
commits: []
```

The `evidence` block is empty (`{}`) in the synthetic report because the
orchestrator does not know which commands the worker attempted before
crashing. The worker's process exit code belongs in `escalations.detail`,
not in an `evidence.tests.exit_code` field — conflating the two would
misrepresent what the test runner (if any) returned.

The synthetic report's existence on disk plus the audit label on the
step-bead together guarantee the failure is visible to anyone running
`bd show <step-bead-id>` followed by a glance at the report directory.

### 4.1 Required-field minimum for the orchestrator

For a report to be considered well-formed, the orchestrator MUST be
able to read at minimum:

- `status`
- `gate_status`

Either field missing — or unparseable as YAML — triggers the synthesis
path. Other required fields (§1.2) are also part of the contract; their
absence is a workmanship issue surfaced through code review rather than
a runtime malformation. This is intentional two-tier validity: the
orchestrator must survive a report that is technically incomplete, log
the gap in the synthetic report's `escalations`, and continue. Full
schema compliance is enforced by review, not by the runtime path.

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
- **`7bk.19.2`** — creates the three worker agents that emit
  `worker-report-v1`.
- **`7bk.19.3`** — rewrites the `implement-bead` orchestrator to
  allocate the report path, parse the report, stamp the audit label,
  and synthesize on crash/malformation.
- **`7bk.19.4`** — wires `implement-feature.formula.toml` and
  `fix-bug.formula.toml` to dispatch the new worker agents with
  explicit stage and iteration arguments.
- **`7bk.19.5`** — updates `docs/specs/bead-pipeline-architecture.md` to
  reference this contract from the relevant stage descriptions, and
  adds the smoke / tracer-bullet that proves the §5 write-tool
  contract holds in practice.
- **`docs/specs/bead-pipeline-architecture.md`** — the canonical
  pipeline architecture; this contract is one of the per-stage
  state-out artifacts referenced there.
- **`src/plugins/beads/.claude/rules/beads.md`** — the I3 sibling-test
  rule that governs how the orchestrator places `discovered_work` items.
