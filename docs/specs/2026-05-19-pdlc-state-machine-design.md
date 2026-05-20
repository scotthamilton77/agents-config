# PDLC State Machine Design

**Source bead**: `agents-config-wgclw.1`
**Parent milestone**: `agents-config-wgclw` (M0 — Discipline-layer rearchitecture)
**Date**: 2026-05-19
**Status**: Design complete, pending implementation planning

## Purpose

This spec defines the deterministic Product Development Life Cycle (PDLC)
state machine for an AI Agent Orchestrator. It maps the **exact**
non-negotiable states a Unit of Work passes through from "Raw Idea" to
"Merged," and for every state it explicitly defines: name and purpose,
operating persona (or Orchestrator / Human), mechanical exit gate, and
failure routing.

This is an **FSM-conceptual** specification. Orchestrator implementation,
worktree management, agent dispatch mechanics, and work-tracker schema are
explicitly out of scope and delegated to downstream implementation specs.

## Immutable Architectural Laws (recap)

1. **The Orchestrator is Code.** Built in Python/Go. Agents do not decide
   what task to do next; the Orchestrator tells them.
2. **Mechanical Gates Only.** No state transition is authorized by an LLM
   "vibe check." Transitions are gated by deterministic proofs (test
   runner exit codes, lint runs, metric thresholds, or explicit
   human-auditable approval).
3. **WMS Decoupling.** Execution agents have zero awareness of the Work
   Management System (Beads, Jira, GitHub, etc.). The Orchestrator manages
   all state persistence.
4. **3-Strike Circuit Breaker.** Any agent gets a maximum of three
   attempts to pass a mechanical gate. On strike three, the pipeline
   halts, the branch is frozen as evidence, and the state routes to
   Autopsy.
5. **No Judgmental Acceptance Tests.** "Agent-Ready" means the Unit of
   Work is backed by atomic, machine-verifiable ATs.

## Anti-Patterns Explicitly Prevented

- **The AI Debate Club.** No state requires two probabilistic models to
  reach consensus to advance. Adversarial reviewers emit *additive
  mechanical findings*; agreement is not the gate.
- **Garbage Amplified.** Large or ambiguous specifications cannot enter
  execution. The Sizing Gate and Atomic-AT gate jointly enforce this.
- **Waterlogged Rocks.** Agents never inherit dirty git branches. On
  3-strike, the branch is frozen as evidence; new attempts proceed from a
  clean base after Autopsy's chosen remediation route dispatches.
- **Bullet-Point Review Hell.** Autopsy emits **structured
  machine-readable** RCA reports, not prose narratives.

## Vocabulary

The canonical glossary lives in `CONTEXT.md` at the project root. This
spec refers to terms defined there: *Idea, Shaped Idea, Capture,
Provenance Backreference, Holding Place, Grooming, Bucket, Last-Groomed
Timestamp, Grooming Nag, Candidate UoW, Spec, Atomic AT, Sizing Gate,
Agent-Worthy, Agent-Ready, Decomposition, Decomposition Plan, Assembly
Graph, Scaffold AT, Cleanup AT, Child-Level AT, Container-Level AT,
Container Closure, Test-Author Agent, Implementer Agent, Reviewer Agent,
Reviewer Toolbox, Finding, Red Gate, Green Gate, Review, Integration,
approval_required, Autopsy, Autopsy Resolution Routes, RCA Agent,
Killed, Epitaph, Blocker-Class Question, Design Interrogator,
Decomposition Architect.*

This spec does not redefine those terms; it composes them into a state
machine.

---

## Overview

