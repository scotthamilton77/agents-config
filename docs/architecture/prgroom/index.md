# prgroom CLI — HLD Artifact Index

> **Source bead**: `agents-config-fca6.12`
> **Subsystem**: prgroom — PR-grooming CLI (`agents-config-fca6` epic)
> **Companion design**: [`design.md`](design.md) — the consolidated, evergreen design these artifacts visualise; the dated, point-in-time proposals that seeded it live under `docs/plans/` and `docs/specs/`
> **Glossary**: per-artifact short glossaries appear at the top of each file
> **Status**: under construction

## Glossary (subsystem-wide terms used across this artifact set)

| Term | Meaning |
|---|---|
| HLD | High-Level Design — evergreen reference material describing how a subsystem is meant to be structured and behave. This folder *is* the HLD set for prgroom. |
| C4 | A model for visualising software architecture in four levels (Context, Container, Component, Code); see [c4model.com](https://c4model.com). This folder uses L1, L2, L3, and Deployment. L4 (code) is intentionally absent. |
| prgroom | The PR-grooming CLI — a uv-installed Python console-script that owns the deterministic PR-grooming work, driven by the thin `monitor-pr` supervisor skill. Replaces the legacy `wait-for-pr-comments` (→ `monitor-pr`) and `reply-and-resolve-pr-threads` (deleted; work absorbed here) skills (see [`cutover-runbook.md`](cutover-runbook.md)). Phase-orchestration moves from agent prose into deterministic code. |
| Verb | A prgroom subcommand. The MVP verb set is `poll`, `cluster`, `fix`, `push`, `rereview`, `reply`, `resolve`, `resolve-escalated`, `wait`, `status`, `run`, `sweep`. (`cap-guard` is an internal pre-push pipeline step, **not** a subcommand. `verify` is a designed, not-yet-implemented pipeline step — see the fix↔verify subsystem status row below.) |
| Phase | A position in prgroom's lifecycle for a single PR-grooming session. Each verb advances or operates within a phase; the run verb chains verbs to traverse phases. |
| Round | A single review-iteration loop. Built pipeline steps in order (`lifecycle/run.py::_build_pipeline`): poll → cluster → fix → cap-guard → push → reply → resolve → rereview (`rereview` runs last, guarded). The outer bound today is the PR-review retry budget `pr_review_retries` (default 5, 0-indexed `pr_review_retries_used` counter): an exhausted budget escalates to `human-gated` with `LIFECYCLE_PR_REVIEW_EXHAUSTED`. |
| Fix↔verify subsystem status | The `verify` step, `VerifyVerdict`, `verify_checklist`, and `fix_verify_retries` terms below are **design-ratified, not implemented** (see [`c4-l3-verify.md`](c4-l3-verify.md)): no `verify` field exists on `PRGroomingState`, no `[verify]` config table, no `LIFECYCLE_FIX_VERIFY_EXHAUSTED` error code, and `_build_pipeline` has no `verify` step. Built to target: `GateStrength` with validated `Disposition.gate`, and the outer `pr_review_retries` budget with `LIFECYCLE_PR_REVIEW_EXHAUSTED`. Treat the remaining entries as target design, not current behavior. |
| `verify` step | The mechanical gate of record. A pre-push `VerbStep` designed to insert between `fix` and `cap-guard` that would run the operator-configured tier command (whole-branch, via `proc.CommandRunner`) to confirm the branch is sound before a push elicits another review round. No-ops when there are no queued fix commits; on inner-budget exhaustion it would flip `phase = HUMAN_GATED` (identical refusal mechanism to cap-guard). See [`c4-l3-verify.md`](c4-l3-verify.md). |
| `GateStrength` | The verify tier enum (`StrEnum`): `FULL = "full"` / `LITE = "lite"`. The whole-branch tier is the strongest `Disposition.gate` across the clean `FIXED` items (any `full` ⇒ full, else `lite`); `Disposition.gate` is typed/validated against it. |
| `VerifyVerdict` | The batch-level verify result persisted on `PRGroomingState` (`verify: VerifyVerdict \| None`): `result` (`"passed"`/`"failed"`), `tier` (`GateStrength`), `retries_used`, `gate_output_ref`, `decided_at`. Additive, omit-when-`None`, so `schema_version` stays `1` (parallels `pending_memory`). |
| `verify_checklist` | The required artifact the armed fix agent emits in `FixOutput` — what its own completion gate ran and the result (the agent's *claim*). On a batch with `FIXED` items, a missing/malformed `verify_checklist` is a `CONTRACT_FIX_AUDIT_FAILED` (the item flips to `FAILED`). It is a forcing function + evidence trail, NOT byte-compared against prgroom's authoritative mechanical gate (trust-but-verify). |
| `fix_verify_retries` / `pr_review_retries` | The two retry caps. **Inner** `fix_verify_retries` (default `2`) bounds the fix↔verify convergence loop's repair re-fixes within one cycle; exhaustion ⇒ `LIFECYCLE_FIX_VERIFY_EXHAUSTED`. **Outer** `pr_review_retries` (default `5`; initial push + 5 fix-pushes = 6 pushes) bounds review-eliciting pushes across cycles; exhaustion ⇒ `LIFECYCLE_PR_REVIEW_EXHAUSTED`. Both escalate to `human-gated` (`LIFECYCLE_CAP` tier, exit 0) and re-arm by raising the relevant knob (entry-probe) or by `poll` observing an external fix. |
| Disposition | The fix contract agent's per-comment classification: `fixed` / `already_addressed` / `skipped` / `deferred` / `wont_fix` / `escalated` / `failed`. Per Section 5 of the design reference. |
| Quiescence | A definite end-state where no further bot or human reviewer activity is expected; prgroom may safely stop watching the PR. Defined in §4 of the design reference. |
| Cluster contract / Fix contract | The two agent-dispatch contracts defined in §5. **Cluster contract** = `cluster` (cheap grouping; local-first via ollama → claude haiku → codex-mini). **Fix contract** = `fix` (opus[1m] orchestrator that decides disposition AND implements). |
| `prsession.Store` | The state-persistence Protocol defined in §2 of the design reference. MVP default is the `file` adapter (`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`); a `memory` adapter exists for tests; the `bd` adapter is deferred to v2. **Naming-collision note:** this is a per-PR typed K/V store with locking — deliberately NOT named `WorkTracker` because PDLC orchestrator has a `WorkTracker` Protocol that abstracts a genuinely different concept (Objective registry with Discovery / CAS / fingerprinting). The two should not be conflated. |
| `EscalationSink` | The Protocol (Section 5) for surfacing items the fix orchestrator classified `ESCALATE`. Lifecycle-internal — the §1 layout gives escalation no dedicated module. Only `StderrSink` is wired as the production default (`cli.py::_build_sink`); a `FileSink` (JSONL) is implemented in `escalation.py` but not yet exposed via a CLI flag; a `bd` adapter is deferred to v2 and does not exist in code. |

Each artifact file in this folder carries its **own short glossary** at the top, listing the terms used in that specific file with one-line definitions.

## Purpose

This folder is the **high-level design (HLD) artifact set** for the prgroom CLI. It exists to fix the big-picture architecture before fca6.10 (the §3 implementation child) opens, so downstream implementation beads share a single mental model of the system boundary and lifecycle.

These artifacts are **evergreen reference material**: they describe how prgroom is meant to be structured and behave, and are amended in place as the design evolves. They are NOT point-in-time proposals — those live in `docs/plans/` and `docs/specs/` with date-prefixed filenames.

## Scope and non-scope

**In scope** for this artifact set:

- prgroom's place in its surrounding ecosystem (operator, scheduler, GitHub, agent CLIs, prsession state store)
- prgroom's internal containers and their responsibilities at MVP
- prgroom's runtime behaviour: one PR-grooming session's traversal through poll → cluster → fix → cap-guard → push → reply → resolve → rereview → wait (the `verify` step is designed but not yet implemented — see the fix↔verify subsystem status above), including the four canonical flows (happy, bot-silence, PR-review-retry exhaustion, resumability)
- prgroom's lifecycle state machine: phase transitions per §3 and quiescence sub-states per §4
- prgroom's data ownership: what lives in the `prsession.Store`-backed state file vs the PR (GitHub) vs the git remote
- prgroom's deployment topology (single-host MVP; post-MVP markers)


**Out of scope** for this artifact set:

- Code-level (C4 L4) diagrams — C4 itself recommends against drawing this level
- Fully-drawn L3 component diagrams for every internal module — `src/prgroom/lifecycle` is fully drawn at L3 (it's the core of the package); `src/prgroom/agent` and `src/prgroom/prsession` each have a **stub L3 file** establishing the home and expected components, to be filled in when their implementation children open
- The agent runtimes' internals (Claude Code, Codex CLI internals)
- Bead-lifecycle helpers, create-PR, merge, worktree cleanup — these stay in `finishing-a-development-branch` / `merge-and-cleanup` per the MVP scope decision in §1

## Reading order

Newcomers should read in this order; deep contributors may navigate freely.

1. **[C4 L1 — System Context](c4-l1-context.md)** — where does the `prgroom` CLI live? Who talks to it?
2. **[C4 L2 — Container](c4-l2-container.md)** — what is inside the `prgroom` system boundary?
3. **[Sequences](sequences.md)** — how does one PR-grooming session run? Four canonical flows (happy, bot-silence, PR-review-retry exhaustion, resumability).
4. **[State Machine](state-machine.md)** — the six `PRPhase` values from §2, the §3.2 priority-cascade transitions, the `pr_review_retries` exhaustion exit, and the §4.1 quiescence predicate's hard gates
5. **[C4 L3 — Lifecycle](c4-l3-lifecycle.md)** — components inside the lifecycle container: the `_run` control flow at the verb level
6. **[C4 L3 — Verify](c4-l3-verify.md)** — components inside the fix↔verify subsystem: the `verify` step, the mechanical tier gate, the bounded convergence (repair) loop, the trust-but-verify contract, and the two retry caps
7. **[Data View](data-view.md)** — what lives where: state file (PRGroomingState ER) + GitHub state + the status output and escalation event JSON contracts
8. **[C4 Deployment](c4-deployment.md)** — single-host MVP topology; scheduler integration; post-MVP markers

**L3 stub files** — placeholder homes for the remaining containers' component diagrams, to be filled in when their implementation children open:

- **[C4 L3 — Agent dispatch](c4-l3-agent-dispatch.md)** *(stub)*
- **[C4 L3 — PR session store](c4-l3-prsession.md)** *(stub)*

## Artifact synopsis

| File | Status | Synopsis |
|---|---|---|
| [`c4-l1-context.md`](c4-l1-context.md) | drawn | **C4 Level 1** — the `prgroom` CLI in its ecosystem: operator, scheduler (cron / `prgroom sweep`), GitHub (PR + reviews + threads), Claude/Codex/OpenCode agent CLIs, prsession state store (via `prsession.Store` interface), local state file |
| [`c4-l2-container.md`](c4-l2-container.md) | drawn | **C4 Level 2** — separately runnable / persistent units of `prgroom`: the `prgroom` process (single short-lived Python console-script), the local state file (`prsession.Store` file-adapter storage), the local git worktree (where fix commits land), and the agent subprocess (forked per cluster or fix dispatch). Internal modules (`src/prgroom/lifecycle`, `src/prgroom/prsession`, `src/prgroom/agent`, `src/prgroom/gh`, `src/prgroom/git`, etc.) are L3 **components** inside the process, not L2 containers. |
| [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) | drawn | **C4 Level 3** (lifecycle) — components inside `src/prgroom/lifecycle`: the `_run` control flow with verb breakdown (`_poll → _cluster → _fix → cap_guard → _push → _reply → _resolve → _rereview → _wait`), showing `escalate_if_needed` and `request_human_review_if_needed` call sites |
| [`c4-l3-verify.md`](c4-l3-verify.md) | drawn — **designed, 0% implemented** | **C4 Level 3** (fix↔verify subsystem) — the `verify` `VerbStep` designed to insert between `fix` and `cap-guard`: the mechanical tier gate (`GateStrength` whole-branch via `proc.CommandRunner`, the authoritative gate of record), the bounded convergence loop (red gate → temp-file gate output → whole-branch repair dispatch → re-audit → re-gate, bounded by `fix_verify_retries` → `LIFECYCLE_FIX_VERIFY_EXHAUSTED`), the trust-but-verify contract (armed fix agent's `verify_checklist` claim vs prgroom's authoritative confirmation), and the two retry caps (`fix_verify_retries` inner / `pr_review_retries` outer). None of this exists in `packages/prgroom/src/` today — see the file's Status marker. |
| [`c4-l3-agent-dispatch.md`](c4-l3-agent-dispatch.md) | **stub** | **C4 Level 3** (`src/prgroom/agent`) — placeholder; expected components: cluster contract provider chain (ollama → haiku → codex-mini), fix contract opus[1m] orchestrator + EscalationSink wiring, per-contract config loader, token-usage JSONL emitter |
| [`c4-l3-prsession.md`](c4-l3-prsession.md) | **stub** | **C4 Level 3** (`src/prgroom/prsession`) — placeholder; expected components: `prsession.Store` Protocol + adapter registry, file adapter (`$XDG_STATE_HOME/prgroom/...`), memory adapter (tests), transactional verb-level + run-aggregate commit model, schema-migration plumbing for `schema_version` |
| [`c4-deployment.md`](c4-deployment.md) | drawn | **C4 Deployment** — single-host MVP topology: prgroom console-script on operator workstation, scheduler integration (cron / systemd timer / `prgroom sweep` loop), state file on local FS, gh CLI auth, agent-CLI bin presence. Explicit "multi-host POST-MVP" markers. |
| [`sequences.md`](sequences.md) | drawn | **Four sequence diagrams** covering the canonical flows: (1) happy path — push → review → fix → verify → push → quiesce; (2) bot silence — Copilot doesn't engage → `review_start_timeout` auto-decline → quiesce; (3) PR-review-retry exhaustion — `pr_review_retries` spent without quiescence → human-gated (`LIFECYCLE_PR_REVIEW_EXHAUSTED`) + auto-add human-review-required label; (4) resumability — process crash mid-`_wait` → next invocation re-evaluates timeouts from stored UTC timestamps |
| [`state-machine.md`](state-machine.md) | drawn | **Phase graph + quiescence predicate**: the six §2 `PRPhase` values (`idle` / `awaiting-review` / `fixes-pending` / `quiesced` / `human-gated` / `merged`) with their §3.2-priority-cascade transition edges, the `Round` counter loop, the `pr_review_retries` exhaustion exit (`LIFECYCLE_PR_REVIEW_EXHAUSTED`, with `EscalationSink` emit + §4.6 auto-label side-effect), the parallel `fix_verify_retries` exhaustion exit out of `fixes-pending` (`LIFECYCLE_FIX_VERIFY_EXHAUSTED`) via the `verify` step, the resurrection edges from `quiesced` and `human-gated` back into the loop (including the `--pr-review-retries` retry-budget re-arm), and a companion `flowchart` for the §4.1 quiescence predicate's 4 hard gates + idle timer |
| [`data-view.md`](data-view.md) | drawn | **State + contract data**: ER for `PRGroomingState` / `ReviewItem` / `Disposition` / `ReviewerState` / `QuiescenceState`; annotated JSON for the §4.5 `status` output, the Section 5 escalation events, and the §7 fix-contract `memory` channel + `recurrence` snapshot-input (non-persisted boundary shapes) plus the persisted `pending_memory` queue added to the state ER; canonical-ownership boundaries (state-file vs PR vs git) |

## Operational runbooks

Operator-facing procedures (not HLD diagrams) that live alongside this artifact set:

- **[`cutover-runbook.md`](cutover-runbook.md)** — the staged legacy → prgroom migration: drain-before-cutover, the readiness gate for retiring the legacy tooling, and the git-revert rollback / straggler escape hatch. Distils the dated design proposal's migration plan (§6.4–6.6).

## Conventions

- **Diagram notation**: Mermaid throughout, for native GitHub rendering. No SVG artifacts — `.md` files are the deliverable.
  - C4 set uses `C4Context` / `C4Container` / `C4Component` / `C4Deployment` syntax
  - Sequences use `sequenceDiagram`
  - State machine uses `stateDiagram-v2`
  - Data view uses `erDiagram` for entity relationships, `flowchart` and markdown tables for canonical-ownership boundaries, fenced JSON for flat contract objects (`status` output, escalation events)

- **PRPhase values** (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, `human-gated`, `merged`) are the canonical lifecycle phase identifiers throughout the artifact set — used verbatim in the state machine and data-view ER. The canonical reference is [§3.1](design.md). Note: Mermaid `stateDiagram-v2` requires valid identifiers (no hyphens), so the state machine diagram uses underscored node IDs (e.g., `awaiting_review`) aliased to labels matching the canonical hyphenated values.

- **C4 L4 (code) is intentionally absent.** C4 itself recommends against drawing this level for systems where the code is reasonably self-documenting; we follow that guidance.

## Design-reference coupling

Diagrams in this folder are **derived artifacts**. The source of truth is [`design.md`](design.md) (the consolidated, evergreen design reference). Diagrams should cite the design section they visualise (each file does so in its header) and be amended in place when the design changes.

## How these artifacts should be used

- During **decomposition** of fca6 (the prgroom epic): every implementation child filer should read at minimum L1, L2, the happy-path sequence, and the state machine before drafting their bead's Spec, so the bead's scope claim aligns with the system boundary visible at L2.
- During **onboarding**: this is the first thing a new contributor (human or agent) reads to orient themselves in the prgroom subsystem.
- During **drift detection**: if implementation diverges from these diagrams without an amendment to them, that is a signal — either the diagrams need updating or the implementation has wandered. Prefer updating both as a paired commit.

## Provenance

Filed as `agents-config-fca6.12` under the `fca6` epic. This artifact set is the authoritative HLD for the prgroom CLI; it is referenced from the source design plan and will be cited from future implementation beads under fca6.
