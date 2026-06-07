# prgroom CLI — C4 Level 2: Container

> **Up**: [index](index.md)
> **Previous**: [C4 L1 — System Context](c4-l1-context.md)
> **Next (reading order)**: [Sequences](sequences.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md)

## Glossary

| Term | Meaning |
|---|---|
| Container (C4 sense) | A separately runnable process or persistent data store — not a Linux / Docker container. |
| Component | A code module inside a container; appears at C4 L3, not L2. |
| `_run` | The lifecycle aggregator inside the process that holds the per-PR lock for the duration of a full grooming cycle and chains the per-verb `_`-prefixed lifecycle steps. Defined in source spec §3.3. |
| Cluster contract | The agent-dispatch contract for `cluster` — cheap grouping of unprocessed review items. Local-first provider chain: ollama+Gemma → claude haiku → codex-mini. Source spec §5. |
| Fix contract | The agent-dispatch contract for `fix` — `opus[1m]` orchestrator that decides per-comment disposition AND implements the fix. Source spec §5. |
| Fix commit | A commit produced by the fix contract agent inside the operator's working tree, then pushed to the PR branch by the `push` verb. |
| Quiescence | A definite end-state where no further reviewer activity is expected; the `wait` verb returns on observing quiescence (or hard cap). Source spec §4. |

## Purpose

Open the `prgroom` system boundary and show its deployable / runnable units. Answers: *what runs, where does state live, how do the running pieces talk to each other?*

A **container** here is a C4 container: a separately runnable process or persistent data store. The CLI dispatcher, lifecycle aggregator (`_run`), prsession store, agent-dispatch contracts, GitHub adapter, and escalation sink all live inside the single `prgroom` process and are therefore **components** of that container, not containers themselves — they appear at L3. The same goes for the bd adapter (v2): `bd` itself is the external system; the bd-backed `prsession.Store` adapter that would call it is a component inside `prgroom`.

## Diagram

