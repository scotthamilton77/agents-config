# Disposition inventory — archive/src/plugins/ (beads and graphify plugins)

The beads sections below come from the 2026-07-24 re-admission survey; the graphify
section at the end was added on 2026-07-26 when that plugin was retired. Both are
covered by the same standing rule: **archive/ is NOT live.**

Disposition inventory from the 2026-07-24 re-admission survey
(`SAVEPOINTS/2026-07-24-archive-readmission-survey.md`), judged against the harness-rework
charter (`docs/specs/2026-07-21-harness-rework-way-forward.md`) with S2–S5 closed and
S6/S8/S9 open. **archive/ is NOT live**: nothing here is a behavioural contract; do not
invoke or follow anything in this tree. This inventory exists so a future admission pass
starts from recorded findings instead of re-surveying. (This file replaces the pre-S3
plugin-authoring guide that previously sat here; that guide is superseded by the live
`src/plugins/AGENTS.md`, which documents scan-based discovery and adapters.)

**Standing decision (Scott, 2026-07-24): beads-specific artifacts are permanently
quarantined.** workcli subsumes all agent interaction with the beads backend (D11); agents
must have no bd knowledge. The only exceptions are the four tracker-agnostic worker agents
below, which never spoke bd in the first place. The remaining live beads surface
(`src/plugins/beads/`, `src/kits/beads/`) is scheduled for archival under
agents-config-9k9.29; beads git hooks are re-evaluated separately under agents-config-9k9.6.

## Scheduled for re-admission (work item minted)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `beads/.agents/agents/tdd-red-team.md` | Authors failing tests from AC bullets, commits, emits structured YAML report | agents-config-9k9.1.11: verified tracker-agnostic (inputs are worktree path, test command, report path); literally the D4 scaffold executor; drop `superpowers:*` deps; author the report contract in-artifact — the cited `worker-report-v1.md` exists nowhere | D4, D14, S7, S9, D16/D20 |
| `beads/.agents/agents/tdd-green-team.md` | Makes given failing tests green minimally without changing the contract | agents-config-9k9.1.11, same changes as red-team | D4, D14, S7, S9 |
| `beads/.agents/agents/bug-diagnoser.md` | Root-cause analysis worker; emits `root_cause_note`, changes no code | agents-config-9k9.1.11; the fix-bug analogue; meaningful only if the executor keeps a bug lane | D14, S9 |
| `beads/.agents/agents/docs-edits-team.md` | Prose/spec/config edit worker; explicitly reads/writes no tracker state | agents-config-9k9.1.11; serves D4's prose-deliverable branch (dispatch brief names the mechanical checks) | D4, D14, S9 |

## Future-slice candidates (no item yet)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `beads/.agents/agents/bead-verifier.md` | Haiku-speed mechanical evidence collector: runs gate commands, returns exit codes + excerpts, no judgment | S6 candidate (noted on agents-config-9k9.17): squarely the D8 mechanical-finding requirement; rename off "bead", drop dead skill deps, inline the report contract | D8, S6, D16 |
| `beads/.agents/skills/dep-health-check/` | Audits the dep graph (provenance mismatches, cycles, stale blockers) with a confidence taxonomy and narrow write allowlist | Explicitly NOT scheduled (Scott excluded it from the S9 batch). Future candidate as a **workcli report verb** only: the discipline (confidence taxonomy, add-only allowlist, cite-or-drop) is portable; the implementation is a bd-CLI client violating D11, and its SKILL.md blows the 2k cap | D11, D10, D16, S9 |

## Harvest-only (lift ideas/code into slice work; never redeploy the file)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `beads/.beads/scripts/bd-close-walk.sh`, `bd-claim-walk.sh` | Cascade-close ancestors / claim-lease the ancestor chain | Semantics already absorbed by `work close`/`work claim` (S2); port only as test oracles into `packages/workcli/tests`; never agent-reachable again | D11, S2 |
| `beads/.agents/skills/implement-bead/` (incl. `setup-worker-audit.sh`) | Metadata-driven dispatcher: resolve step, pour formulas, dispatch workers, apply outcomes | Harvest §4's per-dispatch primitive (synthesize a `status: failed` report when a worker crashes or emits malformed YAML; the orchestrator derives the roll-up, workers never self-declare) into the S9 executor design; §4 is also the only surviving description of the lost worker-report contract | D11, D14, S9 |
| `beads/.agents/skills/run-queue/poll-ready-beads.sh` | Bounded poll with timeout exit codes for ready work | Harvest the bounded-poll-with-exit-code shape as S9 dispatch-trigger design input; the bd call and label-driven readiness die | D11, D14, S9 |
| `beads/.beads/scripts/bd-migrate-deps.sh` | Retargets dep edges brainstorm-seed→impl-bead per a dep-type rubric | Harvest the dep-type migration rubric as the closest thing to a spec for re-parenting (a recorded workcli facade boundary) | D11, S2 |

