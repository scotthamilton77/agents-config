# Design: `prgroom` CLI — replace wait-for-pr-comments + reply-and-resolve-pr-threads

**Status:** Draft (Sections 1–8 fleshed out).
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

1. Moving phase orchestration out of skill prose and into a Python CLI package (`prgroom`).
2. Collapsing the existing skill surface onto the CLI — `reply-and-resolve-pr-threads` is retired, and `wait-for-pr-comments` shrinks to a thin contract-aware supervisor (`monitor-pr`) that shells out to the `prgroom` CLI (see §6).
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
│ prgroom (Python package, this MVP)                       │
│   src/prgroom/cli.py        CLI root + verbs             │
│   src/prgroom/gh/           gh subprocess wrapper        │
│   src/prgroom/git/          git ops (worktree-aware)     │
│   src/prgroom/prsession/    Store Protocol (PR session)  │
│     file.py                 default adapter (JSON/disk)  │
│     bd.py                   bd-notes adapter (later)     │
│   src/prgroom/agent/        subprocess to claude/codex   │
│   src/prgroom/lifecycle/    poll→cluster→fix→push→… + §4 │
│                            quiescence predicate (pure fn)│
└──────────────────────────────────────────────────────────┘
                          │
                          │ subprocess shell-out (fresh agent context)
                          ▼
        ┌────────────────────────────────────┐
        │ claude -p / codex exec / opencode  │
        └────────────────────────────────────┘
