# Candidate 2 judgments

Evaluator: the implementing Codex agent, after the recorded runs. The fixed protocol and each request's writing checks govern these judgments. These are not owner readability judgments.

Accept identifies a useful meaning-preserving improvement. Correct requires an author repair before application. Reject identifies unnecessary churn. Acceptance does not claim complete compliance with every writing check.

## Proposals

| Fixture | Section | Judgment | Writing check | Basis |
| --- | --- | --- | --- | --- |
| PR 838 | `/summary` | Accept | 3 | Separate sentences retain the routing condition, unreachable rules and retained code. |
| PR 838 | `/heads_up/0` | Reject | 1 | The proposal is identical to the original and offers no improvement. |
| PR 838 | `/commit/why` | Accept | 3 | The split retains the fast-seat outcome and its conflict with the specification. |
| PR 838 | `/commit/verification` | Accept | 3 | Separate assertions retain both gate results, 97 passing checks, six tests, four pre-change failures, retained code and the absent review. |
| PR 839 | `/summary` | Accept | 3 | The rewrite retains the intended-policy qualification, scan exclusions and uncaught aliases while separating the scan from its failure condition. |
| PR 839 | `/risk/rows/0/evidence` | Accept | 3 | Two sentences retain case sensitivity and the clean lint result over 94 files. |
| PR 839 | `/risk/rows/0/recovery` | Accept | 3 | The deletion and its reason remain adjacent as separate assertions. |
| PR 839 | `/changes/0/text` | Accept | 3 | The rewrite retains all three rejection cases and makes their predicates explicit. |
| PR 839 | `/changes/1/text` | Accept | 3 | The patterns and the distinction between family names and ids remain separate assertions. |
| PR 839 | `/changes/2/text` | Accept | 3 | The table conversion and two-table constraint remain intact. |
| PR 839 | `/design_notes` | Correct | 4 | The original has six patterns covering both groups; six patterns plus three more changes that total to nine. |
| PR 839 | `/discovered/rows/0/reason` | Accept | 3 | Separate assertions retain the specification definition and exclusion of aliases. |
| PR 839 | `/criteria/0/promise` | Accept | 3 | Naming the lint clarifies the actor while retaining the rejection and named file and id. |
| PR 839 | `/criteria/2/promise` | Reject | 1 | Changing once to if provides no useful clarification of this already clear trigger. |
| PR 839 | `/criteria/3/promise` | Accept | 1 | Naming the lint clarifies the actor without changing the excluded directory. |
| PR 839 | `/criteria/4/promise` | Accept | 1 | Naming the lint clarifies the actor while retaining both absence cases and the named table. |
| PR 839 | `/criteria/5/promise` | Accept | 3 | Separate sentences retain the rejected table occurrence and accepted prose occurrence. |
| PR 839 | `/criteria/6/promise` | Reject | 3 | The original uses one predicate for its tables and columns; splitting that object list is unnecessary. |
| PR 839 | `/commit/why` | Accept | 1 | Naming the missing check clarifies enforcement while preserving the intended-policy qualification. |
| PR 839 | `/commit/change` | Correct | 3 | The proposal has six sentences where the cap is four; retain the original exhaustive scan scope in the correction. |
| PR 839 | `/commit/verification` | Correct | 4 | Retain the explicitly numbered single seeded id as originally written; the proposal replaces One with An. |
| PR 846 | `/summary` | Correct | 3 | The proposal has six sentences where the cap is five and generalizes what the old rule opening said to the whole rule. |
| PR 846 | `/changes/0/text` | Correct | 1 | Restore that the rule now opens with the check; the proposal drops that location from the claim. |
| PR 846 | `/changes/1/text` | Accept | 3 | Separate sentences retain the added column, its contents and the ownership consequence. |
| PR 846 | `/design_notes` | Correct | 1 | Restore the claim about the old rule opening rather than replacing it with what the rule used to say generally. |
| PR 846 | `/criteria/0/promise` | Accept | 3 | The split retains feasibility, completeness and the routing of coverage questions. |
| PR 846 | `/commit/why` | Correct | 1 | Restore the specific claim about the old opening sentence rather than the whole rule. |
| PR 846 | `/commit/change` | Correct | 1 | Restore that the rule now opens with the check; changing now opens to now judges drops that assertion. |
| PR 846 | `/commit/verification` | Accept | 1 | The revised measurement wording retains the pilot case, both ten-run denominators and the clean prose review. |

Totals: 18 accepted, 8 requiring correction and 3 rejected. The raw candidate fails meaning preservation because corrections are needed; raw outputs are retained unchanged.

## Questions

| Fixture | Index | Section | Judgment |
| --- | --- | --- | --- |
| PR 839 | 0 | `/risk/rows/0/evidence` | Reject: this challenges the adequacy of evidence rather than requesting a fact needed to reword it. |
| PR 839 | 1 | `/changes/1/text` | Retain as an author action, but point at the summary carrying the alias caveat rather than the vendor-pattern section. |
| PR 843 | 0 | `/risk/rows/0/evidence` | Reject: the clean evidence sentence is faithfully editable as written, and this question does not justify omitting independent edits elsewhere. |
