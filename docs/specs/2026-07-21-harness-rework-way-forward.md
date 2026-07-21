# Harness Rework — Way Forward

**Date:** 2026-07-21
**Status:** Agreed in dialog (Scott + Fable 5), pending Scott's review of this document
**Companions:** `SAVEPOINTS/2026-07-20-harness-findings-handoff.md` (diagnosis), `SAVEPOINTS/2026-07-20-pr-baseline.md` (outcome baseline), `SAVEPOINTS/LEFT-OFF-NOTES.md` (raw audit verdicts)

This spec records the decisions from the way-forward dialog that followed the
harness self-obstruction findings. It is the charter (parent doc) for the
rework: child specs are written per slice as each is picked up. All eight open
questions from the findings handoff are resolved here.

The one-sentence version: **the harness of tomorrow replaces prose machinery
with contracts and code, admits nothing without justification, and terminates
every loop — including its own construction.**

---

## 1. Decisions

### Contracts and specs

**D1 — Spec falsifiability contract.** Every spec carries enumerated
acceptance criteria, each expressible as a failing test (red-test-convertible).
An edge-case taxonomy is applied during authoring: for each AC — inverse case,
empty/boundary input, dependency failure, repeated/concurrent invocation,
idempotency. The taxonomy grows from escaped defects: every defect that leaks
downstream is traced to its missing-AC class and added.

**D2 — Decomposition shape.** One spec carries an ordered slice list. Each
slice is the smallest change that flips a defined set of ACs red→green and is
separately mergeable; each slice carries its own ACs and is the unit a
scaffold picks up. Size tripwire (initial, tunable): a spec exceeding 400
lines or 8 slices splits into a parent doc + child specs. Decomposition is the
spec author's deliverable — a spec is not ready until it is decomposed.

**D3 — AC-attack review at the readiness gate.** A foreign (non-Anthropic)
model attacks the AC set before implementation: "name behaviors that satisfy
these ACs while still being wrong." Findings must arrive as proposed ACs
(testable claims about inputs/states), never as concerns. Each proposal is
accepted into the AC set or rejected as out-of-scope; the round terminates.
Enforcement of D1–D3 is author-side (the brainstorming replacement's output
contract; the goals-only escape is deleted) plus a mechanical lint at the gate
(AC-section presence and per-slice AC coverage).

### Plan and execution

**D4 — Scaffold-as-plan.** The prose plan document is deleted as an artifact
class (`writing-plans` dies, unreformed). A frontier model materializes the
plan in the repo: compilable stubs + failing tests translating the slice's
ACs, plus a short dispatch brief (ordering, constraints, worktree-absolute
paths). The executor's job is "make these tests green without changing the
contract."

- **Contract-only rule:** scaffold tests may reference only names in the
  spec's contract (public signatures, CLI verbs, routes, UI affordances).
  Lintable; this is the white-box defense.
- **AC↔test bijection:** ACs carry IDs; tests cite them. Coverage of the AC
  set is checked by script, not judgment.
- **Separation:** the scaffold writer is a fresh-context agent receiving the
  spec only — never the spec-writing session. A foreign model reviews the
  scaffold (bijection, contract-only, taxonomy applied). The spec author
  adjudicates disputes only.
- **Prose deliverables** (skills, docs, config) can't scaffold as red tests:
  the dispatch brief names the mechanical checks that gate completion;
  anything not mechanically checkable rides as advisory review.

**D5 — Foreign eyes sit in review seats, not authoring seats.** Authoring
quality dominates in the writer seat (fresh-context Anthropic frontier);
cross-vendor diversity pays where blind spots correlate — AC-attack, scaffold
review, PR verdict.

**D6 — Plan mode is the default for design sessions.** It is an
interaction guardrail (read-only, converge-before-acting, explicit approval)
at zero context cost. The spec contract defines what the session must produce.

### Review and merge

**D7 — Reviews are self-managed invocations.** Triggered when an artifact
claims readiness — never on every push. Class-specific review contracts (typed
code vs spec vs skill prose). Reviewer prompts carry the contract (artifact
class, ACs to judge against), never the house rulebook — external reviewers'
value is fresh context. Reviewers are instructed to ignore in-repo
intentionality claims; verdicts judge against ACs. Re-review triggers only on
claimed-fix pushes.

