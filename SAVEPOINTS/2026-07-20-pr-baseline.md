# PR Baseline Backfill — 50 merged PRs (#315–#369, 2026-06-14 → 2026-07-19)

Generated 2026-07-20 from GitHub API data for the harness-rework outcome-AC baseline.

## Metric definitions

- **rounds** — distinct head SHAs that received ≥1 substantive bot review (Copilot / chatgpt-codex-connector / any Bot login; empty-body approvals, e.g. the merge-approver App, excluded). Multiple bots on one SHA = 1 round.
- **fix** — commits whose committedDate is after the first substantive bot review (rebase/amend can distort committedDate).
- **scott#** — comments authored by login scotthamilton77 (issue + review-thread). **Unreliable as a human-intervention proxy**: agent reply machinery posts via Scott's gh auth, so this conflates human and agent-posted comments.
- **hours** — PR createdAt → mergedAt. PRs open post-implementation, so this measures the review-loop tail only; idea→PR-open lead time is **not computable** from gh history.
- **cat** — changed-file classes: packages (typed code), config-prose (src/user, src/plugins), docs, ci-scripts, other.

## Per-PR table

| PR | hours | size | commits | rounds | fix | scott# | cat | title |
|---|---|---|---|---|---|---|---|---|
| #315 | 0.4 | 911 | 5 | 0 | 0 | 1 | packages | feat(installer): CLI-deploy registry, port, and  |
| #316 | 0.5 | 827 | 8 | 2 | 2 | 6 | packages+docs+other | feat(workcli): track layer slice A — config disc |
| #317 | 3.3 | 863 | 12 | 4 | 9 | 25 | config-prose | feat(wait-for-pr-comments): per-bot re-review di |
| #318 | 0.1 | 158 | 1 | 0 | 0 | 0 | packages | feat(workcli): capability-disposition seam — Rea |
| #319 | 1.4 | 391 | 2 | 2 | 2 | 7 | packages | feat(workcli): multi-step partial-progress contr |
| #320 | 1.3 | 1305 | 6 | 1 | 0 | 17 | packages | feat(installer): deploy_clis + prune_clis decisi |
| #321 | 0.1 | 670 | 4 | 0 | 0 | 0 | packages | feat(workcli): track layer slice B — create gate |
| #322 | 0.0 | 665 | 2 | 0 | 0 | 0 | packages | feat(workcli): track layer slice C — work lint + |
| #323 | 0.6 | 652 | 3 | 1 | 1 | 3 | packages | feat(workcli): work triggers — extraction pressu |
| #324 | 1.0 | 95 | 5 | 3 | 4 | 6 | packages+docs | chore(workcli): MINOR protocol bump to 1.2 — adv |
| #325 | 2.9 | 1360 | 5 | 4 | 5 | 11 | ci-scripts+other | chore: park interim backlog-landscape generator  |
| #326 | 0.8 | 1043 | 10 | 6 | 7 | 15 | packages+config-prose | feat(workcli): work groom --done/--status — back |
| #327 | 0.3 | 1108 | 5 | 2 | 1 | 4 | packages+docs | feat(workcli): work discover — mechanical discov |
| #328 | 1.2 | 662 | 5 | 3 | 2 | 21 | packages+docs+other | feat(installer): wire CLI-deploy stage into cli. |
| #329 | 1.4 | 1261 | 8 | 5 | 6 | 14 | config-prose | feat(skills): add orchestrated-grind multi-lane  |
| #330 | 0.9 | 1683 | 5 | 2 | 2 | 5 | config-prose | feat(openrouter-claude-subagent): vendor SSE-rep |
| #331 | 0.7 | 221 | 6 | 5 | 5 | 16 | config-prose | fix(orchestrated-grind): restore lost escalation |
| #332 | 0.5 | 264 | 3 | 1 | 2 | 5 | config-prose+docs | feat(merge-guard): reaction-path clean-pass fact |
| #333 | 0.1 | 84 | 1 | 0 | 0 | 1 | config-prose | fix(wait-for-pr-comments): make Phase 2 entry ga |
| #334 | 0.8 | 375 | 5 | 5 | 4 | 15 | config-prose | feat(wait-for-pr-comments): structured do-not-re |
| #335 | 0.2 | 138 | 2 | 2 | 1 | 3 | config-prose+docs | feat(merge-guard): Component 2b clean-pass/trigg |
| #336 | 0.5 | 142 | 5 | 3 | 4 | 14 | config-prose | fix(merge-guard): one-ask retry uses --bot-revie |
| #337 | 1.2 | 512 | 6 | 5 | 5 | 14 | config-prose | feat(wait-for-pr-comments): generalize Phase 6 s |
| #338 | 0.1 | 55 | 1 | 0 | 0 | 1 | config-prose | feat(merge-guard): review_wait.bot recognizes Co |
| #339 | 0.5 | 187 | 3 | 2 | 2 | 6 | config-prose+docs | feat(merge-guard): review_summary ratchet surviv |
| #340 | 0.2 | 74 | 2 | 2 | 1 | 5 | config-prose | feat(orchestrated-grind): point ROOT at the cano |
| #341 | 0.4 | 417 | 3 | 3 | 2 | 7 | config-prose | feat(orchestrated-grind): verdict-aware PR watch |
| #342 | 1.3 | 571 | 23 | 6 | 22 | 34 | docs | docs(specs): event-sourced grind runtime + dashb |
| #343 | 0.2 | 76 | 3 | 2 | 2 | 5 | config-prose | feat(orchestration): bare-idle discipline and an |
| #345 | 0.2 | 7 | 2 | 2 | 1 | 3 | docs | test(live-verify): A1 clean-first-pass merge |
| #346 | 0.2 | 6 | 3 | 2 | 1 | 4 | docs | test(live-verify): A2a genuine findings + normal |
| #347 | 0.2 | 6 | 4 | 3 | 3 | 6 | docs | test(live-verify): A2b review_summary ratchet |
| #352 | 0.0 | 19 | 1 | 1 | 0 | 1 | docs | chore(live-verify): remove scratch docs |
| #353 | 0.4 | 178 | 2 | 2 | 1 | 2 | config-prose+docs | fix(merge-guard): union Ruleset-sourced required |
| #354 | 0.4 | 166 | 1 | 1 | 0 | 3 | config-prose | fix(wait-for-pr-comments): expose per-identity d |
| #355 | 0.9 | 3602 | 9 | 2 | 5 | 7 | packages+ci-scripts | feat(grind): event schema + FSM fold — event-sou |
| #356 | 0.2 | 67 | 1 | 1 | 0 | 2 | config-prose | fix(merge-guard): consume request-rereview NDJSO |
| #357 | 0.6 | 3720 | 15 | 3 | 3 | 10 | docs+ci-scripts+other | feat(tracks): track backfill migration tooling ( |
| #358 | 0.8 | 3162 | 4 | 2 | 1 | 2 | config-prose+docs | docs(specs): grind-dashboard design pick — Contr |
| #359 | 0.2 | 91 | 1 | 1 | 0 | 3 | config-prose | fix(wait-for-pr-comments): reconcile poll-copilo |
| #360 | 0.3 | 103 | 2 | 2 | 1 | 3 | config-prose | fix(wait-for-pr-comments): require the initial p |
| #361 | 0.6 | 807 | 3 | 2 | 1 | 3 | packages | fix(vizsuite): constellation round-2 feedback —  |
| #362 | 0.7 | 2211 | 12 | 2 | 5 | 12 | packages+ci-scripts | feat(grind): create/log/status/finish CLI over t |
| #363 | 0.3 | 52 | 5 | 2 | 1 | 6 | config-prose | docs(wait-for-pr-comments): reconcile the >= vs  |
| #364 | 0.1 | 151 | 2 | 1 | 0 | 0 | packages | feat(vizsuite): round-3 UI — sonar overlay zoom/ |
| #365 | 0.2 | 101 | 2 | 2 | 1 | 4 | packages | test(grind): lock in observation routing and ser |
| #366 | 0.1 | 223 | 1 | 1 | 0 | 0 | packages | feat(grind): grind check — external staleness wa |
| #367 | 1.8 | 1182 | 9 | 6 | 8 | 36 | packages | feat(grind): conditions engine — emit-back envel |
| #368 | 1.3 | 1287 | 3 | 3 | 2 | 10 | packages | feat(grind): dashboard render projection over th |
| #369 | 0.1 | 14 | 2 | 1 | 0 | 0 | packages+other | chore(tracks): record the minted groom-state bea |

