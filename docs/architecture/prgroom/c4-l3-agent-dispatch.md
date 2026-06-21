# prgroom CLI — C4 Level 3: Agent Dispatch *(stub)*

> **Up**: [index](index.md)
> **Source bead**: `agents-config-fca6.12`
> **Source design**: [design.md](design.md) — §5 (Agent dispatch) + §7 (PR memory)
> **Container**: `src/prgroom/agent/` inside the prgroom package (see [`c4-l2-container.md`](c4-l2-container.md))
> **Status**: **STUB** — placeholder pending the `src/prgroom/agent` implementation bead. The **Fix contract** deltas below (armed fix agent, `verify_checklist`, repair dispatch) are design-ratified by [design.md](design.md) §5–§6; the fix↔verify convergence loop and the mechanical gate of record are owned by its sibling [`c4-l3-verify.md`](c4-l3-verify.md).

## Why this is a stub

Section 5 of the design reference is ratified at the contract level (the cluster contract and fix contract; provider chains; per-contract config; token-usage logging). The internal component breakdown of `src/prgroom/agent/` is not yet pinned at the same implementation-readiness level as `src/prgroom/lifecycle/` (drawn in [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md)) because no `[Impl]` child bead has opened against `src/prgroom/agent/` yet.

This stub establishes the file's home and the components the eventual drawing must cover. When the impl bead opens, this file gets re-drawn at the same fidelity as the lifecycle L3.

## Expected components (when drawn)

The diagram should cover these named units inside `src/prgroom/agent/`:

### Cluster contract

- **`ClusterContract` Protocol** — the `cluster(items: list[ReviewItem]) -> list[Cluster]` surface that `src/prgroom/lifecycle._cluster` consumes.
- **Provider chain dispatcher** — the fallback ladder. Try the primary; on failure-or-malformed-output, fall to the next. Default chain: `ollama+Gemma` → `claude haiku` → `codex-mini`. Per-provider TOML config for model, timeout, prompt template.
- **Per-provider invokers** — one per `claude`, `codex`, `opencode`, `ollama` subprocess shape. Each owns its own stdin/stdout serialisation and timeout.
- **Cluster output validator** — Cluster contract invariants per §5: schema-conformant JSON AND every input item appears in some cluster. Violations trip `CONTRACT_CLUSTER_MALFORMED` or `CONTRACT_CLUSTER_COVERAGE` (§3.6) and trigger fall-back-to-per-item-clusters.

### Fix contract