## Stay archived

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `beads/.claude/rules/beads.md` | The bd instruction surface: quirk lore, invariants, HEP shell procedure | The single largest thing D11 exists to delete from agent reach | D11, D16/AC1 |
| `beads/.claude/rules/beads-labels.md` | Label registry + molecule→bead linkage probes | Every label is a lifecycle knob of the replaced pipeline; readiness-by-label superseded by `work ready` + typed park reasons | D11, D14, S2 |
| `beads/.claude/rules/delivery.md` | Runs delivery inside molecule steps; names three AC5-deleted skills as step bodies | Doubly dead: molecule steps are gone and it cites skills AC5 requires absent | AC5, D9, D13 |
| `beads/.agents/skills/create-bead/` | Fast idea capture as a placeholder bead | Verb-for-verb replaced by `work create`/mint; its sibling test survives in the live `discovered-work.md` (itself archiving into agents-config-9k9.32) | D11, S2 |
| `beads/.agents/skills/start-bead/` (incl. preflight scripts) | Pipeline traffic cop: Routes A–D/Z, molecule probes, formula wisping | Most charter-conflicting artifact in the sector; superseded by the S5 spec contract → S7 scaffold → S9 executor chain | D4, D11, D14, AC5 |
| `beads/.agents/skills/resolve-human-bead/` (incl. `_test.sh`, `SMOKE-EVIDENCE.md`) | Six-probe classifier for `human`-labeled beads | Wholly the HEP model; D10 replaces it with typed park reasons + three human verbs, already in workcli | D10, D11, S2 |
| `beads/.agents/skills/run-queue/SKILL.md` | Autonomous bead-queue processor | The bead-driven grind D14 re-aims away from; HEP escalation model | D10, D14, S9 |
| `beads/.beads/formulas/*.formula.toml` (5 files) | TOML step DAGs poured into molecules (brainstorm, implement-feature, fix-bug, docs-only, merge-and-cleanup) | The old lifecycle in purest form: D2 replaces the DAG with the ordered slice plan, D4 the plan artifact, D9 the review-cycle steps, S5 deleted the brainstorm path | D2, D4, D9, D14, S5, S7 |
| `beads/.beads/AGENTS.md` | Formula/molecule/wisp/pour vocabulary explainer | Documentation for the replaced model; was repo-only, never installed | D14 |
| `beads/.beads/scripts/bd-finalize-container-gate.sh`, `bd-finalize-create-impl-bead.sh` | Brainstorm-finalize steps 0 and 4 | Formula-internal helpers for a deleted formula; both create `human`-labeled escalation beads | D10, D14, S5 |
| `beads/.beads/scripts/bd-record-decision.sh` | Creates a `decision` bead linked discovered-from | Direct bd writes; decision capture is `work create decision` now | D10, D11 |
| `beads/.claude/commands/implement-bead.md`, `resolve-human-bead.md`, `dep-health-check.md` | Thin slash wrappers | Wrappers for stay-archived skills; the dep-health-check wrapper would follow its skill only if the workcli-verb port ever happens | D11, D16 |
| *(predecessor of this file)* pre-S3 plugin-authoring guide | Documented `--plugins=` flags and `install.sh` registration | Superseded by live `src/plugins/AGENTS.md` (scan-based discovery, adapters, rules-readmes); content replaced by this inventory | S3 |

## graphify plugin — retired 2026-07-26

The rule was the plugin's only artifact, so archiving it retires the plugin: plugin
discovery is a scan of `src/plugins/`'s subdirectories, and `graphify/` no longer has one.
`--plugins=graphify` now raises `UnknownPluginError`, and the plugin tables in `README.md`,
`docs/guide/`, and `src/plugins/AGENTS.md` were swept in the same change.

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `graphify/.agents/rules/graphify.md` | Forbade running `graphify update .` from inside a worktree and committing the result on a feature branch; "keep graphify-out off feature branches" | **Stay archived.** Every clause is vacuous once `graphify-out/` is untracked — there is no diff to flood, nothing to keep off a branch, and no other checkout to break. Carried no `admission:` record, so it deployed nothing while it was live. A rewrite would have to clear `admit-request`, and would fail its always-on test: a constraint that binds only while someone is deliberately building a graph does not belong on every turn of every session. | D16/D20 |

**Residual fact this retirement drops, recorded here rather than re-deployed:** a graph
built from inside a linked worktree indexes that worktree's absolute paths, so it is
specific to the checkout that produced it. Under unversioning that graph is untracked and
dies with the worktree, which is why it no longer warrants a standing rule — but anyone
wiring an automatic rebuild should build from the main checkout.
