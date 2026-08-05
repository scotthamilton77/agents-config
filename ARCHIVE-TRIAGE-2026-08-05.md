# Archive triage — 2026-08-05

Report only. Nothing has been moved, deleted, or edited. This is a working file;
delete it once the sweep is done.

Scope: all 190 files under `docs/`, plus every top-level file and directory
outside `docs/`, `packages/` package-by-package, and a targeted check of `src/`.

**Totals: 80 files under `docs/` plus 8 items outside it to archive; 41 files under
`docs/` plus three regenerable caches to delete; 24 live files that are stale and need
fixing in place rather than moving.**

---

## The headline

Three things, in the order they cost you.

**1. The worst line-of-sight pollution is not archivable — it is live and wrong.**
`README.md`, all five files in `docs/guide/`, and three of six primers describe the
pre-rework harness in confident detail: roughly 25 skills, an agents namespace, a
beads plugin, persona templates, and a three-tier completion gate. None of that
exists. `src/` is now 13 skills, 1 command, 1 rule, 0 agents, 0 formulas — verified
by count. Moving `docs/plans/` out will not help an agent that reads `README.md`
first and learns that `merge-guard` enforces your merge policy.

Two primers now contradict a mechanically enforced gate. `SKILLS_PRIMER.md:106`
tells an author to keep a skill under 500 lines; `surface_budget.py:29` fails the
deploy at 2,000 tokens — roughly a quarter of that. `RULES_PRIMER.md:21` says YAML
frontmatter is "required only for path-scoped rules", which is backwards: a rule
with no `admission:` record is dropped at deploy. Anyone following either primer
authors something that silently ships nothing.

**2. The moves you already made left three dangling pointers, one of them in the
file every agent reads first.** `AGENTS.md:15` sends agents to
`SAVEPOINTS/2026-07-20-harness-findings-handoff.md` as orientation source #3.
`packages/grind/AGENTS.md:19` cites `SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md`
as the evidence for that package's core design constraint. `project-config.toml:8`
cites `archive/docs/specs/bead-pipeline-architecture.md`. All three now resolve into
`../agents-config-ARCHIVE/`. `AGENTS.md` also still carries a section explaining
that `archive/` is not live and a Repository Structure entry describing its shape —
for a directory that is no longer there.

**3. `CONTEXT.md` is the one stale file agents are actively instructed to obey.**
The deployed `USER-CORE.md.template` `<conventions>` block says "If the repo has a
CONTEXT.md glossary, use its terminology." In this repo that resolves to a 690-line
glossary titled *PDLC Domain Glossary*, last touched 2026-05-24. Its core term for a
testable criterion is **AT** (Acceptance Test); the charter says **AC** throughout and
`spec_lint.py` mechanically rejects a spec without an AC section. An agent told to use
this glossary's terminology writes a spec the gate refuses. Details in the CONTEXT.md
section below.

---

## ARCHIVE — move to `../agents-config-ARCHIVE/`

### docs/specs (39 files)

Superseded designs that still carry rationale worth recovering. All 39 are dated
before `GATE_START_DATE` (2026-07-24), so `spec-lint` never reads them — moving them
cannot break `make ci`. None is cited by live code, `project-config.toml`, or an
open work item; I checked each.

*PDLC orchestrator — M0 closed as superseded (D20); D14 names grind, not pdlc, as the
executor loop:*
- `docs/specs/2026-05-19-pdlc-state-machine-design.md`
- `docs/specs/2026-05-23-pdlc-orchestrator-core-design.md` (2,113 lines — the richest
  surviving record of the deferred PDLC scenarios D12 says retain harvest value)
- `docs/specs/2026-05-23-pdlc-orchestrator-core-review-feedback.md`
- `docs/specs/2026-05-23-pdlc-orchestrator-core-codex-adversarial-review.md`

