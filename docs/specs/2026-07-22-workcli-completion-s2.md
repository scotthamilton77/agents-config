# S2 — workcli Completion: the Pipeline Verb Set

**Date:** 2026-07-22
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S2 slice; discharges open verification V2, implements D11 with D10 park semantics)
**Supersedes where they conflict:** `docs/specs/2026-07-04-work-facade-cli-contract.md` (predates the rework; audited, not inherited)

The harness of tomorrow addresses the tracker exclusively through the `work`
facade (D11). This spec records the V2 gap audit of workcli's implemented
verbs against the D11 pipeline set, the decisions closing the gaps, and the
per-slice acceptance criteria. All logic lands in `packages/workcli/`, never
in prose.

---

## 1. V2 audit — implemented verbs vs the D11 pipeline set

Audited 2026-07-22 against `packages/workcli/src/workcli/` (verb registry
`verbs/__init__.py::VERBS`) and the installed CLI's `--help` surface.

| D11 verb | Verdict | Evidence |
| --- | --- | --- |
| **mint** | **partial** | `work create <noun>` exists (`lifecycle/create.py`), guarded and track-aware. Three defects: **(a)** no `milestone` noun — the noun set is `spike\|chore\|decision\|feat\|bugfix\|spec\|epic` (`lifecycle/nouns.py::Noun`); **(b)** `create --raw` is transport-only and rejects `--acceptance` (`verbs/__init__.py::_raw_incompatible_flags`) — combined with (a), a milestone with an acceptance section is not expressible via the facade (S1 fell back to `bd create` for `agents-config-9k9` itself; recorded as a note on that bead); **(c)** noun-based create rejects `--label` (`lifecycle/create.py::_validate_usage`: "labels are set by the noun") — labeled creation needs a second `work label add` call, breaking single-call atomicity. |
| **ready** | **exists** | `verbs/read.py::ready`, capability-gated (`ReadySupport`), used by `claim`'s guard. |
| **claim** | **exists** | `lifecycle/transitions.py::claim` — refuses closed/container/blocked, idempotent on `in_progress`, delegates to bd's atomic `--claim`. |
| **park(reason)** | **missing** | No verb. No facade path sets a non-`open` idle status (`release` only walks `in_progress → open`; `update` refuses status by design). No typed-reason vocabulary exists anywhere in the package. |
| **re-dispatch** | **missing** | No verb. |
| **abandon** | **missing** | No verb. `release` is the nearest neighbor but refuses non-`in_progress` items and records nothing. |
| **close-on-merge** | **partial / wrong-semantics** | `verbs/write.py::close` = batch close + optional disposition note — **no close-walk**. `lifecycle/deliver.py` closes a leaf on `--pr` evidence, and its own docstring promises "a container closes via close-walk when its children close" — but no code anywhere implements a walk. A fully delivered tree strands its containers open forever; D11 requires close + close-walk + note as one verb. |
| **dependency edges** | **exists** | `verbs/relations.py::dep` — add/remove/list, typed, `blocks` type-wall pre-check, capability-gated. |
| **containment** | **partial (accepted)** | Parent set at mint (`--parent`/`--orphan`, mutually exclusive, enforced); queried via `show`/`list --parent`. Re-parenting is not expressible (`update` has no `--set-parent`; the `Backend` seam has no `set_parent`). The pipeline mints containment and never re-parents mid-flight — reparent is **out of scope** for S2, recorded as a known facade boundary (fall back to `bd update --parent` and count each use as a new gap signal). |

Verbs outside the D11 set (`plan`, `promote`, `deliver`, `reconcile`,
`discover`, `track`, `lint`, `graph`, `triggers`, `groom`, `sync`) are not
audited here; they persist unchanged.

## 2. Decisions

**S2-D1 — Park is a status + marker + label, all backend-primitive.**
`work park` sets bd's built-in `blocked` status (drops the item out of
`ready`, so `claim` refuses it with no new guard code), adds the `parked`
label (the cheap queryable handle), and appends a structured note
`[work] parked <ISO-8601> <code>: <text>`. One facade call, three backend
primitives, replay-safe in the L7 idempotency style.

**S2-D2 — Typed reason vocabulary (D10).** Fixed codes, category derived:
machine-actionable = `ci-failure`, `merge-conflict`; human-required =
`approval-required`, `bot-declined`, `budget-exhausted`. Unknown codes are
`E_USAGE` naming the vocabulary. The budget numbers themselves (2 CI-fix
attempts, 1 rebase) are executor policy (S9), not facade logic — the facade
records the outcome, it never counts attempts.

**S2-D3 — `redispatch` and `abandon` are the un-park verbs; recut is not a
tracker verb.** Both walk `parked → open` (label off, status `open`, marker
note appended: `[work] redispatched …` / `[work] abandoned …`). They differ
only in recorded intent — re-dispatch means the cause is fixed, abandon
means the PR is closed and the item returns to ready. D10's *recut* is
abandon at the tracker layer (the fresh implementation is executor behavior),
so no third verb exists.

**S2-D4 — The machine never acts on a parked item; staleness is visibility
only.** `work parked` is a read-only report: parked items with code,
category, parked-at, and a `stale` flag past `--stale-days` (default 7). It
performs zero writes. Surfacing it at open-new-work interactions is S9
wiring, not S2.

