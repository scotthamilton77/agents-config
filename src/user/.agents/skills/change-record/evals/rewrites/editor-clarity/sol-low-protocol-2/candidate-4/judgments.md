# Candidate 4 judgments

Assessment date: 2026-10-16. Evaluator: the implementing Claude agent, after the recorded runs. The protocol beside this directory and each request's writing checks govern these judgments. These are not owner readability judgments.

Accept means a useful, meaning-preserving improvement. Correct requires an author repair before application. Reject identifies a proposal that should not be applied, because it changes meaning or makes clear text worse. Acceptance does not establish compliance with every writing check. Raw outputs remain unchanged.

## Runs

All four calls exited 0 with no tool use and an empty standard error. Calls took 37.4 to 99.1 seconds. Each response fits the response schema, keeps its digests, reports an exact proposal count, names only editable sections and proposes no identical replacement.

| Fixture | Replacements | Questions | Full raw application |
| --- | --- | --- | --- |
| PR 838 | 10 | 7 | Accepted. |
| PR 839 | 18 | 2 | Accepted. |
| PR 843 | 38 | 9 | Accepted. |
| PR 846 | 18 | 3 | Refused: `/summary`, `/design_notes` and `/commit/why` drop the protected word `filed`. Lint also reports a 101-character `/commit/subject`, where the limit is 100. |

## Selected cases

| Fixture | Necessary edit | Outcome | Control | Outcome |
| --- | --- | --- | --- | --- |
| PR 838 | `/risk/rows/0/evidence` | Repaired: the coverage and the pre-change failures are separate sentences. | `/risk/rows/0/recovery` | Unchanged. |
| PR 839 | `/risk/rows/0/evidence` | Repaired: case sensitivity and the clean run over 94 files are separate sentences. | `/risk/rows/1/recovery` | Unchanged. |
| PR 843 | `/criteria/0/promise` | Repaired: the four assertions are four sentences. | `/risk/rows/1/recovery` | Unchanged. |
| PR 846 | `/changes/1/text` | Repaired: the new column and the ownership consequence are separate sentences. | `/risk/rows/0/recovery` | Unchanged. |

Selected-case result: 4 of 4 repairs and 4 of 4 unchanged controls.

## Proposals

