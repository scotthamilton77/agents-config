# PDLC Orchestrator — C4 Level 3: Tick Loop Components

> **Up**: [index](index.md)
> **Previous (reading order)**: [State Machine](state-machine.md)
> **Source bead**: `agents-config-wgclw.2.1`
> **Source spec**: [`2026-05-23-pdlc-orchestrator-core-design.md`](../../specs/2026-05-23-pdlc-orchestrator-core-design.md)

## Glossary

| Term | Meaning |
|---|---|
| `lifecycle_stage` | Where an Objective is in the PDLC FSM — one of the [named Lifecycle Stage Constants](index.md#conventions). Orchestrator-owned. |
| Session | One worker invocation; one Session = one attempt at one gate. See `CONTEXT.md > Session`. |
| CAS (Compare-And-Swap) | Concurrency control: read with a version, write only if the version is unchanged. Mismatch aborts the transition and re-reads. Every tracker write and every state-repo write carries one. |
| Version fingerprint | Per-Objective hash (`spec_hash`, `structural_hash`, `dependency_hash`, `lifecycle_status_hash`) used to detect mid-flight tracker edits during RECONCILE. |
| Lease | A CAS-protected claim — either the per-host tick lock or a per-Session supervisor lease. Carries a fencing token. |
| Fencing token | Monotonic counter attached to a lease; CAS-predicate-evaluated on every write so a stale lease cannot mutate state under a newer holder. |
| Pre-strike triage | Classifier that decides *what kind* of failure a gate failure is (cognition / tooling / reviewer-artifact / flake / config / dependency / spec) before charging a strike. Deterministic Python; never LLM-judged. |
| Sizing Gate | Mechanical composite-score computation that decides Sized (Executable) vs Oversized (Container) at the `CANDIDATE_UOW → AGENT_WORTHY` exit. |
| `needs_reconcile` | An Orchestrator-only flag (NOT a lifecycle stage) raised when the reconcile step cannot determine the correct terminal mapping for an Objective; surfaces on `pdlc health` for human disposition. |
| `terminal_disposition` | Tracker-owned typed metadata field carrying the *why* of an Objective's terminal state (`killed`, `manually-merged`, `duplicate`, `superseded`, `abandoned`); the orchestrator reads it to map into a terminal lifecycle stage. |
| `config_hash` | Hash of the project-config in effect at a tick; pinned on every Session at dispatch; validated at reap. |
| `worktree_base_commit` | Immutable git commit pinned on a Session at fork; reap validates the worker's commits descend from it. |

## Purpose

Zoom into the `pdlc process` container from [C4 L2](c4-l2-container.md). Show the components that make up the **tick loop** — the heart of the Orchestrator — and the adjacent components inside the same process that the tick loop calls.

The tick loop's five named phases (DISCOVER, RECONCILE, REAP, DISPATCH, PERSIST) are each drawn as components, along with the cross-cutting machinery they depend on (lease management, CAS predicate evaluation, pre-strike triage, the Sizing Gate calculator, and the tick-budget timer).

**Scope note**: only the tick loop is fully decomposed here. The other containers from L2 — **WorkTracker adapter**, **JobSupervisor**, **OrchestratorStateRepo** — carry **TODO stubs** at the bottom of this file. They will be filled in when their respective implementation children (under `wgclw.2`) open and have something concrete to draw. Stubbing them now establishes the home; expanding them prematurely would lock in design before it has been ratified.

## Diagram — Tick loop components

```mermaid
C4Component
    title PDLC Orchestrator — Tick Loop Components (C4 L3)

    Container_Boundary(tick, "Tick Loop (within pdlc process)") {
        Component(discover, "DISCOVER", "Python", "Queries WorkTracker for changes since marker (acceleration path); every Nth tick runs full-reconcile via bulk_get + fingerprint diff; initialises unknown Objectives at CANDIDATE_UOW; runs candidate_uow exit gates")
        Component(reconcile, "RECONCILE", "Python", "Compares tracker lifecycle_status vs state-repo lifecycle_stage; applies terminal-disposition classifier; flags fingerprint mismatches as needs_reconcile")
        Component(reap, "REAP", "Python", "Checks heartbeats + deadlines; validates evidence YAML schema; INDEPENDENTLY re-verifies gate command vs worker commit SHA; pre-strike triage; advance OR strike OR route non-cognition")
        Component(dispatch, "DISPATCH", "Python", "For Objectives at worker-driven stages with no in-flight Session: write Session row (pending) BEFORE fork; JobSupervisor.lease() → fork; promote to running")
        Component(persist, "PERSIST", "Python", "Commits state-repo SQL transaction; per-tick Dolt branch checkpoint; writes Discovery marker under CAS")

        Component(lease, "Lease manager", "Python", "Acquires / releases tick lock + supervisor leases via CAS on (holder_id, fencing_token); reclaims stale leases on wake")
        Component(cas, "CAS predicate evaluator", "Python", "Version-fingerprint discipline; spec_hash / structural_hash / dependency_hash / lifecycle_status_hash; aborts transitions on mismatch with reason tracker-version-mismatch or state-version-mismatch")
        Component(triage, "Pre-strike triage classifier", "Python", "DETERMINISTIC; no LLM judgment; 7 failure causes: cognition / tooling / reviewer-artifact / flake / config / dependency / spec; ambiguous cases route to needs_reconcile")
        Component(sizing, "Sizing Gate calculator", "Python", "Composite-score over 5 mechanical inputs (Atomic-AT count, file-touch estimate, subsystem-crossing count, dep fan-out, NFR flag); threshold from project-config")
        Component(budget, "Tick-budget timer", "Python", "Bounds latency-sensitive per-Objective work in DISCOVER + DISPATCH; correctness-critical ops (full-reconcile, lease, REAP verification, CAS, crash-roll-forward) bypass")
    }

    Container_Boundary(pdlc_other, "Other components in pdlc process (called by the tick loop)") {
        Component(adapter, "WorkTracker adapter (bd-bound)", "Python", "Implements WorkTracker protocol against bd; per-call tracker-side CAS predicate (e.g. Dolt row-version). See TODO stub below.")
        Component(super, "JobSupervisor", "Python", "Worker process supervision: lease / heartbeat / deadline / cancel / terminal_status / capture. Owns process_group_id. See TODO stub below.")
        Component(state_client, "OrchestratorStateRepo client", "Python + Dolt SQL", "Typed DAO over the Dolt sidecar; per-tick branch checkpoint commits. See TODO stub below.")
        Component(config_ld, "project-config loader", "Python", "Reads + validates project-config.toml; computes config_hash; pins it on Sessions at dispatch")
    }

    ContainerDb(state_ext, "OrchestratorStateRepo", "Dolt sidecar")
    Container_Ext(worker_ext, "Worker subprocess", "forked")
    System_Ext(tracker_ext, "bd (Work Tracker)")
    System_Ext(config_file, "project-config.toml")

    Rel(discover, adapter, "list_changed_since(marker); bulk_get for full-reconcile")
    Rel(discover, sizing, "Sizing Gate at candidate_uow exit")
    Rel(discover, state_client, "Initialise ObjectiveLifecycleState at CANDIDATE_UOW")
    Rel(discover, budget, "Per-iteration budget check")

    Rel(reconcile, adapter, "bulk_get for fingerprint refresh")
    Rel(reconcile, cas, "Evaluate version fingerprints")
    Rel(reconcile, state_client, "needs_reconcile flag write")

    Rel(reap, super, "heartbeat / deadline / terminal_status / capture")
    Rel(reap, triage, "Classify gate failure cause")
    Rel(reap, adapter, "set_lifecycle_status under CAS (projection write)")
    Rel(reap, state_client, "Append TransitionLog; advance lifecycle_stage OR strike_count++")
    Rel(reap, worker_ext, "Re-read gate-evidence YAML; re-run gate against commit SHA", "independent verification")

    Rel(dispatch, state_client, "Write Session row (pending) BEFORE fork")
    Rel(dispatch, super, "lease(session_id) → fork in process group")
    Rel(dispatch, budget, "Defer if tick budget exhausted")
    Rel(dispatch, config_ld, "Pin config_hash on Session")

    Rel(persist, state_client, "Commit SQL txn; per-tick branch checkpoint")
    Rel(persist, cas, "Marker advance under CAS")

    Rel(lease, state_client, "Leases table read / write under CAS")
    Rel(adapter, tracker_ext, "bd CLI under CAS")
    Rel(state_client, state_ext, "Dolt SQL")
    Rel(super, worker_ext, "fork / SIGTERM / SIGKILL / wait")
    Rel(config_ld, config_file, "Read TOML at tick start")
```

## Element notes — tick loop phases

### DISCOVER

Two execution paths in one component:

- **Acceleration path (every tick)** — `WorkTracker.list_changed_since(marker)` returns Objectives that have changed since the last successful tick. Cheap; processes only the delta.
- **Full-reconcile path (every Nth tick, project-config default N=10)** — `bulk_get` of all Objectives plus per-object fingerprint diff against `OrchestratorStateRepo`. This is a **correctness mechanism**, not a latency-sensitive one — it is therefore **not budget-bounded** and runs to completion regardless of the tick budget.

For each unknown Objective, DISCOVER initialises an `ObjectiveLifecycleState` at `CANDIDATE_UOW` and runs the candidate_uow exit gates (Atomic-AT lint, DoD application, Sizing Gate). Per-iteration budget check at the top of the loop emits `budget-exhausted-in-discover` when the tick budget fires; un-processed Objectives wait for the next tick.

### RECONCILE

Compares the tracker's coarse `lifecycle_status` against the state-repo's fine `lifecycle_stage` per Objective known to both stores. The **terminal-disposition classifier** reads the tracker's typed `terminal_disposition` field and maps each value to the appropriate terminal lifecycle stage. Ambiguous or absent dispositions raise `needs_reconcile=true` — an Orchestrator-only flag, NOT a lifecycle stage — which surfaces on `pdlc health` for human disposition. The classifier never silently collapses semantically-distinct closures (a tracker-side `close` could mean `killed`, `manually-merged`, `duplicate`, `superseded`, or `abandoned` — the human picks if the typed field is absent).

Fingerprint mismatches (`spec_hash`, `structural_hash`, `dependency_hash`, `lifecycle_status_hash`) also raise `needs_reconcile`. RECONCILE never silently mutates terminal state.

### REAP

The most operationally consequential phase. For each Session with `status=running`:

1. Check the JobSupervisor's heartbeat and deadline. Silent past `deadline_ts` → cancel + record strike (subject to pre-strike triage).
2. If supervisor reports `exited` and report present:
   - Validate the gate-evidence YAML schema.
   - **Independently re-run the gate command** against the worker's commit SHA. Reap never trusts the worker's `verdict` field; it re-establishes the claim itself.
   - Validate `config_hash` matches the live config. Mismatch routes the Session to the **config-version-divergence handler**: the Session continues to reap under its original `config_hash`, but no new Session is dispatched against the divergent config until the operator resolves it.
   - Validate worktree state (descended from `worktree_base_commit`, `git status --porcelain` clean).
   - Run **Pre-strike triage** to classify the failure cause.
   - Advance `lifecycle_stage` OR record a cognition strike OR route the non-cognition failure.
   - On 3rd cognition strike: route to `AUTOPSY` (freeze branch; spawn RCA Sessions).

### DISPATCH

For each Objective at a worker-driven `lifecycle_stage` (`TEST_AUTHORING`, `IMPLEMENTING`, `REVIEWING`, `PR_VALIDATION`, `AUTOPSY`) with no in-flight Session:

1. Check tick-budget remaining; defer to next tick if exhausted.
2. **Write the Session row to `OrchestratorStateRepo.Sessions` with `status=pending` BEFORE fork** — so a crash between write and fork leaves a reconcilable record (Crash-Recovery point (a)).
3. Pin `config_hash` on the Session record.
4. Call `JobSupervisor.lease(session_id)` to fork the Worker in its own process group.
5. Promote the Session to `running` and populate `supervisor_id`, `lease_token`, `process_group_id`, `artifact_dir`, `worktree_base_commit`, `deadline_ts`.

Degraded **reap-only mode** (active during config-version divergence or `tracker_unreachable`) SKIPS dispatch but still reaps in-flight Sessions to completion.

### PERSIST

Commits the SQL transaction for the tick's accumulated state-repo writes. Performs the **per-tick Dolt branch checkpoint commit** that enables `dolt log` replay for crash recovery. Writes the new Discovery marker under CAS against the prior marker (marker monotonicity invariant). Releases the tick lease; exits with status code reflecting nominal / degraded.

## Element notes — cross-cutting machinery

### Lease manager

Two leases in play per tick: the **tick lock** (one per host; prevents concurrent ticks corrupting state) and **per-Session supervisor leases** (one per running Worker; fencing-token CAS). A fast-path file lock at `.pdlc/tick.lock` is an *optimisation only* — the authoritative lease lives in `OrchestratorStateRepo.Leases`. Stale-lease detection on machine-wake reclaims abandoned leases.

### CAS predicate evaluator

The heart of the orchestrator's correctness story. Every tracker write carries a tracker-side version predicate (e.g. bd's Dolt row-version); every state-repo write carries a row-version predicate. Mismatch aborts the in-flight transition with `tracker-version-mismatch` or `state-version-mismatch`, and the tick re-reads + re-ticks the affected Objective. The four named fingerprints — `spec_hash`, `structural_hash`, `dependency_hash`, `lifecycle_status_hash` — are computed per-Objective and compared at the read-version step of the transition discipline.

