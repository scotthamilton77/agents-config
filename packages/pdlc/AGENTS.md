# AGENTS.md — `packages/pdlc/`

Package-scoped guidance for the PDLC Orchestrator. The repo-root `AGENTS.md`
still applies. This is real Python code, but **early** — treat it as a tracer
bullet, not a finished subsystem.

## Status

The orchestrator is the intended deterministic FSM engine that drives
Objectives from `CANDIDATE_UOW` through the lifecycle to a terminal stage. Today
only the **happy-path tracer bullet is built**: the `LifecycleStage` enum, the
`tick()` phase order, and the `WorkTracker` Protocol. Substantial designed
pieces are **not yet built** — there is no CLI, the `StateRepo` is in-memory
(not the intended Dolt-backed store), and the strike/autopsy/recovery state
machine is unimplemented. See `docs/architecture/pdlc-orchestrator/` for the
target design and its built-vs-intended markers.

## Toolchain & gate

`uv`-managed, Python ≥ 3.11. **Not yet wired into `make ci`.** Run tests locally
with `uv run pytest` from inside `packages/pdlc/`. Follow the same discipline as
the gated packages (ruff, mypy `--strict`, behavioural tests) so wiring the gate
later is a formality, not a cleanup.

## Reference

Architecture: `docs/architecture/pdlc-orchestrator/index.md`. Peer subsystem:
`packages/holding-place/` (feeds Objectives in via the Promote contract).
