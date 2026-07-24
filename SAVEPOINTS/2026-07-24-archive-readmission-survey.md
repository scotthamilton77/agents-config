# Archive re-admission survey — 2026-07-24

Five-sector parallel survey of `archive/src/**` against the harness-rework charter
(`docs/specs/2026-07-21-harness-rework-way-forward.md`), judged against slice status at
survey time: S2/S3/S4/S5 closed; S6 (review contracts), S8 (prgroom carve), S9 (executor
loop) open. Sectors: PR-loop skills, beads plugin, rules/orchestration, methodology
skills, agents/templates. Default disposition was "stay archived"; every bucket-A claim
had to survive the charter.

Purpose: input to roadmap placement of re-admission work. Every re-admission still goes
through the admission bar (D16/D20 record, D17 four-part test, D15/D19 budget) — this
survey ranks candidates, it does not admit anything.

---

## Bucket A — admissible as-is (content unchanged; needs only an admission record)

| artifact | purpose | why it survives | utility-now |
|---|---|---|---|
| `archive/src/user/.agents/rules/memory-routing.md` | Route each durable fact to exactly one home (repo AGENTS.md vs user memory) | ~120 tokens; passes all four D17 tests; prevents the AC2 drift failure applied to memory | med |
| `archive/src/user/.claude/rules/claude-sandbox.md` | Heredocs fail under Claude sandbox; use repeated `-m` or disable sandbox | ~60 tokens; prevents a silent, repeating tool failure models re-hit by default | med |
| `archive/src/user/.agents/skills/prototype/` | Throwaway code answering one design question; logic-vs-UI routing | 37-line body, no coupling to anything deleted; complements pre-spec design questions | med |

Total always-on cost of the entire bucket: <200 tokens of the 10k budget. The rules
directories are currently empty — headroom is not a reason to admit; the D17 test is.

## Bucket B — relevant to completed work; needs modification before admission

| artifact | needed modification | utility-now |
|---|---|---|
| `sync-after-remote-merge` (Claude skill; 610-line tested Python) | Add record; repoint/cut dangling refs to archived `merge-guard` + `finishing-a-development-branch`. D10's "closed = merged" makes it MORE load-bearing | **high** |
| `handoff` (Claude skill) | Output path → `{project_root}/SAVEPOINTS/{worktree_slug}/`; repoint references onto `work` items and the live skill catalog | **high** |
| `bugfix` | Trim 212 lines under the 2k cap; replace closing verification checklist with a pointer at the S6 verdict artifact | **high** |
| `bd-close-walk.sh` / `bd-claim-walk.sh` (beads plugin) | Port as **test oracles** into `packages/workcli/tests` only; never redeploy as agent-reachable shell | low |

## Bucket C — needed for open backlog work; requires changes (grouped by slice)

### S6 — review contracts (D7/D8) and S8 — prgroom carve (D13)