```mermaid
C4Container
    title prgroom CLI — Containers (C4 L2)

    Person(operator, "Operator (human or wrapping agent)")

    System_Boundary(prgroom, "prgroom CLI") {
        Container(prgroom_proc, "prgroom process", "Python console-script (typer root)", "Single terminal process — runs to completion and exits (one run may take seconds, or many minutes under the autonomous wait/iteration loop): parses verb args, acquires per-PR lock via prsession.Store, runs the lifecycle (poll/cluster/fix/push/rereview/reply/resolve/wait or _run), shells out to the agent subprocess, exits. No daemon, no background threads, no shared memory between invocations.")
        ContainerDb(state, "prsession state file", "JSON on local FS", "$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json. Sole survivor of process exit. flock(2) for concurrency; mktemp+rename(2) for atomicity. Schema versioned (schema_version: 1). Hand-edit-safe but not hand-edit-encouraged.")
        Container(agent_proc, "Agent subprocess", "claude -p / codex exec / opencode run", "Short-lived; forked per cluster or fix call. Receives prompt on stdin + context env; emits structured output. Fresh agent context per invocation — no carryover between calls.")
        ContainerDb(worktree, "Operator's git worktree", "git working tree on local FS", "The repo + branch the operator launched prgroom against. The fix contract agent edits + commits here; the push verb pushes commits to origin. prgroom does NOT manage the worktree lifecycle — the operator (or upstream skill) owns create/cleanup.")
    }

    System_Ext(github, "GitHub", "PR + reviews + threads + CI verdicts + human-review-required label")
    System_Ext(gh_cli, "gh CLI auth state", "OS keyring / config — reused via the gh CLI")
    System_Ext(scheduler, "Scheduler", "cron / systemd timer / GHA / prgroom sweep / /loop session")
    System_Ext(bd_store, "bd (beads store)", "External beads store (v2). prgroom's INTERNAL prsession.Store bd adapter persists state in a linked bead's notes; bd itself is the external system. Deferred — not wired in MVP.")

    Rel(operator, prgroom_proc, "Runs prgroom run / status / resolve-escalated", "CLI invocation")
    Rel(scheduler, prgroom_proc, "Triggers prgroom run (or prgroom sweep)", "tick / event")

    Rel(prgroom_proc, state, "Read / atomically rewrite PRGroomingState; hold flock for verb duration", "local FS")
    Rel(prgroom_proc, github, "Polls reviews / threads / comments / CI; posts replies; resolves threads (GraphQL); pushes commits; sets human-review-required label", "gh + git subprocess")
    Rel(prgroom_proc, gh_cli, "Reuses gh auth token + host config", "config file read")
    Rel(prgroom_proc, agent_proc, "Forks per cluster or fix; pipes prompt; reads structured output", "stdin/stdout pipe")
    Rel(prgroom_proc, worktree, "Reads HEAD SHA, branch ref; the fix contract agent commits here when invoked", "git plumbing")
    Rel(prgroom_proc, bd_store, "v2: internal bd adapter reads/writes state via bd notes (linkage label for-pr-<owner>-<repo>-<n>)", "bd CLI (deferred)")

    Rel(agent_proc, worktree, "Fix contract only: edits files + git commit (the agent runs `git commit` itself, not prgroom)", "git from inside agent")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Element notes

### Internal containers

#### `prgroom` process — Python console-script

The whole CLI runs here. Every invocation is **terminal** — it runs to completion and exits (a single `run` may take seconds, or many minutes under the autonomous wait/iteration loop): parse args, acquire the per-PR lock, do the work, release the lock, exit. There is no daemon, no background thread pool, no in-memory cache between invocations. State that must survive an invocation lives in the **prsession state file** (process-owned) or on the PR itself (GitHub-owned).

Internally — at L3 — this process is composed of:

- `src/prgroom/cli.py` — typer root + per-verb command files; loads the `.prgroom.toml` config (per-contract provider chains, hard-cap, reviewer timeouts) and builds the deps surface passed into the lifecycle
- `src/prgroom/lifecycle/` — verb implementations (`_poll`, `_cluster`, `_fix`, `_push`, `_rereview`, `_reply`, `_resolve`, `_wait`), the `_run` aggregator, the `quiescence_predicate` (§4.1 pure function — lives here, not in a separate package), and the `EscalationSink` Protocol + stderr / file / (later) bd adapters
- `src/prgroom/prsession/` — `Store` Protocol + `file` adapter + `memory` adapter (tests) + (v2) `bd` adapter
- `src/prgroom/agent/` — cluster contract and fix contract dispatch with per-contract provider chains
- `src/prgroom/gh/` — GitHub adapter (wraps the `gh` subprocess)
- `src/prgroom/git/` — git plumbing (worktree-aware reads of HEAD / branch ref; push to the PR branch)

These components are drawn out at L3 — `c4-l3-lifecycle.md` is the core view; `c4-l3-prsession.md` and `c4-l3-agent-dispatch.md` are stubs awaiting their implementation children.

#### prsession state file — JSON on local FS

A single per-PR JSON file at `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`). Carries `PRGroomingState` (per the §2 schema): the round counter, per-reviewer state, per-comment disposition, last-poll SHA, last-pushed-head SHA, quiescence state, human-review-label flag, and the last error. Schema is versioned via `schema_version`; unknown versions surface as `STATE_SCHEMA_UNKNOWN`.

Concurrency: `flock(2)` on the file for the verb's duration (the `run` verb holds it for the whole grooming cycle). Atomicity: `mktemp` + `rename(2)` on the same filesystem — readers always observe either the complete prior file or the complete new file; no partial / corrupt JSON from a race. The `status` verb is the **single exception** to the lock-acquire rule (it does an unlocked `read` to stay responsive under long-running `run --autonomous`).

#### Agent subprocess — `claude -p` / `codex exec` / `opencode run`

Forked per agent dispatch. Two contracts share the subprocess mechanism:

- **Cluster contract** (`cluster` verb) — cheap. Local-first provider chain: ollama+Gemma, falling back to claude haiku, falling back to codex-mini. Bundles unprocessed review items into fix-clusters; no per-item disposition decided here.
- **Fix contract** (`fix` verb) — strong. `opus[1m]` orchestrator that decides per-comment disposition (`fixed` / `already_addressed` / `skipped` / `deferred` / `wont_fix` / `escalated` / `failed`) AND implements the fix in the worktree. The agent does its own `git commit`; prgroom does the subsequent `git push`. Its input is a complete-PR snapshot (description incl. the `## Decisions` block, labels, every thread with full reply-chains, prior-round dispositions, per-item `recurrence`) that prgroom assembles immediately before dispatch (§8.1); its output adds a classified `memory` channel that prgroom routes to the PR (§8.3). The agent never calls `gh`.

