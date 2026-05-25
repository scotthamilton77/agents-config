# prgroom CLI — Data View

> **Up**: [index](index.md)
> **Previous (reading order)**: [C4 L3 — Lifecycle](c4-l3-lifecycle.md)
> **Next (reading order)**: [C4 Deployment](c4-deployment.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md) — Section 2 (state schema) + Section 4.6 (status output) + Section 5 (EscalationSink)

## Glossary

| Term | Meaning |
|---|---|
| `PRGroomingState` | The root persistent entity (§2). One per PR. Lives in the `prsession.Store` file adapter as JSON at `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`. |
| Canonical ownership | Which system is the source of truth for a piece of data. prgroom mirrors much of GitHub's PR state into the prsession store, but GitHub remains canonical for review state; the store is canonical only for prgroom's own lifecycle metadata (Phase, Round, Disposition, etc.). |
| `schema_version` | The integer carried on every `PRGroomingState`. MVP = `1`. Used by `internal/prsession` to dispatch read-time migrations or trip `STATE_SCHEMA_UNKNOWN`. |
| ER (Entity-Relationship) | The relational data view; here used for stateful entities with cardinalities. Mermaid `erDiagram`. |
| JSON contract | A flat dictionary shape exposed at a boundary (`prgroom status --json`, escalation events). Not a relational entity — represented inline as fenced JSON + a field table. |

## Purpose

Two complementary data views in one file:

1. **The persistent state schema** (`PRGroomingState` and its sub-entities) as an ER diagram. Shows the relationships, cardinalities, and key fields that drive the lifecycle. Source: §2.
2. **The boundary JSON contracts** — the shapes that leave the binary's process boundary and become other systems' inputs:
   - `prgroom status --json` output (§4.6) — consumed by future merge-gate components (`gmxo`, `td39`) plus operator inspection
   - `Escalation` (§5) — consumed by `EscalationSink` adapters (stderr / file / bd)
3. **The canonical-ownership boundaries** — which data lives where, and which system is authoritative when state inevitably drifts.

The data view answers: *what shapes does prgroom read, write, and emit; which of those are its own truth vs mirrored from external truth?*

## Persistent state ER diagram

```mermaid
erDiagram
    PRGroomingState ||--|| PRRef                : "has 1"
    PRGroomingState ||--|| QuiescenceState      : "has 1"
    PRGroomingState ||--o{ ReviewerState        : "has 0..N (keyed by Identity)"
    PRGroomingState ||--o{ ReviewItem           : "has 0..N (ordered list)"
    ReviewItem      ||--o| Disposition          : "has 0..1 (nil until fixLocked)"
    ReviewItem      ||--|| Identity             : "has 1 (per-kind)"

    PRGroomingState {
        int     SchemaVersion       "1 in MVP; bumped on incompatible change"
        PRPhase Phase               "idle | awaiting-review | fixes-pending | quiesced | human-gated | merged"
        int     Round               "CLI-observed push counter; bounded by MaxRounds"
        string  LastPollSHA         "last HEAD observed by pollLocked"
        string  LastPushedHeadSHA   "last HEAD pushed by THIS CLI"
        time    LastPolledAt        "UTC"
        time    LastActivityAt      "UTC; LastActivityAt for §4.1 idle_threshold"
        bool    HumanReviewLabelAdded "§4.7 dedup; reset on non-human-gated end-of-cycle"
        string  LastError           "structured §3.7 code; clears on successful cycle completion"
        bool    LifecycleEscalationFiled "per-cycle dedup for lifecycle-tier EscalationSink emits"
    }

    PRRef {
        string Owner   "GitHub owner / org"
        string Repo    "GitHub repo name"
        int    Number  "PR number"
    }

    ReviewerState {
        string         Identity        "gh login or bot id (map key)"
        ReviewerKind   Kind            "human | bot"
        ReviewerStatus Status          "not_requested | requested | in_progress | review_found | declined"
        bool           Required        "true gates G_REVIEWERS quiescence"
        time           LastRequestAt   "UTC; §4.1 review_start_timeout reference"
        time           LastReviewAt    "UTC; §4.1 review_finish_timeout reference"
        time           DeclinedAt      "UTC; set on transition to declined"
        string         DeclinedReason  "user-declined | timeout-no-start | timeout-stalled"
    }

    ReviewItem {
        ItemKind Kind            "review_thread | review_summary | issue_comment"
        string   Author          "gh login of comment author"
        string   BodyExcerpt     "first 200 chars"
        time     SeenAt          "first observed by pollLocked"
        string   ClusterID       "set by clusterLocked; empty = unclustered"
        bool     Replied         "set by replyLocked"
        bool     Resolved        "review_thread only; set by resolveLocked"
        string   DuplicateOfGHID "set if Contract A clustered as duplicate"
    }

    Identity {
        string GHID             "gh's stable id; (Kind, GHID) is natural key"
        string ThreadID         "GraphQL node id; review_thread only"
        int    ReplyToCommentID "review_thread only"
        int    IssueCommentID   "issue_comment only"
    }

    Disposition {
        DispositionKind Kind            "fixed | already_addressed | skipped | deferred | wont_fix | escalated | failed"
        string          Rationale       "required for skipped|deferred|wont_fix|failed; user-facing for soft kinds"
        string_array    Commits         "SHAs for fixed + already_addressed"
        string          ResponsePath    "path to fix-agent-authored response text"
        string          Gate            "full | lite — recommended gate the fix agent thought necessary"
        bool            EscalationFiled "escalated only; per-cycle dedup"
        time            DecidedAt       "UTC"
        string          DecidedBy       "agent CLI id (e.g. claude -p sonnet[1m]) or human:<login>"
    }

    QuiescenceState {
        string CIState     "success | pending | failure | absent — G_CI gate input for LastPushedHeadSHA"
        time   QuiescedAt  "UTC; set when phase transitions to quiesced"
    }
```