| artifact | change required | utility-now |
|---|---|---|
| `merge-guard` (5 tested Python modules + 6k-token SKILL.md) | **Pull forward as first S8 task.** Keep the Python as the merge-eligibility evaluator substrate; shrink prose to a thin invocation contract; strip AC5-deleted couplings (`wait-for-pr-comments`, copilot polling); re-aim `bot-quiescence` onto the D8 verdict artifact | **high** — see live finding #6 |
| `gate-triage` (456 LOC + tests) | Retarget output from deleted completion-gate tiers to D7 review-contract selection; pairs with live `quality-gate.js` (finding #1) | **high** |
| `dispatching-bare-subagents` (Claude skill) | **Only existing implementation of D7** ("reviewer carries the contract, never the house rulebook" — Agent tool can't strip context; this shells `claude --bare`). Re-aim description onto the S6 review seat; trim to 2k | **high** |
| `bead-verifier` agent (beads plugin) | Haiku-speed mechanical evidence collector — exactly the D8 mechanical-finding requirement. Rename off "bead"; drop dead skill deps; inline the report contract | **high** |
| `test-review` | Ready-made class-specific review contract for test code; convert severity rubric to D8 Mechanical/Advisory; delete `quality-reviewer` dispatch | med |
| `openrouter-claude-subagent` (~1.4k lines tested JS) | The non-Anthropic foreign-eyes path for D5's three review seats; shrink SKILL.md to 2k, refresh model roster | med-high |
| `verify-checklist` | **Harvest only**: the IDENTIFY→RUN→READ→VERIFY→CLAIM gate function feeds D8; the 10-step checklist is superseded piecewise | med |
| `quality-reviewer` agent | **Harvest only**: review-dimension checklist as raw input to the S6 code contract; the agent file contradicts D7/D8 on four axes | med |

### S9 — executor loop (D14)

| artifact | change required | utility-now |
|---|---|---|
| `tdd-red-team` / `tdd-green-team` agents (beads plugin) | Tracker-agnostic already; literally the D4 scaffold→green executors. Drop `superpowers:*` deps; inline the report contract (its cited spec `worker-report-v1.md` exists nowhere — must be re-authored) | **high** |
| `orchestrating-subagents` (Claude skill) | Nested-agent await constraint. Ladder rungs → executor dispatch code; interactive residue stays as a 2k skill. Do NOT re-admit its pointer rule | **high** |
| `worktree-safety` (rule+readme) + `worktrees` (rule) + `using-git-worktrees` (skill) | **Merge all three into ONE on-demand skill** (not an always-on rule); mechanical parts go into executor worktree code; delete the ask-consent step | **high** |
| `triaging-discovered-work` | Rewrite bd verbs onto `work` containment/dep verbs (shipped in S2); fixes live dangling mandate (finding #2) | **high** |
| `whats-next` | Port `collect.py` off direct bd queries (its own FIXME admits the D11 violation) onto the `work` facade; its `in_flight` audit is nearly the D10 staleness report; delete brainstorm/planning modes | **high** |
| `bug-diagnoser` / `docs-edits-team` agents | Same treatment as red/green teams; docs-edits serves D4's prose-deliverable branch | med |
| `test-driven-development` | D18 names `tdd` as an initial admission. Under D4 the scaffold writer owns RED — reframe to "make given tests green without changing the contract"; cut 378 lines to 2k | med-high |
| `writing-unit-tests` | Tautology filter is a scaffold-review check for D4/D5; its anti-horizontal-slicing rule directly contradicts scaffold-as-plan — scope it or drop it | med-high |
| `headless-claude` rule | Become an assertion in the executor's dispatch helper (code over prose) | med |
| `subagents` rule | Split three ways (executor code / D8 / orchestrating-subagents); nothing survives as a rule | med |
| `dep-health-check` (beads plugin) | Admit the discipline (confidence taxonomy, add-only allowlist) as a **workcli report verb**, not a skill; implementation is bd-CLI throughout | med |

### D18-named / S10-adjacent

| artifact | change required | utility-now |
|---|---|---|
| `improve-codebase-architecture` | D18 explicitly lists it re-admissible; verify grill-with-docs relative paths post-S5; add record | med |
| `retrospect` | Reroute its `self-improving-agent` delegation to memory + admission bar; feeds D19 tripwire watching | med |
| `writing-skills` | Admit content as **catalog design rules / admission-check criteria** (input to the admit-* skill), not as a 584-line skill | med |
| `SESSION-PRIMER.md.template` | Weakest C: S3-D6 reserved its skill-invocation discipline for later re-entry, but no open slice owns it and its content is stale | low |

## Bucket D — stay archived (with harvest pointers)

Superseded or anti-charter; representative rationale:

- **AC5/D9/D13 deletions:** `wait-for-pr-comments`, `reply-and-resolve-pr-threads`, `monitor-pr`, `pr-comment-fixer-team`, `finishing-a-development-branch` — the PR-comment review medium D9 abolishes.
- **D14 supersession:** `orchestrated-grind` (charter rejects it by name; 10.7k tokens), `tech-lead`, `run-queue`, `implement-bead`, `start-bead`, all five `*.formula.toml`, `resolve-human-bead` (HEP model → typed park reasons).
- **D11 supersession:** archived `beads.md`/`beads-labels.md`/`delivery.md` rules, `create-bead`, bd scripts, `where-does-this-fit`.
- **D17 deletions:** `self-improving-agent` (deleted by name), `optimize-agents-md`, `refresh-agents-md`, `INSTRUCTIONS.md.template`, persona templates, extension stubs (four are 0 bytes).
- **Duplication (AC2/L0):** `simplify` (live `/simplify` + `quality-gate` cover it), `completion-gate` rule (charter names its text for deletion), `delegation`, `orchestrating-subagents` pointer rule.
- **Failed D16 bar / poor shape:** `ralf-implement`, `ralf-review` (shape absorbed by D8), `optimize-my-skill` (5,176 lines, self-documented defects), `optimize-my-agent`, `fablize`, `zoom-out`, `bash-scripting`, `user-prompts`.
- **Scott's personal call (no conflict, but no constructible failure-prevented record):** `caveman`, `explain-diff`.

**Harvest list** (design input to open slices; never redeploy the files):
tech-lead idle/overdue heuristics (S9 park/escalate); orchestrated-grind's nesting +
"a bare idle is not an event" + per-dispatch sizing (S9); implement-bead §4 synthesized
failure-report contract (S9); fablize's richness-vs-liveness check (spec lint); ralf-review's
bounded-cycles-with-termination-predicate shape (D8); run-queue's bounded-poll exit-code
shape (S9 dispatch trigger); bd-migrate-deps' dep-type rubric (the reparent facade boundary);
writing-skills' register split (admission-check criteria).

---

## Live-surface defects found during survey (independent of re-admission)

1. **`src/user/.claude/workflows/quality-gate.js` is deployed but broken**: wired to `completion-gate` (deleted rule), `gate-triage` and `verify-checklist` (archived). Its description promises input nothing can produce. Either re-admit gate-triage/verify-checklist under S6 or rewrite the workflow in the same slice (AC2).
2. **`src/plugins/beads/.agents/rules/discovered-work.md`** mandates archived `triaging-discovered-work` — deployed rule, dangling mandatory reference.
3. **`src/plugins/beads/.agents/rules/beads.md`** speaks raw `bd` in all nine bullets; S2 is closed, so this is deployed text contradicting D11 (and its close-walk bullet contradicts workcli behaviour).
4. **Stale meta-docs**: root `AGENTS.md` repo-structure section lists templates that no longer exist under `src/` (AGENTS.md.template, personas, all four `*-EXTENSIONS`); `src/user/.agents/README.md` documents the pre-S3 assembly; `SESSION-PRIMER-README.md` is orphaned provenance. (Overlaps open item 9k9.13.)
5. **`src/user/.agents/skills/whats-next/`** is a hollow directory containing only `__pycache__` — delete.
6. **Merge-policy enforcement gap**: `project-config.toml` declares `merge-authorization = "rule-based"` / `bot-quiescence` + a GitHub App approver block; the only reader (`merge-guard/resolve_policy.py`) is archived. The standing autonomous-merge grant currently has no gate behind it. Argues for pulling the merge-guard carve forward as the first S8 task.
7. **S6 spec stale inventory**: `docs/specs/2026-07-24-review-contracts-s6.md` §1 says the three PR-loop skills "remain deployed until S8 deletes them" — the archive sweep already removed them; only the prgroom-module half of AC5 is outstanding.
8. **Archive leaks into live skill discovery** (observed in this session): when an agent works on files under `archive/src/user/`, directory-scoped skill discovery loads archived skills (`orchestrated-grind`, `fablize`, etc.) into its available-skills list. The boneyard is not out-of-mind for any session that touches it.

## Recommended roadmap placement

1. **Hygiene batch (now, no admission debate)**: fix defects #1–#5, #7 — small PR(s); #4 folds into open 9k9.13.
2. **`admit-request` skill (now, before any re-admission)**: consistent evaluation process — verify no live counterpart/conflict, run the D17 four-part test, demand the D16/D20 record (failure prevented / cost / removal observation), check D15/D19 budget, place by capability-dependency, set drift policy. Bucket-A trio becomes its shakedown cruise. `writing-skills` content is its raw material.
3. **Wave 1 — genuinely useful now** (small, high-utility, low charter risk): `sync-after-remote-merge`, `handoff`, `bugfix`, `triaging-discovered-work`, `whats-next` (needs the facade port), + bucket-A trio.
4. **Wave 2 — attach to S6/S8**: merge-guard Python carve (first S8 task), gate-triage + quality-gate.js reconciliation, dispatching-bare-subagents, bead-verifier, test-review, openrouter-claude-subagent.
5. **Wave 3 — attach to S9**: red/green/docs/bug worker agents, orchestrating-subagents, unified worktree skill, tdd + writing-unit-tests, headless-claude-as-code.
6. **Harvest notes**: attach the harvest list to the relevant slice work items so the design input isn't lost when archive eventually gets colder.
