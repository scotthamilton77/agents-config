# agent-ruling merge-judge — a merge-worthiness gate behind a head-bound verdict contract

- **Date**: 2026-07-03
- **Bead**: agents-config-xvmf8 (M1, orphan)
- **Status**: draft
- **Related**: agents-config-vaac.2 (shared adversarial-QA convergence /
  evidence-based judge layer — `related-to`, not a blocker; the eventual
  engine-swap target), agents-config-wgclw.14 (the two-axis review/merge
  policy this extends)
- **Extends**: `docs/architecture/review-merge-policy/design.md` (the evergreen
  two-axis contract; the `agent-ruling` row there is *design-reserved* and this
  spec un-reserves it)

## Problem

The two-axis review/merge policy reserves a third merge-rule, `agent-ruling`:
"an independent, cross-model agent evaluates the diff and renders a merge
go/no-go verdict." It is the only merge-rule not built. The resolver hard-
rejects it (`resolve_policy.py:166-167`, PolicyError "design-reserved and not
yet implemented"), and the merge-guard gate refuses it
(`SKILL.md:119`, "Never (design-reserved) … report not implemented and hand
off"). A repo cannot configure autonomous merge on an independent AI judge's
ruling.

Building it means answering two questions the design left implicit:

1. **What is the judge actually deciding?** Not "is this the best possible
   design?" — that is a brainstorm/spec/plan-time critique, already settled
   upstream. At a *merge gate* the only question is **"is there any
   disqualifying defect that must block this merge?"** A design-critique
   reviewer that returns "needs-attention" over an architectural preference
   would block merges on taste and make the rule nearly unusable. The judge is
   a **merge-worthiness gate**, not a design review — it keeps the independent,
   cross-model, adversarial *energy* but aims it at merge-disqualifying
   defects.
2. **How is independence guaranteed at a gate?** The cross-model principle
   ("the judge should not be the model that wrote the code", design.md "AI
   reviewer vs. AI merge-judge") must be *enforced*, not hoped for. A judge that
   fails open, or that turns out to be the author's own model family, silently
   reopens the "no zero-review auto-merge is structurally impossible" hole the
   whole policy exists to keep closed.

## Design

### Core shape: a verdict contract, a pluggable judge, one backend now

Three layers, boundary-first:

1. **The verdict envelope** (the keystone) — a head-bound, structured value the
   gate consumes. This is the contract; everything else is replaceable behind
   it.
2. **A judge backend** — injected, not hardwired. Given `(base, head, diff,
   judge_config)`, it produces a verdict envelope. This PR ships **exactly
   one** backend, `codex`, driven through the plugin's `task` runtime with a
   **bespoke merge-worthiness prompt** (not the stock `adversarial-review`
   template, whose framing is design critique). The interface is shaped for
   additional backends (`claude`, `opencode`) and for vaac.2's future
   evidence-based judge, but **none of those are in this PR**.
3. **The gate** — merge-guard invokes the judge harness at Step 4, merges iff
   `verdict == "go"`, and fails closed to hand-off on every other outcome.

The judge backend is an outside-world dependency **passed in** (the resolved
policy JSON carries the judge config); merge-guard shells out to the harness
exactly as it already shells out to `resolve_policy.py` and
`check-merge-eligibility.sh`. No module reaches for `codex` as a global.

### What the judge evaluates — merge-worthiness, not design critique

The judge receives a strict rubric. It **blocks** (emits a merge-blocking
finding) only for a disqualifying defect:

| Blocks (no-go) | Does **not** block (never a merge finding) |
|---|---|
| Correctness defect the diff introduces (logic bug, broken control flow) | Design/architecture preference ("I'd have used a different pattern") |
| Security vulnerability (injection, secret, auth bypass, unsafe input) | Style, naming, formatting (linters own this) |
| Data-loss / irreversible operation without a guard | DRY / "could be more elegant" opinions |
| Broken public contract or unupdated callers | Speculative "this assumption might fail someday" with no concrete path |
| Regression of behavior other code relies on | Anything already accepted upstream in the spec/plan |
| Code that will not build / run | Test-nice-to-haves beyond the repo's stated coverage bar |

The judge's posture is **"clear unless disqualified"** — a clean-but-imperfect
diff merges. That is a different default from "fail closed": the *review
outcome* defaults to `go` when the review runs and finds nothing
disqualifying; the *harness* defaults to hand-off when the review cannot be run
or trusted at all (see Fail closed). The judge is still adversarial — it hunts
hard for the defect the author's model was blind to — it is just hunting for
*shippability* defects, not design imperfections.

### The verdict envelope

The harness emits one JSON object on stdout — the only shape the gate reads:

```
JudgeVerdict = {
  commit_id: str,              # head SHA the judge evaluated (bind to head)
  verdict: "go" | "no-go" | "abstain",
  judge_backend: str,          # "codex"
  judge_model: str,            # e.g. "gpt-5.5"
  judge_effort: str,           # e.g. "high"
  author_model_family: str,    # declared; recorded for audit
  judge_model_family: str,     # derived from judge_model; recorded for audit
  summary: str,                # the judge's one-line rationale
  merge_blocking_findings: [   # the disqualifying defects it found (empty on go)
    { category, title, file, detail, why_blocking }
  ],
}
```

- **`go`** — the judge ran and found **zero** merge-blocking findings at this
  head. The **only** value that authorizes a merge.
- **`no-go`** — the judge found ≥1 merge-blocking finding. Hand off.
- **`abstain`** — the judge could not render a trustworthy ruling (backend
  unavailable, timeout, non-zero exit, output that fails to parse/validate
  against the judge schema, or a `commit_id` mismatch). Distinct from `no-go`
  for *reporting* only; at the gate both mean **do not merge**.

**Head binding.** `commit_id` is stamped from the head the judge ran against. If
it does not equal the PR's current `headRefOid` at gate time, the verdict is
stale → `abstain` → the gate re-evaluates (same discipline as
`--match-head-commit`). A verdict never counts for a head it was not computed
against.

**Fail closed, always.** Every path that is not an affirmative, current-head
`go` fails to hand-off. There is no branch in which an error, a timeout, an
unparseable output, or an unavailable backend results in a merge. This is the
load-bearing property that keeps `agent-ruling` a *real review* and preserves
"no zero-review auto-merge."

### Verdict collapse — the harness owns go/no-go

The harness, not the model, decides the verdict. The judge prompt asks codex to
emit **only** its `merge_blocking_findings` (against the rubric above) plus a
`summary`; the harness derives:

| Judge output | Envelope `verdict` |
|---|---|
| Valid JSON, `merge_blocking_findings == []` | `go` |
| Valid JSON, `merge_blocking_findings` non-empty | `no-go` |
| non-zero exit / codex unavailable / timeout / unparseable or schema-invalid output / oversized diff | `abstain` |

Deriving `go` from *"the judge reported no disqualifying defect"* — rather than
trusting a model-declared verdict string — keeps the gate evidence-based: the
authority is the presence or absence of a concrete blocking finding, not the
model's self-assessment mood.

### The judge harness

New merge-guard helper, `judge_merge.py` (+ `judge_merge_test.py`). Python, per
the repo's "Python over Bash for testable logic" principle — the collapse
rules, the cross-model check, the head-binding, the diff assembly, and the
fail-closed branches are exactly the logic that needs unit tests. It:

1. Reads the resolved policy JSON (judge config) and the PR coordinates
   (`owner`, `repo`, `pr`, and the `head_ref_oid` merge-guard computed at
   Step 3).
2. Resolves the merge base (the PR's base ref SHA / `git merge-base`) and
   **assembles the branch diff** (`git diff <base>...HEAD`). *(Diff assembly is
   the harness's job now: unlike `review`/`adversarial-review`, `codex task`
   has no `--base`/`--scope` target resolution.)* If the base cannot be
   resolved or the diff is empty, the harness returns `abstain` — "nothing to
   review" must never read as `go`. If the diff exceeds a configured size
   guard, the harness likewise returns `abstain` (a diff too large to review in
   one shot must not silently pass) — chunking / in-sandbox gathering is future
   work.
3. Runs the backend as a **blocking foreign-CLI subprocess** with a timeout,
   piping the bespoke merge-worthiness prompt on stdin (per codex-routing: pipe
   prompts on stdin):

   ```bash
   node "$CODEX_HOME/scripts/codex-companion.mjs" task \
     --json -m "<judge-model>" --effort "<judge-effort>" < merge_judge_prompt.md
   ```

   `CODEX_HOME` resolves per the codex-routing rule
   (`${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex}`).
   No `--write` → the sandbox is read-only. `ensureCodexAvailable` throws
   (non-zero exit) when the codex CLI is absent → harness maps to `abstain` →
   fail closed. The `task` path is the **already-sanctioned** programmatic
   runtime call in codex-routing (it is *the* documented "from a skill or
   subagent" invocation), so no new governance carve-out is required.
4. Extracts the judge JSON from the task output, validates it against the judge
   schema (below), collapses to the envelope, stamps `commit_id =
   head_ref_oid` and the judge/author family fields, and writes the envelope to
   stdout. Any extraction/validation failure → `abstain`.
5. **Records the head-bound verdict** to a state file keyed by
   `<owner>-<repo>-<pr>-<head_sha>.judge.json` (alongside the retained
   `wait-for-pr-comments` inventories). On a re-invocation for the **same
   head**, the harness returns the recorded verdict instead of re-running the
   judge. This makes a `no-go` **mechanically terminal** for that head (no
   verdict-shopping by re-running until a flake says `go`) and avoids re-paying
   a full model review on every merge retry against an unchanged head. A moved
   head changes the key, forcing a fresh ruling.

**The merge-worthiness prompt** (piped to `task`) fixes the role and the
output contract:

> You are an independent merge-gate judge. You did **not** write this code.
> Decide whether the following branch diff (`git diff <base>...HEAD`) contains
> any **disqualifying defect that must block the merge**.
> **Block only on:** correctness defects the diff introduces; security
> vulnerabilities; data-loss/irreversible operations without a guard; broken
> public contracts or unupdated callers; regressions of relied-on behavior;
> code that will not build or run.
> **Do not block on:** design/architecture preference, style, naming,
> DRY/elegance, speculative future risks without a concrete failure path, or
> anything a linter owns.
> Output **exactly one JSON object**, no prose, no code fences, matching:
> `{ "merge_blocking_findings": [ {category, title, file, detail, why_blocking} ], "summary": str }`.
> If nothing is disqualifying, return `merge_blocking_findings: []`.

**Judge schema** (the harness validates the extracted object against this):

```
{ "merge_blocking_findings": [
    { "category": "correctness"|"security"|"data-loss"|"contract-break"|"regression"|"wont-run",
      "title": str, "file": str, "detail": str, "why_blocking": str } ],
  "summary": str }
```

**Transport decision — foreign-CLI subprocess, not a nested Claude subagent.**
merge-guard's SKILL runs as a low-effort sonnet subagent. A nested Claude judge
*agent* would hit the "a subagent cannot await a child it spawns" stall
(`orchestrating-subagents`). A blocking `node` subprocess is a CLI call, not an
agent dispatch, so it sidesteps the coordination trap — and delivers
cross-model-by-construction (a gpt-5.5 judge is not the Claude author) in the
same move.

### Cross-model guard — declared author family, fail closed

The cross-model principle is enforced by a **declared** author family plus a
resolver-time validation, failing closed when it cannot be established:

- `[merge-policy]` gains **`author-model-family`** — the repo declares which
  model family authors its code (`anthropic` | `openai` | `google` | `other`).
- The resolver derives the **judge** family from `judge-model` via a small,
  explicit `model → family` map (`gpt-* → openai`, `claude-*/opus/sonnet/
  haiku/fable → anthropic`, `gemini-* → google`).
- Validation (all at resolve time, fail loud — a PolicyError, never a silent
  degrade):
  - `merge-rule = agent-ruling` **requires** `author-model-family` present and
    one of the known families. Absent or unknown → error ("cannot establish the
    author family the cross-model guard needs").
  - `judge-model`'s derived family **must differ** from `author-model-family`.
    Equal (or judge family underivable) → error. A judge in the author's own
    family is the same-model self-review the rule exists to forbid.

This is a **declared per-repo assumption**, not runtime provenance: it asserts
"code in this repo is authored by family X." A repo with genuinely mixed
authorship (e.g. some diffs written by `codex:rescue --write` in an otherwise
Claude-authored repo) cannot safely declare a single family and should not use
`agent-ruling` until real per-diff provenance exists (out of scope — see
Risks). The guard makes the *declared* violation impossible to configure and
fails closed when the declaration is missing.

### Config schema (`[merge-policy]`, Axis 2)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `merge-rule` | `… \| "agent-ruling"` | unset | un-reserved; selects the judge |
| `judge-backend` | `"codex"` | `"codex"` | only `codex` accepted this PR; other values → "not yet implemented" error (same discipline `agent-ruling` itself had) |
| `judge-model` | str | `"gpt-5.5"` | the judge model; family must differ from `author-model-family` |
| `judge-effort` | `none\|minimal\|low\|medium\|high\|xhigh` | `"high"` | reasoning effort passed to `codex task --effort` |
| `author-model-family` | `"anthropic"\|"openai"\|"google"\|"other"` | unset | **required** when `merge-rule = agent-ruling`; the cross-model guard's author side |
| `judge-timeout` | duration | `"15m"` | blocking-subprocess timeout; elapse → `abstain` |

All judge keys are only meaningful when `merge-rule = agent-ruling`; the
resolver rejects them set while the rule is anything else (mirrors "merge-rule
only valid with rule-based"). `judge-backend` values other than `codex` are
rejected as not-yet-implemented, keeping un-built backends un-selectable rather
than silently broken.

### Resolver changes (`resolve_policy.py`)

- Delete the two-line `agent-ruling` reject (166-167). `agent-ruling` is already
  in `MERGE_RULES` (110), the dataclass (51), and passes the enum +
  rule-based-coupling checks unchanged. It needs **no Axis-1 vacuity guard**
  (unlike `bot-quiescence`/`human-approvals`): the judge always runs a real
  review at merge time, so it resolves fine with `bot-review-expected = false`
  and `human-approvers-required = 0`.
- Extend `ReviewMergePolicy` with `judge_backend`, `judge_model`,
  `judge_effort`, `author_model_family`, `judge_timeout_seconds` (all `None`
  unless `agent-ruling`). Add the keys to `MERGE_POLICY_KEYS`.
- Add the cross-model + effort-enum validation to `validate()`.

### Gate wiring (`merge-guard/SKILL.md`)

Replace the `agent-ruling` row at Step 4 (line 119):

> | `agent-ruling` | Invoke the judge harness (`judge_merge.py`) bound to
> `head_ref_oid`; holds **iff** it returns `verdict == "go"`. `no-go` /
> `abstain` / any harness error → report and hand off. **No retry, no re-run to
> shop for a passing verdict** — a head-bound `no-go` is terminal for that
> head. |

Add a Step-4 sub-step describing the harness call and reading the envelope; add
`rule-based` / `agent-ruling` rows to the Decision Matrix; add a Red Flag:

> | "Judge said no-go, just run it again" | Re-running to fish for a `go` is
> verdict-shopping. The head-bound verdict is recorded; a `no-go` stands for
> that head until the head moves. |

### Safety-property reconciliation (`design.md`)

Un-reserving the resolver **removes** `agent-ruling`'s resolver-side guard, so
the design's "no zero-review auto-merge is structurally impossible" paragraph —
which currently credits *the resolver's validation* and says `agent-ruling`
"when built, is itself a real review" — must be updated in the same change, or
doc and code will directly conflict at the policy's central invariant. The
reconciled statement: for `agent-ruling`, non-vacuity is a **gate** invariant —
the judge harness always performs a real, cross-model, head-bound
merge-worthiness review at merge time, and **only** an affirmative `go`
(zero disqualifying findings) authorizes; every other outcome
(`no-go`/`abstain`/error/unavailable) fails closed to hand-off. The resolver's
role for `agent-ruling` is to guarantee the judge is *configured and
cross-model* (author family ≠ judge family), not to assert a review occurred —
that guarantee moves to the gate. The `agent-ruling` merge-rule row and the
Config-schema / Resolver-contract sections of design.md are amended to match
this spec (verdict envelope, merge-worthiness framing, config keys, cross-model
guard).

### codex-routing rule

No governance carve-out is needed: codex-routing already sanctions programmatic
`task` as *the* "from a skill or subagent" invocation. Add a one-line note that
the merge-gate judge is a sanctioned autonomous `task` caller
(`src/plugins/codex/.claude/rules/codex-routing.md`), so a future reader does
not mistake the merge-gate call for a user-only slash-command path. (This is a
clarifying note, not a prerequisite — the earlier plan to sanction
`adversarial-review` is moot; we no longer use it.)

## Deliverables

1. **Resolver** — un-reserve `agent-ruling`; add judge config fields + keys;
   add the cross-model + effort-enum validation. `resolve_policy.py` + tests.
2. **Verdict envelope + judge harness** — `judge_merge.py` (codex-`task`
   backend, the merge-worthiness prompt, diff assembly + size guard, JSON
   extraction/validation, collapse rules, head binding, fail-closed branches,
   head-keyed verdict record) + `judge_merge_test.py`.
3. **Gate wiring** — `merge-guard/SKILL.md` Step 4 row + sub-step + Decision
   Matrix rows + Red Flag.
4. **design.md amendments** — safety-property reconciliation; `agent-ruling`
   row (merge-worthiness); Config-schema + Resolver-contract additions; the
   verdict envelope.
5. **codex-routing note** — mark the merge-gate as a sanctioned autonomous
   `task` caller.
6. **Bead edge** — already recorded: `agents-config-xvmf8 --related-to
   agents-config-vaac.2`.

All ship in **one PR**, gated by the completion gate. The resolver
un-reservation must not merge ahead of the gate enforcement — otherwise a repo
could configure a rule the gate can only hand off on.

## Testing

- **Resolver** — `agent-ruling` now resolves (flip
  `test_agent_ruling_not_implemented` from exit-1/"not yet implemented" to
  exit-0 with `merge_rule == "agent-ruling"`); resolves with
  `bot-review-expected = false` + `human-approvers-required = 0`; **cross-model
  guard**: `author-model-family` absent → error; author family == judge family
  (`author-model-family = openai` + default `gpt-5.5`) → error; unknown
  `author-model-family` → error; `judge-backend ≠ codex` → not-implemented
  error; bad `judge-effort` enum → error; judge keys set while `merge-rule ≠
  agent-ruling` → error; a valid config (`author-model-family = anthropic`,
  default judge) → resolves and echoes judge fields.
- **Harness verdict collapse** — valid JSON with empty
  `merge_blocking_findings` → `go`; valid JSON with a finding → `no-go`; codex
  non-zero exit → `abstain`; codex-unavailable (`ensureCodexAvailable` throws)
  → `abstain`; timeout elapsed → `abstain`; unparseable output / no JSON object
  → `abstain`; JSON that fails judge-schema validation → `abstain`; oversized
  diff → `abstain` (never a silent pass). Derive the verdict from findings,
  never from a model-declared verdict string.
- **Diff assembly** — base resolved from the PR base ref; `git diff
  <base>...HEAD` is what the judge is asked about (not the working tree); an
  empty diff is a defined case (no changes → out of scope for a merge, treat as
  abstain/handoff, not a silent go).
- **Head binding** — a verdict whose `commit_id ≠` current head → `abstain`
  (stale); envelope always stamps the evaluated head.
- **Verdict record / no verdict-shopping** — a recorded `no-go` for a head is
  returned on re-invocation without re-running the judge; a moved head
  invalidates the record and forces a fresh ruling.
- **Gate integration** — SKILL Step 4 walkthrough with a mocked envelope: `go`
  + eligible → merge; `no-go`/`abstain` → hand off, no force-merge, no retry.

## Risks / notes

- **Fail-open is the whole ballgame.** A single silent-pass branch (unavailable
  / timeout / unparseable / oversized → merge anyway) reopens the closed
  zero-review path. Every non-`go` outcome fails closed, tested explicitly.
- **We own the structured-output contract now.** Trading codex's
  `review-output.schema.json` for a bespoke prompt means the judge's JSON is
  only as reliable as the prompt makes it. The harness validates against the
  judge schema and treats any deviation as `abstain` (fail closed), so an
  unreliable emission costs a hand-off, never a bad merge.
- **Declared author family is an assumption, not provenance.** A Codex-authored
  diff (`codex:rescue --write`) in a repo that declares `anthropic`, judged by
  a gpt-5.5 (openai) judge, passes the guard while violating the cross-model
  *principle* — the guard checks the declaration, not actual authorship. Real
  per-diff provenance is out of scope; mixed-authorship repos must not adopt
  `agent-ruling`.
- **LLM non-determinism at a merge gate.** Re-runs on the same head can flip. A
  `rule-based` merge stays "deterministic" only because the rule is a
  deterministic function over a *judgment input* (like `human-approvals` over
  human judgment) **and** a `no-go` is terminal (recorded, hand off) — never an
  auto-retry loop. The head-keyed record makes that mechanical, not prose.
- **Cost / latency / diff size.** A gpt-5.5 review over a branch diff is
  expensive and slow (the codex stop-gate hook budgets 15 min). `judge-timeout`
  and the head-keyed cache bound it; a merge retried against an unchanged head
  does not re-pay. Very large diffs `abstain` (hand off) rather than risk a
  shallow pass.
- **Disengaged review floor.** With `bot-review-expected = false` +
  `human-approvers-required = 0`, an `agent-ruling` repo turns off Axis-1
  polling and the "review still in flight" floor — so ~100% of the zero-review
  defense rests on the single judge call succeeding and failing closed. That is
  *by design* for a repo that chose an AI judge as its sole reviewer, and it is
  why the fail-closed discipline is non-negotiable. A repo may run the judge as
  its **sole** gate (a named choice); the harness's `abstain`-on-unresolvable-
  base-diff belt ensures "nothing to review" can never read as `go`, and
  CI-green still applies independently when CI is configured.

## Out of scope

- **`adversarial-review` as the instrument** — deliberately not used; its
  design-challenge framing is the wrong question for a merge gate.
- `claude` and `opencode` judge backends (interface shaped for them; not
  implemented — fast-follow beads).
- Real per-diff authorship provenance (declared `author-model-family` is the
  MVP; mixed-authorship repos must not use `agent-ruling`).
- vaac.2's evidence-based judge engine as the adjudicator (later, swapped in
  behind the **same** verdict envelope — the whole point of the contract; its
  per-finding validity model is a natural fit for the merge-worthiness rubric).
- Oversized-diff chunking / in-sandbox diff gathering (MVP abstains and hands
  off on a too-large diff).
- A merge-rule boolean/expression engine (the field stays scalar-shaped for it).
