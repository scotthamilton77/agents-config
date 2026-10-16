# Editor clarity evaluation

This evaluation checks whether the editor repairs necessary edits as well as
whether its proposals preserve meaning. An empty response can pass structural
validation and still fail this evaluation.

## Fixed inputs and runs

Use the four requests in the sibling directories for PRs 838, 839, 843 and 846.
Send the complete instruction text followed by the unchanged request. Run once
per request at the existing editor pin, GPT-6 Luna at low effort. Retain the
instruction snapshot, requests, raw responses, settings and available usage.
Run in an empty directory with project and user instructions disabled. The
editor receives no repository context or additional critique.

The sibling responses are the baseline. Preserve them. This protocol is fixed
before the new runs. A later prompt revision needs its own retained snapshot
and four runs; it does not replace an unsuccessful run.

## Necessary edits and controls

Each selected defect is independently repairable within its field. Its repair
must keep every original assertion and qualification. Splitting a compound
sentence is sufficient; synonyms alone are not a repair.

| Fixture | Necessary edit | Required repair | Clean control |
| --- | --- | --- | --- |
| PR 838 | `/risk/rows/0/evidence` | Give the test coverage and the pre-change failures separate sentences. | `/risk/rows/0/recovery`: Revert. |
| PR 839 | `/risk/rows/0/evidence` | Give case sensitivity and the clean run over 94 files separate sentences. | `/risk/rows/1/recovery`: Add the missing pattern. |
| PR 843 | `/criteria/0/promise` | Separate the four assertions about pins, the round record, refusal and write access. | `/risk/rows/0/evidence`: Tests check that every slot has a pin. |
| PR 846 | `/changes/1/text` | State what the reviewers' table names and how that determines ownership in separate sentences. | `/risk/rows/0/recovery`: Revert. |

## Judgment and threshold

The implementing agent judges the selected repairs and every proposed
replacement against the request's writing checks. For each proposal, record
accept, correct or reject with its field, check number and a sentence of basis.
Check explicitly for strengthened claims, dropped exceptions and erased
deferred work. Mark any unresolved question separately. These judgments are
agent assessments; they do not stand in for the owner's readability judgment.

For each necessary edit, record repaired or missed, including when the editor
omits its field. For each control, record unchanged or unnecessarily rewritten.
An omitted necessary edit counts as a failure even when the editor proposes
other good edits. A question alone does not repair an independently editable
defect.

The selected-case threshold is four repaired defects and four unchanged
controls. Every response must fit the response schema, retain the request and
section digests, name only editable sections and preserve protected values.
Apply all raw replacements to a temporary copy and report full lint results
separately. Existing fixture lint failures must be distinguished from faults
introduced by the editor. Report every semantic rejection and correction; a
raw response requiring either does not pass the meaning-preservation check.

Record the baseline and candidate counts, all selected-case judgments and the
proposal judgments. Report failures without lowering the threshold. The four
runs establish behaviour on these inputs only.
