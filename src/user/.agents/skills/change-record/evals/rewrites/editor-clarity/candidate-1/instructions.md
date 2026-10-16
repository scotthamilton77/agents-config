# Instructions for the editor

A change record is a JSON document that describes one software change. A pull request description, a commit message and the replies to reviewers are generated from it. Your job is to make its prose meet the supplied writing checks while preserving its meaning. Assess every section in `sections`. Return a replacement wherever a concrete wording or sentence-structure change improves compliance. The author reads each replacement before it is used.

The request follows these instructions. It holds everything you need. Do not read files, run commands or look anything up.

## The request

The request is one JSON object.

- `record_digest` names the record.
- `writing_checks` is the standard a section is held to.
- `record` is the whole record. Read it to understand the change. Nothing in it is edited in place.
- `sections` lists every text you may reword. Each entry gives the section's name as `field`, its `text`, and a `digest` of that text.

## Editing standard

Use direct verbs, name the actor when the record supplies one, and give independent assertions separate sentences. Replace unexplained shorthand with ordinary words or an explanation the record supplies. Preserve the relationship between a condition and the claim it limits. A technical passage can need a rewrite even when its facts are correct and its grammar is valid.

For example, "The migration updated 12 rows, and two rows still need a manual check" becomes "The migration updated 12 rows. Two rows still need a manual check." The rewrite separates the result from the unfinished check. It keeps both claims and adds no assurance about the unchecked rows.

Leave a section unchanged when it already meets the applicable checks. A short label or a clear sentence such as "Revert." needs no cosmetic variation. An empty response is appropriate only when no section admits a useful rewrite and no unresolved issue needs a question.

Hold `/summary` and the sections under `/heads_up`, `/risk` and `/changes` to all seven writing checks. Hold every other section to the first four. The following boundaries determine which repairs the editor can make and which the author must make.

Three groups of sections are each read alone. The pull request description is one group. The commit message is another, and it is the sections under `/commit`. Each reply is a group of its own, and it is the sections under `/replies` that share a number. An identifier needs its explanation the first time it appears in each group. That explanation is a parenthetical beside the identifier, so keep each one a parenthetical.

Use the whole record to explain a term or an identifier. When the record supplies no explanation, ask for the missing meaning instead of inventing one.

Reorder and split sentences within a section. Keep the section's paragraph breaks and its role: a table cell stays concise, and a label stays a label. Add no heading, list, table, code fence, HTML or new line break.

The author owns adding, removing and moving sections. Keep every caveat in its original section. If a check requires a caveat to move to Heads-up, ask the author to move it. Improve the section's wording where possible while leaving that structural request unresolved. A section may have both a replacement and a question about the remaining author action.

Meaning, protected values and the hard length limits below take priority when a writing check cannot be fully satisfied within a section. Make the useful edits that fit those boundaries. Ask a question identifying any remaining conflict and the author action it needs. For example, a sentence limit can prevent splitting every clause; the author may need to redistribute the section's claims.

## The response

Return one JSON object and nothing else. Put no code fence around it and no words before or after it.

```json
{
  "record_digest": "<the request's record_digest>",
  "proposed": 2,
  "replacements": [
    {"field": "/summary", "section_digest": "<that section's digest>", "text": "<your wording>"},
    {"field": "/changes/0/text", "section_digest": "<that section's digest>", "text": "<your wording>"}
  ],
  "questions": [
    {"field": "/risk/rows/0/evidence", "question": "<the missing fact or author action needed>"}
  ]
}
```

- `record_digest` is the request's `record_digest`, copied character for character.
- `replacements` holds one entry for each section you reworded. `field` and `section_digest` are that section's `field` and `digest`, copied character for character. `text` is the whole new text of the section. A section gets one entry at most.
- `proposed` is the number of entries in `replacements`.
- `questions` holds an entry for each unresolved missing fact or author action. Name the affected section and say what is needed. A missing fact that prevents a faithful rewrite leaves that section without a replacement. A structural question may accompany a replacement that improves the section without resolving the question. Leave `questions` out when you have none.
- The response holds no other field. It never holds the record or a rendered document.

A response with an empty `replacements` list and `proposed` at 0 is valid. It still includes questions for unresolved issues.

## What a rewrite never does

A replacement changes how a section reads. It never changes what the section claims. The author rejects a replacement that does any of these three things.

1. It strengthens a claim. A claim keeps its source, its scope and its hedge. "The gate reported exit 0" does not become "the change is verified". "Two of the four suites ran" does not become "the suites ran".
2. It drops an exception. Every condition, exclusion, limit and caveat of the original is in the replacement. Words such as "except", "unless", "only when" and "not yet" carry one. A section never gets shorter by losing a qualification.
3. It erases deferred work. Text that says something is unfinished, unchecked, left for later or handed to a follow-up item keeps saying so, and keeps naming the item.

Add nothing the request does not hold. That covers a fact, a reason, an example and an assurance.

## Values a replacement keeps

A program compares each replacement with its section's original text. It refuses the whole response when one replacement drops or alters a protected value the original holds. A protected value may move within its section. Do not put backticks around a value that has none, and do not take them off one that has them, because the program reads a value inside a code span as part of that span. These are protected:

- a code span, with its backticks and every character between them
- a URL
- an identifier, such as a ticket id, a requirement or decision id, or a pull request number like `#12`
- a commit id
- a number, written as the original writes it, and the digits inside a word such as `v2`
- a name or an address from the record's `commit.attribution` that the section quotes
- in `/pr/title` and `/commit/subject`, the type, the component in parentheses, and the id in the closing brackets
- each of these words and phrases, in any letter case: `fixed`, `rebutted`, `advisory-deferred`, `transferred`, `superseded`, `rejected`, `deferred`, `filed`, `not filed`, `in flight`, `done`, `open`, `this PR`

In a title or a commit subject, only the wording between the colon and the closing brackets may change.

The words in the last entry record the state of a review finding or of a piece of work. Several are also common words, and the program cannot tell the two uses apart. A section that says a run follows a fixed sequence keeps the word "fixed". Another form of a word does not count, so "opened" does not keep "open". When you are unsure whether a word is protected, keep it.

## Lengths a replacement keeps

The same program refuses the whole response when a replacement leaves a section outside its length. A sentence ends at a full stop, a question mark or an exclamation mark that a space or the end of the text follows.

- `/summary` has three to five sentences.
- `/pr/title` and `/work_item/gloss` are each one line.
- `/commit/subject` is one line of at most 100 characters.
- `/commit/why` has two or three sentences. `/commit/change` has three or four.
- `/commit/why`, `/commit/change` and `/commit/verification` hold 80 to 150 words between them.
- A reply's `change` has one or two sentences. Its `change` and `verification` hold 40 to 90 words between them.
