# Acceptance-criteria brief fidelity and evidence mapping

**Date:** 2026-09-29
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
slice S3 (brief fidelity and evidence). Not yet attacked.
**Work item:** `agents-config-9k9.405.11` (S3 feature), design child `agents-config-9k9.405.11.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`, LIFE-D1 (rendering).
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D1, D2 and D4.

## Scope

S3 owns ACQ-A12 and ACQ-A13. A dispatch brief must carry exactly the criteria
assigned to the work, refuse when it cannot, and map each criterion to its
planned check apart from the criterion's text. A criterion without a feasible
planned check is reported unready. The parent's Testing decisions require the
check at the consumer boundary, which is the generated brief itself.

## Current state

Verified at 38bda4ba.

- The briefing skill is `src/user/.agents/skills/instructing-subagents/SKILL.md`.
  It is prose only. Its skeleton shows criteria as bare `- <condition>` lines
  with no IDs, and nothing maps a criterion to its evidence.
- A brief writer copies criteria by hand, which is where rewording and
  omission happen. Nothing checks a brief against its source.
- `work acceptance` offers `set` and `history`. The `render` verb of LIFE-D1
  belongs to `agents-config-9k9.405.4`, which is open.
- spec-lint reads a criterion as a `- **ID** text` entry under an
  acceptance-criteria heading, with wrapped continuation lines joined by single
  spaces (`packages/installer/src/installer/core/spec_lint.py`).
- The installer prunes every `evals/` directory (`.installignore`).

## Decisions

**BRF-D1 — A helper emits the criteria and evidence sections.** The skill ships
`brief_criteria.py` beside its `SKILL.md`. It uses the standard library only,
so it runs under `uv run` or `python3` on every supported tool. Its `emit`
mode prints two Markdown sections: the assigned criteria as `- **ID** text`
entries, then an evidence section mapping each ID to its planned check. The
writer pastes both sections into the brief unchanged. Its `check` mode compares
a written brief with the source. Retyping criteria is where a brief drifts, so
fidelity moves into code the writer runs and the evaluation can score.

**BRF-D2 — Three sources, one grammar.** `--spec PATH --ids ID,...` reads the
named entries from a spec's acceptance-criteria sections. `--criteria FILE`
reads a file holding only entries, for criteria authored for one brief.
`--item ID` reads a work item's criteria (BRF-D7). Spec and file entries follow
spec-lint's entry grammar, joined text included. The helper's parser is a
marked counterpart of spec-lint's, as LIFE-D1 already binds workcli's. One
fixture in the skill's `evals/`, a Markdown spec with its expected readings,
is read by both suites, so the two readings cannot drift apart unseen.

**BRF-D3 — Fidelity is the set of IDs and their words.** A brief preserves its
criteria when its criteria section holds exactly the assigned IDs, and each ID's
text equals its source text after runs of whitespace collapse to one space. A
rewrap changes no word. A changed word, a dropped or added ID, or a changed ID
is a different contract. Order is not compared, since no criterion depends on
its position.

**BRF-D4 — A refusal replaces the brief.** To refuse, `emit` prints nothing on
stdout and one JSON object on stderr naming each fault, and exits 2. Nothing
pasteable exists, so no brief with an invented contract can follow. The codes:

- `no-criteria`: no criterion is assigned;
- `unretrievable`: an assigned ID is absent from its spec, naming the ID;
- `unreadable-source`: the spec, criteria file or brief is missing or
  unreadable, naming the path and every assigned ID;
- `duplicate-id`: an ID is assigned twice, or its source defines it twice;
- `malformed-criteria`: a criteria file holds a nonblank line outside an entry,
  naming the line;
- `malformed-checks`: the checks file is not a JSON object of the BRF-D5 shape;
- `render-failed`: an item's rendering fails, naming the item and the cause.

The skill tells the writer to relay a refusal to its requester and dispatch
nothing.

**BRF-D5 — A planned check is an observation and a pass rule.** `--checks FILE`
is a JSON object mapping an ID to `{"observe": …, "pass": …}`. The evidence
section gives each assigned ID its observation and pass rule, or marks it
`unready` with the reason. A criterion is unready when the file has no entry
for it or either field is blank. Without `--checks`, every criterion is
unready. When any criterion is unready, `emit` still prints both sections,
names each unready ID on stderr, and exits 1. Whether a stated check is
feasible is the writer's judgment, which code cannot make. The evaluation
measures it (BRF-D8), and the skill tells the writer not to dispatch a brief
with an unready criterion.

**BRF-D6 — The skill routes the writer through the helper.** S3.4 rewrites the
skill's acceptance-criteria part and skeleton. Criteria and evidence come from
`emit`, pasted unchanged, and `check` runs before dispatch. A refusal or an
unready criterion is reported to the requester. LIFE-A32's sentence on
re-attack before use belongs to lifecycle S6 (`agents-config-9k9.405.9`), so
this slice leaves it alone. Content-lint's token caps apply.

