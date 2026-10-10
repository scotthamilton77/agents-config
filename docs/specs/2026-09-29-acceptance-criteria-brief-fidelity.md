# Acceptance-criteria brief fidelity and evidence mapping

**Date:** 2026-09-29
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
slice S3 (brief fidelity and evidence). Attacked on 2026-10-07; the record is
beside this file.
**Work item:** `agents-config-9k9.405.11` (S3 feature), design child `agents-config-9k9.405.11.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`, LIFE-D1 (rendering).
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D1, D2 and D4.

## Scope

S3 owns ACQ-A12 and ACQ-A13. A dispatch brief must carry exactly the criteria
assigned to the work. It must refuse when it cannot. It must map each
criterion to its planned check, apart from the criterion's text. A criterion
without a feasible planned check is reported unready.

The parent's Testing decisions require the check at the consumer boundary.
That boundary is the generated brief itself.

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
- The installer prunes every `evals/` directory and every `*_test.py` or
  `test_*.py` file (`.installignore`).

## Decisions

**BRF-D1 — A helper emits the criteria and evidence sections.** The skill
ships `brief_criteria.py` beside its `SKILL.md`.

- Its `emit` mode prints exactly two Markdown sections. The first holds the assigned
  criteria as `- **ID** text` entries. The second is an evidence section that
  maps each ID to its planned check. The writer pastes both sections into the
  brief unchanged.
- Its `check` mode compares a written brief with the source, and with the plan
  when given `--checks`.

The helper uses the standard library only, so it runs under `uv run` or
`python3` on every supported tool.

Retyping criteria is where a brief drifts. Fidelity therefore moves into code
that the writer runs and the evaluation can score.

**BRF-D2 — Three sources, one grammar.** The helper reads criteria from three
sources.

- `--spec PATH --ids ID,...` reads the named entries from a spec's
  acceptance-criteria sections.
- `--criteria FILE` reads a file holding only entries, for criteria authored
  for one brief.
- `--item ID` reads a work item's criteria (BRF-D7).

Exactly one source flag is given. More than one, or none, refuses as
`source-conflict`.

Spec and file entries follow spec-lint's entry grammar, joined text included.
The helper's parser is a marked counterpart of spec-lint's: each carries a
marking naming the other, as the lifecycle spec's LIFE-D1 already requires of
workcli's parser. The grammar has five rules, and a criteria file follows all
but the second:

1. An entry opens on a line holding, after optional indentation, `- **ID** `
   and nonblank text, where the ID has spec-lint's criterion ID form.
2. An entry counts only under a heading whose text contains "acceptance
   criteria" in any case. The section runs through deeper subheadings to the
   next heading at the same or a shallower level.
3. Each following line that is nonblank and neither a bullet nor a heading
   continues the entry. It is stripped and joined to the text by one space.
4. A blank line, a bullet or a heading ends the entry.
5. A line inside a fenced code block, its fence markers included, never opens
   or continues an entry, and it ends the current one.

One fixture keeps the two readings from drifting apart unseen. It lives in the
skill's `evals/`. It is a Markdown spec with its expected readings, it holds a
case for each rule, and both suites read it.

A case's label proves nothing about coverage. A variant of the helper's parser
that breaks a rule and still passes every case shows that rule uncovered.

Both suites fail when the fixture is absent. The installer prunes every test
file along with `evals/`, so neither suite ever runs in a deployed tree, and
nothing needs a skip.

**BRF-D3 — Fidelity is the set of IDs and their words.** A brief preserves its
criteria when two things hold. Its criteria section holds exactly the assigned
IDs. Each ID's text equals its source text after runs of whitespace collapse
to one space.

A rewrap changes no word. A changed word, a dropped or added ID, or a changed
ID is a different contract. Order is not compared, since no criterion depends
on its position.

Evidence follows the same rule against the plan. A brief preserves its
evidence when two things hold. Its evidence section holds exactly the assigned
IDs. Each ID's entry equals the entry `emit` prints for it from the same plan
after runs of whitespace collapse to one space. An observation and a pass rule
must therefore equal the planned ones, and an unready ID keeps its mark and
reason.