## Aggregates (median / p75)

| metric | median | p75 |
|---|---|---|
| wall time created→merged (h) | 0.43 | 0.91 |
| diff size (adds+dels) | 320 | 911 |
| commits | 3 | 5 |
| bot review rounds | 2 | 3 |
| fix commits after first bot review | 1 | 4 |
| scotthamilton77 comments | 5 | 11 |

## Distribution notes

- **Prose/process churn confirmed (handoff evidence 14).** Per-100-lines churn top-10 is 8/10 config-prose — all process machinery (wait-for-pr-comments, orchestrated-grind, merge-guard). Typed `packages` PRs: median 1 round, 0 fix commits at median size 665; config-prose PRs: median 2 rounds, 2 fix commits at median size 142. Prose churns ~9× more per line than typed code.
- **Worst absolute churn:** #342 (spec doc, 6 rounds, 22 fix commits), #367 (grind conditions engine, 6 rounds), #326 (workcli groom + prose, 6 rounds), #329/#331/#337/#334 (5 rounds each — all config-prose process machinery).
- **Review-round distribution:** 0 rounds: 6, 1 rounds: 10, 2 rounds: 18, 3 rounds: 7, 4 rounds: 2, 5 rounds: 4, 6 rounds: 3 (n=50).
- **Wall time is short** (median 26 min, max 3.3 h): the review loop itself is fast in wall-clock terms; the cost is in rounds/tokens/attention, and in pre-PR time this dataset cannot see.
- **Large typed diffs converge anyway:** the two biggest PRs (#355 size 3602, #362 size 2211 — both grind event-sourcing in `packages/`) each closed in 2 rounds. Size alone predicts churn weakly; artifact class (prose vs typed) predicts it strongly.

## Not computable / caveats

- Idea→PR-open lead time (needs session/bead data, not gh).
- Human-vs-agent comment split (shared gh auth).
- Fix-commit counts inherit committedDate distortion from rebases.
- Bot-round clustering treats an unresolved `commit` field on a review as its own round (rare).
