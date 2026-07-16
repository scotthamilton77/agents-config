# Work-Tracker Track Partition — workcli Track Layer, Extraction Policy, Operating Model

**Date:** 2026-07-15
**Status:** Draft — pending review
**Bead:** to be minted at PR merge (see Continuations); nearest anchor `agents-config-wgclw.9` (work facade CLI v1)
**Decision:** Keep the monorepo and the single bead database. Partition the *tracker*
with a first-class, split-portable **track** dimension built into the work-facade
CLI (`work`), governed by config in `project-config.toml`. Repo extraction becomes
a written, mechanically-checked policy (pressure + eligibility triggers) instead of
a recurring judgment call. The seeing layer is vizsuite V2's work-map (already
specced and in flight); this spec pins the track contract V2 consumes as a
grouping/filter dimension over its per-plan lanes.

## 1. Problem

One repo and one bead DB host ~9 concurrent workstreams. Evidence from the
2026-07-15 backlog census and repo audit:

- The **code is not a monolith**: one cross-package import in the whole tree
  (pdlc test → holding-place, a declared dev dependency), zero package-to-package
  co-change in the last 150 commits, per-package CI gates. Splitting the repo
  solves nothing that is broken.
- The **backlog is a monolith**: 325 non-closed beads; 55% carry no label;
  existing labels are process metadata, not workstream tags; 9 deferred orphans
  have no milestone ancestry and are invisible to milestone-filtered views;
  three milestones plus PORT are in flight simultaneously.
- **18 live cross-track dependency edges** connect the workstreams (e.g. vizsuite
  work surfaced prgroom merge-gate bugs via `discovered-from`; prgroom blocks
  installer work on the CLI install lifecycle). bd has no native cross-database
  bead-to-bead edge, so these edges are only queryable while all beads share one DB.

Symptom being fixed: the operator cannot hold the concurrent workstreams and
their fragmented roadmaps in one mental picture, and bead placement decisions
("what does this new idea depend on / conflict with / sit next to") lack context.

(Census figures are dated 2026-07-15; the implementation plan re-derives all
counts live rather than trusting them.)

## 2. Decision summary

1. **Track dimension** — the target invariant is that every non-closed,
   non-milestone bead carries exactly one `track:<name>` label, reached via
   the `[tracks].enforcement` staged rollout (advisory permits untracked
   creates flagged by lint, required enforces it — §4). The vocabulary is
   config-defined, not hardcoded.
2. **Interface in workcli, storage in bd** — `work` verbs enforce and speak track;
   underneath it is a plain bd label. Raw `bd` remains fully usable; rollback is
   a label delete.
3. **Extraction policy as config** — written pressure/eligibility triggers,
   evaluated mechanically at Backlog Grooming; a firing trigger flags a human
   review, never an automatic split.
4. **Operating model** — config-defined advisory knobs (milestone WIP cap,
   exempt milestones, nag threshold; agents-config initial values: cap 2, PORT
   exempt, 7 days), reported by `work lint`, plus a **Backlog Grooming**
   ceremony — deliberately named to stay distinct from CONTEXT.md's Idea-scoped
   Grooming (§6).
5. **Seeing layer** — vizsuite V2 work-map consumes track through the existing
   TrackerPort → work-envelope seam as a grouping/color/filter dimension over
   its per-plan lanes (§8). An interim static landscape generator serves
   Backlog Grooming until V2 ships, then retires.

## 3. Track model and configuration

**Vocabulary** (initial; config-owned):

`installer`, `prgroom`, `workcli`, `pdlc-orchestrator`, `holding-place`,
`vizsuite`, `skills-discipline`, `portability`, `ops-meta`.

`skills-discipline`, `portability`, and `ops-meta` are **organizing-only**: they
partition the backlog but are never extraction candidates (they are cross-cutting
config/process, not packages). `work triggers` excludes them from extraction
evaluation entirely.

**Storage:** one `track:<name>` label per bead. Milestone-type beads carry no
track label (they legitimately span tracks) and are exempt from every track
invariant and gate. Closed beads are exempt from all track invariants.

