# prgroom CLI — C4 Level 1: System Context

> **Up**: [index](index.md)
> **Next (reading order)**: [C4 L2 — Container](c4-l2-container.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md)

## Glossary

| Term | Meaning |
|---|---|
| prgroom | The PR-grooming CLI — a single static Go binary that owns the deterministic PR-grooming work, driven by the thin `monitor-pr` supervisor skill. Replaces the legacy `wait-for-pr-comments` (→ `monitor-pr`) and `reply-and-resolve-pr-threads` (deleted; work absorbed here) skills — see §6. |
| Operator | The human (or wrapping AI agent) that invokes `prgroom run` against a PR; reviews `prgroom status`; dispositions `ESCALATE`d items via `prgroom resolve-escalated`. |
| `prsession.Store` (bd adapter, v2) | The deferred `bd`-backed adapter of the `prsession.Store` interface (§2): persists PRGroomingState in a linked bead's notes. MVP default is the `file` adapter on the local filesystem; the `bd` adapter ships in v2. |
| Agent CLI | One of the AI agent command-line tools (`claude -p`, `codex exec`, `opencode run`, local `ollama`) that prgroom subprocesses for the cluster contract and fix contract. The contract — not the runtime — is the API; which runtime serves a contract is TOML-configurable (§5). Each invocation gets a fresh context. |
| Scheduler | Whatever drives autonomous prgroom runs: cron, systemd timer, GitHub Actions, an outer `prgroom sweep` loop, or a `/loop` Claude Code session. prgroom does not care which. |
| Quiescence | The condition under which prgroom may safely stop watching a PR — no further bot or human reviewer activity is expected. Defined in §4 of the source spec. |
| Disposition | The fix contract agent's per-comment classification: `fixed` / `already_addressed` / `skipped` / `deferred` / `wont_fix` / `escalated` / `failed`. |

## Purpose

Place prgroom in its environment. Answers: *what is the system, who uses it, and what other systems does it talk to?* It is the most zoomed-out view in the artifact set — every other diagram drills deeper.

## Diagram

