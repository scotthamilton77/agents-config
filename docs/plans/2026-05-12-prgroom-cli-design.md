# Design: `prgroom` CLI — replace wait-for-pr-comments + reply-and-resolve-pr-threads

**Status:** Draft — brainstorming in progress (Sections 1, 2, 3, 5, 8 fleshed out; Sections 4, 6, 7 sketched).
**Date:** 2026-05-12
**Related beads:**
- `agents-config-d73c` (Optimize wait-for-pr-comments and reply-and-resolve-pr-threads skills) — **superseded by this design**
- `agents-config-gmxo` (Redesign merge-gate bead: sibling-with-dep model) — prerequisite for the broader v2 work; **not** required for this MVP
- `agents-config-vaac` (Milestone M3) — parent milestone

---

## Problem

The current PR-review-response surface consists of two skills and 22 supporting bash scripts:

- `wait-for-pr-comments` — Skill A, ≈800 lines of prose, 9 phases
- `reply-and-resolve-pr-threads` — Skill B, ≈330 lines of prose, 4 phases
- 22 helper bash scripts shared between them
- JSON inventory contract on disk at `~/.claude/state/pr-inventory/`

The bulk of the *actual work* (gh API calls, git ops, JSON manipulation) is already in bash. What remains agentically expensive is the **phase-orchestration glue**: every PR-review cycle loads the skill prose on top of the implementer's already-bloated context window, then walks through phase logic, dispatches subagents, audits their reports, manages crash-recovery branch tables, and so on. This is the cost we have not yet been able to push out of the agent.

## Goal

Reduce the PR-grooming agentic-token cost by an order of magnitude by:

1. Moving phase orchestration out of skill prose and into a compiled Go binary (`prgroom`).
2. Thinning the existing skills to one-line wrappers that shell out to the binary.
3. Confining agent invocations to *named hand-off points* — comment classification, fix-implementation, escalation judgment — invoked via subprocess shell-out from the CLI, each with fresh agent context.
4. Persisting state behind a `prsession.Store` interface so recovery, idempotency, and inspection are uniform regardless of caller (skill, cron, manual invocation, or — later — executable-bead).

## Non-goals (MVP)

- Create-PR, merge, worktree cleanup (stay in `finishing-a-development-branch` and `merge-and-cleanup` skills/formulas for now)
- Brainstorm/implement-bead formula changes
- Executable-bead primitive (separate sub-design; blocks on this MVP)
- gmxo's structural changes (separate sub-design; prerequisite for v2)
- bd adapter for state (v2; file-only in MVP)

---

## Section 1 — Architecture overview

```
┌──────────────────────────────────────────────────────────┐
│ bd (existing)  ──  work tracking, dep graph              │
└──────────────────────────────────────────────────────────┘
                          │
                          │  (later) executable-bead dispatch
                          ▼
┌──────────────────────────────────────────────────────────┐
│ prgroom (Go binary, this MVP)                            │
│   cmd/prgroom/          cobra root + verbs               │
│   internal/gh/          go-gh wrapper                    │
│   internal/git/         git ops (worktree-aware)         │
│   internal/prsession/   Store interface (PR session)     │
│     file/                 default adapter (JSON/disk)    │
│     bd/                   bd-notes adapter (later)       │
│   internal/agent/       subprocess to claude/codex       │
│   internal/lifecycle/   poll→cluster→fix→push→…          │
│   internal/quiescence/  readiness probability + thresholds│
└──────────────────────────────────────────────────────────┘
                          │
                          │ subprocess shell-out (fresh agent context)
                          ▼
        ┌──────────────────────────────────┐
        │ claude -p   /   codex exec       │
        └──────────────────────────────────┘
```

### Three usage patterns

| Pattern | Caller | CLI invocation |
|---|---|---|
| **Interactive** | User in chat, via thinned skill | `prgroom run <pr> --interactive` |
| **Autonomous** | Cron / `/loop` session / GHA | `prgroom run <pr> --autonomous` (or `prgroom sweep <repo>`) |
| **Executable-bead** (v2) | bd-side dispatcher | Bead payload string: `prgroom run --pr 123 --autonomous` |

### Locked decisions

- **Language:** Go (single static binary, native `github.com/cli/go-gh/v2` library reuses `gh auth` state, sub-100ms cold start). **Tooling note:** this is Scott's first end-to-end Go project; the implementation plan must begin with a *toolchain assessment* step that inventories what's installed on the dev machine (`go version`, `golangci-lint`, `gofumpt`, `govulncheck`, `delve`, `air`/hot-reload if desired, VS Code or other editor Go extensions) and installs/configures whatever's missing before any production code is written.
- **CLI framework:** `cobra` (consistency with `gh` and `bd`)
- **Repo placement:** same `agents-config` repo, new top-level `cmd/prgroom/` and `internal/` tree, Go module rooted at repo root
- **Agent boundary:** CLI shells out to `claude -p` / `codex exec` as subprocess. Synchronous. Each invocation = fresh agent context.
- **Command shape:** subcommand verbs (poll, cluster, fix, push, rereview, reply, resolve, resolve-escalated, wait, status, run, sweep)
- **MVP scope:** equivalent of `wait-for-pr-comments` + `reply-and-resolve-pr-threads`; excludes create-PR, merge, cleanup, and bead-lifecycle helpers
- **Migration path:** incremental. Phase 1 absorbs `wait-for-pr-comments`; Phase 2 absorbs `reply-and-resolve-pr-threads`. Each skill thins to a one-line invocation as functionality lands in the CLI.

### Today → tomorrow translation

| Today | Tomorrow |
|---|---|
| `wait-for-pr-comments` skill (~800 lines + 12 helpers) | Skill body: `bash: prgroom run <pr>` + thin report-parsing |
| `reply-and-resolve-pr-threads` skill (~330 lines + 10 helpers) | Absorbed into `prgroom reply` + `prgroom resolve` |
| JSON inventory at `~/.claude/state/pr-inventory/` | `prsession.Store` file-adapter default; bd-adapter optional (v2) |
| 22 bash scripts | `internal/*` modules of `prgroom`, with proper unit + integration tests |
| Skill prose enforces phase order, retries, recovery | CLI orchestrates phases; recovery is a re-invocation |
| `Agent({...})` subagent dispatch from skill | `prgroom` shells out to `claude -p` (fresh context) |

### MVP verb set

| Verb | Purpose |
|---|---|
| `poll <pr>` | Query gh for new items (comments, reviews, CI status); update state. Short-circuits if SHA unchanged. |
| `cluster <pr>` | Group unprocessed items into fix-bundles for cohesive fix work. Cheap agent; no per-item disposition decided here. |
| `fix <pr>` | For each cluster, dispatch a fix agent that decides per-item disposition (fixed / already_addressed / skipped / deferred / wont_fix / escalated / failed) AND implements the fix when warranted. Stronger model. |
| `push <pr>` | Push any accumulated commits the fix agent produced. |
| `rereview <pr>` | Re-request review from required bot reviewers (the remove/add dance under the hood). |
| `reply <pr>` | Render and post replies for every item per template matrix + agent-authored response files. |
| `resolve <pr>` | GraphQL `resolveReviewThread` for every `review_thread` whose disposition is `fixed` or `already_addressed`. |
| `resolve-escalated <pr> <item-id> --as <disposition> [--rationale <text>]` | Human-initiated reclassification of an `escalated` item; flips it to a terminal disposition and lets the lifecycle continue. |
| `wait <pr>` | Sleep/poll until SHA changes or quiescence threshold trips. |
| `status <pr>` | Print current state for inspection. |
| `run <pr>` | Aggregate: orchestrates the above in sequence with iteration until quiescent or hard cap. |
| `sweep <repo>` | Cross-PR autonomous mode: list open PRs, invoke `run` for each (serially, per-PR locks, failure-isolated; see §3.2 sweep paragraph). (Optional MVP if cheap.) |

### Precondition gating (cross-cutting requirement)

**Every verb performs a precondition check before doing any work.** Preconditions fall into three tiers:

1. **Self-healable** — the missing input is something the CLI itself can produce by running deterministic prework. The verb auto-runs the prework, then re-evaluates. Example: `prgroom fix <pr>` invoked with no state → auto-run `poll` and `cluster`, then re-check fix preconditions. This is the default; pass `--no-prework` to make precondition failures terminal instead.
2. **User-error** — invalid arguments, no PR detected, malformed PR ref. Always terminal. Exit non-zero immediately.
3. **Terminal-no-work** — preconditions are satisfied but there's nothing to do (e.g., zero unfixed items). Exit `0` with a status message; this is success, not error.

When a precondition failure is NOT self-healable, the CLI produces a structured stderr error that BOTH humans and agents can parse and act on. Each failure carries:

1. **What is missing** (e.g., `no PR detected from current branch`)
2. **Why it's needed** (e.g., `every verb requires a PR ref`)
3. **How to satisfy** (e.g., `pass <pr-number-or-url> or run from a branch with an open PR`)
4. **A machine-readable error code** (e.g., `PRECONDITION_NO_PR_DETECTED`)

Non-zero exit with structured stderr:

```
error: PRECONDITION_NO_PR_DETECTED
  what: no PR found for the current branch or via positional arg
  why:  every verb requires a PR ref
  how:  pass <pr-number-or-url> or run from a branch with an open PR
```

Stdout remains reserved for normal verb output (status JSON, etc.) so agents can parse stderr independently. The full error-code registry is owned by §3.7.

---

## Section 2 — `prsession.Store` interface + state schema

### Interface

```go
package prsession

type PRRef struct {
    Owner  string
    Repo   string
    Number int
}

// Store persists a single PR's grooming session state. The interface is
// deliberately a typed key-value store with locking — NOT a tracker (no
// change-detection, no event-emission, no CAS predicates). See
// docs/architecture/prgroom/c4-l1-context.md for the contrast with PDLC's
// WorkTracker, which is a different shape entirely.
type Store interface {
    // Returns ErrNotFound if no state for this PR yet.
    Read(PRRef) (*PRGroomingState, error)

    // Atomic full-state replacement. Caller does read-modify-write.
    Write(PRRef, *PRGroomingState) error

    // Exclusive lock for the duration of one verb's work.
    // releaseFn MUST be called (even on error) — defer it.
    Lock(PRRef) (releaseFn func(), err error)

    // List all PRs with tracked state. Used by `sweep`.
    List() ([]PRRef, error)

    // Tombstone state after merge / abandon.
    Delete(PRRef) error
}
```

### Adapters

| Adapter | When | Storage | Lock | Atomicity |
|---|---|---|---|---|
| **`file`** | MVP (default) | `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`) | `flock(2)` on the file | `mktemp` + `rename(2)` on same FS |
| **`memory`** | Tests only (not in production builds) | In-process `map[PRRef]*PRGroomingState` | `sync.Mutex` per ref | Immediate |
| **`bd`** | v2 | Linked bead's `notes` field (cap ~65KB; externalize to file w/ path-ref above that). Linkage label: `for-pr-<owner>-<repo>-<n>`. | Transient bd label `prgroom-lock-<pid>` (written/removed in single `bd update`) | `bd update --notes <new>` (replaces entire field) |

Selection at runtime: `--store file` (default), `--store bd` (v2), or env var `PRGROOM_STORE`.

### State schema (`schema_version: 1`)

The CLI is the schema owner. We absorb the *information* from the old inventory schema but don't preserve its layout — there is no Skill A/B contract to honor. Named so other CLI-internal state (if any) is unambiguous.

```go
package prsession

type PRGroomingState struct {
    SchemaVersion       int             `json:"schema_version"`
    PR                  PRRef           `json:"pr"`
    Phase               PRPhase         `json:"phase"`
    Round               int             `json:"round"`
    LastPollSHA         string          `json:"last_poll_sha"`        // last HEAD observed by poll
    LastPushedHeadSHA   string          `json:"last_pushed_head_sha"` // last HEAD pushed by THIS CLI; distinguishes CLI vs external pushes for Round attribution (see §3.4)
    LastPolledAt        time.Time       `json:"last_polled_at"`
    LastActivityAt      time.Time       `json:"last_activity_at"`
    HumanReviewLabelAdded bool                     `json:"human_review_label_added,omitempty"`  // §4.7: dedup flag for auto-add of `human-review-required` PR label
    Reviewers           map[string]ReviewerState   `json:"reviewers"`            // keyed by reviewer Identity
    Items               []ReviewItem               `json:"items"`
    Quiescence          QuiescenceState            `json:"quiescence"`
    LastError           string                     `json:"last_error,omitempty"` // structured error code (§3.7) for the most recent terminal-tier failure; cleared on successful cycle completion
    LifecycleEscalationFiled bool                  `json:"lifecycle_escalation_filed,omitempty"` // per-cycle dedup for lifecycle-tier EscalationSink emits (cap-trip, terminal-user-error); reset to false when a new lifecycle gate fires
}
```

#### `PRPhase` — what the PR is *waiting on* (not what the CLI is doing)

**Phases describe the PR's state, not the CLI's current activity.** Verbs (`poll`, `cluster`, `fix`, …) are *activities* the CLI performs within or across a phase; a single phase may host many verb executions over its lifetime.

```go
type PRPhase string
const (
    PhaseIdle             PRPhase = "idle"              // no PR-side activity yet observed
    PhaseAwaitingReview   PRPhase = "awaiting-review"   // pushed; waiting for any reviewer to engage (covers initial AND re-review; Round disambiguates)
    PhaseFixesPending     PRPhase = "fixes-pending"    // feedback arrived; items not yet processed
    PhaseQuiesced         PRPhase = "quiesced"          // terminal: everything addressed; safe to merge (auto-mergeable when policy allows)
    PhaseHumanGated       PRPhase = "human-gated"       // terminal: human action required (escalation, hard cap, failed items)
    PhaseMerged           PRPhase = "merged"            // terminal: merged
)
```

`awaiting-initial-review` and `awaiting-rereview` are collapsed into a single `awaiting-review` phase — from the PR's perspective they're the same state ("nothing new since we last pushed"). The `Round` field on `PRGroomingState` distinguishes initial (1) from re-review (≥2) iterations.

#### Phase lifecycle

```
                      ┌──────────────────────────────┐
   first push  ─────► │       awaiting-review        │ ◄──────┐
                      └────────────────┬─────────────┘        │ (push fresh fixes → Round++)
                                       │ (reviewer engaged: review found / human comment)
                                       ▼                      │
                      ┌──────────────────────────────┐        │
                      │     fixes-pending         │        │
                      └────────────────┬─────────────┘        │
                                       │ (all items have a Disposition; all replied + resolved)
                                       ├──────────────────────┘  (any items committed → push → back to awaiting-review)
                                       │
                                       │ (no committed items this round; quiescence threshold trips)
                                       ▼
                      ┌──────────────────────────────┐
                      │         quiesced             │ ───► (auto-merge OR human merge → merged)
                      └──────────────────────────────┘
```

**Any phase may transition to `human-gated`** when:
- An item disposition is `escalated` and we're in interactive mode (or autonomous-with-no-autodefer)
- The re-review round hard cap (§3.5) is exceeded
- A `fix` subagent's audit fails irrecoverably

(Per §4.4, the `human-review-required` PR label is a merge constraint, not a lifecycle gate — it does NOT trigger `human-gated`.)

**`human-gated` exits** to `fixes-pending` (human resolved the issue and may have pushed) or to `merged` (human merged directly).

**`quiesced` is a true terminal that does NOT necessarily require human action.** A `quiesced` PR with all dispositions resolved, all replies posted, all FIX threads resolved, and policy-satisfied CI/coverage is **auto-merge-eligible** (the merge gate is a future capability outside MVP scope; see `td39`). When a policy criterion fails (e.g., CI red), `quiesced` is the "we did our part — human decides whether to ship" state.

**`quiesced` vs `human-gated` distinction:** both are terminal-for-the-CLI states. `quiesced` = "everything we can do is done; safe to merge under policy." `human-gated` = "human judgment is required to proceed." A `quiesced` PR may auto-merge; a `human-gated` PR cannot.

#### `ReviewItem` — one entry per reviewer-produced item

The three review kinds (`review_thread`, `review_summary`, `issue_comment`) share most fields and differ only in identity. Two viable shapes exist in idiomatic Go:

- **Single struct with discriminator + sub-structs** (MVP default) — JSON-friendly, single schema, kind-specific identity grouped in `Identity`, processing outcome in optional `*Disposition`. Runtime validation enforces "only ReviewThread items may have ThreadID set," etc.
- **Interface with three concrete types** — compile-time type safety; requires custom JSON marshal/unmarshal that switches on `kind`. **Deferred to Section 3** as an open implementation decision; if Section 3 demands stronger types, refactor before MVP ships.

