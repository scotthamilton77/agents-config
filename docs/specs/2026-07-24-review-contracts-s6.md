# S6 — Review Contracts: Verdict Schema, Class-Specific Review, AC-Attack, Bot-Identity Invocation

**Date:** 2026-07-24
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S6 slice; implements D3/D7/D8/D9 and the bot-identity substrate of AC7)
**Tracker:** `agents-config-9k9.17`

The rework's review layer stops being prose machinery and becomes a set of
contracts: a typed verdict artifact, class-specific reviewer prompts that carry
only the artifact class and the ACs, a pre-implementation AC-attack round, and a
self-managed invocation that posts under a bot identity and fails merges closed
when the machinery is broken. S6 ships the **contracts, schemas, and
skill/prompt assets** only — the verdict harvester and merge-eligibility
evaluator are S8 code (D13). Every AC here is satisfiable by hand-invocation
now; where an AC needs machinery only S8 provides, it names the handoff.

The mechanism is not hypothetical: the cross-model review loop was run for real
during S5 (PRs #377–#383) with the local codex CLI. S6 encodes what that run
proved — including two hard-won failure modes (stale checkout → phantom
findings; under-declared retained categories → over-reporting) — as contract
requirements, not lore.

---

## 1. Inventory (audited 2026-07-24)

| Artifact | State | Facts |
| --- | --- | --- |
| Cross-model reviewer | working, unpackaged | The local codex CLI is the live foreign reviewer (GitHub codex auto-reviews are off since 2026-07-24 — request-only). Invoked `node "$CODEX_HOME/scripts/codex-companion.mjs" task --model gpt-5.6-terra --json < prompt.md`, `CODEX_HOME=${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex}`, read-only sandbox, run in background (minutes). Proven prompt shape and exact-JSON completion contract exist as tribal practice, in no deployed asset. |
| Verdict artifact schema | nowhere | No schema, no file convention, no notion of "a complete round" keyed to a head SHA. The S5 loop carried the shape in-context only. |
| Class-specific review contracts | nowhere | No typed-code / spec / skill-prose split; no reviewer prompt asset. Reviewers were prompted ad hoc. |
| AC-attack round (D3) | nowhere | No pre-implementation attack asset. The S5 spec-contract slice explicitly deferred this to S6. |
| Bot identity / merge-guard | working | The merge-guard + GitHub App approver machinery exists and is proven on this repo: an App approval counts toward required reviews when the App holds `contents:write` (not merely `pull_requests:write`). Auto-merge additionally needs `MERGE_GUARD_APPROVER_KEY_PATH` set. The plumbing exists; no verdict rides it yet. |
| prgroom | carved target (S8) | Retains `gh`/`git` clients, config, error taxonomy, escalation typing. The **verdict harvester** and **merge-eligibility evaluation** are S8 deliverables (D13), not built here. `wait-for-pr-comments`, `reply-and-resolve-pr-threads`, `monitor-pr` remain deployed until S8 deletes them (AC5). |
| completion-gate / quality-gate skills | deployed, contradictory | House-rulebook review text that D8 supersedes as a review *medium*. S6 does not delete them (that is teardown scope elsewhere); it defines the replacement contract they will route into. |

## 2. Decisions

**Verdict artifact — a typed JSON file keyed to a head SHA.**
A review round emits a JSON object conforming to a shipped JSON Schema:
`{"schema_version", "artifact_class", "round", "base_sha", "head_sha",
"retained_categories":[…], "verdict":"clean"|"findings", "findings":[…]}`.
Each finding is `{"type":"mechanical"|"advisory", "ac", "claim", "evidence"}`.
`evidence` is **mandatory** for `mechanical` findings (a failing test, lint
output, or a broken link) and optional for `advisory`. The artifact lives at a
deterministic path in the PR branch so the merge gate reads it as a file — PR
comments are not a review medium (D9). It records the `head_sha` it was produced
against; a verdict whose `head_sha` ≠ the current PR head is **stale** and the
gate treats it as absent.

**"A complete round" is mechanically defined.** A round is complete iff
(a) it declares a `base_sha` and the checkout was synced to that base before
invocation — the phantom-finding guard (a stale checkout produced 12 phantom
findings in one S5 round); (b) it declares every deliberately-retained category
up front in `retained_categories` — the over-reporting guard (an under-declared
retained set inflated an S5 round); and (c) it emits a schema-valid verdict for
the current `head_sha`. **Review terminates clean** when a complete round
produces zero `mechanical` findings. Advisory findings route to the backlog,
never block, and are never re-litigated in the fix loop (D8).

**Reviewer prompts carry the contract, never the house rulebook (D7).**
Each class-specific prompt carries only: the artifact class, the diff's ACs to
judge against, a pointer to the diff file (under `/tmp`) plus the repo root for
surrounding context, the declared `retained_categories`, and the exact-JSON
completion contract. It carries no laws, decision matrix, or in-repo
intentionality claims. Reviewers are instructed to **ignore intentionality
claims** in the code/docs under review — a "this is intentional" comment is not
evidence; verdicts judge against ACs and mechanical artifacts only.

**Three artifact classes, one review skill.** Classes: **typed code**,
**spec**, **skill/config prose**. One review skill carries all three contracts
(selected by class) rather than three near-duplicate skills. Placement is
Claude-tree (`src/user/.claude/skills/`): invocation depends on the
codex-companion CLI shipped by the Claude codex plugin and on the Skill
machinery. The **verdict schema** is portable data and ships as a shared
asset under `src/user/.agents/` so both the skill and the S8 harvester consume
one source of truth.

**Re-review triggers only on a claimed-fix push (D7).** A push with no
readiness/fix claim triggers no round. A re-invocation after a claimed fix
carries a round-N preamble listing every prior finding and its disposition
(fixed-with-regression-test / rebutted / advisory-deferred), so the reviewer
does not re-raise settled items.

**AC-attack is a pre-implementation round on the spec (D3).** A foreign
(non-Anthropic) model attacks the spec's AC set — "name behaviors that satisfy
these ACs while still being wrong." Output is a JSON array of **proposed ACs**,
each `{"target_ac", "hole", "proposed_ac", "red_test_sketch"}` — testable claims
about inputs/states, never free-form concerns. Each proposal is adjudicated
**accepted** (into the AC set) or **rejected** (out-of-scope); the round
terminates only when every proposal has a disposition. This is distinct from and
runs before the PR verdict.

**Verdicts ride the existing bot identity; the gate fails closed (D9).**
All machine-posted PR comments and approvals use the GitHub App identity, never
the human's auth, reusing the proven merge-guard/App-approver plumbing (the App
must hold `contents:write` for its approval to count). Merge eligibility =
CI green + a terminal-clean verdict keyed to the current `head_sha` + App
approval. A missing, stale, non-terminal, or unparseable verdict **blocks** the
merge — broken review machinery never silently passes. A human PR comment is by
definition an intervention: it routes to escalation, never into the fix loop.
The gate's *evaluation code* is S8 (D13); S6 fixes the contract it evaluates.

