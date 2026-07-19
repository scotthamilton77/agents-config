# Track backfill migration — design

Date: 2026-07-19
Status: draft
Bead: agents-config-jpn0s
Supersedes the migration sketch in `docs/specs/2026-07-15-workcli-track-partition-design.md` §7.

## 1. Problem

`work lint` invariant 1 requires every non-closed, non-milestone work item to
carry exactly one `track:*` label. Today **367** items carry none, and the
`[tracks]` vocabulary they would be labelled against is itself wrong: one track,
`skills-discipline`, would absorb 181 of them — 49% of the backlog, immediately
breaching `[extraction.pressure].max-track-backlog = 100`.

Two problems, one migration: fix the vocabulary, then apply it.

## 2. Why the census classifier is not the mechanism

§7 step 1 of the track-partition design specifies re-running the census
classifier (`scripts/backlog-landscape/classify.py`) to propose labels, applying
the unambiguous majority, and queueing "the ambiguous residue (~16 beads)" for
human decision.

That mechanism was measured and rejected. Re-running the classifier live and
comparing it against a blind per-item assessment of all items gives **64% top-1
agreement** (236/367), 73% within top-3. Its residue metric is also misleading:
it reports only 8 items as `unknown`, but 236 of its assignments rest on
substring matching over title and description — 95 decided by the single token
`skill` appearing anywhere in the text. The ambiguity is not the `unknown`
bucket; it is the keyword tier.

A classifier accurate on two items in three cannot be an auto-apply source, and
its confidence signal does not distinguish its strong assignments from its weak
ones. The migration therefore ships **no classifier**. Classification is an input
artifact, decided once and reviewed, and the applicator is a dumb writer.

## 3. Decided vocabulary

Ten tracks. `skills-discipline` and `portability` are retired; three are minted.
Counts are the decided assignment, not estimates.

| Track | Items | Kind | Charter |
|---|---:|---|---|
| `pipeline-discipline` | 92 | organizing-only | The bead SDLC engine as it exists today: formulas, brainstorm/implement-bead, whats-next, worker-fleet agents and dispatch, RALF skills, HEP escalation, container hygiene gates. Decides *what work happens and how it moves*. |
| `prgroom` | 53 | extractable | The deterministic PR-grooming CLI, its scripts, and the skills driving it. |
| `installer` | 50 | extractable | The install engine: template assembly, DYNAMIC-INCLUDE flattening, per-tool projection and asset compatibility, receipts, CLI deployment, tool detection. |
| `review-and-merge` | 47 | extractable | merge-guard, completion/quality gate including its HEAVY tier, adversarial-QA assets, cross-model review passes, sync-after-remote-merge. |
| `ops-meta` | 39 | organizing-only | Running the operation: roadmap and milestone management, cost/model-routing economics, telemetry, dashboards; external-dependency management and adoption spikes ("decide whether to adopt X"); and purely editorial repo hygiene per §3.2. |
| `workcli` | 31 | extractable | Owner of the issue-tracker boundary: the `work` facade CLI, its verbs and adapter, the `bd-*.sh` helper scripts, bd defects and capability asks, and one-time bead-data migrations. Ownership follows the boundary, not the implementation language — see §3.5. |
| `pdlc-orchestrator` | 29 | extractable | The deterministic FSM engine intended to drive Objectives through the lifecycle, and its design corpus. |
| `vizsuite` | 14 | extractable | Backlog and knowledge-graph visualization and its data contracts. |
| `grind-runtime` | 8 | organizing-only | The event-sourced grind runtime: typed event schema, single-writer append log, pure FSM fold, CLI, dashboard projection. Reclassified `extractable` once a package exists. |
| `holding-place` | 3 | extractable | The idea pipeline and its Promote contract. |

Two tracks proposed during analysis were **rejected on evidence**:
`agent-skill-platform` (5 of 8 candidate members failed its own charter — it
reproduced `skills-discipline` at small scale) and `runtime-integration` (the
PORT milestone's 16 items split 13 to `installer` and 3 here, so the gap it
named was 3 items wide).

### 3.1 Primary tie-break: code-locus over milestone ancestry

An item under a roadmap milestone suggesting one track, but changing code
belonging to another, takes the track of the code it changes. This is why
`portability` could be retired: 13 of the PORT milestone's 16 items have an
unambiguous installer locus.

### 3.2 Secondary tie-break: change-kind over code-locus, bounded

Purely editorial work — zero behavioural delta — takes `ops-meta` **only when it
spans two or more tracks**. Single-track editorial work takes the track of the
asset it edits. Without this bound, `ops-meta`'s hygiene clause can claim an item
from any track.

### 3.3 Policy items with no code locus

An item that defines policy rather than changing code takes the track of the
asset that will implement it.

