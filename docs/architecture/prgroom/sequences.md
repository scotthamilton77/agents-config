# prgroom CLI — Sequence Diagrams

> **Up**: [index](index.md)
> **Previous (reading order)**: [C4 L2 — Container](c4-l2-container.md)
> **Next (reading order)**: [State Machine](state-machine.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md)

## Glossary

| Term | Meaning |
|---|---|
| Cycle | One pass through the lifecycle verbs (`poll → cluster → fix → push → [rereview] → reply → resolve`) followed by either `wait` or terminal exit. `_run` (§3.3) iterates cycles until quiescence or the hard cap. |
| Round | A counter of *review-eliciting pushes prgroom has performed or observed* on the PR. Bumped by `_push` on a successful CLI push and by `_poll` on detection of an external push (SHA transition). Bounded by `max_rounds` (§3.5). |
| Wake event | One of five conditions that exit `_wait` per §4.2: signal-cancel, poll-error, phase-moved, quiescence-trips, or (intentionally absent in MVP) hard wait-timeout. |
| Disposition | The fix contract agent's per-comment classification: `fixed`, `already_addressed`, `skipped`, `deferred`, `wont_fix`, `escalated`, `failed`. |
| `prsession.Store` | The per-PR state store Protocol (§2). The pseudonym `state` in the diagrams below is shorthand for an in-memory `PRGroomingState` value backed by the file adapter's `read`/`write` operations under `flock(2)`. |

## Purpose

Four sequence diagrams covering the canonical PR-grooming flows from operator push through to terminal exit:

1. **Happy path** — push → review → fix → push → quiesce
2. **Bot silence** — Copilot doesn't engage → `review_start_timeout` auto-decline → quiesce
3. **Hard cap** — three rounds without quiescence → human-gated + `human-review-required` label
4. **Resumability** — process crash mid-`_wait` → next invocation re-evaluates timeouts from stored UTC timestamps

Together they answer: *who calls whom, in what order, with what concurrency control, and where do the failure branches live?* Lifecycle-stage transitions, the strike-vs-non-strike taxonomy, and the full phase graph live in [`state-machine.md`](state-machine.md).

---

## Sequence 1 — Happy path

One PR's grooming session from initial push through to quiescence. Three cycles shown: the first triggered by the initial push, the second triggered by Copilot review comments, the third concluding with quiescence. Lock is acquired once by `run()` at the top of `_run` and released only on terminal exit (§3.3).

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant PG as prgroom (_run)
    participant State as prsession state file
    participant GH as GitHub
    participant Cluster as Cluster agent
    participant Fix as Fix agent

    Note over Op,GH: Initial PR push (out-of-band, before prgroom invocation)
    Op->>GH: git push + open PR

    Note over Op,PG: Operator invokes prgroom run PR
    Op->>PG: prgroom run PR --autonomous
    PG->>State: lock(prRef) — acquire flock(2), held until terminal exit
    PG->>State: read — bootstrap zero-value PRGroomingState (schema_version=1, round=0)

    rect rgb(245, 245, 255)
        Note over PG,Fix: Cycle 1 — bootstrap + first reviewer round
        PG->>GH: _poll — list comments / reviews / CI / head SHA
        GH-->>PG: items, reviewers requested, CI pending
        PG->>State: write — round=1 (bootstrap anchor), phase=awaiting-review
        Note over PG: _poll observes no fixable items yet — cycle resolver advances to awaiting-review
        PG->>State: write — phase resolution
        PG->>GH: _wait — sleep poll_interval, then re-poll
        loop poll_interval until activity
            PG->>GH: _poll re-check
            GH-->>PG: (eventually) Copilot review with comments
        end
        PG->>State: write — items, reviewers[copilot]=in_progress, last_activity_at updated, phase=fixes-pending
    end

    rect rgb(255, 245, 245)
        Note over PG,Fix: Cycle 2 — cluster + fix + push
        PG->>Cluster: cluster — bundle unprocessed items into fix-clusters
        Cluster-->>PG: clusters (JSON)
        PG->>State: write — clusters recorded
        PG->>GH: _fix prework — fetch PR body / threads / labels for the complete-PR snapshot (§8.1)
        PG->>Fix: fix — dispatch per cluster with the complete-PR snapshot (PR body incl. any Decisions block, plus per-item recurrence for repeat items — §8.1-8.2) (opus[1m])
        Fix-->>Fix: edits files in operator's worktree + git commit per fixed item
        Fix-->>PG: per-item dispositions + commit SHAs + classified memory[] channel (§8.3)
        PG->>State: write — per-item disposition recorded
        PG->>GH: _push — git push fix commits
        PG->>State: write — round=2, last_pushed_head_sha=new
        PG->>GH: _rereview — remove + re-add Copilot reviewer (force re-review)
        PG->>GH: _reply — post replies (incl. CONTEXTUAL memory thread-replies) + PATCH the Decisions block in PR body (§8.3 — gh API edit, NOT a git commit)
        PG->>GH: _resolve — GraphQL resolveReviewThread for fixed / already_addressed items
        PG->>State: write — items.resolved=true for resolved threads
        Note over PG: End-of-cycle resolver: items dispositioned, push happened → phase=awaiting-review (priority 4)
        PG->>State: write — phase resolution
        PG->>GH: _wait — sleep, then re-poll
    end

    rect rgb(245, 255, 245)
        Note over PG,Fix: Cycle 3 — second reviewer round resolves cleanly → quiesce
        loop poll_interval until activity OR quiescence
            PG->>GH: _poll re-check
        end
        GH-->>PG: Copilot final review (APPROVED or COMMENTED-with-no-new-FIX)
        PG->>State: write — reviewers[copilot]=review_found, ci_state=success
        Note over PG: quiescence_predicate(state) → all hard gates pass (G_REVIEWERS, G_CI, G_DISPOSITIONS, G_NO_BLOCKERS) AND idle_threshold elapsed
        PG->>State: write — phase=quiesced, quiescence.quiesced_at=now()
        PG-->>State: Lock released (deferred release on _run return)
    end

    PG-->>Op: exit 0 (terminal-for-CLI: quiesced)
