# Spec-Capture Glue — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Bead:** agents-config-qn0g.1.1
**Decision:** One skill + one deterministic helper script that takes a finished brainstorm (in-session or external artifact) and lands it as a dated spec, a correctly-placed bead with a spec-id link, and an assessor-lite readiness verdict with evidence-shaped gaps auto-filed on the bead. Capture never blocks; review never loops.

## 1. Problem

The brainstorming skill ends at "write design doc → user reviews → invoke
writing-plans." Nothing in that terminal sequence:

- links the spec to a bead (bead-origin brainstorms get their `brainstormed`
  label and spec pointer stamped by hand, or not at all);
- places idea-origin beads deliberately — today a bead gets created "orphaned
  or in a place I don't expect" (owner, 2026-07-04);
- emits any readiness signal, so the next session re-derives whether the spec
  is actually implementable or quietly under-specified;
- accepts an externally-produced brainstorm artifact (e.g. a Claude coworker
  doc the owner drops in) as first-class input.

The missing piece is glue, not another review system: the M2 epic
(brainstorm-readiness gate) will eventually supply a mechanical gate
(verify-brainstorm, bead `owqa`); this bead supplies the intake path that gate
will sit behind.

A second failure mode constrains the verdict design. The owner's observed
pattern with adversarial spec review (codex): first 1–2 passes surface
legitimate high-severity issues, then the loop returns "do not ship" with
fresh "high" findings indefinitely until a human stops it. The adversarial-loop
convergence decision record explains why (its D5: the alternatives/optimality
lens never drains; its D7: full-surface re-review regenerates best-N findings
every pass). The glue's verdict step must be structurally incapable of that
treadmill.

## 2. Locked owner decisions (2026-07-04 brainstorm — requirements, not options)

1. Primary surface is Claude Code; the brainstorming skill's terminal phase
   invokes the glue. External artifacts enter the same flow as input material.
2. Two origins, two behaviors: **bead-origin** links and stamps the existing
   bead; **idea-origin** creates the bead and **asks placement at capture**
   (one question while context is hot) — never silent guessing, orphan only as
   an explicit choice.
3. Verdict is **assessor-lite** (option A): inline checklist, `ready` /
   `not-ready` + gaps; recorded on the bead as a label and in the spec;
   **capture never blocks** — spec and bead always land.
4. Gaps are **auto-filed on the bead** as answer-me items so the next session
   starts with "answer these N things."
5. Verdict shape follows the convergence decision record
   (`2026-07-03-adversarial-loop-convergence-decision.md`): thin Phase-0
   assessor instance, draining lenses only, evidence-shaped gaps, dual-signal
   reporting, at most one bounded re-entry.

## 3. Flow

```
brainstorm ends (in-session design approved)      external artifact dropped in
        │                                                   │
        └──────────────┬────────────────────────────────────┘
                       ▼
        [skill] distill → dated spec text (docs/specs/YYYY-MM-DD-<topic>.md)
                       ▼
        [skill] origin? ── bead-origin ──► known bead id
                       └── idea-origin ──► ask placement (parent id | orphan)
                       ▼
        [script] land: write spec file, create/link bead, stamp labels,
                 record spec-id ↔ bead-id cross-links
                       ▼
        [skill] assessor-lite checklist over the written spec
                       ▼
        [script] record verdict: spec-ready | spec-gaps label,
                 gaps section appended to spec + auto-filed on bead
                       ▼
        ready ──► proceed (writing-plans / stop, per session)
        not-ready ──► gaps wait on bead; after answers, ONE re-assess;
                      second not-ready parks for human decision
```

Judgment lives in the skill (distillation, checklist); every mechanical,
repeatable step lives in the script (code over prose).

A fourth event closes the loop outside this diagram, at spec-PR merge —
`capture_spec.py` runs the interim delivery protocol
(docs/specs/2026-07-05-work-lifecycle-and-facade.md §9) directly until the
`work` facade ships its lifecycle verbs: it decomposes the merged spec's
`## Continuations` manifest under the still-open bead, then releases the
claim — mint-before-anything-closes. See §7 for the script's full
delivery-time contract.

