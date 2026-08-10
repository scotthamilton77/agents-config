# prgroom CLI — Design Reference

> **Up**: [index](index.md)
> **Subsystem**: prgroom — the PR-grooming CLI
> **Role**: the evergreen, consolidated design — amended in place as the design evolves
> **Companion artifacts**: none in this repository. The C4, sequence, state-machine, data and deployment views that once rendered this design were retired to the `scotthamilton77/agents-config-ARCHIVE` repository, where they keep their original paths under `docs/architecture/prgroom/`. They describe a subsystem substantially larger than the one being kept — read them as history, never as a contract.
> **Historical proposals**: the dated proposals that seeded this design are in the same archive repository under `docs/plans/` and `docs/specs/`; this document is the living source of truth.

This is the high-level design reference for the prgroom CLI. It is **lean by intent** — data structures and contracts are shown; procedural code is not.

**Scope warning.** prgroom is being carved down, not finished, and two different fates are in play. The `verify` gate and its convergence loop, and `sweep`, are design-of-record for a system that will not be built at all. The reply/poll/wait/snapshot machinery described below is a different case: it is built and wired into the CLI today, but charter D13 marks it for deletion rather than completion (the in-package fix-dispatch loop moves to the work-loop instead — the repo-level `grind`/`executor` pipeline charter D14 nominates for that role). Where this document and `packages/prgroom/src/` disagree about what exists, the code is the authority.

## Contents

1. Architecture overview
2. `prsession.Store` interface + state schema
3. Lifecycle state machine — phases, pipeline, the two retry caps, error registry
4. Quiescence model
5. Agent dispatch (named contracts)
6. The verify gate (trust-but-verify)
7. PR memory management

---

## 1. Architecture overview

### Problem & goal

`prgroom` is a Python CLI that took over from the `wait-for-pr-comments` and `reply-and-resolve-pr-threads` skills, both of which were retired. The gh/git/JSON work is already mechanical, but the **phase-orchestration glue** — walking phase logic, dispatching subagents, auditing their reports, managing crash recovery — still loads on top of an implementer's already-bloated context every cycle. `prgroom` moves that orchestration out of agent prose and into deterministic code, confining agent invocations to *named hand-off points* (comment classification, fix implementation, escalation judgment), each shelled out as a fresh agent context. State lives behind a `prsession.Store` interface so recovery, idempotency, and inspection are uniform across every caller.

### Non-goals (MVP)

- Create-PR and merge — no installed skill drives either; both are manual, with merge governed only by the always-on hard line against unauthorized merges
- Worktree cleanup — covered by the `post-merge-cleanup` skill, the `/clean-up-git` command, and the `gitclean` CLI they drive
- Changes to the upstream brainstorming and implementation workflows
- Executable-bead primitive (separate sub-design; blocks on this MVP)
- bd adapter for state (file-only in MVP)

### Package & usage patterns

`prgroom` is a `uv`-managed package at `packages/prgroom/` with the standard `src/prgroom/` layout: a `typer` CLI root, `gh`/`git` subprocess wrappers, a `prsession.Store` Protocol (file adapter default), an `agent` shell-out layer, and a `lifecycle` package that runs the pipeline and owns the quiescence predicate. The CLI shells out to `claude -p` / `codex exec` / `opencode run` synchronously for each agent hand-off.

**Three usage patterns:**

| Pattern | Caller | Invocation |
|---|---|---|
| **Interactive** | User in chat, invoking the CLI directly | `prgroom run <pr> --interactive` |
| **Autonomous** | Cron / `/loop` / GHA | `prgroom run <pr> --autonomous`, or `prgroom sweep <repo>` (design-of-record only; not a registered command) |
| **Executable-bead** (v2) | bd-side dispatcher | bead payload `prgroom run <n> --autonomous` |

The `monitor-pr` skill that used to drive the interactive pattern was retired, and nothing replaced it. Nothing invokes `prgroom` today — no deployed asset and no harness path — so all three rows describe a designed surface rather than a running one; `packages/prgroom/AGENTS.md` states the package's current standing.

**Locked decisions:**

- **Language:** Python 3.11+, reusing the repo's existing toolchain (`ruff`, `mypy --strict`, `pytest` + coverage, `pip-audit`) verbatim. The state model uses `Protocol` (structural interfaces, `mypy --strict`-checked rather than inherited) and `StrEnum` (self-documenting, JSON-serializable values) throughout.
- **CLI framework:** `typer` (type-hint-driven, pairs with `mypy --strict`).
- **Placement:** `packages/prgroom/`, one of the packages under `packages/`.
- **Distribution:** there is no compiled binary and no artifact-transport step. The project installer owns the install — its CLI-deploy stage runs `uv tool install` against `packages/prgroom/`, which places the `prgroom` console-script on `PATH` and records it in the install receipt. The version lives in `packages/prgroom/pyproject.toml` and ships with the repo; there is no independent release cadence, no tags, and no GitHub releases.
- **Agent boundary:** synchronous subprocess shell-out; each invocation is fresh context. The runtime is designed to be chosen per-contract in TOML config — the contract is the API, the runtime is swappable — but no verb resolves a per-repo `.prgroom.toml` path yet (§§4.3/6.3), so today every invocation runs the shipped default chain.
- **Scope:** equivalent of `wait-for-pr-comments` + `reply-and-resolve-pr-threads`; excludes create-PR, merge, cleanup, and bead-lifecycle helpers.

**Precondition gating (cross-cutting):** Every verb checks preconditions before doing work. Direct invocation is terminal on a missing precondition today — e.g. `fix` with no state exits `PRECONDITION_NO_STATE` (exit 2) rather than auto-running `poll`/`cluster` — and *terminal-no-work* (preconditions met but nothing to do — exit `0` as success) is the other built outcome. A third tier, *self-healable* (a verb auto-running its own missing prework, gated by a per-verb `--no-prework` flag), is design-of-record only: no direct verb registers that flag, and `run`'s own `--no-prework` is an accepted-but-no-op parity stub — the aggregate always orchestrates its own prework by running the whole pipeline (§3.3) rather than self-healing a single verb's precondition. Non-terminal-no-work failures emit a structured stderr error (what / why / how / machine-readable code) while stdout stays reserved for verb output so agents can parse each independently. The error-code registry is owned by §3.6.

### MVP verb set

The table below is the MVP verb set (§1); all but `sweep` are user-facing subcommands today — `sweep`'s row states its design-of-record, unregistered status. `cap-guard` is a built **internal pre-push pipeline step** (a `VerbStep` threaded by `run`), not an exposed subcommand. `verify` is designed as a second internal step (§3.4/§6) but is not built into the pipeline — see §3.3 for the built order of record.

| Verb | Role |
|---|---|
| `poll <pr>` | Query gh for new comments, reviews, and CI status; update state. Short-circuits if SHA unchanged. |
| `cluster <pr>` | Group unprocessed items into cohesive fix-bundles. Cheap agent; no per-item disposition here. |
| `fix <pr>` | Per cluster, dispatch a stronger fix agent that decides each item's disposition (fixed / already_addressed / skipped / deferred / wont_fix / escalated / failed) and implements warranted fixes. |
| `push <pr>` | Push commits the fix agent produced. |
| `rereview <pr>` | Re-request review from required bot reviewers (the remove/add dance). |
| `reply <pr>` | Render and post replies for every item per the template matrix + agent-authored response files. |
| `resolve <pr>` | GraphQL `resolveReviewThread` for every thread whose disposition is `fixed` or `already_addressed`. |
| `resolve-escalated <pr> <item-id> --as <disposition> [--rationale <text>]` | Human reclassification of an `escalated` item to a terminal disposition, letting the lifecycle continue. |
| `wait <pr>` | Sleep/poll until SHA changes or the quiescence threshold trips. |
| `status <pr>` | Print current state for inspection. |
| `run <pr>` | Orchestrate the pipeline (§3.3) iterating to quiescence or until the PR-review retry budget is exhausted. |
| `sweep <repo>` | Cross-PR autonomous mode: list open PRs and `run` each serially with per-PR locks, failure-isolated. Design-of-record only — not a registered command; charter D13 forbids building it. |

---

## 2. `prsession.Store` interface + state schema

### `prsession.Store` interface