```

### Notes on the happy path

- **One lock per PR for the entire cycle.** `run()` acquires the `prsession.Store` lock once and holds it until terminal exit — minutes to hours depending on reviewer cadence. A concurrent `prgroom run` invocation on the same PR exits immediately with `PRECONDITION_LOCK_HELD` (exit 75). The `status` verb is the lock-free carve-out for diagnostic polling.
- **Round is incremented exactly once per push.** The bootstrap `_poll` sets `round=1` to anchor the counter at the PR's currently observed HEAD; subsequent CLI pushes bump it via `_push`; external pushes bump it via `_poll` SHA-transition attribution. The cap (default 3) counts CLI-observed rounds only — historical out-of-band pushes are invisible.
- **Quiescence is the four hard gates plus the idle timer.** `G_REVIEWERS` (all Required reviewers terminal), `G_CI` (ci_state in {success, absent}), `G_DISPOSITIONS` (every item dispositioned), `G_NO_BLOCKERS` (no escalated / failed items). The idle timer (default 10m) is the soft "let it settle" buffer for slow human reviewers.
- **The fix agent owns its commits.** The fix contract agent runs `git commit` itself inside the operator's worktree; prgroom does the subsequent `git push`. prgroom does not commit, and the fix contract does not push.
- **PR memory rides on the PR, not in prgroom state (§8).** Before each fix dispatch prgroom assembles a complete-PR snapshot — PR body (incl. the prgroom-maintained `## Decisions` block), all threads with full reply-chains, prior-round dispositions, and a per-item `recurrence` signal — so the fresh-context fix agent remembers earlier rounds without calling `gh` (§8.1–8.2). The agent's output carries a classified `memory` channel; prgroom routes CONTEXTUAL entries to the PR at reply time — thread replies for thread-tied notes, and a sentinel-bounded `## Decisions` block (PATCHed into the PR body, **not** committed) for PR-wide decisions, idempotent by `(round, source-item)` (§8.3). Cycle 2 is the first fix round, so its snapshot's `## Decisions` block is still empty and no item carries `recurrence` yet; both fill in on later rounds (cf. the §8.7 worked example).

---

## Sequence 2 — Bot silence (Copilot never engages)