## 4. Origins and placement

Capture is one bead, pre-facade: the captured bead is the objective, and the
work lifecycle design's lazy path
(docs/specs/2026-07-05-work-lifecycle-and-facade.md §6) governs how
implementation work materializes. The commitment lives in the spec's
`## Continuations` manifest — made binding by the manifest lens (§5) — and
at spec-PR merge delivery decomposes it under the still-open bead: a single
unit mints one typed child, multiple units mint N, and `- none` means the
spec is the deliverable and the bead closes at merge. The dependency-blocked
`[Impl]` placeholder belongs to the facade's `spec` shape: once
`packages/workcli` ships noun-templated creation, idea-origin captures that
expect implementation instantiate that full shape (`work create spec`:
container + design child + blocked placeholder) instead of a bare leaf, and
the script's delivery step becomes placeholder reconciliation per the
lifecycle design's §6. Interruption is self-reporting either way: a merged
spec with no children yet leaves the bead open + `spec-ready` + childless —
planning-queue membership, not silence. This is a distinct mechanism from
the readiness gaps in §6 below, which stay notes-only.

- **Bead-origin** (brainstorm started from an existing bead): the script
  stamps `brainstormed` on the bead, appends the spec path + a one-line
  decision summary to the bead's notes, and leaves the dependency hierarchy
  untouched. The spec header carries the bead id (dated specs are exempt
  from the no-tracker-IDs rule).
- **Idea-origin**: the skill asks exactly one placement question at capture —
  a parent (milestone or epic id) or explicit orphan. The script then creates
  the bead (`--parent` when given; orphan otherwise), stamps `brainstormed`,
  and cross-links spec ↔ bead identically. An orphan is recorded as a choice
  (note on the bead: "orphan by owner choice at capture"), distinguishing it
  from the accidental orphans this design retires.
- The script refuses to create a duplicate: if an idea-origin capture names a
  title that exactly matches an existing open bead, it errors with the
  collision (capture is pure; dedup judgment goes back to the human).

## 5. Verdict: assessor-lite

A thin instance of the convergence record's Phase-0 assessor (its D4; its D15
explicitly names the assessor a "sibling of the M2 brainstorm-readiness gate").
Explicitly **not** a review loop.

- **Single pass, draining lenses only** (per D5): placeholder scan (TBD/TODO/
  empty sections), internal contradictions, ambiguity (a requirement readable
  two ways), scope (single implementation plan vs needs decomposition),
  testable acceptance criteria, and — per the work lifecycle design's
  manifest requirement
  (docs/specs/2026-07-05-work-lifecycle-and-facade.md §6) — manifest present
  and parseable: a `## Continuations` section with one
  `- <noun>: <title> — AC: …` bullet per item, or the literal `- none`. The
  alternatives/optimality lens is **excluded by design** — that work happened
  during the brainstorm, and it is the lens that never drains (the
  codex-treadmill generator).
- **Evidence-shaped gaps** (per D8): every gap must quote the offending line
  or name the missing section. A gap that cannot cite its evidence does not
  ship.
- **Dual-signal, never silent, never blocking** (per D1/D9): the verdict is
  `ready` or `not-ready` + gaps ledger. Both land the spec and the bead;
  `not-ready` is an annotation, not a refusal.
- **Bounded re-entry** (per D7): after the owner answers the gaps, at most
  **one** re-assess of the amended spec; a second `not-ready` parks the spec
  for human decision with the residual gaps attached. The treadmill is
  structurally impossible: one pass + one bounded re-entry, on a lens set
  that drains.
- When the verify-brainstorm gate (`owqa`) ships, it replaces the inline
  checklist **behind the same seam**: the skill calls the gate, the script
  records the same verdict shape. Nothing downstream changes.

## 6. Recording the verdict and gaps