*prgroom — D13 deletes reply/poll/wait/snapshot/legacy-export/fix-dispatch and forbids
verify/sweep. These nine move as one unit; they cross-cite each other and nothing else:*
- `docs/specs/2026-06-20-prgroom-fix-verify-subsystem.md`
- `docs/specs/2026-07-16-prgroom-fix-verify-implementation-readiness.md`
- `docs/specs/2026-07-16-prgroom-dispatcher-observability.md`
- `docs/specs/2026-07-16-prgroom-verb-atomicity.md`
- `docs/specs/2026-07-16-prgroom-silent-path-observability.md`
- `docs/specs/2026-07-17-prgroom-legacy-export-reconciliation.md`
- `docs/specs/2026-07-05-prgroom-disposition-contract.md`
- `docs/specs/2026-07-17-prgroom-resolve-two-axis-vocabulary.md`
- `docs/specs/2026-07-15-prgroom-e2e-write-path-proof.md`

*Merge and review policy — D9 makes the PR a thin merge vehicle and ends PR comments
as a review medium:*
- `docs/specs/2026-07-16-merge-gate-triage-aware-thread-blocker.md`
- `docs/specs/2026-06-30-pr-review-merge-policy.md`
- `docs/specs/2026-07-03-agent-ruling-merge-judge.md`
- `docs/specs/2026-07-05-provenance-rerecord-and-injection-eval.md`
- `docs/specs/2026-07-03-merge-guard-bot-quiescence-retry.md`
- `docs/specs/2026-07-02-completion-gate-routing-design.md`
- `docs/specs/2026-07-03-adversarial-loop-convergence-decision.md`

*Review machinery superseded by S6's verdict schema and the deployed review skills:*
- `docs/specs/2026-07-05-adversarial-qa-agent-team-design.md`
- `docs/specs/2026-07-04-review-feedback-loop-design.md`
- `docs/specs/2026-07-18-codex-rereview-path-design.md`

*Brainstorm/spec glue superseded by `to-spec` + the spec lint (D18, S5):*
- `docs/specs/2026-07-04-spec-capture-glue.md`
- `docs/specs/2026-07-11-brainstorm-pipeline-streamlining.md`
- `docs/specs/2026-07-11-discovered-work-triage-discipline.md`

*Tracker-era, superseded by D11/D12:*
- `docs/specs/2026-07-17-bd-to-work-facade-migration.md`
- `docs/specs/2026-07-19-track-backfill-migration-design.md`

*M0 telemetry and model routing — D19 specifies a different instrument set:*
- `docs/specs/2026-07-04-cost-telemetry-and-token-capture.md`
- `docs/specs/2026-07-04-cross-model-heavy-gate-panel.md`
- `docs/specs/2026-07-04-model-routing-policy-and-escalation-ladder.md`
- `docs/specs/2026-07-04-openrouter-wiring-and-invoker-smoke.md`
- `docs/specs/2026-07-04-foreign-cli-consolidation.md`

*Installer-era and miscellaneous:*
- `docs/specs/2026-05-17-w1qls.1.1-installer-scaffold-design.md`
- `docs/specs/2026-07-04-user-overlay-profiles-project-staging.md` (its §6/§7 are
  explicitly superseded by the 2026-07-06 profiles spec)
- `docs/specs/2026-05-19-cx6.7.3-empirical-eval-loop-design.md`
- `docs/specs/2026-06-20-rules-rightsizing-design.md`
- `docs/specs/2026-07-16-setup-doctor-machine-capability.md`
- `docs/specs/2026-07-12-sync-after-remote-merge.md` (superseded by shipped `gitclean`;
  its "a script must never remove its caller's cwd" analysis is the recoverable part)

### docs/architecture (24 files, two whole directories plus most of a third)

*`docs/architecture/pdlc-orchestrator/` — all 11 files.* Not in `make ci`, not on PATH,
nothing imports it. Carries lease lifecycle, CAS-predicate concurrency control, and
crash-recovery reasoning S9 may want.

