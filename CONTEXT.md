# CONTEXT — PDLC Domain Glossary

> This file is a **glossary**, not a spec or scratch pad. Every term is
> deliberately implementation-agnostic. Architecture and tooling decisions
> live elsewhere (specs, ADRs, code).

## Objective

The unified primitive the Orchestrator tracks. An Objective is any unit of
intent the PDLC drives through its FSM lifecycle — from `CANDIDATE_UOW`
through to a terminal lifecycle stage. Every Objective enters the
lifecycle at `CANDIDATE_UOW` (the universal entry point per Law L6).
Idea-stage entities are a **distinct primitive**, NOT Objectives —
see the `Idea` entry below.

The same Objective wears different names at different lifecycle stages;
the entity is one, the names are stage-specific:

- **Stage 3** — the Objective is a *Candidate UoW* in the Design
  Workspace, carrying a Draft Spec. This is the universal entry point.
- **Stage 4** — the Objective is *Agent-Worthy* (Spec signoff received).
- **Stage 5** — the Objective enters Decomposition; the type-stamp
  (Executable vs Container) is assigned.
- **Stages 6 / 6′** — the Objective is an *Agent-Ready Executable* (queued
  for execution) or a *Decomposed Container* (passive aggregator).
- **Stages 7–10C** — the Objective traverses the Execution Pipeline.
- **Terminal** — the Objective is *Merged*, *Killed*, or *Parked* (held
  in *Library* with a blocking dep awaiting resolution).

Every Objective carries:

- A unique identifier.
- An optional parent (for decomposition hierarchies).
- A set of children (populated when the Objective is stamped Container at
  stage 5).
- A lifecycle stage (see the wgclw.2 Orchestrator Core spec's Lifecycle
  Stage Constants table).
- A lifecycle status projected onto the work-tracker
  (open / in_progress / closed / blocked / deferred).
- Optional provenance backreferences (`originating_idea_id`,
  `decomposition_of`, `discovered_from`, `autopsy_route`) — each
  nullable; not every Objective has every form of provenance.
  `originating_idea_id`, if set, points back into the Holding Place's
  Idea record from which this Objective was promoted.

A Unit of Work (UoW) is the conversational name for an Objective at
stage 3 and beyond. A Container is a UoW stamped Container at stage 5.
An Idea is **NOT** an Objective — it is a distinct primitive (see
below). Promotion from Idea to Objective is the explicit handoff via
the Holding-Place service.

## Idea

A raw thought worth preserving but not yet committed to development. Has not
been designed, decomposed, or validated. May be vague. May overlap with other
Ideas. May be wrong. Survives in the system long enough to be revisited.

An Idea is a **distinct primitive**, NOT an Objective. Ideas live in the
Holding Place under their own lifecycle (Capture → Groom → Shape → Promote
or Kill). The orchestrator does not drive Idea lifecycle; the Holding-Place
service does. When an Idea is *promoted* into an Objective, the Holding
Place calls `WorkTracker.create_objective(..., provenance.originating_idea_id=<idea_id>)`
and the resulting Objective enters the FSM at `CANDIDATE_UOW` like any
other Objective. The Idea record stays in the Holding Place as the
provenance source.

Distinguished from:

- **Spec** (later in the lifecycle) — a designed, reviewed artefact ready to
  drive execution.
- **Objective** — a separate primitive that the Orchestrator tracks through
  its FSM. Ideas are promoted into Objectives; they are not the same entity.
- **Unit of Work** (later) — an executable, thin-sliced, machine-verifiable
  scope; the conversational name for an Objective at stage 3 and beyond.

## Capture

The act of transferring an Idea from speech or typing into persistent storage
with minimum interrupt to the work in flight. Capture is **one-shot and
non-interrogative** — the agent does not probe, clarify, or brainstorm during
Capture. Capture preserves the originator's verbatim phrasing.

## Provenance Backreference

Auto-attached metadata recording what-was-being-done at the moment of Capture
(file, topic, or work-in-flight identifier; timestamp). Exists to make
resurrection of the Idea tractable later — so future-readers can re-hydrate
the originator's mental state without further input.

## Holding Place (working name: Icebox)

