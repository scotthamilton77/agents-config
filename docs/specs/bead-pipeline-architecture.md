# Bead Pipeline Architecture

This document is the canonical target architecture for the bead-implementation pipeline in agents-config. It is self-contained: a reader does not need to consult tracking beads to understand the architecture. Beads in the `agents-config-7bk` epic and its siblings track work toward implementing what is described here; the corpus-to-bead map in section 11 records ownership for future maintenance.

## 1. Goals (meta-intent)

Five pillars define what the pipeline must deliver. Every architectural decision in subsequent sections traces back to one or more of these.

- **Shift-left.** Human interaction concentrates in brainstorming. The brainstorm phase captures not only what to build but also post-implementation policy: which acceptance criteria are machine-verifiable, whether the bead may auto-merge, what depth of code review applies. Pushing these decisions back to brainstorm time means the human is engaged when context is fresh, and the agents downstream operate with full policy guidance.

- **Shift-right.** Human-only acceptance testing at the tail of the pipeline blocks merge until processed. Acceptance criteria flagged as requiring human judgment (visual layout, UX feel, semantic content quality) spawn dedicated child beads at brainstorm time; the source bead cannot close until those children close, and the merge cannot fire until the source bead closes. This is enforced by two gates working together: a PR-state clean-check in the `merge-or-handoff` stage (gate 1), and a source-bead-closure gate inside the `merge-and-cleanup` formula (gate 2). See section 4.3 for the two-gate model.

- **Escape hatch.** Mid-pipeline human involvement is reserved for genuine intervention: a design flaw uncovered by implementation, agents blocked without a defensible path forward, temptation toward dangerous hacks. Every stage may flag-human cleanly. Resumption after human intervention is itself an automated diagnostic step (see `resolve-human-bead` in section 7).

- **Continuous loop.** The ideal steady state is a shell driver running `bd ready → claim → produce → finish → repeat` autonomously while the human spends time brainstorming new beads and verifying finished ones. The pipeline must be resilient to crashes, restartable, and free of unbounded session growth.

- **Just-enough cost.** The pipeline pays just enough model processing cost (model choice + effort level) to reduce rework when models make bad choices. Under-spending creates rework loops that cost more than the saved tokens; over-spending burns tokens for no quality gain. Section 9 specifies the per-stage default cost profile and the empirical mechanism to calibrate it.

## 2. Pipeline overview

The pipeline is structured as three cooperating layers.

1. **External shell driver.** A process outside Claude Code polls `bd` for ready stage-beads in active molecules and spawns one `claude -p` process per ready stage. The driver respects the molecule DAG for sequencing and recycles resources cleanly across beads. It replaces the `run-queue` skill, whose single-session model causes unbounded context growth across many beads.

2. **Per-stage `claude -p` orchestration.** Each `claude -p` invocation drives exactly one stage of one bead's molecule and exits. Inside the invocation, the orchestrator MAY dispatch one level of subagents AND fire slash commands. Stable session-ids (UUIDv5 derived from bead-id and stage role-name) enable transparent resumption across crashes or driver restarts.

3. **bead/molecule + filesystem persistence.** All state crossing stage boundaries lives in `bd` (beads, molecules, labels, notes) or the filesystem (worktree, commits, PR). Nothing crosses via LLM context — every stage reads its inputs fresh from the substrate.

```
[shell driver poll loop]
     │
     │ bd ready --label implementation-ready
     ▼
preflight     →  red-tests  →  green-loop  →  quality-sweep  →  verify-ac
(sonnet-high)*   (sonnet)      (opus)         (haiku)            (haiku)
                                                              │
                                                              ▼
                                              create-pr  →  review-cycle  →  merge-or-handoff
                                              (haiku)       (sonnet)         (haiku)

* For bug-class beads, a `diagnose` stage runs between preflight and red-tests.

State substrate (read by every stage):
   - molecule labels: worktree-path-*, pr-url-*, foreign-eyes-degraded:n/N
   - bead labels:      formula-<name>, auto-mergeable, review-level:*,
                       iteration-cap-*, coverage-threshold-<n>, human, merge-ready
   - bead/step notes:  RALF-IT-ITER:n/MAX, REVIEW-BATCH:n/MAX, AC validation report
   - filesystem:       worktree, feature branch, committed tests, PR
```

**Why per-stage and not single-context.** Two structural constraints argue for per-stage orchestration. First, Claude Code's runtime forbids subagents from spawning subagents and from firing slash commands; a per-stage process model lets each stage's orchestrator dispatch subagents and slash commands directly without nested-spawn requirements. Second, a single-session model running across many beads grows context unboundedly, increasing token cost per bead processed and degrading agent attention. Per-stage processes bound context strictly at one stage's scope. Single-context mode is tracked separately (section 10) as a sibling exploration.

## 3. The stages

Stages are referenced by role name in all implementation surfaces (labels, formula step IDs, slash commands, code identifiers). Numbering is design-discussion vocabulary only and MUST NOT bleed into implementation.

The execution sequence for feature-class beads is: `preflight` → `red-tests` → `green-loop` → `quality-sweep` → `verify-ac` → `create-pr` → `review-cycle` → `merge-or-handoff`. Bug-class beads insert a `diagnose` stage between `preflight` and `red-tests`.

### preflight

**Purpose.** Spec validation, formula selection, worktree creation. A fresh-eyes adversarial check on the implementation-ready bead — not a redo of brainstorming, but a defense-in-depth pass before committing any worktree resources.

The orchestrator selects the formula by reading the bead's `formula-<name>` label, falling back to per-bead-type defaults: feature → `implement-feature`, bug → `fix-bug`, task → `implement-feature`, chore → `implement-feature`, epic → flag-human (epics decompose into children; there is no formula for an epic itself), unknown formula label → flag-human. It verifies the project quality-gate config and marks the `quality-sweep` stage skippable if no checks beyond RALF-IT's defaults exist. It verifies a standard coverage report location exists; if absent or empty AND `[coverage].applicable` is true (or absent), flag-human. When `[coverage].applicable = false`, coverage is opt-out and the report-location check is skipped.

The pour-vs-worktree ordering is critical: pour the formula FIRST, then create the worktree. If pour fails, no worktree is created and there is nothing to clean up. If worktree creation fails after pour, `bd mol squash <mol-id>` the molecule with the failure summary and flag-human; never leave a poured molecule without a worktree.

**Definition of Done.** Poured molecule + worktree exists + `worktree-path-*` label stamped on the molecule. OR `human` label + structured gap-note + (if pour completed) molecule squashed.

**Orchestrator agent + model + effort.** `claude-sonnet-4-6`, effort `high`. The architectural decisions made here govern the entire pipeline run; bad choices corrupt every downstream stage. Stage is short, so absolute cost of effort:high is small.

**Preloaded skills.** None specific; the orchestrator works from the bead description and label inspection.

**Subagents dispatched.** None.

**Foreign-CLI invocations.** None.

**State-out.** Poured molecule; `worktree-path-*` label on molecule (encoding per section 5.3).

**Idempotent re-entry.** Structurally idempotent. On re-entry, the orchestrator checks whether the molecule exists (via the `for-bead-<bead-id>` linkage label), whether the worktree path decodes to an existing git worktree, and skips work already complete.

**cwd contract.** Repo root (the worktree does not yet exist; preflight creates it).

### diagnose (bug-class only)

**Purpose.** Root-cause investigation for bug-class beads. Produces a root-cause note before any tests are written, ensuring tests target the cause, not the symptom.

**Definition of Done.** Root-cause note appended to the diagnose step-bead's notes; identified cause is consistent with the bead's reported symptoms; if root cause exceeds the bead's stated scope, flag-human.

**Orchestrator agent + model + effort.** `claude-sonnet-4-6`, effort `high`. Bug investigation is novel reasoning over an unknown surface; getting it wrong wastes downstream stages on the wrong fix.

**Preloaded skills.** `superpowers:systematic-debugging`, `superpowers:root-cause-tracing`.

**Subagents dispatched.** None at the orchestrator's discretion; debugging skills guide the work directly.

**Foreign-CLI invocations.** None.

**State-out.** Root-cause note in step-bead notes.

**Idempotent re-entry.** Filesystem state and step-bead notes reflect prior progress; on re-entry the orchestrator inspects the notes and continues from where it left off.

**Stage scheduling.** Whether `diagnose` runs is determined by the formula poured upstream of preflight, not by a runtime check. The `fix-bug.formula.toml` step list includes `diagnose` at position 2 (between `preflight` and `red-tests`); the `implement-feature.formula.toml` step list does NOT include `diagnose`. `implement-bead`'s formula-selection step (read `formula-<name>` label, fall back to per-bead-type defaults) determines which formula is poured BEFORE preflight runs; preflight itself only validates that the pour has already happened. Per-bead-type fallbacks: bug → `fix-bug`; feature → `implement-feature`; task → `implement-feature`; chore → `implement-feature`; epic → flag-human (epics decompose into children; there is no formula for an epic itself).

