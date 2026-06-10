# prgroom implementation grinder — milestone execution plan

**Status:** APPROVED. **8.9 re-cut (step 0) COMPLETE & dolt-pushed** (see §3 for the label→ID map). Awaiting go-ahead for the first build run (`8.1` alone). **Do not start build execution until Scott says go.**
**Subject epic:** `agents-config-abn9.8` — prgroom CLI implementation umbrella.
**Companion design doc (source of truth for the code):** `docs/plans/2026-05-12-prgroom-cli-design.md` (1867 lines, §1–§8).
**Architecture HLDs:** `docs/architecture/prgroom/` (`index.md` first; 10 files).

Self-contained operating manual for an agent driving the implementation of epic `abn9.8` in
**human-gated capability milestones**. It exists so the procedure survives context compaction: a
cold agent should execute from this file plus the cited design artifacts, without re-deriving
anything from conversation.

---

## 1. What this is

A **human-gated, milestone-driven grinder**. It processes the beads of one **capability
milestone** through the full implement → quality-gate → deliver pipeline (one PR per bead,
stacked), then runs that milestone's **live demo against a real PR as the definition-of-done**,
reports, and **halts**. Scott reviews + merges the stack and re-triggers the next milestone.
There is **no scheduler, no self-firing loop, no autonomous merge, and no Opus-quota detection**
(see Rejected approaches, §9). The stop points are **capability boundaries**, not an arbitrary
bead count. The human at each milestone boundary *is* the control mechanism.

**Why milestones, not "N beads":** a count tells you when to stop, not whether you have anything.
A milestone is "prgroom can now *do X*, here's it doing X to a real PR." Each is a meaningful
review/merge point and a real validation gate.

---

## 2. Decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Human-gated grinder; Scott re-triggers each milestone | Quota self-governance is fragile and unnecessary (§9) |
| D2 | **Stop at capability-milestone boundaries** (not a bead count) | A milestone is functionally complete + live-testable against a real PR |
| D3 | **Stacked PRs, human merges.** No autonomous merge. | Restores "merge needs human auth"; Scott is awake at every boundary |
| D4 | Beads set `in_progress`, **never `bd close`d by the grinder** | Beads close when Scott merges; avoids the close-walk auto-close trap |
| D5 | Sequential within a milestone | Stacked branches require a linear base chain; beads touch the same package |
| D6 | Control vehicle = **main-session supervisor + fresh per-bead worktree-isolated subagent** | Stateful git/PR/Copilot work stays debuggable in the main loop; bead logic gets clean context |
| D7 | One-shot procedure now; capture as reusable `/grind-prgroom` command/Workflow **only if it proves out** | YAGNI; repo redesign is burning down speculative tooling |
| D8 | Each bead must pass `make ci-prgroom` green at **90% branch coverage**; halt rather than write anti-pattern tests | Quality gate is the only thing between a bead and `main` once merged |
| D9 | **Re-cut bead 8.9 three ways** (8.9a/8.9b/8.9c) before execution | Makes the read-only→write safety line a clean milestone boundary; gives an early tracer; defers the agent-dispatch arm |
| D10 | **First run stops after `8.1` alone** (intra-M1 de-risk checkpoint), then M1 continues | The greenfield scaffold everything stacks on is the riskiest piece; eyeball it before stacking |
| D11 | Milestone DoD = the grinder **runs the live demo and includes its output as evidence**; Scott re-verifies at check-in | Evidence before claims (verify-checklist principle) |

---

## 3. The 8.9 re-cut (D9) — COMPLETE

Bead 8.9 ("lifecycle verbs: _poll, _cluster, _fix, _push, _rereview, _resolve") is split along the
read → stage → write progression so milestone boundaries land on clean bead boundaries:

| New bead | Scope (verbs) | Side effects | Milestone |
|----------|---------------|--------------|-----------|
| **8.9a** | `_poll` + read path (item/reviewer ingest, state update) | read-only (fetches PR via gh) | M1 |
| **8.9b** | `_cluster` + `_fix` | stages commits **locally**; nothing reaches GitHub | M2 |
| **8.9c** | `_push` + `_rereview` + `_resolve` | **writes to GitHub** (push branch, re-request review, resolve threads) | M3 |

