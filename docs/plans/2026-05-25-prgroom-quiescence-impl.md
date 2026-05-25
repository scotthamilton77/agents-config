# prgroom Section 4 — Quiescence Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Section 4 (Quiescence model) runtime of the `prgroom` CLI — the quiescence predicate, the `waitLocked` blocking loop, per-reviewer auto-decline timeouts, the human-review merge constraint, the auto-request-human-review behavior, and the `prgroom status --json` auto-merge eligibility contract.

**Architecture:** Pure-function predicates (`quiescencePredicate`, `should_request_human_review`, human-review derivation) sit beneath two integration surfaces — `pollLocked` extensions (engagement detection, reviewer-timeout evaluation, CI-state capture, `LastActivityAt` updates) and `runLocked` integration (auto-label call sites adjacent to the existing `escalate_if_needed` calls, plus `state.HumanReviewLabelAdded` reset on successful end-of-cycle). `waitLocked` is a single new function — a polling loop with five enumerable wake events. The `prgroom status --json` output gains derived `merge_gates` / `human_review` / `auto_merge_eligible` fields computed per-query from existing state.

**Tech Stack:** Go 1.22+, `context.Context` for cancellation, table-driven tests with fakes (no mocks of own code; mocks only at HTTP/git/subprocess boundaries), `time.Time` UTC throughout (resumability invariant), `gh` adapter abstraction (assumed from foundation).

**Spec source:** `docs/plans/2026-05-12-prgroom-cli-design.md` §4 (lines 984-1320), with cross-references into §2 (schema), §3.3 (lifecycle pseudocode), §3.5 (hard cap), §3.6 (failure tiers), §3.7 (exit codes).

> **`<module>` placeholder:** All Go code blocks in this plan use `<module>` as the Go module path (e.g., `"<module>/internal/prsession"`). Before running `go test`, replace `<module>` with the actual module name from the project's `go.mod` file (e.g., `github.com/scotthamilton77/prgroom`). A quick `grep ^module go.mod` gives the exact string.

---

## Prerequisites

This plan executes on top of two earlier beads. Verify each before starting:

1. **Foundation (`agents-config-abn9.8.1`)** — must have shipped:
   - Go module + `cmd/prgroom/` cobra root
   - `internal/prsession/` with `Store` interface, `file` adapter, `memory` adapter
   - `PRGroomingState`, `ReviewerState`, `QuiescenceState`, `ReviewItem`, `Disposition` Go types per §2 — **including** the §4-introduced fields: `PRGroomingState.HumanReviewLabelAdded bool`, `ReviewerState.LastReviewAt`, `ReviewerState.DeclinedAt`, `ReviewerState.DeclinedReason string`, `QuiescenceState.CIState string`, `QuiescenceState.QuiescedAt time.Time`, `ReviewerStatus` enum including `declined`
   - `internal/config/` TOML loader with CLI-flag / env-var / file precedence per §3.5
   - `internal/gh/` adapter abstraction (HTTP boundary only; concrete `gh` CLI shell-out behind interface)
   - `EscalationSink` interface + stderr/file adapters
   - Fit-test harness convention (`*_fit_test.go` per `internal/*` module)