**cwd contract.** Worktree path decoded from molecule's `worktree-path-*` label.

### red-tests

**Purpose.** TDD red phase — write failing tests covering the AC before implementation. Each test is reviewed by two reviewers (one Claude, one foreign) to catch test-only methods leaking into production, mocking of unverified dependencies, missing edge paths, and white-box coupling.

The orchestrator dispatches a `bead-implementor` subagent to write the tests, then runs the dual-reviewer protocol. The Claude reviewer invokes the `test-review` skill with a checklist covering AC coverage, test-only-method drift, dependency mocking discipline, edge/error paths, white-box minimality, and single-responsibility unit-test structure. The foreign reviewer invokes Codex (`gpt-5.5` default) for adversarial review of added tests in context of surrounding tests, flagging redundant or contradictory tests.

The iteration cap defaults to 2 (override via `iteration-cap-red-tests-<n>` label). At the cap, if reviewers disagree, write a disagreement note to state-out — issues may resolve in `green-loop` or surface in PR comments. Escalate human ONLY if BOTH reviewers agree on a critical-or-major design flaw.

**Reviewer disagreement tiebreak.** When one reviewer flags a finding as critical/major and the other does not, the more-severe rating wins UNLESS the silent reviewer explicitly approved that aspect. If neither silently approved nor explicitly flagged, the finding stands at the higher severity. The orchestrator records this resolution in state-out so the implementor addresses it in `green-loop`.

When `review-level:none` is set on the source bead, the test-review skill and Codex adversarial review subagents skip; tests are still WRITTEN (TDD red phase is correctness substrate, not review depth), but no AI review of the tests runs.

**Hard-escalate + auto-reroute.** This stage has a canonical escalate predicate evaluated FIRST in both formulas, before any reviewer dispatch. **Trigger A** (both `implement-feature` and `fix-bug` paths): if `[gates].test == ""` in `project-config.toml`, the project has no test runner. **Trigger B** (`implement-feature` ONLY): if the bead's `acceptance_criteria` field (per §4.1's canonical AC parser, NOT `description`) has zero `[m]`-classified lines, there is nothing for tests to assert. Apply the canonical line parser (`^\[(m|h)\]\s(.*)$`; untagged lines default to `[m]` per §4.1's backwards-compat rule) to count `[m]` lines. The literal prefix `red-tests escalate: ` is grep-able for verify-ac groundedness and for the green-loop defense-in-depth check. Bug-class asymmetry: `fix-bug` deliberately omits Trigger B because a failing regression test is "proof that the bug cannot silently return"; allowing zero-`[m]` reroute on the bug path would silently waive that invariant — a bug bead with zero `[m]` AC lines and a non-empty `[gates].test` is a brainstorm gap, not an escalate condition. AC tagging + project `[gates].test` are the only signals; there is no per-bead opt-IN/opt-OUT label.

When any trigger fires, the formula executes the **reroute protocol**: clone the source bead (inherit `title`, `description`, `acceptance_criteria`; prepend a redirect warning to the cloned description; do NOT inherit `notes`); stamp the new bead with `formula-docs-only` and `implementation-ready`; add a `discovered-from` dep edge from the new bead to the original; mark the original with `REROUTED-TO:<new-id>`, append a reroute note, close any `merge-gate` child, then close the original; finally `bd mol burn` the current molecule. The `run-queue` in a separate session picks up the new bead organically and pours `docs-only` on it. No `human` label is applied; no human action is required. This auto-reroute supersedes the soft opt-out described in earlier revisions of this document.

**Definition of Done.** Tests committed to feature branch; both reviewers approve "shippable" state (or iteration cap reached with disagreement note recorded). OR step rerouted per the canonical escalate predicate above (original closed with `REROUTED-TO`, new bead created with `formula-docs-only` + `implementation-ready`, current molecule burned, `red-tests escalate: ...` note recorded on step-bead).

**Orchestrator agent + model + effort.** `claude-sonnet-4-6`, effort `medium`.

**Preloaded skills.** `superpowers:test-driven-development`, `writing-unit-tests`, `testing-anti-patterns`.

**Subagents dispatched.** `bead-implementor` (sonnet) for test writing; `test-review` skill invocation by the orchestrator directly (not a subagent).

**Foreign-CLI invocations.** Codex `gpt-5.5` per iteration for adversarial test review. Subject to `z7a` foreign-eyes degradation tracking (section 7).

**State-out.** Committed tests on feature branch; reviewer agreement summary in step-bead notes.

**Idempotent re-entry.** Filesystem state (committed tests) and step-bead notes reflect prior progress. Re-entry re-evaluates state and continues.

**cwd contract.** Worktree.

### green-loop

**Purpose.** Implementation (green phase) via RALF-IT. The orchestrator invokes the RALF-IT skill with `MAX_ITERATIONS=5` (override via `iteration-cap-green-loop-<n>` label, the SOLE override path).

**Defense-in-depth re-evaluation of red-tests escalate triggers.** Before any RALF-IT dispatch, the formula re-runs the red-tests escalate predicate independently — same logic, same `acceptance_criteria` field counting (Trigger A on both paths; Trigger B on `implement-feature` only). If any trigger fires here, the molecule should not have advanced from red-tests; the stage stamps `human` on BOTH the source bead and the green-loop step-bead, appends a defense-in-depth note, and exits. This path is unreachable in normal operation because the red-tests reroute burns the molecule before green-loop runs; it catches manual molecule resumes that bypass red-tests, ensuring the unsatisfiable-DoD contract never silently propagates downstream.

RALF-IT handles implementation subagent dispatch, the quality gate (build/typecheck/lint/test) between every iteration, foreign-eyes review (Codex on iter 1, Gemini on iter 2, pure Claude fresh-eyes on iter 3+), anti-bias rules (the eyes-subagent is not told which iteration it is and is given the original spec, not a prior summary), and the final review pass.

**Foreign-eyes degradation handling.** When foreign-CLIs are unavailable (auth expired, quota exhausted, network failure), RALF-IT records the degradation per iteration in step-bead notes (`FOREIGN-EYES-ITER-<n>: codex=<status>, gemini=<status>`). At end of loop, if foreign-eyes were degraded in 2 or more of N iterations, RALF-IT flag-humans and does not mark the stage complete. A `foreign-eyes-degraded:<n>/<N>` label is stamped on the source bead; the eventual PR description includes a foreign-eyes status section so reviewers know which iterations actually had cross-tool review. The threshold is absolute (≥2), not proportional to the iteration cap: two unverified iterations is structurally unacceptable regardless of cap, because anti-bias is the JUSTIFICATION for foreign-eyes — below that bar, RALF-IT is a self-review loop branded as adversarial.

**Coverage.** The threshold comes from `[coverage].threshold` in `project-config.toml` (default 80%) or the per-bead `coverage-threshold-<n>` label override. The threshold is honored only when `[coverage].applicable` is true or absent; when `[coverage].applicable` is explicitly false (docs-only repos, config repos, etc.), coverage is not a quality gate and the threshold is bypassed. Coverage is an indicator, not a quality measure: the implementor and reviewers focus on quality of tests, not metric satisfaction. Watch for new branches introduced by implementation choices not covered by red-tests.

**Unverifiable/unimplementable triggers** (flag-human + abort): AC bullet requires resources the chunk cannot access (third-party API, secret, hardware); AC bullet contradicts an earlier AC bullet; implementation requires architectural changes outside the bead's stated scope; tests pass in isolation but not in integration (root cause outside bead's scope); no standard coverage report location when `[coverage].applicable` is true or absent (also caught at preflight).

State-out acknowledges any red-tests deferred issues explicitly: invalidated, resolved, or surfaced in PR.

