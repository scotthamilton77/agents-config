# Spec: `pr-comment-fix-report-v1` — per-agent extension for `pr-comment-fixer-team`

Inherits the shared core from [`worker-report-v1.md`](worker-report-v1.md).
This spec adds the agent-specific extension fields required when the
`pr-comment-fixer-team` worker emits its YAML report.

## Summary

The `pr-comment-fixer-team` worker is dispatched once per PR review
comment by the `wait-for-pr-comments` skill. It classifies the comment
(FIX/SKIP/ESCALATE), takes one of three actions
(COMMITTED_FIX/ALREADY_ADDRESSED/NO_ACTION), and writes a single
structured YAML report to a caller-provided absolute path.

The worker is beads-agnostic: it has no bd subcommand calls in its
prompt, no `.beads` references, and no branching on whether bead infra
exists. The caller (the PR-comments skill) owns the tracker lifecycle;
the worker reports outcome via the per-agent YAML extension fields.

## Extension fields

| Field | Type | Required? | Notes |
|-------|------|-----------|-------|
| `comment_id` | `string` | required | Stable identifier for the PR review comment that this dispatch handled. |
| `comment_thread_id` | `string` | required | Identifier of the review thread containing the comment. |
| `classification` | enum `FIX` / `SKIP` / `ESCALATE` | required | Worker's verdict on whether the comment is actionable. |
| `action` | enum `COMMITTED_FIX` / `ALREADY_ADDRESSED` / `NO_ACTION` | required | What the worker actually did. |
| `fix_summary` | `string` | required when `action == COMMITTED_FIX` | One-line description of the fix. |
| `commit_sha` | `string` | required when `action == COMMITTED_FIX` | Full 40-char SHA of the fix commit. |
| `already_addressed_by_sha` | `string` | required when `action == ALREADY_ADDRESSED` | Full 40-char SHA of the prior commit that resolved the concern. |
| `escalation_reason` | `string` | required when `classification == ESCALATE` | Crisp explanation of what the worker needed but could not obtain. |

## Classification / action matrix

| `classification` | Allowed `action` |
|------------------|------------------|
| `FIX` | `COMMITTED_FIX` (the worker landed a fix) or `ALREADY_ADDRESSED` (a prior commit already fixed it) |
| `SKIP` | `NO_ACTION` |
| `ESCALATE` | `NO_ACTION` (worker bails; caller takes the escalation path) |

Any other combination is malformed.

## Status semantics

| `status` | When the worker emits it |
|----------|-------------------------|
| `complete` | Classification + action were emitted and the YAML is well-formed. All non-ESCALATE outcomes reach `complete`. |
| `needs_human` | `classification == ESCALATE` — worker could not make the call. |
| `failed` | Worker could not run to completion (e.g., repo path invalid, tools unavailable). |

## Report example

```yaml
schema_version: "worker-report-v1"
agent: "pr-comment-fixer-team"
status: "complete"
mode: "pr-comment-fix"
comment_id: "ic-9876"
comment_thread_id: "rt-12345"
classification: "FIX"
action: "COMMITTED_FIX"
fix_summary: "Tighten null-check in retryOperation"
commit_sha: "0123456789abcdef0123456789abcdef01234567"
evidence: {}
escalations: []
discovered_work: []
commits:
  - "0123456789abcdef0123456789abcdef01234567"
```

## Orchestrator expectations

- The caller allocates the report path. In a beads workflow the path
  is `<repo-root>/.beads/worker-audit/<step-bead-id>/pr-comment-fixer-team.yaml`;
  outside beads, the caller may pick any absolute path. The worker
  writes to whatever path the caller hands it — it does not branch on
  beads infrastructure presence.
- `evidence` is `{}` for the single-comment fix path; combined-gate
  verification across all fixes is the caller's responsibility (Phase 5a
  of `wait-for-pr-comments`), not the per-comment worker's.
- The caller stamps the audit label (when running under beads) and
  handles thread replies / resolution downstream.

## Runtime-required fields

| Spec | Runtime-required (orchestrator) | On miss |
|------|---------------------------------|---------|
| `pr-comment-fix-report-v1` | `status`, `classification`, `action` | synthesize per shared-core §4.1 |

All other extension fields are contract obligations enforced by review,
not by the runtime.
