# S9 Tier 1 — Executor Seam: Package, Pairing, Budget Enforcement, Parked-Work Surfacing

**Date:** 2026-07-25
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S9 slice — **Tier 1 only**; this is not the S9 spec, see §4)
**Tracker:** `agents-config-9k9.1.20`; covers `agents-config-9k9.1.4` (S9c), `agents-config-9k9.1.3` (S9b), `agents-config-9k9.1.6` (S9e)
**Companions:** `SAVEPOINTS/2026-07-24-tier1-executor-seam-design.md` (options considered and rejected; its §2.4 is void per its own header errata), `SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md` (V1 substrate inventory)

The executor decision layer — the code that consumes grind's facts and enacts
tracker verbs, attempt budgets, and the parked-work surfacing D10 requires —
lives in a new `packages/executor/`. Tier 1 ships the executor's tracker
interface (the pairing layer), its budget arithmetic and enforcement, and the
open-new-work surfacing. It ships no dispatch loop: with no driver calling
these pieces, Tier 1 is the executor's tracker interface and budget policy,
not "the executor loop works."

---

## 1. Inventory — the substrate as merged (audited 2026-07-25 against `main`)

| Piece | State | Facts binding this spec |
| --- | --- | --- |
| `packages/executor/` | absent | Nothing on `main` implements a decision layer. Slice A creates the package. |
| grind decision seam | enforced | A condition is a fact with evidence, never orchestration policy: `conditions.py`'s `IMPERATIVE_VERBS` is a test-enforced forbidden-word list over condition names, and it is nearly the executor's verb set. The decision layer builds above grind, never inside it. |
| grind park vocabulary | reconciled (S9a, PR #386) | `item_parked.reason` carries two axes. Failure axis: `ci-failure`, `merge-conflict`, `approval-required`, `bot-declined`, `budget-exhausted`. Scheduling axis: `discovered-work`, `later-wave`, `deferred` — grind-native, no tracker counterpart. The fold refuses a failure-axis park on an item holding no PR. All reasons share one exit: an explicit `item_enqueued`. |
| shared reason contract | exists | `packages/contracts/park-reasons.toml` defines the failure-axis vocabulary with per-reason category (`machine`\|`human`); grind's and workcli's suites each assert their runtime table against it. |
| grind tracker handle | landed (`9k9.1.19`, `9k9.1.17`) | `Item.work_id` (renamed from `bead`) is populated by both producers, and both normalize `work_id == id` to `None` — so `work_id is not None` means the tracker handle differs from `id`. The grind spec permits ROOT-assigned run-local slugs (`disc-<n>`) as item ids for discovered work with no tracker item. |
| grind budgets | none | `DEFAULT_CONFIG` is `stale_item_after`, `stale_lane_after`, `stalemate_risk_round` — two timers and a repeat-detector. The precedent stands: a caller-supplied threshold a condition compares against, enforcement deferred to the caller. |
| grind CLI | 6 verbs, hardened | `create/log/status/check/render/finish` plus `--dir` resolution and `status --handoff`. Exactly one JSON envelope on stdout; **no protocol version** (`agents-config-9k9.1.18`, out of scope here). `grind check` exits 1 on a stale verdict while emitting `ok: true`. |
| grind terminality | as built | `done` is the only terminal status; `merged` legally advances to `done`; blocker edges resolve on `merged` or `done`. |
| workcli | D11 verb set complete (post-S2) | `create`, `ready`, `claim`, `park --reason` (failure axis only), `redispatch`, `abandon`, `close` (close-walk default, milestone-bounded), `dep`, `parked` (read-only report, `--stale-days` default 7), `sync` (Dolt plane). Protocol-versioned envelope. The facade records outcomes and never counts attempts (S2-D2). |
| installer | registers 3 CLIs | `CLI_PACKAGES` deploys `work`, `prgroom`, `grind` onto PATH with receipts and prune-on-retirement. |

Beads git hooks and `.beads/issues.jsonl` are a separate plane from
`work sync`; neither the executor nor workcli nor grind needs any awareness of
hook configuration or the JSONL plane (`agents-config-9k9.1.7` closed void).

## 2. Decisions

**S9T1-D1 — The seam: a new `packages/executor/`, console script `executor`.**
The executor reaches `grind` and `work` only through their CLI JSON envelopes,
behind two injected ports (`RuntimePort`, `TrackerPort`) with fakes in unit
tests. grind is unchanged by Tier 1 except Slice B's data-model additions;
workcli is unchanged except Slice P. `make ci-executor` mirrors the sibling
gates (lint, format-check, typecheck, coverage, audit, entry-verify) and joins
the top-level `ci` target; the installer registers the package in
`CLI_PACKAGES`. The CLI exposes the pairing enactments plus the two Tier-1
decision surfaces (`attempt`, `next`); enactment verb naming is the
implementer's. Named fallback, decided by measurement not preference: if the
typed parse of grind's envelope exceeds ~150 lines, take a path dependency on
`packages/grind` for the read side, keep `work` as a subprocess, and record
the switch in the package docs.

**S9T1-D2 — The budget split: counts are facts, budgets are config,
enforcement is policy.** "N attempts recorded for item X" is folded state in
grind. The budget numbers (2 CI-fix, 1 rebase — D10's initial, tunable values)
are caller-supplied config the executor seeds into grind's `config`, exactly
as `stalemate_risk_round` works today. Exhaustion enforcement — refusing the
next attempt and parking with `budget-exhausted` — is executor-only. grind
never caps and never acts: it records a third attempt beyond a budget of two
and reports the condition.

**S9T1-D3 — One enforcement point with pre-charge semantics:
`executor attempt <item> --kind ci-fix|rebase`.** The caller (a future
dispatcher, or a human today) declares an attempt before making it. Under
budget: the executor appends `fix_attempted` first, then reports proceed plus
the remaining count — a crash mid-attempt has already spent the budget; a
budget that counts only completed attempts is not a bound. At exhaustion: the
executor refuses without appending, parks the item with `budget-exhausted`,
and reports the refusal. Exhaustion has exactly one definition — grind's
`attempt_budget_spent` condition; the executor maintains no counter of its
own.

**S9T1-D4 — Attempt-ledger lifetime is one PR cycle.** `pr_closed` clears an
item's ledger (a new PR must not inherit spent budget); `item_enqueued` clears
it (leaving the parking lot deliberately grants a fresh window); nothing else
does.

**S9T1-D5 — Tracker-handle routing: `tracker_id(item) = work_id or id`, and
"no handle yet" is a first-class case.** The pairing layer distinguishes three
cases: (a) `work_id` set — the handle differs from `id` (guaranteed by both
producers' normalization); (b) `work_id` is `None` and `id` is outside the
run-local slug grammar — `id` is the handle; (c) `work_id` is `None` and `id`
matches the run-local slug grammar `disc-<n>` — the item has no tracker
handle. Every pairing decision for a case-(c) item is "no tracker call": the
executor never issues a `work` mutation against a run-local slug, and case-(c)
items surface in the command envelope as unpromoted discovered work. Promoting
them — minting tracker items — is out of Tier 1: minting requires placement,
type, and priority judgment the executor does not carry until a dispatch brief
exists (S7).

**S9T1-D6 — Ordering: intents go tracker-first; world-facts go grind-first.**
An intent the executor is about to enact (claim, park, redispatch, abandon)
calls the `work` verb first and appends the grind event only on success — a
tracker failure leaves grind un-advanced and the operation retryable, which is
safe because the S2 verbs are idempotent. A fact about the outside world that
already happened (`pr_opened`, `item_merged`) is appended to grind first, then
reported to the tracker — the fact stays recorded even when the tracker call
fails, and the failure surfaces for retry. This one rule is the mechanism that
keeps execution state and tracker state from drifting apart.

**S9T1-D7 — Failure-axis parks cross untranslated; the executor is the
contract's third reader.** The pairing layer contains no reason-mapping table.
A failure-axis `item_parked.reason` reaches `work park --reason`
byte-identical, and the executor's suite asserts its runtime vocabulary
against `packages/contracts/park-reasons.toml` exactly as grind's and
workcli's suites do. Scheduling-axis parks issue zero tracker writes: they are
sequencing decisions about work that never had a PR to fail, and the facade
deliberately carries no vocabulary for them.

**S9T1-D8 — `item_merged` triggers `work close`; `item_done` triggers
nothing.** D10 fixes closed = merged. grind's `merged → done` advance is
internal post-merge teardown with no tracker counterpart.

**S9T1-D9 — Sync batching per invocation.** Tier 1 has no loop, so the unit of
batching is one executor command invocation: one or more tracker mutations →
exactly one `work sync`, issued last; zero mutations → no sync. Sync is the
Dolt plane only (§1's hooks note).

**S9T1-D10 — The open-new-work surface is two-layered.** `executor next
[--stale-days N]` is the composed surface: it reads `work parked` first, then
`work ready`, and emits one envelope carrying the full parked report (per-item
stale flags) ahead of the ready list; if the parked read fails, the ready list
is suppressed — a degraded report that still hands out new work inverts D10's
"reviewing stuck work is the price of pulling new work." Independently,
`work ready` and `work claim` success envelopes gain a read-only
`parked_stale` block — the parked items past the staleness threshold — always
present, empty when nothing is stale. The block is what makes D10's "surfaced
at the start of any open-new-work interaction" hold for callers that never go
through the executor. It joins two reads and counts nothing (S2-D2 intact),
and it fails closed: a `ready` or `claim` that cannot compute the block errors
rather than emitting an envelope without it.
`ready` and `claim` take no new flags: the block rides S2-D4's default
threshold (7 days), and threshold tuning stays on `work parked --stale-days`.

**S9T1-D11 — The executor envelope is protocol-versioned from birth.** Exactly
one JSON envelope on stdout per invocation, in workcli's
`{"protocol", "ok", "data", "error"}` style, with typed errors and never a
traceback. grind's unversioned envelope is a minted defect
(`agents-config-9k9.1.18`); the new package does not repeat it.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible; IDs are cited by the implementing tests and
PRs. The edge-case taxonomy (inverse, empty/boundary, dependency failure,
repeated invocation, idempotency) is applied per slice. Each slice is
separately mergeable. Item mapping: Slice A discharges `agents-config-9k9.1.4`;
Slices B and C together discharge `agents-config-9k9.1.3` (the item stays open
until C lands — its admission requires enforcement, not just counting); Slices
P and N together discharge `agents-config-9k9.1.6`. Ordering: A, B, and P are
independent and parallelizable; C needs A and B; N needs A. C and N both touch
the executor's `cli.py` — land C before N.

### Slice A — the executor package and the pairing layer (S9c)

- **S9T1-A1** `packages/executor/` exists as its own uv project with console
  script `executor`; `make ci-executor` runs the same gate steps as
  `ci-grind`/`ci-workcli` and joins the top-level `ci` target; the installer's
  `CLI_PACKAGES` registers the package, so a deploy puts `executor` on PATH
  with a receipt and prunes it on retirement.
- **S9T1-A2** Every executor command emits exactly one protocol-versioned JSON
  envelope on stdout; a failed subprocess or an unparseable reply from either
  port yields a typed error envelope, never a traceback (dependency failure).
- **S9T1-A3** All `work`/`grind` subprocess I/O sits behind
  `TrackerPort`/`RuntimePort`; the unit suite passes with both ports faked and
  neither binary present. The grind client absorbs the documented staleness
  quirk: `grind check` exiting 1 with an `ok: true` envelope parses as a
  healthy staleness verdict, not a crash (boundary).
- **S9T1-A4** The pairing table is total under test: a parametrized test walks
  every execution transition the executor enacts or observes and finds exactly
  one tracker action or an explicit no-action row; a transition without a row
  fails the suite rather than silently doing nothing (absent-row boundary).
- **S9T1-A5** A failure-axis park crosses untranslated: `item_parked.reason`
  reaches `work park --reason` byte-identical for every failure code, and the
  executor's suite asserts its vocabulary against
  `packages/contracts/park-reasons.toml`; a scheduling-axis park issues zero
  tracker calls (inverse pair).
- **S9T1-A6** Tracker-handle routing: with `work_id` set, the tracker sees
  `work_id`; with `work_id` `None` and an `id` outside the run-local slug
  grammar, the tracker sees `id`; with `work_id` `None` and an `id` matching
  `disc-<n>`, no `work` mutation is issued — across the whole suite the fake
  tracker's mutation log contains no run-local slug — and the envelope
  surfaces the item as unpromoted discovered work rather than erroring (the
  first-class case, not an error path).
- **S9T1-A7** Intent ordering: with the fake tracker raising on
  `claim`/`park`/`redispatch`/`abandon`, no grind event is appended and the
  command reports a retryable typed error; re-running after the fake recovers
  succeeds with no duplicated tracker effect, riding the S2 verbs' idempotency
  (dependency failure + repeated invocation).
- **S9T1-A8** World-fact ordering: with the fake tracker raising on `close`,
  the `item_merged` grind event is appended anyway and the failure surfaces
  for retry (inverse of S9T1-A7); `item_done` produces zero tracker calls.
- **S9T1-A9** Sync batching: N tracker mutations in one invocation produce
  exactly one `work sync`, issued after the last mutation; an invocation with
  zero mutations issues none (empty boundary).
- **S9T1-A10** A source-scan test pins that `bd` is never invoked from
  `packages/executor/src/**` — the admission's remove-when observable.

### Slice B — attempt counting in grind's fold (S9b, grind half)

- **S9T1-B1** New event `fix_attempted` with payload `{item, kind, note?}`,
  `kind` one of `ci-fix`\|`rebase`: an unknown kind is a command error
  appending nothing (validator); on a parked, terminal, or absent item the
  event is an accept-and-flag anomaly leaving the ledger unchanged — grind's
  uniform anomaly discipline (inverse + dependency failure).
- **S9T1-B2** `Item.attempts` folds per-kind counts: two `ci-fix` events fold
  to a ci-fix count of 2; a third is still recorded and folds to 3 — grind
  counts, it never caps (inverse of enforcement).
- **S9T1-B3** Ledger lifetime: `pr_closed` resets the item's ledger;
  `item_enqueued` resets it; no other event does (representatives: `pr_opened`
  and `review_round` leave it unchanged) (boundary + inverse).
- **S9T1-B4** `DEFAULT_CONFIG` gains `ci_fix_budget: 2` and
  `rebase_budget: 1`; a caller-seeded override in `config` is honored by the
  condition (the `stalemate_risk_round` precedent).
- **S9T1-B5** New condition `attempt_budget_spent` fires per kind iff that
  kind's count ≥ its budget, carrying the item, the kind, and both numbers as
  evidence; it fires at count == budget and not at budget − 1 (boundary); it
  is absent for parked and terminal items (inverse); its name is added
  explicitly to the `IMPERATIVE_VERBS` lock test's covered-name set — the
  fixture does not cover new conditions for free.
- **S9T1-B6** `attempts` joins the serialized item in `status --full`, and the
  existing replay-determinism suite stays green over logs containing the new
  event (fold/replay idempotency).

### Slice C — budget enforcement in the executor (S9b, executor half)

- **S9T1-C1** `executor attempt <item> --kind …` under budget appends
  `fix_attempted` before returning and reports proceed with the remaining
  count — the append happens even though no fix has run yet (pre-charge: a
  crash after the call has already spent the attempt).
- **S9T1-C2** At exhaustion the same command refuses: no `fix_attempted` is
  appended, `work park --reason budget-exhausted` is called first and
  `item_parked` with reason `budget-exhausted` appended second (S9T1-D6 intent
  ordering), and the envelope names the kind, the count, and the budget
  (boundary at count == budget).
- **S9T1-C3** Exhaustion has one definition: the executor honors the
  `attempt_budget_spent` condition as reported through `RuntimePort` and
  maintains no attempt counter of its own — with the fake runtime reporting
  the condition, the refusal fires in a fresh executor process that has
  observed no prior attempts (single source of truth; fresh-process case).
- **S9T1-C4** Refusal edges: `executor attempt` on an already-parked item, and
  on an item holding no open PR, are typed refusals with zero grind events and
  zero tracker calls — matching grind's failure-reason-requires-a-PR fold rule
  (inverse cases).
- **S9T1-C5** A second `executor attempt` after the exhaustion park is refused
  as parked, with zero further grind events and zero further tracker
  mutations — no double-park (repeated invocation).

### Slice P — the parked_stale block in the facade (S9e, workcli half)

- **S9T1-P1** `work ready` and `work claim` success envelopes carry a
  read-only `parked_stale` block listing the parked items older than the
  staleness threshold (S2-D4's default, 7 days), each with id, title, reason,
  category, and parked-at; the block is always present — an empty list when
  nothing is stale, because the absence of stale parked work is a reported
  fact, not a missing field (empty boundary).
- **S9T1-P2** The block is computed by reads only: `work ready`'s backend call
  log shows zero mutations, and `work claim`'s write set is unchanged from its
  pre-block behavior (S2-D2 intact — joins two reads, counts nothing).
- **S9T1-P3** An item parked more recently than the threshold appears in
  `work parked` but not in the block — the block is the threshold surfacing
  D10 names, not a second full report (inverse/boundary).
- **S9T1-P4** If the parked read fails, `ready` and `claim` fail with a typed
  error rather than emitting an envelope without the block — the surfacing
  cannot be bypassed by a degraded report (dependency failure, fail-closed).
- **S9T1-P5** An item whose park marker is unparseable surfaces in the block
  with a null reason rather than crashing the verb — S2-B7's tolerance carries
  over (dependency failure).

### Slice N — `executor next` (S9e, executor half)

- **S9T1-N1** `executor next` reads `work parked` first, then `work ready`
  (order pinned against the fake), and emits one envelope carrying the full
  parked report with per-item stale flags ahead of the ready list.
- **S9T1-N2** A failed parked read suppresses the ready list entirely: the
  envelope reports the degradation and hands out no new work (fail-closed;
  dependency failure).
- **S9T1-N3** The whole command is mutation-free: the fake tracker's mutation
  log is empty and no grind event is appended (read-only; and by S9T1-D9, no
  sync — zero mutations).
- **S9T1-N4** An empty parked report is still present in the envelope (empty
  boundary), and `--stale-days` passes through to `work parked` verbatim — the
  executor does not reimplement the threshold, whose default stays the
  facade's (S2-D4).

## 4. Out of scope — this is Tier 1, not the S9 spec

Tier 1 covers exactly `agents-config-9k9.1.4`, `agents-config-9k9.1.3`, and
`agents-config-9k9.1.6`. Everything else in S9 is out, in particular:

- **Tier 2 — the loop's decision inputs.** Dispatch of scaffold→green workers
  (needs S7's dispatch-brief format), review triggering and verdict
  consumption (needs S6's Mechanical/Advisory schema; carry V1's enum-collision
  finding when minting), and the merge-eligibility call site (needs S8's
  evaluator and verdict harvester). Those children are deliberately unminted:
  specifying them now would fix contracts that do not exist yet, which is the
  failure V1 was run to avoid. Tier 2 gets its own child spec when S6/S7/S8
  have landed.
- **Promotion of run-local discovered work.** Case (c) of S9T1-D5 surfaces
  such items; minting tracker items for them waits for the placement judgment
  a dispatch brief carries (S7).
- **Beads git hooks and `issues.jsonl`.** `agents-config-9k9.1.7` is closed
  void; no capability detection or hook awareness is built anywhere.
- **grind envelope protocol version** — `agents-config-9k9.1.18`, its own
  item.
- **A scheduling axis in the facade.** grind's scheduling parks never cross
  the boundary (S9T1-D7); whether `work park` should grow a scheduling
  vocabulary is a facade question outside S9.
- **Renderer surfacing of the attempt ledger** — display-only, no test value
  in Tier 1; admissible later if a human dashboard needs it.