```

### Three usage patterns

| Pattern | Caller | CLI invocation |
|---|---|---|
| **Interactive** | User in chat, via the `monitor-pr` skill | `prgroom run <pr> --interactive` |
| **Autonomous** | Cron / `/loop` session / GHA | `prgroom run <pr> --autonomous` (or `prgroom sweep <repo>`) |
| **Executable-bead** (v2) | bd-side dispatcher | Bead payload string: `prgroom run --pr 123 --autonomous` |

### Locked decisions

- **Language:** Python 3.11+ — a `uv`-managed package that shells out to `gh` for GitHub operations. Reuses the repository's existing Python toolchain (`ruff`, `mypy --strict`, `pytest` + coverage, `pip-audit`) and conventions verbatim — no new language toolchain to stand up. The state-model / `Protocol` / `StrEnum` shape mirrors the sibling `pdlc` package (the deterministic-FSM orchestrator), which is the closest reference implementation.
- **CLI framework:** `typer` (type-hint-driven subcommands; pairs naturally with `mypy --strict`)
- **Repo placement:** same `agents-config` repo, new `packages/prgroom/` package — a fourth sibling to `installer`, `pdlc`, and `holding-place` — `uv`-managed with the standard `src/prgroom/` layout
- **Agent boundary:** CLI shells out to `claude -p` / `codex exec` / `opencode run` as subprocess. Synchronous. Each invocation = fresh agent context. The runtime is chosen per-contract in TOML config — the contract is the API, the runtime is swappable.
- **Command shape:** subcommand verbs (poll, cluster, fix, push, rereview, reply, resolve, resolve-escalated, wait, status, run, sweep)
- **MVP scope:** equivalent of `wait-for-pr-comments` + `reply-and-resolve-pr-threads`; excludes create-PR, merge, cleanup, and bead-lifecycle helpers
- **Migration path:** incremental. Phase 1 absorbs `wait-for-pr-comments` (reborn as the `monitor-pr` supervisor); Phase 2 retires `reply-and-resolve-pr-threads` (deleted — its work is covered by prgroom verbs). See §6.

### Today → tomorrow translation

| Today | Tomorrow |
|---|---|
| `wait-for-pr-comments` skill (~800 lines + 12 helpers) | Replaced by `monitor-pr` — thin supervisor: `prgroom run <pr>` + status-JSON interpretation + escalation handling (§6.2) |
| `reply-and-resolve-pr-threads` skill (~330 lines + 10 helpers) | Absorbed into `prgroom reply` + `prgroom resolve` |
| JSON inventory at `~/.claude/state/pr-inventory/` | `prsession.Store` file-adapter default; bd-adapter optional (v2) |
| 22 bash scripts | `src/prgroom/*` modules of `prgroom`, with proper unit + integration tests |
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

```python

# src/prgroom/prsession/store.py
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@dataclass(frozen=True, slots=True)
class PRRef:
    owner: str
    repo: str
    number: int

# Store persists a single PR's grooming session state. The Protocol is

# deliberately a typed key-value store with locking — NOT a tracker (no

# change-detection, no event-emission, no CAS predicates). See

# docs/architecture/prgroom/c4-l1-context.md for the contrast with PDLC's

# WorkTracker, which is a different shape entirely.
@runtime_checkable
class Store(Protocol):
    # Raises StateNotFoundError if no state for this PR yet.
    def read(self, ref: PRRef) -> PRGroomingState: ...  # pragma: no cover

    # Atomic full-state replacement. Caller does read-modify-write.
    def write(self, ref: PRRef, state: PRGroomingState) -> None: ...  # pragma: no cover

    # Exclusive lock for the duration of one verb's work.
    # Release is guaranteed by the context manager's finally — use `with store.lock(ref):`.
    def lock(self, ref: PRRef) -> AbstractContextManager[None]: ...  # pragma: no cover

    # List all PRs with tracked state. Used by `sweep`.
    def list_refs(self) -> list[PRRef]: ...  # pragma: no cover

    # Tombstone state after merge / abandon.
    def delete(self, ref: PRRef) -> None: ...  # pragma: no cover
```

### Adapters

| Adapter | When | Storage | Lock | Atomicity |
|---|---|---|---|---|
| **`file`** | MVP (default) | `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`) | `fcntl.flock(fd, LOCK_EX)` on the file | `tempfile.NamedTemporaryFile` + `os.replace` on same FS |
| **`memory`** | Tests only (not in production builds) | In-process `dict[PRRef, PRGroomingState]` | `threading.Lock` per ref | Immediate |
| **`bd`** | v2 | Linked bead's `notes` field (cap ~65KB; externalize to file w/ path-ref above that). Linkage label: `for-pr-<owner>-<repo>-<n>`. | Transient bd label `prgroom-lock-<pid>` (written/removed in single `bd update`) | `bd update --notes <new>` (replaces entire field) |

Selection at runtime: `--store file` (default), `--store bd` (v2), or env var `PRGROOM_STORE`.

### State schema (`schema_version: 1`)

The CLI is the schema owner. We absorb the *information* from the old inventory schema but don't preserve its layout — there is no Skill A/B contract to honor. Named so other CLI-internal state (if any) is unambiguous.

```python

# src/prgroom/prsession/state.py

@dataclass(slots=True)
class PRGroomingState:
    pr: PRRef
    phase: PRPhase
    round: int
    last_polled_at: datetime
    last_activity_at: datetime
    quiescence: QuiescenceState
    schema_version: int = SCHEMA_VERSION
    last_poll_sha: str = ""             # last HEAD observed by poll
    last_pushed_head_sha: str = ""      # last HEAD pushed by THIS CLI; distinguishes CLI vs external pushes for Round attribution (see §3.4)
    human_review_label_added: bool = False  # §4.7: dedup flag for auto-add of `human-review-required` PR label; omitted from JSON when falsy
    reviewers: dict[str, ReviewerState] = field(default_factory=dict)  # keyed by reviewer Identity
    items: list[ReviewItem] = field(default_factory=list)
    last_error: str | None = None       # structured error code (§3.7) for the most recent terminal-tier failure; cleared on successful cycle completion; omitted from JSON when None
    lifecycle_escalation_filed: bool = False  # per-cycle dedup for lifecycle-tier EscalationSink emits (cap-trip, terminal-user-error); reset to False when a new lifecycle gate fires; omitted from JSON when falsy
```

#### `PRPhase` — what the PR is *waiting on* (not what the CLI is doing)

**Phases describe the PR's state, not the CLI's current activity.** Verbs (`poll`, `cluster`, `fix`, …) are *activities* the CLI performs within or across a phase; a single phase may host many verb executions over its lifetime.

```python
class PRPhase(StrEnum):
    IDLE = "idle"                        # no PR-side activity yet observed
    AWAITING_REVIEW = "awaiting-review"  # pushed; waiting for any reviewer to engage (covers initial AND re-review; round disambiguates)
    FIXES_PENDING = "fixes-pending"      # feedback arrived; items not yet processed
    QUIESCED = "quiesced"                # terminal: everything addressed; safe to merge (auto-mergeable when policy allows)
    HUMAN_GATED = "human-gated"          # terminal: human action required (escalation, hard cap, failed items)
    MERGED = "merged"                    # terminal: merged
```

`awaiting-initial-review` and `awaiting-rereview` are collapsed into a single `awaiting-review` phase — from the PR's perspective they're the same state ("nothing new since we last pushed"). The `round` field on `PRGroomingState` distinguishes initial (1) from re-review (≥2) iterations.

#### Phase lifecycle

```
                      ┌──────────────────────────────┐
   first push  ─────► │       awaiting-review        │ ◄──────┐
                      └────────────────┬─────────────┘        │ (push fresh fixes → round++)
                                       │ (reviewer engaged: review found / human comment)
                                       ▼                      │
                      ┌──────────────────────────────┐        │
                      │         fixes-pending        │        │
                      └────────────────┬─────────────┘        │
                                       │ (all items have a disposition; all replied + resolved)
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

The three review kinds (`review_thread`, `review_summary`, `issue_comment`) share most fields and differ only in identity. Two viable shapes exist in idiomatic Python:

- **Single dataclass with discriminator + sub-dataclasses** (MVP default) — JSON-friendly, single schema, kind-specific identity grouped in `Identity`, processing outcome in optional `Disposition | None`. Runtime validation enforces "only review_thread items may have thread_id set," etc.
- **Protocol with three concrete types** — stronger static typing via mypy; requires a hand-written to_dict/from_dict pair that switches on `kind`. **Deferred to Section 3** as an open implementation decision; if Section 3 demands stronger types, refactor before MVP ships.

**A single `Disposition` enum captures the item's outcome.** The cluster verb does not classify; the fix agent decides the disposition at the time it (potentially) does the work. One unified field is therefore cleaner than separating intent (classification) from result (fix outcome).

```python
class ItemKind(StrEnum):
    REVIEW_THREAD = "review_thread"
    REVIEW_SUMMARY = "review_summary"
    ISSUE_COMMENT = "issue_comment"

class DispositionKind(StrEnum):
    FIXED = "fixed"                          # committed a new fix
    ALREADY_ADDRESSED = "already_addressed"  # prior commit handles it
    SKIPPED = "skipped"                      # ack only, no work
    DEFERRED = "deferred"                    # valid but out of scope; tracked elsewhere
    WONT_FIX = "wont_fix"                    # disagreement on a defensible basis
    ESCALATED = "escalated"                  # human must decide
    FAILED = "failed"                        # attempted but couldn't address

# disposition is Disposition | None on ReviewItem: None = not yet processed.

# (Parallel to any future optional sub-state; uniform None semantics for "no decision yet".)
@dataclass(frozen=True, slots=True)
class Disposition:
    kind: DispositionKind
    decided_at: datetime
    decided_by: str                         # agent CLI id (e.g. "claude -p opus[1m]") or "human:<login>"
    rationale: str = ""                      # required for skipped|deferred|wont_fix|failed; user-facing for skipped|deferred|wont_fix  # omitted from JSON when falsy
    commits: list[str] = field(default_factory=list)  # SHAs for fixed + already_addressed; multiple commits per item permitted  # omitted from JSON when falsy
    response_path: str | None = None         # path to fix-agent-authored response text (long-form replies)  # omitted from JSON when None
    gate: str = ""                           # full | lite — recommended gate the fix agent thought necessary  # omitted from JSON when falsy
    escalation_filed: bool = False           # escalated only  # omitted from JSON when falsy

@dataclass(slots=True)
class ReviewItem:
    kind: ItemKind
    identity: Identity

    # Common metadata
    author: str
    body_excerpt: str                        # first 200 chars
    seen_at: datetime

    # Clustering (set during the cluster verb; informs fix dispatch)
    cluster_id: str = ""                     # empty = not yet clustered  # omitted from JSON when falsy

    # Disposition (set when the fix verb processes this item; None until then)
    disposition: Disposition | None = None   # omitted from JSON when None

    # Response tracking
    replied: bool = False
    resolved: bool = False                   # review_thread only (and only when disposition.kind in {fixed, already_addressed})  # omitted from JSON when falsy
    duplicate_of_gh_id: str = ""             # omitted from JSON when falsy

@dataclass(frozen=True, slots=True)
class Identity:
    gh_id: str                               # gh's stable id; (kind, gh_id) is natural key
    thread_id: str = ""                      # GraphQL node id, review_thread only  # omitted from JSON when falsy
    reply_to_comment_id: int = 0             # review_thread only  # omitted from JSON when falsy
    issue_comment_id: int = 0                # issue_comment only  # omitted from JSON when falsy
```

**Why `Disposition | None`?** `None` is the explicit "no decision yet" state and survives JSON serialization without ambiguity. Same convention used for any future optional sub-state. (Note: a similar None-vs-empty choice could apply to `Classification` if we keep it; the unified `Disposition` makes the question moot.)

#### `ReviewerState` — generalized from `CopilotState`

Any PR can have **0..N reviewers** (Copilot today; codex bot tomorrow; codeowners if the team grows). They're tracked in a `dict[str, ReviewerState]` keyed by `Identity` (gh login or bot id). The dict allows arbitrary reviewer cardinality without schema churn.

```python
class ReviewerKind(StrEnum):
    HUMAN = "human"
    BOT = "bot"

class ReviewerStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    REVIEW_FOUND = "review_found"
    DECLINED = "declined"  # covers explicit pass AND §4 auto-decline (timeout-no-start / timeout-stalled); see ReviewerState.declined_reason

@dataclass(slots=True)
class ReviewerState:
    identity: str                                # gh login or bot id
    kind: ReviewerKind
    status: ReviewerStatus
    required: bool                               # true = gates quiescence (PR cannot quiesce until this reviewer's status ∈ {review_found, declined})
    last_request_at: datetime                    # §4.1: start-timeout reference
    last_review_at: datetime | None = None       # §4.1: first observed engagement post-request; finish-timeout reference  # omitted from JSON when None
    declined_at: datetime | None = None          # §4.1: set on transition to declined (any reason)  # omitted from JSON when None
    declined_reason: str | None = None           # §4.1: user-declined | timeout-no-start | timeout-stalled  # omitted from JSON when None
```

**Required vs optional reviewers.** A reviewer's `required` flag is the gate signal for quiescence. By default, Copilot is added as `required=True` on PR creation (parallel to today's behavior). Future codeowners or codex-bot reviewers can be added with `required=True` (gates quiescence) or `required=False` (advisory — their absence/silence does not block quiescence). Section 4 (Quiescence model) consumes this flag.

**Migration shape from old `CopilotState`:** in MVP, the `reviewers` dict contains exactly one entry — `{"copilot": ReviewerState(kind=ReviewerKind.BOT, ...)}` — preserving current behavior. The dict shape just leaves room for v2+ expansion.

#### `QuiescenceState`

```python
@dataclass(frozen=True, slots=True)
class QuiescenceState:
    ci_state: str = ""               # omitted from JSON when falsy. §4.1: success | pending | failure | absent — G_CI gate input for state.last_pushed_head_sha
    quiesced_at: datetime | None = None  # omitted from JSON when None. §4.2: set when phase transitions to quiesced
```

**Agent-contract callout (forward reference to Section 5):** the CLI's interactions with agent-CLIs (the cluster contract and fix contract) need strict input/output contracts. Section 5 is the owner; the state schema above carries only the *results* (`cluster_id`, `Disposition`).

### Transactional model (verb-level + run-aggregate)

**Public verbs are locking wrappers; lifecycle work happens in lock-assuming internal functions.** Every top-level CLI verb (`poll`, `cluster`, `fix`, `push`, `reply`, `resolve`, `rereview`, `resolve-escalated`, `wait`, `status`) is implemented as a thin public method that acquires the PR lock via the `lock()` context manager, calls its internal lock-assuming counterpart, then releases on the context manager's `finally`. The internal methods are conventionally named with a leading-underscore prefix (`_poll`, `_cluster`, etc.) and assume the caller already holds the PR lock for the duration of their work.

```python

# Public locking wrapper (one per verb)
def poll(self, pr_ref: PRRef) -> None:
    with self._store.lock(pr_ref):
        self._poll(pr_ref)

# Lock-assuming internal lifecycle method
def _poll(self, pr_ref: PRRef) -> None:
    """Caller must hold the per-ref lock (see lock())."""
    state = self._store.read(pr_ref)
    # ... mutate state in memory ...
    state.phase = next_phase
    state.last_activity_at = datetime.now(UTC)
    self._store.write(pr_ref, state)
```

**`run` is the only verb that acquires the lock once and calls multiple `_`-prefixed internals in sequence**, so `run` does not nest lock acquisitions on itself. See §3.3 for the full `run` algorithm.

Crash semantics: if the process dies between `lock()` and `write()`, the file-adapter lock is released (process-scoped); the on-disk state reflects the prior successful `write()`. **No partial states. No `crash_recovery` flag. Recovery = re-invoke.**

### Concurrency posture

- One-at-a-time per PR. Second invocation while one runs → non-zero exit with message `prgroom: another invocation holds the lock for <owner>/<repo>#<n> (pid <pid>)`.
- No queue. No lock-acquire timeout. Caller (cron, agent) retries on next cadence.
- The current skill's "concurrency-recovery branch table" evaporates because no partial writes can exist.

### Schema deliberately omits

- `crash_recovery` block (replaced by `phase` + `last_error` + lock semantics)
- `polling.copilot_review_submitted_at` (folded into `reviewers["Copilot"].last_review_at`)
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
              ┌─────────► │   round disambiguates initial vs re-review  │ ────────┐
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
              │ (round += 1, │                      │                             │
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
                                   │ poll observes external push, OR
                                   │ run --max-rounds (cap re-arm)
                                   ▼
                          (back to fixes-pending)
```

**Note on merge transitions (omitted from the diagram for clarity):** every non-terminal phase (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, `human-gated`) transitions to `merged` when `_poll` observes the PR closed via merge. The diagram shows only the `quiesced → merged` and `human-gated → merged` edges; `awaiting-review → merged` and `fixes-pending → merged` are equally legal and enumerated in the §3.2 matrix `poll` row.

**Note on direct `idle → fixes-pending` (omitted from the diagram for clarity):** when the first `_poll` observes both ≥1 commit on the remote AND ≥1 reviewer item already filed (uncommon but legal — a reviewer commented during the bootstrap window before `prgroom` ran), the verb advances `idle → fixes-pending` directly, bypassing the `awaiting-review` step. This edge is enumerated in the §3.2 `poll`-from-`idle` row; the diagram shows only the typical `idle → awaiting-review → fixes-pending` path.

**Any non-terminal phase transitions to `human-gated` at end-of-cycle when** (priority order, applied by `resolve_end_of_cycle_phase` in §3.2):

- Hard cap would be exceeded by the next push (`round >= max_rounds` with queued fix commits)
- Any item has `disposition.kind == DispositionKind.FAILED` produced by `CONTRACT_AUDIT_FAILED` or terminal-runtime failure (§3.6)
- Any item has unresolved `disposition.kind == DispositionKind.ESCALATED`
- A terminal-runtime failure occurred during the cycle

**Terminal-for-CLI phases:** `quiesced`, `human-gated`, `merged`. The CLI takes no further autonomous action; re-entry requires an external trigger observed by `poll`, an operator-issued `resolve-escalated`, or — when the gate is the hard cap — a `run` with raised `--max-rounds` (cap re-arm, §3.5).

**Graph-terminal phase:** `merged` only. Both `quiesced` and `human-gated` can re-enter `fixes-pending` when new reviewer activity, escalation resolution, or (for a cap-gated PR) a `--max-rounds` raise occurs.

### 3.2 Phase × verb transition matrix

For every `(current phase, verb invoked)`, the next phase and side effects are pinned. The matrix covers the **11 per-PR lifecycle verbs** (`poll`, `cluster`, `fix`, `push`, `reply`, `resolve`, `rereview`, `wait`, `resolve-escalated`, `status`, `run`). The optional `sweep` verb is a cross-PR aggregator outside this per-PR matrix; it iterates open PRs and invokes `run` for each, with no phase semantics of its own.

**`sweep` lock semantics and failure isolation (MVP):** `sweep` iterates open PRs **serially**, acquiring one PR's lock at a time via `store.lock(pr)` exactly as a direct `run <pr>` invocation would. **There is no store-wide or cross-PR `sweep` lock** — each PR is independently lockable, so a separate `run <other-pr>` invocation initiated by another process or operator does not block `sweep` from making progress on remaining PRs. **Failures are isolated per-PR:** a non-zero exit from one PR's `run` invocation (any tier — `RUNTIME_TRANSIENT`, `RUNTIME_TERMINAL_USER`, `STATE_CORRUPT`, `RUNTIME_CANCELLED`, etc.) does NOT abort the sweep. `sweep` logs each failure to stderr (PR ref + exit code + first stderr line) and continues to the next PR. `sweep`'s own exit code is `0` if every PR's `run` reached a terminal-for-CLI or transient outcome without unhandled errors, non-zero only on `sweep`-level errors (e.g., `gh pr list` failure to enumerate open PRs at the start). Because `run --autonomous` blocks for the full lifecycle of each PR per §3.5, `sweep` over N PRs in `awaiting-review` may take O(N × per-PR-wait) to complete — concurrency caps and ordering policies are deferred to a later section.

**Default behavior is "with prework" (`PRECONDITION_SELFHEAL`).** Cells marked **precondition fail** show the terminal outcome you get with `--no-prework`. Under the default self-heal path (Section 1 cross-cutting precondition gating), the verb auto-runs the missing deterministic prework and re-evaluates rather than returning the precondition error. For example, `fix` invoked in `idle` with no clusters under the default self-heal path runs `poll` → `cluster` → retries `fix`, then transitions per the `fixes-pending` row. With `--no-prework`, it returns `PRECONDITION_NO_CLUSTERS` immediately. Cells marked **no-op** mean the verb returns success (exit 0) without state change.

**This matrix describes the public verb's behavior when invoked directly** (e.g., `prgroom fix <pr>` from the shell). The `run` aggregate verb (§3.3) gates internal `_`-prefixed lifecycle methods by phase and does not exercise the per-verb precondition self-heal path — `run` already orchestrates the prework sequence. When reconciling §3.2 and §3.3, the matrix is the **direct-invocation contract**; §3.3 is the **run-driven flow**.

| Verb | from `idle` | from `awaiting-review` | from `fixes-pending` | from `quiesced` | from `human-gated` | from `merged` |
|------|-------------|------------------------|----------------------|-----------------|--------------------|---------------|
| `poll` | observes first push → `awaiting-review`; observes reviewer item → `fixes-pending`; else no-op | observes reviewer item → `fixes-pending`; observes PR-closed → `merged`; observes external push → round++ if SHA changed, stay; else no-op | observes new item → stay (item appended); observes PR-closed → `merged`; observes external push → round++ if SHA changed, stay; else no-op | observes new item → `fixes-pending`; observes PR-closed → `merged`; observes external push → `awaiting-review` (round++ per §3.4; `_push`'s ReviewerState flip applies); else no-op | observes new item → `fixes-pending`; observes PR-closed → `merged`; observes external push → `fixes-pending` (operator resolved gate; round++ per §3.4); else no-op | terminal; no-op |
| `cluster` | `PRECONDITION_NO_ITEMS` | `PRECONDITION_NO_ITEMS` (by definition, `awaiting-review` has no items needing clustering; if `poll` had observed items the phase would already be `fixes-pending`) | sets `cluster_id` on unclustered items; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `fix` | `PRECONDITION_NO_CLUSTERS` | `PRECONDITION_NO_CLUSTERS` | sets `disposition.kind` per item (`fixed`/`already_addressed`/`skipped`/`deferred`/`wont_fix`/`escalated`/`failed`); may produce commits; **no phase change** here — phase resolution happens at end-of-cycle via the priority cascade (§3.2); contract-audit failures flip the affected item to `disposition.kind = DispositionKind.FAILED` and the resolver promotes to `human-gated` via priority 2 | terminal; no-op | terminal; no-op | terminal; no-op |
| `push` | `PRECONDITION_NO_COMMITS` | uploads queued commits if any; **round++** if ≥1 commit pushed; no phase change | uploads queued commits if any; **round++** if ≥1 commit pushed; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `reply` | `PRECONDITION_NO_ITEMS` | **no-op** (exit 0; emits `PRECONDITION_NO_UNREPLIED` only under `--no-prework`) unless prior round left replies pending | renders templates + posts via gh API; marks `replied=True`; no phase change | re-applies idempotently to unreplied items; no phase change | re-applies idempotently | terminal; no-op |
| `resolve` | `PRECONDITION_NO_ITEMS` | **no-op** (exit 0; emits `PRECONDITION_NO_UNRESOLVED` only under `--no-prework`) | resolves review-threads with `disposition.kind ∈ {DispositionKind.FIXED, DispositionKind.ALREADY_ADDRESSED}` AND `resolved == False`; marks `resolved=True`; no phase change | re-applies idempotently | re-applies idempotently | terminal; no-op |
| `rereview` | `PRECONDITION_NO_ITEMS` | re-requests review for `required=True` reviewers in `{not_requested, declined}` (`_push` flips stale `review_found` → `not_requested`, see §3.4); **no-op exit 0 if no reviewers match** the target set; no phase change | invoked by `_run` immediately after a successful `_push` for the same set of reviewers; no phase change | re-requests if reviewer state stale; no phase change | re-applies idempotently | terminal; no-op |
| `wait` | sleeps; returns when `_wait` contract (§3.3) breaks — phase change, quiescence trip (§4), or signal-cancel (§4.2) | sleeps; returns when `_wait` contract (§3.3) breaks — phase change, quiescence trip (§4), or signal-cancel (§4.2); hard cap is NOT checked here (§3.5) | `PRECONDITION_WAIT_NOT_APPLICABLE` (exit 2 `EX_USAGE`) — `fixes-pending` has actionable work; the caller should invoke `run` (or `fix`+`push`) instead | sleeps; returns when `_wait` contract (§3.3) breaks — typically poll-event transitions to `fixes-pending` or `merged` | sleeps; returns when `_wait` contract (§3.3) breaks — typically poll-event transitions out | terminal; no-op |
| `resolve-escalated` | `PRECONDITION_NO_ESCALATIONS` | `PRECONDITION_NO_ESCALATIONS` | flips one item's `disposition.kind` from `escalated` to a terminal value; phase unchanged | `PRECONDITION_NO_ESCALATIONS` | flips one item's `disposition`; **only clears the `escalated` items gate** (§3.2 priority 3). Does NOT clear `LIFECYCLE_HARD_CAP_EXCEEDED` (requires `--max-rounds` raise + re-run), `STATE_CORRUPT` (requires operator state-file inspection), or `failed`-items gating (requires the operator to address the underlying `failed` disposition first). After the flip: phase moves to `fixes-pending` if and only if ALL of: (a) `state.items` has no `escalated` items remaining, (b) `state.items` has no `failed` items, AND (c) `state.last_error ∉ BlockingErrorCodes` (defined below). Otherwise phase stays `human-gated`. **`BlockingErrorCodes`** = { `LIFECYCLE_HARD_CAP_EXCEEDED`, `STATE_CORRUPT`, `STATE_SCHEMA_UNKNOWN`, `RUNTIME_GH_TERMINAL`, `RUNTIME_PUSH_REJECTED` } — these codes signal conditions outside `resolve-escalated`'s scope and require the recovery paths in §3.6/§3.7. ("Repo deleted" is one of the conditions classified under `RUNTIME_GH_TERMINAL`, per §3.6's example list; no distinct `RUNTIME_REPO_DELETED` code is registered.) (`CONTRACT_AUDIT_FAILED` is intentionally NOT in this set: per §3.3 `handle_verb_error`, contract-audit failures are surfaced via per-item `disposition.kind = DispositionKind.FAILED`, not via `state.last_error`; the `failed`-items check in clause (b) handles them.) | terminal; no-op |
| `status` | read-only (**lock-free**; see §3.3 carve-out — `--locked` opt-in for strictly-consistent read) | read-only | read-only | read-only | read-only | read-only |
| `run` | invokes lifecycle loop (§3.3) | invokes lifecycle loop (§3.3) | invokes lifecycle loop (§3.3) | invokes `_poll` **once** to detect external transitions (e.g., operator merged externally → `merged`; new reviewer activity → `fixes-pending`). If phase advances out of `quiesced`, re-enter the lifecycle loop; otherwise return 0. | invokes `_poll` **once** to detect external resolutions (operator pushed a fix → `fixes-pending`; operator merged → `merged`), then re-evaluates the hard cap: if `last_error == LIFECYCLE_HARD_CAP_EXCEEDED` and the cap no longer trips because the operator raised `--max-rounds` (cap re-arm, §3.5 Recovery), clears `last_error` and advances → `fixes-pending`. If phase advances out of `human-gated` by either path, re-enter the lifecycle loop; otherwise return 0 (awaits operator action). | returns 0 immediately (graph-terminal; `merged` is absorbing) |

**End-of-cycle phase resolution** (applied by `run` after each cycle via `resolve_end_of_cycle_phase`, see §3.3): from `fixes-pending` the resolver chooses the next phase by evaluating these conditions in strict priority order — the first match wins.

1. Hard-cap would be exceeded by the next push (`round >= max_rounds` AND `has_queued_fix_commits(state)`) → `human-gated` with `last_error = LIFECYCLE_HARD_CAP_EXCEEDED`. **Check is pre-push** (§3.5), so the cap-tripping push is *not* uploaded.
2. Any item with `disposition.kind == DispositionKind.FAILED` (regardless of underlying cause — contract audit, runtime terminal error, or agent-reported "could not converge") → `human-gated`. For runtime-terminal-user failures, `state.last_error` was already set by `handle_verb_error` (the `PROPAGATE` path); the resolver preserves it. For contract-audit failures and pure agent-reported failures, `state.last_error` is left unset — the per-item `disposition.rationale` is the source of truth for the cause. (Rationale: `handle_verb_error` only writes `state.last_error` on `PROPAGATE`-disposition errors; `CONTRACT_AUDIT_FAILED` returns `VerbDisposition.CONTINUE` and surfaces the cause via per-item `disposition`. Cross-reference §3.3 `handle_verb_error` and the §3.7 error-code registry.)
3. Any item with unresolved `disposition.kind == DispositionKind.ESCALATED` → `human-gated`; file exactly one `EscalationSink` event per cycle (deduped across items). The `EscalationSink` always exists (Section 5: stderr is the default sink) — there is no "no resolution path" branch.
4. ≥1 commit pushed this cycle (`round` was incremented) → `awaiting-review`. `rereview` already invoked from within the cycle (§3.3) for required bot reviewers needing fresh review.
5. No commits pushed this cycle AND quiescence threshold trips (§4) → `quiesced`.
6. Otherwise (no commits pushed, quiescence did not trip) → `awaiting-review`. **Rule-6 rationale:** this covers the case where every item processed this cycle dispositioned to `skipped`/`wont_fix`/`deferred` (zero commits, no fresh work), and the §4 quiescence threshold has not yet judged the PR ready. The next cycle's `wait` either observes new reviewer activity (→ back to `fixes-pending` via `poll`) or accumulates idle time until quiescence trips. Already-processed items remain in `state.items` with `disposition is not None`; subsequent `_cluster`/`_fix` skip them (idempotent on dispositioned items), so re-entering `fixes-pending` only does work for NEW items.

### 3.3 `run` aggregate verb algorithm

`run --autonomous` is **long-running and blocking** for non-terminal phases — the invocation holds the PR lock through the cycle loop while the phase is `idle`, `awaiting-review`, or `fixes-pending`. **When the phase reaches `quiesced`, `human-gated`, or `merged`, `run` releases the lock and returns**, so external triggers (operator's `resolve-escalated`, manual push, manual merge) are free to acquire the lock and act. Each `_`-prefixed internal writes state to disk before returning, so a crashed process leaves the on-disk state consistent (per Section 2's transactional model) and the next `run` invocation resumes from the last successful write.

`run` is the **only verb that acquires the PR lock once and calls multiple lock-held internals in sequence**. This is the singular exception to Section 2's "every verb acquires its own lock" rule, and is the reason the lock-held internal contract exists.

**Lock-held internal contract.** Each lock-held internal (a private `_`-prefixed method whose docstring states `Caller must hold the per-ref lock (see lock()).`):

- Assumes the caller already holds the PR lock for the duration of the call.
- Reads no state from disk; instead receives the current in-memory `PRGroomingState` from the caller.
- Returns the (potentially) mutated `PRGroomingState`, or raises an error tagged with its failure tier (§3.6).
- Atomically `store.write`s state before returning, so the on-disk view always reflects the last successful internal call.
- Is **idempotent on already-processed items**: `_cluster` is a no-op when every item has `cluster_id != ""`; `_fix` is a no-op when every item has `disposition is not None`; `_reply` is a no-op when every item has `replied == True`; `_resolve` is a no-op when no item has `disposition.kind in {DispositionKind.FIXED, DispositionKind.ALREADY_ADDRESSED}` and `resolved == False`; `_push` is a no-op when `has_queued_fix_commits` returns false. This idempotency contract is load-bearing — `_run`'s priority-6 re-entry path (§3.2) relies on it to avoid hot loops.
- **`_fix` restart-safety under transient agent failures.** When a transient-tier agent failure (`RUNTIME_AGENT_TIMEOUT`, `RUNTIME_AGENT_UNAVAILABLE`) aborts a cycle mid-cluster, items already processed before the failure carry `disposition is not None` and are skipped on the next `_fix` invocation per the idempotency rule above; items not yet processed carry `disposition is None` and are reprocessed. This guarantees that partial-cluster processing is never lost (no double-fixing of already-dispositioned items) and never starved (un-dispositioned items always get another attempt on the next `run` invocation, driven by the scheduler's retry of exit-75).

**Tier → exit code mapping** (`exit_code_for_tier`) — `run`'s public wrapper applies this to translate a tier-tagged error into the documented sysexits code:

```python
def exit_code_for_tier(err) -> int:          # takes the full tier-tagged error, not just err.tier
    match err.tier:                          # all cases inspect err.tier only, EXCEPT RUNTIME_CANCELLED
        case Tier.PRECONDITION_USER_ERROR:   return 2   # EX_USAGE
        case Tier.PRECONDITION_NO_WORK:      return 0   # success-no-op
        case Tier.PRECONDITION_LOCK_HELD:    return 75  # EX_TEMPFAIL (transient-equivalent for scheduler retry)
        case Tier.RUNTIME_TRANSIENT:         return 75  # EX_TEMPFAIL
        case Tier.RUNTIME_TERMINAL_USER:     return 77  # EX_NOPERM
        case Tier.RUNTIME_CANCELLED:         return 128 + err.signum  # err.signum is 2 (SIGINT→130) or 15 (SIGTERM→143); non-retryable; only RUNTIME_CANCELLED reads err payload beyond .tier
        case Tier.CONTRACT_AUDIT_FAILED:     return 65  # EX_DATAERR
        case Tier.STATE_CORRUPT | Tier.STATE_SCHEMA_UNKNOWN: return 78  # EX_CONFIG
        case Tier.LIFECYCLE_CAP:             return 0   # graceful terminal exit
        case _:                              return 1   # generic failure
```

```python
def run(pr: PRRef, mode: Mode) -> int:        # mode in {INTERACTIVE, AUTONOMOUS}
    try:
        with store.lock(pr):                  # public locking shell; the contextmanager's
                                              # finally guarantees release even on error
            _run(pr, mode)
    except TaggedError as err:                # PRECONDITION_LOCK_HELD raised on acquire → 75;
        return exit_code_for_tier(err)        # any tier-tagged error from _run lands here too
    return 0

def _run(pr: PRRef, mode: Mode) -> PRGroomingState:
    """Caller must hold the per-ref lock (see lock())."""
    try:
        state = store.read(pr)
    except StateNotFoundError:
        # First invocation against this PR — bootstrap zero-value state.
        # Auto-bootstrap is performed regardless of --no-prework; absence of
        # state is a discovery condition, not a precondition failure.
        # Initialize ALL non-default fields explicitly per §2 schema —
        # schema_version=1 is required (a default 0 would fail STATE_SCHEMA_UNKNOWN
        # validation on next read); pr identifies the bead-tracker key; items
        # and reviewers are initialized to empty containers (not None) so subsequent
        # appends/inserts are safe.
        state = PRGroomingState(
            schema_version=SCHEMA_VERSION,    # = 1
            pr=pr,
            phase=PRPhase.IDLE,
            round=0,
            last_poll_sha="",
            last_pushed_head_sha="",
            reviewers={},
            items=[],
            last_error=None,
            lifecycle_escalation_filed=False,
        )
        store.write(pr, state)
    except Exception as cause:
        raise tagged_error(Tier.STATE_CORRUPT, cause) from cause

    # Entry-time external-transition probe: if state is already terminal-for-CLI
    # at entry (operator invoked `run` against a quiesced/human-gated PR), run
    # one _poll first to detect external transitions (e.g., operator merged
    # the PR externally; operator pushed a manual fix that cleared the gate).
    # Without this, terminal-for-CLI → merged / human-gated → fixes-pending
    # transitions are unreachable per the §3.2 matrix (the `run` row for those
    # phases). The probe runs at most once per invocation; if _poll raises, the
    # standard handle_verb_error pattern applies (caught and translated below).
    if state.phase in {PRPhase.QUIESCED, PRPhase.HUMAN_GATED}:
        try:
            state = _poll(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # §3.3
                state = request_human_review_if_needed(state) # §4.7 (auto-label-add)
                raise
        # If _poll transitioned phase to a non-terminal-for-CLI value
        # (fixes-pending after operator fix-push, or back into awaiting-review
        # after external push from quiesced), the loop top below re-enters the
        # cycle. If it stayed terminal-for-CLI or advanced to merged, the
        # loop-top check returns cleanly.

        # Cap re-arm (§3.5 "Recovery"): clear the hard-cap gate when the operator
        # has raised max_rounds above the current round (via --max-rounds /
        # PRGROOM_MAX_ROUNDS / .prgroom.toml), then re-enter the cycle so the
        # refused fix commits push under the raised cap. This clears the CAP gate
        # specifically — it does NOT require the cap to be the sole blocker;
        # escalated/failed items (if present) are re-asserted at end-of-cycle below.
        # This predicate is the exact inverse of the §3.5 pre-push cap-trip
        # condition, so it self-gates: a bare `run` with no raise leaves
        # round >= max_rounds → condition false → phase stays human-gated. The
        # raised budget IS the explicit operator authorization; the cap is never
        # silently lifted. Escalated/failed items are NOT bypassed — if any
        # remain, the re-entered cycle pushes the queued commits and
        # resolve_end_of_cycle_phase re-asserts human-gated via §3.2 priority 2/3.
        if (
            state.phase == PRPhase.HUMAN_GATED
            and state.last_error == "LIFECYCLE_HARD_CAP_EXCEEDED"
            and not (has_queued_fix_commits(state) and state.round >= max_rounds)
        ):
            state = dataclasses.replace(
                state,
                phase=PRPhase.FIXES_PENDING,
                last_error=None,
                lifecycle_escalation_filed=False,   # re-arm, not suppress: a fresh gate after re-entry fires one Sink event
                human_review_label_added=False,     # §4.7: reset so a later gate re-adds the label
            )
            store.write(pr, state)
            # loop top re-enters the cycle

    while True:
        # Terminal-for-CLI: emit any pending escalations + auto-label, return.
        # All escalation emission funnels through escalate_if_needed (§3.3); the
        # parallel request_human_review_if_needed (§4.7) handles GitHub-label
        # auto-add for review-content gating conditions (cap-trip, escalated/failed
        # items). Both are called from the same two sites: HERE (clean phase
        # transitions) and before each PROPAGATE-return below (terminal-error
        # transitions). Both sites are dedup-safe via the per-item escalation_filed
        # flag, the lifecycle lifecycle_escalation_filed flag, and the human_review_label_added
        # flag — second invocation in the same cycle is a no-op for all three.
        if state.phase in {PRPhase.MERGED, PRPhase.QUIESCED, PRPhase.HUMAN_GATED}:
            state = escalate_if_needed(state)             # per-item + lifecycle dedup; writes state (§3.3)
            state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
            return state

        # === Cycle start (state.phase in {IDLE, AWAITING_REVIEW, FIXES_PENDING}) ===

        try:
            state = _poll(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise

        if state.phase in {PRPhase.MERGED, PRPhase.QUIESCED, PRPhase.HUMAN_GATED}:
            continue                          # loop top will emit + return

        if state.phase == PRPhase.IDLE:
            if mode == Mode.INTERACTIVE:
                print("prgroom: nothing to do — PR has no commits yet (phase=idle)", file=sys.stderr)
                return state
            try:
                state = _wait(pr, state)
            except TaggedError as err:
                if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                    state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                    state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                    raise
            continue

        if state.phase == PRPhase.AWAITING_REVIEW:
            if mode == Mode.INTERACTIVE:
                return state                  # user owns the wait
            try:
                state = _wait(pr, state)
            except TaggedError as err:
                if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                    state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                    state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                    raise
            continue

        # === state.phase == FIXES_PENDING ===
        try:
            state = _cluster(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise

        try:
            state = _fix(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise

        # Pre-push hard-cap check (§3.5). Set state ONLY; the next loop-top
        # iteration's escalate_if_needed emits one Sink event for this gate,
        # using state.lifecycle_escalation_filed to dedup.
        if has_queued_fix_commits(state) and state.round >= max_rounds:
            state = dataclasses.replace(
                state,
                phase=PRPhase.HUMAN_GATED,
                last_error="LIFECYCLE_HARD_CAP_EXCEEDED",
                lifecycle_escalation_filed=False,   # cleared so loop-top fires once
            )
            store.write(pr, state)
            continue                                # loop top emits + returns

        try:
            state = _push(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise

        # Post-push rereview for required bot reviewers needing fresh review.
        # _push already flipped review_found → not_requested per §3.4,
        # so has_required_reviewers_to_refresh reduces to "any required=True
        # reviewers configured" after a successful push.
        if push_uploaded_commits_this_cycle(state) and has_required_reviewers_to_refresh(state):
            try:
                state = _rereview(pr, state)
            except TaggedError as err:
                if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                    state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                    state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                    raise

        try:
            state = _reply(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise
        try:
            state = _resolve(pr, state)
        except TaggedError as err:
            if handle_verb_error(err, state) == VerbDisposition.PROPAGATE:
                state = escalate_if_needed(state)             # flush per-item + lifecycle emits before propagating (§3.3)
                state = request_human_review_if_needed(state) # auto-add `human-review-required` label if applicable (§4.7)
                raise

        # End-of-cycle phase resolution — priority cascade per §3.2.
        # Phase resolution sets state ONLY; loop-top emits via escalate_if_needed.
        state = dataclasses.replace(state, phase=resolve_end_of_cycle_phase(state))
        if state.phase in {PRPhase.HUMAN_GATED} and new_lifecycle_gate_this_cycle(state):
            state = dataclasses.replace(state, lifecycle_escalation_filed=False)  # cleared so loop-top fires once
        if state.phase not in {PRPhase.HUMAN_GATED}:
            # Successful cycle completion clears any prior gating error
            # (e.g., LIFECYCLE_HARD_CAP_EXCEEDED carried over from a previous run
            # that the operator has since resolved out-of-band or by raising --max-rounds).
            # Realistic carry-over reaching this clear: LIFECYCLE_HARD_CAP_EXCEEDED
            # (operator raised --max-rounds and re-ran). Other BlockingErrorCodes
            # (STATE_CORRUPT, STATE_SCHEMA_UNKNOWN, RUNTIME_GH_TERMINAL, RUNTIME_PUSH_REJECTED)
            # keep phase at human-gated via handle_verb_error or the end-of-cycle
            # resolver and never reach this clear-on-success branch.
            # See §3.5 "Recovery" bullet.
            state = dataclasses.replace(
                state,
                last_error=None,
                lifecycle_escalation_filed=False,   # reset for next gate, if any
                human_review_label_added=False,     # §4.7: reset so next gating event re-adds the label
            )
        store.write(pr, state)
        continue                                    # loop top handles terminal + emits
```

Notes on the rewrite vs. earlier drafts:

- Every lock-held internal returns the in-memory `PRGroomingState` so `_run` threads it without disk re-reads. The lock guarantees no external mutation; re-reads were redundant.
- `handle_verb_error` returns a disposition enum (`VerbDisposition.CONTINUE` or `VerbDisposition.PROPAGATE`) rather than an error, eliminating the shadow / ambiguous-return pattern. Continuable errors (`CONTRACT_AUDIT_FAILED`) write state and return `VerbDisposition.CONTINUE`; terminal-tier errors return `VerbDisposition.PROPAGATE` and `_run` re-raises the original tagged error to `run`, which applies `exit_code_for_tier`.
- All escalation emission flows through `escalate_if_needed`, called immediately followed by `request_human_review_if_needed` (§4.7) at every site. Both are called from **two** sites in `_run` — the loop-top terminal-for-CLI check (clean transitions to `merged`/`quiesced`/`human-gated`), and immediately before each `PROPAGATE` re-raise after `handle_verb_error` (terminal-error paths: auth-expiry, push-rejected, state-corrupt). All three dedup flags share the same mechanism — per-item `escalation_filed`, lifecycle-tier `lifecycle_escalation_filed`, and `human_review_label_added` (§4.7) — each with atomic state write after emit. Calling either function twice in one cycle is a no-op the second time (the relevant flag is already set). The cap-trip branch and end-of-cycle resolver only WRITE state (setting `lifecycle_escalation_filed = False` and `human_review_label_added = False` to invite a new emit). Crash-recovery safe modulo Sink idempotency (bd `label add` is idempotent; `--append-notes` is not — bd-adapter must use label-only emit, or content-hash dedup on notes) and GitHub-label idempotency (`gh.add_label` is idempotent server-side).

**Terminal-signal emission — parallel-function design.** `_run` emits terminal signals via two parallel functions: `escalate_if_needed(state)` (Sink semantics; §3.3) and `request_human_review_if_needed(state)` (GitHub-label semantics; §4.7). There are **two** call sites for both, both dedup-safe via `escalation_filed`/`lifecycle_escalation_filed`/`human_review_label_added` flags: (1) the loop-top terminal-for-CLI check (clean transitions), and (2) immediately before each `PROPAGATE` re-raise (terminal-error transitions). `handle_verb_error` sets state and (for terminal tiers) updates `state.last_error` and `state.lifecycle_escalation_filed = False` but does NOT emit directly. The cap-trip branch and end-of-cycle resolver also only WRITE state (setting `state.lifecycle_escalation_filed = False` and `state.human_review_label_added = False` to invite fresh emits when a new lifecycle gate fires). Recommended call order at every site is `escalate_if_needed` first (Sink), then `request_human_review_if_needed` (label) — either ordering is correct since both are idempotent and read disjoint state; the convention is for readability.

`escalate_if_needed(state)` semantics:

- Walks `state.items`: for any item where `item.disposition is not None` AND `item.disposition.kind in {DispositionKind.ESCALATED, DispositionKind.FAILED}` AND `item.disposition.escalation_filed == False`, calls `escalation_sink.emit(...)` and sets `escalation_filed = True`.
- If `state.last_error is not None` AND `state.lifecycle_escalation_filed == False`, calls `escalation_sink.emit(...)` for the lifecycle-tier condition and sets `lifecycle_escalation_filed = True`.
- Atomically `store.write`s state after emission.
- **Sink failure handling:** if `escalation_sink.emit(...)` raises (stderr write failure, bd-adapter API blip), the failure is swallowed (best-effort emit). The corresponding `escalation_filed` / `lifecycle_escalation_filed` flag is NOT set on Sink error, so the next invocation of `escalate_if_needed` re-attempts the emission for the same item or lifecycle gate. Persistent Sink failures produce repeated retry attempts but never block lifecycle progression (the cycle continues; phase transitions still happen). Operators inspecting `prgroom status` see the gating condition via `state.last_error` and per-item `disposition.kind` regardless of Sink reachability. **Relation to the crash-window dedup paragraph below:** the Sink-error retry path produces the same double-fire risk as the crash window (next invocation re-emits) and relies on the same Sink-side dedup contract — bd-adapter must use label-only emit or content-hash dedup on notes; stderr sinks accept the duplicate as a single extra log line.

**Crash-window dedup:** a crash between Sink emit and state write may double-fire on the next invocation. The Sink itself is expected to dedup idempotently — bd's `label add` is idempotent (acceptable); bd's `--append-notes` is NOT (would duplicate notes lines on retry), so the bd-adapter MUST use label-only emit, or content-hash dedup on notes. Stderr-only sinks have no dedup but the cost is one extra log line, accepted.

**Verb-error handling (`handle_verb_error`).** Returns a control-flow disposition enum — named `VerbDisposition` to avoid collision with the `Disposition` value-object (§2):

```python
class VerbDisposition(StrEnum):
    CONTINUE = "continue"      # cycle proceeds; loop-top emits at terminal
    PROPAGATE = "propagate"    # _run re-raises the tagged error to run()

def handle_verb_error(err, state: PRGroomingState) -> VerbDisposition:
    if err is None:
        return VerbDisposition.CONTINUE
    match err.tier:
        case Tier.RUNTIME_TRANSIENT:
            state.last_error = err.code
            store.write(pr, state)
            return VerbDisposition.PROPAGATE      # run will exit 75; scheduler retries
        case Tier.RUNTIME_TERMINAL_USER:
            state.phase = PRPhase.HUMAN_GATED
            state.last_error = err.code
            state.lifecycle_escalation_filed = False   # invites loop-top emit
            store.write(pr, state)
            return VerbDisposition.PROPAGATE      # run will exit 77
        case Tier.CONTRACT_AUDIT_FAILED:
            # Verb has already flipped affected items to disposition.kind = FAILED
            # with rationale set. End-of-cycle resolver (§3.2 priority 2) decides
            # phase consequence. Per-item escalation_filed flag controls dedup.
            return VerbDisposition.CONTINUE       # cycle proceeds; loop-top emits at terminal
        case Tier.STATE_CORRUPT | Tier.STATE_SCHEMA_UNKNOWN:
            state.phase = PRPhase.HUMAN_GATED
            state.last_error = err.code
            state.lifecycle_escalation_filed = False
            store.write(pr, state)
            return VerbDisposition.PROPAGATE      # run will exit 78
        case Tier.RUNTIME_CANCELLED:
            # Normal non-retryable lifecycle exit (SIGINT/SIGTERM from operator or scheduler).
            # No phase change, no state mutation — leave state exactly as written by the
            # last successful lock-held internal so `prgroom status` reports the last known
            # phase accurately. run applies exit_code_for_tier (→ 130 or 143).
            return VerbDisposition.PROPAGATE
        case _:
            # Unknown tier is a programmer error — the tier enum is exhaustive
            # over registered tiers (§3.6) and adding a new tier requires
            # updating both the registry and this match. Crash-loud propagation
            # is intentional: do NOT store.write(pr, state) here, because doing so
            # would silently persist any verb-level state mutations carried in
            # the (potentially undefined) error and mask the bug from operators.
            # run maps default-tier propagation to exit code 1 (generic failure)
            # via exit_code_for_tier. (There is no compile-time exhaustiveness in
            # Python; the explicit `case _` plus a unit test enumerating every Tier
            # member recovers the equivalent safety.)
            return VerbDisposition.PROPAGATE
```

**`_wait` contract surface (implementation owned by §4).** §3.3 only relies on the following surface; §4 defines the quiescence/timeout logic that implements it:

- Signature: `def _wait(self, pr: PRRef, state: PRGroomingState) -> PRGroomingState:` (private; `Caller must hold the per-ref lock (see lock()).`).
- Behavior: sleeps + internally invokes `_poll` at the §4-defined cadence, returning when either (a) the polled state transitions to a new phase, (b) the §4-defined quiescence threshold trips (writes `phase = PRPhase.QUIESCED` and returns), or (c) a §4-defined hard-timeout fires (returns without phase change).
- Error tiers: may raise `RUNTIME_TRANSIENT` if internal `_poll` invocations hit gh API blips beyond the retry budget; `RUNTIME_CANCELLED` if a signal interrupts the wait (see Cancellation below); otherwise returns normally.
- Cancellation: long waits use a bounded poll loop checking an interval and a deadline (`datetime.now(UTC) < deadline`), with `signal`-based SIGINT/SIGTERM handling for graceful interrupt (if a cancellation token is genuinely needed, model it as a `threading.Event` checked each poll iteration). In MVP, signals (SIGINT/SIGTERM) cause `_wait` to raise an error tagged `RUNTIME_CANCELLED` (NOT `RUNTIME_TRANSIENT`) so the lock releases cleanly AND the scheduler does not retry the cancelled invocation. The exit code is `128 + signum` per Unix convention (130 for SIGINT, 143 for SIGTERM), distinct from `RUNTIME_TRANSIENT`'s exit 75 (`EX_TEMPFAIL`). This separation prevents the "cancelled-work resurrection" failure mode in which a Ctrl-C'd `run --autonomous` is re-driven by the scheduler against the operator's intent.
- Lock semantics: assumes the caller holds the PR lock; does NOT release the lock during sleep (lock stays held for the entire `run --autonomous` invocation per §3.5).

**`run --interactive` differences:** identical control flow except the verb returns 0 on reaching `awaiting-review`, `idle`, or any terminal-for-CLI phase. It never calls `_wait`. On `idle`, the interactive variant emits a one-line stderr advisory (`prgroom: nothing to do — PR has no commits yet (phase=idle)`) so callers can distinguish "nothing to do" from "completed work." Escalations route through the default `EscalationSink` (stderr).

**Lock-hold duration:** `run --autonomous` holds the lock continuously from the first `store.lock(pr)` call. Within each cycle, the lock is held through the full sequence `_poll → _cluster → _fix → _push → [_rereview] → _reply → _resolve → resolve_end_of_cycle_phase → store.write` (no mid-cycle release). After each cycle's phase resolution, if the new phase is terminal-for-CLI (`quiesced`, `human-gated`, or `merged`), the loop `continue`s, the loop-top terminal check fires, `_run` returns, and the `lock()` context manager (entered by `run`) releases the lock in its `finally`. Concurrent invocations on the same PR exit immediately with `PRECONDITION_LOCK_HELD` (exit 75); once the holder returns, the next invocation may acquire.

**`status` read-only carve-out.** The `status` verb is the **single exception** to Section 2's "every verb acquires the PR lock" rule. `status` performs a single `store.read(pr)` and prints the result without calling `store.lock(pr)`. Rationale: under a long-running `run --autonomous` invocation that holds the lock for the entire `awaiting-review` wait (potentially minutes-to-hours per §4 quiescence semantics), a lock-acquiring `status` would block or exit `PRECONDITION_LOCK_HELD` for that whole duration — a UX regression versus the legacy `wait-for-pr-comments` skill, which exposes per-poll state readable at any time. The cost: a `status` invocation that races with an in-progress `store.write` from another verb may observe a **stale-but-internally-consistent snapshot** — the pre-replace state from the prior write. Because writes are file-atomic per Section 2 (`tempfile` + `os.replace` on the same filesystem), a reader always observes either the old complete file or the new complete file. Partial/corrupt JSON from a race is not possible; `status` does not retry on staleness (a single read is always parseable). True `STATE_CORRUPT` errors (hand-edited state file, filesystem corruption) remain distinguishable from lock-free staleness and surface via the normal `STATE_CORRUPT` handling. Operators who need a strictly-consistent read can invoke `prgroom status --locked <pr>`, which DOES acquire the lock via the standard `store.lock(pr)` path. Under contention, `--locked` exits **75** (`PRECONDITION_LOCK_HELD` per §3.7) on the standard scheduler-retry cadence — it does NOT block indefinitely; the default lock-free `status` invocation is the right tool for diagnostic polling under a long-running `run --autonomous`.

**Resilience:** every lock-held internal writes state atomically (per Section 2's transactional model). If the process dies mid-`run`, the OS releases the file-adapter lock, the next invocation re-acquires it, reads the last-good state, and resumes from there. There is no `crash_recovery` flag.

### 3.4 `round` counter semantics

`round` represents the **count of distinct review-eliciting pushes** observed for this PR. It disambiguates initial review (`round=1`) from re-review (`round≥2`) within the `awaiting-review` phase.

**Initialization and increment rules.** The unifying principle: `round` increments from 0 to 1 on the **first observation of a non-empty PR HEAD by either code path** (whichever happens first), and increments further only on subsequent **distinct review-eliciting pushes**. Both `_poll` and `_push` must guard their increment with idempotency checks so they do not double-bump.

- The zero value of `PRGroomingState` has `round = 0` and `last_poll_sha == ""`.
- **`_poll` bootstrap (Round 0 → 1).** When `_poll` runs with `state.last_poll_sha == ""`, it inspects the remote PR HEAD:
  - If the remote HEAD is **non-empty** (the PR has ≥1 commit), `_poll` idempotently sets `state.round = max(state.round, 1)` (a prior `_push` may have already set it to 1, in which case this is a no-op), sets `state.last_poll_sha = <observed HEAD SHA>`, and follows the §3.2 `poll`-from-`idle` row to transition phase out of `idle`.
  - If the remote HEAD is **empty** (PR opened with no commits — uncommon but legal), `_poll` leaves `state.round = 0` and `state.last_poll_sha = ""`, returns no phase change. The next `_poll` invocation re-evaluates the bootstrap condition.
  This bootstrap is not subject to the CLI-vs-external attribution rule below (which applies only when `state.last_poll_sha != ""`).
- **`_push` bootstrap (Round 0 → 1).** If `_push` successfully uploads ≥1 commit while `state.round == 0` (e.g., `prgroom` is the first agent to push commits to a freshly-opened empty PR), it sets `state.round = 1` and `state.last_pushed_head_sha = <new HEAD SHA>` in the same write. If a `_poll` runs subsequently while `state.last_poll_sha == ""`, it follows the **`_poll` bootstrap rule above** (NOT the attribution rule): it inspects the remote HEAD, observes `state.round == 1` (already bumped by `_push`), idempotently skips re-incrementing, sets `state.last_poll_sha = <observed HEAD SHA>`, and follows the §3.2 `poll`-from-`idle` row to transition phase. The bootstrap branch is identified by `state.last_poll_sha == ""`; the attribution branch (below) is identified by `state.last_poll_sha != ""`. The two branches are mutually exclusive.
- **`_push` subsequent increments (Round N → N+1, N ≥ 1).** When `state.round >= 1`, `_push` increments `round` if and only if it uploaded **≥1 new commit** to the remote, and sets `state.last_pushed_head_sha = <new HEAD SHA>` in the same write.
- **`_poll` subsequent increments (Round N → N+1, N ≥ 1).** When `state.round >= 1` and `_poll` observes a HEAD SHA change attributable to commits the CLI did not author, it increments `round` (see the attribution rule below).
- A complete fix-cycle that produced zero commits (every item dispositioned `skipped`/`wont_fix`/`deferred`) does NOT increment `round`. Such a cycle counts toward quiescence (§4) but not toward the hard cap.
- `resolve-escalated` does NOT increment `round` — the disposition flip alone is not visible to reviewers.
- **`§3.5` narrative consistency:** the §3.5 "round=1 → fix-push #2 → fix-push #3" example assumes the typical case in which the first observed push (by either bootstrap path above) is followed by CLI-authored fix-pushes. The exact code path that produced `round=1` (poll-bootstrap on a human-authored push vs. push-bootstrap on a CLI-authored initial push) does not affect cap semantics — both consume one round.

**CLI-vs-external push attribution.** When `_poll` observes that the remote HEAD differs from `state.last_poll_sha`:

- If `new_head_sha == state.last_pushed_head_sha` → the change is the CLI's own push (already counted by `_push`); update `state.last_poll_sha = new_head_sha`, do NOT increment `round`. `_push` already performed the reviewer-state flip in this case, so `_poll` leaves `state.reviewers` untouched.
- Otherwise → external push (operator or third party); increment `round`, set `state.last_poll_sha = new_head_sha`, leave `state.last_pushed_head_sha` untouched. **Additionally, mirror `_push`'s reviewer-state flip:** walk `state.reviewers` and flip every entry with `required == True` AND `status == "review_found"` to `status = "not_requested"` (same predicate as the "`ReviewerState.status` transition on `_push`" rule below). External pushes invalidate prior reviews on the old SHA exactly as CLI pushes do, so the post-push `_rereview` predicate `has_required_reviewers_to_refresh(state)` evaluates correctly. The CLI does NOT update `last_pushed_head_sha` for pushes it didn't make.

This rule prevents double-counting CLI pushes (which would otherwise be incremented once by `_push` and again by the next `_poll`) and prevents missing external pushes. The reviewer-flip mirror ensures stale reviews are detected regardless of the push's author.

**Force-push and rebase edge cases (best-effort attribution).** When operators force-push or rebase, history is rewritten and the simple "SHA equality" check above can under- or over-count rounds:

- *Under-count:* CLI pushed X (set `last_pushed_head_sha = X`). Operator force-pushed Y over X. CLI then pushed Z on top of Y. `last_pushed_head_sha` now reads Z. The intermediate Y is unobservable because it was overwritten; the round it consumed is not counted.
- *Over-count:* In `awaiting-review`, the operator force-pushes a rebase whose tree is logically identical to the prior HEAD. `last_pushed_head_sha` no longer matches the new HEAD, so `_poll` increments `round` even though no new review work was elicited.

These edge cases are accepted as **best-effort attribution**, not corrected automatically. Rationale: detecting history rewrites reliably (especially distinguishing "rebase with identical tree" from "rebase with different commits") requires comparing tree hashes, parent chains, and committer metadata — a feature surface disproportionate to the value, given that operators who care can manually adjust `--max-rounds`. If precise round accounting under force-push becomes a recurring need, a follow-up bead should split `MaxRoundsCLI` vs `MaxRoundsTotal` (mentioned in §3.5) so the cap can be raised without altering CLI-side budgets.

**Detecting queued (unpushed) fix commits.** `prgroom` does not maintain a separate state field for the commit queue. The remote tip is the source of truth: `_push` consults `gh pr view --json headRefOid` for the authoritative remote HEAD on the PR branch and compares it to the local PR-branch HEAD via `git rev-list <remote-head>..HEAD`. This avoids the `@{upstream}` tracking-ref requirement (which is not guaranteed in fresh clones or non-standard worktree configurations). `has_queued_fix_commits(state)` evaluates to true iff the local PR-branch HEAD differs from the remote HEAD and the diff contains commits authored by the local branch. `_push` uploads exactly those commits; if none exist, the verb raises `PRECONDITION_NO_COMMITS` (under `--no-prework`) or a no-op (under default). Crash recovery: if the process dies after `_fix` but before `_push`, re-invoking `run` will re-enter at `_poll` → `fixesPending` → `_cluster` (idempotent on classified items) → `_fix` (idempotent on items already carrying `disposition`) → `_push` (uploads the orphaned-by-crash commits). No special crash-recovery code path is required.

**`_push` idempotency.** If `git push` succeeds but the subsequent state write fails (disk full, partial write), the next invocation's queued-commits check returns empty (commits already remote), so `_push` early-returns without incrementing `round` a second time. The result is a possible round under-count by one — preferred over double-counting.

**`ReviewerState.status` transition on `_push`.** A reviewer's `status == "review_found"` is bound to the SHA the reviewer evaluated. When `_push` uploads ≥1 new commit, the HEAD SHA changes and prior reviews become stale. After a successful push, `_push` walks `state.reviewers` and flips every entry with `required == True` AND `status == "review_found"` to `status = "not_requested"`. This ensures the post-push `_rereview` call (§3.3) finds reviewers to re-request. Reviewers in `{requested, in_progress, declined}` are left as-is — `rereview` already targets `{declined}` (plus `{not_requested}` after the flip) per §3.2, and `requested`/`in_progress` reviewers should not be disturbed mid-pass.

**Predicate definitions used in §3.3 pseudocode:**

- `has_queued_fix_commits(state) -> bool` — true iff the remote/local HEAD comparison yields ≥1 unpushed commit (see "Detecting queued (unpushed) fix commits" above).
- `has_required_reviewers_to_refresh(state) -> bool` — true iff `state.reviewers` contains ≥1 entry with `required == True` AND `status ∈ {not_requested, declined}`. After `_push`'s flip, this reduces to "any `required=True` reviewers are configured." False only when no required reviewers exist (e.g., the PR has no Copilot/codeowner required reviewer set).
- `push_uploaded_commits_this_cycle(state) -> bool` — true iff `state.last_pushed_head_sha` was updated during the current cycle (i.e., the most recent `_push` returned with a non-zero commit upload). Implemented in the in-memory state copy threaded by `_run`.
- `new_lifecycle_gate_this_cycle(state) -> bool` — true iff `state.last_error` was set by the end-of-cycle resolver in this cycle (cap-trip, etc.) and was not set in the prior cycle. Used to gate `lifecycle_escalation_filed = False` so each new gate fires exactly one Sink event.

**`_push` partial-write self-correction.** If `git push` succeeds but the subsequent state write fails, the next invocation's queued-commits check returns empty (commits are on the remote), so `_push` early-returns without incrementing `round`. The next `_poll` then observes `new_head_sha != state.last_pushed_head_sha` (because `last_pushed_head_sha` was not updated) and attributes the change as an external push, incrementing `round` via the external-push path. **Net effect: `round` is incremented exactly once, just via the external-attribution code path.** `last_pushed_head_sha` catches up on the next successful CLI push.

### 3.5 Hard-cap behavior

- **Default cap:** `MAX_ROUNDS = 3` — parallel to the current `wait-for-pr-comments` Round-3 cap. With `round` initialized to 1 on initial push, this allows the initial PR push plus two CLI fix-pushes before the cap trips.
- **Configurability:** `--max-rounds N` flag on `run` and `wait`; env var `PRGROOM_MAX_ROUNDS`; per-repo override in `.prgroom.toml` (file format owned by Section 7). **Precedence (highest → lowest):** CLI flag > env var > per-repo TOML > built-in default (3).
- **Trigger location:** the cap is checked **pre-push**, inside `run`'s cycle loop (§3.3), so the push that would exceed it is refused rather than uploaded:
  - condition: `has_queued_fix_commits(state) and state.round >= MAX_ROUNDS`
  - action: `state.phase = PRPhase.HUMAN_GATED`, `state.last_error = "LIFECYCLE_HARD_CAP_EXCEEDED"`, emit one escalation via `EscalationSink`, `store.write`, then return on next loop top (releasing lock).
- **Semantic clarification:** `MAX_ROUNDS` is the maximum count of *review-eliciting pushes the CLI will perform or observe* for this PR, including the initial push. The cap is a ceiling on `round`, not on it-plus-one. With `MAX_ROUNDS=3` the visible push history is exactly: initial (round=1) → fix-push #1 (round=2) → fix-push #2 (round=3) → cap blocks fix-push #3.
- **`wait` verb interaction:** `_wait` is only invoked from `awaiting-review` or `idle` (not from `fixes-pending`). It does NOT itself check the cap; the cap check belongs to the pre-push branch of `_run`. `wait`'s break conditions are owned by §4.
- **First-poll on an already-active PR (operator migration case).** When `prgroom run` is first invoked on a PR with prior reviewer rounds already on it (operator was running other tooling before adopting `prgroom`), the first `_poll` sets `round = 1` per §3.4's bootstrap rule but does NOT retroactively count the historical rounds. **The cap counts only rounds observed by `prgroom`** — historical out-of-band rounds are not visible to the CLI and so do not consume the budget. If the operator wants the cap to reflect the PR's full lifetime, they can pass `--max-rounds` lower to compensate, or wait for a future enhancement.
- **External pushes and the cap — "observed transitions only" rule.** External pushes count toward `MAX_ROUNDS` only when `_poll` observes them as a **SHA change between two consecutive poll invocations** (i.e., `new_head_sha != state.last_poll_sha` and `new_head_sha != state.last_pushed_head_sha`). The first-poll bootstrap (§3.4) sets `round = 1` to anchor the counter at the PR's currently observed HEAD; it does NOT retroactively scan and count historical pushes that occurred before `prgroom` ever ran on this PR. Rationale: the cap measures review work `prgroom` has *observed* the PR ask of reviewers, not the PR's total lifetime push history. This makes the §3.4 CLI-vs-external attribution rule and this rule fully consistent: historical pushes are invisible to `prgroom` and so do not count; pushes observed in-flight (CLI's own pushes counted by `_push`, external pushes counted by `_poll` SHA-transition attribution) do count. The consequence: if an operator force-pushes three times while `prgroom run --autonomous` is in `awaiting-review` and polling, those three transitions each bump `round` and may consume the cap; if the operator instead pushes three times BEFORE first launching `prgroom`, only the bootstrap `round = 1` is recorded. To mitigate cap consumption from in-flight external activity, `_push` emits a one-line stderr warning when the imminent push would advance `round` to `MAX_ROUNDS` (e.g., `prgroom: warning — this push reaches MAX_ROUNDS=3; subsequent fix work will gate to human-gated`). Operators who want CLI-only round budgets should distinguish via `--max-rounds` adjustment when manual pushes occur, or file a follow-up bead to split `MAX_ROUNDS_CLI` vs `MAX_ROUNDS_TOTAL`.
- **Recovery (cap re-arm).** Recovery is two *orthogonal* operator actions — escalation clearance and cap clearance are distinct authorizations:
  - **Escalated items** (only if the gate carries any): `resolve-escalated <pr> <item-id> --as <disposition>` flips each. This clears the *escalated-items* gate only; it does NOT clear `LIFECYCLE_HARD_CAP_EXCEEDED`, which is in `BlockingErrorCodes` (§3.2).
  - **The cap:** raise the budget (`--max-rounds N`, `PRGROOM_MAX_ROUNDS`, or `.prgroom.toml`) and re-invoke `run`. The §3.3 entry probe re-evaluates the cap: when `last_error == "LIFECYCLE_HARD_CAP_EXCEEDED"` and the raised budget means the cap no longer trips (`not (has_queued_fix_commits(state) and round >= MAX_ROUNDS)`), it clears `last_error`, sets `phase = PRPhase.FIXES_PENDING`, and re-enters the cycle. The refused fix commits then push under the raised cap, and end-of-cycle resolution writes a non-`human-gated` phase — the success path that also clears `last_error` (§3.3, immediately after `resolve_end_of_cycle_phase`). **The raised budget is the explicit operator authorization: a bare re-`run` with no raise leaves `round >= MAX_ROUNDS`, the predicate is false, and the phase stays `human-gated` — the cap is never silently lifted.** No `clear-error` verb is needed; manual state-file editing is never required.
  - **Or out of band:** a manual push, which `_poll` observes on the next invocation and re-enters `fixes-pending`.

### 3.6 Failure tier model

Extends Section 1's three-tier precondition gating into runtime errors. Every verb's failure path classifies into one of the tiers below. The tier determines the exit code, whether the phase transitions to `human-gated`, and whether an `EscalationSink` event is filed.

| Tier | Examples | Exit code | Phase change | Escalation | Caller (scheduler/agent) behavior |
|------|----------|-----------|--------------|------------|-----------------------------------|
| `PRECONDITION_SELFHEAL` | `fix` with no clusters → auto-runs `poll` + `cluster`, retries | 0 on self-heal success | none | no | proceeds normally |
| `PRECONDITION_USER_ERROR` | bad args, no PR detected, malformed PR ref | 2 (`EX_USAGE`) | none | no | aborts; user fixes invocation |
| `PRECONDITION_NO_WORK` | preconditions met but nothing to do | 0 (success-no-op) | none | no | proceeds |
| `RUNTIME_TRANSIENT` | gh 5xx, network blip, rate-limit with `Retry-After`, GraphQL transient | 75 (`EX_TEMPFAIL`) | none; `last_error` set | no | scheduler retries on next cadence |
| `RUNTIME_TERMINAL_USER` | gh auth missing/expired, repo deleted, branch protection blocks push, OAuth scope insufficient | 77 (`EX_NOPERM`) | → `human-gated`; `last_error` set | yes | aborts; user/operator must resolve |
| `RUNTIME_CANCELLED` | SIGINT / SIGTERM received during `_wait` (or other blocking internal); operator Ctrl-C or scheduler-issued cancellation (concrete codes: `RUNTIME_CANCELLED_SIGINT`, `RUNTIME_CANCELLED_SIGTERM` per §3.7) | 130 (SIGINT) / 143 (SIGTERM) — `128 + signum` per Unix convention | none; `last_error` left unchanged (cancellation is not a gating condition) | no | scheduler MUST NOT retry — non-retryable by convention; operator decides whether to re-invoke |
| `CONTRACT_AUDIT_FAILED` | fix-agent commit-orphan check failed; cluster output malformed after retry+fallback | 65 (`EX_DATAERR`) | affected item → `disposition.kind = DispositionKind.FAILED` with `disposition.rationale` set by the verb. **`handle_verb_error` returns `VerbDisposition.CONTINUE` for this tier — it does NOT set `state.last_error`.** End-of-cycle resolver §3.2 priority 2 promotes phase to `human-gated` (any `failed` item, any cause). The cause is available per-item via `disposition.rationale`, not via `state.last_error`. | yes | the run loop continues through the rest of the cycle; resolver fires one escalation per cycle (deduped via the `escalation_filed` flag on each item) |
| `STATE_CORRUPT` | store JSON corrupt; `schema_version` unknown; lock file present but holding PID dead-and-not-self | 78 (`EX_CONFIG`) | → `human-gated`; `last_error` set | yes | aborts; operator inspects state file |
| `LIFECYCLE_CAP` | pre-push cap guard tripped: `has_queued_fix_commits(state) and state.round >= max_rounds` (§3.5) | 0 (graceful terminal exit) | → `human-gated`; `last_error = LIFECYCLE_HARD_CAP_EXCEEDED` | yes | aborts; operator resolves escalations and/or raises the cap and re-runs (cap re-arm, §3.5) |

**Retry policy for `RUNTIME_TRANSIENT`:** the retry budget is **per logical API call, not per verb**. A single `_poll` may issue several distinct gh API calls (comments, reviews, CI status, head SHA); each gets its own budget independently. Per API call: **up to 3 total attempts** (initial call + 2 retries) before propagating the error. Back-off between retries is exponential: 1s before retry #1, then 4s before retry #2. When the failure response carries a `Retry-After` header (e.g., gh API rate-limit responses), the CLI honors that value instead of the exponential schedule for that retry. The CLI never retries indefinitely inside one process; after the third attempt fails for a single API call, the verb exits with the tier's code (75 `EX_TEMPFAIL`) and the scheduler (cron, `/loop`, agent caller) drives long-horizon retry.

**Note on `PRECONDITION_LOCK_HELD` tier classification.** Named like a precondition but exits 75 (transient-equivalent) — see §3.7 for rationale. The reason: lock contention is short-lived; scheduler retry-on-cadence is the right recovery, identical to `RUNTIME_TRANSIENT`. The "precondition" naming captures the *pre-work check* shape; the exit-code captures the *retry semantics*.

**`human-gated` re-entry:** the paths OUT of `human-gated` are:
- `resolve-escalated <item-id>` flips the gating disposition; phase moves to `fixes-pending` once no `escalated` items remain and `state.last_error not in BLOCKING_ERROR_CODES` (so a hard-cap gate is NOT cleared by `resolve-escalated` alone — see the cap re-arm path below).
- `poll` observes externally-resolved state (operator pushed a fix manually, or merged the PR) and writes `fixes-pending` or `merged` accordingly.
- `run` with a raised `--max-rounds` re-arms a hard-cap gate: the §3.3 entry probe clears `LIFECYCLE_HARD_CAP_EXCEEDED` and moves to `fixes-pending` when the cap no longer trips (§3.5 Recovery).
- (Note: the `human-review-required` PR label per §4.4 is a merge constraint, NOT a lifecycle gate — operator does not need to clear it to exit `human-gated`.)

### 3.7 Error-code registry

Every code carries `what` / `why` / `how` per Section 1's structured-stderr contract. Codes are stable identifiers in the form `<CATEGORY>_<SPECIFIC>`. Adding a new code is a non-breaking change; renaming or repurposing one is breaking.

**Tier assignment per code** (the §3.6 tier determines exit code via `exit_code_for_tier`, §3.3):

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
| `PRECONDITION_NO_UNRESOLVED` | `resolve` invoked with no items in `disposition.kind ∈ {DispositionKind.FIXED, DispositionKind.ALREADY_ADDRESSED}` AND `resolved is False` | nothing to do | exit-0 success-no-op (or exit 2 under `--no-prework`) |
| `PRECONDITION_NO_ESCALATIONS` | `resolve-escalated` invoked but no `escalated` items | nothing to resolve | re-check `status`; item may have been resolved already |
| `PRECONDITION_WAIT_NOT_APPLICABLE` | `wait` invoked while phase is `fixes-pending` | `wait` is for non-actionable phases; `fixes-pending` has work to do | invoke `run` (full cycle) or `fix`+`push` directly |
| `PRECONDITION_LOCK_HELD` | Another `prgroom` invocation holds the PR lock | concurrency model = one-at-a-time per PR; classified `RUNTIME_TRANSIENT`-equivalent (exit 75 `EX_TEMPFAIL`) | wait for the other invocation; scheduler retries on next cadence; `prgroom status <pr>` shows pid |

#### `RUNTIME_*`

| Code | Tier | What | Why | How |
|------|------|------|-----|-----|
| `RUNTIME_GH_TRANSIENT` | `RUNTIME_TRANSIENT` (75) | gh API returned 5xx or rate-limited with `Retry-After` | external service degraded | retry on next scheduler cadence |
| `RUNTIME_GH_TERMINAL` | `RUNTIME_TERMINAL_USER` (77) | gh API returned 4xx other than 404 or rate-limit | auth/scope/permission issue | inspect stderr; reconfigure gh token. For mid-flight auth expiry specifically, this is the runtime equivalent of `PRECONDITION_NO_AUTH`; re-run `gh auth login` and re-invoke |
| `RUNTIME_GRAPHQL_FAILED` | `RUNTIME_TRANSIENT` (75) | `resolve_review_thread` GraphQL mutation failed | thread may have been resolved externally or schema drifted | re-run `resolve`; if persistent, escalate via Sink |
| `RUNTIME_PUSH_REJECTED` | `RUNTIME_TERMINAL_USER` (77) | `git push` rejected (non-fast-forward, hook block, branch protection) | local branch diverged or rule blocks push; retry without intervention is futile | inspect git stderr; manual reconciliation required (rebase, fix hook, or adjust branch protection). After resolving manually, `_poll` will observe the new state on next `run` |
| `RUNTIME_GIT_TRANSIENT` | `RUNTIME_TRANSIENT` (75) | git network operation timed out | upstream connectivity blip | retry on next cadence |
| `RUNTIME_AGENT_UNAVAILABLE` | `RUNTIME_TRANSIENT` (75) | Primary AND fallback agent CLIs both failed | upstream model/tool unavailable | check `claude` / `codex` CLIs; verify quotas |
| `RUNTIME_AGENT_TIMEOUT` | `RUNTIME_TRANSIENT` (75) | Per-contract time budget exceeded | agent exceeded its budget for one cluster | re-run; if persistent, raise budget or shrink cluster |
| `RUNTIME_CANCELLED_SIGINT` | `RUNTIME_CANCELLED` (130) | SIGINT received during a blocking internal (typically `_wait`); operator pressed Ctrl-C | operator-initiated stop; non-retryable | inspect state via `prgroom status`; re-invoke `run` manually if/when desired |
| `RUNTIME_CANCELLED_SIGTERM` | `RUNTIME_CANCELLED` (143) | SIGTERM received during a blocking internal; scheduler-issued cancellation or container shutdown | external-initiated stop; non-retryable | inspect state via `prgroom status`; scheduler MUST treat 143 as terminal, not as a retry signal |

#### `CONTRACT_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `CONTRACT_CLUSTER_MALFORMED` | Cluster output JSON failed schema validation | Cluster contract invariant violated | retry once; second failure falls back to per-item clusters |
| `CONTRACT_CLUSTER_COVERAGE` | Some input items did not appear in any cluster after fallback | Cluster contract invariant: every item clustered | re-cluster; if persistent, file `failed` disposition for orphans |
| `CONTRACT_FIX_MALFORMED` | Fix output JSON failed schema validation | Fix contract invariant violated | item flipped to `failed`; escalate |
| `CONTRACT_FIX_ORPHAN_COMMIT` | Commits exist on branch that no item claimed | Fix contract invariant: every commit claimed | stash isolation applied; affected items flipped to `failed`; escalate |
| `CONTRACT_FIX_UNREACHABLE_SHA` | Output claims `commit_shas[i]` not on branch | Fix contract invariant violated | item flipped to `failed`; escalate |
| `CONTRACT_FIX_AUDIT_FAILED` | Disposition+evidence combination violates audit rules | Fix contract post-conditions | item flipped to `failed`; end-of-cycle resolution may promote phase to `human-gated` |

#### `STATE_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `STATE_CORRUPT` | Tracker JSON failed parse | state file written incompletely or hand-edited | move state file aside (`<file>.corrupt-YYYYMMDD`); re-run to rebuild |
| `STATE_SCHEMA_UNKNOWN` | `schema_version` not recognized | CLI older than state file (or vice versa) | upgrade/downgrade CLI; do not run conflicting versions concurrently |

**Locking mechanism note.** Section 2 specifies `flock(2)` advisory locking on the state file. `flock(2)` is **released automatically by the kernel on process death**, so the failure-tier registry does NOT include a "stale lock from dead process" code — that condition cannot occur with `flock(2)`. (Earlier drafts referenced `STATE_LOCK_STALE` and `NOTICE_LOCK_STALE_CLEANED` reflecting an `fcntl`-style protocol; both have been removed to match the chosen mechanism.) Lock contention by a live process surfaces as `PRECONDITION_LOCK_HELD` (registered above, exit 75).

#### `LIFECYCLE_*`

| Code | What | Why | How |
|------|------|-----|-----|
| `LIFECYCLE_HARD_CAP_EXCEEDED` | pre-push cap guard tripped: `has_queued_fix_commits(state) AND round >= max_rounds` (so `round` is never allowed to exceed `max_rounds`; the cap-tripping push is refused) | hard cap reached without quiescence | resolve outstanding escalations; raise `--max-rounds` and re-run — the §3.3 entry probe re-arms the cap and a successful cycle clears `last_error` automatically (a bare re-run with no raise stays `human-gated`; see §3.5 Recovery); or hand off to human review |

Adding new codes is straightforward; the registry's structure (`<CATEGORY>_<SPECIFIC>` with what/why/how) is the stable contract that agents and humans both consume.

---

## Section 4 — Quiescence model

Section 4 owns the **quiescence predicate** (when end-of-cycle resolution should transition `awaiting-review` → `quiesced`), the **`_wait` internals** (the `wait` verb's blocking-loop implementation, whose contract surface is declared in §3.3), the **human-review merge constraint** (a label-based satisfaction protocol that does NOT block the lifecycle), the **auto-merge eligibility contract** exposed by `prgroom status --json` (handoff surface for the future merge-gate `gmxo`/`td39`), and the **auto-request-human-review behavior** that adds a visible GitHub label when the CLI's lifecycle reaches a review-content gate.

Section 4 uses **hard gates + an idle timer**, not a tuneable probability score. Operators reading `prgroom status` get an explicit named gate as the answer to "why didn't it quiesce?"

### 4.1 Quiescence decision: hard gates + idle timer

`_wait` evaluates a **quiescence predicate** on every poll. The predicate is satisfied iff all hard gates pass AND the idle timer has elapsed. Hard gates are binary and operator-debuggable; `prgroom status` names the failing gate.

**Hard gates (all must pass):**

| Gate | Condition | Source field(s) |
|------|-----------|-----------------|
| `G_REVIEWERS` | Every reviewer with `required=True` has `status in {ReviewerStatus.REVIEW_FOUND, ReviewerStatus.DECLINED}` | `state.reviewers[*].required`, `state.reviewers[*].status` |
| `G_CI` | `state.quiescence.ci_state in {success, absent}` for `state.last_pushed_head_sha` | `state.quiescence.ci_state` |
| `G_DISPOSITIONS` | Every `state.items[*].disposition is not None` (sanity check — structurally guaranteed by `_fix` having run this cycle per §3.3 idempotency contract) | `state.items[*].disposition` |
| `G_NO_BLOCKERS` | No item has `disposition.kind in {DispositionKind.ESCALATED, DispositionKind.FAILED}` (sanity check — §3.2 priority cascade routes those to `human-gated` before reaching this predicate) | `state.items[*].disposition.kind` |

**Idle timer (the soft "let it settle" buffer):** `datetime.now(UTC) - state.last_activity_at >= idle_threshold`. `last_activity_at` is the timestamp of the most-recent PR-side mutation observed by `_poll` (new comment, new review, push, CI state change, label change). The idle timer's purpose is *not* to detect bot inactivity (per-reviewer timeouts in §4.1 own that case); it gives a short final buffer in case a slow human reviewer is mid-comment-draft when all hard gates flip green.

**`G_REVIEWERS` and the `declined` substates.** A Required reviewer can reach `status = ReviewerStatus.DECLINED` three ways:
1. Human reviewer explicitly passed (`declined_reason = "user-declined"`)
2. Auto-declined by `review_start_timeout` (`declined_reason = "timeout-no-start"`) — Copilot was requested but never engaged
3. Auto-declined by `review_finish_timeout` (`declined_reason = "timeout-stalled"`) — Copilot engaged but never produced a terminal review

All three count as gate-satisfying. The declined_reason is preserved for operator inspection via `prgroom status` so the operator can tell silence from explicit decline.

**`_poll` auto-decline logic (Section 4 add-on to §3.3's `_poll`):**

```python
def evaluate_reviewer_timeouts(state: PRGroomingState) -> None:   # invoked inside _poll, post-fetch
    for r in state.reviewers.values():
        if r.status == ReviewerStatus.REQUESTED and r.last_review_at is None:
            if datetime.now(UTC) - r.last_request_at > review_start_timeout:
                r.status = ReviewerStatus.DECLINED
                r.declined_at = datetime.now(UTC)
                r.declined_reason = "timeout-no-start"
        elif r.status == ReviewerStatus.IN_PROGRESS and r.last_review_at is not None:
            if datetime.now(UTC) - r.last_review_at > review_finish_timeout:
                r.status = ReviewerStatus.DECLINED
                r.declined_at = datetime.now(UTC)
                r.declined_reason = "timeout-stalled"
```

**"Engagement" detection — what sets `last_review_at` (Section 4 add-on to §3.3's `_poll`):** any actor-attributed activity after `last_request_at` and after the most-recent push timestamp:

- New comment on `/issues/{n}/comments` whose `user.login == r.identity` (Copilot's known top-level-comment reply pattern per the reviewer-bot quirks observed in prior `wait-for-pr-comments` runs)
- New review (`/pulls/{n}/reviews`) by `r.identity` in any state (`PENDING`, `COMMENTED`, `APPROVED`, `CHANGES_REQUESTED`)
- New inline review comment (`/pulls/{n}/comments`) by `r.identity`
- New thread reply by `r.identity`

First such activity flips `r.status = ReviewerStatus.IN_PROGRESS` and sets `r.last_review_at = activity.created_at`. Subsequent activity refreshes `r.last_review_at` AND `state.last_activity_at`. When `r.status` transitions to terminal (`ReviewerStatus.REVIEW_FOUND` for `APPROVED`/`CHANGES_REQUESTED`/`COMMENTED-with-final-disposition` per Section 5's contract; `ReviewerStatus.DECLINED` per the timeout paths above), no further `r.last_review_at` updates are needed.

**End-of-cycle interaction with §3.3's `resolve_end_of_cycle_phase`:** the priority cascade in §3.2 places quiescence at **priority 5** (after the blocker gates at priorities 1-3 and the commit-pushed rule at priority 4). `resolve_end_of_cycle_phase` calls `quiescence_predicate(state)` at priority 5; when true, sets `state.phase = PRPhase.QUIESCED`, `state.quiescence.quiesced_at = datetime.now(UTC)`. When false, phase stays `awaiting-review` and the next `_wait` invocation re-evaluates.

```python
def quiescence_predicate(state: PRGroomingState) -> bool:
    return (all_reviewer_gates_pass(state)              # G_REVIEWERS
            and ci_gate_allows(state.quiescence.ci_state)   # G_CI
            and all_items_dispositioned(state)         # G_DISPOSITIONS
            and no_blocker_dispositions(state)         # G_NO_BLOCKERS
            and datetime.now(UTC) - state.last_activity_at >= idle_threshold)
```

### 4.2 `_wait` internals

**Contract surface** (declared in §3.3, "`_wait` contract surface"): `_wait(self, pr: PRRef, state: PRGroomingState) -> PRGroomingState`. The public verb `wait(pr)` is the locking wrapper that does `with self._store.lock(pr): return self._wait(pr, state)`; `_wait` itself assumes the PR lock is already held — its docstring states `Caller must hold the per-ref lock (see lock()).`. The lock is held for the entire invocation (no mid-sleep release), guaranteed by the `lock()` context manager's `finally`. Cancellation is honored through a `threading.Event` (the cancel token) set by `run`'s OS signal handler.

**Pseudocode notation:** `signum` below denotes the integer signal number captured by `run`'s OS signal handler (installed at process startup per §3.7 via the stdlib `signal` module). The cancel-token `threading.Event` itself does not carry a signal number, so the handler records the observed `signum` in a value visible to the cancellation path (e.g. an instance attribute or a small accessor on the deps surface) alongside setting the event. Concrete implementation is the implementer's call; the contract is only that `signum` is available at error-construction time for the exit-code mapping in §3.7.

```python
def _wait(self, pr: PRRef, state: PRGroomingState) -> PRGroomingState:
    """Caller must hold the per-ref lock (see lock())."""
    while True:
        # Wake event 1: signal-cancel — return immediately, RUNTIME_CANCELLED tier
        if self._cancel.is_set():
            raise RuntimeCancelledError(signum=self._signum)

        # Interruptible sleep — wakes on poll_interval expiry or cancel-token set.
        # Event.wait(timeout) returns True if the event was set during the wait
        # (cancellation), False if the full poll_interval elapsed.
        if self._cancel.wait(timeout=poll_interval.total_seconds()):
            raise RuntimeCancelledError(signum=self._signum)

        # Wake event 2: any _poll error propagates per §3.3 handle_verb_error.
        # _poll returns the mutated state; on failure it raises, and _run's
        # handle_verb_error decides PROPAGATE vs CONTINUE.
        state = self._poll(pr, state)

        # _poll side-effects relevant to §4 (added by this section):
        #   - updates state.last_activity_at on observed PR-side mutations
        #   - calls evaluate_reviewer_timeouts(state)  (§4.1)
        #   - updates state.quiescence.ci_state from latest check-runs/statuses
        #     for state.last_pushed_head_sha
        #   - reads state.human_review_label_added is unchanged here
        #     (set by §4.7's request_human_review_if_needed)

        # Wake event 3: phase already moved off awaiting-review/idle (fix commits arrived,
        # external push, PR merged externally, etc.) → return to let _run re-enter cycle
        if state.phase not in {PRPhase.AWAITING_REVIEW, PRPhase.IDLE}:
            return state

        # Wake event 4: quiescence predicate satisfied → trip to quiesced, write, return
        if quiescence_predicate(state):
            state.phase = PRPhase.QUIESCED
            state.quiescence.quiesced_at = datetime.now(UTC)
            self._store.write(pr, state)
            return state

        # Otherwise: loop back, sleep again
```

**Wake event registry (all paths that exit `_wait`):**

| Trigger | Exit condition | Phase on exit | Error tier |
|---------|---------------|---------------|------------|
| Signal (SIGINT/SIGTERM) | cancel token set | unchanged | `RUNTIME_CANCELLED` (130/143 per §3.7) |
| `_poll` transient error | gh API past retry budget | unchanged | `RUNTIME_TRANSIENT` (75) — scheduler retries |
| `_poll` terminal error | gh auth expired, etc. | `human-gated` | `RUNTIME_TERMINAL_USER` (77) |
| Activity moves phase | fix commits arrived → `fixes-pending`; PR merged externally → `merged`; escalated/failed item produced → `human-gated` via §3.2 cascade on next cycle | as observed | normal return |
| Quiescence trips | `quiescence_predicate(state) == True` | `quiesced` | normal return |
| *(intentional non-trigger)* | n/a — no hard wait-timeout in MVP | n/a | n/a |

**No hard wait-timeout in MVP** — the design relies on (a) per-reviewer timeouts (§4.1) to handle bot silence, (b) the `human-review-required` label as the explicit operator merge-block (§4.4), (c) signal-cancel as the manual bail-out. A hard wait-timeout would add a fourth exit path racing with the others without solving a distinct failure mode. If operations experience shows long waits hanging too often, it's a one-line addition in v2.

**Lock semantics:** the lock is held continuously for the entire `_wait` invocation (the public `wait` wrapper's `lock()` context manager spans it). Per §3.3's "`status` read-only carve-out", the `status` verb is lock-free, so operators can `prgroom status <pr>` during long waits without contending.

**Signal handling:** `run`'s OS signal handler sets the cancel-token `threading.Event` on SIGINT/SIGTERM (installed via the stdlib `signal` module at process startup). `_wait` honors the cancel token both at the top of each loop iteration AND inside the interruptible sleep (`Event.wait(timeout=...)`, which returns early when the event is set). A cancelled wait raises `RuntimeCancelledError`, a distinct error tier from `RUNTIME_TRANSIENT` (per §3.3's `handle_verb_error` `RUNTIME_CANCELLED` case), so the scheduler does NOT retry a cancelled wait.

**Resumability (crash-recovery semantics).** All §4 timestamps in state are stored as **absolute UTC** (RFC3339 / ISO-8601):

- `state.last_activity_at`
- `state.quiescence.quiesced_at`
- `state.reviewers[r].last_request_at`
- `state.reviewers[r].last_review_at`
- `state.reviewers[r].declined_at`

Timeout *deadlines* are **derived per-evaluation**, never stored:

```python
start_deadline_passed = datetime.now(UTC) - r.last_request_at > review_start_timeout
finish_deadline_passed = (
    r.last_review_at is not None
    and datetime.now(UTC) - r.last_review_at > review_finish_timeout
)
idle_satisfied = datetime.now(UTC) - state.last_activity_at >= idle_threshold
```

Crash-recovery flow:
1. Process dies mid-`_wait`. The OS releases the §2 file-adapter lock via `flock(2)`-on-fd-close (the `lock()` context manager's fd is closed on process exit; per §3.7's "Locking mechanism note").
2. Scheduler re-invokes `prgroom run`. `run` acquires the lock; `_run` reads state from disk.
3. All §4 timestamps are intact (last written by `_poll` before crash).
4. Re-entered `_wait`'s first `_poll` re-evaluates deadlines from the current `datetime.now(UTC)`. Elapsed time across the crash gap counts. A reviewer with `datetime.now(UTC) - r.last_request_at > review_start_timeout` auto-declines as expected — same outcome as if the process had never died.

Config-change semantics: operator raises `review_start_timeout` from 3m→5m mid-flight via TOML edit. Next `_poll` evaluation reads the new value (Section 7 owns config-reload cadence; assume re-read per `run` invocation). A reviewer who would have been auto-declined at 3m gets the extension. Operator intent always wins because deadlines aren't frozen at start-time.

### 4.3 Configuration surface

All Section 4 knobs follow §3.5's established precedence pattern: **CLI flag > env var > per-repo `.prgroom.toml` > built-in default**.

| Setting | Default | Flag | Env var | TOML key |
|---------|---------|------|---------|----------|
| `idle_threshold` | `10m` | `--idle-threshold` | `PRGROOM_IDLE_THRESHOLD` | `quiescence.idle_threshold` |
| `poll_interval` | `30s` | `--poll-interval` | `PRGROOM_POLL_INTERVAL` | `quiescence.poll_interval` |
| `review_start_timeout` | `3m` | `--review-start-timeout` | `PRGROOM_REVIEW_START_TIMEOUT` | `quiescence.review_start_timeout` |
| `review_finish_timeout` | `15m` | `--review-finish-timeout` | `PRGROOM_REVIEW_FINISH_TIMEOUT` | `quiescence.review_finish_timeout` |
| `auto_request_human_review` | `true` | `--auto-request-human-review[=false]` | `PRGROOM_AUTO_REQUEST_HUMAN_REVIEW` | `quiescence.auto_request_human_review` |

All durations parse with a small duration-string helper accepting `30s`, `10m`, `1h30m` syntax into a `datetime.timedelta`. Section 7 owns the TOML format and config-loading mechanism; §4 just declares the keys it consumes.

### 4.4 Human-review merge constraint (NOT a lifecycle blocker)

The PR label `human-review-required` is a **merge constraint**, not a lifecycle constraint. The full poll → cluster → fix → push → rereview → reply → resolve cycle runs normally when the label is set; quiescence still trips when gates pass. The label only affects `auto_merge_eligible` in §4.6.

**The constraint:** GitHub PR label `human-review-required` (literal string, case-insensitive match). Indicates a human must approve before merge.

**Satisfaction signals (OR — any one satisfies the constraint):**

- Label `human-approved` (literal string, case-insensitive) — covers the self-PR case where GitHub blocks self-approval
- A GitHub PR review with `state == APPROVED` AND `reviewer.actor.type != "Bot"` — i.e., a real human approval through the standard reviewer flow

The `Bot`-filter on PR approvals is **load-bearing**: without it, Copilot's auto-approval of a self-PR would satisfy the gate. Bot approvals do not count for the human-review gate.

**CLI read path:** `_poll` already fetches labels and reviewer-state as part of standard PR poll. The constraint check is pure-derivation from existing state fields — no new API calls. `_poll` does NOT persist `human_review_constrained` or `human_review_satisfied` in state; both are derived per-status-query because they're functions of current GitHub state, not lifecycle history.

**Lifecycle behavior:** none. `_poll` does NOT transition phase based on the label. The cluster/fix/push/reply/resolve cycle continues normally.

**Quiescence behavior:** unchanged from §4.1 — gates pass → idle timer trips → `phase = PRPhase.QUIESCED`. The label does NOT block quiescence.

**Operator workflow:**

- To require human review (upstream signal): `gh pr edit --add-label human-review-required`
- To satisfy via label (self-PR or supplemental): `gh pr edit --add-label human-approved`
- To satisfy via standard reviewer flow: leave a GitHub PR review with "Approve"
- To unrequire (rare; usually leave the historical record): `gh pr edit --remove-label human-review-required`

### 4.5 Relationship to §3.5 hard-cap

Quiescence (§4) and the round hard-cap (§3.5) are **independent terminal paths**:

| | Round hard-cap (§3.5) | Quiescence (§4) |
|---|---|---|
| Trigger condition | `state.round >= MAX_ROUNDS` AND `has_queued_fix_commits(state)` | All hard gates pass AND idle timer trips |
| Triggers from phase | `fixes-pending` (pre-push check in `_run`) | `awaiting-review` (inside `_wait` or end-of-cycle resolver) |
| Result phase | `human-gated` | `quiesced` |
| `last_error` | `LIFECYCLE_HARD_CAP_EXCEEDED` | (unset) |
| Auto-merge-eligible | No | Yes (modulo §4.6) |
| Auto-request human review | Yes (§4.7) | No |
| Recovery | Operator raises `--max-rounds` + re-runs; or `resolve-escalated` + re-runs | None needed — `quiesced` is success |

A PR can reach either terminal but not both in the same cycle: the round cap fires inside `_run`'s cycle (pre-push, §3.3 "Pre-push hard-cap check"), before the next `_wait` invocation. Once in `human-gated`, `_wait` is not invoked — the §3.2 priority cascade routes elsewhere.

**No new hard-cap defined in §4.** The bead description's "hard cap parallel to current `wait-for-pr-comments` round-3 cap" requirement is satisfied by §3.5's existing `MAX_ROUNDS=3` default. §4 only adds the auto-request-human-review behavior (§4.7) that fires when §3.5's cap trips.

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
auto_merge_eligible =
  merge_gates.phase_is_quiesced     AND
  merge_gates.last_error_clear      AND
  merge_gates.no_blocker_items      AND
  merge_gates.human_review_satisfied

merge_gates.phase_is_quiesced      = state.phase == PRPhase.QUIESCED
merge_gates.last_error_clear       = state.last_error is None or state.last_error == ""
merge_gates.no_blocker_items       = no item with disposition.kind in {DispositionKind.ESCALATED, DispositionKind.FAILED}
merge_gates.human_review_satisfied = not human_review.required or human_review.satisfied_by is not None

human_review.required              = has_label("human-review-required")
human_review.satisfied_by          = first matching:
                                        "label" if has_label("human-approved")
                                        "approval:{login}" if any review has state == APPROVED and not actor.type == "Bot"
                                        None otherwise
human_review.candidates_seen       = list of all examined PR-approval candidates with bot-filter outcome,
                                     e.g. [{"login": "github-copilot[bot]", "approved": true, "counted": false, "reason": "bot"}]
```

The `candidates_seen` field is for operator debuggability — answers "why didn't approval X count?" without re-running queries.

**Stability commitment:** the JSON shape above is part of §4's stable interface. Adding fields is non-breaking. Removing or renaming fields is breaking and requires a version-bumped JSON envelope (deferred to `gmxo`/`td39` brainstorm if needed).

### 4.7 Auto-request human review on lifecycle gating

When `_run` transitions to `human-gated` for a **review-content reason**, prgroom automatically adds the `human-review-required` label to the PR. This complements the existing `EscalationSink` event (stderr / bd-adapter) with a GitHub-visible marker so operators scanning their PR list immediately see "automation gave up here."

**Triggering conditions (any one):**

| Trigger | Source |
|---------|--------|
| `state.last_error == "LIFECYCLE_HARD_CAP_EXCEEDED"` | §3.5 round hard-cap trip |
| Any item with `disposition.kind == DispositionKind.ESCALATED` | §3.2 priority cascade (escalated items) |
| Any item with `disposition.kind == DispositionKind.FAILED` | §3.2 priority cascade (audit-failed or agent-could-not-converge) |

**Explicit non-triggers (review-content vs infra/state distinction):**

- `RUNTIME_TERMINAL_USER` (gh auth expired, etc.) — infra problem, not a review problem
- `STATE_CORRUPT` / `STATE_SCHEMA_UNKNOWN` — operator-investigate-state-file
- `RUNTIME_PUSH_REJECTED` / `RUNTIME_GH_TERMINAL` — infra problem

**Implementation — `request_human_review_if_needed(state)`:**

```python
def should_request_human_review(state):
    return (
        state.last_error == "LIFECYCLE_HARD_CAP_EXCEEDED"
        or any(item.disposition is not None and item.disposition.kind == DispositionKind.ESCALATED for item in state.items)
        or any(item.disposition is not None and item.disposition.kind == DispositionKind.FAILED for item in state.items)
    )

def request_human_review_if_needed(state):
    if not auto_request_human_review:                            # §4.3 config knob
        return
    if not should_request_human_review(state):
        return
    if state.human_review_label_added:
        return                                                   # already added once this gating event
    try:
        gh.add_label(pr, "human-review-required")
    except Exception as exc:
        log_stderr("prgroom: warning — failed to add human-review-required label: " + str(exc))
        return                                                   # best-effort; flag stays false; next cycle retries
    state.human_review_label_added = True
    store.write(pr, state)
```

`request_human_review_if_needed` is invoked alongside `escalate_if_needed` at the **same two dedup-safe call sites in `_run`** (per §3.3): the loop-top terminal-for-CLI check, and immediately before each `PROPAGATE`-return after `handle_verb_error`. Both functions are idempotent and best-effort; both follow the same crash-window dedup posture.

**Reset semantics (mirrors §3.3's `last_error` clear-on-success after `resolve_end_of_cycle_phase`):** `state.human_review_label_added` is reset to `False` on the **same condition** that clears `last_error` — successful end-of-cycle resolution to any phase other than `human-gated` (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, or `merged`). Wired into §3.3's `_run` pseudocode at the same point that clears `last_error`. After reset, if the gating condition recurs (a new cap-trip after operator raised `--max-rounds`), the label gets re-added on the next gating event.

**Operator override (deliberate one-way intent):** if the operator manually `gh pr edit --remove-label human-review-required` while `state.human_review_label_added == True`, prgroom does NOT re-add the label on the next invocation — `human_review_label_added` is still `True` in state, so `request_human_review_if_needed` short-circuits. The label re-adds only after the reset path above fires AND the gating condition recurs. This preserves operator intent ("I've handled this") without permanent suppression.

**Interaction with §4.4's `human-approved` satisfaction signal:** the operator adding `human-approved` (or leaving a human PR approval) AFTER prgroom added `human-review-required` causes §4.6's `auto_merge_eligible` to become `True`. **The `human-review-required` label persists** as historical record; the operator does NOT need to remove it. Future audits see "constraint was raised AND satisfied." This is exactly why §4.4 chose positive-signal satisfaction over absence-of-negative — clean operator-actionable records.

**Permissions:** `gh.add_label` requires triage or write access on the repo. Failure is logged to stderr (one-line warning) but does NOT tier-tag the error, does NOT block lifecycle progression, does NOT propagate via `handle_verb_error`. Same best-effort posture as the Sink-error handling in §3.3 (`escalate_if_needed` semantics). Operators seeing persistent label-add failures should check their PAT scopes.

### 4.8 §2 schema fields consumed by Section 4

| §2 field | Section using | Purpose |
|----------|---------------|---------|
| `PRGroomingState.last_activity_at` | §4.1, §4.2 | idle-timer reference |
| `PRGroomingState.human_review_label_added` | §4.7 | dedup flag for `human-review-required` label auto-add |
| `ReviewerState.last_request_at` | §4.1 | `review_start_timeout` reference |
| `ReviewerState.last_review_at` | §4.1 | `review_finish_timeout` reference; first observed engagement post-request |
| `ReviewerState.declined_at` | §4.1 | timestamp of decline (any reason) |
| `ReviewerState.declined_reason` | §4.1, §4.6 | one of: `user-declined`, `timeout-no-start`, `timeout-stalled` |
| `QuiescenceState.ci_state` | §4.1 | `G_CI` gate input for `state.last_pushed_head_sha` |
| `QuiescenceState.quiesced_at` | §4.2, §4.6 | set on transition to `quiesced`; surfaced in status JSON |
| `ReviewerStatus.DECLINED` | §4.1 | covers explicit pass AND auto-decline; subcause via `declined_reason` |

## Section 5 — Agent dispatch internals (named contracts)

The cheap agent is bad at deciding intent but good at grouping; the heavy agent is good at deciding intent because it can see the whole picture. The two contracts split along that line:

- **Cluster** (cheap agent) — groups related items into fix-bundles. Does NOT decide disposition.
- **Fix** (heavy agent / orchestrator) — for each cluster, decides per-item disposition AND implements the work where warranted. Inherits the full PR context, prior PR memories, and access to skills/agents.
- **Resolve-escalated** (human-initiated verb) — flips an `escalated` disposition into a terminal one and lets the lifecycle continue.

Each contract is a **stable, versioned interface** between the CLI and the agent-CLI. That stability is what lets us swap `claude -p` for `codex exec` or `opencode run`, change models, run different agents per hand-off, or fall back when the primary is unavailable — without touching the CLI's lifecycle code. Available runtimes (`claude -p`, `codex exec`, `opencode run`, local `ollama`) are selected per-contract in TOML config; the per-contract default chains below are just the shipped defaults, not the limit of what's supported.

#### Cluster contract — the `cluster` verb

- **When:** during the `cluster` verb. Operates on the set of items with `cluster_id == ""`.
- **Default agent CLI (primary → fallback chain):** Prefer a local model via `ollama` (Gemma 4 or similar small classifier) if installed; otherwise `claude -p` with model `haiku` / effort `high`; otherwise `codex-mini`. Cheap, fast — grouping intent is NOT decisional work, so locally-runnable models are appropriate.
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

#### Fix contract — the `fix` verb

- **When:** during the `fix` verb, **once per cluster**. Serial in MVP (parallel deferred).
- **Default agent CLI:** `claude -p` with model `opus[1m]` and effort `xhigh`. This launches an **orchestrator** agent that will itself choose skills/sub-agents (e.g. `quality-reviewer`, `simplify`, language-specific debuggers). Model and effort for those sub-agents are set by the orchestrator, not by `prgroom`.
- **Input (JSON, written to a file passed by path):**
  ```json
  {
    "contract_version": 1,
    "pr": { "owner": "...", "repo": "...", "number": 123 },
    "cluster_id": "c-abc123",
    "item_gh_ids": ["<id>", "<id>"],
    "items": [ { /* full ReviewItem entries for this cluster; items carrying a prior disposition also carry a `recurrence` object — see §8.2 */ } ],
    "pr_detail_path": "<path to file: COMPLETE PR snapshot — description (incl. the `## Decisions` block), labels, every review thread with full reply-chains, and prior-round dispositions (kind/rationale/commits/decided_by). See §8.1>",
    "branch_state_path": "<path to file: recent commits + diff-since-base>",
    "memory_dir": "<path to an ephemeral within-run scratchpad for the agent's internal sub-agents; NOT cross-round memory — that lives in the PR + prior dispositions. See §8.4>",
    "response_outbox_dir": "<path to directory the agent writes per-item response text files to>"
  }
  ```
  The CLI does the gh-API legwork up-front and dumps everything to files; the agent does NOT re-call gh itself (rationale: runtime swappability, auth containment, rate-limit centralisation, reproducibility — see §8.1). (There is deliberately no `root_cause_note` field — it does not apply to PR-grooming.) The complete-snapshot guarantee and the `memory_dir` role are specified in **Section 8 — PR memory management**.
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
    "memory_writes": ["<path>", "..."],           // optional; files the agent created in memory_dir — ephemeral scratch, containment-audited (§8.4, §8.6)
    "memory": [                                   // optional; classified memory the CLI routes (§8.3). MVP routes CONTEXTUAL→PR only; other classes accepted-but-deferred. Each entry sets EXACTLY ONE of `content` | `path`; `classification` ∈ {UNIVERSAL, PROJECT, PLANNED, HISTORICAL, CONTEXTUAL}
      {                                           // inline form — thread-less PR-wide decision → `## Decisions` PR-body block
        "content": "<inline markdown>",
        "classification": "CONTEXTUAL"
      },
      {                                           // file form — note tied to a specific thread
        "path": "<file in memory_dir>",
        "classification": "CONTEXTUAL",
        "target_hint": "<thread node-id>"         // optional; the CONTEXTUAL thread-reply target
      }
    ]
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
- **What it does:** finds the item, replaces `disposition` accordingly, sets `disposition.decided_by = "human:<git-user>"`. The lifecycle resumes on the next `run` / `wait` / `reply` invocation.
- **Why a verb:** interactive prompts mid-flight create UX coupling between the CLI and its caller; an explicit verb is debuggable, scriptable, and undo-able (re-run with different args).

