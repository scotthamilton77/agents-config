# S9 Tier 1 — Executor Seam: Package, Pairing, Budget Enforcement, Parked-Work Surfacing

**Date:** 2026-07-25
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S9 slice — **Tier 1 only**; this is not the S9 spec, see §4)
**Tracker:** `agents-config-9k9.1.20`; covers `agents-config-9k9.1.4` (S9c), `agents-config-9k9.1.3` (S9b), `agents-config-9k9.1.6` (S9e)
**Companions**, both in the `scotthamilton77/agents-config-ARCHIVE` repository: `SAVEPOINTS/2026-07-24-tier1-executor-seam-design.md` (options considered and rejected; its §2.4 is void per its own header errata), `SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md` (V1 substrate inventory)

**Prior art**, also in that archive repository, at `packages/pdlc/` and `packages/holding-place/`: an earlier deterministic-FSM orchestrator, retired 2026-08-05. It is not a design to resume, but four problems this seam will meet were worked through there against an adversarial review round, and the reasoning is worth reading before solving them again: lease lifecycle, concurrency control by compare-and-set predicate, crash recovery by roll-forward, and pre-strike triage.

The executor decision layer — the code that consumes grind's facts and enacts
tracker verbs, attempt budgets, and the parked-work surfacing D10 requires —
lives in a new `packages/executor/`. Tier 1 ships the pairing layer, the
budget arithmetic and enforcement, and the open-new-work surfacing — and no
dispatch loop: with no driver calling these pieces, do not report Tier 1 as
"the executor loop works."

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

Beads git hooks and `.beads/issues.jsonl` are a separate plane from `work
sync`; no executor, workcli, or grind awareness of either is needed
(`agents-config-9k9.1.7` closed void).

## 2. Decisions

**S9T1-D1 — The seam: a new `packages/executor/`, console script `executor`.**
The executor reaches `grind` and `work` only through their CLI JSON envelopes,
behind two injected ports (`RuntimePort`, `TrackerPort`) with fakes in unit
tests. grind is unchanged by Tier 1 except Slice B's data-model additions;
workcli is unchanged except Slice P. `make ci-executor` mirrors the sibling
gates (lint, format-check, typecheck, coverage, audit, entry-verify) and joins
the top-level `ci` target; the installer registers the package in
`CLI_PACKAGES`. The CLI surface is part of the contract: `executor start`,
`park`, `redispatch`, `abandon`, `pr-opened`, `pr-closed`, `merged`, and
`done` enact the pairing table (S9T1-D12), and `attempt` (S9T1-D3) and `next`
(S9T1-D10) are the two decision surfaces. Named fallback: if grind's envelope
parse grows disproportionate (order of 150+ lines of typed mapping), the read
side may switch to a path dependency on `packages/grind`, recorded in the
package docs — `work` stays a subprocess either way.

