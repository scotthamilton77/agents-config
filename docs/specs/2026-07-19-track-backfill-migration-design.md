# Track backfill migration — design

Date: 2026-07-19
Status: draft
Bead: agents-config-jpn0s
Supersedes the migration sketch in `docs/specs/2026-07-15-workcli-track-partition-design.md` §7.

## 1. Problem

`work lint` invariant 1 requires every non-closed, non-milestone work item to
carry exactly one `track:*` label. Today **368** items carry none, and the
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
comparing its output against a blind per-item assessment of all 368 items gives
**64% top-1 agreement** (236/367), 73% within top-3. Its residue metric is also
misleading: it reports only 8 items as `unknown`, but 236 of its 368 assignments
rest on substring matching over title and description — 95 of them decided by the
single token `skill` appearing anywhere in the text. The ambiguity is not the
`unknown` bucket; it is the keyword tier.

A classifier accurate on two items in three cannot be an auto-apply source, and
its confidence signal does not distinguish its strong assignments from its weak
ones. The migration therefore ships **no classifier**. Classification is an input
artifact, decided once and reviewed, and the script is a dumb applicator.

## 3. Decided vocabulary

Twelve tracks. `skills-discipline` and `portability` are retired; five tracks are
minted. Counts are the decided assignment, not estimates.

| Track | Items | Kind | Charter |
|---|---:|---|---|
| `pipeline-discipline` | 73 | organizing-only | The bead SDLC engine as it exists today: formulas, brainstorm/implement-bead, whats-next, worker-fleet agents and dispatch, HEP escalation, container hygiene gates. Decides *what work happens and how it moves*. |
| `ops-meta` | 68 | organizing-only | Running the operation: roadmap and milestone management, cost/model-routing economics, telemetry, dashboards — plus pure repo hygiene (zero behavioural delta) and research spikes whose acceptance is "decide whether to adopt X". |
| `prgroom` | 45 | extractable | The deterministic PR-grooming CLI and the skills driving it. |
| `installer` | 42 | extractable | The install engine: template assembly, DYNAMIC-INCLUDE flattening, receipts, CLI deployment, per-tool detection. |
| `review-and-merge` | 39 | extractable | merge-guard, the completion/quality gate including its HEAVY tier, adversarial QA teams, cross-model review passes, post-merge sync. Decides *whether work is good enough to land*. |
| `pdlc-orchestrator` | 26 | extractable | The deterministic FSM engine intended to drive Objectives through the lifecycle. |
| `workcli` | 25 | extractable | Owner of the issue-tracker boundary: the `work` facade CLI and its verbs, **and all direct bd tooling** — `bd-*.sh` helper scripts, bd CLI defects, one-time bead-data migrations. Ownership is by boundary, not by implementation language. |
| `vizsuite` | 14 | extractable | Backlog and knowledge-graph visualization and its data contracts. |
| `grind-runtime` | 8 | extractable | The event-sourced grind runtime: typed event schema, single-writer append log, pure FSM fold, CLI, dashboard projection. |
| `agent-skill-platform` | 8 | organizing-only | Importing, adapting, versioning and recording provenance for external skill sources; maintenance of the imported skill set. |
| `runtime-integration` | 5 | organizing-only | Cross-harness behavioural compatibility for shared assets across Claude, Codex, Gemini and OpenCode. |
| `holding-place` | 3 | extractable | The idea pipeline and its Promote contract. |

### Tie-break rule

**Code-locus wins over milestone ancestry.** An item under a roadmap milestone
suggesting one track, but changing code belonging to another, takes the track of
the code it changes.

The rule has one documented blind spot: cross-harness compatibility work has no
single code locus by construction — it touches every tool. `runtime-integration`
exists to hold that case, and is the reason `portability` (which duplicated
milestone grouping) could be retired without losing the work it named.

## 4. How the assignment was decided

Three independent inputs, reconciled:

1. **Blind assessment, pass 1.** All 368 items assessed against the charters by
   19 parallel agents (20 items each), each returning up to 3 ranked track
   recommendations with confidence and rationale, blind to the classifier.
2. **Blind assessment, pass 2.** The 105 items where pass 1's top pick fell below
   0.70 confidence, re-assessed independently by a second model against a
   corrected charter, blind to pass 1's answers.
3. **Human decision.** The 14 items with empty descriptions, and every case the
   two passes could not resolve.

Reconciliation, in precedence order:

