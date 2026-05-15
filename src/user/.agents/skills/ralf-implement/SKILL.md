---
name: ralf-implement
model: opus[1m]
effort: xhigh
argument-hint: "[target + DoD + context + optional max cycles + subagent_type]"
description: Explicit invocation only — iterative implementation with adversarial fresh-eyes cycles; inner-methodology only (no worktree or delivery ownership)
---

# ralf-implement

Iterative implementation methodology for code changes. This skill owns only the inner quality loop.

The caller must provide the target, Definition of Done, relevant context, optional max cycle count, and the doer's `subagent_type` (the worker agent that will run the inner implementation dispatch). This skill owns no outer workflow state: no worktree setup, branch delivery, PR creation, tracker updates, or dispatch-formula decisions.

## Required inputs

The invocation must include or already have in context:
- target task or implementation goal
- original specification or acceptance criteria
- Definition of Done
- relevant architectural context and quality commands
- `subagent_type` of the doer worker (see §"Doer subagent_type contract")
- optional max cycles, integer `1..20`

Fail fast when the target or Definition of Done is missing, the optional max cycle count is malformed or out of range, required referenced context cannot be read, or the project quality commands cannot be identified.

## Worker-report-v1 consumption

This skill consumes `worker-report-v1` YAML reports produced by each dispatched doer worker. Per the shared core (see `docs/specs/worker-report-v1.md`), every worker writes a report file containing:

- `status` (`complete | needs_human | failed`) — the worker's terminal verdict.
- `evidence` — optional per-kind evidence blocks (`tests`, `build`, `lint`, `typecheck`). Each present evidence block carries `command`, `exit_code`, `skipped`, and (for `tests`) `passing` / `failing`. See `worker-report-v1.md` §1.1.
- `escalations`, `discovered_work`, `commits` — orchestrator handoffs.

After each dispatch, this skill reads the report from the orchestrator-supplied path and computes the **derived gate roll-up** per `worker-report-v1.md` §1.1:

| Derived gate | When |
|--------------|------|
| `pass`       | Every present evidence block has `skipped == false` AND `exit_code == 0` |
| `fail`       | At least one present evidence block has `skipped == false` AND `exit_code != 0` |
| `partial`    | At least one present block has `skipped == true`, AND no present block satisfies the `fail` rule |
| `n/a`        | `evidence` is `{}` (e.g., synthetic crash report or docs-only dispatch with no runnable gates) |

Workers do NOT emit `gate_status`; the orchestrator (this skill, per cycle) derives it from the evidence blocks. The status verdict and the derived gate roll-up are independent signals — both feed the convergence predicate below.

## Doer dispatch via Agent tool

The doer is dispatched via the **Agent tool** from this skill's host session. The dispatch argument list:

```
Agent({
  subagent_type: <required: see "Doer subagent_type contract">,
  prompt: <the substituted template body for this cycle>
})
```

The `subagent_type` argument is **required** — this skill never dispatches without it. The actual per-dispatch primitive (build worker task-spec, allocate report path, classify worker exit, derive gate, stamp audit label, synthesize on crash/malformed) is owned upstream — see `implement-bead/SKILL.md` §4 per-dispatch primitive, which this skill calls into per cycle. The §4 primitive is not inlined here; this skill is the loop layer.

## Doer subagent_type contract

The doer's `subagent_type` is required. If the caller did not pass one, resolve it as follows.

### Interactive context (default)

Prompt the user with EXACTLY these two options:

1. `tdd-green-team` — canonical worker for green-loop (implementation) cycles. Emits a `tdd-green-report-v1` YAML.
2. `general-purpose` — the Claude Code builtin fallback worker. Use for docs-only or non-test-runner dispatches.

Other named worker types — `tdd-red-team` and `bug-diagnoser` — are **NOT offered** as prompt options. `tdd-red-team` writes the failing tests in the red-tests stage and never participates in the green-loop iteration this skill drives; `bug-diagnoser` is direct-dispatch from the diagnose stage and is not iterated. (Their names may appear elsewhere — e.g. in the `worker-audit-*` label policy below — but they are explicitly excluded from the prompt-option list.)

If the user declines both options, this skill aborts with a diagnostic. Decline-abort diagnostic text:

> "ralf-implement: declining both prompt options aborts the loop. Re-invoke with an explicit subagent_type (tdd-green-team for green-loop work, general-purpose for non-test-runner dispatches). No iteration was attempted."

