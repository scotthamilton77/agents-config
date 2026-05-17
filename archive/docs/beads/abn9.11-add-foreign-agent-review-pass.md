# Spec: Add foreign-agent review pass to `ralf-review` skill (and rename to `ralf-spec`)

**Bead:** `agents-config-abn9.11`
**Parent milestone:** `agents-config-abn9` (M1 — Stabilize, finish in-flight, ship immediate accelerators)
**Status:** brainstormed; pending implementation
**Authors:** Scott Hamilton, principal engineering assistant (Claude), foreign perspective from Gemini 3 Pro

---

## Summary

Replace the existing single-perspective `ralf-review` skill with `ralf-spec` — a closed-loop adversarial review-and-revise methodology for **text artifacts** (spec docs, design docs, ADRs, bead descriptions). Each cycle dispatches reviewers in parallel, an in-skill Claude reviser applies findings to the target between cycles, and a tiered pipeline (cheap → deep → convergence) controls token spend.

This bead bundles three related changes that share one implementation: (a) introduce foreign-agent review participation, (b) restructure cycles into a tiered pipeline, (c) rename and narrow scope.

---

## Background / motivation

The 2026-04-19 `ralf-it` form re-evaluation design (`docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md`) split the old `ralf-it` skill into `ralf-review` and `ralf-implement`. At that split, foreign-agent review was kept in `ralf-implement` only, with an explicit deferral: "foreign-eyes-prompt may be reused by ralf-review if foreign-agent review of spec/design docs is desired" (line 330–331). This bead is that deferred decision, now triggered.

Three follow-on tensions surfaced during brainstorming:

1. **Single-perspective blindspots.** Claude reviewing a Claude-written spec misses model-specific blindspots. Foreign-agent participation (Codex, Gemini) was the original RALF-IT rationale.
2. **Cycle semantics for immutable targets.** The current `ralf-review` SKILL.md describes "multi-pass" review but is unclear about whether the target evolves between cycles. The actual intent is iterate-with-revisions: findings → revise spec → re-review.
3. **Name vs. scope mismatch.** "ralf-review" is non-specific about *what* it reviews; with the closed-loop revise model, the skill fundamentally operates on writable text artifacts, not code.

Independent input from Gemini 3 Pro flagged additional risks worth designing against:

- **Oscillation:** reviewer A flags X, fixer applies fix, reviewer B flags the fix as defect Y.
- **MINOR-issue loop-trap:** if any finding retriggers a cycle, MINOR findings keep the loop spinning forever.
- **Bikeshedding:** without explicit guardrails, foreign reviewers will critique stylistic choices the author considers intentional.
- **Series vs. fan-out cost:** running reviewers serially pays the spec-rewrite cost N times; fan-out pays it once per cycle.

---

## Requirements

### R1 — Rename and scope narrow

- `src/user/.agents/skills/ralf-review/` → `src/user/.agents/skills/ralf-spec/`.
- `SKILL.md` frontmatter `name: ralf-review` → `name: ralf-spec`; description and argument-hint updated.
- Scope explicitly narrowed to: spec docs, design docs, ADRs, bead descriptions, and other writable text artifacts. Code targets are out of scope (see R10).
- All cross-references in the repo updated (`docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md`, any rule files, formula step bodies, command files, etc.).

### R2 — Input contract: required inputs & fail-fast

The skill accepts exactly one invocation shape. **All five inputs are required.** If any required input is missing or malformed, the skill MUST fail fast with a structured error naming the missing input — do NOT guess, default, or proceed with partial inputs.

| Input | Form | Required | Notes |
|---|---|---|---|
| `target` | File path OR bead ID | Yes | See R3 for resolution semantics. |
| `definition_of_done` | Structured Markdown | Yes | Must contain an **agent-verifiable acceptance-criteria** subsection (see below). |
| `original_spec_context` | Markdown text or file path | Yes | The originating requirements/design context the target was written against. Used by reviewers as the "is the target meeting its goals?" yardstick. |
| `cycle_overrides` | `ralf:cycles=N` label OR direct override | Optional | See R10. |
| `session_id` | Caller-provided slug OR auto-generated UUID | Optional | Used to namespace the staging area (R4). Defaults to ULID if absent. |

