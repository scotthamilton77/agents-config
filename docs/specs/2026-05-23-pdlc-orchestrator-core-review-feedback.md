# PDLC Orchestrator Core — Merged Review Feedback (Round 1)

Companion to: `docs/specs/2026-05-23-pdlc-orchestrator-core-design.md`

## Purpose

Merge and group the Round-1 review feedback from two independent reviewers
into concept areas so we can carve a deliberate path through revision. This
doc is a **working triage ledger** — we update `Status` as we resolve each
finding across multiple passes.

## Sources

- **Scott** (crit, 2026-05-23) — 19 inline comments at
  `/Users/scott/.crit/reviews/6c185cd92050/review.json`. Anchors and bodies
  preserved verbatim in the appendix.
- **Codex gpt-5.5 adversarial review** (2026-05-23) — 8 numbered sections.
  Full text archived at `docs/specs/2026-05-23-pdlc-orchestrator-core-codex-adversarial-review.md`.

## Finding ID convention

- `S-NN` — Scott crit comment (numbered in the order they appear in the
  review.json file, not by crit ID).
- `C-Sec.Item` — Codex finding (e.g. `C-1.3` = Codex Section 1, item 3).

## Status legend

- `open` — not yet discussed
- `discuss` — needs conversation before resolution
- `applied` — edit landed in the spec; record commit/diff reference
- `deferred-child` — pushed to a child bead under wgclw.2 implementation
- `deferred-followup` — post-MVP, captured in follow-up bead (with id once filed)
- `out-of-scope` — explicitly rejected with reason
- `superseded` — replaced by a more comprehensive finding (link to superseder)

---

## Concept Area 1 — Naming & Terminology Hygiene

**Theme:** Cryptic codes (`6'`, `10A`, `I3`, `stage_3`, `fsm_stage`) and
opaque names (`spec_blob`) make the spec unreadable and will pollute any
generated code, logs, and dashboards. CONTEXT.md must hold the universal
language; references like "Integration §A" violate that contract.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-01 | Scott | major | spec L94 | All `fsm_stage` values (1, 2, 3, …, 6', 10A/B/C, 11) need English constant names — no cryptic codes through the data | Define a stage-name constants table (e.g. `IDEA_RAW`, `IDEA_SHAPED`, `CANDIDATE_UOW`, `SHAPING`, `READY_TO_DECOMPOSE`, `IMPLEMENT`, `IMPLEMENT_FIXUP` for 6', `REVIEW`, `MERGE_GATE`, `PR_MECHANICAL`, `PR_HUMAN_HOLD`, `MERGING`, `KILLED`/`MERGED`/`PARKED`). Use the names throughout the spec; relegate numeric stage IDs to a dim "ordering hint" column. | applied (22eeded) |
| S-04 | Scott | major | spec L109 | `fsm_state` is a concept name applied to a problem; rename to `objective_lifecycle_state` (or better) | Rename `fsm_state` → `objective_lifecycle_state` in the Objective data model; rename `fsm_stage` → `lifecycle_stage`. Cascades to all subsequent code, tables, CLI strings. | applied (22eeded) |
| S-12 | Scott | major | spec L189 | "FSM stage" in attributes table should read "Objective Lifecycle Stage" | Apply rename from S-04 consistently in attribute tables. | applied (22eeded) |
| S-15 | Scott | minor | spec L304 | `fsm_stage` in Session data model — apply the rename | Same rename cascade. | applied (22eeded) |
| S-16 | Scott | major | spec L356 | Pseudocode `run_stage_3_gates(o.id)` — no obscure references in code | Rename to `run_<lifecycle-stage-name>_gates(o.id)` using the canonical English name from S-01. | applied (22eeded) |
| S-03 | Scott | minor | spec L101–102 | `spec_blob` — if it's the Draft Spec body, call it `draft_spec` and drop the `_blob` suffix | Rename `spec_blob` → `draft_spec`. | applied (22eeded) |
| S-10 | Scott | major | spec L162 | `I3` is meaningless to a reader — stay away from unexplained codes/acronyms | Replace `I3 sibling captures` with descriptive prose; do a global sweep for any other inline rule-IDs that aren't defined in this spec. | applied (22eeded) |
| S-07 | Scott | major | spec L133–135 | CONTEXT.md references "Integration §A/B/C" instead of actual terms — violates CONTEXT.md's mandate to establish a universal language | Replace `Integration §A/§B/§C` with the named lifecycle stages (PR Mechanical Validation, Human Approval Hold, Merge + Cleanup). Sweep the spec AND CONTEXT.md for any other §-style references that should be names. | applied (22eeded) |
| S-08 | Scott | minor | spec L137 | Terminal states (Merged / Killed / Parked) should appear in CONTEXT.md too | Add the terminal-state entries to CONTEXT.md alongside the other Objective lifecycle stages. | applied (22eeded) |

**Cross-cutting notes:** Codex's "Things The Spec Gets Right" item about
"first-class Sessions" survives the rename; nothing in this concept area
changes the underlying model.

---

## Concept Area 2 — Data Model Completeness (Objective)

**Theme:** The Objective attribute list is missing things Scott considers
load-bearing (priority, dependencies). The `type_stamp` vs container
distinction should be explicit-binary, not enum-substring. Bucket placement
needs to match its actual scope.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-02 | Scott | major | spec L98–100 | Separate `type` (Story/Task/Chore/Bug/Epic/Feature/...) from `is_container` (boolean). Some types (epic) SHOULD always be containers; encoding that as string-compare against a growing list is fragile | Add explicit `is_container: bool` field on Objective. Type rules in code key off the boolean, not the type-stamp string. Define which type-stamps default to container=true (Epic, Feature-with-children, Milestone). | applied |
| S-13a | Scott | major | spec L86 | Are dependencies tracked or mirrored in Objective state? Readiness queries need blocking/open/priority signal | Resolved via CA-12: dependencies move to orchestrator sidecar (`OrchestratorStateRepo.DependencyEdges`) for MVP; v2 protocol expansion captures tracker-side sync. | applied |
| S-14 | Scott | major | spec L86 | Priority is not in the Objective attribute list | Add `priority` field to Objective; sourced from tracker (PriorityLevel 0..4, P0-P4). Orchestrator does not override; it projects as a sort key. | applied |
| S-11 | Scott | minor | spec L176 | Add Priority to the State Notes table | Add row. | applied |
| S-13b | Scott | minor | spec L194 | Bucket (Now/Next/Later/Library) only meaningful at stages 1–2 — should it be an Idea-specific property rather than a generic Objective attribute? Mirroring is acceptable if useful | Resolved via CA-8 Option A: Bucket moves to the `Idea` primitive entirely; Objectives have no Bucket field. | applied |