```
HOLDING PLACE                    DESIGN WORKSPACE                 EXECUTION PIPELINE                 TERMINAL
═════════════                    ════════════════                 ══════════════════                 ════════
  Idea ──┐                       Candidate UoW ──┐                Agent-Ready ──┐
         │  ┌───── Grooming ─────►  (Draft Spec) │                              │
  Shaped │  │                                    │                              ▼
  Idea ──┘  │                  Agent-Worthy ◄────┘                  Test-Authoring
            │                       │                                           │
            │                       ▼                                           ▼ (Red Gate)
            │                  Decomposition                            Implementation
            │                    │      │                                       │
            │              ┌─────┘      └──────┐                                ▼ (Green Gate)
            │              ▼                   ▼                            Review
            │           Sized               Oversized                           │
            │           (Executable)        (Container)                         ▼ (all Mechanical Findings clear)
            │              │                   │                            Integration
            │              │                   ├─► children re-enter            │
            │              │                   │   Holding Place at stage 2     ├─ A. PR Mechanical Validation
            │              │                   │                                ├─ B. Human Approval Hold (if approval_required)
            │              │                   ▼                                └─ C. Merge + Cleanup
            │              │           Decomposed Container                     │
            │              │           (passive aggregator)                     ▼
            │              │                                                MERGED ◄── happy terminal
            │              ▼
            │           Agent-Ready ──► Execution Pipeline                  Autopsy ◄── 3-Strike from any
            │                                                                 │           agent-vs-gate state
            └─────────────────────────────────────────────────────────────────┤
                                                                              │
                                                                              ▼
                                                                       human picks from
                                                                       closed taxonomy:
                                                                         1. → stage 3 (re-brainstorm)
                                                                         2. → stage 5 (re-decompose)
                                                                         3. → Killed
                                                                         4. → Library + Architectural Debt
                                                                         5. → Now + Tooling Escalation
```

---

## State Specifications

Every state below specifies the four fields the source bead's DoD
demands: **purpose**, **persona** (or Orchestrator/Human), **mechanical
exit gate**, **failure routing**.

### Stage 1 — Idea

| Field | Value |
|---|---|
| **Purpose** | Preserve a raw thought with minimum interrupt to the work in flight. |
| **Persona** | Idea Curator (transcribes only; no probing; no clarifying questions). |
| **Exit gate** | Card persisted with verbatim quote + Provenance Backreference + timestamp. |
| **Failure routing** | Persistence retry. No semantic failure mode at this stage. |

Lives in the Holding Place. Capture is one-shot and non-interrogative.

### Stage 2 — Shaped Idea

| Field | Value |
|---|---|
| **Purpose** | Hold an Idea that has been touched by one or more light brainstorm passes, carrying a one-paragraph what-why-rough-success summary in addition to the original verbatim. Legitimises the "pick it up in Grooming, shape it a little, put it back" UX. |
| **Persona** | Grooming Agent (Reasoned Proposer — proposes bucket assignments and shaping refinements with one-line reasoning; the human confirms or overrides). |
| **Exit gate** | Human pulls the Shaped Idea during Grooming and explicitly initiates a full brainstorm session against it. |
| **Failure routing** | Brainstorm reveals fatal flaw → *Killed* (with Epitaph). Brainstorm yields "not now" → return to stage 2 in *Later* / *Library*. Brainstorm aborts midway without verdict → remains at stage 2 in its current bucket. |

Lives in the Holding Place alongside stage-1 Ideas.

### Stage 3 — Candidate UoW (Draft Spec)

| Field | Value |
|---|---|
| **Purpose** | Produce a complete Draft Spec via full brainstorm: atomic ATs, DoD applied, scope clear, no blocker-class questions outstanding. |
| **Persona** | Design Interrogator (Socratic, breadth-first, completeness-driven; challenges underdefined claims; sharpens terminology; surfaces alternatives). |
| **Exit gate** | **Composite, all must hold**: (1) Atomic-AT lint clean — or every flag has a one-line recorded override; (2) DoD applied (project-standard template + UoW-specific NFRs); (3) no outstanding *blocker-class* question (rubric deferred — see Future Work); (4) human signoff captured. |
| **Failure routing** | Lint flags unresolved → stay at stage 3. Fatal flaw discovered → *Killed*. "Not worth doing now" → return to stage 2 (typically into *Later*). Human declines signoff → stay at stage 3 with feedback. |

Lives in the Design Workspace.

### Stage 4 — Agent-Worthy Candidate UoW

| Field | Value |
|---|---|
| **Purpose** | Transient handoff state — the Spec is signed; advance immediately to Decomposition. |
| **Persona** | Orchestrator (mechanical). |
| **Exit gate** | Auto-advance into Decomposition (stage 5) on signoff. |
| **Failure routing** | N/A — no observable failure mode in this transient state. |

### Stage 5 — Decomposition

Decomposition is mandatory for *every* Agent-Worthy Candidate UoW. The
type-stamp (Executable vs Container) is an *output* of this state, not an
input.

