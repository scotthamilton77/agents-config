# Editor clarity results

Assessment dates: 2026-10-15 and 2026-10-16. Evaluator: the implementing Codex agent.
The protocol beside this file defines the cases and standard. These are agent
assessments, not the owner's readability judgments.

## Baseline

The existing sibling requests and responses contain six replacements across
162 sections. The four selected controls are unchanged. None of the four
selected defects receives the required sentence separation.

| Fixture | Proposals / sections | Selected defect | Control |
| --- | --- | --- | --- |
| PR 838 | 0 / 29 | Missed: the test coverage and pre-change failures remain in one sentence. | Unchanged. |
| PR 839 | 0 / 30 | Missed: case sensitivity and the run over 94 files remain in one sentence. | Unchanged. |
| PR 843 | 1 / 77 | Missed: all four assertions in the criterion remain in one sentence. | Unchanged. |
| PR 846 | 5 / 26 | Missed: the proposal changes wording but leaves the table's contents and ownership consequence in one sentence. | Unchanged. |

Selected-case result: 0 of 4 repairs and 4 of 4 unchanged controls. The baseline
fails the declared repair threshold.

### Baseline proposals

| Fixture | Section | Judgment | Writing check | Basis |
| --- | --- | --- | --- | --- |
| PR 843 | `/summary` | Accept | 5 | Direct verbs preserve the five assertions, including the fixed recovery sequence and unchecked effort. |
| PR 846 | `/summary` | Accept | 1 | The wording clarifies the overlapping questions and retains all reported counts and continued detection of the planted criterion. |
| PR 846 | `/risk/rows/1/evidence` | Accept | 1 | The clearer referent retains the run count, shared settings and flaw in both versions. |
| PR 846 | `/changes/0/text` | Correct | 1 | Restore that the rule now opens with the check; the proposal says what the rule judges but drops the statement about its opening. |
| PR 846 | `/changes/1/text` | Correct | 1 | Restore that the table gains a column; naming what the table now contains alone omits that concrete change. |
| PR 846 | `/commit/why` | Accept | 1 | The clearer wording retains the coverage misclassification and the 2-of-10 control result. |

These judgments assess improvements rather than asserting that every accepted
section fully satisfies every writing check. In particular, the selected PR
846 defect remains missed despite its proposal. All six proposals retain the
original claim scope, exceptions and deferred-work statements apart from the
two omissions identified above. They add no factual assurance.

## Candidate 1

The candidate instruction snapshot and settings are retained under
`candidate-1/`. Its input references resolve to the unchanged sibling requests;
the settings record their hashes. The model and effort remain GPT-6 Luna and
low.

The owner authorized the external transfer of these four requests and the
revised instructions on 2026-10-15. All four calls completed at the unchanged
pin. Each directory retains its raw response, event log, stderr, settings with
usage, and local validation results. No editor used a tool. Two calls emitted
a nonfatal system-skill installation warning; each still completed with exit 0.

| Fixture | Actual replacements | Selected defect | Control | Full raw application |
| --- | --- | --- | --- | --- |
| PR 838 | 3 | Missed. | Unchanged. | Accepted. |
| PR 839 | 12 | Repaired. | Unchanged. | Refused: the commit change has five sentences instead of three to four. |
| PR 843 | 6 | Missed. | Unchanged. | Refused: the summary drops the protected word "fixed". |
| PR 846 | 6 | Repaired. | Unchanged. | Accepted. |

The candidate repairs 2 of 4 selected defects, up from 0 in the baseline.
All four selected controls remain textually unchanged. The required four
repairs are not achieved. The PR 843 control also attracts an unnecessary
question despite its wording staying unchanged.

There are 27 actual replacements, compared with 6 in the baseline. PR 839's
response incorrectly reports 13 proposals for its 12 entries. The application
code permits a larger count because an author can prune a response, so that
count error passes its check. It is still a violation of the raw editor
contract and would inflate the pruning metric.

All four responses fit the JSON schema and retain valid record and section
digests. Three pass every pre-lint application check. Two pass full raw
application. Every original fixture passes lint, so both refusals arise from
the editor's changes. PR 839 also supplies three question pointers outside
the listed editable sections. PR 846 proposes one byte-identical replacement.

The implementing agent's judgments under `candidate-1/judgments.md` cover all
27 replacements and all 11 questions. Eighteen replacements are accepted,
six need correction and three are rejected. Only one question is directly
actionable; another needs its pointer corrected, and nine should be discarded.
These are agent assessments, not owner judgments. The raw candidate fails the
meaning-preservation and selected-repair thresholds.