Operator pushed the PR with Copilot requested as a Required reviewer. Copilot never engages within `review_start_timeout` (default 3m). `_poll`'s reviewer-timeout evaluator auto-declines Copilot, the quiescence predicate then trips, and prgroom exits cleanly. No fix work happens.

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant PG as prgroom (_run)
    participant State as prsession state file
    participant GH as GitHub

    Note over Op,GH: PR push with copilot as Required reviewer
    Op->>GH: git push + open PR + request copilot review
    Op->>PG: prgroom run PR --autonomous

    PG->>State: lock(prRef) then read — bootstrap state
    PG->>GH: _poll — initial fetch
    GH-->>PG: no items, reviewers[copilot].status=requested, reviewers[copilot].last_request_at=PR-create-time
    PG->>State: write — round=1, phase=awaiting-review

    PG->>GH: _wait — sleep + re-poll loop
    loop every poll_interval (default 30s)
        PG->>GH: _poll re-check
        GH-->>PG: still no copilot activity
        Note over PG: evaluate_reviewer_timeouts(state):<br/>copilot.status == requested AND last_review_at is zero<br/>AND now() - last_request_at > review_start_timeout (3m)
        PG->>State: write — reviewers[copilot].status=declined<br/>declined_reason="timeout-no-start"<br/>declined_at=now()
        Note over PG: quiescence_predicate(state):<br/>G_REVIEWERS pass (declined satisfies the gate)<br/>G_CI pass (ci_state=success or absent)<br/>G_DISPOSITIONS pass (no items)<br/>G_NO_BLOCKERS pass<br/>idle_threshold elapsed
        PG->>State: write — phase=quiesced, quiescence.quiesced_at=now()
        Note right of PG: exits the wait loop
    end

    PG-->>State: Lock released
    PG-->>Op: exit 0 (terminal-for-CLI: quiesced)

    Note over Op,PG: prgroom status PR later shows:<br/>copilot.declined_reason="timeout-no-start"<br/>(operator can tell silence from explicit decline)
```

### Notes on the bot-silence path

- **`declined` satisfies `G_REVIEWERS`.** A Required reviewer can reach `declined` three ways: human explicit pass, `review_start_timeout` (this diagram), or `review_finish_timeout` (engaged but never produced a terminal review). All three count as gate-satisfying. The `declined_reason` is preserved for operator inspection.
- **No fix work happens.** With no items, the cycle skips cluster / fix / push / rereview / reply / resolve entirely. The first wake event after timeout is the quiescence trip.
- **Deadlines are derived, never stored.** `now() - last_request_at > review_start_timeout` is computed per-evaluation. This makes the path identical regardless of whether prgroom slept through the timeout in one process or across a crash gap (see Sequence 4).

---

## Sequence 3 — Hard cap (3 rounds without quiescence)

Operator pushed the PR (round=1). Two prgroom-driven fix-push rounds raised it to round=3. The third reviewer pass still produces FIX comments. The pre-push cap guard refuses the would-be fourth push, sets `phase=human-gated`, emits an `EscalationSink` event, raises the `human-review-required` label on the PR, and exits cleanly (exit 0 — graceful terminal).

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant PG as prgroom (_run)
    participant State as prsession state file
    participant GH as GitHub
    participant Sink as EscalationSink
    participant Fix as Fix agent

    Op->>GH: git push + open PR (round will bootstrap to 1)
    Op->>PG: prgroom run PR --autonomous

    PG->>State: lock then read — bootstrap
    PG->>PG: cycle round=2 — _poll → _cluster → _fix → _push
    Note over PG: First fix round commits + pushes
    PG->>GH: rereview, reply, resolve
    PG->>GH: _wait — reviewer activity

    GH-->>PG: Copilot returns with more FIX comments
    PG->>PG: cycle round=3 — _poll → _cluster → _fix → _push
    Note over PG: Second fix round commits + pushes<br/>_push emits stderr warning:<br/>"this push reaches max_rounds=3 —<br/>subsequent fix work will gate to human-gated"
    PG->>GH: rereview, reply, resolve
    PG->>GH: _wait — reviewer activity

    GH-->>PG: Copilot returns AGAIN with more FIX comments
    PG->>GH: _poll — observe items
    PG->>Fix: _fix — the fix contract produces more commits in worktree
    Fix-->>PG: per-item dispositions + commit SHAs
    PG->>State: write — items.disposition recorded

    Note over PG: _push pre-check (§3.5):<br/>has_queued_fix_commits(state) == true<br/>AND state.round (3) >= max_rounds (3)<br/>→ CAP TRIPPED — refuse the push

    PG->>State: write — phase=human-gated<br/>last_error=LIFECYCLE_HARD_CAP_EXCEEDED
    PG->>Sink: emit one Escalation (kind=lifecycle-cap)
    PG->>GH: §4.7 — request_human_review_if_needed(state) → POST add label human-review-required (because state.human_review_label_added was false)
    PG->>State: write — human_review_label_added=true
    PG-->>State: Lock released
    PG-->>Op: exit 0 (graceful terminal — LIFECYCLE_CAP tier)

    Note over Op,PG: Recovery — two orthogonal actions:<br/>(1) escalated items → prgroom resolve-escalated (clears items only, NOT the cap).<br/>(2) the cap → raise --max-rounds and re-invoke run: the §3.3 entry probe re-arms when<br/>last_error==LIFECYCLE_HARD_CAP_EXCEEDED AND the cap no longer trips, re-enters the cycle,<br/>and last_error clears on the next successful cycle. A bare re-run with no raise stays human-gated.<br/>The human-review-required label is a merge constraint, NOT a lifecycle gate —<br/>operator need not remove it to exit human-gated (§4.4).
```

