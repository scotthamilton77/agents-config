# Superpowers: impactful changes since the vendored snapshot

## Scope

Compared `oss-snapshots/superpowers/` with the local upstream clone at
`/Users/scott/src/oss/obra/superpowers/`.

- Vendored baseline: effectively upstream `v5.1.0` (the snapshot's comparable
  files match that tag).
- Upstream current: `v6.1.1`, commit `d884ae0`, dated 2026-07-02.
- This report covers the skills represented in the snapshot and supporting
  files that materially change their behavior. Packaging, README, and harness
  additions are included only when they affect skill use.

## Highest-impact changes

### 1. Subagent-driven development has a new review architecture

**Affected skill:** `subagent-driven-development`

The old per-task two-reviewer sequence (spec reviewer, then code-quality
reviewer) was replaced with:

1. one task reviewer returning both spec-compliance and quality verdicts;
2. a targeted fix-and-rereview loop for Critical/Important findings;
3. one broad whole-branch review after all tasks complete.

The controller now performs a batched pre-flight scan for plan conflicts and
plan-mandated defects before dispatching Task 1. Reviewers are explicitly
read-only, must judge from supplied evidence, may not be coached to suppress
findings or pre-rate severity, and must cite file/line evidence.

The handoff mechanism also changed from prompt/diff text in the controller
conversation to files:

- `scripts/task-brief` extracts one task into a unique brief file.
- `scripts/review-package` writes the commit list, stat, and full diff to a
  unique review package.
- `task-reviewer-prompt.md` replaces the separate
  `spec-reviewer-prompt.md` and `code-quality-reviewer-prompt.md`.
- `scripts/sdd-workspace` creates the self-ignoring working-tree artifact
  directory `.superpowers/sdd`.
- A progress ledger and implementer report carry status and TDD red/green
  evidence across turns.

Model selection is now explicit for every dispatch, with guidance to use
cheaper tiers for mechanical implementation and reserve the strongest model
for architecture/final review. This is a substantive cost, context, and
quality change, not merely a wording cleanup.

**Porting implication:** This cannot be updated by copying only `SKILL.md`.
The new reviewer prompt and three helper scripts are part of the contract;
the old two-reviewer prompt files should not be retained as active guidance.

### 2. The brainstorming visual companion is materially safer and more robust

**Affected skill:** `brainstorming`

The visual companion moved from an unauthenticated local web server to a
session-keyed service:

- every HTTP endpoint and WebSocket connection requires the per-session key;
- the key is persisted in owner-only session files and carried in a
  tab-scoped cookie;
- content serving rejects symlinks, dotfiles, path traversal, and macOS
  resource-fork files;
- responses add no-store and anti-framing protections;
- shutdown verifies the PID's per-start server identity before signaling it,
  failing closed on stale or ambiguous metadata.

Lifecycle behavior also changed: project sessions reuse the last port/key so
an open tab can reconnect, the browser can be opened only after explicit user
approval, the page reconnects and displays live/paused status, and the idle
timeout defaults to four hours. Windows/MSYS2 process handling was hardened,
and WebSocket payloads are capped.

The skill now offers the companion just-in-time when a question benefits from
visual treatment, rather than offering it at the beginning of every potentially
visual brainstorm.

**Porting implication:** Treat the server scripts, browser client, and skill
guidance as one security-sensitive unit. Copying only the prose would preserve
the old server vulnerabilities; copying only the server would leave agents
with the wrong consent and lifecycle instructions.

### 3. Worktrees are project-local; the legacy global fallback is removed

**Affected skills:** `using-git-worktrees`, `finishing-a-development-branch`

The `~/.config/superpowers/worktrees/` fallback is gone. Worktrees now resolve
to an existing project-local `.worktrees/` or `worktrees/` directory, otherwise
`.worktrees/`, with explicit instructions taking precedence. Project-local
directories must be git-ignored before creation.