- Bead label: `spec-ready` or `spec-gaps` (mutually exclusive; re-assess swaps
  them). `ASSUMPTION:` these two label names; they follow the existing
  readiness-label style (`brainstormed`, `implementation-ready`).
- Spec: a `## Readiness` section at the end — verdict, date, and the gaps
  ledger (each gap: quoted evidence + the question to answer). On `ready`,
  the section is one line.
- Bead: gaps auto-filed as a structured answer-me block appended to the
  bead's notes (numbered items mirroring the spec's gaps ledger).
  `ASSUMPTION:` gaps live in the bead's notes, not as child beads — child
  beads would pollute the hierarchy the placement question just got right,
  and close-walk semantics make disposable question-children hazardous. If
  gap volume proves notes-unwieldy, a follow-up can revisit. This is
  unrelated to the implementation children delivery mints per §4 — those are
  real planned work under the still-open bead, not disposable
  question-children.
- Re-entry bookkeeping: the script stamps `spec-reassessed` alongside the
  swap on the single allowed re-entry, making "second not-ready → park" a
  mechanical check, not a memory. `ASSUMPTION:` label name.

## 7. Surface: one skill + one script

- **Skill** (`ASSUMPTION:` name `capture-spec`; a shared skill under the
  agents skills namespace so it deploys to all tools): owns distillation
  (transcript or artifact → spec text following the docs/specs conventions),
  the placement question, the assessor checklist, and the decision to invoke
  the script. The brainstorming skill's step-6 spec location
  (`docs/superpowers/specs/`) is overridden by this repo's convention
  (`docs/specs/YYYY-MM-DD-<topic>.md`) — the skill states the precedence rule
  ("project conventions override the shipped default") rather than hardcoding
  this repo's path, since deployed skills serve other projects too.
- **Script** (`ASSUMPTION:` `capture_spec.py`, a PEP 723 uv-run helper shipped
  as a skill asset, the gate-triage/resolve-policy pattern): deterministic
  operations only — dated-filename computation and collision handling
  (`-2` suffix on same-day same-topic), spec file write, bead create/link,
  label stamping in a fixed order (link notes → labels → gaps), gaps append
  (bd `--append-notes`, never the clobbering replace flags), verdict
  recording, delivery decomposition (§4), and a `--json` result envelope
  (paths, bead id, verdict, gap count, minted child ids at delivery) so
  callers — including a future PDLC orchestrator binding — can consume it
  mechanically. Exit non-zero with a specific error on any bd failure; no
  silent fallbacks.
- The skill never shells raw `bd` for these operations; the script is the
  single place bd quirks live. `capture_spec.py` is a client of the `work`
  facade, not a competing implementation of it: until `packages/workcli`
  ships its lifecycle verbs, the script implements the interim protocol
  (docs/specs/2026-07-05-work-lifecycle-and-facade.md §9) directly at
  spec-PR merge — it decomposes the merged spec's manifest under the
  still-open bead (§4), minting the typed children there, releases the
  claim, and stamps labels, mint-before-anything-closes ordering, always.
  Once the facade ships, the
  script delegates these same mutations to `work` verbs instead of raw `bd`
  calls, behind its own boundary.

## 8. External-artifact intake