**A single `Disposition` enum captures the item's outcome.** The cluster verb does not classify; the fix agent decides the disposition at the time it (potentially) does the work. One unified field is therefore cleaner than separating intent (classification) from result (fix outcome).

```go
type ItemKind string
const (
    KindReviewThread  ItemKind = "review_thread"
    KindReviewSummary ItemKind = "review_summary"
    KindIssueComment  ItemKind = "issue_comment"
)

type DispositionKind string
const (
    DispositionFixed           DispositionKind = "fixed"             // committed a new fix
    DispositionAlreadyAddressed DispositionKind = "already_addressed"// prior commit handles it
    DispositionSkipped         DispositionKind = "skipped"           // ack only, no work
    DispositionDeferred        DispositionKind = "deferred"          // valid but out of scope; tracked elsewhere
    DispositionWontFix         DispositionKind = "wont_fix"          // disagreement on a defensible basis
    DispositionEscalated       DispositionKind = "escalated"         // human must decide
    DispositionFailed          DispositionKind = "failed"            // attempted but couldn't address
)

// Disposition is a pointer on ReviewItem: nil = not yet processed.
// (Parallel to *FixOutcome being optional; uniform nil semantics for "no decision yet".)
type Disposition struct {
    Kind         DispositionKind `json:"kind"`
    Rationale    string          `json:"rationale,omitempty"`     // required for skipped|deferred|wont_fix|failed; user-facing for skipped|deferred|wont_fix
    Commits      []string        `json:"commits,omitempty"`       // SHAs for fixed + already_addressed; multiple commits per item permitted
    ResponsePath string          `json:"response_path,omitempty"` // path to fix-agent-authored response text (long-form replies)
    Gate         string          `json:"gate,omitempty"`          // full | lite — recommended gate the fix agent thought necessary
    EscalationFiled bool         `json:"escalation_filed,omitempty"` // escalated only
    DecidedAt    time.Time       `json:"decided_at"`
    DecidedBy    string          `json:"decided_by"`              // agent CLI id (e.g. "claude -p sonnet[1m]") or "human:<login>"
}

type ReviewItem struct {
    Kind     ItemKind `json:"kind"`
    Identity Identity `json:"identity"`

    // Common metadata
    Author      string    `json:"author"`
    BodyExcerpt string    `json:"body_excerpt"`   // first 200 chars
    SeenAt      time.Time `json:"seen_at"`

    // Clustering (set during the cluster verb; informs fix dispatch)
    ClusterID string `json:"cluster_id,omitempty"`  // empty = not yet clustered

    // Disposition (set when the fix verb processes this item; nil until then)
    Disposition *Disposition `json:"disposition,omitempty"`

    // Response tracking
    Replied         bool   `json:"replied"`
    Resolved        bool   `json:"resolved,omitempty"`           // review_thread only (and only when Disposition.Kind in {fixed, already_addressed})
    DuplicateOfGHID string `json:"duplicate_of_gh_id,omitempty"`
}

type Identity struct {
    GHID             string `json:"gh_id"`                         // gh's stable id; (Kind, GHID) is natural key
    ThreadID         string `json:"thread_id,omitempty"`           // GraphQL node id, review_thread only
    ReplyToCommentID int64  `json:"reply_to_comment_id,omitempty"` // review_thread only
    IssueCommentID   int64  `json:"issue_comment_id,omitempty"`    // issue_comment only
}
```

**Why `*Disposition` (pointer)?** `nil` is the explicit "no decision yet" state and survives JSON marshalling without ambiguity. Same convention used for any future optional sub-state. (Note: a similar nil-vs-empty choice could apply to `Classification` if we keep it; the unified `Disposition` makes the question moot.)

#### `ReviewerState` — generalized from `CopilotState`

Any PR can have **0..N reviewers** (Copilot today; codex bot tomorrow; codeowners if the team grows). They're tracked in a `map[string]ReviewerState` keyed by `Identity` (gh login or bot id). The map allows arbitrary reviewer cardinality without schema churn.

```go
type ReviewerKind string
const (
    ReviewerHuman ReviewerKind = "human"
    ReviewerBot   ReviewerKind = "bot"
)

type ReviewerStatus string
const (
    ReviewerNotRequested ReviewerStatus = "not_requested"
    ReviewerRequested    ReviewerStatus = "requested"
    ReviewerInProgress   ReviewerStatus = "in_progress"
    ReviewerReviewFound  ReviewerStatus = "review_found"
    ReviewerDeclined     ReviewerStatus = "declined"  // covers explicit pass AND §4 auto-decline (timeout-no-start / timeout-stalled); see ReviewerState.DeclinedReason
)

type ReviewerState struct {
    Identity       string         `json:"identity"`        // gh login or bot id
    Kind           ReviewerKind   `json:"kind"`
    Status         ReviewerStatus `json:"status"`
    Required       bool           `json:"required"`        // true = gates quiescence (PR cannot quiesce until this reviewer's Status ∈ {review_found, declined})
    LastRequestAt  time.Time      `json:"last_request_at"` // §4.1: start-timeout reference
    LastReviewAt   time.Time      `json:"last_review_at,omitempty"`  // §4.1: first observed engagement post-request; finish-timeout reference
    DeclinedAt     time.Time      `json:"declined_at,omitempty"`     // §4.1: set on transition to declined (any reason)
    DeclinedReason string         `json:"declined_reason,omitempty"` // §4.1: user-declined | timeout-no-start | timeout-stalled
}
```

**Required vs optional reviewers.** A reviewer's `Required` flag is the gate signal for quiescence. By default, Copilot is added as `Required=true` on PR creation (parallel to today's behavior). Future codeowners or codex-bot reviewers can be added with `Required=true` (gates quiescence) or `Required=false` (advisory — their absence/silence does not block quiescence). Section 4 (Quiescence model) consumes this flag.

**Migration shape from old `CopilotState`:** in MVP, the `Reviewers` map contains exactly one entry — `{"copilot": ReviewerState{Kind: ReviewerBot, ...}}` — preserving current behavior. The map shape just leaves room for v2+ expansion.

#### `QuiescenceState`

```go
type QuiescenceState struct {
    CIState    string    `json:"ci_state,omitempty"`     // §4.1: success | pending | failure | absent — G_CI gate input for state.LastPushedHeadSHA
    QuiescedAt time.Time `json:"quiesced_at,omitempty"`  // §4.2: set when phase transitions to quiesced
}
```

**Agent-contract callout (forward reference to Section 5):** the CLI's interactions with agent-CLIs (Contract A: cluster, Contract B: fix) need strict input/output contracts. Section 5 is the owner; the state schema above carries only the *results* (`ClusterID`, `Disposition`).

### Transactional model (verb-level + run-aggregate)

**Public verbs are locking wrappers; lifecycle work happens in lock-assuming internal functions.** Every top-level CLI verb (`poll`, `cluster`, `fix`, `push`, `reply`, `resolve`, `rereview`, `resolve-escalated`, `wait`, `status`) is implemented as a thin public function that acquires the PR lock, calls its internal lock-assuming counterpart, then releases. The internal functions are conventionally named with a `Locked` suffix (`pollLocked`, `clusterLocked`, etc.) and assume the caller already holds the PR lock for the duration of their work.

```go
// Public locking wrapper (one per verb)
func Poll(prRef PRRef) error {
    release, err := store.Lock(prRef)
    if err != nil { return err }
    defer release()
    return pollLocked(prRef)
}

// Lock-assuming internal lifecycle function
func pollLocked(prRef PRRef) error {
    state, err := store.Read(prRef)
    // ... mutate state in memory ...
    state.Phase = nextPhase
    state.LastActivityAt = time.Now().UTC()
    return store.Write(prRef, state)
}
```

**`run` is the only verb that acquires the lock once and calls multiple `*Locked` internals in sequence**, so `run` does not nest lock acquisitions on itself. See §3.3 for the full `run` algorithm.

Crash semantics: if the process dies between Lock and Write, the file-adapter lock is released (process-scoped); the on-disk state reflects the prior successful Write. **No partial states. No `crash_recovery` flag. Recovery = re-invoke.**

### Concurrency posture

- One-at-a-time per PR. Second invocation while one runs → non-zero exit with message `prgroom: another invocation holds the lock for <owner>/<repo>#<n> (pid <pid>)`.
- No queue. No lock-acquire timeout. Caller (cron, agent) retries on next cadence.
- The current skill's "concurrency-recovery branch table" evaporates because no partial writes can exist.

### Schema deliberately omits

- `crash_recovery` block (replaced by Phase + LastError + lock semantics)
- `polling.copilot_review_submitted_at` (folded into `Copilot.LastReviewAt`)
- Pre-rendered `reply_body` (rendered at `reply` verb time from current item state)
- Separate `partial`/`complete` write state (every write is complete)

---

## Section 3 — Lifecycle state machine

Section 2 defined the `PRPhase` values and sketched a high-level phase diagram. This section pins down every transition — which verb produces which phase change under which condition, how the `run` aggregate verb threads the lifecycle, the round-counter and hard-cap semantics, the runtime-failure tier model, and the full structured-error-code registry referenced from Section 1's precondition gating.

### 3.1 Phase state graph

Section 2's sketch expanded to label every edge with its `(verb, condition)` trigger. Every edge below is an autonomous CLI transition unless explicitly noted otherwise.

```
                          ┌─────────────────────────┐
   first invocation  ───► │          idle           │
                          └────────────┬────────────┘
                                       │ poll (first push observed via gh API)
                                       ▼
                          ┌─────────────────────────────────────────────┐
                          │              awaiting-review                │
              ┌─────────► │   Round disambiguates initial vs re-review  │ ────────┐
              │           └──────────────────┬──────────────────────────┘         │
              │                              │ poll (new reviewer item observed)  │
              │                              ▼                                    │
              │           ┌─────────────────────────────────────────────┐         │
              │           │              fixes-pending                  │         │
              │           └──┬──────────────────────┬───────────────────┘         │
              │              │                      │                             │
              │              │                      │ end-of-cycle:               │
              │ end-of-cycle:│                      │   zero commits pushed       │
              │  ≥1 commit   │                      │   AND quiescence            │
              │  pushed      │                      │   threshold trips (§4)      │
              │ (Round++,    │                      │                             │
              │  no cap trip)│                      ▼                             │
              └──────────────┘           ┌─────────────────────────┐              │
                                         │        quiesced         │              │
                                         │  (terminal-for-CLI;     │              │
                                         │   auto-merge-eligible   │              │
                                         │   when policy permits)  │              │
                                         └──┬──────────────────────┘              │
                                            │                                     │
                          ┌───── poll (PR closed via merge) ──────────────────────┘
                          │                 │
                          ▼                 │ poll (new reviewer item)
                  ┌──────────────┐          ▼
                  │    merged    │   (back to fixes-pending)
                  │  (terminal)  │
                  └──────────────┘
                          ▲
                          │ poll (PR closed via merge)
                          │
              ┌─────────────────────────────────────────────┐
              │                human-gated                  │
              │   (terminal-for-CLI; awaits human action)   │
              └────────────────────┬────────────────────────┘
                                   │ resolve-escalated, OR
                                   │ poll observes external push
                                   ▼
                          (back to fixes-pending)
```

**Note on merge transitions (omitted from the diagram for clarity):** every non-terminal phase (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, `human-gated`) transitions to `merged` when `pollLocked` observes the PR closed via merge. The diagram shows only the `quiesced → merged` and `human-gated → merged` edges; `awaiting-review → merged` and `fixes-pending → merged` are equally legal and enumerated in the §3.2 matrix `poll` row.

**Note on direct `idle → fixes-pending` (omitted from the diagram for clarity):** when the first `pollLocked` observes both ≥1 commit on the remote AND ≥1 reviewer item already filed (uncommon but legal — a reviewer commented during the bootstrap window before `prgroom` ran), the verb advances `idle → fixes-pending` directly, bypassing the `awaiting-review` step. This edge is enumerated in the §3.2 `poll`-from-`idle` row; the diagram shows only the typical `idle → awaiting-review → fixes-pending` path.

**Any non-terminal phase transitions to `human-gated` at end-of-cycle when** (priority order, applied by `resolve_end_of_cycle_phase` in §3.2):

- Hard cap would be exceeded by the next push (`Round >= MaxRounds` with queued fix commits)
- Any item has `Disposition.Kind == failed` produced by `CONTRACT_AUDIT_FAILED` or terminal-runtime failure (§3.6)
- Any item has unresolved `Disposition.Kind == escalated`
- A terminal-runtime failure occurred during the cycle

**Terminal-for-CLI phases:** `quiesced`, `human-gated`, `merged`. The CLI takes no further autonomous action; re-entry requires an external trigger observed by `poll`, or an operator-issued `resolve-escalated`.

**Graph-terminal phase:** `merged` only. Both `quiesced` and `human-gated` can re-enter `fixes-pending` when new reviewer activity or escalation resolution occurs.

### 3.2 Phase × verb transition matrix

For every `(current phase, verb invoked)`, the next phase and side effects are pinned. The matrix covers the **11 per-PR lifecycle verbs** (`poll`, `cluster`, `fix`, `push`, `reply`, `resolve`, `rereview`, `wait`, `resolve-escalated`, `status`, `run`). The optional `sweep` verb is a cross-PR aggregator outside this per-PR matrix; it iterates open PRs and invokes `run` for each, with no phase semantics of its own.

**`sweep` lock semantics and failure isolation (MVP):** `sweep` iterates open PRs **serially**, acquiring one PR's lock at a time via `store.Lock(pr)` exactly as a direct `run <pr>` invocation would. **There is no store-wide or cross-PR `sweep` lock** — each PR is independently lockable, so a separate `run <other-pr>` invocation initiated by another process or operator does not block `sweep` from making progress on remaining PRs. **Failures are isolated per-PR:** a non-zero exit from one PR's `run` invocation (any tier — `RUNTIME_TRANSIENT`, `RUNTIME_TERMINAL_USER`, `STATE_CORRUPT`, `RUNTIME_CANCELLED`, etc.) does NOT abort the sweep. `sweep` logs each failure to stderr (PR ref + exit code + first stderr line) and continues to the next PR. `sweep`'s own exit code is `0` if every PR's `run` reached a terminal-for-CLI or transient outcome without unhandled errors, non-zero only on `sweep`-level errors (e.g., `gh pr list` failure to enumerate open PRs at the start). Because `run --autonomous` blocks for the full lifecycle of each PR per §3.5, `sweep` over N PRs in `awaiting-review` may take O(N × per-PR-wait) to complete — concurrency caps and ordering policies are deferred to a later section.

**Default behavior is "with prework" (`PRECONDITION_SELFHEAL`).** Cells marked **precondition fail** show the terminal outcome you get with `--no-prework`. Under the default self-heal path (Section 1 cross-cutting precondition gating), the verb auto-runs the missing deterministic prework and re-evaluates rather than returning the precondition error. For example, `fix` invoked in `idle` with no clusters under the default self-heal path runs `poll` → `cluster` → retries `fix`, then transitions per the `fixes-pending` row. With `--no-prework`, it returns `PRECONDITION_NO_CLUSTERS` immediately. Cells marked **no-op** mean the verb returns success (exit 0) without state change.

**This matrix describes the public verb's behavior when invoked directly** (e.g., `prgroom fix <pr>` from the shell). The `run` aggregate verb (§3.3) gates internal `*Locked` lifecycle functions by phase and does not exercise the per-verb precondition self-heal path — `run` already orchestrates the prework sequence. When reconciling §3.2 and §3.3, the matrix is the **direct-invocation contract**; §3.3 is the **run-driven flow**.