The finishing skill now cleans only `.worktrees/` and `worktrees/`, and no
longer embeds `gh pr create`; branch publication is forge-neutral. This
reduces accidental deletion of harness-owned/global worktrees and avoids
assuming GitHub as the forge.

**Porting implication:** Any local workflow, rule, or completion gate that
still creates or cleans `~/.config/superpowers/worktrees/` is stale and can
conflict with the upstream behavior.

### 4. Plans now carry downstream contracts and are right-sized for review

**Affected skill:** `writing-plans`

The plan template gained:

- a **Global Constraints** section for exact project-wide requirements;
- per-task **Interfaces** sections describing consumed and produced names,
  parameters, and return types;
- task right-sizing guidance: each task should carry its own test cycle and
  meaningful reviewer gate, while setup/configuration/docs belong with the
  deliverable that needs them.

This is aimed directly at a known SDD failure mode: implementers and reviewers
see only a task and otherwise have to reconstruct constraints and neighboring
contracts from context.

**Porting implication:** The local plan format should be considered
incompatible if it omits these fields while using the new SDD controller.

### 5. Skill prose is broadly runtime-neutral, with per-runtime references

**Affected skills:** most shared skills, especially `using-superpowers`,
`executing-plans`, `dispatching-parallel-agents`, `writing-skills`, and code
review skills.

Claude-specific vocabulary was replaced with action language such as
“dispatch a subagent,” “create todos,” and “your instructions file.” The
bootstrap was compressed and now has runtime references for Codex, Pi, and
Antigravity. Gemini and Copilot mapping files were removed from the upstream
skill tree as the integration model changed.

Notable behavior changes include:

- parallel dispatch is explained as issuing multiple dispatches in one
  response;
- `executing-plans` recognizes Codex CLI, Codex App, and Copilot CLI as
  subagent-capable runtimes;
- `writing-skills` renames Claude Search Optimization (CSO) to Skill Discovery
  Optimization (SDO) and replaces Claude-specific assumptions;
- the TDD skill uses a relative link to its testing anti-patterns reference;
- code-review references use portable relative links and generic dispatch
  language.

**Porting implication:** This is relevant if our shared skill layer is intended
to deploy across Codex, Claude, Gemini, and OpenCode. The runtime-neutral prose
is useful, but upstream's reference-file set does not map one-for-one to this
repository's own capability-dependency placement rules.

### 6. Writing-skills now distinguishes discipline failures from output-shape failures

**Affected skill:** `writing-skills`

The skill added a “Match the Form to the Failure” decision table:

- use prohibitions and rationalization defenses for agents that knowingly skip
  rules under pressure;
- use positive recipes/contracts for incorrectly shaped output;
- use required template slots for omitted fields;
- use observable-predicate conditionals for conditional behavior.

It also added a micro-test method for wording: fresh-context samples, a
no-guidance control, at least five repetitions per variant, manual inspection
of flagged matches, and variance as a signal of unstable wording. The
rationalization toolkit is explicitly scoped to discipline failures rather
than used as a universal fix.

**Porting implication:** This is a methodology improvement likely relevant to
our skill-authoring guidance, especially where our current rules rely on long
prohibition lists for shaping problems.

## Secondary but worth porting

- `systematic-debugging` changes “Ultrathink” to “Ultra-think” to avoid
  accidentally triggering Claude Code's extended-thinking keyword scanner.
- `using-git-worktrees` fixes skipped step numbering after the already-in-a-
  worktree/consent branches.
- `receiving-code-review` removes a private in-joke and replaces it with
  explicit guidance to name the concern and tell the partner.
- `dispatching-parallel-agents` removes a Claude `Task` code example and makes
  same-response parallel dispatch the portable rule.
- `test-driven-development` fixes the relative link to
  `testing-anti-patterns.md`.
- `using-superpowers` removes a stale “debugging” skill reference and
  compresses the bootstrap; runtime-specific mapping content is now smaller
  and more action-oriented.
- `finishing-a-development-branch` and related docs remove GitHub-specific PR
  creation instructions, leaving push/publication to the available forge
  tooling.