**D8 — Verdict artifact schema = Mechanical/Advisory** (adopting the
CONTEXT.md design). Mechanical findings block and must carry a mechanical
artifact (failing test, lint output, broken link). Advisory findings route to
the backlog, never block, and are never re-litigated in the fix loop. Review
exits when a complete round produces zero mechanical findings.

**D9 — The PR is a thin merge vehicle.** Merge eligibility = CI green +
verdict artifact + approval. PR comments cease to be a review medium; a human
comment on a PR is by definition an intervention and routes to escalation. All
machine-posted comments and approvals use the bot App identity, never Scott's
auth. The merge gate requires the verdict artifact — broken review machinery
blocks merges rather than silently passing them.

**D10 — Non-merging PRs park; the machine disengages.** Closed = merged, no
exceptions (dependents key off merge). A work item whose PR won't merge enters
a parked state with a typed reason:

- *Machine-actionable* (CI failure, merge conflict): bounded budget — 2 CI-fix
  attempts, 1 rebase attempt (initial, tunable) — then park with the log.
- *Human-required* (ruleset demands human approval, bot declines, budget
  exhausted): park immediately, zero attempts.

Human verbs on a parked item: re-dispatch (cause fixed) or abandon (PR closed,
item back to ready). A read-only staleness report lists parked items and
reasons — it reports, never acts. Optional backstop: a PR parked > 7 days is
closed and recut fresh from main.

### Platform

**D11 — workcli first; the harness never speaks bd.** The future harness
addresses the tracker exclusively through the `work` facade. Scope to the
pipeline's verb set — mint, ready, claim, park(reason), re-dispatch, abandon,
close-on-merge, dependency edges, containment — with atomicity at the facade
layer (close + close-walk + note is one verb). The Backend seam is the
portability guarantee; one working backend (beads) ships it. GH-issues/Jira
adapters are later work admitted separately. This deletes the bd instruction
surface (plugin rules, quirk lore, multi-call choreography) from agent reach.

**D12 — Tracker reset.** Full export of the current beads DB as a dated,
committed reference; the old DB is archived, not destroyed (close notes and
deferred PDLC scenarios retain harvest value). A new, empty DB holds the new
roadmap; only work admitted under the new bar enters, via `work` verbs
wherever the facade can express the operation — any gap found is a contract
gap found early.