**Dependency re-points (replacing the single 8.9 node):**
- `8.5 → 8.9a`, `8.8 → 8.9a` (poll/read needs gh-read + lifecycle core; **NOT** the agent arm)
- `8.9a → 8.9b`, `8.7 → 8.9b`, `8.8 → 8.9b` (cluster/fix need poll/state + agent audits + core)
- `8.9b → 8.9c` (push/rereview/resolve build on cluster/fix output)
- `8.9a → 8.11` (status reads poll'd state)
- `8.9c → 8.10` (run needs the full verb set)
- `8.10 → 8.12`, `8.6 → 8.13`, `8.11 → 8.13`, `8.12 → 8.13`, `8.13 → 8.14` (unchanged)

**Label → real bd ID (authoritative; bd has no ID-rename, so 8.9 was repurposed in place):**

| Label | Real bd ID | Note |
|-------|-----------|------|
| **8.9a** | `agents-config-abn9.8.9` | repurposed in place — `8.9 ≡ 8.9a` |
| **8.9b** | `agents-config-abn9.8.15` | created under the epic |
| **8.9c** | `agents-config-abn9.8.16` | created under the epic |

**Verified final `blocks` graph (read back from bd):**
- `8.9a (.9)` — depends-on `{8.5, 8.8}` · blocks `{8.11, 8.9b}`
- `8.9b (.15)` — depends-on `{8.9a, 8.7}` · blocks `{8.9c}`
- `8.9c (.16)` — depends-on `{8.9b}` · blocks `{8.10}`
- `8.10` depends-on `{8.9c}` (was 8.9) · `8.11` depends-on `{8.9a}` · `8.7` blocks `{8.9b}` (was 8.9)

**Do not re-run** — the graph above is live in bd and pushed to the Dolt remote. Everywhere this
doc says "8.9a / 8.9b / 8.9c", resolve to real IDs via the table above (`.9 / .15 / .16`).

---

## 4. Capability milestones (the stop points)

Verb safety split (from design §3.2): **read-only** = `poll`, `cluster`, `wait`, `status`;
**write** = `fix`(stages local), `push`, `rereview`, `reply`, `resolve`, `resolve-escalated`,
`run`, `sweep`. The read-only→write line is the key safety boundary (M2→M3).

| M | Capability | Live demo (the DoD evidence) | R/W | New beads | Cumulative |
|---|-----------|------------------------------|-----|-----------|------------|
| **M1** | **It sees a PR** | `prgroom poll <pr>` then `prgroom status <pr> --json` against a real open PR → prints phase, items, reviewers, and which quiescence gate blocks | read-only | `8.1, 8.3, 8.5, 8.8, 8.9a, 8.11` | 6 |
| **M2** | **It decides what to do** | `prgroom cluster <pr>` + `prgroom fix <pr>` → every item gets a disposition; fixes **staged locally** (`git log` shows commits), nothing pushed | read-only* | `8.4, 8.7, 8.9b` | 9 |
| **M3** | **It changes a PR** | `prgroom push` + `rereview` + `resolve` against a **throwaway** PR → commits land on branch, review re-requested, threads resolved | **WRITE** | `8.9c` | 10 |
| **M4** | **It grooms autonomously** | `prgroom run <pr> --autonomous` drives a full cycle to quiesced/human-gated (replies still a no-op skeleton here) | **WRITE** | `8.10` | 11 |
| **M5** | **It talks back + replaces the old skill** | `prgroom reply` posts real replies + memory routing; `resolve-escalated` flips items; `monitor-pr` skill drives `run`; `wait-for-pr-comments` retired. **§6.5 readiness gate runs here: ≥3 real PRs end-to-end to quiesced/merged, no revert, no wrong/duplicate replies or bad resolves** | **WRITE** | `8.12, 8.6, 8.13` | 14 |
| **M6** | **Cleanup** | `reply-and-resolve-pr-threads` retired; standalone verbs documented | — | `8.14` | 15 |

\* M2 is "read-only" only toward GitHub — it stages commits on the local worktree branch; nothing
is pushed. It does invoke the fix agent (subprocess).

**Inherited quirk (honest note):** full `reply` lives in `8.12`, which depends on `8.10` (run),
so "it talks back" (M5) lands *after* "it grooms autonomously" (M4) — M4's `run` loop ships with a
no-op `_reply`. This is the existing decomposition's choice (run mechanics separated from
reply-rendering); not re-cut here to avoid churn beyond 8.9. Flag to Scott if the ordering matters.

**Milestone target PRs:** M1 needs any real open PR (read-only — safe anywhere; Scott names one or
the grinder picks an open PR in this repo). M2 stages locally (safe). M3–M5 mutate a PR → use a
**throwaway/sandbox PR**, never a real one, until the M5 readiness gate.

---

## 5. The epic DAG (post-re-cut; recompute the frontier from this — `bd ready` won't advance pre-merge)