#### Escalation surface — via `EscalationSink` abstraction

The CLI does NOT directly call `bd label add ...` from inside Section-5 contract code. Escalation routing goes through an `EscalationSink` interface so the CLI works with or without beads:

```python
@dataclass(frozen=True, slots=True)
class Escalation:
    pr: PRRef
    reason: str                              # free-form, public-safe
    severity: Severity                       # info | warn | block
    item: ReviewItem | None = None           # optional; the item that triggered the escalation

@runtime_checkable
class Sink(Protocol):
    def emit(self, escalation: Escalation) -> None:
        """emit records ("files", verb-sense) an Escalation. The method name was
        chosen for clarity vs the `file` adapter; both `stderr`, `file`, and
        `bd` adapters implement this single method."""
        ...  # pragma: no cover
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
| `cluster`           | A (per batch)  | persist `cluster_id` on each item |
| `fix`               | B (per cluster)| dump gh detail; serial cluster dispatch; per-subagent audit; orphan-commit check; stash isolation on audit fail |
| `push`              | none           | `git push` (any accumulated fix-agent commits) |
| `rereview`          | none           | remove/add reviewer dance to coerce a fresh `review_requested` event |
| `reply`             | none           | render templates + use `response_path` files; post via gh API |
| `resolve`           | none           | GraphQL `resolveReviewThread` for `review_thread` items whose `disposition.kind ∈ {fixed, already_addressed}` |
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
fallback = { cli = "claude", model = "haiku", effort = "high" }
fallback2 = { cli = "codex", model = "gpt-5.4-mini" }

[agents.fix]
primary  = { cli = "claude", model = "opus[1m]", effort = "xhigh" }
fallback = { cli = "codex",  model = "gpt-5.5", write = true }
```