2. **§3 lifecycle implementation bead** (not yet filed at plan-writing time; see fca6 epic) — must have shipped:
   - `internal/lifecycle/run.go` with `runLocked` per §3.3 pseudocode (the 11 sites for `escalate_if_needed` already wired)
   - `internal/lifecycle/poll.go` with `pollLocked` per §3.4 (HEAD-SHA observation, reviewer-state flips, `Round` increments)
   - `internal/lifecycle/end_of_cycle.go` with `resolve_end_of_cycle_phase` per §3.2 priority cascade (priorities 1-4 wired: 1-3 route to `human-gated`, 4 routes to `awaiting-review` on commit-pushed; **priority 5 quiescence is THIS plan's responsibility** — Task 8)
   - `internal/lifecycle/predicates.go` with `has_queued_fix_commits`, `has_required_reviewers_to_refresh`, `new_lifecycle_gate_this_cycle`, `push_uploaded_commits_this_cycle`
   - `internal/lifecycle/errors.go` with `handle_verb_error` returning `Continue` / `Propagate`
   - `internal/lifecycle/escalation.go` with `escalate_if_needed(state)` (per-item dedup via `Disposition.EscalationFiled`; lifecycle dedup via `state.LifecycleEscalationFiled`)
   - `internal/gh/labels.go` may already exist for `gh.RemoveLabel` (used by §3.4 reviewer dance); if so, this plan extends it. If not, this plan adds it (Task 9).

**If any prerequisite is missing, file a blocker and pause.** Do not stub the missing surface — the contract violations cascade and the integration tests will fail meaningfully only against the real surface.

**Worktree:** Per project worktree convention (see `src/user/.agents/rules/worktrees.md` in this repo, deployed to `~/.claude/rules/worktrees.md`), create the worktree at `.claude/worktrees/<branch>` before starting Task 1. Recommended branch: `feat/prgroom-section4-quiescence`.

---

## File Structure

**New files** (created by this plan):

| Path | Purpose |
|------|---------|
| `internal/lifecycle/quiescence.go` | `QuiescenceGate` enum, `quiescencePredicate(state) bool`, `failingGate(state) QuiescenceGate` |
| `internal/lifecycle/quiescence_test.go` | Table-driven gate tests + predicate truth-table |
| `internal/lifecycle/engagement.go` | `isReviewerEngagement(activity, reviewer, lastRequestAt, lastPushAt)` helper |
| `internal/lifecycle/engagement_test.go` | Activity-type / actor-match / timestamp-ordering matrix |
| `internal/lifecycle/reviewer_timeouts.go` | `evaluateReviewerTimeouts(state, cfg, now)` mutating function |
| `internal/lifecycle/reviewer_timeouts_test.go` | Start-timeout, finish-timeout, no-double-decline, config-extension paths |
| `internal/lifecycle/human_review.go` | `DeriveHumanReview(labels []string, approvals []ApprovalRecord)`, `ShouldRequestHumanReview(state *prsession.PRGroomingState)`, `RequestHumanReviewIfNeeded(ctx, state, adder LabelAdder, cfg HumanReviewCfg, write StoreWriter)` |
| `internal/lifecycle/human_review_test.go` | Derivation truth-table (label/approval/Bot-filter), dedup, reset, operator-override |
| `internal/lifecycle/wait.go` | `waitLocked(ctx, pr, state, deps) (*PRGroomingState, error)` |
| `internal/lifecycle/wait_test.go` | Five-wake-event tests with fake clock + fake pollLocked + fake ctx |

**Modified files** (extended by this plan):

| Path | Modification |
|------|---|
| `internal/config/config.go` | Add 5 §4 knobs: `IdleThreshold`, `PollInterval`, `ReviewStartTimeout`, `ReviewFinishTimeout`, `AutoRequestHumanReview` |
| `internal/config/config_test.go` | Precedence tests for the new knobs |
| `internal/lifecycle/poll.go` | §4 add-ons inside `pollLocked`: `LastActivityAt` bump on observed mutations, `CIState` refresh, `evaluateReviewerTimeouts` call, engagement-detection-driven `Status` transitions + `LastReviewAt` updates |
| `internal/lifecycle/poll_test.go` | Tests for each §4 add-on (one per add-on) |
| `internal/lifecycle/end_of_cycle.go` | Add priority-5 quiescence rule to `resolve_end_of_cycle_phase` |
| `internal/lifecycle/end_of_cycle_test.go` | Priority-5 quiescence-trip path + `QuiescedAt` stamp |
| `internal/lifecycle/run.go` | Add `requestHumanReviewIfNeeded(...)` calls (void; mutates `state` via the pointer it already receives) at the 11 dedup-safe sites in `runLocked` adjacent to existing `escalate_if_needed` calls; add `state.HumanReviewLabelAdded = false` to the clear-on-success branch |
| `internal/lifecycle/run_test.go` (or fit-test) | Cap-trip → label-added; reset-on-success → re-add on next trip |
| `internal/gh/labels.go` | Add `AddLabel(ctx, pr, label) error` if missing |
| `internal/gh/labels_test.go` | Fake HTTP transport test for `AddLabel` |
| `internal/status/json.go` (or wherever the foundation's `status` verb lives) | Extend output with `merge_gates`, `human_review`, `auto_merge_eligible`; computed per-query |
| `internal/status/json_test.go` | Golden-file test for the JSON shape (per §4.6 stability commitment) |
| `internal/lifecycle/lifecycle_fit_test.go` (or new) | End-to-end fit-tests: resumability across simulated restart, full lifecycle to quiesced, cap-trip→label-add |

**Untouched** (do NOT modify in this plan): `internal/prsession/` schema or adapters (any schema gap is a prerequisite-bead bug, not this plan's scope). Note: `cmd/prgroom/` verb-logic files are also out of scope — **except** for the CLI flag additions in Task 1 (adding cobra flags for the 5 §4 config knobs is in scope; changing verb behavior is not).

---

## Tasks

### Task 1: Add Section 4 configuration knobs

**Files:**
- Modify: `internal/config/config.go`
- Modify: `internal/config/config_test.go`

**Reference:** §4.3 — precedence is **CLI flag > env var > per-repo `.prgroom.toml` > built-in default** (matches §3.5).

- [ ] **Step 1: Write the failing precedence test**

Append to `internal/config/config_test.go`:

```go
func TestSection4_DefaultsApplied(t *testing.T) {
    cfg, err := config.Load(config.LoadOpts{}) // no flags, no env, no file
    if err != nil {
        t.Fatalf("Load: %v", err)
    }
    if cfg.Quiescence.IdleThreshold != 10*time.Minute {
        t.Errorf("IdleThreshold: got %v, want 10m", cfg.Quiescence.IdleThreshold)
    }
    if cfg.Quiescence.PollInterval != 30*time.Second {
        t.Errorf("PollInterval: got %v, want 30s", cfg.Quiescence.PollInterval)
    }
    if cfg.Quiescence.ReviewStartTimeout != 3*time.Minute {
        t.Errorf("ReviewStartTimeout: got %v, want 3m", cfg.Quiescence.ReviewStartTimeout)
    }
    if cfg.Quiescence.ReviewFinishTimeout != 15*time.Minute {
        t.Errorf("ReviewFinishTimeout: got %v, want 15m", cfg.Quiescence.ReviewFinishTimeout)
    }
    if cfg.Quiescence.AutoRequestHumanReview != true {
        t.Errorf("AutoRequestHumanReview: got %v, want true", cfg.Quiescence.AutoRequestHumanReview)
    }
}

func TestSection4_PrecedenceFlagBeatsEnv(t *testing.T) {
    t.Setenv("PRGROOM_IDLE_THRESHOLD", "20m")
    cfg, err := config.Load(config.LoadOpts{
        Flags: config.Flags{IdleThreshold: ptr(5 * time.Minute)},
    })
    if err != nil {
        t.Fatalf("Load: %v", err)
    }
    if cfg.Quiescence.IdleThreshold != 5*time.Minute {
        t.Errorf("flag should beat env: got %v, want 5m", cfg.Quiescence.IdleThreshold)
    }
}

func TestSection4_PrecedenceEnvBeatsTOML(t *testing.T) {
    dir := t.TempDir()
    tomlPath := filepath.Join(dir, ".prgroom.toml")
    if err := os.WriteFile(tomlPath, []byte(`
[quiescence]
idle_threshold = "1h"
`), 0o644); err != nil {
        t.Fatalf("WriteFile: %v", err)
    }
    t.Setenv("PRGROOM_IDLE_THRESHOLD", "20m")
    cfg, err := config.Load(config.LoadOpts{TOMLPath: tomlPath})
    if err != nil {
        t.Fatalf("Load: %v", err)
    }
    if cfg.Quiescence.IdleThreshold != 20*time.Minute {
        t.Errorf("env should beat TOML: got %v, want 20m", cfg.Quiescence.IdleThreshold)
    }
}

func ptr[T any](v T) *T { return &v }
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/config/ -run 'TestSection4' -v`
Expected: FAIL — `cfg.Quiescence` field does not exist.

- [ ] **Step 3: Add the Quiescence config struct**

In `internal/config/config.go`, add (near the existing `Config` struct):

```go
// QuiescenceConfig holds Section 4 settings. See docs/plans/2026-05-12-prgroom-cli-design.md §4.3.
type QuiescenceConfig struct {
    IdleThreshold          time.Duration `toml:"idle_threshold"`
    PollInterval           time.Duration `toml:"poll_interval"`
    ReviewStartTimeout     time.Duration `toml:"review_start_timeout"`
    ReviewFinishTimeout    time.Duration `toml:"review_finish_timeout"`
    AutoRequestHumanReview bool          `toml:"auto_request_human_review"`
}
```

Add `Quiescence QuiescenceConfig` to `Config`. Add corresponding `Flags` fields (each pointer so unset means "unset"):

```go
type Flags struct {
    // ... existing flags ...
    IdleThreshold          *time.Duration
    PollInterval           *time.Duration
    ReviewStartTimeout     *time.Duration
    ReviewFinishTimeout    *time.Duration
    AutoRequestHumanReview *bool
}
```

Defaults (apply in the loader if no source set the value):

```go
var quiescenceDefaults = QuiescenceConfig{
    IdleThreshold:          10 * time.Minute,
    PollInterval:           30 * time.Second,
    ReviewStartTimeout:     3 * time.Minute,
    ReviewFinishTimeout:    15 * time.Minute,
    AutoRequestHumanReview: true,
}
```

Env-var keys (resolve via the loader's existing env-var lookup helper; if absent, `os.LookupEnv`):

- `PRGROOM_IDLE_THRESHOLD`
- `PRGROOM_POLL_INTERVAL`
- `PRGROOM_REVIEW_START_TIMEOUT`
- `PRGROOM_REVIEW_FINISH_TIMEOUT`
- `PRGROOM_AUTO_REQUEST_HUMAN_REVIEW`

Wire each through the loader's existing precedence chain (CLI flag → env → TOML → default). Durations parse via `time.ParseDuration`; the bool parses via `strconv.ParseBool` (returns error on `os.Getenv` of `"yes"` etc. — accept that for MVP).

- [ ] **Step 4: Wire cobra flags**

In whatever file binds the `run` and `wait` verbs' flags (foundation's `cmd/prgroom/`), add:

```go
runCmd.Flags().Duration("idle-threshold", 0, "quiescence idle-timer threshold (§4.3); 0 = use config/default")
runCmd.Flags().Duration("poll-interval", 0, "wait-loop poll interval (§4.3); 0 = use config/default")
runCmd.Flags().Duration("review-start-timeout", 0, "auto-decline reviewer if no engagement within this window (§4.1); 0 = use config/default")
runCmd.Flags().Duration("review-finish-timeout", 0, "auto-decline reviewer if engaged but not finished within this window (§4.1); 0 = use config/default")
runCmd.Flags().Bool("auto-request-human-review", true, "auto-add `human-review-required` label on lifecycle gating (§4.7)")
```

In the flag-to-`Flags` translation layer, treat duration `0` as "unset" (`Flags.IdleThreshold = nil`); non-zero becomes `ptr(v)`. The bool flag is always set; the way to express "unset" is for the caller to not pass `--auto-request-human-review` at all, which cobra exposes via `cmd.Flags().Changed("auto-request-human-review")`. Use that to decide `nil` vs `ptr(v)`.

- [ ] **Step 5: Run tests, verify pass**

Run: `go test ./internal/config/ -run 'TestSection4' -v`
Expected: PASS, all three tests.

- [ ] **Step 6: Commit**

```bash
git add internal/config/config.go internal/config/config_test.go cmd/prgroom/
git commit -m "feat(prgroom): add Section 4 quiescence config knobs"
```

---

### Task 2: Define quiescence gates + predicate

**Files:**
- Create: `internal/lifecycle/quiescence.go`
- Create: `internal/lifecycle/quiescence_test.go`

**Reference:** §4.1 — four hard gates (`G_REVIEWERS`, `G_CI`, `G_DISPOSITIONS`, `G_NO_BLOCKERS`) + idle timer. `failingGate` names the first failing gate (deterministic ordering — same as the table).

- [ ] **Step 1: Write the failing test**

Create `internal/lifecycle/quiescence_test.go`:

```go
package lifecycle

import (
    "testing"
    "time"

    "<module>/internal/prsession"
)

func TestQuiescencePredicate_AllGatesPassAndIdleElapsed(t *testing.T) {
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        Phase:          prsession.PhaseAwaitingReview,
        LastActivityAt: now.Add(-15 * time.Minute), // idle 15m, threshold 10m
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound},
        },
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
        },
        Quiescence: prsession.QuiescenceState{CIState: "success"},
    }
    cfg := QuiescenceCfg{IdleThreshold: 10 * time.Minute}
    if !QuiescencePredicate(state, cfg, now) {
        t.Errorf("expected predicate true; failing gate: %s", FailingGate(state, cfg, now))
    }
}

func TestQuiescencePredicate_GatesFailingInPriorityOrder(t *testing.T) {
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    cfg := QuiescenceCfg{IdleThreshold: 10 * time.Minute}
    base := func() *prsession.PRGroomingState {
        return &prsession.PRGroomingState{
            LastActivityAt: now.Add(-15 * time.Minute),
            Reviewers: map[string]prsession.ReviewerState{
                "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound},
            },
            Items: []prsession.ReviewItem{
                {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
            },
            Quiescence: prsession.QuiescenceState{CIState: "success"},
        }
    }

    cases := []struct {
        name       string
        mutate     func(*prsession.PRGroomingState)
        wantGate   QuiescenceGate
    }{
        {
            name: "G_REVIEWERS_failing_required_in_progress",
            mutate: func(s *prsession.PRGroomingState) {
                s.Reviewers["copilot"] = prsession.ReviewerState{Identity: "copilot", Required: true, Status: prsession.ReviewerInProgress}
            },
            wantGate: GateReviewers,
        },
        {
            name: "G_REVIEWERS_optional_in_progress_does_not_fail",
            mutate: func(s *prsession.PRGroomingState) {
                s.Reviewers["alice"] = prsession.ReviewerState{Identity: "alice", Required: false, Status: prsession.ReviewerInProgress}
            },
            wantGate: GateNone, // optional reviewers don't gate
        },
        {
            name: "G_REVIEWERS_declined_counts",
            mutate: func(s *prsession.PRGroomingState) {
                s.Reviewers["copilot"] = prsession.ReviewerState{
                    Identity: "copilot", Required: true,
                    Status: prsession.ReviewerDeclined, DeclinedReason: "timeout-no-start",
                }
            },
            wantGate: GateNone,
        },
        {
            name: "G_CI_failing_failure_state",
            mutate: func(s *prsession.PRGroomingState) {
                s.Quiescence.CIState = "failure"
            },
            wantGate: GateCI,
        },
        {
            name: "G_CI_pending_is_failing",
            mutate: func(s *prsession.PRGroomingState) {
                s.Quiescence.CIState = "pending"
            },
            wantGate: GateCI,
        },
        {
            name: "G_CI_absent_passes",
            mutate: func(s *prsession.PRGroomingState) {
                s.Quiescence.CIState = "absent"
            },
            wantGate: GateNone,
        },
        {
            name: "G_DISPOSITIONS_failing_nil_disposition",
            mutate: func(s *prsession.PRGroomingState) {
                s.Items = append(s.Items, prsession.ReviewItem{Disposition: nil})
            },
            wantGate: GateDispositions,
        },
        {
            name: "G_NO_BLOCKERS_failing_escalated",
            mutate: func(s *prsession.PRGroomingState) {
                s.Items = append(s.Items, prsession.ReviewItem{Disposition: &prsession.Disposition{Kind: prsession.DispositionEscalated}})
            },
            wantGate: GateNoBlockers,
        },
        {
            name: "G_NO_BLOCKERS_failing_failed",
            mutate: func(s *prsession.PRGroomingState) {
                s.Items = append(s.Items, prsession.ReviewItem{Disposition: &prsession.Disposition{Kind: prsession.DispositionFailed}})
            },
            wantGate: GateNoBlockers,
        },
        {
            name: "GateIdle_failing_recent_activity",
            mutate: func(s *prsession.PRGroomingState) {
                s.LastActivityAt = now.Add(-5 * time.Minute) // 5m < 10m threshold
            },
            wantGate: GateIdle,
        },
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            s := base()
            c.mutate(s)
            got := FailingGate(s, cfg, now)
            if got != c.wantGate {
                t.Errorf("FailingGate: got %v, want %v", got, c.wantGate)
            }
            wantPredicate := (c.wantGate == GateNone)
            if QuiescencePredicate(s, cfg, now) != wantPredicate {
                t.Errorf("QuiescencePredicate: got %v, want %v", !wantPredicate, wantPredicate)
            }
        })
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestQuiescencePredicate' -v`
Expected: FAIL — file does not compile (`QuiescencePredicate`, `FailingGate`, `QuiescenceGate`, `GateXxx` consts, `QuiescenceCfg` not defined).

- [ ] **Step 3: Implement the gates and predicate**

Create `internal/lifecycle/quiescence.go`:

```go
package lifecycle

import (
    "time"

    "<module>/internal/prsession"
)

type QuiescenceGate int

const (
    GateNone QuiescenceGate = iota
    GateReviewers
    GateCI
    GateDispositions
    GateNoBlockers
    GateIdle
)

func (g QuiescenceGate) String() string {
    switch g {
    case GateNone:
        return "none"
    case GateReviewers:
        return "G_REVIEWERS"
    case GateCI:
        return "G_CI"
    case GateDispositions:
        return "G_DISPOSITIONS"
    case GateNoBlockers:
        return "G_NO_BLOCKERS"
    case GateIdle:
        return "Idle"
    }
    return "unknown"
}

// QuiescenceCfg is the subset of config the quiescence predicate consumes.
// Passed as a value to keep the predicate pure-of-mind (no config-reload races).
type QuiescenceCfg struct {
    IdleThreshold time.Duration
}

// QuiescencePredicate returns true iff every hard gate passes AND the idle
// timer has elapsed. See §4.1.
func QuiescencePredicate(state *prsession.PRGroomingState, cfg QuiescenceCfg, now time.Time) bool {
    return FailingGate(state, cfg, now) == GateNone
}

// FailingGate returns the first gate that fails, in the priority order
// G_REVIEWERS → G_CI → G_DISPOSITIONS → G_NO_BLOCKERS → Idle. Returns
// GateNone if all pass. Operators read this via `prgroom status`.
func FailingGate(state *prsession.PRGroomingState, cfg QuiescenceCfg, now time.Time) QuiescenceGate {
    if !allRequiredReviewersTerminal(state) {
        return GateReviewers
    }
    if !ciGateAllows(state.Quiescence.CIState) {
        return GateCI
    }
    if !allItemsDispositioned(state) {
        return GateDispositions
    }
    if hasBlockerDisposition(state) {
        return GateNoBlockers
    }
    if now.Sub(state.LastActivityAt) < cfg.IdleThreshold {
        return GateIdle
    }
    return GateNone
}

func allRequiredReviewersTerminal(state *prsession.PRGroomingState) bool {
    for _, r := range state.Reviewers {
        if !r.Required {
            continue
        }
        if r.Status != prsession.ReviewerReviewFound && r.Status != prsession.ReviewerDeclined {
            return false
        }
    }
    return true
}

func ciGateAllows(ciState string) bool {
    // §4.1: success | absent pass. pending and failure fail.
    return ciState == "success" || ciState == "absent" || ciState == ""
    // Note: "" is treated as "absent" for backward-compat when state.Quiescence.CIState
    // has never been written. The first pollLocked sets it explicitly per Task 6.
}

func allItemsDispositioned(state *prsession.PRGroomingState) bool {
    for i := range state.Items {
        if state.Items[i].Disposition == nil {
            return false
        }
    }
    return true
}

func hasBlockerDisposition(state *prsession.PRGroomingState) bool {
    for i := range state.Items {
        d := state.Items[i].Disposition
        if d == nil {
            continue
        }
        if d.Kind == prsession.DispositionEscalated || d.Kind == prsession.DispositionFailed {
            return true
        }
    }
    return false
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestQuiescencePredicate' -v`
Expected: PASS, all subtests in `TestQuiescencePredicate_GatesFailingInPriorityOrder` plus the all-pass case.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/quiescence.go internal/lifecycle/quiescence_test.go
git commit -m "feat(prgroom): add Section 4 quiescence predicate + gate enum"
```

---

### Task 3: Engagement-detection helper

**Files:**
- Create: `internal/lifecycle/engagement.go`
- Create: `internal/lifecycle/engagement_test.go`

**Reference:** §4.1 "Engagement detection — what sets `LastReviewAt`". Any actor-attributed activity after `LastRequestAt` AND after the most-recent push counts.

- [ ] **Step 1: Write the failing test**

Create `internal/lifecycle/engagement_test.go`:

```go
package lifecycle

import (
    "testing"
    "time"
)

func TestIsReviewerEngagement(t *testing.T) {
    requested := time.Date(2026, 5, 25, 10, 0, 0, 0, time.UTC)
    pushed    := time.Date(2026, 5, 25, 10, 5, 0, 0, time.UTC)
    afterPush := pushed.Add(1 * time.Minute)
    beforePush := pushed.Add(-1 * time.Minute)
    cases := []struct {
        name      string
        activity  ReviewerActivity
        reviewer  string
        want      bool
    }{
        {
            name: "issue_comment_by_reviewer_after_push_engages",
            activity: ReviewerActivity{
                Kind: ActivityIssueComment, ActorLogin: "copilot", CreatedAt: afterPush,
            },
            reviewer: "copilot", want: true,
        },
        {
            name: "review_by_reviewer_after_push_engages",
            activity: ReviewerActivity{
                Kind: ActivityReview, ActorLogin: "copilot", CreatedAt: afterPush, ReviewState: "COMMENTED",
            },
            reviewer: "copilot", want: true,
        },
        {
            name: "inline_review_comment_by_reviewer_engages",
            activity: ReviewerActivity{
                Kind: ActivityInlineReviewComment, ActorLogin: "copilot", CreatedAt: afterPush,
            },
            reviewer: "copilot", want: true,
        },
        {
            name: "thread_reply_by_reviewer_engages",
            activity: ReviewerActivity{
                Kind: ActivityThreadReply, ActorLogin: "copilot", CreatedAt: afterPush,
            },
            reviewer: "copilot", want: true,
        },
        {
            name: "activity_by_other_actor_does_not_engage",
            activity: ReviewerActivity{
                Kind: ActivityIssueComment, ActorLogin: "alice", CreatedAt: afterPush,
            },
            reviewer: "copilot", want: false,
        },
        {
            name: "activity_before_push_does_not_engage",
            activity: ReviewerActivity{
                Kind: ActivityIssueComment, ActorLogin: "copilot", CreatedAt: beforePush,
            },
            reviewer: "copilot", want: false,
        },
        {
            name: "activity_before_request_does_not_engage",
            activity: ReviewerActivity{
                Kind: ActivityIssueComment, ActorLogin: "copilot", CreatedAt: requested.Add(-1 * time.Minute),
            },
            reviewer: "copilot", want: false,
        },
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            got := IsReviewerEngagement(c.activity, c.reviewer, requested, pushed)
            if got != c.want {
                t.Errorf("got %v, want %v", got, c.want)
            }
        })
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestIsReviewerEngagement' -v`
Expected: FAIL — `ReviewerActivity`, `ActivityXxx` consts, `IsReviewerEngagement` not defined.

- [ ] **Step 3: Implement the engagement helper**

Create `internal/lifecycle/engagement.go`:

```go
package lifecycle

import "time"

type ActivityKind int

const (
    ActivityUnknown ActivityKind = iota
    ActivityIssueComment        // /issues/{n}/comments
    ActivityReview              // /pulls/{n}/reviews (any state)
    ActivityInlineReviewComment // /pulls/{n}/comments
    ActivityThreadReply         // GraphQL thread reply
)

// ReviewerActivity is the minimal projection of a PR-side event the
// engagement check needs. The full event source (gh JSON) lives in the
// gh adapter; pollLocked converts each fetched event into this shape before
// passing it through IsReviewerEngagement.
type ReviewerActivity struct {
    Kind        ActivityKind
    ActorLogin  string // e.g. "copilot", "alice"; matched case-insensitively against reviewer Identity
    CreatedAt   time.Time
    ReviewState string // present only for ActivityReview; otherwise empty
}

// IsReviewerEngagement reports whether this activity counts as the reviewer
// "engaging" with the PR for §4.1 timeout purposes. The reviewer must own
// the activity (case-insensitive login match), and the activity must occur
// after BOTH the most-recent review request AND the most-recent push (whichever
// is later — engagement on stale SHAs is not engagement on the current push).
func IsReviewerEngagement(a ReviewerActivity, reviewerIdentity string, lastRequestAt, lastPushAt time.Time) bool {
    if !equalLoginFold(a.ActorLogin, reviewerIdentity) {
        return false
    }
    threshold := lastRequestAt
    if lastPushAt.After(threshold) {
        threshold = lastPushAt
    }
    if !a.CreatedAt.After(threshold) {
        return false
    }
    switch a.Kind {
    case ActivityIssueComment, ActivityReview, ActivityInlineReviewComment, ActivityThreadReply:
        return true
    }
    return false
}

func equalLoginFold(a, b string) bool {
    if len(a) != len(b) {
        // Equal-length string compare is fine for typical reviewer ids (e.g. "copilot"),
        // but gh sometimes returns suffixed bot logins (e.g. "github-copilot[bot]").
        // Callers normalize before calling; we keep this strict to make mismatches
        // visible rather than silently fuzzy.
        return false
    }
    for i := 0; i < len(a); i++ {
        ca, cb := a[i], b[i]
        if ca >= 'A' && ca <= 'Z' {
            ca += 'a' - 'A'
        }
        if cb >= 'A' && cb <= 'Z' {
            cb += 'a' - 'A'
        }
        if ca != cb {
            return false
        }
    }
    return true
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestIsReviewerEngagement' -v`
Expected: PASS — all seven subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/engagement.go internal/lifecycle/engagement_test.go
git commit -m "feat(prgroom): add reviewer-engagement helper for §4.1 timeouts"
```

---

### Task 4: Reviewer-timeout evaluator

**Files:**
- Create: `internal/lifecycle/reviewer_timeouts.go`
- Create: `internal/lifecycle/reviewer_timeouts_test.go`

**Reference:** §4.1 `evaluate_reviewer_timeouts` pseudocode. Auto-declines two paths: `timeout-no-start` (requested, never engaged) and `timeout-stalled` (engaged, never finished).

- [ ] **Step 1: Write the failing test**

Create `internal/lifecycle/reviewer_timeouts_test.go`:

```go
package lifecycle

import (
    "testing"
    "time"

    "<module>/internal/prsession"
)

func TestEvaluateReviewerTimeouts(t *testing.T) {
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    cfg := TimeoutsCfg{
        ReviewStartTimeout:  3 * time.Minute,
        ReviewFinishTimeout: 15 * time.Minute,
    }

    cases := []struct {
        name           string
        initialStatus  prsession.ReviewerStatus
        lastRequestAt  time.Time
        lastReviewAt   time.Time
        wantStatus     prsession.ReviewerStatus
        wantReason     string
    }{
        {
            name:          "requested_within_start_window_no_change",
            initialStatus: prsession.ReviewerRequested,
            lastRequestAt: now.Add(-2 * time.Minute),
            wantStatus:    prsession.ReviewerRequested,
        },
        {
            name:          "requested_past_start_window_declines",
            initialStatus: prsession.ReviewerRequested,
            lastRequestAt: now.Add(-4 * time.Minute),
            wantStatus:    prsession.ReviewerDeclined,
            wantReason:    "timeout-no-start",
        },
        {
            name:          "in_progress_within_finish_window_no_change",
            initialStatus: prsession.ReviewerInProgress,
            lastRequestAt: now.Add(-20 * time.Minute),
            lastReviewAt:  now.Add(-10 * time.Minute),
            wantStatus:    prsession.ReviewerInProgress,
        },
        {
            name:          "in_progress_past_finish_window_declines",
            initialStatus: prsession.ReviewerInProgress,
            lastRequestAt: now.Add(-30 * time.Minute),
            lastReviewAt:  now.Add(-16 * time.Minute),
            wantStatus:    prsession.ReviewerDeclined,
            wantReason:    "timeout-stalled",
        },
        {
            name:          "review_found_does_not_decline",
            initialStatus: prsession.ReviewerReviewFound,
            lastRequestAt: now.Add(-30 * time.Minute),
            wantStatus:    prsession.ReviewerReviewFound,
        },
        {
            name:          "already_declined_does_not_re_decline",
            initialStatus: prsession.ReviewerDeclined,
            lastRequestAt: now.Add(-30 * time.Minute),
            wantStatus:    prsession.ReviewerDeclined,
            wantReason:    "",
        },
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            state := &prsession.PRGroomingState{
                Reviewers: map[string]prsession.ReviewerState{
                    "copilot": {
                        Identity:      "copilot",
                        Required:      true,
                        Status:        c.initialStatus,
                        LastRequestAt: c.lastRequestAt,
                        LastReviewAt:  c.lastReviewAt,
                    },
                },
            }
            EvaluateReviewerTimeouts(state, cfg, now)
            got := state.Reviewers["copilot"]
            if got.Status != c.wantStatus {
                t.Errorf("Status: got %v, want %v", got.Status, c.wantStatus)
            }
            if got.DeclinedReason != c.wantReason {
                t.Errorf("DeclinedReason: got %q, want %q", got.DeclinedReason, c.wantReason)
            }
            if c.wantStatus == prsession.ReviewerDeclined && c.wantReason != "" && got.DeclinedAt.IsZero() {
                t.Errorf("DeclinedAt should be set on a fresh decline")
            }
        })
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestEvaluateReviewerTimeouts' -v`
Expected: FAIL — `EvaluateReviewerTimeouts`, `TimeoutsCfg` not defined.

- [ ] **Step 3: Implement the timeout evaluator**

Create `internal/lifecycle/reviewer_timeouts.go`:

```go
package lifecycle

import (
    "time"

    "<module>/internal/prsession"
)

type TimeoutsCfg struct {
    ReviewStartTimeout  time.Duration
    ReviewFinishTimeout time.Duration
}

// EvaluateReviewerTimeouts mutates state in place per §4.1's auto-decline rules.
// Reviewers in {requested, in_progress} that exceed their respective timeout
// transition to {declined} with a DeclinedReason of "timeout-no-start" or
// "timeout-stalled". Reviewers in any other status are untouched.
func EvaluateReviewerTimeouts(state *prsession.PRGroomingState, cfg TimeoutsCfg, now time.Time) {
    for id, r := range state.Reviewers {
        switch r.Status {
        case prsession.ReviewerRequested:
            if !r.LastReviewAt.IsZero() {
                // Shouldn't happen — LastReviewAt being set implies in_progress or terminal.
                // Skip rather than reclassify; pollLocked owns Status transitions.
                continue
            }
            if now.Sub(r.LastRequestAt) > cfg.ReviewStartTimeout {
                r.Status = prsession.ReviewerDeclined
                r.DeclinedAt = now
                r.DeclinedReason = "timeout-no-start"
                state.Reviewers[id] = r
            }
        case prsession.ReviewerInProgress:
            if r.LastReviewAt.IsZero() {
                // Inconsistent: in_progress implies engagement, which sets LastReviewAt.
                // Skip; pollLocked owns the transition that should have set it.
                continue
            }
            if now.Sub(r.LastReviewAt) > cfg.ReviewFinishTimeout {
                r.Status = prsession.ReviewerDeclined
                r.DeclinedAt = now
                r.DeclinedReason = "timeout-stalled"
                state.Reviewers[id] = r
            }
        }
        // Other statuses: no change.
    }
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestEvaluateReviewerTimeouts' -v`
Expected: PASS — all six subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/reviewer_timeouts.go internal/lifecycle/reviewer_timeouts_test.go
git commit -m "feat(prgroom): add reviewer auto-decline timeout evaluator (§4.1)"
```

---

### Task 5: Wire Section 4 add-ons into `pollLocked`

**Files:**
- Modify: `internal/lifecycle/poll.go`
- Modify: `internal/lifecycle/poll_test.go`

**Reference:** §4.1 `pollLocked side-effects relevant to §4`, §4.2 wake-event 2 comment block. Four add-ons:
1. Update `state.LastActivityAt` on observed PR-side mutations
2. Update `state.Quiescence.CIState` from latest check-runs/statuses for `state.LastPushedHeadSHA`
3. Call `EvaluateReviewerTimeouts(state, cfg, now)` post-fetch
4. Drive engagement-detection-based `Status` transitions + `LastReviewAt` updates

**Important:** `pollLocked` already exists from the §3 lifecycle bead. This task EXTENDS it. Read the existing file first; identify where it processes per-reviewer events; insert the §4 logic there.

- [ ] **Step 1: Read the existing pollLocked**

Read `internal/lifecycle/poll.go`. Map out:
- where the gh fetch happens (comments, reviews, check-runs)
- where reviewer state is mutated (the §3.4 HEAD-SHA flip, the reviewer-state assignments)
- whether the function accepts a `now func() time.Time` clock or calls `time.Now()` directly (the §4 logic needs a clock for testability)

If `pollLocked` calls `time.Now()` directly, refactor to accept a `clock func() time.Time` field on a `pollDeps` struct (or similar). This is a small refactor needed before any §4 add-on is testable in unit-tests.

- [ ] **Step 2: Write the failing tests (one per add-on)**

Append to `internal/lifecycle/poll_test.go`. Use the existing fake `gh` client convention from the foundation; if a `fakeGH` struct exists, extend it; otherwise create one in this file.

Test 1 — `LastActivityAt` updates on observed mutations:

```go
func TestPollLocked_UpdatesLastActivityAtOnNewComment(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    start := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR:             pr,
        Phase:          prsession.PhaseAwaitingReview,
        LastActivityAt: start.Add(-30 * time.Minute),
        LastPushedHeadSHA: "abc",
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerRequested, LastRequestAt: start.Add(-5 * time.Minute)},
        },
    }
    gh := &fakeGH{
        IssueComments: []ghComment{{Login: "copilot", CreatedAt: start.Add(-1 * time.Minute), Body: "looking at this"}},
        HeadSHA:       "abc",
        CheckRuns:     []ghCheckRun{{Conclusion: "success"}},
    }
    deps := pollDeps{GH: gh, Clock: func() time.Time { return start }, Cfg: TimeoutsCfg{ReviewStartTimeout: 3 * time.Minute, ReviewFinishTimeout: 15 * time.Minute}}

    state, err := pollLocked(pr, state, deps)
    if err != nil {
        t.Fatalf("pollLocked: %v", err)
    }
    wantActivity := start.Add(-1 * time.Minute) // the comment's CreatedAt
    if !state.LastActivityAt.Equal(wantActivity) {
        t.Errorf("LastActivityAt: got %v, want %v", state.LastActivityAt, wantActivity)
    }
}
```

Test 2 — `CIState` reflects latest check-run for the pushed head:

```go
func TestPollLocked_CapturesCIStateForLastPushedHead(t *testing.T) {
    // Three scenarios in one test via subtests: success, failure, absent
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    cases := []struct {
        name      string
        checkRuns []ghCheckRun
        want      string
    }{
        {"success_all_pass", []ghCheckRun{{Conclusion: "success"}, {Conclusion: "success"}}, "success"},
        {"failure_any_failed", []ghCheckRun{{Conclusion: "success"}, {Conclusion: "failure"}}, "failure"},
        {"pending_any_pending", []ghCheckRun{{Conclusion: ""}, {Conclusion: "success"}}, "pending"},
        {"absent_no_runs", []ghCheckRun{}, "absent"},
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            state := &prsession.PRGroomingState{PR: pr, LastPushedHeadSHA: "abc"}
            gh := &fakeGH{HeadSHA: "abc", CheckRuns: c.checkRuns}
            deps := pollDeps{GH: gh, Clock: func() time.Time { return now }, Cfg: TimeoutsCfg{}}
            state, err := pollLocked(pr, state, deps)
            if err != nil {
                t.Fatalf("pollLocked: %v", err)
            }
            if state.Quiescence.CIState != c.want {
                t.Errorf("CIState: got %q, want %q", state.Quiescence.CIState, c.want)
            }
        })
    }
}
```

Test 3 — engagement flips `requested → in_progress`:

```go
func TestPollLocked_EngagementFlipsRequestedToInProgress(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    start := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR:                pr,
        LastPushedHeadSHA: "abc",
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {
                Identity:      "copilot",
                Required:      true,
                Status:        prsession.ReviewerRequested,
                LastRequestAt: start.Add(-5 * time.Minute),
            },
        },
    }
    activityTime := start.Add(-1 * time.Minute)
    gh := &fakeGH{
        IssueComments: []ghComment{{Login: "copilot", CreatedAt: activityTime, Body: "looking"}},
        HeadSHA:       "abc",
        PushedAt:      start.Add(-3 * time.Minute),
    }
    deps := pollDeps{GH: gh, Clock: func() time.Time { return start }, Cfg: TimeoutsCfg{ReviewStartTimeout: 3 * time.Minute, ReviewFinishTimeout: 15 * time.Minute}}

    state, err := pollLocked(pr, state, deps)
    if err != nil {
        t.Fatalf("pollLocked: %v", err)
    }
    r := state.Reviewers["copilot"]
    if r.Status != prsession.ReviewerInProgress {
        t.Errorf("Status: got %v, want in_progress", r.Status)
    }
    if !r.LastReviewAt.Equal(activityTime) {
        t.Errorf("LastReviewAt: got %v, want %v", r.LastReviewAt, activityTime)
    }
}
```

Test 4 — `EvaluateReviewerTimeouts` is invoked (request-side timeout):

```go
func TestPollLocked_AutoDeclinesOnStartTimeout(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR:                pr,
        LastPushedHeadSHA: "abc",
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {
                Identity:      "copilot",
                Required:      true,
                Status:        prsession.ReviewerRequested,
                LastRequestAt: now.Add(-5 * time.Minute), // past 3m start timeout
            },
        },
    }
    gh := &fakeGH{HeadSHA: "abc"}
    deps := pollDeps{GH: gh, Clock: func() time.Time { return now }, Cfg: TimeoutsCfg{ReviewStartTimeout: 3 * time.Minute, ReviewFinishTimeout: 15 * time.Minute}}

    state, err := pollLocked(pr, state, deps)
    if err != nil {
        t.Fatalf("pollLocked: %v", err)
    }
    r := state.Reviewers["copilot"]
    if r.Status != prsession.ReviewerDeclined || r.DeclinedReason != "timeout-no-start" {
        t.Errorf("expected timeout-no-start decline; got Status=%v Reason=%q", r.Status, r.DeclinedReason)
    }
}
```

- [ ] **Step 3: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestPollLocked' -v`
Expected: FAIL — likely a compile error if `pollDeps` doesn't have `Clock` or `Cfg` fields, or behavioral fails if the §4 add-ons aren't yet in `pollLocked`.