---

## Concept Area 3 — Architectural Visualization & HLD Artifacts

**Theme:** Specs alone don't cement the big picture for human or agent
decomposers. We need diagrams in this spec AND a high-priority HLD bead
ahead of all implementation.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-09a | Scott | major | spec L119 | Add at least a happy-path flowchart to THIS spec | Happy-path Mermaid flowchart landed in § "Happy-path flowchart"; reworked per CA-8 to remove `IDEA_RAW`/`IDEA_SHAPED` nodes and add a Holding-Place Idea node with a labelled Promote transition. | applied |
| S-09b | Scott | major | spec L119 | Queue a priority bead AHEAD of all implementation to produce HLD artifacts in as many views as possible | HLD multi-view artifacts deferred to follow-up bead. | deferred-followup (bead: `agents-config-wgclw.2.1`) |

---

## Concept Area 4 — Persistence / OrchestratorStateRepo Spine

**Theme:** Codex's #1 showstopper: deferring storage is deferring the
failure boundary. Scott echoes that whatever we pick MUST be versioned;
Dolt-backed beads is an interesting reference. The spec says "OrchestratorStateRepo
deferred to implementation child" — both reviewers say no.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.1 | Codex | **showstopper** | "State Ownership" / "OrchestratorStateRepo backing store — deferred" | Storage is the failure boundary of the whole orchestrator. Single-writer locking, pending-before-fork session records, append-only transition logs, marker updates, crash recovery, queryability, and corruption resistance are not implementation details. Flat YAML/JSON must be rejected — it cannot safely support async sessions, append logs, marker updates, and concurrent reads | DoltDB (embedded) committed as backing store in § "Backing store: DoltDB (embedded)"; SQL transactions, CAS-via-`UPDATE ... WHERE version = ?`, lease-based locking, append-only `TransitionLog` table, schema migrations under `migrations/state-repo/`. | applied |
| S-17 | Scott | major | spec L460–462 | Whatever we pick, it MUST be versioned. Dolt (as bd uses) with a remote is an interesting reference. Versioning is a hard requirement; this comment is not implementation-selection but requirement-statement | DoltDB committed; native versioning, optional project-local remote for off-host backup. | applied |
| C-3.6 | Codex | major | "Designed too early" + "Deferred incorrectly" | The spec defers exactly the parts that the "Code over Prose / Python over Bash" doctrine demands be code-first: state store, adapter conformance, config schema, gate evidence schema, supervision, marker semantics | All flagged items pulled into the spec body: state store (DoltDB / CA-4), adapter conformance (4-domain MVP / CA-12), config schema (versioning + two-tier validation / CA-13), gate-evidence schema (CA-15), JobSupervisor contract (CA-7), bd marker semantics (CA-6). | applied |
| C-2.0 | Codex | major | Assumptions §2 | Assumption: "OrchestratorStateRepo corruption is recoverable" — but no rebuild story exists; tracker lacks FSM state, strike counters, session state, transition logs. Repo loss = lifecycle brain loss | "Crash-recovery primitives" subsection added under OrchestratorStateRepo; per-tick branch checkpoint, `dolt log` replay, rebuild-from-tracker fallback for the recoverable subset (lifecycle_status, hierarchy, spec — explicitly NOT lifecycle_stage / strike counts / transition log). | applied |

---

## Concept Area 5 — Concurrency, Atomicity, Crash Safety

**Theme:** Tick algorithm reads as happy-path script. No transactional
discipline, no compensation, no crash-recovery table. Local-host PID lock
is insufficient for autonomous overnight execution.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.2 | Codex | **showstopper** | "Process Model: CLI-driven Tick > Tick algorithm" | Tick is not atomic. Discovery, gates, reconcile, reap, dispatch, then persist — if any step mutates tracker/filesystem/worker/session state before the final flush, recovery is undefined | "Transition execution discipline" subsection codifies the read-version → validate-invariant → write-event → commit → side-effect → record-side-effect-result pattern. Side-effects are resumable or compensatable. | applied |
| C-1.4 | Codex | **showstopper** | "Single-writer lock (.pdlc/tick.lock)" | Local lock only protects one filesystem on one host. Stale lock files after process death, PID reuse, multiple terminals, cron overlap across worktrees, remote runners — all bypass it | Lease-based lock in `OrchestratorStateRepo.Leases` (`holder_id`, `fencing_token`, `acquired_ts`, `heartbeat_ts`, `expiry_ts`); file lock retained as fast-path optimisation only. Stale-lease recovery rule specified (`now > expiry_ts + grace`). | applied |
| C-5.1 | Codex | major | Missing concerns — Crash recovery | No recovery table for: before fork, after fork before PID write, after worker exit before report write, after report read before stage advance, after tracker write before marker write | New top-level § "Crash-Recovery" with the 5-point table (a–e) covering each named transition point with detection mechanism + recovery action. | applied |
| C-5.2 | Codex | major | Missing concerns — Concurrency | No snapshot isolation, compare-and-swap, tracker version checks, or fencing tokens specified | "Compare-and-swap on tracker writes" subsection specifies CAS / version-check semantics; every tracker write reads current version into the predicate, mismatch aborts with `tracker-version-mismatch`. | applied |
| C-5.3 | Codex | major | Missing concerns — Race conditions | Human edits, worker commits, reviewer artifacts, config reloads, tracker status updates can all race the tick | "Race enumeration" table enumerates five race cases with detection + remediation each. | applied |