**BRF-D4 — A refusal replaces the brief.** To refuse, `emit` prints nothing on
stdout and one JSON object on stderr naming each fault, and exits 2. Nothing
pasteable exists, so no brief with an invented contract can follow. The codes:

- `no-criteria`: the source is readable and well-formed and assigns no
  criterion;
- `unretrievable`: an assigned ID is absent from its spec, naming the ID;
- `unreadable-source`: the spec, criteria file, checks file or brief is
  missing or unreadable, naming the path and every assigned ID;
- `source-conflict`: more than one source flag, or none, naming the flags
  given;
- `duplicate-id`: an ID is assigned twice, or its source defines it twice;
- `malformed-criteria`: a criteria file holds a nonblank line outside an entry,
  naming the line;
- `malformed-checks`: the checks file breaks the BRF-D5 shape;
- `render-failed`: an item's rendering fails, naming the item and the cause.

One refusal names every fault the helper detects in the sources it can read.
Two absent IDs therefore yield one refusal naming both. A criteria file whose
only nonblank lines sit outside any entry is malformed, not empty. It refuses
as `malformed-criteria` alone.

The skill tells the writer to relay a refusal to its requester and dispatch
nothing.

**BRF-D5 — A planned check is an observation and a pass rule.** `--checks FILE`
is a JSON object mapping an ID to `{"observe": …, "pass": …}`, where each field
is a string.

The file breaks that shape when it is not JSON, its top level is not an
object, an entry is not an object, or `observe` or `pass` is present and not
a string. The shape rule covers every entry, assigned or not, and reads no
other key.

A field is blank when its key is absent or its string holds only whitespace.
A missing key therefore makes a criterion unready. It never makes the file
malformed. A key other than `observe` and `pass` is ignored.

An entry keyed to an unassigned ID is otherwise ignored, because one checks
file can serve several briefs that each carry part of a spec's criteria. A
mistyped ID therefore surfaces as its intended criterion being unready.

The evidence section holds exactly the assigned IDs. It gives each one its
observation and pass rule, or marks it `unready` with its reason. The reasons
are a closed set:

- `no planned check` means the file has no entry for the ID;
- `blank observation` and `blank pass rule` name each blank field.

Without `--checks`, every criterion is unready with the reason `no planned
check`.

When any criterion is unready, `emit` still prints both sections, names each
unready ID on stderr, and exits 1. The criteria section is the same whether
`--checks` is absent, complete or leaves a criterion unready.

Those reasons are the helper's. The writer adds one of its own: whether a
stated check is feasible is the writer's judgment, which code cannot make, and
a criterion whose planned check the writer judges infeasible is unready too,
reported to the requester in the writer's words and never dispatched. The
evaluation measures that judgment (BRF-D8), and the skill tells the writer not
to dispatch a brief with an unready criterion.

**BRF-D6 — The skill routes the writer through the helper.** S3.4 rewrites the
skill's acceptance-criteria part and skeleton. Criteria and evidence come from
`emit`, pasted unchanged, and `check` runs before dispatch. A refusal or an
unready criterion is reported to the requester.

LIFE-A32's sentence on re-attack before use belongs to lifecycle S6
(`agents-config-9k9.405.9`), so this slice leaves it alone.

Content-lint's token caps apply.

**BRF-D7 — Item criteria come only from the facade renderer.** `--item` runs
`work acceptance render ID` and reads its acceptance-criteria section. It never
resolves an item's acceptance field itself, since that would be a third
resolver of LIFE-D1.

Until `agents-config-9k9.405.4` ships the verb, `--item` refuses as
`render-failed`, naming the missing verb.

**BRF-D8 — The generated-brief evaluation.** The evaluation scores the output
a writer produces for each of seven fixtures.

The writer is a Claude Opus model through the native Agent tool, given the
skill from the source tree by full path. The scorer holds the writer's model
ID as a constant, its configured model, and an attempt's record must name
that ID as the one the writer resolved to. Changing the configured model
amends this spec. For each fixture it briefs a subagent for a
fixed task and returns its output instead of dispatching. Returning a brief
stands for dispatching it, and the writer runs with no subagent tool, so
returning is its only route.

