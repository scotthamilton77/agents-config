# PDLC Orchestrator — C4 Level 1: System Context

> **Up**: [index](index.md)
> **Source bead**: `agents-config-wgclw.2.1`
> **Source spec**: [`2026-05-23-pdlc-orchestrator-core-design.md`](../../specs/2026-05-23-pdlc-orchestrator-core-design.md)

## Glossary

| Term | Meaning |
|---|---|
| Objective | The unified primitive the Orchestrator tracks from `CANDIDATE_UOW` to a terminal lifecycle stage. The same record wears different names at different stages (Candidate UoW, Agent-Worthy, Executable, etc.). See `CONTEXT.md > Objective`. |
| Idea | A pre-Objective primitive in the Holding Place pipeline (Capture → Groom → Shape → Promote). Distinct from Objective; not tracked by the Orchestrator until promoted. See `CONTEXT.md > Idea`. |
| Work Tracker | The external system that holds Objective identity, structural graph, lifecycle_status, and spec body. `bd` is the reference adapter. |
| Holding Place | The peer service for the Idea pipeline; the Orchestrator interacts with it via exactly two call types (promote and create_idea). |
| Lifecycle Stage | The Orchestrator-owned position of an Objective in the PDLC FSM (e.g. `CANDIDATE_UOW`, `IMPLEMENTING`, `MERGED`). Named English constants only; the canonical list is in the [index](index.md#conventions). |
| `config_hash` | Hash of the project-config TOML in effect at a tick; pinned on every Session at dispatch so reap can detect mid-flight config drift. |
| `needs_reconcile` | An Orchestrator-only flag — NOT a lifecycle stage — raised when the reconcile step cannot mechanically determine the correct mapping; surfaces on `pdlc health` for human disposition. |

## Purpose

Place the PDLC Orchestrator in its environment. Answers: *what is the system, who uses it, and what other systems does it talk to?* It is the most zoomed-out view in the artifact set — every other diagram drills deeper.

## Diagram

```mermaid
C4Context
    title PDLC Orchestrator — System Context (C4 L1)

    Person(operator, "Developer / Operator", "Invokes pdlc commands; reviews pdlc health; signs off at AGENT_WORTHY and PR_HUMAN_HOLD; resolves needs_reconcile flags")

    System(pdlc, "PDLC Orchestrator", "Drives Objectives through the PDLC FSM via tick-based dispatch and reap; owns lifecycle_stage, strike counters, sessions, leases")

    System_Ext(tracker, "Work Tracker (bd)", "Source of truth for Objective identity, structural graph, lifecycle_status, spec body, priority")
    System_Ext(holding, "Holding Place", "Peer service for Ideas; orchestrator calls promote(idea_id) and create_idea(decomposition_of) only")
    System_Ext(git, "Git + worktrees", "Hosts per-attempt worker branches under pdlc/<objective_id>/<lifecycle_stage>/<attempt>; merge target")
    System_Ext(ci, "CI provider", "Runs mechanical gates on PRs during PR_VALIDATION")
    System_Ext(agents, "AI agent runtimes", "Claude Code, Codex CLI, Gemini CLI — invoked by Worker subprocesses to perform gate work")
    System_Ext(cron, "Cron scheduler", "Triggers pdlc tick on the project-config cadence")
    System_Ext(config, "project-config files", "TOML on disk; carries every PDLC parameter; pinned per-Session by config_hash")

    Rel(operator, pdlc, "Runs pdlc tick / health / objectives; signs off at human gates")
    Rel(operator, holding, "Captures Ideas via HoldingPlace-CLI", "originates pre-Objective work")
    Rel(operator, tracker, "Creates Idea-less Objectives directly: bugs, chores, sibling captures", "originates work")
    Rel(cron, pdlc, "Triggers pdlc tick", "cron")
    Rel(config, pdlc, "Provides config_hash-stamped configuration", "read at tick start")

    Rel(pdlc, tracker, "Reads Objectives + structural graph; writes lifecycle_status projection under CAS")
    Rel(pdlc, holding, "promote / create_idea", "exactly 2 call types")
    Rel(pdlc, git, "Creates worker branches; validates base-commit descent; performs MERGING")
    Rel(pdlc, ci, "Pushes PRs; consumes mechanical-gate verdicts at PR_VALIDATION")
    Rel(pdlc, agents, "Spawns Worker subprocesses (via JobSupervisor — internal)")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Element notes

### People

- **Developer / Operator** — the human at the wheel. Four load-bearing interactions:
  - **Originating work** — the operator is the source of all new units of intent the system tracks. Two paths exist depending on the maturity of the thought: capture an `Idea` in the **Holding Place** when the thought needs Grooming and Shaping before it can be specified, or create an *Idea-less Objective* directly in the **Work Tracker** for obvious work (bug with clean repro, chore, dependency bump, sibling capture discovered mid-implementation). Both paths converge at `CANDIDATE_UOW` per Law L6 — Ideas reach it via Holding-Place promotion, Idea-less Objectives arrive there directly. The Orchestrator observes both via Discovery on the next tick. Programmatic creation by formulas, hygiene sweeps, or Autopsy routes 4 & 5 is the same shape and routes through the same surfaces; "operator" here is human-or-agent.
  - **Ad-hoc command invocations** (`pdlc tick`, `pdlc health`, `pdlc objectives show <id>`, `pdlc reconcile`, `pdlc objectives unfreeze`). The CLI is the entire user-facing surface for PDLC itself; there is no daemon and no dashboard.
  - **Human signoffs** at the two human gates the FSM mandates: `CANDIDATE_UOW → AGENT_WORTHY` (Spec signoff) and `PR_HUMAN_HOLD → MERGING` (approval before merge).
  - **`needs_reconcile` disposition** when the Orchestrator surfaces an Objective it could not reconcile mechanically (terminal-disposition classifier ambiguous; fingerprint mismatch unresolved).

### External systems

- **Work Tracker (bd)** — the canonical authority on *what Objectives exist*. The Orchestrator never invents Objectives; it observes them via the Discovery Sweep and mirrors their structural graph. Reparenting, child creation, dependency edits, and spec-body changes flow through bd first; the Orchestrator picks them up on the next tick. Per Law L8, bd is the *reference adapter* for the WorkTracker protocol — future trackers conform to the protocol, not the other way around.

- **Holding Place** — a peer service for the pre-Objective Idea pipeline (Capture → Groom → Shape → Promote). The Orchestrator's interaction with it is restricted to **exactly two call types**: `promote(idea_id) → objective_id` and `create_idea(decomposition_of=container_id) → idea_id`. The Orchestrator never `tick`s the Holding Place; Ideas are a distinct primitive with qualitatively different mechanics (Capture is one-shot and non-interrogative, Grooming is a batch ceremony, Bucket and Killed-without-Spec are Idea-only states) and reusing the Objective primitive for them would bloat orchestrator state with fields nil for most records.

- **Git + worktrees** — every Worker operates on its own branch named `pdlc/<objective_id>/<lifecycle_stage>/<attempt_number>`. Branches descend from a `worktree_base_commit` pinned at fork; reap validates descent before accepting work. The Orchestrator performs the merge itself at `MERGING`.

- **CI provider** — runs the mechanical gates on PRs during `PR_VALIDATION` (build, test, lint, coverage, security scan). The Orchestrator pushes the PR and consumes the verdicts; it does NOT re-implement CI gates inside its own tick loop.

- **AI agent runtimes** — Claude Code, Codex CLI, Gemini CLI. Workers (orchestrator-internal) shell out to these runtimes to perform the actual gate work (test-authoring, implementation, review, RCA). The Orchestrator does not care which runtime a Worker uses — the persona contract is what matters.

- **Cron scheduler** — production trigger for `pdlc tick`. Cadence lives in project-config. The cron-driven invocation is the same code path as a human-invoked tick; no daemon, no event loop.

- **project-config files** — versioned TOML on disk. Every PDLC parameter (tick budget, Reviewer Agent list, Sizing Gate weights and thresholds, coverage thresholds, retry budgets, `approval_required` defaults, aging-nag thresholds, cron cadence) lives here. Each tick computes a `config_hash` at start; every Session pins the hash at dispatch; reap validates the pin matches.

## What this diagram does NOT show

- Anything inside the PDLC Orchestrator boundary — those are containers (L2) and components (L3).
- The internal mechanics of any external system (bd's storage, the CI provider's pipelines, the agent runtimes' internals).
- Failure paths, retry behaviour, lifecycle-stage transitions. Those live in [`sequences.md`](sequences.md) and [`state-machine.md`](state-machine.md).
- Deployment topology (host count, process layout, filesystem layout). That lives in [`c4-deployment.md`](c4-deployment.md).

## Cross-references

- **Next**: [C4 L2 — Container](c4-l2-container.md) — opens the PDLC Orchestrator boundary
- **Companion source**: orchestrator core design spec §§ [Holding Place handoff](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#holding-place-handoff), [State Ownership](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#state-ownership), [The Process Model: CLI-driven Tick](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#the-process-model-cli-driven-tick)
- **Glossary**: `CONTEXT.md` entries for *Objective*, *Idea*, *Holding Place*, *Work Tracker*