---

## Concept Area 6 — Discovery / Reconciliation Correctness

**Theme:** A single opaque `discover_since(marker)` is fantasy under real
trackers. The orchestrator can advance against stale reality if discovery
misses one structural edit.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.3 | Codex | **showstopper** | "Discovery Sweep" using `discover_since(marker)` | Clock skew, Dolt state, rebases, human edits, deleted/closed items, sidecar metadata drift, and adapter bugs will lose events under a single opaque marker | `discover_since` reframed as acceleration path only. "Per-tick full reconciliation" subsection (every Nth tick, default N=10) + "Per-object version fingerprints" `(spec_hash, structural_hash, dependency_hash, lifecycle_status_hash)` with read-before-transition CAS. | applied |
| C-6.7 | Codex | major | Stress scenario — "Discovery Sweep misses a tracker change" | Orchestrator continues from stale structure; parent/child DAG, deps, spec body, or lifecycle can diverge indefinitely because the marker is trusted | Subsumed by C-1.3 full-reconcile + fingerprint diff. | applied |
| C-4.4 | Codex | major | "Deferred incorrectly: bd marker semantics" | bd is the reference adapter. If discovery can't be made correct there, the whole adapter abstraction is speculative | "bd marker semantics (reference adapter)" subsection added; marker pinned as `(dolt_commit_hash, max_updated_ts)` pair with concrete translation contract. | applied |

---

## Concept Area 7 — Worker Dispatch & Session Supervision

**Theme:** PID is not a reliable job identity. Sessions need a real
supervisor contract. Authority must be enforced before/during execution,
not at reap time.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.5 | Codex | **showstopper** | "Worker Dispatch — Async (Option B)" + "Session Primitive" | Detached subprocess + PID is not a reliable job model. PIDs die, get reused, lose process groups, survive parent death weirdly. Session has no deadline, heartbeat, timeout policy, or process-group identity | Session record reshaped: `pid` removed; `supervisor_id`, `lease_token`, `heartbeat_ts`, `deadline_ts`, `process_group_id`, `artifact_dir` added. New "JobSupervisor contract" subsection enumerates the six supervisor capabilities. Sandboxing v2 deferred. | applied |
| C-1.6 | Codex | **showstopper** | "Worker authority" — "Orchestrator does not enforce boundaries in code" | "We'll catch it at reap" is damage assessment, not enforcement. A Test-Author can delete files, alter secrets, modify config, weaken tests, or exfiltrate before reap. Reviewers can inject new rules that distort project policy | "Worker authority" section replaced by "Pre-execution & in-flight authority enforcement": sandboxed worktree, per-persona path allowlist, pre-fork diff validation, environment scrubbing, default-deny network policy, immutable base snapshot reference. Reap-time checks remain as defence in depth only. Sandboxing v2 (containerisation) deferred. | applied; sandboxing v2: deferred-followup (bead: `agents-config-5vxfw`) |
| C-6.2 | Codex | major | Stress — worker hangs forever | Session has no timeout/deadline/heartbeat; "running" forever unless implementation invents missing semantics | Subsumed by C-1.5 supervisor contract; `deadline_ts` + `heartbeat_ts` in Session record + supervisor `cancel()` cover the hang case. | applied |
| C-5.9 | Codex | major | Missing concerns — Config changes in flight | Sessions don't record the config hash they were launched with. Reaping under a different config can invalidate gate meaning | `config_hash` recorded on Session at dispatch; reap validates equality and routes mismatch to config-version-divergence handler (CA-13). | applied |

---

## Concept Area 8 — Universal Entry vs Objective Primitive Contradiction