**Config** (`project-config.toml`):

```toml
[tracks]
names = ["installer", "prgroom", "workcli", "pdlc-orchestrator",
         "holding-place", "vizsuite", "skills-discipline",
         "portability", "ops-meta"]
organizing-only = ["skills-discipline", "portability", "ops-meta"]
enforcement = "advisory"   # "advisory" | "required"; omitted key ⇒ "advisory" (fail-safe)

[operating-model]
milestone-wip-cap = 2
wip-exempt-milestones = ["agents-config-uxns2"]  # PORT — identified by bead id, never display name
backlog-groom-nag-days = 7
groom-state-bead = ""   # bead id holding backlog-groom state; minted during backfill (§7)

[extraction.pressure]
# PRESSURE signals — "this track would BENEFIT from its own repo."
max-track-backlog = 100            # mechanical: non-closed beads in one track.
                                   # Dial ≈ 2x today's largest extractable track
                                   # (prgroom, 49); tune at Backlog Grooming.
external-consumer-tracks = []      # human-declared (see §5)
independent-release-tracks = []    # human-declared (see §5)

[extraction.eligibility]
# ELIGIBILITY gate — "this track CAN split without severing load-bearing edges."
max-cross-track-edges = 3          # mechanical: TOTAL cross-track dependency edges
                                   # touching the track, both directions (§5)

# Semantics: (any pressure signal) AND (eligibility holds) → per-track flag in the
# Backlog Grooming report: "pressured + eligible — schedule extraction review."
# Never auto-split.
```

**Config discovery:** workcli reads no config today; this spec introduces it.
Resolution follows the package's existing dependency-injection pattern: `main()`
constructs a config loader and passes it down — never a module-global read, and
without widening the fixed handler signature (the loader attaches via the same
`args`-attachment precedent already used for `read_file`). The loader searches
upward from the working directory to the enclosing git root for
`project-config.toml`; an explicit `--config <path>` flag overrides. When no
config is found, every new flag/verb in §4 fails with the typed
`E_NOT_CONFIGURED` error and **all pre-existing verbs behave exactly as today**.

## 4. workcli surface changes

All changes are **additive** to the transport-layer and lifecycle-layer verb
contracts: new flags, new verbs, new envelope fields, new `ErrorCode` members
(`E_TRACK_REQUIRED`, `E_UNKNOWN_TRACK`, `E_NOT_CONFIGURED`) — no `Backend`
protocol change ships under this spec. In a repo without `[tracks]` config, no
existing verb changes at all. In a repo **with** config, the behavioral changes
to the shipped `create` verb are exactly three, all config-gated: (a) parent
track inheritance stamps a `track:*` label on the new bead, (b) in `advisory`
mode an underivable create succeeds untracked with a warning in the envelope,
(c) in `required` mode — a further explicit opt-in — the same call is refused.
This spec amends the work-facade CLI contract (2026-07-04 transport spec,
2026-07-05 lifecycle spec); the `track` envelope field is an additive `Item`
field, so the protocol version bumps MINOR.

- **`work create <noun>`** — track resolution is *derive, else enforce*:
  - with `--parent`: inherit the parent's `track:*` label; a track-less parent
    falls through to enforcement.
  - `--track <name>` is validated against `[tracks].names`; unknown names fail
    with `E_UNKNOWN_TRACK` naming the vocabulary — never a new label.
  - enforcement mode (from `[tracks].enforcement`; omitted ⇒ `advisory`):
    - `advisory` — an underivable, unflagged create **succeeds untracked**; the
      envelope carries a warning and `work lint` flags the bead. No existing
      caller breaks.
    - `required` — the same call fails with `E_TRACK_REQUIRED` and creates
      nothing.
  - **Staged rollout:** agents-config starts at `advisory`; the flip to
    `required` is its own continuation, taken only after the §7 backfill exit
    criterion has held. Consumers that programmatically call `work create`
    (holding-place Promote when it ships, capture flows) must supply or derive
    track before the flip; the flip continuation owns that audit.
  - `work create --raw` does **not** enforce track: it is the adapter-layer
    primitive and a documented bypass. Milestones (created via `--raw
    --type milestone` or raw bd) are track-exempt by §3. Beads entering through
    `--raw` or raw bd are caught by lint invariant 1, not at the gate.
