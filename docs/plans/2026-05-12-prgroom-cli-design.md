# Design: `prgroom` CLI — replace wait-for-pr-comments + reply-and-resolve-pr-threads

**Status:** Draft — brainstorming in progress (Sections 1, 2, 5, 8 fleshed out; Sections 3, 4, 6, 7 sketched).
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
4. Persisting state behind a `WorkTracker` interface so recovery, idempotency, and inspection are uniform regardless of caller (skill, cron, manual invocation, or — later — executable-bead).

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
│   internal/tracker/     WorkTracker interface            │
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
| JSON inventory at `~/.claude/state/pr-inventory/` | `WorkTracker` file-adapter default; bd-adapter optional (v2) |
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
| `sweep <repo>` | Cross-PR autonomous mode: list open PRs, invoke `run` for each. (Optional MVP if cheap.) |

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

Stdout remains reserved for normal verb output (status JSON, etc.) so agents can parse stderr independently. The full error-code registry is owned by the spec's Section 3 (lifecycle state machine — TBD).

---

## Section 2 — `WorkTracker` interface + state schema

### Interface

```go
package tracker

type PRRef struct {
    Owner  string
    Repo   string
    Number int
}

type WorkTracker interface {
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

Selection at runtime: `--tracker file` (default), `--tracker bd` (v2), or env var `PRGROOM_TRACKER`.

### State schema (`schema_version: 1`)

The CLI is the schema owner. We absorb the *information* from the old inventory schema but don't preserve its layout — there is no Skill A/B contract to honor. Named so other CLI-internal state (if any) is unambiguous.

```go
package tracker

type PRGroomingState struct {
    SchemaVersion       int             `json:"schema_version"`
    PR                  PRRef           `json:"pr"`
    Phase               PRPhase         `json:"phase"`
    Round               int             `json:"round"`
    LastPollSHA         string          `json:"last_poll_sha"`
    LastPolledAt        time.Time       `json:"last_polled_at"`
    LastActivityAt      time.Time       `json:"last_activity_at"`
    HumanReviewRequired bool                       `json:"human_review_required,omitempty"`
    Reviewers           map[string]ReviewerState   `json:"reviewers"`            // keyed by reviewer Identity
    Items               []ReviewItem               `json:"items"`
    Quiescence          QuiescenceState            `json:"quiescence"`
    LastError           string                     `json:"last_error,omitempty"`
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
    PhaseHumanGated       PRPhase = "human-gated"       // terminal: human action required (escalation, hard cap, HumanReviewRequired)
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
- The re-review round hard cap (Section 4) is exceeded
- `HumanReviewRequired` was set upstream (brainstorm flagged the PR; Section 4 defines the signal)
- A `fix` subagent's audit fails irrecoverably

**`human-gated` exits** to `fixes-pending` (human resolved the issue and may have pushed) or to `merged` (human merged directly).

**`quiesced` is a true terminal that does NOT necessarily require human action.** A `quiesced` PR with all dispositions resolved, all replies posted, all FIX threads resolved, no `HumanReviewRequired` flag, and policy-satisfied CI/coverage is **auto-merge-eligible** (the merge gate is a future capability outside MVP scope; see `td39`). When `HumanReviewRequired = true` or any policy criterion fails, `quiesced` is the "we did our part — human decides whether to ship" state.

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
    ReviewerTimeout      ReviewerStatus = "timeout"
    ReviewerDeclined     ReviewerStatus = "declined"  // human reviewer explicitly passed
)

type ReviewerState struct {
    Identity      string         `json:"identity"`      // gh login or bot id
    Kind          ReviewerKind   `json:"kind"`
    Status        ReviewerStatus `json:"status"`
    Required      bool           `json:"required"`      // true = gates quiescence (PR cannot quiesce until this reviewer's Status ∈ {review_found, declined})
    LastRequestAt time.Time      `json:"last_request_at"`
    LastReviewAt  time.Time      `json:"last_review_at,omitempty"`
}
```

**Required vs optional reviewers.** A reviewer's `Required` flag is the gate signal for quiescence. By default, Copilot is added as `Required=true` on PR creation (parallel to today's behavior). Future codeowners or codex-bot reviewers can be added with `Required=true` (gates quiescence) or `Required=false` (advisory — their absence/silence does not block quiescence). Section 4 (Quiescence model) consumes this flag.

**Migration shape from old `CopilotState`:** in MVP, the `Reviewers` map contains exactly one entry — `{"copilot": ReviewerState{Kind: ReviewerBot, ...}}` — preserving current behavior. The map shape just leaves room for v2+ expansion.

#### `QuiescenceState`

```go
type QuiescenceState struct {
    LastChangeAt    time.Time `json:"last_change_at"`   // most recent PR-side mutation observed
    OpenThreadCount int       `json:"open_thread_count"`
    CIState         string    `json:"ci_state"`         // pending | success | failure
    Score           float64   `json:"score,omitempty"`  // 0.0–1.0 readiness; computed lazily
}
```

**Agent-contract callout (forward reference to Section 5):** the CLI's interactions with agent-CLIs (Contract A: cluster, Contract B: fix) need strict input/output contracts. Section 5 is the owner; the state schema above carries only the *results* (`ClusterID`, `Disposition`).

### Transactional model (verb-level)

```go
release, err := tracker.Lock(prRef)
defer release()