The four calls took 7.2 to 11.0 seconds each. The retained usage records total
100,804 input tokens and 3,003 output tokens, with zero reported reasoning
output tokens. These figures describe the Codex dispatch, including its
runtime context; they are not a measurement of request text alone.

The prompt elicits more editing on this sample, but the candidate is not
ready to ship. A single run per fixture does not establish general model
reliability or isolate the prompt's effect from run-to-run variation.

## Candidate 2

The second instruction snapshot and settings are retained under
`candidate-2/`. It uses the same requests, pin and judging protocol. The
revision makes coverage of evidence and criterion fields explicit. It
distinguishes a wording edit from a review of evidence, keeps qualifications
and each section's claims, limits structural questions to missing author
actions, and restates protected-value and sentence-cap requirements.

The owner authorized this revision and further necessary refinements using
these same four fixtures on Luna-low. All four calls completed with exit 0
and no tool use. There are 29 actual replacements. The PR 846 response says
9 were proposed but contains 8 entries. One PR 838 entry is byte-identical to
its original.

The candidate repairs 2 of 4 selected defects and leaves all four selected
controls textually unchanged. It again misses the PR 838 test-evidence split
and the four-assertion criterion in PR 843. The PR 843 response proposes no
replacement and asks another evidence-review question.

All four responses pass schema and pre-lint application checks. Full raw
application accepts PR 838 and the empty PR 843 response. It refuses PR 839
because its commit change has six sentences, and PR 846 because its summary
has six. The allowed maxima are four and five respectively.

The PR 839 design-note proposal also changes the recorded six patterns
covering both groups into six patterns plus three more. That changes the
total to nine. The program's protected-value check does not detect this
semantic error.

The judgments under `candidate-2/judgments.md` cover all 29 replacements and
all three questions. Eighteen replacements are accepted, eight need
correction and three are rejected. Two questions challenge evidence rather
than identify missing wording context; the alias question needs its pointer
corrected. The candidate fails the fixed repair and preservation thresholds.

Calls took 6.3 to 16.3 seconds. Usage totals are 102,694 input tokens and
3,519 output tokens, with zero reported reasoning output tokens.

## Candidate 3

The third prompt groups coverage, section independence, meaning preservation
and hard limits more closely. It is 1,048 words, down from 1,578 in candidate
2. Its snapshot, raw outputs, usage, validation and full proposal judgments
are retained under `candidate-3/`. This instruction snapshot was tested as an experimental source draft. It
does not pass. The snapshot is evaluation data, not the active instructions.

| Fixture | Actual replacements | Selected defect | Control text | Full raw application |
| --- | --- | --- | --- | --- |
| PR 838 | 24 | Repaired. | Unchanged, but needlessly returned as an identical replacement. | Refused: an understated proposal count and changed protected-value representation; the commit change also exceeds its cap. |
| PR 839 | 8 | Repaired. | Unchanged. | Refused: six summary sentences. |
| PR 843 | 19 | Missed. | Unnecessarily changed. | Refused: an understated proposal count; commit and reply changes also exceed their caps. |
| PR 846 | 20 | Repaired. | Unchanged. | Refused: an understated proposal count; the summary also exceeds its cap. |

All four calls completed with exit 0 and no tool use. All responses fit the
JSON schema. Their 71 actual replacements are reported as 58 proposals, with
three understated counts. Twenty entries are byte-identical to their
originals. Every raw response is refused by full application. The selected
result is 3 of 4 repairs and 3 of 4 control texts unchanged.

The protected-value refusal in PR 838 arises because the proposal wraps the
plain command containing the digit 2 in backticks. The digit remains in the
command text, but the checker now treats it as part of a code span instead of
its original standalone value. The editor instructions require retaining
that wrapping.

The judgments under `candidate-3/judgments.md` assess all 71 entries and all
four questions. Thirty replacements are accepted, eighteen need correction
and twenty-three are rejected, including the twenty identical entries.
Corrections address semantic scope, attribution, qualifications and hard
limits. The four-assertion PR 843 criterion remains omitted despite edits to
nearby criteria and replies.

Calls took 12.3 to 19.6 seconds. Usage totals are 100,226 input tokens and
8,121 output tokens, with zero reported reasoning output tokens.

## Higher-grade model comparison

The owner paused prompt refinement and requested a stronger-model comparison.
GPT-6.1 Sol at low effort received the byte-identical candidate-3 instructions
and four unchanged request files. The Codex route, isolation, tool settings,
selected repairs, controls and rubric stayed the same. Only the requested
model changed. The protocol, instruction snapshot, raw outputs, settings,
usage, validation and full judgments are under `model-contrast-sol-low/`.