**Theme:** L6 says every Objective enters at stage 3, but the Objective
primitive (and CONTEXT.md) say stages 1–2 ARE Objective stages. Pick one.
Scott's bucket-placement question (Concept Area 2) is the same problem
seen from below.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.9 | Codex | **showstopper** | "Universal Entry Point" (Law L6) | L6 says every Objective enters at stage 3, while the Objective primitive and CONTEXT.md say stages 1–2 are Objectives with fsm_stage, bucket, grooming state, and provenance | **Option A committed** — Idea is a distinct primitive in the Holding Place; `IDEA_RAW` / `IDEA_SHAPED` dropped from the lifecycle-stage enum; L6 restated cleanly; "Holding Place handoff" subsection specifies the contract. | applied |
| C-3.1 | Codex | major | Inconsistencies | L6 vs Objective primitive vs CONTEXT.md — three documents disagree | Three-doc sweep applied: design spec primitive + L6 restated, CONTEXT.md Objective/Idea/Holding Place/Bucket/Candidate UoW entries restated. FSM-spec local restatements added (L2/L4) per CA-9 — FSM spec itself not edited. | applied |
| C-3.2 | Codex | major | Inconsistencies — Discovery Sweep vs FSM Stage 5 child creation | Target spec: unknown Objective initializes at stage 3. FSM spec stage 5: oversized Container emits children into Holding Place at stage 2. Contradiction — next Discovery would re-initialize those children at stage 3, skipping their stage-2 lifecycle | Resolved via Option A: stage-5 child emission calls `HoldingPlace.create_idea(...)`, NOT `create_objective(...)`. Discovery does not see Holding-Place entities (they're on the other side of the WorkTracker boundary); promotion is the explicit handoff. | applied |
| C-3.3 | Codex | minor | Inconsistencies | "Same record moves through FSM" vs "Idea-less Objectives created directly at stage 3" — storage model does not define whether stage 1–2 records live in same tracker namespace as stage 3+ records | Namespace boundary explicit: Ideas live in the Holding Place; Objectives live in the WorkTracker. Same Dolt instance, separate schema. | applied |
| C-7.3 | Codex | major | Law L6 critique | Internally confused — if stages 1–2 exist, they need ownership; if outside the FSM, stop calling them Objective stages and remove from `fsm_stage` | Subsumed by C-1.9 Option A. | applied |

---

## Concept Area 9 — Mechanical Gate Discipline & 3-Strike Routing

**Theme:** Reviewer-added mechanical findings can game the strike counter.
Tooling bugs, flaky tests, broken reviewer artifacts need separate routing
before they get charged to the Implementer.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.7 | Codex | **showstopper** | "Review" / "Reviewer Agents may add tests, lint rules, AST detectors…" | The spec lets probabilistic agents mutate the mechanical vocabulary during review, then treats their outputs as blocking. A bad reviewer can create an impossible Mechanical Finding and burn three Implementer strikes | "Reviewer-artifact validator" subsection added: proposed artifacts land in `.pdlc/proposed-artifacts/` and pass schema-conformance / isolated-execution / idempotency / finite-runtime checks before blocking. Failures route to tooling-escalation, NOT Implementer strikes. | applied |
| C-7.2 | Codex | major | Law L4 critique | 3-Strike is naive as written. "Same gate failed three times" ≠ "agent cognition failed". Tooling bugs, flaky tests, bad reviewer artifacts, broken config, unavailable deps, stale specs all need different routing before strikes are charged | L4 local restatement added; "Pre-strike triage" subsection enumerates seven failure causes (cognition / tooling / reviewer-artifact / flake / config / dependency / spec) with routing rules. Strikes charged only for cognition failures. | applied |
| C-6.9 | Codex | major | Stress — Reviewer toolbox emits Mechanical Finding Implementer cannot fix | Implementer burns strikes and routes to Autopsy even though the failure is tooling | Subsumed by C-1.7 + C-7.2. | applied |
| C-7.1 | Codex | minor | Law L2 critique | "Mechanical Gates Only" is overstated. Stage 3 has human signoff, blocker-class judgment, linter overrides. Stage 5 has human signoff. These are valid but not purely mechanical | L2 local restatement added: "execution transitions are mechanical AFTER explicit human gates"; the gate set itself includes human signoffs at `CANDIDATE_UOW → AGENT_WORTHY` and `DECOMPOSE` exit. FSM spec itself not edited. | applied |

---

## Concept Area 10 — Terminal State Semantics

**Theme:** Collapsing every flavor of "closed in the tracker" into the
single terminal `Killed` is reckless. Closed-as-merged, closed-as-duplicate,
closed-by-parent-walk, accidental close all mean different things.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-1.8 | Codex | **showstopper** | "Tracker closed while Orchestrator pre-terminal → Killed" | "Closed" in a tracker is not semantically equal to Killed. May mean manually completed, merged outside orchestrator, closed as duplicate, closed by parent propagation, or accidental close. Killing in-flight sessions based on coarse status destroys valid work | Terminal-disposition classifier in "Terminal disposition" subsection; tracker `terminal_disposition` typed-metadata field (Domain 2 lifecycle write) drives the mapping; absent/ambiguous → `needs_reconcile=true` (NOT auto-Killed). `terminal_disposition` field added to `objective_lifecycle_state`. | applied |

---

## Concept Area 11 — Mid-Flight Change Reconciliation

**Theme:** Spec body, tracker structure, and config can all change while
an Objective is in flight. Scott wants the Agent-Ready gate re-applied on
mid-flight spec mutation. Codex extends the concern to human edits and
config reloads. Sessions need to be pinned to the config they were dispatched
under (already noted in Concept Area 7, C-5.9).

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-18 | Scott | post-MVP / major | spec L221–223 | When tracker spec body changes during stages 7–10: instead of just advisory-flagging, re-apply Agent-Ready gate checks to the updated spec. Pass → info notice. Fail → escalate to human; offer (a) put on hold and bump back to stage 3, or (b) override and continue | Spec-mutation re-gate deferred per Pre-Ultraplan Briefing OUT-of-MVP. One-line pointer in spec body "Deferred (post-MVP)" table. | deferred-followup (bead: `agents-config-opnn2`) |
| C-6.3 | Codex | major | Stress — human edits tracker mid-tick | Tick advances against stale spec/hierarchy, then persists a marker that hides the edit. Next tick only sees orchestrator projection, not human intent | "Mid-tick edit detected" subsection added; CAS + fingerprint diff aborts in-flight transition, re-reads, re-ticks — no stale-read side-effects persisted. | applied |
| C-6.5 | Codex | major | Stress — Project-config reloads with breaking changes while workers in flight | Reap may validate old worker output against new rules. Valid work fails, invalid passes | Subsumed by C-5.9 config_hash binding + CA-13 two-tier validation. | applied |
| C-6.6 | Codex | major | Stress — Child Objective killed while parent Container mid-Decomposition | Parent's Decomposition Plan may still allocate ATs to killed child. Container closure becomes impossible or silently partial | "Decomposition-plan invalidation" subsection added; on child-`KILLED`, parent's Decomposition Plan surfaces for human disposition; no silent re-allocation. | applied |

---

## Concept Area 12 — Protocol Scope & Adapter Cost

**Theme:** Codex's L3/L8 critique: the rich 7-domain WorkTracker protocol
is "coupling behind an interface." A bigger protocol means every adapter
becomes a fragile emulation layer. Scott's c_439569 dependency question
intersects this — if dependencies are in the protocol, every adapter
must emulate them.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-4.1 | Codex | major | "Designed too early: rich WorkTracker protocol" | Seven domains of tracker behavior specified before proving the minimal core. Overfits to imagined universal tracker; every adapter becomes expensive | **Four-domain MVP committed**: Discovery & state (Domain 1, minus `resolve_provenance`), Lifecycle (Domain 2, with `set_terminal_disposition` added), Hierarchy (Domain 3), Spec content (Domain 4, renumbered from 6). Domains 4 / 5 / 7 (was) move to orchestrator sidecar (`OrchestratorStateRepo`). v2 protocol expansions deferred. | applied; v2 protocol: deferred-followup (bead: `agents-config-o2oub`) |
| C-7.4 | Codex | major | Law L3 critique | Target protocol makes orchestrator depend on tracker hierarchy, metadata, search, lifecycle, dependencies, spec mutation, provenance — that is coupling behind an interface | Resolved via C-4.1 four-domain shrink. | applied |
| C-7.5 | Codex | major | Law L7 critique | "Tracker wins structural, Orchestrator wins FSM" does not resolve compound transitions like child creation, close-walk, autopsy parking, manual closure | "Compound-transition decision table" added covering six transitions (child creation, container closure, autopsy parking, manual closure, reparenting, Idea promotion) with tracker writes / orchestrator writes / disagreement resolution columns. | applied |
| C-7.6 | Codex | minor | Law L8 critique | Correct instinct, wrong scale — the larger the protocol the more every adapter is a fragile emulation layer | Resolved via four-domain shrink (~50% adapter surface reduction). | applied |
| C-2.1 | Codex | major | Assumption | Adapters can synthesize the full WorkTracker protocol — if wrong, Jira/GitHub/bd adapters become sidecar databases pretending to be trackers, and L8 becomes false-abstraction theater | Adapter-conformance subsection now states bd adapter is validated against the shrunk four-domain protocol before this revision pass completes; v2 expansions get their own corpus when their bead opens. | applied |

---

## Concept Area 13 — Project-Config Versioning & Lifecycle

**Theme:** Config needs ergonomic defaults, layered overrides, and
in-flight-safety. Sessions launched under config v1 should not be reaped
under v2 without explicit migration handling.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-19 | Scott | post-MVP / minor | spec L499 | Post-MVP: user-level defaults; project overrides user; `.local` non-versioned overrides. CLI tolerates absence of `project-config.toml`; either auto-creates with defaults OR works without it (create-on-demand) | One-line "Deferred (post-MVP)" pointer in spec body. | deferred-followup (bead: `agents-config-p2dq8`) |
| C-5.8 | Codex | major | Missing concerns — Upgrade / migration | No schema versioning, config version pinning, state migration, backward compatibility, or rolling upgrade behavior | `config-schema-version` field added to `[project]` block; loader refuses unknown versions; "Schema migrations" subsection specifies versioned migration scripts under `migrations/config/`. | applied |
| C-2.8 | Codex | major | Assumption | Config hard-fail on every tick is safe — if wrong, one bad config edit freezes all reaping, including cleanup of already-running sessions | "Validation discipline — two-tier" subsection: Tier-1 structural validation hard-fails the tick; Tier-2 semantic divergence routes to degraded reap-only mode preserving in-flight reap under original config_hash. | applied |

---

## Concept Area 14 — Observability, Audit, Forensics

**Theme:** `pdlc health` is named but not designed. Transition logs exist
in the data model but have no tamper model, event schema, hash chain, or
retention policy.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-5.6 | Codex | major | Missing concerns — Audit / forensics | Transition logs mentioned but no tamper model, event schema, hash chain, artifact retention policy, or way to reconstruct a run | "Transition log event schema" section added; event fields `(ts, objective_id, session_id?, from_stage, to_stage, reason, gate_evidence_ref, actor, config_hash)`; retention keep-forever via Dolt. Cryptographic hash-chain deferred. | applied; hash-chain layer: deferred-followup (bead: `agents-config-64ecc`) |
| C-5.7 | Codex | major | Missing concerns — Observability | `pdlc health` named but not designed. No metrics, structured logs, trace IDs, session correlation IDs, failure taxonomy, alert thresholds | "`pdlc health` output contract" section specifies seven required sections (Session inventory / Lifecycle-stage histogram / Strike-counter distribution / Recent failure taxonomy / Marker-drift indicator / Lease-holder identity / Degraded-mode flags). Rich dashboards deferred. | applied; dashboards: deferred-followup (bead: `agents-config-ak007`) |

---

## Concept Area 15 — Tracer Bullet & Integration Test Strategy

**Theme:** Scott wants pseudo-code integration tests with mocked repos that
simulate flows/transitions/failure states, **scheduled into the child beads**
so PRs aren't perpetually red. The first scenario IS the tracer bullet that
drives implementation order. Aligns with Codex's "deferred incorrectly:
adapter conformance" finding.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| S-20 | Scott | major | spec L601–602 | Start with pseudo-code integration tests mocking repos and other moving parts, simulating flows, transitions, failure states across all moving parts. Schedule these into child beads so we're not writing tests that fail continually. First scenario = tracer bullet that prioritizes path to full test working | Appendix A "Integration-test scenarios (pseudocode)" added with 7 scenarios; Scenario 1 marked tracer-bullet P0; impl-child umbrella `agents-config-wgclw.2.2` for scenario implementation. | applied; test code: deferred-impl-child (bead: `agents-config-wgclw.2.2`) |
| C-4.5 | Codex | major | "Deferred incorrectly: gate evidence schema" | Gates are the core architectural law. Deferring evidence shape means the law has no executable interface | "Gate-evidence schema (structural)" section added with 10 named fields (`gate_id`, `gate_version`, `objective_id`, `session_id`, `attempt_number`, `started_ts`, `ended_ts`, `verdict`, `evidence_artifacts`, `failure_class?`); worker writes / reap re-verifies. | applied |
| C-2.6 | Codex | major | Assumption | Stage transitions are cheap enough to run during discovery — if wrong, discovering a backlog triggers gate work and `pdlc tick` becomes a long-running batch | `tick-budget-seconds` (default 60) added to `[orchestrator]` config block; tick algorithm starts the budget timer; dispatch checks remaining budget and defers overflow to the next tick. | applied |
| C-2.7 | Codex | major | Assumption | Sizing Gate can be deterministic from file-touch / subsystem-crossing counts — Codex sniffs LLM judgment smuggled into "mechanical" law | "Sizing Gate decision table" section added with five inputs, default weights, and a `human-mechanical` escape clause requiring recorded operator override for any LLM-judgment axis. | applied |

---

## Concept Area 16 — Adversarial Inputs & Security

**Theme:** The spec has no explicit security posture for tracker content,
worker filesystem access, log handling, or prompt injection.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-5.5 | Codex | major | Missing concerns — Adversarial inputs | No safe YAML parsing policy, path traversal guard, symlink handling, untrusted logs, prompt injection handling, secret exposure policy, or malicious tracker content handling | New "Security Posture" section added with subsections: Parser hardening (yaml.safe_load only; tomllib only); Filesystem boundary (canonicalised absolute prefixes; symlink-resolved); Untrusted log handling; Prompt-injection escape-hatch; Secret exposure. | applied |
| C-2.2 | Codex | major | Assumption | Tracker and Orchestrator can safely share identity by Objective ID only — if wrong, deleted/recreated IDs, migrated trackers, imported items, or duplicate sidecar rows corrupt FSM history | "Identity model" subsection under Security Posture: every Objective keyed by `(tracker_origin_id, tracker_id, creation_fingerprint)`; identity continuity verified before every FSM-state read; mismatch routes to `needs_reconcile=true`. | applied |
| C-2.3 | Codex | major | Assumption | Worker reports can be trusted enough to drive gates — if wrong, a malicious or confused worker fabricates YAML, spoofs paths, or claims evidence the orchestrator does not independently verify | "Independent verification of gate-driving claims" subsection: orchestrator re-runs the gate command itself from reap step against the worker's commit SHA; evidence YAML is the *claim*, the re-run *establishes* the claim. No trust-by-report. | applied |

---

## Concept Area 17 — Multi-User / Multi-Host / Distributed

**Theme:** Spec assumes single-user, single-host. The 85/5/10 overnight-autonomy
goal will eventually demand more.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-5.4 | Codex | major | Missing concerns — Multi-user / multi-host | No owner identity, distributed lock, remote runner model, shared artifact store, or conflict policy | "Single-host constraint (MVP)" subsection states the constraint explicitly; distributed orchestration deferred. | deferred-followup (bead: `agents-config-89v77`) |
| C-2.4 | Codex | minor | Assumption — Local cron + tick is enough for overnight autonomy | If wrong: sleep/wake cycles, machine restarts, stale locks, hung workers, network outages silently stall the system | "Machine-wake recovery" subsection added: stale-lease reclaim (`expiry_ts + grace < now`), heartbeat-silent Session reap, wake-recovery actions surfaced on `pdlc health`. | applied |

---

## Concept Area 18 — Worktree Correctness

**Theme:** Codex flags worktree mechanics as undefined in the spec. We
operate in worktrees daily but the orchestrator never specifies the
discipline.

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-5.9 | Codex | major | Missing concerns — Worktree correctness | No branch naming, base commit pinning, dirty-state detection, branch freezing semantics, cleanup idempotency, or conflict handling | New top-level § "Worktree Discipline" added: branch naming `pdlc/<objective_id>/<lifecycle_stage>/<attempt_number>`; `worktree_base_commit` pinning at fork; dirty-state detection via `git status --porcelain`; idempotent `cleanup_worktree`; merge-conflict routes to HEP (NOT Autopsy). | applied |
| C-2.5 | Codex | minor | Assumption — Human tracker edits can be reconciled after the fact | If wrong: a mid-tick edit races stage advancement, causing stale specs, orphaned children, or killed sessions | Subsumed by C-6.3 mid-tick edit handling + Worktree Discipline base-commit pinning. | applied |

---

## Concept Area 19 — Tracker Unreachability / Degraded Modes

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-6.8 | Codex | major | Stress — Tracker unreachable for extended period | Hard fail likely blocks discovery, reconcile, lifecycle projection, and maybe reaping. Workers may finish but cannot be advanced. No offline mode or degraded reap-only mode is defined | "Degraded modes" subsection under Process Model: read-only-cache discovery, reap-only mode, config-version-divergence handler, human-alert mode. `pdlc tick` exits with degraded-status code (distinct from error). | applied |

---

## Concept Area 20 — Invariant Model (Missing Up Front)

| ID | Source | Severity | Location | Claim | Proposed action | Status |
|---|---|---|---|---|---|---|
| C-4.7 | Codex | major | "Missing upfront: invariant model" | Spec needs a list of state invariants: legal transitions, parent-child stage constraints, session cardinality, config version pinning, marker monotonicity, terminal-state rules | New top-level § "Invariants" with 8 numbered invariants (legal transitions, parent-child constraints, session cardinality, config-version pinning, marker monotonicity, terminal-state rules, lease uniqueness, CAS coverage), each with precondition / postcondition / violation-handling triplet. | applied |

---

## Concept Area 21 — Things The Spec Gets Right (Preserve)

Codex's short list of items NOT to break during revision:

- The async dispatch / reap shape is the right direction; daemonizing too
  early would add operational weight.
- Separating tracker-visible lifecycle from orchestrator-owned FSM state
  is necessary.
- Treating Sessions as first-class records is correct.
- Rejecting capability flags in core orchestration is sound, **provided
  the required protocol is made much smaller and more rigorously testable**
  (cross-ref Concept Area 12).
- The insistence on structured evidence, transition logs, and adapter
  fixture tests is the right instinct (but evidence schema must be defined
  — cross-ref Concept Area 15 / C-4.5).

---

## Appendix A — Scott crit comments (verbatim)

Source: `/Users/scott/.crit/reviews/6c185cd92050/review.json`, scope=line,
review_round=1, all comments by Scott Hamilton, 2026-05-23.

### S-01 — c_4f6cc6 — spec L94

> We need to have english "constant" names for all of these"  I don't want
> cryptic codes floating through the data that make it hard to debug.

Anchor: `fsm_stage                         # one of: 1, 2, 3, 4, 5, 6, 6', 7, 8, 9,`

### S-02 — c_670650 — spec L98–100

> Let's separate "type" from "is_container"; the latter could theoretically
> be derived from whether there are children or not, but we want this to
> be explicit, because some types (e.g. epic) _should_ be a container and
> not itself an executable UoW.  It'll be easier to design rules and logic
> around the binary than a string compare to a list that could grow over
> time.

Anchor: `type_stamp` (Executable / Container)

### S-03 — c_6fb8d4 — spec L101–102

> If this is truly the "Draft Spec body" then let's call it draft_spec."
> (Do we need to append "_blob" to the property name?)

Anchor: `spec_blob`

### S-04 — c_8d26a0 — spec L109

> We should have a better, scoped name for this.  FSM is a concept, but
> this is applied to a scope/problem.  This is the objective_lifecycle_state.
> If you don't like that, give me a better name.

Anchor: `fsm_state {                       # Orchestrator-owned; not in tracker`

### S-13a — c_439569 — spec L86

> Should dependencies also be tracked or mirrored here?  Or do you envision
> that is tracked solely in the WMS?  Ultimately the response to "what's
> ready" will be a function of what's blocking, what's open, what's
> priority, right?

Anchor: `### Attributes`

### S-14 — c_ad6f2f — spec L86

> Priority?

Anchor: `### Attributes`

### S-07 — c_cd4549 — spec L133–135

> I don't like that our CONTEXT.md file is using references (integration
> section a, b, c) vs. actual terms.  That feels like a violation of what
> CONTEXT.md is supposed to do: establish a [clear] universal language.
> Let's fix this in all places where this is abused.