### Non-interactive context

If the caller passed `non_interactive: true` as an argument, OR the environment variable `RALF_NONINTERACTIVE=1` is set, this skill **fails fast** when `subagent_type` is missing — no prompt is offered. The fail-fast diagnostic is identical to the decline-abort diagnostic above but prefixed with `[non-interactive]`.

This means: in autonomous contexts (run-queue, bead-driver shells, formula-driven dispatch), the caller MUST pass `subagent_type` explicitly. The interactive prompt is only honored when both `non_interactive` is absent/false AND `RALF_NONINTERACTIVE` is unset.

## Worker-audit label policy

Per `worker-report-v1.md` §3 and `implement-bead/SKILL.md` Audit-label scope:

- `worker-audit-<agent-name>[-iter<N>]` SHOULD be stamped on the step-bead for every dispatch of a **named worker** (`tdd-red-team`, `tdd-green-team`, `bug-diagnoser`).
- `general-purpose` and other non-worker doers SHOULD NOT carry a `worker-audit-*` label — they are out-of-band of the named-worker forensic namespace.
- This is documentation-only policy here; the actual label stamping happens inside the per-dispatch primitive in `implement-bead/SKILL.md` §4.

Upstream tracking: full enforcement of the "named-worker only" audit-label restriction is tracked under `agents-config-go1w`. Until `agents-config-go1w` lands, `general-purpose` dispatches via `implement-bead/SKILL.md` §4 per-dispatch primitive WILL receive `worker-audit-general-purpose-iter<N>` labels — this is a known transient overreach, not a violation of the policy stated here.

## Core invariants

1. **Iteration** — multi-pass, bounded by a cycle cap.
2. **Independence** — each fresh-eyes pass is a new subagent with no prior-cycle context.
3. **Adversarial posture** — each pass searches for missing, weak, or incorrect behavior.
4. **Convergence** — stop when the convergence predicate accepts the current cycle's report, or when the cycle budget is exhausted.

## Cycle budget contract

Default cycle cap: `RALF_IMPLEMENT_DEFAULT_CYCLES=3`

The caller may pass an explicit max cycle count. If absent, use the default. Reject malformed, duplicate, or out-of-range cycle inputs instead of guessing.

## Iteration routing

Per cycle:

1. **Dispatch the doer.** Read the appropriate template by relative path, substitute the uppercase-bracket placeholders, and call `Agent({ subagent_type: <doer>, prompt: <substituted-body> })`. Templates read fresh on each dispatch — no caching.
   - cycle 1: Codex (`gpt-5.5`) via foreign-cycle dispatch — see `./subagent-foreign-cycle.md` and `./foreign-cli-instructions.md`.
   - cycle 2: Gemini via foreign-cycle dispatch — same templates, agent=gemini.
   - cycle 3+: pure-Claude fresh-eyes via `./subagent-fresh-eyes.md`.
2. **Read the worker's report** from the orchestrator-supplied path. Apply R1.4.1 synthesis-path extension below if the report is malformed.
3. **Compute the derived gate roll-up** from the evidence blocks per `worker-report-v1.md` §1.1.
4. **Apply the convergence predicate** (see "Convergence predicate" below) using both `status` and the derived gate roll-up.
5. **Run the per-cycle loop steps** (quality-reviewer + simplify) ONLY on convergence candidates.
6. **Decide**: converge, iterate next cycle, or — at cycle cap — emit `PASS_WITH_RESERVATIONS` or `FAIL`.

### Template-path references (operational procedure)

Iteration-routing references each prompt template by concrete relative path AS DOCUMENTATION REFERENCES:

- `./subagent-implementer.md` — initial implementer dispatch (when this skill is invoked from a cold start with no prior iteration). Used by callers that want a clean first-pass before fresh-eyes review.
- `./subagent-fresh-eyes.md` — pure-Claude fresh-eyes pass (cycle 3+).
- `./subagent-foreign-cycle.md` — foreign-eyes dispatch wrapper (cycles 1–2).
- `./foreign-cli-instructions.md` — instruction file piped on stdin to `codex-companion.mjs task` (Codex) or `gemini` (Gemini). This file is piped to the foreign CLI on stdin — it is NOT inline-pasted into an Agent-tool prompt; the foreign CLI sees it as the review request, not as a Claude subagent prompt.

Operational procedure on every cycle:

1. Read the template file by relative path (e.g. `./subagent-fresh-eyes.md`).
2. Substitute the uppercase-bracket placeholders (e.g. `[PASTE ORIGINAL DOD]`, `[PASTE ORIGINAL SPEC]`, `[PASTE CONTEXT]`, `[ARCHITECTURE / CONVENTIONS / RELATED FILES]`). This `[...]` style applies to the Claude subagent templates (`subagent-implementer.md`, `subagent-fresh-eyes.md`, `subagent-foreign-cycle.md`) that are dispatched via the `Agent` tool. The foreign-CLI instruction file (`foreign-cli-instructions.md`) is a separate template piped to Codex/Gemini on stdin and uses lowercase curly-brace placeholders (`{dod}`, `{spec}`, etc.) — substitute those when constructing the foreign-CLI stdin payload, not when constructing an `Agent` prompt.
3. Dispatch via `Agent({ subagent_type: <doer>, prompt: <substituted-body> })`.

Templates are read fresh on each dispatch — no caching. `subagent-implementer.md` is used for the INITIAL cold-start dispatch only (before any numbered fresh-eyes cycle); cycles 1/2/3+ are fresh-eyes passes using `subagent-foreign-cycle.md` (cycles 1–2) or `subagent-fresh-eyes.md` (cycle 3+). Prior-cycle findings are NEVER injected into the substituted prompt — Core Invariant 2 (independence) forbids it.

### Degradation cascade

