# Review-panel iteration strategy

**Date:** 2026-08-20 · **Status:** settled design, implementation not started
**Drives:** `agents-config-9k9.17.9` (cost-driver reassessment, PANEL-A1–A4), `agents-config-9k9.17.16` (iteration-strategy reassessment, PANEL-B1–B9), with upstream companion `agents-config-9k9.229`.
**Evidence base:** PRs #402/#403 (first two campaigns) and #556/#557 (9k9.215 campaigns, per-lens convergence data). Settled in a grilling session; the tracker items carry the observation detail.

## 1. Goals

1. **Efficient and comprehensive** detection of quality issues across work shapes, including mixed targets (e.g. a skill combining prose and scripts).
2. **No compensation for missing mechanical verification.** The panel assumes acceptance criteria were turned into mechanical tests upstream and that those tests passed. It checks for *evidence* of that and bounces targets that lack it; it never re-derives it.
3. **Minimum force, including zero.** Force is minimized against expected total cost — tokens spent plus escaped-defect interventions — not tokens alone. A zero-force verdict is legitimate only when the residual surface is genuinely empty, and is always recorded with its justification, never silent.

What is not broken survives: adversarial multi-model review stays; the settled-items ledger stays (zero rebutted findings were ever re-filed) and extends to rebutted design-decision attacks.

## 2. Root causes of the four observed cost drivers (PANEL-A1)