Anchor: `| 10A | PR Mechanical Validation | Integration §A |`

### S-08 — c_40a43a — spec L137

> Why wouldn't we include this in CONTEXT.md too?

Anchor: `| Merged | terminal — happy | — |`

### S-09 — c_f3de75 — spec L119

> Let's do a flowchart for at least the happy path in this spec, but let's
> also queue up a priority bead ahead of all implementation to create
> some HLD artifacts that show the entire system architecture in as many
> views as we can at this stage.  These would also help to cement the big
> picture as we decompose the work.

Anchor: `### Lifecycle name mapping`

### S-10 — c_47c8ee — spec L162

> I3 is meaningless to the reader.  Stay away from unexplained codes/acronyms.

Anchor: `- Discovered work mid-implementation (I3 sibling captures).`

### S-11 — c_a09237 — spec L176

> Add: Priority

Anchor: `| State | Notes |`

### S-12 — c_00fb90 — spec L189

> Objective Lifecycle Stage

Anchor: `| FSM stage | per the FSM spec's enumeration |`

### S-13b — c_9d6cd9 — spec L194

> If this is true (only meaningful at FSM stages 1-2) then should this be
> a property of an idea?  Even if so, if it helps to mirror here, that's
> fine.

Anchor: `| Bucket | Now / Next / Later / Library — only meaningful at FSM stages 1–2 |`