The persistent store where Captured Ideas — at any pre-Spec growth stage —
sleep until acted on. Holds `Idea` records (the distinct primitive); does
**not** hold Objectives, Candidate UoWs, or anything further along. Entries
are **pull-only by default** — nothing surfaces them automatically except
the Grooming Nag (below).

The Holding Place is a **peer service**, NOT owned by the Orchestrator.
The Orchestrator's only call into the Holding Place is
`promote(idea_id) → objective_id`; the orchestrator does NOT `tick` the
Holding Place. Capture, Grooming, Bucket assignment, Killed-without-Spec,
and resurrection are all HoldingPlace-CLI commands. See the wgclw.2
Orchestrator Core spec's "Holding Place handoff" section for the contract.

## Grooming

An intentional, human-initiated triage ceremony, distinct from the
"what's next to work on" pull. During Grooming, every Idea in the Holding
Place is reviewed and assigned (or re-assigned) to a Bucket. Grooming is
where Ideas are promoted toward design, demoted to longer-term parking, or
declared dead.

Grooming is **not** brainstorming. Brainstorming explores one Idea in depth;
Grooming triages the whole backlog at low resolution.

## Bucket

The disposition of an Idea after Grooming. **Bucket is an `Idea`
property only** — there is no equivalent on Objective. (Per the
CA-8 primitive split: stages 1–2 are Idea-only territory; Objectives
have no Bucket field.) The live buckets are:

- **Now** — ready to be brainstormed in the near term; expected to be picked
  up before the next Grooming pass.
- **Next** — known-valuable but not yet prioritised for the current horizon.
- **Later** — recognised as potentially valuable, no current commitment.
- **Library** — kept as inspiration or reference, with no expectation of
  becoming work. Stays searchable; never re-surfaces during Grooming unless
  the originator explicitly summons it.

A separate terminal disposition exists:

- **Killed** — verdict-of-record that this Idea is not worth pursuing. Stays
  in the underlying store; nothing is deleted. The Killed *state* hides the
  Idea from the living view — it does not appear in Grooming, Holding Place
  surfacing, or work-pull. Carries a mandatory one-line **Epitaph** (the
  cause-of-death) and the timestamp/agent of the killing. Resurrection is
  legal but explicit: the originator must summon a Killed Idea by name,
  which transitions it back to its prior bucket (typically *Library* or
  *Later*), and the Epitaph is preserved as historical record.

## Last-Groomed Timestamp

A per-system (or per-Holding-Place) timestamp recording when the most recent
Grooming session completed. Used as the input to the Grooming Nag.

## Grooming Nag

A deterministic, threshold-driven prompt that piggybacks on the "what's next
to work on" pull. If `now - last_groomed > threshold`, the work-pull surface
prepends a single dismissible message advising that the Holding Place is
overdue for triage. The nag is mechanical (pure timestamp arithmetic — no LLM
judgment) and self-silences once Grooming completes.

---

## Shaped Idea

A `Idea` record that has been touched by one or more *light* brainstorm
passes (typically during Grooming). Carries a one-paragraph
what-why-rough-success statement in addition to the original verbatim
quote and provenance. Still pre-Spec; still lives in the Holding Place.

A Shaped Idea remains an `Idea` (the distinct primitive — NOT an
Objective). The "Shaped" qualifier captures the developmental move
*"pick it up in Grooming, shape it a little, put it back not-yet-ready"* —
without it, the Holding Place would falsely require every entity to be
a raw Idea or a fully-brainstormed Candidate UoW with nothing in
between. The transition from Shaped Idea to Candidate UoW is the
**Promote** operation (Holding-Place service → WorkTracker), which
creates a NEW Objective at `CANDIDATE_UOW`.

## Candidate UoW

A Unit of Work that has been fully brainstormed into a Draft Spec but has
**not yet** received a type-stamp (Epic / Story / Task / Chore / etc.). The
type-stamp is an *output* of the Sizing Gate downstream, not an input. Lives
in the Design Workspace, never in the Holding Place. A Candidate UoW is an
*Objective* at `CANDIDATE_UOW` — the first lifecycle stage of an Objective;
promoted from an Idea (via the Holding-Place service) or created directly
by a human / formula / Autopsy route. **Every Objective enters the lifecycle
at `CANDIDATE_UOW`** (the universal entry point per Law L6); see the
wgclw.2 Orchestrator Core spec for the universal-entry-point discipline.