*`docs/architecture/prgroom/` — 11 of 13.* Keep `design.md` and `index.md`; they hold
the ~15–20% D13 retains (failure tiers, error-code registry, EscalationSink,
merge-eligibility contract). Archive:
`c4-l1-context.md`, `c4-l2-container.md`, `c4-deployment.md`, `c4-l3-lifecycle.md`,
`c4-l3-verify.md`, `c4-l3-agent-dispatch.md`, `c4-l3-prsession.md`, `sequences.md`,
`state-machine.md`, `data-view.md`, `cutover-runbook.md`.

Two of those carry something worth lifting before they go. `c4-deployment.md` has one
currently-true paragraph (the installer owns `uv tool install`) that belongs in
`design.md`. `cutover-runbook.md` asserts "prgroom is not yet deployed by the installer",
which is now false — it is one of the five CLIs on PATH.

*`docs/architecture/review-merge-policy/` — both files.* Its §Consumers names three
things — `merge-guard`, `resolve_policy.py`, the two PR-thread skills — and none exists
in this repo any more. **See the blocker list: `project-config.toml` cites `design.md`
twice as its schema origin.**

### docs/primers (1 file)

- `docs/primers/FORMULAS_PRIMER.md` — `find src -name '*.toml'` returns zero. The
  primitive has no instances and no interface; `bd mol`/`cook` was its only one, and
  D11 removes `bd` from agent reach.

### docs/plans and prototypes (16 files)

- `docs/plans/2026-06-07-prgroom-impl-grinder.md` — its "Rejected approaches" section
  (no scheduler, no self-firing loop, no autonomous merge) is prior art S9 will re-decide
- `docs/plans/2026-06-16-prgroom-8.12-reply-resolve-escalated-design.md` — a design, not
  a plan; decides CONTEXTUAL memory routing for machinery D13 deletes
- `docs/plans/visualization-suite/2026-07-13-implementation-plan.md` — **blocked, see
  below: `packages/vizsuite/src/vizsuite/__init__.py:9` cites it**
- `docs/plans/visualization-suite/HANDOFF.md` — instructs the reader to `bd show` an
  epic that no longer exists
- `docs/plans/visualization-suite/operationalization-notes.md`
- `docs/plans/visualization-suite/oss-landscape.md`
- `docs/plans/visualization-suite/spec-judgment-inputs.md`
- `docs/plans/visualization-suite/prototype-v2/brief_A_lanes.md`, `brief_B_territory.md`,
  `brief_C_constellation.md`
- `docs/plans/visualization-suite/prototype-v2/fixpass_A.md`, `fixpass_B.md`,
  `fixpass_C.md`, `fixpass_common.md`
- `docs/plans/visualization-suite/prototype/variant_D.js.retired`
- `docs/beads/4vn5.2-mattpocock-skills-audit.md` — the 28-skill research sweep behind
  D18's admissions; superseded as a decision by D18 itself. Archiving it empties
  `docs/beads/` entirely.

### Outside docs/ (8 items)

- `CONTEXT.md` — see the dedicated section below. Highest priority in this list.
- `IDEAS.md` — every item is now either a charter decision (WMS decoupling → D11,
  red/green gate → D4, three-strike → D10) or unminted backlog. Its own header says to
  purge it once captured.
- `packages/pdlc/` and `packages/holding-place/` — 1,848 LOC of dead code. Not in
  `make ci` (no `ci-pdlc` target exists), not in `CLI_PACKAGES`, and
  `grep -rn 'import pdlc' packages --include='*.py'` outside `packages/pdlc/` returns
  **zero**. holding-place's only importer is a pdlc test. **Move them together** — pdlc
  has a path dependency on holding-place and splitting them breaks its lockfile.
- `scripts/backlog-landscape/` — its own retirement is already written down in
  `docs/specs/2026-07-19-track-backfill-migration-design.md:367`; hardcodes bead IDs from
  the pre-reset DB; no Makefile target
- `scripts/track-backfill/` — one-shot migration, 356 rows in `applied.log`, already run.
  Its three test suites are ungated (`content-tests` only walks `src/`), so it will rot
  silently.
- `.grind/ORCHESTRATION-STATE.md` — a complete record of a nine-PR hand-run orchestration
  including the merge-authority grant it operated under. Post-mortem value for the
  AC6/AC7 baseline. **`.grind/` is untracked — git holds no copy, so deleting it is
  unrecoverable.**
