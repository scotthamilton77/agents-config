# PDLC Orchestrator — Sequence Diagrams

> **Up**: [index](index.md)
> **Previous (reading order)**: [C4 L2 — Container](c4-l2-container.md)
> **Next (reading order)**: [State Machine](state-machine.md)
> **Source bead**: `agents-config-wgclw.2.1`
> **Source spec**: [`2026-05-23-pdlc-orchestrator-core-design.md`](../../specs/2026-05-23-pdlc-orchestrator-core-design.md)

## Glossary

| Term | Meaning |
|---|---|
| Tick | One end-to-end run of the orchestrator's DISCOVER → RECONCILE → REAP → DISPATCH → PERSIST cycle; one `pdlc tick` invocation = one tick. |
| Session | One worker invocation; one Session = one attempt at one gate. |
| Gate | A discrete pass/fail checkpoint inside a lifecycle stage (e.g. red-tests gate, green-gate, reviewer-gate, PR-validation gate). |
| Reap | The phase where the orchestrator collects results from completed Worker Sessions and decides what to do next. |
| Dispatch | The phase where the orchestrator decides which Objectives need new Worker Sessions and forks them. |
| CAS (Compare-And-Swap) | Concurrency control: read with a version, write only if the version is unchanged; mismatch aborts the transition and re-reads. |
| `config_hash` | Hash of project-config in effect at tick start; pinned on every Session at dispatch; validated at reap. |
| Independent gate verification | Reap re-runs the gate command itself against the worker's commit SHA; the worker's claimed verdict is never trusted. |

## Purpose

Two sequence diagrams covering the orchestrator's behaviour at two complementary timescales:

1. **Single tick cycle** — what happens during one `pdlc tick` invocation; spans seconds to ~60s
2. **Objective happy path** — what happens to one Objective from Idea capture through to merge; spans many ticks (often days)

Together they answer: *who calls whom, in what order, with what concurrency control, and where do the failure branches live?*

---

## Sequence 1 — Single tick cycle

One invocation of `pdlc tick`. The same code path serves cron-driven and human-invoked ticks. Phases run sequentially within a single tick; the lease prevents concurrent ticks from corrupting state.