A per-PR typed key-value store **with locking** — deliberately **not** a tracker: no change-detection, no event emission, no compare-and-swap predicates. It persists one PR's grooming session as a single replaceable blob; callers do their own read-modify-write under an exclusive lock. (Contrast with PDLC's `WorkTracker`, a different shape entirely.)

```python
@dataclass(frozen=True, slots=True)
class PRRef:
    owner: str
    repo: str
    number: int

@runtime_checkable
class Store(Protocol):
    def read(self, ref: PRRef) -> PRGroomingState: ...
    def write(self, ref: PRRef, state: PRGroomingState) -> None: ...
    def lock(self, ref: PRRef) -> AbstractContextManager[None]: ...
    def list_refs(self) -> list[PRRef]: ...
    def delete(self, ref: PRRef) -> None: ...
```

`read` raises `StateNotFoundError` when no state exists yet; `write` is atomic full-state replacement; `lock` grants an exclusive lock for one verb's work, release guaranteed by the context manager; `list_refs` powers `sweep`; `delete` tombstones after merge or abandon.

### Adapters

| Adapter | When | Storage |
|---|---|---|
| `file` | default | `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`); `flock` lock, temp-file + atomic `os.replace` |
| `memory` | tests only | in-process `dict[PRRef, PRGroomingState]`, per-ref `threading.Lock` |
| `bd` | v2 (deferred) | linked bead's `notes` field, externalized to a file above ~65KB |

Selected via `--store` (default `file`) or `PRGROOM_STORE`.

### State schema (`schema_version: 1`)

The CLI owns the schema. Phases describe what the **PR is waiting on**, not what the CLI is doing; verbs are activities performed within or across a phase.

```python
@dataclass(slots=True)
class PRGroomingState:
    pr: PRRef
    phase: PRPhase
    pr_review_retries_used: int
    last_polled_at: datetime
    last_activity_at: datetime
    quiescence: QuiescenceState
    schema_version: int = SCHEMA_VERSION
    last_poll_sha: str = ""
    last_pushed_head_sha: str = ""
    last_rereviewed_sha: str = ""            # resumable-rereview markers (§3.3 rereview)
    last_review_invalidated_sha: str = ""
    human_review_label_added: bool = False
    reviewers: dict[str, ReviewerState] = field(default_factory=dict)
    items: list[ReviewItem] = field(default_factory=list)
    last_error: str | None = None
    lifecycle_escalation_filed: bool = False
    pending_memory: list[RoutedMemory] = field(default_factory=list)  # durable memory queue, drained by _reply (§7.3)

class PRPhase(StrEnum):
    IDLE = "idle"
    AWAITING_REVIEW = "awaiting-review"
    FIXES_PENDING = "fixes-pending"
    QUIESCED = "quiesced"
    HUMAN_GATED = "human-gated"
    MERGED = "merged"
```

`pending_memory` (the durable CONTEXTUAL-memory queue, §7.3) and the two resumable-rereview SHA markers are **additive, omit-when-empty** — old state files load empty defaults, so `schema_version` stays `1`.

`awaiting-initial-review` and `awaiting-rereview` collapse into one `awaiting-review`; `pr_review_retries_used` (0-indexed) disambiguates initial from re-review iterations (see §3.5 — The two retry caps). Any phase may transition to `human-gated` on an `escalated` disposition (interactive / no-autodefer), an exhausted PR-review retry budget (§3.5), or an irrecoverable fix-agent audit failure. `quiesced` is a terminal that does **not** require human action — it is auto-merge-eligible when policy (CI/coverage) is satisfied; `human-gated` is terminal-requiring-human. `human-gated` exits to `fixes-pending` or `merged`.

```python
@dataclass(slots=True)
class ReviewItem:
    kind: ItemKind
    identity: Identity
    author: str
    body_excerpt: str
    seen_at: datetime
    cluster_id: str = ""
    disposition: Disposition | None = None
    replied: bool = False
    own_reply_id: int = 0
    resolved: bool = False
    duplicate_of_gh_id: str = ""

class DispositionKind(StrEnum):
    FIXED = "fixed"
    ALREADY_ADDRESSED = "already_addressed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"
    WONT_FIX = "wont_fix"
    ESCALATED = "escalated"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class Disposition:
    kind: DispositionKind
    decided_at: datetime
    decided_by: str
    rationale: str = ""
    commits: list[str] = field(default_factory=list)
    response_path: str | None = None
    gate: GateStrength | None = None      # None until `fix` disposes the item; §6.2 defines GateStrength
    escalation_filed: bool = False
```

One `ReviewItem` per reviewer-produced item across three kinds (`review_thread`, `review_summary`, `issue_comment`), discriminated by `kind` with kind-specific identity in `Identity`. `disposition` is `None` until the fix verb processes the item — the cluster verb does not classify; the fix agent decides the disposition when it does (or declines) the work.

```python
@dataclass(slots=True)
class ReviewerState:
    identity: str
    kind: ReviewerKind
    status: ReviewerStatus
    required: bool
    last_request_at: datetime
    last_review_at: datetime | None = None
    declined_at: datetime | None = None
    declined_reason: str | None = None
```