### S-18 — c_e4ac6b — spec L221–223

> One thing we could do (perhaps something to capture for post-MVP) is
> re-apply the agent-ready gate checks to the updated spec, and if all
> is still ok, merely flag this to the user (info), but if it fails,
> implying the change to the spec took us away from the mandate for "only
> high-quality specs are agent-ready" then we should report this to the
> user and see if the user agrees to put this on hold and bump it back
> up to stage 3, or wants to override and let it through.

Anchor: tracker spec body changed during stages 7–10 advisory note

### S-15 — c_d13106 — spec L304

> note earlier comments on rename

Anchor: `fsm_stage           # 7, 8, 9, 10A, or 11 — the gate it targets`

### S-16 — c_3aedce — spec L356

> rename - no "stage_3" kind of obscure references in code.

Anchor: `run_stage_3_gates(o.id)`

### S-17 — c_b1a220 — spec L460–462

> Whatever our implementation choice, it must be versioned.  Beads has
> an interesting model to follow using dolt where dolt is configured with
> a remote.  This comment is not to suggest the implementation at this
> time, but the requirement of versioning.

Anchor: likely-implementations paragraph

### S-19 — c_5b1015 — spec L499

> Post-MVP: we'll want user-level defaults where project settings override
> user.  We should also think about a project-config.toml.local
> (non-versioned local overrides).  But for the default values, we'll
> need the pdlc CLI to tolerate the absence of this file and create it
> with the defaults, OR, allow it to always not exist, perhaps creating
> it for the user on demand.

