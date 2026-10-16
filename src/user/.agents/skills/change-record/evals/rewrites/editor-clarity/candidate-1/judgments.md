# Candidate 1 judgments

Assessed on 2026-10-15 by the implementing Codex agent against the fixed
protocol and each request's writing checks. These are agent judgments. The
owner has not supplied readability judgments.

## Selected cases

| Fixture | Necessary edit | Result | Control |
| --- | --- | --- | --- |
| PR 838 | `/risk/rows/0/evidence` | Missed. The editor omits the section, leaving test coverage and pre-change failures in one sentence. | Unchanged. |
| PR 839 | `/risk/rows/0/evidence` | Repaired. Two sentences retain case sensitivity and the clean run over 94 files. | Unchanged. |
| PR 843 | `/criteria/0/promise` | Missed. The editor omits the section, leaving all four assertions in one sentence. | Unchanged. |
| PR 846 | `/changes/1/text` | Repaired. Separate sentences retain the added column, its contents and the ownership consequence. | Unchanged. |

The selected-case result is 2 of 4 repairs and 4 of 4 controls unchanged. A
question about the PR 843 control creates unnecessary author work, although
the control's text stays unchanged. The required repair threshold fails.

## Proposed replacements

Accept means a useful improvement that preserves the section's claims.
Correct means the author must repair a proposal before applying it. Reject
means the proposal offers no useful improvement or should be discarded.
Acceptance here does not assert that every sentence satisfies every check.

| Fixture | Section | Judgment | Writing check | Basis |
| --- | --- | --- | --- | --- |
| PR 838 | `/summary` | Accept | 3 | Separating unreachable escalation from retained code keeps the routing condition and unfinished cleanup explicit. |
| PR 838 | `/changes/0/text` | Accept | 5 | Naming the expert as actor makes the routing outcome direct; the record supplies the expert's role. |
| PR 838 | `/changes/1/text` | Accept | 1 | Leading the second sentence with its channel condition clarifies where heavy effort remains. |
| PR 839 | `/summary` | Correct | 1 | Restore the intended-policy qualification: a table that is meant to be the sole inventory is not evidence that the skill already uses it exclusively. |
| PR 839 | `/risk/rows/0/failure` | Accept | 3 | Separating rejection from its blocking consequence retains both possible failure outcomes within the risk row. |
| PR 839 | `/risk/rows/0/exposed` | Reject | 1 | Replacing "opening" with "who opens" supplies no missing meaning and does not improve this concise table cell. |
| PR 839 | `/risk/rows/0/evidence` | Accept | 3 | Separating the assertions repairs the selected defect while retaining case sensitivity and 94 files. |
| PR 839 | `/risk/rows/0/recovery` | Accept | 3 | Separate sentences retain both the deletion instruction and the reason that the file ships nothing. |
| PR 839 | `/risk/rows/1/failure` | Correct | 1 | Keep "still" so the proposal preserves the original statement that this risk remains after the change. |
| PR 839 | `/risk/rows/1/exposed` | Reject | 1 | The original clearly identifies projects with installed copies; changing it to an installation action offers no improvement and makes the population less precise. |
| PR 839 | `/changes/0/text` | Accept | 3 | Three sentences retain all three rejection cases without changing their scope. |
| PR 839 | `/changes/1/text` | Accept | 3 | Separate sentences retain the vendor patterns and distinction between a family name and a model id. |
| PR 839 | `/changes/2/text` | Accept | 3 | The table conversion and its two-table constraint remain adjacent as separate assertions. |
| PR 839 | `/commit/change` | Correct | 3 | The split produces five sentences where the hard limit is four; preserve all three rejection cases in a compliant rewrite. |
| PR 839 | `/commit/verification` | Accept | 3 | Separating uncaught aliases from the absent review round retains the qualifications and every reported count. |
| PR 843 | `/summary` | Correct | 1 | Restore the protected word "fixed" and the fixed nature of the recovery sequence; the raw replacement is mechanically refused. |
| PR 843 | `/heads_up/0` | Accept | 3 | Separate sentences retain the system-bash setting and the Homebrew-bash failure that explains it. |
| PR 843 | `/heads_up/1` | Accept | 3 | Separate sentences retain the reviewed commit and the four subsequent prose-only commits. |
| PR 843 | `/heads_up/2` | Accept | 5 | Naming the machine as holder retains the 27 raw answers, their purpose and their location outside the repository. |
| PR 843 | `/risk/rows/0/failure` | Accept | 1 | "Effort level" clarifies the setting while retaining the risk of incompatible effort or tools. |
| PR 843 | `/changes/2/text` | Accept | 3 | Separating the retries retains the effort reduction, provider change and stated halt condition without adding an assurance. |
| PR 846 | `/summary` | Correct | 1 | Restore the coverage rule's name and the qualification that the second rule now judges only the check; both matter to the scope of the change. |
| PR 846 | `/heads_up/1` | Accept | 3 | Separate sentences retain the changed fingerprints and explicitly preserve their cause. |
| PR 846 | `/risk/rows/0/evidence` | Reject | 1 | The replacement is byte-identical to its original and provides no improvement. |
| PR 846 | `/risk/rows/1/evidence` | Accept | 1 | The clearer referents retain the ten runs per document, shared settings and flaw in both versions. |
| PR 846 | `/changes/0/text` | Correct | 1 | Restore that the rule now opens with the check and remove the added assertion about its reviewer; the proposal changes this section's set of claims. |
| PR 846 | `/changes/1/text` | Accept | 3 | Separate sentences retain the added column and the link between what a reviewer reads and rule ownership. |