- **`work list --track <name>`** — filter sugar over the label. `track` becomes
  an **`Item`-level envelope field**, so it appears on every read verb (`show`,
  `ready`, `search`, `list`); consumers never parse label strings. Derivation
  happens in the **verb layer** (the bd adapter stays config-free). Beads with
  no `track:*` label expose `track: null` — a lint violation, not an envelope
  error; beads with **more than one** `track:*` label (reachable via raw label
  writes) also expose `track: null` and are flagged by lint invariant 1.
- **`work track set <id> <name> [--cascade]`** — track reassignment is its own
  verb family, keeping `update` scalar-replace-only per the contract's layering
  (labels are not `UpdateFields`). Semantics:
  - validated against the vocabulary; single-command label swap (remove old
    `track:*` if present — on an untracked bead this is a pure add — then add
    new). The two underlying label operations are **not transactional**: an
    interruption can leave the bead track-less, which lint surfaces —
    *lint-recoverable, not atomic*.
  - default scope is the named bead only.
  - `--cascade` relabels only descendants whose current track equals the
    bead's pre-change track (plus untracked descendants); descendants
    deliberately on another track are **skipped and reported**, never
    clobbered (cross-track parenting is legal). The result reports relabeled
    and skipped counts.
  - Raw `work label add track:<anything>` remains possible and **unvalidated by
    design** — raw bd stays usable; lint is the net, `track set` is the gate.
- **`work lint`** — standing hygiene report (JSON envelope on stdout, opt-in
  `--format human` view to stderr), all advisory in v1 (no CI gate; §9):
  1. every non-closed, non-milestone bead has exactly one `track:*` label;
  2. every non-closed bead has a milestone ancestor or an explicit
     `lint-exempt:no-milestone` label;
  3. in-progress milestone count vs `[operating-model].milestone-wip-cap`,
     excluding `wip-exempt-milestones`;
  4. per-track lease report — warn when a track holds >1 `in_progress` bead;
     list every non-milestone lease for staleness triage;
  5. soft warning on parent–child track mismatch below milestone level.
- **`work graph --json`** — bulk export of nodes (non-closed beads + closed
  containers needed for ancestry) and typed edges (dependency + parent-child),
  with track, status, priority, labels per node. The output's JSON schema is a
  **shipped deliverable** of the track-layer continuation (a schema file in the
  package); it is the data contract for the vizsuite V2 work-map and any
  landscape regeneration.
- **`work triggers`** — evaluates §3's extraction config at each Backlog
  Grooming: computes per-track backlog and cross-track edge counts
  (organizing-only tracks appear in counts but are excluded from extraction
  evaluation), echoes the human-declared pressure lists with a "still
  accurate?" prompt, optionally proposes additions from a best-effort local
  scan (sibling project manifests and `<project>/.agents-config/` install
  receipts referencing a package) — advisory only, never edits config — and
  emits per-track status:
  `no-pressure` | `pressured-ineligible` | `pressured-eligible (schedule review)`.
- **`work groom --done` / `work groom --status`** — records **Backlog
  Grooming** completion. State (`backlog_last_groomed`) lives **in the bd
  backend itself**, on the designated `[operating-model].groom-state-bead`
  (metadata preferred; a parseable note is the fallback — the mechanism is an
  implementation decision, the requirements are fixed: dolt-synced across
  machines, no per-machine divergence, no git commit churn). `--status`
  returns days-since and whether `[operating-model].backlog-groom-nag-days` is
  breached; `--done` resets the clock. The whats-next surface consumes
  `--status` to prepend one dismissible line that must be unmistakably labeled
  as the **backlog** grooming nag — mechanical and self-silencing like
  CONTEXT.md's Grooming Nag, but a distinct instance on a distinct timestamp,
  so the two nags can coexist on the whats-next surface once the Holding Place
  ships (§6).