- [ ] **Step 4: Refactor `pollLocked` to accept clock + cfg, add §4 add-ons**

If the existing `pollLocked` signature is `pollLocked(pr, state)`, change to `pollLocked(pr, state, deps)` where `pollDeps` is:

```go
type pollDeps struct {
    GH    ghClient        // interface from foundation
    Clock func() time.Time
    Cfg   TimeoutsCfg
}
```

Inside `pollLocked`, near the end of the function (after gh fetches have populated local variables `comments`, `reviews`, `inlineComments`, `threadReplies`, `checkRuns`, `headSHA`, `pushedAt`), add this block before the final write:

```go
// === §4 add-ons (see docs/plans/2026-05-12-prgroom-cli-design.md §4.1) ===

// (a) Update CIState for the pushed head.
state.Quiescence.CIState = summarizeCIState(checkRuns)

// (b) Engagement detection per reviewer: flip requested → in_progress
//     and bump LastReviewAt on first qualifying activity.
for id, r := range state.Reviewers {
    if r.Status != prsession.ReviewerRequested && r.Status != prsession.ReviewerInProgress {
        continue
    }
    activities := collectReviewerActivities(comments, reviews, inlineComments, threadReplies)
    for _, a := range activities {
        if !IsReviewerEngagement(a, r.Identity, r.LastRequestAt, pushedAt) {
            continue
        }
        if r.Status == prsession.ReviewerRequested {
            r.Status = prsession.ReviewerInProgress
        }
        if a.CreatedAt.After(r.LastReviewAt) {
            r.LastReviewAt = a.CreatedAt
        }
        if a.CreatedAt.After(state.LastActivityAt) {
            state.LastActivityAt = a.CreatedAt
        }
        state.Reviewers[id] = r
    }
}

// (c) Auto-decline timeouts.
EvaluateReviewerTimeouts(state, deps.Cfg, deps.Clock())

// (d) LastActivityAt also bumps on any push/label/CI change observed this
//     fetch (engagement loop above already covered comment/review activity).
if pushedAt.After(state.LastActivityAt) {
    state.LastActivityAt = pushedAt
}
// (label changes and CI conclusion changes — best-effort observation via the
//  gh fetch; if your foundation's gh adapter exposes these, bump
//  state.LastActivityAt to their observed timestamp here.)
```

