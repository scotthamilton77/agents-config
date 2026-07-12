# HANDOFF — Visualization Suite fablize session (next phase: V2/V3 brainstorm → grouped spec)

For a fresh context resuming work on **agents-config-yf2ov.2** (epic:
"Visualization suite: PR shape, work-DAG, and codebase evolution", child of
milestone M5). Read this file, `findings.md`, and `bd show agents-config-yf2ov.2`
before doing anything.

## Session type and hard requirements

- This is a **fablize** session (frontier-window spec-fest): the deliverable is a
  **grouped dated design spec** in `docs/specs/`, NOT an implementation. Invoke the
  `fablize` skill's Phase-0 model check — the session must run on **Fable**
  (`claude-fable-5`); stop and tell the user if it isn't.
- Scott multitasks with long gaps between turns: **never park deliverables behind
  a localhost server** (the visual-companion server idle-times-out at 30 min).
  Deliver self-contained HTML files on disk, `open` them, send via SendUserFile.
- **Use-cases before architecture**: pin moments/questions/actions and let Scott
  react to prototypes before any runtime/data-model questions. He corrected this
  once; don't reoffend.
- Delegation pattern that worked: Fable writes judgment (briefs, data stories,
  contract shells, spec text); Sonnet workers (explicit model+effort on every
  dispatch) build D3/HTML mechanics; Fable verifies headlessly via playwright
  (file:// is blocked — serve via scratch `python3 -m http.server`, kill after).

## Decisions already made (do not relitigate)

1. **Batch** (approved): F0 shared foundations + V1 PR-shape + V2 work-DAG + V3
   codebase evolution. One grouped spec covering all. Readiness labels stamped on
   continuation beads at spec merge. At spec-PR merge: mint continuations under
   the still-open epic, release any claim, stamp labels — in that order.
2. **Runtime architecture (F0 load-bearing decision, user-approved):
   shared-canvas hybrid** — deliverables are self-contained HTML artifacts
   (explain-diff convention); when generated/opened inside a live session, a
   lightweight loop (events-file / notes-export pattern) makes them interactive
   with the agent. The session IS the agent; no dedicated backend service.
3. **Use cases selected** (browser card exercise + caveats):
   - V1: 60-second briefing, blast-radius interrogation, merge-gate decision
     support, morning fleet triage. Multi-axis heat: change complexity ×
     load-bearing (structural centrality) × consequence class — kept as separate
     dials (user's "are load-bearing and risky the same?" hypothesis: related
     cousins, not twins; weight sliders let him feel it).
   - V2: plan comprehension, execution progression, **multi-plan overlay** (several
     speculative plans plotted together against the codebase: cross-plan
     dependencies, touch points, conflicts — Scott's addition, judged the thickest
     remaining unknown). What-if dialog (uc6) and scope negotiation (uc8) were
     NOT selected as primary; pattern mining (uc11) dropped.
   - V3: directional retrospective + context recovery, reframed **topical**: pick a
     concept ("PR review"), trace thought→plan→implementation through history to
     now, connected forward to planned work / future designs (bridges into V2).
4. **V1 prototype verdicts** (3 reaction rounds, detail in `findings.md`):
   Estate treemap = strong keep (collapse-reflow, hierarchical zoom, worst-offender
   roll-up all validated). Attention ledger = strong keep (review-budget bar,
   ranked reading order, drill panel). Constellation = promising, needs multi-PR
   experience to judge utility (spec: evaluation criterion, not build item).
   Impact sonar = retired as top-level; survives as per-file drill-down concept.
5. **15 design principles** extracted in `findings.md` — treat them as spec
   requirements (attention bar for narrative content; centrality-blindness to new
   load-bearing code; layout reflows around attention; view-module container
   hygiene; deterministic force layouts + legends; luminance-picked labels; etc.)

## State

- V1 prototype: `prototype/pr-shape-proto-v3.html` (self-contained; open it).
  Sources + regen scripts alongside; scratch originals under
  `.superpowers/brainstorm/proto-v1/` (gitignored, may be wiped).
- Bead: epic `agents-config-yf2ov.2` is OPEN (unclaimed), has NO children yet —
  by design: children get minted from the spec's Continuations at merge.
  Progress notes appended on the bead. Claim it (`bd update --claim`) when
  actively working it.
- Memories exist for the process lessons (use-cases-first, no-fragile-infra,
  subagent right-sizing) — they'll load automatically in-project.

## Next actions (in order)

1. **V2 brainstorm with Scott** — focus the multi-plan overlay use case: what
   does "several speculative plans plotted against the codebase" look like?
   Candidate data sources: beads DAG (`bd list/dep`), `docs/specs/*` +
   `docs/plans/*` (planned-but-unstarted work), graphify graph for the codebase
   substrate. Prototype-first: build reaction mockups (Sonnet workers, same
   pattern), one question at a time. Likely shared bones with V1: the scene =
   codebase graph + overlays; plans are *speculative overlays* where the PR was a
   *concrete* one — pressure-test that unification in the brainstorm.
2. **V3 brainstorm** (lighter): topical-evolution thread — likely rides V2's
   overlay machinery pointed backward in time (git history) plus forward
   (plans). Validate with 1-2 mockups, not a full prototype, unless Scott asks.
3. **Write the grouped spec** — `docs/specs/2026-MM-DD-visualization-suite-design.md`
   following the local dated-spec pattern: F0 shared foundations (scene contract,
   shared-canvas runtime, heat model, drill/annotation pattern) + one section per
   visualization + evaluation criteria + `## Continuations` naming each child
   bead to mint under the epic (with ACs). Then: brainstorming-skill user review
   gate → completion gate → PR → at merge: mint continuations, stamp readiness
   labels (approved), release claim.

## Open questions to carry into the V2 brainstorm

- Multi-plan conflict semantics: what counts as a "conflict" (same file? same
  subsystem? same bead dependency chain?) and how is it scored/shown?
- Plan footprint extraction: how does a spec/plan doc map to a speculative
  codebase footprint (named files? named modules? agent-inferred)?
- V2 progression view: live update source (beads status polling?) vs regenerated
  artifact per morning-triage moment.
- Whether V1's weight-slider semantics (normalized weighted average) need an
  in-UI explanation layer (principle #2) — carry into F0 spec text.
