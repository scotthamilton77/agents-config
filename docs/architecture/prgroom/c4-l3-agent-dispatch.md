# prgroom CLI — C4 Level 3: Agent Dispatch *(stub)*

> **Up**: [index](index.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md) — Section 5 (Agent dispatch internals)
> **Container**: `internal/agent/` inside the prgroom binary (see [`c4-l2-container.md`](c4-l2-container.md))
> **Status**: **STUB** — placeholder pending the `internal/agent` implementation bead.

## Why this is a stub

Section 5 of the source spec is ratified at the contract level (the cluster contract and fix contract; provider chains; per-contract config; token-usage logging). The internal component breakdown of `internal/agent/` is not yet pinned at the same implementation-readiness level as `internal/lifecycle/` (drawn in [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md)) because no `[Impl]` child bead has opened against `internal/agent/` yet.

This stub establishes the file's home and the components the eventual drawing must cover. When the impl bead opens, this file gets re-drawn at the same fidelity as the lifecycle L3.

## Expected components (when drawn)

The diagram should cover these named units inside `internal/agent/`:

### Cluster contract

- **`ClusterContract` interface** — the `Cluster(ctx, items []ReviewItem) ([]Cluster, error)` surface that `internal/lifecycle/clusterLocked` consumes.
- **Provider chain dispatcher** — the fallback ladder. Try the primary; on failure-or-malformed-output, fall to the next. Default chain: `ollama+Gemma` → `claude haiku` → `codex-mini`. Per-provider TOML config for model, timeout, prompt template.
- **Per-provider invokers** — one per `claude`, `codex`, `opencode`, `ollama` subprocess shape. Each owns its own stdin/stdout serialisation and timeout.
- **Cluster output validator** — Cluster contract invariants per §5: schema-conformant JSON AND every input item appears in some cluster. Violations trip `CONTRACT_CLUSTER_MALFORMED` or `CONTRACT_CLUSTER_COVERAGE` (§3.7) and trigger fall-back-to-per-item-clusters.

### Fix contract

- **`FixContract` interface** — the `Fix(ctx, cluster Cluster) (FixResult, error)` surface that `internal/lifecycle/fixLocked` consumes.
- **`opus[1m]` orchestrator dispatcher** — primary provider; runs in the operator's worktree; agent does its own `git commit`.
- **Fix output validator** — Fix contract invariants per §5: schema-conformant JSON; every claimed `commit_shas[i]` is reachable on the branch; no orphan commits (every commit on the branch is claimed by exactly one item). Violations trip `CONTRACT_FIX_MALFORMED` / `CONTRACT_FIX_ORPHAN_COMMIT` / `CONTRACT_FIX_UNREACHABLE_SHA` (§3.7) and flip the affected items to `Disposition.Kind = failed`.
- **Disposition+evidence audit** — Fix contract post-condition rules (`CONTRACT_FIX_AUDIT_FAILED` trip).
- **EscalationSink wiring** — the fix contract handles `escalated` disposition by writing a per-item escalation record; the cross-cutting `escalate_if_needed` hook in `internal/lifecycle` then surfaces it via the `EscalationSink`.

### Planned — RCA / issue-analysis pass (post-MVP, under design)

A future enhancement, **not** in the parity MVP and **not yet ratified**: an RCA / issue-analysis step that *accompanies the cluster pass* to assess each reported review item's true **scope, impact, and nature** before fix dispatch — feeding richer context into the fix contract, and potentially gating which clusters are worth a fix attempt at all. Candidate shapes (to be settled in a dedicated brainstorm): extend the cluster contract's output schema with per-cluster RCA metadata, or insert a dedicated analysis contract between `cluster` and `fix`. Drawn here only as forward context; the design is tracked separately and must be brainstormed before this L3 is drawn.

### Cross-cutting components

- **Per-contract config loader** — reads the `[agents.cluster]` and `[agents.fix]` TOML sections; resolves `--cluster-model` / `--fix-model` flag overrides; provides the `Contract*` constructors with their provider chains.
- **Token-usage JSONL emitter** — appends one line per agent invocation to `$XDG_STATE_HOME/prgroom/usage.jsonl`. Schema per §5: `{ts, pr, contract, provider, model, input_tokens, output_tokens, duration_ms, outcome}`. MVP does no aggregation — the file is the baseline data; analysis is a v2 deferral.
- **Subprocess lifecycle wrapper** — owns the `exec.CommandContext` plumbing for `claude -p` / `codex exec` / `opencode run` / `ollama`; ctx-aware kill on cancellation; stdin/stdout pipe management; per-contract time-budget enforcement.

## Out of scope for this L3 (when drawn)

- **The agent CLIs themselves** — `claude -p`, `codex exec`, and `opencode run` are external systems (L1 / L2). This L3 zooms inside `internal/agent`, not inside the agent binaries.
- **Prompt template content** — the prompts themselves are version-controlled artifacts under `internal/agent/prompts/`; the L3 component view shows the dispatcher and validator components, not the prompt text.
- **`prsession.Store` interactions** — agent dispatch does not read or write `prsession.Store` directly. `internal/lifecycle` is the sole consumer of the `Store`; `internal/agent` consumes only the items / clusters passed in by lifecycle.

## Cross-references

- **Container view**: [`c4-l2-container.md`](c4-l2-container.md)
- **Lifecycle that consumes these contracts**: [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) (see `cluster` and `fix` Rel edges into `internal/agent`)
- **Source spec**: [Section 5 — Agent dispatch internals (named contracts)](../../plans/2026-05-12-prgroom-cli-design.md)