- `.viz/kimi-k3-ui-assessment-2026-07-18.md` — a hand-written cross-model UI review
  naming four bugs the panel missed. Not regenerable, and it is sitting in a directory
  `vizsuite` auto-manages and will sweep.

---

## DELETE — nothing to recover

### docs/plans (38 files)

D4 deletes the prose plan as an artifact class. Every file below was verified two ways:
its companion design spec still exists in `docs/specs/`, and the implementation either
sits in the tree or is in git. Roughly a third of them are plans for machinery that no
longer exists anywhere in the working tree.

`.DS_Store` ·
`2026-05-23-w1qls.2.1-implementation-plan.md` ·
`2026-05-25-prgroom-quiescence-impl.md` ·
`2026-05-31-w1qls.2.3-template-suffix-strip.md` ·
`2026-05-31-w1qls.2.4-dynamic-include-file-form.md` ·
`2026-06-02-w1qls.3.1-shared-toolspecific-staging.md` ·
`2026-06-07-w1qls.6.1-plugin-registry.md` ·
`2026-06-09-prgroom-8.3-store-errors.md` ·
`2026-06-09-prgroom-foundation.md` ·
`2026-06-09-prgroom-gh-git-adapters.md` ·
`2026-06-09-prgroom-poll-read-path.md` ·
`2026-06-09-prgroom-status-merge-gate.md` ·
`2026-06-11-w1qls.6.5-plugin-extensions.md` ·
`2026-06-13-ruff-postedit-hook.md` ·
`2026-06-19-prgroom-8.12-implementation-plan.md` ·
`2026-06-20-installignore-exclusion-manifest.md` ·
`2026-06-26-install-receipt-pruning.md` ·
`2026-07-01-pr-review-merge-policy.md` ·
`2026-07-03-completion-gate-routing.md` ·
`2026-07-03-merge-guard-bot-quiescence-retry.md` ·
`2026-07-04-agent-ruling-merge-judge.md` ·
`2026-07-10-workcli-transport-layer.md` ·
`2026-07-11-brainstorm-pipeline-streamlining.md` ·
`2026-07-11-discovered-work-triage-discipline.md` ·
`2026-07-11-explain-diff-quiz-contract.md` ·
`2026-07-11-merge-approver-app.md` ·
`2026-07-11-prgroom-gate-strength.md` ·
`2026-07-11-prgroom-pr-review-retries.md` ·
`2026-07-12-discovered-work-skill-extraction.md` ·
`2026-07-12-s2-project-scoped-install.md` ·
`2026-07-12-sync-after-remote-merge.md` ·
`2026-07-12-workcli-lifecycle-layer.md` ·
`2026-07-14-sync-after-remote-merge-two-phase.md` ·
`2026-07-15-prgroom-e2e-write-path-proof.md` ·
`2026-07-15-workcli-realbd-integration-harness-plan.md` ·
`2026-07-16-installer-cli-deploy-plan.md` ·
`2026-07-17-workcli-track-layer.md` ·
`2026-07-19-track-backfill-migration.md`

Two worth naming individually. `2026-05-25-prgroom-quiescence-impl.md` is the largest
single deletion at 2,844 lines — it is **Go**, written for a package that pivoted to
Python about two weeks later and never used it. `2026-07-10-workcli-transport-layer.md`
and `2026-07-12-workcli-lifecycle-layer.md` are **blocked**: `packages/workcli/AGENTS.md`
cites them three times.

### docs/specs (3 files) — misfiled prose plans

- `docs/specs/2026-05-17-w1qls.1.1-installer-scaffold-plan.md` (665 lines)
- `docs/specs/2026-05-19-w1qls.1.3-io-port-plan.md` (1,194 lines)
- `docs/specs/2026-05-19-cx6.7.3-empirical-eval-loop-plan.md` (1,309 lines)

Each has a design counterpart carrying the rationale; two of those counterparts are KEEP
and one is on the archive list above.

