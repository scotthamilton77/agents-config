# prgroom Fix↔Verify Subsystem — Implementation-Readiness Reconciliation

**Date:** 2026-07-16
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.23 (parent container; children agents-config-abn9.8.23.2, agents-config-abn9.8.23.3), agents-config-abn9.8.22 (armed fix agent + contracts). agents-config-abn9.8.24 (`--doctor`) is touched only by the sequencing ruling (§7).
**Related:** `2026-06-20-prgroom-fix-verify-subsystem.md` — the approved design this spec reconciles; every decision there **stands** (this spec re-verifies, amends at the margins, and re-arms the bead graph — it does not redesign). `2026-07-16-prgroom-verb-atomicity.md` — its §3 effect-idempotency invariant post-dates the design; §4 here supplies the verify row and the crash-rerun ruling. `2026-07-16-prgroom-dispatcher-observability.md` — its §3 `Dispatched[T]` envelope changes the dispatcher surface the repair dispatch will consume (§7 quotes the shape so implementers need not chase it). HLD: `docs/architecture/prgroom/c4-l3-verify.md`, `c4-l3-agent-dispatch.md`, `data-view.md` (the `verify_checklist` shape amendment in §3 lands with this spec's PR).

## 1. Problem

The fix↔verify subsystem was designed and approved on 2026-06-20 (source bead
`agents-config-fca6.16`), decomposed into implementation beads, and then
deliberately parked by triage-2026-07-04 as the `prgroom-tail`. Since then:

- Two of its five decomposition beads **landed** (`abn9.8.23.1` GateStrength,
  `abn9.8.25` outer retry cap) — the design's foundations are in the package.
- The remaining three (`abn9.8.23.2` verify step, `abn9.8.23.3` convergence
  loop, `abn9.8.22` armed agent) sit deferred with acceptance criteria written
  before the design existed — the parent bead's own AC contradicts the design
  it was decomposed under (§6).
- Two same-cycle specs (verb atomicity, dispatcher observability) introduce
  contracts on the exact surfaces the verify step and repair dispatch will
  occupy — the 06-20 design predates both.
- The `verify_checklist` contract was refined in bead notes (2026-06-21) to a
  structured findings schema that never made it into the design artifacts,
  and an adversarial implementability pass on this spec surfaced edge rulings
  the 06-20 design leaves to a guess (§5).

This spec closes those gaps so the three remaining beads are implementable by
a non-frontier model without re-deriving any judgment.

## 2. Currency audit — the 06-20 design against today's code

Every load-bearing claim of the 06-20 spec, re-verified against the package
(line references are current):

| Design element | 06-20 § | Current code fact | Verdict |
|---|---|---|---|
| The gap: nothing consumes `recommended_gate` | §1 | `Disposition.gate` round-trips through state JSON; zero runtime consumers (only tests read it) | **Still true** |
| Pipeline insertion point: between `fix` and cap-guard | §3.1 | `_build_pipeline` (`run.py:403-413`): `cluster → fix → cap-guard → push → reply → resolve → rereview` — no verify step | **Still valid** |
| Refusal mechanism: `phase=HUMAN_GATED`, post-step terminal check breaks pipeline | §3.2 | The `is_terminal_for_cli` check inside the pipeline loop sits at `run.py:392`; cap-guard closure factory at `run.py:416-434` | **Still valid** (line drift only) |
| `GateStrength` + validated `Disposition.gate` | §6.1 | **Built**: `prsession/enums.py:45-68`, audit at `agent/fix_audit.py:116-120`, stored at `agent/fix.py:347` | Landed (8.23.1) |
| Outer retry cap (`pr_review_retries`, `LIFECYCLE_PR_REVIEW_EXHAUSTED`) | §4 | **Built**: `config.py`, `errors.py`, cap-guard in `run.py`; delivered via PR #246 | Landed (8.25) |
| `status --json` gains additive `verify` block | §6.3 | `build_status` (`lifecycle/status.py:62-92`) has since gained `merge_gates` / `auto_merge_eligible`; contract is documented additive-only | **Still valid** (additive) |
| `[verify]` config + "this work wires `repo_config`" | §8 | Every `cli.py` `PrgroomConfig.load()` call site omits `repo_config` (falling to its `None` default), so `.prgroom.toml` is never read from disk | **Still true — and still 8.23.2's job** (§6.3) |

**Verdict: the design is current.** No decision is stale; no element conflicts
with the code. The amendments below are additions the design predates, not
corrections.

## 3. Amendment — the structured `verify_checklist` contract

The 06-20 spec §5 defines `verify_checklist` as "what it ran and the result."
Bead `abn9.8.22`'s design notes (2026-06-21) refined it into a structured
findings schema; this spec formalizes that as the contract `abn9.8.22`
implements, using the severity rubric shared with quality-reviewer, crit, and
simplify:

```json
"verify_checklist": {
  "iterations": [
    {
      "reviews_run": ["quality-review", "simplify", "make ci-prgroom"],
      "findings": [
        { "severity": "MAJOR", "title": "unguarded array access in dispatch loop", "resolution": "addressed" },
        { "severity": "MINOR", "title": "stale import left after refactor", "resolution": "unresolved" }
      ]
    }
  ]
}
```

- **Attachment: one checklist per dispatch, batch-level.** `verify_checklist`
  is a new top-level `FixOutput` field — not per-item. It is required
  whenever the dispatch claims commits: in fix mode, on a batch with `FIXED`
  items (06-20 §5 unchanged); in repair mode, on a non-empty
  `repair.commits` (§5.1).
- **Grouping is by inner iteration** — the fix agent's own fix → review → fix
  cycles within one dispatch (distinct from prgroom's outer PR-review loop).
  One iteration entry per cycle, in order; `reviews_run` records what the
  agent actually executed that cycle (it may be empty — the audit does not
  police diligence, only schema honesty).
- **Parse leniently, validate in the audit.** `contracts.py`'s `from_dict`
  stores the checklist without raising — the `MemoryEntry` precedent
  (`contracts.py:137-145`): a `from_dict` raise would discard valid item
  dispositions wholesale. Schema validation lives in `fix_audit`, exactly
  like `recommended_gate` (lenient `GateStrength.parse` at the boundary,
  enforcement in the audit).
- **Audit rule** (extends the existing `CONTRACT_FIX_AUDIT_FAILED` audit): on
  a batch that claims commits, `verify_checklist` must be present and
  schema-valid — a parseable object with ≥1 iteration, every finding carrying
  a valid severity (one of `BLOCKING`, `CRITICAL`, `MAJOR`, `MINOR`) and a
  valid resolution (one of `addressed`, `unresolved`). Malformed ⇒ the same contract-audit
  failure path as a missing checklist. An `unresolved` BLOCKING or CRITICAL
  finding is **not** an audit failure — the checklist is the agent's honest
  claim, and the mechanical gate remains the sole authority on whether the
  branch ships; compelling honesty matters more than compelling green.
- **Enums**: `ChecklistSeverity` and `ChecklistResolution` join
  `prsession/enums.py` beside `GateStrength`, with the same lenient,
  case-insensitive `.parse()` idiom.
- **Purpose split is unchanged**: forcing function + evidence (audit trail,
  and input to the feedback-signal miner, bead `agents-config-4vn5.1`, which
  absorbed the earlier learning-loop bead); never byte-compared against the
  mechanical gate.
- **HLD**: `data-view.md`'s "Fix output — `verify_checklist` artifact" section
  gains this fenced shape (amendment ships with this spec's PR;
  `c4-l3-agent-dispatch.md`'s prose already matches and needs no edit).

## 4. Amendment — effect-idempotency conformance (verb-atomicity reconciliation)

The verb-atomicity spec's §3 invariant ("every remote mutation a verb issues
must be safe to re-issue on a rerun from the pre-call state") post-dates the
06-20 design. Conformance ruling for the verify step:

- **`verify` issues zero remote mutations.** The mechanical gate is a local
  `proc.CommandRunner` run; the repair dispatch is a local agent invocation
  producing local commits. Its row in the `run.py` docstring audit table
  (added by `abn9.8.23.2`, after z4m2h lands the table):

  | Verb | Remote mutations per invocation | Rerun-safety mechanism |
  |---|---|---|
  | `verify` | none remote (local gate run; local repair commits) | n/a — see crash-rerun ruling below |

- **Crash-rerun ruling (local-effects analog).** A crash inside the
  convergence loop discards the deepcopy (verdict, repair bookkeeping) but the
  repair's **local git commits survive** on the branch. On rerun, the verify
  step starts fresh: it re-runs the gate on the branch as-is — surviving
  repair commits included — and a green gate falls through to push. Prior
  repair commits whose batch attribution died with the discarded state are
  treated as **external-equivalent branch content**: the repair audit is a
  dispatch-time contract check on the agent's claims (§5.2), not a branch
  inventory, and the gate of record re-validates the whole branch regardless
  of who authored what. No re-attribution pass is built. This mirrors the
  atomicity spec's reasoning for `push` (truth lives where the effect lives —
  here, the branch itself).
- **Retry-budget accounting across a crash** follows from the same discard:
  `retries_used` lives on the deepcopy, so a crash mid-loop resets the
  observed count to the last persisted verdict's value. The budget bounds
  spend per *persisted* cycle, not across crashes — accepted as a judgment
  call: verify's effects are local (the atomicity spec's option-(b)
  *insufficiency* ground concerns duplicate remote mutations and does not
  transfer), but persisting mid-loop would require the same mid-verb
  `Store` injection option (b) was rejected for, and a crash-repeated local
  gate run or repair costs money, not correctness.

## 5. Amendment — repair-mode output contract and verify-step edge rulings

The 06-20 spec ratifies *that* repair commits are audited outside the
per-cluster rule (§5.2 there) but leaves the contract shape to a guess. Ruled
here:

### 5.1 Repair `FixOutput` shape

Repair mode emits the same top-level `FixOutput` schema with:

- `items: []` — **required empty**. Repair never touches review-item
  dispositions; a repair output with items is a contract-audit failure.
- A required `repair` result block:

  ```json
  "repair": {
    "commits": ["<full sha>", "..."]
  }
  ```

  `commits` claims every commit the repair created (may be empty when the
  agent concluded no change was needed — the re-gate then decides).
  `verify_checklist` stays a top-level `FixOutput` field in repair mode too
  (§3 — one checklist per dispatch, never nested under `repair`); §3's schema
  and audit rule apply, triggered by non-empty `commits`.

### 5.2 Repair audit — dispatch-scoped baseline

- **Baseline**: the convergence loop captures branch `HEAD` immediately
  before each repair dispatch. "The repair's new commits" =
  `rev-list <baseline>..<post-dispatch HEAD>` — the per-cluster
  `ancestors_of_pre`/`new_in_cluster` machinery (`fix_audit.py`) reused with
  the repair baseline as `<pre>`.
- **Orphan rule, repair-scoped**: every commit in that range must be claimed
  in `repair.commits`; every claimed sha must be reachable. Prior-iteration
  repair commits sit behind the baseline and are never re-audited (this is
  the §4 crash-rerun ruling's audit-side twin).
- **Audit failure consumes the retry.** A repair whose output fails the
  contract audit (items non-empty, orphan/unreachable commits, missing or
  malformed checklist) is a failed repair attempt: log it, increment
  `retries_used`, and **re-gate the branch as-is** — the gate of record, not
  the contract audit, decides convergence. The commits are on the branch
  either way; refusing to re-gate would punish the operator for the agent's
  paperwork.

### 5.3 Gate-tier edge: no clean `FIXED` items

`has_queued_fix_commits` gates on commits, not dispositions — a batch can
carry queued commits with zero clean `FIXED` items (every item flipped to
`FAILED`, or the commits predate this cycle). Ruling: with an empty
clean-`FIXED` set, `select_gate_tier` returns **`FULL`** — no agent
recommendation is in scope, so the gate runs at maximum strength
(risk-asymmetric default, same instinct as the unconfigured-command hard
stop). The tier is selected **once per verify invocation**; every re-gate in
the convergence loop runs at that same tier.

### 5.4 `VerifyVerdict` field semantics

- `gate_output_ref` always references the **last gate run's** captured
  output — green or red; verify runs the gate at least once, so the field is
  never absent (06-20 §6.2's non-optional `str` stands).
- `decided_at` comes from an injected clock (a `now` parameter, the
  `run_cluster` idiom) — never read inline — per the contracts-and-boundaries
  rule; this keeps the verdict writer deterministic under test.

## 6. Bead-graph reconciliation

### 6.1 The parent bead's AC contradiction

`abn9.8.23`'s acceptance criteria include "the fix agent's allow-list is
unchanged (still tight)" — written **before** the fca6.16 design ratified the
armed agent (06-20 §5.1). Resolution: that AC line binds **`abn9.8.23.2`
only** — the mechanical gate needs no agent arming, and 8.23.2 must not
smuggle the arming in. The arming itself is `abn9.8.22`'s ratified scope; the
apparent contradiction is a scoping artifact, not a design conflict.

### 6.2 The parent bead's disposition

`abn9.8.23` is a container: its entire remaining scope lives in `8.23.2` and
`8.23.3`. It stays open as the tracking parent and **closes when both children
land** (`8.22` is tracked independently — it is `8.23.3`'s dependency, not
`8.23`'s child).

### 6.3 Config wiring ownership

`abn9.8.23.2` wires minimal repo-root `.prgroom.toml` resolution exactly per
06-20 §8 (the `[verify]` table is dead code without it). Two parked beads
revive **against** that landing rather than blocking it:
`abn9.8.39` (the `[agents.*]` table is inert for the same
unresolved-`repo_config` reason) and `2w7vz` (path resolution across all
verbs). 8.23.2 builds the resolution; those beads spread it.

## 7. Sequencing

```
z4m2h (verb atomicity, P1)  ──┐
abn9.8.26 (dispatcher obs, P1)┴──►  abn9.8.22 ∥ abn9.8.23.2  ──►  abn9.8.23.3
                                    (independent of each other)
abn9.8.24 (--doctor): stays deferred until 8.23.2 defines the config it diagnoses.
```

- **The two P1 specs land first.** Both touch `run.py` /
  `agent/dispatcher.py`; landing the verify work after them avoids
  invalidating their reviewed line anchors, and the repair dispatch must be
  written against the observability spec's §3 surface — quoted here so the
  implementer need not chase it: `dispatch()` returns a frozen
  `Dispatched[T]` envelope, `{output: T, winner: AgentSpec,
  failures: tuple[LinkFailure, ...]}` with derived `rung`, `fell_back`, and
  `decided_by` properties. The repair dispatch unwraps `.output` and records
  `.decided_by`, like every other consumer.
- **`abn9.8.22` and `abn9.8.23.2` are independent** (contract/arming vs
  lifecycle step) and may proceed in parallel worktrees.
- **`abn9.8.23.3` needs both** — the loop consumes 8.23.2's gate and 8.22's
  repair contract.

## 8. Out of scope

- Any change to a 06-20 decision — mechanical gate, whole-branch max-strength
  tier, insertion point, two sibling caps, batch-level verdict, hard-stop
  config: all stand as written.
- Implementation (the beads own it); `--doctor` (8.24, deferred).
- The feedback-mining loop over collected checklists
  (`agents-config-4vn5.1`).
- Re-baselining the 06-20 spec's line-number citations (drift is expected;
  implementers anchor on the current-line table in §2).

## 9. Test-plan delta and acceptance criteria

The 06-20 spec's §10-§11 and `c4-l3-verify.md`'s testability notes remain the
implementation test contract for 8.23.2/8.23.3 unchanged. This spec adds the
behaviors its rulings introduce:

Owned by **`abn9.8.22`**:

1. `test_fix_output_parses_structured_verify_checklist` — a valid checklist
   (2 iterations, mixed severities/resolutions) round-trips through
   `contracts.py`'s lenient parse.
2. `test_from_dict_never_raises_on_malformed_checklist` — garbage checklist
   content is stored raw; item dispositions survive (the `MemoryEntry`
   precedent, §3).
3. `test_fixed_batch_missing_checklist_fails_contract_audit` — existing 06-20
   rule, pinned against the new schema path.
4. `test_fixed_batch_malformed_checklist_fails_contract_audit` — invalid
   severity value / empty iterations ⇒ `CONTRACT_FIX_AUDIT_FAILED` (the
   audit, not the parse, rejects).
5. `test_unresolved_blocking_finding_does_not_fail_audit` — honesty is not
   punished; the mechanical gate is the authority (§3).
6. `test_repair_output_with_items_fails_contract_audit` — §5.1's
   required-empty rule.

Owned by **`abn9.8.23.2`**:

7. `test_tier_is_full_when_no_clean_fixed_items` — queued commits, zero clean
   `FIXED` items ⇒ gate runs `FULL` (§5.3).

Owned by **`abn9.8.23.3`**:

8. `test_repair_orphan_audit_scopes_to_dispatch_baseline` — two-iteration
   convergence: iteration 2's audit sees only commits after iteration 2's
   baseline; iteration 1's commits are not re-flagged (§5.2).
9. `test_audit_failing_repair_consumes_retry_and_regates` — a contract-invalid
   repair increments `retries_used` and the gate re-runs (§5.2).

**AC (this spec's PR):** this document merged; `data-view.md` carries the §3
fenced shape; the five beads' notes updated with the §3-§7 rulings
(`bd update --append-notes`); `abn9.8.22` + `abn9.8.23.2` un-deferred and
labeled implementation-ready; `abn9.8.23.3` un-deferred with its 8.22+8.23.2
dependency edges verified; `abn9.8.24` left deferred.

## 10. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` the 2026-06-21 bead-note schema (severities, per-iteration
  grouping, addressed/unresolved) is the intended final checklist contract —
  §3 formalizes it verbatim with two additions (the explicit
  malformed-vs-unresolved audit split; the lenient-parse placement).
- `ASSUMPTION:` `FULL` as the empty-tier default (§5.3) is the intended
  risk posture — the alternative (skip the gate when nothing is `FIXED`)
  silently pushes unverified commits, which is the defect class this
  subsystem exists to kill.
- `ASSUMPTION:` treating crash-orphaned repair commits as external-equivalent
  branch content (§4) is acceptable — the alternative (persisting repair-batch
  attribution mid-loop) needs the mid-verb `Store` injection the atomicity
  spec rejected with its option (b).
- `ASSUMPTION:` landing order P1 specs → verify tail (§7) is a rebase-hygiene
  preference, not a hard dependency — if priorities shift, only the
  `Dispatched[T]` consumption note in §7 is load-bearing.

## Continuations

- no new beads — the implementation units pre-exist. At this spec's merge:
  un-defer `agents-config-abn9.8.22` and `agents-config-abn9.8.23.2` (both
  implementation-ready per §7), un-defer `agents-config-abn9.8.23.3` (blocked
  by those two), keep `agents-config-abn9.8.24` deferred, and append the
  §3-§7 rulings to each bead's notes so the spec and tracker agree.