### 3.4 `prgroom` / `review-and-merge`: the PR-corridor boundary

These two are the easiest pair to confuse, because `prgroom`'s charter is a
**code locus** while `review-and-merge`'s reads as a **purpose** — and by purpose
alone, prgroom is a subset of review-and-merge (everything prgroom does also
decides whether work lands).

The discriminator is the asset, not the purpose:

- **`prgroom`** — the PR-grooming corridor: the prgroom package and its scripts,
  the `monitor-pr` skill, **and the `wait-for-pr-comments` / `reply-and-resolve-pr-threads`
  assets that prgroom supersedes.** Superseded assets stay with their successor
  so that retirement work and successor work share one track.
- **`review-and-merge`** — the gates around that corridor: merge-guard,
  completion/quality gate, adversarial-QA, cross-model review dispatch,
  sync-after-remote-merge.

This rule is load-bearing: 21 items in this assignment touch
`wait-for-pr-comments` or `reply-and-resolve-pr-threads`, and without it they
split arbitrarily between the two tracks.

### 3.5 `workcli` owns a boundary, not a directory

`workcli` is the one track defined by **ownership of an integration boundary**
rather than by code locus: everything concerning how this repo talks to its
issue tracker belongs there, including defects and capability asks against the
`bd` binary itself.

The tension this creates is acknowledged rather than resolved. `workcli` is
marked `extractable`, yet a handful of its members (`1sso`, `f298`, `p3`) are
upstream `bd` concerns that cannot travel with `packages/workcli/` on
extraction. The alternative — routing upstream defects to `ops-meta` — was
rejected because it splits one team's working set across two tracks to satisfy a
property that only matters on the day extraction happens. If `workcli` is ever
extracted, those members are re-homed at that point.

### 3.6 Known expiry: `pipeline-discipline` / `pdlc-orchestrator`

These two are separated by *time*, not structure: both own "what work happens and
how it moves", differing only in whether the mechanism is shipped or planned.
The boundary is therefore temporary by construction. **Merge condition:**
`pdlc-orchestrator` folds into `pipeline-discipline` when the FSM engine drives
its first Objective end-to-end. Recorded so the boundary expires by decision
rather than by drift.

## 4. How the assignment was decided

Three independent inputs, reconciled:

1. **Blind assessment, pass 1.** All items assessed against the charters by 19
   parallel agents (20 items each), each returning up to 3 ranked recommendations
   with confidence and rationale, blind to the classifier.
2. **Blind assessment, pass 2.** The 105 items where pass 1's top pick fell below
   0.70 confidence, re-assessed independently by a second model against a
   corrected charter, blind to pass 1's answers.
3. **Human decision.** Items with empty descriptions, retired-track reroutes, and
   every case the two passes could not resolve.

The result is `scripts/track-backfill/assignment.json`: **366 explicit
assignments**, each carrying the rule that decided it in
its `provenance` field. It is committed as the migration's audit record.

Inheritance for the 9 merge-artifact items is **resolved at artifact-build time**
into explicit assignments; see §5.2.

**Traceability limit.** `provenance` records the deciding *rule*, not the
underlying evidence. For the plurality of items decided by a single confident
pass, "traceable" means traceable to a rule name. The raw pass-1/pass-2 outputs
are not committed. A reviewer wanting to audit a specific assignment must re-run
the assessment for that item.

## 5. Application

### 5.1 The artifact decays; the migration is drift-tolerant by design

This backlog is under active multi-agent work. Between generating the assignment
and reviewing it — roughly one hour — five covered items closed and three new
untracked items appeared. **Any snapshot decays faster than the review cycle that
consumes it.**

The migration therefore does not attempt to be exhaustive at apply time. It:

1. Applies every assignment whose id is still a live violation.
2. **Skips** assignments whose id is no longer live, reporting them.
3. **Reports** live violations absent from the artifact as *residue* — it does
   not guess at them.

Residue is expected, not a failure. It converges to zero only when
`[tracks].enforcement` flips to `required`, at which point `work create` gates on
track and no new untracked item can be created. Until then each Backlog Grooming
cycle sweeps whatever accumulated. The exit criterion in §8 is stated against
*covered* violations for exactly this reason.

### 5.2 No cascade

`work track set --cascade` is **not used**. Its descendant walk applies no status
filter, so cascading from the 8 viable roots would have written track labels onto
~30 **closed** descendants — inert for lint, invisible to every acceptance
criterion, and absent from the audit record.

Three of the twelve merge-artifacts could not have inherited at all: their
containers (`abn9.10`, `7bk.19.9`, `acmh.13`) are closed and carry no track.

All twelve are therefore resolved to explicit assignments at artifact-build time
— nine from their live container's decided track, three from the subject of their
closed container. Nine explicit writes cost less than a 30-item blast radius, and
the ordering hazard the cascade introduced disappears with it.