**S9T1-D2 — The budget split: counts are facts, budgets are config,
enforcement is policy.** "N attempts recorded for item X" is folded state in
grind. The budget numbers (2 CI-fix, 1 rebase — D10's initial, tunable values)
are caller-supplied config the executor seeds into grind's `config`, exactly
as `stalemate_risk_round` works today. Exhaustion enforcement — refusing the
next attempt and parking with `budget-exhausted` — is executor-only. grind
never caps and never acts.

**S9T1-D3 — One enforcement point with pre-charge semantics:
`executor attempt <item> --kind ci-fix|rebase`.** The caller (a future
dispatcher, or a human today) declares an attempt before making it. Under
budget: the executor appends `fix_attempted` first, then reports proceed plus
the remaining count — a crash mid-attempt has already spent the budget; a
budget that counts only completed attempts is not a bound. At exhaustion: the
executor refuses without appending, parks the item with `budget-exhausted`,
and reports the refusal. Exhaustion has exactly one definition — grind's
`attempt_budget_spent` condition; the executor maintains no counter of its
own. Concurrency is scoped by the substrate: grind's documented model is a
single writer per run log, and the executor is that writer. Tier 1 builds no
cross-process lock; concurrent `attempt` invocations against one run are
outside the contract until the Tier-2 dispatcher owns the loop as that single
writer.

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
handle. Every pairing decision for a case-(c) item is "no tracker call" — the
executor never issues a `work` mutation against a run-local slug; the item is
surfaced instead (S9T1-D11). Promotion — minting tracker items — is out of
Tier 1: it takes placement, type, and priority judgment that arrives with the
dispatch brief (S7).

**S9T1-D6 — Ordering: intents go tracker-first; world-facts go grind-first.**
An intent the executor is about to enact (claim, park, redispatch, abandon)
calls the `work` verb first and appends the grind event only on success — a
tracker failure leaves grind un-advanced and the operation retryable, which is
safe because the S2 verbs are idempotent. A fact about the outside world that
already happened (`pr_opened`, `item_merged`) is appended to grind first, then
reported to the tracker — the fact stays recorded even when the tracker call
fails, and the failure surfaces for retry. The rule does not prevent
divergence — S9T1-A8 and S9T1-C2 deliberately permit transient one-sided
states — it bounds every divergence to a single failed call whose retry
converges, and it fixes which side leads. Enactment is also state-checked
idempotent: when grind already records the transition — a retry whose first
run appended but whose response was lost — the executor appends no duplicate
and reports success.

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
exactly one `work sync`, issued last; zero mutations → no sync. A sync that
fails after successful mutations is reported as a typed, retryable
degradation naming its repair — running `work sync` directly; an enacting
command is never re-run to repair sync, and a refusal envelope issues none.
Sync is the Dolt plane only (§1's hooks note).

**S9T1-D10 — The open-new-work surface is two-layered.** `executor next
[--stale-days N]` is the composed surface: it reads `work parked` first, then
`work ready`, and emits one envelope with the S9T1-D11 `{parked, ready}`
data; if the parked read fails, the ready list is suppressed — a degraded
report that still hands out new work inverts D10's "reviewing stuck work is
the price of pulling new work." Independently, `work ready` and `work claim`
success envelopes gain a read-only `parked_stale` block — the parked items
past the staleness threshold, plus any whose age cannot be read — always
present, empty when nothing qualifies, and the layer that makes D10's "any
open-new-work interaction" hold for callers that never touch the executor.
It joins two reads, counts nothing (S2-D2 intact), and fails closed: a
`ready` or `claim` that cannot compute it fails typed rather than emitting an
envelope without it. `ready` and `claim` take no new flags: the block rides
S2-D4's default threshold (7 days); tuning stays on `work parked
--stale-days`.

**S9T1-D11 — The executor envelope is protocol-versioned from birth.** Exactly
one JSON envelope on stdout per invocation, in workcli's
`{"protocol", "ok", "data", "error"}` style; the protocol value starts at
`"1"`, and a failure is never a traceback. `error` is
`{code, message, retryable, data?}` over a closed code set: transport
failures are retryable — `E_TRACKER_SUBPROCESS`, `E_RUNTIME_SUBPROCESS`,
`E_RUNTIME_ENVELOPE` (unparseable reply), `E_SYNC_FAILED` — and contract
refusals are not: `E_ITEM_PARKED`, `E_NO_OPEN_PR`, `E_BUDGET_EXHAUSTED`
(whose `data` is `{kind, attempts, budget}`). `attempt`'s success data
carries `{item, kind, attempts, budget, remaining, proceed}`; `next`'s data
carries `{parked, ready}` (the parked report's items with their stale flags,
and the ready list); a case-(c) item touched by any enactment is surfaced
under the command data's `unpromoted` list. (grind's own unversioned envelope
is the minted defect `agents-config-9k9.1.18`, §1.)

**S9T1-D12 — The pairing universe is closed.** The pairing table is exactly
these rows:

| Executor verb and arguments | Grind event | Tracker action |
| --- | --- | --- |
| `start <id>` | `item_started` | `work claim` |
| `park <id> --reason <code> [--note <text>; default: the reason code]`, failure axis | `item_parked` | `work park --reason` (same code) |
| `park <id> --reason <code> [--note <text>; default: the reason code]`, scheduling axis | `item_parked` | none |
| `redispatch <id>` | `item_enqueued`, no closure | `work redispatch` |
| `abandon <id> --pr <n> [--reason <text>]` | `item_enqueued` with closure (S9T1-B7) | `work abandon` |
| `pr-opened <id> --pr <n>` | `pr_opened` | none |
| `pr-closed <id> --pr <n> --next <status> --reason <text>` | `pr_closed` | none |
| `merged <id> --sha <sha>` | `item_merged` (`pr` from folded state; absent → `E_NO_OPEN_PR`) | `work close` |
| `done <id>` | `item_done` | none |
| `attempt <id> --kind <k>` under budget | `fix_attempted` | none |
| `attempt <id> --kind <k>` at exhaustion | `item_parked` (`budget-exhausted`) | `work park --reason budget-exhausted` |

Three scope notes. The table closes the executor's *mutation* surface — grind
events appended and tracker writes; port reads (folded state, conditions,
facade reads) appear in no row and are unrestricted, which is how `attempt`
reports counts (S9T1-C1) and honors the condition (S9T1-C3). Every tracker
action above is subject to S9T1-D5's handle routing: for a case-(c) item the
tracker column reads none and the item is surfaced instead. S9T1-D9's
invocation-level trailing `work sync` applies over any mutating row. The rest
of grind's event vocabulary — run lifecycle, lanes, attention, reviews,
blocking, discovery — is enacted by no Tier-1 executor command; totality
claims are decidable against this table and nothing else.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible; IDs are cited by the implementing tests and
PRs; the edge-case taxonomy (inverse, empty/boundary, dependency failure,
repeated invocation, idempotency) is applied per slice; each slice is
separately mergeable. Item mapping: Slice A discharges `agents-config-9k9.1.4`;
Slices B and C together discharge `agents-config-9k9.1.3` (the item stays open
until C lands — its admission requires enforcement, not just counting; Slice B
also carries S9T1-B7, the abandon-closure fold addition, same fold/payload
surface); Slices P and N together discharge `agents-config-9k9.1.6`. Ordering: A, B, and P are
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
  port yields a typed error envelope in the S9T1-D11 shape, never a traceback
  (dependency failure).
- **S9T1-A3** All `work`/`grind` subprocess I/O sits behind
  `TrackerPort`/`RuntimePort`; the unit suite passes with both ports faked and
  neither binary present. The grind client absorbs the documented staleness
  quirk: `grind check` exiting 1 with an `ok: true` envelope parses as a
  healthy staleness verdict, not a crash (boundary).
- **S9T1-A4** The pairing table is total over the closed universe: a
  parametrized test walks every S9T1-D12 row except the two `attempt` rows
  (whose pairing S9T1-C1/C2 pin in Slice C) and asserts exactly that row's
  tracker action or its explicit none; the CLI exposes exactly the S9T1-D12
  verbs plus `next` — an executor verb outside the enumeration, or a walked
  row without a test, fails the suite (absent-row boundary).
- **S9T1-A5** A failure-axis park crosses untranslated: `item_parked.reason`
  reaches `work park --reason` byte-identical for every failure code on a
  handle-bearing item (case-(c) items route per S9T1-D5), and the executor's
  suite asserts its vocabulary against
  `packages/contracts/park-reasons.toml`; a scheduling-axis park issues zero
  tracker calls (inverse pair).
- **S9T1-A6** Tracker-handle routing: with `work_id` set, the tracker sees
  `work_id`; with `work_id` `None` and an `id` outside the run-local slug
  grammar, the tracker sees `id`; with `work_id` `None` and an `id` matching
  `disc-<n>`, no `work` mutation is issued — across the whole suite the fake
  tracker's mutation log contains no run-local slug — and the envelope
  surfaces the item in the command data's `unpromoted` list (S9T1-D11) rather
  than erroring (the first-class case, not an error path).
- **S9T1-A7** Intent ordering: with the fake tracker raising on
  `claim`/`park`/`redispatch`/`abandon`, no grind event is appended and the
  command reports a typed error with `retryable: true`; re-running after the
  fake recovers succeeds with no duplicated tracker effect, riding the S2
  verbs' idempotency (dependency failure + repeated invocation); an intent
  whose grind event is already applied — a response-lost retry — appends no
  duplicate and reports success (S9T1-D6 idempotent enactment). Convergence
  means status, label, and grind agreement; a facade-internal partial park
  (marker lost under S2-B3's no-op) is the facade's concern, tracked
  separately, never an executor retry obligation.
- **S9T1-A8** World-fact ordering: with the fake tracker raising on `close`,
  the `item_merged` grind event is appended anyway and the failure surfaces
  for retry (inverse of S9T1-A7); the retry re-issues only the tracker close
  and sync — when grind already records the item `merged`, the enactment
  appends no second `item_merged`, and the same state-checked skip covers
  `pr-opened` and `pr-closed` re-runs (repeated invocation); `item_done`
  produces zero tracker calls.
- **S9T1-A9** Sync batching: N tracker mutations in one invocation produce
  exactly one `work sync`, issued after the last mutation; an invocation with
  zero mutations issues none (empty boundary).
- **S9T1-A10** A source-scan test pins that `bd` is never invoked from
  `packages/executor/src/**` — the executor addresses the tracker only
  through `work`.

### Slice B — attempt counting in grind's fold (S9b, grind half)

- **S9T1-B1** New event `fix_attempted` with payload `{item, kind, note?}`,
  `kind` one of `ci-fix`\|`rebase`: an unknown kind is a command error
  appending nothing (validator); on a parked, terminal, or absent item — or
  one holding no open PR (attempts exist only inside a PR cycle, mirroring
  the failure-park rule) — the event is an accept-and-flag anomaly leaving
  the ledger unchanged (inverse + dependency failure).
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
- **S9T1-B7** `item_enqueued` accepts an optional `closure` payload
  `{pr, reason}`: when present, the fold appends the closed-ledger entry,
  clears the item's PR reference, and the park exit proceeds unchanged — an
  abandoned PR's closure is recorded on the single exit without granting
  `pr_closed` a new source state; when absent, the PR reference survives the
  exit (redispatch resumes the same PR — inverse); a closure without an
  integer `pr` is a command error appending nothing (dependency failure).

### Slice C — budget enforcement in the executor (S9b, executor half)

- **S9T1-C1** `executor attempt <item> --kind …` under budget appends
  `fix_attempted` before returning and reports the S9T1-D11 attempt fields
  with `proceed: true`, the counts read from grind's folded state through
  `RuntimePort` (the S9T1-B6 surface) — the append happens even though no fix
  has run yet (pre-charge: a crash after the call has already spent the
  attempt).
- **S9T1-C2** At exhaustion the same command refuses: no `fix_attempted` is
  appended, `work park --reason budget-exhausted` is called first and
  `item_parked` with reason `budget-exhausted` appended second (S9T1-D6 intent
  ordering), and the refusal is `E_BUDGET_EXHAUSTED` with
  `data {kind, attempts, budget}` (S9T1-D11; boundary at count == budget). If the grind append fails after the tracker
  park succeeded, a retry converges: the exhaustion path re-runs, the facade
  re-park is an idempotent no-op (S2-B3), and the missing `item_parked` is
  appended (dependency failure).
- **S9T1-C3** Exhaustion has one definition: the executor honors the
  `attempt_budget_spent` condition as reported through `RuntimePort` and
  maintains no attempt counter of its own — with the fake runtime reporting
  the condition, the refusal fires in a fresh executor process that has
  observed no prior attempts (single source of truth; fresh-process case).
- **S9T1-C4** Refusal edges: `executor attempt` on an item grind records as
  parked, and
  on an item holding no open PR, are typed refusals with zero grind events and
  zero tracker calls — matching grind's failure-reason-requires-a-PR fold rule
  (inverse cases).
- **S9T1-C5** A second `executor attempt` after the exhaustion park is fully
  recorded is refused as parked, with zero further grind events and zero
  further tracker mutations — no double-park (repeated invocation). A sync
  that failed in the exhausting invocation is repaired by running `work sync`
  directly, which that invocation's degradation report names (S9T1-D9); the
  refusal itself still issues none.

### Slice P — the parked_stale block in the facade (S9e, workcli half)

- **S9T1-P1** `work ready` and `work claim` success envelopes carry a
  read-only `parked_stale` block listing the parked items older than the
  staleness threshold (S2-D4's default, 7 days) together with any parked item
  whose age is unknowable, each with id, title, reason, category, and
  parked-at; the block is always present — an empty list when nothing
  qualifies, because the absence of stale parked work is a reported fact, not
  a missing field (empty boundary).
- **S9T1-P2** The block is computed by reads only: `work ready`'s backend call
  log shows zero mutations, and `work claim`'s write set is unchanged from its
  pre-block behavior (S2-D2 intact — joins two reads, counts nothing).
- **S9T1-P3** An item parked more recently than the threshold appears in
  `work parked` but not in the block — the block is the threshold surfacing
  D10 names, not a second full report (inverse/boundary).
- **S9T1-P4** If the parked read fails, `ready` and `claim` fail with a typed
  error rather than emitting an envelope without the block — the surfacing
  cannot be bypassed by a degraded report; for `claim` the parked read
  precedes the backend claim mutation, so that failure leaves the backend
  mutation log empty — an error envelope never hides a taken item
  (dependency failure, fail-closed).
- **S9T1-P5** An item whose park marker is unparseable surfaces in the block
  with null reason and null parked-at rather than crashing the verb or being
  silently exempted: block membership is proven-stale or unknown-age —
  deliberately more conservative than `work parked`'s stale flag, which stays
  false when age is unprovable (S2-B7) — so a corrupted marker never exempts
  an item from surfacing (dependency failure, fail-closed).
- **S9T1-P6** Two consecutive `work ready` calls against an unchanged backend
  and a held clock return identical `parked_stale` blocks, with zero
  mutations both times (repeated invocation; idempotent read).

### Slice N — `executor next` (S9e, executor half)

- **S9T1-N1** `executor next` reads `work parked` first, then `work ready`
  (order pinned against the fake), and emits one envelope whose data carries
  the S9T1-D11 `{parked, ready}` shape — the full parked report with per-item
  stale flags, and the ready list.
- **S9T1-N2** A failed parked read suppresses the ready list entirely: the
  envelope reports the degradation as an S9T1-D11 typed error with the ready
  list absent, and hands out no new work (fail-closed; dependency failure).
- **S9T1-N3** The whole command is mutation-free: the fake tracker's mutation
  log is empty and no grind event is appended (read-only; and by S9T1-D9, no
  sync — zero mutations).
- **S9T1-N4** An empty parked report is still an empty `parked` list in the
  data, never an absent key (empty boundary), and `--stale-days` passes
  through to `work parked` verbatim — the executor does not reimplement the
  threshold, whose default stays the facade's (S2-D4).
- **S9T1-N5** Two consecutive `executor next` runs against an unchanged fake
  return identical envelopes and stay mutation-free (repeated invocation;
  idempotent read).

## 4. Out of scope — this is Tier 1, not the S9 spec

Tier 1 covers exactly `agents-config-9k9.1.4`, `agents-config-9k9.1.3`, and
`agents-config-9k9.1.6`. Everything else in S9 is out, in particular:

- **Tier 2 — the loop's decision inputs.** Dispatch of scaffold→green workers
  (needs S7's dispatch-brief format), review triggering and verdict
  consumption (needs S6's Mechanical/Advisory schema; carry V1's enum-collision
  finding when minting), and the merge-eligibility call site (needs S8's
  evaluator and verdict harvester). Those children are deliberately unminted —
  specifying them now would fix contracts that do not exist yet. Tier 2 gets
  its own child spec when S6/S7/S8 have landed.
- **Promotion of run-local discovered work.** Case (c) of S9T1-D5 surfaces
  such items; minting tracker items for them waits for the placement judgment
  a dispatch brief carries (S7).
- **Beads git hooks and `issues.jsonl`.** `agents-config-9k9.1.7` is closed
  void; no capability detection or hook awareness is built anywhere.
- **grind envelope protocol version** — `agents-config-9k9.1.18`.
- **A scheduling axis in the facade.** grind's scheduling parks never cross
  the boundary (S9T1-D7); whether `work park` should grow a scheduling
  vocabulary is a facade question outside S9.
- **Renderer surfacing of the attempt ledger** — display-only; admissible
  later if a human dashboard needs it.
