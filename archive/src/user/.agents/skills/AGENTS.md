# Disposition inventory — archive/src/user/.agents/skills/

Disposition inventory from the 2026-07-24 re-admission survey
(`SAVEPOINTS/2026-07-24-archive-readmission-survey.md`), judged against the harness-rework
charter (`docs/specs/2026-07-21-harness-rework-way-forward.md`) with S2–S5 closed and
S6/S8/S9 open. **archive/ is NOT live**: nothing here is a behavioural contract; do not
invoke or follow anything in this tree. This inventory exists so a future admission pass
starts from recorded findings instead of re-surveying.

## Scheduled for re-admission (work item minted)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `prototype/` | Throwaway code answering one design question; logic-vs-UI routing | Bucket A (37-line body, no coupling to anything deleted); shakedown candidate for the admit-request skill — agents-config-9k9.27 | D6, D1, D16 |
| `merge-guard/` | Pre-merge enforcement: resolves `[merge-policy]`, computes eligibility floor, App-attested approval + squash merge | agents-config-9k9.28 (S8 pull-forward): keep the five tested Python modules as the merge-eligibility evaluator substrate; shrink ~6k-token prose to a thin invocation contract; strip AC5-deleted couplings; re-aim `bot-quiescence` onto the D8 verdict artifact. Live gap: `project-config.toml` declares a policy only this code can read | D8, D9, D13, D16, AC5, S6/S8 |
| `gate-triage/` | Deterministic Python router computing SKIP/SERIAL/HEAVY tier floor from diff facts | Decision item agents-config-9k9.17.6 (with the quarantined `quality-gate.js` workflow): either retarget from deleted completion-gate tiers to D7 review-contract selection, or fold tier-routing into the S6 design and retire | S6, D7, D8, D16, AC2 |
| `triaging-discovered-work/` | Sibling test for scope; anchoring + provenance discipline for discovered work | agents-config-9k9.32: rewrite bd verbs onto `work` containment/dep/discover verbs (S2 shipped); absorb the sibling-test content of the beads-plugin `discovered-work.md` rule as it archives (agents-config-9k9.29); drop the verify-checklist handoff | D11, S2, AC2/AC3 |
| `where-does-this-fit/` | Situate a work item in project goals/architecture | Promoted from stay-archived by Scott 2026-07-24 — agents-config-9k9.33: port `bd show`/`bd list` to `work` verbs; drop the AGENTS.md milestone-table assumption (D17 zero-base); fix the caveman coupling | D11, D17 |
| `explain-diff/` | Self-contained interactive HTML diff explainer in persona voices | Promoted from stay-archived by Scott 2026-07-24 — agents-config-9k9.31: admission record must be honest (user-requested utility, not failure-prevented); confirm ~1k lines of assets acceptable under D15/D19 instruments | D16, D9 |
| `caveman/` | Ultra-compressed response register at three intensities | Promoted from stay-archived by Scott 2026-07-24 — agents-config-9k9.31: personal-preference admission (~600 tokens catalog cost); drop the where-does-this-fit coupling check | D16 |
| `whats-next/` | Five-mode work-queue surface incl. `in_flight` audit with claim age and PR flags | agents-config-9k9.1.14 (S9): port `collect.py` off direct bd queries (its own FIXME admits the D11 violation) onto the `work` facade; align `in_flight` with the D10 staleness report; delete brainstorm/planning modes | D10, D11, S9, S10 |
| `test-driven-development/` | Red-green-refactor discipline, Iron Law, rationalization tables | agents-config-9k9.1.15 (S9): D18 names `tdd` an initial admission; reframe for D4 — the scaffold writer owns RED, so "make the given tests green without changing the contract"; cut 378 lines to the 2k cap | D18, D4, S7/S9, D16 |
| `writing-unit-tests/` | Behavior-vs-implementation, refusal criteria, doubles hierarchy, tautology filter | agents-config-9k9.1.16 (S9): the tautology filter becomes a D4/D5 scaffold-review check; resolve the anti-horizontal-slicing rule's direct conflict with scaffold-as-plan; drop the plan-approval step | S7 (D4, D5), D16 |
| `using-git-worktrees/` | Detect-then-create isolated workspace; native tool preferred | Merge into the unified worktree skill — agents-config-9k9.1.13 (with `worktrees` rule and Claude `worktree-safety`); compress from 197 lines; delete the ask-consent step | S9 (D14), AC2, D16 |

## Future-slice candidates (no item yet)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `test-review/` | Review contract for test code specifically | S6 candidate (noted on agents-config-9k9.17): replace CRITICAL/HIGH/SUGGESTIONS with the D8 Mechanical/Advisory verdict; delete the `quality-reviewer` dispatch and companion-skill table | S6 (D7, D8) |
| `improve-codebase-architecture/` | Find shallow modules to deepen; module/interface/depth/seam vocabulary; deletion test | D18 lists it explicitly as re-admissible later; its grilling-loop handoff targets live skills; verify `grill-with-docs` relative paths still resolve post-S5; needs an admission record | D18 |
| `retrospect/` | Session retrospective routing findings to context/tooling/prompting fixes | Charter-native root-cause table (compliance failure → mechanical gate, not prose rule); reroute its delegation to the deleted `self-improving-agent` onto memory + the admission bar; feeds D19 tripwire watching | D17, D16, D19, S10 |