| Field | Value |
|---|---|
| **Purpose** | Run the Sizing Gate; in the Sized branch, stamp Executable and advance. In the Oversized branch, author a Decomposition Plan and stamp Container. |
| **Persona** | **Sizing Gate**: Orchestrator (deterministic pure function). **Decomposition Plan authoring (Oversized branch)**: Decomposition Architect (integration-aware, optimises for minimum total Scaffold + Cleanup AT churn; prefers user-visible value per slice as secondary preference; kicks the UoW back to stage 3 if a functional-contract flaw emerges mid-decomposition). |
| **Exit gate** | **Sized branch**: composite mechanical score below threshold → stamp Executable → advance to stage 6. **Oversized branch**: Decomposition Plan satisfies all five exit criteria (every parent atomic AT allocated, every child has name + provenance + allocated ATs + integration-role annotation, Assembly Graph acyclic, foreseeable Scaffold / Cleanup ATs attached, human signoff on the Plan) → stamp Container, emit N children into the Holding Place at stage 2, advance Container to stage 6′. |
| **Failure routing** | Plan fails any exit criterion → stay at stage 5 with the Decomposition Architect iterating. Human rejects Plan → stay with feedback. Decomposition reveals the parent should not exist → *Killed* (rare — usually caught at stage 3). Decomposition reveals a Spec flaw → return to stage 3 with a specific complaint. |

### Stage 6 — Agent-Ready Executable UoW

| Field | Value |
|---|---|
| **Purpose** | Hold a Sized, stamped-Executable UoW in the Execution Pipeline queue until a worker pulls. |
| **Persona** | Orchestrator (queue). |
| **Exit gate** | Execution Pipeline pulls the UoW → enters Test-Authoring (stage 7). |
| **Failure routing** | N/A — pure queue state. |

### Stage 6′ — Decomposed Container

| Field | Value |
|---|---|
| **Purpose** | Passive aggregator. Holds a Container while its children traverse their own lifecycles. |
| **Persona** | Orchestrator (passive). |
| **Exit gate** | **Container Closure**: all children closed AND all Container-Level ATs pass AND no Scaffold AT persists (every paired Cleanup AT successful). |
| **Failure routing** | Child *Killed* mid-flight → human re-grooms the Decomposition Plan (may adjust scope or accept partial). Container-Level AT fails → blocked until repaired. Scaffold AT leaks past its paired Cleanup → blocked until Cleanup ATs land. |

### Stage 7 — Test-Authoring

| Field | Value |
|---|---|
| **Purpose** | Convert atomic ATs into runnable failing tests. The Orchestrator mechanically scaffolds one test skeleton per atomic AT (naming aligned with the AT identifier); the Test-Author Agent fleshes out fixtures, mocks, and assertion details. |
| **Persona** | Test-Author Agent — authority on test files; signature-only stubs permitted in production paths (mechanically verified via AST check); no other production modification. |
| **Exit gate** | **Red Gate** (composite): (1) tests compile / import / discover; (2) tests run to verdict via project test runner; (3) tests for this UoW's atomic ATs fail. Passing tests at this stage are themselves a Red Gate failure. |
| **Failure routing** | Red Gate fails → strike against Test-Author. 3-Strike → Autopsy. |

### Stage 8 — Implementation