Define `summarizeCIState`:

```go
func summarizeCIState(runs []ghCheckRun) string {
    if len(runs) == 0 {
        return "absent"
    }
    sawPending := false
    for _, r := range runs {
        switch r.Conclusion {
        case "failure", "timed_out", "cancelled", "action_required":
            return "failure"
        case "":
            sawPending = true
        case "success", "neutral", "skipped":
            // ok
        }
    }
    if sawPending {
        return "pending"
    }
    return "success"
}
```

Define `collectReviewerActivities` to normalize the gh fetches into `[]ReviewerActivity`:

```go
func collectReviewerActivities(
    comments []ghComment,
    reviews []ghReview,
    inlineComments []ghInlineComment,
    threadReplies []ghThreadReply,
) []ReviewerActivity {
    out := make([]ReviewerActivity, 0, len(comments)+len(reviews)+len(inlineComments)+len(threadReplies))
    for _, c := range comments {
        out = append(out, ReviewerActivity{Kind: ActivityIssueComment, ActorLogin: c.Login, CreatedAt: c.CreatedAt})
    }
    for _, r := range reviews {
        out = append(out, ReviewerActivity{Kind: ActivityReview, ActorLogin: r.Login, CreatedAt: r.SubmittedAt, ReviewState: r.State})
    }
    for _, c := range inlineComments {
        out = append(out, ReviewerActivity{Kind: ActivityInlineReviewComment, ActorLogin: c.Login, CreatedAt: c.CreatedAt})
    }
    for _, t := range threadReplies {
        out = append(out, ReviewerActivity{Kind: ActivityThreadReply, ActorLogin: t.Login, CreatedAt: t.CreatedAt})
    }
    return out
}
```

If `ghComment`, `ghReview`, etc. names differ in the foundation, adapt to whatever names exist — the shape (`Login`, `CreatedAt`, `State` on reviews) is what matters.

- [ ] **Step 5: Update all `pollLocked` callers**

Search for `pollLocked(` and update each call to pass `deps`. `runLocked` is the main caller; `waitLocked` will be the second (Task 7). The deps come from `runLocked`'s own input (it'll receive deps in a separate Task or have them already from a foundation refactor — if not, do that refactor now and update the test).

- [ ] **Step 6: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestPollLocked' -v`
Expected: PASS — all four `TestPollLocked_*` cases.

- [ ] **Step 7: Run the full lifecycle test suite**

Run: `go test ./internal/lifecycle/ -v`
Expected: PASS — existing tests should still pass (the §4 add-ons are additive). If existing tests fail because they now need a `deps` argument, update them to pass a zero-value `pollDeps{}` with a stub clock returning the test's `now`.

- [ ] **Step 8: Commit**

```bash
git add internal/lifecycle/poll.go internal/lifecycle/poll_test.go
git commit -m "feat(prgroom): wire §4 add-ons into pollLocked (engagement, timeouts, CIState, LastActivityAt)"
```

---

### Task 6: Implement `waitLocked` core (sleep + ctx + quiescence-trip)

**Files:**
- Create: `internal/lifecycle/wait.go`
- Create: `internal/lifecycle/wait_test.go`

**Reference:** §4.2 `waitLocked` pseudocode. Five wake events:
1. Signal-cancel at loop top (`ctx.Err() != nil`)
2. Signal-cancel during sleep (`ctx.Done()` in `select`)
3. `pollLocked` error propagates per §3.3 `handle_verb_error`
4. Phase moved off `awaiting-review`/`idle` (fix commits arrived, external push, PR merged externally) → return to let `runLocked` re-enter cycle
5. Quiescence predicate satisfied → trip to `quiesced`, write, return

This task covers events 1, 2, 5. Events 3, 4 land in Task 7.

- [ ] **Step 1: Write the failing tests (wake events 1, 2, 5)**

Create `internal/lifecycle/wait_test.go`:

```go
package lifecycle

import (
    "context"
    "errors"
    "testing"
    "time"

    "<module>/internal/prsession"
)

// fakePollFn is the seam for unit-testing waitLocked without going through the
// real pollLocked + gh adapter. The wait_test.go file installs one of these
// via waitDeps.PollFn.
type fakePollFn func(pr prsession.PRRef, state *prsession.PRGroomingState, now time.Time) (*prsession.PRGroomingState, error)

func TestWaitLocked_QuiescenceTripsAndReturns(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR:             pr,
        Phase:          prsession.PhaseAwaitingReview,
        LastActivityAt: now.Add(-15 * time.Minute), // idle > 10m
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound},
        },
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
        },
        Quiescence: prsession.QuiescenceState{CIState: "success"},
    }
    deps := waitDeps{
        PollFn: func(_ prsession.PRRef, s *prsession.PRGroomingState, _ time.Time) (*prsession.PRGroomingState, error) {
            // Predicate is already satisfiable on entry; this poll is a no-op refresh.
            return s, nil
        },
        Clock:        func() time.Time { return now },
        Sleep:        func(_ context.Context, _ time.Duration) error { return nil }, // instant
        Cfg:          QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        StoreWrite: func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil },
    }
    ctx := context.Background()
    state, err := waitLocked(ctx, pr, state, deps)
    if err != nil {
        t.Fatalf("waitLocked: %v", err)
    }
    if state.Phase != prsession.PhaseQuiesced {
        t.Errorf("Phase: got %v, want quiesced", state.Phase)
    }
    if state.Quiescence.QuiescedAt.IsZero() {
        t.Errorf("QuiescedAt should be stamped on quiescence trip")
    }
}

func TestWaitLocked_CtxCancelledAtLoopTopReturnsCancelled(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{PR: pr, Phase: prsession.PhaseAwaitingReview}
    ctx, cancel := context.WithCancel(context.Background())
    cancel() // already cancelled on entry
    deps := waitDeps{
        PollFn: func(_ prsession.PRRef, _ *prsession.PRGroomingState, _ time.Time) (*prsession.PRGroomingState, error) {
            t.Fatal("PollFn should not be called when ctx is already cancelled at loop top")
            return nil, nil
        },
        Clock:        func() time.Time { return time.Now().UTC() },
        Sleep:        func(_ context.Context, _ time.Duration) error { return nil },
        Cfg:          QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        StoreWrite: func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil },
    }
    _, err := waitLocked(ctx, pr, state, deps)
    if err == nil {
        t.Fatal("expected error on cancellation")
    }
    if !errors.Is(err, context.Canceled) {
        t.Errorf("expected wrapped context.Canceled, got %v", err)
    }
    if !IsRuntimeCancelledError(err) {
        t.Errorf("expected RUNTIME_CANCELLED tier; got %v", err)
    }
}

func TestWaitLocked_CtxCancelledDuringSleepReturnsCancelled(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{PR: pr, Phase: prsession.PhaseAwaitingReview}
    ctx, cancel := context.WithCancel(context.Background())
    deps := waitDeps{
        PollFn: func(_ prsession.PRRef, s *prsession.PRGroomingState, _ time.Time) (*prsession.PRGroomingState, error) {
            return s, nil // predicate not satisfiable → loop continues to sleep
        },
        Clock: func() time.Time { return time.Now().UTC() },
        Sleep: func(c context.Context, _ time.Duration) error {
            cancel() // cancel from inside sleep
            <-c.Done()
            return c.Err()
        },
        Cfg:          QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        StoreWrite: func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil },
    }
    _, err := waitLocked(ctx, pr, state, deps)
    if err == nil || !IsRuntimeCancelledError(err) {
        t.Errorf("expected RUNTIME_CANCELLED, got %v", err)
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestWaitLocked' -v`
Expected: FAIL — `waitLocked`, `waitDeps`, `IsRuntimeCancelledError` not defined.

- [ ] **Step 3: Implement waitLocked core**

Create `internal/lifecycle/wait.go`:

```go
package lifecycle

import (
    "context"
    "time"

    "<module>/internal/prsession"
)

// waitDeps is the dependency surface for waitLocked. Production code wires
// real implementations (the actual pollLocked, time.Sleep with ctx-aware select,
// the real clock, the file-backed prsession.Store write); tests inject fakes.
type waitDeps struct {
    PollFn       func(pr prsession.PRRef, state *prsession.PRGroomingState, now time.Time) (*prsession.PRGroomingState, error)
    Clock        func() time.Time
    Sleep        func(ctx context.Context, d time.Duration) error // returns ctx.Err() if cancelled
    Cfg          QuiescenceCfg
    PollInterval time.Duration
    StoreWrite func(pr prsession.PRRef, state *prsession.PRGroomingState) error
}

// waitLocked implements §4.2. The caller holds the PR lock; waitLocked
// does NOT release during sleep. Cancellation honors ctx; signal handling is
// the caller's job (Run sets up SIGINT/SIGTERM → ctx.cancel).
func waitLocked(ctx context.Context, pr prsession.PRRef, state *prsession.PRGroomingState, deps waitDeps) (*prsession.PRGroomingState, error) {
    for {
        // Wake event 1: signal-cancel at loop top.
        if err := ctx.Err(); err != nil {
            return state, wrapRuntimeCancelled(err)
        }

        // Wake event 2: signal-cancel during sleep. Implemented by deps.Sleep.
        if err := deps.Sleep(ctx, deps.PollInterval); err != nil {
            return state, wrapRuntimeCancelled(err)
        }

        // Wake event 3: pollLocked error propagation lands in Task 7.
        var err error
        state, err = deps.PollFn(pr, state, deps.Clock())
        if err != nil {
            return state, err // Task 7 refines: tier-based decision + handle_verb_error
        }

        // Wake event 4: phase moved off awaiting-review/idle lands in Task 7.

        // Wake event 5: quiescence predicate satisfied.
        if QuiescencePredicate(state, deps.Cfg, deps.Clock()) {
            state.Phase = prsession.PhaseQuiesced
            state.Quiescence.QuiescedAt = deps.Clock()
            if werr := deps.StoreWrite(pr, state); werr != nil {
                return state, werr
            }
            return state, nil
        }
    }
}

// runtimeCancelledError marks an error as RUNTIME_CANCELLED tier per §3.6/§3.7.
// The Run wrapper inspects this to apply the cancelled-tier exit code (130 for
// SIGINT, 143 for SIGTERM). The signum itself is NOT carried on this error —
// the cause may be context.Canceled (no signal observable from the error
// alone). Run is the single source of truth for which signal fired: its own
// signal handler captures the signum at OS-observation time and combines that
// with this tier marker to derive the exit code per §3.7.
type runtimeCancelledError struct{ cause error }

func (e *runtimeCancelledError) Error() string { return "prgroom: cancelled: " + e.cause.Error() }
func (e *runtimeCancelledError) Unwrap() error { return e.cause }

func wrapRuntimeCancelled(cause error) error { return &runtimeCancelledError{cause: cause} }

// IsRuntimeCancelledError reports whether err is the RUNTIME_CANCELLED tier.
// Run uses this to apply exit code 130/143 and avoid scheduler retry.
func IsRuntimeCancelledError(err error) bool {
    if err == nil {
        return false
    }
    var rce *runtimeCancelledError
    return errorsAs(err, &rce)
}

// errorsAs is a tiny shim so the test file doesn't have to import errors.
// If the foundation already exposes a similar helper, delete this and use that.
func errorsAs(err error, target interface{}) bool {
    type unwrapper interface{ Unwrap() error }
    for err != nil {
        switch t := target.(type) {
        case **runtimeCancelledError:
            if rce, ok := err.(*runtimeCancelledError); ok {
                *t = rce
                return true
            }
        }
        if u, ok := err.(unwrapper); ok {
            err = u.Unwrap()
            continue
        }
        return false
    }
    return false
}
```

(If `errors.As` is already imported and used in the package, replace `errorsAs` with the standard `errors.As` and remove the shim.)

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestWaitLocked' -v`
Expected: PASS — all three subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/wait.go internal/lifecycle/wait_test.go
git commit -m "feat(prgroom): implement waitLocked core (ctx, sleep, quiescence-trip)"
```

---

### Task 7: Extend `waitLocked` with pollLocked-error + phase-transition exits

**Files:**
- Modify: `internal/lifecycle/wait.go`
- Modify: `internal/lifecycle/wait_test.go`

**Reference:** §4.2 wake events 3 (pollLocked error → propagate per `handle_verb_error`) and 4 (phase moved off `awaiting-review`/`idle` → return). Also the wake-event-registry table.

- [ ] **Step 1: Write the failing tests**

Append to `internal/lifecycle/wait_test.go`:

```go
func TestWaitLocked_PhaseMovedOffAwaitingReviewExitsCleanly(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{PR: pr, Phase: prsession.PhaseAwaitingReview}
    deps := waitDeps{
        PollFn: func(_ prsession.PRRef, s *prsession.PRGroomingState, _ time.Time) (*prsession.PRGroomingState, error) {
            s.Phase = prsession.PhaseFixesPending // simulate fix commits arrived
            return s, nil
        },
        Clock:        func() time.Time { return now },
        Sleep:        func(_ context.Context, _ time.Duration) error { return nil },
        Cfg:          QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        PollInterval: 30 * time.Second,
        StoreWrite: func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil },
    }
    state, err := waitLocked(context.Background(), pr, state, deps)
    if err != nil {
        t.Fatalf("waitLocked: %v", err)
    }
    if state.Phase != prsession.PhaseFixesPending {
        t.Errorf("Phase: got %v, want fixes-pending", state.Phase)
    }
}

func TestWaitLocked_PollLockedErrorPropagates(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{PR: pr, Phase: prsession.PhaseAwaitingReview}
    wantErr := errors.New("transient gh failure")
    deps := waitDeps{
        PollFn: func(_ prsession.PRRef, s *prsession.PRGroomingState, _ time.Time) (*prsession.PRGroomingState, error) {
            return s, wantErr
        },
        Clock:        func() time.Time { return now },
        Sleep:        func(_ context.Context, _ time.Duration) error { return nil },
        Cfg:          QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        PollInterval: 30 * time.Second,
        StoreWrite: func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil },
    }
    _, err := waitLocked(context.Background(), pr, state, deps)
    if !errors.Is(err, wantErr) {
        t.Errorf("expected wrapped %v, got %v", wantErr, err)
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestWaitLocked' -v`
Expected: PASS on `TestWaitLocked_PollLockedErrorPropagates` (Task 6 already returns the error directly) but FAIL on `TestWaitLocked_PhaseMovedOffAwaitingReviewExitsCleanly` — the loop currently only exits on cancel or quiescence.

- [ ] **Step 3: Add the phase-transition exit**

In `internal/lifecycle/wait.go`, between the `if err != nil` check and the `QuiescencePredicate` check, insert:

```go
        // Wake event 4: phase moved off awaiting-review/idle (fix commits
        // arrived, external push, PR merged externally) → return to let
        // runLocked re-enter the cycle.
        if state.Phase != prsession.PhaseAwaitingReview && state.Phase != prsession.PhaseIdle {
            return state, nil
        }
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestWaitLocked' -v`
Expected: PASS — all five subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/wait.go internal/lifecycle/wait_test.go
git commit -m "feat(prgroom): waitLocked exits on phase-transition + propagates pollLocked errors"
```

---

### Task 8: Wire quiescence trip into `resolve_end_of_cycle_phase` (priority 5)

**Files:**
- Modify: `internal/lifecycle/end_of_cycle.go`
- Modify: `internal/lifecycle/end_of_cycle_test.go`

**Reference:** §4.1 "End-of-cycle interaction with §3.3's `resolve_end_of_cycle_phase`". Quiescence is priority 5 in §3.2's cascade: priorities 1-3 route to `human-gated` (blocker gates), priority 4 routes to `awaiting-review` on commit-pushed, priority 5 is quiescence → `quiesced`. The §3 lifecycle bead implements priorities 1-4; this task adds priority 5.

- [ ] **Step 1: Write the failing test**

Append to `internal/lifecycle/end_of_cycle_test.go`:

```go
func TestResolveEndOfCyclePhase_Priority5QuiescenceTrips(t *testing.T) {
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        Phase:          prsession.PhaseFixesPending, // about to resolve
        LastActivityAt: now.Add(-15 * time.Minute),
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound},
        },
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
        },
        Quiescence: prsession.QuiescenceState{CIState: "success"},
    }
    cfg := QuiescenceCfg{IdleThreshold: 10 * time.Minute}
    newPhase := resolveEndOfCyclePhase(state, cfg, now)
    if newPhase != prsession.PhaseQuiesced {
        t.Errorf("Phase: got %v, want quiesced", newPhase)
    }
}

func TestResolveEndOfCyclePhase_BlockerBeatsQuiescence(t *testing.T) {
    // §3.2 priority cascade: an escalated item must route to human-gated
    // BEFORE reaching priority 5 quiescence.
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        Phase:          prsession.PhaseFixesPending,
        LastActivityAt: now.Add(-15 * time.Minute),
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionEscalated}},
        },
    }
    cfg := QuiescenceCfg{IdleThreshold: 10 * time.Minute}
    newPhase := resolveEndOfCyclePhase(state, cfg, now)
    if newPhase != prsession.PhaseHumanGated {
        t.Errorf("Phase: got %v, want human-gated (escalated item)", newPhase)
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestResolveEndOfCyclePhase' -v`
Expected: FAIL on the priority-5 quiescence trip (priorities 1-4 already implemented by §3 bead; priority 5 is missing).

The signature change `resolveEndOfCyclePhase(state) → resolveEndOfCyclePhase(state, cfg, now)` may also break the call site in `runLocked`. Plan to update that callsite in the same task.

- [ ] **Step 3: Add the priority-5 quiescence rule**

In `internal/lifecycle/end_of_cycle.go`, find `resolveEndOfCyclePhase`. After the existing priority-1-through-4 checks (priorities 1-3 route to `human-gated`; priority 4 is the commit-pushed → `awaiting-review` branch per §3.2), and BEFORE the function's default return, add:

```go
    // Priority 5: quiescence. If all hard gates pass AND idle timer elapsed,
    // transition to quiesced. See §4.1.
    if QuiescencePredicate(state, cfg, now) {
        state.Quiescence.QuiescedAt = now
        return prsession.PhaseQuiesced
    }
```

Update the signature: `func resolveEndOfCyclePhase(state *prsession.PRGroomingState, cfg QuiescenceCfg, now time.Time) prsession.PRPhase`.

Update the caller in `internal/lifecycle/run.go` — the existing `state.Phase = resolveEndOfCyclePhase(state)` call site (see §3.3 pseudocode line 721) becomes `state.Phase = resolveEndOfCyclePhase(state, deps.QuiescenceCfg, deps.Clock())`. The `runLocked` deps struct gets two new fields: `QuiescenceCfg QuiescenceCfg` and `Clock func() time.Time`. (Likely already has Clock from Task 5's pollLocked refactor; if not, add it.)

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestResolveEndOfCyclePhase' -v`
Expected: PASS, both subtests.

Then: `go test ./internal/lifecycle/ -v`
Expected: PASS — all existing tests (caller signature changes propagated correctly).

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/end_of_cycle.go internal/lifecycle/end_of_cycle_test.go internal/lifecycle/run.go
git commit -m "feat(prgroom): end-of-cycle resolver priority-5 quiescence rule (§4.1)"
```

---

### Task 9: `gh.AddLabel` adapter (if not already present)

**Files:**
- Modify (or create): `internal/gh/labels.go`
- Modify (or create): `internal/gh/labels_test.go`

**Reference:** §4.7 `gh.AddLabel(pr, "human-review-required")`. Best-effort: failure logs to stderr; does NOT tier-tag the error.

- [ ] **Step 1: Check whether `AddLabel` exists**

Read `internal/gh/labels.go` if it exists. If `AddLabel(ctx, pr, label) error` is already defined (the §3.4 reviewer dance is a `RemoveLabel`/`AddLabel` pair — `AddLabel` may already be there), skip to Task 10. Otherwise continue.

- [ ] **Step 2: Write the failing test**

Create or extend `internal/gh/labels_test.go`:

```go
package gh

import (
    "context"
    "io"
    "net/http"
    "net/http/httptest"
    "testing"
)

func TestAddLabel_PostsLabelsToIssuesAPI(t *testing.T) {
    var capturedPath string
    var capturedBody string
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        capturedPath = r.URL.Path
        body, _ := io.ReadAll(r.Body)
        capturedBody = string(body)
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte(`[{"name":"human-review-required"}]`))
    }))
    defer server.Close()

    c := NewClient(ClientOpts{BaseURL: server.URL, Token: "test"})
    pr := PRRef{Owner: "o", Repo: "r", Number: 42}
    if err := c.AddLabel(context.Background(), pr, "human-review-required"); err != nil {
        t.Fatalf("AddLabel: %v", err)
    }
    wantPath := "/repos/o/r/issues/42/labels"
    if capturedPath != wantPath {
        t.Errorf("path: got %q, want %q", capturedPath, wantPath)
    }
    if !contains(capturedBody, "human-review-required") {
        t.Errorf("body should contain label name; got %q", capturedBody)
    }
}

func contains(s, sub string) bool {
    return len(s) >= len(sub) && (s == sub || indexOf(s, sub) >= 0)
}
func indexOf(s, sub string) int {
    for i := 0; i+len(sub) <= len(s); i++ {
        if s[i:i+len(sub)] == sub {
            return i
        }
    }
    return -1
}
```

(If the foundation's `gh` package uses a different constructor signature, adapt.)

- [ ] **Step 3: Run tests, verify failure**

Run: `go test ./internal/gh/ -run 'TestAddLabel' -v`
Expected: FAIL — `AddLabel` not defined.

- [ ] **Step 4: Implement AddLabel**

Add to `internal/gh/labels.go`:

```go
package gh

import (
    "bytes"
    "context"
    "encoding/json"
    "fmt"
    "net/http"
)

// AddLabel adds a label to the PR's underlying issue. Idempotent server-side
// (gh returns 200 even when the label is already present).
func (c *Client) AddLabel(ctx context.Context, pr PRRef, label string) error {
    body, err := json.Marshal(struct{ Labels []string `json:"labels"` }{Labels: []string{label}})
    if err != nil {
        return fmt.Errorf("AddLabel: marshal: %w", err)
    }
    url := fmt.Sprintf("%s/repos/%s/%s/issues/%d/labels", c.baseURL, pr.Owner, pr.Repo, pr.Number)
    req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
    if err != nil {
        return fmt.Errorf("AddLabel: new request: %w", err)
    }
    req.Header.Set("Authorization", "Bearer "+c.token)
    req.Header.Set("Accept", "application/vnd.github+json")
    req.Header.Set("Content-Type", "application/json")
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return fmt.Errorf("AddLabel: do: %w", err)
    }
    defer resp.Body.Close()
    if resp.StatusCode >= 300 {
        return fmt.Errorf("AddLabel: status %d", resp.StatusCode)
    }
    return nil
}
```

Match the foundation's existing client field names (`baseURL`, `token`, `httpClient`) — adjust as needed if they're different.

- [ ] **Step 5: Run tests, verify pass**

Run: `go test ./internal/gh/ -run 'TestAddLabel' -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/gh/labels.go internal/gh/labels_test.go
git commit -m "feat(prgroom): add gh.AddLabel adapter for §4.7 label automation"
```

---

### Task 10: Human-review constraint derivation (pure)

**Files:**
- Create: `internal/lifecycle/human_review.go`
- Create: `internal/lifecycle/human_review_test.go`

**Reference:** §4.4 "Satisfaction signals (OR — any one satisfies)" and §4.6 "human_review.satisfied_by" / "candidates_seen". This task implements ONLY the pure derivation function (no I/O). Tasks 11-12 add the auto-add and runLocked integration.

The derivation has THREE outputs:
- `required bool` — `hasLabel("human-review-required")` (case-insensitive)
- `satisfiedBy string` — `"label"` | `"approval:<login>"` | `""`
- `candidates []ApprovalCandidate` — every PR approval examined, with Bot-filter outcome (for the `candidates_seen` debuggability field)

- [ ] **Step 1: Write the failing test**

Create `internal/lifecycle/human_review_test.go`:

```go
package lifecycle

