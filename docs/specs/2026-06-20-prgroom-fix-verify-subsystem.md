# 2026-06-20 — prgroom fix↔verify subsystem

> **Status**: approved (design) — feeds implementation beads `agents-config-abn9.8.22`, `agents-config-abn9.8.23` (+ children), gated by `agents-config-abn9.8.25`.
> **Source bead**: `agents-config-fca6.16`
> **Extends**: `docs/plans/2026-05-12-prgroom-cli-design.md` — this spec is the source-of-truth for the **fix↔verify gate**, the **trust-but-verify fix contract**, and the **retry-cap reframe**. It refines that plan's §3.5 (PR-review retry budget), §3.6/§3.7 (new codes + tier), and §5 (fix-contract output + repair dispatch).
> **HLD artifacts** (this PR): [`c4-l3-verify.md`](../architecture/prgroom/c4-l3-verify.md) + deltas to [`c4-l3-lifecycle.md`](../architecture/prgroom/c4-l3-lifecycle.md), [`state-machine.md`](../architecture/prgroom/state-machine.md), [`data-view.md`](../architecture/prgroom/data-view.md), [`c4-l3-agent-dispatch.md`](../architecture/prgroom/c4-l3-agent-dispatch.md), [`index.md`](../architecture/prgroom/index.md).

## 1. Problem — the undesigned seam

prgroom's `fix → push` path has an architecture gap: nothing designed the contract between the **fix agent** (which edits code to address review clusters, and can introduce *new* defects it should have caught) and a **mechanical verifier** that confirms the branch is sound before the push elicits another review round. Two halves were missing:

1. **The fix agent was a muzzled editor.** Its allow-list is `Read Edit Write Bash(git *)` (`agent/subprocess_runner.py:224`) — it cannot run the repo's tests/build/lint, spawn sub-agents, or invoke skills. It is launched top-level via `claude -p` (NOT a nested sub-agent), so it *can* safely orchestrate — the await-own-child footgun does not apply — but it is not armed to.
2. **There was no gate of record.** `recommended_gate` is emitted by the fix contract (`agent/contracts.py:128`) and persists as `Disposition.gate` (`prsession/state.py:87`), but **nothing consumes it** — it is a free `str` read only by tests. No mechanical verification runs before push.

This spec fills both halves and the contract between them.

## 2. Decisions (grounded — do not relitigate)

- **prgroom's verifier is a MECHANICAL command gate** — it runs the repo's tests/build/lint via the existing `proc.CommandRunner`, NOT an agent review. Agent review is what the *fix agent* does to itself; prgroom's gate is the independent, deterministic confirmation (*Code over Prose*; trust-but-verify).
- **Whole-branch, max-strength tier.** `recommended_gate` is per-item, but push is all-or-nothing (`git push HEAD:branch`) and the resolver already gates the whole PR on any one `FAILED` item. So the gate takes the **strongest** `recommended_gate` across the clean `FIXED` items (any `full` ⇒ full, else `lite`) and runs **one** whole-branch gate. No per-item push partitioning.
- **Insertion point.** A new `verify` `VerbStep` after `fix` (after its audits) and before `cap-guard`/`push`, mirroring the cap-guard pattern: a pre-push step that refuses the push by flipping `phase`.
- **Fail path = bounded auto-re-fix.** On a red gate, the fix agent is re-dispatched against the gate output, re-audited, and re-gated; push happens only when green. Bounded by its own retry budget (the PR-review retry budget counts *pushes*; a verify-fail never pushes, so the PR-review retry budget cannot bound it).
- **Two sibling retry caps.** Both the inner (fix↔verify) and outer (PR-review) loops are expressed as **retry caps** that escalate to `human-gated` on exhaustion, with consistently-named blocking codes and identical re-arm semantics.
- **Verdict at batch level.** The verify verdict is persisted on `PRGroomingState`, not per-item (`FAILED` drops the gate field, and verification is whole-branch).
- **Unconfigured command ⇒ hard stop.** prgroom checks at startup and exits hard with guidance; never a silent skip. Auto-detection is deferred to a separate `--doctor` bead.