### Pre-strike triage classifier

Strict deterministic Python. Seven failure causes (see [`state-machine.md`](state-machine.md) for the routing): **cognition** (charge strike), **tooling** (no strike — Autopsy route v), **reviewer-artifact** (no strike — tooling escalation), **flake** (retry then strike), **config** (no strike — divergence handler), **dependency** (no strike — park via route iv), **spec** (no strike — Specification RCA). **LLM judgment is forbidden in failure-cause assignment** — the classifier inputs are gate-evidence YAML, exit code, reviewer-artifact validation, `config_hash` check, dependency check, and worktree state check; nothing else. Ambiguous cases route to `needs_reconcile=true` for human disposition rather than guessing.

### Sizing Gate calculator

Mechanical composite-score computation at `CANDIDATE_UOW → AGENT_WORTHY` exit. Five mechanical inputs (Atomic-AT count, file-touch estimate, subsystem-crossing count, dependency fan-out, NFR-escalation flag), each normalised and weighted from project-config. Score < threshold → **Sized** (Executable); score ≥ threshold → **Oversized** (Container). If a project's adoption demands an LLM-judgment axis (e.g. "architectural risk"), that axis MUST be marked `human-mechanical` and require an explicit recorded operator override — the orchestrator does not silently accept LLM-judgment inputs into the Sizing Gate.