**S2-D5 — Close-walk is `close`'s default semantics, bounded by milestones.**
After closing its ids, `work close` walks each parent chain: a parent closes
iff it is not a milestone, not already closed, and every child is closed;
each auto-close appends `[work] close-walk: all children closed` and the walk
recurses upward. Milestones never auto-close — a milestone closes on its own
acceptance section (charter AC9), not on child exhaustion. `deliver`'s leaf
close shares the same walk helper, making its docstring true. `reconcile`'s
internal closes keep their current no-walk behavior (advisory follow-up, not
an S2 AC).

**S2-D6 — Milestone noun.** `work create milestone` mints bd type
`milestone` with shape label `shape-milestone` (declared-state container,
consistent with the shape discipline; `is_container` already catches the
type as fallback). `--acceptance` flows through like every noun. Not a
`discover` noun (LEAF_NOUNS unchanged). `create --raw` stays
transport-minimal and keeps rejecting lifecycle flags — the milestone noun is
what closes the expressibility gap, not a fatter primitive.

**S2-D7 — `--label` on noun create is additive with a reserved-namespace
wall.** User labels append after the noun's shape labels. Labels that forge
lifecycle state are refused as `E_USAGE`: prefix `shape-`, prefix `track:`
(that's `--track`'s job), and the exact machine labels `planned`,
`creating-spec`, `impl-placeholder`, `spec-ready`, `parked`.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible against the fake backend; IDs are cited by
the tests. Edge-case taxonomy (inverse, boundary, dependency failure,
repeated invocation, idempotency) applied per slice.

### Slice A — mint completeness (audit rows: mint a/b/c)

- **S2-A1** `work create milestone --title T --acceptance X --orphan`
  succeeds; the created item has bd type `milestone`, label
  `shape-milestone`, and the acceptance text recorded.
- **S2-A2** `work create milestone` is refused a second creation with the
  same title (`E_DUPLICATE_TITLE` — existing rule holds for the new noun).
- **S2-A3** `work create feat --parent P --label install --title T` succeeds
  in one call; the item carries both `shape-feat` and `install`.
- **S2-A4** Reserved labels are refused with `E_USAGE`: `--label shape-x`,
  `--label track:workcli`, `--label planned` (representatives of the wall in
  S2-D7); the backend sees zero create calls (refusal precedes mutation).
- **S2-A5** `work claim <milestone-id>` is refused `E_NOT_CLAIMABLE` as a
  container (inverse: the new noun does not leak into the claimable set).

### Slice B — park / re-dispatch / abandon / parked (D10)

- **S2-B1** `work park ID --reason ci-failure [--note TEXT]` on an
  `in_progress` item → status `blocked`, label `parked`, one
  `[work] parked <ISO> ci-failure: …` note; envelope data reports
  `{id, status: "parked", reason: "ci-failure", category: "machine"}`.
- **S2-B2** Every code in the S2-D2 vocabulary maps to its category
  (machine: ci-failure, merge-conflict; human: approval-required,
  bot-declined, budget-exhausted); an unknown code is `E_USAGE` naming the
  vocabulary, with zero backend writes.
- **S2-B3** Parking a closed item is `E_USAGE`; re-parking an already-parked
  item is an idempotent no-op (no second marker, no error).
- **S2-B4** A parked item is not claimable: `work claim` → `E_NOT_CLAIMABLE`
  (via the existing ready-set guard — parked never re-enters `ready`).
- **S2-B5** `work redispatch ID` on a parked item → status `open`, `parked`
  label removed, `[work] redispatched <ISO>` note; on an unparked open item
  it is an idempotent no-op; on a closed item `E_USAGE`.
- **S2-B6** `work abandon ID` — same transition and guards as S2-B5 with an
  `[work] abandoned <ISO>` note (distinct recorded intent).
- **S2-B7** `work parked` lists exactly the `parked`-labeled items with
  `{id, title, reason, category, parked_at, stale}`; `stale` is true iff
  parked_at is older than `--stale-days` (default 7) against the injected
  clock; the report issues zero backend mutations (fake call log is
  read-only). An item whose marker is unparseable surfaces with
  `reason: null` rather than crashing the report (dependency failure).

### Slice C — close-walk atomicity (close-on-merge)

- **S2-C1** Closing the last open child of an epic in one `work close` call
  also closes the epic and appends `[work] close-walk: all children closed`
  to it.
- **S2-C2** The walk recurses: when the auto-closed epic was itself the last
  open child of a non-milestone grandparent, the grandparent closes too.
- **S2-C3** The walk stops at milestones: a milestone whose last child
  closes stays open (boundary from S2-D5).
- **S2-C4** Closing a child while a sibling remains open leaves the parent
  open (inverse); a parent already closed is not re-closed (idempotency).
- **S2-C5** `work deliver ID --pr N` on the last open leaf of a container
  triggers the identical walk (the deliver docstring's promise becomes
  code).

## 4. Out of scope

Re-parenting (audit row: containment), reparse/backfill of pre-S2 parked
states (none exist in the new DB), staleness surfacing at open-new-work
interactions and attempt-budget counting (S9 executor loop), `reconcile`
walk-on-close (advisory follow-up), GH-issues/Jira adapters (admitted
separately per D11).