```mermaid
sequenceDiagram
    autonumber
    participant Cron as Cron / Operator
    participant PDLC as pdlc process
    participant Config as project-config loader
    participant State as OrchestratorStateRepo
    participant Adapter as WorkTracker adapter
    participant BD as bd (Work Tracker)
    participant Super as JobSupervisor
    participant Worker as Worker subprocess

    Cron->>PDLC: exec pdlc tick
    PDLC->>State: acquire tick lease (CAS on Leases)
    State-->>PDLC: lease granted (fencing token)
    PDLC->>Config: read project-config.toml + compute config_hash
    Config-->>PDLC: config + config_hash

    Note over PDLC: pre-tick toolchain assertion
    PDLC->>PDLC: probe project-config.toolchain.required for PATH presence + min versions
    alt missing or under-versioned binary
        PDLC->>State: mark dispatchable Objectives needs_reconcile=true (missing-toolchain:X)
        Note over PDLC: skip DISPATCH this tick (REAP of in-flight Sessions still runs)
    end

    Note over PDLC: start tick-budget timer

    rect rgb(245, 245, 255)
        Note over PDLC,BD: DISCOVER
        PDLC->>Adapter: list_changed_since(marker)
        Adapter->>BD: bd query (delta)
        BD-->>Adapter: changed Objectives
        Adapter-->>PDLC: delta
        alt every Nth tick (full-reconcile path)
            PDLC->>Adapter: bulk_get (NOT budget-bounded)
            Adapter->>BD: bd query (all)
            BD-->>Adapter: all Objectives + fingerprints
            Adapter-->>PDLC: full set
        end
        loop for each unknown Objective (budget-checked)
            PDLC->>State: init ObjectiveLifecycleState at CANDIDATE_UOW
            PDLC->>PDLC: run candidate_uow exit gates (lint, DoD, Sizing Gate)
        end
    end

    rect rgb(255, 245, 245)
        Note over PDLC,State: RECONCILE
        loop for each known Objective
            PDLC->>Adapter: bulk_get + fingerprints
            Adapter-->>PDLC: tracker view
            PDLC->>State: compare lifecycle_status vs lifecycle_stage
            alt tracker closed + terminal_disposition present
                PDLC->>State: map to terminal lifecycle_stage
            else terminal_disposition ambiguous / absent
                PDLC->>State: set needs_reconcile=true
            else fingerprint mismatch
                PDLC->>State: set needs_reconcile=true
            end
        end
    end

    rect rgb(245, 255, 245)
        Note over PDLC,Worker: REAP
        loop for each Session status=running
            PDLC->>Super: heartbeat / deadline / terminal_status
            Super-->>PDLC: status
            alt worker exited with report
                PDLC->>Worker: read gate-evidence YAML from report_path
                PDLC->>PDLC: validate evidence schema
                PDLC->>PDLC: INDEPENDENTLY re-run gate vs worker commit SHA
                PDLC->>PDLC: validate config_hash matches live config
                PDLC->>PDLC: validate worktree descent from worktree_base_commit
                PDLC->>PDLC: pre-strike triage (cognition / tooling / flake / ...)
                alt pass
                    PDLC->>Adapter: set_lifecycle_status (CAS)
                    PDLC->>State: advance lifecycle_stage + append TransitionLog
                else cognition strike
                    PDLC->>State: strike_count++ + append TransitionLog
                    opt strike_count == 3
                        PDLC->>State: route to AUTOPSY + freeze branch
                    end
                else non-cognition (tooling / config / dep / spec)
                    PDLC->>State: route to corrective path (no strike)
                end
            else heartbeat silent past deadline
                PDLC->>Super: cancel (SIGTERM → SIGKILL)
                PDLC->>State: record strike (subject to triage)
            end
        end
    end

    rect rgb(255, 255, 240)
        Note over PDLC,Super: DISPATCH
        alt degraded reap-only mode<br/>(toolchain missing OR config divergence OR tracker unreachable)
            Note over PDLC: SKIP dispatch
        else nominal
            loop for each Objective at worker-driven stage with no in-flight Session
                PDLC->>PDLC: check tick-budget remaining
                PDLC->>State: write Session row status=pending + config_hash (BEFORE fork)
                PDLC->>Super: lease(session_id)
                Super->>Worker: fork in process group + assign deadline_ts
                Super-->>PDLC: supervisor_id, lease_token, process_group_id, artifact_dir
                PDLC->>State: promote Session to status=running
            end
        end
    end

    rect rgb(240, 240, 240)
        Note over PDLC,State: PERSIST
        PDLC->>State: commit SQL transaction
        PDLC->>State: per-tick Dolt branch checkpoint
        PDLC->>State: write new Discovery marker (CAS vs prior)
    end

    PDLC->>State: release tick lease
    PDLC-->>Cron: exit (status: nominal / degraded)
```

### Notes on the tick cycle