Edge `X → Y` = X blocks Y (X complete before Y). Because the grinder does **not** merge/close
beads, `bd ready` will not advance between milestones; compute readiness from this DAG (a bead is
ready when all blockers are merged to `main` or present earlier in the current stack).

```
8.1 ─┬─→ 8.3 ─→ 8.8 ─┬─→ 8.9a ─→ 8.9b ─→ 8.9c ─→ 8.10 ─→ 8.12 ─┐
     ├─→ 8.4 ─→ 8.7 ──┘         (8.7→8.9b)                       │
     ├─→ 8.5 ─────────→ 8.9a                                     ├─→ 8.13 ─→ 8.14
     └─→ 8.6 ───────────────────────────────────────────────────┤
                          8.9a ─→ 8.11 ───────────────────────────┘
```
- 8.9a ← {8.3, 8.5, 8.8} (via 8.1). **No agent-dispatch arm.**
- 8.9b ← {8.9a, 8.7, 8.8}; 8.7 ← 8.4 ← 8.1
- 8.9c ← 8.9b
- 8.10 ← 8.9c · 8.11 ← 8.9a · 8.12 ← 8.10
- 8.13 ← {8.6, 8.11, 8.12} · 8.14 ← 8.13

Closed / out of scope: `8.2` (breakdown task), `fca6.6` (superseded).

---

## 6. Bead → design-doc/HLD mapping (read fresh per bead; do not infer scaffold from this table)

| Bead | Title | Read (design §) | Read (HLD) |
|------|-------|-----------------|------------|
| 8.1 | foundation — scaffold + core infra | §1, §2, §6.7, §7 | `index`, `c4-l2-container`, `c4-l3-prsession`, `c4-l3-lifecycle` |
| 8.3 | store residuals + error model | §2, §3.7 | `c4-l3-prsession`, `data-view` |
| 8.4 | agent dispatch (Cluster/Fix, subprocess, fallback, token usage) | §5 | `c4-l3-agent-dispatch` |
| 8.5 | gh/git Protocol adapter layer (recorded-response fakes) | §1, §2 | `c4-l2-container` |
| 8.6 | installer ownership (uv-tool-install, console-script) | §6.1, §7 | `c4-deployment` |
| 8.7 | agent audits (cluster validator, fix audit, memory-channel audit) | §5, §8.6 | `c4-l3-agent-dispatch` |
| 8.8 | lifecycle core (phase model, predicates, quiescence, resolver, locking) | §3, §4 | `state-machine`, `c4-l3-lifecycle` |
| **8.9a** | lifecycle read verb — `_poll` + read path | §3.2, §3.3 | `c4-l3-lifecycle`, `sequences` |
| **8.9b** | lifecycle stage verbs — `_cluster` + `_fix` (§8.1 snapshot, §8.2 recurrence) | §3.2, §5, §8.1–8.2 | `c4-l3-lifecycle`, `c4-l3-agent-dispatch` |
| **8.9c** | lifecycle write verbs — `_push` + `_rereview` + `_resolve` | §3.2, §3.4 | `c4-l3-lifecycle`, `sequences` |
| 8.10 | run loop (_run, _wait, run verb, escalation/human-review, sweep) | §3.3, §4.2 | `sequences` |
| 8.11 | status verb + merge-gate contract (status --json, §4.4/§4.6) | §4.4, §4.6 | `data-view` |
| 8.12 | deterministic verbs (reply + CONTEXTUAL memory routing, resolve-escalated) | §3, §4, §8.3 | `c4-l3-lifecycle` |
| 8.13 | Phase-1 cutover (monitor-pr, retire Skill A, hook/rule repoint) | §6.2, §6.4 | `c4-deployment` |
| 8.14 | Phase-2 retirement (delete reply-and-resolve-pr-threads, re-repoint) | §6.3 | — |

---

## 7. Control architecture (vehicle = D6)

The **main session is the supervisor**: owns the milestone frontier, worktree creation, branch
stacking, PR creation, Copilot waits, `bd` state, the live-demo run, and the distress tripwires.
Each bead's heavy lifting goes to a **fresh, worktree-isolated subagent** (clean context). Stateful
delivery (git/gh/PR/Copilot) stays in the main loop where results are visible and recoverable.
Optionally, inside a single bead, a small `Workflow` may do the test-design/implement/review
fan-out; default to plain subagent dispatch.

---

## 8. Per-bead pipeline (run for each bead in the milestone, in dependency order)

