---
name: implement-bead
description: >
  Use when a step-bead is ready for autonomous execution. Reads the
  step-bead and labels, resolves execution context, decides dispatch
  shape from metadata, and either invokes an orchestration skill
  in-session or runs a single direct dispatch via the per-dispatch
  primitive documented below. The invoking agent is the ORCHESTRATOR
  only — workers are dispatched via the Agent tool from the top-level
  session. Loop ownership lives in `ralf-implement` / `ralf-review`,
  never in this skill.
model: sonnet[1m]
effort: high
---

# implement-bead

Metadata-driven dispatcher. One step-bead per invocation.

## 1. Read step-bead and labels

1. Run `bd show <step-bead-id>` and `bd label list <step-bead-id>`.
2. Run `bd show <step-bead-id> --json | jq -r '.[0].parent'` to get `<mol-id>`.
3. Derive `<source-bead-id>` from the molecule's `for-bead-<source-bead-id>` label (stamped by `start-bead` / `implement-bead` per the molecule→bead linkage convention in `src/plugins/beads/.claude/rules/beads.md`): `bd label list <mol-id> | awk '/^for-bead-/{sub(/^for-bead-/,""); print; exit}'`.
4. Run `bd label list <source-bead-id>` to capture `ralf:required` / `ralf:cycles=N`.

## 2. Resolve execution context

1. Worktree path: decode the molecule's `worktree-path-*` label (`__ → /` then `_u → _`); verify with `git -C <path> rev-parse --is-inside-work-tree`.
2. Mode: canonical lookup is the source bead's `formula-<name>` label (per `bead-pipeline-architecture.md` §3 preflight and §4.2 — preflight reads `formula-<name>` on the source bead, falling back to per-bead-type defaults: feature/task/chore → `implement-feature`, bug → `fix-bug`, epic → flag-human). Read via `bd label list <source-bead-id> | awk '/^formula-/{sub(/^formula-/,""); print; exit}'`. On absent or ambiguous label, fall back to molecule title: `bd show <mol-id> --json | jq -r '.[0].title'`. Allowed mode values: `implement-feature` | `fix-bug`.
3. Repo root: `dirname $(git -C <worktree> rev-parse --path-format=absolute --git-common-dir)`.
4. Target report path template: `<repo-root>/.beads/worker-audit/<step-bead-id>/<agent-name>[-iter<N>].yaml` (per `worker-report-v1.md` §2).

## 3. Decide dispatch shape from metadata

1. If `ralf:required` is on the source bead → invoke the orchestration skill in-session: `ralf-implement` for green-loop / fix stages, `ralf-review` for review-cycle stages. Pass: spec, Definition of Done, quality commands, optional `ralf:cycles=N` cap, the doer's `subagent_type`, the worktree path, the target report path template, and reference to the per-dispatch primitive in §4. The orchestration skill substitutes `<agent-name>` and `-iter<N>` into the template per cycle when invoking the per-dispatch primitive. The orchestration skill executes as in-session skill code in this same top-level session — NOT as a subagent.
2. Otherwise → load the appropriate execution skill for the stage (e.g. `superpowers:test-driven-development`) and run §4 once with the doer's `subagent_type` from §5.

This skill does NOT invoke itself recursively via `claude -p` and does NOT dispatch orchestration skills as subagents.

## 4. Per-dispatch primitive

Inputs: `(stage, mode, iteration?, execution_context, doer_subagent_type)`.

1. Compute report path by substituting `<step-bead-id>`, `<agent-name>`, and (when `iteration` is supplied) `-iter<N>` into the template.
2. Build worker task-spec: worktree path, mode-specific inputs (per per-agent specs in `worker-report-v1`), absolute target report path, project test-runner command, iteration counter when applicable. For `(red-tests, fix-bug)` and `(green-loop, fix-bug)`, include `root_cause_note` (and `reproduction_steps` for red-tests) retrieved per §6.
3. Dispatch from this top-level session: `Agent({ subagent_type: <doer>, prompt: <task-spec> })`. Subagents cannot spawn subagents — Agent dispatch is valid only from the top-level session.
4. After the worker exits, classify:
   - Non-zero exit OR no file at target path → synthesize `status: failed` at the target path per `worker-report-v1.md` §4: `evidence: {}`, `escalations[].reason: "Worker crashed"`, `escalations[].detail`: exit code + stderr tail, `discovered_work: []`, `commits: []`.
   - File present but unparseable as YAML or missing core required field (`status` per `worker-report-v1.md` §4.1) → synthesize `status: failed` with `escalations[].reason: "Worker emitted malformed report"` (per §4) wrapping the parse error and raw bytes in `escalations[].detail`.
   - File present and parseable but missing a per-agent runtime-required field (e.g. `bug-diagnoser` with empty or missing `root_cause_note`) → synthesize `status: failed` with `escalations[].reason: "Worker emitted malformed report"` wrapping the missing-field name and raw bytes in `escalations[].detail`.
   - Otherwise → read and parse the YAML.