Anchor: `Global defaults live in \`project-config.toml\` and its includes.`

### S-20 — c_9e39d8 — spec L601–602

> We should start with a set of peudo-code integration tests that mock
> out the repos and other moving parts but simulate the various flows,
> transitions, failure states, etc. of all the moving parts.  These could
> be "scheduled" into the child beads that implement the parts that make
> it work so we're not writing tests that are continually failing even
> when a PR should be complete.  The first of these scenario tests would
> be a tracer bullet that also prioritizes the path to get to the full
> test working.

Anchor: "The following are mentioned but not designed here; each becomes
a child bead under wgclw.2:"

---

## Appendix B — Codex adversarial review (full text)

Full output preserved at
`docs/specs/2026-05-23-pdlc-orchestrator-core-codex-adversarial-review.md`.
The concept-area sections above carry the actionable Codex findings with
IDs C-N.M. Two items from Codex Section 2 (Load-Bearing Assumptions) and
all 9 of Codex Section 6 (Stress Tests) appear distributed across the
appropriate concept areas. Codex Section 8 (Things The Spec Gets Right)
is preserved verbatim in Concept Area 21.

---

## Pre-Ultraplan Briefing (Round 1 → ultraplan handoff)

> Inputs to be passed alongside the spec and this ledger when invoking
> `/ultraplan`. Locks in pre-decisions and non-negotiable constraints so
> ultraplan does not waste revision cycles on choices we have already
> made — and does not finesse the contested architectural choices we
> need it to recommend on.