**D13 — prgroom is carved, not finished.** Retain (~15–20%): `gh`/`git`
clients, config, error taxonomy, escalation typing. Delete with their tests:
reply, poll, wait, snapshot, legacy export, and the in-package fix-dispatch
machinery (fixing is the work-loop's job). Never build `verify`/`sweep` —
scaffold red tests superseded them. Add thin: verdict harvester (parse
invoked-review output into the verdict artifact) and merge-eligibility
evaluation. Absorb `abn9.8.33` (classic commit-status), `abn9.8.49` (5xx ≠
auth failure), `j8pdq` (pagination). Delete the skills
`wait-for-pr-comments`, `reply-and-resolve-pr-threads`, `monitor-pr`, and the
contradictory completion-gate text. The audits' "finish verify and cut over"
verdict predates the review-medium decision and is superseded.

**D14 — Grind runtime re-aimed.** `wgclw.30` (event-sourced grind runtime) is
the one live M0 workstream pointed at the future: it becomes the executor loop
of the new pipeline (dispatch scaffold→green workers, bounded budgets, typed
park reasons), not an upgrade to the `orchestrated-grind` skill. Its fit is
verified against its spec before slice scoping (open verification V1).

**D15 — Config homes.** Installer deploys to the standard homes only
(`~/.claude`, `~/.codex`, `~/.gemini`, `~/.config/opencode`), exactly one
target per tool, with deploy receipts and prune-on-install. `home2` keeps
only its hand-managed `settings.json` (dual-subscription isolation needs
nothing more).

### Surface and admission

**D16 — Admission bar and budget.** The always-on instruction surface
(everything loading before the user types) is capped at **10k tokens**,
enforced mechanically by the installer at deploy time. Skill bodies load on
invoke and are capped at **2k tokens** each — a skill needing more delegates
to code. Every deployed rule/skill/command carries an admission record: the
failure it prevents, what it costs, and what observation would remove it.
Nothing enters by default or nostalgia.

**D17 — User-scoped AGENTS.md is zero-based.** A line earns always-on status
only if all four hold: universal across projects; not model-default behavior;
not owned by pipeline code/contract; fits the ~800-token sub-budget.
Survivors from the old template: the L0–L3 laws, the decision matrix
(compressed), git-safety hard lines, state-the-decision-not-history. The
"every correction mints a rule" hook (`self-improving-agent`) is deleted —
corrections land in memory and become rules only through the admission bar.
Draft in Appendix A. The DYNAMIC-INCLUDE assembly machinery is reassessed
once content shrinks below what justifies it.

**D18 — Skills strategy: import shapes, own contracts, admit per-item.**
Never adopt a set wholesale. Initial admissions from Pocock (each with a
graft): `grilling` (+AC/taxonomy exit criterion) as the brainstorming core;
`to-spec` (+AC section and slice list as output contract); `to-tickets`
(aimed at `work` verbs); `tdd` (executor-side); `code-review`'s two-axis
shape (pattern feeds the verdict design, not adopted as a skill);
`writing-great-skills` + the user-invoked/model-invoked axis as catalog
design rules. Skipped, re-admissible later: `ask-matt` (a catalog small
enough to need no router is the goal), `wayfinder` (autopsy scheduled when
the parent-spec path is designed), `triage`,
`improve-codebase-architecture`. This discharges `wgclw.24`/`.25`.

### Measurement and sequencing

**D19 — Instruments.** Bot App identity separates human from machine PR
comments (the interventions-per-PR proxy). Pre-PR cycle time is measured from
work-item timestamps (claim → PR-open). Size distributions (spec lines, slice
counts, PR diff lines) are tracked as erosion tripwires — watched, never
targeted. PR diff tripwire (initial, tunable): > 800 changed lines excluding
mechanical churn requires an explicit override.

**D20 — Roadmap disposition.** M0 closes as superseded, not finished — its
live surface almost entirely hardens machinery this spec deletes. M3 pauses
until the minimal readiness gate (D1–D3) exists. The WIP cap of 2 is honored.
A new milestone — **Harness rework** — carries this spec as its charter and
the ACs below as its acceptance section; the D13/D14/D18 keepers migrate into
it with admission records.

---

## 2. Acceptance criteria

ACs carry IDs; slice work cites them.

### Structural (checkable at any time)

- **AC1** Installed always-on surface ≤ 10k tokens; the installer fails a
  deploy that exceeds it.
- **AC2** A deploy-time audit finds zero pairs of deployed artifacts asserting
  conflicting facts about the live workflow.
- **AC3** 100% of deployed rules/skills/commands carry a complete admission
  record.
- **AC4** A new spec without an AC section and per-slice ACs fails the spec
  lint.
- **AC5** `wait-for-pr-comments`, `reply-and-resolve-pr-threads`,
  `monitor-pr`, `writing-plans`, and the prgroom deleted modules are absent
  from `src/` and from every deploy target; no deployed text references them.

### Outcome (against the 2026-07-20 baseline, over the termination window)

- **AC6** Config-prose PRs converge like typed code: median bot-review rounds
  ≤ 1 and median fix-commits-after-first-review ≤ 1 (baseline: 2 and 2;
  typed-package baseline: 1 and 0).
- **AC7** Every PR in the window has machine comments/approvals under the bot
  identity and human comments separable — the interventions-per-PR instrument
  reports a number.
- **AC8** Pre-PR cycle time (claim → PR-open) is reported for every work item
  in the window.

### Termination

- **AC9** When AC1–AC5 hold and **10 consecutive PRs** flow through the new
  pipeline meeting AC6–AC8, the Harness-rework milestone closes and harness
  work loses its standing track — it competes in the normal backlog
  thereafter.

Outcome ACs are trend evidence over the window, not per-PR gates — the PR
stream is low-n and per-PR gating invites Goodharting.

---

## 3. Ordered slice list

Each slice gets its own child spec (with per-slice ACs) when picked up;
ordering is by dependency, and S2/S3/S4 can run in parallel.

- **S1 — Tracker reset.** Export + archive the old DB; open the new DB; mint
  the Harness-rework milestone carrying this spec; re-mint the D13/D14/D18
  keepers with admission records. (Discharges D12, part of D20.)
- **S2 — workcli completion.** Gap-audit implemented verbs against the D11
  pipeline set (V2), then close the gap; atomic composite verbs; park/reason
  semantics. (D11)
- **S3 — Installer.** Single-home deploy + receipts + prune; surface-budget
  enforcement (AC1); admission-record schema + check (AC3). (D15, D16)
- **S4 — User AGENTS.md zero-base.** Ship Appendix A; delete the
  INSTRUCTIONS.md mountain; reassess DYNAMIC-INCLUDE. (D17)
- **S5 — Spec contract.** Admit + graft `grilling`/`to-spec`; edge-case
  taxonomy; spec lint (AC4); delete the old brainstorming skill's goals-only
  path by deleting the skill. (D1, D2, D18)
- **S6 — Review contracts.** Verdict schema (D8); class-specific review
  contracts; AC-attack contract (D3); self-managed invocation + bot identity
  (D7, D9, AC7).
- **S7 — Scaffold pipeline.** Scaffold discipline + dispatch-brief format;
  contract-only lint; AC↔test bijection check; scaffold-review contract.
  (D4, D5)
- **S8 — prgroom carve.** Delete + retain per D13; verdict harvester;
  merge-eligibility evaluation; absorb the three foundation bugs. (D13, AC5)
- **S9 — Executor loop.** Re-aim the grind runtime as the pipeline executor
  (post-V1); park/escalate wiring through `work` verbs; staleness report.
  (D10, D14)
- **S10 — Instruments.** Pre-PR cycle-time reporting (AC8); size-distribution
  tracking; the interventions number (AC7). (D19)
- **Close-out:** the AC9 observation window, then milestone close.

### Open verifications (first task of their slice)

- **V1** (before S9): read the grind-runtime spec/code; confirm the
  executor-loop fit claimed in D14, or re-scope S9.
- **V2** (S2 first task): inventory workcli's implemented verbs against the
  D11 set; the July 4 contract spec predates this rework and is audited, not
  assumed.
- **V3** (S1 first task): confirm bd export/import + dolt archive mechanics
  preserve close notes and dependency edges in the frozen reference.

---

## Appendix A — Draft user-scoped AGENTS.md (zero-based)

~450 tokens. Every line passed the D17 admission test.

```markdown
# AGENTS.md

<laws>
Precedence: L0 > L1 > L2 > L3. Surface conflicts; never silently resolve them.
- L0 Codebase: refuse changes that cause architectural drift, duplication, or design violations
- L1 Safety: no vulnerabilities or bugs; challenge incorrect assumptions about the code — don't just agree
- L2 Obey: follow instructions unless L0/L1 is violated — then propose alternatives
- L3 Clarity: readable, testable, consistent code
</laws>

<decisions>
Facing an unknown, classify then act:
- Verifiable fact → verify it yourself (code, docs, git, tests). Never ask.
- In-scope choice, or an architectural question with a clear best option → decide and proceed. Never ask for validation.
- Genuinely balanced architectural trade-off, or the option space needs human context → escalate, with your ranking.
- Instructions conflict beyond what L0–L3 precedence resolves → escalate, surfacing both sides.
Narrow "when in doubt, do the safe thing" rules (merge authorization, destructive git) override this matrix on their domain.
</decisions>

<hard-lines>
- No hard resets, force pushes, amends, or `git clean -fd` without explicit approval.
- Creating a PR is not authorization to merge. Absent an explicit instruction or a configured rule-based policy, do not merge.
- Before deleting or overwriting work you didn't create, look at it; surface contradictions instead of proceeding.
</hard-lines>

<conventions>
- Minimal, surgical edits: touch only what the task requires; nothing speculative.
- Artifacts state the current decision, not its history — git is the changelog.
- If the repo has a CONTEXT.md glossary, use its terminology.
</conventions>
```