Of 27 actual replacements, 18 are accepted, 6 need correction and 3 are
rejected. The six corrections include semantic preservation, protected-value
preservation and a hard sentence limit. None of the accepted proposals
strengthens a reported check into a verification assurance, drops an
exception or erases deferred work. The identified qualifications and omissions
in the corrected proposals remain failures of the raw output.

## Questions

Question numbers below are zero-based positions in each raw response. A
structural request can be valid without being necessary. Requests that
duplicate an existing row, challenge the author's evidence, or apply the
Heads-up rule to a standalone commit do not help the bounded editing task.

| Fixture | Question | Section | Disposition and basis |
| --- | --- | --- | --- |
| PR 838 | 0 | `/summary` | Retain as an author action under check 7: retained escalation code is a caveat that can receive a separate Heads-up row. |
| PR 838 | 1 | `/heads_up/0` | Reject as a duplicate of question 0; the existing row describes test changes and should not absorb another caveat. |
| PR 838 | 2 | `/design_notes` | Reject as unnecessary structural expansion; this section takes the first four checks, and question 0 already covers the summary's retained-code caveat. |
| PR 838 | 3 | `/commit/verification` | Reject: moving the commit's qualification to PR Heads-up would not preserve the standalone commit's meaning; check 7 does not apply to commit fields. |
| PR 839 | 0 | `/heads_up/0` | The alias caveat is a reasonable author action under check 7, but the pointer names an excluded generator row rather than the affected editable summary. |
| PR 839 | 1 | `/risk/rows/0` | Reject as an evidence review rather than a missing fact needed for faithful wording; the pointer also names a row object instead of a listed section. |
| PR 839 | 2 | `/risk/rows/1` | Reject as a more specific version of the alias request with an unlisted row pointer; the editor should retain the recorded alias limit without inventing another failure scenario. |
| PR 843 | 0 | `/risk/rows/0/evidence` | Reject as unnecessary evidence review; the sentence is already clear and the editor can preserve its limited claim without proving compatibility. |
| PR 843 | 1 | `/changes/2/text` | Reject as written: it says a condition was omitted to satisfy a sentence rule without support for that explanation, and asks to move a condition absent from the section. |
| PR 846 | 0 | `/summary` | Reject as redundant: the untracked run records already have their own Heads-up row. |
| PR 846 | 1 | `/risk/rows/0/evidence` | Reject as redundant and mislocated: fingerprint changes already have their own Heads-up row and do not qualify this evidence cell. |

Only the PR 838 summary request remains a direct unresolved author action.
The PR 839 alias request needs its pointer corrected before it is actionable.
The other nine questions should be discarded. They do not count as repairs
of the selected defects.