When `review-level:none` is set, the per-iteration code-review and simplify subagent dispatches inside RALF-IT skip (RALF-IT's own quality gate continues to run).

**Adversarial-codex sub-step.** When `review-level:deep` is set on the source bead, green-loop's iteration includes an additional adversarial review pass invoking `/codex:adversarial-review --model gpt-5.4` after the per-iteration quality gate. Otherwise this sub-step self-skips. It is a conditional sub-component INSIDE green-loop, not a peer stage; the skip matrix in section 4.2 governs its activation.

**Definition of Done.** RALF-IT reports complete; tests green; coverage meets target (when `[coverage].applicable` is true or absent); build/typecheck/lint pass.

**Orchestrator agent + model + effort.** `claude-opus-4-7`, effort `medium`. The RALF-IT controller is opus by skill frontmatter; the synthesis decisions ("converge or loop?") are the highest-leverage in the pipeline. Medium effort is sufficient because the synthesis is bounded, not novel design.

**Preloaded skills.** RALF-IT methodology embedded in the controller.

**Subagents dispatched.** `bead-implementor` (claude-sonnet-4-6, effort: high on iteration 1, effort: medium on iterations 2-N per agents-config-7bk.15 TR3) per iteration for implementation work; `quality-reviewer` (claude-opus-4-7, standard 200K context per-iteration runs; claude-opus-4-7[1m] for the final review pass on the full bead diff) per iteration; pure-Claude fresh-eyes subagent on iter 3+. Per-iteration `simplify` skill invocation is dropped in favor of running `simplify` once at the final review pass.

**Foreign-CLI invocations.** Codex `gpt-5.5` on iter 1; Gemini (`gemini -p "" --approval-mode plan -o text`) on iter 2. Foreign-CLI model selection per stage is a per-stage implementation decision deferred to empirical calibration (see section 9.2); the architectural commitment is to foreign-eyes presence at iters 1-2, not to specific model versions. Defaults are configurable via `[foreign-cli]` in `project-config.toml` (section 5.1).

**State-out.** RALF-IT final report in step-bead notes; filesystem (committed implementation; green build/test). `RALF-IT-ITER:<n>/<MAX>` marker persisted after each iteration.

**Idempotent re-entry.** RALF-IT reads the `RALF-IT-ITER:` marker on re-entry (default 0 if absent) and resumes at iteration `<n>+1`. The iteration cap counts toward the global cap regardless of how many `claude -p` processes participated. The marker is written AFTER an iteration completes, so a crash mid-iteration leaves the marker at the prior value; re-entry retries the failed iteration.

**cwd contract.** Worktree.

### quality-sweep

**Purpose.** Global quality sweep across the entire project (not just RALF-IT's changed files). Skippable when preflight has marked it so (project-config.toml introduces no checks beyond RALF-IT's gates).

**Coverage.** quality-sweep does not separately enforce a coverage threshold; coverage gating, if any, lives in green-loop's Definition of Done and is conditional on `[coverage].applicable`.

The order is fixed: lint auto-fixes FIRST (`[lint-autofix].command`), then build/typecheck/lint, then static-analysis (semgrep, depcheck, etc., from `[static-analysis]`), then tests. The stage ALWAYS ends with build + tests after any code changes — this guarantees `verify-ac` starts on green.

Auto-fix vs. flag-human: auto-fix unless issues betray a design flaw requiring fundamental design changes. The orchestrator uses judgment based on the size of the fix.

When `review-level:none` is set on the source bead, the entire stage skips.

**Definition of Done.** All gate commands exit zero (or stage skipped per preflight assessment / review-level:none).

**Orchestrator agent + model + effort.** `claude-haiku-4-5`, effort `medium`. The work is mostly shell-out; the orchestrator's job is decide-skip-vs-run plus interpret exit codes.

**Preloaded skills.** None specific.

**Subagents dispatched.** None typically; static-analysis tools are shell-invoked.

**Foreign-CLI invocations.** None.

**State-out.** Filesystem (green build); step-bead notes record outcomes.

**Idempotent re-entry.** Re-running re-evaluates state and runs only what is not already green.

**cwd contract.** Worktree.

### verify-ac

**Purpose.** Mechanical AC matching. The orchestrator validates each `[m]`-tagged AC bullet against worktree state by dispatching `bead-verifier` (haiku, evidence-only) subagents to run shell-runnable witnesses and collect output. `[h]`-tagged AC bullets are NOT validated by this stage; instead, brainstorm-bead's finalize step has already spawned human follow-up child beads for them, which are tracked separately.

Additional functional/UI tests from `[functional-tests]` in `project-config.toml` (e2e, UI tests) run here. Validation report persists to BOTH the bead's notes AND the eventual PR description.

If functional tests fail at this stage: create one bug bead per failure, flag each as `human`-needed, note in PR comments. Do NOT loop back; do NOT auto-revert. The molecule continues to `create-pr`.

When `review-level:none` is set, the entire stage skips.

**Definition of Done.** Every mechanical AC bullet has explicit witness evidence; human-review bullets have follow-up beads filed (work done at brainstorm-time finalize, but verify-ac confirms presence).

**Orchestrator agent + model + effort.** `claude-haiku-4-5`, effort `medium`. The work is templating: for each `[m]` AC line, decide which command witnesses it; collect output; assemble report.

**Preloaded skills.** None specific.

**Subagents dispatched.** `bead-verifier` (haiku, low effort) per `[m]` AC bullet for shell-runnable witness collection.

**Foreign-CLI invocations.** None.

**State-out.** Validation report appended to bead notes; new bug bead refs (if any) recorded.

**Idempotent re-entry.** Re-running re-evaluates and continues from where the prior pass left off.

**cwd contract.** Worktree.

### create-pr

**Purpose.** Create the PR and persist its URL to the molecule.

The orchestrator invokes the `superpowers:finishing-a-development-branch` skill. The PR description includes: bead reference and AC, RALF-IT iteration summary, verify-ac validation report, bug beads filed during verify-ac, human-required AC follow-up bead references, and the foreign-eyes status section (per `z7a`).

PR creation failure flag-humans cleanly with the worktree intact.

**Definition of Done.** PR exists; URL persisted as `pr-url-*` label on the molecule (symmetric with `worktree-path-*`).

**Orchestrator agent + model + effort.** `claude-haiku-4-5`, effort `medium`. The work is `gh pr create` plus structured PR-body composition.

**Preloaded skills.** `superpowers:finishing-a-development-branch`.

**Subagents dispatched.** None.

**Foreign-CLI invocations.** None.

**State-out.** `pr-url-*` label on molecule; bead notes updated with PR reference.

**Idempotent re-entry.** Re-running queries `gh pr view` first. If a PR exists for the branch and is OPEN, skip creation and persist the URL idempotently. If a PR exists and is CLOSED (closed by a human or bot between runs), flag-human; do NOT auto-reopen and do NOT create a new PR — a closed PR is a signal that human judgment intervened, and the resume path must go through `resolve-human-bead`.

**cwd contract.** Worktree.

### review-cycle

**Purpose.** Long-running PR-review cycle. The orchestrator invokes the `wait-for-pr-comments` skill, which polls Copilot via background script (zero Anthropic tokens during the wait), classifies each comment as FIX/SKIP/ESCALATE, dispatches per-comment fix subagents, pushes combined commits, then chains internally to `reply-and-resolve-pr-threads` to reply to every thread and resolve FIXED ones via GraphQL.

One iteration equals one outbound reply-batch: poll PR until new review activity or timeout, address all open FIX-class threads in one commit + reply pass, push, mark threads resolved on GitHub. The cap counts batches, not polls.

Iteration cap defaults to 5 batches with early exit when no remaining FIX-class items. Override via `iteration-cap-review-cycle-<n>` label.

Exit conditions are configurable per bead: `review-exit-copilot-only` (implicit when no `review-exit-human-approvers-<n>` label is present — exit when Copilot review completes; ignore human-approver count) or `review-exit-human-approvers-<n>` (require N human approvers in addition to Copilot; mutually exclusive with copilot-only).

When `review-level:none` is set, the stage skips entirely.

**Definition of Done.** Every review thread has a reply; FIXED items resolved on GitHub; no in-flight FIX work.

**Orchestrator agent + model + effort.** `claude-sonnet-4-6`, effort `medium`. Per-comment classification and reply composition; cost scales with comment volume.

**Preloaded skills.** `wait-for-pr-comments` (which chains to `reply-and-resolve-pr-threads`).

**Subagents dispatched.** Per-comment fix subagents (sonnet) for FIX-class items.

**Foreign-CLI invocations.** None.

**State-out.** PR threads resolved; commits pushed; `REVIEW-BATCH:<n>/<MAX>` marker persisted in step-bead notes.

**Idempotent re-entry.** Reads `REVIEW-BATCH:` marker on re-entry; PR thread state on GitHub is the source of truth, so the counter is just for cap enforcement. If the PR is CLOSED on re-entry (closed by a human or bot mid-cycle), flag-human; do not poll. Closed PRs require human judgment for resume.

**cwd contract.** Worktree.

### merge-or-handoff

**Purpose.** Either auto-merge the PR or hand off to the human, based on the `auto-mergeable` label and a two-gate enforcement model.

**Gate 1 — PR-state clean-check.** The orchestrator first evaluates: zero open Copilot review threads, zero open human-author review threads, all CI checks green, and a 5-minute quiet window with no new comments or review activity. On `wait-for-pr-comments` timeout, the clean-check is treated as NOT clean — better to ask than ship unreviewed. Gate 1 decides whether the auto-merge path may proceed (and pour merge-and-cleanup); it does NOT itself check `[h]` follow-up children, because those are gated downstream.

**Gate 2 — source-bead-closure gate inside the merge-and-cleanup formula.** The merge-and-cleanup formula contains a gate-step that blocks on source-bead closure. The source bead can only close when ALL children close, including `[h]` follow-up children (created at brainstorm-time per section 4.3) AND the `merge-{source-id}` child (also created at brainstorm-time finalize per section 4.3, closes when the merge action completes as the FINAL action of the merge step in merge-and-cleanup). Gate 2 is the enforcement point for shift-right: the merge action cannot fire while any `[h]` follow-up child is still open, AND the merge action's completion is what permits the source bead to close at all.

The two gates ask different questions. Gate 1: "is this PR ready to merge from a review/CI perspective?" Gate 2: "have ALL prerequisites for source-bead completion been met (including human verification)?" Together they enforce shift-right.

The `merge-{source-id}` child bead is filed by **brainstorm-bead's finalize step** alongside the `[h]` follow-up children — not at merge-and-cleanup pour time. Filing the child at finalize ensures the I2 close-walk's "all children closed" check has access to the merge child the moment any `[h]` child closes, regardless of when merge-and-cleanup is poured. The merge child is closed by the merge step in merge-and-cleanup as its final action. See section 4.3 for the finalize-step semantics.

**Auto-merge path** (`auto-mergeable` label present AND clean-check returns clean): pour `merge-and-cleanup`, drive it. Cleanup includes branch deletion (local + remote), worktree removal (decoded from molecule's `worktree-path-*` label), and the parent-chain close-walk. The merge step re-runs the clean-check immediately before the merge call to catch comments arrived between the last review cycle and merge time.

> **`merge-and-cleanup` MUST be `phase = "liquid"`.** Vapor molecules are session-scoped and do not survive across `claude -p` invocations or driver restarts. The two-gate model requires the merge-and-cleanup molecule to PERSIST while `[h]` follow-up children are verified by the human (which can take hours to days). A vapor molecule disappears between sessions; the gate-step + `merge-{source-id}` child cannot survive on a vapor substrate. Vapor phase is incompatible with the two-gate model.

**Hand-off path** (default — `auto-mergeable` absent OR clean-check returns dirty): the original bead transitions to bd status `open` and is stamped with two labels: `merge-ready` (the discriminator telling the human why the bead is on their queue) and `human` (the human-flag protocol marker that surfaces it via `bd human list`). The bead does NOT close until the human runs `/merge-and-cleanup`, which (a) merges the PR, (b) executes the merge-and-cleanup formula's cleanup actions, and (c) closes the bead with the parent-chain close-walk.

**I1 invariant exception (deliberately documented).** The hand-off path transitions the original bead from `in_progress` back to `open`. This appears to violate the I1 claim-walk invariant ("mark in_progress when work begins"). It is deliberate: by the merge-or-handoff hand-off path, all automated work is complete; the bead is blocked on a human action. Returning to `open` keeps the bead visible to standard `bd ready` query semantics, but the `human` label gates `bd ready` exclusion (so it surfaces only in `bd human list`), and the `merge-ready` label tells the human why. Re-claim by an automated agent is prevented by the `human` label, not by status.

**Definition of Done.** Appropriate path executed; if auto-merge path, PR merged + branches deleted + worktree torn down + parent-chain closed. If hand-off path, bead status `open` + `human` and `merge-ready` labels stamped.

**Orchestrator agent + model + effort.** `claude-haiku-4-5`, effort `medium`. The work is branch-and-stamp; the auto-merge clean-check is structured rule evaluation against PR state.

**Preloaded skills.** None specific.

**Subagents dispatched.** None.

**Foreign-CLI invocations.** None.

**State-out.** Bead status + labels updated; (auto-merge) merge complete + cleanup done.

**Idempotent re-entry.** Queries `gh pr view --json mergedAt` first; if non-null, skip merge and proceed to cleanup. Status and label transitions are idempotent at the SQL level.

**cwd contract.** Repo root (the worktree may be torn down by this stage; the merge runs from the main checkout).

### docs-only formula

**Purpose.** Pipeline for work that legitimately has no code tests: documentation edits, spec changes, prose-only refactors, config-only changes (where config has no test harness), meta/agent/skill authoring work. The `docs-only` formula is the routing target for two paths: (a) brainstorm-bead's `finalize` step proposes `formula-docs-only` when the heuristic fires (zero `[m]` AC lines OR `[gates].test == ""`) and the user confirms; (b) the red-tests escalate predicate in `implement-feature` / `fix-bug` auto-reroutes a misrouted bead to a freshly-cloned bead stamped `formula-docs-only` (see red-tests above).

**Stage sequence.** `preflight` → `apply-edits` → `review` → `verify-ac` → `create-pr` → `review-cycle` → `merge-or-handoff`. Deliberately omitted: `red-tests`, `green-loop`, `quality-sweep` — the docs-only path has no test runner and no RALF-IT iteration loop.

**Stage semantics.** `preflight` skips the coverage and `[gates]` checks (the formula is the routing target for projects/beads where those gates do not apply). `apply-edits` runs a single bead-implementor pass — no red-phase, no iteration. `review` runs the standard `quality-reviewer` + `simplify` pair on the diff. `verify-ac` counts `[m]` AC lines from the canonical `acceptance_criteria` field; if zero, it logs `verify-ac: no [m] AC lines — skipping mechanical witness verification (warn-and-pass)` to step-bead notes and passes without blocking. `create-pr`, `review-cycle`, and `merge-or-handoff` mirror the implement-feature contracts.

**Reroute lineage.** The clone-and-reroute mechanic intentionally keeps the original bead's lifecycle distinct: closing the original (with `REROUTED-TO:<new-id>` label and reroute note) records the decision; the `discovered-from` dep edge from new to original preserves the audit trail. The `merge-gate` child (if present) is closed as part of the reroute so the original can close cleanly. The new bead is independently picked up by `run-queue` in a dedicated session — never by the session that just burned the misrouted molecule (no `implementation-readied-session-*` label is stamped on the new bead).

## 4. Brainstorm-bead expansion

The brainstorm phase delivers shift-left by capturing post-implementation policy decisions upfront, when the human is engaged and spec context is fresh.

### 4.1 Acceptance Criteria classification

AC lines are tagged `[m]` (mechanical) or `[h]` (human). Tags are case-sensitive, must appear at the start of each line, followed by exactly one ASCII space.

- `[m]` mechanical: testable by build/test/lint/type/coverage/etc. Validated by the `verify-ac` stage.
- `[h]` human: requires human judgment (visual layout, UX feel, content quality, semantic correctness of generated text, etc.). Spawns a human follow-up child bead at brainstorm-bead's finalize step.

**Storage model.** `bd update --acceptance "<string>"` REPLACES the `acceptance_criteria` field with a single string. Multi-line content is stored verbatim with embedded newlines. The brainstorm-bead `classify-and-policy` step composes the full multi-line string and passes it in a single call.

**Canonical line parser.** Every consumer inlines this regex (about five lines in any language):

```
Pattern:   ^\[(m|h)\]\s(.*)$
Match:     group 1 = tag (m|h); group 2 = AC text
No match:  treat as untagged → default to [m]
```

Apply per-line after splitting the field on `\n`. Trim trailing whitespace per line. Skip blank lines.

**Backwards-compat / collision avoidance.** Lines beginning with `[` but NOT matching `^\[(m|h)\]\s` (for example `[BUG] foo`, `[FIX] bar`, `[ ] todo`, `[x] done`, `[Mechanical] foo`) are treated as untagged and default to `[m]`. The strict regex (case-sensitive, single character, requires trailing space) prevents both misclassification and silent drops.

**Tag aliases are not supported.** `[mechanical]`, `[H]`, `[M]`, `[Mechanical]` all fall through to the untagged → `[m]` default. The brainstorm phase agents tag canonically; the parser does not normalize input.

### 4.2 Policy knob labels

Cross-cutting policy is captured as bd labels on the source bead. Each label is independent and idempotent. If absent, the consuming stage uses its default. If present with a malformed value, the consuming stage flag-humans. If multiple mutually-exclusive labels appear (for example two `formula-*` labels), flag-human. This rule extends to parameterized labels: two labels with the same parameterized prefix but different parameter values (for example two `iteration-cap-green-loop-<n>` with different n; two `coverage-threshold-<n>` with different n) are also treated as a collision and trigger flag-human. The reader contract applies to the prefix, not to the entire label string.

| Label | Read by | Default | Meaning |
|---|---|---|---|
| `formula-<name>` | `implement-bead` (pour selection) | per bead type (feature → `implement-feature`, bug → `fix-bug`, task → `implement-feature`, chore → `implement-feature`, epic → flag-human) | Selects the formula variant to pour. Allowed values: `implement-feature`, `fix-bug`, `docs-only`. Stamped by brainstorm-bead `finalize` (heuristic + confirm/override) on the normal path, or by the red-tests reroute handler (always `formula-docs-only`) on the auto-reroute path. New variants plug in by adding a `<name>.formula.toml` and updating the formulary index. |
| `auto-mergeable` | merge-or-handoff | absent (hand-off path) | When present, the merge-or-handoff stage takes the auto-merge branch, subject to clean-check. |
| `iteration-cap-red-tests-<n>` | red-tests | 2 | Override red-tests review-loop cap. `<n>` is a positive integer. |
| `iteration-cap-green-loop-<n>` | green-loop (RALF-IT) | 5 | Override RALF-IT MAX_ITERATIONS. `<n>` is a positive integer. SOLE override path. |
| `iteration-cap-review-cycle-<n>` | review-cycle | 5 | Override review-cycle iteration cap (one iteration = one outbound reply-batch). `<n>` is a positive integer. |
| `review-exit-copilot-only` | review-cycle | implicit when `review-exit-human-approvers-<n>` is absent | Exit when Copilot review completes; ignore human-approver count. |
| `review-exit-human-approvers-<n>` | review-cycle | absent | Require `<n>` human approvers (in addition to Copilot) before review-cycle exits. Mutually exclusive with `review-exit-copilot-only`. |
| `coverage-threshold-<n>` | green-loop | from `[coverage].threshold` in project-config.toml; if absent there, 80 | Override the project's default coverage threshold for this bead. `<n>` is an integer percent 0-100. |
| `review-level:<value>` | red-tests, code-review/simplify within green-loop, verify-ac, adversarial-codex (when present) | `standard` | Gates the depth of AI review. Values: `none` (no review of any kind, including red-tests reviewers), `light` (verifier only), `standard` (full gate without adversarial Codex), `deep` (full gate plus adversarial Codex). |

**Skip matrix for `review-level:*`** (single source of truth for skip behavior across all stages):

| review-level | red-tests reviewers | code-review (in green-loop) | simplify | quality-sweep | verify-ac | review-cycle | adversarial-codex |
|---|---|---|---|---|---|---|---|
| `none` | skip | skip | skip | skip | skip | skip | skip |
| `light` | run | skip | skip | run | run | run | skip |
| `standard` | run | run | run | run | run | run | skip |
| `deep` | run | run | run | run | run | run | run |

Brainstorm-bead's `classify-and-policy` step warns when proposing `review-level:none` for a bead whose title or spec mentions security-sensitive terms (`auth`, `token`, `password`, `permission`).

**Combination warnings.** brainstorm-bead's `classify-and-policy` step warns and requires explicit user override when ANY of the following dangerous combinations are proposed:

- `review-level:none` AND `auto-mergeable` AND zero `[h]` AC lines (no verification gate of any kind would fire).
- `review-level:none` on a bead whose title or description mentions `auth`, `token`, `password`, `permission`, `secret`, or similar security-relevant keywords.
- `auto-mergeable` on a bead whose AC contains any `[h]` line (the auto-merge bypass cannot fire if `[h]` children block the gate; the combination is logically inconsistent and likely indicates wrong intent).

### 4.3 Human follow-up beads

For every `[h]`-tagged AC line on the source bead, the `finalize` step of brainstorm-bead spawns one child bead:

- `--parent <source-bead-id>` (child of source bead)
- `--type task`
- `--title "[Human verify] <AC text minus tag>"`
- `--description` containing the verbatim AC text plus a one-line warning: `"WARNING: closing this bead without verifying allows the source bead to merge. Re-verify before closing."`
- `--priority` inherited from source
- `--assignee` inherited from source
- Label `human` (so the bead appears in `bd human list`)
- NOT labeled `implementation-ready` (so the shell driver ignores it)

Human follow-ups are leaf tasks: they themselves are not eligible for brainstorming, are not assigned `[m]`/`[h]` AC of their own, and do not spawn further follow-ups. Their AC is the verify action itself.

**Source bead waits via I2 close-walk on all children, including the merge child.** brainstorm-bead's finalize step files a `merge-{source-id}` child bead alongside the `[h]` follow-up children:

- `--parent <source-bead-id>`, `--type task`
- `--title "[Merge gate] <source-title>"`
- `--description`: `"Closes when the merge-and-cleanup formula's merge step completes."`
- Label `merge-gate` (so the gate-step in merge-and-cleanup can identify and close it as its final action)
- NOT labeled `human` (this is a system-managed gate child, not a human-attention item)
- NOT labeled `implementation-ready` (the shell driver ignores it)

The merge child closes when the merge action completes (PR merged + cleanup done) as the FINAL action of the merge step inside merge-and-cleanup. The source bead's I2 close-walk closes the source only when ALL children close — the human follow-ups AND the merge child. This dissolves any close-before-merge state-honesty window: `bd show <source>` reports closed only after the PR has actually merged.

This is **gate 2** in the two-gate shift-right model. Gate 1 is the PR-state clean-check inside `merge-or-handoff` (section 3); gate 2 is the source-bead-closure gate inside merge-and-cleanup. Gate 1 decides whether to pour merge-and-cleanup; gate 2 enforces that all `[h]` follow-up verification is complete before the merge action runs. Together they enforce the shift-right pillar from section 1.

**`verified-by-human` label requirement.** The merge-and-cleanup gate-step MUST verify, before clearing, that EVERY `[h]` follow-up child carries the `verified-by-human` label. The label is applied by the human (or by `resolve-human-bead`) at the time of verification, distinct from `bd close`. A `closed` follow-up without `verified-by-human` does NOT satisfy the gate; the gate-step flag-humans with a note about the missing label. This guards against accidental `bd close` of a follow-up that has not actually been verified, which would otherwise silently bypass the shift-right gate.

Epic close-walk participates normally: the source bead's eventual closure runs the standard I2 walk up to its parent epic; no special handling for the epic chain.

**Mistakenly-closed-follow-up risk (with verified-by-human guard).** If a human `bd close`s a follow-up by mistake without applying `verified-by-human`, the source bead's I2 walk still closes the source — but the merge-and-cleanup gate-step refuses to clear because the missing `verified-by-human` label is detected. The molecule pauses; the human reviews and either applies the label (if verification was actually done) or reopens the follow-up. The follow-up's description carries an explicit warning to apply `verified-by-human` BEFORE closing.

**Idempotent finalize and AC reconciliation.** brainstorm-bead's finalize step is idempotent. On every run, it:

1. Lists current open follow-up children of the source bead via `bd list --parent <source>` filtered by label `human`.
2. For each `[h]` AC line in the current spec:
   - If a matching follow-up exists (matched by title prefix `[Human verify] <AC text minus tag>`), leave it alone.
   - If no matching follow-up exists, create one per the spec above.
3. For each existing follow-up child whose AC line is no longer `[h]` in the current spec (re-classified to `[m]` or removed), close it with reason `"AC re-classified to [m] or removed; follow-up no longer needed."`
4. The `merge-{source-id}` child is created if absent (idempotent on re-run; never duplicated).
5. Re-running with unchanged AC is a no-op.

The `resolve-human-bead` skill's "spec amended" recovery path invokes this reconciliation as part of its recovery sequence, ensuring that re-brainstormed beads do not produce orphaned or duplicate follow-up children.

### 4.4 Decomposed bead-spec personas

The brainstorm phase dispatches three role-specific personas instead of a single shared agent. This decomposition restores the fresh-eyes property on spec review (the spec writer is not the spec reviewer) and avoids cross-bead context contamination.

- **bead-assessor** — handles `assess` and `classify-and-policy` steps. Reads the bead, identifies gaps, proposes `[m]`/`[h]` AC tags, proposes `auto-mergeable: true|false` and `review-level:<value>` with rationale.
- **bead-specwriter** — handles `write-spec`. Writes the structured spec document covering background, requirements, design notes, dependencies, AC.
- **bead-reviewer** — handles `ralf-spec-review`. Adversarial review of the spec, with widened scope: heuristically reviews classification + knob choices for plausibility (flagging, for example, `review-level:none` on a bead whose spec mentions security-sensitive terms).

All three personas are `claude-opus-4-7`, with read-only tools (`Read`, `Grep`, `Glob`), `memory: none` (no user-scoped memory accumulation), distinct colors, and per-role skill preloading: assessor uses `superpowers:brainstorming`; specwriter uses `superpowers:brainstorming` plus `superpowers:writing-plans`; reviewer uses `superpowers:brainstorming` only.

The `bead-reviewer` MUST be a different persona from `bead-specwriter` so the review pass runs in fresh context — restoring the property RALF-IT requires.

## 5. Cross-cutting infrastructure

### 5.1 project-config.toml schema

The file `project-config.toml` lives at the project root and configures stage behavior per project. Sections:

- `[gates]` — default quality-gate commands (build, typecheck, lint, test). Read by green-loop's quality gate and by quality-sweep.
- `[coverage]` — `applicable` (default `true`), `threshold` (default 80), `report-location`, `per-module-pattern`, `format`. Read by green-loop, quality-sweep, and preflight. When `applicable = false`, the opt-out applies pipeline-wide: preflight skips the report-location check and does NOT fire the human-flag protocol on missing/empty `report-location`; green-loop's Definition of Done does NOT enforce the coverage threshold; quality-sweep does not separately enforce a threshold. Use this for docs-only or config-only repos that have no test infrastructure. When absent or `true`, the existing semantics apply (empty/missing `report-location` triggers human-flag, and green-loop's DoD enforces the threshold).
- `[lint-autofix]` — `command` for the lint auto-fix step. Read by quality-sweep.
- `[static-analysis]` — extra checks (semgrep, depcheck, etc.). Read by quality-sweep. If absent, quality-sweep is skippable.
- `[functional-tests]` — UI/e2e commands. Read by verify-ac.
- `[review-requirements]` — `copilot-required`, `human-approvers-required` defaults. Read by review-cycle.
- `[foreign-cli]` — foreign-CLI binary paths, model selections, and concurrency hints. Read by red-tests, green-loop, and any stage invoking adversarial-codex. Fields:
  - `codex_binary_path` (default: `${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs`)
  - `gemini_binary_path` (default: `gemini`)
  - `codex_red_tests_model` (default: `gpt-5.5`) — general adversarial review of test design; canonical model post-2026-05-04.
  - `codex_green_loop_iter1_model` (default: `gpt-5.5`) — general adversarial review of implementation diff per RALF-IT iter 1.
  - `codex_adversarial_review_model` (default: `gpt-5.4`) — deeper-reasoning adversarial review for `review-level:deep` beads only; chosen per `~/.claude/rules/codex-routing.md` profile (gpt-5.4 for architecture-sensitive review).
  - `gemini_green_loop_iter2_model` (default: `gemini-2.5-pro`)
  - `codex_max_concurrent` (default: 1) — per-driver concurrency hint for Codex calls
  - `gemini_max_concurrent` (default: 1) — per-driver concurrency hint for Gemini calls

Section names use no stage-numbering vocabulary. Stage role names are the only authority.

### 5.2 Worktree-path label encoding

The molecule carries a `worktree-path-<encoded>` label specifying its worktree location. The encoding is reversible (bijective) using a double-character escape so decoding is unambiguous regardless of literal underscores or `__` substrings in the path.

Encode (apply IN ORDER):
1. `_` → `_u`
2. `/` → `__`

Decode (apply IN ORDER):
1. `__` → `/`
2. `_u` → `_`

Trailing slash on the input path is stripped before encoding. The encoded value MUST match `[A-Za-z0-9._-]+` (with `_` permitted from the escape sequence). If the input path contains characters outside `[A-Za-z0-9._/_-]`, encode-time validation fails and the orchestrator flag-humans rather than silently corrupting the label.

**Round-trip example.** Input `a__b/c` → step 1 → `a_u_ub/c` → step 2 → `a_u_ub__c`. Decode `a_u_ub__c` → step 1 → `a_u_ub/c` → step 2 → `a__b/c`. ✓

**Required test cases.** Encoder unit tests MUST cover:

- `/Users/Scott/.claude/worktrees/feat-001-impl` (realistic macOS path, mixed case)
- `/Users/scott/src/projects/agents-config/.claude/worktrees/agents-config-7bk.9-impl` (typical worktree path with dots)
- `/tmp/test_path` (literal underscore)
- A path with a literal `__` substring
- A path with multiple `/` separators
- A trailing-slash input

The encoder MUST NOT lowercase-normalize inputs: case-sensitive Linux filesystems treat `/Users/scott` and `/Users/Scott` as distinct paths. Both must round-trip cleanly.

**Decode-time validation.** Every stage that reads the `worktree-path-*` label and uses it as cwd MUST:

1. Decode via the documented bijection (`__` → `/`, then `_u` → `_`).
2. Verify the decoded value matches `[A-Za-z0-9._/_-]+`.
3. Verify the path points to an existing directory.
4. Verify it is a git worktree: `git -C <path> rev-parse --is-inside-work-tree` returns 0.

On any failure, the stage MUST flag-human with a structured note that includes: the raw label value, the decoded path (if decoding succeeded), and which of the four checks failed. The stage MUST NOT silently fall through to a default cwd; doing so risks committing to the wrong tree. The idempotent-re-entry semantics in section 5.5 cross-reference this validation.

### 5.3 Session-id convention

`claude -p --session-id` requires a valid UUID. Stages MUST use UUIDv5 derived from a pinned namespace UUID and the input string `<bead-id>:<stage-role-name>`, so re-invocation by the same identity auto-resumes the prior session.

Pinned namespace UUID: `27ece4fd-4a06-49bf-a921-bf07ecb0dc10`. This namespace MUST NOT change once shipped — changing it invalidates all existing resumable sessions.

The stage-role-name component is one of: `preflight`, `diagnose`, `red-tests`, `green-loop`, `quality-sweep`, `verify-ac`, `create-pr`, `review-cycle`, `merge-or-handoff`. The `--name <name>` flag is for display only (resume picker, terminal title) and is not used as session identifier.

### 5.4 Per-stage `claude -p` invocation contract

Default invocation: `claude -p --session-id <uuidv5> "/implement-bead <bead-id>"`.

The `/implement-bead` command is installed globally to `~/.claude/commands/` by `install.sh` (via the beads plugin overlay phase); it is discoverable from any cwd via Claude Code's global command lookup, not via project-local walk-up.

Slash-command invocation requires slash-commands enabled (the default; broken only by `--disable-slash-commands`).

The shell driver sets cwd before spawning each `claude -p`:

| Stage | cwd |
|---|---|
| preflight | repo root (worktree does not yet exist) |
| diagnose, red-tests, green-loop, quality-sweep, verify-ac, create-pr, review-cycle | worktree path decoded from `worktree-path-*` |
| merge-or-handoff | repo root (worktree may be torn down) |

### 5.5 Idempotent re-entry semantics

`claude -p` processes are not infinitely-lived; the shell driver may restart them, the host may crash, or a long-running stage may be killed and re-run. Every stage's `claude -p` MUST be idempotent on re-entry.

- **preflight, create-pr, merge-or-handoff** are structurally idempotent. Re-running re-checks state (worktree exists? PR exists? merge done?) and skips work already complete.
- **diagnose, red-tests, quality-sweep, verify-ac** are idempotent because their work products live in the filesystem (committed work, lint fixes, validation report appended to step-bead notes). Re-running re-evaluates state and continues.
- **green-loop** persists `RALF-IT-ITER:<n>/<MAX>` to step-bead notes after each iteration completes. On re-entry, RALF-IT reads the marker (default 0 if absent) and resumes at iteration `<n>+1`.
- **review-cycle** persists `REVIEW-BATCH:<n>/<MAX>` after each batch. PR thread state on GitHub is the source of truth; the counter exists for cap enforcement.

All stages: filesystem work (commits, push) is idempotent because git's content-addressed model deduplicates. Re-running an already-pushed commit is a no-op.

Every stage that uses the worktree as cwd MUST run the decode-time validation in section 5.2 (decode → charset check → directory existence → `git rev-parse --is-inside-work-tree`) before any work. Validation failure flag-humans rather than falling back to a default cwd.

### 5.6 Human-flag protocol

When a stage cannot proceed without human input, it executes the human-flag protocol cleanly:

1. Set the `human` label on BOTH the step-bead AND the source bead. The step-bead label parks the molecule's current step; the source-bead label is what `bd ready` filters on, so the source bead must carry the label to be excluded from the ready queue. If only the step-bead is labeled and the source bead is not, the source bead may incorrectly reappear in `bd ready`.
2. Transition the step-bead status to `open` (NOT `in_progress` — this is the I1 exception path).
3. Append a structured note to the step-bead describing the gap, recommended action, and any state pointers.
4. Exit cleanly (zero exit code; the stage has not failed, only paused).

The hand-off path in `merge-or-handoff` (section 3) is a special case: at that point there is no active step-bead (the molecule is poised on the merge step, but no stage is mid-flight). Only the source bead is labeled `human` (plus `merge-ready` to discriminate the reason); see the merge-or-handoff stage description for details.

**Worktree fate across the human pause.** The worktree is preserved across the flag-human pause: the human may need to inspect uncommitted state, run the failing tests interactively, or audit RALF-IT's intermediate output. The `worktree-path-*` label on the molecule is preserved alongside the worktree itself.

**Verification labels.** When a human closes a `[h]` follow-up after verifying it, they SHOULD apply the `verified-by-human` label first. The label distinguishes "verified and closing" from "closing for some other reason" (mistake, no-longer-applicable, etc.). The merge-and-cleanup gate-step refuses to clear if any `[h]` follow-up is closed without `verified-by-human`. The `resolve-human-bead` skill prompts for this label when its scenario is "human follow-up verification."

The shell driver excludes `human`-labeled beads from `bd ready` queries. The human resolves the gap and invokes the `resolve-human-bead` skill (section 7), which diagnoses the resume scenario, applies the recommended recovery (reset markers, burn molecules, file follow-ups, adjust labels), decides the worktree's fate (keep — when resuming the same molecule; delete — when burning the molecule and re-pouring; migrate — rare), and clears the `human` label from both step-bead and source bead. The bead reappears in the ready list naturally on the next driver poll.

Re-pickup is fresh: the stage reads inputs and decides idempotently. The human's note becomes part of state-in.

### 5.7 Severity vocabulary

All reviewer stages share a uniform severity vocabulary:

- **critical** — ship-stopper, safety, data loss.
- **major** — correctness or design flaw warranting escalation.
- **minor** — quality issue, not ship-stopping.
- **nit** — preference; drop.

When two reviewers disagree on severity, the more-severe rating wins UNLESS the silent reviewer explicitly approved that aspect. If neither silently-approved nor explicitly-flagged, the finding stands at the higher severity. The orchestrator records the resolution in state-out.

### 5.8 State channels (per stage transition)

| Transition | Channel |
|---|---|
| Bead → preflight | bead description, AC sections, bead labels |
| preflight → diagnose (bug only) / red-tests | poured molecule, `worktree-path-*` label, bead notes |
| diagnose → red-tests | step-bead notes (root-cause), filesystem, bead notes |
| red-tests → green-loop | filesystem (worktree, feature branch, committed tests), step-bead notes |
| green-loop → quality-sweep | RALF-IT final report (step-bead notes), filesystem |
| quality-sweep → verify-ac | filesystem (green build), step-bead notes |
| verify-ac → create-pr | bead notes (validation report), filesystem, new bug bead refs |
| create-pr → review-cycle | `pr-url-*` label (on molecule), bead notes |
| review-cycle → merge-or-handoff | bead notes (review-cycle complete), `pr-url-*` label, PR state on GitHub |

## 6. Agent catalog

| Name | Model | Effort | Tools | Preloaded skills | Color | Purpose | Status |
|---|---|---|---|---|---|---|---|
| bead-verifier | claude-haiku-4-5 | low | Read, Grep, Glob, Bash | superpowers:verification-before-completion | cyan | Mechanical verification: run quality-gate commands, report exit codes + error excerpts, no judgment. Dispatched by verify-ac for `[m]` AC bullets. | delivered |
| bead-implementor | claude-sonnet-4-6 | medium (high for green-loop iter 1) | Read, Edit, Write, Grep, Glob, Bash | superpowers:test-driven-development, writing-unit-tests, testing-anti-patterns, superpowers:using-git-worktrees, superpowers:verification-before-completion, superpowers:systematic-debugging, superpowers:root-cause-tracing | blue | TDD test-writing in red-tests; iterative implementation in green-loop; debugging in diagnose. cd into the worktree path passed by the orchestrator. Never declares done without verification evidence. | planned |
| bead-assessor | claude-opus-4-7 | medium (high if data supports) | Read, Grep, Glob | superpowers:brainstorming | purple | Brainstorm `assess` and `classify-and-policy` steps. Identifies spec gaps; proposes `[m]`/`[h]` AC tags; proposes `auto-mergeable` and `review-level:*` with rationale. memory: none. | planned |
| bead-specwriter | claude-opus-4-7 | high | Read, Grep, Glob | superpowers:brainstorming, superpowers:writing-plans | indigo | Brainstorm `write-spec` step. Writes the structured spec document. memory: none. | planned |
| bead-reviewer | claude-opus-4-7 | medium | Read, Grep, Glob | superpowers:brainstorming | blue | Brainstorm `ralf-spec-review` step. Adversarial review of the spec including classification + knob heuristics. MUST be a different persona from bead-specwriter to preserve fresh-eyes property. memory: none. | planned |
| quality-reviewer | claude-opus-4-7 (standard 200K context per-iteration; claude-opus-4-7[1m] for final review pass on full bead diff) | medium | Read, Grep, Glob, Bash | superpowers:verification-before-completion | (existing) | Code review per RALF-IT iteration; final review pass at end of green-loop. | delivered (skill preload hygiene pending) |

All agents respect the cwd contract for their dispatching stage.

## 7. Skill catalog (changes only)

| Skill | Purpose | Changes from prior state |
|---|---|---|
| create-bead | Captures a placeholder bead from user intent. | Out of scope for changes by this architecture; included for completeness of bead lifecycle entry. A bead enters the pipeline via `create-bead`, then proceeds through brainstorm before reaching `preflight`. |
| implement-bead | The per-stage orchestrator skill. Reads the appropriate stage step-bead, dispatches subagents/skills/slash commands per the stage's spec, persists state-out to beads/filesystem, exits. | Drives ONE stage per invocation, not the whole molecule. Stays a SKILL (not converted to slash command). The `/implement-bead` slash-command wrapper at `src/plugins/beads/.claude/commands/implement-bead.md` takes `$ARGUMENTS` (the bead-id) and invokes the skill, supporting both interactive and `claude -p` invocation paths. |
| start-bead | Routes a bead from creation to the right workflow. | Route A's hand-off destination is the shell driver (no longer the run-queue skill). Route D added: when the target bead carries the `human` label, route to resolve-human-bead. Existing routes for brainstorm and trivial-inline preserved. |
| resolve-human-bead | Helps a human bring a human-flagged bead back into the autonomous pipeline safely. Reads the human-flagged bead's notes plus recent bd activity (commits, label changes, edits) to detect what the human did. Re-evaluates molecule state. Diagnoses the resume scenario: spec amended (re-brainstorm + burn parked molecule); scope expanded (file follow-up bead with dep, then resume); tooling/credential issue resolved (resume same molecule, no reset); architectural rework needed (squash molecule + re-pour fresh); bead abandoned (close with reason). Applies recommended action with user confirmation: reset RALF-IT-ITER markers, burn molecules, remove `human` label, etc. | New skill. Manual invocation `/resolve-human-bead <bead-id>`; agent-detected invocation when the user expresses intent to resolve/fix/address a human-labeled bead; start-bead Route D dispatch when its target carries `human`. |
| run-queue | Polls bd for implementation-ready beads and processes them. | DEPRECATED but not deleted. Replaced by the production shell driver once the driver achieves functional parity with the user-facing run-queue behavior. The deletion happens in the production driver's bead, not in the per-stage architecture bead. The transitional `scripts/bead-driver-test.sh` shipped with the per-stage architecture is a TEST harness only. |
| RALF-IT | Iterative refinement with fresh-eyes subagents. | Foreign-eyes degradation tracked per iteration in step-bead notes (`FOREIGN-EYES-ITER-<n>: codex=<status>, gemini=<status>`); hard-fail at end of loop if degraded in 2 or more of N iterations, with `foreign-eyes-degraded:<n>/<N>` label stamped on source bead and a foreign-eyes status section injected into the eventual PR description. Per-iteration `simplify` skill invocation dropped; `simplify` runs once at the final review pass. `bead-implementor` runs at effort:high for iter 1 only; effort:medium for iters 2-5. `quality-reviewer` per-iteration uses standard 200K context; the final review pass on the full bead diff uses `claude-opus-4-7[1m]`. |

## 8. Production driver

The production shell driver replaces `run-queue` once it achieves functional parity. It runs continuously outside Claude Code, polling `bd` for ready stage-beads in active molecules and spawning one `claude -p` process per ready stage with the cwd contract from section 5.4 and the session-id convention from section 5.3.

The driver's brainstorm-time questions remain open and will be resolved by the bead tracking driver work:

- **Concurrency model.** Single driver instance vs. multiple? Per-bead vs. per-stage parallelism? Cap on concurrent `claude -p` processes?
- **Foreign-CLI rate limits.** With multiple green-loop stages running concurrently, Codex/Gemini rate limits apply. Per-driver concurrency limit on foreign-eyes calls?
- **Worktree contention.** All worktrees go to `.claude/worktrees/`. Git lock contention on shared `.git/` at scale?
- **Driver lifecycle.** Cron, daemon, on-demand invocation? Crash recovery semantics? Stuck-stage detection (stage open beyond N hours)?
- **bd database access.** Concurrent updates to `.beads/*.db` from multiple driver instances. Locking? Single-writer enforced?
- **Mid-pipeline main-branch drift.** When bead A merges while bead B is mid green-loop, B's worktree is behind main. Rebase protocol?
- **`claude -p` start failure handling.** API down, quota exhausted, auth expired — exponential backoff per-bead-per-stage? When does the driver give up and flag-human?
- **run-queue replacement timing.** At what point does the driver replace user-facing run-queue functionality?

A transitional `scripts/bead-driver-test.sh` ships with the per-stage architecture for end-to-end smoke testing: a minimal `bd ready --label implementation-ready --json` query loop plus `claude -p` spawn per ready stage. The smoke test runs against an isolated scratch project under `/tmp/` with its own `bd init`, leaving the agents-config bd database untouched.

> **`scripts/bead-driver-test.sh` is a TEST harness shipped by 7bk.9.** It is interactive, single-instance, and MUST NOT run unattended in production. Continuous-loop autonomy (the meta-intent's fourth pillar) requires the production driver from agents-config-7bk.11 to brainstorm and ship. Until then, the architecture's pipeline runs in operator-supervised single-shot mode.

## 9. Cost model

### 9.1 Per-stage default model/effort table

The defaults below are the canonical cost profile for the pipeline. They are consumed by per-step `Model:` and `Effort:` directives in formula TOML files (the directives are stamped onto step-beads at pour time; the orchestrator reads the step-bead at dispatch time to spawn `claude -p` with the appropriate model and effort). Subagent dispatches inside each stage have their own defaults per agent frontmatter (see section 6).

| Stage | Model | Effort | Rationale |
|---|---|---|---|
| preflight | claude-sonnet-4-6 | high | Architectural gate; bad decisions corrupt the whole pipeline run; cheap absolute cost |
| diagnose (bug only) | claude-sonnet-4-6 | high | Root-cause investigation; novel reasoning over an unknown bug surface |
| red-tests | claude-sonnet-4-6 | medium | TDD orchestration; moderate complexity |
| green-loop | claude-opus-4-7 | medium | RALF-IT controller; synthesis ("converge or loop?") is highest-leverage; bounded reasoning, not novel design |
| quality-sweep | claude-haiku-4-5 | medium | Mostly shell-out (lint/build/typecheck/test/static-analysis) |
| verify-ac | claude-haiku-4-5 | medium | Mechanical AC matching against worktree state |
| create-pr | claude-haiku-4-5 | medium | `gh pr create` plus structured PR body composition |
| review-cycle | claude-sonnet-4-6 | medium | Per-comment classify + dispatch fix subagents + reply |
| merge-or-handoff | claude-haiku-4-5 | medium | Branch-and-stamp |

These defaults are calibration-by-argument, not by data. Empirical validation runs as a separate exercise (section 9.2).

### 9.2 Calibration via empirical A/B testing

The per-stage defaults will be validated empirically against real bead processing to produce data-driven recommendations for future tuning.

**Methodology.**

1. Pick 5-10 representative beads from history covering small/medium/large scope, feature/bug/chore mix, and varying AC complexity.
2. For each bead, process through the pipeline N times with different stage-defaults variants, for example:
   - Variant A: F-04 baseline (the table in 9.1).
   - Variant B: cheaper (downgrade preflight + diagnose to sonnet-medium; opus-medium → sonnet-high in green-loop).
   - Variant C: expensive (upgrade four haiku stages to sonnet-medium).
3. Capture per-run metrics: total token cost (Anthropic + foreign-CLI), wall-time per stage and total, number of RALF iterations to converge, number of Copilot comments (FIX-class), number of human escapes (flag-human invocations), number of reverts/regressions in subsequent commits.
4. Quality scoring: human (or independent reviewer agent) reviews each variant's PR and scores 1-5 on test correctness, implementation quality, AC coverage, and idiomatic / non-hacky style.
5. Output: a calibration report with specific recommendations to amend the default table (or confirm it as-is).

The calibration is project-specific; cross-project generalization is out of scope.

### 9.3 Just-enough principle

The cost profile balances two failure modes:

- **Underspending** at a stage produces wrong-first-pass output that downstream stages must re-do (RALF-IT iterations, Copilot review feedback, human escape). The cost of one extra RALF iteration ($0.50–1.00 in subagent + reviewer + foreign-eyes spend) is typically larger than the savings from downgrading a haiku-eligible stage to a cheaper model. Underspending also raises the rate of human escapes — eroding the meta-intent's autonomy goal.

- **Overspending** at a stage produces no quality lift on already-bounded work. Running quality-sweep with opus instead of haiku reads a few exit codes more expensively without changing the answer. The pipeline's high-leverage synthesis decisions live in green-loop and brainstorm; spending opus there is justified, but spending opus on shell-out stages is performative.

Per-stage defaults reflect this principle: opus only at synthesis-heavy stages (green-loop), sonnet at orchestration-heavy stages (preflight, red-tests, review-cycle), haiku at mechanical stages (quality-sweep, verify-ac, create-pr, merge-or-handoff). The empirical calibration validates whether each placement is right.

## 10. Alternative architectures (sibling explorations)

**Single-context mode.** A sibling exploration proposes that a single agent run an entire molecule in one session, with no per-stage `claude -p` invocations. Trade-offs to evaluate at brainstorm time:

- Bounded vs unbounded context: single-context bounds at one session per bead; per-stage bounds at one stage.
- Subagent-spawn constraint: single-context cannot dispatch subagents from within subagents (current Claude Code limit). Per-stage works around this by exiting and respawning.
- Performance: single-context avoids the `claude -p` cold-start tax (estimated 5-30s per spawn, multiplied by 8 stages). Per-stage costs that tax but allows parallelism across beads.
- Resilience: per-stage idempotent re-entry handles crashes by design; single-context loses progress on crash.

The unresolved question is whether single-context should be (a) a fallback profile for trivial beads where per-stage overhead exceeds benefit, (b) an A/B alternative for performance comparison, (c) an eventual replacement when the subagent-spawning constraint relaxes in Claude Code, or (d) obsolete given the per-stage architecture ships first. Brainstorm of the single-context mode bead does not start until the per-stage architecture has shipped, providing a baseline for comparison.

## 11. Bead corpus → architecture map

This table records which bead owns which architectural topic. When an architecture detail changes, the listed bead is the place to update the tracking record.

| Architecture topic | Owning bead |
|---|---|
| Per-stage `claude -p` orchestration model + 8-stage workflow + cross-cutting infrastructure (sections 2, 3, 5) | agents-config-7bk.9 |
| `diagnose` stage for bug-class beads (section 3) | agents-config-7bk.9 |
| `pr-url-*` molecule label semantics (sections 3, 5.8) | agents-config-7bk.9 |
| Worktree-path label encoding charset (section 5.2) | agents-config-7bk.9 |
| `bead-implementor` agent definition (section 6) | agents-config-7bk.9 (scope item #7) |
| `/implement-bead` slash command wrapper (section 5.4) | agents-config-7bk.9 (scope item #2) |
| `scripts/bead-driver-test.sh` test driver (section 8) | agents-config-7bk.9 (scope item #4) |
| Brainstorm-bead expansion: AC `[m]`/`[h]` classification, policy knob labels, human follow-up beads, gate-step semantics (section 4) | agents-config-7bk.12 |
| Auto-mergeable and `review-level:*` skip matrix including red-tests reviewers (sections 4.1, 4.2) | agents-config-7bk.12 |
| `verified-by-human` label requirement on `[h]` follow-up children (sections 4.3, 5.6) | agents-config-7bk.12 (R5) |
| `merge-{source-id}` child bead filing in brainstorm-bead finalize (sections 3, 4.3) | agents-config-7bk.12 (R4 finalize) |
| Decomposed bead-spec personas: bead-assessor, bead-specwriter, bead-reviewer (sections 4.4, 6) | agents-config-7bk.3 |
| `resolve-human-bead` skill (section 7) | agents-config-7bk.13 |
| Per-step `Model:` and `Effort:` directives in formula TOMLs (section 9.1 mechanism) | agents-config-7bk.14 |
| Per-stage default model/effort table (section 9.1 values) | agents-config-7bk.15 |
| `quality-reviewer` skill preload hygiene (TR6) | agents-config-7bk.15 |
| Empirical A/B testing methodology and calibration (section 9.2) | agents-config-7bk.16 |
| Production shell driver (section 8) | agents-config-7bk.11 |
| RALF-IT foreign-eyes degradation tracking, hard-fail, PR record (sections 3 green-loop, 7) | agents-config-z7a |
| Single-context mode alternative (section 10) | agents-config-76r |
| AGENTS.md File Formats schema example update (out-of-band agent frontmatter docs) | agents-config-7bk.4 |
| Uniform effort policy decision for opus[1m] reviewer-class agents (out-of-band) | agents-config-7bk.5 |
| Replace remaining `bd human <id>` folklore in beads-plugin skills | agents-config-gcg |