- **`FixContract` Protocol** — the `fix(cluster: Cluster) -> FixResult` surface that `src/prgroom/lifecycle._fix` consumes. Input carries the complete-PR snapshot (`pr_detail_path`, including the `## Decisions` block) plus a per-item `recurrence` object for items with a prior disposition (§7.1–7.2); the agent never calls `gh`.
- **`opus[1m]` armed fix agent dispatcher** — primary provider; runs in the operator's worktree; agent does its own `git commit`. Launched top-level via `claude -p` (**NOT** a nested sub-agent), so it can safely orchestrate sub-agents — the await-own-child footgun does not apply. Its allow-list is the full implementation set (broad `Bash`, `Task`, `Skill`, …), so the agent runs its **own completion gate** (tests/build/lint via its skills/sub-agents) rather than acting as a muzzled `Read Edit Write Bash(git *)` editor. A configurable allow/deny aggregation layer governs the concrete tool set.
  - **SECURITY (residual risk).** A headless `--permission-mode dontAsk` process with broad shell, running on a branch whose review threads carry **attacker-authored text**, is a prompt-injection surface. Mitigated by worktree-trust (the agent runs in the operator's already-trusted worktree) and operator opt-in (autonomous grooming is a deliberate choice); documented as an accepted residual risk, not a blocker.
- **Fix output validator** — Fix contract invariants per §5: schema-conformant JSON; every claimed `commit_shas[i]` is reachable on the branch; no orphan commits (every commit on the branch is claimed by exactly one item). Violations trip `CONTRACT_FIX_MALFORMED` / `CONTRACT_FIX_ORPHAN_COMMIT` / `CONTRACT_FIX_UNREACHABLE_SHA` (§3.6) and flip the affected items to `disposition.kind = failed`.
- **Disposition+evidence audit** — Fix contract post-condition rules (`CONTRACT_FIX_AUDIT_FAILED` trip).
- **`verify_checklist` validator** — the fix output carries a **required** `verify_checklist` artifact: the armed fix agent's own completion-gate result (what it ran and the outcome). On a batch with `FIXED` items, a missing or malformed `verify_checklist` is a contract-audit failure (`CONTRACT_FIX_AUDIT_FAILED` → the item flips to `disposition.kind = failed`). The artifact is the agent's **claim** — a forcing function (the contract compels self-gating) and evidence (an audit trail); it is **not** byte-compared against the mechanical result. prgroom's mechanical `verify` step is authoritative (the independent gate of record; see [`c4-l3-verify.md`](c4-l3-verify.md)).
- **Repair dispatch** — a whole-branch **repair** mode of the fix contract, invoked by the fix↔verify convergence loop on a red mechanical gate. Distinct from the per-cluster fix: it targets the whole branch (a gate failure is a branch property, not attributable to one cluster), uses the `fix-repair` prompt template, and takes an optional `verify_failure_path` input (the temp file holding the gate's captured `stdout`/`stderr`/exit code). The commit-attribution audit is **adapted** — the orphan/sha audit attributes the repair's new commits to the verify-repair batch, not to any review item (the standard per-cluster "every commit claimed by some item" rule does not apply to whole-branch repair commits). The loop that drives repair dispatch is owned by [`c4-l3-verify.md`](c4-l3-verify.md).
- **`memory`-channel validator (§7.6)** — the fix output carries an optional classified `memory[]` channel (§7.3 / §7.5): each entry sets exactly one of `content` / `path`, a five-class `classification`, and an optional `target_hint`. Enforces: `classification ∈ {UNIVERSAL, PROJECT, PLANNED, HISTORICAL, CONTEXTUAL}` (unknown → `CONTRACT_AUDIT_FAILED` for that item); a CONTEXTUAL `target_hint` must reference a real thread in the snapshot; non-CONTEXTUAL entries are accepted-but-deferred (logged, not errors). The agent **declares** memory; `src/prgroom/lifecycle` **actuates** the PR write — see [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md).
- **`memory_dir` containment audit (§7.6)** — every `memory_writes` path must resolve inside `memory_dir` (ephemeral within-run scratch, NOT cross-round memory). An escaping path (absolute or `..` traversal) is a security-relevant hard violation: the offending cluster's items flip to `disposition.kind = failed` and an `EscalationSink` event fires. A declared-but-unwritten path is a soft stderr warning, not a failure.
- **EscalationSink wiring** — the fix contract handles `escalated` disposition by writing a per-item escalation record; the cross-cutting `escalate_if_needed` hook in `src/prgroom/lifecycle` then surfaces it via the `EscalationSink`.

### Planned — RCA / issue-analysis pass (post-MVP, under design)

A future enhancement, **not** in the parity MVP and **not yet ratified**: an RCA / issue-analysis step that *accompanies the cluster pass* to assess each reported review item's true **scope, impact, and nature** before fix dispatch — feeding richer context into the fix contract, and potentially gating which clusters are worth a fix attempt at all. Candidate shapes (to be settled in a dedicated brainstorm): extend the cluster contract's output schema with per-cluster RCA metadata, or insert a dedicated analysis contract between `_cluster` and `_fix`. Drawn here only as forward context; the design is tracked separately and must be brainstormed before this L3 is drawn.

### PR-memory routing (§7)

Actuation of the `memory` channel is deliberately **not** an agent-dispatch concern: the agent only *declares* memory; `src/prgroom/lifecycle` performs the two CONTEXTUAL routes (thread reply via `_reply`; thread-less PR-wide decision → `## Decisions` PR-body PATCH via the gh adapter, **not** a git commit). See [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md). The per-item `recurrence` input (above) is also the primary signal the **Planned RCA pass** (above) will consume if/when it lands.

### Cross-cutting components

- **Per-contract config loader** — reads the `[agents.cluster]` and `[agents.fix]` TOML sections; resolves `--cluster-model` / `--fix-model` flag overrides; provides the `Contract*` constructors with their provider chains.
- **Token-usage JSONL emitter** — appends one line per agent invocation to `$XDG_STATE_HOME/prgroom/usage.jsonl`. Schema per §5: `{ts, pr, contract, provider, model, input_tokens, output_tokens, duration_ms, outcome}`. MVP does no aggregation — the file is the baseline data; analysis is a v2 deferral.
- **Subprocess lifecycle wrapper** — owns the `subprocess.run` plumbing for `claude -p` / `codex exec` / `opencode run` / `ollama`; cancellation-aware kill (via the threading.Event cancel-token); stdin/stdout pipe management; per-contract time-budget enforcement.

## Out of scope for this L3 (when drawn)

- **The agent CLIs themselves** — `claude -p`, `codex exec`, and `opencode run` are external systems (L1 / L2). This L3 zooms inside `src/prgroom/agent`, not inside the agent binaries.
- **Prompt template content** — the prompts themselves are version-controlled artifacts under `src/prgroom/agent/prompts/`; the L3 component view shows the dispatcher and validator components, not the prompt text.
- **`prsession.Store` interactions** — agent dispatch does not read or write `prsession.Store` directly. `src/prgroom/lifecycle` is the sole consumer of the `Store`; `src/prgroom/agent` consumes only the items / clusters passed in by lifecycle.

## Cross-references

- **Container view**: [`c4-l2-container.md`](c4-l2-container.md)
- **Lifecycle that consumes these contracts**: [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) (see `cluster` and `fix` Rel edges into `src/prgroom/agent`)
- **Fix↔verify subsystem**: [`c4-l3-verify.md`](c4-l3-verify.md) — owns the convergence loop and the mechanical gate of record that consume the `verify_checklist` claim and drive the repair dispatch (`fix_verify_retries`-bounded; `LIFECYCLE_FIX_VERIFY_EXHAUSTED` on exhaustion).
- **Source design**: [§5 Agent dispatch (named contracts)](design.md)