| Fixture | Section | Judgment | Writing check | Basis |
| --- | --- | --- | --- | --- |
| PR 838 | `/summary` | Accept | 3 | The split keeps the routing condition, the unreachable rules and the retained code. |
| PR 838 | `/heads_up/0` | Accept | 1 | Selecting an option is the plain form of an option pick, and the thread case remains. |
| PR 838 | `/risk/rows/0/evidence` | Accept | 3 | Two sentences keep six covering tests and four pre-change failures. |
| PR 838 | `/risk/rows/1/failure` | Accept | 1 | Naming the answer's route clarifies the unchanged risk. |
| PR 838 | `/risk/rows/1/evidence` | Accept | 1 | The expanded referent keeps the existing test and the no-task assertion. |
| PR 838 | `/changes/2/text` | Accept | 1 | Spelling out specification keeps the three passages and the expert's weighing. |
| PR 838 | `/discovered/rows/0/reason` | Accept | 1 | The record's discovered row supplies both objects that the pronoun named. |
| PR 838 | `/criteria/0/promise` | Accept | 3 | Three sentences keep the same qualified answer as their subject. |
| PR 838 | `/commit/why` | Accept | 3 | The split keeps the fast-seat routing and its conflict with the seating decision. |
| PR 838 | `/commit/verification` | Accept | 3 | The split keeps both gates, 97 passing, six tests, four earlier failures, the retained code and the absent review. |
| PR 839 | `/work_item/gloss` | Accept | 1 | The record's design notes identify the lint as a pytest suite, so the test names the same object. |
| PR 839 | `/summary` | Accept | 3 | Five sentences keep the intended-policy hedge, both scan exclusions and the uncaught aliases. |
| PR 839 | `/risk/rows/0/failure` | Accept | 5 | The rewrite keeps the false-positive rejection and its blocking consequence. |
| PR 839 | `/risk/rows/0/evidence` | Accept | 3 | The split keeps case sensitivity and the clean run over 94 files. |
| PR 839 | `/risk/rows/0/recovery` | Accept | 3 | The deletion and its reason stay adjacent as separate assertions. |
| PR 839 | `/risk/rows/1/evidence` | Accept | 3 | The exit status and the named line stay attributed to the appended id. |
| PR 839 | `/changes/0/topic` | Accept | 1 | The topic names the same suite that the record calls the lint. |
| PR 839 | `/changes/0/text` | Accept | 3 | Three sentences keep the inventory, other-table and routing-shape failures. |
| PR 839 | `/changes/1/text` | Accept | 3 | The split keeps the vendor patterns and their consequence for family names. |
| PR 839 | `/changes/2/text` | Accept | 3 | Reordering keeps the two-table allowance as the cause of the conversion. |
| PR 839 | `/discovered/rows/0/reason` | Correct | 3 | Restore that an alias is not an id; the rewrite states only the premise that an alias follows no vendor scheme. |
| PR 839 | `/criteria/0/promise` | Accept | 3 | The split keeps the scanned-file scope and the naming of both file and id. |
| PR 839 | `/criteria/1/promise` | Accept | 1 | The landed repository tree is the same tree. |
| PR 839 | `/criteria/2/promise` | Accept | 1 | The record identifies the removed row as the routing-table entry, and the code-block gloss is accurate. |
| PR 839 | `/criteria/4/promise` | Accept | 3 | The split keeps the absent and empty cases and the named table. |
| PR 839 | `/criteria/5/promise` | Accept | 3 | The split keeps rejection outside the routing table and acceptance in prose. |
| PR 839 | `/commit/change` | Accept | 3 | Four sentences keep every exclusion, all three failure classes and the conversion's cause. |
| PR 839 | `/commit/verification` | Correct | 1 | Remove the stub-lint gloss; the record never says the stub returns no files or violations. |
| PR 843 | `/summary` | Accept | 1 | Both glosses match the record's meaning of the diff file and the pinned effort. |
| PR 843 | `/heads_up/0` | Accept | 3 | The hang leads, the PATH gloss is conventional, and the causal link remains. |
| PR 843 | `/heads_up/1` | Correct | 3 | The second sentence starts with lowercase "four"; reorder or rephrase so the sentence begins correctly. |
| PR 843 | `/heads_up/2` | Accept | 5 | The rewrite keeps all 27 answers and their location outside the repository. |
| PR 843 | `/risk/rows/0/evidence` | Accept | 1 | The record defines a pin as configured effort and tools; this cell is not a control under this protocol. |
| PR 843 | `/risk/rows/1/failure` | Accept | 3 | The alternatives remain an out-of-sequence retry or a round that never stops. |
| PR 843 | `/changes/0/text` | Accept | 3 | The split keeps every reviewer slot and the shell prohibition. |
| PR 843 | `/changes/1/text` | Accept | 1 | The record describes the emitter as what writes the prompts. |
| PR 843 | `/changes/2/text` | Accept | 3 | The split keeps the ordered retries and the halt. |
| PR 843 | `/design_notes` | Correct | 1 | Restore the comma or rephrase so slice B is the later work that adds the pins, not a holder of the same pins. The other paragraphs keep their claims. |
| PR 843 | `/discovered/rows/0/reason` | Accept | 1 | The record's row supplies the comparison the pronoun named. |
| PR 843 | `/discovered/rows/1/reason` | Accept | 1 | The record names the read-evidence gate. |
| PR 843 | `/discovered/rows/2/reason` | Accept | 1 | The record names the skill file. |
| PR 843 | `/discovered/rows/3/reason` | Accept | 1 | The record names the two advisory review findings. |
| PR 843 | `/criteria/0/promise` | Accept | 3 | Four sentences keep the four assertions. |
| PR 843 | `/criteria/1/promise` | Accept | 1 | The gloss matches the record's doctrine files and keeps all three reached targets. |
| PR 843 | `/criteria/2/promise` | Accept | 3 | The split keeps the step-down, the other provider, the halt and the cost-free refusal. |
| PR 843 | `/commit/why` | Accept | 2 | The problem leads and all three assertions remain. |
| PR 843 | `/commit/change` | Correct | 3 | Restore that the configuration holds effort and tools for every slot as its own assertion, and repair the ungrammatical "follows retries". |
| PR 843 | `/commit/verification` | Correct | 1 | Restore the clean sweep; a round with no findings drops that named review phase. The terminal-commit gloss is supported by the campaign record. |
| PR 843 | `/replies/0/verification` | Accept | 3 | The test gloss and split keep the failure, the pass and the isolated mutant result. |
| PR 843 | `/replies/1/change` | Accept | 1 | The gloss and wording keep both deletions and the unchanged rule on main. |
| PR 843 | `/replies/2/verification` | Accept | 1 | The finding record supplies the schema's meaning for transport-failure. |
| PR 843 | `/replies/3/verification` | Accept | 3 | The split keeps the missing halt key, the later pass and the isolated failure. |
| PR 843 | `/replies/4/verification` | Accept | 1 | The mutant gloss is accurate and sweep keeps its name. |
| PR 843 | `/replies/5/verification` | Accept | 3 | Both visibility results stay attributed to the trial, with the count and the unit-test limit. |
| PR 843 | `/replies/6/verification` | Accept | 3 | The split keeps five diff calls, the before-and-after result and the other passing tests. |
| PR 843 | `/replies/7/verification` | Accept | 3 | The split keeps the low-effort pin and the unexecuted-example limit. |
| PR 843 | `/replies/8/change` | Accept | 1 | The refusal glosses match the record, and both refusal kinds stay correctable at no cost. |
| PR 843 | `/replies/8/verification` | Accept | 3 | The split keeps refusal before the ledger write and no attempt cost. |
| PR 843 | `/replies/9/verification` | Accept | 3 | The split keeps the new assertion and the before-and-after results. |
| PR 843 | `/replies/10/verification` | Accept | 3 | The split keeps the untested comment, the doctrine comparison and the fixed failover slot. |
| PR 843 | `/replies/11/verification` | Accept | 3 | The split keeps the untested docstring, the code comparison and the named test. |
| PR 843 | `/replies/12/change` | Accept | 1 | Restricting to each case keeps both "only" limits and the free refusal of a third transport. |
| PR 843 | `/replies/12/verification` | Accept | 3 | The split keeps the authorisation cause, the later pass and the mutant failure. |
| PR 843 | `/replies/13/verification` | Accept | 3 | The split keeps two failing and two passing cases and all four passing on the unchanged gate. |
| PR 843 | `/replies/17/verification` | Accept | 3 | Three sentences keep the absent prose test, the duplicate report and the single change. |
| PR 843 | `/replies/18/verification` | Accept | 3 | The split keeps the advisory status, the reason, the unchanged answers and the absent prose test. |
| PR 846 | `/pr/title` | Reject | 1 | Filing gaps by one rule changes filing them under one rule, and the reviewers gloss adds nothing the title needs. |
| PR 846 | `/summary` | Correct | 3 | Restore the protected word `filed`; the application refuses the response. The rest keeps the counts and the coverage question. |
| PR 846 | `/heads_up/0` | Accept | 5 | The machine as subject keeps the untracked location of the run records. |
| PR 846 | `/risk/rows/0/exposed` | Correct | 1 | Restore specifications attacked with the standard; reviewed by the panel names a broader population. |
| PR 846 | `/risk/rows/1/exposed` | Reject | 1 | The original was clear, and the rewrite obscures who believes what. |
| PR 846 | `/risk/rows/1/evidence` | Accept | 1 | The rewrite keeps ten runs per document, shared settings and the flaw in both versions. |
| PR 846 | `/risk/rows/1/recovery` | Accept | 1 | The gloss matches the record's measurement on a defective document and a corrected control. |
| PR 846 | `/changes/0/text` | Accept | 3 | The rule gloss and split keep the old opening, the new opening and the routing to coverage. |
| PR 846 | `/changes/1/text` | Accept | 3 | Two sentences keep the added column, the reading unit and the ownership consequence. |
| PR 846 | `/design_notes` | Correct | 3 | Restore the protected word `filed`, and restore that no attack record is reopened because the check binds to the revision; the split drops that cause. |
| PR 846 | `/criteria/0/promise` | Accept | 3 | The split keeps the open question of whether each criterion names a check. |
| PR 846 | `/criteria/1/promise` | Accept | 1 | The reading unit is the record's term for what each reviewer reads. |
| PR 846 | `/criteria/2/promise` | Accept | 3 | The split keeps both thresholds and their populations. |
| PR 846 | `/criteria/3/promise` | Reject | 4 | Inverting a clear exit-status statement makes it harder to read. |
| PR 846 | `/commit/subject` | Reject | 1 | The subject is 101 characters where the limit is 100, and it carries the title's change of meaning. |
| PR 846 | `/commit/why` | Correct | 3 | Restore the protected word `filed`; the application refuses the response. |
| PR 846 | `/commit/change` | Accept | 3 | The split keeps the new opening, the coverage ownership and the reading-unit consequence. |
| PR 846 | `/commit/verification` | Correct | 4 | Restore "make ci exits 0"; the inverted sentence reads worse. The measurements and the clean prose round remain. |

