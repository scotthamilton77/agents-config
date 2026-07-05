# Work Lifecycle and the `work` Facade — Design

**Date:** 2026-07-05
**Status:** Draft (pending review)
**Bead:** filed by the adoption sweep (§12) as the first native citizen of this design's own taxonomy
**Decision:** Work-item state is declared, never inferred: status is a claim lease, labels carry phase, and the tracker's own dependency engine gates phase transitions. Objectives are containers that never close before their planned work exists as trackable children; implementation children are created as dependency-blocked placeholders at capture when implementation is expected. A `work` facade CLI (`packages/work`) owns every lifecycle mutation; skills and the future PDLC orchestrator are its clients. Beads remains the storage engine.

## 1. Problem

The 2026-07-04 fablize specfest left five beads (`abn9.40.2`, `abn9.40.4`,
`qn0g.1.1`, `uxns2.1`, `vaac.3`) at `status: in_progress` after their design
specs merged. Because `bd ready` returns only `status: open` beads, all five —
correctly labeled `implementation-ready` — were invisible to every dispatch
queue. Three defects compounded:

- **No status-transition rule exists.** The archived formula-driven lifecycle
  (brainstorm-bead finalize: close the spec'd bead X, mint implementation bead
  Y open) guaranteed status hygiene structurally. The formula machinery was
  quarantined 2026-05-17; the current skills inherited its readiness *labels*
  but no rule for when a claim ends.