## Spec

The design artefact carried by a Candidate UoW. Comprises:

- **Functional contract** — a set of Atomic ATs.
- **Non-functional contract** — the project's standard DoD template (tests
  pass, coverage thresholds, lint clean, etc.) plus any UoW-specific NFRs.
- **Human signoff** — an auditable approval that the Spec is well-formed
  (i.e., that the Atomic-AT gate has been satisfied either by clean linting
  or by recorded overrides, and that the DoD is appropriate). The signoff
  is the *only* non-mechanical authority permitted at this gate.

## Atomic AT (Acceptance Test)

An AT that is irreducible — it cannot be legitimately split into more than
one AT without sacrificing test quality. Atomic-AT-ness is a precondition
for a Spec to leave stage 3. Enforced by a hybrid gate: a deterministic
linter flags suspect ATs (conjunctions, multi-verb assertions, list
assertions); a human either rewrites or records a one-line override.

## Decomposition

A mandatory pipeline stage that *every* Agent-Worthy Candidate UoW passes
through. Runs the Sizing Gate, emits one of two outcomes, and — in the
Oversized branch — authors a Decomposition Plan. Decomposition is where the
type-stamp (Executable vs Container) is *assigned*, never before.

## Test-Author Agent (persona)

Operates exclusively in the Execution Pipeline's Test-Authoring state. Takes
the Agent-Ready UoW's atomic ATs and produces runnable failing tests. The
*shape* of each test (one skeleton per atomic AT, naming aligned with the
AT identifier) is mechanically scaffolded by the orchestrator; the
Test-Author Agent *fleshes out* fixtures, mocks, and assertion details.

**Authority boundaries:**

- **Test files**: full authority — writes assertions, fixtures, mocks,
  setup/teardown.
- **Production paths**: limited to **signature-only stubs** required for
  tests to compile (or import, in dynamic languages). Function/class
  signatures only; no logic in bodies. A mechanical post-commit AST check
  verifies signature-only-ness — any logic in a stub fails the Red Gate
  and counts as a strike against the Test-Author.
- **No other production code modification** is permitted.

The Test-Author exists to deny the Implementer a back door around its own
tests (the separation-of-authorities discipline).

## Implementer Agent (persona)

Operates exclusively in the Execution Pipeline's Implementation state.
Receives a worktree in a red state — failing tests for the UoW's atomic
ATs — and writes the minimum production code required to turn red to
green.

**Authority boundaries:**

- **Production paths**: full authority — including filling in the
  signature-only stubs the Test-Author left behind.
- **Test files**: **read-only**. The Implementer cannot modify, delete, or
  weaken tests authored by the Test-Author. Any commit touching test paths
  fails the Green Gate and counts as a strike.
- **No new production paths outside the Spec's declared scope** without
  escalation.

The Implementer exists to deny itself a back door around its own tests.

## Green Gate

The mechanical exit gate of the Implementation state. Composite check; all
components must pass on the same commit:

1. **All tests pass** — new tests (from this UoW's atomic ATs) and every
   prior test in the suite. No regression tolerated.
2. **Typecheck clean** (where the project has typecheck).
3. **Build succeeds**.
4. **Lint clean** per the project's lint config.
5. **Coverage threshold met** — threshold read from the UoW's DoD (which
   inherits project default; may be overridden upward).

Green Gate is pure orchestrator code — no LLM judgment. Each component is
individually diagnosable on failure. Failure counts as a strike against
the Implementer under the 3-Strike Circuit Breaker.

## Red Gate

The mechanical exit gate of the Test-Authoring state. Composite check, all
three must pass:

1. **Tests compile** (or are importable / discoverable, language-dependent).
2. **Tests run** to a verdict via the project's standard test runner.
3. **Tests for this UoW's atomic ATs fail** — at least one, ideally all, of
   the new tests reports failure. Passing tests at this stage indicate no
   new behaviour to implement, which is a Red Gate failure in its own right.

Red Gate is pure orchestrator code — no LLM involved. A Red Gate failure
counts as a strike against the Test-Author Agent under the 3-Strike Circuit
Breaker.

## Review (state)