**Agent-verifiable acceptance-criteria contract.** The `definition_of_done` MUST contain at least one acceptance criterion that an agent can verify — by inspection of the target, by invoking tools (build passes, grep returns / doesn't return a pattern, script exits 0, file matches a schema, directory contains exactly the listed entries, API returns an expected response, doc structure satisfies a parser, etc.), or by any combination thereof. The criterion need not be a single shell command, but it MUST be something an agent can reach a defensible verdict on without further human input. If the DoD lacks any agent-verifiable AC, the skill MUST stop and surface a structured error of the form:

```
INPUT_CONTRACT_VIOLATION: definition_of_done contains no agent-verifiable acceptance criteria.
At minimum, one AC must be something an agent can verify by inspection or by invoking tools.
The orchestrating agent (or human) must supply one before this skill can run.
```

The skill must NOT attempt to synthesize ACs on the caller's behalf — that is the orchestrator's job, and proceeding without them defeats the purpose of measuring convergence against a defined target.

### R2.1 — Preflight size check (large-spec warning)

After input-contract validation passes but BEFORE any tier begins, the skill performs a size-preflight on the resolved target content:

- **Threshold:** if the target exceeds **200 non-blank lines**, the skill flags it as a large-spec candidate for decomposition.
- **Interactive mode:** the skill emits a structured `USER_DECISION_REQUIRED` block to stdout (machine-parseable JSON, schema below) and exits with code 2. The orchestrator captures the block and re-invokes the skill with one of: `--proceed-monolith=true` (proceed) or a new file-path target pointing at a decomposed-spec set (abort + decompose). The skill itself does not pause for stdin; it returns control to the orchestrator, which owns the user-interaction loop. Recommended: orchestrator invokes the spec-modularization skill (`agents-config-3f52`) once it exists.
- **Autonomous mode:** the skill logs the warning to the staging area's `pipeline-report.json` and proceeds with the monolithic review. (Future: once `agents-config-3f52` lands, autonomous mode will instead auto-invoke that skill before proceeding.)

**`USER_DECISION_REQUIRED` block schema** (used by R2.1 size warning, R5 T3-escalation, and any future skill decision point):

```json
{
  "type": "USER_DECISION_REQUIRED",
  "reason": "LARGE_SPEC | T3_ESCALATION | <other>",
  "context": { "...reason-specific details..." },
  "options": [
    { "id": "proceed", "label": "...", "reinvoke_flags": [...] },
    { "id": "abort",   "label": "...", "reinvoke_flags": [...] }
  ]
}
```

Skill exits with code 2 after emitting the block. Code 0 = pipeline ran to completion; code 1 = unrecoverable error; code 2 = decision required from orchestrator. The orchestrator is responsible for surfacing the decision to a human (in interactive mode) or applying a policy default (in autonomous mode) and re-invoking with the chosen flags.

The threshold is tunable per-invocation by passing a `large_spec_threshold` integer in the input; default = 200. The warning is informational, not a fail-fast gate — the skill never refuses to review a large spec, it only nudges toward decomposition.

Rationale: very large specs lose review-quality regardless of reviewer model. Reviewers struggle to keep the full context coherent; the synthesis pass has more redundancy to deduplicate; the reviser blast-radius grows; the loop is more likely to oscillate. Surfacing this up-front gives the orchestrating agent or user a chance to decompose before paying for a sub-optimal review pass.

### R3 — Target resolution

The skill accepts two target forms:

| Target form | Resolution | Revision mechanism |
|---|---|---|
| File path (e.g. `docs/beads/abn9.11-*.md`) | Read from disk; copy into staging (R4) | `Edit` tool from the in-skill reviser, applied to the staged copy |
| Bead ID (e.g. `agents-config-abn9.11`) | See "Bead-ID field selection" below; selected field copied into staging | `Edit` tool from the in-skill reviser, applied to the staged copy |

For both target forms, the reviser only ever writes to the staged copy (R8 enforces this via path-scope precondition). Write-back to the original (file edit, `bd update`, etc.) is the orchestrating agent's responsibility.

Free-text targets are NOT supported (no writable home). Fail fast on free-text input.

**Bead-ID field selection.** A bead's spec content can live in one of three places: `description`, `notes`, or an externalized `docs/beads/<id>-*.md` file referenced from `description`/`notes`. The skill resolves bead-ID targets as follows:

1. If a `target_bead_field` input is provided (`description` | `notes`), copy that field's content into staging.
2. Otherwise, default field selection: prefer `notes` if non-empty AND larger than `description`; else `description`.
3. If `description` (or selected field) is just a short pointer like `See docs/beads/<id>-*.md`, the skill emits an `EXTERNALIZED_SPEC` warning. **Pointer heuristic** (all must be true): (a) selected-field content ≤500 chars after whitespace strip; (b) content contains a relative path matching `docs/beads/.*\.md`; (c) content contains NO markdown structure (no `#` headings, no list-marker lines, no table pipes `|`) — i.e. the field is essentially "See <path>" prose, not a thin spec that incidentally mentions a See-also. **Interactive mode** uses the same `USER_DECISION_REQUIRED` block + exit-code-2 contract as R2.1 (`reason: EXTERNALIZED_SPEC`), surfacing options `proceed-with-pointer` and `retarget-to-file` (with the detected file path pre-populated as a `reinvoke_flags` value). **Autonomous mode** logs the warning to `pipeline-report.json` and proceeds with the pointer text as the target (typically resulting in a thin review that catches little).

This convention keeps the bead-ID path useful for the common case (full spec in `description` or `notes`) without silently producing a useless review when the bead just references an external file.

**Crucially, this skill does NOT mutate the original target.** It produces a revised version in a staging area (R4). The orchestrating agent decides whether/how to apply the staged revision back to the original — by `Edit`, `bd update --notes` / `bd update --description`, a PR, a diff review, or simply discarding it. The reviser's path-scope precondition (R8) is the load-bearing enforcement that keeps the original untouched even though the reviser is equipped with the `Edit` tool. This keeps the skill bead-agnostic and file-agnostic for downstream consumers, and preserves the original for rollback, diffs, audit, and side-by-side comparison.

### R4 — Staging area & per-cycle observability

On each invocation, the skill creates a staging area under `.ralf/<session_id>/spec/`:

```
.ralf/<session_id>/spec/
  in/
    <target-basename>                 # verbatim copy of the original target at invocation time
    definition_of_done.md             # the DoD as passed in
    original_spec_context.md          # the original spec context
  cycle-T1-1/                          # tier name + cycle number within tier
    reviewers/
      gemini-review.json              # one JSON file per reviewer that ran in this cycle
      gemini-errors.log               # foreign-CLI stderr (if any)
    defect-ledger.json                # aggregated + synthesized ledger (R6)
    reviser-input-target.md           # snapshot the reviser saw
    reviser-output-target.md          # post-reviser revised text
    reviser-report.json               # what reviser applied/refused/why
    diff.patch                        # diff(reviser-input, reviser-output)
  cycle-T1-2/...
  cycle-T2-1/...
  cycle-T3-1/...
  out/
    <target-basename>                 # final revised version after all tiers
  pipeline-report.json                # the final structured output (R8)
  pipeline-report.md                  # human-readable rendering of the above
```

Every cycle gets its own subfolder. Every reviewer output, the aggregated ledger, the reviser's input/output, the diff, and the reviser report are persisted. This gives the orchestrator (and any auditor) a complete forensic trail of how the spec evolved, who suggested what, and which findings the reviser applied/refused at each step.

The staging directory is **not** deleted by the skill — the orchestrator owns lifecycle (commit it, archive it, gitignore it, etc.). Project convention: the existing `.ralf/` gitignore entry already covers this; treat the directory as ephemeral working state.

**`pipeline-report.json` write-lifecycle.** The file is created at staging-init time with a skeleton (`{"warnings": [], "tiers": [], "score": null}`) and appended to incrementally as the pipeline progresses: R2.1 preflight warnings land first, each tier-cycle adds an entry as it completes, the final score is set at exit. This ensures every section of the spec that references "log to `pipeline-report.json`" has a target file to write to even before any tier runs. The corresponding `pipeline-report.md` is rendered from the JSON at exit (not maintained incrementally).

### R5 — Tiered review pipeline

Three tiers run in strict order. Tier 2 always runs after Tier 1 (regardless of Tier 1 outcome) because they catch different defect classes. Tier 3 only runs conditionally.

| Tier | Reviewers (parallel) | Reviser | Default cap | Termination |
|---|---|---|---|---|
| T1 — Cheap structural sweep | Gemini | `ralf-spec-reviser` agent (in-skill) | 3 cycles | No non-minor findings remain, OR T1 cap hit |
| T2 — Deep semantic adversarial | Claude + Codex (parallel) | `ralf-spec-reviser` agent (in-skill) | 3 cycles | No non-minor findings remain, OR T2 cap hit |
| T3 — Convergence confirmation | Claude + Codex + Gemini (parallel) | `ralf-spec-reviser` agent (in-skill) | 2 cycles | See T3 escalation policy below; fires only if T2 applied any non-minor fix |

Within a tier-cycle, parallel reviewers run as concurrent subagent / foreign-CLI invocations (no serial dependency between them). The defect-synthesis step (R6) runs after reviewers return. The reviser is dispatched *after* synthesis with the synthesized ledger.

**T3 escalation policy.** Tier 3 is the safety-net pass. Its purpose is to confirm the core is safely executable and that any lingering MAJOR/MINOR issues are safe to schedule as discovered work — NOT to keep grinding on blocker/critical defects. If T3 still finds blocker/critical issues after 2 cycles, **stop the pipeline and escalate**:

- In **interactive mode**, emit a `USER_DECISION_REQUIRED` block with `reason: T3_ESCALATION` (see R2.1 schema) describing the surviving findings, then exit code 2. The orchestrator surfaces to the user and re-invokes only after a directional decision (re-architect, accept, defer, etc.).
- In **autonomous mode**, invoke the Human-Escalation Pattern (HEP) — create a `human`-labeled escalation bead with the T3 transcript and pipeline-report as evidence, and pause the source workflow.

The intuition: blocker/critical findings surviving T3 are evidence that the spec has a structural problem the iterative loop cannot fix. Continuing to spend tokens on it is throwing good money after bad.

**Parallel-dispatch caveat (pre-`agents-config-abn9.12`).** "Parallel" reviewers within a cycle (e.g. Claude + Codex in T2) are dispatched by the executing agent issuing multiple Agent / Bash tool calls in a single assistant turn. Pre-abn9.12, this is best-effort by the executing agent and not deterministically enforced. Once abn9.12 lands, the wrapper script makes parallel dispatch a structural guarantee. Until then, a sequential dispatch in place of parallel is a degraded mode rather than a correctness violation — outputs are the same, just slower.

### R6 — Defect synthesis (between reviewer fan-out and reviser dispatch)

The reviser-myopia risk is real: a reviewer flagging "X is wrong on line 12, change to Y" may be reporting a localized symptom of a *systemic* issue that recurs throughout the spec. A reviser that applies only the targeted patch leaves the rest of the systemic issue intact, and the next cycle's reviewers report it again — wasting cycles or, worse, producing a partially-fixed spec.

To address this, a **defect-synthesis pass** runs between reviewer fan-out and reviser dispatch. The synthesis pass is a small Claude subagent (dispatched via `Agent` tool, no other skills loaded) whose only job is to produce a clean synthesized ledger.

**Synthesis pass responsibilities:**

1. **Dedupe.** Findings from different reviewers that point at the same location and same root issue collapse into one entry (preserving the multi-reviewer attribution and the union of recommendations).
2. **Severity reconciliation.** When reviewers disagree on severity for the same defect, take the **max** severity (most conservative). Record the disagreement in the entry.
3. **Pattern promotion.** When ≥2 findings describe semantically similar issues at different locations, the synthesis pass promotes them into a single **systemic** defect entry that lists ALL the locations the reviewers cited. The synthesis pass does NOT speculate about additional unseen occurrences — enumeration is the reviser's responsibility per R8 (the reviser semantically identifies further occurrences, with `Grep` available as a tool when textual search helps). This avoids a double-enumeration handoff where both synthesis and reviser try to own the same task.
4. **Bikeshedding filter (final pass).** Even with anti-bikeshedding clauses in reviewer prompts, slip-through happens. The synthesis pass drops MINOR entries whose `recommendation` is pure style/naming/formatting unless they cite a specific DoD violation.
5. **Annotation.** Each entry in the synthesized ledger carries: original reviewer attributions, severity (max), scope (`localized` | `systemic`), and locations array.

**Synthesized ledger entry shape (extension of R7):**

```json
{
  "severity": "blocking | critical | major | minor",
  "scope": "localized | systemic",
  "locations": ["section / line range / quoted text", "..."],
  "issue": "<consolidated description>",
  "recommendations": ["<reviewer A's fix>", "<reviewer B's fix>"],
  "attributions": ["gemini", "codex"],
  "severity_disagreement": null | {"gemini": "major", "codex": "critical"},
  "title": "<short title>"
}
```

The reviser is then explicitly instructed in its prompt: for `scope: systemic` entries, apply the fix across ALL listed `locations` AND semantically identify additional occurrences of the underlying pattern. For `scope: localized`, the targeted-edit discipline applies as-is.

This preserves the diff-patch discipline (no full-document regeneration) while restoring coherence: the reviser sees a deduplicated, severity-reconciled, pattern-promoted ledger instead of an unfiltered defect pile from each reviewer.

**Synthesis pass as a named agent.** The synthesis pass is its own custom named agent: `src/user/.agents/agents/ralf-spec-synthesis.md`. Like the reviser, its agent file is discoverable, individually configurable, and individually testable. Frontmatter: `model: opus[1m]` (semantic deduplication and pattern promotion benefit from the strongest model — same reasoning as the reviser), `effort: xhigh`, tools `Read, Grep, Glob, Bash` (read-only; no `Edit`, no `Write`, no `Agent`). The synthesis pass NEVER mutates the staging area's target file — it only reads per-reviewer JSON outputs and emits the consolidated `defect-ledger.json`.

**Prior-cycle signal carry-forward (T1 and T2 — content preserved, model attribution stripped).** Each cycle is dispatched with a *fresh* reviewer subagent (the Independence invariant from the 2026-04-19 split-design). Carrying prior-cycle reviewer identities into a "fresh" prompt would anchor the new reviewer to who-said-what, weakening Independence. To preserve the invariant against model-anchoring while still preventing redundant cycle-after-cycle re-discovery, the signal carried forward in T1 and T2 is partially anonymized: **model attributions and severity verdicts are stripped**, but the **finding content (`title`, `locations`, issue summary) is preserved**. This is a deliberate partial relaxation of Independence — content preservation creates some prior-phrasing anchoring, but the alternative (full anonymization via hash-only "issue X resolved") loses too much signal to be useful. The tradeoff is explicit: T1/T2 reviewers see what the prior cycle thought was an issue, but not who flagged it or how severely; if they disagree with the prior cycle's framing they can re-raise with a different recommendation.

1. **Carried disagreements (anonymized).** When the prior cycle's synthesis recorded a `severity_disagreement` on an entry, the next cycle's reviewer prompts include a `prior_cycle_disagreements` section that reports the disagreement existed and at what locations, WITHOUT naming the reviewers or their verdicts. The carry-forward text is **outcome-agnostic** — it does not presume the reviser applied the fix:

   > "Prior cycle flagged a severity disagreement on `<title>` at `<locations>`. Outcome: `[applied at max-severity | refused with reason <reason>]`. Please evaluate independently whether the issue is resolved."

   No model attributions, no severity verdicts from prior reviewers — only the existence of the disagreement, its location, and whether the reviser ultimately applied or refused the consolidated entry.
2. **Carried refusals (anonymized).** Entries the reviser refused (DoD-violation or conflict) are carried forward as `prior_cycle_refusals` with the refusal reason but without identifying which prior-cycle reviewer raised the original finding. Reviewers can re-raise (possibly with a different recommendation) or accept the issue stands open.

**Prior-cycle signal carry-forward (T3 — full history).** T3's purpose IS to check for oscillation across the iterative loop, which requires full history. T3 reviewers receive: the cumulative pre→post target diff, the full sequence of cycle-by-cycle synthesized ledgers, and prior reviewer attributions. The Independence invariant is **explicitly waived for T3** because oscillation-detection cannot be done from anonymized signal. The waiver is scoped — it does not propagate back to T1/T2.

Carry-forward is signal, not constraint: reviewers are not forbidden from disagreeing with prior conclusions. The synthesis pass in the next cycle is the canonical place where new findings are reconciled with carried-forward signal.

### R7 — Defect-ledger formats (internal)

**Per-reviewer output** (reviewer subagents and foreign CLIs all return this shape):

```json
{
  "summary": {
    "score": "PASS | PASS_WITH_RESERVATIONS | FAIL",
    "rationale": "<1-2 concrete sentences>"
  },
  "defects": [
    {
      "severity": "blocking | critical | major | minor",
      "title": "<short title>",
      "location": "<section / line range / quoted text>",
      "issue": "<what is wrong>",
      "recommendation": "<specific fix>"
    }
  ]
}
```

**Synthesized ledger** (R6 output, reviser input): see R6 entry shape above. Persisted as `defect-ledger.json` in the cycle subfolder.

JSON is the internal format; the user-facing report (R10) is a human-readable structured markdown report rendered from the internal JSON.

### R8 — `ralf-spec-reviser` custom named agent

The reviser is its own custom named agent — NOT an inline-prompted subagent. This makes it discoverable, individually configurable, individually testable, and consistent across all callers.

**Agent file:** `src/user/.agents/agents/ralf-spec-reviser.md`

**Agent contract:**

- **Inputs (via prompt):** target file path (**MUST be the staged copy under `.ralf/<session_id>/spec/in/` or `.ralf/<session_id>/spec/cycle-*/`**, never the original target path), synthesized defect ledger path, Definition of Done path, original spec context path.
- **Path-scope precondition (enforced).** Before any `Edit` call, the reviser's prompt instructs it to assert that the target path contains `/.ralf/<session_id>/spec/` followed by either `in/` or `cycle-T<N>-<M>/` — matching the regex `(?:^|/)\.ralf/[^/]+/spec/(in|cycle-T[123]-\d+)/[^/]+$` (accepts both relative and absolute paths; project convention is absolute paths). On match failure, the reviser refuses with a structured `PATH_SCOPE_VIOLATION` error and records it in `reviser-report.json`. This is the load-bearing mechanism that keeps the "never mutate the original" invariant true: the `Edit` tool itself does not know about staging, but the reviser does, and it refuses to operate on out-of-scope paths. The orchestrator (skill or `agents-config-abn9.12` wrapper) is correspondingly responsible for ONLY invoking the reviser with a staged path.
- **Tools allowed:** `Read`, `Edit`, `Grep`, `Glob`, `Bash`. No `Write` (forces `Edit` discipline; `Edit` requires a Read first, which guarantees the reviser sees the current text before patching). No `Agent` (no recursive dispatch).
- **Model:** `opus[1m]`. Revision IS a deep-reasoning task — applying systemic fixes coherently across a spec, refusing on conflicts, and identifying additional pattern occurrences semantically all benefit from the strongest model. Reviser-induced regressions are expensive to detect (next cycle catches them, costing a cycle); paying once for opus to get the revision right is cheaper than paying twice for a cycle to fix a sloppy revision.
- **Effort:** `xhigh`.
- **Deploy target:** **Claude-only.** The `opus[1m]` alias is Claude-specific; this agent file installs only to `~/.claude/agents/`. Non-Claude tools (Codex, Gemini, OpenCode) do not get a copy. Cross-tool wrappers in `agents-config-abn9.12` will invoke this agent via `claude -p` regardless of which tool launched the pipeline.

**Reviser behavior:**

1. For each defect in the synthesized ledger, in severity order (blocking → critical → major; MINOR entries are addressed only if they appear in the synthesized ledger after the bikeshedding filter):
   - **`scope: localized`** — apply the recommended fix at the listed location(s) via `Edit`.
   - **`scope: systemic`** — apply the recommended fix at ALL listed locations AND semantically identify all additional occurrences of the underlying pattern or issue. For each additional occurrence, apply the analogous fix. ("Semantically identify" means the reviser reasons about the pattern at a conceptual level, not just by literal grep matching — though Grep is available as a tool when textual search helps narrow candidate locations.)
2. **Conflict handling.** If two entries in the ledger prescribe conflicting changes at the same location, the reviser MUST refuse to silently pick one. It records both, marks the entry `refused`, and proceeds; the conflict surfaces in the cycle output and the synthesis pass for the next cycle will see both findings again and either reconcile severity or escalate. **Reviewer disagreements (severity or recommendation) recorded by the synthesis pass are carried forward as explicit signal into the next cycle's reviewer prompts** — see R6 "Prior-cycle signal carry-forward."
3. **DoD-violation refusal.** Refusal under `refused_reason: dod-violation` is limited to a **closed enumeration** of mechanically-detectable conditions — not abstract judgments about whether a post-edit spec "still satisfies" the DoD. The reviser refuses ONLY when the proposed edit would:
   - **(a)** delete an entire section the DoD declares must exist (e.g. DoD says "spec must contain a Security section"; edit deletes the Security section);
   - **(b)** remove an AC line the DoD pins verbatim;
   - **(c)** modify a literal string the DoD calls out as required (e.g. "the error string `INPUT_CONTRACT_VIOLATION` must appear in R2").
   Anything more abstract — "this edit weakens AC #7's intent" — is NOT the reviser's call; it surfaces as an applied edit and the next cycle's reviewers can flag it if they disagree. This keeps refusal narrow and auditable.
4. **No second-guessing of reviewers.** The reviser does NOT adjudicate "is this defect actually valid?" — that is the reviewer's and synthesis pass's job. The reviser applies the ledger faithfully or records refusals under the closed enumeration above. Abstract concerns about edit quality are out of scope for the reviser.
5. **Output:** a `reviser-report.json` per cycle recording: applied entries, refused entries (with reasons), Grep-scanned additional occurrences fixed, and a `diff.patch` of pre→post target.

### R9 — Universal exit rules

- **MINOR-don't-retrigger (exit flow).** In an exit-decision flow, MINOR findings are non-failing and informational only. A cycle whose post-reviser ledger contains ONLY minor findings is treated as converged for that tier; the tier exits.
- **MINOR-during-fix-phase.** During the fix phase of a cycle (synthesis + reviser run), legitimate MINOR issues that survived the bikeshedding filter and the synthesis pass ARE still applied. The "don't retrigger" rule governs whether MINOR-only cycles trigger ANOTHER cycle — it does not absolve the current cycle's reviser from addressing them.
- **No dangling issues.** A cycle MUST end with either (a) the synthesis pass's non-refused entries all applied by the reviser, OR (b) refused entries recorded with reasons. The pipeline NEVER exits with un-addressed entries silently dropped. This applies to FAIL exits too — even when the cap is hit and the tier ends with non-minor findings present, those findings appear in the final report's Remaining Concerns with explicit rationale (either reviser-refused-with-reason, or "deferred to discovered-work because cap-hit") so they can be triaged later, not lost.
- **Cap exhaustion.** When a tier hits its cap with non-minor findings still present, the tier exits with `PASS_WITH_RESERVATIONS` (or `FAIL` per scoring rubric, R10) and the pipeline proceeds to the next tier (or exits per T3 escalation policy).
- **Foreign-agent failure (graceful degradation).** A degraded reviewer (UNAVAILABLE, TIMED_OUT, QUOTA_EXCEEDED, AUTH_FAILED, NO_OUTPUT, UNUSABLE_OUTPUT) drops that reviewer from the current cycle. The reviewer's fallback (per R12) is invoked if configured; otherwise surviving reviewers in the cycle continue and the cycle counts. If ALL reviewers in a tier degrade simultaneously and no fallbacks succeed, the tier is skipped with a logged degradation status.

### R10 — Output contract & scoring

**Overall scoring rubric:**

- **`PASS`** — at exit, the final cycle's synthesized ledger had no blocker, no critical, and no major findings. The tier(s) terminated via natural convergence (no non-minor findings remaining), NOT via cap exhaustion. All findings (including MINOR if any survived the synthesis filter) were applied by the reviser or refused with documented reasons.
- **`PASS_WITH_RESERVATIONS`** — entered ONLY via cap exhaustion: at least one tier exited because its cycle cap was reached with non-minor findings still present. At exit, the final cycle's synthesized ledger has no blocker and no critical findings, but had `>0` major findings (which were either applied or refused-with-reason). The orchestrator should review the Remaining Concerns before treating the spec as complete.
- **`FAIL`** — at exit, the final cycle still has blocker or critical findings that the reviser could not (or refused to) address, OR T3 hit its escalation policy (R5). The pipeline did not converge; orchestrator intervention is required.

`PASS_WITH_RESERVATIONS` is mutually exclusive with natural convergence: a tier exiting because its `no non-minor findings remain` condition was met always scores `PASS` if all upstream tiers also converged naturally. `PASS_WITH_RESERVATIONS` is the unambiguous signal "we ran out of budget before we ran out of issues."

**No dangling issues rule (re-stated for scoring):** PASS / PASS_WITH_RESERVATIONS / FAIL all require that every found issue has either been applied as a revision OR been recorded as refused-with-reason. A score of FAIL with un-recorded issues is a skill bug.

**Output: structured markdown report (single document, returned to caller and also persisted as `pipeline-report.md`):**

- **Overall score:** `PASS` / `PASS_WITH_RESERVATIONS` / `FAIL`
- **Score rationale:** 1–2 concrete sentences
- **Convergence trends:** per-cycle counts of NEW findings by severity (blocker/critical/major/minor), so an auditor can see whether the loop is converging, plateauing, or oscillating across cycles. Trend table example:
  ```
  Tier  Cycle  Blocker  Critical  Major  Minor  Applied  Refused
  T1    1      0        0         3      4      6        1
  T1    2      0        0         1      2      2        1
  T2    1      0        1         4      3      7        1
  T2    2      0        0         1      2      2        1
  T3    1      0        0         0      1      0        1
  ```
- **Per-model efficacy:** for each reviewer (gemini, codex, claude), counts of findings raised, findings that survived synthesis, findings that were applied by the reviser, and findings that were refused. **Attribution rule:** counts are based on **pre-dedupe raw outputs**. A finding raised by both gemini and codex counts as +1 raised for each. The same rule applies to survived/applied/refused: every reviewer in a consolidated entry's `attributions` list is credited with that outcome. This means the columns will not sum to the total finding count across reviewers (they intentionally double-count shared findings), but each reviewer's row is internally consistent and lets the operator see which model is contributing the most signal vs. noise.
- **Per-tier results:**
  - Tier name and termination reason (converged / cap-hit / all-reviewers-degraded / T3-escalation / **skipped** for T3 when its conditional trigger didn't fire — i.e. T2 applied no non-minor fixes)
  - Cycles run (`n/cap`); for skipped tiers the row shows `0/cap (skipped — <reason>)` and trend-table T3 row is `T3 — skipped (no T2 non-minor fixes)`
  - Reviewer status per cycle (PASS / degraded with reason / unavailable / fallback-invoked)
- **Applied revisions:** ordered summary of reviser edits across all tiers — one bullet per non-trivial edit, linking back to the cycle's `diff.patch`.
- **Remaining concerns (decided-not-to-fix only):** this list is curated, NOT a dump of everything found. It contains:
  1. Entries the reviser explicitly refused, with the refusal reason.
  2. Entries deferred to discovered-work because the tier cap was hit before they could be applied.
  3. Alarming trends from the Convergence Trends section (e.g. "T2 found 3 new criticals in cycle 2 after cycle 1 applied 7 fixes — possible oscillation").

  The applied/converged findings are NOT repeated here; they're already covered by Applied Revisions. The Remaining Concerns list is an **actionable** triage list, not a defect inventory.

### R11 — Tier configuration files (prompts embedded)

Each tier owns a single YAML configuration file that declares its agent(s), model(s), effort, fallback, **and the default prompt body**, with optional per-agent header/footer extensions for the agents that need to diverge from the shared default. Embedding the prompt in the YAML (rather than referring to a sibling `.tmpl` file) keeps a tier's contract in one file — easier to audit, easier to override, fewer moving parts.

**Config-file convention:** `src/user/.agents/skills/ralf-spec/config/<tier-name>.yaml`. Tiers are named by **purpose**, not by agent:

- `tier-1-cheap-sweep.yaml` (T1)
- `tier-2-deep-semantic.yaml` (T2)
- `tier-3-convergence.yaml` (T3)
- `synthesis.yaml` (the defect-synthesis pass dispatch; R6 — see also the `ralf-spec-synthesis` agent file)
- `reviser.yaml` (the in-skill reviser agent dispatch; R8 — see also the `ralf-spec-reviser` agent file)

**Per-tier YAML schema (multi-agent example, T2):**

```yaml
tier: tier-2-deep-semantic
default_cap: 3
default_prompt: |
  You are a deep-semantic adversarial reviewer for a spec document.
  ...
  [shared prompt body used by all agents in this tier unless overridden]
agents:
  - id: claude
    cli: claude
    model: opus[1m]
    effort: xhigh
    prompt_header_extension: null     # optional verbatim text prepended to default_prompt
    prompt_footer_extension: null     # optional verbatim text appended to default_prompt
    fallback: null                    # see R12
  - id: codex
    cli: codex
    model: gpt-5.5
    effort: xhigh
    prompt_header_extension: |
      # Codex-specific framing: you are in read-only mode; emit your review to stdout.
    prompt_footer_extension: null
    fallback:
      cli: claude
      model: opus[1m]
      effort: xhigh
      # Fallback uses the same default_prompt + the primary's header/footer extensions
      # unless overridden here with its own header/footer extensions.
```

Tier 1 (Gemini-only) has a single-agent block; Tier 2 has two; Tier 3 has three. Each tier's YAML carries its full prompt body inline. The bulk of the prompt is shared across agents within a tier (because they share the tier's *purpose*); per-agent extensions cover CLI-specific framing or model-specific quirks.

**Named agents** under `src/user/.agents/agents/`:

- `ralf-spec-reviser.md` (R8) — the in-skill reviser; its agent file owns its prompt body
- `ralf-spec-synthesis.md` (R6) — the defect-synthesis pass; its agent file owns its prompt body

Both are full custom Claude agents with frontmatter declaring tools, model, and effort. The `reviser.yaml` and `synthesis.yaml` config files govern only how the skill *invokes* these agents (e.g. inputs, output paths in staging), not their behavior.

**Skill orchestration wrapper — fast-follow bead.** The MVP shipped by THIS bead populates the YAML configs, the two named agents (`ralf-spec-reviser`, `ralf-spec-synthesis`), and the `SKILL.md`. The deterministic orchestration wrapper that drives the full tiered pipeline end-to-end — managing multi-tier × multi-agent fan-out × fallback chains × per-cycle staging — is tracked as **`agents-config-abn9.12` (P0, fast-follow, blocks-on this bead)**. Per Scott's crit comment c29: "there will be pain as there are too many moving parts for the agent to remain deterministic through the workflow." The wrapper must land soon after this bead; until it does, the skill is operable only by a careful executing agent reading the YAMLs and dispatching reviewers by hand, which is acceptable for a brief transitional window but not for production use. `agents-config-abn9.12` is explicitly P0 to keep that window short.

**Pre-abn9.12 orchestration contract (binding on SKILL.md authoring).** During the transitional window, the calling Claude session IS the orchestrator. SKILL.md MUST therefore describe the orchestration loop in **imperative form** — step-by-step instructions a Claude session can execute via its own `Agent` (subagent dispatch) and `Bash` (foreign-CLI invocation, staging directory creation, JSON aggregation) tools. The SKILL.md sections must explicitly cover: (a) parse the tier YAMLs in order; (b) create the staging directory layout per R4; (c) per tier-cycle, dispatch reviewers in parallel via multi-tool-call assistant turns; (d) collect per-reviewer JSON, invoke the `ralf-spec-synthesis` agent, then the `ralf-spec-reviser` agent; (e) check termination per R9; (f) emit `pipeline-report.json` and `pipeline-report.md`. Once abn9.12 lands, SKILL.md transitions to documenting the wrapper invocation interface; the imperative steps move into the wrapper code.

### R11.2 — Pre-abn9.12 vs post-abn9.12 execution semantics (deterministic-vs-LLM gap)

Several requirements in this spec (R2.1 exit codes, R8 path-scope regex self-assertion, R11.1 schema validation emitting `CONFIG_VALIDATION_ERROR` on stderr) describe *deterministic* behavior that a wrapper script can guarantee but a LLM-orchestrated execution can only approximate. The gap is real, intentional, and time-boxed:

| Behavior | Pre-abn9.12 (LLM-orchestrated) | Post-abn9.12 (wrapper script) |
|---|---|---|
| Exit codes (0/1/2) | Conceptual; orchestrator agent stops dispatching and emits an explicit "skill exit code: N" line in its turn-output | Literal `exit(N)` from the wrapper |
| Stderr emissions (`CONFIG_VALIDATION_ERROR`, etc.) | Emitted as labeled lines in orchestrator's turn-output (LLMs don't have a real stderr); pattern-matchable by downstream callers | Real fd-2 writes from the wrapper |
| Path-scope regex precondition (R8) | LLM-asserted, defense-in-depth; **additionally** a Bash pre-run `sha256sum` snapshot of the original target file is taken at staging-init, and a post-run comparison at pipeline exit verifies the original is byte-identical (true safety net) | Wrapper enforces the regex in code before forwarding to the reviser; sha256 snapshot/comparison still runs as defense-in-depth |
| YAML schema validation | LLM reads each YAML, walks the R11.1 required-key list, emits labeled `CONFIG_VALIDATION_ERROR` lines on failure | Wrapper uses a real YAML parser + schema validator; same labeled error format |
| Parallel reviewer dispatch | Best-effort: orchestrator places multiple Agent/Bash tool calls in a single assistant turn; not enforceable by the spec | Wrapper uses real concurrent subprocess execution |

