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

## 1. Resolve step-bead from source-bead-id

The slash-command argument is the **source bead-id** (e.g. `7bk.19.3`) — the same id the shell driver passes from `bd ready --label implementation-ready`. Resolve the chain source-bead → molecule → current step-bead:

1. `<mol-id>` from the source bead's linkage label: `bd list --label for-bead-<source-bead-id> --type molecule --json | jq '[.[] | select(.status != "closed")]'` (per the molecule→bead linkage convention in `src/plugins/beads/.claude/rules/beads-labels.md`). **If empty (first stage — no molecule yet)**: select the formula and pour. Formula selection is canonical: read the source bead's `formula-<name>` label first via the JSON array shape (per `src/plugins/beads/.claude/rules/beads-labels.md` molecule→bead linkage convention — `bd label list <id> --json` returns a flat JSON array of label strings, NOT `{labels: [...]}`; the awk-with-`exit` pattern previously used here returned the FIRST match and could not detect ambiguity, silently swallowing §4.2 policy-knob collisions):

       formula_names=$(bd label list <source-bead-id> --json \
         | jq -r '.[] | select(startswith("formula-"))' \
         | sed 's/^formula-//' \
         | sort -u)
       formula_count=$(printf '%s\n' "$formula_names" | sed '/^$/d' | wc -l | tr -d ' ')

       if [ "$formula_count" = "0" ]; then
         # No formula-* label → fall back to type-based default below.
         formula_to_pour=""
       elif [ "$formula_count" = "1" ]; then
         formula_to_pour="$formula_names"
       else
         # Multiple distinct formula-* labels → §4.2 policy-knob collision.
         # Per §5.6, flag-human is a pause (not a failure); exit cleanly.
         # No step-bead exists yet (the molecule has not been poured), so
         # only the source bead is labeled — the §5.6 step-bead path
         # applies only after pour, and is enforced in §2 below.
         bd label add <source-bead-id> human
         bd update <source-bead-id> --append-notes "implement-bead: multiple formula-* labels detected ($formula_names) — §4.2 collision; manual resolution required."
         exit 0
       fi

   If `formula_to_pour` is non-empty, use it. Otherwise branch on the source bead's type as the fallback: `epic` → flag-human (stamp `human` on the source bead, append note: "epic source bead requires decomposition before implementation, not a formula pour") and exit; do NOT pour; `bug` → `fix-bug`; `feature` / `task` / `chore` (or null) → `implement-feature`. Pour the selected formula with the appropriate `--var` shape (one variable name per formula): `implement-feature` → `--var feature="<title>" --var title-slug=<slug>`; `fix-bug` → `--var bug="<title>" --var title-slug=<slug>`; `docs-only` → `--var topic="<title>" --var title-slug=<slug>`; `merge-and-cleanup` → `--var title-slug=<slug> --var pr="<pr-number>"` (where `<pr-number>` is the open PR number to merge; `bead-id` is the source bead being delivered). All formulas additionally take `--var bead-id=<source-bead-id>`. The `<slug>` is derived from the source bead's title using the canonical slug generation algorithm: (1) lowercase the title, (2) replace spaces with hyphens, (3) strip all characters except a-z, 0-9, and hyphens, (4) collapse consecutive hyphens to a single hyphen, (5) truncate to a maximum of 30 characters, (6) strip leading and trailing hyphens, (7) fallback: if the result is empty, use the first 30 characters of the bead-id. Stamp `bd label add <new-mol-id> for-bead-<source-bead-id>` immediately after pour (linkage convention). Then re-run the existence probe to obtain `<mol-id>`. If exactly one non-closed molecule → take its `id`. If multiple → apply the disambiguation logic from `src/plugins/beads/.claude/rules/beads-labels.md` "Molecule → bead linkage convention" (resume the winner if one clearly supersedes others; otherwise stamp `human` on the source bead and exit).