The Execution Pipeline state immediately after Implementation's Green Gate.
Adversarial cross-review by multiple Reviewer Agents in parallel, each
scoped to a domain (code quality, security, performance, API contract,
documentation, …). The exact list is project-configured.

Loop semantics:

1. All Reviewer Agents run in parallel against the worktree.
2. Each emits zero or more Findings (three classes — see below).
3. **Mechanical Findings** route to the Implementer's fix-loop; the
   Implementer must fix or escalate to human (HEP). Silent rejection is
   forbidden.
4. Reviewers re-run after each Implementer fix-commit.
5. Review exits when a complete round produces zero Mechanical Findings.
   Advisory and Proposed Rule queues empty to the Holding Place /
   project-rule queue at merge time.

3-Strike Circuit Breaker bounds the loop; strike 3 routes to Autopsy.

## Reviewer Agent (persona, configurable list)

Specialises in one domain. Each project chooses its active Reviewer
Agents and equips each with a domain-specific Reviewer Toolbox.

**Authority boundaries:**

- May add new tests, lint rules, AST pattern detectors, microbenchmarks,
  mutation tests, property tests, profiler-comparison harnesses.
- May **not** modify existing production paths.
- May **not** modify existing tests authored by the Test-Author.
- May **not** emit Mechanical Findings without a corresponding mechanical
  artefact.

## Reviewer Toolbox

The mechanical instruments equipping a Reviewer Agent, per-domain and
project-configurable. Indicative examples:

- **Code Quality**: AST-similarity duplication detectors (jscpd, pmd-cpd,
  semgrep), cyclomatic / cognitive complexity metrics, function-length,
  file-length, nesting depth, coupling metrics (fan-in / fan-out).
- **Security**: SAST runners, dependency CVE scanners, secret detectors,
  AST packs for known vulnerability classes.
- **Performance**: microbenchmarks-as-ATs, profiler diffs against a
  baseline, AST detectors for known anti-patterns (N+1, allocation in
  hot path, sync-in-async, etc.).
- **API Contract**: schema / snapshot diff, breaking-change detectors.

## Finding (three classes)

### Mechanical Finding (blocking)

A concrete machine-verifiable artefact — a failing test, a triggered lint
rule, a metric over threshold, a static-analysis violation. Gates the
Review state. Routes to the Implementer's fix loop. Must be cleared
before Review exits.

### Advisory Finding (non-blocking)

A judgment-class observation with no mechanical artefact. Does **not**
gate Review. Is **not** shown to the Implementer during the fix loop
(prevents vibe-pressure). At merge time, each Advisory Finding is
Captured as an Idea in the Holding Place — with provenance pointing to
the Reviewer, the UoW, and the reviewed commit. Re-enters the design
pipeline as a normal Captured Idea, triaged at the next Grooming.

### Proposed Rule (non-blocking on this PR; gates future)

A Reviewer-drafted candidate lint rule, AST detector, or test pattern,
accompanied by a demonstration that it triggers on the current case.
Captured as an Idea with type-hint *rule* at merge time. Human approval
during Grooming promotes it into the project's lint / test corpus, where
it gates all future PRs. The mechanism by which the project's mechanical
vocabulary *grows* over time.

## Integration (stage)

The Execution Pipeline stage that carries a UoW from "Review passed
locally" to "Merged on origin." Internally sequenced as three stages:

### Stage A — PR Mechanical Validation

Always present. PR is opened against the merge target; CI re-runs the
Green Gate composite plus the project's mechanical Reviewer Toolboxes;
external automated reviewers (Copilot-class) participate under the same
discipline as internal Reviewers — Mechanical Findings block, Advisory
Findings capture as Ideas at merge, Proposed Rules queue for the
project-rule queue.

**Failure routing**: Mechanical Findings → Implementer fix-loop with
3-Strike Circuit Breaker → Autopsy on strike 3.

### Stage B — Human Approval Hold (conditional)

Inserted only when the UoW's `approval_required` flag is `true`. Emits a
HEP-style `human`-tagged work item that gates C until the human acts. No
auto-escalation around human silence — that defeats the configuration's
purpose.

**Failure routing**: aging-nag. After a project-configured threshold of
human inaction, the work-pull surface prepends a dismissible reminder
("PR awaiting your approval for X days"). The B stage stays open
indefinitely; only the human can close it.