The output takes one of two forms. A brief is the prompt the writer would
dispatch. A report is the writer's message to its requester. It holds no
criteria or evidence section. It relays anything the helper printed on
stderr, and it names any IDs the writer itself judged unready under BRF-D5.
Each output opens with a line naming its form, `Form: brief` or
`Form: report`, so the scorer reads the form mechanically. An output present
without such a line, or whose line names any other form, fails its run.

Each fixture runs five times in fresh contexts, so one attempt on every
fixture plans 35 dispatches, plus the repeats and second fives defined below.
The attempt's record names the writer's resolved model ID. The outputs cannot
show a fresh context or the native Agent tool, so the operator attests both in
the record.

Fixtures live in the skill's `evals/`:

| Fixture | Assignment | A run passes when |
| --- | --- | --- |
| F1 | three spec criteria, one wrapped over several lines and one quoting code, each with a planned check | preservation: `check` accepts the brief; evidence: `check --checks` accepts its evidence section |
| F2 | three criteria in a criteria file, each with a planned check | as F1 |
| F3 | no criterion assigned | the output is a report relaying the refusal object that carries `no-criteria` |
| F4 | one assigned ID the spec lacks | the output is a report relaying the refusal object that carries `unretrievable` and names the ID |
| F5 | an unreadable spec path | the output is a report relaying the refusal object that carries `unreadable-source` and names the path and every assigned ID |
| F6 | three criteria, one whose pass rule is "a reviewer confirms it reads well" | the output names that ID as unready |
| F7 | three criteria: one with a planned check, one with none, one with a blank pass rule | the output is a report naming the two unready IDs |

F3 to F7 pass only in the report form. A brief for any of them fails the run.
That includes a brief that carries `unready` marks and a brief that lacks a
criteria section.

`evals/score_briefs.py` scores the outputs mechanically, and scores F1's and
F2's preservation and evidence separately.

A run with no output is repeated at most twice. It is then left pending and
never scored as failed. The repeat limit is an operator procedure, because no
output shows a retry. A repeat is dispatched only for a run that has produced
no output. Each output names its run. The attempt's record names, for each of
a fixture's five runs and each of a second five, the one output that counts.
When a repeated run's earlier dispatch delivers late, that output stays
committed and the record marks it superseded, naming the output that counts
for its run. The scorer refuses a record naming more than one counting output
for a run, or more than five runs for a fixture or for its second five, and
it refuses an attempt whose directory holds an output the record neither
counts nor marks superseded. A fixture behind a refused record is incomplete
until the record is amended.

A fixture is locked on its own runs, under the evaluation contract's rule
(ACE-D7, ACE-D8), with a second stage wider than the contract's. F1 and F2
each have two sides, preservation and evidence, also called halves. Every
other fixture has one. A side runs five times. When all five pass, the side
passes. When three or four of the five pass, the side gets a second five, and
it passes when at least eight of its ten runs pass. When two or fewer pass,
the side fails. No run is discarded. A fixture is locked when every side
passes.

One rule serves every fixture, F6 included. The contract passes a side at four
of five and sends only a three-of-five side on to a second five. This
evaluation sends a four-of-five side on as well, because a brief is cheap to
score. Seven fixtures at five Opus dispatches each make 35 dispatches. For a
writer right nineteen times in twenty, about one side in five goes on to its
second five, so an attempt costs some 45 dispatches. The contract's 29 cases
on Codex cannot afford a second five that often. The second stage buys
discrimination. A writer that pastes wrong one time in five locks a side about
seven times in ten under this rule and eight in ten under the contract's, and
a writer right nineteen times in twenty locks a side ninety-nine times in a
hundred under both. Ten runs still cannot tell a writer right ninety-nine
times in a hundred from one right every time. The helper decides the outputs
of F1 to F5 and F7, but a stricter threshold on those fixtures would still
measure nothing more. The scope's rule that a criterion without a feasible
planned check is reported unready is measured by these runs, never proved by
them. A failed run behind a lock is committed and read like any other, and a
defect it shows is answered by changing the skill, which voids the lock and
runs the fixture again.