```mermaid
C4Context
    title prgroom CLI — System Context (C4 L1)

    Person(operator, "Operator (human or wrapping agent)", "Invokes prgroom run / status; dispositions ESCALATE items via resolve-escalated; pushes the original PR commits; reviews the human-review-required label")

    System(prgroom, "prgroom CLI", "Go binary that drives a PR through poll → cluster → fix → push → re-review → reply → resolve → wait until quiescence or hard cap; one PR per run, per-PR lock, fresh agent context per dispatch")

    System_Ext(github, "GitHub", "Hosts the PR, its reviews + threads, CI verdicts, and the human-review-required label that prgroom raises on hard-cap or ESCALATE")
    System_Ext(agents, "AI agent CLIs", "Claude Code (claude -p), Codex CLI (codex exec), OpenCode (opencode run), local models (ollama). Subprocessed for the cluster contract and fix contract. Runtime is chosen per-contract in TOML config — the contract is the API, the runtime is swappable. Each call is a fresh, isolated context.")
    System_Ext(scheduler, "Scheduler", "Whatever triggers autonomous runs: cron, systemd timer, GitHub Actions, prgroom sweep, or a /loop Claude Code session. Not strict; not required for interactive mode.")
    SystemDb_Ext(statefile, "Local state file", "$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json — the prsession.Store file-adapter's storage. flock(2) for concurrency; mktemp+rename for atomicity.")
    System_Ext(bd_store, "bd (beads store)", "External work/issue store (beads CLI + Dolt-backed DB). In v2, prgroom's INTERNAL prsession.Store bd adapter persists PRGroomingState in a linked bead's notes field — bd itself is the external system; the adapter is prgroom plumbing (drawn at L3). Shown for forward context; not used in MVP. NOTE: bd is shared but the contracts differ — PDLC orchestrator uses bd as its WorkTracker (Objective registry with Discovery / CAS / fingerprints); prgroom uses bd only as a backing K/V behind prsession.Store.")
    System_Ext(gh_cli, "gh CLI (auth state)", "github.com/cli/go-gh/v2 reuses the existing gh auth token, scopes, and host config. prgroom does not store credentials.")

    Rel(operator, prgroom, "Runs prgroom run / status / resolve-escalated", "tty or subprocess")
    Rel(operator, github, "Pushes the original PR; reviews escalated items; opens / merges the PR", "browser, git, gh")
    Rel(scheduler, prgroom, "Triggers prgroom run (or prgroom sweep)", "cron tick / GHA event / loop iteration")

    Rel(prgroom, github, "Polls comments/reviews/CI; posts replies; resolves threads (GraphQL); pushes fix commits; raises human-review-required label", "gh API via go-gh")
    Rel(prgroom, agents, "Subprocesses cluster and fix; fresh context per call", "stdin/stdout pipe")
    Rel(prgroom, statefile, "Reads + atomically rewrites PRGroomingState; holds flock for the duration of one verb", "local FS")
    Rel(prgroom, bd_store, "v2: internal bd adapter reads/writes state via bd notes (linkage label for-pr-<owner>-<repo>-<n>)", "bd CLI (deferred)")
    Rel(prgroom, gh_cli, "Reuses gh auth state (token + host)", "OS keyring / config file")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Element notes

### People

- **Operator (human or wrapping agent)** — the actor at the wheel. Three load-bearing interactions:
  - **Original PR push** — the operator (or an upstream agent / skill) creates the PR being groomed. prgroom does NOT create PRs; that responsibility stays with `finishing-a-development-branch` and equivalents per the MVP scope decision in §1.
  - **`prgroom run` invocation** — the entry point for grooming a single PR through to quiescence. The same code path serves the interactive `--interactive` flag (operator-at-tty) and the autonomous `--autonomous` flag (scheduler-driven). The CLI is the entire user-facing surface; there is no daemon and no dashboard.
  - **`resolve-escalated` disposition** — when the fix contract classifies a review comment as `escalated`, prgroom surfaces it via the `EscalationSink` and stops attempting to auto-disposition it. The operator picks a terminal disposition (`fixed` / `already_addressed` / `skipped` / `deferred` / `wont_fix`) via `prgroom resolve-escalated <pr> <item-id> --as <disposition>` and the lifecycle continues. This is the primary feedback path from human back into prgroom's lifecycle; the other is raising `--max-rounds` to re-arm a hard-cap gate (§3.5).

  "Operator" includes a *wrapping AI agent* — a thin caller that invokes `prgroom run` and reads its exit code + JSON, exactly as a human at a terminal would. There is **no fix-now / reply-later split**: prgroom drives the full **fix → push → reply → resolve** loop inside a single locked cycle (§3.3 `runLocked`), so each review thread is answered and resolved in the *same* cycle that pushes its fix. Threads are never left dangling for a later pass. (During migration the legacy `reply-and-resolve-pr-threads` skill is **deleted** and `wait-for-pr-comments` is **replaced** by `monitor-pr` — a thin (~50-line) contract-aware supervisor that invokes `prgroom run` and interprets its exit code + JSON. The wrapping skill is a thin caller; the deterministic runtime lives entirely in `prgroom`. See §6.)

### External systems

- **GitHub** — the canonical authority on the PR being groomed. prgroom never invents PR state; it polls reviews + threads + comments + CI verdicts via `gh` API (using `github.com/cli/go-gh/v2`), posts replies, resolves threads via GraphQL `resolveReviewThread`, pushes fix commits the fix contract agent produced, and raises a `human-review-required` label on hard-cap or `escalated` items. The PR itself stays where it is — prgroom never opens or merges PRs (those are out of MVP scope).

- **AI agent CLIs** — `claude -p`, `codex exec`, `opencode run`, and local `ollama`. prgroom shells out to these as subprocesses with a fresh context per call. Which runtime serves a given contract is TOML-configurable per §5 — the contract is the stable API, the runtime is swappable (opencode is an available runtime, not part of the default chain). Two contract types per §5:
  - **Cluster contract** (`cluster` verb): cheap grouping of unprocessed review items into fix-bundles. Local-first chain: ollama+Gemma → claude haiku → codex-mini. No per-item disposition decided here.
  - **Fix contract** (`fix` verb): an `opus[1m]` orchestrator that decides per-comment disposition AND implements the fix in the working tree. The output is a set of commits + a per-comment disposition manifest.
  prgroom does not care which runtime a contract uses; the contract is the API. Per-contract provider chains live in TOML config.

- **Scheduler** — production trigger for autonomous mode. prgroom does not embed a scheduler; the operator picks (cron, systemd timer, GitHub Actions on a schedule, `prgroom sweep` driving a serial loop, or a `/loop` Claude Code session). The interactive code path and the scheduler-driven code path are the same — there is no daemon and no event loop inside prgroom. The §4 quiescence model deliberately blocks on `waitLocked` rather than re-arming externally.

- **Local state file** — `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json` (fallback `~/.local/state/prgroom/`). The `prsession.Store` file adapter's storage. Concurrency control is `flock(2)` on the file; atomicity is `mktemp` + `rename(2)` on the same filesystem. The state file is the *only* persistent prgroom data — there is no database, no cache, no shared volume.

- **`bd` (beads store)** — the external work/issue store (beads CLI + Dolt-backed DB). In v2, prgroom gains an **internal** `prsession.Store` bd adapter that persists `PRGroomingState` in a linked bead's `notes` field, with a linkage label `for-pr-<owner>-<repo>-<n>`. `bd` is the external system; the adapter is prgroom-internal plumbing (it appears as a component at L3, not as its own external box). Shown here for forward context because the `prsession.Store` interface is intentionally adapter-pluggable, but it does not ship in MVP. v2 unlocks survival of operator-machine churn and cross-session visibility via `bd`.

- **gh CLI (auth state)** — prgroom reuses the existing `gh` auth token, scopes, and host config via `github.com/cli/go-gh/v2`. It does NOT store credentials of its own. If the operator can `gh pr view <pr>`, prgroom can talk to GitHub.

## What this diagram does NOT show

- Anything inside the prgroom boundary — those are containers (L2) and components (L3).
- The internal mechanics of any external system (GitHub's API internals, the agent CLIs' model dispatch, `gh`'s auth flow).
- Failure paths, retry behaviour, hard-cap escalation, quiescence sub-states. Those live in [`sequences.md`](sequences.md) and [`state-machine.md`](state-machine.md).
- Deployment topology (host count, scheduler integration, filesystem layout). That lives in [`c4-deployment.md`](c4-deployment.md).
- Data shapes — `PRGroomingState`, the §4.6 `status` output, the §5 escalation event JSON. Those live in [`data-view.md`](data-view.md).

## Cross-references

- **Next**: [C4 L2 — Container](c4-l2-container.md) — opens the prgroom system boundary
- **Companion source**: source spec §§ [Section 1 — Architecture overview](../../plans/2026-05-12-prgroom-cli-design.md), [Section 5 — Agent dispatch internals](../../plans/2026-05-12-prgroom-cli-design.md)
- **Glossary**: [index](index.md#glossary-subsystem-wide-terms-used-across-this-artifact-set)