### Notes on the hard-cap path

- **The cap is checked pre-push, inside `_run`.** This way the would-be cap-tripping push is refused rather than uploaded. The commits the fix agent produced sit in the worktree (uncommitted-from-the-remote's-perspective) for the operator to inspect, push manually, or discard.
- **`LIFECYCLE_CAP` exits 0 (graceful terminal).** Distinct from runtime errors that exit non-zero — the cap-trip is a planned terminal outcome, not a failure of prgroom. The scheduler should not retry; the operator decides.
- **Auto-label is gated by `state.human_review_label_added`.** prgroom sets the label exactly once per lifecycle gate; the flag is reset on successful cycle completion so subsequent gates can re-add it. The flag is not a re-entrancy mutex for the lifecycle — re-invoking `run` after operator action is the recovery path, not a label-state machine.
- **The label is a merge constraint, not a lifecycle gate.** Per §4.4 the `human-review-required` label tells `gmxo` / `td39` (future merge-gate consumers) to require human approval; it does NOT block prgroom from running another cycle. Operator clears `human-gated` by resolving the gating items, not by removing the label.

---

## Sequence 4 — Resumability (process crash mid-`_wait`)

prgroom is mid-`_wait` waiting for Copilot to engage. The process dies (operator Ctrl-C that doesn't honor signal handling, machine sleep, OOM kill — any cause). The state file's last successful write is intact. The operator (or scheduler) re-invokes `prgroom run`. Resumed `_wait` re-evaluates per-reviewer timeouts using `now() - last_request_at`, picking up exactly where the prior process left off — including across the crash gap.

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator / scheduler
    participant PG1 as prgroom #1 (first invocation)
    participant PG2 as prgroom #2 (re-invocation)
    participant State as prsession state file
    participant GH as GitHub
    participant OS as OS / kernel

    Op->>GH: git push + open PR (copilot Required)
    Op->>PG1: prgroom run PR
    PG1->>State: lock — flock(2) on fd
    PG1->>State: read then write — bootstrap, round=1, phase=awaiting-review<br/>reviewers[copilot].last_request_at=t0 (RFC3339 UTC)
    PG1->>GH: _wait — poll_interval sleep + re-poll loop
    loop a few iterations
        PG1->>GH: _poll re-check
        GH-->>PG1: no copilot activity
        PG1->>State: write — (no field changes, loop continues)
    end

    Note over PG1,OS: Process #1 dies mid-wait (kill -9 / OOM / panic / power)
    PG1->>OS: process exit
    OS->>State: flock(2) auto-released on fd close<br/>(no stale-lock cleanup needed)
    Note over State: state file unchanged since last successful write<br/>last_request_at=t0 still intact

    Note over Op,PG2: Operator or scheduler re-invokes
    Op->>PG2: prgroom run PR
    PG2->>State: lock(prRef) — acquires immediately (no stale lock to clear)
    PG2->>State: read — full PRGroomingState (incl. last_request_at=t0)
    PG2->>GH: _wait — first iteration enters
    PG2->>GH: _poll re-check
    GH-->>PG2: still no copilot activity
    Note over PG2: evaluate_reviewer_timeouts(state):<br/>computes now() - last_request_at<br/>= (t0 + elapsed-including-crash-gap) - t0<br/>= elapsed-including-crash-gap<br/>which exceeds review_start_timeout (3m)
    PG2->>State: write — reviewers[copilot].status=declined<br/>declined_reason="timeout-no-start"
    Note over PG2: quiescence_predicate → true (same path as Sequence 2)
    PG2->>State: write — phase=quiesced
    PG2-->>State: Lock released
    PG2-->>Op: exit 0
```

### Notes on the resumability path

- **All §4 timestamps stored as absolute UTC (RFC3339).** `last_activity_at`, `quiesced_at`, `last_request_at`, `last_review_at`, `declined_at`. Timeout *deadlines* are derived per-evaluation: `now() - last_request_at > review_start_timeout`. Storing absolute timestamps + deriving deadlines makes the crash gap automatically count.
- **`flock(2)` self-clears on process death.** The OS releases the file lock when the holding process exits via any path — clean exit, signal, kill, panic, power. No stale-lock detection code is needed. The error registry has no `STATE_LOCK_STALE` code by design.
- **Same outcome as if the process had never died.** PG2's behaviour is bit-for-bit identical to a hypothetical PG1 that had stayed alive through the same wall-clock interval. Resumability is a §4 invariant, not a separate recovery mode.
- **Config-change semantics are friendly.** If the operator raises `review_start_timeout` mid-flight (TOML edit), the next `_poll` evaluation reads the new value — a reviewer who would have been auto-declined at 3m gets the extension. Operator intent always wins because deadlines aren't frozen at start-time.

---

## Pending design that will reshape these flows

**An RCA / issue-analysis pass is under design** (tracked separately; not yet ratified, not in the parity MVP). It would *accompany the cluster pass* — assessing each review item's true scope, impact, and nature before fix dispatch — and feed richer context into the fix step, potentially gating which clusters are worth a fix attempt at all. Candidate shapes (to be settled in a dedicated brainstorm): extend the cluster contract's output schema with per-cluster RCA metadata, or insert a dedicated analysis step between `cluster` and `fix`. **When that lands, Sequences 1–3 will gain a pre-/intra-cluster analysis interaction and the `cluster → fix` handoff will change shape.** See [`c4-l3-agent-dispatch.md`](c4-l3-agent-dispatch.md) for the structural counterpart of this note.

## What these diagrams do NOT show

- **Phase transitions and the strike-vs-non-strike taxonomy.** The phase graph (`idle` ↔ `awaiting-review` ↔ `fixes-pending` ↔ `quiesced` / `human-gated` / `merged`) and the quiescence sub-states live in [`state-machine.md`](state-machine.md).
- **The full failure-tier registry.** All seven tiers (`PRECONDITION_*`, `RUNTIME_*`, `CONTRACT_*`, `STATE_*`, `LIFECYCLE_*`) with their exit codes, escalation, and scheduler-retry semantics live in source spec §§3.6–3.7. Sequence 3 shows the `LIFECYCLE_CAP` happy-path exit; the runtime tiers are not drawn here.
- **CAS aborts and retries inside `prsession.Store`.** The MVP `file` adapter uses `flock(2)` + atomic rename, not CAS — concurrent verbs on the same PR exit with `PRECONDITION_LOCK_HELD` rather than abort-and-retry. (PDLC orchestrator's `WorkTracker` uses CAS; prgroom's `prsession.Store` does not. Different shape for different needs.)
- **Per-item disposition mechanics inside the fix contract.** The disposition decisions (`fixed` / `already_addressed` / `skipped` / `deferred` / `wont_fix` / `escalated` / `failed`) and their evidence requirements live in source spec §5 (fix contract audit rules).
- **Component-level mechanics inside the prgroom package.** See [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) for the components that execute these sequences.

## Cross-references

- **Companion structural views**: [`c4-l2-container.md`](c4-l2-container.md), [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md)
- **Companion state view**: [`state-machine.md`](state-machine.md)
- **Companion data view**: [`data-view.md`](data-view.md)
- **Source spec**: source spec §§ [Section 3.3 `run` aggregate verb algorithm](../../plans/2026-05-12-prgroom-cli-design.md), [Section 3.5 Hard-cap behavior](../../plans/2026-05-12-prgroom-cli-design.md), [Section 4 Quiescence model](../../plans/2026-05-12-prgroom-cli-design.md), [Section 4.7 Auto-request human review](../../plans/2026-05-12-prgroom-cli-design.md)