Fallback triggers: primary binary not on PATH; primary exits with quota/auth/network error code; primary times out (per-contract budget). If both primary AND fallback fail, the verb emits a `failed` disposition for the affected items + escalates via the `EscalationSink`.

#### Prompt templates

Each contract's prompts (system + user) live in `agent/prompts/<contract>.tmpl` as template files. Templates take a contract-specific dataclass as data. Loaded once at startup; the template engine is the same one used for reply rendering. The user can override via `PRGROOM_PROMPTS_DIR=<dir>` (any matching filename in the override dir wins). Override is for power users / experimentation, not the default path.

#### Token-usage logging

The CLI logs **per-contract token usage** to `$XDG_STATE_HOME/prgroom/usage.jsonl` when the agent CLI emits a usage line (Claude and Codex CLIs both do). The CLI does NOT do analysis or aggregation; this is **MVP baseline-capture only**, so future cost-optimization work has data to start from. The "should the CLI surface cost estimates inside its output?" question is deferred.

#### Audit guards in Python

Each contract's audit is a Python function with table-driven (parametrized) tests (parallels the current `audit-subagent-report.sh`). Audit failures emit structured errors and route through `EscalationSink` as appropriate.

## Section 6 — Migration plan

This section defines the **incremental cutover** from the two prose skills to `prgroom`: what lands in each phase, the fate of every bash script, how the surviving skill is reshaped, the cutover protocol, and rollback. Locked constraints: **incremental, two-phase, no legacy-state migration.**