import (
    "testing"
)

func TestDeriveHumanReview(t *testing.T) {
    cases := []struct {
        name          string
        labels        []string
        approvals     []ApprovalRecord
        wantRequired  bool
        wantSatBy     string
        wantCandCount int
    }{
        {
            name:         "no_label_no_constraint",
            labels:       []string{"good-first-issue"},
            wantRequired: false,
            wantSatBy:    "",
        },
        {
            name:         "label_set_no_approvals_not_satisfied",
            labels:       []string{"human-review-required"},
            wantRequired: true,
            wantSatBy:    "",
        },
        {
            name:         "label_set_human_label_satisfies",
            labels:       []string{"human-review-required", "human-approved"},
            wantRequired: true,
            wantSatBy:    "label",
        },
        {
            name:   "label_set_human_pr_approval_satisfies",
            labels: []string{"human-review-required"},
            approvals: []ApprovalRecord{
                {Login: "alice", State: "APPROVED", ActorType: "User"},
            },
            wantRequired:  true,
            wantSatBy:     "approval:alice",
            wantCandCount: 1,
        },
        {
            name:   "bot_approval_does_not_satisfy",
            labels: []string{"human-review-required"},
            approvals: []ApprovalRecord{
                {Login: "github-copilot[bot]", State: "APPROVED", ActorType: "Bot"},
            },
            wantRequired:  true,
            wantSatBy:     "",
            wantCandCount: 1,
        },
        {
            name:   "bot_then_human_approval_picks_human",
            labels: []string{"human-review-required"},
            approvals: []ApprovalRecord{
                {Login: "github-copilot[bot]", State: "APPROVED", ActorType: "Bot"},
                {Login: "alice", State: "APPROVED", ActorType: "User"},
            },
            wantRequired:  true,
            wantSatBy:     "approval:alice",
            wantCandCount: 2,
        },
        {
            name:   "non_approved_state_does_not_count",
            labels: []string{"human-review-required"},
            approvals: []ApprovalRecord{
                {Login: "alice", State: "CHANGES_REQUESTED", ActorType: "User"},
            },
            wantRequired:  true,
            wantSatBy:     "",
            wantCandCount: 0, // we only enumerate APPROVED candidates in candidates_seen
        },
        {
            name:         "label_match_is_case_insensitive",
            labels:       []string{"HUMAN-REVIEW-REQUIRED"},
            wantRequired: true,
            wantSatBy:    "",
        },
        {
            name:         "human_approved_label_alone_does_not_imply_required",
            labels:       []string{"human-approved"}, // no required label
            wantRequired: false,
            wantSatBy:    "",
        },
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            got := DeriveHumanReview(c.labels, c.approvals)
            if got.Required != c.wantRequired {
                t.Errorf("Required: got %v, want %v", got.Required, c.wantRequired)
            }
            if got.SatisfiedBy != c.wantSatBy {
                t.Errorf("SatisfiedBy: got %q, want %q", got.SatisfiedBy, c.wantSatBy)
            }
            if len(got.Candidates) != c.wantCandCount {
                t.Errorf("Candidates count: got %d, want %d (%v)", len(got.Candidates), c.wantCandCount, got.Candidates)
            }
        })
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestDeriveHumanReview' -v`
Expected: FAIL — `DeriveHumanReview`, `ApprovalRecord`, `HumanReviewState` not defined.

- [ ] **Step 3: Implement derivation**

Create `internal/lifecycle/human_review.go`:

```go
package lifecycle

import "strings"

const (
    labelHumanReviewRequired = "human-review-required"
    labelHumanApproved       = "human-approved"
)

// ApprovalRecord is the minimal projection of a GitHub PR review needed for
// human-review derivation. ActorType matches gh's actor.type field ("User",
// "Bot", "Organization").
type ApprovalRecord struct {
    Login     string
    State     string // APPROVED | CHANGES_REQUESTED | COMMENTED | PENDING
    ActorType string // User | Bot | ...
}

// ApprovalCandidate is one row of §4.6's candidates_seen output — every
// APPROVED-state review and whether it counted as a human approval.
type ApprovalCandidate struct {
    Login    string `json:"login"`
    Approved bool   `json:"approved"`
    Counted  bool   `json:"counted"`
    Reason   string `json:"reason,omitempty"` // populated when Counted=false (e.g., "bot")
}

// HumanReviewState is the §4.4 derivation result for the per-status-query JSON.
type HumanReviewState struct {
    Required    bool                `json:"required"`
    SatisfiedBy string              `json:"satisfied_by,omitempty"` // "label" | "approval:<login>"
    Candidates  []ApprovalCandidate `json:"candidates_seen,omitempty"`
}

// DeriveHumanReview computes §4.4's required + satisfied_by + candidates_seen
// purely from the inputs. No persisted state — every status call recomputes.
func DeriveHumanReview(labels []string, approvals []ApprovalRecord) HumanReviewState {
    out := HumanReviewState{}
    out.Required = hasLabelFold(labels, labelHumanReviewRequired)

    // satisfied_by: label first (cheaper, covers self-PR case).
    if hasLabelFold(labels, labelHumanApproved) {
        out.SatisfiedBy = "label"
    }

    // candidates_seen: enumerate APPROVED reviews; record Bot-filter outcome.
    for _, a := range approvals {
        if a.State != "APPROVED" {
            continue
        }
        cand := ApprovalCandidate{Login: a.Login, Approved: true}
        if a.ActorType == "Bot" {
            cand.Counted = false
            cand.Reason = "bot"
        } else {
            cand.Counted = true
        }
        out.Candidates = append(out.Candidates, cand)

        // First counted human approval wins, unless a label already satisfied.
        if cand.Counted && out.SatisfiedBy == "" {
            out.SatisfiedBy = "approval:" + cand.Login
        }
    }
    return out
}

func hasLabelFold(labels []string, needle string) bool {
    for _, l := range labels {
        if strings.EqualFold(l, needle) {
            return true
        }
    }
    return false
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestDeriveHumanReview' -v`
Expected: PASS — all nine subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/human_review.go internal/lifecycle/human_review_test.go
git commit -m "feat(prgroom): human-review constraint derivation (§4.4)"
```

---

### Task 11: `requestHumanReviewIfNeeded` + `shouldRequestHumanReview`

**Files:**
- Modify: `internal/lifecycle/human_review.go`
- Modify: `internal/lifecycle/human_review_test.go`

**Reference:** §4.7 pseudocode. `requestHumanReviewIfNeeded` is the side-effect wrapper around `shouldRequestHumanReview`; it adds the label, sets the dedup flag, and is best-effort on API failure.

- [ ] **Step 1: Write the failing tests**

Append to `internal/lifecycle/human_review_test.go`:

```go
import (
    "context"
    "errors"
)

func TestShouldRequestHumanReview(t *testing.T) {
    cases := []struct {
        name string
        state *prsession.PRGroomingState
        want bool
    }{
        {
            name: "no_gating_condition_no",
            state: &prsession.PRGroomingState{
                Items: []prsession.ReviewItem{{Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}}},
            },
            want: false,
        },
        {
            name: "hard_cap_yes",
            state: &prsession.PRGroomingState{LastError: "LIFECYCLE_HARD_CAP_EXCEEDED"},
            want: true,
        },
        {
            name: "escalated_item_yes",
            state: &prsession.PRGroomingState{
                Items: []prsession.ReviewItem{{Disposition: &prsession.Disposition{Kind: prsession.DispositionEscalated}}},
            },
            want: true,
        },
        {
            name: "failed_item_yes",
            state: &prsession.PRGroomingState{
                Items: []prsession.ReviewItem{{Disposition: &prsession.Disposition{Kind: prsession.DispositionFailed}}},
            },
            want: true,
        },
        {
            name: "runtime_terminal_user_no", // §4.7 explicit non-trigger
            state: &prsession.PRGroomingState{LastError: "RUNTIME_TERMINAL_USER"},
            want: false,
        },
        {
            name: "state_corrupt_no", // §4.7 explicit non-trigger
            state: &prsession.PRGroomingState{LastError: "STATE_CORRUPT"},
            want: false,
        },
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            if got := ShouldRequestHumanReview(c.state); got != c.want {
                t.Errorf("got %v, want %v", got, c.want)
            }
        })
    }
}

// fakeLabelAdder is a tiny in-test seam for the gh.AddLabel call.
type fakeLabelAdder struct {
    callCount int
    failNext  bool
    callsFor  []string // labels added per call
}

func (f *fakeLabelAdder) AddLabel(_ context.Context, _ prsession.PRRef, label string) error {
    f.callCount++
    if f.failNext {
        f.failNext = false
        return errors.New("simulated network failure")
    }
    f.callsFor = append(f.callsFor, label)
    return nil
}

func TestRequestHumanReviewIfNeeded_AddsLabelAndSetsDedup(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{PR: pr, LastError: "LIFECYCLE_HARD_CAP_EXCEEDED"}
    adder := &fakeLabelAdder{}
    cfg := HumanReviewCfg{AutoRequest: true}
    var written *prsession.PRGroomingState
    write := func(_ prsession.PRRef, s *prsession.PRGroomingState) error { written = s; return nil }

    RequestHumanReviewIfNeeded(context.Background(), state, adder, cfg, write)

    if adder.callCount != 1 {
        t.Errorf("AddLabel calls: got %d, want 1", adder.callCount)
    }
    if !state.HumanReviewLabelAdded {
        t.Error("HumanReviewLabelAdded should be true after successful add")
    }
    if written == nil {
        t.Error("store.Write should have been called after dedup flag set")
    }
}

func TestRequestHumanReviewIfNeeded_DedupSecondCallNoOp(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{
        PR: pr, LastError: "LIFECYCLE_HARD_CAP_EXCEEDED",
        HumanReviewLabelAdded: true, // already added this gating event
    }
    adder := &fakeLabelAdder{}
    cfg := HumanReviewCfg{AutoRequest: true}
    write := func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil }

    RequestHumanReviewIfNeeded(context.Background(), state, adder, cfg, write)

    if adder.callCount != 0 {
        t.Errorf("expected zero AddLabel calls under dedup; got %d", adder.callCount)
    }
}

func TestRequestHumanReviewIfNeeded_ApiFailureDoesNotSetDedup(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{PR: pr, LastError: "LIFECYCLE_HARD_CAP_EXCEEDED"}
    adder := &fakeLabelAdder{failNext: true}
    cfg := HumanReviewCfg{AutoRequest: true}
    write := func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil }

    RequestHumanReviewIfNeeded(context.Background(), state, adder, cfg, write)

    if state.HumanReviewLabelAdded {
        t.Error("dedup flag should NOT be set on API failure (so next cycle retries)")
    }
}