| Cost driver (observed) | Root cause | Change class |
|---|---|---|
| Typo-class findings block at the same weight as self-contradictions (#402) | Severity is a flat mechanical/advisory binary with no class carve-out; cosmetic defects have no cheaper route than a frontier lens seat | Panel scope (preconditions absorb the mechanical pre-pass; profiles set force ceilings) + lens instruction text (cosmetic findings excluded from mandates) |
| Prose artifacts accrete under fixing; same defect class re-minted on newly written text (#402: 388→500 lines) | The fix side is entirely ungoverned — the contract instructs reviewers only, so fixes layer qualifiers onto wrong text instead of replacing it | Panel scope: the contract extends to a fix-dispatch contract (§6) |
| One lens consumed a round with unbounded output (13/20 round-1 findings from test-adequacy, #403) | Lens mandates lack stopping conditions; a lens that can always produce output always will | Lens instruction text: every mandate states what makes an instance worth reporting (PANEL-A4) |
| Termination read count while severity rose; deepest defect surfaced last (#403: 20→7→5 with rising severity) | No termination contract exists at all — no deployed round cap, no severity reading; every campaign ended by improvised human ruling | Panel scope: trend-analyst termination + terminal sweep (§7, §5) |

## 3. Precondition gate

Emission refuses a target that lacks recorded evidence that its profile's declared mechanical gates ran green at the head SHA under review, naming the missing gate. Evidence bound to a stale head refuses as stale. The refusal verb is **bounce upstream** — the panel does not review around the gap, and it does not judge whether the upstream gates were the right ones.

"Mechanical gates" is per-profile, not one rule: an AC-derived test gate for typed code, doc-lint plus an ac-attack-surviving criteria artifact for specs and docs, nothing at all for a profile that declares zero preconditions. A profile with an empty precondition set passes on empty evidence.

Producing this evidence is upstream's obligation, encoded as default de-facto ACs on the planning and implementation phases (`agents-config-9k9.229`): criteria red-test-convertible and ac-attack-survived before implementation; profile named at planning time; gate evidence recorded at the delivered head; scope boundaries stated in the claim. Deploy order matters: the gate is not enforced on real campaigns before that encoding lands, or every legitimate target bounces.

## 4. Classes, profiles, and staffing

**Classes stay coarse** — typed-code, spec, prose — because a class is heavy: its own lens roster, its own round per mixed target, its own verdict. Sub-type sensitivity lives in a **profile table** the staffing step reads: one row per artifact type carrying default staffing, force ceiling, and precondition set. Minimum rows: prototype (zero-force default, no preconditions), changelog (mechanical-only), agent-instruction prose (skills, rules, CLAUDE.md — mandates derived from the writing-skills discipline rather than freshly minted lens text), spec, general docs. An unlisted type picks the nearest profile explicitly and records the choice — never an improvised lens set. A new sub-type is a row edit, not a design event. Splitting the panel into per-shape skills instead moves classification upstream to an invoker with less information, multiplies deployed surface, and duplicates the round/verdict machinery that must stay identical — the mixed-target case (one round per class over a partitioned target) is the argument for one skill, and it is already the incumbent architecture.

**Staffing is a first-class, per-round recorded artifact**: a foreign mid-tier model recommends which of the class's lenses actually apply to this target, with rationale; interactive sessions float the recommendation to the user, non-interactive runs record it and proceed. Staffing is **subtract-only** — the class roster is the ceiling. The verdict references the staffing record, and verdict completeness is validated against it rather than the class table, so a silently dropped seat still fails validation. A zero-lens decision with justification is itself the terminal record; no verdict exists for it.

**Embedded prose** (comments, docstrings — the most persistent defect class on #557, reviewed like code while rotting like prose) is a lens duty, not a fourth class: the typed-code documentation-quality mandate explicitly owns narration, drift, and history-vs-decision rot, with a stopping condition under which each finding names the misreading the comment causes. A merely brief comment is not a finding. The fix-side narration clause (§6) attacks the same class from the other flank.

## 5. Round lifecycle

1. **Round 1 — whole artifact**, staffed per the staffing decision. A clean, complete full round 1 is terminal directly: it is already a whole-artifact clean read by a superset of the sweep seats.
2. **Rounds ≥2 — delta-scoped by default.** Each surviving lens reads only the change since the head it last judged, plus the disposition ledger. Staffing is re-evaluated every round from the finding trend and the nature of the fixes; lenses that went clean drop. A newly re-staffed lens (no prior head) reads full. The staffing record can force a full rescope — the **accretion trigger**: fixes since the last full read have grown beyond trivial, or a finding shows an original assumption was wrong.
3. **Terminal sweep — exactly one whole-artifact pass** before terminal-clean is declared on any campaign that reached its zero-blocking round through deltas. Unconditional by contract, not triggered by a detector: the exit door has one full re-read built into the frame, because the late finds on both evidence campaigns (#403 round 3, #557 round 6 on code unchanged since round 1) are invisible to delta scoping by construction. Staffed by the class's frontier-tier seats only, framed blocking-only ("confirm no blocking defect exists" — a verdict, not a findings hunt), ledger loaded. Sweep findings re-enter the normal fix → delta-verify loop; no second sweep follows unless the accretion trigger re-arms it.

Per-round full re-reads as the default instead are what produced the churn: constant re-litigation surface, and exhausted seats turning findings-generator (#557's security seat, silent four rounds, then a burst of rebutted design attacks).

## 6. Fix-dispatch contract

A findings round emits a fix dispatch alongside its verdict. The review contract and the fix contract are one loop with one economics — the evidence shows the fixer driving the accretion spiral (three of four narration-class recurrences on #557 were written *during* fix passes), and the one lens whose findings decayed to zero and stayed there was the one whose fixes carried mutation evidence. Four clauses:

1. **Smallest net change** that achieves the fix with quality — no over-explaining, no unnecessary code, no pointless prose.
2. **Mutation evidence for code fixes** — the test fails without the fix. In the ledger, `fixed` on a typed-code mechanical finding requires non-blank evidence, exactly as `rebutted` already does.
3. **Replacement-first for prose** — prefer replacing incorrect text over adding qualifying text; a fix that grows the artifact states why replacement couldn't achieve it. Non-trivial net growth in a fix round re-staffs the consistency lens next round, diff-scoped over the new text: growth is paid for with reading, not forbidden. A hard no-net-growth rule forbids the correct fix for any gap finding and invites clarity-destroying compression; a numeric growth budget has the wrong shape — one legitimate section busts it while five scattered qualifiers sneak under it.
4. **Narration sweep** — no transition commentary minted under review pressure ("as before", "has ever claimed"); prose states the current decision, not the fix's history.

## 7. Dispositions, blame, and termination

**Blame split at round assembly.** The assembler (not a new seat — the split is git-blame-assisted and the assembler already touches every finding) attributes each finding: PR-induced or missed-in-scope stays in the campaign; pre-existing and non-blocking transfers out. The disposition set gains **`transferred`**, valid only with a pre-existing blame attribution and a filed work-item id as evidence, carried to re-reviews through the settled-items channel as out-of-scope-accounted. A pre-existing *blocking* finding is not transferable. Blame truth itself is judgment; the recorded attribution is what stays mechanical and auditable.

**The bent ruler halts.** A finding that indicts the acceptance criteria or requirements themselves — as opposed to pre-existing artifact content — produces a halted verdict with an upstream-defect halt reason, never another round: every further round would measure against a ruler known to be bent. The review resumes only after the upstream artifact is fixed. This is the concrete mechanism for "re-review in aggregate when original assumptions were incorrect."

**Fixer decisions are accepted within rounds.** No lens re-litigates a settled item; rebutted design-decision attacks enter the settled ledger like any rebuttal. Blocking-severity rebuttals accumulate into the terminal verdict for the human ruling.

**Termination has no numeric round cap.** A count cap reads the wrong signal — the observed campaigns fell 20→7→5 in count while severity rose. Termination is: terminal-clean (§5), or a **trend-analyst verdict**. After round 2, and after every 2 further non-clean rounds, a Fable-high trend-analysis dispatch reads the campaign — finding trends per lens, fix history, severity direction — and answers whether the findings indicate an upstream problem (missing/ambiguous ACs, design flaw) or a lens that is bikeshedding. Its recorded verdict is one of: **(a) continue two more rounds**, carrying staffing advice the next staffing decision consumes (a bikeshedding lens is de-staffed); **(b) terminate and bounce upstream** for remediation; **(c) terminate and escalate to the human**. Severity rising while count falls reads as non-convergence, never as progress. Analyst dispatch failure resolves as (c) — the machine fails toward the human, never toward silent continuation. The analyst is the covert-case complement to the bent-ruler halt, which fires in-round when a single finding overtly indicts the upstream artifact. This is a standing Fable-high spend, bounded to campaigns that have already burned two rounds without cleaning; it is the deliberate top-tier-for-judgment seat.

## 8. Acceptance criteria

PANEL-A1–A4 stand on `agents-config-9k9.17.9` (A1 is satisfied by §2; A3's termination rule is the §7 analyst — one mechanism, not two). PANEL-B1–B9 are recorded as acceptance on `agents-config-9k9.17.16` via `work acceptance set`, one criterion per contract surface above: B1 precondition gate (§3), B2 staffing artifact (§4), B3 delta default (§5), B4 terminal sweep (§5), B5 fix dispatch (§6), B6 transferred + halt (§7), B7 trend analyst (§7), B8 profile table (§4), B9 embedded-prose duty (§4).

## 9. Implementation notes and deliberate deferrals

- **Verdict envelope changes** (shared `review-verdict` skill — wider blast radius than the Claude-only panel): a staffing-record reference, the `transferred` disposition, the upstream-defect halt reason, and evidence required on `fixed` for typed-code mechanical findings. Completeness condition 4 reads the staffing record instead of the class table. The envelope currently stores no per-lens counts; the trend analyst reads across retained per-round verdicts rather than requiring a trend field in the schema.
- **Lens text is gated code**, not prose files: mandates live in `src/user/.claude/skills/review-panel/contracts.json` and boilerplate in `src/user/.claude/skills/review-panel/emit_prompts.py`, both under paired test suites. `src/user/.claude/skills/review-panel/SKILL.md` sits at 1984/2000 tokens against the hard per-skill cap — measure on current main before budgeting any prose there; substance lands in the contracts file and scripts.
- **No size gate.** An oversized multi-concern PR is an upstream failure; partition machinery inside the review would compensate for it, and no volume-induced panel failure has been observed. Deferred until one is — that observation is the admission record for a preflight bound whose verb is the same bounce as §3.
- **Interactive grilling surface** for staffing float-by and session UX is separate work (`agents-config-9k9.221`).
