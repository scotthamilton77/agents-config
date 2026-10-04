# Criteria-attack rule ownership and record surface

**Date:** 2026-10-04
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
part of slice S2 (quality assessment).
**Work item:** `agents-config-9k9.405.13`, design child `agents-config-9k9.405.13.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D3, D5 and D7.

## Scope

Every rule of the acceptance-criteria standard gets exactly one owning lens.
Test suites pin what the criteria attack emits and what its record check
refuses.

A lens is one of the four reviewers the criteria attack runs over a document's
acceptance criteria. The standard is the `acceptance-criteria` skill, and each
of its rules carries an ID.

This spec serves seven parent criteria:

- ACQ-A20, ACQ-A22, ACQ-A26, ACQ-A28 and ACQ-A29, in full;
- ACQ-A23, apart from its clause on template additions;
- ACQ-A24, for one part: every rule has a lens that can object under it.

The rest of slice S2 belongs to the evaluation contract on
`agents-config-9k9.405.10`. That spec judges how well a lens catches a defect,
which needs repeated runs of a stochastic lens. The criteria here need none.
Deterministic suites check them, so this spec does not wait for the evaluation
contract.

## Current state

Verified at 7e7d8b1a.

- The standard holds seventeen rules.
- The four lenses live in `src/user/.claude/skills/ac-attack/lenses/`. Each
  lens's `prompt.md` front matter carries an `enforces` list. Together the four
  lists name eleven rules.
- Six rules are in no list: `restraint`, `verified-premise`,
  `human-measurement`, `human-judgment`, `pending-until-performed` and
  `stochastic-and-window`.
- The record check refuses an objection that cites a rule outside its lens's
  list, as `ground-outside-lens`. A lens therefore cannot report a defect
  under any of those six rules.
- No test fails when a rule of the standard has no owning lens.
- The emitter suite, `emit_prompts_test.py`, already pins prompt composition
  and refuses a lens that names a rule the standard lacks. The checker suite,
  `check_record_test.py`, already pins the `invalid-workings`,
  `unreported-residue` and `ground-outside-lens` refusals.

## Decisions

**ARO-D1 — Every rule has exactly one owning lens.** The lenses enforce these rules:

| Lens | Rules |
| --- | --- |
| behavioural-outcome | `observable-obligation`, `document-deliverable`, `one-obligation`, `verification-contract`, `human-measurement`, `human-judgment`, `pending-until-performed`, `stochastic-and-window` |
| obligation-reduction | `coverage`, `sufficiency`, `can-fail`, `has-basis`, `restraint` |
| set-consistency | `consistency`, `decision-closure`, `verified-premise` |
| what-if | `what-if-questions` |

A lens's `enforces` list names the rules it owns. The emitter puts exactly
those rules into the lens's prompt. The record check accepts an objection from
the lens only under those rules.

Six assignments are new, one for each rule that has no lens today:

- `human-measurement`, `human-judgment`, `pending-until-performed` and
  `stochastic-and-window` go to behavioural-outcome. They are verification
  rules, and ACQ-D6 gives behavioural-outcome checkability.
- `restraint` goes to obligation-reduction. A duplicate or an unsupported
  prescription discharges no obligation part of its own, and the
  obligation-reduction inventory shows that.
- `verified-premise` goes to set-consistency. A premise contradicted by
  evidence inside the document is a contradiction, and set-consistency reads
  for contradictions. No lens reads the repository, so evidence outside the
  document is not checked.

A rule with two owners is rejected. The evaluation contract scores each
rule's cases against one lens, and one owner per rule gives each case one
lens.

The cost falls on behavioural-outcome. Its prompt grows from four rules to
eight, and the effect on how well it catches each rule is not measured here.
This spec changes the `enforces` lists only. The lens bodies are revised, and
the catch rates measured, under the evaluation contract. An assignment is
reconsidered when that measurement shows its lens failing the rule's cases.

**ARO-D2 — The suites hold the attack surface while ownership changes.** The
emitter suite and the checker suite pin three things: how a prompt is
composed, which lenses run, and what the record check refuses.

Nine of the criteria below name tests that exist today: ARO-A3, ARO-A4,
ARO-A5, ARO-A8, ARO-A9, ARO-A10, ARO-A15, ARO-A16 and ARO-A17. They already
pass. They are preservation criteria, and they must still pass after the
`enforces` lists change. The slice adds a test for each other criterion that
a suite checks, where none exists. ARO-A18 is checked by the gate it names.

A correct registry does not show that an attack runs four lenses. Dispatch is
the invoking agent's act, which no suite observes. The suites can observe the
two ends of it: the round the emitter writes, and the record the check closes.
ARO-A12 and ARO-A13 pin those.

Checking the `enforces` lists alone is rejected. A list is configuration, and
a correct list does not show that the prompt a lens receives carries its
rules. ARO-A11 therefore checks the emitted prompt.

## Acceptance criteria

The emitter suite is `emit_prompts_test.py` and the checker suite is
`check_record_test.py`, both in `src/user/.claude/skills/ac-attack/`. Both run
under `make content-tests`.

- **ARO-A1** In the source tree, every rule ID the standard holds appears
  exactly once across the four lenses' `enforces` lists. The emitter suite
  fails, naming the rule, when a rule appears in no list or more than once,
  whether in two lenses' lists or twice in one.
- **ARO-A2** The emitter suite fails when the lens registry holds any set other
  than behavioural-outcome, obligation-reduction, set-consistency and what-if.
- **ARO-A3** Each emitted prompt equals its lens's body plus the four shared
  contracts, byte for byte, under the existing prompt-composition test.
- **ARO-A4** Each emitted prompt carries exactly the rules its lens enforces,
  under the existing prompt-composition test.
- **ARO-A5** A lens naming a rule the standard lacks is refused as `no-lenses`
  with nothing written, under the existing emitter test.
- **ARO-A6** The record check refuses as `schema` an objection that lacks, or
  leaves blank, its target, its ground's rule, or any scenario part. The
  target `none`, for an objection no criterion covers, is not blank.
- **ARO-A7** The record check refuses as `schema` an objection carrying a field
  outside the objection schema, such as a drafted criterion.
- **ARO-A8** The record check refuses an obligation-reduction report whose
  workings are missing or fail their schema, as `invalid-workings`.
- **ARO-A9** The record check refuses a report whose undischarged part has no
  objection naming it, as `unreported-residue`.
- **ARO-A10** The record check refuses a ground its lens does not enforce, as
  `ground-outside-lens`.
- **ARO-A11** The prompt emitted for each lens carries exactly the rules
  ARO-D1's table lists for that lens. The emitter suite fails, naming the
  lens, when the rules in a lens's prompt differ from its row.
- **ARO-A12** Given the source registry, the round the emitter writes names
  exactly the four lenses, and the emitter writes exactly one prompt for each.
- **ARO-A13** The record check reports a record as incomplete when any of the
  four lenses has no entry in it, naming the lens. A lens that reported
  `empty` has an entry.
- **ARO-A14** For each rule in ARO-D1's table, the record check reports no
  error on an otherwise complete record that carries a well-formed,
  adjudicated objection from the owning lens citing that rule.
- **ARO-A15** The emitter refuses an empty lens registry as `no-lenses` with
  nothing written, under the existing emitter test.
- **ARO-A16** The emitter refuses an absent standard as `no-standard` with
  nothing written, under the existing emitter test.
- **ARO-A17** Emitting twice from an unchanged tree and document writes
  byte-identical prompts, under the existing determinism test.
- **ARO-A18** With the `enforces` lists changed as ARO-D1 states, `make
  content-tests` exits 0, so no other content suite regresses.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A20 | ARO-A6, ARO-A7 | Checker suite |
| ACQ-A22 | ARO-A2, ARO-A12, ARO-A13 | Emitter suite, checker suite |
| ACQ-A23, apart from template additions | ARO-A3 | Emitter suite, existing test |
| ACQ-A24, an owning lens for every rule | ARO-A1, ARO-A11, ARO-A14 | Emitter suite, checker suite |
| ACQ-A26 | ARO-A4, ARO-A5, ARO-A15, ARO-A16, ARO-A17 | Emitter suite, existing tests |
| ACQ-A28 | ARO-A8, ARO-A9 | Checker suite, existing tests |
| ACQ-A29 | ARO-A10 | Checker suite, existing test |
| No regression in the other content suites | ARO-A18 | `make content-tests` |

### What-if questions

- A failure names what broke: the rule for ARO-A1, the lens for ARO-A11, and
  the refusal code for ARO-A5 to ARO-A10.
- An empty registry is ARO-A15, and an absent standard is ARO-A16. A blank
  field in an objection is ARO-A6.
- A rule added to the standard with no owner fails ARO-A1. A lens naming a
  rule the standard lacks is ARO-A5. A lens missing from a record is ARO-A13.
- The registry is the set of lens directories holding a `prompt.md`. A lens
  whose `prompt.md` is absent is therefore out of the registry, which fails
  ARO-A2.
- A lens whose `enforces` list is empty fails ARO-A11, because no row of the
  table is empty.
- A rule in two lists, or twice in one list, fails ARO-A1.
- Emitting again with nothing changed is ARO-A17. This slice changes the
  `enforces` lists and adds tests. It changes no code path that writes, so it
  adds no criterion on what a check leaves behind.

## Ordered slice list

- **S2.1: Rule ownership and the attack surface** (ARO-A1 to ARO-A18; ARO-D1,
  ARO-D2). Reassign `enforces` in `lenses/*/prompt.md`, and add the new tests
  to `emit_prompts_test.py` and `check_record_test.py`. Depends on the
  parent's S1, landed.

## Continuations

- feat: AC attack S2.1: rule ownership and the attack surface (ARO-D1, ARO-D2) — AC: ARO-A1, ARO-A2, ARO-A3, ARO-A4, ARO-A5, ARO-A6, ARO-A7, ARO-A8, ARO-A9, ARO-A10, ARO-A11, ARO-A12, ARO-A13, ARO-A14, ARO-A15, ARO-A16, ARO-A17, ARO-A18.

## Out of scope

- Revising a lens's body for the rules it gained, and measuring how well it
  catches them. The evaluation contract does both.
- An addition to the shared attack template, and the evidence ACQ-A23 requires
  of one.
- Evaluation cases, scoring and the judge.
- ACQ-A25, which the parent gives to its S1.
- A record that carries a report from a lens outside the registry. The record
  check keeps a retired lens's round closed, and this slice does not change
  that.
- Observing that each lens was dispatched. Dispatch is the invoking agent's
  act, and the record attests to it.