1. **Claim + isolate.** `bd update <bead> --claim` (→ in_progress). Worktree under
   `.claude/worktrees/<bead-shortname>` via `EnterWorktree`, based on: `main` for the first bead
   on top of the last-merged base; the previous bead's branch for stacked siblings.
2. **Implement (fresh subagent, in the worktree).** Per the dispatch contract (§9): read the cited
   design-doc section(s) + HLD(s) → `writing-plans` → `test-driven-development` → reach
   **`make ci-prgroom` green at 90% branch coverage**. Explicit instruction: **halt and escalate
   rather than write tautology/anti-pattern tests** to clear coverage (`writing-unit-tests`).
3. **Completion gate (mandatory, in order).** `quality-reviewer` → address → `simplify` → address
   → `verify-checklist` with evidence.
4. **Deliver.** `finishing-a-development-branch` → push → PR **targeting the base branch** (not
   `main`, for stacked beads) → `wait-for-pr-comments` (Copilot; classify FIX/SKIP/ESCALATE; fix
   FIX items; chains to `reply-and-resolve-pr-threads`).
5. **Stop short of merge.** **Do NOT merge. Do NOT `bd close`.** Record the PR URL:
   `bd update <bead> --append-notes "PR: <url>"`. Leave the PR open.
6. **Advance.** Next bead branches off this bead's branch.

**At milestone end:** run the **live demo** (§4 table) and capture its output as evidence (D11),
then go to §10 (report) and HALT. **Special case (D10):** the very first run stops after `8.1`
alone — report the scaffold + `make ci-prgroom` result, await go-ahead before continuing M1.

---

## 9. Per-bead subagent dispatch contract (give to each implementer subagent)

> You are implementing bead `<id>` (`<title>`) of the prgroom CLI, in the worktree at `<path>`
> (already created; work only there). prgroom is a Python package replacing two PR-grooming skills
> with deterministic, testable verbs.
>
> **Read first (do not infer from any summary):** `docs/plans/2026-05-12-prgroom-cli-design.md`
> §`<sections>`, and `docs/architecture/prgroom/<hlds>`. Mirror the structure and toolchain of
> `packages/installer/` (the established template).
>
> **Build:** Follow `writing-plans` then `test-driven-development`. Package at `packages/prgroom/`.
> Your work must make **`make ci-prgroom` pass green** from the worktree root: ruff check,
> ruff format --check, `mypy --strict src`, pytest `--cov` at **90% branch coverage**
> (`fail_under = 90`, `branch = true`), `pip-audit` (uv sync --frozen), and `verify-entry-prgroom`
> (`uv --project packages/prgroom run prgroom --help`).
>
> **Hard rule:** If you cannot reach 90% branch coverage without anti-pattern tests (tautologies,
> testing the language/stdlib, asserting on mocks), **STOP and report blocked** — do not ship
> coverage-gaming tests (`writing-unit-tests`).
>
> **Completion gate (before declaring done):** `quality-reviewer` → fix → `simplify` → fix →
> `verify-checklist` with evidence.
>
> **Do NOT:** create the PR, merge, push to main, run `install.sh`/`install.py`, or `bd close`
> anything. Commit on your worktree branch only. Report: what you built, the `make ci-prgroom`
> result (paste output), coverage %, completion-gate findings + resolutions, any blocker.

### Bead 8.1 specific scope (confirm against design §6.7 + §7 — the spec wins; greenfield, no `packages/prgroom/` exists)

Expected deliverables (verify against the spec):
- `packages/prgroom/` with `pyproject.toml` (uv; deps incl. typer; dev: ruff, mypy, pytest,
  pytest-cov; `[tool.coverage.run] branch = true`, `[tool.coverage.report] fail_under = 90`).
- `src/prgroom/`: `cli.py` (typer root + verb skeletons: poll, cluster, fix, push, rereview,
  reply, resolve, resolve-escalated, wait, status, run, sweep), `prsession/` (Store Protocol +
  state dataclasses `PRGroomingState`/`ReviewItem`/`Disposition`/`ReviewerState`; `memory`
  adapter; `file` adapter stub; `write_atomic`; `SCHEMA_VERSION=1`), Cluster/Fix contract
  Protocols + `contract_version`, `Tier` StrEnum + `PreconditionError`, `EscalationSink` Protocol,
  `Deps.clock`/`Deps.randomness`, TOML config loader, precondition gating tiers.
- `tests/unit/` + `tests/integration/` + `conftest.py`.
- **Makefile:** add `ci-prgroom` (+ `lint/format-check/typecheck/cov/audit/verify-entry-prgroom`)
  mirroring `ci-installer`, and wire `ci-prgroom` into the root `ci` target.