### Outside docs/ (3 items)

- `.viz/out/` — 5.6M of regenerable `viz pr` output for merged PRs #278/#282/#284/#307.
  `packages/vizsuite/src/vizsuite/output.py:52` recreates it on the next run. **Keep the
  `.viz/` directory and its `.gitignore`** — vizsuite owns that file and hand-editing it
  puts you in conflict with a live package.
- `.grind/` minus `ORCHESTRATION-STATE.md` — eight `watch-pr-3xx.sh` watchers targeting
  merged PRs #332–#339, plus a dashboard. Nothing writes `.grind/` today: `grep -rniE
  '\.grind' packages/grind/src` returns zero hits, and the package identifies its
  directory by an `events.jsonl` that `.grind/` does not have.
- `.ruff_cache/` and the four stray `.DS_Store` files (root, `oss-snapshots/`,
  `oss-snapshots/anthropics/`, `oss-snapshots/pocock/`) — all gitignored tool droppings.

---

## Blockers — fix these in the same change, or the move leaves a dead pointer

None of these is a gate failure. Every one is a prose or docstring citation, so nothing
turns red. They are the pointers that will mislead the next reader.

| Citing file | Cites | Fix |
|---|---|---|
| `AGENTS.md:15` | `SAVEPOINTS/2026-07-20-harness-findings-handoff.md` | **Already dangling.** Repoint or drop orientation source #3 |
| `AGENTS.md` (archive bullet + Repository Structure) | `archive/` | **Already dangling.** Both describe a tree that is gone |
| `packages/grind/AGENTS.md:19` | `SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md` | **Already dangling.** It is the evidence for grind's core design constraint |
| `project-config.toml:8` | `archive/docs/specs/bead-pipeline-architecture.md` | **Already dangling** |
| `project-config.toml:7,77` | `docs/architecture/review-merge-policy/design.md` | Replace both comment lines with plain language — e.g. "Merge authorization: charter D9, CI green + verdict artifact + approval". Pointing them into the archive is worse than deleting them |
| `packages/vizsuite/src/vizsuite/__init__.py:9` | `docs/plans/visualization-suite/2026-07-13-implementation-plan.md` | Edit the module docstring |
| `packages/workcli/AGENTS.md:11,19,121` | the two workcli plans | Three edits; the surviving specs are the real authority |
| `docs/specs/2026-07-12-visualization-suite-design.md:14–19` | all four viz working notes + both prototype dirs | Update the "Evidence corpus" line |
| `docs/architecture/prgroom/index.md` | a reading order through 10 files | Rewrite to orient over `design.md` alone |
| `src/user/.claude/rules/AGENTS.md`, `src/user/.agents/README.md:17`, `src/user/.agents/rules/AGENTS.md` | `archive/src/user/...` | **Already dangling.** Source-side, not deployed |

One data point that needs lifting before its file moves:
`docs/architecture/prgroom/data-view.md` holds two D13-**retained** contracts — the §5
escalation-event JSON and the §4.5 `status` output — inside a 450-line file whose backbone
is the deleted lifecycle. Lift those two blocks into `design.md` first, then archive.

---

## CONTEXT.md — the one to handle first

**Verdict: archive, and decide the `<conventions>` line's fate in the same change.**

No code reads it. The only live pointer is the deployed `USER-CORE.md.template`
`<conventions>` block — a generic, correct convention that in this repo resolves to a
superseded PDLC glossary. Leaving the line while removing the file is fine; the line is
conditional. Leaving the file is not.

Of its 41 headings, roughly 80% describe machinery the charter deleted:

- The ten-stage lifecycle FSM (`## Terminal Lifecycle States` and its four children),
  owned by `packages/pdlc` — dead code. D10's park model is different: a typed reason
  from the five-code closed vocabulary in `packages/contracts/park-reasons.toml`.
- The entire Holding-Place idea pipeline (8 headings) — `packages/holding-place` is dead.
- The agent-persona roster (`Test-Author`, `Implementer`, `Reviewer`, `RCA`,
  `Decomposition Architect`) — no deployed implementation; D5 replaced the framing with
  review-seat/authoring-seat.