## Changes not recommended for direct porting as skill behavior

The upstream clone also contains substantial new harness/plugin packaging,
eval infrastructure, tests, README/release documentation, and integration
files for Kimi, Pi, Antigravity, OpenCode, and Codex portal packaging. Those
may matter to a future snapshot refresh, but they are not changes to the
relevant vendored skill behavior by themselves. The only harness additions
with direct skill implications are the runtime-neutral vocabulary and the
per-runtime reference model described above.

## Suggested refresh order

If we decide to refresh the snapshot, the safest order is:

1. `subagent-driven-development` plus its prompt/scripts and artifact
   directory helper;
2. brainstorming companion server/client and consent/security guidance;
3. worktree and finishing-branch policies;
4. writing-plans contract fields;
5. runtime-neutral wording and `using-superpowers` references;
6. writing-skills methodology additions and the smaller correctness fixes.

The first two items have the largest behavioral and security surface; they
should not be refreshed as isolated Markdown files.

## Recommendations against our customized skills

These recommendations compare upstream `v6.1.1` with the authoritative
customized sources under `src/user/**`. They are intentionally not a blanket
resync: local delivery, tracker, worktree, and completion-gate behavior takes
precedence where it is more developed than upstream.

### Priority summary

| Priority | Local target | Recommendation |
|---|---|---|
| Critical | `src/user/.agents/skills/brainstorming/` | Adopt the complete visual-companion security and lifecycle bundle, plus just-in-time consent. |
| High | `src/user/.agents/skills/writing-plans/SKILL.md` | Add task right-sizing, Global Constraints, and per-task Interfaces; retain our plan path and TDD handoff. |
| High | `src/user/.agents/skills/writing-skills/SKILL.md` | Merge the form-to-failure decision model and wording micro-tests into our richer amalgam. |
| Medium | `src/user/.agents/skills/finishing-a-development-branch/SKILL.md` | Remove legacy global-worktree cleanup and make PR creation action-oriented, while preserving provenance and PR-monitoring extensions. |
| Medium | `src/user/.agents/skills/using-git-worktrees/SKILL.md` | Take the numbering and location-selection fixes only; preserve our cross-agent location convention. |
| Medium | `src/user/.agents/skills/bugfix/SKILL.md` | Change `ultrathink` to `ultra-think` to avoid accidental Claude extended-thinking activation. |
| Low | `src/user/.agents/skills/test-driven-development/SKILL.md` | Replace the stale `@testing-anti-patterns.md` reference with a relative Markdown link. |
| Low | reviewer prompt templates | Replace Claude `Task tool` vocabulary with action-oriented subagent dispatch language. |
| Reject as direct import | upstream `subagent-driven-development` | Harvest its evidence-handoff and reviewer-isolation ideas; do not add a competing end-to-end implementation controller. |

### 1. Brainstorming: adopt as a security-sensitive bundle

**Files to update together:**

- `src/user/.agents/skills/brainstorming/SKILL.md`
- `src/user/.agents/skills/brainstorming/visual-companion.md`
- every file under `src/user/.agents/skills/brainstorming/scripts/`

Our current server has a WebSocket handshake but no application-level session
authentication. It also retains the old 30-minute lifecycle, lacks the
per-start process identity check, and does not have upstream's hardened file
serving and reconnect behavior. This is the one change set where selective
prose copying would be actively unsafe.

Adopt upstream's:

- per-session key for all HTTP and WebSocket access;
- tab-scoped cookie and owner-only token/session files;
- traversal, symlink, dotfile, and resource-fork rejection;
- no-store and anti-framing headers;
- bounded WebSocket payloads;
- stable project port/key and browser reconnect state;
- PID plus server-instance ownership proof before shutdown;
- four-hour configurable idle timeout and Windows/MSYS2 lifecycle fixes;
- `--open` behavior only after explicit consent;
- just-in-time companion offer at the first genuinely visual question.