- **Phase ordering is fixed**: DISCOVER → RECONCILE → REAP → DISPATCH → PERSIST. Inverting REAP and DISPATCH would risk dispatching against state the just-completed worker had already mutated.
- **Per-tick lease** is acquired first and released last. A fast-path file lock at `.pdlc/tick.lock` is an optimisation; the authoritative lease lives in `OrchestratorStateRepo.Leases`.
- **Full-reconcile** (the every-Nth-tick `bulk_get` path) is **not budget-bounded** — it runs to completion. Budgeting it would trade correctness for latency.
- **Independent gate verification** at REAP is non-negotiable: the orchestrator never trusts the worker's `verdict` claim in the evidence YAML.
- **Pending-before-fork** ordering at DISPATCH means a crash between Session-write and fork leaves a reconcilable record (next tick sees a stale `pending` Session and cleans it up).
- **Degraded reap-only mode** preserves the ability to complete in-flight workers even when dispatch is unsafe (config divergence, tracker unreachable, **missing required toolchain**). The pre-tick toolchain assertion gates entry to this mode for the missing-toolchain case; once the operator restores tooling, the next tick proceeds normally.
- **Non-transient tooling failures are bounded.** The pre-tick toolchain assertion catches the common case (declared binary not on `PATH`) before any worker forks. For failures it cannot statically detect, the orchestrator maintains a `tooling_strike_count` per `(objective_id, lifecycle_stage, error_signature)`; on `project-config.tooling_max_strikes` recurrence the Objective is marked `needs_reconcile=true` and dispatch halts. Detail: [`state-machine.md` § Tooling-failure handling](state-machine.md#tooling-failure-handling-pre-tick-assertion--bounded-retry).

---

## Sequence 2 — Objective happy path

One Objective traversing the FSM from initial capture through to merge. **Multiple ticks** span this sequence — each `pdlc tick` invocation advances the Objective by at most one stage per gate-pass. Worker Sessions sit between ticks; they may run for minutes to tens of minutes.

This diagram shows the happy path only — failure branches (strikes, autopsy routing, container divergence) live in [`state-machine.md`](state-machine.md). It also collapses the tick-cycle internals (already shown in Sequence 1) into single arrows where applicable.

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant HP as Holding Place
    participant BD as bd (Work Tracker)
    participant PDLC as pdlc (across many ticks)
    participant State as OrchestratorStateRepo
    participant TA as Test-Author worker
    participant Impl as Implementer worker
    participant Rev as Reviewer worker
    participant PRFix as PR-fix worker (per-comment)
    participant CI as CI
    participant Git as Git remote

    Note over Op,HP: Idea phase (Holding Place pipeline)
    Op->>HP: capture Idea
    Op->>HP: groom / shape Ideas (batch ceremony)
    Op->>HP: promote(idea_id)
    HP->>BD: create_objective(provenance.originating_idea_id=...)
    BD-->>HP: objective_id

    Note over PDLC,BD: tick N — DISCOVER picks up new Objective
    PDLC->>BD: list_changed_since(marker)
    BD-->>PDLC: new Objective at CANDIDATE_UOW
    PDLC->>State: init ObjectiveLifecycleState at CANDIDATE_UOW
    PDLC->>PDLC: run candidate_uow exit gates (lint, DoD, Sizing Gate)

    Note over Op,PDLC: Human signoff gate
    PDLC->>Op: surface on pdlc health — needs signoff
    Op->>BD: signoff annotation (or pdlc objectives signoff)

    Note over PDLC: tick N+m — promote to AGENT_WORTHY
    PDLC->>State: advance to AGENT_WORTHY
    PDLC->>State: advance to DECOMPOSE + assign type_stamp + is_container
    alt is_container=false (Executable)
        PDLC->>State: advance to EXECUTABLE_READY
    else is_container=true (Container)
        Note over PDLC,BD: emit children as direct Objectives at CANDIDATE_UOW (parent-linked)
        PDLC->>BD: create_objective(parent_id=container_id, lifecycle_status=open) × N
        PDLC->>State: init each child ObjectiveLifecycleState at CANDIDATE_UOW
        PDLC->>State: advance Container to CONTAINER_DECOMPOSED (passive aggregator)
        Note over PDLC: each child runs its own CANDIDATE_UOW exit gates — Container Closure waits for all descendants to MERGE
    end

    Note over PDLC,TA: tick N+m+k — DISPATCH worker for TEST_AUTHORING
    PDLC->>State: write Session row pending (TEST_AUTHORING, attempt=1)
    PDLC->>TA: fork (via JobSupervisor)
    TA-->>TA: write failing tests + commit + write evidence YAML + exit
    Note over PDLC,TA: tick N+m+k+1 — REAP TEST_AUTHORING
    PDLC->>TA: read evidence + re-run gate vs commit SHA
    PDLC->>State: advance to IMPLEMENTING

    Note over PDLC,Impl: tick — DISPATCH Implementer
    PDLC->>State: write Session row pending (IMPLEMENTING, attempt=1)
    PDLC->>Impl: fork
    Impl-->>Impl: write production code + commit + evidence YAML + exit
    Note over PDLC: tick — REAP IMPLEMENTING
    PDLC->>Impl: read evidence + re-run gate vs commit SHA
    PDLC->>State: advance to REVIEWING

    Note over PDLC,Rev: tick — DISPATCH Reviewer
    PDLC->>State: write Session row pending (REVIEWING, attempt=1)
    PDLC->>Rev: fork
    Rev-->>Rev: review + commit findings if any + evidence YAML + exit
    Note over PDLC: tick — REAP REVIEWING
    PDLC->>State: advance to PR_VALIDATION

    Note over PDLC,CI: tick — PR_VALIDATION begins: push PR and await CI verdicts
    PDLC->>Git: push branch + open PR (gh pr create)
    Git->>CI: PR trigger
    CI-->>Git: mechanical-gate verdicts
    PDLC->>Git: read verdicts (gh pr checks)

    Note over PDLC,Git: PR review-iteration loop (bounded by review_max_rounds)
    loop until clean OR escalation OR rounds exhausted
        PDLC->>Git: poll review comments (issue + inline)
        Git-->>PDLC: comments
        PDLC->>PDLC: classify each comment FIX / SKIP / ESCALATE
        alt any FIX comments
            PDLC->>PRFix: dispatch per-comment fix worker (via JobSupervisor)
            PRFix-->>PRFix: apply fix + commit + reply + resolve thread
            PDLC->>Git: push fixes
            Git->>CI: PR re-trigger
            CI-->>Git: mechanical-gate verdicts
        end
    end

    alt CI green + no FIX backlog + no ESCALATE + no upstream HUMAN_HOLD marker
        PDLC->>State: advance to MERGING (skip PR_HUMAN_HOLD — default happy path)
    else ESCALATE raised OR upstream HUMAN_HOLD marker set
        PDLC->>State: advance to PR_HUMAN_HOLD
        Note over Op,PDLC: Human approval hold (conditional path)
        PDLC->>Op: surface on pdlc health — needs merge approval
        Op->>PDLC: approval annotation
        PDLC->>State: advance to MERGING
    end

    Note over PDLC,Git: MERGING
    PDLC->>Git: merge PR (gh pr merge)
    Git-->>PDLC: merged
    PDLC->>BD: set_lifecycle_status(id, closed) under CAS
    PDLC->>State: advance to MERGED (terminal)
    PDLC->>PDLC: cleanup worktree (idempotent)

    Note over PDLC: tick — cleanup pass
    PDLC->>State: cleanup ephemeral Session records + archive TransitionLog
```

### Notes on the happy path

- **The sequence spans many ticks.** Each `pdlc tick` advances the Objective by at most one gate-pass. Between ticks, Workers run (minutes to tens of minutes) and humans signoff (asynchronous).
- **Idea creation is operator-driven, NOT orchestrator-driven.** Operators capture Ideas in the Holding Place and either promote them (Holding Place path) or create Idea-less Objectives directly in bd. The orchestrator observes the result on the next DISCOVER.
- **DECOMPOSE for Containers emits direct Objectives at `CANDIDATE_UOW`.** Children of an oversized Container are created directly in the tracker with `parent_id=<container_id>`; each runs its own `CANDIDATE_UOW` exit gates (Atomic-AT lint + DoD + Sizing Gate + human signoff) before advancing. The Container becomes a passive aggregator at `CONTAINER_DECOMPOSED` and reaches `MERGED` only when every descendant has reached `MERGED`.
- **Container Closure bubbles upward.** A Container reaches `MERGED` only when every descendant has merged, every Container-Level AT passes, and every Scaffold AT has been paired with a successful Cleanup AT.
- **Human gates.** One always-present: `CANDIDATE_UOW → AGENT_WORTHY` (per-Objective Spec signoff — applies to every Objective, including decomposer-originated children). One conditional: `PR_HUMAN_HOLD → MERGING` (merge approval), engaged only when the Objective carries an upstream HUMAN_HOLD marker OR PR review iteration raised an `ESCALATE` classification. The happy path with no escalation flows `PR_VALIDATION → MERGING` directly.
- **PR review iteration is non-cognition.** The `FIX / SKIP / ESCALATE` classification loop inside `PR_VALIDATION` does not charge cognition strikes — it is bounded by `review_max_rounds` from project-config. Only CI failures inside `PR_VALIDATION` charge strikes.
- **Cleanup is idempotent.** `cleanup_worktree(session_id)` is safe to call multiple times; first call removes the worktree and deletes the branch, subsequent calls no-op. This makes crash-recovery's worktree cleanup safe to retry across ticks.

## What these diagrams do NOT show

- **Strike and autopsy routing.** A cognition strike loops back to the same lifecycle stage with `attempt_number++`; on the 3rd strike, the Objective routes to `AUTOPSY`. See [`state-machine.md`](state-machine.md).
- **Non-cognition failure routes** (tooling, config, dependency, spec). Each has its own corrective path; none charge a cognition strike. See [`state-machine.md`](state-machine.md).
- **CAS aborts and retries.** Mid-tick edits to the tracker fail the CAS predicate at the write step; the orchestrator re-reads and re-ticks. Not drawn for brevity; covered in [the orchestrator core design spec's transition execution discipline](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#transition-execution-discipline).
- **Container-decomposition divergence beyond the single CONTAINER_DECOMPOSED stop.** Container Closure conditions and Scaffold/Cleanup pairing live in [`state-machine.md`](state-machine.md).
- **Component-level mechanics inside the pdlc process.** See [`c4-l3-tick-loop.md`](c4-l3-tick-loop.md) for the components that execute these sequences.

## Cross-references

- **Companion structural views**: [`c4-l2-container.md`](c4-l2-container.md), [`c4-l3-tick-loop.md`](c4-l3-tick-loop.md)
- **Companion state view**: [`state-machine.md`](state-machine.md)
- **Companion data view**: [`data-view.md`](data-view.md)
- **Source spec**: orchestrator core design §§ [Tick algorithm](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#tick-algorithm-high-level), [Transition execution discipline](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#transition-execution-discipline), [Crash-Recovery](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#crash-recovery)