### MVP Boundary — what is IN for the first wgclw.2 implementation pass

- **Objective primitive** with the full attribute list (after CA-2 Phase-2 additions: `is_container`, `priority`).
- **The PDLC lifecycle-stage runner** — every named stage from `CANDIDATE_UOW` through `MERGING`.
- **Holding Place** (`IDEA_RAW` / `IDEA_SHAPED`) — minimum viable handling per the CA-8 decision (ownership choice pending ultraplan recommendation).
- **Single-host CLI tick** (`pdlc tick`) with the async dispatch + reap pattern (Option B).
- **OrchestratorStateRepo** — persistence spine; **versioned** (S-17 non-negotiable). Backend choice pending CA-4 ultraplan recommendation.
- **Session primitive + JobSupervisor contract** (CA-7) — pre-execution authority, not reap-time.
- **Discovery + reconciliation** against the minimum WorkTracker protocol (CA-12, shrunk from 7 domains).
- **Reference bd adapter** validated against the protocol before the revision pass completes.
- **Mechanical gates with pre-strike triage** (CA-9) — separate cognition failures from tooling / reviewer-artifact / flake / config / dependency failures.
- **Terminal-state semantics** with explicit disposition metadata (CA-10).
- **Transition log** (append-only, schema specified per CA-14).
- **Invariant model** section in spec (CA-20).
- **Crash-recovery table** covering the named transition points (CA-5 / C-5.1).
- **Worktree discipline** (CA-18) — branch naming, base-commit pinning, dirty-state detection, cleanup idempotency.

### MVP Boundary — what is OUT (deferred to follow-up beads, do NOT bloat into this revision)

- Distributed / multi-host / remote-runner orchestration (CA-17 / C-5.4) — single-host assumption is explicit.
- `.local` config layering + on-demand config-file creation (S-19 / CA-13).
- Post-MVP re-apply-Agent-Ready-gate on spec-mutation during `TEST_AUTHORING` through `PR_VALIDATION` (S-18 / CA-11).
- Worker-authority sandboxing v2 (containerization beyond worktree-isolation + path allowlists).
- Full audit-forensics layer (hash-chain transition log, tamper model). Basic append-only log is IN; cryptographic layer is OUT.
- Rich `pdlc health` dashboards. Basic stage-histogram + session inventory + recent failure taxonomy are IN.
- Multi-reviewer / codeowner-aware reviewer-state generalization (post-MVP).
- Spec-modularization skill referenced in related-bead R2.1.

### What ultraplan MUST decide (recommend with reasoning — do NOT punt)

- **CA-4** — Choice of storage backend (SQLite-WAL vs Dolt-style versioned store vs other). Versioning is the non-negotiable; ultraplan picks among candidates that meet that bar.
- **CA-8** — Holding-Place ownership: Option A (external HoldingPlace service, stages 1–2 NOT Orchestrator Objectives) vs Option B (orchestrator owns stages 1–2). A hybrid that re-creates the L6/primitive contradiction is unacceptable.
- **CA-12** — Final scope of the minimum WorkTracker protocol: which of the seven domains stay, which move to the orchestrator sidecar, which become explicit v2 protocol expansion.

### Non-Negotiable Constraints

ultraplan **must honor** these without recommending around them:

1. **OrchestratorStateRepo MUST be versioned** (S-17). Backend is open; versioning is not.
2. **Mission alignment**: every revision serves the 85/5/10 operating ratio. Revisions that add human gates without proportional autonomy gains FAIL this filter.
3. **Doctrine**: code-over-prose, Python-over-bash, amalgams-over-conflicts. Logic that needs testing belongs in Python, not Markdown or shell.
4. **No architectural drift into the FSM spec** (`docs/specs/2026-05-19-pdlc-state-machine-design.md`) — this revision pass is scoped to the orchestrator core. FSM-amendment suggestions go to a separate follow-up bead.
5. **Worker authority enforced BEFORE/DURING execution** (CA-7 / C-1.6). Reap-time checks remain but do not replace pre-execution enforcement.
6. **3-Strike pre-triage** (CA-9 / C-7.2) — failure cause is classified BEFORE a strike is charged. Strikes are charged only for cognition failures.
7. **Protocol shrinks to MVP minimum** (CA-12) and validates against the bd reference adapter before this revision completes.
8. **Holding-Place ownership is a decision, not a finesse** (CA-8).
9. **Worktree discipline** (CA-18) — implementation work happens on feature branches in worktrees, never directly on `main`.
10. **Mid-flight reconciliation** (CA-11) — sessions pinned to the `config_hash` they launched under; tracker version-checks on every write; full-reconcile pass per tick is an acceptable correctness fallback to cursor-based discovery (CA-6 / C-1.3).

### Scope-bloat watchdog

Any revision that touches an OUT item above gets pushed back with
`defer-followup, do not include in this revision`. The Round-1 ledger
absorbs the finding; the spec stays in scope.

### Iteration discipline (operator-side)

- One ultraplan iteration cycle per concept-area cluster, not per finding.
- Cap at **3 rounds**. If a contested decision remains after round 3, save the plan to file via Cancel and resolve in a separate human-led conversation before re-engaging.
- Group inline comments by concept area.
- Emoji-react for accept/reject on individual recommendations.
- Reserve inline comments for "rework this section" feedback.

---

## Working notes

- This is the **Round 1** merged feedback. Future review cycles append
  new sections at the bottom (e.g. `## Round 2 Additions`) rather than
  rewriting prior findings — status fields capture resolution history.
- When a finding becomes `applied`, record the commit SHA or diff
  reference in the Status cell so we can audit later.
- When a finding becomes `deferred-followup` or `deferred-child`, record
  the bead ID once filed.
- Cross-cutting decisions that touch multiple concept areas (e.g. the
  Holding Place ownership decision in CA-8) should be promoted to a
  decision record in the spec body once resolved.