- Green Gate / Red Gate / Reviewer Toolbox / the three-stage Integration sequence — D9
  reduces this to CI green + verdict artifact + approval.
- Autopsy and its resolution taxonomy — D10 replaced it with typed park + bounded budget.
- **`## Atomic AT`, `## Scaffold AT`, `## Cleanup AT`, `## Child-Level AT vs
  Container-Level AT`.** This is the damaging one. "AT" is the retired term; the charter
  says AC throughout and `spec_lint.py` checks for an AC section.

One section partially survives: `## Finding (three classes)`. D8 says the verdict schema
adopts "the CONTEXT.md design", and Mechanical/Advisory do match the deployed
`review-verdict` skill. But its Advisory routes to "the Holding Place" (dead), and its
third class, `## Proposed Rule`, is precisely the every-correction-mints-a-rule loop D17
deleted along with `self-improving-agent`. The live contract is the `review-verdict`
skill — a strictly better-specified version of the same idea.

Nothing in the file is uniquely live. Park reasons live in `packages/contracts/`, the
verdict schema in the `review-verdict` skill, the AC and slice vocabulary in the charter.

---

## Stale and live — not archive candidates, but this is what agents actually read

These 24 files stay. They are wrong. Listing them because they defeat the purpose of the
sweep if left as they are.

**`README.md`** — the front door. Names `writing-plans` (`:119`), `monitor-pr` (`:136`),
`wait-for-pr-comments` (`:137`), `reply-and-resolve-pr-threads` (`:138`) — all four are
AC5-named deletions, and I confirmed all four are absent from `src/`. Also cites
`src/user/.agents/agents/` (`:100`), `src/plugins/beads/` (`:185`, `:300`), three
non-existent persona/extension templates (`:170`), and describes `merge-guard` as
enforcing your merge policy (`:28`). Its `packages/` list stops at four and misses all
three CLIs now on PATH.

**`docs/guide/` — all five files.** Every one is internally consistent with a repo state
that ended weeks ago. `configuration.md`'s mandatory *first step* is to personalize two
persona templates that do not exist. `sdlc-workflow.md` has five of nine phases describing
deleted machinery. `reference.md` is roughly 90% false — its skills table lists ~25 skills
of which 6 exist, its agents table lists 3 that don't, its commands table lists 3 that
don't, and it tells the reader to run `bd list --type milestone`. `index.md:5` is linked
from `README.md` as the entry point for anyone new.

Cheapest honest interim fix: a banner on `docs/guide/index.md` saying it describes the
pre-rework harness, pointing at the charter. Note `reference.md` is a rewrite, not an
edit — and patching it now means patching it again after S5–S9.

**`docs/primers/`** — `SKILLS_PRIMER.md` (500-line budget vs the enforced 2,000-token
cap; no mention of the admission record), `RULES_PRIMER.md` (frontmatter claim inverted;
work item 9k9.132 is already open on it), `AGENTS_PRIMER.md` (describes a class with zero
instances; cites the dead `src/plugins/beads/` namespace). `COMMANDS_PRIMER.md` has
already been rewritten correctly and is the model the other three should follow.

**`docs/architecture/installer/` — all six files, and this is the highest-value fix on
the list.** The installer is the one live, CI-gated subsystem in `docs/architecture/`, and
its HLD is materially good — receipts, prune authority, the `StagingPlan`, the `clis`
integrity reasoning are all precise. But AC1, AC2 and AC3 are *all* enforced by installer
code, and the HLD documents none of it. A grep for `admission`, `deploy_gate`, `sanitize`,
`surface_budget`, `content_lint`, `spec_lint` and `conflict_audit` across
`docs/architecture/installer/*.md` returns **zero hits**. Eleven live `core/` modules are
missing from every component list. Someone reading this to learn how the charter's
structural ACs get enforced concludes they aren't.

Smaller: `CLI_PACKAGES` is five entries now (`workcli`, `prgroom`, `grind`, `executor`,
`gitclean`); four files still say three. `index.md:7` says "under construction".