| Field | Value |
|---|---|
| **Purpose** | Write minimum production code to turn red tests green. |
| **Persona** | Implementer Agent — authority on production paths; test files read-only; any commit touching tests fails the Green Gate. |
| **Exit gate** | **Green Gate** (composite, all on the same commit): (1) all tests pass — new + every prior; (2) typecheck clean; (3) build succeeds; (4) lint clean; (5) coverage threshold met (read from UoW's DoD). |
| **Failure routing** | Green Gate fails → strike against Implementer. 3-Strike → Autopsy. |

### Stage 9 — Review

Adversarial cross-review by multiple Reviewer Agents in parallel.
"Adversarial" means *additive mechanical findings from independent
reviewers*, **not** consensus.

| Field | Value |
|---|---|
| **Purpose** | Surface mechanical Findings the Implementer's gates missed: duplication, complexity, performance anti-patterns, security flaws, API contract regressions, etc. Capture judgment-class observations as Advisory Findings (non-blocking) and as Proposed Rules (project-corpus growth). |
| **Persona** | Multiple Reviewer Agents (project-configurable list — *Code Quality*, *Security*, *Performance*, *API Contract*, *Documentation*, …). Each runs in parallel with a domain-specific Reviewer Toolbox. May add tests, lint rules, AST pattern detectors, microbenchmarks, mutation tests, property tests, profiler harnesses. May not modify existing production paths or existing tests. |
| **Exit gate** | A complete round (every active Reviewer has run since the last Implementer commit) produces **zero Mechanical Findings**. Advisory Findings and Proposed Rules do not gate; they queue for emission at merge time. |
| **Failure routing** | Mechanical Finding → Implementer fix-loop; the Implementer either commits a fix or escalates to human via HEP — *silent rejection is forbidden*. Strikes accumulate against the Implementer in this state. 3-Strike → Autopsy. |

**Toolbox examples (indicative):**

- *Code Quality*: AST-similarity duplication detectors (jscpd, pmd-cpd, semgrep duplication packs); cyclomatic / cognitive complexity metrics; function-length, file-length, nesting-depth thresholds; coupling metrics (fan-in / fan-out).
- *Security*: SAST runners; dependency CVE scanners; secret detectors; AST packs for known vulnerability classes.
- *Performance*: microbenchmarks-as-ATs; profiler diffs against a baseline; AST detectors for known anti-patterns (N+1, allocation-in-hot-path, sync-in-async).
- *API Contract*: schema / snapshot diff; breaking-change detectors.

### Stage 10 — Integration

Integration carries a UoW from "Review passed locally" to "Merged on
origin." Internally sequenced as three stages — **A always**, **B
conditional**, **C always**.

#### Stage 10.A — PR Mechanical Validation

| Field | Value |
|---|---|
| **Purpose** | Server-side re-validation. PR opened against the merge target; CI re-runs the Green Gate composite plus the project's mechanical Reviewer Toolboxes; external automated reviewers (Copilot-class) participate under the same discipline as internal Reviewers — Mechanical Findings block, Advisory captures as Ideas at merge, Proposed Rules queue for the project-rule queue. |
| **Persona** | Orchestrator (CI dispatch) + external automated reviewers (under Reviewer Agent discipline). |
| **Exit gate** | All CI checks green AND zero Mechanical Findings from external reviewers in a complete round. |
| **Failure routing** | Mechanical Finding → Implementer fix-loop (the Implementer re-engages briefly to address). 3-Strike → Autopsy. |

#### Stage 10.B — Human Approval Hold (conditional)

Inserted only when the UoW's `approval_required` flag is `true`.

| Field | Value |
|---|---|
| **Purpose** | Hold the PR open and surface a human-tagged work item; the human must explicitly act before merge can proceed. |
| **Persona** | Human. The Orchestrator emits a HEP-style `human`-tagged work item that owns this gate. |
| **Exit gate** | Human acts (approves PR, closes the HEP item with disposition). |
| **Failure routing** | **Aging-nag**. After a project-configured threshold of human inaction, the human's work-pull surface prepends a dismissible reminder ("PR awaiting your approval for X days"). No auto-escalation around human silence — that defeats the configuration's purpose. The B stage stays open indefinitely; only the human can close it. |

#### Stage 10.C — Merge + Cleanup

| Field | Value |
|---|---|
| **Purpose** | Execute the merge per project config (squash / ff / rebase); walk the parent chain (close Container if all children closed); remove worktree and branch; close the UoW. |
| **Persona** | Orchestrator (merge automation). |
| **Exit gate** | Merge committed to origin AND post-merge housekeeping complete AND UoW closed. |
| **Failure routing** | Merge conflict / branch protection / push rejection are *infrastructure* failures — **not** agent-vs-gate failures — so they route to retry-or-human-escalate via HEP, **not** to Autopsy. Autopsy is for agent-cognition failures; C's failures are world-state failures. |

### Stage 11 — Autopsy (failure branch)

Destination of any 3-Strike Circuit Breaker firing from Test-Authoring,
Implementation, Review's fix-loop, or Integration Stage A's fix-loop.

| Field | Value |
|---|---|
| **Purpose** | Diagnose — not repair. Produce machine-readable RCA reports; route to human for remediation choice. |
| **Persona** | **Specification RCA Agent** (analyses Spec for logical contradictions, missing context, untestable criteria, ambiguous ATs, mid-pipeline scope creep) + **Architecture Health RCA Agent** (analyses worktree and codebase context at fault sites for tight coupling, legacy debt, state contamination, layering violations, dependency-direction inversions). Both run in parallel; both are read-only; both remain interactively available for the duration of the autopsy. |
| **Exit gate** | Human picks a route from the **closed Autopsy Resolution Route taxonomy** (see below). |
| **Failure routing** | RCA itself fails (cannot diagnose) → human receives a "could-not-diagnose" stub; the UoW enters manual-investigation by the human. |

**On entry to Autopsy:**

- The Execution Pipeline halts for this UoW.
- The branch and worktree are **frozen** as evidence — no agent is
  permitted further work against them. They are **not** burned on entry.
- Strike history, gate logs, and commit SHA chain are preserved as
  forensic artefacts.

**During Autopsy:**

- Both RCA Agents emit structured machine-readable reports (YAML / JSON)
  with named root-cause categories, citations into spec / code / gate
  logs, and recommended remediations drawn from the closed taxonomy.
- The human may interactively interrogate either RCA agent — ask
  follow-up questions, request deeper analysis of specific findings,
  request comparisons against prior incidents.

**On exit (human picks route):**

- The chosen route is dispatched by the Orchestrator.
- The branch and worktree are **then** burned, and the autopsy bead is
  closed with the chosen remediation recorded.

#### Autopsy Resolution Routes (closed taxonomy)

1. **Back to stage 3 — Re-brainstorm.** Spec RCA found a flaw in the functional contract.
2. **Back to stage 5 — Re-decompose.** Decomposition was unviable.
3. **Killed.** UoW is not worth pursuing (standard Killed semantics — Epitaph required, resurrection legal).
4. **File-as-Architectural-Debt + Park.** Architecture RCA found a structural blocker; a new Idea is Captured for the debt with provenance pointing to this Autopsy; the UoW returns to *Library* with a dep on the new debt Idea. When the debt clears, the UoW becomes eligible again.
5. **Escalate-Tooling.** Evidence shows the failure was tooling (orchestrator bug, agent harness bug, CI infrastructure), not code or spec; a tooling-bug Idea is Captured; this UoW returns to *Now* with a tooling-blocker dep.

---

## Cross-Cutting Mechanisms

### Capture and the Cool Idea Quarantine

**Capture** is the act of transferring an Idea from speech or typing into
persistent storage with minimum interrupt to the work in flight. Capture
is one-shot and non-interrogative: the Idea Curator transcribes the
verbatim quote, auto-attaches a Provenance Backreference (what was being
done at the moment of Capture — file, topic, or work-in-flight
identifier; timestamp), and returns control to the originator. No
clarifying questions during Capture.

The **Cool Idea Quarantine** is the same protocol applied *inside* a
brainstorming session. When a tangential Idea fires during a stage-3
brainstorm of a *different* Candidate UoW, the Design Interrogator
Captures it to the Holding Place using the same protocol (verbatim,
Provenance Backreference identifying the in-progress brainstorm),
acknowledges briefly ("noted, parked in icebox, returning"), and resumes
the current brainstorm without further engagement on the tangent. The
parked Idea will be groomed in due course; it is not allowed to derail
the in-flight brainstorm.

### Holding Place and Grooming

The Holding Place is the persistent store where stage-1 Ideas and
stage-2 Shaped Ideas sleep until acted on. It is **pull-only by
default** — nothing surfaces them automatically except the Grooming Nag.

**Grooming** is an intentional, human-initiated triage ceremony, distinct
from the "what's next to work on" pull. During Grooming, every Idea in
the Holding Place is reviewed and assigned (or re-assigned) to a Bucket.
Grooming is *not* brainstorming — Grooming triages the whole backlog at
low resolution; brainstorming explores one Idea in depth.

**Buckets (live):** *Now*, *Next*, *Later*, *Library*.

**Terminal disposition:** *Killed* (with Epitaph; resurrection legal but
explicit).

**Grooming Nag:** deterministic, threshold-driven prompt that piggybacks
on the "what's next to work on" pull. If `now - last_groomed > threshold`,
the work-pull surface prepends a single dismissible message advising
that the Holding Place is overdue for triage. The nag self-silences once
Grooming completes.

### 3-Strike Circuit Breaker

Each Execution Pipeline state that involves an agent vs. a mechanical
gate maintains a per-state-instance strike counter:

- **Test-Authoring** — Test-Author Agent strikes on Red Gate failures.
- **Implementation** — Implementer Agent strikes on Green Gate failures.
- **Review (fix-loop)** — Implementer Agent strikes on Mechanical Finding rounds where it fails to converge.
- **Integration Stage A (fix-loop)** — Implementer Agent strikes on server-side Mechanical Finding rounds.

On strike 3, the state routes to Autopsy.

Strike counters reset on gate-pass (the state advances) or on entry to
the next attempt of the same UoW via an Autopsy Resolution Route.

### Findings (three classes)

- **Mechanical Finding** (blocking) — a machine-verifiable artefact: a failing test, a triggered lint rule, a metric over threshold, a static-analysis violation. Routes to the Implementer's fix-loop.
- **Advisory Finding** (non-blocking) — a judgment-class observation with no mechanical artefact. *Not* shown to the Implementer during the fix loop. Captured as an Idea at merge time with provenance.
- **Proposed Rule** (non-blocking on this PR; gates future) — a Reviewer-drafted candidate lint rule, AST detector, or test pattern, accompanied by a demonstration that it triggers on the current case. Captured as an Idea with type-hint *rule* at merge time. Human approval during Grooming promotes it into the project's lint/test corpus.

### Scaffold / Cleanup AT pairs and Container Closure

When a Container's Decomposition Plan emits children, each child's
eventual Agent-Ready AT-set includes:

- **Inherited atomic ATs** — its slice of the parent's functional contract.
- **Scaffold ATs** — temporary assertions describing harness, stub, mock, or demo behaviour required for the slice to ship in isolation. Each Scaffold AT is annotated with the paired Cleanup AT that will retire it.
- **Cleanup ATs** — assertions in a *later* child (per the Assembly Graph) that explicitly assert the removal of a prior child's Scaffold AT.

**Container Closure** requires: every child closed AND every
Container-Level AT passes AND no Scaffold AT persists (every Scaffold
paired with a successful Cleanup). A Scaffold leak blocks Container
closure indefinitely until the leak is repaired.

---

## Future Work (deferred)

These items are mentioned in the source bead and the project's
"Current State" idea-dump but are not load-bearing for this FSM design
pass. They are tracked for downstream consideration.

- **Pre-Mortem / Historical Linter.** A stage-3 helper that reviews Specs before execution and flags weaknesses *only when it can cite a specific documented historical failure or ADR* — eliminating strawman hallucinations. Belongs as a Design Interrogator helper tool. Out of scope here.
- **Blocker-Class Question rubric.** The exact rubric distinguishing blocker-class questions from nice-to-have during stage 3 brainstorming. Co-developed with the Design Interrogator's implementation.
- **Dreaming Process.** A background capability that periodically scans the work-item graph for new, broken, or stale connections — strengthening edges between memory nodes. Would feed Grooming with surfaced connections and feed work-pull with sequencing recommendations. Captured in `AGENTS.md`.
- **Visual AT Analysis Engine.** A spatial / visual node-graph rendering of ATs against stable CONTEXT.md domains, sized by complexity and coloured by risk, with multimodal AI analysis for topological violations. Captured in `AGENTS.md`.
- **Reviewer Agent taxonomy.** The actual project-default list of Reviewer Agents (which domains ship "in the box" and which thresholds). Project-config concern, not FSM concern.
- **Sizing Gate weights and thresholds.** Per-project tuning of the composite mechanical score's inputs. Project-config concern.

---

## Out of Scope (explicit)

The following are deliberately not addressed by this spec and are
delegated to downstream implementation specs:

- **Orchestrator implementation.** Process model (daemon vs per-task spawn), state persistence (event-sourced vs CRUD), agent dispatch transport, recovery semantics. The FSM defines *what*; the orchestrator implementation defines *how*.
- **Worktree management.** Allocation, lifecycle, cleanup, branch-naming, base-selection on retry. Implementation concern.
- **Work-tracker schema.** Whether Integration's A/B/C are sub-UoWs in the tracker or internal phases of the parent UoW (the Q15a question, explicitly deferred during design). Implementation concern.
- **Spec format.** The literal file layout / schema of a Draft Spec — Markdown? YAML? Some hybrid? Out of scope.
- **External LLM reviewer adapter logic.** The mechanics of subjecting Copilot-class reviewers to the Mechanical-vs-Advisory discipline. Implementation concern.
- **Project-config schema.** Where Reviewer Agent lists, Sizing Gate weights, coverage thresholds, approval-required defaults, aging-nag thresholds, and similar parameters live. Implementation concern.

---

## Acceptance Criteria for This Spec

Per the source bead's Definition of Done, this spec is complete when
every state from "Raw Idea" to "Merged" has explicitly defined:

- ✅ State Name and its purpose.
- ✅ The Agent Persona operating inside it (or Human / Orchestrator).
- ✅ The Mechanical Gate (deterministic trigger, script, or explicit human approval) required to exit.
- ✅ The Failure Routing (exactly where the state reverts on rejection).

All four are covered for stages 1 through 11.

**Build passes. Typecheck passes. Tests pass.** (Universal acceptance criteria — N/A for a design doc, but stated for symmetry with the project's standard DoD.)