### Cardinality notes

- `PRGroomingState` is the aggregate root; everything else is owned by it. There are no cross-aggregate relationships.
- `ReviewerState` map keys (`Identity` field) are unique per state — `map[string]ReviewerState` in Go. In MVP the map typically holds 1-2 entries (`"copilot"`, maybe `"alice"`).
- `ReviewItem` list is ordered by `SeenAt` (append-only growth as `pollLocked` discovers new comments).
- `Disposition` is a **pointer** field on `ReviewItem` — `nil` is the explicit "not yet processed" state. Once set, it's not unset (the lifecycle only forward-resolves dispositions).
- `Identity` is shape-polymorphic by `Kind`: only `review_thread` carries `ThreadID` + `ReplyToCommentID`; only `issue_comment` carries `IssueCommentID`. `GHID` is always populated. The §2 spec notes this is enforced by runtime validation, not by separate struct types (the single-struct + discriminator shape is the MVP default for JSON-marshal simplicity).

## Canonical-ownership boundaries

prgroom mirrors much of GitHub's PR state into the local prsession store. But mirroring is not authority — when the two disagree, GitHub wins for review state and prgroom wins for its own lifecycle metadata.

```mermaid
flowchart LR
    subgraph PG["prgroom-canonical (prsession state file)"]
        P1[Phase + Round + LastError]
        P2[Per-item Disposition + Rationale + Commits + DecidedBy]
        P3[Per-item Replied + Resolved flags]
        P4[Per-item ClusterID]
        P5[HumanReviewLabelAdded dedup flag]
        P6[LastActivityAt + QuiescedAt]
        P7[Per-reviewer LastRequestAt + LastReviewAt + DeclinedReason]
    end

    subgraph GH["GitHub-canonical (PR + reviews + threads)"]
        G1[PR open / merged / closed state]
        G2[Comment / review / thread bodies + authors + timestamps]
        G3[Thread resolved state]
        G4[Reviewer requested / submitted state]
        G5[CI check-runs / statuses]
        G6[Labels including human-review-required]
    end

    subgraph Git["Git-canonical (operator's worktree + remote)"]
        T1[Commit SHAs + commit graph]
        T2[Branch refs]
        T3[Worktree HEAD]
    end

    P3 -.->|"mirror; GH wins on conflict"| G3
    P2 -.->|"prgroom-canonical (decision); references commits Git-canonical"| T1
    G6 -.->|"prgroom writes; GH stores"| P5
```

### Tie-breakers when state drifts

| Conflict | Winner | Resolution |
|---|---|---|
| `state.Items[i].Resolved == true` but GitHub thread is unresolved | GitHub | Next `pollLocked` observes; flips `Resolved=false`; `resolveLocked` may re-resolve |
| `state.Reviewers[r].Status == in_progress` but no recent activity per `pollLocked` fetch | GitHub-observed | `evaluate_reviewer_timeouts` re-evaluates and may flip to `declined` |
| PR HEAD SHA != `state.LastPollSHA` | GitHub | `pollLocked` updates; Round++ via SHA-transition attribution if `LastPushedHeadSHA` doesn't match |
| PR has `human-review-required` label but `state.HumanReviewLabelAdded == false` | GitHub-observed | prgroom does NOT clear the flag mismatch — label is a write-only output from prgroom, not a read input (the label is consumed by `gmxo`/`td39`, not by prgroom itself) |
| `state.LastError != ""` but a successful cycle just completed | prgroom | End-of-cycle resolver clears `LastError` on writing a non-human-gated phase |