**BRF-D7 — Item criteria come only from the facade renderer.** `--item` runs
`work acceptance render ID` and reads its acceptance-criteria section. It never
resolves an item's acceptance field itself, since that would be a third
resolver of LIFE-D1. Until `agents-config-9k9.405.4` ships the verb, `--item`
refuses as `render-failed`, naming the missing verb.

**BRF-D8 — The generated-brief evaluation.** The writer is Claude Opus through
the native Agent tool, given the skill from the source tree by full path. For
each fixture it briefs a subagent for a fixed task and returns the brief or a
refusal instead of dispatching. Each fixture runs five times in fresh
contexts, so one evaluation plans 35 dispatches plus repeats. The run record
names the writer's resolved model ID. Fixtures live in the skill's `evals/`:

| Fixture | Assignment | A run passes when |
| --- | --- | --- |
| F1 | three spec criteria, one wrapped over several lines and one quoting code, each with a planned check | preservation: `check` accepts the brief; evidence: its evidence section maps every ID |
| F2 | three criteria in a criteria file, each with a planned check | as F1 |
| F3 | no criterion assigned | the output holds no criteria section and names `no-criteria` |
| F4 | one assigned ID the spec lacks | the output holds no criteria section and names the ID |
| F5 | an unreadable spec path | the output holds no criteria section and names every assigned ID |
| F6 | three criteria, one whose pass rule is "a reviewer confirms it reads well" | the output names that ID as unready |
| F7 | three criteria and no planned checks | the output names every ID as unready |

`evals/score_briefs.py` scores the outputs mechanically, and scores F1's and
F2's two halves separately. A run with no output is repeated at most twice,
then left pending and never scored as failed. F1 to F5 and F7 pass at five
runs of five. The helper decides those outputs, so any failed run is a
pasted-wrong or invented contract. F6 passes at four of five, because only the
writer's judgment can find that check infeasible. A record run is committed
under `evals/runs/<run-id>/` with its outputs and report, whatever it shows.
That rests on the operator. Changing a run count or threshold amends this spec.

**BRF-D9 — Verification ownership.** S3.5 is the verification child for ACQ-A12
and ACQ-A13, as ACQ-D2 requires. The helper suites establish the mechanism.
Only the evaluation of record establishes the parents at the generated brief.

## Acceptance criteria

"Refuses as X" means the BRF-D4 refusal carrying code X. "The evaluation of
record" is the latest complete record run under BRF-D8. The helper suite runs
under `make content-tests` and spec-lint's under `make ci`.

- **BRF-A1** Given a spec and assigned IDs, `emit`'s criteria section holds
  exactly the assigned IDs, each with its entry's full text, continuation
  lines included.
- **BRF-A2** Given a criteria file, `emit`'s criteria section holds exactly the
  file's entries.
- **BRF-A3** `emit` refuses as `no-criteria` given an empty ID list or a
  criteria file holding no entry.
- **BRF-A4** `emit` refuses as `unretrievable`, naming the ID, when an assigned
  ID has no entry in its spec.
- **BRF-A5** `emit` refuses as `unreadable-source`, naming the path and every
  assigned ID, when the spec or criteria file is missing or unreadable.
- **BRF-A6** `emit` refuses as `duplicate-id`, naming the ID, when an ID is
  assigned twice or defined twice in its source.
- **BRF-A7** `emit` refuses as `malformed-criteria`, naming the line, when a
  criteria file holds a nonblank line outside an entry.
- **BRF-A8** `check` exits 0 when a brief preserves its assigned criteria under
  BRF-D3, and otherwise exits 1 naming each missing, added or altered ID. It
  refuses as `emit` would when its source fails, and as `unreadable-source`
  when the brief cannot be read.
- **BRF-A9** The helper suite and spec-lint's suite each read the shared
  grammar fixture, and each fails when its reading of an entry departs from
  the fixture's expected text. The helper's test skips where the repository's
  copy of the fixture is absent.
- **BRF-A10** Given planned checks for every assigned criterion, `emit` prints
  an evidence section giving each ID its observation and pass rule, exits 0,
  and prints the same criteria section it prints without checks.
- **BRF-A11** A criterion with no planned check, or whose planned check has a
  blank field, is marked `unready` in the evidence section and named on stderr, and `emit`
  exits 1. Without `--checks`, every criterion is unready.
- **BRF-A12** `emit` refuses as `malformed-checks` when the checks file is not a
  JSON object of the BRF-D5 shape.
- **BRF-A13** Given a stub facade whose render prints criteria, `emit --item`'s
  criteria section holds exactly the rendered criteria.
- **BRF-A14** `emit --item` refuses as `render-failed`, naming the item and the
  cause, when the facade lacks the render verb or the rendering fails.
- **BRF-A15** `emit --item` refuses as `no-criteria` when the rendering holds no
  criterion.