### 5.3 Execution order

Order is load-bearing. `work track set` calls `require_known_track` **first**, so
applying before the config update fails every write to a new track with
`E_UNKNOWN_TRACK` — 158 of 366 assignments.

1. `bd dolt commit -m "pre-track-backfill checkpoint"` — the rollback point.
2. Update `[tracks].names` and `[tracks].organizing-only` (§6).
3. Verify `work lint` still parses and the vocabulary loads.
4. Dry run: print the full write plan, mutate nothing.
5. Apply the 366 assignments.
6. Reparent the 3 anchored orphans (§5.4); label the 6 exempted.
7. Mint the groom-state bead (§5.6) and set `groom-state-bead`.
8. Verify §8.
9. `bd dolt commit` + `bd dolt push`.

**Run from the main tree, never a worktree** — the bd/Dolt database lives in the
main checkout, and the repo's operating rules forbid DB operations from linked
worktrees.

**Write path:** `work track set` only. Raw `bd label add track:*` bypasses
`require_known_track` and is forbidden, per the parent design §4.

**Failure disposition:** on `E_NOT_FOUND`, skip and record (the item closed
mid-run). On `E_LOCK_CONTENTION` or `E_TIMEOUT` after the adapter's retries,
**abort** — do not continue writing into a contended database. A partial run is
safe to resume by re-running (§5.5).

**Scale:** 366 invocations, each 2–4 `bd` subprocess calls. Budget 5–20 minutes
of continuous Dolt writes and announce against the live leases (§5.5) before
starting.

### 5.4 Milestone orphans

Nine items lack a milestone ancestor. They are not one policy case.

**Anchored** — their own descriptions name the milestone; exempting them would
silence a real roadmap gap rather than satisfy the invariant. Anchoring means
**reparenting**, a graph mutation `work track set` cannot perform:

| Item | Anchor | Evidence |
|---|---|---|
| `agents-config-ysfvl` | M4 (`agents-config-t142`) | "The M4 overnight-autonomy goal removes the human who would otherwise notice the gap" |
| `agents-config-9v0y` | M3, under `agents-config-7bk` | "When 7bk.12 ships, re-run Smoke 2"; a follow-up to `7bk.13` |
| `agents-config-n7q0p` | M5 (`agents-config-yf2ov`) | Title ends "(post-MVP)"; references the pdlc-orchestrator core design |

Reparenting `9v0y` places a `review-and-merge` item under a `pipeline-discipline`
parent, which raises lint invariant 5 (`track_mismatches`, currently 0). **This
is accepted**: cross-track parenting is legal per the parent design §4, and
invariant 5 is a soft warning. §8 records the expected nonzero count so the
regression is observed rather than discovered.

**Exempted** with `lint-exempt:no-milestone` — the label's first use in this repo:

| Item | Rationale |
|---|---|
| `agents-config-4vn5` | Self-declared: "Runs opportunistically — no milestone dep." |
| `agents-config-acmh.2`, `agents-config-717` | Children of `4vn5`; the label does not cascade (§7) |
| `agents-config-bkvgz`, `agents-config-gvt64`, `agents-config-ulv3` | Opportunistic hygiene with no honest roadmap position |

### 5.5 Recovery and concurrency

`work track set` removes stale `track:*` labels then adds the target only if
absent, and bd exits 0 on repeat add/remove. Re-running against a correct item
issues zero writes, so **partial application is repaired by re-running**.

The two label writes are **not transactional**: an interruption between them
leaves the item track-less, which lint invariant 1 reports.

**Rollback is `bd backup restore`, or re-import from the `bd export` dump taken
before the run** — `bd dolt` has no `reset` and no `log` subcommand, so a
Dolt-reset rollback does not exist. `bd vc status` names the commit that is the
recovery point. Re-running is forward-healing only — it cannot undo a wrong
decision. Note that rollback is trivial today only because the prior state is
uniformly "no label"; that ceases to be true after the first successful run.

**Concurrency: the migration requires an exclusive, quiescent window, and the
applicator enforces it.** `work track set` has no status guard and the tracker
offers no compare-and-set, so between the sweep that computes the plan and the
write that applies it, an item can close or another agent can set a track — and
that write would be silently overwritten. Rather than hand-roll optimistic
concurrency for a script that is deleted after one use, the migration takes the
cheaper and stronger option: it refuses to run at all while any covered item is
leased. `apply.py` aborts on a lease intersecting the artifact, so the operator
confirms-or-releases first instead of racing.

Two claims are stale at 65 days and are confirmed-or-released before the run:
`agents-config-y9mm`, `agents-config-abn9.23`.

The residual risk this leaves is narrow and stated rather than papered over: an
agent that takes a *new* lease after `apply.py`'s check, on a covered item, is
still not detected. That window is seconds wide and is closed by operational
discipline — do not dispatch agents during the run — not by the tooling.