### Explicit non-ownership

- prgroom does NOT own commit content. The fix agent commits to the worktree; git owns the commit graph; prgroom only references commits by SHA in `Disposition.Commits`.
- prgroom does NOT own reviewer identity beyond the gh-login string. Whether `Identity="copilot"` is actually GitHub Copilot or a custom bot or a typo is GitHub's problem.
- prgroom does NOT own the `human-review-required` label semantics. It writes the label; it does not read or wait on it. Future merge-gate components (`gmxo`, `td39`) consume the label as their merge-block signal.

## Boundary JSON contract #1 — `prgroom status --json` (§4.6)

The output of `prgroom status <pr> --json`. Computed per-query from `PRGroomingState` + a small live gh API enrichment (label state, PR-approval reviews). Stability commitment per §4.6: **adding fields is non-breaking; removing or renaming is breaking and requires a version-bumped envelope**.

```json
{
  "pr": 42,
  "phase": "quiesced",
  "last_error": "",
  "round": 2,
  "reviewers": [
    {"login": "github-copilot[bot]", "required": true, "is_bot": true, "status": "review_found", "declined_reason": ""},
    {"login": "alice", "required": false, "is_bot": false, "status": "in_progress", "declined_reason": ""}
  ],
  "ci_state": "success",
  "items_summary": {"fixed": 3, "already_addressed": 1, "wont_fix": 0, "escalated": 0, "failed": 0, "skipped": 0, "deferred": 0},
  "last_activity_at": "2026-05-25T14:32:11Z",
  "quiesced_at": "2026-05-25T14:42:11Z",
  "merge_gates": {
    "phase_is_quiesced": true,
    "last_error_clear": true,
    "no_blocker_items": true,
    "human_review_satisfied": false
  },
  "human_review": {
    "required": true,
    "satisfied_by": null,
    "candidates_seen": []
  },
  "auto_merge_eligible": false
}
```

| Field | Source | Notes |
|---|---|---|
| `pr` | `state.PR.Number` | |
| `phase` | `state.Phase` | One of the 6 phase enum values |
| `last_error` | `state.LastError` | Empty string = clean |
| `round` | `state.Round` | CLI-observed push counter |
| `reviewers[]` | `state.Reviewers` map | Sorted by login for deterministic output |
| `ci_state` | `state.Quiescence.CIState` | `success` / `pending` / `failure` / `absent` |
| `items_summary` | aggregation over `state.Items` | Counts per `Disposition.Kind` |
| `last_activity_at` | `state.LastActivityAt` | RFC3339 UTC |
| `quiesced_at` | `state.Quiescence.QuiescedAt` | Empty string if not quiesced |
| `merge_gates.phase_is_quiesced` | `state.Phase == quiesced` | Derived per-query |
| `merge_gates.last_error_clear` | `state.LastError == ""` | Derived per-query |
| `merge_gates.no_blocker_items` | no item with `Disposition.Kind ∈ {escalated, failed}` | Derived per-query |
| `merge_gates.human_review_satisfied` | `NOT human_review.required OR human_review.satisfied_by != null` | Derived per-query |
| `human_review.required` | `hasLabel("human-review-required")` from live gh fetch | Source: GitHub, not state |
| `human_review.satisfied_by` | first match: `"label"` if `hasLabel("human-approved")`; `"approval:<login>"` if any non-bot review is APPROVED; else `null` | Source: GitHub |
| `human_review.candidates_seen` | All examined PR-approval candidates with bot-filter outcome | For operator debuggability: "why didn't approval X count?" |
| `auto_merge_eligible` | AND of the four `merge_gates` fields | Derived per-query |

### Stability and versioning

The shape above is the §4 stable contract. Consumers (`gmxo`, `td39`, operator scripts) may rely on it. Adding fields is non-breaking. Removing or renaming requires a version-bumped envelope (deferred to `gmxo`/`td39` brainstorm — not designed in MVP).

## Boundary JSON contract #2 — `Escalation` (§5)

Emitted by `escalate_if_needed` (per-item) and `request_human_review_if_needed` (lifecycle gate) via the `EscalationSink` interface. Three adapters consume the same shape:

```go
package escalation

type Severity string
const (
    SeverityInfo  Severity = "info"
    SeverityWarn  Severity = "warn"
    SeverityBlock Severity = "block"
)

type Escalation struct {
    PR       PRRef                  // copy of state.PR
    Reason   string                 // free-form, public-safe
    Item     *prsession.ReviewItem  // optional; the item that triggered the escalation
    Severity Severity               // info | warn | block
}

type Sink interface {
    Emit(Escalation) error
}
```

Wire-format example (`file` adapter — one JSON line per escalation):