2. `<step-bead-id>` from the molecule's current step: `bd mol current <mol-id> --json | jq -r 'if type == "array" then .[] else . end | select(.status != "closed") | .id' | head -1` (defensive against both array and object JSON shapes, matching the pattern in `scripts/bead-driver-test.sh`).
3. Run `bd show <step-bead-id>` and `bd label list <step-bead-id>` for step-bead context.
4. Run `bd label list <source-bead-id>` to capture `ralf:required` / `ralf:cycles=N`.

## 2. Resolve execution context

1. Worktree path: decode the molecule's `worktree-path-*` label (`__ → /` then `_u → _`); verify with `git -C "<path>" rev-parse --is-inside-work-tree`. If the command exits non-zero or prints anything other than `true` → flag-human protocol: stamp `human` on BOTH the step-bead AND source bead, append diagnostic note (the decoded path that failed verification), and exit. Do NOT proceed without a verified worktree.
2. Mode: canonical lookup is the source bead's `formula-<name>` label (per `bead-pipeline-architecture.md` §3 preflight and §4.2 policy-knob labels — preflight reads `formula-<name>` on the source bead, falling back to per-bead-type defaults: feature/task/chore → `implement-feature`, bug → `fix-bug`, epic → flag-human). implement-bead reads the same authority via the JSON array shape (per `src/plugins/beads/.claude/rules/beads-labels.md` molecule→bead linkage convention — `bd label list <id> --json` returns a flat JSON array of label strings, NOT `{labels: [...]}`; the awk-with-`exit` pattern previously used here returned the FIRST match and could not detect ambiguity, silently swallowing §4.2 policy-knob collisions):

       formula_names=$(bd label list <source-bead-id> --json \
         | jq -r '.[] | select(startswith("formula-"))' \
         | sed 's/^formula-//' \
         | sort -u)
       formula_count=$(printf '%s\n' "$formula_names" | sed '/^$/d' | wc -l | tr -d ' ')

       if [ "$formula_count" = "0" ]; then
         # No formula-* label → fall back to molecule title below.
         mode=""
       elif [ "$formula_count" = "1" ]; then
         mode="$formula_names"
       else
         # Multiple distinct formula-* labels → §4.2 policy-knob collision.
         # Full §5.6 flag-human protocol: label BOTH source + step-bead,
         # transition step-bead to open, exit cleanly (this is a pause,
         # not a failure).
         bd label add <source-bead-id> human
         bd label add <step-bead-id> human
         bd update <source-bead-id> --append-notes "implement-bead: multiple formula-* labels detected ($formula_names) — §4.2 collision; manual resolution required."
         bd update <step-bead-id> --status open
         exit 0
       fi

   On absent label (`mode` empty), fall back to molecule title: `bd show <mol-id> --json | jq -r '.[0].title'`. Allowed mode values: `implement-feature` | `fix-bug` | `docs-only`. (The `docs-only` mode does not have entries in §5's stage→agent map; its steps are non-RALF and dispatched directly per its formula.)
3. Repo root: `dirname "$(git -C "<worktree-path>" rev-parse --path-format=absolute --git-common-dir)"` (both `<worktree-path>` and the `$(...)` substitution must be double-quoted to survive paths with spaces or special characters).
4. Worker-audit setup: run `setup-worker-audit.sh <repo-root>` (located alongside this SKILL.md). Idempotent — creates `<repo-root>/.beads/worker-audit/` and writes a `*`-pattern `.gitignore` inside it if either is absent. Call this immediately after the repo root is known, before any dispatch.
5. Target report path template: `<repo-root>/.beads/worker-audit/<step-bead-id>/<agent-name>[-iter<N>].yaml` (per `worker-report-v1.md` §2).

## 3. Decide dispatch shape from metadata

1. If `ralf:required` is on the source bead → invoke the orchestration skill in-session: `ralf-implement` for green-loop / fix stages, `ralf-review` for review-cycle stages. Pass: spec, Definition of Done, quality commands, optional `ralf:cycles=N` cap, the doer's `subagent_type`, the worktree path, the target report path template, and reference to the per-dispatch primitive in §4. The orchestration skill substitutes `<agent-name>` and `-iter<N>` into the template per cycle when invoking the per-dispatch primitive. The orchestration skill executes as in-session skill code in this same top-level session — NOT as a subagent.
2. Otherwise → load the appropriate execution skill for the stage (e.g. `superpowers:test-driven-development`) and run §4 once with the doer's `subagent_type` from §5.

This skill does NOT invoke itself recursively via `claude -p` and does NOT dispatch orchestration skills as subagents.

## 4. Per-dispatch primitive

Inputs: `(stage, mode, iteration?, execution_context, doer_subagent_type)`.

1. Compute report path by substituting `<step-bead-id>`, `<agent-name>`, and (when `iteration` is supplied) `-iter<N>` into the template.
2. Build worker task-spec: worktree path, mode-specific inputs (per per-agent specs in `worker-report-v1.md`), absolute target report path, project test-runner command, iteration counter when applicable. For `(red-tests, fix-bug)` and `(green-loop, fix-bug)`, include `root_cause_note` (and `reproduction_steps` for red-tests) retrieved per §6.
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
5. Failure mode: if the upstream report is missing or unparseable, stamp `human` on BOTH the step-bead AND the source bead and append a missing-context detail. Do NOT proceed with an empty `root_cause_note`. The dependency is hard.

## 7. File discovered_work before applying status outcomes

1. For every non-synthetic report (status is `complete`, `needs_human`, or `failed` from the worker), file each `discovered_work` item as a new bead. Apply this step BEFORE step 8 outcomes, so any escalations may reference the newly-filed beads.
2. Synthetic reports always have `discovered_work: []` per `worker-report-v1.md` §4 — moot but explicit.
3. Placement decision is the orchestrator's, not the worker's. Apply the I3 sibling test from `src/plugins/beads/.claude/rules/beads.md`: passes → `bd create --parent <epic-id>`; fails → orphan + `bd dep add <new-id> <source-bead-id> --type discovered-from`. Default when no obvious sibling fit exists: orphan + `discovered-from`.

## 8. Apply status outcomes to the step-bead

Outcomes are stage-blind: `status` is the only outcome input. Stage-specific success criteria — including red-tests' "fail-is-success" — live in each worker's per-agent spec, which is also where the worker decides between `complete` and `needs_human` based on the derived gate. The orchestrator's derived gate roll-up is forensic context (recorded via the audit label, the report file on disk, and the `--append-notes` evidence appended on escalation paths), not an outcome branch. All `human` stamps cover BOTH the step-bead AND the source bead (human-flag protocol).

1. Direct-dispatch path (no `ralf:required`) — exactly one report processed:
   - `complete` → close step-bead with summary; exit.
   - `needs_human` → stamp `human` on step-bead AND source bead, append escalations, close step-bead with summary; exit.
   - `failed` (real or synthesized) → stamp `human` on step-bead AND source bead, append failure detail, close step-bead with summary; exit.
2. Orchestration path (RALF) — `ralf-implement` or `ralf-review` returns an aggregate verdict (final report, foreign-eyes status) on convergence or max-cycles exhaustion. Apply the same status-only rules above using the aggregate verdict (every `human` stamp covers BOTH step-bead AND source bead), then close the step-bead and exit. The orchestration skill owns per-iteration gate inspection during the loop and stamps per-iteration audit labels; this skill closes the step-bead at the end.

## Audit-label scope

`worker-audit-<agent-name>[-iter<N>]` labels apply ONLY to dispatches of `tdd-red-team`, `tdd-green-team`, and `bug-diagnoser` (worker-only). Review, fresh-eyes, and adversarial subagents dispatched by orchestration skills are out-of-band and are explicitly excluded from the `worker-audit-` namespace; their audit trail (if any) is the orchestration skill's concern, not this skill's.
