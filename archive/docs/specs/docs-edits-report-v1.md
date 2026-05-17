# Spec: `docs-edits-report-v1` — per-agent extension for `docs-edits-team`

Inherits the shared core from [`worker-report-v1.md`](worker-report-v1.md).
This spec adds the agent-specific extension fields required when the
`docs-edits-team` worker emits its YAML report.

## Summary

The `docs-edits-team` worker runs the `apply-edits` stage of the
`docs-only` formula. It applies documented prose, spec, and config
changes inside a worktree, commits the result, and writes a single
structured YAML report to a caller-provided absolute path. The shared
core defines completion status, evidence, escalations, discovered work,
and commits. This per-agent spec adds the four fields below.

## Extension fields

| Field | Type | Required? | Notes |
|-------|------|-----------|-------|
| `files_changed` | `[string]` | required | List of paths (repo-root-relative) modified by this dispatch. Empty list when the worker recognized the bead was misrouted and applied no edits. |
| `commit_sha` | `string` | required | Full 40-char SHA of the single commit produced by this dispatch. Empty string when the worker applied no edits (mirrors the shared-core `commits: []` convention). |
| `summary` | `string` | required | One-line description of the edits applied. |
| `skipped_items` | `[{path, reason}]` | required | Items the worker deliberately did NOT apply, with a path and a reason. Use `[]` when nothing was skipped. |

## Status semantics

| `status` | When the worker emits it |
|----------|-------------------------|
| `complete` | Edits were applied (or correctly determined to be no-ops) and the commit landed cleanly. |
| `needs_human` | The bead requires changes that would introduce code needing a test harness (the docs-only formula has no red-tests stage), or the documented spec is internally contradictory. Populate `escalations` with the specific reason. |
| `failed` | The worker could not proceed (e.g., worktree missing, repo state inconsistent). |

## Report example

```yaml
schema_version: "worker-report-v1"
agent: "docs-edits-team"
step_bead_id: "agents-config-mol-abcdef"
source_bead_id: "agents-config-7bk.30"
mode: "docs-only-apply-edits"
status: "complete"
evidence: {}
files_changed:
  - "docs/specs/foo.md"
  - "README.md"
commit_sha: "0123456789abcdef0123456789abcdef01234567"
summary: "Reword §3 of foo.md to align with new terminology"
skipped_items: []
escalations: []
discovered_work: []
commits:
  - "0123456789abcdef0123456789abcdef01234567"
```

## Orchestrator expectations

- The orchestrator allocates the report path under
  `<repo-root>/.beads/worker-audit/<step-bead-id>/docs-edits-team.yaml`
  per `worker-report-v1` §2.
- The orchestrator stamps the audit label
  `worker-audit-docs-edits-team` on the step-bead after the worker
  exits (success or synthesized crash report).
- `evidence` is `{}` because the docs-only formula has no test, build,
  lint, or typecheck blocks. The derived gate roll-up is `n/a`.

## Runtime-required fields

| Spec | Runtime-required (orchestrator) | On miss |
|------|---------------------------------|---------|
| `docs-edits-report-v1` | `status` | synthesize per shared-core §4.1 |

All other extension fields are contract obligations enforced by review,
not by the runtime.