- **BRF-A16** F1 and F2 pass on preservation in the evaluation of record.
- **BRF-A17** F1 and F2 pass on evidence mapping in the evaluation of record.
- **BRF-A18** F3 passes in the evaluation of record.
- **BRF-A19** F4 and F5 pass in the evaluation of record.
- **BRF-A20** F6 and F7 pass in the evaluation of record.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A12, preservation | BRF-A1, BRF-A2, BRF-A8, BRF-A9, BRF-A13, BRF-A16 | Helper suite, spec-lint suite, the scorer's report |
| ACQ-A12, zero criteria | BRF-A3, BRF-A15, BRF-A18 | Helper suite, the scorer's report |
| ACQ-A12, unretrievable criterion | BRF-A4, BRF-A5, BRF-A6, BRF-A7, BRF-A14, BRF-A19 | Helper suite, the scorer's report |
| ACQ-A13, evidence apart from text | BRF-A10, BRF-A17 | Helper suite, the scorer's report |
| ACQ-A13, unready criterion | BRF-A11, BRF-A12, BRF-A20 | Helper suite, the scorer's report |

### What-if questions

The refusal criteria BRF-A3 to BRF-A7, BRF-A12, BRF-A14 and BRF-A15 are the
failure and missing-input answers for `emit`. Empty is BRF-A3, BRF-A11's
missing `--checks`, and BRF-A15. `emit` and `check` read and never
write, so running either twice or with nothing changed prints the same result,
and concurrent runs share nothing. A limit does not apply, since neither mode
bounds how many criteria it carries. For BRF-A16 to BRF-A20, a failure names
the fixture, a missing output leaves the run pending rather than failed, and
each fixture is fixed, so empty applies only where F3 and F7 test it.

## Ordered slice list

- **S3.1: The helper's sources, refusals and check** (BRF-A1 to BRF-A9;
  BRF-D1 to BRF-D4). `brief_criteria.py`, `brief_criteria_test.py` and
  the grammar fixture in `src/user/.agents/skills/instructing-subagents/`,
  and the fixture test in `packages/installer/tests/unit/test_spec_lint.py`.
  Depends on S1, landed.
- **S3.2: The evidence map** (BRF-A10 to BRF-A12; BRF-D5). The `--checks` path
  of the helper and its tests. Depends on S3.1.
- **S3.3: Item criteria** (BRF-A13 to BRF-A15; BRF-D7). The `--item` path, tested
  against a stub facade. Depends on S3.1. Its live use waits on
  `agents-config-9k9.405.4`, and S3.5 does not wait on it.
- **S3.4: The skill** (BRF-D6). The acceptance-criteria part and skeleton of
  `SKILL.md`. Depends on S3.2.
- **S3.5: Evaluation of record** (BRF-A16 to BRF-A20; BRF-D8, BRF-D9). The
  fixtures, `evals/score_briefs.py` with its suite, and the committed record
  run. The verification child for ACQ-A12 and ACQ-A13. Depends on S3.4.

## Continuations

- feat: AC brief S3.1: the helper's sources, refusals and check (BRF-D1 to BRF-D4) — AC: BRF-A1, BRF-A2, BRF-A3, BRF-A4, BRF-A5, BRF-A6, BRF-A7, BRF-A8, BRF-A9; make content-tests and make ci exit 0.
- feat: AC brief S3.2: the evidence map (BRF-D5) — AC: BRF-A10, BRF-A11, BRF-A12; make content-tests exits 0.
- feat: AC brief S3.3: item criteria through the facade renderer (BRF-D7) — AC: BRF-A13, BRF-A14, BRF-A15; make content-tests exits 0.
- feat: AC brief S3.4: the briefing skill routes through the helper (BRF-D6) — AC: make content-lint exits 0, and S3.5's evaluation runs against this skill text.
- feat: AC brief S3.5: generated-brief evaluation of record, the verification child (BRF-D8, BRF-D9) — AC: BRF-A16, BRF-A17, BRF-A18, BRF-A19, BRF-A20.

## Out of scope

The render verb itself (`agents-config-9k9.405.4`). LIFE-A32's citation of the
re-attack rule in briefs (`agents-config-9k9.405.9`). Judging whether a planned
check is feasible in code. Criterion quality, which the attack judges.

## Evidence

- BRF-A1 | open
- BRF-A2 | open
- BRF-A3 | open
- BRF-A4 | open
- BRF-A5 | open
- BRF-A6 | open
- BRF-A7 | open
- BRF-A8 | open
- BRF-A9 | open
- BRF-A10 | open
- BRF-A11 | open
- BRF-A12 | open
- BRF-A13 | open
- BRF-A14 | open
- BRF-A15 | open
- BRF-A16 | open
- BRF-A17 | open
- BRF-A18 | open
- BRF-A19 | open
- BRF-A20 | open