The two skills are treated differently:

- `reply-and-resolve-pr-threads` is **deleted** — its work is fully covered by deterministic `prgroom` verbs.
- `wait-for-pr-comments` is **replaced** by a new, thin *contract-aware supervisor* skill, **`monitor-pr`**, that drives `prgroom run` and owns the agent-side judgment prgroom hands back. prgroom does the grunt work; `monitor-pr` does the exception handling — the "5% troubleshooting" slice of the project vision.

#### 6.1 Migration principles

1. **Prerequisite (not a phase) — prgroom must be installable first (cross-ref §7).** No skill can thin until `prgroom` is built and on `PATH` via `scripts/install.sh`. The first migration commit wires §7's build/install path; skills stay untouched until it lands.
2. **Separate state stores, no collision.** prgroom writes `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`); the legacy skills write `~/.claude/state/pr-inventory/`. Neither reads the other.
3. **No legacy-state migration (locked).** In-flight PRs under the old inventory are not converted. The cutover protocol (§6.4) drains them instead.
4. **Both deletions are git-revertible** — the rollback unit is the phase commit (§6.5).

#### 6.2 Phase 1 — absorb `wait-for-pr-comments`; birth `monitor-pr`

**Verbs that must be production-ready (the whole loop):** `poll`, `cluster`, `fix`, `push`, `rereview`, `wait`, `status`, `run`, plus the deterministic `reply`, `resolve`, and `resolve-escalated`. (`sweep` optional if cheap.)