An artifact produced elsewhere (Claude coworker doc, another agent's output)
is input material to the same flow: the skill reads it, distills/normalizes it
into the spec shape (it may already be nearly a spec), and everything from
placement onward is identical. The artifact's provenance is recorded in the
spec header (`Source: external artifact, <description>`). No separate intake
command; "any surface" is satisfied by the distillation step accepting
arbitrary markdown, not by per-surface adapters.

## 9. Seams (siblings, cited by name)

| Sibling | Relationship |
|---|---|
| brainstorming skill | Its terminal phase invokes this glue after user design approval (replacing its bare "write design doc and commit" step in projects that install the glue); the skill's own flow is otherwise untouched. |
| `owqa` verify-brainstorm gate | Future replacement for the inline checklist behind the same verdict seam (§5). This spec deliberately keeps the checklist thin so owqa replaces rather than fights it. |
| `7bk.12` AC classification / brainstorm-time knobs | Consumes the same spec+bead shape; the `## Readiness` section is where its mechanical/human AC classification will attach. |
| `7bk.25` bead-spec agent | Downstream consumer of the spec-id ↔ bead-id cross-links this glue guarantees. |
| `4htl` spec post-mortem | Audits the same artifacts; the verdict + gaps ledger gives it a baseline to audit against. |
| Convergence decision record | Verdict shape source (D1, D4, D5, D7, D8, D9, D15); `vaac.2` is the deferred full build-out — this glue adopts the assessor shape without building the engine. |

## 10. Non-goals

- No review loop, no severity taxonomy, no triage bench — assessor-lite only
  (the full discipline is `vaac.2`, deferred).
- No mechanical prose-quality gate (that is `owqa`).
- No AC mechanical/human classification (that is `7bk.12`).
- No per-surface intake adapters (distillation accepts markdown; done).
- No auto-placement heuristics for idea-origin beads — the design's point is
  asking, not guessing.
- No writing-plans invocation ownership: the glue ends at verdict; what runs
  next stays with the session.

## 11. Test plan (script behavioral contracts; bd faked via the shim pattern, temp dirs, no live Dolt)

1. Dated filename: topic → `docs/specs/YYYY-MM-DD-<slug>.md`; same-day
   same-slug collision → `-2` suffix, not overwrite.
2. Bead-origin: existing bead gets `brainstormed` label + notes append
   containing the spec path; no new bead created; hierarchy untouched
   (fake records no dep calls).
3. Idea-origin with parent: bead created with `--parent`, no separate
   `dep add` (auto-edge quirk respected — fake asserts absence).
4. Idea-origin orphan: bead created parentless with the orphan-by-choice
   note.
5. Duplicate-title guard: exact open-bead title match → non-zero exit naming
   the colliding bead; no writes.
6. Verdict recording: `ready` → `spec-ready` label + one-line Readiness
   section; `not-ready` with N gaps → `spec-gaps` label + N numbered
   answer-me items appended to bead notes (append flag used, never replace).
7. Re-entry bookkeeping: second recording on the same bead swaps labels and
   stamps `spec-reassessed`; a third attempt exits non-zero with "park for
   human" messaging.
8. JSON envelope: every success and failure path emits the envelope; exit
   code mirrors success.
9. bd failure mid-sequence (fake fails on label step): non-zero exit, error
   names the failed step, prior steps' effects reported (no silent partial
   success).
10. Delivery decomposition: a merged spec whose manifest names two units
    mints exactly two typed children under the still-open bead and releases
    the claim; a re-run is a no-op (idempotent); a `- none` manifest closes
    the bead at merge; an interrupted run (fake fails after child 1 of 2)
    leaves the bead open and claimed-released with one child — the re-run
    mints only the missing child.

## 12. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` skill name `capture-spec`; script `capture_spec.py` as a
  skill asset (PEP 723, uv-run).
- `ASSUMPTION:` label names `spec-ready` / `spec-gaps` / `spec-reassessed`.
- `ASSUMPTION:` gaps auto-file into bead **notes** (numbered answer-me block),
  not child beads.
- `ASSUMPTION:` checklist wording of the six draining lenses (§5) — the lens
  *set* is locked; the prompt text is the skill author's.
- `ASSUMPTION:` duplicate-title guard is exact-match only (fuzzy dedup is
  human judgment, out of scope).
- `ASSUMPTION:` spec filename slug derivation and `-2` collision suffix.
- `DECIDED (owner, 2026-07-04):` the brainstorming skill this project owns
  (`src/user/.agents/skills/brainstorming/SKILL.md`) is modified directly — its
  terminal phase invokes this glue in-body, not via a wrapper overlay. Resync
  policy: on an upstream resync, diff the project's version against the captured
  `oss-snapshots/superpowers/brainstorming/` baseline to identify the local
  edits to port onto the newer upstream.