Preserve our local additions in `brainstorming/SKILL.md`, especially the
`## Continuations` tracker handoff and our `docs/plans` / spec workflow. Update
the source metadata to the new upstream SHA/date only after the complete
bundle and its upstream tests are imported and pass locally.

### 2. Writing plans: adopt contracts, not upstream routing

**File:** `src/user/.agents/skills/writing-plans/SKILL.md`

Insert three upstream concepts:

1. **Task Right-Sizing** after File Structure: a task owns one independently
   testable deliverable and a meaningful review gate; setup, configuration,
   scaffolding, and docs stay with the task that needs them.
2. **Global Constraints** in the plan header: exact version floors,
   dependency limits, naming/copy rules, platform requirements, and other
   cross-task invariants copied verbatim from the approved spec.
3. **Interfaces** in every task: exact Consumes/Produces contracts, including
   signatures and types relied upon by neighboring tasks.

Also extend Self-Review to verify that every global constraint reaches the
tasks it governs and every consumed interface has exactly one earlier
producer.

Do **not** copy upstream's `docs/superpowers/plans` path or its handoff to
`superpowers:subagent-driven-development` / `executing-plans`. Keep our
`docs/plans` path, bare-name cross-skill conventions, TDD requirement, and
execution routing. Upstream's new fields solve context loss; its controller
names do not belong in our portable source tree.

One local inconsistency deserves a separate design decision: the skill still
offers an ad hoc “fresh subagent per task” execution mode even though our
completion-gate owns final review and delivery. When implementation routing is
next revised, replace that prose with the project's canonical tracked-work
dispatcher rather than importing upstream SDD wholesale.

### 3. Writing skills: merge the new method into our amalgam

**File:** `src/user/.agents/skills/writing-skills/SKILL.md`

Our customized skill is already stronger than upstream on skill types,
trigger-eval design, progressive disclosure, and register selection. Preserve
those sections. Add upstream's two genuinely new ideas:

- a **Match the Form to the Failure** section immediately before our
  bulletproofing section, distinguishing discipline violations, wrong-shaped
  output, missing template fields, and conditional behavior;
- a **Micro-Test Wording** subsection in Testing Methodology requiring a
  no-guidance control, at least five fresh-context samples per variant,
  manual inspection of matches, and variance as a first-class failure signal.

Then add two checklist entries:

- guidance form matches the observed baseline failure;
- behavior-shaping wording was micro-tested against a no-guidance control.

Adapt upstream terminology and links to our folder structure: supporting
documents live under `references/`, and our technique/discipline/reference
register split remains authoritative. Do not replace our trigger-eval workflow
with micro-tests; micro-tests are the cheap wording loop before the full
pressure/application/retrieval scenarios.

### 4. Finishing a branch: remove stale ownership and forge assumptions

**File:** `src/user/.agents/skills/finishing-a-development-branch/SKILL.md`

Adopt immediately:

- remove `~/.config/superpowers/worktrees/` from both cleanup-provenance
  checks; our creation skill and shared worktree rule no longer create there;
- remove the hardcoded `gh pr create` heredoc and describe the action as
  “create the PR with the available forge integration.”

Preserve all local load-bearing extensions:

- reviewer-brief requirements for the PR body;
- per-commit authorship provenance and fail-closed merge judging;
- mandatory `wait-for-pr-comments` monitoring through quiescence;
- merge-authorization policy and merge-guard behavior.

The provenance commands are GitHub-specific by design, so the skill should
make that branch conditional on the resolved merge policy/integration rather
than pretending the entire delivery path is forge-neutral. Upstream removed a
hardcoded creation mechanism; it did not solve our policy sidecar.

### 5. Worktree creation: small corrective merge

**File:** `src/user/.agents/skills/using-git-worktrees/SKILL.md`

Our customized version already removed the legacy global fallback and added
the important cross-agent convention: Claude native worktrees under
`.claude/worktrees/`, other agents under `.worktrees/`. Preserve that local
behavior.