A lock records its fixture's fingerprint: the digest of every file the writer
is given, which is the skill directory without `evals/` together with the
`acceptance-criteria` skill directory the skill sends the writer to, the
digest of the fixture's own files, and the configured model ID. A lock is current
while its fingerprint matches the tree and its stored runs still pass under
the current scorer. A change voids only the locks whose fingerprint it alters,
and only those fixtures run again. A change to the scorer dispatches no
writer: the stored outputs are rescored, and a lock stands when its fixture
still passes and falls when it does not.

A fingerprint gets one attempt, plus the second five a side at three or four
of five earns. An attempt counts against its fingerprint once committed,
complete or not. An incomplete attempt is completed in place: its pending runs
are repeated under the limit above and its record amended, and it is never
replaced. A run still pending after its repeats leaves the fixture unlocked
until a change alters its fingerprint, and the new fingerprint gets an attempt
of its own. The scorer refuses a second attempt recording a fingerprint it has
already seen, whether the earlier locked, failed or stayed incomplete, so a
failed fixture is answered only by changing something, and a locked one is not
re-rolled.

An attempt is committed under `evals/runs/<run-id>/` with its outputs, its
record and its report, whatever it shows, and a second five is committed
beside the attempt it extends. That rests on the operator. The evaluation of
record is the set of current locks. Changing a run count or threshold amends
this spec.

**BRF-D9 — Verification ownership.** S3.5 is the verification child for ACQ-A12
and ACQ-A13, as ACQ-D2 requires. The helper suites establish the mechanism.
Only the evaluation of record establishes the parents at the generated brief.

## Acceptance criteria

- "Refuses as X" means the BRF-D4 refusal carrying code X.
- "The report form" is BRF-D8's report.
- "The evaluation of record" is BRF-D8's set of current locks. A fixture
  "passes in the evaluation of record" when it holds a current lock, and a
  side passes there when it passes under BRF-D8's two stages on the runs
  behind that lock.

An attempt is complete for a fixture when four things hold. The fixture has
five scored outputs, and five more when a side earned a second five. The
attempt's directory holds every output its report scores. Its record names the
writer's resolved model ID, which equals the configured model, and the
fixture's fingerprint. Its record carries the operator's attestation of fresh contexts
and the native Agent tool. A fixture with a pending dispatch among its first
five runs is incomplete and cannot lock. A fixture whose earned second five
has fewer than five runs named is awaiting it (BRF-A32), which is neither
incomplete nor locked; a named output the directory lacks, or a record fault,
makes the attempt incomplete first.

The helper suite and the scorer's suite run under `make content-tests`, and
spec-lint's under `make ci`.

- **BRF-A1** Given a spec and assigned IDs, `emit`'s criteria section holds
  exactly the assigned IDs, each with its entry's full text, continuation
  lines included, for three IDs and for several hundred alike.
- **BRF-A2** Given a criteria file, `emit`'s criteria section holds exactly the
  file's entries.
- **BRF-A3** `emit` refuses as `no-criteria` given an empty ID list or a
  criteria file holding nothing but blank lines.
- **BRF-A4** `emit` refuses as `unretrievable`, naming the ID, when an assigned
  ID has no entry in its spec.
- **BRF-A5** `emit` refuses as `unreadable-source`, naming the path and every
  assigned ID, when the spec, criteria file or checks file is missing or
  unreadable.
- **BRF-A6** `emit` refuses as `duplicate-id`, naming the ID, when an ID is
  assigned twice or defined twice in its source.
- **BRF-A7** `emit` refuses as `malformed-criteria`, naming the line, when a
  criteria file holds a nonblank line outside an entry. The refusal carries no
  `no-criteria` fault, even when the file holds no entry.
- **BRF-A8** Without `--checks`, `check` exits 0 when a brief preserves its
  assigned criteria under BRF-D3, and otherwise exits 1 naming each missing,
  added or altered ID.
