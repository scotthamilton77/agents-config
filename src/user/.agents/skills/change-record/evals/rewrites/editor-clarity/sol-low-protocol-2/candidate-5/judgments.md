# Candidate 5 judgments

Assessment date: 2026-11-05. Evaluator: a Claude subagent dispatched by the implementing session. The protocol beside this directory and each request's writing checks govern these judgments. These judgments are agent assessments, and they do not stand in for the owner's readability judgment.

Accept means a useful, meaning-preserving improvement. Correct requires an author repair before application. Reject identifies a proposal that should not be applied, because it changes meaning or makes clear text worse. Acceptance does not establish compliance with every writing check. Raw outputs remain unchanged.

The evaluator's brief named the 10% limit and the PR 839 digest failure before any proposal was judged, so the evaluator was not ignorant of the consequence. Each verdict rests on the comparison its row states, and the section on close calls names the verdicts another reader could reasonably change.

## Outcome first

Candidate 5 fails the protocol on the digest, whatever the semantic count is. The PR 839 response carries a malformed `section_digest` on `/commit/verification`, so it fails the response schema and the validation never attempted its application. A failed candidate 5 fails the evaluation, and the owner decides the next step.

## Runs

All four calls exited 0 with an empty standard error, and each event log holds one agent message and no tool use. Calls took 37.6 to 84.8 seconds. The request hashes and the instruction hash match the protocol.

| Fixture | Replacements | Questions | Full raw application |
| --- | --- | --- | --- |
| PR 838 | 6 | 1 | Accepted, with no lint finding. |
| PR 839 | 12 | 2 | Not attempted: the response fails the schema. |
| PR 843 | 33 | 6 | Accepted, with no lint finding. |
| PR 846 | 12 | 0 | Accepted, with no lint finding. |

The malformed digest has 57 hexadecimal characters where the request's has 64. The response drops the seven characters `ea5c796` after the first 48 and keeps everything on either side of them. The record digest and every other section digest in all four responses match their requests. Every response states its exact proposal count.

## Selected cases

| Fixture | Necessary edit | Outcome | Control | Outcome |
| --- | --- | --- | --- | --- |
| PR 838 | `/risk/rows/0/evidence` | Repaired: the coverage and the pre-change failures are separate sentences. | `/risk/rows/0/recovery` | Unchanged. |
| PR 839 | `/risk/rows/0/evidence` | Repaired in the wording: case sensitivity and the clean run over 94 files are separate sentences. The response that carries the repair fails the schema. | `/risk/rows/1/recovery` | Unchanged. |
| PR 843 | `/criteria/0/promise` | Repaired: the four assertions are four sentences. | `/risk/rows/1/recovery` | Unchanged. |
| PR 846 | `/changes/1/text` | Repaired: the new column and the ownership consequence are separate sentences. | `/risk/rows/0/recovery` | Unchanged. |

Selected-case result: 4 of 4 repairs and 4 of 4 unchanged controls.

## Proposals

Rows follow each response's order. A basis beginning "Unnecessary" marks an edit to a section that passed its checks on a fair reading, or an edit that repairs nothing.