**`CONTRIBUTING.md`** — cites `src/user/.agents/agents/*.md` (absent) and the retired
`obra/superpowers` + `steveyegge/beads` prerequisites. Public-facing.

**`.graphifyinclude`** — three of seven globs point at the deleted `src/plugins/beads/`.

**`src/plugins/AGENTS.md:44`** — a plugin-merge precedence table still carrying a row for
formula TOMLs, for a file type that cannot occur.

**`src/user/.agents/skills/writing-skills/SKILL.md:59`** — "**REQUIRED BACKGROUND:** You
MUST understand `test-driven-development` before using this skill." That skill came from
the retired superpowers plugin. This text survives sanitization and is in the deployed
copy at `~/.claude/skills/`. D18 lists `tdd` as an intended admission, so the fix is
either admit it or drop the requirement — it should not sit as a hard prerequisite on
nothing.

---

## Your call

**1. The visualization-suite subtree is misfiled, not retired.** It has never been a plan
tree: it is a prototype corpus plus a findings log that the live `vizsuite` spec names as
its evidence corpus and that a CI-gated package points at. My recommendation is to **move
the keepers to `docs/prototypes/visualization-suite/`** rather than archive them — which
also empties `docs/plans/` completely and lets you delete the directory. Keepers:
`README.md`, `findings.md`, the seven V1 prototype files, and the five V2 files
(`v2_variant_A/B/C.html`, `v2_data.json`, `shared-conventions.md`). Relevant history: the
recorded V1 fidelity loss came from exactly this kind of reference going missing.

**2. `oss-snapshots/` — 1.6M, 244 tracked files. I kept it, but it is the closest call.**
Six deployed skills have provenance rows pointing at it, but only `writing-skills` carries
`accept-periodic-resync` — the one drift policy that ever re-reads the snapshot. The other
five are `local-fork` or `rewrite-and-divorce`, i.e. explicitly do-not-resync. So most of
it is a diff baseline nobody will diff. Cheap middle path: re-pin `writing-skills` to
`local-fork`, archive `anthropics/` and `superpowers/`, keep `pocock/` (S5 sources
`grilling` and `to-spec` from it).

**3. `packages/pdlc/` + `holding-place/` — dead by every mechanical test, but 1,848 LOC
of designed FSM.** Their lease-based locking and fencing-token work came out of a heavy
adversarial review round with 20+ applied showstoppers, and `packages/grind` is being
built to do the same job. Archiving loses nothing git can't recover, but it also takes it
out of grind's line of sight. Your call whether S9 wants to read it first.

**4. `docs/architecture/prgroom/c4-l3-verify.md` — archive or delete.** D13 says *never
build* `verify`, which is the strongest "this will never exist" signal in the charter. I
kept it because the trust-but-verify seam — a mechanical gate overriding an agent's
self-reported completion claim — is load-bearing reasoning for commitment 4. If you read
"scaffold red tests superseded them" as superseding the reasoning too, delete it.

**5. Two prgroom specs are kept only as bug carriers.**
`2026-07-16-prgroom-runloop-state-derivation.md` and `2026-07-17-prgroom-preflight-gate.md`
carry two of the three foundation bugs D13 tells S8 to absorb. Once S8 lands they should
follow their nine siblings into the archive.

**6. `.grind/` is untracked — there is no git copy.** Deleting it is permanent. That is
fine for the eight PR watchers; it is why I put `ORCHESTRATION-STATE.md` on the archive
list rather than the delete list.

---

## One charter correction, unrelated to the sweep

Charter D13 says to absorb `abn9.8.49` ("5xx ≠ auth failure"). That bug is
**`abn9.8.44`** throughout `docs/specs/2026-07-17-prgroom-preflight-gate.md`, which is
where its analysis and ruling live. `abn9.8.49` appears nowhere else in `docs/`. I
verified both by grep. D13's third absorb target, `j8pdq` (pagination), has no spec at
all — it exists only as a bead in the reset DB.
