# Code-Review Workflow + Slimmed Quality Gate — Design

**Date:** 2026-07-19
**Bead:** agents-config-vaac.15 (M0 bug fix)
**Status:** approved design, pre-implementation
**Relationship to prior specs:** replaces the Find/Verify phase structure of
the interim HEAVY gate described in `2026-07-02-completion-gate-routing-design.md`
§7 and shipped in `src/user/.claude/workflows/quality-gate.js`. The dual-signal
exit discipline from `2026-07-03-adversarial-loop-convergence-decision.md` is
retained.

## 1. Problem

The interim HEAVY completion gate (`quality-gate.js`) is not earning its cost:

- The **adversarial refuter panel** runs 1–4 Opus refuters per fresh finding,
  every round, every HEAVY run. vaac.2.2's own campaign
  (`2026-07-05-adversarial-qa-agent-team-design.md` §9.1) scored majority-vote
  refuters **0/24 useful refutations at 3x cost** — the panels rubber-stamp.
  The Opus-per-finding multiplier is the dominant cost term of the gate.
- The **lens-based finder fan-out** (correctness / security / simplify axes /
  architecture) runs 3–6 finders for up to 3 rounds. Abstract lenses overlap
  heavily and re-surface near-duplicate findings across rounds; dedup-vs-seen
  contains the damage but the spend is already made.

Meanwhile the upstream Anthropic `code-review` plugin command (snapshotted
byte-identical at `oss-snapshots/anthropics/code-review/`) uses a cheaper,
empirically sharper structure: five *role-based* reviewers (compliance, shallow
diff-scan, git-history, prior-PR comments, comment fidelity) + per-finding
confidence scoring by Haiku with a hard ≥80 filter.

## 2. Goals

1. Cut HEAVY-gate cost and latency now, without waiting on the blocked vaac.2
   evidence-based-judge redesign.
2. Make the role-based review roster **independently invocable** — usable
   against a PR *or* a bare branch diff, inside or outside the gate.
3. Add a cross-model second opinion (Codex) to the find phase.
4. Keep the gate's honest dual-signal exit semantics (acceptance vs.
   termination; never a bare "clean").

