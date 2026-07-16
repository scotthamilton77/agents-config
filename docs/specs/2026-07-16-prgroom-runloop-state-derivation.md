# prgroom Run-Loop State Derivation — Interactive Quiescence Reachability + Mixed-CI Signal Merge

**Date:** 2026-07-16
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.38 (interactive run cannot reach `quiesced` without the wait verb), agents-config-abn9.8.33 (`_ci_state` ignores classic commit-status on mixed-CI repos). One spec, two beads — both are gaps in how the run loop derives PR state from observation; each bead's AC section is separate (§6).
**Related:** `2026-07-16-prgroom-verb-atomicity.md` — no logical overlap (it never touches `_ci_state` or the interactive waiting-phase branch), but it diffs the same three files this spec's beads diff (`lifecycle/run.py`, `lifecycle/poll.py`, `test_lifecycle_poll.py`), so §5 sequences this work after it. `2026-07-16-prgroom-dispatcher-observability.md` — overlap is `lifecycle/run.py` only (its edits sit at `run.py:149-256`, far from the interactive branch); ordering relative to it is preference, not need. Bead agents-config-abn9.8.32 (closed) — its E2E campaign is where .38 was discovered; `docs/architecture/prgroom/cutover-runbook.md` and the monitor-pr skill carry the operational contract this spec corrects.

## 1. Problem

Two ways the run loop's derived state diverges from observable reality:

**Interactive runs strand a finished PR at `awaiting-review`.** Only two
paths ever evaluate `quiescence_predicate`: end-of-cycle resolution after a
`FIXES_PENDING` pipeline pass, and the blocking `wait_pr` loop (reached via
autonomous mode or the standalone `wait` verb). The interactive branch
(`run.py:373-384`) returns immediately at a waiting phase (`IDLE`,
`AWAITING_REVIEW`) — no quiescence check. A fully-groomed, long-quiet PR
therefore never flips to `quiesced` under repeated `prgroom run --interactive`
invocations; the operator must know to invoke `prgroom wait` separately. The
monitor-pr skill's documented contract (`run --interactive` + `status --json`)
omits that leg, so following it as written strands the PR at
`awaiting-review` while every merge gate reads not-quiesced. Discovered live
during the abn9.8.32 E2E campaign (PR #281).

**A red classic status is invisible on mixed-CI repos.** `_ci_state`
(`poll.py:378-386`) is a strict either/or: if any check runs exist on the head
SHA, their rollup is returned and the legacy combined-status endpoint is never
read. A repo where GitHub Actions check runs coexist with a classic
Status-API check (a third-party integration) reports `ci_state: success` from
the Actions rollup alone while the classic side is red — the quiescence CI
gate passes on a red PR. This is the mirror image of the pre-jkha6 defect
(combined-status blind to Actions); jkha6 (PR #252) fixed the Actions-only
case and explicitly left mixed-CI out of scope.

## 2. Decision — interactive quiescence (abn9.8.38)

**Fix the root gap in code, and align the two operating documents in the same
PR.** The bead offered docs-only as an alternative (require `prgroom wait`
after interactive runs); rejected — it leaves interactive mode a footgun for
any direct-CLI caller who skips the skill, and it adds a permanent manual leg
to the operating loop this project exists to shrink. The `wait` verb remains
the *blocking* way to reach quiescence; interactive mode gains the
*synchronous* check it always should have had.

Mechanics (all in `_run`'s interactive waiting-phase branch,
`run.py:373-384`):

- After the poll lands the state in a waiting phase, and before the
  interactive early-return, evaluate `quiescence_predicate`
  (`quiescence.py:99-103` — pure; state, now, and idle-threshold config are
  already in scope in `RunContext`).
- On trip: set `phase = QUIESCED` + `quiesced_at`, persist — mirroring
  `wait_pr`'s transition (`wait.py:135-139`) exactly, including its persist
  call shape — then `continue` to the loop-top so the existing
  terminal-for-CLI check flushes terminal signals and returns through the
  standard path. No new return site.
- On no-trip: the existing early-return behavior is byte-unchanged (including
  the `_IDLE_ADVISORY` stderr message on `IDLE`).
- Both waiting phases get the check, matching `_WAITING_PHASES` and
  `wait_pr`'s own semantics — the predicate internals (`_g_idle`'s
  `idle_threshold` gate, populated-state gates) already decide what "quiet
  enough" means; the branch does not second-guess them.

Consequences, stated for the operating docs:

- `run --interactive` on a quiet PR now reaches `quiesced` and exits through
  the terminal flush — the wait leg becomes optional, not required.
- Quiescence is *reachable*, not *instant*: a PR whose `last_activity_at` is
  younger than `idle_threshold` still returns `awaiting-review`/`idle`; the
  operator's re-invoke cadence is unchanged, only the terminal state is now
  reachable on the interactive path.
- The three quiescence-trip sites (end-of-cycle, `wait_pr`, this branch) stay
  separate — consolidation into a shared helper is deliberately out of scope
  (§4) while two in-flight specs hold reviewed line anchors into `run.py`.

Doc alignment (same PR as the code fix, since both describe its behavior):

- `src/user/.agents/skills/monitor-pr/SKILL.md` — the interactive-path
  contract ("interactive returns at `awaiting-review`/`idle` so you own the
  wait") gains the corrected outcome: a quiet PR returns `quiesced` directly;
  `prgroom wait` remains the blocking alternative.
- `docs/architecture/prgroom/cutover-runbook.md` — its mode descriptions
  (interactive "returns control between cycles" / autonomous "blocks in wait
  between cycles") gain the corrected interactive outcome: a quiet PR reaches
  `quiesced` directly on the interactive path. (The runbook documents no
  separate trailing `wait` step today — the addition is the reachability
  note, not a removal.) The dated E2E campaign spec
  (`2026-07-15-prgroom-e2e-write-path-proof.md`) is a point-in-time record of
  the pre-fix contract and is not edited.

## 3. Decision — mixed-CI signal merge (abn9.8.33)

**Merge the two rollups conditionally, with the `total_count == 0` guard**
(the bead's suggested fix, tightened). `_ci_state` becomes:

1. Read check runs (`_check_runs_state`, unchanged). If the rollup is `None`
   (no check runs / 404), fall back to combined-status alone — the existing
   jkha6 path, byte-unchanged.
2. If the rollup is `"failure"`, return it — already terminal; the classic
   read adds nothing.
3. Otherwise (`"success"` / `"pending"`), also read combined-status and merge.
   A combined-status response with `total_count == 0` — or a 404 (`"absent"`)
   — is **no classic signal**: the check-runs rollup stands. This guard is the
   critical non-regression: Actions-only repos report
   `state: "pending", total_count: 0` forever, and a naive merge would cap
   `ci_state` at `pending` on all-green check runs, re-breaking jkha6.

Merge lattice (applies only when both sources carry signal):

| check-runs \ classic | `success` | `pending` | `failure`/`error` |
|---|---|---|---|
| `success` | `success` | `pending` | `failure` |
| `pending` | `pending` | `pending` | `failure` |

- Failure in **either** source is failure — the gate must not pass a red PR.
- A registered classic context that has not reported yet (`pending`,
  `total_count > 0`) holds the merged state at `pending` — conservative by
  design: GitHub's own branch protection treats an unreported required
  context as not-passing, and quiescence gating on a half-reported SHA is the
  exact false-green this bead exists to kill.
- Cost: one extra REST read per poll, only on repos with check runs and only
  while the rollup is non-failure. The bead accepts this as marginal; no
  config flag (a knob to re-introduce a false-green is not a feature).
- `_combined_status_state` gains the `total_count` read (today it never reads
  that field); the module design comment (`poll.py:65-90`) is updated from
  "fallback-only" to describe the merge.

## 4. Out of scope

- Consolidating the three quiescence-trip sites into one helper (§2) —
  revisit when the run.py churn from the two P1 specs has settled.
- Any change to `wait_pr`'s blocking contract (4 wake events), the standalone
  `wait` verb's preconditions, `_entry_probe`, or `_WAITING_PHASES`
  membership.
- Per-context filtering or required-context awareness in the CI merge — the
  merge is rollup-level, matching the existing derivation's granularity.
- `rereview`-triggered CI re-evaluation timing; anything in `_ingest_items`
  (the verb-atomicity spec owns that neighborhood).

## 5. Sequencing

Both beads land **after `z4m2h`** (verb atomicity) — no logical dependency,
but it diffs the same `run.py` / `poll.py` / `test_lifecycle_poll.py`
surfaces and carries reviewed line anchors that churn here would invalidate.
Ordering relative to `abn9.8.26` (dispatcher observability) is a soft
preference only — its edits share nothing but distant `run.py` lines. The two
beads here are independent of each other and of the fix↔verify tail; **one PR
per bead** (small-PR discipline — `test_lifecycle_poll.py` is the shared
surface that makes a combined PR balloon).

## 6. Test plan and acceptance criteria

### 6.1 agents-config-abn9.8.38 — `tests/unit/test_lifecycle_run.py` (+ docs)

New behaviors, one red-green cycle at a time:

1. `test_interactive_run_reaches_quiesced_when_predicate_trips` — state at
   `AWAITING_REVIEW`, activity older than `idle_threshold`, no actionable
   items; `_run` returns `phase=QUIESCED` with `quiesced_at` set and the
   state persisted (store fake). Exit-code and terminal-flush behavior are
   not asserted here — `_run` returns state, not an int, and the flush hooks
   no-op without a blocker or error; the existing terminal-path tests at the
   `run_lifecycle` level already pin that routing. Add one CLI-level
   companion in `test_cli_run.py`: interactive run on a quiet PR → exit 0
   with the quiesced status line.
2. `test_interactive_run_returns_waiting_when_predicate_holds` — activity
   younger than `idle_threshold` → returns `AWAITING_REVIEW` unchanged, no
   persist of a phase change (pins the no-trip path byte-unchanged).
3. `test_interactive_idle_still_emits_advisory` — `IDLE` + predicate-false →
   advisory on stderr, phase unchanged (existing behavior pin).
4. `test_interactive_idle_quiesces_when_predicate_trips` — `IDLE` + predicate
   true → `QUIESCED` (parity with `wait_pr` from the same phase).
5. Autonomous-mode and standalone-`wait` test suites stay green unmodified —
   the blocking contract is untouched.

**Existing-test migration (same PR).** Two pre-existing interactive-branch
pins (`test_lifecycle_run.py:515-526` and `:581-587`) assert
`AWAITING_REVIEW`/`IDLE` on the default `_quiescent_state()` fixture — whose
hour-stale activity **already satisfies the predicate** against the 10-minute
default `idle_threshold`. Once the fix lands, both flip to `QUIESCED` by
design. They are superseded, not broken: migrate each to a
recent-activity fixture so it pins the no-trip path (behaviors 2-3 above are
their successors); do not delete the waiting-phase coverage.

Doc AC: monitor-pr `SKILL.md` interactive contract and
`cutover-runbook.md` operating loop updated per §2 in the same PR.

### 6.2 agents-config-abn9.8.33 — `tests/unit/test_lifecycle_poll.py`

1. `test_mixed_ci_both_green_is_success` — check runs all success +
   combined-status success (`total_count > 0`) → `success`.
2. `test_mixed_ci_classic_red_is_failure` — check runs success +
   combined-status `failure` → `failure`. **The bead's headline regression
   test.**
3. `test_mixed_ci_classic_error_is_failure` — combined-status `error` maps
   into the merge as failure (pins the existing `error → failure` mapping
   through the new path).
4. `test_mixed_ci_classic_pending_holds_pending` — check runs success +
   combined-status pending (`total_count > 0`) → `pending`.
5. `test_actions_only_total_count_zero_ignored` — check runs success +
   combined-status `pending`/`total_count == 0` → `success`. **The jkha6
   non-regression pin.**
6. `test_checkruns_failure_skips_classic_read` — check-runs failure → exactly
   one CI-related GET (no combined-status read), result `failure` (cost +
   short-circuit pin).
7. `test_classic_404_with_checkruns_present_keeps_rollup` — combined-status
   404 → rollup stands (absent = no signal).

**Existing-test migration (same PR).** The merge adds a second CI read
whenever the check-runs rollup is `success`/`pending`, and the recorded-fake
idiom **raises on response exhaustion** (`tests/fakes.py:45-47`) — so the
existing suite does not stay green by itself:

- The shared `_gh()` fixture helper (~35 call sites defaulting
  `ci="success"`) queues a combined-status response with
  `total_count == 0` after its check-runs response. Semantics-preserving —
  the rollup stands — and it turns every legacy path into a standing
  regression pin on the jkha6 guard.
- The three direct check-runs tests in the `test_lifecycle_poll.py:991-1108`
  range that queue a single explicit CI response each gain the same explicit
  second response (only where the rollup is non-failure; the
  failure-rollup test doubles as the short-circuit pin, behavior 6).
- The fallback-path tests (empty check-runs / 404 → combined-status alone)
  are byte-unchanged — that path still issues exactly one read.

**AC (both beads):** the named behaviors covered red-green;
`make ci-prgroom` green from the worktree root; no change to `wait_pr`, the
`wait` verb, `_execute_step`, or any verb signature; `.33` adds no state or
schema fields (the merge is derivation-only, `ci_state`'s value vocabulary —
`success`/`pending`/`failure`/`absent` — is unchanged).

## 7. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` the REST combined-status payload carries `total_count`
  (GitHub documents it; `_combined_status_state` just never read it).
  Verified at implementation before the merge branch is written.
- `ASSUMPTION:` flipping to `quiesced` from `IDLE` when the predicate trips
  is correct (parity with `wait_pr`, which already does exactly this from
  `_WAITING_PHASES`) — the predicate's populated-state gates own the "was
  anything ever groomed" question, not the caller.
- `ASSUMPTION:` the E2E campaign's "quiesced only via wait" observation was an
  artifact of the pre-fix code, not a contract anyone depends on — the
  runbook is updated; the dated campaign spec stays as the historical record.
- `ASSUMPTION:` one extra REST read per poll on mixed-CI/Actions repos is
  acceptable (the bead's own cost note; no flag added).

## Continuations

- none — this spec is the deliverable; beads agents-config-abn9.8.38 and
  agents-config-abn9.8.33 are the pre-existing implementation units (one PR
  each, sequenced per §5).