### Stage C — Merge + Cleanup

Always present. Executes the merge (squash / ff / rebase per project
config), walks the parent chain (closes Container if all children closed),
removes worktree and branch, closes the UoW.

**Failure routing**: merge conflict / branch protection / push rejection
are *infrastructure* failures — not agent-vs-gate failures — so they route
to retry-or-human-escalate via HEP, **not** to Autopsy. Autopsy is for
agent-cognition failures; C's failures are world-state failures.

## `approval_required`

A per-UoW boolean configuration. Default `false`. When `true`, Integration
inserts Stage B between A and C.

## Autopsy (state)

The destination of any 3-Strike Circuit Breaker firing within the
Execution Pipeline (Red Gate, Green Gate, Review's fix-loop, or
Integration Stage A's fix-loop). Autopsy diagnoses; it does not repair.

**On entry:**

- The Execution Pipeline halts.
- The branch and worktree are **frozen** — no agent is permitted further
  work against them. They are **not** burned at this point. They are
  *evidence* and must remain available for RCA interrogation.
- Strike history, gate logs, and the current commit SHA chain are
  preserved as forensic artefacts.

**During Autopsy:**

- The **Specification RCA Agent** analyses the spec for logical
  contradictions, missing context, untestable criteria, ambiguous ATs,
  mid-pipeline scope creep.
- The **Architecture Health RCA Agent** analyses the worktree and the
  codebase context at fault sites for tight coupling, legacy debt, state
  contamination, layering violations, dependency-direction inversions.
- Both run in parallel. Each emits a **structured machine-readable
  report** (YAML / JSON) with named root-cause categories, citations
  into spec / code / gate logs, and recommended remediations drawn from
  a **closed taxonomy** (see Autopsy Resolution Routes). No prose
  narratives.
- The human may **interactively interrogate** either RCA agent further —
  ask follow-up questions, request deeper analysis of specific findings,
  request comparisons against prior incidents. RCA agents are not
  one-shot reporters; they remain available for the duration of the
  autopsy.

**On exit (human picks a route from the closed taxonomy):**

- The chosen route is dispatched by the orchestrator.
- **At this point**, the branch and worktree are burned and the autopsy
  bead is closed with the chosen remediation recorded.

## Autopsy Resolution Routes (closed taxonomy)

The human's choice from a fixed set, after consulting the RCA reports:

- **(i) Back to stage 3 — Re-brainstorm.** Spec RCA found a flaw in the
  functional contract; UoW returns to Candidate UoW status for repair.
- **(ii) Back to stage 5 — Re-decompose.** Decomposition was unviable;
  the Decomposition Plan is reopened.
- **(iii) Killed.** UoW is not worth pursuing; standard Killed
  semantics (Epitaph required, resurrection legal).
- **(iv) File-as-Architectural-Debt + Park.** Architecture RCA found a
  structural blocker; a new Idea is Captured for the debt with provenance
  pointing to this Autopsy; the UoW returns to *Library* with a dep on
  the new debt Idea. When the debt clears, the UoW becomes eligible again.
- **(v) Escalate-Tooling.** Evidence shows the failure was tooling
  (orchestrator bug, agent harness bug, CI infrastructure), not code or
  spec; a tooling-bug Idea is Captured; this UoW returns to *Now* with a
  tooling-blocker dep.

## RCA Agent (persona, dual instance)

Two instances:

- **Specification RCA Agent** — input: the UoW's full Spec, the strike
  history, the gate-failure type, the worktree state. Output:
  structured machine-readable diagnosis scoped to spec quality.
- **Architecture Health RCA Agent** — input: the worktree at strike-3,
  the codebase context at fault sites, the strike history. Output:
  structured machine-readable diagnosis scoped to architecture and
  state-contamination concerns.

Both are read-only — they do not modify code, tests, or spec. They
remain interactively available for the duration of the autopsy.

## Decomposition Architect (persona)

Operates exclusively at stage 5 in the Oversized branch. **Does not probe
requirements** — that is the Design Interrogator's job at stage 3. **Does
not write production code** — that is the implementer's job in the
Execution Pipeline. Its single output is the Decomposition Plan.

**Optimisation function:**

- **Primary**: minimise total Scaffold + Cleanup AT churn across the
  Container's lifetime.
- **Secondary preference**: among slicings of comparable primary cost,
  prefer those where more children demonstrate user-visible value (the
  tracer-bullet aesthetic). This is a *preference*, not a constraint —
  scaffold-only slices remain legal when warranted.
- **Container-level "working software" commitments** are honoured via
  Container-Level ATs, not by forcing every child to be independently
  shippable-to-users.

**Handoff discipline**: if a flaw in the functional contract emerges
mid-decomposition (an atomic AT that resists slicing, a missing AT a slice
demands), the Architect kicks the UoW back to stage 3 with a specific
complaint. It does **not** silently patch the Spec.

## Sizing Gate

The deterministic, pure-function size check inside Decomposition. Consumes
a *composite mechanical score* of: Atomic-AT count, file-touch estimate,
subsystem-crossing count, dependency fan-out, and presence of NFR
escalations (perf, security, compliance). Weights and thresholds are
project-configured. Returns one of two outcomes:

- **Sized** — score below threshold; UoW is stamped Executable
  (Story / Task / Chore / Bug / etc.) and advances toward Agent-Ready.
- **Oversized** — score above threshold; UoW is stamped Container
  (Epic / Feature / etc.); a Decomposition Plan must be authored.

The Sizing Gate is mechanical by law — no LLM judgment.

## Decomposition Plan

The artefact emitted by Decomposition in the Oversized branch. Three layers:

- **Children** — named candidate slices, each with parent-as-provenance and
  allocated atomic ATs.
- **Assembly Graph** — DAG of "comes-before" edges between children. Must
  be acyclic. Constrains Grooming priority *mechanically* — a child cannot
  be promoted to *Now* ahead of its predecessors. Edits to the order
  happen by editing the DAG, not by violating it.
- **Integration annotations per child** — the slice's role in the eventual
  whole, plus any decomposition-time-discoverable Scaffold / Cleanup ATs.

**Exit criteria for the Decomposition state (Oversized branch):**

1. Every parent atomic AT is allocated — either to a Child (Child-Level AT)
   or to the Container itself (Container-Level AT). No orphan ATs.
2. Every child has: a name, parent-as-provenance, allocated atomic ATs, an
   integration-role annotation.
3. The Assembly Graph is acyclic.
4. Scaffold / Cleanup ATs that are foreseeable at decomposition time are
   attached; the rest is deferred to child brainstorms with an explicit
   "to be discovered" marker.
5. Human signoff on the Decomposition Plan.

## Child-Level AT vs Container-Level AT

A testability-scope distinction. A **Child-Level AT** is testable on a
single slice. A **Container-Level AT** is testable only across the
assembled whole — it lives on the Container and validates at aggregation
time. Cross-cutting ATs ("the system works end-to-end") are
Container-Level.

## Scaffold AT

A *temporary* AT describing harness, stub, mock, or demo behaviour required
for a slice to ship in isolation. Annotated with the Cleanup AT (or
child-slice) that will retire it. A Scaffold AT that survives into the
Container's final state is a leak — the Container does **not** close until
every Scaffold AT has been retired by its paired Cleanup AT.

## Cleanup AT

An AT in a *later* child (per the Assembly Graph) that explicitly asserts
the *removal* of a prior child's Scaffold AT. Scaffold and Cleanup ATs
travel as pairs across the Assembly Graph; the pair is the lifecycle unit.

## Container Closure

A Container (stage 6′) closes when **all** of:

1. Every child is closed.
2. Every Container-Level AT passes.
3. No Scaffold AT persists (all paired with successful Cleanup ATs).

Failure of any condition keeps the Container open.

## Agent-Worthy

A property of a Candidate UoW whose Spec is complete. The Agent-Worthy gate
requires **all** of:

1. Atomic-AT lint clean (or every flag has a one-line recorded override).
2. DoD applied (project-standard template, plus any UoW-specific NFRs).
3. **No outstanding *blocker-class* question** remains — judged by either
   the Design Interrogator or the human.
4. Human signoff captured.

Agent-Worthy is the precondition for entering Decomposition. Not yet a
guarantee of Agent-Ready.

## Blocker-Class Question (rubric deferred)

A question whose resolution is required before a Candidate UoW may exit
stage 3. The full rubric distinguishing blocker-class from nice-to-have
questions is a **deferred sub-design** — to be developed alongside the
Design Interrogator's implementation. For the FSM design pass, it suffices
that *some* such rubric exists and that both the Design Interrogator and
the human have authority to flag a question as blocker-class.

## Agent-Ready

A property of an Executable UoW (stage 6) that has passed both Agent-Worthy
and the Sizing Gate. Only Executables are ever Agent-Ready; Containers are
never Agent-Ready — they are *Decomposed* and aggregate their children's
outcomes.

## Design Workspace

The environment that holds Candidate UoWs (stage 3) and Agent-Worthy
Candidate UoWs (stage 4) and Decomposition (stage 5). Distinct from the
Holding Place (which holds only pre-Spec Ideas) and from the Execution
Pipeline (which holds Agent-Ready UoWs).

## Terminal Lifecycle States

The three terminal states an Objective reaches at the end of the PDLC
lifecycle. Each maps to a Lifecycle Stage Constant defined in the
wgclw.2 Orchestrator Core spec's Lifecycle Stage Constants table.

### Merged

Constant: `MERGED`. The happy terminal. The Objective's PR has been
merged into the integration target, all Container Closure conditions
that depend on it are eligible to roll up, and the Orchestrator removes
its worktree and branch. The work item closes in the tracker; the
transition log retains the complete audit history.

### Killed

Constant: `KILLED`. Verdict-of-record that this Objective will not be
completed. Stays in the underlying store; nothing is deleted. The
Killed *state* hides the Objective from the living view — it does not
appear in Grooming, Holding Place surfacing, work-pull, or in-flight
session inventories. Carries a mandatory one-line **Epitaph** (the
cause-of-death) and the timestamp / actor of the killing. Resurrection
is legal but explicit: the originator must summon a Killed Objective
by name, which transitions it back to a pre-terminal lifecycle stage
appropriate to its previous state, and the Epitaph is preserved as
historical record.

`KILLED` applies at any Objective lifecycle stage from `CANDIDATE_UOW`
through the Execution Pipeline. Ideas (the separate primitive in the
Holding Place) have their own Killed concept — a Bucket disposition
discussed under Bucket above — which is a related-but-distinct
mechanism that lives in the Holding-Place service and predates any
Objective creation. Both honour the Epitaph + resurrection rules.

### Parked

Constant: `PARKED`. Terminal-ish: the Objective is held in *Library*
with a blocking dep awaiting resolution (typically a follow-up tooling
fix, environment change, or external prerequisite). Parked is distinct
from Killed in that there is an expected unblocking event; it is
distinct from Library-bucketed Ideas in that the Parking carries an
explicit blocking dep, not just a "maybe someday" status. When the
blocker resolves, the Orchestrator surfaces the Parked Objective for
human review — it does not auto-resume execution. Used by Autopsy
Resolution Routes (iv) and (v).

### NeedsReconcile

**Inspection flag, NOT a terminal lifecycle stage.** Set on an
Objective when the orchestrator's reconcile step cannot determine the
correct terminal mapping (e.g. tracker `terminal_disposition` field
absent or ambiguous, identity-fingerprint mismatch, version-fingerprint
divergence). Surfaces on `pdlc health` and `pdlc objectives show`
for human disposition.

`NeedsReconcile` is intentionally **not** a `Killed` mapping (that
would silently destroy valid work — Codex showstopper C-1.8). The
orchestrator holds the Objective in its current pre-terminal lifecycle
stage and waits for human input. The terminal mapping happens only
after the operator picks the correct `terminal_disposition` value
(`killed` / `manually-merged` / `duplicate` / `superseded` /
`abandoned`).

---

## Forward-referenced terms (mentioned but not yet defined here)

- **Execution Pipeline stages** — Red-Tests, Implementation, Review, Merge,
  Autopsy. Defined in later glossary passes.
- **Dreaming Process** — a candidate future background capability that
  strengthens edges between Ideas and existing work items. Captured in
  `AGENTS.md` for later development. Would feed Grooming with surfaced
  connections; not load-bearing on the current state-machine narrative.