A PR has 0..N reviewers tracked in `reviewers: dict[str, ReviewerState]` keyed by identity (gh login or bot id), allowing arbitrary cardinality without schema churn. `required=True` gates quiescence (the PR cannot quiesce until that reviewer's status ∈ {`review_found`, `declined`}); §4 consumes this flag. In MVP the dict holds exactly one entry — Copilot, `required=True`.

```python
@dataclass(frozen=True, slots=True)
class QuiescenceState:
    ci_state: str = ""
    quiesced_at: datetime | None = None
```

### Transactional model

Every public verb is a thin locking wrapper: it acquires the per-PR lock via `lock()`, calls a lock-assuming `_`-prefixed internal that does the read-modify-write, and releases on the context manager's `finally`. Two exceptions: `run` acquires the lock once and threads multiple internals in sequence (§3.3), avoiding nested acquisition; `status` (§3.2) is unlocked by default — a single `store.read` that may observe a stale-but-internally-consistent snapshot under a concurrent write — with `--locked` opt-in for a strictly-consistent read.

### Concurrency posture

One invocation at a time per PR; a second concurrent invocation exits non-zero reporting the holding pid. No queue, no acquire timeout — the caller (cron, agent) retries on its next cadence. Crash between `lock()` and `write()` releases the process-scoped lock and leaves the last successful `write()` on disk: no partial states, no recovery flag — recovery is re-invocation.

### Schema deliberately omits

No `crash_recovery` block (replaced by `phase` + `last_error` + lock semantics), no separate `copilot_review_submitted_at` (folded into a reviewer's `last_review_at`), no pre-rendered reply body (rendered at `reply` time), and no `partial`/`complete` write state — every write is complete.

---

## 3. Lifecycle state machine

The lifecycle is a six-phase state machine. Verbs drive transitions; `run` (§3.3) threads the whole cycle. The pipeline within an active cycle is **cluster → fix → cap-guard → push → reply → resolve → rereview** (§3.3); a `verify` step between `fix` and the cap-guard is design-of-record only (§3.4/§6), not built.

### 3.1 Phase state graph

`PRPhase` has six members:

```
idle | awaiting-review | fixes-pending | quiesced | human-gated | merged
```

A PR starts in `idle` on first invocation. `poll` advances it to `awaiting-review` once the first push lands, and to `fixes-pending` when a reviewer item appears. Within `fixes-pending` the cycle does its work; at end-of-cycle the phase resolves to `awaiting-review` (commits pushed), `quiesced` (no commits, quiescence trips), or `human-gated` (a gate trips). Every non-terminal phase transitions to `merged` when `poll` observes the PR closed via merge.

**Terminal-for-CLI:** `quiesced`, `human-gated`, `merged`. The CLI takes no further autonomous action in these phases. **Re-enters the loop:** both `quiesced` and `human-gated` can return to `fixes-pending` — on new reviewer activity, an operator `resolve-escalated`, or (for a budget-gated PR) a raised PR-review retry budget; an external push also re-enters the loop from either phase, landing at `awaiting-review` from `quiesced` and at `fixes-pending` from `human-gated` (§3.2 `poll` row). **Graph-terminal:** `merged` only (absorbing).

The transition matrix in §3.2 carries the same edges in table form.

### 3.2 Phase × verb transition matrix

Each cell gives the next phase and side effects for `(verb, current phase)` on **direct** invocation. Self-heal (a verb auto-running its own missing prework, gated by `--no-prework`) is design-of-record only (§1) — no direct verb has that flag today, so every precondition cell below is the actual, unconditional outcome, not a `--no-prework`-gated one; **no-op** means exit 0, no state change. `run` (§3.3) orchestrates the whole pipeline itself and never exercises these per-verb preconditions.

The matrix covers the 11 per-PR verbs. The cross-PR `sweep` aggregator iterates open PRs serially and invokes `run` per PR with isolated per-PR failures; it has no phase semantics of its own.

| Verb | `idle` | `awaiting-review` | `fixes-pending` | `quiesced` | `human-gated` | `merged` |
|------|--------|-------------------|-----------------|------------|---------------|----------|
| `poll` | first push → `awaiting-review`; reviewer item → `fixes-pending`; PR-closed → `merged`; else no-op | reviewer item → `fixes-pending`; PR-closed → `merged`; external push → `pr_review_retries_used++` if SHA changed, stay; else no-op | new item → stay (appended); PR-closed → `merged`; external push → `pr_review_retries_used++` if SHA changed, stay; else no-op | new item → `fixes-pending`; PR-closed → `merged`; external push → `awaiting-review` (`pr_review_retries_used++`); else no-op | new item → `fixes-pending`; PR-closed → `merged`; external push → `fixes-pending` (`pr_review_retries_used++`); else no-op | terminal; no-op |
| `cluster` | `PRECONDITION_NO_ITEMS` | `PRECONDITION_NO_ITEMS` | sets `cluster_id` on unclustered items; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `fix` | `PRECONDITION_NO_CLUSTERS` | `PRECONDITION_NO_CLUSTERS` | sets per-item `disposition.kind`; may produce commits; no phase change (resolved at end-of-cycle); audit failures flip the item to `FAILED` → `human-gated` | terminal; no-op | terminal; no-op | terminal; no-op |
| `push` | `PRECONDITION_NO_COMMITS` | uploads queued commits; `pr_review_retries_used++` if ≥1 pushed; no phase change | uploads queued commits; `pr_review_retries_used++` if ≥1 pushed; no phase change | terminal; no-op | terminal; no-op | terminal; no-op |
| `reply` | no-op (no items yet) | no-op unless replies pending (`PRECONDITION_NO_UNREPLIED` is registered but never raised — no `--no-prework` flag exists for `reply`) | posts replies; marks `replied`; no phase change | re-applies idempotently | re-applies idempotently | terminal; no-op |
| `resolve` | no-op (no items yet) | no-op (`PRECONDITION_NO_UNRESOLVED` is registered but never raised — no `--no-prework` flag exists for `resolve`) | resolves threads for `FIXED`/`ALREADY_ADDRESSED` items; marks `resolved`; no phase change | re-applies idempotently | re-applies idempotently | terminal; no-op |
| `rereview` | `PRECONDITION_NO_ITEMS` | re-requests review for required reviewers in `{not_requested, declined}`; no-op exit 0 if none match; no phase change | runs after a successful push for the same reviewers; no phase change | re-requests if reviewer state stale | re-applies idempotently | terminal; no-op |
| `wait` | sleeps; returns on `_wait` contract break (phase change, quiescence, signal-cancel) | sleeps; returns on `_wait` contract break; PR-review budget NOT checked here (§3.5) | `PRECONDITION_WAIT_NOT_APPLICABLE` (exit 2) — actionable work exists; use `run` | sleeps; returns on contract break (usually → `fixes-pending`/`merged`) | sleeps; returns on contract break (usually → out) | terminal; no-op |
| `resolve-escalated` | `PRECONDITION_NO_ESCALATIONS` | `PRECONDITION_NO_ESCALATIONS` | flips one item from `escalated` to a terminal disposition; phase unchanged | `PRECONDITION_NO_ESCALATIONS` | flips one item; clears only the `escalated` gate. → `fixes-pending` iff no `escalated` items remain, no `failed` items, and `last_error ∉ BlockingErrorCodes`; else stays `human-gated`. Does NOT clear `LIFECYCLE_PR_REVIEW_EXHAUSTED` (needs budget raise + re-run), `STATE_CORRUPT`, or `failed`-items gating | terminal; no-op |
| `status` | read-only (lock-free; `--locked` opt-in) | read-only | read-only | read-only | read-only | read-only |
| `run` | lifecycle loop (§3.3) | lifecycle loop (§3.3) | lifecycle loop (§3.3) | `_poll` once for external transitions; re-enter loop if phase advances out, else return 0 | `_poll` once for external resolutions, then re-evaluate the budget: if `last_error == LIFECYCLE_PR_REVIEW_EXHAUSTED` and the raised `--pr-review-retries` budget no longer trips, clear it → `fixes-pending`; re-enter loop if phase advances out, else return 0. (The fix↔verify sibling — `LIFECYCLE_FIX_VERIFY_EXHAUSTED` / `--fix-verify-retries` — is design-of-record only, §3.4; neither exists to re-arm.) | returns 0 (absorbing) |

`BlockingErrorCodes` = { `LIFECYCLE_PR_REVIEW_EXHAUSTED`, `STATE_CORRUPT`, `STATE_SCHEMA_UNKNOWN`, `RUNTIME_GH_TERMINAL`, `RUNTIME_GIT_TERMINAL`, `RUNTIME_PUSH_REJECTED` } — conditions outside `resolve-escalated`'s scope, recoverable only via §3.6.

**End-of-cycle phase resolution** (applied by `run` from `fixes-pending`; first match wins):

1. PR-review retry budget would be exceeded by the next push → `human-gated`, `last_error = LIFECYCLE_PR_REVIEW_EXHAUSTED` (the pre-push refusal detail is in §3.5).
2. Any item `disposition.kind == FAILED` (audit, runtime-terminal, or agent non-convergence) → `human-gated`. `last_error` preserved for runtime-terminal-user failures; left unset for audit/agent failures (per-item `rationale` is the cause).
3. Any unresolved `disposition.kind == ESCALATED` → `human-gated`; file one deduped `EscalationSink` event per cycle.
4. ≥1 commit pushed this cycle → `awaiting-review` (`rereview` already invoked in-cycle for required bot reviewers).
5. No commits pushed AND quiescence trips (§4) → `quiesced`.
6. Otherwise → `awaiting-review`: every item dispositioned to `skipped`/`wont_fix`/`deferred` (zero commits) and quiescence has not yet judged the PR ready. Dispositioned items persist and are skipped idempotently next cycle.

### 3.3 The `run` pipeline

`run` is the aggregate verb: it acquires the per-PR lock **once** and threads the lock-assuming internals in sequence (§2's transactional model) rather than re-locking per verb. From `fixes-pending` it drives one **cycle** through the pipeline; `lifecycle/run.py::_build_pipeline` is the built order of record:

```
cluster → fix → cap-guard → push → reply → resolve → rereview
```

Each step is a `VerbStep` run in order; a step with no work no-ops (`push` when there are no queued commits). `cap-guard` can **refuse the push** by flipping `phase = HUMAN_GATED` when the PR-review retry budget is spent (§3.5). A post-step terminal check inspects `phase` after each step; on `human-gated` it breaks the pipeline before the remaining steps run, and the loop-top flushes the `EscalationSink` event + the `human-review-required` label (§4.6). `rereview` runs **last** and guarded: only required bot reviewers needing a fresh review are re-requested, and only after a successful push.

A `verify` step between `fix` and `cap-guard` — and the cap-guard-after-verify ordering that would imply — is design-of-record only (§3.4/§6); it is not part of the pipeline above.

The cycle repeats; end-of-cycle resolution (§3.2) yields the next phase. On a terminal phase (`quiesced` / `human-gated` / `merged`) `run` returns; on `awaiting-review` it blocks in `_wait` (§4.2) until reviewer activity or quiescence breaks the wait, then loops.

**Entry-probe.** When `run` is invoked while already at a terminal phase (`quiesced` / `human-gated`), it runs `poll` once before deciding whether to re-enter the cycle — the **entry-probe** (`lifecycle/run.py::_entry_probe`) — to catch an external merge or push that already cleared the gate. From `human-gated` specifically, it also re-checks whether a raised `--pr-review-retries` budget (§3.5) no longer trips and, if so, clears the gate and advances to `fixes-pending` for the refused commits to push; the inner fix↔verify cap's entry-probe re-arm (§3.5) is part of the same unbuilt convergence loop (§3.4).

### 3.4 The fix↔verify convergence loop

The heart of the fix↔verify subsystem. Within one `fixes-pending` cycle, after `fix` produces commits + dispositions (and its `verify_checklist` claim, §5), the `verify` step runs the mechanical gate (§6). The re-fix-or-escalate decision is made **after** verify produces a verdict:

- **Green gate** → fall through to `cap-guard` → `push`.
- **Red gate, inner retries remain** → write the gate output to a temp file, dispatch a whole-branch **repair** fix (fed the temp file, in `fix-repair` mode), re-audit (orphan/sha with repair-attribution), and re-run the gate. Loop.
- **Red gate, inner retries exhausted** → `phase = HUMAN_GATED`, `last_error = LIFECYCLE_FIX_VERIFY_EXHAUSTED`.

The loop is bounded by `fix_verify_retries` (§3.5), independent of the PR-review retry budget because a verify-fail never pushes. Like the fix step's per-cluster fan-out, the convergence loop is **internal to one cycle** — not a state-machine transition; the only state edge it produces is the exhaustion → `human-gated`. The repair dispatch (§5) is whole-branch, not per-cluster. None of this convergence loop is built: there is no `verify` field on `PRGroomingState`, no `verify` pipeline step, and no `LIFECYCLE_FIX_VERIFY_EXHAUSTED` code.

### 3.5 The two retry caps

Both are designed as **retry caps** that, on exhaustion, escalate to `human-gated` and surface a blocking `LIFECYCLE_*_EXHAUSTED` code. Only the outer, PR-review cap is built; the inner, fix↔verify cap is design-of-record only (§3.4) — no counter, no exhaustion code, and no re-arm path exist for it today. They bound orthogonal loops.

| | **Inner — fix↔verify loop** *(design-of-record only, §3.4 — not built)* | **Outer — PR-review loop** |
|---|---|---|
| Bounds | repair re-fixes within one cycle (no push between) | review-eliciting pushes across cycles |
| Knob | `fix_verify_retries` | `pr_review_retries` |
| Default | **2** (⇒ max 3 `opus[1m]` fix spends/cycle) | **5** (initial push + 5 fix-pushes = 6 pushes) |
| Counter | none — not built | `pr_review_retries_used`, 0-indexed |
| Exhaustion code | `LIFECYCLE_FIX_VERIFY_EXHAUSTED` — not a registered `ErrorCode` | `LIFECYCLE_PR_REVIEW_EXHAUSTED` |
| Tier / exit | `LIFECYCLE_CAP` / 0 (graceful terminal) | `LIFECYCLE_CAP` / 0 (graceful terminal) |
| Re-arm | none — no `--fix-verify-retries` flag or entry-probe exists | raise `--pr-review-retries` (entry-probe) or `poll` |

**At the outer boundary:** a *verified-good* batch is still escalated when `pr_review_retries` is spent — the outer cap bounds review *iteration*, not mechanical quality (a green push still elicits another review that may surface fresh comments). The inner cap governs mechanical convergence; the outer governs how many review rounds run before a human confirms. The cap is checked **pre-push**, so the budget-tripping push is refused, not uploaded.

### 3.6 Failure tiers & error-code registry

Section 1's three-tier precondition gating extends into runtime errors. Every verb failure classifies into a tier that fixes its exit code, whether the phase gates to `human-gated`, and whether an `EscalationSink` event fires.

| Tier | Exit | Phase → | Escalation | Caller behaviour |
|------|------|---------|------------|------------------|
| `PRECONDITION_USER_ERROR` | 2 | — | no | abort; fix the invocation |
| `PRECONDITION_NO_WORK` | 0 | — | no | proceed (success no-op) |
| `PRECONDITION_LOCK_HELD` | 75 | — | no | another invocation holds the lock; retry on cadence |
| `RUNTIME_TRANSIENT` | 75 | — | no | scheduler retries on next cadence |
| `RUNTIME_TERMINAL_USER` | 77 | human-gated | yes | abort; operator resolves |
| `RUNTIME_CANCELLED` | 130 / 143 | — | no | non-retryable; operator decides |
| `CONTRACT_AUDIT_FAILED` | 65 | human-gated (via resolver) | yes | item → `FAILED`; run continues, resolver gates |
| `STATE_CORRUPT` | 78 | human-gated | yes | abort; operator inspects state file |
| `LIFECYCLE_CAP` | 0 | human-gated | yes | graceful terminal; resolve and/or raise a retry budget, re-run |

`RUNTIME_TRANSIENT` retries are budgeted **per logical API call** (3 attempts: initial + 2 retries; exponential back-off 1s/4s, honouring `Retry-After`); after the third the verb exits 75 and the scheduler drives long-horizon retry.

Codes are stable `<CATEGORY>_<SPECIFIC>` identifiers, each carrying `what`/`why`/`how` per §1's structured-stderr contract. Adding a code is non-breaking; renaming/repurposing is breaking.

| Category | Codes (representative) | Tier / exit |
|----------|------------------------|-------------|
| `PRECONDITION_*` user-error | `NO_PR_DETECTED`, `NO_AUTH`, `REPO_UNREACHABLE`, `BAD_PR_REF`, `WRONG_BRANCH` | user-error / 2 |
| `PRECONDITION_NO_*` no-work (enumerated) | `NO_ITEMS`, `NO_CLUSTERS`, `NO_COMMITS`, `NO_UNREPLIED`, `NO_UNRESOLVED`, `NO_ESCALATIONS` | no-work / 0 (2 under `--no-prework`) |
| `PRECONDITION_NO_VERIFY_CONFIG` | tier's verify command unconfigured (§6.3) | user-error / 2 |
| `PRECONDITION_LOCK_HELD` | live-process lock contention | transient-equiv / 75 |
| `RUNTIME_*` | `GH_TRANSIENT`, `GH_TERMINAL`, `GRAPHQL_FAILED`, `PUSH_REJECTED`, `GIT_TRANSIENT`, `AGENT_UNAVAILABLE`, `AGENT_TIMEOUT`, `CANCELLED_{SIGINT,SIGTERM}` | tagged per code (75 / 77 / 130 / 143) |
| `CONTRACT_*` | `CLUSTER_MALFORMED`, `CLUSTER_COVERAGE`, `FIX_MALFORMED`, `FIX_ORPHAN_COMMIT`, `FIX_UNREACHABLE_SHA`, `FIX_AUDIT_FAILED` | audit / 65 |
| `STATE_*` | `STATE_CORRUPT`, `STATE_SCHEMA_UNKNOWN` | state / 78 |
| `LIFECYCLE_*` | `LIFECYCLE_FIX_VERIFY_EXHAUSTED`, `LIFECYCLE_PR_REVIEW_EXHAUSTED` | cap / 0 (graceful) |

**`PRECONDITION_WRONG_BRANCH` guards the one irreversible mutation.** `push` uploads the local PR-branch HEAD, so an ambient checkout on another branch — or a detached HEAD, which reads as the literal `HEAD` — would publish the wrong commits. The check runs before the queued-commit read rather than trusting the working tree, and it refuses rather than correcting: the operator checks out the PR head branch, or runs from its worktree, and re-invokes.

`flock(2)` auto-releases on process death, so there is no stale-lock code; live contention surfaces as `PRECONDITION_LOCK_HELD`. The `BlockingErrorCodes` set (§3.2) is not cleared by `resolve-escalated` alone — each member needs its own recovery (a retry-budget raise for the `LIFECYCLE_*` caps, state inspection for `STATE_*`, manual reconciliation for the terminal `RUNTIME_*`).

---

## 4. Quiescence model

Section 4 owns the **quiescence predicate** (when end-of-cycle resolution transitions `awaiting-review` → `quiesced`), the **`_wait` blocking-loop internals**, a **human-review merge constraint** that does NOT block the lifecycle, the **auto-merge eligibility contract** surfaced by `prgroom status --json`, and the **auto-request-human-review** behaviour that adds a GitHub label on lifecycle gating.

Quiescence uses **hard gates plus an idle timer**, not a tunable probability score. Operators reading `prgroom status` get a named failing gate as the answer to "why didn't it quiesce?"

### 4.1 Quiescence predicate — hard gates + idle timer

`_wait` evaluates the predicate on every poll. It is satisfied iff **all hard gates pass AND the idle timer has elapsed**. Gates are binary and operator-debuggable; `status` names the failing gate.

| Gate | Condition |
|------|-----------|
| `G_REVIEWERS` | Every `required` reviewer is `REVIEW_FOUND` or `DECLINED` |
| `G_CI` | `quiescence.ci_state in {success, absent}` for `last_pushed_head_sha` |
| `G_DISPOSITIONS` | Every item has a non-null disposition (structurally guaranteed by `fix` over every clustered item per the cycle contract) |
| `G_NO_BLOCKERS` | No item disposition is `ESCALATED` or `FAILED` (cascade routes those to `human-gated` first) |

**Idle timer:** `now - last_activity_at >= idle_threshold`, where `last_activity_at` is the timestamp of the most-recent PR-side mutation observed by `_poll` (comment, review, push, CI change, label change). It is a short final settle-buffer for a slow human mid-draft, not a bot-inactivity detector — per-reviewer timeouts own that.

**Reviewer `DECLINED` substates** (all gate-satisfying; `declined_reason` preserved for `status` inspection): `user-declined` (human explicitly passed), `timeout-no-start` (requested but never engaged, per `review_start_timeout`), `timeout-stalled` (engaged but never produced a terminal review, per `review_finish_timeout`).

**Engagement detection** (sets `last_review_at`): any actor-attributed activity by the reviewer identity after `last_request_at` and after the latest push — a top-level comment, a review in any state, an inline review comment, or a thread reply. First such activity flips the reviewer to `IN_PROGRESS`; subsequent activity refreshes both `last_review_at` and `last_activity_at`.

End-of-cycle resolution places quiescence at **priority 5** (after blocker gates 1–3 and the commit-pushed rule at 4). When the predicate holds, phase becomes `QUIESCED` and `quiescence.quiesced_at` is stamped; otherwise phase stays `awaiting-review` for the next `_wait` to re-evaluate.

### 4.2 `_wait` internals

The public `wait(pr)` verb is a locking wrapper (`with store.lock(pr): _wait(...)`); `_wait` assumes the per-ref lock is already held and holds it continuously for the entire invocation (no mid-sleep release, guaranteed by the `lock()` context manager's `finally`). The lock-free `status` carve-out lets operators query during long waits without contending.

Each loop iteration honours the cancel token, then performs an **interruptible sleep** (`Event.wait(poll_interval)`) that wakes early if the token is set, then polls. `_poll` mutates state: it updates `last_activity_at`, evaluates reviewer timeouts, and refreshes `quiescence.ci_state` for `last_pushed_head_sha`.

The wait exits on exactly these triggers:

| Trigger | Phase on exit | Error tier |
|---------|---------------|------------|
| Signal-cancel (SIGINT/SIGTERM sets the cancel token) | unchanged | `RUNTIME_CANCELLED` (130/143) — not retried |
| `_poll` transient error (past gh retry budget) | unchanged | `RUNTIME_TRANSIENT` (75) — scheduler retries |
| `_poll` terminal error (gh auth expired, etc.) | `human-gated` | `RUNTIME_TERMINAL_USER` (77) |
| Phase moved off `awaiting-review`/`idle` (fix commits arrived, external push, merged externally, escalation produced) | as observed | normal return |
| Quiescence predicate satisfied | `quiesced` (writes `quiesced_at`) | normal return |

**No hard wait-timeout in MVP.** The design relies on per-reviewer timeouts for bot silence, the `human-review-required` label as the operator merge-block, and signal-cancel as the manual bail-out; a fourth timeout exit would race the others without covering a distinct failure mode.

**Resumability:** all timestamps are stored as absolute UTC; timeout *deadlines* are derived per-evaluation, never frozen. On crash mid-wait the kernel releases the `flock(2)` lock on fd-close; the scheduler re-invokes `run`, state reloads with timestamps intact, and the first `_poll` re-evaluates deadlines against current time — elapsed cross-crash time counts, so a stalled reviewer auto-declines exactly as if the process had never died. The same property means a mid-flight config change (e.g. raising `review_start_timeout`) takes effect on the next evaluation; operator intent always wins.

### 4.3 Configuration surface

`PrgroomConfig.load` (`config.py`) resolves each knob below with precedence **CLI-flag parameter > env var > per-repo `.prgroom.toml` `[quiescence]` table > built-in default** — implemented and unit-tested at the loader. Durations parse `30s`/`10m`/`1h30m` syntax. (The `[verify]` table is owned by §6.3, which notes the same gap below.)

**Not yet wired to the CLI:** no `prgroom` verb exposes a flag for any of the five settings below, and no verb passes `load()` a `repo_config` path — every production call site in `cli.py` takes the `None` default, so `.prgroom.toml` is never actually read outside tests. `pr_review_retries` is the one config knob with a real CLI flag today (`run --pr-review-retries`, §3.5) — a separate top-level TOML key, not part of the `[quiescence]` table below.

| Setting | Default | Env var | TOML key (`[quiescence]`) |
|---------|---------|---------|----------|
| `idle_threshold` | `10m` | `PRGROOM_IDLE_THRESHOLD` | `idle_threshold` |
| `poll_interval` | `30s` | `PRGROOM_POLL_INTERVAL` | `poll_interval` |
| `review_start_timeout` | `3m` | `PRGROOM_REVIEW_START_TIMEOUT` | `review_start_timeout` |
| `review_finish_timeout` | `15m` | `PRGROOM_REVIEW_FINISH_TIMEOUT` | `review_finish_timeout` |
| `auto_request_human_review` | `true` | `PRGROOM_AUTO_REQUEST_HUMAN_REVIEW` | `auto_request_human_review` |

### 4.4 Human-review merge constraint (NOT a lifecycle blocker)

The PR label `human-review-required` is a **merge** constraint, not a lifecycle one: the full cycle (§3.3) runs normally and quiescence still trips when gates pass. The label affects only `auto_merge_eligible` (§4.5). It is satisfied (OR) by a `human-approved` label or a non-bot PR review with `state == APPROVED` — the bot-filter is load-bearing so Copilot's self-PR auto-approval cannot satisfy it. Both constraint and satisfaction are derived per-status-query from already-fetched state, never persisted.

### 4.5 Auto-merge eligibility contract

The actual merge gate and policy overlay are owned by future beads; §4 defines only what `prgroom status <pr> --json` exposes so they have a stable contract. A PR is auto-merge-eligible iff all four gates hold:

| Gate | Condition |
|------|-----------|
| `phase_is_quiesced` | `phase == QUIESCED` |
| `last_error_clear` | `last_error` is unset/empty |
| `no_blocker_items` | no item disposition is `ESCALATED` or `FAILED` |
| `human_review_satisfied` | label `human-review-required` absent, OR satisfied per §4.4 |

The status JSON also surfaces `human_review.candidates_seen` (each examined PR-approval with its bot-filter outcome) for debuggability — "why didn't approval X count?" Adding fields is non-breaking; removing/renaming requires a version-bumped envelope.

#### The envelope

This is the shape a consumer may rely on. It is assembled per-query from `PRGroomingState` plus a live gh enrichment for the label and approval state; the four `merge_gates` bools and `auto_merge_eligible` are derived at query time and never persisted.

```json
{
  "pr": 42,
  "phase": "quiesced",
  "last_error": "",
  "pr_review_retries_used": 1,
  "reviewers": [
    {"login": "github-copilot[bot]", "required": true, "is_bot": true, "status": "review_found", "declined_reason": ""}
  ],
  "ci_state": "success",
  "items_summary": {"fixed": 3, "already_addressed": 1, "wont_fix": 0, "escalated": 0, "failed": 0, "skipped": 0, "deferred": 0},
  "items": [
    {
      "kind": "review_summary",
      "gh_id": "3141592653",
      "thread_id": "",
      "author": "github-copilot[bot]",
      "disposition": {"kind": "skipped", "decided_at": "2026-05-25T14:40:02Z", "decided_by": "claude sonnet"},
      "replied": true,
      "resolved": false,
      "posted_reply_ids": ["4875007359"]
    }
  ],
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
    "candidates_seen": [{"login": "alice", "approved": true, "counted": false, "reason": "bot"}]
  },
  "auto_merge_eligible": false
}
```

Four properties of the envelope are load-bearing rather than incidental:

- **`items[]` is a deliberate projection, not a state dump.** `body_excerpt`, `rationale`, `commits`, `response_path`, `gate`, `escalation_filed` and the cluster bookkeeping stay private to the store. `disposition` is `null` for an untriaged item and otherwise carries exactly `kind`, `decided_at`, `decided_by`.
- **`gh_id` and `posted_reply_ids` are strings.** A consumer matching them against live GitHub ids must coerce GitHub's numeric ids to string first. `posted_reply_ids` is a list even though one reply per item is the current storage shape, so a future multi-reply change stays non-breaking.
- **`reviewers[]` is sorted by login** so the output is deterministic and diffable.
- **`no_blocker_items` screens the same disposition set the quiescence predicate uses** (§4.1), never a parallel notion of "blocker".

`author` on an item is informational and must never be used as an exclusion key. `quiesced_at` is the empty string when the PR has not quiesced.

### 4.6 Auto-request human review on lifecycle gating

When `_run` reaches `human-gated` for a reason that warrants human review, prgroom adds the `human-review-required` label, complementing the `EscalationSink` event with a GitHub-visible marker. Triggers (any one): `last_error == LIFECYCLE_PR_REVIEW_EXHAUSTED` (outer PR-review budget — §3.5) or `last_error == LIFECYCLE_FIX_VERIFY_EXHAUSTED` (inner fix↔verify budget — §3.4) — the two sibling caps gate identically, and §3.3 flushes the label on either `human-gated` break — or any item disposition of `ESCALATED` or `FAILED`. Explicit non-triggers are infra/state failures (`RUNTIME_GH_TERMINAL`, `RUNTIME_GIT_TERMINAL`, `STATE_CORRUPT`, `STATE_SCHEMA_UNKNOWN`, `RUNTIME_PUSH_REJECTED`) — those are not review problems.

The add is idempotent and best-effort: gated by `auto_request_human_review`, deduped by `human_review_label_added`, label-add failures log a stderr warning without tier-tagging, blocking, or propagating. The dedup flag resets on the same condition that clears `last_error` (successful end-of-cycle resolution to any phase but `human-gated`), so a recurring gate re-adds the label. An operator who manually removes the label while the flag is still set is respected — prgroom does not re-add until the reset path fires AND the gate recurs. When later satisfied via §4.4, the `human-review-required` label persists as historical record ("constraint raised AND satisfied") rather than being removed.

---

## 5. Agent dispatch (named contracts)

The cheap agent groups well but decides intent poorly; the heavy agent decides intent well because it sees the whole picture. Two agent contracts split along that line, plus one human-initiated verb:

- **Cluster** (cheap agent) — groups related items into fix-bundles; does NOT decide disposition.
- **Fix** (heavy orchestrator) — per cluster, decides each item's disposition AND implements the work where warranted; inherits full PR context, prior PR memories, and access to skills/sub-agents.
- **Resolve-escalated** (human-initiated verb) — flips an `escalated` disposition to a terminal one so the lifecycle resumes.

### Cluster contract — `cluster` verb

Cheap grouping of unprocessed review items (`cluster_id == ""`) into fix-bundles. Grouping is non-decisional, so a locally-runnable model suffices. Default provider chain: local `ollama` (Gemma-class small classifier) if installed → `claude -p` model `haiku` / effort `high` → `codex` model `gpt-5.6-luna`.

```
Input:  { contract_version, pr{owner,repo,number},
          items[ReviewItem], pr_context_path, memory_path }
Output: { clusters[ { cluster_id, item_gh_ids[], rationale } ] }
```

Audit guards: every input item in exactly one cluster; cluster ids unique; rationale non-empty. On second failure, fall back to per-item degenerate clusters so `fix` can still proceed.

### Fix contract — `fix` verb

Runs once per cluster (serial). Default provider: `claude -p` model `opus[1m]` effort `xhigh` — an **orchestrator** that chooses its own skills/sub-agents (model/effort for those are the orchestrator's, not prgroom's). The CLI does all gh-API legwork up front and dumps it to files; the agent never re-calls gh (runtime swappability, auth containment, rate-limit centralisation, reproducibility — see §7.1).

```
FixInput:  { contract_version, pr{owner,repo,number}, cluster_id,
             item_gh_ids[], items[ReviewItem],          # prior-disposition items carry a `recurrence` object (§7.2)
             pr_detail_path, branch_state_path,
             memory_dir, response_outbox_dir }
```

```
FixOutput: { contract_version, items[ItemDisposition],
             memory_writes[path],                        # ephemeral scratch, containment-audited (§7.4/§7.6)
             memory[MemoryEntry] }                       # classified; MVP routes CONTEXTUAL→PR only (§7.3)

Disposition = fixed | already_addressed | skipped | deferred | wont_fix | escalated | failed

ItemDisposition: { gh_id,
                   disposition: Disposition,
                   commit_shas[sha],                     # required for fixed + already_addressed
                   response_path,                        # optional; verbatim reply text for the reply verb
                   rationale,                            # required for skipped|deferred|wont_fix|escalated|failed
                   recommended_gate: full | lite,        # required for fixed; selects the verify tier (§6)
                   verify_checklist: [...] }             # design-of-record only (§6) — not a field on the built FixItemResult
```

Audit guards (CLI-side): `fixed` commits fall between pre-cluster SHA and post-cluster HEAD (≥1 each); `already_addressed` commits predate the baseline yet are reachable; the rationale-bearing dispositions carry non-empty rationale; and every commit on the branch is claimed by some item (orphan check). Violations re-classify the item to `failed` and emit an escalation via `EscalationSink`; orphan commits are stash-isolated for inspection.

**Armed for self-verification.** The fix agent is launched top-level (`claude -p`, not a nested sub-agent), so it can safely orchestrate — the await-own-child footgun does not apply. Its allow-list broadens from the muzzled `Read Edit Write Bash(git *)` to the full implementation set (broad `Bash`, `Task`, `Skill`, …), governed by a configurable allow/deny aggregation layer, so it can run the repo's completion gate (tests/build/lint) and spawn sub-agents. In the unbuilt verify design (§6) it would emit a **required** `verify_checklist` in `FixOutput` — what it ran and the result — as the agent's *claim*, confirmed by prgroom's `verify` step (trust-but-verify); neither side is built today. *Security:* a headless `--permission-mode dontAsk` broad-shell agent running on a branch whose threads carry attacker-authored text is a prompt-injection surface — mitigated by operator-trusted worktrees and operator opt-in, documented as an accepted residual risk.

**Repair dispatch.** When the `verify` gate is red and inner retries remain (§3.4), prgroom re-invokes the fix agent in **repair** mode — whole-branch (a gate failure is a property of the branch, not one cluster's), fed the gate output via an optional `verify_failure_path` input and a `fix-repair` prompt. Its orphan/sha audit attributes the repair's new commits to the verify-repair batch, not to any review item.

### Resolve-escalated — `resolve-escalated` verb

Human-initiated reclassification of one item (a CLI verb, not an agent shell-out): takes `<gh-id>`, replaces its disposition, sets `decided_by = "human:<git-user>"`; the lifecycle resumes on the next `run`/`wait`/`reply`. A verb (not an interactive prompt) is debuggable, scriptable, and undo-able.

### EscalationSink

Escalation routing is abstracted so the CLI works with or without beads — it never calls `bd label add` directly from contract code:

```python
@dataclass(frozen=True, slots=True)
class Escalation:
    pr: PRRef
    reason: str
    severity: Severity            # info | warn | block
    item: ReviewItem | None = None

@runtime_checkable
class Sink(Protocol):
    def emit(self, escalation: Escalation) -> None: ...
```

| Sink | When | Behavior | Built? |
|---|---|---|---|
| **stderr** | Default (interactive) | Pretty-print to stderr | Yes — the only sink `_build_sink` returns |
| **file** | intended `--escalation-file <path>` | Append one JSON line per escalation; for watchers/cron | Class implemented, **no flag selects it** |
| **bd** | intended `--bd-bead <id>` / `PRGROOM_BD_BEAD` | Add `human` label + append notes | No — deferred to v2, no code |

Adapter selection is unbuilt: the CLI always constructs the stderr sink. Treat the file and bd rows as design intent, not as an operator-reachable surface.

**The file sink's wire format** is one JSON line per event, flat and public-safe by construction — it carries the triggering item's id but never its body, rationale, or disposition detail:

```json
{"pr": "scotthamilton77/agents-config#42", "reason": "item PRRT_kgABC456 dispositioned escalated", "severity": "block", "item_gh_id": "PRRT_kgABC456"}
```

`pr` is the `<owner>/<repo>#<number>` shorthand, not an object. `item_gh_id` is present only when an item triggered the event.

**Severity** is a three-value vocabulary (`info` / `warn` / `block`). The lifecycle hook files `block` both for a per-item `escalated`/`failed` disposition and for a set `last_error`; the agent-side audit layer defaults to `warn` and reserves `block` for orphan commits and memory-containment breaches.

**Emission is best-effort and dedup-safe, in that order.** A dedup flag — `escalation_filed` per item, `lifecycle_escalation_filed` per gate — is set *only after* the emit returns successfully, and the state is written immediately after. So a sink that raises is swallowed (and logged, so a persistently unreachable sink is visible rather than silent), the flag stays unset, and the next pass retries. Lifecycle progression never blocks on sink reachability. A crash between a successful emit and the state write may double-fire on the next invocation; sinks absorb that on the receiving end.

### Verb → contract → CLI action

| Verb / step | Agent contract | CLI does (deterministic) |
|---|---|---|
| `poll` | none | gh API (comments, reviews, CI); update state |
| `cluster` | Cluster | persist `cluster_id` per item |
| `fix` | Fix | dump gh detail; serial dispatch; per-subagent audit; orphan check; stash-isolate on fail |
| `verify` *(internal step — design-of-record only, §3.4, not built)* | none | mechanical re-check of fix output (see §6) |
| `cap-guard` *(internal step)* | none | check the PR-review retry budget; refuse the push and flip `phase = HUMAN_GATED` if spent (§3.3/§3.5) |
| `push` | none | `git push` accumulated commits |
| `rereview` | none | reviewer remove/add dance to coerce a fresh `review_requested` |
| `reply` | none | render templates + `response_path` files; post via gh |
| `resolve` | none | GraphQL `resolveReviewThread` for fixed/already_addressed `review_thread` items |
| `resolve-escalated` | none | human-initiated single-item reclassification |
| `wait` | none | sleep + re-poll; quiescence may transition phase |
| `run` | Cluster + Fix chained | full lifecycle loop (§3.3) |

### Contract is the API, runtime is swappable (per-contract TOML)

Each contract is a stable, versioned (`contract_version`) interface; the runtime behind it is designed to be selected per-contract in TOML, so `claude -p` / `codex exec` / `opencode run` / `ollama`, models, and fallback chains would swap without touching lifecycle code.

```toml
[agents.cluster]
primary   = { cli = "ollama", model = "gemma4" }
fallback  = { cli = "claude", model = "haiku", effort = "high" }
fallback2 = { cli = "codex",  model = "gpt-5.6-luna" }

[agents.fix]
primary   = { cli = "claude", model = "opus[1m]", effort = "xhigh", write = true }
fallback  = { cli = "codex",  model = "gpt-5.6-terra", write = true }
```

**Not yet wired to the CLI:** the table above matches the shipped default chain (`agent/dispatcher.py::_DEFAULT_CHAINS`) exactly, but no verb resolves a `repo_config` path — both dispatcher builders in `cli.py` call `load_chain(..., repo_config=None, ...)` unconditionally — so a `[agents.cluster]`/`[agents.fix]` override in a real `.prgroom.toml` is never read; every invocation runs the default chain shown.

Fallback triggers: primary not on PATH, quota/auth/network exit, or per-contract timeout. If both primary and fallback fail, the verb emits `failed` for affected items and escalates via `EscalationSink`. The PR-review retry budget governs how many full loops `run` may attempt (§3.5). Per-contract prompts live in `agent/prompts/<contract>.tmpl` (overridable via `PRGROOM_PROMPTS_DIR`); per-contract token usage is logged to `$XDG_STATE_HOME/prgroom/usage.jsonl` as MVP baseline-capture only.

---

## 6. The verify gate (trust-but-verify)

The `fix → push` seam needs a gate of record between the fix agent (which can introduce new defects it should have caught) and the push that elicits another review round. prgroom's verifier is a **mechanical command gate** — it runs the repo's tests/build/lint via `proc.CommandRunner`, NOT an agent review. Agent self-review is what the *fix agent* does to itself (its `verify_checklist` claim, §5); prgroom's gate is the independent, deterministic confirmation. The two compose as **trust-but-verify**: the agent's claim is a forcing function (the contract compels it to gate itself) plus an evidence trail; the mechanical run is authoritative and decides any divergence (agent claimed green, gate is red → the gate wins, and it drives the auto-re-fix loop). The claim is *not* byte-compared against the mechanical result.

### 6.1 Mechanical gate of record

A `verify` `VerbStep` sits between `fix` and `cap-guard` in the pipeline (§3.3). It **no-ops when there are no queued fix commits** (mirrors `push`'s degenerate no-op). When there are commits it runs the operator-configured tier command, **whole-branch**, in the worktree:

- **Green** → fall through to `cap-guard` → `push`.
- **Red** → drive the bounded convergence loop (§3.4): repair-dispatch + re-gate, bounded by `fix_verify_retries`; on exhaustion, refuse the push by setting `phase = HUMAN_GATED` + `LIFECYCLE_FIX_VERIFY_EXHAUSTED` — the **identical** refusal mechanism as `cap-guard` (§3.3). Effectful failures inside the step (a `CommandRunner` error, an agent-CLI failure) raise a tagged error through the shared error site like any verb.

Push is all-or-nothing (`git push HEAD:branch`) and the resolver already gates the whole PR on any one `FAILED` item, so verification is whole-branch with a single tier — no per-item push partitioning.

### 6.2 Tier selection, `GateStrength`, and the verdict

`recommended_gate` is per-item, but the gate runs once for the branch at the **strongest** tier across the clean `FIXED` items (any `full` ⇒ `full`, else `lite`):

```python
class GateStrength(StrEnum):
    FULL = "full"
    LITE = "lite"
```

`Disposition.gate` is typed/validated against `GateStrength`; a `FIXED` item whose `gate` is absent or not a valid `GateStrength` is a `CONTRACT_FIX_AUDIT_FAILED` (the item flips to `FAILED`) — this makes `recommended_gate` load-bearing.

The verify verdict would be persisted at **batch level** on `PRGroomingState` (not per-item — `FAILED` drops the gate field, and verification is whole-branch):

```python
@dataclass(frozen=True, slots=True)
class VerifyVerdict:
    result: str            # "passed" | "failed"
    tier: GateStrength     # the gate strength actually run
    retries_used: int      # repair re-fixes consumed this cycle
    gate_output_ref: str   # path/excerpt of the last gate output (status + escalation)
    decided_at: datetime   # UTC
```

Design-of-record only: none of this is built. `PRGroomingState` (`prsession/state.py`) has no `verify` field and `prgroom status --json` has no `verify` block. If built, the addition would follow the additive, omit-when-`None` pattern the built `pending_memory` field already uses — `verify: VerifyVerdict | None` on `PRGroomingState`, an additive `verify` block (`result` / `tier` / `retries_used` / `last_error`) on the status envelope, `schema_version` unchanged — but today `last_error` is the only place an exhaustion code surfaces.

### 6.3 Configuration surface

A `[verify]` table in the per-repo `.prgroom.toml` (precedence **flag > env > TOML > built-in default**):

```toml
[verify]
lite               = "make lint"   # command (or list) run for the lite tier
full               = "make ci"     # command (or list) run for the full tier
fix_verify_retries = 2             # inner retry budget
```

The verify **commands have no built-in default**. Because the needed tier is known only after `fix` selects the strongest `GateStrength`, the precondition is **fail-fast**: `run`/`fix` entry asserts that **both** the `lite` and `full` commands are configured, and the absence of either is a **hard stop** (`PRECONDITION_NO_VERIFY_CONFIG`, exit 2, structured what/why/how) — caught before the expensive fix run, never silently skipped. (Auto-detection is deferred to a `--doctor` bead.) `fix_verify_retries` defaults to `2`; `--fix-verify-retries` / `PRGROOM_FIX_VERIFY_RETRIES` override. **Not yet wired to the CLI:** `repo_config` — the repo-root `.prgroom.toml` — is currently always passed `None`, so this table is never actually read (same gap as §4.3/§5).

---

## 7. PR memory management

Across re-review retries the `fix` agent runs with fresh context each dispatch (a new subprocess; see §5). Without recall of earlier passes — "we already declined this with rationale X", "we adopted pattern Y PR-wide", "this cluster was deferred to bead Z" — it re-litigates closed disagreements and regresses prior decisions.

### 7.0 Premise — the PR *is* the memory

The PR itself is the durable, portable memory: its **description**, **labels**, and **comment/review threads**. Any agent in any harness can read a PR, so memory written *to the PR* is universally accessible; anything kept only in prgroom's private state is invisible to everyone outside this toolset. Two consequences:

- **Portability lives on the *write* side.** Memory worth carrying forward routes *to the PR*, not a private store. prgroom's `prsession` state (§2) is a faithful **read-replica** of the PR plus prgroom's bookkeeping — not a competing source of truth.
- **The *read* mechanism is an internal optimization.** The fix agent reads a prgroom-provided snapshot of that same public PR; it does not fork the memory.

Memory classification follows the project's five-class taxonomy (UNIVERSAL / PROJECT / PLANNED / HISTORICAL / CONTEXTUAL). **PR-grooming memory is almost always CONTEXTUAL.** This section designs only the CONTEXTUAL→PR slice; the repo-wide taxonomy and the four non-CONTEXTUAL homes are a separate concern.

### 7.1 Read path — prior memory reaches the fix agent

Before each `fix` dispatch, prgroom assembles a **complete PR snapshot** into the files the fix contract already passes (`pr_detail_path`, `branch_state_path`; §5). It is guaranteed to contain:

- PR **description** (including the `## Decisions` block prgroom maintains — §7.3) and **labels**
- **Every** review thread with its **full reply-chain** (not just the latest comment)
- **Prior-retry dispositions** for every processed item — `disposition.kind`, `rationale`, `commits`, `decided_by` — sourced from `prsession` state (§2), which already persists them across retries
- The per-item **`recurrence`** signal (§7.2)

The snapshot is captured **immediately before fix dispatch** (not at top-of-cycle `poll`) to bound the staleness window to roughly the fix duration. **The fix agent never calls `gh`** (a locked §5 premise; see the four reasons there). A PR change *during* a long fix run is caught by the next cycle's `poll`; the lifecycle is convergent (§3) and self-heals.

### 7.2 Recurrence signal — deterministic, prgroom-owned

"The prior fix was inadequate" has three forms, separated by *who can detect them*. Only the first is deterministic, and prgroom owns it:

| Case | Detection | Owner |
|---|---|---|
| Same thread reopened ("you said fixed, reviewer says still broken") | Deterministic — prgroom holds disposition history + thread state | **prgroom** computes, fix agent interprets |
| Fix too narrow ("the pattern recurs in other files") | Judgment, proactive | optional root-cause-analysis (RCA) pass |
| Fix caused new problems ("your commit broke Y") | Judgment, reactive, causal | fix agent / RCA |

prgroom **computes** a deterministic `recurrence` value for each item carrying a prior disposition and includes it in the snapshot. It is **derived from `prsession` disposition history at snapshot-assembly time — not a persisted field** (so §2's schema is unchanged):

```python
@dataclass(frozen=True, slots=True)
class Recurrence:
    reopened: bool
    attempt_count: int
    prior_disposition: str
    prior_commits: list[str]
    first_seen_retry: int
```

prgroom **detects; it does not interpret.** The fix agent reads `recurrence` and decides how to respond — widen the sweep, rethink, reaffirm, or escalate. MVP Option A: the fix agent self-interprets; an RCA enrichment pass is optional, not load-bearing, and `recurrence` is the primary new input it would consume.

### 7.3 Write path — new memory routes to the PR

**The fix agent never writes the PR.** Consistent with §5's produce/publish split, it *declares* memory in its contract output; **prgroom is the sole actuator** of every outward write (push, reply, resolve, label, PR-body edits). This preserves crash-safety (every outward effect is gated by prgroom-owned state; recovery = re-invoke) and keeps formatting deterministic across runtimes.

The fix contract output gains a classified **`memory`** channel (§5), each entry tagged with one taxonomy class. **MVP routes only CONTEXTUAL, only to the PR**, two ways:

1. **Thread reply** — a CONTEXTUAL note tied to a specific review thread rides out on that thread via the existing `reply` verb. No new mechanism.
2. **`## Decisions` block** — a CONTEXTUAL note *not* tied to a single thread (a PR-wide decision) is recorded in a prgroom-maintained `## Decisions` section via a `gh` PATCH of the PR description (an API edit, not a git commit), at the same point as `reply`.

**Durability — the `pending_memory` queue.** `_fix` does not route at fix time; it resolves the declared `memory` channel into persisted `RoutedMemory` records appended to `state.pending_memory` (written atomically with the dispositions they derive from). `_reply` drains and routes them, then clears the queue. The persisted queue is what makes routing crash-safe: a cycle that ends before `_reply` — a retry-cap trip, a transient `gh` failure on push — keeps its decision memo for the next cycle instead of losing it (in-memory routing would drop the memo on every such cycle). Only CONTEXTUAL entries reach this stage (§7.0), so the persisted record carries no classification tag — that lives only on the pre-resolution `MemoryEntry` (§7.5/§7.6).

```python
@dataclass(frozen=True, slots=True)
class RoutedMemory:
    content: str                    # resolved verbatim: inline content, or the path-form entry's file body
    retry: int                      # (retry, source_item) is the Decisions-block dedup key
    source_item: str
    decided_by: str
    target_hint: str | None = None  # thread node-id → thread reply; None → ## Decisions
```

prgroom owns the `## Decisions` block between sentinel markers and rewrites it wholesale each time (read-modify-write), making re-runs idempotent without a state flag. Each entry carries the retry it was decided on, a title, a one-line rationale, the deciding agent, and the source item; it is **keyed by `(retry, source-item)`** so a crash-and-re-run never double-appends. Entries accumulate across retries; prgroom never deletes a prior decision — the block is the cross-retry decision ledger any future reader sees in the §7.1 snapshot.

**Non-CONTEXTUAL classes are accepted-but-deferred.** UNIVERSAL / PROJECT / PLANNED / HISTORICAL entries pass schema validation (§7.6) and are logged as deferred; routing them to their homes is out of MVP scope.

### 7.4 `memory_dir` — ephemeral within-run scratch

`memory_dir` is an **ephemeral scratchpad for the fix orchestrator's own internal sub-agents** within a single run (e.g. notes an internal `quality-reviewer` leaves for an internal `simplify`) — **not** cross-retry memory (that is the PR + dispositions, §7.1). `memory_writes` (paths written under it) is retained solely for containment auditing (§7.6).

### 7.5 Contract deltas (owned by §5)

- **Fix input** (§5): complete-snapshot guarantee (§7.1); per-item `recurrence` (§7.2); `memory_dir` (scratch only).
- **Fix output** (§5): keep `memory_writes` (scratch paths); add the classified `memory` channel — `[{ "content" | "path", "classification", "target_hint" }]`, where `target_hint` is an optional thread node-id for CONTEXTUAL thread-replies.

### 7.6 Audit semantics

- **`memory_dir` containment** — `memory_writes` paths resolve relative to `memory_dir`; any path resolving outside (absolute elsewhere, or a `..` climb-out) is a **hard `Severity.BLOCK` violation**: the cluster's items flip to `failed` with a containment rationale, an `EscalationSink` event fires, and the resolver promotes to `human-gated` (§3.2). Security-relevant — never soft-failed.
- **Soft `Severity.WARN` breaches** (surfaced as escalations; do **not** flip dispositions or trigger `git stash` — the fix commits are valid, only the bookkeeping is malformed): `classification` not one of the five classes; not exactly one of `content`|`path`; a CONTEXTUAL `target_hint` referencing no real thread in the snapshot (a thread-less CONTEXTUAL entry routes to `## Decisions`).
- **Non-CONTEXTUAL** — accepted, logged as deferred, not an error.
- **Declared-but-missing `memory_writes` path** — soft warning (stderr), not a cluster failure.

`memory_dir` containment is the only hard cluster-flipping memory breach (orphan commits, §5, are the other). A worked 3-retry example — a first-retry decision surviving two fresh-context dispatches via the `## Decisions` block, preventing re-litigation and silent regression — lives in the source proposal, now in the `scotthamilton77/agents-config-ARCHIVE` repository under `docs/plans/`.
