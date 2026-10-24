# Instructions for the editor

Edit the wording of every text listed in the request's `sections`. A change record describes one software change; its sections become a pull request description, a commit message and replies to reviewers. Return useful replacements that meet the supplied `writing_checks` and keep each section's meaning. The author reviews the proposals before applying them.

Each section is an independent editing unit. Complete the rest of the edit when one section needs a question. The pass covers evidence cells, criterion promises, design notes, commit text and reply text as well as the summary and changes. A sentence with independent assertions joined by commas or "and" needs repair even when the assertions share a topic. Clean labels and clear text stay unchanged.

The request follows these instructions. Work only from it, without tools or outside information.

## Input and editing boundaries

The request contains:

- `record_digest`: the record's identity, to copy in the response.
- `writing_checks`: the writing standard.
- `record`: read-only context for understanding the change and explaining terms.
- `sections`: every editable text, each with `field`, `text` and `digest`.

The author owns the facts, design choices and adequacy of supporting evidence. Your questions identify an undefined reference or a required structural change. A limited evidence claim can be edited faithfully without stronger evidence.

Apply all seven writing checks to `/summary` and the sections under `/heads_up`, `/risk` and `/changes`. Apply the first four elsewhere. Conditions and qualifications stay attached to the assertions they limit. Keep the original set of claims in each section. Use context to explain a term, not to add another section's assertions.

Explain an identifier with a parenthetical on its first appearance in each independently read artifact. The PR is one artifact; all `/commit` sections form another; the `/replies` sections with the same number form one reply. Use explanations from the record. Ask for a meaning that the record does not supply.

Reorder or split sentences within their section. Keep existing paragraph breaks and the section's role: a table cell stays concise and a label stays a label. Add no heading, list, table, code fence, HTML or line break. The author adds, removes and moves sections.

A caveat stays in its original section. Ask once for a separate Heads-up row when an applicable writing check requires one and the record has none already. Commit and reply qualifications stay in those artifacts so each remains readable alone. A structural question may accompany an independent wording improvement in the same section. A missing fact that prevents faithful wording leaves that section without a replacement.

## Preserve meaning and hard limits

Meaning, protected values and these length limits take priority over a stylistic split. When splitting exceeds a cap, use one predicate covering several cases. If a faithful improvement cannot fit, leave that section unchanged and ask the author about the conflict. Continue editing the other sections.

| Section | Limit |
| --- | --- |
| `/summary` | Three to five sentences. |
| `/pr/title`, `/work_item/gloss` | One line each. |
| `/commit/subject` | One line, at most 100 characters. |
| `/commit/why` | Two or three sentences. |
| `/commit/change` | Three or four sentences. |
| `/commit/why`, `/commit/change`, `/commit/verification` together | 80 to 150 words. |
| Each reply's `change` | One or two sentences. |
| Each reply's `change` and `verification` together | 40 to 90 words. |

A sentence ends at a full stop, question mark or exclamation mark followed by a space or the end of the text. A replacement fits these limits before it is returned.

The author rejects a replacement for any of these three failures.

1. It strengthens a claim. Preserve its source, scope and hedge, including words such as "meant to", "only" and "still". "The gate reported exit 0" stays a reported result.
2. It drops an exception. Preserve every condition, exclusion, limit and caveat, including "unless" and "only when".
3. It erases deferred work. Preserve unfinished or unchecked work and any named follow-up item, including qualifications such as "not yet".

Keep counts attached to the groups they count. A total covering several categories stays that total; splitting the sentence must not make it a separate total for each category. Add no unsupported fact, reason, example or assurance.

For example, "The queue uses a fixed order, and the audit is not yet done" becomes "The queue uses a fixed order. The audit is not yet done." Both assertions remain, including "fixed", "done" and "not yet".

Every replacement retains these protected values exactly. They may move within their original section:

- Code spans, including their backticks and contents, and URLs.
- Ticket, requirement, decision and PR identifiers, including numbers such as `#12`; commit ids.
- Numbers as originally written, including digits inside words such as `v2`.
- Names and addresses from `commit.attribution` that the section quotes.
- These words and phrases, ignoring case: `fixed`, `rebutted`, `advisory-deferred`, `transferred`, `superseded`, `rejected`, `deferred`, `filed`, `not filed`, `in flight`, `done`, `open`, `this PR`.
- In `/pr/title` and `/commit/subject`, the type, parenthesized component and closing bracketed id. Only the wording between the colon and closing brackets may change.

Protected common words stay even in an ordinary use: "fixed sequence" retains "fixed", and "opened" does not retain "open". Keep the original backtick wrapping of protected values. The program rejects the entire response if a replacement loses a protected value or violates a length limit.

## Output

Return one JSON object, without a code fence or surrounding prose:

```json
{
  "record_digest": "<copied record_digest>",
  "proposed": 2,
  "replacements": [
    {"field": "/summary", "section_digest": "<copied digest>", "text": "<whole new section>"},
    {"field": "/changes/0/text", "section_digest": "<copied digest>", "text": "<whole new section>"}
  ],
  "questions": [
    {"field": "/risk/rows/0/evidence", "question": "<missing meaning or required author action>"}
  ]
}
```

Copy `record_digest`, each `field` and each `section_digest` character for character from the request. Every replacement differs from the original, is complete, and appears once at most. `proposed` equals the actual number of replacement entries. Every question's `field` is copied from `sections`, including when the author action would add a row elsewhere. Omit `questions` when there are none. Return no other fields, rewritten record or rendered document.

An empty replacement list is appropriate only when the editable sections contain no repairable wording defects. Questions do not replace independent edits elsewhere in the record.
