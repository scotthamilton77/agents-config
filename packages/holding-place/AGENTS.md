# AGENTS.md — `packages/holding-place/`

Package-scoped guidance for the Holding Place subsystem. The repo-root
`AGENTS.md` still applies. This is real Python code, but **early** — a small
peer subsystem to the PDLC Orchestrator, not a finished component.

## Status

Holding Place is the intended Idea pipeline: it captures and shapes Ideas and
exposes the **Promote contract** that hands a ready Idea to the PDLC
Orchestrator as an Objective. Only the foundational pieces exist so far. Expect
churn; do not over-document internals until the Promote contract with
`packages/pdlc/` stabilizes.

## Toolchain & gate

`uv`-managed, Python ≥ 3.11. **Not yet wired into `make ci`.** Run tests locally
with `uv run pytest` from inside `packages/holding-place/`. Hold to the same
discipline as the gated packages (ruff, mypy `--strict`, behavioural tests).

## Reference

Peer subsystem and downstream consumer: `packages/pdlc/` +
`docs/architecture/pdlc-orchestrator/index.md`.