- **BRF-A9** The shared grammar fixture holds a case for each BRF-D2 grammar
  rule. The helper suite and spec-lint's suite each read it, and each fails
  when its reading of an entry departs from the case's expected text. In the
  repository, for each rule, a variant of the helper's parser that breaks that
  rule fails at least one case. Each parser carries a marking naming the
  other as its counterpart. Each suite's fixture test fails when the fixture
  is absent.
- **BRF-A10** Given planned checks for every assigned criterion, `emit` prints
  an evidence section holding exactly the assigned IDs, each with its planned
  observation and pass rule, and exits 0. A well-formed checks entry keyed
  to an unassigned ID changes neither section, stderr nor the exit status.
- **BRF-A11** A criterion with no planned check, or whose planned check has a
  blank field, is marked `unready` with its reason in the evidence section and
  named on stderr, and `emit` exits 1. The reason is `no planned check`, or it
  names each blank field as `blank observation` or `blank pass rule`. A checks
  entry lacking the `observe` or `pass` key has a blank field. Without
  `--checks`, every criterion is unready with the reason `no planned check`.
- **BRF-A12** `emit` refuses as `malformed-checks` when the checks file is not
  JSON, its top level is not an object, an entry is not an object, or
  `observe` or `pass` is present and not a string. An entry that lacks a key
  is not malformed, and a key other than `observe` and `pass`, whatever its
  value, changes neither section, stderr nor the exit status.
- **BRF-A13** Given a stub facade that answers only `acceptance render` and
  prints criteria, `emit --item`'s criteria section holds exactly the rendered
  criteria, and the helper makes no other facade call.
- **BRF-A14** `emit --item` refuses as `render-failed`, naming the item and the
  cause, when the facade lacks the render verb or the rendering fails.
- **BRF-A15** `emit --item` refuses as `no-criteria` when the rendering holds no
  criterion.
- **BRF-A16** F1 and F2 pass on preservation in the evaluation of record.
- **BRF-A17** F1 and F2 pass on evidence mapping in the evaluation of record,
  where a run passes only when `check --checks` accepts its evidence section.
- **BRF-A18** F3 passes in the evaluation of record, where a run passes only
  when its output is the report form relaying the helper's refusal object that
  carries `no-criteria`.
- **BRF-A19** F4 and F5 pass in the evaluation of record, where a run passes
  only when its output is the report form relaying the helper's refusal object
  with its code and the named IDs, and for F5 the path.
- **BRF-A20** F6 and F7 pass in the evaluation of record, where a run passes
  only when its output is the report form naming the fixture's unready IDs. A
  brief carrying `unready` marks fails the run.
- **BRF-A21** `check` refuses as `emit` would when a source it shares with
  `emit` fails, and as `unreadable-source` when the brief cannot be read.
- **BRF-A22** `emit`'s criteria section is identical whether `--checks` is
  absent, supplies every planned check, or leaves a criterion unready. The
  exit-1 output holds that full criteria section, and no output holds a
  third section.
- **BRF-A23** Given `--checks`, `check` exits 1 naming each ID whose evidence
  entry is missing, added or altered under BRF-D3, and exits 0 when both the
  criteria and the evidence sections are preserved.
- **BRF-A24** Run by `python3` where no third-party package is importable,
  `emit` and `check` give the same stdout, stderr and exit status as under
  `uv run` for the same arguments and sources.
- **BRF-A25** One refusal names every fault the helper detects in the sources
  it can read. Given two assigned IDs absent from their spec, `emit` prints one
  refusal naming both.
- **BRF-A26** The scorer reports a fixture as incomplete, never as locked or
  failed, when its attempt has fewer than five scored outputs, when the
  attempt's directory lacks an output its record names, when the record names
  no resolved model ID, one other than the configured model, or no
  fingerprint, or when the record lacks the operator's attestation of fresh
  contexts and the native Agent tool. It names each missing output as
  pending. These hold whatever stage the fixture's sides are at.