- Cycle 1 foreign-eyes via Codex → if degraded (UNAVAILABLE / TIMED_OUT / QUOTA_EXCEEDED / AUTH_FAILED / NO_OUTPUT / UNUSABLE_OUTPUT), fall back to Gemini for that same cycle index.
- If Gemini also degrades, fall back to pure-Claude fresh-eyes for that cycle index.
- Cycle still counts against the cap regardless of which tier produced the cycle's report.
- **Evidence-store canonicalization**: both attempt artifacts persist on disk (the degraded foreign-CLI output AND the fallback agent's output are both written to the session evidence store). The fallback agent's output is the canonical report for that cycle — the orchestrator reads the fallback's report; the degraded artifact is retained as forensic context only.

## Convergence predicate

A cycle's report is a **convergence candidate** when ALL of the following hold:

1. `status=complete` (a real-or-synthesized `status=failed` is NOT a convergence candidate — see the `status=failed` row of the table below).
2. The derived gate roll-up is `pass` OR `n/a`. The `status=complete + gate=pass` branch is a convergence candidate when fresh-eyes finds no blocking/critical findings; the `status=complete + gate=n/a` branch is a convergence candidate where fresh-eyes alone decides.
3. The fresh-eyes (or foreign-eyes) review attached to the cycle finds no `blocking` or `critical` findings.

Enumerated decision table:

| status        | derived gate | fresh-eyes severity         | Convergence candidate? | Action |
|---------------|--------------|-----------------------------|------------------------|--------|
| `needs_human` | any          | any                         | NO                     | abort immediately; surface worker's `escalations[]` to caller; do NOT iterate; do NOT run quality-reviewer/simplify |
| `failed`      | any          | any                         | NO                     | iterate (or — at cap — FAIL) |
| `complete` | `pass`       | no blocking/critical        | YES                    | converge (within cap) → PASS |
| `complete` | `pass`       | blocking or critical present | NO                    | iterate (or — at cap — see scoring below) |
| `complete` | `n/a`        | no blocking/critical        | YES                    | converge; fresh-eyes alone decides (no gate to consult). NOTE: workers do NOT emit `gate_status` — the orchestrator derives `gate=n/a` from an `evidence.tests.command` that is explicitly empty/absent. For a tdd-green-team dispatch in a test-capable repo, an empty `evidence.tests` block is treated by the orchestrator as `gate=fail` (the worker failed to exercise the runner), not `gate=n/a`. |
| `complete` | `n/a`        | blocking or critical present | NO                    | iterate (fresh-eyes findings hold; nothing else to consult) |
| `complete` | `fail`       | any                         | NO                     | iterate (gate must turn green) |
| `complete` | `partial`    | any                         | NO                     | iterate (skipped gates are not implicit passes) |

**At cycle cap** (cycles exhausted with no convergence candidate yet accepted):

- Score = `PASS_WITH_RESERVATIONS` when the final cycle has `status=complete` AND the derived gate roll-up is in `{pass, n/a}` AND the final cycle's fresh-eyes pass found no `blocking` or `critical` issues. Open `major` issues are allowed and ARE the "reservations".
- Score = `FAIL` otherwise — i.e., the final cycle either has `status: failed`, or its derived gate is `fail`/`partial`, or it carries unresolved `blocking`/`critical` findings.

### R1.4.1 synthesis-path extension (malformed evidence sub-blocks)

The per-dispatch primitive in `implement-bead/SKILL.md` §4 already synthesizes `status: failed` on worker crash (non-zero exit OR no file at the target path) and on top-level malformed report (parse error, missing `status`). This skill extends that synthesis path with one further trigger:

- A present `evidence` block (e.g. `evidence.tests`) that is **missing one of its required sub-fields** (`command`, `exit_code`, `passing`, `failing`, `skipped` — per `worker-report-v1.md` §1.1) is treated as a malformed report. The orchestrator synthesizes a `status: failed` report with `escalations[].reason: "Worker emitted malformed report"`, wrapping the missing-sub-field name and the raw bytes of the worker's file in `escalations[].detail`.

This extension means: a worker that emits a top-level-parseable YAML but supplies a `tests` block with `command` only (no `exit_code`, no `skipped`) is **not** a convergence candidate — its report fails the synthesis-path check before the derived gate is computed. Synthesized `status: failed` reports always have `evidence: {}` (per `worker-report-v1.md` §4), so their derived gate is `n/a` — but `status=failed` short-circuits the convergence predicate (the `status=failed` row of the table above) regardless of gate.

## Per-cycle loop steps

After each dispatch, the orchestrator decides whether to run `quality-reviewer` and `simplify` based on convergence-candidate status:

- **Convergence candidates** (status=`complete` AND gate ∈ `{pass, n/a}`): run `quality-reviewer` (ONLY on convergence candidates) and `simplify` (ONLY on convergence candidates) as the per-cycle loop quality steps.
- **Non-candidates** (status=`failed`, or gate=`fail`, or gate=`partial`): skip `quality-reviewer` and `simplify`; dispatch the next cycle (or — at cap — emit `FAIL`).

**quality-reviewer rejection rule**: if `quality-reviewer` finds `blocking` or `critical` issues on a convergence candidate, the candidate is **rejected** — it reverts to non-candidate status. Iterate (or — at cap — score as `FAIL` if blocking/critical remain; `PASS_WITH_RESERVATIONS` if only `major` remain after quality-reviewer). `simplify` does NOT run on a quality-reviewer-rejected candidate.

This avoids wasting `quality-reviewer` / `simplify` runs on reports the loop is going to reject anyway.

### simplify advisory-only contract

`simplify` runs on a convergence candidate to propose further clarity/duplication/maintainability edits. It is **advisory** — its output is accepted only when it does not regress the worker's evidence:

1. After `simplify` lands edits, **re-run `evidence.tests.command`** from the worker's report (the same command the worker ran).
2. If any previously-passing test now fails → reject `simplify`'s output, restart the loop via a new worker dispatch (the rejected simplify edits are reverted; the next cycle's worker sees the unsimplified state).
3. If all previously-passing tests still pass → accept `simplify`'s edits; the convergence candidate stands.

**N/A case** (when `evidence.tests.command` is empty, absent, or the gate is `n/a` — e.g., docs-only / config repos with no test runner): accept `simplify`'s output without re-running tests. There is no measurable trigger; fresh-eyes alone is the convergence signal.

This is the only measurable trigger for rejecting `simplify`'s output. The re-run trigger language above is intentionally narrow: the orchestrator re-runs `evidence.tests.command` literally (no transformation, no broader sweep) and checks for "previously-passing test now failing". `simplify` is not a hidden gate — it is advisory cleanup gated by a single behavior-preservation check.

### verify-checklist removed

`verify-checklist` is **no longer** a per-iteration step in this skill. Earlier versions of this skill listed the completion gate as `quality-reviewer` → `simplify` → `verify-checklist` per cycle; the new contract is `quality-reviewer` → `simplify` only, with the evidence-block re-run replacing `verify-checklist`'s role inside the loop. (`verify-checklist` still applies as a downstream gate at workflow boundaries — e.g., before PR creation — but that is outside this skill.)

## Per-cycle dispatch sequence