func TestRequestHumanReviewIfNeeded_AutoRequestDisabled(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    state := &prsession.PRGroomingState{PR: pr, LastError: "LIFECYCLE_HARD_CAP_EXCEEDED"}
    adder := &fakeLabelAdder{}
    cfg := HumanReviewCfg{AutoRequest: false}
    write := func(_ prsession.PRRef, _ *prsession.PRGroomingState) error { return nil }

    RequestHumanReviewIfNeeded(context.Background(), state, adder, cfg, write)

    if adder.callCount != 0 {
        t.Errorf("AutoRequest=false should suppress AddLabel; got %d calls", adder.callCount)
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestShouldRequestHumanReview|TestRequestHumanReviewIfNeeded' -v`
Expected: FAIL — none of the new types/functions defined.

- [ ] **Step 3: Implement should + request**

Append to `internal/lifecycle/human_review.go`:

```go
import (
    "context"
    "fmt"
    "os"

    "<module>/internal/prsession"
)

// HumanReviewCfg is the subset of config consumed by RequestHumanReviewIfNeeded.
type HumanReviewCfg struct {
    AutoRequest bool
}

// LabelAdder is the narrow seam over gh.Client used by RequestHumanReviewIfNeeded.
// The real implementation is *gh.Client; tests inject fakes.
type LabelAdder interface {
    AddLabel(ctx context.Context, pr prsession.PRRef, label string) error
}

// StoreWriter is the narrow seam for persisting state after dedup-flag flip.
type StoreWriter func(pr prsession.PRRef, state *prsession.PRGroomingState) error

// ShouldRequestHumanReview returns true iff the state matches a §4.7 trigger:
//   - LastError == "LIFECYCLE_HARD_CAP_EXCEEDED" (cap-trip), or
//   - at least one item with Disposition.Kind == Escalated or Failed.
// All other LastError values (RUNTIME_TERMINAL_USER, STATE_CORRUPT, etc.) and
// any state with no escalated/failed items are non-triggers, and the function
// returns false.
func ShouldRequestHumanReview(state *prsession.PRGroomingState) bool {
    if state.LastError == "LIFECYCLE_HARD_CAP_EXCEEDED" {
        return true
    }
    for i := range state.Items {
        d := state.Items[i].Disposition
        if d == nil {
            continue
        }
        if d.Kind == prsession.DispositionEscalated || d.Kind == prsession.DispositionFailed {
            return true
        }
    }
    return false
}

// RequestHumanReviewIfNeeded implements §4.7's request_human_review_if_needed.
// Best-effort: failure to add the label logs to stderr and leaves the dedup
// flag false so the next cycle retries. Idempotent under HumanReviewLabelAdded.
func RequestHumanReviewIfNeeded(
    ctx context.Context,
    state *prsession.PRGroomingState,
    adder LabelAdder,
    cfg HumanReviewCfg,
    write StoreWriter,
) {
    if !cfg.AutoRequest {
        return
    }
    if !ShouldRequestHumanReview(state) {
        return
    }
    if state.HumanReviewLabelAdded {
        return
    }
    if err := adder.AddLabel(ctx, state.PR, labelHumanReviewRequired); err != nil {
        fmt.Fprintf(os.Stderr, "prgroom: warning — failed to add %s label: %v\n", labelHumanReviewRequired, err)
        return // best-effort; dedup flag stays false; next cycle retries
    }
    state.HumanReviewLabelAdded = true
    if err := write(state.PR, state); err != nil {
        // Persistence failure here is bad — the label is on GitHub but our
        // state-side dedup won't survive. Log and continue; next invocation
        // will attempt the (idempotent) AddLabel a second time.
        fmt.Fprintf(os.Stderr, "prgroom: warning — failed to persist HumanReviewLabelAdded: %v\n", err)
    }
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestShouldRequestHumanReview|TestRequestHumanReviewIfNeeded' -v`
Expected: PASS — six + four = ten subtests.

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/human_review.go internal/lifecycle/human_review_test.go
git commit -m "feat(prgroom): RequestHumanReviewIfNeeded with dedup + best-effort error handling (§4.7)"
```

---

### Task 12: Wire `RequestHumanReviewIfNeeded` into `runLocked` (11 sites + reset)

**Files:**
- Modify: `internal/lifecycle/run.go`
- Modify: `internal/lifecycle/run_test.go` (or fit-test)

**Reference:** §3.3 pseudocode lines 611-718 — `request_human_review_if_needed(state)` lives at 11 dedup-safe sites adjacent to `escalate_if_needed`. Plus the clear-on-success branch at line 736 resets `state.HumanReviewLabelAdded = false`.

**The 11 sites (from spec line numbers 613, 633, 641, 654, 664, 672, 678, 694, 705, 711, 716):**

1. Entry-time external-transition probe `Propagate` path
2. Loop-top terminal-for-CLI check (clean transitions)
3. After `pollLocked` Propagate
4. After `waitLocked` Propagate (idle case)
5. After `waitLocked` Propagate (awaiting-review case)
6. After `clusterLocked` Propagate
7. After `fixLocked` Propagate
8. After `pushLocked` Propagate
9. After `rereviewLocked` Propagate
10. After `replyLocked` Propagate
11. After `resolveLocked` Propagate

**Plus** the clear-on-success branch (§3.3 line 736): `state.HumanReviewLabelAdded = false`.

- [ ] **Step 1: Write the failing fit-test**

Append to `internal/lifecycle/run_test.go` (or wherever the runLocked fit-test lives):

```go
func TestRunLocked_HardCapTripAddsHumanReviewLabel(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR: pr, Phase: prsession.PhaseFixesPending, Round: 3,
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
        },
    }
    adder := &fakeLabelAdder{}
    // (Build whatever fake deps the foundation's runLocked accepts —
    //  gh client, agent dispatcher, prsession.Store writer, etc. Set MaxRounds=3
    //  in config so this cycle trips the cap on push.)
    deps := buildTestRunDeps(t, fakeRunDepsOpts{
        Clock: func() time.Time { return now },
        QuiescenceCfg: QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        HumanReviewCfg: HumanReviewCfg{AutoRequest: true},
        LabelAdder: adder,
        MaxRounds: 3,
        // The fake fix verb should NOT escalate or fail items, but produce
        // queued commits so the cap check trips.
    })

    state, err := runLocked(context.Background(), pr, state, deps)
    if err != nil {
        t.Fatalf("runLocked: %v", err)
    }
    if state.Phase != prsession.PhaseHumanGated {
        t.Errorf("Phase: got %v, want human-gated", state.Phase)
    }
    if state.LastError != "LIFECYCLE_HARD_CAP_EXCEEDED" {
        t.Errorf("LastError: got %q, want LIFECYCLE_HARD_CAP_EXCEEDED", state.LastError)
    }
    if !state.HumanReviewLabelAdded {
        t.Error("HumanReviewLabelAdded should be true after cap trip")
    }
    if adder.callCount != 1 {
        t.Errorf("AddLabel: got %d calls, want 1 (one per cap-trip)", adder.callCount)
    }
}

func TestRunLocked_SuccessfulCycleResetsHumanReviewLabelAddedFlag(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    now := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR: pr, Phase: prsession.PhaseFixesPending,
        LastError: "LIFECYCLE_HARD_CAP_EXCEEDED",
        HumanReviewLabelAdded: true, // carryover from prior cap-trip
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
        },
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound},
        },
        Quiescence: prsession.QuiescenceState{CIState: "success"},
    }
    deps := buildTestRunDeps(t, fakeRunDepsOpts{
        Clock: func() time.Time { return now },
        QuiescenceCfg: QuiescenceCfg{IdleThreshold: 0}, // immediately quiescible
        HumanReviewCfg: HumanReviewCfg{AutoRequest: true},
        MaxRounds: 10,
        // No queued commits this cycle → no cap trip; end-of-cycle resolves to quiesced.
    })

    state, err := runLocked(context.Background(), pr, state, deps)
    if err != nil {
        t.Fatalf("runLocked: %v", err)
    }
    if state.Phase != prsession.PhaseQuiesced {
        t.Errorf("Phase: got %v, want quiesced", state.Phase)
    }
    if state.HumanReviewLabelAdded {
        t.Error("HumanReviewLabelAdded should be false after clear-on-success")
    }
    if state.LastError != "" {
        t.Errorf("LastError should also clear; got %q", state.LastError)
    }
}
```

The `buildTestRunDeps` helper depends on how the §3-lifecycle bead wrote `runLocked`'s deps struct. Build out the helper inline based on the actual struct shape; the structure here is illustrative.

- [ ] **Step 2: Run tests, verify failure**

Run: `go test ./internal/lifecycle/ -run 'TestRunLocked_HardCap|TestRunLocked_Successful' -v`
Expected: FAIL — `runLocked` doesn't call `RequestHumanReviewIfNeeded` yet; the flag stays false and the AddLabel fake is never called.

- [ ] **Step 3: Add the 11 callsites + reset**

Open `internal/lifecycle/run.go`. The function `runLocked` should mirror the §3.3 pseudocode at lines 600-739 of the spec. At each of the 11 sites adjacent to `escalate_if_needed`, add:

```go
state = escalate_if_needed(state)                            // existing
RequestHumanReviewIfNeeded(ctx, state, deps.LabelAdder, deps.HumanReviewCfg, deps.StoreWrite) // §4.7
```

(Or whatever the project's naming style is — adapt to the existing call shape of `escalate_if_needed`.)

In the clear-on-success branch (the spec's lines 724-738 — when `state.Phase ∉ {human-gated}` after `resolve_end_of_cycle_phase`), add:

```go
state.HumanReviewLabelAdded = false // §4.7: reset so next gating event re-adds the label
```

The `runLocked` deps struct gains two fields if not already present:

```go
type runDeps struct {
    // ... existing ...
    LabelAdder     LabelAdder
    HumanReviewCfg HumanReviewCfg
    StoreWrite   StoreWriter
}
```

Wire these from the `Run` public wrapper (cmd/prgroom wiring may need a tiny update to plumb `cfg.Quiescence.AutoRequestHumanReview` into the deps).

- [ ] **Step 4: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestRunLocked_HardCap|TestRunLocked_Successful' -v`
Expected: PASS — both subtests.