**Every deployed asset reads standalone.** The verdict schema, the
review skill, the AC-attack skill, and the invocation/trigger doc are written to
be read with zero planning jargon — no charter/slice/decision/AC IDs in their
bodies. Slice and decision IDs live here, in commits, and in the tracker only.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible; IDs are cited by the implementing tests and
PRs. The edge-case taxonomy (inverse, empty/boundary, dependency failure,
repeated/concurrent invocation, idempotency) is applied per slice. Ordering: A
first (B and D consume the schema); B, C, D may then run in parallel.

### Slice A — Verdict artifact schema (D8)

- **S6-A1** A JSON Schema file ships as a shared asset under
  `src/user/.agents/` defining the verdict envelope (typed JSON keyed to a head
  SHA); a document with a
  `mechanical` finding and no `evidence` fails validation, while the same
  finding as `advisory` validates (evidence-mandatory-for-mechanical boundary).
- **S6-A2** A verdict records the `head_sha` it was produced against; the
  merge-eligibility check treats a verdict whose `head_sha` ≠ the current PR
  head as absent (stale-verdict guard). Satisfiable by hand-comparison now;
  names the S8 merge-eligibility-evaluation handoff for the automated check.
- **S6-A3** A round declaring a `base_sha` that differs from the diff's actual
  base is rejected as an **incomplete** round (the phantom-finding guard); a round
  whose declared base matches is accepted
  (inverse pair).
- **S6-A4** Terminal-clean is defined as a complete round with zero
  `type:"mechanical"` findings; a verdict carrying only `advisory` findings
  still reads terminal-clean (advisory never blocks, D8) — and a `verdict:
  "findings"` object with an empty `findings` array fails validation
  (internal-consistency boundary).
- **S6-A5** The schema file and its inline documentation contain no
  charter/slice/decision/AC jargon (`grep` for `D[0-9]`, `S6-`, `AC[0-9]`
  returns zero hits in the deployed asset) — the standalone-read requirement.
- **S6-A6** Validating the same verdict JSON twice returns the identical result
  (idempotency), and a malformed / non-JSON artifact yields a typed validation
  error rather than a crash (dependency-failure input).

### Slice B — Class-specific review contracts (D7)

- **S6-B1** A review skill under `src/user/.claude/skills/` carries three class
  contracts (typed code / spec / skill-config prose); for a given class the
  emitted reviewer prompt contains the artifact class, the diff's ACs, the
  `/tmp` diff-file pointer plus repo root, the declared `retained_categories`,
  and the exact-JSON completion contract — and contains no laws/decision-matrix
  text (`grep` guard on the emitted prompt).