5. Stamp `worker-audit-<agent-name>[-iter<N>]` on the step-bead (forensic, append-only).
6. Derive gate roll-up from the evidence blocks per `worker-report-v1.md` §1.1 (`pass` / `fail` / `partial` / `n/a`). Workers do NOT emit `gate_status`; the orchestrator derives it.
7. Return `{ report, gate, audit_label }` to the caller.

## 5. Stage→agent map

- `(red-tests, implement-feature)` → `tdd-red-team` (multi-AC mode; AC bullets in task-spec).
- `(red-tests, fix-bug)` → `tdd-red-team` (single-regression mode; `root_cause_note` and `reproduction_steps` from upstream diagnose report).
- `(green-loop, implement-feature)` → `tdd-green-team` (no `root_cause_note` in task-spec).
- `(green-loop, fix-bug)` → `tdd-green-team` (with `root_cause_note` from upstream diagnose report).
- `(diagnose, fix-bug)` → `bug-diagnoser`.

## 6. Upstream report retrieval

For `(red-tests, fix-bug)` and `(green-loop, fix-bug)`, retrieve the prior diagnose step's `root_cause_note`:

1. Locate the upstream step-bead-id within the same molecule: `bd list --parent <mol-id> --all --type task --json | jq -r '.[] | select(.title | startswith("Diagnose:")) | .id'`. A more robust stage label may replace this lookup later.
2. Build the upstream report path: `<repo-root>/.beads/worker-audit/<upstream-step-bead-id>/bug-diagnoser.yaml` (no iter suffix; diagnose is direct dispatch).
3. Read and parse the YAML; extract `root_cause_note` (and `reproduction_steps` for red-tests).
4. Inject extracted fields into the downstream task-spec.
5. Failure mode: if the upstream report is missing or unparseable, stamp `human` on the step-bead and append a missing-context detail. Do NOT proceed with an empty `root_cause_note`. The dependency is hard.

## 7. File discovered_work before applying status outcomes

1. For every non-synthetic report (status is `complete`, `needs_human`, or `failed` from the worker), file each `discovered_work` item as a new bead. Apply this step BEFORE step 8 outcomes, so any escalations may reference the newly-filed beads.
2. Synthetic reports always have `discovered_work: []` per `worker-report-v1.md` §4 — moot but explicit.
3. Placement decision is the orchestrator's, not the worker's. Apply the I3 sibling test from `src/plugins/beads/.claude/rules/beads.md`: passes → `bd create --parent <epic-id>`; fails → orphan + `bd dep add <new-id> <source-bead-id> --type discovered-from`. Default when no obvious sibling fit exists: orphan + `discovered-from`.

## 8. Apply status outcomes to the step-bead

1. Direct-dispatch path (no `ralf:required`) — exactly one report processed:
   - `complete` + gate `pass` → close step-bead with summary; exit.
   - `complete` + gate `fail` or `partial` → stamp `human`, append gate-fail evidence to step-bead notes, close step-bead with summary; exit.
   - `needs_human` → stamp `human`, append escalations, close step-bead with summary; exit.
   - `failed` (real or synthesized) → stamp `human`, append failure detail, close step-bead with summary; exit.
2. Orchestration path (RALF) — `ralf-implement` or `ralf-review` returns an aggregate verdict (final report, final derived gate, foreign-eyes status) on convergence or max-cycles exhaustion. Apply the same outcome rules above using the aggregate verdict, then close the step-bead and exit. The orchestration skill stamps per-iteration audit labels during the loop; this skill closes the step-bead at the end.

## Audit-label scope

`worker-audit-<agent-name>[-iter<N>]` labels apply ONLY to dispatches of `tdd-red-team`, `tdd-green-team`, and `bug-diagnoser` (worker-only). Review, fresh-eyes, and adversarial subagents dispatched by orchestration skills are out-of-band and are explicitly excluded from the `worker-audit-` namespace; their audit trail (if any) is the orchestration skill's concern, not this skill's.