## 3. The pipeline and the verify step

### 3.1 Position

The lifecycle pipeline (`lifecycle/run.py:_build_pipeline`) gains one step between `fix` and `cap-guard`:

```
cluster → fix → verify → cap-guard → push → reply → resolve → rereview
```

The `verify` step **no-ops when `not has_queued`** (there are no fix commits to verify — mirrors `_push`'s degenerate no-op).

### 3.2 Refusal mechanism

`verify` refuses the push by the **identical** mechanism as `cap-guard`: on terminal failure it sets `phase = HUMAN_GATED`, and the pipeline's post-step terminal check (`run.py:386-393`) breaks the loop before `cap-guard`, `push`, `reply`, or `resolve` run; the loop-top then flushes the escalation + human-review label. Effectful failures inside the step (a `CommandRunner` error, an agent-CLI failure) raise a tagged `PrgroomError` and route through the single shared error site (`_execute_step`, `run.py:437-456`) like any verb.

### 3.3 The fix↔verify convergence loop

The convergence loop is the heart of the subsystem. Within one `fixes-pending` cycle:

```
fix (initial)
  └─ verify: run mechanical gate (tier-selected, whole-branch)
       ├─ GREEN  → fall through to cap-guard → push
       └─ RED    → if fix_verify_retries remain:
       │              write gate output → temp file
       │              dispatch REPAIR fix (whole-branch, fed the temp file)
       │              re-audit (orphan / sha / repair-attribution)
       │              re-run gate            ← loop
       └─ exhausted → phase = HUMAN_GATED + LIFECYCLE_FIX_VERIFY_EXHAUSTED
```

The decision to re-fix-or-escalate is made **after** `verify` produces a verdict — a guard placed before `verify` would be blind to whether the work is good enough to push. The loop's budget is independent of the PR-review retry budget because a verify-fail never pushes.

## 4. The two retry caps

Both caps are **retry caps**: they escalate to `human-gated` on exhaustion, surface a blocking `LIFECYCLE_*_EXHAUSTED` code, and re-arm by raising the budget (entry-probe) or by `poll` observing an external fix.

| | **Inner — FIX↔VERIFY loop** | **Outer — PR_REVIEW loop** |
|---|---|---|
| Bounds | repair re-fixes within one cycle (no push between) | review-eliciting pushes across cycles |
| Knob | `fix_verify_retries` | `pr_review_retries` |
| Default | **2** (⇒ max 3 `opus[1m]` fix spends/cycle) | **5** (initial push + 5 fix-pushes = 6 pushes) |
| Counter | new, 0-indexed retry count | `pr_review_retries_used`, 0-indexed retry count |
| Exhaustion code | `LIFECYCLE_FIX_VERIFY_EXHAUSTED` | `LIFECYCLE_PR_REVIEW_EXHAUSTED` |
| Tier / exit | `LIFECYCLE_CAP` / 0 (graceful terminal) | `LIFECYCLE_CAP` / 0 (graceful terminal) |
| Re-arm | raise `--fix-verify-retries` (entry-probe) or `poll` | raise `--pr-review-retries` (entry-probe) or `poll` |

**Outer-cap reframe is a separate effort.** The outer cap is the PR-review retry budget: `pr_review_retries` (default 5), surfacing `LIFECYCLE_PR_REVIEW_EXHAUSTED`, with the 0-indexed `pr_review_retries_used` counter. The code + counter migration is owned by `agents-config-abn9.8.25` (which blocks 8.23); this spec and every HLD artifact depict the to-be state.

**Behavior at the outer boundary.** A *verified-good* batch is still escalated when `pr_review_retries` is spent — the outer cap bounds *review iteration*, not mechanical quality (a green push still elicits another review that may surface fresh comments). The inner cap governs mechanical convergence; the outer cap governs how many review rounds run before a human confirms. Orthogonal loops, same retry-cap shape.

## 5. Trust-but-verify — the fix↔verify contract

Two halves, with the mechanical gate authoritative:

1. **The fix agent's claim.** The armed fix agent runs its *own* completion gate (its skills/sub-agents run tests/build/lint) and emits a **required** `verify_checklist` artifact in `FixOutput` — what it ran and the result. On a batch with `FIXED` items, a missing or malformed `verify_checklist` is a contract-audit failure (`CONTRACT_FIX_AUDIT_FAILED` → the item flips to `FAILED`). The artifact is a **forcing function** (the contract compels the agent to gate itself) and **evidence** (an audit trail) — it is *not* byte-compared against the mechanical result.
2. **prgroom's confirmation.** The `verify` step runs the operator-configured tier command via `proc.CommandRunner`, whole-branch, in the worktree. This run is the **gate of record**. A divergence (agent claimed green, mechanical gate is red) is resolved by the mechanical result — it drives the auto-re-fix loop.

### 5.1 The armed fix agent

The fix agent's allow-list broadens from `Read Edit Write Bash(git *)` to the full implementation set (broad `Bash`, `Task`, `Skill`, …) so it can run its completion gate and orchestrate sub-agents. A configurable allow/deny aggregation layer governs the concrete set.

**Security — residual risk.** The armed fix agent is a headless `--permission-mode dontAsk` process with broad shell, running on a branch whose review threads carry **attacker-authored text** — a prompt-injection surface. It is mitigated by worktree-trust (the agent runs in the operator's already-trusted worktree) and operator opt-in (autonomous grooming is a deliberate choice), and is documented as an accepted residual risk, not a blocker.

### 5.2 The repair dispatch

The auto-re-fix loop re-invokes the fix agent in a **repair** mode distinct from the per-cluster fix:

- **Whole-branch, not per-cluster** — the mechanical gate failure is a property of the branch, not attributable to one review cluster.
- **Input** gains an optional `verify_failure_path` (the temp file holding the gate's `stdout`/`stderr`/exit code) and a repair-mode prompt (`fix-repair` template).
- **Commit-attribution audit is adapted** — the orphan/sha audit attributes the repair's new commits to the verify-repair batch, not to any review item (the standard per-cluster orphan rule, "every commit claimed by some item", does not apply to whole-branch repair commits).

## 6. Data-model deltas

### 6.1 `GateStrength`

```python
class GateStrength(StrEnum):
    FULL = "full"
    LITE = "lite"
```

`Disposition.gate` is typed/validated against `GateStrength`. A `FIXED` item whose `gate` is absent or not a valid `GateStrength` is a `CONTRACT_FIX_AUDIT_FAILED`. This makes `recommended_gate` load-bearing.

### 6.2 `VerifyVerdict` (batch-level on `PRGroomingState`)

```python
@dataclass(frozen=True, slots=True)
class VerifyVerdict:
    result: str            # "passed" | "failed"
    tier: GateStrength     # the gate strength actually run
    retries_used: int      # repair re-fix attempts consumed this cycle
    gate_output_ref: str   # path/excerpt of the last gate output (for status + escalation)
    decided_at: datetime   # UTC
```

Added as `verify: VerifyVerdict | None` on `PRGroomingState`. **Additive, omit-when-`None`** in JSON, so old state files load `None` and `schema_version` stays `1` (parallels the `pending_memory` precedent).

### 6.3 `status --json` — new `verify` block

`build_status()` (`lifecycle/status.py`) gains a `verify` block (additive, non-breaking):

```json
"verify": {
  "result": "failed",
  "tier": "full",
  "retries_used": 2,
  "last_error": "LIFECYCLE_FIX_VERIFY_EXHAUSTED"
}
```

`last_error` continues to surface the exhaustion code at the top level too.

## 7. Error codes & preconditions

| Code | Tier (exit) | Phase | Blocking | Meaning |
|---|---|---|---|---|
| `LIFECYCLE_FIX_VERIFY_EXHAUSTED` | `LIFECYCLE_CAP` (0) | → human-gated | yes | inner retry budget spent, gate still red |
| `LIFECYCLE_PR_REVIEW_EXHAUSTED` | `LIFECYCLE_CAP` (0) | → human-gated | yes | outer review-retry budget spent |
| `PRECONDITION_NO_VERIFY_CONFIG` | `PRECONDITION_USER_ERROR` (2) | unchanged | n/a | the tier's verify command is unconfigured |

- Both `LIFECYCLE_*_EXHAUSTED` codes join `BlockingErrorCodes` (cleared only by raising the relevant budget — entry-probe re-arm — or by `poll` observing an external fix; not by `resolve-escalated` alone).
- `PRECONDITION_NO_VERIFY_CONFIG` follows the existing structured-stderr precondition pattern (what / why / how + code), raised at `run`/`fix` entry when the needed tier command is unconfigured. It is **not** in the `PRECONDITION_NO_WORK` set — absence of config is a user-actionable error, not absence of work.

## 8. Configuration surface

A `[verify]` table in the per-repo `.prgroom.toml`, following the established precedence **flag > env > TOML > built-in default**:

```toml
[verify]
lite          = "make lint"      # command (or list) run for the lite tier
full          = "make ci"        # command (or list) run for the full tier
fix_verify_retries = 2           # inner retry budget
```

- The verify **commands have no built-in default** — their absence for a needed tier is the §7 hard stop (the gate must be deliberately configured, never silently skipped).
- `fix_verify_retries` defaults to `2`; `--fix-verify-retries` / `PRGROOM_FIX_VERIFY_RETRIES` override.
- This work **wires `repo_config`**, which is currently always passed `None` (the `.prgroom.toml` is never actually read today); the search resolves the repo-root `.prgroom.toml`.

## 9. State-machine deltas

One new transition out of `fixes-pending`, parallel to the cap-guard edge:

- `fixes-pending → human-gated` via the `verify` step when `fix_verify_retries` is exhausted — carries the `EscalationSink` emit + the §4.7 `human-review-required` auto-label (it reuses `request_human_review_if_needed`, gated on `phase=human-gated`).

The inner convergence loop is **not** a state-machine transition — like the `fix` step's per-cluster fan-out, it is internal to one cycle. The outer-cap edge carries the `LIFECYCLE_PR_REVIEW_EXHAUSTED` code under the PR-review retry budget framing (per §4 / 8.25).

## 10. Sequence — one cycle with a repair

```
fix          → commits + dispositions + verify_checklist claim
verify gate  → RED (agent regressed a test)
  └ write gate output → /tmp/prgroom-verify-XXXX
  └ repair dispatch (whole-branch, fed the temp file)
  └ re-audit (orphan/sha, repair-attribution)
  └ verify gate → GREEN
cap-guard    → pr_review_retries_used < pr_review_retries → no-op
push         → git push HEAD:branch ; pr_review_retries_used++
reply/resolve/rereview …
```

## 11. Decomposition (implementation beads)

| Bead | Scope |
|---|---|
| `abn9.8.25` | PR-review retry budget: `LIFECYCLE_PR_REVIEW_EXHAUSTED`, 0-indexed `pr_review_retries_used` counter, default 5. **Blocks 8.23.** |
| `abn9.8.22` | Arm the fix agent + `verify_checklist` contract + repair-dispatch contract. |
| `abn9.8.23.1` | `GateStrength` enum + `Disposition.gate` validation/audit. |
| `abn9.8.23.2` | `verify` `VerbStep` (gate + tier + config + hard-stop + `VerifyVerdict` + status block). Needs 8.23.1, 8.25. |
| `abn9.8.23.3` | fix↔verify convergence loop + `LIFECYCLE_FIX_VERIFY_EXHAUSTED`. Needs 8.23.2, 8.22. |

## 12. Out of scope

- Implementation (the beads above).
- `prgroom --doctor` verify-command auto-detection (separate bead).
- Re-mechanizing the outer `pr_review_retries_used` counter's §3.4 push-attribution rules beyond the counter migration (owned by 8.25).
- Parallel verify across PRs; per-item push partitioning (no precedent; not built).