- **S6-B2** The emitted prompt declares all deliberately-retained categories up
  front; a contract invocation with an empty/absent retained-category
  declaration is refused (the over-reporting guard) rather than run.
- **S6-B3** The reviewer instruction directs ignoring in-repo intentionality
  claims: a finding stands on ACs + mechanical evidence even when the code under
  review carries a "this is intentional" comment (inverse — the comment does not
  suppress the finding).
- **S6-B4** A push with no readiness/fix claim triggers no review round
  (inverse of "every push reviews"); a re-invocation after a claimed fix carries
  a round-N preamble enumerating prior findings and their dispositions.
- **S6-B5** The skill encodes the checkout-sync precondition: if the working
  tree's base ≠ the diff's declared base it emits an **incomplete** round (or
  refuses) rather than producing findings against a stale tree (dependency
  failure; the S5 phantom-finding lesson).
- **S6-B6** The review skill body passes `surface_budget.skill_body_violations`
  (≤ 2k tokens) and contains no charter/slice/AC jargon (standalone read).

### Slice C — AC-attack contract (D3)

- **S6-C1** An AC-attack skill under `src/user/.claude/skills/` emits a prompt
  carrying the spec's AC set, the "name behaviors that satisfy these ACs while
  still being wrong" mandate, and the proposed-AC output contract — and no house
  rulebook.
- **S6-C2** Output is proposed ACs (each a testable input/state claim with a
  `red_test_sketch`); a returned item shaped as a free-form concern — no
  testable claim — is rejected as malformed (inverse: a concern is not a valid
  finding).
- **S6-C3** Every proposal is adjudicated `accepted` (into the AC set) or
  `rejected` (out-of-scope); an un-adjudicated proposal blocks round termination
  — the round terminates only when the disposition set covers every proposal
  (repeated-invocation-safe: re-running over a fully-adjudicated set is a no-op).
- **S6-C4** The round runs pre-implementation against the spec artifact and is
  distinct from the S6-A/S6-B PR verdict; an empty proposal list (the attacker
  finds no hole) terminates the round clean (empty-input boundary).
- **S6-C5** The AC-attack skill body is ≤ 2k tokens and reads standalone — no
  charter/slice/AC jargon in the deployed asset (standalone read).

### Slice D — Self-managed invocation + bot identity (D7, D9, AC7)

- **S6-D1** The review trigger fires on an explicit readiness claim, never on
  every push; the trigger contract ships as a deployed asset that reads
  standalone. A push absent a readiness claim fires nothing (inverse).
- **S6-D2** Machine-posted PR comments and approvals carry the GitHub App
  identity; a verdict-driven approval is attributable to the App, never the
  human auth, and counts toward required reviews only when the App holds
  `contents:write` (carried from proven repo behavior, reusing the merge-guard /
  App-approver plumbing — not rebuilt here).
- **S6-D3** Merge eligibility requires CI green + a terminal-clean verdict keyed
  to the current `head_sha` (Slice A) + App approval; a missing, stale, or
  non-terminal verdict blocks the merge (fail-closed). Satisfiable by
  hand-verification now; names the S8 merge-eligibility-evaluation handoff.
- **S6-D4** A human PR comment is treated as an intervention → escalation, and
  is never fed into the fix loop (D9); machine (App) and human comments are
  separable on the PR, which is the substrate the S10 interventions-per-PR
  instrument reads (the number itself is S10, not S6).
- **S6-D5** Broken review machinery — reviewer error, no verdict emitted, or an
  unparseable verdict — blocks the merge rather than passing silently
  (fail-closed; dependency-failure case).

## 4. Out of scope

The **verdict harvester** and **merge-eligibility evaluation** code (S8, D13) —
S6 ships the schema, prompts, and skill assets and defines what the gate must
check; every gate-shaped AC above is hand-satisfiable now and names the S8
handoff. The **scaffold-review contract** (S7, D4/D5). **Park semantics and the
staleness report** (S9 / shipped-S2, D10) — S6 only defines the merge-eligibility
inputs a parked item keys off, never park state itself. Deletion of
`wait-for-pr-comments` / `reply-and-resolve-pr-threads` / `monitor-pr` and the
contradictory completion-gate text (S8, D13/AC5). The **interventions-per-PR
number** and **pre-PR cycle-time** instruments (S10, D19) — S6 lands only the
bot-identity substrate that makes the interventions count separable. Building the
codex-companion CLI or the App/merge-guard plumbing (both pre-exist). Wiring the
same review contracts onto foreign harnesses beyond the Claude tree (pipeline
work; the portable verdict schema is the seam that keeps that door open).