**Defense-in-depth sha256 safety net (R8 reinforcement).** At staging-init, the skill computes `sha256sum <original-target>` and stores it in `.ralf/<session_id>/spec/in/original.sha256`. At pipeline exit (success or failure), the skill re-computes the sha256 and compares. Mismatch raises `ORIGINAL_TARGET_MUTATED` as a top-level error in `pipeline-report.json` regardless of any other outcome — this is the deterministic backstop against an LLM-orchestration mistake that bypasses the reviser's regex precondition. AC #18 is updated to use sha256 comparison rather than mtime (more robust on filesystems that update mtime on Read).

ACs that depend on deterministic exit codes / stderr (AC #12, #14, #17, #20) are scoped to **post-abn9.12 execution** unless explicitly noted otherwise. Pre-abn9.12 they verify the labeled lines appear in the orchestrator's turn-output; post-abn9.12 they verify exit codes and fd-2 writes.

### R11.1 — Tier-YAML schema validation & load contract

Configuration files are subject to the same fail-fast posture as R2's input contract. Malformed or under-specified YAML must be rejected before any reviewer is dispatched, not produce confusing runtime failures mid-pipeline.

**Load order.** The skill (and the abn9.12 wrapper, when present) loads YAMLs in this order: `tier-1-cheap-sweep.yaml` → `tier-2-deep-semantic.yaml` → `tier-3-convergence.yaml` → `synthesis.yaml` → `reviser.yaml`. Each load is parsed and validated; any failure aborts the pipeline with a structured error naming the offending file and key.

**Per-tier required keys** (validated before tier execution begins):

| Key | Type | Constraint |
|---|---|---|
| `tier` | string | Must match the canonical tier name for the file |
| `default_cap` | integer | `1 ≤ default_cap ≤ 5` |
| `default_prompt` | string | Non-empty (length > 0 after stripping whitespace) |
| `agents` | list[object] | Length ≥ 1 |
| `agents[].id` | string | Unique within the tier; matches `^[a-z][a-z0-9-]*$` |
| `agents[].cli` | string | One of: `claude`, `codex`, `gemini` (the v1 supported set; future CLIs added in follow-on beads as they become relevant) |
| `agents[].model` | string | Non-empty; format validated per CLI (claude allows `opus[1m]`, `sonnet[1m]`, `haiku`; codex allows `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.3-codex`; gemini allows family names) |
| `agents[].effort` | string | One of: `default`, `low`, `medium`, `high`, `xhigh` |
| `agents[].prompt_header_extension` | string \| null | Optional |
| `agents[].prompt_footer_extension` | string \| null | Optional |
| `agents[].fallback` | object \| null | If present, validated recursively as an `agents[]` entry (model/effort/cli) |

**Failure modes:**

- Missing required key → exit code 1 with `CONFIG_VALIDATION_ERROR: <file>:<key> missing` on stderr.
- Type mismatch → exit code 1 with `CONFIG_VALIDATION_ERROR: <file>:<key> expected <type>, got <type>`.
- Unknown CLI → exit code 1 with `CONFIG_VALIDATION_ERROR: <file>:<agent-id>.cli '<value>' not in supported set`.
- `default_prompt` empty after whitespace-strip → exit code 1 with `CONFIG_VALIDATION_ERROR: <file>:default_prompt is empty`.

Validation runs ONCE per skill invocation, before any cycle starts. A successfully-validated YAML is cached for the run. AC #2 verifies presence of `default_prompt:`; the deeper schema contract is verified by AC #16 (a fixture invocation against a deliberately-broken YAML asserts the expected exit code and error string).

**Anti-bikeshedding clause (verbatim, all reviewer prompt templates):**

> Do not critique stylistic choices, naming conventions, or formatting unless they directly violate the explicit Definition of Done. Assume the author's stylistic choices are intentional. MINOR findings are informational only and will not be sent back for revision.

### R12 — Foreign-agent fallback & degradation handling

For each reviewer agent in each tier's YAML, an optional `fallback` block declares the substitute reviewer to invoke when the primary degrades. The fallback runs at the same tier-cycle, using the same prompt template (or its tier-N-`<fallback-cli>` variant if defined), and its output replaces the primary's in the synthesis pass.

**Degradation triggers** (any of these on the primary triggers the fallback):

- CLI not on `PATH` (UNAVAILABLE)
- Wall-clock timeout (default 10 min; per-agent override allowed)
- Exit code matching the per-CLI quota / auth / network failure codes (QUOTA_EXCEEDED, AUTH_FAILED)
- Empty or unparseable JSON output (NO_OUTPUT, UNUSABLE_OUTPUT)

**Fallback chains.** A `fallback` may itself declare a further fallback. **Maximum 3 invocation attempts per reviewer slot per cycle**: primary, then up to 2 fallbacks (i.e. 2 fallback edges in the chain). Beyond 3 failed attempts for a single reviewer slot in a cycle, that slot is dropped and the cycle proceeds with surviving reviewers.

**MVP fallback defaults** (initial hard-coded values in the tier YAMLs; satisfy R11.1 schema validation):

- Gemini T1: fallback → Claude `sonnet[1m]` with `effort: medium` and the same T1 prompt body (cheap-sweep). **Diversity-collapse warning required**: any T1 cycle whose foreign reviewer fell back to a Claude variant MUST be flagged in `pipeline-report.md` Remaining Concerns as `FOREIGN_PERSPECTIVE_DEGRADED — T1 cycle <N> ran Claude-on-Claude (Gemini unavailable: <status>). The cheap-sweep tier's adversarial purpose was not fully met.` This makes Gemini-unavailability visible rather than silently degrading T1 into a Claude-self-review.
- Codex T2: fallback → Claude `sonnet[1m]` with `effort: high` and the T2 codex prompt body. Same diversity-collapse warning rule applies to T2 if Codex falls back. (`effort: high` instead of `xhigh` because the fallback is a cost-aware substitute, not the full xhigh deep-semantic original.)
- Claude T2: no fallback (Claude is the home environment; if it's failing, the whole skill is broken).
- T3 reviewers: no fallback (T3 is a safety net; if a reviewer can't run, log degradation and proceed with survivors). T3 with surviving reviewers still produces a valid convergence pass; T3 with all reviewers degraded surfaces `T3_ALL_DEGRADED` in Remaining Concerns and scores FAIL if blocker/critical findings remain from T2.

All MVP fallback declarations include the full required-key set per R11.1 (`cli`, `model`, `effort`) so the schema validator accepts them on load.

**Notes on project-config.toml integration.** The existing `project-config.toml` has the beginnings of a foreign-agent configuration scheme but it is not yet adapted for ralf-loop semantics. This bead does NOT extend `project-config.toml` — the per-tier YAML is the configuration interface introduced here. A future bead may unify the two configuration surfaces; tracked as discovered work.

### R13 — Cycle-cap configuration

- **Default per-tier caps:** T1=3, T2=3, T3=2 (the **standard configuration**, hard-coded in MVP YAML files).
- **`ralf:cycles=N` label semantics:** N is a **ceiling** on the SUM of T1+T2 cycles, not a target. The algorithm may under-allocate when N exceeds the per-tier cap sum (max 6 in standard config); the under-allocation is intentional, not a violation of the ceiling. N must be an integer in `[2, 12]`; out-of-range or malformed values are rejected at the input-contract step (R2). `ralf:cycles=N` is **defined ONLY for the standard configuration** (T1_default=3, T2_default=3). If the YAML configs are overridden with non-standard caps (e.g. T1_default=5), the skill rejects `ralf:cycles=N` with `CYCLES_OVERRIDE_UNSUPPORTED_CONFIG` and falls back to the YAML-declared per-tier caps unmodified.
- **T3 budget is additive, not bounded by `ralf:cycles`.** T3 fires conditionally per R5 (only if T2 applied any non-minor fix) and runs to its own per-tier cap. Total cycle budget under `ralf:cycles=N` is therefore `N + (T3_cap if T3 fires else 0)` cycles, not `N`. This is documented behavior — callers wanting a true global ceiling on all cycles must additionally edit `tier-3-convergence.yaml` `default_cap` (minimum 1 per R11.1 schema; setting to 1 limits T3's contribution to a single pass). A future bead may add a `ralf:no-t3` escape hatch or unified-budget mode if operational pain emerges; tracked as discovered work.
- **Cap allocation under `ralf:cycles=N` (T2-minimum-reserve rule):** for the standard configuration, the skill MUST allocate at least 1 cycle to T2 regardless of N, because R5 guarantees "T2 always runs after T1." Allocation algorithm: reserve `T2 = min(3, max(1, N - 3))`; then `T1 = N - T2`, capped at `3`. Examples:
  - `ralf:cycles=2` → T2=1 (minimum reserve), T1=1. Allocated sum=2 (matches N).
  - `ralf:cycles=3` → T2=1, T1=2. Allocated sum=3 (matches N).
  - `ralf:cycles=4` → T2=1, T1=3. Allocated sum=4 (matches N).
  - `ralf:cycles=5` → T2=2, T1=3. Allocated sum=5 (matches N).
  - `ralf:cycles=6` → T2=3, T1=3 (the standard default). Allocated sum=6 (matches N).
  - `ralf:cycles=8` → T2=3 (capped), T1=3 (capped). Allocated sum=6 (under-allocation; warning `CYCLES_CAP_EXCEEDS_TIER_BUDGET` emitted explaining that N exceeds the maximum T1+T2 capacity for the standard configuration).
  - `ralf:cycles=12` → same as N=8: T2=3, T1=3. Allocated sum=6. Same warning.
  This preserves the R5 "T2 always runs" invariant under any valid N. The T2-minimum-reserve rule is verified by AC #16.

### R14 — Code review is explicitly out of scope

Following the rename, code-targeted review is dropped from this skill. The 2026-04-19 design spec (line 374) anticipated using `ralf-review` for a completion-gate `code-review` step; that future use is now formally deferred to a separate future bead. Existing code-review needs are served by `quality-reviewer` agent and `ralf-implement` (which has its own implement-and-review cycle).

### R15 — Downstream impact

- **`brainstorm-bead` formula:** the `ralf-spec-review` step (already named with `spec` terminology) is retargeted to dispatch `ralf-spec` instead of `ralf-review`. No formula structural change; only the skill name in the step body changes.
- **`docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md`:** updated to reflect the rename; the deferred line 330–331 note is marked resolved by this bead; the line 374 future code-review note is marked deferred to a future bead.
- **`src/user/.agents/INSTRUCTIONS.md.template` and `src/user/.claude/rules/delegation.md`:** `ralf-review` → `ralf-spec` references updated.
- **`src/user/.claude/commands/`:** any `/ralf-review` command files renamed to `/ralf-spec` (or new file added; old removed).
- **Install prune-list:** the `scripts/` install infrastructure ships a prune-list (sibling of `install.sh`) that enumerates deployed artifacts removable on `--prune`. Add the old `ralf-review/` paths to the prune-list so a `--prune` run on an upgrading install cleanly removes the deprecated skill folder from `~/.claude/`, `~/.codex/`, etc.
- **Memory entries:** any prior memory entries mentioning `ralf-review` are updated by the implementing agent during the housekeeping step.

---

## Out of scope (deferred to follow-on beads)

- **Deterministic orchestration wrapper + `project-config.toml` override mechanism** — **tracked in `agents-config-abn9.12` (P0 fast-follow, blocks-on this bead).** This bead lands YAML configs + named agents + SKILL.md; abn9.12 lands the wrapper that drives the pipeline end-to-end deterministically. Per Scott's crit c29, the deferral is acceptable as a *separate* bead but NOT as an indefinite "when we feel pain" punt — abn9.12 is P0 specifically to keep the operational gap small.
- **Spec-modularization skill** — **tracked in `agents-config-3f52` (P1).** R2.1 (preflight size check) emits a warning suggesting decomposition when the target exceeds 200 non-blank lines; the actual decomposition skill it can hand off to lives in that bead. Until 3f52 lands, autonomous mode logs + proceeds; interactive mode prompts the user to decompose manually or proceed monolithically.
- **JSON output contract to external consumers.** The defect-ledger JSON is internal-only. Callers receive a human-readable structured markdown report (`pipeline-report.md`). Future bead may convert the output contract to JSON for programmatic consumers (e.g. `merge-guard`-style gates), but not here.
- **Tiered model-selection knobs for cost tuning** (e.g. swapping Gemini Flash for Gemini Pro per-tier via env vars). The per-tier YAML (R11) is the configuration surface in this bead; richer cost-tuning knobs come with the wrapper-script bead (abn9.12).
- **Replacement of `ralf-implement`'s code-review flow** with code-aware `ralf-spec` analogue. Future bead.
- **Cross-PR / cross-bead reviewer memory.** Each invocation is stateless w.r.t. prior invocations. Memory across runs is a future bead if/when it becomes useful.
- **Streaming / progressive output during long pipelines.** Skill blocks until completion; no streaming.
- **Concurrency-controlled parallel dispatch.** Reviewers in a cycle are dispatched in a single message with multiple Agent / Bash tool calls; no semaphore or queue beyond that. Adequate for the 2- or 3-reviewer max.
- **Telemetry / metrics emission.** No structured metrics from this skill; observability lives in the staging area's per-cycle persisted files + the molecule audit trail.

---

## Acceptance criteria

Each AC is **agent-verifiable** — either a shell-checkable assertion or an agent-inspectable condition.

1. **Skill directory exists.** `test -d src/user/.agents/skills/ralf-spec/ && ! test -e src/user/.agents/skills/ralf-review/`.
2. **Required files present.** `src/user/.agents/skills/ralf-spec/` contains: `SKILL.md`, `config/tier-1-cheap-sweep.yaml`, `config/tier-2-deep-semantic.yaml`, `config/tier-3-convergence.yaml`, `config/synthesis.yaml`, `config/reviser.yaml`. Each tier YAML carries its own embedded default prompt body (no separate `.tmpl` files). Verifiable by `ls` + `test -f` per file plus `grep -F "default_prompt:" config/<name>.yaml` returning ≥1 line per tier file.
3. **Reviser agent file exists.** `test -f src/user/.agents/agents/ralf-spec-reviser.md` and its YAML frontmatter declares `name: ralf-spec-reviser`, `tools: Read, Edit, Grep, Glob, Bash` (no `Write`, no `Agent`), `model: opus[1m]`, `effort: xhigh`. **Claude-only deploy target:** after install, the file exists at `~/.claude/agents/ralf-spec-reviser.md` and is NOT present under `~/.codex/`, `~/.gemini/`, or `~/.config/opencode/`.
4. **Synthesis agent file exists.** `test -f src/user/.agents/agents/ralf-spec-synthesis.md` and its YAML frontmatter declares `name: ralf-spec-synthesis`, `tools: Read, Grep, Glob, Bash` (no `Edit`, no `Write`, no `Agent`), `model: opus[1m]`, `effort: xhigh`. **Claude-only deploy target:** same scoping as the reviser — installs only to `~/.claude/agents/`.
5. **SKILL.md covers all sections.** A `grep -c` on the SKILL.md returns ≥1 for each section heading PLUS an obligation-keyword check per section: input contract (R2, grep "INPUT_CONTRACT_VIOLATION"), preflight size check (R2.1, grep "USER_DECISION_REQUIRED"), target resolution (R3, grep "Bead-ID field selection"), staging area (R4, grep ".ralf/"), tiered pipeline (R5, grep "T2 always runs"), defect synthesis (R6, grep "Pattern promotion"), defect-ledger format (R7), reviser contract (R8, grep "PATH_SCOPE_VIOLATION"), exit rules (R9, grep "No dangling issues"), output contract (R10, grep "PASS_WITH_RESERVATIONS"), tier config files (R11, grep "default_prompt"), YAML schema validation (R11.1, grep "CONFIG_VALIDATION_ERROR"), fallback (R12, grep "FOREIGN_PERSPECTIVE_DEGRADED"), cycle-cap (R13, grep "T2-minimum-reserve"), out-of-scope (R14), downstream (R15). Section heading PLUS obligation-keyword presence is the minimum bar.
6. **All cross-references updated.** `grep -r "ralf-review" src/ docs/ | grep -v "docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md" | grep -v "docs/beads/"` returns zero lines. (Excluding all of `docs/beads/` preserves historical bead descriptions that may legitimately reference the old name; per R15, only the live skill/agent/config/rule paths require updating, not historical bead audit trail.)
7. **Install dry-run clean.** `scripts/install.sh --dry-run` reports no skill-name collisions and stages `ralf-spec` cleanly under every active tool's deploy target. Exit code 0.
8. **Prune-list updated.** The `scripts/`-sibling prune-list contains entries for the deprecated `ralf-review` paths under each tool's deploy target. `grep -F "ralf-review" scripts/<prune-list-file>` returns ≥1 line for each deploy target.
9. **Formula step retargeted.** The `brainstorm-bead` formula's `ralf-spec-review` step body references `ralf-spec` (not `ralf-review`). `grep -F "ralf-spec" src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml` returns ≥1 line; `grep -F "ralf-review" src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml` returns 0.
10. **Build / typecheck / tests.** No project-level build, typecheck, or test commands exist (per repo `AGENTS.md`: "this is pure documentation"). AC satisfied as N/A.
11. **Dogfood gate (single-tier, fixture-target, MVP-scoped).** This AC is intentionally narrowed to a feasible and non-circular bar before `agents-config-abn9.12` lands: a **single tier (T1)** invocation of `ralf-spec` against a **fixture spec** (NOT this bead's own description — avoids the dogfood-edits-its-own-success-criteria circularity) located at `tests/fixtures/ralf-spec/dogfood-target.md` runs end-to-end and produces a `pipeline-report.json` with overall score `PASS` or `PASS_WITH_RESERVATIONS`. The fixture is a deliberately-flawed ~150-line spec that exercises the cheap-sweep T1 path including ≥1 finding the reviser applies. The fixture, the `pipeline-report.md`, and the post-revision staged target are all attached to the bead as a comment for review. The full 3-tier dogfood is moved to `agents-config-abn9.12`'s acceptance criteria, where the deterministic wrapper makes the multi-tier × multi-cycle × multi-reviewer × fallback orchestration tractable. Rationale: (a) gating bead closure on a full 3-tier hand-orchestrated dogfood would deadlock against abn9.12's `blocks-on this bead` dep; (b) a self-referential dogfood (against this bead's spec) would let the reviser edit its own success criteria. Fixture-target dogfood breaks both problems.
12. **Input-contract fail-fast verified.** A test invocation of `ralf-spec` with a target but no agent-verifiable AC in the DoD MUST exit with the `INPUT_CONTRACT_VIOLATION` error from R2 (no silent default, no synthesized AC). Verifiable by running the skill against a deliberately-incomplete DoD and asserting exit non-zero plus the error string in output.
13. **T3 escalation policy verified.** A test invocation where T3 finds blocker/critical after 2 cycles MUST result in a `human`-labeled escalation bead (autonomous mode) OR a structured stop with re-architect recommendation (interactive mode). This can be verified by a fixture spec engineered to fail T3.
14. **Preflight size warning verified.** A test invocation against a target exceeding 200 non-blank lines emits a structured size-warning before any tier runs. Interactive mode prompts for proceed/abort; autonomous mode logs and proceeds. Verifiable by running the skill against a fixture spec of 250 lines and asserting the warning appears in `pipeline-report.json` and stderr.
15. **Fast-follow deps recorded.** `bd show agents-config-abn9.12 --json | jq '.[0].dependencies[].id' | grep agents-config-abn9.11` returns the expected blocks edge; `bd show agents-config-3f52 --json | jq '.[0].dependencies[].id' | grep agents-config-abn9.11` returns the expected discovered-from edge.
16. **T2-minimum-reserve cap allocation verified.** Fixture invocations confirm the R13 allocation table: `ralf:cycles=2` → T1=1/T2=1, `ralf:cycles=3` → T1=2/T2=1, `ralf:cycles=4` → T1=3/T2=1, `ralf:cycles=5` → T1=3/T2=2, `ralf:cycles=6` → T1=3/T2=3, `ralf:cycles=12` → T1=3/T2=3 + `CYCLES_CAP_OVERCOMMITTED` warning. T2 is NEVER allocated 0 cycles.
17. **YAML schema validation fail-fast verified.** A fixture invocation with a tier YAML missing a required key (e.g. `default_prompt` removed) exits with code 1 and emits `CONFIG_VALIDATION_ERROR: <file>:<key> ...` on stderr. A fixture with `default_prompt: ""` (empty after whitespace-strip) also exits 1 with the empty-prompt error message.
18. **Reviser path-scope precondition + sha256 safety net verified.** Two sub-checks:
    - **18a:** A fixture invocation that attempts to invoke the reviser with a target path outside `.ralf/<session_id>/spec/` (e.g. directly against the original target file) causes the reviser to refuse with `PATH_SCOPE_VIOLATION` recorded in `reviser-report.json`. The regex accepts both absolute and relative paths (verified by two sub-fixtures).
    - **18b:** Independent of the regex check, a fixture invocation where a misbehaving reviser DOES edit the original (simulated by manually editing the original file mid-pipeline) causes the pipeline-exit sha256 comparison to detect the mutation and emit `ORIGINAL_TARGET_MUTATED` as a top-level error in `pipeline-report.json`. `sha256sum <original-target>` matches the pre-run snapshot in `.ralf/<session_id>/spec/in/original.sha256` for the non-mutation case.
19. **Per-model efficacy attribution verified.** A fixture pipeline report whose synthesized ledger includes one entry with `attributions: ["gemini", "codex"]` produces a `pipeline-report.md` Per-Model Efficacy table where the `raised` column shows `+1` for gemini AND `+1` for codex (i.e. double-counted by design). Similarly for `applied`/`refused` when the reviser acts on the shared entry.
20. **EXTERNALIZED_SPEC interactive contract verified.** A fixture invocation with a bead-ID target whose description is `See docs/beads/<other>-*.md` (matching R3's pointer heuristic) in interactive mode exits with code 2 and emits a `USER_DECISION_REQUIRED` block with `reason: EXTERNALIZED_SPEC` and a populated `retarget-to-file` option in `reinvoke_flags`.

---

## Design notes (decisions and rationale)

### D1 — Why Hybrid integration was chosen over Substitution or Synthesis

Three integration models were considered:
- **Synthesis:** one Claude reviewer wraps + invokes foreign CLI, then merges into a single report. Pro: Claude re-weights foreign findings against project context. Con: extra tokens; foreign perspective gets diluted by Claude's filter.
- **Substitution:** foreign CLI's output IS the cycle's report. Pro: cheapest; purest foreign perspective. Con: no sanity filter; raw foreign findings reported as-is.
- **Hybrid:** Claude reviewer + foreign reviewer dispatched independently in parallel; skill aggregates both reports. Pro: maximum diversity per cycle; both perspectives preserved unfiltered. Con: most expensive per cycle.

**Chosen: Hybrid**, because the cost premium is modest (one extra subagent dispatch per cycle) and the diversity benefit is the entire reason for adding foreign-agent participation in the first place. Filtering or diluting the foreign perspective via a Claude wrapper would defeat the purpose.

### D2 — Why the closed-loop in-skill reviser

The alternative — caller-driven revision between invocations — would push the loop coordination onto every caller (formula steps, manual invocations, future automation). With the closed loop, callers get a one-shot interface: "review and converge this spec," return when done. Centralized fixer also keeps revision style consistent (one Claude voice across the whole revision history of the target) and avoids the "fixer drift" problem where different revisers introduce stylistic inconsistencies.

The cost of this choice: the skill now writes to its target (file or bead description). The "read-only w.r.t. codebase" invariant from the original 2026-04-19 design is preserved — code is still untouched — but the skill is no longer read-only w.r.t. all targets. The rename to `ralf-spec` makes this scope shift explicit.

### D3 — Why tiered over flat-fan-out-every-cycle

Gemini 3 Pro's advice was the load-bearing input here. The argument: most spec defects fall in distinct difficulty classes. Cheap structural defects (missing sections, formatting, blatant omissions) are caught by a fast/cheap reviewer; semantic and adversarial defects need heavyweight reviewers. Running heavyweight reviewers on cycle 1 wastes their tokens on cheap-defect-class issues. Running cheap reviewers on a polished spec wastes their tokens on issues that are already absent.

Tier 1 (cheap Gemini) catches the bulk-quantity-low-severity issues fast. Tier 2 (Claude + Codex deep adversarial) then operates on a spec that has already had its low-hanging fruit cleared, so its tokens go toward issues that genuinely need heavyweight perspective. Tier 3 (single all-three pass, conditional on T2 having applied non-minor fixes) is a safety net against the oscillation problem — confirming that T2's revisions didn't introduce new defects from a multi-perspective view.

### D4 — Why MINOR-don't-retrigger is universal

Without this rule, the loop terminates only on "zero findings" — which an adversarial reviewer can prevent indefinitely by always finding *some* minor stylistic critique. The loop never converges; tokens hemorrhage; the user reads a transcript of 10 cycles arguing about variable naming. With MINOR-informational-only, MINOR findings are reported but never block tier exit. The tradeoff: minor improvements aren't auto-applied. That is the correct tradeoff for a bounded-cost loop.

### D5 — Why anti-bikeshedding clause goes in reviewer prompts, not in the reviser

The bikeshedding risk is on the *reviewer* side (it generates the MINOR findings). The reviser is downstream — it only applies what the ledger contains. Placing the clause in reviewer prompts means MINOR findings simply aren't generated for stylistic issues, which is cleaner than generating them and then filtering at ledger time.

### D6 — Why diff-patch discipline for the reviser

Gemini 3 Pro explicitly flagged the regression risk of full-document regeneration: a reviser that rewrites the whole document to "apply" a localized fix has license to hallucinate elsewhere. Forcing the reviser into `Edit`-tool discipline (old_string / new_string targeted replacements) constrains blast radius to the actual defect locations and makes any unintended change easy to spot in the cycle's diff output.

### D7 — Why a defect-synthesis pass between reviewer fan-out and reviser

The reviser-myopia risk surfaced during crit: independent reviewers flagging "X is wrong on line 12 → change to Y" may each be reporting localized symptoms of a systemic issue. A reviser receiving the raw ledger applies the targeted patches, leaves the underlying pattern untouched at lines 47, 89, 134, the next cycle's reviewers report the same pattern again, and the loop wastes cycles. The synthesis pass exists to detect this: it deduplicates, reconciles severity, promotes ≥2 similar findings to a single `systemic` entry with a list of locations and a recommendation to grep for additional occurrences. The reviser then knows to apply systemic fixes across all occurrences AND scan for more, while preserving the diff-patch discipline for the actual edits. This costs one extra subagent dispatch per cycle but pays for itself by killing the localized-symptom-of-systemic-issue loop.

### D8 — Why the reviser is a named custom agent (not an inline-prompted subagent)

A named agent file (`src/user/.agents/agents/ralf-spec-reviser.md`) is discoverable (shows up in `agents/` listings), independently configurable (tools, model, effort all set in frontmatter and overridable per environment), and individually testable (can be invoked directly from a shell with a fixture ledger). An inline-prompted subagent loses all three. The cost is one extra file in the repo; the benefit is operational visibility and the ability to tune the reviser in isolation.

### D9 — Why the staging area, not in-place mutation

Two reasons. **First**, observability and audit: every cycle's reviewer outputs, synthesized ledger, reviser input/output, and resulting diff are persisted. An auditor can reconstruct exactly how a spec evolved across the pipeline. **Second**, separation of concerns: the skill produces a revised version; the orchestrator decides whether to apply it back to the original (file, bead, PR, discard). This makes the skill bead-agnostic and file-agnostic at the same time — downstream consumers all just see "here is the staged revised version, and here is the forensic trail." Rollback and side-by-side comparison are free.

### D10 — Why agent-verifiable AC is a required input

Without agent-verifiable ACs, "convergence" has no objective definition. The reviewers can only judge "does this spec feel complete?" — which lets MINOR-class style debates drag the loop on indefinitely and turns PASS into a vibes-check. Requiring at least one shell-checkable AC in the DoD forces the orchestrator to articulate "what would prove this spec is done?" up-front. Reviewers and synthesis can then explicitly score findings against that AC, and the reviser's refusal-on-DoD-violation rule has something to refuse on. The fail-fast at input is intentional: the skill refuses to start rather than silently degrading to a vibes-check.

---

## Open questions

None at write-spec time. All identified questions were resolved during the discuss step or applied via crit review; remaining decisions were within engineering judgment and are recorded as decisions in this document.

If implementation surfaces a question that needs human judgment (e.g. T1 Gemini CLI availability is unexpectedly poor and the cheap-sweep tier becomes useless in practice even with fallback), the implementer should follow the Human-Escalation Pattern rather than guess.

---

## References

- `docs/specs/2026-04-19-ralf-it-form-reevaluation-design.md` — the original `ralf-it` split; this bead resolves the deferred foreign-agent-on-review decision (line 330–331)
- `docs/plans/2026-03-15-ralf-foreign-agents-design.md` — prior foreign-agent design for `ralf-implement`; the new prompts borrow patterns from here
- `src/user/.agents/skills/ralf-implement/foreign-agent-prompt.md` and `foreign-eyes-prompt.md` — prompt patterns and degradation-status enum referenced by R6 and R8
- `src/user/.claude/rules/codex-routing.md` — Codex invocation contract (`codex-companion.mjs task < prompt.md`, model selection guidance)
- Gemini 3 Pro guidance (chat input, 2026-05-13) — source of the tiered architecture, anti-bikeshedding clauses, MINOR-informational-only rubric, JSON defect-ledger pattern, and diff-patch discipline for the reviser
