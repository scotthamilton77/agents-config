# PDLC Orchestrator — C4 Level 3: JobSupervisor Components (STUB)

> **Up**: [index](index.md)
> **Sibling L3**: [Tick Loop](c4-l3-tick-loop.md) (fully drawn)
> **Source bead**: `agents-config-wgclw.2.1`
> **Status**: **STUB — not yet drawn**

## Why this file exists

The JobSupervisor is one of the components inside the `pdlc process` container (see [C4 L2](c4-l2-container.md)). Its component-level breakdown belongs at L3, alongside the [Tick Loop component diagram](c4-l3-tick-loop.md).

This file is a **placeholder home** for that diagram. It will be filled in when the JobSupervisor implementation child (under `wgclw.2`) opens. Establishing the home now means future contributors don't have to invent folder structure mid-stride; drafting the components prematurely would lock in design decisions the implementation child has not ratified.

## Glossary

| Term | Meaning |
|---|---|
| Session | One worker invocation; one Session = one attempt at one gate. See `CONTEXT.md > Session` |
| Lease | A CAS-protected claim on a worker process; carries a fencing token so a stale lease cannot mutate state under a newer holder |
| Fencing token | Monotonic counter attached to a lease; predicate-evaluated on every supervisor write to prevent stale-lease writes |
| Process group | Unix process group containing the worker and its descendants; enables clean cancellation of the whole tree via a single signal |
| Heartbeat | Periodic liveness signal from the supervisor reporting the worker is still making progress |
| Deadline | Absolute timeout (`deadline_ts`) past which the supervisor cancels the worker via SIGTERM → SIGKILL |
| `terminal_status` | The supervisor's post-exit report: exit code, exit signal, report path, log path — durable across orchestrator restarts |

## Expected components (pending design ratification)

When this stub is expanded, the diagram is expected to contain at least:

- **Lease lifecycle** — `lease(session_id) → SupervisorLease`; forks the worker in its own process group; writes the supervisor record (`supervisor_id`, `lease_token`, `process_group_id`, `artifact_dir`) atomically
- **Heartbeat reporter** — periodic liveness signal under CAS via fencing token; orchestrator's REAP phase polls this
- **Deadline enforcer** — SIGTERM at expiry; SIGKILL after grace period; deadline-set / deadline-extend API
- **Terminal-status collector** — exit code, exit signal, report path, log path; persisted durably so the report survives orchestrator restarts
- **Capture handles** — supervisor-owned stdout / stderr / artifact-dir handles for streaming and forensic preservation
- **Cancellation handler** — idempotent SIGTERM to the worker's process group; safe to re-call
- **Crash-recovery roll-forward** — on machine-wake, reclaim stale leases whose `expiry_ts + grace < now`

## When to expand this stub

When the implementation child for the JobSupervisor is filed under `wgclw.2` and has:

1. A ratified component breakdown of the supervisor capability surface
2. A concrete decision on the supervisor's deployment shape (in-process thread vs separate process)
3. A concrete decision on the durability mechanism for `terminal_status` (filesystem vs SQL vs both)
4. A concrete decision on signal-handling semantics (SIGTERM grace, SIGKILL escalation, process-group reaping)

Until then, this stub stays as-is.

## Cross-references

- **Container view (L2)**: [c4-l2-container.md](c4-l2-container.md) — places the JobSupervisor inside the `pdlc process` container, supervising Worker subprocesses
- **Tick loop (L3)**: [c4-l3-tick-loop.md](c4-l3-tick-loop.md) — shows REAP and DISPATCH interactions with the supervisor
- **Source spec**: [JobSupervisor contract section of the orchestrator core design](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#jobsupervisor-contract)