| Fixture | Section | Judgment | Writing check | Basis |
| --- | --- | --- | --- | --- |
| PR 838 | `/summary` | Accept | 3 | The split keeps the unreachable rules and the retained code as two adjacent assertions. |
| PR 838 | `/risk/rows/0/evidence` | Accept | 3 | Two sentences keep six covering tests and four pre-change failures, with "them" still counting the six. |
| PR 838 | `/design_notes` | Accept | 3 | Every paragraph keeps its claims and turns each "because" into "therefore", and "four" gains the "test rows" that the sentence before it already elided. |
| PR 838 | `/criteria/0/promise` | Accept | 3 | Three sentences keep the same qualified answer as their subject. |
| PR 838 | `/commit/change` | Accept | 3 | The conditions match the design notes, which say "runs at" for both efforts, so "uses" in place of "keeps" loses nothing the record asserts, and the criterion's evidence shows the turn ran at medium effort before the change. |
| PR 838 | `/commit/verification` | Accept | 3 | The split keeps both gates, 97 passing, six tests, four earlier failures, the retained code and the absent review, and "make" keeps its command casing as it does at the start of the original. |
| PR 839 | `/summary` | Accept | 3 | Five sentences keep the "meant to" hedge, both scan exclusions and the uncaught aliases. |
| PR 839 | `/risk/rows/0/failure` | Accept | 3 | The split keeps the rejection of a word that is not an id and its blocking consequence. |
| PR 839 | `/risk/rows/0/evidence` | Accept | 3 | The split keeps case sensitivity and the clean run over 94 files. |
| PR 839 | `/risk/rows/0/recovery` | Accept | 3 | "Therefore" keeps the cause, and the deletion stays the recovery. |
| PR 839 | `/risk/rows/1/evidence` | Accept | 3 | "That run" keeps the exit status and the named line on the same appended id. |
| PR 839 | `/changes/1/text` | Accept | 3 | "Therefore" keeps the consequence for family names. |
| PR 839 | `/changes/2/text` | Accept | 3 | The reorder keeps the two-table allowance as the cause of the conversion. |
| PR 839 | `/discovered/rows/0/reason` | Accept | 3 | The split keeps both assertions in their original words, and "not one" carries the same looseness it has in the original. |
| PR 839 | `/criteria/5/promise` | Accept | 3 | The split keeps the failing row and the passing prose. |
| PR 839 | `/commit/change` | Accept | 3 | "Limit of two tables" is what the design notes state when they fail a third table, and the cause of the conversion remains in one predicate that fits the four-sentence cap. |
| PR 839 | `/commit/verification` | Accept | 3 | The split keeps the head, 20 suites, 34 cases, the exit status, the named line, the aliases and the absent review, and the sentence opening on "20" stands next to the gate it belongs to. |
| PR 839 | `/criteria/4/promise` | Accept | 3 | Unnecessary: the original has one clause and the rewrite has the same structure, but the failure still reports the table's name and the dangling "naming it" reads no better. |
| PR 843 | `/heads_up/0` | Accept | 3 | "Therefore" keeps the hang as the cause of the bash order. |
| PR 843 | `/heads_up/1` | Accept | 3 | The split keeps the commit id and the four prose-only commits, and the new sentence begins correctly. |
| PR 843 | `/risk/rows/0/evidence` | Accept | 1 | The record's design notes support the gloss on "pin", and this cell is not a control under this protocol. |
| PR 843 | `/risk/rows/1/failure` | Reject | 3 | "A run that dies outside the sequence" moves the sequence from the retry to the death, "include" opens a closed pair of failures, and the sentence still joins two cases. |
| PR 843 | `/changes/0/text` | Accept | 3 | The split keeps every reviewer slot and the shell prohibition. |
| PR 843 | `/changes/2/text` | Accept | 3 | Unnecessary: the original's first sentence has one clause, but the rewrite keeps the order of the retries and the halt. |
| PR 843 | `/criteria/0/promise` | Accept | 3 | Four sentences keep the four assertions. |
| PR 843 | `/criteria/2/promise` | Accept | 3 | The split keeps the three steps and the cost-free refusal of a claim outside them. |
| PR 843 | `/commit/why` | Accept | 3 | The split keeps the agent as the actor and the unsupported belief. |
| PR 843 | `/commit/change` | Correct | 3 | Restore that the configuration holds the settings and the record copies them, because "appear in the configuration and in the record as copies" blurs which is the source, and restore "retries" in the recovery sentence. |
| PR 843 | `/replies/0/verification` | Accept | 3 | The split keeps the failure, the pass and the isolated mutant result. |
| PR 843 | `/replies/1/change` | Accept | 1 | Unnecessary: the original was one clause, but "both" keeps the rule and its tests and the unchanged rule on main. |
| PR 843 | `/replies/2/change` | Accept | 3 | "Location puts it outside" makes the implied cause explicit, the changed-files criterion supports that cause, and the follow-on note remains, although the wording is stiffer than the original. |
| PR 843 | `/replies/2/verification` | Accept | 3 | "Therefore" keeps the schema's unchanged reading as the consequence of no edit. |
| PR 843 | `/replies/3/verification` | Accept | 3 | The split keeps the missing halt key, the later pass and the isolated failure. |
| PR 843 | `/replies/5/change` | Accept | 3 | One predicate keeps the reader and the reason within the two-sentence cap, although "supplies that reader's identity" is stiffer than "names". |
| PR 843 | `/replies/5/verification` | Accept | 3 | Both visibility results stay attributed to the trial, with the count and the unit-test limit. |
| PR 843 | `/replies/6/change` | Accept | 3 | The split keeps the single computation and the reuse across reviewers. |
| PR 843 | `/replies/6/verification` | Accept | 3 | The split keeps five diff calls, the before-and-after result and the other passing tests. |
| PR 843 | `/replies/7/verification` | Accept | 3 | The split keeps the low-effort pin, the holding test and the unexecuted-example limit as the cause of reading by hand. |
| PR 843 | `/replies/8/change` | Correct | 3 | Restore that the refused claim spends no attempt, because "another claim at no attempt cost" moves the exemption to the next claim, and the record shows that an authorized claim spends an attempt. |
| PR 843 | `/replies/8/verification` | Accept | 3 | "Therefore" keeps the ledger order as the reason no attempt is spent. |
| PR 843 | `/replies/9/change` | Accept | 3 | "A run that died with no output" keeps both assertions in one predicate within the two-sentence cap. |
| PR 843 | `/replies/9/verification` | Accept | 3 | The split keeps the new assertion and the before-and-after results. |
| PR 843 | `/replies/11/verification` | Accept | 3 | "Therefore" keeps the absence of a test as the reason for the reading, and the named test stays. |
| PR 843 | `/replies/12/change` | Correct | 3 | Restore "only" on each case, because "accepts only failover or a lower-effort retry" says the gate accepts nothing else, and the record shows it also accepts an initial claim. |
| PR 843 | `/replies/12/verification` | Accept | 3 | The split keeps the authorisation cause, the later pass and the mutant failure. |
| PR 843 | `/replies/13/verification` | Accept | 3 | The adjacent sentence keeps the other two cases under the same mutant, and all four still pass on the unchanged gate. |
| PR 843 | `/replies/15/verification` | Accept | 3 | The split keeps "only", the refusal without guidance and the code comparison as a consequence. |
| PR 843 | `/replies/16/verification` | Accept | 3 | The split keeps the restatement, the agreement, the absent test, the duplicate report and the one change. |
| PR 843 | `/replies/17/verification` | Accept | 3 | The split keeps the duplicate report and the single change. |
| PR 843 | `/replies/18/verification` | Accept | 3 | The split keeps "advisory", "fixed", the reason and the unchanged answers. |
| PR 843 | `/replies/20/change` | Reject | 3 | The rewrite says the section attributes neither direction's exceptional status to a possibility, which presumes the exceptional status the original denies and turns the cause into the thing not attributed. |
| PR 846 | `/pr/title` | Accept | 1 | Unnecessary: "(the reviewers)" adds little to the title, but it is true and the rest of the title is unchanged, and no rule requires the title to match the unedited commit subject. |
| PR 846 | `/summary` | Correct | 3 | Repair "caused that rule's reviewer to have filed", whose perfect infinitive is ungrammatical after "caused" and keeps the protected word only by distorting its tense. The rest keeps the counts and the coverage question. |
| PR 846 | `/heads_up/1` | Accept | 3 | "Therefore" keeps the rule text as the cause of the changed fingerprints. |
| PR 846 | `/risk/rows/1/exposed` | Accept | 3 | The owner and the mistaken belief remain, and the relative clause is gone. |
| PR 846 | `/risk/rows/1/evidence` | Accept | 3 | Unnecessary: "remaining" and "present" only replace "left" and "has", but ten runs per document, the shared settings and the flaw in both versions all remain. |
| PR 846 | `/changes/0/text` | Accept | 3 | The gloss matches the work item's description of the rule, and the split keeps the old opening, the new opening and the routing to coverage. |
| PR 846 | `/changes/1/text` | Accept | 3 | Two sentences keep the added column, the reading unit and the ownership consequence. |
| PR 846 | `/design_notes` | Accept | 3 | Every count stays with its group, "therefore" keeps the reason no record is reopened, and "requirement" is a fair word for what a rule of the standard says. |
| PR 846 | `/criteria/0/promise` | Accept | 3 | The split keeps the open question of whether each criterion names a check. |
| PR 846 | `/criteria/2/promise` | Accept | 3 | The split keeps both thresholds and their populations. |
| PR 846 | `/commit/why` | Accept | 3 | "Therefore" keeps the cause, and "that rule's reviewer" keeps the relationship between the rule and its reviewer. |
| PR 846 | `/commit/change` | Accept | 3 | The gloss and split keep the new opening, the coverage ownership and the reading-unit consequence. |