- **Routing infers phase from structure.** `whats-next/collect.py` deduces
  containerhood from child counts and type — a safety-critical, fail-closed
  inference machine still written against the dead formula design (`-mol-`
  filters, merge-gate children, "leaf impl bead produced by brainstorm-bead
  finalize").
- **Planned work can hide.** Nothing guarantees that work a merged spec
  commits to exists as trackable items. A close-and-mint handoff was
  considered and rejected during design: its failure window (closed spec bead,
  mint interrupted) *destroys visibility* of planned work — strictly worse
  than today's stale-but-visible failure.

## 2. Invariants

These are the contract. Every mechanism in this design exists to enforce one
of them; any future change that breaks one is wrong regardless of convenience.

1. **Conservation of committed work.** Committed-but-undone work is visible in
   the tracker at every instant. No transition may destroy a work item's
   visibility before its successor exists.
2. **Every failure state is a queue state.** An interrupted transition lands
   the work in a list somebody already reads (planning queue, attention list)
   — never in a state that looks finished.
3. **Claims are leases.** `in_progress` means one live session holds the item
   for the current phase's work. A claim releases at the phase deliverable;
   staleness is mechanically detectable and self-healing.
4. **Phase completion requires externalized evidence.** A merged artifact
   (spec PR, impl PR), minted work items, or both. Never a session's
   say-so. A design phase MAY legitimately conclude by scheduling work
   (created, linked beads) rather than merging a document.
5. **Queues are phase-typed; state is declared, not inferred.** Every queue
   dispatches exactly the kind of work its consumers perform. Containers
   appear in the planning queue (decomposition is work) and never in the
   implementation queue. Queue membership is a function of declared shape,
   phase labels, claim status, and dependency-readiness — never deduced from
   the shape of the tree.

## 3. State model

**Status is claim. Labels are phase. Nothing else.**

| Status | Meaning |
|---|---|
| `open` | Unclaimed. Eligible for dispatch per its queue (given shape/labels/blockers). |
| `in_progress` | Claimed by a live session for the current phase's work. Never legitimately outlives the phase deliverable. |
| `closed` | This item's own deliverable exists (merged PR, recorded findings, all children closed). |

Phase labels: `brainstormed`, `spec-ready` / `spec-gaps` / `spec-reassessed`
(assessor verdict, unchanged from the spec-capture-glue design), `planned`
(containers; §5). Shape labels (`shape-*`, §4) are stamped at creation and
identify which lifecycle template an item follows.

## 4. Shapes and the creation taxonomy

Under the nouns there are three lifecycle shapes plus pure structure. Every
noun is a preset over those shapes; `work create <noun>` instantiates the
template — no agent or human ever hand-assembles the structure.

| Noun | Shape created | Enters queue | Closes against | Secondary work |
|---|---|---|---|---|
| `spike` | terminal leaf | do-it (implementation queue) | recorded findings (notes/doc) | none expected; discoveries via the discovered-work rule |
| `chore` | terminal leaf | do-it | merged PR / completed operation | none |
| `decision` | terminal leaf | do-it | merged decision record | none — done-when-designed as a first-class noun |
| `spec` | container + design child (ready) + `[Impl]` placeholder child blocks-linked behind the design child | design child → brainstorm queue | container closes via close-walk when children close | placeholder reconciled against the spec's manifest at delivery (§6) |
| `feat` | implementation leaf | evidence rule (below) | merged impl PR | none — it is the secondary work |
| `bugfix` | implementation leaf (repro + TDD discipline in AC) | evidence rule (below) | merged impl PR + passing repro test | none |
| `epic` / `milestone` | structural container | planning queue until `planned` | close-walk | children are the work |

**Evidence rule.** An implementation leaf presumes design is settled, so the
facade demands proof: `work create feat --spec <ref>` (or an explicit
`--trivial` acknowledgment) is born dispatchable into the implementation
queue. Without evidence it is created anyway but routed to the brainstorm
queue. Nobody is refused; under-specified work simply cannot masquerade as
dispatchable. The noun sets the shape; the evidence sets the phase.

**Promotion.** A `feat` whose brainstorm reveals real scope is promoted to
spec-shape (`work promote`): children minted under it, it becomes the
container. A `spec` whose design concludes "trivial" reconciles its
placeholder into a single ready leaf. Wrong guesses at capture are cheap.

**Placement.** `work create` asks placement at capture (parent id or explicit
orphan-by-choice) per the spec-capture-glue locked decision. Never
orphan-by-accident.

The noun set is deliberately closed at seven. `docs` is a `chore`/`feat` with
a docs deliverable; `story` is `feat`; `investigation` is `spike`. Additions
require a demonstrated routing failure, not taste.

## 5. Containers and the `planned` label

A container is in the planning queue from creation until explicitly labeled
`planned` — child count is irrelevant (a container with a partial set of
anticipated children still needs planning). `work plan <id> --done` stamps
the label and expects evidence (created children, a plan doc, or an explicit
override). The label is revocable: scope changes remove it and the container
re-enters the planning queue. Replanning is a state transition, not an
embarrassment.

`spec`-shaped containers are born `planned` — the template is the plan
(design child, then impl). Structural containers (`epic`/`milestone`) are
born unplanned.

## 6. The impl placeholder and reconciliation

For objectives where implementation is expected at capture (`spec` noun), the
`[Impl] <objective> (scope: per spec)` placeholder child is created at the
same moment as the design child, `blocks`-linked behind it. `bd ready`
already hides dependency-blocked items, so the placeholder is **visible in
the tracker from birth** (conservation at the finest grain) but **cannot be
dispatched** until the design child closes. The tracker's dependency engine
is the phase gate — no new state machinery.

Every spec written under this design carries a required `## Continuations`
section — the manifest — naming each item to create (noun, title, AC) or
explicitly `none — this spec is the deliverable`. Review feedback that
reshapes scope amends the manifest in the same PR. The assessor-lite verdict
(spec-capture-glue §5) gains a sixth draining lens: manifest present and
parseable.

At delivery, reconciliation is pure parsing of the merged spec:

- **Single unit** → retitle the placeholder, install spec-derived AC; it
  surfaces the moment its blocker closed, correctly typed.
- **Multiple units** → the placeholder becomes the impl sub-container: N
  properly-typed children are created under it, preserving its blocks-edge
  history; it closes via close-walk when they do.
- **None** → close the placeholder as not-needed, reason recorded; close-walk
  finishes the objective.

Work captured as a plain leaf whose brainstorm later reveals implementation
scope takes the lazy path: delivery decomposes it (children minted under it,
it becomes a container). If reconciliation is interrupted, the item sits
open + `spec-ready` + childless → planning queue. Self-reporting (invariant 2).

## 7. The `work` facade

`packages/work` — a real, CI-gated Python package following the installer /
prgroom pattern. Beads is the storage engine; the facade owns every lifecycle
mutation and is the single place bd quirks live. Skills call it today; the
PDLC orchestrator (`packages/pdlc`) drives the same verbs later;
`holding-place`'s Promote contract resolves to `work create <noun>`.

| Verb | What it does | Guards |
|---|---|---|
| `work create <noun>` | Instantiates the noun's template: items, children, blocks-edges, birth labels; asks placement | duplicate-title guard; evidence rule for `feat`/`bugfix` |
| `work claim <id>` | open → in_progress for the current phase's work | refuses containers; refuses blocked leaves |
| `work release <id>` | in_progress → open, no phase advance | — |
| `work deliver <id> --evidence <pr\|items>` | Closes a leaf against evidence; for a design child, parses the merged spec's manifest and reconciles the placeholder (§6) | evidence must verify (merged PR, existing items); idempotent, replay-safe |
| `work plan <id> --done` | Stamps `planned`; container exits planning queue | warns without children/evidence |
| `work promote <id>` | `feat` → spec-shape when brainstorm reveals scope | — |
| `work reconcile` | Recovery sweep: stale claims with merged evidence → deliver retroactively; merged-spec-but-unreconciled placeholders; interrupted expansions | pure detection + idempotent repair; safe for any session, model tier, or cron |

All verbs emit a `--json` result envelope; non-zero exit with a specific
error on any tracker failure; no silent fallbacks.

**Out-of-band merges.** Merge-time is when a transition becomes *valid*, not
the only execution opportunity. Because `deliver` and `reconcile` are
idempotent and evidence-driven, any observer may run them: the authoring
session via monitor-pr at actual merge time (common case), `whats-next` as a
pre-render sweep, session start, or an overnight run. A claim is never
silently wrong; at worst briefly stale, self-correcting on the next glance at
the tracker.

## 8. Queue routing (`whats-next` rewrite)

Queue membership becomes trivial reads of declared state:

| Queue | Membership |
|---|---|
| Planning | container, not `planned`, unclaimed |
| Brainstorm | design child or evidence-less `feat`/`bugfix`/legacy leaf; unblocked, unclaimed |
| Implementation | terminal leaf (`spike`/`chore`/`decision` — dispatchable at birth) or evidence-bearing impl leaf; unblocked, unclaimed |
| Attention | `human`-labeled, plus `work reconcile` findings |

The active-child-count index, `-mol-` filters, merge-gate exclusions, and
formula-era comments in `collect.py` are deleted. During migration the router
reads shape labels when present and falls back to the legacy type/children
inference for unstamped beads — two regimes, one output contract, removed
when the backlog drains.

## 9. Interim protocol (pre-facade)

Until `packages/work` ships its first verbs, skills carry the protocol
manually, and this section is normative:

1. Specs include the `## Continuations` manifest (§6).
2. At spec-PR merge the delivering session: creates impl children under the
   objective per manifest, **objective stays open**, releases the claim
   (status → open), stamps labels. Mint-before-anything-closes ordering,
   always.
3. A session that finds a claimed bead whose spec PR already merged runs
   step 2 retroactively — the recovery path, manual edition.

`fablize` step 9 and the brainstorming terminal phase adopt this immediately;
`capture_spec.py` (per the amended spec-capture-glue design) mechanizes it;
`packages/work` supersedes both.

## 10. Migration

Grandfather by default; stamp by sweep. A one-time mechanical sweep stamps
shape labels onto the live backlog (type + children → shape; containers with
≥1 non-closed child → `planned`; genuinely childless containers stay in the
planning queue — that is their true state). `implementation-ready` retires
for facade-created work (shape + evidence + unblocked replaces it) and stays
honored on legacy beads until they drain. No bd changes are required —
parent-child edges across types, `blocks` edges between non-epics,
ready-hides-blocked, and labels are all existing primitives.

## 11. Asset impact

| Asset | Change |
|---|---|
| `packages/work` (new) | The facade (§7). Filed as a `spec`-shaped objective — the first native citizen of its own taxonomy. |
| `whats-next` / `collect.py` | Router rewrite (§8). |
| `fablize` SKILL.md | Step 9 adopts the interim protocol (§9); readiness end-state = children minted + claim released, never a bare label on a claimed bead. |
| spec-capture-glue spec (`qn0g.1.1`) | Amended: `capture_spec.py` becomes a facade client (interim: implements §9); its bead-origin stamping adopts placeholder reconciliation; manifest lens added to assessor-lite. |
| brainstorming skill terminal phase | Invokes the capture flow (already planned); protocol per §9 until the facade ships. |
| beads plugin rules | Claim semantics (§3) and `planned` convention (§5) documented in `beads.md`. |
| `run-queue` references | Vestigial mentions in `whats-next`, `tech-lead`, `ralf-implement`, `wait-for-pr-comments` cleaned up or re-pointed at the implementation queue. |
| `holding-place` | Promote contract resolves to `work create <noun>`. |
| `packages/pdlc` | The FSM drives facade verbs; no orchestrator change now, seam noted. |

## 12. Specfest repair plan

The first manual run of the recovery path (§9.3), covering **every bead
referenced by specfest PRs #220–#227**, not only the five known-stuck ones —
wave 2 (`abn9.40.1`, `25rmt`, `qptb4`, `g42cj`, `abn9.40.3`) is audited for
the same stale-claim state.

Per stuck bead (claimed with spec merged; unclaimed wave-2 beads skip the
release step): release the claim (→ `open`), stamp `brainstormed`, then the
verdict fork — these specs carry ASSUMPTION ledgers awaiting owner scan (five
flags on the `abn9.40.4` spec, seven on the shared `abn9.40.2`/`vaac.3` spec,
seven on `qn0g.1.1`'s; the Gemini seat in the HEAVY-gate panel spec is
explicitly UNVERIFIED):

- **Owner scans and blesses** → impl children minted per manifest scope,
  `planned` stamped where children exist.
- **Owner defers** → `spec-gaps`, assumptions filed as answer-me items on the
  bead, placeholder (where created) stays blocked.

The shared `abn9.40.2`/`vaac.3` spec splits its continuations across its two
objectives. `uxns2.1` mints only its own slice of the three-topic PR #224
spec. The lifecycle objective bead for this design is created during the
sweep with placement asked at capture.

## 13. Non-goals

- No new tracker. Beads owns storage; the facade owns semantics. The
  invariants are tracker-agnostic; beads already provides the three
  primitives that make them structural (parent-child, close-walk,
  ready-hides-blocked).
- No formula/molecule revival. The old design's structural truth is
  recovered with plain primitives + one facade; its prescriptive state
  machine is not.
- No auto-placement heuristics; placement is asked at capture.
- No review-loop machinery; the assessor-lite verdict shape is unchanged
  apart from the manifest lens.
- No PDLC orchestrator build-out; this design defines the verbs it will
  drive, nothing more.

## 14. Test plan (facade behavioral contracts; bd faked via the shim pattern, temp dirs, no live Dolt)

1. `create spec` instantiates container + design child + blocked placeholder;
   placeholder absent from ready output while design child is open.
2. `create feat --spec <ref>` is born implementation-queue-eligible;
   `create feat` without evidence routes to brainstorm queue.
3. `create <any>` asks placement; orphan recorded as orphan-by-choice;
   exact-duplicate title exits non-zero naming the collision.
4. `deliver` on a design child: single-unit manifest retitles the
   placeholder and installs AC; multi-unit expands to N typed children;
   `none` closes the placeholder with reason and close-walk closes the
   objective.
5. `deliver` replay: second invocation with identical evidence is a no-op
   (idempotency markers), exit 0.
6. `deliver` with unverifiable evidence (no merged PR, missing items) exits
   non-zero; no mutations.
7. Interrupted expansion (fake fails after child 1 of 3): objective remains
   open and unplanned → planning-queue membership; re-run completes the
   remaining children only.
8. `claim` refuses containers and blocked leaves; `release` restores open
   without phase advance.
9. `plan --done` without children or evidence warns / requires override;
   label revocation re-enters planning queue.
10. `promote` converts a feat leaf to spec-shape preserving id, parent, and
    existing edges.
11. `reconcile` detects: claimed leaf with merged evidence (delivers
    retroactively), merged-spec-with-unreconciled-placeholder, interrupted
    expansion; each repair idempotent.
12. Router (`collect.py`): shape-labeled beads route per §8; unstamped legacy
    beads route per legacy inference; a task-typed container with `planned`
    and children never surfaces in the implementation queue.

## 15. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` shape label names `shape-spike|chore|decision|spec|feat|bugfix`,
  plus `shape-design` (design child) and `impl-placeholder` (pre-reconciliation);
  reconciliation swaps `impl-placeholder` for the manifest noun's shape label.
- `ASSUMPTION:` `planned` as the container phase label; revocation = label
  removal.
- `ASSUMPTION:` manifest grammar — `## Continuations` with one bullet per
  item (`- <noun>: <title> — AC: …`) or the literal `- none`; exact grammar
  finalized by `capture_spec.py` / the facade parser.
- `ASSUMPTION:` bd type mapping — `spec` → feature (epic when the manifest
  expands past a threshold), `bugfix` → bug, `decision` → decision,
  `spike`/`chore` → task + shape label; facade owns the mapping exclusively.
- `ASSUMPTION:` `work` package name and location `packages/work`; verb
  surface as tabled in §7.
- `ASSUMPTION:` migration stamping heuristic (type + children → shape;
  ≥1 non-closed child → `planned`).
- `ASSUMPTION:` evidence flags `--spec <ref>` / `--trivial`; exact flag names
  facade's to finalize.
- `DECIDED (owner, 2026-07-05):` status is claim, labels are phase; objective
  containers never close before planned work exists as children; blocked
  placeholder at capture for expected-impl work; noun-templated creation;
  `planned` is explicit and revocable; the facade is the sole lifecycle
  mutation path once shipped.

## Continuations

- spec: `packages/work` facade — verbs, bd mapping, JSON envelopes (§7) —
  AC: test plan items 1–11 pass under `make ci`-style gates.
- feat: `whats-next` router rewrite to declared-state reads with legacy
  fallback (§8) — AC: test plan item 12 passes; formula-era machinery deleted.
- chore: fablize step 9 + brainstorming terminal phase adopt the interim
  protocol (§9) — AC: both skills state the mint-before-close ordering and
  claim release; no step leaves a claimed bead behind a merged spec.
- chore: spec-capture-glue spec amendment (§11) — AC: amended spec reflects
  facade layering, placeholder reconciliation, and the manifest lens.
- chore: specfest repair sweep + backlog shape-stamping migration (§10, §12)
  — AC: zero claimed beads with merged specs; all PRs #220–#227 beads
  audited and dispositioned.
- chore: beads plugin rules update — claim semantics + `planned` (§11) —
  AC: `beads.md` documents both; no contradiction with deployed rules.