> **Why reply/resolve ship in Phase 1, not Phase 2.** They are "no-agent" deterministic verbs (§5 verb→contract table). `prgroom run` must be a no-regression drop-in for today's full post-push flow, which *includes* Skill A's Phase-8 hand-off to Skill B (reply + resolve). A Phase-1 `run` that stopped before reply/resolve would regress; the only alternative — having `run` shell out to the still-live Skill B — needs a throwaway prgroom→legacy-inventory bridge (format mismatch). We build the verbs natively instead. This makes **Phase 2 a light retirement phase** (§6.3), not a second build.

**The `monitor-pr` skill (the reborn supervisor).** Body ≈ 50 lines, not 800. It is **contract-aware**: it interprets what prgroom returns and *acts on* the human-judgment kickbacks (it does not merely watch). It must know three prgroom contracts:

| prgroom contract | Source | What `monitor-pr` does with it |
|---|---|---|
| **Exit-code registry** | §3.7 | Map exit code → action (success / retry / surface-to-human) — see decision table below |
| **`status --json` shape** | §4.6 | Read `phase`, `items_summary`, `merge_gates`, `auto_merge_eligible`, escalated/failed items → build user summary + detect kickbacks |
| **Terminal phases** | §3, §4 | `quiesced`/`merged` → report; `human-gated` → surface escalations + hand over the `resolve-escalated` recipe |