state, err := tracker.Read(prRef)
// ... mutate state in memory ...
state.Phase = nextPhase
state.LastActivityAt = time.Now().UTC()

return tracker.Write(prRef, state)
```

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

## Sections 3–7 — Open sub-designs (TBD)

These sections are NOT YET DRAFTED. Listed here so the reviewer can leave annotations on the open questions.

### Section 3 — Lifecycle state machine

- Exact phase transitions: which verb sets which `Phase`, valid transitions, terminal phases
- Phase-to-verb mapping for `run` (when does `run` invoke `cluster` vs `fix` vs `rereview`)
- Round-counter semantics; hard-cap behavior parallel to current Phase 6
- Failure handling: when a verb fails (push fails, GraphQL error, gh API error), what's the next state

### Section 4 — Quiescence model

- Probability function inputs: time-since-last-update, required-reviewer statuses (every `Required=true` reviewer must be in `review_found` or `declined` to allow quiescence), open-thread count, CI state, items-with-no-Disposition count
- Threshold parameters and how they're set (flags? config file? per-repo `.prgroom.toml`? heuristics bead?)
- `wait` verb semantics: how long, what events break the wait
- `human-review-required` signal: how marked upstream (brainstorm? hand-flagged label?), how the CLI reads it, how it overrides quiescence
- Hard cap parallel to current `wait-for-pr-comments` round-3 cap
- Auto-merge eligibility check: which signals must align for a `quiesced` PR to be auto-merge-eligible (handed off to a future merge-gate, outside this MVP — see bead `td39`)

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
    Item     *tracker.ReviewItem // optional; the item that triggered the escalation
    Severity Severity            // info | warn | block
}

type Sink interface {
    File(Escalation) error
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

- **Interfaces designed FIRST for unit testability.** Every cross-module dependency goes behind an interface (gh, git, tracker, agent-dispatcher, clock, randomness). No direct stdlib reach-through from `internal/lifecycle/`.
- **Fit-test commitment.** Each `internal/*` module ships with a `*_fit_test.go` that exercises the module's public surface against a minimal fake-implementation of its dependencies. A module without a passing fit-test does not merge.
- **No mocks of code we own.** Fakes (full small implementations) for our own interfaces; mocks only at the system boundary (HTTP, subprocess, filesystem). Parallel to the existing `writing-unit-tests` skill's guidance.
- **Test pyramid targets:** unit (`go test ./...`, fast, no I/O) — broad coverage; integration (fixture repos under `testdata/`, real git, real `tracker.file`) — narrower; end-to-end (recorded gh API responses via `gock` or equivalent) — narrowest.
- **Coverage floor: 80% line / 70% branch on changed code per PR.** Inherited from the project's AGENTS.md.
- **CI:** prgroom tests run in GHA on every PR. Merge-gate on `go test ./... -race` + `golangci-lint` + `govulncheck`.
- **Coverage GHA gate:** GHA runs `go test ./... -coverprofile=cover.out`, then a coverage action (`codecov-action`, or in-line `go tool cover -func | awk` script) enforces the 80% line / 70% branch floor on changed code per PR. Build fails when the floor is breached; floor is reported as a PR status check. Choice of tool deferred to implementation; `codecov-action` is the likely default.

### Section 8 — PR memory management (new sub-design)

Across re-review rounds the `fix` agent needs to remember decisions from earlier passes: "we already declined this with rationale X", "we agreed on Y pattern earlier", "the cluster of foo-related comments was deferred to a follow-up bead Z." Without persistent memory, the agent re-litigates closed disagreements and may regress prior decisions.

**Not yet designed; called out so it isn't lost.** Open questions for the dedicated sub-design:

- **Storage location.** **Both**: a per-PR directory (`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>/memory/`) is the always-present file-backed home (agent-side this is `memory_dir` in Contract B); when bd is available it ALSO mirrors decisions into bd beads of type `decision` or `memory`, so beads remain a source of truth that survives outside the file-tracker. The file directory keeps the agent bd-agnostic; the bead mirror keeps the system memory durable and queryable.
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
- **`bd` adapter for `WorkTracker`.** File-only in MVP.
