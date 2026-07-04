# Cross-Model HEAVY Gate Panel

**Date:** 2026-07-04
**Status:** Draft — proposed design for bead `agents-config-abn9.40.4`
**Parent epic:** Post-Fable economics (`agents-config-abn9.40`)
**Related:** `2026-07-02-completion-gate-routing-design.md` (routing tiers, scale_hint), `2026-07-03-adversarial-loop-convergence-decision.md` (the successor discipline this must stay compatible with), the in-flight **model-routing policy and escalation ladder** spec (per-archetype preferred + fallback routing — panel archetypes route through it)

## Problem

The HEAVY completion-gate tier runs the `quality-gate` workflow: multi-lens finders → adversarial refuter panels + fix wave → synthesis. Every one of those agents is spawned through the Workflow harness's `agent()` with **no model override**, so the whole fleet inherits the session model. Post-Fable, that means an expensive model doing finder work a cheap model can do, and — worse for review quality — a **same-model monoculture**: finders, refuters, and synthesizer share one model's blind spots. The repo's mission commitment #3 is to substitute *adversarial cross-model review* for human review; the HEAVY gate is the flagship review surface and currently has zero model diversity.

Bead acceptance criteria:

1. The `quality-gate` workflow no longer spawns same-model fleets by default.
2. Cost per HEAVY run is measured.

## Goals

- Re-point the HEAVY panel's **finder** roles to foreign-CLI models (Codex `gpt-5.4-mini`, Gemini, OpenCode budget profiles) plus a cheap native-Claude baseline, so each lens is covered by a *different* model where availability allows.
- Route **synthesis** to Opus (judgment-dense, per the subagents right-sizing rule).
- Degrade gracefully: a missing/unauthenticated foreign CLI never blocks the gate; its lenses fall back down a declared chain, and the degradation is reported, never silent.
- Emit a **per-run cost record** so HEAVY runs become economically observable.

## Non-goals

- No change to SKIP/SERIAL tiers, gate-triage, or the tier-floor rules.
- No change to the interim loop's convergence semantics (round cap, dual-signal exit, dedup-vs-seen). The convergence discipline (M3 lineage, decision record D1–D15) replaces the loop's *shape* later; this spec only re-points *who staffs it*.
- No new refuter design. Refuter panels are slated for retirement by the convergence discipline (its D8 replaces them with an evidence-based judge layer); investing in cross-model refuters now would be building on a condemned foundation.
- No OpenRouter provider wiring itself — that is `agents-config-abn9.40.3`; this spec consumes its output (OpenCode profiles) when present.

## Design

### 1. Role → model matrix (the re-point)

The panel has four staffed roles. Per the per-archetype principle from the model-routing spec (workers are not homogeneous; each archetype gets a preferred model + ordered fallback chain):

| Role (archetype) | Work character | Preferred staffing | Fallback chain |
|---|---|---|---|
| Finder | Breadth reading, pattern spotting — cheap, parallel, diversity-sensitive | **Cross-model spread**: each lens assigned round-robin across the available provider set {codex:gpt-5.4-mini, gemini, opencode:budget-profile, claude:haiku-low} | Unavailable provider → next provider in the set → native claude haiku/low (always available) |
| Refuter | Interim mechanism, condemned by convergence D8 | Native Claude, sonnet / medium effort (unchanged) | — |
| Fixer | Writes the working tree | Native Claude, sonnet / medium effort | — (foreign CLIs stay read-only in the gate; tree writes remain native so worktree discipline and sandbox rules hold) |
| Synthesizer | Judgment-dense residual-risk narrative | **Opus, high effort** (per bead: "opus synthesis") | Session-model at `scale_hint.synthesis_effort` (current behavior) |

Default flip (AC 1): when **at least one** foreign provider passes the availability probe, the finder roster is cross-model. The native-only fleet is now the *degraded* mode, reached only when zero foreign providers are available — and reported as such in the run output.

`ASSUMPTION:` the Workflow harness `agent()` accepts `model: 'haiku'`/`'opus'`/`'sonnet'` overrides from workflow scripts the same way the Agent tool does. If a given id is rejected, the adapter keeps the harness default and the cost record marks the substitution.