- **BRF-A27** Given an output set seeded with three failed runs on each side
  of each fixture, such as altered criteria for F1's preservation half, altered
  evidence entries for its evidence half, briefs returned for F3, reports for
  F3 that lack the refusal object, reports for F4 that carry a criteria
  section, outputs with no `Form:` line or one naming another form, and
  briefs returned for F6, the
  scorer fails each seeded side and names its fixture. Given a set in which
  every side passes all five of its runs, under a record that BRF-A26 finds
  complete, it locks every fixture on five runs a side.
- **BRF-A28** The skill's acceptance-criteria part and skeleton tell the
  writer to take the criteria and evidence sections from `emit`, paste them
  unchanged, run `check` before dispatch, and relay a refusal or an unready
  criterion to the requester instead of dispatching; a content test reads
  each of the four instructions in the skill text.
- **BRF-A29** `emit` and `check` refuse as `source-conflict`, naming the flags
  given, when more than one source flag or none is given.
- **BRF-A30** `emit`, `check` and the scorer run twice over unchanged
  arguments and sources give identical stdout, stderr and exit status, `emit`
  and `check` write no file, and two runs over different sources at the same
  time share nothing.
- **BRF-A31** `make content-tests` runs the helper suite and the scorer's
  suite, and `make ci` runs spec-lint's fixture test: a test seeded to fail
  in each suite turns its gate red.
- **BRF-A32** Given an attempt under a record that BRF-A26 finds complete, in
  which one side has three or four passing runs of five, every other side
  passes, and fewer than five further runs are named, the scorer reports that
  fixture as awaiting its second five, neither locked, failed nor incomplete. Given the second five, it locks the
  fixture when the side's passing runs across the ten reach eight, so a side
  at three needs all five and a side at four needs four, and fails it when
  they do not.
- **BRF-A33** Given a committed lock whose recorded fingerprint differs from
  the one the scorer computes from the skill directory without `evals/`, the
  `acceptance-criteria` skill directory, the fixture's own files and the
  configured model ID, the scorer reports the lock
  as not current and leaves the fixture out of the evaluation of record.
  Given one whose fingerprint matches and whose stored runs still pass under
  the current scorer, it reports the lock as current and counts it, whatever
  changed outside its fingerprint. Given one whose fingerprint matches but
  whose stored runs no longer pass under the current scorer, it reports the
  lock as fallen and leaves the fixture out.
- **BRF-A34** Given two committed attempts recording the same fingerprint, the
  scorer scores the earlier and reports the later as refused, whether the
  earlier locked, failed or is incomplete.
- **BRF-A35** Given a record naming six counting outputs for one fixture's five
  runs, or six for its second five, or two for one run, the scorer refuses the
  attempt, names the fixture and reports it as incomplete. Given an output in
  the directory that the record neither counts nor marks superseded, it
  refuses likewise. Given a late output the record marks superseded beside the
  five it counts, it scores the five and reports the fixture on them alone.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A12, preservation | BRF-A1, BRF-A2, BRF-A8, BRF-A9, BRF-A13, BRF-A16, BRF-A24, BRF-A30 | Helper suite, spec-lint suite, the scorer's report |
| ACQ-A12, zero criteria | BRF-A3, BRF-A15, BRF-A18 | Helper suite, the scorer's report |
| ACQ-A12, unretrievable criterion | BRF-A4, BRF-A5, BRF-A6, BRF-A7, BRF-A14, BRF-A19, BRF-A21, BRF-A25, BRF-A29 | Helper suite, the scorer's report |
| ACQ-A12 and ACQ-A13, the writer's route | BRF-A28 | Content test |
| ACQ-A13, evidence apart from text | BRF-A10, BRF-A17, BRF-A22, BRF-A23 | Helper suite, the scorer's report |
| ACQ-A13, unready criterion | BRF-A11, BRF-A12, BRF-A20 | Helper suite, the scorer's report |
| ACQ-A12 and ACQ-A13, a trustworthy evaluation of record | BRF-A26, BRF-A27, BRF-A32, BRF-A33, BRF-A34, BRF-A35 | Scorer suite |
| The gates that run the suites | BRF-A31 | Makefile read, seeded failure |

### What-if questions

For `emit` and `check`:

- The failure and missing-input answers are the refusal criteria BRF-A3 to
  BRF-A7, BRF-A12, BRF-A14, BRF-A15, BRF-A21, BRF-A25 and BRF-A29.
