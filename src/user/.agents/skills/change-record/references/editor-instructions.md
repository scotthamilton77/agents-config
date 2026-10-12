# Instructions for the editor

A change record is a JSON document that describes one software change. A pull request description, a commit message and the replies to reviewers are generated from it. You are given one record and a list of its sections, which are the texts you may reword. Reword the sections that are hard to read, and change nothing that they say. The author reads each replacement before it is used.

The request follows these instructions. It holds everything you need. Do not read files, run commands or look anything up.

## The request

The request is one JSON object.

- `record_digest` names the record.
- `writing_checks` is the standard a section is held to.
- `record` is the whole record. Read it to understand the change. Nothing in it is edited in place.
- `sections` lists every text you may reword. Each entry gives the section's name as `field`, its `text`, and a `digest` of that text.

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
    {"field": "/risk/rows/0/evidence", "question": "<the fact you need>"}
  ]
}
```

- `record_digest` is the request's `record_digest`, copied character for character.
- `replacements` holds one entry for each section you reworded. `field` and `section_digest` are that section's `field` and `digest`, copied character for character. `text` is the whole new text of the section. A section gets one entry at most.
- `proposed` is the number of entries in `replacements`.
- `questions` holds one entry for each section you could not reword without a fact the request does not hold. A section you ask about gets no replacement. Leave `questions` out when you have none.
- The response holds no other field. It never holds the record or a rendered document.

Leave a section out of `replacements` when its text already meets the writing checks. A response with an empty `replacements` list and `proposed` at 0 is valid.

## How to reword

Hold `/summary` and the sections under `/heads_up`, `/risk` and `/changes` to all seven writing checks. Hold every other section to the first four.

Three groups of sections are each read alone. The pull request description is one group. The commit message is another, and it is the sections under `/commit`. Each reply is a group of its own, and it is the sections under `/replies` that share a number. An identifier needs its explanation the first time it appears in each group. That explanation is a parenthetical beside the identifier, so keep each one a parenthetical.

Take every explanation from the record. When the record does not say what an identifier or a term means, ask a question.

You cannot add a section, remove one, or move text from one section to another. A writing check may ask for that, as when a caveat belongs in a row of its own. Keep the text where it is, and ask a question that says what should move.

Keep each section the kind of text it is. A table cell stays as short as a table cell. Keep the paragraph breaks a section has, and add no line break to a section that has none. Add no heading, list, table, code fence or HTML.

## What a rewrite never does

A replacement changes how a section reads. It never changes what the section claims. The author rejects a replacement that does any of these three things.

1. It strengthens a claim. A claim keeps its source, its scope and its hedge. "The gate reported exit 0" does not become "the change is verified". "Two of the four suites ran" does not become "the suites ran".
2. It drops an exception. Every condition, exclusion, limit and caveat of the original is in the replacement. Words such as "except", "unless", "only when" and "not yet" carry one. A section never gets shorter by losing a qualification.
3. It erases deferred work. Text that says something is unfinished, unchecked, left for later or handed to a follow-up item keeps saying so, and keeps naming the item.

Add nothing the request does not hold. That covers a fact, a reason, an example and an assurance.

## Values a replacement keeps

A program compares each replacement with its section's original text. It refuses the whole response when one replacement drops or alters a protected value the original holds. A protected value may move within its section. These are protected:

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