Each invocation is a **fresh context** — no conversation memory between calls. Per-call token-usage is logged to JSONL (`src/prgroom/agent` emits this) for later baseline analysis; MVP does no aggregation.

#### Operator's git worktree

The repo + branch the operator launched prgroom against. The fix contract agent edits + commits here; the `push` verb pushes commits to origin. **prgroom does NOT manage the worktree lifecycle** — the operator (or upstream skill like `finishing-a-development-branch`) owns create / cleanup. This is a deliberate scope decision per source spec §1 non-goals.

### External systems (carried forward from L1)

- **GitHub** — at L1 this was a single "GitHub" box. At L2 the relationship list expands but the box stays singular; the components inside `prgroom` (`src/prgroom/gh`, `src/prgroom/lifecycle/{_poll,_push,_reply,_resolve,_rereview}`) split the GitHub interactions into REST + GraphQL + label-mutation slices, but those splits live at L3.
- **gh CLI auth state** — unchanged from L1. `prgroom` does not store credentials; it reuses what `gh auth` already established.
- **Scheduler** — unchanged from L1. Whatever drives autonomous mode (cron, systemd timer, GitHub Actions, `prgroom sweep`, a `/loop` Claude Code session) is opaque to `prgroom`.
- **`bd` (beads store)** — unchanged from L1. `bd` is the external store; prgroom's `bd`-backed `prsession.Store` adapter is an internal component (deferred to v2), not an external system. In MVP this box is "drawn for context, not wired".

## Container-relationship discipline (worth memorising)

- **One prsession lock per PR.** Every verb acquires `prsession.Store.lock(pr_ref)` before doing work; the `run` verb holds the lock for the entire grooming cycle. Concurrent invocations on the same PR exit immediately with `PRECONDITION_LOCK_HELD` (exit 75). The `status` verb is the sole carve-out: an unlocked `read` returns a stale-but-atomic snapshot for diagnostic polling.
- **Fresh agent context per dispatch.** The agent subprocess receives only what `prgroom` pipes in. No carryover state, no agent memory between calls. This is what makes the contracts deterministic from the orchestrator's perspective.
- **prgroom owns the prsession state file; the agent owns the worktree edits.** `prgroom` writes the state file from inside `_run`. The fix contract agent writes files + runs `git commit` inside the worktree itself. `prgroom` never commits; the agent never reads / writes the prsession state file.
- **GitHub is the source of truth for review state.** `prsession` mirrors the relevant slice (per-comment disposition, per-reviewer status) but is not authoritative — if `prsession` and GitHub disagree (e.g., operator hand-resolved a thread), the next `poll` reconciles toward GitHub.
- **No daemon, no shared memory.** Crash recovery = re-invoke. The state file plus the PR's GitHub state are sufficient to resume any in-flight cycle. Resumability is a §4 invariant (UTC timestamps; reviewer-timeout evaluated against now, not against process-start).

## What this diagram does NOT show

- Components inside the `prgroom` process — those live in [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) (drawn), [`c4-l3-prsession.md`](c4-l3-prsession.md) (stub), and [`c4-l3-agent-dispatch.md`](c4-l3-agent-dispatch.md) (stub).
- Verb ordering or sequence — see [`sequences.md`](sequences.md) for the four canonical flows.
- Phase transitions and the §4 quiescence sub-states — see [`state-machine.md`](state-machine.md).
- Data schema (`PRGroomingState`, `ReviewItem`, etc.) and the §4.6 status output / §5 escalation event JSON contracts — see [`data-view.md`](data-view.md).
- Where these containers physically run + scheduler integration — see [`c4-deployment.md`](c4-deployment.md).

## Cross-references

- **Previous**: [C4 L1 — System Context](c4-l1-context.md)
- **Next (reading order)**: [Sequences](sequences.md) — the four canonical PR-grooming flows
- **Related**: [C4 L3 — Lifecycle](c4-l3-lifecycle.md) — components inside the `prgroom` process
- **Companion source**: source spec §§ [Section 1 — Architecture overview](../../plans/2026-05-12-prgroom-cli-design.md), [Section 2 — `prsession.Store` interface + state schema](../../plans/2026-05-12-prgroom-cli-design.md), [Section 5 — Agent dispatch internals](../../plans/2026-05-12-prgroom-cli-design.md)