| Verb | from `idle` | from `awaiting-review` | from `fixes-pending` | from `quiesced` | from `human-gated` | from `merged` |
|------|-------------|------------------------|----------------------|-----------------|--------------------|---------------|
| `poll` | observes first push → `awaiting-review`; observes reviewer item → `fixes-pending`; else no-op | observes reviewer item → `fixes-pending`; observes PR-closed → `merged`; observes external push → Round++ if SHA changed, stay; else no-op | observes new item → stay (item appended); observes PR-closed → `merged`; observes external push → Round++ if SHA changed, stay; else no-op | observes new item → `fixes-pending`; observes PR-closed → `merged`; observes external push → `awaiting-review` (Round++ per §3.4; pushLocked's ReviewerState flip applies); else no-op | observes new item → `fixes-pending`; observes PR-closed → `merged`; observes external push → `fixes-pending` (operator resolved gate; Round++ per §3.4); else no-op | terminal; no-op |
| `cluster` | `PRECONDITION_NO_ITEMS` | `PRECONDITION_NO_ITEMS` (by definition, `awaiting-review` has no items needing clustering; if `poll` had observed items the phase would already be `fixes-pending`) | sets `ClusterID` on unclustered items; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `fix` | `PRECONDITION_NO_CLUSTERS` | `PRECONDITION_NO_CLUSTERS` | sets `Disposition.Kind` per item (`fixed`/`already_addressed`/`skipped`/`deferred`/`wont_fix`/`escalated`/`failed`); may produce commits; **no phase change** here — phase resolution happens at end-of-cycle via the priority cascade (§3.2); contract-audit failures flip the affected item to `Disposition.Kind = failed` and the resolver promotes to `human-gated` via priority 3 | terminal; no-op | terminal; no-op | terminal; no-op |
| `push` | `PRECONDITION_NO_COMMITS` | uploads queued commits if any; **Round++** if ≥1 commit pushed; no phase change | uploads queued commits if any; **Round++** if ≥1 commit pushed; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `reply` | `PRECONDITION_NO_ITEMS` | **no-op** (exit 0; emits `PRECONDITION_NO_UNREPLIED` only under `--no-prework`) unless prior round left replies pending | renders templates + posts via gh API; marks `Replied=true`; no phase change | re-applies idempotently to unreplied items; no phase change | re-applies idempotently | terminal; no-op |
| `resolve` | `PRECONDITION_NO_ITEMS` | **no-op** (exit 0; emits `PRECONDITION_NO_UNRESOLVED` only under `--no-prework`) | resolves review-threads with `Disposition.Kind ∈ {fixed, already_addressed}` AND `Resolved == false`; marks `Resolved=true`; no phase change | re-applies idempotently | re-applies idempotently | terminal; no-op |
| `rereview` | `PRECONDITION_NO_ITEMS` | re-requests review for `Required=true` reviewers in `{not_requested, declined}` (`pushLocked` flips stale `review_found` → `not_requested`, see §3.4); **no-op exit 0 if no reviewers match** the target set; no phase change | invoked by `runLocked` immediately after a successful `pushLocked` for the same set of reviewers; no phase change | re-requests if reviewer state stale; no phase change | re-applies idempotently | terminal; no-op |
| `wait` | sleeps; returns when `waitLocked` contract (§3.3) breaks — phase change, quiescence trip (§4), or signal-cancel (§4.2) | sleeps; returns when `waitLocked` contract (§3.3) breaks — phase change, quiescence trip (§4), or signal-cancel (§4.2); hard cap is NOT checked here (§3.5) | `PRECONDITION_WAIT_NOT_APPLICABLE` (exit 2 `EX_USAGE`) — `fixes-pending` has actionable work; the caller should invoke `run` (or `fix`+`push`) instead | sleeps; returns when `waitLocked` contract (§3.3) breaks — typically poll-event transitions to `fixes-pending` or `merged` | sleeps; returns when `waitLocked` contract (§3.3) breaks — typically poll-event transitions out | terminal; no-op |
| `resolve-escalated` | `PRECONDITION_NO_ESCALATIONS` | `PRECONDITION_NO_ESCALATIONS` | flips one item's `Disposition.Kind` from `escalated` to a terminal value; phase unchanged | `PRECONDITION_NO_ESCALATIONS` | flips one item's `Disposition`; **only clears the `escalated` items gate** (§3.2 priority 4). Does NOT clear `LIFECYCLE_HARD_CAP_EXCEEDED` (requires `--max-rounds` raise + re-run), `STATE_CORRUPT` (requires operator state-file inspection), or `failed`-items gating (requires the operator to address the underlying `failed` disposition first). After the flip: phase moves to `fixes-pending` if and only if ALL of: (a) `state.Items` has no `escalated` items remaining, (b) `state.Items` has no `failed` items, AND (c) `state.LastError ∉ BlockingErrorCodes` (defined below). Otherwise phase stays `human-gated`. **`BlockingErrorCodes`** = { `LIFECYCLE_HARD_CAP_EXCEEDED`, `STATE_CORRUPT`, `STATE_SCHEMA_UNKNOWN`, `RUNTIME_GH_TERMINAL`, `RUNTIME_PUSH_REJECTED` } — these codes signal conditions outside `resolve-escalated`'s scope and require the recovery paths in §3.6/§3.7. ("Repo deleted" is one of the conditions classified under `RUNTIME_GH_TERMINAL`, per §3.6's example list; no distinct `RUNTIME_REPO_DELETED` code is registered.) (`CONTRACT_AUDIT_FAILED` is intentionally NOT in this set: per §3.3 `handle_verb_error`, contract-audit failures are surfaced via per-item `Disposition.Kind = failed`, not via `state.LastError`; the `failed`-items check in clause (b) handles them.) | terminal; no-op |
| `status` | read-only (**lock-free**; see §3.3 carve-out — `--locked` opt-in for strictly-consistent read) | read-only | read-only | read-only | read-only | read-only |
| `run` | invokes lifecycle loop (§3.3) | invokes lifecycle loop (§3.3) | invokes lifecycle loop (§3.3) | invokes `pollLocked` **once** to detect external transitions (e.g., operator merged externally → `merged`; new reviewer activity → `fixes-pending`). If phase advances out of `quiesced`, re-enter the lifecycle loop; otherwise return 0. | invokes `pollLocked` **once** to detect external resolutions (operator pushed a fix → `fixes-pending`; operator merged → `merged`). If phase advances out of `human-gated`, re-enter the lifecycle loop; otherwise return 0 (awaits operator action). | returns 0 immediately (graph-terminal; `merged` is absorbing) |

**End-of-cycle phase resolution** (applied by `run` after each cycle via `resolve_end_of_cycle_phase`, see §3.3): from `fixes-pending` the resolver chooses the next phase by evaluating these conditions in strict priority order — the first match wins.

1. Hard-cap would be exceeded by the next push (`Round >= MaxRounds` AND `has_queued_fix_commits(state)`) → `human-gated` with `LastError = LIFECYCLE_HARD_CAP_EXCEEDED`. **Check is pre-push** (§3.5), so the cap-tripping push is *not* uploaded.
2. Any item with `Disposition.Kind == failed` (regardless of underlying cause — contract audit, runtime terminal error, or agent-reported "could not converge") → `human-gated`. For runtime-terminal-user failures, `state.LastError` was already set by `handle_verb_error` (Propagate path); the resolver preserves it. For contract-audit failures and pure agent-reported failures, `state.LastError` is left unset — the per-item `Disposition.Rationale` is the source of truth for the cause. (Rationale: `handle_verb_error` only writes `state.LastError` on Propagate-tier errors; `CONTRACT_AUDIT_FAILED` returns `Continue` and surfaces the cause via per-item `Disposition`. Cross-reference §3.3 `handle_verb_error` and the §3.7 error-code registry.)
3. Any item with unresolved `Disposition.Kind == escalated` → `human-gated`; file exactly one `EscalationSink` event per cycle (deduped across items). The `EscalationSink` always exists (Section 5: stderr is the default sink) — there is no "no resolution path" branch.
4. ≥1 commit pushed this cycle (`Round` was incremented) → `awaiting-review`. `rereview` already invoked from within the cycle (§3.3) for required bot reviewers needing fresh review.
5. No commits pushed this cycle AND quiescence threshold trips (§4) → `quiesced`.
6. Otherwise (no commits pushed, quiescence did not trip) → `awaiting-review`. **Rule-6 rationale:** this covers the case where every item processed this cycle dispositioned to `skipped`/`wont_fix`/`deferred` (zero commits, no fresh work), and the §4 quiescence threshold has not yet judged the PR ready. The next cycle's `wait` either observes new reviewer activity (→ back to `fixes-pending` via `poll`) or accumulates idle time until quiescence trips. Already-processed items remain in `state.Items` with `Disposition != nil`; subsequent `clusterLocked`/`fixLocked` skip them (idempotent on dispositioned items), so re-entering `fixes-pending` only does work for NEW items.

### 3.3 `run` aggregate verb algorithm

`run --autonomous` is **long-running and blocking** for non-terminal phases — the invocation holds the PR lock through the cycle loop while the phase is `idle`, `awaiting-review`, or `fixes-pending`. **When the phase reaches `quiesced`, `human-gated`, or `merged`, `run` releases the lock and returns**, so external triggers (operator's `resolve-escalated`, manual push, manual merge) are free to acquire the lock and act. Each `*Locked` internal writes state to disk before returning, so a crashed process leaves the on-disk state consistent (per Section 2's transactional model) and the next `run` invocation resumes from the last successful write.

`run` is the **only verb that acquires the PR lock once and calls multiple `*Locked` internals in sequence**. This is the singular exception to Section 2's "every verb acquires its own lock" rule, and is the reason the `*Locked` internal contract exists.

**`*Locked` internal contract.** Each `*Locked` function:

- Assumes the caller already holds the PR lock for the duration of the call.
- Reads no state from disk; instead receives the current in-memory `*PRGroomingState` from the caller.
- Returns `(*PRGroomingState, error)` — the (potentially) mutated state and any error tagged with its failure tier (§3.6).
- Atomically `store.Write`s state before returning, so the on-disk view always reflects the last successful internal call.
- Is **idempotent on already-processed items**: `clusterLocked` is a no-op when every item has `ClusterID != ""`; `fixLocked` is a no-op when every item has `Disposition != nil`; `replyLocked` is a no-op when every item has `Replied == true`; `resolveLocked` is a no-op when no item is in `{fixed, already_addressed} ∧ Resolved == false`; `pushLocked` is a no-op when `has_queued_fix_commits` returns false. This idempotency contract is load-bearing — `runLocked`'s priority-7 re-entry path (§3.2) relies on it to avoid hot loops.
- **`fixLocked` restart-safety under transient agent failures.** When a transient-tier agent failure (`RUNTIME_AGENT_TIMEOUT`, `RUNTIME_AGENT_UNAVAILABLE`) aborts a cycle mid-cluster, items already processed before the failure carry `Disposition != nil` and are skipped on the next `fixLocked` invocation per the idempotency rule above; items not yet processed carry `Disposition == nil` and are reprocessed. This guarantees that partial-cluster processing is never lost (no double-fixing of already-dispositioned items) and never starved (un-dispositioned items always get another attempt on the next `run` invocation, driven by the scheduler's retry of exit-75).

**Tier → exit code mapping** (`exitCodeForTier`) — `Run`'s public wrapper applies this to translate a tier-tagged error into the documented sysexits code:

```text
function exitCodeForTier(err):              # takes the full tier-tagged error, not just err.Tier
    switch err.Tier:                         # all cases inspect err.Tier only, EXCEPT RUNTIME_CANCELLED
        case PRECONDITION_USER_ERROR:    return 2   # EX_USAGE
        case PRECONDITION_NO_WORK:       return 0   # success-no-op
        case PRECONDITION_LOCK_HELD:     return 75  # EX_TEMPFAIL (transient-equivalent for scheduler retry)
        case RUNTIME_TRANSIENT:          return 75  # EX_TEMPFAIL
        case RUNTIME_TERMINAL_USER:      return 77  # EX_NOPERM
        case RUNTIME_CANCELLED:          return 128 + err.Signum  # err.Signum is 2 (SIGINT→130) or 15 (SIGTERM→143); non-retryable; only RUNTIME_CANCELLED reads err payload beyond .Tier
        case CONTRACT_AUDIT_FAILED:      return 65  # EX_DATAERR
        case STATE_CORRUPT, STATE_SCHEMA_UNKNOWN: return 78  # EX_CONFIG
        case LIFECYCLE_CAP:              return 0   # graceful terminal exit
        default:                         return 1   # generic failure
```

```text
function Run(pr, mode):                       # mode ∈ {interactive, autonomous}
    release, err := store.Lock(pr)          # public locking shell
    if err != nil:
        return exitCodeForTier(err)      # likely PRECONDITION_LOCK_HELD → 75
    defer release()

    state, err := runLocked(pr, mode)
    if err != nil:
        return exitCodeForTier(err)
    return 0

function runLocked(pr, mode) (*PRGroomingState, error):
    state, err := store.Read(pr)
    if errors.Is(err, ErrNotFound):
        # First invocation against this PR — bootstrap zero-value state.
        # Auto-bootstrap is performed regardless of --no-prework; absence of
        # state is a discovery condition, not a precondition failure.
        # Initialize ALL non-zero-default fields explicitly per §2 schema —
        # SchemaVersion=1 is required (zero-default 0 would fail STATE_SCHEMA_UNKNOWN
        # validation on next read); PR identifies the bead-tracker key; Items
        # and Reviewers are initialized to empty containers (not nil) so subsequent
        # appends/inserts are safe.
        state = PRGroomingState{
            SchemaVersion:      1,
            PR:                 pr,
            Phase:              "idle",
            Round:              0,
            LastPollSHA:        "",
            LastPushedHeadSHA:  "",
            Reviewers:          map[string]ReviewerState{},
            Items:              []ReviewItem{},
            LastError:          "",
            LifecycleEscalationFiled: false,
        }
        store.Write(pr, state)
    else if err != nil:
        return state, taggedError(STATE_CORRUPT, err)

    # Entry-time external-transition probe: if state is already terminal-for-CLI
    # at entry (operator invoked `run` against a quiesced/human-gated PR), run
    # one pollLocked first to detect external transitions (e.g., operator merged
    # the PR externally; operator pushed a manual fix that cleared the gate).
    # Without this, terminal-for-CLI → merged / human-gated → fixes-pending
    # transitions are unreachable per the §3.2 matrix (the `run` row for those
    # phases). The probe runs at most once per invocation; if pollLocked errors,
    # follow the standard handle_verb_error pattern.
    if state.Phase ∈ {quiesced, human-gated}:
        state, err = pollLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # §3.3
            state = request_human_review_if_needed(state)  # §4.7 (auto-label-add)
            return state, err
        # If pollLocked transitioned phase to a non-terminal-for-CLI value
        # (fixes-pending after operator fix-push, or back into awaiting-review
        # after external push from quiesced), the loop top below re-enters the
        # cycle. If it stayed terminal-for-CLI or advanced to merged, the
        # loop-top check returns cleanly.

    for {
        # Terminal-for-CLI: emit any pending escalations + auto-label, return.
        # All escalation emission funnels through escalate_if_needed (§3.3); the
        # parallel request_human_review_if_needed (§4.7) handles GitHub-label
        # auto-add for review-content gating conditions (cap-trip, escalated/failed
        # items). Both are called from the same two sites: HERE (clean phase
        # transitions) and before each Propagate-return below (terminal-error
        # transitions). Both sites are dedup-safe via the per-item EscalationFiled
        # flag, the lifecycle LifecycleEscalationFiled flag, and the HumanReviewLabelAdded
        # flag — second invocation in the same cycle is a no-op for all three.
        if state.Phase ∈ {merged, quiesced, human-gated}:
            state = escalate_if_needed(state)              # per-item + lifecycle dedup; writes state (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, nil

        # === Cycle start (state.Phase ∈ {idle, awaiting-review, fixes-pending}) ===

        state, err = pollLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err

        if state.Phase ∈ {merged, quiesced, human-gated}:
            continue                          # loop top will emit + return

        if state.Phase == idle:
            if mode == interactive:
                fmt.Fprintln(os.Stderr, "prgroom: nothing to do — PR has no commits yet (phase=idle)")
                return state, nil
            state, err = waitLocked(pr, state)
            if disposition := handle_verb_error(err, &state); disposition == Propagate:
                state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
                return state, err
            continue

        if state.Phase == awaiting-review:
            if mode == interactive:
                return state, nil             # user owns the wait
            state, err = waitLocked(pr, state)
            if disposition := handle_verb_error(err, &state); disposition == Propagate:
                state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
                return state, err
            continue

        # === state.Phase == fixes-pending ===
        state, err = clusterLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err

        state, err = fixLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err

        # Pre-push hard-cap check (§3.5). Set state ONLY; the next loop-top
        # iteration's escalate_if_needed emits one Sink event for this gate,
        # using state.LifecycleEscalationFiled to dedup.
        if has_queued_fix_commits(state) AND state.Round >= MaxRounds:
            state.Phase = "human-gated"
            state.LastError = "LIFECYCLE_HARD_CAP_EXCEEDED"
            state.LifecycleEscalationFiled = false   # cleared so loop-top fires once
            store.Write(pr, state)
            continue                                 # loop top emits + returns

        state, err = pushLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err

        # Post-push rereview for required bot reviewers needing fresh review.
        # pushLocked already flipped review_found → not_requested per §3.4,
        # so has_required_reviewers_to_refresh reduces to "any Required=true
        # reviewers configured" after a successful push.
        if push_uploaded_commits_this_cycle(state) AND has_required_reviewers_to_refresh(state):
            state, err = rereviewLocked(pr, state)
            if disposition := handle_verb_error(err, &state); disposition == Propagate:
                state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
                return state, err

        state, err = replyLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err
        state, err = resolveLocked(pr, state)
        if disposition := handle_verb_error(err, &state); disposition == Propagate:
            state = escalate_if_needed(state)              # flush per-item + lifecycle emits before propagating (§3.3)
            state = request_human_review_if_needed(state)  # auto-add `human-review-required` label if applicable (§4.7)
            return state, err

        # End-of-cycle phase resolution — priority cascade per §3.2.
        # Phase resolution sets state ONLY; loop-top emits via escalate_if_needed.
        state.Phase = resolve_end_of_cycle_phase(state)
        if state.Phase ∈ {human-gated} AND new_lifecycle_gate_this_cycle(state):
            state.LifecycleEscalationFiled = false   # cleared so loop-top fires once
        if state.Phase ∉ {human-gated}:
            # Successful cycle completion clears any prior gating error
            # (e.g., LIFECYCLE_HARD_CAP_EXCEEDED carried over from a previous run
            # that the operator has since resolved out-of-band or by raising --max-rounds).
            # Realistic carry-over reaching this clear: LIFECYCLE_HARD_CAP_EXCEEDED
            # (operator raised --max-rounds and re-ran). Other BlockingErrorCodes
            # (STATE_CORRUPT, STATE_SCHEMA_UNKNOWN, RUNTIME_GH_TERMINAL, RUNTIME_PUSH_REJECTED)
            # keep phase at human-gated via handle_verb_error or the end-of-cycle
            # resolver and never reach this clear-on-success branch.
            # See §3.5 "Recovery" bullet.
            state.LastError = ""
            state.LifecycleEscalationFiled = false   # reset for next gate, if any
            state.HumanReviewLabelAdded = false      # §4.7: reset so next gating event re-adds the label
        store.Write(state)
        continue                                     # loop top handles terminal + emits
}
```

Notes on the rewrite vs. earlier drafts:

- Every `*Locked` returns `(*PRGroomingState, error)` so `runLocked` threads in-memory state without disk re-reads. The lock guarantees no external mutation; re-reads were redundant.
- `handle_verb_error` returns a disposition enum (`Continue` or `Propagate`) rather than `error`, eliminating the shadow / ambiguous-return pattern. Continuable errors (`CONTRACT_AUDIT_FAILED`) write state and return `Continue`; terminal-tier errors return `Propagate` and `runLocked` returns the original tagged error to `Run`, which applies `exitCodeForTier`.
- All escalation emission flows through `escalate_if_needed`, called immediately followed by `request_human_review_if_needed` (§4.7) at every site. Both are called from **two** sites in `runLocked` — the loop-top terminal-for-CLI check (clean transitions to `merged`/`quiesced`/`human-gated`), and immediately before each Propagate-return after `handle_verb_error` (terminal-error paths: auth-expiry, push-rejected, state-corrupt). All three dedup flags share the same mechanism — per-item `EscalationFiled`, lifecycle-tier `LifecycleEscalationFiled`, and `HumanReviewLabelAdded` (§4.7) — each with atomic state write after emit. Calling either function twice in one cycle is a no-op the second time (the relevant flag is already set). The cap-trip branch and end-of-cycle resolver only WRITE state (setting `LifecycleEscalationFiled = false` and `HumanReviewLabelAdded = false` to invite a new emit). Crash-recovery safe modulo Sink idempotency (bd `label add` is idempotent; `--append-notes` is not — bd-adapter must use label-only emit, or content-hash dedup on notes) and GitHub-label idempotency (`gh.AddLabel` is idempotent server-side).

**Terminal-signal emission — parallel-function design.** `runLocked` emits terminal signals via two parallel functions: `escalate_if_needed(state)` (Sink semantics; §3.3) and `request_human_review_if_needed(state)` (GitHub-label semantics; §4.7). There are **two** call sites for both, both dedup-safe via `EscalationFiled`/`LifecycleEscalationFiled`/`HumanReviewLabelAdded` flags: (1) the loop-top terminal-for-CLI check (clean transitions), and (2) immediately before each `return state, err` on Propagate paths (terminal-error transitions). `handle_verb_error` sets state and (for terminal tiers) updates `state.LastError` and `state.LifecycleEscalationFiled = false` but does NOT emit directly. The cap-trip branch and end-of-cycle resolver also only WRITE state (setting `state.LifecycleEscalationFiled = false` and `state.HumanReviewLabelAdded = false` to invite fresh emits when a new lifecycle gate fires). Recommended call order at every site is `escalate_if_needed` first (Sink), then `request_human_review_if_needed` (label) — either ordering is correct since both are idempotent and read disjoint state; the convention is for readability.

`escalate_if_needed(state)` semantics:

- Walks `state.Items`: for any item with `Disposition.Kind ∈ {escalated, failed}` AND `Disposition.EscalationFiled == false`, calls `EscalationSink.Emit(...)` and sets `EscalationFiled = true`.
- If `state.LastError != ""` AND `state.LifecycleEscalationFiled == false`, calls `EscalationSink.Emit(...)` for the lifecycle-tier condition and sets `LifecycleEscalationFiled = true`.
- Atomically `store.Write`s state after emission.
- **Sink failure handling:** if `EscalationSink.Emit(...)` returns an error (stderr write failure, bd-adapter API blip), the failure is swallowed (best-effort emit). The corresponding `EscalationFiled` / `LifecycleEscalationFiled` flag is NOT set on Sink error, so the next invocation of `escalate_if_needed` re-attempts the emission for the same item or lifecycle gate. Persistent Sink failures produce repeated retry attempts but never block lifecycle progression (the cycle continues; phase transitions still happen). Operators inspecting `prgroom status` see the gating condition via `state.LastError` and per-item `Disposition.Kind` regardless of Sink reachability. **Relation to the crash-window dedup paragraph below:** the Sink-error retry path produces the same double-fire risk as the crash window (next invocation re-emits) and relies on the same Sink-side dedup contract — bd-adapter must use label-only emit or content-hash dedup on notes; stderr sinks accept the duplicate as a single extra log line.

**Crash-window dedup:** a crash between Sink emit and state write may double-fire on the next invocation. The Sink itself is expected to dedup idempotently — bd's `label add` is idempotent (acceptable); bd's `--append-notes` is NOT (would duplicate notes lines on retry), so the bd-adapter MUST use label-only emit, or content-hash dedup on notes. Stderr-only sinks have no dedup but the cost is one extra log line, accepted.

**Verb-error handling (`handle_verb_error`).** Returns a disposition enum:

```text
function handle_verb_error(err, state) Disposition:
    if err == nil: return Continue
    switch err.Tier:
        case RUNTIME_TRANSIENT:
            state.LastError = err.Code
            store.Write(state)
            return Propagate                  # Run will exit 75; scheduler retries
        case RUNTIME_TERMINAL_USER:
            state.Phase = "human-gated"
            state.LastError = err.Code
            state.LifecycleEscalationFiled = false   # invites loop-top emit
            store.Write(state)
            return Propagate                  # Run will exit 77
        case CONTRACT_AUDIT_FAILED:
            # Verb has already flipped affected items to Disposition.Kind = failed
            # with rationale set. End-of-cycle resolver (§3.2 priority 3) decides
            # phase consequence. Per-item EscalationFiled flag controls dedup.
            return Continue                   # cycle proceeds; loop-top emits at terminal
        case STATE_CORRUPT, STATE_SCHEMA_UNKNOWN:
            state.Phase = "human-gated"
            state.LastError = err.Code
            state.LifecycleEscalationFiled = false
            store.Write(state)
            return Propagate                  # Run will exit 78
        case RUNTIME_CANCELLED:
            # Normal non-retryable lifecycle exit (SIGINT/SIGTERM from operator or scheduler).
            # No phase change, no state mutation — leave state exactly as written by the
            # last successful *Locked so `prgroom status` reports the last known phase
            # accurately. Run applies exitCodeForTier (→ 130 or 143).
            return Propagate
        default:
            # Unknown tier is a programmer error — the tier enum is exhaustive
            # over registered tiers (§3.6) and adding a new tier requires
            # updating both the registry and this switch. Crash-loud propagation
            # is intentional: do NOT store.Write(state) here, because doing so
            # would silently persist any verb-level state mutations carried in
            # the (potentially undefined) error and mask the bug from operators.
            # Run maps default-tier propagation to exit code 1 (generic failure)
            # via exitCodeForTier.
            return Propagate
```

**`waitLocked` contract surface (implementation owned by §4).** §3.3 only relies on the following surface; §4 defines the quiescence/timeout logic that implements it:

- Signature: `waitLocked(pr PRRef, state *PRGroomingState) (*PRGroomingState, error)`.
- Behavior: sleeps + internally invokes `pollLocked` at the §4-defined cadence, returning when either (a) the polled state transitions to a new phase, (b) the §4-defined quiescence threshold trips (writes `Phase = quiesced` and returns), or (c) a §4-defined hard-timeout fires (returns without phase change).
- Error tiers: may return `RUNTIME_TRANSIENT` if internal `pollLocked` invocations hit gh API blips beyond the retry budget; `RUNTIME_CANCELLED` if a signal interrupts the wait (see Cancellation below); otherwise `nil`.
- Cancellation: honors a context `Done` channel if the caller plumbs one through; in MVP, signals (SIGINT/SIGTERM) cause `waitLocked` to return promptly with an error tagged `RUNTIME_CANCELLED` (NOT `RUNTIME_TRANSIENT`) so the lock releases cleanly AND the scheduler does not retry the cancelled invocation. The exit code is `128 + signum` per Unix convention (130 for SIGINT, 143 for SIGTERM), distinct from `RUNTIME_TRANSIENT`'s exit 75 (`EX_TEMPFAIL`). This separation prevents the "cancelled-work resurrection" failure mode in which a Ctrl-C'd `run --autonomous` is re-driven by the scheduler against the operator's intent.
- Lock semantics: assumes the caller holds the PR lock; does NOT release the lock during sleep (lock stays held for the entire `Run --autonomous` invocation per §3.5).

**`run --interactive` differences:** identical control flow except the verb returns 0 on reaching `awaiting-review`, `idle`, or any terminal-for-CLI phase. It never calls `waitLocked`. On `idle`, the interactive variant emits a one-line stderr advisory (`prgroom: nothing to do — PR has no commits yet (phase=idle)`) so callers can distinguish "nothing to do" from "completed work." Escalations route through the default `EscalationSink` (stderr).

**Lock-hold duration:** `Run --autonomous` holds the lock continuously from the first `store.Lock(pr)` call. Within each cycle, the lock is held through the full sequence `pollLocked → clusterLocked → fixLocked → pushLocked → [rereviewLocked] → replyLocked → resolveLocked → resolve_end_of_cycle_phase → store.Write` (no mid-cycle release). After each cycle's phase resolution, if the new phase is terminal-for-CLI (`quiesced`, `human-gated`, or `merged`), the loop `continue`s, the loop-top terminal check fires, `runLocked` returns, and the `defer release()` registered by `Run` releases the lock. Concurrent invocations on the same PR exit immediately with `PRECONDITION_LOCK_HELD` (exit 75); once the holder returns, the next invocation may acquire.

**`status` read-only carve-out.** The `status` verb is the **single exception** to Section 2's "every verb acquires the PR lock" rule. `status` performs a single `store.Read(pr)` and prints the result without calling `store.Lock(pr)`. Rationale: under a long-running `run --autonomous` invocation that holds the lock for the entire `awaiting-review` wait (potentially minutes-to-hours per §4 quiescence semantics), a lock-acquiring `status` would block or exit `PRECONDITION_LOCK_HELD` for that whole duration — a UX regression versus the legacy `wait-for-pr-comments` skill, which exposes per-poll state readable at any time. The cost: a `status` invocation that races with an in-progress `store.Write` from another verb may observe a **stale-but-internally-consistent snapshot** — the pre-rename state from the prior write. Because writes are file-atomic per Section 2 (`mktemp` + `rename(2)` on the same filesystem), a reader always observes either the old complete file or the new complete file. Partial/corrupt JSON from a race is not possible; `status` does not retry on staleness (a single read is always parseable). True `STATE_CORRUPT` errors (hand-edited state file, filesystem corruption) remain distinguishable from lock-free staleness and surface via the normal `STATE_CORRUPT` handling. Operators who need a strictly-consistent read can invoke `prgroom status --locked <pr>`, which DOES acquire the lock via the standard `store.Lock(pr)` path. Under contention, `--locked` exits **75** (`PRECONDITION_LOCK_HELD` per §3.7) on the standard scheduler-retry cadence — it does NOT block indefinitely; the default lock-free `status` invocation is the right tool for diagnostic polling under a long-running `run --autonomous`.

**Resilience:** every internal `*Locked` writes state atomically (per Section 2's transactional model). If the process dies mid-`run`, the OS releases the file-adapter lock, the next invocation re-acquires it, reads the last-good state, and resumes from there. There is no `crash_recovery` flag.

### 3.4 `Round` counter semantics

`Round` represents the **count of distinct review-eliciting pushes** observed for this PR. It disambiguates initial review (`Round=1`) from re-review (`Round≥2`) within the `awaiting-review` phase.

**Initialization and increment rules.** The unifying principle: `Round` increments from 0 to 1 on the **first observation of a non-empty PR HEAD by either code path** (whichever happens first), and increments further only on subsequent **distinct review-eliciting pushes**. Both `pollLocked` and `pushLocked` must guard their increment with idempotency checks so they do not double-bump.

- The zero value of `PRGroomingState` has `Round: 0` and `LastPollSHA == ""`.
- **`pollLocked` bootstrap (Round 0 → 1).** When `pollLocked` runs with `state.LastPollSHA == ""`, it inspects the remote PR HEAD:
  - If the remote HEAD is **non-empty** (the PR has ≥1 commit), `pollLocked` idempotently sets `state.Round = max(state.Round, 1)` (a prior `pushLocked` may have already set it to 1, in which case this is a no-op), sets `state.LastPollSHA = <observed HEAD SHA>`, and follows the §3.2 `poll`-from-`idle` row to transition phase out of `idle`.
  - If the remote HEAD is **empty** (PR opened with no commits — uncommon but legal), `pollLocked` leaves `state.Round = 0` and `state.LastPollSHA = ""`, returns no phase change. The next `pollLocked` invocation re-evaluates the bootstrap condition.
  This bootstrap is not subject to the CLI-vs-external attribution rule below (which applies only when `state.LastPollSHA != ""`).
- **`pushLocked` bootstrap (Round 0 → 1).** If `pushLocked` successfully uploads ≥1 commit while `state.Round == 0` (e.g., `prgroom` is the first agent to push commits to a freshly-opened empty PR), it sets `state.Round = 1` and `state.LastPushedHeadSHA = <new HEAD SHA>` in the same write. If a `pollLocked` runs subsequently while `state.LastPollSHA == ""`, it follows the **`pollLocked` bootstrap rule above** (NOT the attribution rule): it inspects the remote HEAD, observes `state.Round == 1` (already bumped by `pushLocked`), idempotently skips re-incrementing, sets `state.LastPollSHA = <observed HEAD SHA>`, and follows the §3.2 `poll`-from-`idle` row to transition phase. The bootstrap branch is identified by `state.LastPollSHA == ""`; the attribution branch (below) is identified by `state.LastPollSHA != ""`. The two branches are mutually exclusive.
- **`pushLocked` subsequent increments (Round N → N+1, N ≥ 1).** When `state.Round >= 1`, `pushLocked` increments `Round` if and only if it uploaded **≥1 new commit** to the remote, and sets `state.LastPushedHeadSHA = <new HEAD SHA>` in the same write.
- **`pollLocked` subsequent increments (Round N → N+1, N ≥ 1).** When `state.Round >= 1` and `pollLocked` observes a HEAD SHA change attributable to commits the CLI did not author, it increments `Round` (see the attribution rule below).
- A complete fix-cycle that produced zero commits (every item dispositioned `skipped`/`wont_fix`/`deferred`) does NOT increment `Round`. Such a cycle counts toward quiescence (§4) but not toward the hard cap.
- `resolve-escalated` does NOT increment `Round` — the disposition flip alone is not visible to reviewers.
- **`§3.5` narrative consistency:** the §3.5 "Round=1 → fix-push #2 → fix-push #3" example assumes the typical case in which the first observed push (by either bootstrap path above) is followed by CLI-authored fix-pushes. The exact code path that produced `Round=1` (poll-bootstrap on a human-authored push vs. push-bootstrap on a CLI-authored initial push) does not affect cap semantics — both consume one round.

**CLI-vs-external push attribution.** When `pollLocked` observes that the remote HEAD differs from `state.LastPollSHA`:

- If `newHeadSHA == state.LastPushedHeadSHA` → the change is the CLI's own push (already counted by `pushLocked`); update `state.LastPollSHA = newHeadSHA`, do NOT increment `Round`. `pushLocked` already performed the reviewer-state flip in this case, so `pollLocked` leaves `state.Reviewers` untouched.
- Otherwise → external push (operator or third party); increment `Round`, set `state.LastPollSHA = newHeadSHA`, leave `state.LastPushedHeadSHA` untouched. **Additionally, mirror `pushLocked`'s reviewer-state flip:** walk `state.Reviewers` and flip every entry with `Required == true` AND `Status == "review_found"` to `Status = "not_requested"` (same predicate as the "`ReviewerState.Status` transition on `pushLocked`" rule below). External pushes invalidate prior reviews on the old SHA exactly as CLI pushes do, so the post-push `rereviewLocked` predicate `has_required_reviewers_to_refresh(state)` evaluates correctly. The CLI does NOT update `LastPushedHeadSHA` for pushes it didn't make.

This rule prevents double-counting CLI pushes (which would otherwise be incremented once by `pushLocked` and again by the next `pollLocked`) and prevents missing external pushes. The reviewer-flip mirror ensures stale reviews are detected regardless of the push's author.

**Force-push and rebase edge cases (best-effort attribution).** When operators force-push or rebase, history is rewritten and the simple "SHA equality" check above can under- or over-count rounds:

- *Under-count:* CLI pushed X (set `LastPushedHeadSHA = X`). Operator force-pushed Y over X. CLI then pushed Z on top of Y. `LastPushedHeadSHA` now reads Z. The intermediate Y is unobservable because it was overwritten; the round it consumed is not counted.
- *Over-count:* In `awaiting-review`, the operator force-pushes a rebase whose tree is logically identical to the prior HEAD. `LastPushedHeadSHA` no longer matches the new HEAD, so `pollLocked` increments `Round` even though no new review work was elicited.

These edge cases are accepted as **best-effort attribution**, not corrected automatically. Rationale: detecting history rewrites reliably (especially distinguishing "rebase with identical tree" from "rebase with different commits") requires comparing tree hashes, parent chains, and committer metadata — a feature surface disproportionate to the value, given that operators who care can manually adjust `--max-rounds`. If precise round accounting under force-push becomes a recurring need, a follow-up bead should split `MaxRoundsCLI` vs `MaxRoundsTotal` (mentioned in §3.5) so the cap can be raised without altering CLI-side budgets.

**Detecting queued (unpushed) fix commits.** `prgroom` does not maintain a separate state field for the commit queue. The remote tip is the source of truth: `pushLocked` consults `gh pr view --json headRefOid` for the authoritative remote HEAD on the PR branch and compares it to the local PR-branch HEAD via `git rev-list <remote-head>..HEAD`. This avoids the `@{upstream}` tracking-ref requirement (which is not guaranteed in fresh clones or non-standard worktree configurations). `has_queued_fix_commits(state)` evaluates to true iff the local PR-branch HEAD differs from the remote HEAD and the diff contains commits authored by the local branch. `pushLocked` uploads exactly those commits; if none exist, the verb returns `PRECONDITION_NO_COMMITS` (under `--no-prework`) or a no-op (under default). Crash recovery: if the process dies after `fixLocked` but before `pushLocked`, re-invoking `run` will re-enter at `pollLocked` → `fixesPending` → `clusterLocked` (idempotent on classified items) → `fixLocked` (idempotent on items already carrying `Disposition`) → `pushLocked` (uploads the orphaned-by-crash commits). No special crash-recovery code path is required.

**`pushLocked` idempotency.** If `git push` succeeds but the subsequent state write fails (disk full, partial write), the next invocation's queued-commits check returns empty (commits already remote), so `pushLocked` early-returns without incrementing `Round` a second time. The result is a possible Round under-count by one — preferred over double-counting.

**`ReviewerState.Status` transition on `pushLocked`.** A reviewer's `Status == "review_found"` is bound to the SHA the reviewer evaluated. When `pushLocked` uploads ≥1 new commit, the HEAD SHA changes and prior reviews become stale. After a successful push, `pushLocked` walks `state.Reviewers` and flips every entry with `Required == true` AND `Status == "review_found"` to `Status = "not_requested"`. This ensures the post-push `rereviewLocked` call (§3.3) finds reviewers to re-request. Reviewers in `{requested, in_progress, declined}` are left as-is — `rereview` already targets `{declined}` (plus `{not_requested}` after the flip) per §3.2, and `requested`/`in_progress` reviewers should not be disturbed mid-pass.

**Predicate definitions used in §3.3 pseudocode:**

- `has_queued_fix_commits(state) bool` — true iff the remote/local HEAD comparison yields ≥1 unpushed commit (see "Detecting queued (unpushed) fix commits" above).
- `has_required_reviewers_to_refresh(state) bool` — true iff `state.Reviewers` contains ≥1 entry with `Required == true` AND `Status ∈ {not_requested, declined}`. After `pushLocked`'s flip, this reduces to "any `Required=true` reviewers are configured." False only when no required reviewers exist (e.g., the PR has no Copilot/codeowner required reviewer set).
- `push_uploaded_commits_this_cycle(state) bool` — true iff `state.LastPushedHeadSHA` was updated during the current cycle (i.e., the most recent `pushLocked` returned with a non-zero commit upload). Implemented in the in-memory state copy threaded by `runLocked`.
- `new_lifecycle_gate_this_cycle(state) bool` — true iff `state.LastError` was set by the end-of-cycle resolver in this cycle (cap-trip, etc.) and was not set in the prior cycle. Used to gate `LifecycleEscalationFiled = false` so each new gate fires exactly one Sink event.

**`pushLocked` partial-write self-correction.** If `git push` succeeds but the subsequent state write fails, the next invocation's queued-commits check returns empty (commits are on the remote), so `pushLocked` early-returns without incrementing `Round`. The next `pollLocked` then observes `newHeadSHA != state.LastPushedHeadSHA` (because `LastPushedHeadSHA` was not updated) and attributes the change as an external push, incrementing `Round` via the external-push path. **Net effect: `Round` is incremented exactly once, just via the external-attribution code path.** `LastPushedHeadSHA` catches up on the next successful CLI push.

### 3.5 Hard-cap behavior

- **Default cap:** `MaxRounds = 3` — parallel to the current `wait-for-pr-comments` Round-3 cap. With `Round` initialized to 1 on initial push, this allows the initial PR push plus two CLI fix-pushes before the cap trips.
- **Configurability:** `--max-rounds N` flag on `run` and `wait`; env var `PRGROOM_MAX_ROUNDS`; per-repo override in `.prgroom.toml` (file format owned by Section 7). **Precedence (highest → lowest):** CLI flag > env var > per-repo TOML > built-in default (3).
- **Trigger location:** the cap is checked **pre-push**, inside `run`'s cycle loop (§3.3), so the push that would exceed it is refused rather than uploaded:
  - condition: `has_queued_fix_commits(state) AND state.Round >= MaxRounds`
  - action: `state.Phase = "human-gated"`, `state.LastError = "LIFECYCLE_HARD_CAP_EXCEEDED"`, emit one escalation via `EscalationSink`, `store.Write`, then return on next loop top (releasing lock).
- **Semantic clarification:** `MaxRounds` is the maximum count of *review-eliciting pushes the CLI will perform or observe* for this PR, including the initial push. The cap is a ceiling on `Round`, not on it-plus-one. With `MaxRounds=3` the visible push history is exactly: initial (Round=1) → fix-push #1 (Round=2) → fix-push #2 (Round=3) → cap blocks fix-push #3.
- **`wait` verb interaction:** `waitLocked` is only invoked from `awaiting-review` or `idle` (not from `fixes-pending`). It does NOT itself check the cap; the cap check belongs to the pre-push branch of `runLocked`. `wait`'s break conditions are owned by §4.
- **First-poll on an already-active PR (operator migration case).** When `prgroom run` is first invoked on a PR with prior reviewer rounds already on it (operator was running other tooling before adopting `prgroom`), the first `pollLocked` sets `Round = 1` per §3.4's bootstrap rule but does NOT retroactively count the historical rounds. **The cap counts only rounds observed by `prgroom`** — historical out-of-band rounds are not visible to the CLI and so do not consume the budget. If the operator wants the cap to reflect the PR's full lifetime, they can pass `--max-rounds` lower to compensate, or wait for a future enhancement.
- **External pushes and the cap — "observed transitions only" rule.** External pushes count toward `MaxRounds` only when `pollLocked` observes them as a **SHA change between two consecutive poll invocations** (i.e., `newHeadSHA != state.LastPollSHA` AND `newHeadSHA != state.LastPushedHeadSHA`). The first-poll bootstrap (§3.4) sets `Round = 1` to anchor the counter at the PR's currently observed HEAD; it does NOT retroactively scan and count historical pushes that occurred before `prgroom` ever ran on this PR. Rationale: the cap measures review work `prgroom` has *observed* the PR ask of reviewers, not the PR's total lifetime push history. This makes the rule on line 807 and this rule fully consistent: historical pushes are invisible to `prgroom` and so do not count; pushes observed in-flight (CLI's own pushes counted by `pushLocked`, external pushes counted by `pollLocked` SHA-transition attribution) do count. The consequence: if an operator force-pushes three times while `prgroom run --autonomous` is in `awaiting-review` and polling, those three transitions each bump `Round` and may consume the cap; if the operator instead pushes three times BEFORE first launching `prgroom`, only the bootstrap `Round = 1` is recorded. To mitigate cap consumption from in-flight external activity, `pushLocked` emits a one-line stderr warning when the imminent push would advance `Round` to `MaxRounds` (e.g., `prgroom: warning — this push reaches MaxRounds=3; subsequent fix work will gate to human-gated`). Operators who want CLI-only round budgets should distinguish via `--max-rounds` adjustment when manual pushes occur, or file a follow-up bead to split `MaxRoundsCLI` vs `MaxRoundsTotal`.
- **Recovery:** the operator may `resolve-escalated` the gating item(s), raise `--max-rounds`, and re-run. **`LastError` is cleared automatically on the next successful cycle completion** — defined as: end-of-cycle resolution writes any phase other than `human-gated` (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, or `merged`). The clearing is wired in §3.3's `runLocked` pseudocode immediately after `resolve_end_of_cycle_phase`. No `clear-error` verb is needed; manual state-file editing is never required. Alternatively, the operator may resolve out of band (manual push), which `pollLocked` will observe on the next invocation and re-enter `fixes-pending`.

### 3.6 Failure tier model

Extends Section 1's three-tier precondition gating into runtime errors. Every verb's failure path classifies into one of the tiers below. The tier determines the exit code, whether the phase transitions to `human-gated`, and whether an `EscalationSink` event is filed.

| Tier | Examples | Exit code | Phase change | Escalation | Caller (scheduler/agent) behavior |
|------|----------|-----------|--------------|------------|-----------------------------------|
| `PRECONDITION_SELFHEAL` | `fix` with no clusters → auto-runs `poll` + `cluster`, retries | 0 on self-heal success | none | no | proceeds normally |
| `PRECONDITION_USER_ERROR` | bad args, no PR detected, malformed PR ref | 2 (`EX_USAGE`) | none | no | aborts; user fixes invocation |
| `PRECONDITION_NO_WORK` | preconditions met but nothing to do | 0 (success-no-op) | none | no | proceeds |
| `RUNTIME_TRANSIENT` | gh 5xx, network blip, rate-limit with `Retry-After`, GraphQL transient | 75 (`EX_TEMPFAIL`) | none; `LastError` set | no | scheduler retries on next cadence |
| `RUNTIME_TERMINAL_USER` | gh auth missing/expired, repo deleted, branch protection blocks push, OAuth scope insufficient | 77 (`EX_NOPERM`) | → `human-gated`; `LastError` set | yes | aborts; user/operator must resolve |
| `RUNTIME_CANCELLED` | SIGINT / SIGTERM received during `waitLocked` (or other blocking internal); operator Ctrl-C or scheduler-issued cancellation (concrete codes: `RUNTIME_CANCELLED_SIGINT`, `RUNTIME_CANCELLED_SIGTERM` per §3.7) | 130 (SIGINT) / 143 (SIGTERM) — `128 + signum` per Unix convention | none; `LastError` left unchanged (cancellation is not a gating condition) | no | scheduler MUST NOT retry — non-retryable by convention; operator decides whether to re-invoke |
| `CONTRACT_AUDIT_FAILED` | fix-agent commit-orphan check failed; cluster output malformed after retry+fallback | 65 (`EX_DATAERR`) | affected item → `Disposition.Kind = failed` with `Rationale` set by the verb. **`handle_verb_error` returns `Continue` for this tier — it does NOT set `state.LastError`.** End-of-cycle resolver §3.2 priority 3 promotes phase to `human-gated` (any `failed` item, any cause). The cause is available per-item via `Disposition.Rationale`, not via `state.LastError`. | yes | the run loop continues through the rest of the cycle; resolver fires one escalation per cycle (deduped via the `EscalationFiled` flag on each item) |
| `STATE_CORRUPT` | store JSON corrupt; `schema_version` unknown; lock file present but holding PID dead-and-not-self | 78 (`EX_CONFIG`) | → `human-gated`; `LastError` set | yes | aborts; operator inspects state file |
| `LIFECYCLE_CAP` | pre-push cap guard tripped: `has_queued_fix_commits(state) AND Round >= MaxRounds` (§3.5) | 0 (graceful terminal exit) | → `human-gated`; `LastError = LIFECYCLE_HARD_CAP_EXCEEDED` | yes | aborts; operator resolves or raises cap and re-runs |

**Retry policy for `RUNTIME_TRANSIENT`:** the retry budget is **per logical API call, not per verb**. A single `pollLocked` may issue several distinct gh API calls (comments, reviews, CI status, head SHA); each gets its own budget independently. Per API call: **up to 3 total attempts** (initial call + 2 retries) before propagating the error. Back-off between retries is exponential: 1s before retry #1, then 4s before retry #2. When the failure response carries a `Retry-After` header (e.g., gh API rate-limit responses), the CLI honors that value instead of the exponential schedule for that retry. The CLI never retries indefinitely inside one process; after the third attempt fails for a single API call, the verb exits with the tier's code (75 `EX_TEMPFAIL`) and the scheduler (cron, `/loop`, agent caller) drives long-horizon retry.

**Note on `PRECONDITION_LOCK_HELD` tier classification.** Named like a precondition but exits 75 (transient-equivalent) — see §3.7 for rationale. The reason: lock contention is short-lived; scheduler retry-on-cadence is the right recovery, identical to `RUNTIME_TRANSIENT`. The "precondition" naming captures the *pre-work check* shape; the exit-code captures the *retry semantics*.

**`human-gated` re-entry:** the only paths OUT of `human-gated` are:
- `resolve-escalated <item-id>` flips the gating disposition; phase moves to `fixes-pending` once no `escalated` items remain.
- `poll` observes externally-resolved state (operator pushed a fix manually, or merged the PR) and writes `fixes-pending` or `merged` accordingly.
- (Note: the `human-review-required` PR label per §4.4 is a merge constraint, NOT a lifecycle gate — operator does not need to clear it to exit `human-gated`.)

### 3.7 Error-code registry

Every code carries `what` / `why` / `how` per Section 1's structured-stderr contract. Codes are stable identifiers in the form `<CATEGORY>_<SPECIFIC>`. Adding a new code is a non-breaking change; renaming or repurposing one is breaking.

**Tier assignment per code** (the §3.6 tier determines exit code via `exitCodeForTier`, §3.3):

- `PRECONDITION_*` codes are `PRECONDITION_USER_ERROR` tier (exit 2 `EX_USAGE`), EXCEPT:
  - `PRECONDITION_LOCK_HELD` → `PRECONDITION_LOCK_HELD` tier (exit 75 — transient-equivalent, since locks free up; scheduler retries succeed)
  - **The "no-work" exception applies ONLY to the following explicitly enumerated codes** (NOT by `PRECONDITION_NO_` prefix matching): `PRECONDITION_NO_ITEMS`, `PRECONDITION_NO_CLUSTERS`, `PRECONDITION_NO_COMMITS`, `PRECONDITION_NO_UNREPLIED`, `PRECONDITION_NO_UNRESOLVED`, `PRECONDITION_NO_ESCALATIONS` → `PRECONDITION_NO_WORK` tier (exit 0 success-no-op under default self-heal; exit 2 only under `--no-prework`). **`PRECONDITION_NO_AUTH` and `PRECONDITION_NO_PR_DETECTED` — despite the `NO_` substring — are NOT in the exception set; they remain `PRECONDITION_USER_ERROR` tier (exit 2)** because they denote user-actionable configuration/invocation errors, not absence-of-work conditions. Future codes named `PRECONDITION_NO_*` will be `PRECONDITION_USER_ERROR` tier (exit 2) BY DEFAULT and must be explicitly added to this enumeration to gain `PRECONDITION_NO_WORK` treatment.
- `RUNTIME_*` codes are tagged in the table below.
- `CONTRACT_*` codes → `CONTRACT_AUDIT_FAILED` tier (exit 65 `EX_DATAERR`).
- `STATE_*` codes → `STATE_CORRUPT` tier (exit 78 `EX_CONFIG`).
- `LIFECYCLE_*` codes → `LIFECYCLE_CAP` tier (exit 0 graceful terminal).

#### `PRECONDITION_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `PRECONDITION_NO_PR_DETECTED` | No PR found for current branch or positional arg | every verb requires a PR ref | pass `<pr-number-or-url>` or run from a branch with an open PR |
| `PRECONDITION_NO_AUTH` | `gh auth status` failed at startup precondition check | every verb requires gh auth | run `gh auth login`. Note: if auth was valid at startup but expires mid-verb (token rotation, etc.), the mid-flight failure surfaces as `RUNTIME_GH_TERMINAL` (exit 77), not this precondition code. |
| `PRECONDITION_REPO_UNREACHABLE` | gh API returned 404 for the repo | repo must be accessible | verify repo path and gh token scope |
| `PRECONDITION_BAD_PR_REF` | Provided PR ref is malformed | parseable PR ref required | pass `<number>`, `<owner>/<repo>#<n>`, or full URL |
| `PRECONDITION_NO_ITEMS` | Verb requires items but state has none | each verb declares its preconditions | run `poll` first |
| `PRECONDITION_NO_CLUSTERS` | `fix` requires clustered items | clustering precedes fixing | run `cluster` first |
| `PRECONDITION_NO_COMMITS` | `push` invoked with no local commits queued | `push` is degenerate without commits | run `fix` first OR accept no-op |
| `PRECONDITION_NO_UNREPLIED` | `reply` invoked with no unreplied items | nothing to do | exit-0 success-no-op (or exit 2 under `--no-prework`) |
| `PRECONDITION_NO_UNRESOLVED` | `resolve` invoked with no items in `Disposition.Kind ∈ {fixed, already_addressed}` AND `Resolved == false` | nothing to do | exit-0 success-no-op (or exit 2 under `--no-prework`) |
| `PRECONDITION_NO_ESCALATIONS` | `resolve-escalated` invoked but no `escalated` items | nothing to resolve | re-check `status`; item may have been resolved already |
| `PRECONDITION_WAIT_NOT_APPLICABLE` | `wait` invoked while phase is `fixes-pending` | `wait` is for non-actionable phases; `fixes-pending` has work to do | invoke `run` (full cycle) or `fix`+`push` directly |
| `PRECONDITION_LOCK_HELD` | Another `prgroom` invocation holds the PR lock | concurrency model = one-at-a-time per PR; classified `RUNTIME_TRANSIENT`-equivalent (exit 75 `EX_TEMPFAIL`) | wait for the other invocation; scheduler retries on next cadence; `prgroom status <pr>` shows pid |

#### `RUNTIME_*`

| Code | Tier | What | Why | How |
|------|------|------|-----|-----|
| `RUNTIME_GH_TRANSIENT` | `RUNTIME_TRANSIENT` (75) | gh API returned 5xx or rate-limited with `Retry-After` | external service degraded | retry on next scheduler cadence |
| `RUNTIME_GH_TERMINAL` | `RUNTIME_TERMINAL_USER` (77) | gh API returned 4xx other than 404 or rate-limit | auth/scope/permission issue | inspect stderr; reconfigure gh token. For mid-flight auth expiry specifically, this is the runtime equivalent of `PRECONDITION_NO_AUTH`; re-run `gh auth login` and re-invoke |
| `RUNTIME_GRAPHQL_FAILED` | `RUNTIME_TRANSIENT` (75) | `resolveReviewThread` GraphQL mutation failed | thread may have been resolved externally or schema drifted | re-run `resolve`; if persistent, escalate via Sink |
| `RUNTIME_PUSH_REJECTED` | `RUNTIME_TERMINAL_USER` (77) | `git push` rejected (non-fast-forward, hook block, branch protection) | local branch diverged or rule blocks push; retry without intervention is futile | inspect git stderr; manual reconciliation required (rebase, fix hook, or adjust branch protection). After resolving manually, `pollLocked` will observe the new state on next `Run` |
| `RUNTIME_GIT_TRANSIENT` | `RUNTIME_TRANSIENT` (75) | git network operation timed out | upstream connectivity blip | retry on next cadence |
| `RUNTIME_AGENT_UNAVAILABLE` | `RUNTIME_TRANSIENT` (75) | Primary AND fallback agent CLIs both failed | upstream model/tool unavailable | check `claude` / `codex` CLIs; verify quotas |
| `RUNTIME_AGENT_TIMEOUT` | `RUNTIME_TRANSIENT` (75) | Per-contract time budget exceeded | agent exceeded its budget for one cluster | re-run; if persistent, raise budget or shrink cluster |
| `RUNTIME_CANCELLED_SIGINT` | `RUNTIME_CANCELLED` (130) | SIGINT received during a blocking internal (typically `waitLocked`); operator pressed Ctrl-C | operator-initiated stop; non-retryable | inspect state via `prgroom status`; re-invoke `run` manually if/when desired |
| `RUNTIME_CANCELLED_SIGTERM` | `RUNTIME_CANCELLED` (143) | SIGTERM received during a blocking internal; scheduler-issued cancellation or container shutdown | external-initiated stop; non-retryable | inspect state via `prgroom status`; scheduler MUST treat 143 as terminal, not as a retry signal |

#### `CONTRACT_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `CONTRACT_CLUSTER_MALFORMED` | Cluster output JSON failed schema validation | Contract A invariant violated | retry once; second failure falls back to per-item clusters |
| `CONTRACT_CLUSTER_COVERAGE` | Some input items did not appear in any cluster after fallback | Contract A invariant: every item clustered | re-cluster; if persistent, file `failed` disposition for orphans |
| `CONTRACT_FIX_MALFORMED` | Fix output JSON failed schema validation | Contract B invariant violated | item flipped to `failed`; escalate |
| `CONTRACT_FIX_ORPHAN_COMMIT` | Commits exist on branch that no item claimed | Contract B invariant: every commit claimed | stash isolation applied; affected items flipped to `failed`; escalate |
| `CONTRACT_FIX_UNREACHABLE_SHA` | Output claims `commit_shas[i]` not on branch | Contract B invariant violated | item flipped to `failed`; escalate |
| `CONTRACT_FIX_AUDIT_FAILED` | Disposition+evidence combination violates audit rules | Contract B post-conditions | item flipped to `failed`; end-of-cycle resolution may promote phase to `human-gated` |

#### `STATE_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `STATE_CORRUPT` | Tracker JSON failed parse | state file written incompletely or hand-edited | move state file aside (`<file>.corrupt-YYYYMMDD`); re-run to rebuild |
| `STATE_SCHEMA_UNKNOWN` | `schema_version` not recognized | CLI older than state file (or vice versa) | upgrade/downgrade CLI; do not run conflicting versions concurrently |

**Locking mechanism note.** Section 2 specifies `flock(2)` advisory locking on the state file. `flock(2)` is **released automatically by the kernel on process death**, so the failure-tier registry does NOT include a "stale lock from dead process" code — that condition cannot occur with `flock(2)`. (Earlier drafts referenced `STATE_LOCK_STALE` and `NOTICE_LOCK_STALE_CLEANED` reflecting an fcntl-style protocol; both have been removed to match the chosen mechanism.) Lock contention by a live process surfaces as `PRECONDITION_LOCK_HELD` (registered above, exit 75).

#### `LIFECYCLE_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `LIFECYCLE_HARD_CAP_EXCEEDED` | pre-push cap guard tripped: `has_queued_fix_commits(state) AND Round >= MaxRounds` (so `Round` is never allowed to exceed `MaxRounds`; the cap-tripping push is refused) | hard cap reached without quiescence | resolve outstanding escalations; raise `--max-rounds` and re-run (a successful cycle clears `LastError` automatically); or hand off to human review |

Adding new codes is straightforward; the registry's structure (`<CATEGORY>_<SPECIFIC>` with what/why/how) is the stable contract that agents and humans both consume.

---

## Sections 6, 7 — Open sub-designs (TBD)

These sections are NOT YET DRAFTED. Listed here so the reviewer can leave annotations on the open questions. (Section 4 is drafted below; Section 5 is drafted further down; Section 8 is sketched at the end.)

## Section 4 — Quiescence model

Section 4 owns the **quiescence predicate** (when end-of-cycle resolution should transition `awaiting-review` → `quiesced`), the **`waitLocked` internals** (the `wait` verb's blocking-loop implementation declared at §3.3 line 794), the **human-review merge constraint** (a label-based satisfaction protocol that does NOT block the lifecycle), the **auto-merge eligibility contract** exposed by `prgroom status --json` (handoff surface for the future merge-gate `gmxo`/`td39`), and the **auto-request-human-review behavior** that adds a visible GitHub label when the CLI's lifecycle reaches a review-content gate.

Section 4 chose **hard gates + idle timer** over the originally-sketched "weighted probability" framing. Operators reading `prgroom status` get an explicit named gate as the answer to "why didn't it quiesce?" — not a tuneable score.

### 4.1 Quiescence decision: hard gates + idle timer

`waitLocked` evaluates a **quiescence predicate** on every poll. The predicate is satisfied iff all hard gates pass AND the idle timer has elapsed. Hard gates are binary and operator-debuggable; `prgroom status` names the failing gate.

**Hard gates (all must pass):**

| Gate | Condition | Source field(s) |
|------|-----------|-----------------|
| `G_REVIEWERS` | Every reviewer with `Required=true` has `Status ∈ {review_found, declined}` | `state.Reviewers[*].Required`, `state.Reviewers[*].Status` |
| `G_CI` | `state.Quiescence.CIState ∈ {success, absent}` for `state.LastPushedHeadSHA` | `state.Quiescence.CIState` |
| `G_DISPOSITIONS` | Every `state.Items[*].Disposition != nil` (sanity check — structurally guaranteed by `fixLocked` having run this cycle per §3.3 idempotency contract) | `state.Items[*].Disposition` |
| `G_NO_BLOCKERS` | No item has `Disposition.Kind ∈ {escalated, failed}` (sanity check — §3.2 priority cascade routes those to `human-gated` before reaching this predicate) | `state.Items[*].Disposition.Kind` |

**Idle timer (the soft "let it settle" buffer):** `time.Now().UTC().Sub(state.LastActivityAt) >= idle_threshold`. `LastActivityAt` is the timestamp of the most-recent PR-side mutation observed by `pollLocked` (new comment, new review, push, CI state change, label change). The idle timer's purpose is *not* to detect bot inactivity (per-reviewer timeouts in §4.1 own that case); it gives a short final buffer in case a slow human reviewer is mid-comment-draft when all hard gates flip green.

**`G_REVIEWERS` and the `declined` substates.** A Required reviewer can reach `Status = declined` three ways:
1. Human reviewer explicitly passed (`DeclinedReason = "user-declined"`)
2. Auto-declined by `review_start_timeout` (`DeclinedReason = "timeout-no-start"`) — Copilot was requested but never engaged
3. Auto-declined by `review_finish_timeout` (`DeclinedReason = "timeout-stalled"`) — Copilot engaged but never produced a terminal review

All three count as gate-satisfying. The DeclinedReason is preserved for operator inspection via `prgroom status` so the operator can tell silence from explicit decline.

**`pollLocked` auto-decline logic (Section 4 add-on to §3.3's `pollLocked`):**

```text
function evaluate_reviewer_timeouts(state):                   # invoked inside pollLocked, post-fetch
    for r in state.Reviewers values:
        if r.Status == requested AND r.LastReviewAt.IsZero():
            if time.Now().UTC().Sub(r.LastRequestAt) > review_start_timeout:
                r.Status = declined
                r.DeclinedAt = time.Now().UTC()
                r.DeclinedReason = "timeout-no-start"
        elif r.Status == in_progress AND NOT r.LastReviewAt.IsZero():
            if time.Now().UTC().Sub(r.LastReviewAt) > review_finish_timeout:
                r.Status = declined
                r.DeclinedAt = time.Now().UTC()
                r.DeclinedReason = "timeout-stalled"
```

**"Engagement" detection — what sets `LastReviewAt` (Section 4 add-on to §3.3's `pollLocked`):** any actor-attributed activity after `LastRequestAt` and after the most-recent push timestamp:

- New comment on `/issues/{n}/comments` whose `user.login == r.Identity` (Copilot's known top-level-comment reply pattern per the reviewer-bot quirks observed in prior `wait-for-pr-comments` runs)
- New review (`/pulls/{n}/reviews`) by `r.Identity` in any state (`PENDING`, `COMMENTED`, `APPROVED`, `CHANGES_REQUESTED`)
- New inline review comment (`/pulls/{n}/comments`) by `r.Identity`
- New thread reply by `r.Identity`

First such activity flips `r.Status = in_progress` and sets `r.LastReviewAt = activity.CreatedAt`. Subsequent activity refreshes `r.LastReviewAt` AND `state.LastActivityAt`. When `r.Status` transitions to terminal (`review_found` for `APPROVED`/`CHANGES_REQUESTED`/`COMMENTED-with-final-disposition` per Section 5's contract; `declined` per the timeout paths above), no further `r.LastReviewAt` updates are needed.

**End-of-cycle interaction with §3.3's `resolve_end_of_cycle_phase`:** the priority cascade in §3.2 places quiescence at **priority 5** (after the blocker gates at priorities 1-3 and the commit-pushed rule at priority 4). `resolve_end_of_cycle_phase` calls `quiescencePredicate(state)` at priority 5; when true, sets `state.Phase = "quiesced"`, `state.Quiescence.QuiescedAt = time.Now().UTC()`. When false, phase stays `awaiting-review` and the next `waitLocked` invocation re-evaluates.

```text
function quiescencePredicate(state):
    return allReviewerGatesPass(state)        # G_REVIEWERS
       AND ciGateAllows(state.Quiescence.CIState)   # G_CI
       AND allItemsDispositioned(state)       # G_DISPOSITIONS
       AND noBlockerDispositions(state)       # G_NO_BLOCKERS
       AND time.Now().UTC().Sub(state.LastActivityAt) >= idle_threshold
```

### 4.2 `waitLocked` internals

**Contract surface** (declared at §3.3 line 794): `waitLocked(pr PRRef, state *PRGroomingState) (*PRGroomingState, error)`. Holds the PR lock for the entire invocation (no mid-sleep release). Cancellation honors a `context.Context` plumbed through `Run`'s public wrapper.

**Pseudocode notation:** `signum` below denotes the integer signal number captured by `Run`'s OS signal handler (installed at process startup per §3.7). `context.Context` itself does not carry a signal number, so the handler stores the observed signum in a value visible to the cancellation path (e.g. an atomic int, a channel read on demand, or a small accessor on the deps surface). Concrete implementation is the implementer's call; the contract is only that `signum` is available at error-construction time for the exit-code mapping in §3.7.

```text
function waitLocked(pr, state) (*PRGroomingState, error):
    for {
        # Wake event 1: signal-cancel — return immediately, RUNTIME_CANCELLED tier
        if ctx.Err() != nil:
            return state, taggedError(RUNTIME_CANCELLED, ctx.Err(), Signum=signum)

        # Interruptible sleep — wakes on poll_interval expiry or ctx.Done
        select {
            case <-time.After(poll_interval):
            case <-ctx.Done():
                return state, taggedError(RUNTIME_CANCELLED, ctx.Err(), Signum=signum)
        }

        # Wake event 2: any pollLocked error propagates per §3.3 handle_verb_error
        state, err = pollLocked(pr, state)
        if err != nil:
            return state, err          # runLocked's handle_verb_error decides Propagate vs Continue

        # pollLocked side-effects relevant to §4 (added by this section):
        #   - updates state.LastActivityAt on observed PR-side mutations
        #   - calls evaluate_reviewer_timeouts(state)  (§4.1)
        #   - updates state.Quiescence.CIState from latest check-runs/statuses for state.LastPushedHeadSHA
        #   - reads state.HumanReviewLabelAdded is unchanged here (set by §4.7's request_human_review_if_needed)

        # Wake event 3: phase already moved off awaiting-review/idle (fix commits arrived,
        # external push, PR merged externally, etc.) → return to let runLocked re-enter cycle
        if state.Phase != awaiting-review AND state.Phase != idle:
            return state, nil

        # Wake event 4: quiescence predicate satisfied → trip to quiesced, write, return
        if quiescencePredicate(state):
            state.Phase = quiesced
            state.Quiescence.QuiescedAt = time.Now().UTC()
            store.Write(state)
            return state, nil

        # Otherwise: loop back, sleep again
    }
```

**Wake event registry (all paths that exit `waitLocked`):**

| Trigger | Exit condition | Phase on exit | Error tier |
|---------|---------------|---------------|------------|
| Signal (SIGINT/SIGTERM) | `ctx.Done()` | unchanged | `RUNTIME_CANCELLED` (130/143 per §3.7) |
| `pollLocked` transient error | gh API past retry budget | unchanged | `RUNTIME_TRANSIENT` (75) — scheduler retries |
| `pollLocked` terminal error | gh auth expired, etc. | `human-gated` | `RUNTIME_TERMINAL_USER` (77) |
| Activity moves phase | fix commits arrived → `fixes-pending`; PR merged externally → `merged`; escalated/failed item produced → `human-gated` via §3.2 cascade on next cycle | as observed | `nil` |
| Quiescence trips | `quiescencePredicate == true` | `quiesced` | `nil` |
| *(intentional non-trigger)* | n/a — no hard wait-timeout in MVP | n/a | n/a |

**No hard wait-timeout in MVP** — the design relies on (a) per-reviewer timeouts (§4.1) to handle bot silence, (b) the `human-review-required` label as the explicit operator merge-block (§4.4), (c) signal-cancel as the manual bail-out. A hard wait-timeout would add a fourth exit path racing with the others without solving a distinct failure mode. If operations experience shows long waits hanging too often, it's a one-line addition in v2.

**Lock semantics:** lock is held continuously for the entire `waitLocked` invocation. Per §3.3 line 806, the `status` verb is lock-free, so operators can `prgroom status <pr>` during long waits without contending.

**Signal handling:** `runLocked`'s caller plumbs `context.Context` through `Run`'s public wrapper; the context cancels on SIGINT/SIGTERM. `waitLocked` honors `ctx.Done()` both at the top of each loop iteration AND inside the `select` that wraps the sleep. Distinct error tier from `RUNTIME_TRANSIENT` (per §3.3 line 799) so the scheduler does NOT retry a cancelled wait.

**Resumability (crash-recovery semantics).** All §4 timestamps in state are stored as **absolute UTC** (RFC3339):

- `state.LastActivityAt`
- `state.Quiescence.QuiescedAt`
- `state.Reviewers[r].LastRequestAt`
- `state.Reviewers[r].LastReviewAt`
- `state.Reviewers[r].DeclinedAt`

Timeout *deadlines* are **derived per-evaluation**, never stored:

```text
startDeadlinePassed  := time.Now().UTC().Sub(r.LastRequestAt) > review_start_timeout
finishDeadlinePassed := !r.LastReviewAt.IsZero() &&
                        time.Now().UTC().Sub(r.LastReviewAt) > review_finish_timeout
idleSatisfied        := time.Now().UTC().Sub(state.LastActivityAt) >= idle_threshold
```

Crash-recovery flow:
1. Process dies mid-`waitLocked`. OS releases the §2 file-adapter lock via `flock(2)`-on-fd-close (per §3.7 line 958).
2. Scheduler re-invokes `prgroom run`. `Run` acquires lock; `runLocked` reads state from disk.
3. All §4 timestamps are intact (last written by `pollLocked` before crash).
4. Re-entered `waitLocked`'s first `pollLocked` re-evaluates deadlines from current `time.Now().UTC()`. Elapsed time across the crash gap counts. A reviewer with `Now - LastRequestAt > review_start_timeout` auto-declines as expected — same outcome as if the process had never died.

Config-change semantics: operator raises `review_start_timeout` from 3m→5m mid-flight via TOML edit. Next `pollLocked` evaluation reads the new value (Section 7 owns config-reload cadence; assume re-read per `Run` invocation). A reviewer who would have been auto-declined at 3m gets the extension. Operator intent always wins because deadlines aren't frozen at start-time.

### 4.3 Configuration surface

All Section 4 knobs follow §3.5's established precedence pattern: **CLI flag > env var > per-repo `.prgroom.toml` > built-in default**.

| Setting | Default | Flag | Env var | TOML key |
|---------|---------|------|---------|----------|
| `idle_threshold` | `10m` | `--idle-threshold` | `PRGROOM_IDLE_THRESHOLD` | `quiescence.idle_threshold` |
| `poll_interval` | `30s` | `--poll-interval` | `PRGROOM_POLL_INTERVAL` | `quiescence.poll_interval` |
| `review_start_timeout` | `3m` | `--review-start-timeout` | `PRGROOM_REVIEW_START_TIMEOUT` | `quiescence.review_start_timeout` |
| `review_finish_timeout` | `15m` | `--review-finish-timeout` | `PRGROOM_REVIEW_FINISH_TIMEOUT` | `quiescence.review_finish_timeout` |
| `auto_request_human_review` | `true` | `--auto-request-human-review[=false]` | `PRGROOM_AUTO_REQUEST_HUMAN_REVIEW` | `quiescence.auto_request_human_review` |

All durations parse with Go's `time.ParseDuration` syntax (`30s`, `10m`, `1h30m`). Section 7 owns the TOML format and config-loading mechanism; §4 just declares the keys it consumes.

### 4.4 Human-review merge constraint (NOT a lifecycle blocker)

The PR label `human-review-required` is a **merge constraint**, not a lifecycle constraint. The full poll → cluster → fix → push → rereview → reply → resolve cycle runs normally when the label is set; quiescence still trips when gates pass. The label only affects `auto_merge_eligible` in §4.6.

**The constraint:** GitHub PR label `human-review-required` (literal string, case-insensitive match). Indicates a human must approve before merge.

**Satisfaction signals (OR — any one satisfies the constraint):**

- Label `human-approved` (literal string, case-insensitive) — covers the self-PR case where GitHub blocks self-approval
- A GitHub PR review with `state == APPROVED` AND `reviewer.actor.type != "Bot"` — i.e., a real human approval through the standard reviewer flow

The `Bot`-filter on PR approvals is **load-bearing**: without it, Copilot's auto-approval of a self-PR would satisfy the gate. Bot approvals do not count for the human-review gate.

**CLI read path:** `pollLocked` already fetches labels and reviewer-state as part of standard PR poll. The constraint check is pure-derivation from existing state fields — no new API calls. `pollLocked` does NOT persist `HumanReviewConstrained` or `HumanReviewSatisfied` in state; both are derived per-status-query because they're functions of current GitHub state, not lifecycle history.

**Lifecycle behavior:** none. `pollLocked` does NOT transition phase based on the label. The cluster/fix/push/reply/resolve cycle continues normally.

**Quiescence behavior:** unchanged from §4.1 — gates pass → idle timer trips → `Phase = quiesced`. The label does NOT block quiescence.

**Operator workflow:**

- To require human review (upstream signal): `gh pr edit --add-label human-review-required`
- To satisfy via label (self-PR or supplemental): `gh pr edit --add-label human-approved`
- To satisfy via standard reviewer flow: leave a GitHub PR review with "Approve"
- To unrequire (rare; usually leave the historical record): `gh pr edit --remove-label human-review-required`

### 4.5 Relationship to §3.5 hard-cap

Quiescence (§4) and the round hard-cap (§3.5) are **independent terminal paths**:

| | Round hard-cap (§3.5) | Quiescence (§4) |
|---|---|---|
| Trigger condition | `state.Round >= MaxRounds` AND `has_queued_fix_commits(state)` | All hard gates pass AND idle timer trips |
| Triggers from phase | `fixes-pending` (pre-push check in `runLocked`) | `awaiting-review` (inside `waitLocked` or end-of-cycle resolver) |
| Result phase | `human-gated` | `quiesced` |
| `LastError` | `LIFECYCLE_HARD_CAP_EXCEEDED` | (unset) |
| Auto-merge-eligible | No | Yes (modulo §4.6) |
| Auto-request human review | Yes (§4.7) | No |
| Recovery | Operator raises `--max-rounds` + re-runs; or `resolve-escalated` + re-runs | None needed — `quiesced` is success |

A PR can reach either terminal but not both in the same cycle: the round cap fires inside `runLocked`'s cycle (pre-push, §3.3 line 678), before the next `waitLocked` invocation. Once in `human-gated`, `waitLocked` is not invoked — the §3.2 priority cascade routes elsewhere.

**No new hard-cap defined in §4.** The bead description's "hard cap parallel to current `wait-for-pr-comments` round-3 cap" requirement is satisfied by §3.5's existing `MaxRounds=3` default. §4 only adds the auto-request-human-review behavior (§4.7) that fires when §3.5's cap trips.

### 4.6 Auto-merge eligibility contract

**Out of scope for MVP:** the actual merge gate is owned by future bead `gmxo`; the policy layer (coverage, security-scan, branch-protection overlay) is owned by future bead `td39`. Section 4 only defines what `prgroom status --json` exposes so those downstream beads have a stable contract to consume.

**`prgroom status <pr> --json` output:**

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

**Computation:**

```text
auto_merge_eligible :=
  merge_gates.phase_is_quiesced     AND
  merge_gates.last_error_clear      AND
  merge_gates.no_blocker_items      AND
  merge_gates.human_review_satisfied

merge_gates.phase_is_quiesced      := state.Phase == quiesced
merge_gates.last_error_clear       := state.LastError == ""
merge_gates.no_blocker_items       := no item with Disposition.Kind ∈ {escalated, failed}
merge_gates.human_review_satisfied := NOT human_review.required OR human_review.satisfied_by != null

human_review.required              := hasLabel("human-review-required")
human_review.satisfied_by          := first matching:
                                        "label" if hasLabel("human-approved")
                                        "approval:{login}" if any review has state==APPROVED AND NOT actor.type=="Bot"
                                        null otherwise
human_review.candidates_seen       := list of all examined PR-approval candidates with bot-filter outcome,
                                      e.g. [{"login": "github-copilot[bot]", "approved": true, "counted": false, "reason": "bot"}]
```

The `candidates_seen` field is for operator debuggability — answers "why didn't approval X count?" without re-running queries.

**Stability commitment:** the JSON shape above is part of §4's stable interface. Adding fields is non-breaking. Removing or renaming fields is breaking and requires a version-bumped JSON envelope (deferred to `gmxo`/`td39` brainstorm if needed).

### 4.7 Auto-request human review on lifecycle gating

When `runLocked` transitions to `human-gated` for a **review-content reason**, prgroom automatically adds the `human-review-required` label to the PR. This complements the existing `EscalationSink` event (stderr / bd-adapter) with a GitHub-visible marker so operators scanning their PR list immediately see "automation gave up here."

**Triggering conditions (any one):**

| Trigger | Source |
|---------|--------|
| `state.LastError == "LIFECYCLE_HARD_CAP_EXCEEDED"` | §3.5 round hard-cap trip |
| Any item with `Disposition.Kind == "escalated"` | §3.2 priority cascade (escalated items) |
| Any item with `Disposition.Kind == "failed"` | §3.2 priority cascade (audit-failed or agent-could-not-converge) |

**Explicit non-triggers (review-content vs infra/state distinction):**

- `RUNTIME_TERMINAL_USER` (gh auth expired, etc.) — infra problem, not a review problem
- `STATE_CORRUPT` / `STATE_SCHEMA_UNKNOWN` — operator-investigate-state-file
- `RUNTIME_PUSH_REJECTED` / `RUNTIME_GH_TERMINAL` — infra problem

**Implementation — `request_human_review_if_needed(state)`:**

```text
function should_request_human_review(state):
    return state.LastError == "LIFECYCLE_HARD_CAP_EXCEEDED"
        OR any(item.Disposition != nil AND item.Disposition.Kind == "escalated" for item in state.Items)
        OR any(item.Disposition != nil AND item.Disposition.Kind == "failed"    for item in state.Items)

function request_human_review_if_needed(state):
    if NOT auto_request_human_review:                             # §4.3 config knob
        return
    if NOT should_request_human_review(state):
        return
    if state.HumanReviewLabelAdded:
        return                                                   # already added once this gating event
    err := gh.AddLabel(pr, "human-review-required")
    if err != nil:
        log_stderr("prgroom: warning — failed to add human-review-required label: " + err.Error())
        return                                                   # best-effort; flag stays false; next cycle retries
    state.HumanReviewLabelAdded = true
    store.Write(state)
```

`request_human_review_if_needed` is invoked alongside `escalate_if_needed` at the **same two dedup-safe call sites in `runLocked`** (per §3.3): the loop-top terminal-for-CLI check, and immediately before each Propagate-return after `handle_verb_error`. Both functions are idempotent and best-effort; both follow the same crash-window dedup posture.

**Reset semantics (mirrors §3.5 line 868 `LastError` clearing):** `state.HumanReviewLabelAdded` is reset to `false` on the **same condition** that clears `LastError` — successful end-of-cycle resolution to any phase other than `human-gated` (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, or `merged`). Wired into §3.3's `runLocked` pseudocode at the same point that clears `LastError`. After reset, if the gating condition recurs (a new cap-trip after operator raised `--max-rounds`), the label gets re-added on the next gating event.

**Operator override (deliberate one-way intent):** if the operator manually `gh pr edit --remove-label human-review-required` while `state.HumanReviewLabelAdded == true`, prgroom does NOT re-add the label on the next invocation — `HumanReviewLabelAdded` is still `true` in state, so `request_human_review_if_needed` short-circuits. The label re-adds only after the reset path above fires AND the gating condition recurs. This preserves operator intent ("I've handled this") without permanent suppression.

**Interaction with §4.4's `human-approved` satisfaction signal:** the operator adding `human-approved` (or leaving a human PR approval) AFTER prgroom added `human-review-required` causes §4.6's `auto_merge_eligible` to become `true`. **The `human-review-required` label persists** as historical record; the operator does NOT need to remove it. Future audits see "constraint was raised AND satisfied." This is exactly why §4.4 chose positive-signal satisfaction over absence-of-negative — clean operator-actionable records.

**Permissions:** `gh.AddLabel` requires triage or write access on the repo. Failure is logged to stderr (one-line warning) but does NOT tier-tag the error, does NOT block lifecycle progression, does NOT propagate via `handle_verb_error`. Same best-effort posture as Sink-error handling in §3.3 line 745. Operators seeing persistent label-add failures should check their PAT scopes.

### 4.8 §2 schema fields consumed by Section 4

| §2 field | Section using | Purpose |
|----------|---------------|---------|
| `PRGroomingState.LastActivityAt` | §4.1, §4.2 | idle-timer reference |
| `PRGroomingState.HumanReviewLabelAdded` | §4.7 | dedup flag for `human-review-required` label auto-add |
| `ReviewerState.LastRequestAt` | §4.1 | `review_start_timeout` reference |
| `ReviewerState.LastReviewAt` | §4.1 | `review_finish_timeout` reference; first observed engagement post-request |
| `ReviewerState.DeclinedAt` | §4.1 | timestamp of decline (any reason) |
| `ReviewerState.DeclinedReason` | §4.1, §4.6 | one of: `user-declined`, `timeout-no-start`, `timeout-stalled` |
| `QuiescenceState.CIState` | §4.1 | `G_CI` gate input for `state.LastPushedHeadSHA` |
| `QuiescenceState.QuiescedAt` | §4.2, §4.6 | set on transition to `quiesced`; surfaced in status JSON |
| `ReviewerStatus.declined` | §4.1 | covers explicit pass AND auto-decline; subcause via `DeclinedReason` |

### Section 5 — Agent dispatch internals (named contracts)

The cheap agent is bad at deciding intent but good at grouping; the heavy agent is good at deciding intent because it can see the whole picture. The two contracts split along that line:

- **Cluster** (cheap agent) — groups related items into fix-bundles. Does NOT decide disposition.
- **Fix** (heavy agent / orchestrator) — for each cluster, decides per-item disposition AND implements the work where warranted. Inherits the full PR context, prior PR memories, and access to skills/agents.
- **Resolve-escalated** (human-initiated verb) — flips an `escalated` disposition into a terminal one and lets the lifecycle continue.

Each contract is a **stable, versioned interface** between the CLI and the agent-CLI. That stability is what lets us swap `claude -p` for `codex exec`, change models, run different agents per hand-off, or fall back when the primary is unavailable — without touching the CLI's lifecycle code.

#### Contract A — `cluster`

- **When:** during the `cluster` verb. Operates on the set of items with `ClusterID == ""`.
- **Default agent CLI (primary → fallback chain):** Prefer a local model via `ollama` (Gemma 4 or similar small classifier) if installed; otherwise `claude -p` with model `haiku` / effort `low`; otherwise `codex-mini`. Cheap, fast — grouping intent is NOT decisional work, so locally-runnable models are appropriate.
- **Input (JSON, written to a file passed by path):**
  ```json
  {
    "contract_version": 1,
    "pr": { "owner": "...", "repo": "...", "number": 123 },
    "items": [ { /* full ReviewItem entries needing clustering */ } ],
    "pr_context_path": "<path to dumped PR detail (title, body, recent commits, CI summary)>",
    "memory_path": "<path to PR memory directory, if any prior rounds exist>"
  }
  ```
- **Output (JSON):**
  ```json
  {
    "clusters": [
      {
        "cluster_id": "c-abc123",
        "item_gh_ids": ["<id>", "<id>"],
        "rationale": "<short why-these-belong-together>"
      }
    ]
  }
  ```
- **Audit guards:** every input item appears in exactly one cluster; cluster ids unique; rationale non-empty per cluster.
- **Failure modes:** malformed JSON, items missing from output, agent timeout → retry once; on second failure, fall back to **per-item degenerate clusters** (one item per cluster) so the fix verb can still proceed.

#### Contract B — `fix`

- **When:** during the `fix` verb, **once per cluster** (was: once per FIX item). Serial in MVP (parallel deferred).
- **Default agent CLI:** `claude -p` with model `sonnet[1m]` and effort `medium`. This launches an **orchestrator** agent that will itself choose skills/sub-agents (e.g. `quality-reviewer`, `simplify`, language-specific debuggers). Model and effort for those sub-agents are set by the orchestrator, not by `prgroom`.
- **Input (JSON, written to a file passed by path):**
  ```json
  {
    "contract_version": 1,
    "pr": { "owner": "...", "repo": "...", "number": 123 },
    "cluster_id": "c-abc123",
    "item_gh_ids": ["<id>", "<id>"],
    "items": [ { /* full ReviewItem entries for this cluster */ } ],
    "pr_detail_path": "<path to file: full gh PR API output (title, body, files, all comments, reviews)>",
    "branch_state_path": "<path to file: recent commits + diff-since-base>",
    "memory_dir": "<path to PR memory directory; agent may read prior rounds and MUST write new memories per the PR-memory skill (see Section 8)>",
    "response_outbox_dir": "<path to directory the agent writes per-item response text files to>"
  }
  ```
  The CLI does the gh-API legwork up-front and dumps everything to files; the agent does NOT re-call gh itself. Origin of `root_cause_note` (from the old contract): it was an artifact of `fix-bug` formulas — it does NOT apply to PR-grooming and is dropped. PR-memory dir is a forward-reference to **Section 8 — PR memory management** (a new sub-design).
- **Output (JSON):**
  ```json
  {
    "contract_version": 1,
    "items": [
      {
        "gh_id": "<id>",
        "disposition": "fixed" | "already_addressed" | "skipped" | "deferred" | "wont_fix" | "escalated" | "failed",
        "commit_shas": ["<sha>", "..."],          // required for fixed + already_addressed; multiple permitted (impl→review→fix rounds within the cluster)
        "response_path": "<file in response_outbox_dir>",  // optional; long-form reply text the reply verb will use verbatim
        "rationale": "<text>",                    // required for skipped | deferred | wont_fix | escalated | failed; user-facing for skipped|deferred|wont_fix
        "recommended_gate": "full" | "lite"       // required for fixed
      }
    ],
    "memory_writes": ["<path>", "..."]            // optional; files the agent created in memory_dir (audited)
  }
  ```
- **Side effects allowed:** the agent may make **multiple commits** per item. Multiple-commit support is needed when the agent does an impl → review → fix cycle internally within the cluster work. The audit enforces that every claimed SHA is reachable AND that no orphan commits exist (every new commit on the branch is claimed by some item's `commit_shas`).
- **Audit guards (CLI-side):**
  - `fixed` → every `commit_shas[i]` is a real commit between pre-cluster SHA and post-cluster HEAD; at least one commit per `fixed` item
  - `already_addressed` → every `commit_shas[i]` predates the pre-cluster baseline AND is reachable in PR-branch history
  - `skipped | deferred | wont_fix | escalated | failed` → non-empty `rationale`
  - Orphan check: every commit between pre-cluster and post-cluster HEAD must be claimed by some item
- **Failure modes:** audit violations re-classify the offending item to `failed` with `rationale = "subagent contract violation: <details>"` and emit an escalation via the `EscalationSink` (see below). Stash isolation (`git stash` on orphan commits) preserves the contamination for inspection.

#### Contract C — `resolve-escalated` (human-initiated; not an agent contract)

This surfaces as a **CLI verb**, not an agent shell-out. The verb takes an `<item-id>` and reclassifies the item's disposition.

- **CLI usage:** `prgroom resolve-escalated <pr> <gh-id> --as fixed|skipped|deferred|wont_fix --rationale '<text>' [--commits <sha>,<sha>]`
- **What it does:** finds the item, replaces `Disposition` accordingly, sets `Disposition.DecidedBy = "human:<git-user>"`. The lifecycle resumes on the next `run` / `wait` / `reply` invocation.
- **Why a verb:** interactive prompts mid-flight create UX coupling between the CLI and its caller; an explicit verb is debuggable, scriptable, and undo-able (re-run with different args).

#### Escalation surface — via `EscalationSink` abstraction

The CLI does NOT directly call `bd label add ...` from inside Section-5 contract code. Escalation routing goes through an `EscalationSink` interface so the CLI works with or without beads:

```go
package escalation

type Escalation struct {
    PR       PRRef
    Reason   string             // free-form, public-safe
    Item     *prsession.ReviewItem // optional; the item that triggered the escalation
    Severity Severity            // info | warn | block
}

type Sink interface {
    // Emit records ("files", verb-sense) an Escalation. The method name was
    // chosen for clarity vs the `file` adapter; both `stderr`, `file`, and
    // `bd` adapters implement this single method.
    Emit(Escalation) error
}
```

Adapters:

| Sink | When | Behavior |
|---|---|---|
| **stderr** | Default (chat interactive) | Pretty-print to stderr; orchestrator/user sees it in-context |
| **bd** | When `--bd-bead <id>` flag set (or `PRGROOM_BD_BEAD` env) | Adds `human` label + appends notes (same effect as current autonomous Skill A behavior) |
| **file** | When `--escalation-file <path>` set | Append JSON line per escalation; used by external watchers / cron |

#### Verb → contract → CLI action

| Verb                | Agent contract | CLI does (deterministic) |
|---------------------|----------------|--------------------------|
| `poll`              | none           | gh API calls (comments, reviews, CI status); update state |
| `cluster`           | A (per batch)  | persist `ClusterID` on each item |
| `fix`               | B (per cluster)| dump gh detail; serial cluster dispatch; per-subagent audit; orphan-commit check; stash isolation on audit fail |
| `push`              | none           | `git push` (any accumulated fix-agent commits) |
| `rereview`          | none           | remove/add reviewer dance to coerce a fresh `review_requested` event |
| `reply`             | none           | render templates + use `response_path` files; post via gh API |
| `resolve`           | none           | GraphQL `resolveReviewThread` for `review_thread` items whose `Disposition.Kind ∈ {fixed, already_addressed}` |
| `resolve-escalated` | none           | human-initiated reclassification of one item |
| `wait`              | none           | sleep + re-poll; quiescence threshold may transition phase |
| `run`               | A + B chained  | full lifecycle loop |

#### Contract versioning

Each contract carries `contract_version: int` in its JSON input/output. The CLI bumps version on any breaking shape change; old versions may be supported in parallel for migration windows.

#### Agent-CLI configuration & fallback

Per-contract agent CLI is configurable and supports a fallback for unavailability:

```toml
# prgroom config (location TBD in Section 7)
[agents.cluster]
primary  = { cli = "ollama", model = "gemma4" }                 # local; near-zero per-call cost
fallback = { cli = "claude", model = "haiku", effort = "low" }
fallback2 = { cli = "codex", model = "gpt-5.4-mini" }

[agents.fix]
primary  = { cli = "claude", model = "sonnet[1m]", effort = "medium" }
fallback = { cli = "codex",  model = "gpt-5.4", write = true }
```

Fallback triggers: primary binary not on PATH; primary exits with quota/auth/network error code; primary times out (per-contract budget). If both primary AND fallback fail, the verb emits a `failed` disposition for the affected items + escalates via the `EscalationSink`.

#### Prompt templates

Each contract's prompts (system + user) live in `internal/agent/prompts/<contract>.tmpl` as Go `text/template` files. Templates take a contract-specific struct as data. Loaded once at startup; the template engine is the same one used for reply rendering. The user can override via `PRGROOM_PROMPTS_DIR=<dir>` (any matching filename in the override dir wins). Override is for power users / experimentation, not the default path.

#### Token-usage logging

The CLI logs **per-contract token usage** to `$XDG_STATE_HOME/prgroom/usage.jsonl` when the agent CLI emits a usage line (Claude and Codex CLIs both do). The CLI does NOT do analysis or aggregation; this is **MVP baseline-capture only**, so future cost-optimization work has data to start from. The "should the CLI surface cost estimates inside its output?" question is deferred.

#### Audit guards in Go

Each contract's audit is a Go function with table-driven tests (parallels the current `audit-subagent-report.sh`). Audit failures emit structured errors and route through `EscalationSink` as appropriate.

### Section 6 — Migration plan

- Phase 1 (absorb wait-for-pr-comments): exact verb set landed; how the skill body changes; what bash scripts get deleted
- Phase 2 (absorb reply-and-resolve-pr-threads): same
- Rollback strategy if MVP fails in production
- Coexistence with existing skills during transition (both can run side-by-side?)
- **No legacy-state migration.** In-flight PRs under the old JSON inventory format are *not* automatically migrated. Cutover is ad-hoc: finish out any in-flight PR using the current skill before switching that PR's tooling to `prgroom`. New PRs use `prgroom` from day one.

### Section 7 — Build, distribution, and test discipline

- Build pipeline (just `go build`? GHA-built artifacts? `go install`?)
- Installation through `scripts/install.sh`: build from source or fetch binary?
- Versioning, release cadence

#### Test discipline (load-bearing, not aspirational)

Per the design's stated motivation ("the more we push into this modular monolith CLI codebase, the more we can put better unit and integration tests around these functions"), test discipline is a first-class constraint on the architecture itself, not a Section-7 afterthought:

- **Interfaces designed FIRST for unit testability.** Every cross-module dependency goes behind an interface (gh, git, prsession, agent-dispatcher, clock, randomness). No direct stdlib reach-through from `internal/lifecycle/`.
- **Fit-test commitment.** Each `internal/*` module ships with a `*_fit_test.go` that exercises the module's public surface against a minimal fake-implementation of its dependencies. A module without a passing fit-test does not merge.
- **No mocks of code we own.** Fakes (full small implementations) for our own interfaces; mocks only at the system boundary (HTTP, subprocess, filesystem). Parallel to the existing `writing-unit-tests` skill's guidance.
- **Test pyramid targets:** unit (`go test ./...`, fast, no I/O) — broad coverage; integration (fixture repos under `testdata/`, real git, real `prsession.file`) — narrower; end-to-end (recorded gh API responses via `gock` or equivalent) — narrowest.
- **Coverage floor: 80% line / 70% branch on changed code per PR.** Inherited from the project's AGENTS.md.
- **CI:** prgroom tests run in GHA on every PR. Merge-gate on `go test ./... -race` + `golangci-lint` + `govulncheck`.
- **Coverage GHA gate:** GHA runs `go test ./... -coverprofile=cover.out`, then a coverage action (`codecov-action`, or in-line `go tool cover -func | awk` script) enforces the 80% line / 70% branch floor on changed code per PR. Build fails when the floor is breached; floor is reported as a PR status check. Choice of tool deferred to implementation; `codecov-action` is the likely default.

### Section 8 — PR memory management (new sub-design)

Across re-review rounds the `fix` agent needs to remember decisions from earlier passes: "we already declined this with rationale X", "we agreed on Y pattern earlier", "the cluster of foo-related comments was deferred to a follow-up bead Z." Without persistent memory, the agent re-litigates closed disagreements and may regress prior decisions.

**Not yet designed; called out so it isn't lost.** Open questions for the dedicated sub-design:

- **Storage location.** **Both**: a per-PR directory (`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>/memory/`) is the always-present file-backed home (agent-side this is `memory_dir` in Contract B); when bd is available it ALSO mirrors decisions into bd beads of type `decision` or `memory`, so beads remain a source of truth that survives outside the file-backed store. The file directory keeps the agent bd-agnostic; the bead mirror keeps the system memory durable and queryable.
- **Memory shape.** Free-form markdown files. No schema enforced; the agent picks file names and structure that fit the round's content. Bead-mirrored entries carry the same markdown as their description/notes field.
- **Read API.** Agent receives `memory_dir` path in its Contract B input. Reads what it wants.
- **Write API.** Agent declares `memory_writes` in output. CLI audits that all writes landed inside `memory_dir`; mirroring to beads (when enabled) happens CLI-side after audit passes.
- **Compaction / pruning.** Defer. Memory is PR-scoped so unbounded growth is not expected to be a problem in the normal case. Revisit only if it becomes one.
- **Cross-PR memory.** Future enhancement; out of MVP scope. The bead mirror is a natural integration point if/when we want it.
- **Skill ownership.** A new `pr-memory-management` skill that the `fix` agent invokes? Or simply documented prompt template guidance? Decision deferred; both are workable.

This sub-design is deferred to a separate spec but **MVP must carve out the skeleton hooks** (memory_dir input, memory_writes output) so we don't rework Contract B again later.

---

## Risks & open questions

1. **CLI becomes a new god-node.** Mitigation: internal modularity (each `internal/*` is its own module with its own tests). Discipline-required, not automatic. Reinforced by the test-discipline commitment in Section 7.
2. **Cold-start latency.** Go ~50–100ms; acceptable but not free. Cron-fired invocations every 60s could add up. May favor longer cadences (5–15min) for autonomous mode.
3. **gh API rate limits.** A `sweep` over many open PRs could hit them. Need backoff strategy.
4. **bd adapter (v2) is coupling-heavy.** Stuffing JSON into bead notes is workable but ugly. Alternative: bead description for metadata, separate file for items. Defer to v2.
5. **Concurrency UX.** Lock-out is correct but may surprise users; need clear error messaging (covered by precondition-gating contract).

## Deferred to later versions

- **`detect-pr-push.sh` PostToolUse hook coexistence with `prgroom`** — the hook currently suggests `wait-for-pr-comments`. Reworking the hook to point at `prgroom run` (or be replaced entirely by a cron/autonomous trigger) is **deferred to v3+**. During MVP, the existing hook stays as-is and points at the (thinned) skill; the thinned skill shells out to `prgroom` internally, so the hook still works without changes.
- **Auto-detection of in-flight PRs at cutover.** No migration tool. (See Section 6.)
- **Parallel `fix` subagents.** Serial in MVP; file-overlap prediction is unsolved.
- **`bd` adapter for `prsession.Store`.** File-only in MVP.