**`monitor-pr` decision table** (authority for codes is §3.7; phases §3/§4):

| prgroom result | Interactive mode | Autonomous mode |
|---|---|---|
| exit 0, `phase ∈ {quiesced, merged}` | Report success summary from `status --json` | Exit 0; sink silent |
| `phase = human-gated` (escalated/failed items; or `last_error = LIFECYCLE_HARD_CAP_EXCEEDED`) | Surface each item's rationale; hand over `prgroom resolve-escalated <pr> <id> --as … --rationale …`; re-invoke after | Route via `EscalationSink` (bd/file); exit non-zero |
| `RUNTIME_TERMINAL_USER` (gh auth expired, etc.) | Surface the infra problem; stop | Escalate via sink; exit non-zero |
| `RUNTIME_TRANSIENT` | Re-invoke (bounded) | Let scheduler retry |
| `RUNTIME_CANCELLED` | Report cancellation; stop | Exit per signal |

Mode is selected from the trigger (chat = interactive; cron / `/loop` / GHA = autonomous), mirroring §1's three usage patterns; the skill passes `--interactive` / `--autonomous` to `prgroom run`.

**Skill-body change.** `wait-for-pr-comments/SKILL.md` (~800 lines, 9 phases) is **deleted**; `monitor-pr/SKILL.md` is **created** with the supervisor body above. Treated as new-skill + delete-old rather than in-place rename, because identity, trigger wiring, and body all change.

**Script fates — Skill A:**

| Fate | Scripts |
|---|---|
| Absorbed → `prgroom/gh` + `poll`/`rereview`/`fix` | poll-copilot-review.sh, poll-copilot-rereview-start.sh, poll-new-comments.sh, fetch-and-normalize-comments.sh, detect-pr-context.sh, request-rereview.sh, count-unresolved-threads.sh, audit-subagent-report.sh |
| Deleted, no 1:1 successor (format/plumbing) | build-inventory-body.sh, write-inventory.sh, validate-inventory.sh (→ replaced by the `prsession` `Store` schema), lib.sh |
| Kept, with a one-line edit | detect-pr-push.sh (hook) — suggestion string updated `wait-for-pr-comments` → `monitor-pr`; full hook rework still deferred to v3 |

All deleted scripts' `*_test.sh` go with them. After deletion, `install.sh --prune` removes the deployed copies.

**Reference-repointing (same commit).** Grep the rule set for the old skill name and repoint: `delivery.md` and `completion-gate.md` reference `wait-for-pr-comments` by name → update to `monitor-pr`. (The "by default invokes `reply-and-resolve-pr-threads`" clause is rewritten in Phase 2, when Skill B dies.)

#### 6.3 Phase 2 — retire `reply-and-resolve-pr-threads`

Deliberately light: `reply` / `resolve` / `resolve-escalated` already shipped in Phase 1. Phase 2 is **retirement + cleanup**, gated on Phase 1 baking (§6.5 readiness gate).