### 5.6 Groom-state bead

`work create <noun>` rejects `--label` at runtime (labels are set by the noun),
which would leave the new bead a milestone orphan between creation and
labelling. `work create --raw` accepts `--label`, closing that window:

1. `work create --raw --label lint-exempt:no-milestone` — the bead exists
   already exempt, so it is never briefly a violation.
2. `work track set <id> ops-meta` — the track goes through the validated gate,
   never a raw label write.
3. Record its id in `[operating-model].groom-state-bead`.

All three complete **before** the §8 verification.

## 6. Config changes

`project-config.toml`:

- `[tracks].names` — remove `skills-discipline`, `portability`; add
  `pipeline-discipline`, `review-and-merge`, `grind-runtime`
- `[tracks].organizing-only` — `pipeline-discipline`, `grind-runtime`, `ops-meta`
- `[operating-model].groom-state-bead` — the id minted in §5.6

`[tracks].enforcement` stays `advisory`. Flipping it is a separate work item —
and per §5.1, the flip is what makes this migration's result stable, so it should
follow promptly rather than waiting on a long observation window.

The parent design justifies `max-track-backlog = 100` as "≈ 2× today's largest
extractable track (prgroom, 49)". Under this vocabulary the largest extractable
track is `prgroom` at 53, so the rationale survives unchanged. The largest track overall is `pipeline-discipline` at 92, which is
organizing-only and never evaluated for extraction pressure. Its headroom against
the cap is only 8 items, so it is the next split candidate if it grows.

## 7. Known gap: exemption does not cascade

`_milestone_orphans` in `packages/workcli/src/workcli/verbs/report.py` checks
`lint-exempt:no-milestone` **per item**, with no ancestor walk. Two consequences:

1. Exempting `4vn5` does not clear its children; each needs its own label.
2. Every future child of `4vn5` re-triggers invariant 2, so a deliberately
   milestone-free bucket epic can never stay lint-clean.

The exemption model does not compose with container beads. Out of scope here;
filed as a continuation.

## 8. Acceptance criteria

1. **Outcome matches the artifact.** For every id in `assignment.json.items` that
   was live at apply time, the item's derived `track` in the `work` read envelope
   equals the assigned value. No item outside that set carries a `track:*` label.
   *(This is the criterion that binds the result to the reviewed decision; the
   others are well-formedness checks that a wholly incorrect run could pass.)*
2. `work lint` reports zero `track_violations` **among covered ids**. Uncovered
   ids are reported as residue with their count, per §5.1.
3. `work lint` reports zero `milestone_orphans`.
4. No **extractable** track exceeds `[extraction.pressure].max-track-backlog`.
   Largest is `prgroom` at 53 against a cap of 100.
5. `work lint` `track_mismatches` equals **exactly** the committed baseline in
   `scripts/track-backfill/expected_mismatches.json` (54 ids) plus the one
   deliberate addition from the `9v0y` reparent — 55 in total. Checked in both
   directions: an id beyond the expected set means an unintended cross-track
   parenting was introduced; an expected id *missing* means the graph changed
   under the migration unnoticed.

   The pre-migration count is 0, but only because nothing is labelled yet —
   labelling materializes every pre-existing cross-track parent edge at once.
   Reading that 0 as a stable baseline is the mistake this criterion exists to
   prevent. Note also that `work lint` keys these entries on `child`, not `id`.
6. `[operating-model].groom-state-bead` names an existing item that carries the
   `ops-meta` track and the `lint-exempt:no-milestone` label.
7. A second consecutive run leaves `bd dolt status` clean — no writes.

Invariant 3 (milestone WIP cap) is **out of scope**: it is breached today (3
active against a cap of 2) and is separate work.

## 9. Continuations

- Update `docs/specs/2026-07-15-workcli-track-partition-design.md` §7 to point at
  this design; its classifier-based mechanism is obsolete.
- Retire `scripts/backlog-landscape/classify.py`'s track-classification role, or
  document it as census-only and not an assignment source.
- Fix the non-cascading `lint-exempt:no-milestone` check (§7).
- Reconcile the milestone WIP-cap breach (3 active vs cap 2).
- Reconcile deferred-P0 items: `agents-config-hft` is P0, deferred since
  2026-04-19.
- Backfill descriptions for the 13 items that have none; placement does not make
  them actionable.
- Audit the auto-generated `merge-*` artifact items — 15 exist with no content of
  their own; they may warrant closure rather than tracking.
- Commit the raw pass-1/pass-2 assessment outputs, or enrich `assignment.json`
  with title/confidence/runner-up, so §4's traceability claim is fully supported.
- Reclassify `grind-runtime` as extractable once a package exists under
  `packages/`.