Totals: 69 accepted, 11 requiring correction and 4 rejected, across 84 proposals.

## Questions

| Fixture | Index | Section | Judgment |
| --- | --- | --- | --- |
| PR 838 | 0 | `/summary` | Retain: the retained unreachable code is a caveat missing from the Heads-up rows. |
| PR 838 | 1 | `/changes/1/text` | Retain: the record does not define the effort levels. |
| PR 838 | 2 | `/design_notes` | Retain: the effort levels and the two readings are undefined in the record. |
| PR 838 | 3 | `/criteria/1/promise` | Retain, as a repeat of the task-effort question for this section. |
| PR 838 | 4 | `/criteria/2/promise` | Retain, as a repeat of the heavy-effort question for this section. |
| PR 838 | 5 | `/criteria/3/promise` | Retain, as a repeat of the task-effort question for this section. |
| PR 838 | 6 | `/commit/change` | Retain: the commit is read alone and the terms are undefined. |
| PR 839 | 0 | `/summary` | Retain the alias row. The second row is an author choice; the directory exclusion is scope, not a caveat. |
| PR 839 | 1 | `/design_notes` | Retain: the record does not explain PEP 723 or the tier grid. |
| PR 843 | 0 | `/summary` | Retain: the unchecked pinned effort lacks its own Heads-up row. |
| PR 843 | 1 | `/design_notes` | Retain: the record does not define these terms. |
| PR 843 | 2 | `/replies/2/change` | Retain: an author structural question with a counted split and a named claim to move. |
| PR 843 | 3 | `/replies/4/change` | Retain: the record defines neither the tier categories nor the sweep. |
| PR 843 | 4 | `/replies/5/change` | Retain: the record does not list all five files. |
| PR 843 | 5 | `/replies/6/change` | Reject: the question concedes the edit fits and asks permission for a gloss the record's description of the function supports. |
| PR 843 | 6 | `/replies/9/change` | Retain: an author structural question with a counted split. |
| PR 843 | 7 | `/replies/10/change` | Retain: an author structural question with a counted split. |
| PR 843 | 8 | `/replies/15/change` | Retain: an author structural question with a counted split. |
| PR 846 | 0 | `/heads_up/1` | Retain: the record does not define the fingerprint. |
| PR 846 | 1 | `/changes/1/text` | Retain: the record names the attack skill without defining it. |
| PR 846 | 2 | `/risk/rows/1/evidence` | Retain: the residual control objection lacks its own Heads-up row. |

Twenty questions are retained and one is rejected. No question asks about the closing title or subject id, asks to relax a limit, or misstates a count.

## Outcome

Candidate 4 fails the protocol. It repairs all four necessary edits and leaves all four controls unchanged. It fails on three grounds:

1. The PR 846 response fails full raw application. Three sections drop the protected word `filed`, and the subject exceeds 100 characters.
2. Eleven proposals need correction and four are rejected, so the meaning-preservation check fails in PRs 839, 843 and 846.
3. Each failure in the first two grounds is one the instructions already forbid in plain words. These include protected common words, the subject limit, keeping named phases, unsupported explanations and leaving clear text unchanged.

The evaluation stays pending, and the protocol permits candidate 5.