- **Skill deletion.** `reply-and-resolve-pr-threads/SKILL.md` is deleted. Standalone reply/resolve becomes the verbs `prgroom reply <pr>` / `prgroom resolve <pr>`; the old `--resume` crash-recovery becomes "re-invoke prgroom" (reads `prsession` state; idempotent).
- **Script fates — Skill B** (all absorbed by Phase 1's verbs; the files are deleted now):

| Fate | Scripts |
|---|---|
| Absorbed → `reply`/`resolve`/`status` + `prgroom/git` | render-reply-bodies.sh, post-replies.sh, resolve-threads.sh, verify-head-sha.sh, probe-fix-shas.sh, build-final-report.sh |

  Tests deleted with them; `install.sh --prune`.
- **Reference-repointing.** Rewrite the `completion-gate.md` / `delivery.md` clause "…invokes `reply-and-resolve-pr-threads`" → "…prgroom handles reply + resolve within `run`." Grep confirms no remaining references to the deleted skill.

#### 6.4 Cutover protocol — "drain before cutover"

The concrete form of the locked "finish-on-legacy / new-on-prgroom":

1. **Drain.** Before installing Phase 1, finish (merge or abandon) every PR with a live legacy inventory (`ls ~/.claude/state/pr-inventory/ 2>/dev/null` — tolerates a missing/already-drained dir).
   - **Why drain rather than hand over:** `resolve` is idempotent (resolving an already-resolved thread is a server-side no-op), but **`reply` is not** — pointing prgroom at a half-replied legacy PR would double-post. Draining is the clean boundary.
2. **Install Phase 1.** From here every PR is prgroom-native, starting from a fresh `prsession`.
3. **Stragglers.** A legacy PR that must be touched post-cutover: `git revert` Phase 1 temporarily (the rollback path doubles as the escape hatch), finish it on restored legacy tooling, then re-apply.

#### 6.5 Rollback strategy

- **Unit:** the Phase-N git commit(s) in `agents-config`.
- **Triggers (operator judgment; no auto-rollback):** prgroom corrupts/loses `prsession` state; posts a wrong or duplicate reply; resolves a thread that wasn't fixed; the fix agent ships a regression the audit missed; or measured token cost exceeds the skill it replaced (defeats the goal).
- **Mechanism:** `git revert <phase-commit>` → `scripts/install.sh` **without** `--prune` (so reverted scripts redeploy).
- **Why Phase-1 rollback is coherent:** Phase 1 does **not** touch `reply-and-resolve-pr-threads`. Reverting Phase 1 restores `wait-for-pr-comments`, whose Phase-8 hand-off targets the still-present Skill B — a complete legacy chain. prgroom's separate state store is untouched by the revert; the reverted PR re-grooms under legacy from a drained/fresh state.
- **Phase-1 → Phase-2 readiness gate:** ≥3 real PRs groomed end-to-end to `quiesced`/`merged` with no revert and no observed wrong/duplicate replies or bad resolves. Skill B (the rollback anchor) is burned only after the loop is trusted.

#### 6.6 Coexistence during transition

- **Phase 1 window:** `monitor-pr` → prgroom owns the full loop for native PRs; `reply-and-resolve-pr-threads` remains intact, independently invokable, and serves as the dormant rollback anchor. Separate state stores; per-PR exclusivity (a PR is legacy XOR prgroom, never both — guaranteed by drain).
- **Hook coexistence:** `detect-pr-push.sh` keeps firing post-push; its suggestion now names `monitor-pr`, which runs `prgroom run`. The hook transparently drives prgroom with no rework (just the one-line name edit from §6.2). Full hook → cron/autonomous-trigger rework stays deferred to v3.
- **Phase 2 window:** Skill B is gone; prgroom is the sole reply/resolve path.

#### 6.7 Phase → implementation-bead boundary

Per this sub-design's acceptance criteria, the two implementation child beads fileable under the epic:

| Bead | Scope | Depends on |
|---|---|---|
| **Phase 1 impl** | 8 core verbs + `reply`/`resolve`/`resolve-escalated` engine + `run` loop; create `monitor-pr`; delete Skill A prose + scripts; hook + rule repointing | Foundation bead (Store, preconditions, `EscalationSink`, config, Cluster + Fix contracts, verb skeletons); §7 install path |
| **Phase 2 impl** | Delete `reply-and-resolve-pr-threads` + scripts; document standalone verbs + crash-recovery; rule re-repointing | Phase 1 baked (readiness gate, §6.5) |

## Section 7 — Build, distribution, and test discipline

`prgroom` is not a new toolchain — it is a fourth Python package in a repo that already builds, lints, type-checks, and tests three. The entire build/distribution story is therefore *reuse*, and the only genuinely new surface is the test discipline the architecture leans on (the modular-monolith bet from §1: the more orchestration moves out of skill prose and into testable modules, the more we can guard it mechanically). This section settles build, distribution, versioning, CI, and that test discipline.

#### 7.1 Build & distribution

`prgroom` is a `uv`-managed Python package at `packages/prgroom/`, standard `src/prgroom/` layout, a fourth sibling to `installer`, `pdlc`, and `holding-place`. Its `pyproject.toml` mirrors the installer's tool stanzas verbatim (`ruff` line-length 100 / target `py311` / the same `E/W/F/I/B/UP/SIM/S/RET/ARG/PTH/TRY/RUF/N` select set; `mypy` `strict=True` with `warn_unreachable` + `disallow_any_decorated` + the `redundant-expr`/`truthy-bool`/`possibly-undefined` error codes; `coverage` `branch=true`, `source=["src/prgroom"]`).

- **No artifact build, no prebuilt-binary pipeline.** There is no compiled binary to produce, sign, or copy to a host. The package ships as a wheel built with `uv build`; the install host *already has `uv`* (it runs the installer), so there is **no new runtime to ship** and no "scp the binary" step. Distribution is `uv tool install`, not artifact transport.
- **Distribution = a console-script entry point.** `prgroom` is declared as a `[project.scripts]` console-script entry point and installed with `uv tool install ./packages/prgroom`, which places a `prgroom` executable on `PATH`. The entry point matters: it lets every invocation skip the per-call dependency-resolution tax that `uv run prgroom …` pays. On the hot paths — `sweep` (per-PR loop) and `wait` (poll loop) — we call the installed entry point directly; we do **not** prescribe `uv run` there. Cold-start lands around 100–300 ms (a `uv`-installed console script), acceptable for a synchronous CLI invoked at hand-off points, not in a tight inner loop.
- **Dependencies are pinned and thin.** Runtime deps are `typer` + stdlib; GitHub access is a `subprocess.run` shell-out to `gh`, not a vendored API client. The lockfile pins the set; `uv sync --frozen` reproduces it in CI.

#### 7.2 Installer ownership

`scripts/install.sh` (the live installer) owns the `prgroom` install. On install it runs `uv tool install ./packages/prgroom` (idempotent; `--force` on upgrade), guarded by a `uv`-present check, and ensures the `prgroom` console-script is on `PATH`. `install.sh --prune` removes `prgroom` (via `uv tool uninstall`) when the package is dropped from the source tree, consistent with how `--prune` removes other orphaned deploy outputs.

`scripts/install.py` is an early partial port and is **not** authoritative for this — `install.sh` stays the source of truth for the `prgroom` install path until the port catches up. This ownership is a hard prerequisite for migration: §6.1 gates every skill-thinning on `prgroom` being installable first, and "installable" means this `install.sh` path.

#### 7.3 Versioning & release cadence

`prgroom` is an in-repo package versioned in `packages/prgroom/pyproject.toml` (semver). It has **no independent release cadence** — it ships with the repo and upgrades land by re-running the installer, which re-runs `uv tool install --force`. There are **no git tags and no GitHub releases** for the MVP; the repo commit is the version boundary, and the installer is the upgrade mechanism. This is the same lifecycle the `installer` and `pdlc` packages already follow — versioned with the code, not released independently.

#### 7.4 CI

A `ci-prgroom` Makefile target is added, mirroring `ci-installer` one-for-one and wired into the aggregate `make ci`:

| Step | Command (run in `packages/prgroom/`) |
|---|---|
| Lint | `uv run ruff check` |
| Format check | `uv run ruff format --check` |
| Typecheck | `uv run mypy --strict src` |
| Coverage | `uv run pytest --cov --cov-report=term-missing` |
| Audit | `uv sync --frozen && uv run pip-audit` |

`.github/workflows/ci.yml` already provisions `uv` + Python 3.11 for the existing packages, so **no workflow change is needed** beyond invoking the new target from `make ci`. This is the package's mandatory quality gate: as with `packages/installer/`, no change under `packages/prgroom/` merges without `make ci-prgroom` green. Concurrency is **not** a CI concern: there is no race detector and no race-instrumented test run; cross-process correctness is verified by explicit lock tests against the `InMemoryStore` test double (§7.6), not by an instrumented test run.

#### 7.5 Coverage floor

Coverage floor is **`fail_under = 90` (branch) on the package**, enforced via `coverage.py` / `pytest-cov` (`branch = true`, `source = ["src/prgroom"]`) and run as part of `make ci-prgroom`; the build fails when the floor is breached. This matches the sibling `installer` package's gate. Treat the floor as a *minimum behavioral target*, not a quality bar — it is cleared by testing real behavior at the right altitude (§7.6), never by anti-pattern tests written to move the number.

#### 7.6 Test discipline (load-bearing, not aspirational)

Per the design's stated motivation ("the more we push into this modular monolith CLI codebase, the more we can put better unit and integration tests around these functions"), test discipline is a **first-class constraint on the architecture itself**, not a Section-7 afterthought. The shape below is what makes the modular monolith pay off.

- **Interfaces designed FIRST for unit testability.** Every cross-module dependency sits behind a `@runtime_checkable` `Protocol`: `gh`, `git`, `prsession.Store`, the agent dispatcher, the clock, and randomness. `src/prgroom/lifecycle/` reaches for **no** stdlib singleton directly — `datetime.now(UTC)` and any RNG arrive through an injected clock/randomness Protocol, so the quiescence predicate and the poll→cluster→fix→push orchestration are deterministic under test. Concrete adapters (`FileStore`, `InMemoryStore`, the `gh`/`git` wrappers) **structurally satisfy** their Protocol — they do not inherit it; `mypy --strict` checks the structural fit at type-check time, exactly as `pdlc`'s `InMemoryWorkTracker` satisfies `WorkTracker` without subclassing it.
- **Fit-test commitment.** Each module under `src/prgroom/*` ships with a fit-test, `tests/test_<module>_fit.py`, that exercises the module's public surface against minimal **fakes** of its dependencies. A module without a passing fit-test does not merge. (A fitness/integration test maps to `tests/test_*_fit.py` here; golden fixtures map to `tests/fixtures/`.)
- **No mocks of code we own.** Use **fakes** — full, small in-memory implementations — for our own Protocols (`InMemoryStore` for `Store`, a fake `gh`/`git`/clock). **Mock only at the system boundary**: `subprocess`, HTTP, filesystem. For `gh`/`git`/`claude` subprocess shell-outs, inject a fake runner or `monkeypatch` `subprocess.run`; for raw HTTP, use `responses`/`respx`. This is the existing `writing-unit-tests` discipline, stated as architecture: a mock of code we own is a test of our own implementation, not of behavior.
- **Test pyramid.** Broad-to-narrow, matching cost and blast radius:

  | Layer | Scope | Fixtures / boundary | Breadth |
  |---|---|---|---|
  | **Unit** | One module's logic; `pytest`, fast, **no I/O** | Fakes for every Protocol dependency | Broadest |
  | **Integration** | A real slice — real `git`, real `FileStore` JSON adapter | Fixture repos under `tests/fixtures/` | Narrower |
  | **End-to-end** | Full verb / `run` loop | Recorded `gh` API responses (`responses`/`respx`); `pytest-xdist` for parallelism | Narrowest |

- **Exhaustiveness, recovered without a compiler.** Python has no compile-time exhaustiveness check over a `StrEnum`. Where a verb dispatches on `PRPhase`, `DispositionKind`, or `ReviewerStatus`, we `match` on the enum with an explicit `case _:` arm that raises (`AssertionError`/`ValueError`), and we back it with `mypy --strict` plus a unit test that enumerates every member of the enum. The triple — closed `match`, type-checker, member-enumeration test — recovers the safety the compiler would have given, and a newly added enum member that no arm handles fails that test loudly rather than silently falling through.
- **Error-path coverage is explicit, not incidental.** The error model is exception-based, so the tests assert on raises: `read()` raising `StateNotFoundError` when no state exists; the CLI catching `PreconditionError` and formatting the 4-line stderr block with the right registry code; the `lock()` context manager releasing in its `finally` even when the wrapped verb raises (no leaked lock — there is no manual release to forget). Terminal-no-work is asserted as a normal exit-0 return, *not* as an exception, so the success-with-nothing-to-do path is pinned distinctly from the failure paths.

## Section 8 — PR memory management

Across re-review rounds the `fix` agent runs with fresh context each time (each dispatch is a new subprocess; see §5). It needs to remember decisions from earlier passes — "we already declined this with rationale X", "we adopted pattern Y PR-wide", "this cluster was deferred to follow-up bead Z" — or it re-litigates closed disagreements and regresses prior decisions.

### 8.0 Premise — the PR *is* the memory

The PR itself is the durable, portable contextual memory: its **description**, **labels**, and **comment/review threads**. Any agent, in any harness, at any time can read a PR — so memory written *to the PR* is universally accessible, while anything kept only in prgroom's private state is invisible to everyone outside this toolset.

This yields the load-bearing split:

- **Portability lives on the *write* side.** Memory worth carrying forward is routed *to the PR*, not into a private store. prgroom's `prsession` state (§2) is a faithful **read-replica** of the PR plus prgroom's own bookkeeping — not a competing source of truth.
- **The *read* mechanism is an internal optimization.** The fix agent reads a prgroom-provided snapshot (§8.1), not live `gh`. The snapshot is a copy of the same public PR; it does not fork the memory.

Memory classification follows the project's five-class taxonomy — UNIVERSAL / PROJECT / PLANNED / HISTORICAL / CONTEXTUAL. **PR-grooming memory is almost always CONTEXTUAL** (relevant to work in flight). The general taxonomy, its routing rule, and the four non-CONTEXTUAL homes are a separate, repo-wide concern owned by `agents-config-abn9.23.4`; this section designs only the CONTEXTUAL→PR slice and the forward-compatible seam to the rest.

### 8.1 Read path — prior memory reaches the fix agent

Before each `fix` dispatch, prgroom assembles a **complete PR snapshot** and writes it to the files the fix contract already passes (`pr_detail_path`, `branch_state_path`; see §5). The snapshot is guaranteed to contain:

- PR **description** (including the `## Decisions` block prgroom maintains — §8.3)
- PR **labels**
- **Every** review thread with its **full reply-chain** (not just the latest comment)
- **Prior-round dispositions** for every already-processed item — `disposition.kind`, `rationale`, `commits`, `decided_by` — sourced from `prsession` state (§2), which already persists them across rounds (§3.2 rule 6)
- The per-item **`recurrence`** signal (§8.2)

**Capture timing:** the snapshot is taken **immediately before fix dispatch**, not at top-of-cycle `poll`, to minimise the staleness window to roughly the fix duration.

**The fix agent does not call `gh`.** This is a locked §5 premise, and the reasons are load-bearing, not incidental:

1. **Runtime swappability** — the contract must run on `claude -p`, `codex exec`, `opencode run`, or a local `ollama` model. Requiring live `gh` would force every runtime to carry `gh` + auth + network.
2. **Auth blast radius** — the agent subprocess never holds GitHub credentials.
3. **Centralised rate-limiting** — one actuator (prgroom) means one place to back off; N agents calling `gh` freely is how a `sweep` gets throttled.
4. **Reproducibility** — "fix = pure function of input files → output JSON" is what makes a fix replayable and testable.

A change to the PR *during* a long fix run is caught by the next cycle's `poll`; the lifecycle is convergent (§3), so it self-heals without live reads. A future prgroom-mediated mid-run refresh is possible but explicitly out of MVP scope.

### 8.2 Recurrence signal — deterministic, prgroom-owned

"The prior fix was inadequate" has three forms, separable by *who can detect them*. Only the first is deterministic, and prgroom owns it:

| Case | Detection | Owner |
|---|---|---|
| Same thread reopened ("you said fixed, reviewer says still broken") | Deterministic — prgroom holds disposition history + thread state | **prgroom** computes, fix agent interprets |
| Fix too narrow ("the pattern recurs in other files") | Judgment, proactive | RCA pass (`agents-config-p53nm`) |
| Fix caused new problems ("your commit broke Y") | Judgment, reactive, causal | fix agent / RCA |

prgroom **computes** a deterministic **`recurrence`** value for each item carrying a prior disposition and includes it in the snapshot fed to the fix agent (§8.1). It is **derived from `prsession` disposition history at snapshot-assembly time — not a persisted state field** (derived data is not stored, so §2's `ReviewItem`/`Disposition` schema is unchanged):

```python
@dataclass(frozen=True, slots=True)
class Recurrence:
    reopened: bool                  # a prior disposition exists AND a new reviewer reply arrived on the same thread
    attempt_count: int              # how many times this item has been dispositioned (1 = first pass)
    prior_disposition: str          # the most recent prior DispositionKind value
    prior_commits: list[str]        # SHAs from the most recent prior disposition  # omitted from JSON when empty
    first_seen_round: int           # round the item was first observed
```

prgroom **detects; it does not interpret.** The fix agent reads `recurrence` and decides how to respond — widen the sweep, rethink the approach, reaffirm the prior decision, or escalate. That interpretation is the producer's judgment (**MVP Option A**: the fix agent self-interprets; the RCA pass `agents-config-p53nm` is an *optional* enrichment, not a load-bearing dependency). `recurrence` is the primary new input that pass will consume if/when it lands.

### 8.3 Write path — new memory routes to the PR

**The fix agent never writes the PR.** Consistent with §5's produce/publish split, the agent *declares* memory in its contract output; **prgroom is the sole actuator** of every outward-facing write (push, reply, resolve, label, and now PR-body edits). This preserves prgroom's crash-safety guarantee (every outward effect is gated by state it controls; recovery = re-invoke) and keeps formatting deterministic regardless of which runtime produced the words.

The fix contract output gains a classified **`memory`** channel (§5), each entry tagged with one taxonomy class. **MVP routes only `CONTEXTUAL`, and only to the PR**, two ways:

1. **Thread reply** — a CONTEXTUAL note tied to a specific review thread rides out on that thread via the existing `reply` verb. No new mechanism.
2. **`## Decisions` block in the PR body** — a CONTEXTUAL note *not* tied to a single thread (a PR-wide decision) is recorded in a prgroom-maintained `## Decisions` section, written by a `gh` **PATCH of the PR description** (an API edit, **not** a git commit). This runs at the same point as the `reply` verb.

**`## Decisions` block format and idempotency.** prgroom owns the block between sentinel markers and rewrites it wholesale each time (read-modify-write the PR body), so re-runs never duplicate entries — the sentinels make the operation naturally idempotent without a state flag:

```markdown
<!-- prgroom:decisions:start -->
## Decisions
- **[r1] Result<T> error pattern** — adopted PR-wide for handlers (item #c1). _decided_by: claude -p opus[1m]_
- **[r1] Declined rename AuthMiddleware→AuthHandler** — "Middleware" suffix denotes pipeline composition (item #a). _decided_by: claude -p opus[1m]_
<!-- prgroom:decisions:end -->
```

Each entry carries the round it was decided, a title, a one-line rationale, the deciding agent, and the source item, and is **keyed by `(round, source-item)`**; merging skips a key that already exists, so a crash-and-re-run of the same round never double-appends. Entries accumulate across rounds within the block; prgroom never deletes a prior decision (the block is the cross-round decision ledger any future reader — ours or foreign — sees in the snapshot at §8.1).

**Non-CONTEXTUAL classes are accepted-but-deferred.** UNIVERSAL / PROJECT / PLANNED / HISTORICAL entries pass schema validation (§8.6) and are logged as deferred; routing them to their homes (`~/.claude/memories/`, `AGENTS.md`, the work adapter, `docs/adr/`) is `agents-config-abn9.23.4`'s job, on this same channel. MVP does not route them.

### 8.4 `memory_dir` — ephemeral within-run scratch

`memory_dir` is retained from the carved-out skeleton hook, but its role is now narrow: an **ephemeral scratchpad for the fix orchestrator's own internal sub-agents** within a single run (e.g. notes an internal `quality-reviewer` leaves for an internal `simplify`). It is **not** cross-round memory — cross-round memory is the PR + dispositions (§8.1). `memory_writes` (paths the agent wrote in `memory_dir`) is retained solely for containment auditing (§8.6).

### 8.5 Contract deltas (owned by §5)

- **Fix input** (§5): complete-snapshot guarantee (§8.1); per-item `recurrence` (§8.2); `memory_dir` (scratch only).
- **Fix output** (§5): keep `memory_writes` (scratch paths); **add** the classified `memory` channel — `[{ "content" | "path", "classification", "target_hint" }]`, where `target_hint` is an optional thread node-id for CONTEXTUAL thread-replies.

### 8.6 Audit semantics

- **`memory_dir` containment** — every `memory_writes` path must resolve inside `memory_dir`. A path that escapes (absolute, or `..` traversal) is a **hard violation**: the offending cluster's items flip to `disposition.kind = failed` with `rationale = "memory containment violation: <path>"`, an `EscalationSink` event is emitted, and the end-of-cycle resolver promotes to `human-gated` (§3.2 priority 2). This is security-relevant — the agent writing outside its sandbox — so it is never soft-failed.
- **Classification enum** — each `memory` entry's `classification` must be one of the five classes; an unknown (or empty) value is a `CONTRACT_AUDIT_FAILED` audit failure for that memory entry.
- **Exactly one of content|path** — a `memory` entry must set exactly one of `content` or `path`; neither-or-both is a `CONTRACT_AUDIT_FAILED` audit failure for that entry.
- **CONTEXTUAL routability** — a CONTEXTUAL entry with a `target_hint` must reference a real thread in the snapshot; an unknown hint is a `CONTRACT_AUDIT_FAILED` audit failure for that entry. A thread-less CONTEXTUAL entry routes to the `## Decisions` block.
- **Soft vs. hard severity** — a `memory` entry carries no `gh_id`; it is PR/cluster-wide bookkeeping, not a review item. So the per-entry classification, content|path, and unknown-`target_hint` failures above are **soft `Severity.WARN`** breaches: they are surfaced as escalations but do **not** flip any review-item disposition and do **not** trigger `git stash`. The fix commits are valid; only the memory bookkeeping is malformed. The **only** hard cluster-flipping memory breach is `memory_dir` containment (`Severity.BLOCK`); orphan commits (§5) are the other hard cluster-flipping breach.
- **Non-CONTEXTUAL** — accepted, logged as deferred, **not** an error (forward-compat with `agents-config-abn9.23.4`).
- **Declared-but-missing path** — a `memory_writes` path the agent declared but never wrote is a soft warning (stderr), not a cluster failure: the fix work already happened; this is bookkeeping drift, not a breach.

### 8.7 Worked example — a 3-round PR

**Round 1.** Copilot files three items. The fix agent disposes: item *a* (rename `AuthMiddleware`) → `wont_fix` ("suffix denotes pipeline semantics"); item *b* (missing null check) → `fixed` (commit `b1`); item *c* (ad-hoc error handling) → `fixed` (commit `c1`, adopting a `Result<T>` pattern). It declares two CONTEXTUAL `memory` entries: the `Result<T>` adoption and the rename rationale — both thread-less PR-wide decisions. prgroom posts thread replies, PATCHes the `## Decisions` block with both `[r1]` entries, and pushes `b1`,`c1`.

**Round 2.** Copilot reopens thread *a* ("still think the rename is clearer") and files new item *d* (another handler with ad-hoc error handling). prgroom computes `recurrence` for *a*: `{reopened: true, attempt_count: 2, prior_disposition: "wont_fix", first_seen_round: 1}`. The snapshot to the fix agent now includes the `## Decisions` block, thread *a*'s full chain, and the recurrence flag. The agent: reaffirms *a* → `wont_fix`, citing the recorded rationale **without re-litigating**; disposes *d* → `fixed` (commit `d1`), applying the **same `Result<T>` pattern from the Decisions block** so the fix is consistent with round 1. prgroom appends nothing new to Decisions (no new PR-wide decision), replies, resolves, pushes `d1`.

**Round 3.** Copilot files item *e* questioning the `Result<T>` choice ("why not exceptions here?"). The snapshot carries the `## Decisions` block, so the agent sees the round-1 PR-wide decision. It disposes *e* → `wont_fix`, pointing to the established decision — or, if it judges the reviewer has a genuinely new point, `escalated`. Either way the round-1 memory **prevented a silent regression and a re-litigation**: the decision survived two fresh-context agent dispatches because it lived in the PR, not in the agent's vanished context.

### 8.8 Out of scope / explicitly dropped

- **5-class routing for non-CONTEXTUAL memory** → `agents-config-abn9.23.4` (same `memory` channel, extended router).
- **RCA interpretation of `recurrence`, and any forced post-round-1 analysis** → `agents-config-p53nm`.
- **Resumable agent session capture / retrospection harvest** → `agents-config-9xj1f` (reserve `{runtime, session_id}` in the §5 dispatch/audit record when §5 is implemented).
- **Dropped, do not build:** a `_memory_route` verb, file frontmatter parsing, ADR-writing from prgroom, and any mechanical "route memories" git commit. These solved the general-routing problem, which is `abn9.23.4`'s, not prgroom's.
- **Compaction / pruning** of the `## Decisions` block and **cross-PR memory** remain deferred; revisit only if block growth becomes a real problem.

---

## Risks & open questions

1. **CLI becomes a new god-node.** Mitigation: internal modularity (each `src/prgroom/*` submodule is its own module with its own tests). Discipline-required, not automatic. Reinforced by the test-discipline commitment in Section 7.
2. **Cold-start latency.** Python via a `uv`-installed console-script entry point ~100–300ms; acceptable but not free. Cron-fired invocations every 60s could add up. May favor longer cadences (5–15min) for autonomous mode.
3. **gh API rate limits.** A `sweep` over many open PRs could hit them. Need backoff strategy.
4. **bd adapter (v2) is coupling-heavy.** Stuffing JSON into bead notes is workable but ugly. Alternative: bead description for metadata, separate file for items. Defer to v2.
5. **Concurrency UX.** Lock-out is correct but may surprise users; need clear error messaging (covered by precondition-gating contract).

## Deferred to later versions

- **`detect-pr-push.sh` hook → cron/autonomous-trigger rework.** Replacing the post-push hook with a cron/autonomous trigger (or pointing it directly at `prgroom run` rather than at a skill) is deferred to v3+. (The Phase-1 cutover itself already renames the hook's suggestion string to `monitor-pr` — see §6.2.)
- **Auto-detection of in-flight PRs at cutover.** No migration tool. (See Section 6.)
- **Parallel `fix` subagents.** Serial in MVP; file-overlap prediction is unsolved.
- **`bd` adapter for `prsession.Store`.** File-only in MVP.