| Rule (applied in this precedence order) | Items |
|---|---:|
| New-track cluster membership (subtree closure) | 21 |
| Human-decided (empty descriptions, overrides) | 13 |
| Merge-artifact items → inherit container's track via cascade | 12 |
| Both passes agree on top-1 | 52 |
| Near-agreement (each pick in the other's top-3) → pass 2's pick | 30 |
| Human-resolved disagreement | 4 |
| Single-pass high confidence (≥0.70), uncontested | 236 |
| **Total** | **368** |

Each item carries its deciding rule in the artifact's `provenance` field.

The result is `scripts/track-backfill/assignment.json`: 356 explicit assignments
plus 12 inheriting. It is committed as the migration's audit record — the label
on any item is traceable to the evidence that produced it.

## 5. Application

### 5.1 Order

Explicit assignments first, cascade second. `work track set --cascade` relabels
descendants that are untracked or on the root's pre-change track, and **skips**
descendants already on a different track. Applying the 356 explicit assignments
before cascading the 12 merge-artifacts therefore guarantees cascade cannot
overwrite a decided value.

Three merge-artifacts (`agents-config-30fpy`, `agents-config-hrvzu`,
`agents-config-vinbn`) are parented directly to the M3 milestone. Milestones
carry no track, so these cannot inherit and are assigned explicitly.

### 5.2 Idempotency and recovery

`work track set` removes stale `track:*` labels then adds the target, so
re-running against an already-correct item is a no-op. The two label writes are
**not transactional**: an interruption between them leaves the item track-less,
which is exactly what lint invariant 1 reports.

**Recovery is re-running the script.** No checkpoint file, no resume state. This
is a deliberate consequence of the applicator being stateless over a fixed input.

### 5.3 Milestone orphans

Nine items lack a milestone ancestor. They are not one policy case:

**Anchored** (their own descriptions name the milestone; exempting them would
silence a real roadmap gap rather than satisfy the invariant):

| Item | Anchor | Evidence |
|---|---|---|
| `agents-config-ysfvl` | M4 (`agents-config-t142`) | "The M4 overnight-autonomy goal removes the human who would otherwise notice the gap" |
| `agents-config-9v0y` | M3, under `agents-config-7bk` | "When 7bk.12 ships, re-run Smoke 2"; a follow-up to `7bk.13` |
| `agents-config-n7q0p` | M5 (`agents-config-yf2ov`) | Title ends "(post-MVP)"; references the pdlc-orchestrator core design |

**Exempted** with `lint-exempt:no-milestone` — the label's first use in this
repo:

| Item | Rationale |
|---|---|
| `agents-config-4vn5` | Self-declared: "Runs opportunistically — no milestone dep." |
| `agents-config-acmh.2`, `agents-config-717` | Children of `4vn5`; the label does not cascade (see §7) |
| `agents-config-bkvgz`, `agents-config-gvt64`, `agents-config-ulv3` | Opportunistic hygiene with no honest roadmap position |

### 5.4 Lease sweep

Nine non-milestone items hold an `in_progress` claim. Seven are fresh (0–1 days)
and confirmed live. Two are stale at 65 days and are confirmed-or-released:
`agents-config-y9mm`, `agents-config-abn9.23`.

### 5.5 Groom-state bead

Mint one item on the `ops-meta` track carrying `lint-exempt:no-milestone`, and
record its id in `[operating-model].groom-state-bead`.

## 6. Config changes

`project-config.toml`:

- `[tracks].names` — remove `skills-discipline`, `portability`; add
  `pipeline-discipline`, `review-and-merge`, `grind-runtime`,
  `agent-skill-platform`, `runtime-integration`
- `[tracks].organizing-only` — `pipeline-discipline`, `agent-skill-platform`,
  `runtime-integration`, `ops-meta`
- `[operating-model].groom-state-bead` — the id minted in §5.5

`[tracks].enforcement` stays `advisory`. Flipping it is a separate work item
gated on this migration's exit criterion holding across a full Backlog Grooming
cycle.

## 7. Known gap: exemption does not cascade

`_milestone_orphans` in `packages/workcli/src/workcli/verbs/report.py` checks
`lint-exempt:no-milestone` **per item**, with no ancestor walk. Two consequences:

1. Exempting `4vn5` does not clear its children; each needs its own label.
2. Every future child of `4vn5` re-triggers invariant 2, so a deliberately
   milestone-free bucket epic can never stay lint-clean.

The exemption model does not compose with container beads. Out of scope here;
filed as a continuation.

## 8. Acceptance criteria

1. `work lint` reports **zero** `track_violations` (invariant 1).
2. `work lint` reports **zero** `milestone_orphans` (invariant 2).
3. Every non-closed, non-milestone item derives a non-null `track` in the `work`
   read-verb envelope.
4. No track exceeds `[extraction.pressure].max-track-backlog`.
5. `[operating-model].groom-state-bead` names an existing item.
6. Re-running the migration script is a no-op (idempotency).

Invariant 3 (milestone WIP cap) is **explicitly out of scope** — it is breached
today (3 active against a cap of 2) and is separate work.

## 9. Continuations

- Update `docs/specs/2026-07-15-workcli-track-partition-design.md` §7 to point at
  this design; its classifier-based mechanism is obsolete.
- Retire `scripts/backlog-landscape/classify.py`'s track-classification role, or
  document it as census-only and not an assignment source.
- Fix the non-cascading `lint-exempt:no-milestone` check (§7).
- Reconcile the milestone WIP-cap breach (3 active vs cap 2).
- Reconcile deferred-P0 items: `agents-config-hft` is P0 and has been deferred
  since 2026-04-19.
- Backfill descriptions for the 14 items that have none; placement does not make
  them actionable.
- Audit the auto-generated `merge-*` artifact items — 15 exist with no content of
  their own; they may warrant closure rather than tracking.