### Totals

| Fixture | Proposals | Accept | Correct | Reject |
| --- | --- | --- | --- | --- |
| PR 838 | 6 | 6 | 0 | 0 |
| PR 839 | 12 | 12 | 0 | 0 |
| PR 843 | 33 | 28 | 3 | 2 |
| PR 846 | 12 | 11 | 1 | 0 |
| All | 63 | 57 | 4 | 2 |

Five edits are unnecessary but harmless, and all five are accepted, as candidate 4's judgments accepted such edits when they did not make the text worse. They are PR 839 `/criteria/4/promise`, PR 843 `/changes/2/text`, PR 843 `/replies/1/change`, PR 846 `/pr/title` and PR 846 `/risk/rows/1/evidence`.

No correction or rejection turns on a dropped exception or on erased deferred work. Two corrections concern a shifted limit, one concerns a lost source relationship, one concerns grammar, and the two rejections concern changed meaning.

## Close calls

Six verdicts carry the judgment most open to dispute.

- PR 843 `/replies/8/change` is corrected here, yet candidate 4's judgments accepted its near-identical "claimable again at no attempt cost". This judgment differs because the record's finding on an unauthorised transport says an authorized claim spends an attempt, so the exemption cannot belong to the next claim. A reader who takes "at no attempt cost" to describe only the refusal would accept it.
- PR 843 `/replies/12/change` is corrected on the scope of "only". A reader who takes the gate's claim as confined to recovery claims would accept it.
- PR 839 `/criteria/4/promise` is accepted as harmless. "Fails with its name" is not idiomatic, and a reader who finds it worse than the original would reject it, as candidate 4 rejected other needless rewordings of clear text.
- PR 839 `/commit/verification` is accepted although the instructions say to reorder a split that would start a sentence with a number. Candidate 4's judgments accepted the identical "20 content suites pass", and the records themselves open sentences on digits, so the sentence is grammatical house usage. A strict reading of the instruction would correct it.
- PR 843 `/replies/2/change` is accepted although it makes an implied cause explicit. A reader who holds that the location alone does not place the schema outside the change would correct it.
- PR 838 `/commit/change` is accepted although "uses" replaces "keeps". A reader who treats "keeps" as a named relationship would correct it.