| Cycle | Doer dispatch                      | Foreign agent  | Default model       |
|-------|------------------------------------|----------------|---------------------|
| 1     | Codex foreign-eyes via `./subagent-foreign-cycle.md` | Codex          | `gpt-5.5`           |
| 2     | Gemini foreign-eyes via `./subagent-foreign-cycle.md` | Gemini         | (default)           |
| 3+    | pure-Claude fresh-eyes via `./subagent-fresh-eyes.md` | (none)         | (default Claude)    |

Cycle 1 = Codex (`gpt-5.5`). Cycle 2 = Gemini. Cycle 3+ = pure-Claude.

Foreign-agent failures degrade per the **degradation cascade** above (Codex degraded → Gemini fallback → pure-Claude fallback). The cycle still counts. The evidence-store retains both the degraded attempt and the fallback artifact; the fallback's output is canonical.

This skill reports convergence state only. The caller decides whether to continue, defer, escalate, or accept with reservations.

## Severity rubric

- **Blocking** — prevents execution, validation, installation, or required delivery.
- **Critical** — violates explicit requirements, creates security/data-loss risk, or makes the implementation materially incorrect.
- **Major** — leaves important behavior, edge cases, tests, maintainability, or integration contracts incomplete.
- **Minor** — localized quality issue, documentation gap, naming issue, or small missing guard that does not threaten correctness.

## Implementation ordering — ralf-review is deferred

This bead (`agents-config-abn9.10`) covers R3.1 (the ralf-implement rename and SKILL.md rewrite). The companion R3.2 (analogous ralf-review rename) and R2.3 (new ralf-review template files) are **deferred** to `agents-config-abn9.13`. The `ralf-review` skill is intentionally left with its current templates and naming until `agents-config-abn9.13` runs — future readers should not assume ralf-review was renamed in this work. The ralf-review rename is deferred deliberately to keep the diff scope on ralf-implement only.

## ralf:required label semantics (canonical home)

This SKILL.md is the **canonical home** for `ralf:required` label semantics. The two formula files (`implement-feature.formula.toml`, `fix-bug.formula.toml`) carry a header pointer comment back here rather than re-stating the semantics inline:

- `ralf:required` on a source bead is the dispatch signal that tells the `green-loop` formula step to invoke this skill (`ralf-implement`) instead of running a single-shot `superpowers:test-driven-development` dispatch.
- `ralf:cycles=N` on the source bead overrides the default cycle cap (`RALF_IMPLEMENT_DEFAULT_CYCLES=3`). The label form is `ralf:cycles=N` where `N` is a decimal integer in `1..20`. Multiple `ralf:cycles=` labels on the same bead are a configuration error — remove existing `ralf:cycles=` labels before adding a replacement.
- `ralf:required` is honored only by `green-loop` (implementation) and (for ralf-review, post-abn9.13) `review-cycle` stages. It does NOT cause this skill to be invoked from `preflight`, `red-tests`, `quality-sweep`, `verify-ac`, `create-pr`, or `merge-or-handoff` — those stages have their own dispatch contracts.

The canonical-home invariant: any future change to `ralf:required` semantics MUST land here first and propagate to formula files via the header pointer comment. Formula files MUST NOT re-state semantics in their own prose.

## Output contract

Produce a structured report with:
- **Score:** `PASS`, `PASS_WITH_RESERVATIONS`, or `FAIL`
- **Score rationale:** one or two concrete sentences
- **Cycles run:** `<n>/<max>`
- **Severity counts:** blocking, critical, major, minor
- **Foreign-eyes status:** per cycle, including degraded Codex/Gemini runs
- **Evidence summary:** per-cycle `status` and derived gate roll-up (`pass | fail | partial | n/a`)
- **Per-cycle loop evidence:** `quality-reviewer` and `simplify` status for the convergence candidate (when one was found)
- **Changes applied:** significant fixes or completion work
- **Remaining concerns:** grouped by severity

Scoring:
- `PASS` — a cycle reached convergence-candidate status and was accepted (no blocking/critical findings; `quality-reviewer` and `simplify` both clean).
- `PASS_WITH_RESERVATIONS` — at cycle cap with status=`complete` AND gate ∈ `{pass, n/a}` AND no blocking/critical findings. Open major concerns are the reservations.
- `FAIL` — cycle budget was exhausted without satisfying the `PASS_WITH_RESERVATIONS` criteria (i.e., status=`failed`, OR gate=`fail|partial`, OR unresolved blocking/critical findings).