| Fixture | Actual replacements | Questions | Selected repair | Control unchanged | Full raw application |
| --- | --- | --- | --- | --- | --- |
| PR 838 | 12 | 6 | Yes. | Yes. | Accepted. |
| PR 839 | 15 | 4 | Yes. | Yes. | Accepted. |
| PR 843 | 40 | 11 | Yes. | No. | Accepted. |
| PR 846 | 14 | 4 | Yes. | Yes. | Accepted. |

All four calls completed with exit 0 and no tool use. Every response has an
exact proposal count, valid schema and digests, preserved protected values,
zero identical replacement entries and a lint-clean application. Sol repairs
the four-assertion PR 843 criterion that all three Luna revisions missed.

The PR 843 control replaces pin with configured effort and tools. The record
explicitly defines pin that way, so this is a useful jargon clarification
under writing check 1. The original clean-control choice is questionable.
Its predeclared unchanged-control test still fails; the control is not
reclassified after seeing the answer.

The implementing agent judged all 81 proposals and 25 questions. Seventy-three
proposals are accepted and eight require correction. For example, the commit
change drops that a round record copies its settings from the corresponding
slot pin. Another proposal replaces the specific sweep review phase with a
full reread. A criterion rewrite presupposes that a check exists rather than
retaining the explicit question of whether each criterion names one. These
semantic changes pass the mechanical guards, so full application acceptance
does not establish fidelity. Some questions also request permission to shorten
text already editable, or assert conflicts without establishing them. One
incorrectly claims a reply would fall below 40 words; it would have 50.

Calls took 34.9 to 81.3 seconds. Usage totals are 99,194 input tokens and
10,473 output tokens, including 572 reported reasoning output tokens. These
are dispatch usage figures, including runtime context. Luna candidate 3 took
12.3 to 19.6 seconds per call with 100,226 input tokens and 8,121 output tokens.
No dollar-cost comparison is made.

This sample shows a substantial improvement with Sol-low while holding the
prompt and request bytes fixed. It supports model choice as a contributor to
the observed problem. It does not isolate stochastic variation through
repeated trials or establish general reliability. Sol still fails the fixed
unchanged-control and meaning-preservation thresholds.

## Outcome

| Prompt | Actual replacements | Selected repairs | Control texts unchanged | Full raw applications accepted |
| --- | --- | --- | --- | --- |
| Baseline | 6 | 0 of 4 | 4 of 4 | Not reassessed here. |
| Candidate 1 | 27 | 2 of 4 | 4 of 4 | 2 of 4 |
| Candidate 2 | 29 | 2 of 4 | 4 of 4 | 2 of 4, including one empty response |
| Candidate 3, Luna-low | 71 | 3 of 4 | 3 of 4 | 0 of 4 |
| Candidate 3, Sol-low | 81 | 4 of 4 | 3 of 4 | 4 of 4 |

No tested model and prompt combination meets every fixed criterion. Sol-low
makes materially better use of the same whole-record prompt on this sample.
Its responses remove Luna's application failures, repair all four selected
defects and avoid identical replacements. Meaning review still finds eight
proposals needing correction.

This PR retains evidence only. Every experimental instruction snapshot is
source-side evaluation data excluded from installation by the existing evals
rule. The active skill, editor instructions, rewrite guide, response schema,
model pin and application protections are unchanged from this branch's base.
The experimental implementation remains in its separate worktree. Prompt
refinement and any redesign into smaller requests remain paused at the owner's
direction. The original editor fix is not complete. The comparison informs a
later implementation decision without changing the one-dispatch design or
production pin.

## Experiment validation

The experimental rewrite suite passed all 75 tests with exit 0. Documentation
lint exited 0 over the experimental changes. A direct comparison confirms that the response
schema differs only in descriptions, the editor pin is byte-identical, and
the retained candidate instruction and input hashes match their snapshots.

The second-candidate draft passed the full repository gate and its 75-test
rewrite suite. The third-candidate full repository gate exited 2 because the unchanged
327-test context suite exceeded its 120-second runner limit. Its standalone
rerun passed all 327 tests in 129.86 seconds with exit 0. The other 27 content
suites and preceding gates passed in the full run. The full gate is therefore
not green for the current draft; no timeout or test was changed. These
mechanical checks do not establish the editor's readability or
meaning-preservation performance.

## Evidence-only PR validation

The evidence-only branch starts from current main. Its diff contains only this
evaluation directory. All four original request hashes and the byte-identical
candidate-3 instructions used for both model runs are checked against the
retained files. The copied experiment artifacts match the original worktree;
only this report changes to state the evidence-only scope. No model run is
repeated or substituted.

The evidence-only branch's repository and documentation gates are pending.
Their collected exit statuses must be recorded before this PR claims them.
The earlier experimental timeout remains recorded above; a new gate result
cannot replace that outcome.