Adopt upstream's:

- corrected Step 2/Step 3 numbering and all corresponding jump targets;
- explicit directory-resolution sequence: instructions, existing
  project-local directory, then `.worktrees/` default;
- use of a resolved `$LOCATION/$BRANCH_NAME` instead of hardcoding
  `.worktrees/$BRANCH_NAME` in the fallback command.

Do not remove our native-tool ownership guidance or cross-agent discovery
paragraph; upstream lacks the collaboration context this repository requires.

### 6. Debugging and TDD: two surgical fixes

**Files:**

- `src/user/.agents/skills/bugfix/SKILL.md`
- `src/user/.agents/skills/test-driven-development/SKILL.md`

Change “Use ultrathink” to “Use ultra-think” in `bugfix`. Although upstream's
fix landed in `systematic-debugging`, our promoted equivalent contains the
same scanner-sensitive token and therefore has the same defect.

Change `@testing-anti-patterns.md` to
`[testing-anti-patterns.md](testing-anti-patterns.md)` in TDD. This is a
portable relative link and avoids harness-specific `@` loading semantics.

### 7. Reviewer templates: adopt action vocabulary

**Files:**

- `src/user/.agents/skills/brainstorming/spec-document-reviewer-prompt.md`
- `src/user/.agents/skills/writing-plans/plan-document-reviewer-prompt.md`

Both still begin with `Task tool (general-purpose):`. Replace that with a
portable action contract such as `Subagent (general-purpose):`, retaining the
existing prompt body. Model and effort must remain explicit under our shared
subagent rule.

This is the useful portion of upstream's runtime-neutralization. Do not import
upstream's per-harness reference-file layout: our installer already separates
shared and tool-specific capability dependencies.

### 8. Subagent-driven development: harvest, do not install

There is no authoritative `subagent-driven-development` source under
`src/user/**`; the vendored snapshot is research material, not an installed
local controller. Adding upstream's full skill would create overlapping
ownership with our completion-gate, quality-reviewer/simplify sequence,
worktree lifecycle, PR monitoring, and tracked-work routing.

Adopt these ideas at their existing ownership points instead:

- **file-based task briefs and diff packages:** use when a dispatcher must
  keep large task/diff payloads out of the orchestrator context;
- **read-only reviewers:** add to reviewer contracts so review cannot mutate
  HEAD, index, branch, or worktree;
- **no reviewer coaching:** prohibit suppression lists and controller-supplied
  severity ratings;
- **batched pre-flight conflict scan:** add at the plan-to-execution boundary;
- **explicit model on every dispatch:** already enforced by
  `src/user/.agents/rules/subagents.md`; no additional copy is needed;
- **whole-change review:** already owned by the completion-gate; do not add a
  second final-review loop.

Before implementing file-based review packages, decide their canonical home
and lifecycle in the tracked-work dispatcher. The deployed environment lists
`implement-bead`, `start-bead`, and `run-queue`, but no corresponding source
exists under `src/**` in this checkout; per this repository's architecture,
deployed artifacts must not be edited as a workaround. That source/deployment
gap should be reconciled before attaching new helper scripts to those flows.

## Recommended implementation slices

To keep reviewable changes cohesive:

1. **Security slice:** brainstorming server/client bundle, guidance, and
   imported upstream regression tests.
2. **Planning slice:** Global Constraints, Interfaces, right-sizing, and
   self-review checks.
3. **Skill-authoring slice:** form-to-failure method, micro-tests, and
   checklist updates.
4. **Workflow hygiene slice:** worktree numbering/location fixes, finishing
   cleanup provenance, forge-neutral PR creation action, reviewer-template
   vocabulary, `ultra-think`, and the TDD link.
5. **Orchestration design slice:** resolve the missing tracked-work dispatcher
   source, then evaluate file-relay briefs/review packages at that boundary.

The first four slices are independently adoptable. The fifth is architectural
and should not be bundled into a routine upstream resync.