## Questions

| Fixture | Index | Section | Judgment |
| --- | --- | --- | --- |
| PR 838 | 0 | `/summary` | Retain: the retained unreachable code is a caveat missing from the Heads-up rows, which name only the tests and the absent review. |
| PR 839 | 0 | `/summary` | Retain: the record's one Heads-up row covers only the absent review, as the question says, and the alias caveat has no row. |
| PR 839 | 1 | `/design_notes` | Retain: the record uses PEP 723 and the tier grid once each and explains neither. |
| PR 843 | 0 | `/summary` | Retain: the unchecked pinned effort lacks its own Heads-up row. |
| PR 843 | 1 | `/design_notes` | Retain: the record defines none of the three terms, and it never lists the files that "those files" must mean. |
| PR 843 | 2 | `/commit/verification` | Retain: the record uses sweep only in its review findings and never defines it for a commit read alone. |
| PR 843 | 3 | `/replies/4/verification` | Retain: the record does not define a sweep or its three named kinds. |
| PR 843 | 4 | `/replies/10/change` | Retain: an author structural question with a correct count of three sentences against a cap of two. |
| PR 843 | 5 | `/replies/15/change` | Retain: an author structural question with a correct count of four sentences against a cap of two. |

Nine questions are retained and none is rejected. PR 846's response asks no question. No question asks about the closing title or subject id, asks to relax a limit, or misstates a count.

### Unresolved questions

All nine questions stay open for the author, because the record supplies no answer to any of them. The judgment of each one is settled, so none is unresolved as a judgment.

## Threshold

| Candidate 5 threshold | Result |
| --- | --- |
| It repairs all four selected defects. | Holds. |
| It keeps all four controls unchanged. | Holds. |
| Every raw response fits the response schema, keeps its record and section digests, and states its exact proposal count. | Fails. The PR 839 response fits neither the schema nor its section digest on `/commit/verification`. All four responses state their exact counts. |
| Every raw response is accepted in full by apply-prose, with no lint finding the editor introduced. | Fails. The PR 839 response was never attempted, so it was not accepted. The other three were accepted with no introduced lint finding. |
| Corrections plus rejections are at most 10% of all candidate 5 proposals across the four fixtures. | Holds on these judgments. Six of 63 proposals is 9.5%, and the limit allows no more than six, so one more correction or rejection would cross it. |

Over the three responses that were applied, the same six are 6 of 51 proposals, or 11.8%. The protocol's denominator is all four fixtures, so that figure changes no result.

## Outcome

Candidate 5 fails the protocol, and that failure stands whatever the semantic count is. It repairs all four necessary edits and leaves all four controls unchanged. It fails on one fault with two consequences: the malformed digest in the PR 839 response fails the schema bullet and leaves that response without the full application the next bullet requires.

The evaluation is failed, the protocol admits no third candidate, and the owner decides the next step. These four runs establish behaviour on these inputs only.