## Harvest-only (lift ideas/code into slice work; never redeploy the file)

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `verify-checklist/` | 10-step completion gate + the IDENTIFY→RUN→READ→VERIFY→CLAIM evidence gate | Harvest the gate function ("no completion claims without fresh verification evidence in this message") into D8's mechanical-artifact requirement via agents-config-9k9.17.6; the checklist itself is superseded piecewise by D7/D8, D9/D13, and the triage path | S6 (D8), S8 (D13), D9 |
| `writing-skills/` | TDD-for-documentation; skill register split (discipline/technique/reference); frontmatter mechanics | Harvest as catalog design rules and admission-check criteria for the admit-request skill (agents-config-9k9.27); disqualified as a skill: 584-line body + 3,321 lines of references vs the 2k cap | D18, D16, AC1/AC3, S3 |
| `ralf-review/` | Bounded adversarial review cycles with PASS/PASS_WITH_RESERVATIONS/FAIL | Harvest only the shape — bounded cycles with an explicit termination predicate — which D8 already encodes; its severity rubric would contradict the two-class verdict (AC2) | D7, D8, S6 |

## Stay archived

| artifact | purpose | disposition & required changes | charter refs |
|---|---|---|---|
| `bugfix/` | Three parallel evidence threads (git archaeology / failing repro / data-flow trace) before any fix; 3-strike architectural escalation | Scott 2026-07-25: stays quarantined (reversed from scheduled; item agents-config-9k9.26 closed unstarted). No charter conflict; if ever revisited, the recorded plan was: trim 212 lines under the 2k cap, retarget the closing verification checklist onto the S6 verdict artifact | D16, D10 |
| `wait-for-pr-comments/` | End-to-end PR-review responder: polls Copilot, classifies comments, dispatches fixes | Named for deletion in D13 and AC5; its premise (PR comments as review medium) is what D9 abolishes; ~11.6k tokens prose + ~4,800 lines bash | D9, D13, AC5, D16 |
| `reply-and-resolve-pr-threads/` | Replies to every PR review thread and resolves FIXED ones via GraphQL | Named in D13 and AC5; pure PR-comment bookkeeping in the medium D9 removes | D9, D13, AC5, D16 |
| `monitor-pr/` | Thin supervisor over `prgroom run` | Named in D13 and AC5; supervises precisely the prgroom subsystem S8 deletes; was never live | D13, AC5, S8 |
| `finishing-a-development-branch/` | Post-implementation 4-option menu (merge/PR/keep/discard) | Superseded twice: hands off to AC5-deleted deps, and an end-of-branch human menu is the babysitting the prime directive targets; its worktree-cleanup value is carried by `sync-after-remote-merge` and the unified worktree skill | D9, D10, AC5, D16 |
| `ralf-implement/` | Bounded adversarial implement loop with foreign-model cycles | Most charter-conflicting artifact in this folder: references deleted formulas, `worker-report-v1.md`, `ralf:*` labels; function reassigned to the D14/S9 executor loop as code | D4, D14, D16, D11, S9 |
| `simplify/` | Three-axis (reuse/quality/efficiency) review-and-apply pass | Duplicated twice over: a live `/simplify` harness skill ships with Claude Code and the quality-gate workflow ran the same axes; re-admission creates the conflicting pair AC2 forbids | AC2, D16, L0 |
| `self-improving-agent/` | Mint a persistent prevention rule from every user correction | Deleted by name in the charter: corrections land in memory and become rules only through the admission bar | D17, D16 |
| `optimize-my-skill/` | Audit/improve SKILL.md files with an empirical eval loop | 5,176 lines incl. a 1,325-line HTML viewer and scripts self-documenting five unfixed defects (one SIGTERMs arbitrary PIDs); the harness-obstruction pattern the rework deletes | D16, AC1, AC3 |
| `optimize-my-agent/` | Audit agent persona files against a primer rubric | Targets an asset class with no live instance (no `agents/` under `src/`); rubric contains pre-D11 lore | D16, D11 |
| `optimize-agents-md/` | Shrink bloated CLAUDE.md/AGENTS.md files | D17 zero-bases the user AGENTS.md and S3 enforces the budget mechanically; its stop-and-ask-five-questions flow is the intervention the prime directive targets | D17, S3, AC1 |
| `clean-up-git/` | Drive worktree/branch cleanup through the `gitclean` CLI; relay every withheld reason; never name a target the user did not | Retired 2026-08-02 on measurement rather than judgement, so re-admission needs new evidence rather than a re-read: across nine headless trials on a repository where ancestry is wrong in both directions, 8 of 9 agents carrying no such skill reached the correct end state and the 9th produced a correct plan and asked first — which falsifies the `prevents` claim its admission record rested on. What the same trials confirmed is the opposite gap: none of the nine reached for `gitclean` at all. That function is now carried by the `post-merge-cleanup` skill, with the `/clean-up-git` command for the interactive path | D16, D20 |