Then: `go test ./internal/lifecycle/ -v`
Expected: PASS — existing tests should be unaffected (the new call is no-op when `ShouldRequestHumanReview` returns false, which is the default for tests that don't set up a gating condition).

- [ ] **Step 5: Commit**

```bash
git add internal/lifecycle/run.go internal/lifecycle/run_test.go
git commit -m "feat(prgroom): runLocked wires RequestHumanReviewIfNeeded at 11 sites + reset (§4.7)"
```

---

### Task 13: Extend `prgroom status --json` with merge gates + human review

**Files:**
- Modify: whichever foundation file implements the `status` verb's JSON output (likely `internal/status/json.go` or `cmd/prgroom/status.go`)
- Modify: corresponding `_test.go`

**Reference:** §4.6 — exact JSON shape, derivation rules, stability commitment ("Adding fields is non-breaking; removing/renaming is breaking and requires version bump"). The function pulls labels + approvals from the gh adapter at query time (this is the `status` verb's already-existing fetch).

- [ ] **Step 1: Find the status output struct**

Read the foundation's `status` JSON output struct. It already has `pr`, `phase`, `last_error`, `round`, `reviewers`, `last_activity_at`, etc. We add `ci_state`, `quiesced_at`, `merge_gates`, `human_review`, `auto_merge_eligible`, and `items_summary`.

- [ ] **Step 2: Write the failing golden-file test**

Create or extend the status test:

```go
func TestStatusJSON_Section4Fields(t *testing.T) {
    state := &prsession.PRGroomingState{
        PR:                prsession.PRRef{Owner: "o", Repo: "r", Number: 42},
        Phase:             prsession.PhaseQuiesced,
        Round:             2,
        Quiescence:        prsession.QuiescenceState{CIState: "success", QuiescedAt: time.Date(2026, 5, 25, 14, 42, 11, 0, time.UTC)},
        LastActivityAt:    time.Date(2026, 5, 25, 14, 32, 11, 0, time.UTC),
        Reviewers: map[string]prsession.ReviewerState{
            "github-copilot[bot]": {Identity: "github-copilot[bot]", Kind: prsession.ReviewerBot, Required: true, Status: prsession.ReviewerReviewFound},
            "alice":               {Identity: "alice", Kind: prsession.ReviewerHuman, Required: false, Status: prsession.ReviewerInProgress},
        },
        Items: []prsession.ReviewItem{
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}},
            {Disposition: &prsession.Disposition{Kind: prsession.DispositionAlreadyAddressed}},
        },
    }
    labels := []string{"human-review-required"}
    approvals := []lifecycle.ApprovalRecord{} // none
    out := BuildStatusJSON(state, labels, approvals)

    if out.AutoMergeEligible {
        t.Error("auto_merge_eligible should be false when human-review-required is set but not satisfied")
    }
    if !out.MergeGates.PhaseIsQuiesced {
        t.Error("phase_is_quiesced should be true")
    }
    if out.MergeGates.HumanReviewSatisfied {
        t.Error("human_review_satisfied should be false")
    }
    if out.HumanReview.Required != true {
        t.Error("human_review.required should be true")
    }
    if out.HumanReview.SatisfiedBy != "" {
        t.Errorf("human_review.satisfied_by: got %q, want empty", out.HumanReview.SatisfiedBy)
    }
    if out.ItemsSummary.Fixed != 3 {
        t.Errorf("items_summary.fixed: got %d, want 3", out.ItemsSummary.Fixed)
    }
    if out.ItemsSummary.AlreadyAddressed != 1 {
        t.Errorf("items_summary.already_addressed: got %d, want 1", out.ItemsSummary.AlreadyAddressed)
    }
}

func TestStatusJSON_AutoMergeEligibleWhenAllGatesPass(t *testing.T) {
    state := &prsession.PRGroomingState{
        Phase:      prsession.PhaseQuiesced,
        LastError:  "",
        Items:      []prsession.ReviewItem{{Disposition: &prsession.Disposition{Kind: prsession.DispositionFixed}}},
        Quiescence: prsession.QuiescenceState{CIState: "success"},
    }
    labels := []string{}    // no human-review-required → constraint not active
    approvals := []lifecycle.ApprovalRecord{}
    out := BuildStatusJSON(state, labels, approvals)
    if !out.AutoMergeEligible {
        t.Errorf("auto_merge_eligible should be true; merge_gates=%+v", out.MergeGates)
    }
}

func TestStatusJSON_BotApprovalInCandidatesNotCounted(t *testing.T) {
    state := &prsession.PRGroomingState{Phase: prsession.PhaseQuiesced}
    labels := []string{"human-review-required"}
    approvals := []lifecycle.ApprovalRecord{
        {Login: "github-copilot[bot]", State: "APPROVED", ActorType: "Bot"},
    }
    out := BuildStatusJSON(state, labels, approvals)
    if out.AutoMergeEligible {
        t.Error("bot approval must not satisfy human-review constraint")
    }
    if len(out.HumanReview.Candidates) != 1 {
        t.Fatalf("expected 1 candidate; got %d", len(out.HumanReview.Candidates))
    }
    c := out.HumanReview.Candidates[0]
    if c.Counted || c.Reason != "bot" {
        t.Errorf("candidate: got Counted=%v Reason=%q; want Counted=false Reason=bot", c.Counted, c.Reason)
    }
}
```

- [ ] **Step 3: Run tests, verify failure**

Run: `go test ./internal/status/ -run 'TestStatusJSON_Section4' -v`
Expected: FAIL — `BuildStatusJSON` output struct missing the new fields.

- [ ] **Step 4: Extend the output struct + builder**

Add to the status JSON output (illustrative — match the foundation's existing JSON tags and field names):

```go
type StatusJSON struct {
    // ... existing: PR, Phase, LastError, Round, Reviewers, LastActivityAt ...

    CIState           string                  `json:"ci_state,omitempty"`
    QuiescedAt        time.Time               `json:"quiesced_at,omitempty"`
    ItemsSummary      ItemsSummary            `json:"items_summary"`
    MergeGates        MergeGates              `json:"merge_gates"`
    HumanReview       lifecycle.HumanReviewState `json:"human_review"`
    AutoMergeEligible bool                    `json:"auto_merge_eligible"`
}

type ItemsSummary struct {
    Fixed            int `json:"fixed"`
    AlreadyAddressed int `json:"already_addressed"`
    WontFix          int `json:"wont_fix"`
    Escalated        int `json:"escalated"`
    Failed           int `json:"failed"`
    Skipped          int `json:"skipped"`
    Deferred         int `json:"deferred"`
}

type MergeGates struct {
    PhaseIsQuiesced      bool `json:"phase_is_quiesced"`
    LastErrorClear       bool `json:"last_error_clear"`
    NoBlockerItems       bool `json:"no_blocker_items"`
    HumanReviewSatisfied bool `json:"human_review_satisfied"`
}

func BuildStatusJSON(state *prsession.PRGroomingState, labels []string, approvals []lifecycle.ApprovalRecord) StatusJSON {
    hr := lifecycle.DeriveHumanReview(labels, approvals)
    summary := summarizeItems(state.Items)
    gates := MergeGates{
        PhaseIsQuiesced:      state.Phase == prsession.PhaseQuiesced,
        LastErrorClear:       state.LastError == "",
        NoBlockerItems:       summary.Escalated == 0 && summary.Failed == 0,
        HumanReviewSatisfied: !hr.Required || hr.SatisfiedBy != "",
    }
    return StatusJSON{
        // ... existing field assignment ...
        CIState:           state.Quiescence.CIState,
        QuiescedAt:        state.Quiescence.QuiescedAt,
        ItemsSummary:      summary,
        MergeGates:        gates,
        HumanReview:       hr,
        AutoMergeEligible: gates.PhaseIsQuiesced && gates.LastErrorClear && gates.NoBlockerItems && gates.HumanReviewSatisfied,
    }
}

func summarizeItems(items []prsession.ReviewItem) ItemsSummary {
    var s ItemsSummary
    for i := range items {
        d := items[i].Disposition
        if d == nil {
            continue
        }
        switch d.Kind {
        case prsession.DispositionFixed:           s.Fixed++
        case prsession.DispositionAlreadyAddressed: s.AlreadyAddressed++
        case prsession.DispositionWontFix:         s.WontFix++
        case prsession.DispositionEscalated:       s.Escalated++
        case prsession.DispositionFailed:          s.Failed++
        case prsession.DispositionSkipped:         s.Skipped++
        case prsession.DispositionDeferred:        s.Deferred++
        }
    }
    return s
}
```

Wire the `status` verb's gh-fetch (already there from foundation) to populate `labels` and `approvals` before calling `BuildStatusJSON`.

- [ ] **Step 5: Run tests, verify pass**

Run: `go test ./internal/status/ -run 'TestStatusJSON_Section4' -v`
Expected: PASS — all three subtests.

- [ ] **Step 6: Commit**

```bash
git add internal/status/ cmd/prgroom/status.go
git commit -m "feat(prgroom): status --json exposes §4.6 merge gates + human review + auto_merge_eligible"
```

---

### Task 14: Resumability fit-test (state survives simulated restart)

**Files:**
- Modify (or create): `internal/lifecycle/lifecycle_fit_test.go`

**Reference:** §4.2 "Resumability (crash-recovery semantics)". All §4 timestamps are stored as absolute UTC; deadlines derive per-evaluation. Process restart must produce the same outcome as if the process had never died.

- [ ] **Step 1: Write the failing fit-test**

Append to `internal/lifecycle/lifecycle_fit_test.go`:

```go
func TestResumability_TimeoutDeadlinesAcrossSimulatedRestart(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 42}
    requestedAt := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR: pr,
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {
                Identity:      "copilot",
                Required:      true,
                Status:        prsession.ReviewerRequested,
                LastRequestAt: requestedAt,
            },
        },
        LastPushedHeadSHA: "abc",
    }

    // Pretend the process died and is restarting 4 minutes later (past 3m start
    // timeout). Re-invoking pollLocked must auto-decline the reviewer using
    // the persisted LastRequestAt.
    laterNow := requestedAt.Add(4 * time.Minute)
    deps := pollDeps{
        GH:    &fakeGH{HeadSHA: "abc"},
        Clock: func() time.Time { return laterNow },
        Cfg:   TimeoutsCfg{ReviewStartTimeout: 3 * time.Minute, ReviewFinishTimeout: 15 * time.Minute},
    }
    state, err := pollLocked(pr, state, deps)
    if err != nil {
        t.Fatalf("pollLocked: %v", err)
    }
    r := state.Reviewers["copilot"]
    if r.Status != prsession.ReviewerDeclined || r.DeclinedReason != "timeout-no-start" {
        t.Errorf("post-restart auto-decline failed: Status=%v Reason=%q", r.Status, r.DeclinedReason)
    }
}

func TestResumability_ConfigChangeMidFlightExtendsExistingDeadline(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 42}
    requestedAt := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR: pr,
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerRequested, LastRequestAt: requestedAt},
        },
        LastPushedHeadSHA: "abc",
    }
    // Operator raised start timeout 3m → 5m mid-flight. At t=4m, the reviewer
    // should still be `requested` (NOT auto-declined yet) under the new config.
    fourMinutesLater := requestedAt.Add(4 * time.Minute)
    deps := pollDeps{
        GH:    &fakeGH{HeadSHA: "abc"},
        Clock: func() time.Time { return fourMinutesLater },
        Cfg:   TimeoutsCfg{ReviewStartTimeout: 5 * time.Minute, ReviewFinishTimeout: 15 * time.Minute},
    }
    state, err := pollLocked(pr, state, deps)
    if err != nil {
        t.Fatalf("pollLocked: %v", err)
    }
    r := state.Reviewers["copilot"]
    if r.Status != prsession.ReviewerRequested {
        t.Errorf("config extension should suppress auto-decline; got Status=%v Reason=%q", r.Status, r.DeclinedReason)
    }
}
```

- [ ] **Step 2: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestResumability' -v`
Expected: PASS — both tests are derivative of Task 4's `EvaluateReviewerTimeouts` already-correct behavior. If either fails, the bug is in Task 4's implementation or Task 5's `pollLocked` wiring.

- [ ] **Step 3: Commit**

```bash
git add internal/lifecycle/lifecycle_fit_test.go
git commit -m "test(prgroom): resumability fit-tests for §4 timeout deadlines"
```

---

### Task 15: End-to-end quiescence fit-test

**Files:**
- Modify: `internal/lifecycle/lifecycle_fit_test.go`

**Reference:** §4.1 quiescence trip end-to-end. Drive `runLocked` through one full cycle that ends in `quiesced` with all gates passing.

- [ ] **Step 1: Write the failing fit-test**

```go
func TestRunLocked_HappyPathQuiescenceTripsToQuiesced(t *testing.T) {
    pr := prsession.PRRef{Owner: "o", Repo: "r", Number: 1}
    start := time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC)
    state := &prsession.PRGroomingState{
        PR:    pr,
        Phase: prsession.PhaseFixesPending,
        Round: 1,
        Items: []prsession.ReviewItem{
            // pre-populated, ready to disposition; the fake fix verb resolves all
        },
        Reviewers: map[string]prsession.ReviewerState{
            "copilot": {Identity: "copilot", Required: true, Status: prsession.ReviewerReviewFound, LastRequestAt: start.Add(-10 * time.Minute)},
        },
        LastActivityAt:    start.Add(-15 * time.Minute), // already idle
        LastPushedHeadSHA: "abc",
        Quiescence:        prsession.QuiescenceState{CIState: "success"},
    }
    deps := buildTestRunDeps(t, fakeRunDepsOpts{
        Clock:          func() time.Time { return start },
        QuiescenceCfg:  QuiescenceCfg{IdleThreshold: 10 * time.Minute},
        HumanReviewCfg: HumanReviewCfg{AutoRequest: true},
        MaxRounds:      3,
        // No new clusters/fixes needed; cluster/fix verbs return clean.
        // Reply/resolve verbs are no-ops on already-dispositioned items.
        // End-of-cycle resolver hits priority 5 and trips to quiesced.
    })
    state, err := runLocked(context.Background(), pr, state, deps)
    if err != nil {
        t.Fatalf("runLocked: %v", err)
    }
    if state.Phase != prsession.PhaseQuiesced {
        t.Errorf("Phase: got %v, want quiesced", state.Phase)
    }
    if state.Quiescence.QuiescedAt.IsZero() {
        t.Error("QuiescedAt should be stamped on quiescence trip")
    }
    if state.HumanReviewLabelAdded {
        t.Error("HumanReviewLabelAdded should be false on happy-path quiescence")
    }
}
```

- [ ] **Step 2: Run tests, verify pass**

Run: `go test ./internal/lifecycle/ -run 'TestRunLocked_HappyPath' -v`
Expected: PASS. If it fails because `runLocked` doesn't reach the end-of-cycle resolver in this state shape, the bug is in §3-lifecycle bead's runLocked flow, not §4 — file a blocker and investigate.

- [ ] **Step 3: Commit**

```bash
git add internal/lifecycle/lifecycle_fit_test.go
git commit -m "test(prgroom): end-to-end happy-path quiescence fit-test"
```

---

### Task 16: Full-suite verification + coverage check

- [ ] **Step 1: Run the full test suite**

```bash
go test ./... -race
```

Expected: PASS — all tests across all packages.

- [ ] **Step 2: Run coverage check**

```bash
go test ./internal/lifecycle/ -coverprofile=/tmp/cover.out
go tool cover -func=/tmp/cover.out | tail -20
```

Expected: line coverage ≥ 80% on changed code per §7's commitment. Branch coverage requires `--cov-branch` equivalent which Go doesn't natively support; the GHA gate (per §7) covers this at CI time.

- [ ] **Step 3: Run linter + vuln check**

```bash
golangci-lint run ./internal/lifecycle/ ./internal/gh/ ./internal/status/ ./internal/config/
govulncheck ./...
```

Expected: clean. Fix any findings before moving on.

- [ ] **Step 4: Build the binary**

```bash
go build -o /tmp/prgroom ./cmd/prgroom/
/tmp/prgroom --help
```

Expected: builds cleanly; `--help` lists the new flags from Task 1.

- [ ] **Step 5: Smoke-test status on a real PR (optional but recommended)**

If a PR exists where `prgroom` state has been written (or a test fixture in `testdata/`), invoke:

```bash
/tmp/prgroom status <pr> --json | jq '.merge_gates, .human_review, .auto_merge_eligible'
```

Expected: the three new fields render per §4.6 shape.

- [ ] **Step 6: Commit any cleanup**

```bash
git status # check nothing surprising is unstaged
# Commit any pure cleanup (gofmt, comment polish) discovered during the verification pass:
git add ...
git commit -m "chore(prgroom): post-implementation cleanup (gofmt, comments)"
```

---

## Self-Review Notes for the Implementer

After Task 16:

1. **Spec coverage check** — open `docs/plans/2026-05-12-prgroom-cli-design.md` §4 and skim every subsection. Each of §4.1, §4.2, §4.3, §4.4, §4.6, §4.7 maps to one or more tasks above; §4.5 is a cross-reference (no code) and §4.8 is a schema-fields reference (covered by Prerequisites). If you find an unaddressed spec requirement, file a follow-on bead with `bd dep add <new-bead> <impl-bead> --type discovered-from`.

2. **The "no hard wait-timeout" non-trigger** (§4.2 line 1103-1105) — no code is needed; document via a `// §4.2: no hard wait-timeout in MVP — see spec` comment on the `waitLocked` for-loop if helpful for the reader. (Default to no comment per project convention; only add if a future reader is likely to ask "why no timeout here?")

3. **The §4.4 "operator workflow" bullet list** (lines 1170-1175) — those are operator UX docs, not implementation surface. Confirm the labels `human-review-required` and `human-approved` are both queryable via `prgroom status --json .merge_gates.human_review_satisfied`.

4. **`§4.5` non-task** — §3.5's MaxRounds=3 default is unchanged by this plan. Confirm by `grep -n "MaxRounds" internal/config/` and noting the value is set by the §3-lifecycle bead, not here.

5. **`§4.7 operator override`** (line 1301) — explicitly verified by Task 11's `TestRequestHumanReviewIfNeeded_DedupSecondCallNoOp`. The override semantic (operator removes label → CLI does NOT re-add until reset+regate) is a function of the dedup flag's persistence; the test covers the persistence path.

---

## Execution Notes

This plan does NOT include the standard "Execution Handoff" choice (subagent-driven vs. inline). Per the orchestrator's instruction at plan-writing time: **do NOT start the implementation bead from this plan.** The plan exists as the deliverable that ratifies `agents-config-fca6.2`'s design phase. An implementation bead will be filed under the `agents-config-fca6` epic at a separate decision point; the implementer there will receive this plan as their input.

**For the future implementer:**

- Foundation (`abn9.8.1`) and §3-lifecycle bead must be complete before this plan executes. Confirm the Prerequisites section at the top before claiming the implementation bead.
- Per the project completion-gate rule, after Task 16 run `quality-reviewer` agent, `simplify` skill, `verify-checklist` skill before opening the PR.
- Per the project delivery rule, after PR creation invoke `wait-for-pr-comments` (chains to `reply-and-resolve-pr-threads`).
- Per the user's note on subagent dispatch, this plan's pseudocode has been written with `ruff`/`go vet` mindset — but Go-specific lint fixes (especially `golangci-lint` rule deviations) may still appear; authorize the implementer to apply minimum-deviation fixes that match existing project precedent.