### 2. Foreign finders run behind native adapter agents

Foreign CLIs cannot be spawned directly by the Workflow harness — they have no `agent()` presence, no StructuredOutput, no budget accounting. The gate therefore staffs each foreign lens with a **finder adapter**: a native `agent()` call (claude haiku, effort low — mechanical work) whose entire job is:

1. Render the lens brief + diff context into a prompt file using the severity-rubric template already proven by ralf-implement's foreign-review flow (BLOCKING/CRITICAL/MAJOR/MINOR, file/line/issue/recommendation output contract).
2. Invoke the assigned CLI **read-only**:
   - Codex: through the Codex plugin companion (`codex-companion.mjs task`, prompt on stdin, no `--write`), per the Codex routing rule; model `gpt-5.4-mini` (first-pass review profile).
   - Gemini: headless plan-mode text output (the ralf foreign-review invocation shape).
   - OpenCode: the budget profile (GLM 5.2 / Fugu Ultra) installed by `abn9.40.3`.
3. Parse the rubric-formatted stdout into the existing `FINDINGS_SCHEMA` (severity mapped 1:1; `fixClass` defaulted to `semantic` unless the foreign reviewer's recommendation is a plainly local, behavior-preserving edit — when unsure, `semantic`, matching the schema's own guidance).
4. Report the CLI's usage figures (tokens/cost if the CLI emits them; otherwise a size-based estimate) in a `usage` side-channel field for the cost record.

The adapter preserves every existing harness property: bounded StructuredOutput (the "work lands, report dies" guard), `parallel()` scheduling, resume-from-run-id, budget visibility for the native half, and the untrusted-content fence — foreign stdout is data, fenced exactly like finder output is today before it reaches refuter/fixer prompts.

`ASSUMPTION:` Gemini's headless flags (`-p "" --approval-mode plan -o text`) and the Codex companion contract remain as documented in the ralf foreign-review template and Codex routing rule. The adapter treats a non-zero exit, empty stdout, or unparseable output as **provider failure** (see §4), never as "no findings."

### 3. Availability probe

A deterministic preflight (script, not judgment — code over prose) runs once per gate invocation, before fleet sizing:

- **codex**: companion script resolvable AND `codex` authenticated (the plugin's own status check).
- **gemini**: binary on PATH AND a cheap no-op invocation exits 0.
- **opencode**: binary on PATH AND the budget profile from `abn9.40.3` present in config. Until `abn9.40.3` lands, this probe always reports unavailable — the design needs no special casing for the interim.

The probe emits `{providers: {codex: bool, gemini: bool, opencode: bool}, detail: [...]}`. It is packaged with the gate assets (not inline JS) so Codex/Gemini/OpenCode-hosted gates can reuse it later, per the composability requirement (convergence decision D15).

Probe output feeds lens assignment: lenses are dealt round-robin across the available providers in the fixed order `codex → gemini → opencode → claude-haiku`, so a 4-lens run with all three foreign providers available gets 4 distinct models (maximum diversity per finding surface); with one foreign provider it alternates foreign/native; with zero it is all-native and flagged degraded.

### 4. Degradation path

Failure is handled at two moments, both non-blocking:

- **Probe-time**: provider unavailable → its lens slots reassign down the chain (next foreign provider, then native haiku). Reported in the workflow log line and in the result object (`panel.degraded: true`, `panel.missing: [...]`).
- **Run-time**: an adapter whose CLI call fails (non-zero exit, timeout, unparseable output) retries once, then **falls back in-place to a native haiku finder for that lens in the same round** — the lens is never silently dropped (the no-silent-caps rule). The substitution is recorded per-lens in the cost record.

The gate's fail-shape therefore matches gate-triage's own: measurement failures degrade toward *more* native coverage, never toward skipped coverage.

### 5. Cost record (AC 2)

Every HEAVY run appends one record to the user-space spend ledger defined by the model-routing spec (append-only JSONL, user-scoped so accrual spans sessions and projects) and mirrors a summary into the workflow result object:

```json
{
  "kind": "heavy-gate-run",
  "bead": "<bead-or-branch>",
  "native_output_tokens": 184000,
  "foreign": [
    {"provider": "codex", "model": "gpt-5.4-mini", "lenses": ["security"], "usage": {...}, "estimated_usd": 0.04}
  ],
  "panel": {"lenses": 4, "assignment": {"correctness": "gemini", "...": "..."}, "degraded": false},
  "rounds": 2, "exit": "acceptance"
}
```

- Native side: `budget.spent()` at exit (the harness's own counter).
- Foreign side: per-adapter `usage` capture, priced by the user-configured per-model rates from the model-routing spec's ledger design. `ASSUMPTION:` where a CLI emits no usage figures, the adapter estimates from prompt+output size and marks the entry `estimated: true`; the ledger is an estimates ledger, not an invoice.

This makes "cost per HEAVY run" a queryable fact (weekly rollup is `abn9.40.1`'s telemetry bead; this spec only guarantees the records exist).

### 6. Configuration

`project-config.toml` `[completion-gate]` gains one key:

- `heavy_panel = "cross-model" | "native"` — default **cross-model** (the flip is the point of the bead). `native` is the explicit opt-out for repos where foreign CLIs must not read the code (e.g. corporate/no-cloud constraints on the work machine — the PORT milestone's overlay carries per-machine defaults).

Everything else (lens roster, refuter width, round cap, synthesis effort) keeps its existing `scale_hint`/constant sourcing — no new knobs without evidence they earn their keep.

### 7. Compatibility with the convergence discipline

The convergence decision restructures the *loop* (delta-scoped rounds, judge layer, certification pass) but keeps the same staffing archetypes: specialist finders, evidence verifiers, a triage bench, a fixer. The pieces this spec builds — the availability probe, the foreign finder adapter + rubric-output parser, the per-run cost record — are exactly the composable tier the decision record's D15 demands, and carry forward unchanged: cross-model *discovery* staffing is orthogonal to how rounds converge. Nothing here deepens investment in the refuter mechanism D8 retires.

## Acceptance criteria

1. With at least one foreign provider available, a HEAVY `quality-gate` run assigns at least one finder lens to a non-session-model provider, and the run result names the per-lens assignment. (Bead AC 1.)
2. With zero foreign providers available, the run completes on the native fleet and reports `panel.degraded: true` with the missing providers listed — never blocks, never silently pretends diversity.
3. A run-time adapter failure on one lens still yields finder coverage for that lens (native fallback), recorded in the result.
4. Every HEAVY run appends a `heavy-gate-run` record (native tokens + foreign usage + panel assignment) to the spend ledger and includes the summary in the workflow result. (Bead AC 2.)
5. Foreign stdout is fenced as untrusted data everywhere it enters a native prompt, matching the existing finder-output fencing.
6. `heavy_panel = "native"` restores the current all-native behavior verbatim.

## Implementation shape (for the planning pass, not binding)

- `quality-gate.js`: probe call, lens→provider assignment, adapter prompt builder, cost-record assembly, `model:` overrides on synthesis (`opus`/`high`) and native finders (`haiku`/`low`).
- New probe + rubric-parse helpers as small tested scripts alongside the gate assets (Python/Node over inline bash, per repo principle).
- Reuse, don't fork, the ralf foreign-review prompt template — one severity rubric across both consumers.

## Open items

- `ASSUMPTION:` harness `agent()` model-override ids (`haiku`/`opus`) are accepted in workflow scripts; substitutions are recorded when rejected.
- `ASSUMPTION:` Gemini/Codex headless invocation contracts as documented in the ralf template and Codex routing rule still hold on both target machines.
- `ASSUMPTION:` OpenCode participation is gated on `abn9.40.3` (budget profiles); until it lands the probe reports opencode unavailable and the design runs codex+gemini+native.
- `ASSUMPTION:` foreign usage figures may be estimates (size-based) where the CLI emits none; the ledger records `estimated: true` rather than blocking on exact billing data.
- `ASSUMPTION:` refuters and fixers stay native-Claude in the interim; revisiting that is explicitly deferred to the convergence-discipline implementation, which replaces refuters wholesale.