```json
{
  "pr": {"owner": "scotthamilton77", "repo": "agents-config", "number": 42},
  "reason": "item escalated to human review — fix agent could not converge on cluster c3",
  "item": {
    "kind": "review_thread",
    "identity": {"gh_id": "PRR_kgABC123", "thread_id": "PRRT_kgABC456", "reply_to_comment_id": 789012},
    "author": "github-copilot[bot]",
    "body_excerpt": "Consider refactoring this loop to use a builder pattern...",
    "cluster_id": "c3",
    "disposition": {"kind": "escalated", "rationale": "design choice spans 3 files; outside agent's confident scope", "decided_at": "2026-05-25T14:30:00Z", "decided_by": "claude -p sonnet[1m]"}
  },
  "severity": "warn"
}
```

### Adapter behaviour per sink

| Sink | Wire format | Side-effects |
|---|---|---|
| **stderr** (default) | Pretty-print human-readable lines | Visible inline in operator's shell |
| **file** (`--escalation-file <path>`) | One JSON line per event (append-only) | External watchers / cron can tail |
| **bd** (`--bd-bead <id>` or `PRGROOM_BD_BEAD` env) | Adds `human` label + appends notes | Parallels current autonomous Skill A behaviour |

### Severity assignment

| Triggering condition | Severity |
|---|---|
| Per-item `Disposition.Kind == escalated` | `warn` |
| Per-item `Disposition.Kind == failed` (Contract B audit failure) | `warn` |
| `state.LastError == LIFECYCLE_HARD_CAP_EXCEEDED` (§3.5) | `block` |
| `state.LastError ∈ {STATE_CORRUPT, STATE_SCHEMA_UNKNOWN}` | `block` |
| Future: deferred-from-spec advisories | `info` |

### Sink failure handling

If `Sink.Emit(...)` returns an error (stderr write failure, bd-adapter API blip), the failure is swallowed (best-effort emit). The corresponding `EscalationFiled` / `LifecycleEscalationFiled` flag is **NOT** set on Sink error, so the next invocation re-attempts the emission for the same item / lifecycle gate. Persistent Sink failures produce repeated retry attempts but never block lifecycle progression.

Sinks MUST be dedup-aware on the receiving end — bd-adapter uses label-only emit or content-hash dedup on notes; stderr accepts duplicates as extra log lines.

## Auxiliary persistent data

Two append-only artifacts live alongside the per-PR state files:

| File | Path | Contents |
|---|---|---|
| Token-usage log | `$XDG_STATE_HOME/prgroom/usage.jsonl` | One line per agent invocation: `{ts, pr, contract, provider, model, input_tokens, output_tokens, duration_ms, outcome}`. MVP: capture only; no aggregation. |
| Escalation file log (optional) | `<path>` from `--escalation-file` | One JSON line per `Escalation` event. Used by external watchers. |

Neither file is part of `prsession.Store` — they are output streams owned by `internal/agent` and `internal/escalation` respectively.

## What this diagram does NOT show

- **Per-verb state-write atomicity contracts.** That's the [`c4-l3-prsession.md`](c4-l3-prsession.md) concern (stub) — the `prsession.Store` interface + mktemp+rename + flock semantics.
- **Schema migration plumbing.** Versions, migration registry, `STATE_SCHEMA_UNKNOWN` trip — see [`c4-l3-prsession.md`](c4-l3-prsession.md) (stub).
- **The actual GitHub API field shapes prgroom polls.** `internal/gh` wraps `go-gh`; the per-endpoint payload shapes are go-gh's documented surface, not prgroom's contract.
- **Cross-PR enumeration data** — `prgroom sweep`'s output. Not designed at the data-contract level in MVP; `sweep` writes per-PR exit codes to its own stderr.
- **The §3.7 error-code registry itself.** This file references `LastError` as a string; the full code list with what/why/how lives in source spec §3.7.

## Cross-references

- **Previous**: [C4 L3 — Lifecycle](c4-l3-lifecycle.md) — the components that read / write this data
- **Next (reading order)**: [C4 Deployment](c4-deployment.md) — where this data physically lives on disk
- **Related stubs**: [`c4-l3-prsession.md`](c4-l3-prsession.md) (state store adapters), [`c4-l3-agent-dispatch.md`](c4-l3-agent-dispatch.md) (token-usage emitter)
- **Source spec**: [Section 2 — `prsession.Store` interface + state schema](../../plans/2026-05-12-prgroom-cli-design.md), [Section 4.6 Auto-merge eligibility contract](../../plans/2026-05-12-prgroom-cli-design.md), [Section 5 — Agent dispatch internals](../../plans/2026-05-12-prgroom-cli-design.md) (EscalationSink section)