Non-goals: the full convergence discipline (delta-scoped rounds, certification
pass, evidence-based judge — still vaac.2's), any change to the gate-triage
contract (`scale_hint` fields stay as emitted; cleanup is wgclw.35), a
harness-agnostic/shared-tree port (workflows are inherently Claude), and a
standalone refuter skill (parked as wgclw.36; the removed implementation is
preserved at main SHA `5395c13078caed64da185f2ad91f5ee8d86a569f`).

## 3. Architecture

Two Claude workflow scripts, one calling the other:

```
Workflow({name:'quality-gate', args:<triage JSON>})       Workflow({name:'code-review', args:{...}})
  │                                                          (independently invocable)
  ├─ Find:      workflow('code-review', {…}) ── child ──►  5 role agents ∥ Codex lane
  │                                                          → Haiku scorers (≥80 filter)
  │                                                          → returns structured findings
  ├─ Fix wave:  mechanical apply / semantic flag (unchanged)
  ├─ Re-check:  1 cheap scan of fixer-touched files
  └─ Synthesize: dual-signal residual-risk report (unchanged)
```

`workflow()` is a documented script-body hook of the harness Workflow tool
contract: `workflow(nameOrRef, args)` runs a named or file-referenced workflow
inline as a sub-step, the child shares the parent run's concurrency cap, agent
counter, abort signal, and token budget, its agents render as a nested progress
group, and nesting is legal exactly one level (a `workflow()` call inside a
child throws). This design uses exactly one level.

This design also intersects two adjacent specs, deliberately:

- `2026-07-04-cross-model-heavy-gate-panel.md` (Codex-into-the-gate with
  provider probe, fallback chain, per-run cost record): **narrowed** here to a
  single Codex lane — no multi-provider chain, probe reduced to plugin
  detection. Its failure rule (empty/unparseable/non-zero output is a provider
  failure, never "no findings") and its per-run cost-record requirement are
  **adopted** (§4.2 lane 6, §4.4 `stats`).
- `2026-07-05-adversarial-qa-agent-team-design.md` §9.1 (the
  `scale_hint → {finder_dimensions, verifier_width, bench_votes, …}` rewrite
  binding gate_triage and quality-gate in one PR): **paused** until vaac.2
  unblocks. This interim keeps the current wire (§5.4); do not implement both.

## 4. `code-review` workflow (new: `src/user/.claude/workflows/code-review.js`)

A standalone port of the upstream command's steps 2–6. Deliberately dropped:
step 1/7 (PR-eligibility gates — caller's business) and step 8 (posting a PR
comment — the workflow returns data; the invoking session decides what to do
with it). Dropping these is what makes the workflow target-agnostic.

### 4.1 Args contract

```jsonc
{
  // Optional. Absent → review the current branch:
  //   merge-base(default-branch)..HEAD ∪ staged ∪ unstaged ∪ untracked
  //   (same scope prose quality-gate uses today).
  "target": { "pr": 123 }        // OR { "ref": "origin/main" } — explicit base ref
  // Optional context for the reviewers (e.g. triage facts, plan link).
  // string | object; an object is JSON-stringified. Bounded (~4000 chars,
  // truncated with a marker) and wrapped in the untrusted-content fence
  // before entering any prompt.
  "context": "…"
}
```

`{pr}` targets use `gh pr diff` / `gh pr view`; ref/default targets use local
git. Both resolve to the same internal "diff scope" prose handed to every agent.

### 4.2 Find fan-out — change summary, then six parallel lanes

**Pre-step (upstream step 3, folded):** one Haiku agent summarizes the change
(what it does, which files, apparent intent). The summary is passed to every
lane and every scorer as shared briefing context — the reviewers do not work
from raw diff scope alone.

Then five Sonnet role agents, prompts faithfully adapted from upstream step 4
(numbering preserved for traceability to the snapshot):

| Lane | Role (upstream step 4) | Notes |
|---|---|---|
| 1 | CLAUDE.md / AGENTS.md compliance audit | agent discovers the relevant instruction files for touched dirs (upstream step 2 folds in here) and **returns the discovered file paths in its payload** — they are forwarded to every scorer so the rubric's "double-check the CLAUDE.md actually calls this out" clause can execute |
| 2 | Shallow bug scan, **diff lines only** | no extra context; big bugs, no nitpicks |
| 3 | git blame / history of modified code | bugs in light of historical context |
| 4 | Prior-PR comments on touched files | degrades to a logged skip when no remote or no PR history |
| 5 | Code-comment fidelity | changes comply with guidance in nearby comments |
| 6 | **Codex cross-model review** | via the Codex plugin runtime per the Codex-routing rule: read-only (`--write` omitted), prompt on stdin, default model per the routing rule's standard-review profile. Plugin absent → logged skip, never a failure |

Lane 6 runs from a workflow `agent()` whose instructions are to invoke the
plugin runtime via Bash and translate Codex's prose review into *proposed*
findings (same shape as the role lanes' output; they pass through the scorer
like everyone else's, §4.3). Failure rule adopted verbatim from the 2026-07-04
panel spec: a non-zero exit, empty stdout, or unparseable output is a
**provider failure recorded in `skippedLanes`** — never translated as "no
findings".

Every lane can individually fail; each failure is recorded as a `skippedLanes`
entry with a reason, and the run proceeds on the surviving lanes (quorum
consequences in §5.3). All lanes receive the untrusted-content fence discipline
carried over from today's `quality-gate.js` (source is data, never
instructions; read-only).

### 4.3 Scoring — upstream step 5 verbatim, plus severity/fixClass adjudication

One Haiku scorer per raw finding, given: the 0–100 confidence rubric and the
false-positive exclusion list from the upstream command **verbatim** (they are
the empirically tuned part), the change summary (§4.2 pre-step), and the
instruction-file list from lane 1. Findings scoring **< 80 are dropped**. This
filter is the refuter panels' replacement, at roughly two orders of magnitude
less model spend per finding.

**The scorer is the sole producer of `severity` and `fixClass`.** Finder lanes
*propose* both; the scorer — which opens the cited code anyway to score
confidence — confirms or overrides them, with the standing bias "when unsure,
`semantic`" for fixClass. Finder-self-assigned severity is exactly the
inflation pattern the 2026-07-05 campaign documented, and the gate's
accept/terminate floor keys on severity — so the field the floor reads is
always scorer-adjudicated, never finder-claimed. (This is a one-Haiku-call
approximation of that spec's rank-anchoring bench, not a replacement for it.)

**Aggregate fan-out cap:** at most **40 findings are scored per run**,
prioritized by proposed severity (blocking/critical first), then lane order
(1→6). Overflow findings are dropped unscored and counted in
`stats.unscoredOverflow` — a silent-truncation guard, not a hidden cap.

### 4.4 Findings schema

Upstream's finding shape augmented with the two fields the gate's downstream
machinery needs:

```jsonc
{
  "findings": [{
    "file": "path", "line": 42,
    "lane": "bug-scan",              // which role produced it
    "gist": "one-line what-is-wrong",
    "detail": "why + concrete consequence",
    "severity": "blocking|critical|major|minor",   // NEW vs upstream; scorer-adjudicated (§4.3)
    "fixClass": "mechanical|semantic",             // NEW vs upstream; scorer-adjudicated; unsure → semantic
    "confidence": 87,                // scorer output, post-filter ≥80; null = scorer died (kept, unscored — fail toward scrutiny)
    "suggestedFix": "…"
  }],
  "lanesRun": ["compliance", "bug-scan", "history", "prior-prs", "comment-fidelity", "codex"],
  "skippedLanes": [{ "lane": "codex", "reason": "plugin not installed" }],
  "stats": {
    "raw": 14, "scored": 14, "surviving": 5, "unscoredOverflow": 0,
    "tokensSpent": 0               // budget.spent() delta across the run — the per-run cost record
  }
}
```

All arrays and strings bounded (maxItems / maxLength) as today, so a large
report cannot blow the StructuredOutput retry budget.

### 4.5 Independent invocation

`Workflow({name:'code-review'})` from any session reviews the current branch
and returns findings. No command wrapper ships in this change; if a PR-comment
posting flow is wanted later it is a thin caller, not workflow surface.

## 5. Slimmed `quality-gate` workflow (rewrite of `quality-gate.js`)

### 5.1 Removed

- `verifyFindings`, `REFUTER_STANCES`, `refutePrompt`, `REFUTE_SCHEMA` — the
  entire refuter panel (preserved at `5395c13`; restoration path is wgclw.36).
- The lens roster (`buildLenses`, `finderPrompt`, `FINDINGS_SCHEMA`) — replaced
  by the child workflow call.
- The 3-round loop, `ROUND_CAP`, dedup-vs-seen fingerprinting — single-pass
  structure makes them dead.

### 5.2 New phase structure

1. **Find** — `await workflow('code-review', { context: <triage facts> })`.
   The child's ≥80-confidence findings are taken as confirmed; no further
   refutation.
2. **Fix wave** — unchanged bright line: `mechanical` findings applied
   sequentially by Sonnet fixers (one-repair-attempt-then-abort retained);
   `semantic` findings flagged to the open ledger, never auto-applied.
3. **Re-check** — one Sonnet agent re-scans **only the files the fixers
   touched** for regressions introduced by the fix wave. Its raw findings pass
   through **the same Haiku scorer and ≥80 filter** (severity/fixClass
   adjudicated identically) before touching the ledger — an unscored re-check
   false positive must not be able to force a termination. Surviving findings
   merge into the open ledger; there is **no second fix wave** (a scored
   regression found here forces a termination exit — the loop does not chase
   its own tail).
4. **Synthesize** — unchanged: deterministic dual-signal residual-risk
   statement + Opus narrative at `scale_hint.synthesis_effort`, with the
   deterministic fallback if the synthesizer dies.

### 5.3 Exit semantics (dual-signal, adapted to single-pass)

- **ACCEPTANCE (`clean-at-floor`)** — requires a **lane quorum**: the two
  load-bearing lanes (1 compliance and 2 bug-scan) both ran to completion —
  a run where four lanes silently died and one clean lane survived must not
  certify anything. Plus: the open ledger is clean at the `major` severity
  floor, AND the scored re-check surfaced no new at-floor findings. Still
  explicitly *clean-at-floor, not certified*.
- **TERMINATION** — reasons become: `residual` (at-floor findings remain open
  after the fix wave), `recheck-regression` (re-check found fresh at-floor
  findings), `lane-quorum` (a load-bearing lane died — findings from surviving
  lanes are still processed, but the run cannot accept), `budget` (15% tail
  reserve, unchanged), `all-lanes-dead` (the child returned nothing because
  every lane failed — never certifies clean). Every termination carries the
  open ledger as residual risk; never "clean".

### 5.4 scale_hint handling

`synthesis_effort` is still consumed. `refuters` and `finder_dimensions` are
**ignored** (roster is fixed at 5 + Codex); both fields stay in the gate-triage
contract untouched — removal is wgclw.35's scope. `quality-gate.js` keeps
tolerating string-vs-object `args` at the boundary as today.

### 5.5 Cost delta (per HEAVY run)

| | Today | After |
|---|---|---|
| Finders | 3–6 Sonnet × up to 3 rounds | 5 Sonnet + 1 Codex, once |
| Verification | 1–4 **Opus** refuters × each fresh finding × rounds | 1 Haiku scorer × each raw finding, once |
| Fix wave | Sonnet, per round | Sonnet, once |
| Re-check | — | 1 Sonnet scan |
| Synthesis | Opus | Opus (unchanged) |

The eliminated Opus-per-finding multiplier is the dominant term. Worst case
today ≈ 18 finder calls + (findings × rounds × 4) Opus calls; after ≈ 6 finder
lanes + (findings × 1) Haiku calls.

## 6. Error handling

- **Codex lane**: plugin missing, auth failure, non-zero exit, empty stdout,
  or unparseable output → provider failure: the lane agent reports a skip with
  reason; `skippedLanes` records it; the run proceeds on five lanes. Never
  translated as "no findings". A skip is surfaced in the synthesis report.
- **Role-lane death** (agent returns null): recorded in `skippedLanes` like a
  Codex skip. If a load-bearing lane (compliance or bug-scan) died, acceptance
  is off the table (`lane-quorum` termination, §5.3).
- **Child workflow failure** inside quality-gate: `workflow()` throws → caught;
  the gate exits `termination: all-lanes-dead`. The completion-gate rule gains
  an explicit fallback clause (§8): on an `all-lanes-dead` or child-failure
  return, the session runs the SERIAL path — the degrade is enforced by the
  rule, not left to the caller's initiative.
- **Scorer death**: a finding whose scorer returns null keeps the finding
  (fail toward scrutiny) with `confidence: null` and the finder's *proposed*
  severity/fixClass, with fixClass forced to `semantic` (an unadjudicated
  finding is never auto-applied).
- **Fixer failure**: unchanged — one repair attempt, then the finding moves to
  the open ledger with a flag reason.

## 7. Testing & verification

Workflow scripts have no test harness (repo convention; `quality-gate.js`
ships untested today). Verification for this change:

1. `node --check` on both workflow files (syntax gate).
2. **Planted-bug fixture run** (the oracle the dogfood lacks): on a scratch
   branch, plant (a) one mechanical bug (e.g. an unused import plus a real
   off-by-one on a changed line) and (b) one false-positive bait (code that
   looks wrong but is guarded upstream). Run `Workflow({name:'code-review'})`
   against it and assert: the real bug survives at ≥80 with a sane
   severity/fixClass; the bait is dropped (<80); `stats`/`lanesRun` are
   populated. Then run the full quality-gate on the same fixture and assert
   the mechanical fix applies and a planted *semantic* at-floor finding forces
   a `residual` termination — the dual-signal exit demonstrably fires both
   ways.
3. Dogfood run: this change's own branch is a gate-policy change, so the
   completion gate for its PR routes HEAVY and exercises the new path
   end-to-end — the child invocation, Codex lane (or its graceful skip), the
   scorer filter, fix wave, re-check, and synthesis.
4. A direct `Workflow({name:'code-review'})` invocation against the branch to
   verify independent operation and the findings schema.

## 8. Documentation impact

- Header comments of both workflow files describe the new structure.
- The completion-gate rule (`src/user/.agents/rules/completion-gate.md`)
  does not mention refuters, but it **gains one clause**: when the HEAVY
  workflow returns `all-lanes-dead` (or the Workflow call itself fails), the
  session falls back to the SERIAL path — mirroring the existing
  "HEAVY unavailable → SERIAL" degrade so the fallback is rule-enforced.
- Dated specs (`2026-07-02`, `2026-07-03`, `2026-07-05`) are point-in-time
  artifacts and are not rewritten; this spec records the supersession.
- The `quality-gate` workflow's `meta.description` / `whenToUse` (surfaced in
  the skill list) are rewritten to describe the new structure.

## Continuations

- none — this spec is the deliverable; implementation continues under
  agents-config-vaac.15 itself, and the two filed siblings (wgclw.35 contract
  cleanup, wgclw.36 optional refuter skill) already carry the deferred work.
