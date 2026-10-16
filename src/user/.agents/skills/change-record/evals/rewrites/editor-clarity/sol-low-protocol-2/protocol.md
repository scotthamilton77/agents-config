# Editor evaluation at the Sol-low pin

This protocol evaluates editor instruction candidates at the skill's pin,
GPT-6.1 Sol at low effort. It is fixed before its first run. It keeps the
cases, judgment standard and thresholds of the parent protocol in the
directory above, with one change: PR 843's clean control. The parent
protocol, its candidates and the Sol-low model comparison stay as recorded.

## Fixed inputs

Each run sends the complete instruction snapshot, a newline, and then the
unchanged request file for its fixture. The request files are the ones
beside each fixture's recorded baseline run.

| Fixture | Request file | SHA-256 |
| --- | --- | --- |
| PR 838 | `pr-838/request.json` under the rewrite evaluations | `80e77009d030e04c649f356f151aab550b1ee29fc4c99c006d0009a0e3269a41` |
| PR 839 | `pr-839/request.json` under the rewrite evaluations | `f4a53fe9450c5e02ea19e138ba705a418539ec83688d132da49b9753b8bb80f3` |
| PR 843 | `pr-843/request.json` under the rewrite evaluations | `19207b75900cfaccd03fe1f32848edea42876eb30b3cb844b7fc10c55a93fb71` |
| PR 846 | `pr-846/request.json` under the rewrite evaluations | `40d13064ed3279bc71511c0a9ad67d0b5badaa5a1a2ffe93113f0f3500353745` |

The candidate 4 snapshot is `instructions.md` in the `candidate-4` directory
beside this protocol. Its SHA-256 is
`89eede8af9a4173c4c84f02c985d96f8f4a9a983a966b99003a9d87127528730`. It is
byte-identical to the skill's live editor instructions when this protocol is
fixed.

## Runs

Each candidate gets one run per fixture, four runs in all. Every run uses
model `gpt-6.1-sol` at effort `low`, which is the skill's pin file.

Every run goes through `codex exec` with the same isolation the Sol-low model
comparison records. The working directory is empty. The user configuration
file is not loaded, and execution-policy rules are not loaded. Project
documents are limited to zero bytes. Developer instructions are empty. The
shell tool is off and web search is disabled. The sandbox is read-only, and
the session is not persisted. The prompt arrives on standard input. The
editor receives no repository context and no critique.

Each fixture directory in the candidate's directory retains the raw response,
the event log, standard error, the settings with usage and timing, and the
local validation. A call that exits non-zero or returns no response is a
failed run of that candidate. It is retained as it is. No retry replaces a
run, and no later run replaces an earlier one.

## Candidates

This protocol admits at most two candidates. Candidate 4 runs first.
Candidate 5 runs only when candidate 4 fails. Each candidate has its own
directory holding its instruction snapshot and its four runs. A failed
candidate's directory is retained unchanged. Candidate 5's snapshot hash is
recorded in its run settings before its first call. Everything else here
applies to it unchanged.

A failed candidate 4 leaves the evaluation pending and permits candidate 5.
When candidate 5 also fails, the evaluation is failed and the owner decides
the next step. No third candidate runs under this protocol.

## Necessary edits and controls

Each selected defect is independently repairable within its field. Its repair
must keep every original assertion and qualification. Splitting a compound
sentence is sufficient; synonyms alone are not a repair.

| Fixture | Necessary edit | Required repair | Clean control |
| --- | --- | --- | --- |
| PR 838 | `/risk/rows/0/evidence` | Give the test coverage and the pre-change failures separate sentences. | `/risk/rows/0/recovery`: Revert. |
| PR 839 | `/risk/rows/0/evidence` | Give case sensitivity and the clean run over 94 files separate sentences. | `/risk/rows/1/recovery`: Add the missing pattern. |
| PR 843 | `/criteria/0/promise` | Separate the four assertions about pins, the round record, refusal and write access. | `/risk/rows/1/recovery`: Revert. |
| PR 846 | `/changes/1/text` | State what the reviewers' table names and how that determines ownership in separate sentences. | `/risk/rows/0/recovery`: Revert. |

The parent protocol's PR 843 control is `/risk/rows/0/evidence`, which reads
"Tests check that every slot has a pin." Its house term "pin" is one that the
first writing check requires an editor to explain, so it is not clean text.
This protocol uses the one-word recovery cell that the PR 838 and PR 846
controls also use. The runs under the parent protocol keep their recorded
control outcomes.

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

A candidate passes only when all four of its runs meet every threshold above.
Record the counts, all selected-case judgments and the proposal and question
judgments. Report failures without lowering the threshold. The four runs
establish behaviour on these inputs only.