- Empty is BRF-A3, BRF-A11's missing `--checks`, and BRF-A15.
- A checks file that names an unassigned ID is BRF-A10.
- `emit` and `check` read and never write, so running either twice or with
  nothing changed prints the same result and concurrent runs share nothing
  (BRF-A30). BRF-A24 extends that sameness across the two runtimes.
- A limit does not apply, since neither mode bounds how many criteria it
  carries.

For BRF-A16 to BRF-A20:

- A failure names the fixture (BRF-A27).
- A missing output leaves its fixture pending and its attempt incomplete
  (BRF-A26).
- A side at three or four of five waits on its second five (BRF-A32).
- A lock the tree no longer matches is not current (BRF-A33), and a second
  attempt on an unchanged fingerprint is refused (BRF-A34).
- An output the record neither counts nor marks superseded is a refusal
  (BRF-A35).
- Each fixture is fixed, so empty applies only where F3 and F7 test it.

## Ordered slice list

- **S3.1: The helper's sources, refusals and check** (BRF-A1 to BRF-A9,
  BRF-A21, BRF-A24, BRF-A25, BRF-A29 to BRF-A31; BRF-D1 to BRF-D4). `brief_criteria.py`,
  `brief_criteria_test.py` and the grammar fixture in
  `src/user/.agents/skills/instructing-subagents/`, and the fixture test in
  `packages/installer/tests/unit/test_spec_lint.py`. Depends on S1, landed.
- **S3.2: The evidence map** (BRF-A10 to BRF-A12, BRF-A22, BRF-A23; BRF-D5).
  The `--checks` paths of `emit` and `check` and their tests. Depends on S3.1.
- **S3.3: Item criteria** (BRF-A13 to BRF-A15; BRF-D7). The `--item` path, tested
  against a stub facade. Depends on S3.1. Its live use waits on
  `agents-config-9k9.405.4`, and S3.5 does not wait on it.
- **S3.4: The skill** (BRF-A28; BRF-D6). The acceptance-criteria part and
  skeleton of `SKILL.md`, and the content test that reads them. Depends on
  S3.2.
- **S3.5: Evaluation of record** (BRF-A16 to BRF-A20, BRF-A26, BRF-A27,
  BRF-A32 to BRF-A35; BRF-D8, BRF-D9). The fixtures, `evals/score_briefs.py`
  with its suite, and the committed attempts that lock every fixture. The
  verification child for ACQ-A12 and ACQ-A13.
  Depends on S3.4.

## Continuations

- feat: AC brief S3.1: the helper's sources, refusals and check (BRF-D1 to BRF-D4) — AC: BRF-A1, BRF-A2, BRF-A3, BRF-A4, BRF-A5, BRF-A6, BRF-A7, BRF-A8, BRF-A9, BRF-A21, BRF-A24, BRF-A25, BRF-A29, BRF-A30, BRF-A31; make content-tests and make ci exit 0.
- feat: AC brief S3.2: the evidence map (BRF-D5) — AC: BRF-A10, BRF-A11, BRF-A12, BRF-A22, BRF-A23; make content-tests exits 0.
- feat: AC brief S3.3: item criteria through the facade renderer (BRF-D7) — AC: BRF-A13, BRF-A14, BRF-A15; make content-tests exits 0.
- feat: AC brief S3.4: the briefing skill routes through the helper (BRF-D6) — AC: BRF-A28; make content-lint exits 0.
- feat: AC brief S3.5: generated-brief evaluation of record, the verification child (BRF-D8, BRF-D9) — AC: BRF-A16, BRF-A17, BRF-A18, BRF-A19, BRF-A20, BRF-A26, BRF-A27, BRF-A32, BRF-A33, BRF-A34, BRF-A35.

## Out of scope

- The render verb itself (`agents-config-9k9.405.4`).
- LIFE-A32's citation of the re-attack rule in briefs
  (`agents-config-9k9.405.9`).
- Judging whether a planned check is feasible in code.
- Criterion quality, which the attack judges.
