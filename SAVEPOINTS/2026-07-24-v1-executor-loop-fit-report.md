# V1 — Executor-loop fit verification (D14)

**Bead:** `agents-config-9k9.1.1` (child of `agents-config-9k9.1`, S9 epic)
**Date:** 2026-07-24
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md` — open verification V1
**Method:** read-only. Two specs, one package (3,286 lines src + 268 tests), the
charter, the `work` CLI surface, and the frozen tracker export.

---

## Verdict — FIT, with a scope correction

D14's claim is **confirmed at the substrate layer and overstated at the loop
layer.**

The event-sourced grind runtime is a **generic, complete, CI-gated
event-sourcing engine for work-across-workers**. Its coupling to the
`orchestrated-grind` skill lives in spec prose and in unbuilt integration work,
**not in the code**. It is sound to keep, import, and build on. S9 is a re-aim,
not a rewrite, and not a re-scope.

But "becomes the executor loop" understates the remaining work. What exists is
the **state machine**: what happened, what is derivable from it, what is stale.
What does not exist is the **decision layer**: what to dispatch, when to stop
trying, when a review is done, whether a PR may merge, and how any of it reaches
the tracker. S9 builds that layer on a substrate that is genuinely ready to carry
it.

**S9 is scoped as a re-aim. It should not be scoped as a small one.**

---

## AC-V1.1 — Subsystem fit classification

| Subsystem | Verdict | Note |
|---|---|---|
| Event envelope | **KEEP** | Typed fields throughout; nothing the consumer must parse is free text |
| Event taxonomy (21 types) | **KEEP, extend** | Core lifecycle is generic PR-workflow vocabulary; `review_round.kind` and `lane_handover` carry local vocabulary that widens rather than blocks |
| Fold + transition table | **KEEP** | The load-bearing asset. Derived-never-asserted status, fixpoint cascade-unblock, accept-and-flag anomalies |
| Conditions + emit-back | **KEEP, re-aim consumer** | Condition set is generic facts-with-evidence; only the *documented consumer* is skill-flavoured |
| CLI contract (6 verbs) | **KEEP** | `create/log/status/check/render/finish` name no agent role |
| Staleness watchdog | **KEEP, re-aim arming** | `grind check` is a generic probe; the spec's arming procedure is skill-specific and is discarded |
| Compaction handoff | **RE-AIM** | Projection mechanism is generic; its stated purpose (replace `ORCHESTRATION-STATE.md` §7) dies with the skill integration |
| Dashboard renderer | **KEEP** | Pure function of folded state, byte-deterministic. Human-facing, which is fine — it reports, it does not act |
| Seed / create flow | **RE-AIM** | `lanes[].agent/model/effort` is the only schema shaped by the old topology, and the fold treats those as opaque strings |
| Single-writer model | **RE-AIM** | Documented as "ROOT is the only writer." No locking exists. A pipeline executor is also a single writer, so the constraint survives; the justification is rewritten |
| Integration into orchestrated-grind | **DROP** | Entirely `.30.7` scope. Never built. Discarded by D14 |

---

## AC-V1.2 — The orchestrated-grind tension, resolved

The tension is **resolved in the code's favour, decisively.**

Spec prose reads as heavily skill-coupled: the emit-back section exists "so ROOT
reads decision-relevant state," the watchdog is armed by ROOT, the handoff
"replaces `ORCHESTRATION-STATE.md` §7 entirely," and the seed schema records "the
model+effort the lieutenant runs at."

The code does not agree:

- `lieutenant`, `bookkeeper`, `teammate` — **zero occurrences** anywhere in the package.
- `ROOT` — appears only inside explanatory comments citing the spec
  (`fold.py:413`, `conditions.py:284`, `model.py:124`). Never an identifier,
  never a branch, never dispatched on.
- `Lane.agent` / `.model` / `.effort` (`model.py:112-114`) are opaque strings
  copied through from `lane_handover` (`fold.py:183-187`), never interpreted or
  validated against any roster.
- `mission` / `protocols` are `JsonValue` blobs — required to be objects at the
  payload boundary (`payloads.py:90-91`), never introspected by fold,
  conditions, or verbs. Only the renderer extracts a display string.
- No imports of `workcli`, no shelling to `bd`/`gh`/`git`, no filesystem
  assumptions beyond a caller-supplied `--dir`.

**No code in the package would break or lose meaning under a different agent
topology.**

The reason is visible in the freeze state: the skill coupling was scoped as
`.30.7` (SKILL.md rewrite, bookkeeper retirement, `ORCHESTRATION-STATE.md`
removal) and `.30.7` **was never completed** — `in_progress` at freeze, blocked
on its siblings. The mechanics (`.30.1`–`.30.6`) all closed; the integration that
would have welded them to the skill did not.

**The one unfinished piece is the one piece D14 discards.** The runtime is clean
because nobody finished coupling it.

---

## AC-V1.3 — Pipeline obligations vs. what exists

| Executor obligation (charter) | Runtime today |
|---|---|
| Dispatch scaffold→green workers (D4/S7) | **Does not supply.** The runtime records that an item started; nothing dispatches |
| Bounded budgets — 2 CI-fix, 1 rebase (D10) | **Does not supply.** See below |
| Typed park reasons (D10) | **Partially supplies — wrong vocabulary.** See below |
| Park/escalate via `work` verbs (D11/S9) | **Does not supply.** Zero external coupling by design |
| Staleness report (D10/S9) | **Substantially supplies.** `stale_item`/`stale_lane` conditions + `grind check`; surfacing at open-new-work is the S9 wiring |
| Never act on a parked item unbidden (D10) | **Supplies, exactly.** See below |
| Consume verdict artifact as review exit (D8/S6) | **Does not supply**, and has a colliding enum. See AC-V1.4 |
| Merge eligibility = CI + verdict + approval (D9/S8) | **Does not supply.** No `gh` awareness at all |
| Close-on-merge atomicity (D11) | **Does not supply** the call; `work close` already does the walk |
| Human PR comment → escalation (D9) | **Does not supply.** No identity awareness |
| AC7/AC8 instrument source data (D19) | **Partially supplies.** Every event is timestamped; bot-vs-human identity is absent from the taxonomy |

### There is no budget concept

`DEFAULT_CONFIG` (`model.py:165-169`) is the **entire** threshold surface:
`stale_item_after: "45m"`, `stale_lane_after: "30m"`,
`stalemate_risk_round: 3`. Two timers and a repeat-detector.

A timer reports that nothing happened. A budget decides you have spent enough.
D10 requires the latter. Both sides confirm the gap independently — the S2 spec
is explicit that "the budget numbers themselves (2 CI-fix attempts, 1 rebase) are
executor policy (S9), not facade logic — the facade records the outcome, it never
counts attempts."

**Attempt counting is net-new S9 work.** Nothing upstream supplies it.

`review_stalemate_risk` (`conditions.py:216-245`) is the nearest relative — it
fires when the last N review rounds carry the same `head_sha` — and it is a
*condition*, not a budget: it reports risk, it does not exhaust.

### The park vocabularies are disjoint

This is the sharpest concrete finding in the report.

- **grind** `ParkKind` (`model.py:35`): `discovered-work`, `human-gated`, `later-wave`, `deferred`
- **`work park --reason`** (D10, shipped in S2): `ci-failure`, `merge-conflict`, `approval-required`, `bot-declined`, `budget-exhausted`

**No member is shared.** They are not near-misses; they are different
taxonomies. grind's kinds are *scheduling* decisions — this is out of wave, this
is backlog. D10's reasons are *failure* decisions — this PR did not merge and
here is why, split into machine-actionable and human-required.

Reconciling them is a fold-level change with tests behind it, and it is a
prerequisite to any `work park` wiring. It belongs in S9's first child, not
discovered mid-slice.

### Where the fit is genuinely excellent

The only exit from parked is an explicit `item_enqueued` event
(`fold.py:531-551`). There is no timer, no TTL, no automatic resurrection.

D10: *"The machine never acts on a parked item of its own accord; there is no
automatic TTL action."*

The runtime already enforces D10's most important safety property, and it did so
before D10 was written. The same holds for `item_waiting_human` →
auto-`AttentionEntry` → cleared only by an explicit `item_resumed` carrying a
ruling. The escalation semantics the charter wants are already load-bearing,
tested code.

---

## AC-V1.4 — Named upstream coupling for S9 scoping

**S6 (verdict schema, D8) — hard block, plus an enum collision.**
`payloads.py` already ships `_VERDICTS = clean | findings | stalemate`,
`_REVIEW_KINDS = codex | copilot | ralf | human`, and
`_DISPOSITIONS = fixed | wont-fix | deferred | escalated`, with a `review_round`
fold handler, `round_history` tracking, and tests. D8 mandates a
**Mechanical/Advisory** schema where mechanical findings block and must carry a
mechanical artifact.

These do not compose. S6 will be rewriting an enum that has built, tested fold
behaviour behind it. **S6 must be told this before it designs the schema** — the
existing vocabulary is prior art with a migration cost, not a blank page.

**S7 (dispatch brief, D4) — hard block.** The executor's work order format. The
runtime has no dispatch concept whatsoever.

**S8 (verdict harvester + merge-eligibility, D13) — hard block.** The
"is this PR done" oracle. The runtime has no `gh` awareness.

**`work` facade (D11) — not a block; ready.** Post-S2 the tracker-state half of
the executor's job is fully expressed: `claim`, `release`, `ready`, `park
--reason`, `redispatch`, `abandon`, and `close` with close-walk by default. Two
recorded boundaries matter to S9: *recut* is deliberately not a verb (it is
`abandon` + fresh implementation, executor-side), and re-parenting is not
expressible.

**Net:** S9's *substrate* is ready and its *tracker* is ready. Its **decision
inputs are all unbuilt**. S9 cannot be dispatched until S6, S7, and S8 land.

---

## AC-V1.5 — Outcome

**FIT.** D14 is confirmed. S9 is scoped as a re-aim of the existing runtime, not
a re-scope and not a rebuild. The event core, fold, conditions, CLI, and
renderer are kept and imported.

Two qualifications ride with the confirmation:

1. **Scope correction.** The substrate is roughly half the executor. The
   decision layer — dispatch, budgets, review triggering, merge-eligibility
   consumption, `work`-verb wiring — is net-new and larger than "re-aim" implies.
2. **S9 is hard-blocked on S6, S7, and S8** for its decision inputs. Only the
   preparatory children below can start before those land.

### Recommended S9 children

Startable before S6/S7/S8 (substrate-only, no decision inputs needed):

- **Park vocabulary reconciliation** — fold `ParkKind` onto D10's typed reasons.
- **Attempt-budget counting** — net-new; the runtime has timers, not budgets.
- **`work`-verb wiring** — `park`/`redispatch`/`abandon`/`claim`/`close`/`sync` call sites.
- **Installer registration** — absorb `wgclw.30.9`; see below.
- **Staleness surfacing at open-new-work** — explicitly deferred here by S2-D4.

Blocked on upstream slices:

- **Dispatch of scaffold→green workers** (needs S7's brief format).
- **Review triggering + verdict consumption** (needs S6's schema).
- **Merge-eligibility evaluation call site** (needs S8's evaluator).
- **Bot-vs-human identity in the event taxonomy** (needs S6's bot identity; feeds AC7).

Also in scope, independent: **beads git-hooks retirement** (`agents-config-9k9.6`),
once `work sync` call sites exist.

Explicitly discarded: `.30.7` (SKILL.md integration) and `.30.8` (slim SKILL.md)
— both `orchestrated-grind` work that D14 rejects.

---

## AC-V1.6 — Freeze state accounted for

Ten records under `agents-config-wgclw.30*` in
`SAVEPOINTS/2026-07-21-beads-final-export.jsonl`:

- **Epic `wgclw.30`** — open. Consistent with D14 treating it as live, not finished.
- **`.30.1`–`.30.6`** — all closed. Event schema + FSM fold, CLI verbs, dashboard
  renderer, observations, emit-back, staleness watchdog. The mechanics.
- **`.30.7`** — **in_progress at freeze**, blocked on all siblings. The
  orchestrated-grind integration. Discarded by D14. Its incompleteness is why the
  code is clean.
- **`.30.8`** — open, self-flagged "MUST REASSESS BEFORE EXECUTING." Discarded
  with `.30.7`.
- **`.30.9`** — open. `grind` was never registered in the installer's
  `CLI_PACKAGES`. **Verified directly during V1:**
  `packages/installer/src/installer/core/clis.py:39-42` lists `workcli` and
  `prgroom` only. The binary D14 nominates as the executor loop **is not on
  PATH**. Absorb into S9.

Resolved during V1: `.30.1`'s close note reads "PR #355 open... awaiting bot
review," which looks inconsistent with its closed status. It is stale note text
— the code is in `main`, `make ci-grind` is wired into the top-level `ci` target
(`Makefile:21`), and 268 tests collect. No action.

---

## Build state (evidence for the KEEP verdicts)

3,286 lines across 14 modules. No stubs, no TODOs, no `NotImplementedError`.
21 event types, each with a validator (`payloads.py`) and a fold handler
(`fold.py`). 268 tests across 22 files, including replay determinism.
`make ci-grind` mirrors `ci-workcli` (lint, format-check, typecheck, coverage,
audit, entry-verify) and is wired into `make ci`.

One architectural note for S9: grind has **no `Protocol`/ABC seam** — zero hits.
Contrast `workcli`'s `class Backend(Protocol)` (`backend.py:39`), the D11
portability guarantee. grind's only injections are `Clock` and IO callables for
testability. Importing `grind.fold`/`conditions`/`verbs` as a library works today
(nothing in them touches argv or files), but there is no formal extension point
marking that supported. Whether S9 adds one is a design call for the slice, not a
fit blocker.

---

## Addendum — the hard seam (added after the verdict; strengthens it)

A late pass over the condition vocabulary surfaced the single most important
architectural fact for S9 scoping, and it changes *how* the slice should be
built without changing the FIT verdict.

The runtime is **designed never to decide**, and that design is enforced in
code. `conditions.py:5-9`:

> "HARD SEAM: a condition is a fact with evidence, never orchestration policy
> — its name states what is true and its fields carry the evidence, never an
> instruction ("nudge the lane", "escalate the review"). `IMPERATIVE_VERBS` is
> the convention lock a test asserts every condition name against; growing the
> vocabulary means adding a name here, never a verb."

`IMPERATIVE_VERBS` (`conditions.py:44+`) forbids exactly: `nudge`, `escalate`,
`notify`, `alert`, `retry`, `resume`, `pause`, `abort`, `cancel`, `block`,
`unblock`, `merge`, `close`, `reopen`.

That list is, almost verbatim, **the executor loop's verb set**. A test fails if
any condition name expresses one.

This is not an obstacle — it is a directive, and a correct one. It settles a
question S9 would otherwise litigate mid-slice:

**The decision layer goes above grind, not inside it.** grind stays a
fact-emitter — it folds events into state and surfaces conditions with
evidence. The executor consumes those conditions and owns every decision:
attempt budgets, review triggering, merge eligibility, park reasons, `work`
verb calls. S9 must not grow grind's condition vocabulary toward imperatives;
the lock will fail the build, and it should.

Consequence for scoping: S9 is a **new consumer built on grind**, plus targeted
changes inside grind's data model (the park-vocabulary reconciliation, and
whatever budget *state* must be folded so attempt counts survive compaction).
The split is clean, and the existing test guards it.

Corroborating this stance, `review_stalemate_risk` is explicitly a detector and
not a cap — the spec states "stalemate *declaration* stays with the review
skill's §3 rule," so the fold computes the arithmetic and defers enforcement
entirely. The runtime has consistently declined to be the decider. Nothing about
that needs changing; something above it needs building.

### Two smaller corrections to AC-V1.3

**`blocked` self-resolves with zero events — the one genuinely unattended
path.** Unblocking is derived: an edge resolves only when its target reaches
`merged`/`done`, and when every edge resolves the fold returns the item to
`queued` and fires `item_unblocked`. There is no unblock event. Real unattended
progress exists in the runtime today, for `blocked` specifically.

Parked work has no equivalent. All four park kinds share one exit
(`item_enqueued`), and `kind` is descriptive metadata rendered as a dashboard
chip — **there is no kind-conditional routing**, no auto-recheck of whether a
`later-wave` item's cohort has arrived. So the sharper form of the residual risk
below: `blocked` grinds unattended, `parked` waits for someone. Which is exactly
right for `human-gated` and exactly wrong for the machine-actionable reasons S9
is about to introduce (`ci-failure`, `merge-conflict`). The park-vocabulary
reconciliation must decide whether the machine-actionable kinds get a routed
re-entry path or inherit the single manual gate.

**Terminal is `done` only — `merged` is an intermediate step.** The transition
table labels only `done` terminal; `merged` legally advances to `done`
(post-merge teardown). D10 says "Closed = merged, no exceptions (dependents key
off merge)." Meanwhile grind's blocker edges resolve on `merged` *or* `done`,
so dependents do key off merge — the two agree on the load-bearing behaviour and
differ on the vocabulary. Minor, but the close-on-merge wiring must pick one and
say so, rather than discovering the mismatch at the call site.

## Residual risk

The runtime encodes **ten distinct human-in-the-loop assumptions** in its spec —
open-once dashboard, human-confirmed partition, `item_waiting_human`, an
`item_resumed.ruling` field recording "the human's decision, terse," a
`human-gated` park kind, and a watchdog whose ring is "a doorbell" for a human
when the driver is dead.

Most are correct and wanted: they are D10's escalation gates, and D10 explicitly
forbids the machine acting on parked items. But the charter's prime directive is
to reduce human interventions per merged PR, and a runtime with a doorbell is
worth watching. The distinction S9 must hold is between **parked because a human
must rule** (correct, keep) and **parked because nobody built the machine path**
(a queue for the morning, and an intervention the instruments should count).

The disjoint park vocabularies are exactly where that distinction gets decided.