**Split-portability constraint (design rule, not shipped code):** no new
surface in this spec may assume single-DB semantics in its *contract* — every
verb is track-relative, never repo-relative. The track→backend source-resolver
itself is **deferred to extraction execution** (§9): at N=1 it would ship zero
behavior, and amending the `Backend` protocol for zero behavior fails the
additive audit. When extraction work begins, the resolver is designed then,
against this spec's track dimension.

## 5. Extraction policy

Purpose: replace recurring "should package X get its own repo?" deliberation
with a written, falsifiable policy.

- **Pressure** signals say a track would *benefit* from extraction:
  - `max-track-backlog` (mechanical, from live counts);
  - `external-consumer-tracks` (human-declared: some project outside this
    repo's install pipeline consumes the package — another repo's manifest
    names it, an independent `uv tool install`, or publication to an index.
    A second *install target* of this repo — the PORT milestone's multi-machine
    story — is NOT an external consumer);
  - `independent-release-tracks` (human-declared: the package needs its own
    release cadence).
- **Eligibility** gates whether extraction is *safe*. The metric is the
  **total count of cross-track dependency edges touching the track, in both
  directions**: every non-parent-child dependency edge between two non-closed
  beads whose tracks differ, where either endpoint's track is the track under
  evaluation. Both directions count because extraction severs edges
  regardless of direction — a track that blocks others is as entangled as one
  others block. bd cannot express live cross-database edges, so every counted
  edge would degrade to a coarse convention after a split.
- **Firing:** any pressure signal AND eligibility → `work triggers` flags the
  track for a human extraction review in the Backlog Grooming report. Nothing
  splits automatically. Failure mode is soft by design: a missed declaration
  only delays a review.

Worked example (2026-07-15 data): prgroom has 49 non-closed beads (no backlog
pressure at threshold 100) and ~5 total cross-track edges — 3 inbound
`discovered-from` edges from vizsuite plus 2 outbound `blocks` edges into
installer — which exceeds the eligibility threshold of 3 (ineligible).
Status: `no-pressure`, ineligible — no review, no deliberation.

## 6. Operating model

All knobs live in `[operating-model]` (§3) — nothing is hardcoded, and the
exempt milestone is identified by bead id so the CLI stays portable.
agents-config's initial values: cap 2, PORT exempt, 7-day nag.

- **WIP cap:** at most `milestone-wip-cap` milestones `in_progress`
  concurrently, excluding `wip-exempt-milestones`. Advisory: `work lint`
  reports breaches; nothing blocks. (Adopted with M0 already narrowed-to-close.)
- **Backlog Grooming cadence:** nag after `backlog-groom-nag-days`. A session:
  triage new and deferred beads, confirm trigger declarations (`work
  triggers`), review the lint report, regenerate the landscape artifact,
  `work groom --done`.