- console-script entry point `prgroom`.
- All green under `make ci-prgroom`.

---

## 10. Halt + report (milestone end, intra-M1 8.1 checkpoint, or distress)

Structured report:
- **Per bead:** status (`PR-open` / `halted`), PR URL, `make ci-prgroom` result, coverage %,
  Copilot disposition, worktree path, branch + base branch.
- **Milestone live-demo output** (D11) — paste the actual `prgroom …` command output as evidence
  the capability works. (Skip for the 8.1-only checkpoint — report scaffold + CI result instead.)
- **If halted by distress:** which tripwire fired + exact failing output. Leave the in-flight
  bead's worktree + partial PR intact; touch nothing downstream.
- **Stack + suggested merge order** (bottom-up).
- **Next milestone / next beads** (recompute frontier from §5).

Then **STOP**. Wait for Scott.

### Distress tripwires (any one → halt; do not start the next bead)

1. `make ci-prgroom` won't go green after **2 full fix attempts**.
2. Can't hit 90% branch coverage without anti-pattern tests.
3. Implementer subagent **escalates or returns blocked** (genuine spec ambiguity, or spec-vs-code
   conflict L0–L3 can't resolve).
4. A **blocking `quality-reviewer` finding** survives one fix pass.
5. **Copilot** returns a security finding, or FIX items unresolved after one pass.
6. Subagent **dies / times out / returns null**.
7. **git / worktree / PR op fails** in a way needing human hands.
8. **Thrash:** identical failure repeats across attempts (no forward progress).

---

## 11. Rejected approaches (do not re-litigate)

- **Arbitrary "N beads per batch" (dropped).** A count is not a checkpoint; it tells you when to
  stop, not whether a capability is complete. Replaced by capability milestones (§4) that are each
  live-testable against a real PR.
- **6 milestones without re-cutting 8.9 (rejected).** Keeping 8.9 whole forces the first read-only
  tracer to drag in the entire agent-dispatch arm (8.4/8.7) it never uses — 8 beads to first demo
  instead of 6, and the read-only→write safety line is not a clean stop. The 3-way 8.9 re-cut (D9)
  buys the early tracer for ~1 bead split + a few dep re-points.
- **Opus→Sonnet quota self-governance (dropped earlier).** Verified: the session transcript JSONL
  records `message.model` per turn (ground truth); statusline JSON exposes `model.id` +
  `rate_limits.five_hour/seven_day.used_percentage` (proactive gauge). BUT a `Workflow` script has
  no filesystem/clock/model-introspection (only a token `budget`), so it cannot self-detect
  fallback — detection can only live in the main session; and there is **no setting to make Claude
  Code hard-error instead of silently downgrading**. Best achievable bound was "no new bead starts
  on Sonnet; fallback caught within one bead." Discarded in favor of human-gated milestone
  boundaries, which never misfire.
- **Monolithic overnight Workflow doing all beads (rejected).** Workflows can't durably own
  worktree/PR/Copilot state; good at fan-out, bad at long stateful delivery.
- **Auto-merge on green (rejected).** Chosen under the "runs overnight while asleep" premise; the
  milestone-boundary check-in makes a human merge gate cheap → stacked-PRs-human-merges (D3).

---

## 12. Pre-flight reminders for the executing agent

- **Step 0 = the 8.9 re-cut** (§3) — only after go-ahead; verify bd capabilities/arg order first.
- **Never run `install.sh` / `install.py`** automatically (repo rule). 8.6/8.13 *modify* install
  scripts as code, never *invoke* the installer.
- **Worktrees** live under `<repo-root>/.claude/worktrees/`. The grinder does not merge, so
  post-merge worktree cleanup is Scott's (or a later milestone's) step.
- **Run `make ci-prgroom` from the bead's worktree root** (each worktree has its own checkout incl.
  the `Makefile`); never run against, or write into, the main tree.
- **bd state:** set `in_progress` on claim; record PR URL in notes; never `close` (Scott closes on
  merge).
- **Never run `graphify update .` from a bead worktree** — it commits worktree-specific graph data
  and repoints `.graphify_root`, polluting the PR. The graph refresh is deferred to `main` after the
  stack merges (a post-merge maintenance step), never on a feature branch.
- This is a dated plan file → bead IDs are allowed here (the no-tracker-IDs rule exempts dated
  plan/spec/audit files).
- **First run stops after `8.1` alone** (D10); subsequent runs go milestone-by-milestone.