### Tick-budget timer

Bounds latency-sensitive per-Objective work at two checkpoints: inside DISCOVER (before evaluating Candidate UoW exit gates for each unknown Objective) and inside DISPATCH (before forking a new worker Session). **Correctness-critical operations bypass the budget**: full-reconcile, lease acquisition/release, REAP heartbeat/deadline checks and worker-report verification, CAS predicate evaluation, Crash-Recovery roll-forward. Budgeting these would trade correctness for latency — the wrong trade.

## Other containers' L3 views

The other L2 containers — **WorkTracker adapter**, **JobSupervisor**, and **OrchestratorStateRepo** — have their own L3 component diagrams in this folder. They are currently **stubs**, to be filled in when their respective implementation children (under `wgclw.2`) open and have ratified design decisions to draw against:

- [c4-l3-worktracker-adapter.md](c4-l3-worktracker-adapter.md) — **STUB** — expected components: protocol-method groupings, bd CLI invocation, CAS predicate computation, fingerprint computation, error translation, Discovery marker management
- [c4-l3-jobsupervisor.md](c4-l3-jobsupervisor.md) — **STUB** — expected components: lease lifecycle, heartbeat reporter, deadline enforcer, terminal-status collector, capture handles, cancellation handler, crash-recovery roll-forward
- [c4-l3-state-repo.md](c4-l3-state-repo.md) — **STUB** — expected components: schema migrations, per-table DAOs, branch-checkpoint mechanism, CAS predicate API, read-only-cache fallback, retention policy

Each stub file lists its expected components, its when-to-fill trigger, and its source-spec pointer. Establishing the homes now means future contributors don't have to invent folder structure mid-stride.

## What this diagram does NOT show

- The **runtime ordering** of the five phases — that lives in [`sequences.md`](sequences.md) tick cycle.
- The **lifecycle stages** the tick loop transitions Objectives through — that lives in [`state-machine.md`](state-machine.md).
- The **table-level data layout** of `OrchestratorStateRepo` — that lives in [`data-view.md`](data-view.md).
- The **physical layout** of where these components run — that lives in [`c4-deployment.md`](c4-deployment.md).
- Components inside the Worker subprocess (persona-specific; out of orchestrator scope).

## Cross-references

- **Up**: [C4 L2 — Container](c4-l2-container.md) — the `pdlc process` container being zoomed
- **Companion sequence**: [`sequences.md`](sequences.md) — runtime ordering of these components
- **Companion source**: orchestrator core design spec §§ [Tick algorithm (high-level)](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#tick-algorithm-high-level), [Transition execution discipline](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#transition-execution-discipline), [Pre-strike triage](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#pre-strike-triage), [Sizing Gate decision table](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#sizing-gate-decision-table)