- **Terminology guard:** CONTEXT.md's **Grooming** is the Holding-Place
  ceremony that triages *Ideas* into Buckets; its Last-Groomed Timestamp and
  Grooming Nag are pinned to that ceremony. This spec's ceremony triages
  *beads* (Objectives) and is everywhere called **Backlog Grooming**, with its
  own `backlog_last_groomed` timestamp and its own nag label; the whats-next
  surface must label the two nags unmistakably when both exist. The two
  ceremonies may share a calendar slot once the Holding Place ships; the
  primitives, timestamps, and nags stay distinct. (A fully non-overlapping
  name — e.g. "Backlog Triage" — remains open to the glossary owner; this
  spec's mechanics are name-independent.)
- **Interim seeing layer:** the 2026-07-15 static landscape generator
  (milestone swimlanes, track colors, cross-track edge emphasis,
  placement-demo panel) is parked at `scripts/backlog-landscape/` and
  regenerated from a live export at each Backlog Grooming. **Retirement
  condition:** deleted when the vizsuite V2 work-map ships its track
  grouping/filter view. `bd graph --html --all` remains available for ad-hoc
  dependency inspection.

## 7. Backfill migration (one-shot)

A script under `scripts/` (not a workcli verb — migration code does not earn
permanent residence):

1. Re-run the census classifier (milestone/epic ancestry, then label, then
   keyword) over all non-closed beads to propose `track:*` labels — counts
   re-derived live, not trusted from the 2026-07-15 census.
2. Apply unambiguous proposals via `work track set` (the validated gate — the
   script does not use raw label writes).
3. Queue the ambiguous residue (~16 beads at census time) for human decision
   at the next Backlog Grooming.
4. Anchor the milestone-orphans under a milestone or apply
   `lint-exempt:no-milestone` explicitly.
5. One-time lease sweep of the non-milestone `in_progress` beads: confirm
   live (two are the in-flight vizsuite V2 build) or release.
6. Mint the groom-state bead (ops-meta track, `lint-exempt:no-milestone`) and
   record its id in `[operating-model].groom-state-bead`.

Exit criterion: `work lint` invariants 1–2 report zero violations. Holding that
criterion across a full Backlog Grooming cycle is the precondition for the
enforcement flip to `required` (its own continuation).

## 8. Coordination with in-flight vizsuite V2

The V2 work-map is being built in parallel (under `agents-config-yf2ov.2`).
V2's own approved design models **per-plan lanes** (`plans[] / steps[] /
regions[] / edges[]`); a track is coarser than a plan — one track contains many
plans. Track is therefore a **grouping/color/filter dimension over V2's
per-plan lanes, not the lane identity**. Contract-first discipline applies:

- This spec pins what V2 may rely on: the `[tracks]` vocabulary, the
  `track:<name>` label format, the `Item`-level `track` envelope field on all
  read verbs, and `work graph --json` with its shipped schema. These freeze at
  spec merge; changes thereafter go through contract amendment, not drift.
- The V2 builder must read the `track` envelope field via TrackerPort and must
  not parse `track:*` labels directly.
- Request to the vizsuite effort (its owner decides the exact semantics): an
  optional `track` attribute on `plans[]`, derived from the plan's bead
  subtree, enabling group-by-track, color-by-track, and filter-to-track over
  the existing lanes. The handoff records an explicit accepted-or-declined
  disposition — filter-by-track via `Item.track` works either way; group/color
  by track over lanes needs the attribute.
- Until `work graph --json` lands, V2 may continue against existing verbs; the
  graph verb is an optimization of its read path, not a blocker.
- Action at spec merge: notify the V2 build session/agent of this contract.

## 9. Out of scope

- **Bucket labels on beads.** CONTEXT.md's CA-8 split is binding: Bucket is an
  Idea-only property. `deferred` status remains the Objective parking mechanism.
- **Rendering in workcli.** All visualization stays in vizsuite / the interim
  script; workcli ships data verbs only.
- **Extraction execution.** No repo split, bd DB split, migration tooling, or
  `Backend` source-resolver ships under this spec — only the policy that would
  trigger a review, and the contract-level split-portability rule (§4).
- **CI-gating `work lint`.** v1 is advisory at Backlog Grooming. Promoting
  invariants 1–2 to a CI gate is a separate later decision, taken only after
  backfill coverage has held for multiple Backlog Grooming cycles.
- **Dreaming Process.** The placement-assistant remains post-MVP; the interim
  landscape's lexical what-if panel is a demo, not its design.

## 10. Acceptance criteria

1. `work create` with a tracked parent inherits the parent's track with no
   `--track` flag, in both enforcement modes.
2. With `enforcement = "required"`: `work create` with no derivable parent and
   no `--track` fails with `E_TRACK_REQUIRED` and creates nothing.
3. With `enforcement = "advisory"`: the same call succeeds untracked, the
   envelope carries a warning, and `work lint` flags the created bead.
4. With `[tracks]` present and the `enforcement` key omitted, `create` behaves
   exactly as in `advisory` mode.
5. `work create --track <unknown-name>` fails with `E_UNKNOWN_TRACK` naming the
   configured vocabulary.
6. `work track set <id> <name>` leaves the bead with exactly one `track:*`
   label — the new one — including when the bead was previously untracked
   (pure add); unknown names fail with `E_UNKNOWN_TRACK`.
7. `work track set --cascade` relabels descendants on the bead's pre-change
   track (and untracked descendants), skips descendants on other tracks, and
   reports relabeled and skipped counts; without `--cascade` descendants are
   untouched.
8. Every read verb's envelope carries `track` for every bead: the label's name
   when exactly one `track:*` label is present, `null` when none or more than
   one is present; `work list --track <name>` returns exactly the beads
   labeled with that track.
9. Milestone-type beads are created without any track requirement and are
   never flagged by lint invariant 1.
10. `work lint` on a fixture exercising all five invariant classes (missing
    track, milestone-orphan, WIP breach among non-exempt milestones, a track
    holding two `in_progress` beads, a parent–child track mismatch) reports
    each class and exits advisory (zero exit code in v1).
11. A milestone listed in `wip-exempt-milestones` is not counted toward the
    WIP cap.
12. `work graph --json` output contains every non-closed bead with its track,
    every dependency edge typed, and validates against the schema file shipped
    with the package.
13. `work triggers` reports `pressured-eligible` only when a pressure signal
    fires AND the total cross-track edge count (both directions, per §5) is
    below threshold; organizing-only tracks never receive an extraction
    status.
14. `work groom --status` reports nag-breached exactly when days-since-groomed
    exceeds the configured threshold.
15. Immediately after `work groom --done`, `--status` reports not-breached and
    the whats-next surface shows no backlog-grooming nag line.
16. Config resolution finds `project-config.toml` via upward search from a
    repo subdirectory, and an explicit `--config <path>` overrides the search.
17. With no `[tracks]` config resolvable: every new flag/verb fails with
    `E_NOT_CONFIGURED` and every pre-existing verb behaves exactly as before
    this spec.

Test plan detail (fixtures, test names, coverage targets) is deferred to the
implementation plan, authored under the writing-unit-tests discipline.

## 11. Continuations

- **workcli track layer** — implement §4: config loading/discovery, `create`
  track resolution with enforcement modes, `Item.track` envelope field,
  `work track set` (±cascade), `work lint`, `work graph --json` **with its
  schema file**, the three new `ErrorCode` members; amend the work-facade
  contract spec (MINOR protocol bump). Acceptance: criteria 1–12, 16–17.
- **Extraction triggers + groom state** — implement `work triggers` and
  `work groom` (bd-backed state per §4); wire the backlog-grooming nag line
  into the whats-next surface. Acceptance: criteria 13–15.
- **Backfill migration** — the §7 script and its one-time supervised run,
  including minting the groom-state bead. Acceptance: §7 exit criterion.
- **Enforcement flip** — audit programmatic `work create` call sites
  (holding-place Promote design, capture flows), confirm each supplies or
  derives track, then set `enforcement = "required"`. Precondition: §7 exit
  criterion held across a full Backlog Grooming cycle. Acceptance: criterion 2
  passes in this repo with no consumer breakage.
- **Interim landscape parking** — move the 2026-07-15 generator from /tmp to
  `scripts/backlog-landscape/` with regeneration instructions and the §6
  retirement note. Acceptance: one command regenerates the artifact from a
  live export.
- **V2 contract handoff** — deliver §8's pinned contract to the vizsuite V2
  build effort, including the `plans[].track` attribute request. Acceptance:
  V2 reads the `track` envelope field for grouping/filter with no label
  parsing, and the `plans[].track` request has a recorded accepted-or-declined
  disposition.
- **Placement queue** (deferred capture, not committed): "create a bead for X"
  placement assistance beyond the demo panel — belongs to the Dreaming Process
  design when it is taken up.
