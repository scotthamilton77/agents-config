# The rewrite pass

An editor may reword a record's wording and none of its facts. The pass has three steps:

1. `extract-prose` writes a request that lists what may be reworded.
2. An editor returns a response that holds a replacement for each field it reworded.
3. The author takes out each replacement they do not accept, and `apply-prose` applies the rest.

Both subcommands only read and write files. Neither calls GitHub, the tracker or any other program.

## What an editor may reword

A section is one field the schema marks `x-rewritable`. It is named by its path in the record, as in `/summary` or `/changes/0/text`. `fields.md` beside this file says which fields carry the mark. The request lists every section, and a replacement for anything else is refused.

Three kinds of marked text are not sections:

- a heads-up row that opens with a generator's name and a colon, which is the generator's
- the `"None."` entry of an empty heads-up list, which is no prose
- the reason of a filed row of discovered work, which is the tracker's

## `extract-prose`

```bash
uv run scripts/change_record.py extract-prose record.json [--output FILE]
```

`extract-prose` writes the request to stdout, or to the file `--output` names. The record must fit the schema.

```json
{
  "record_digest": "9f2c…",
  "writing_checks": "All seven apply to the summary, …",
  "record": {"pr": {}, "summary": "…"},
  "sections": [
    {"field": "/summary", "text": "…", "digest": "5d41…"},
    {"field": "/changes/0/text", "text": "…", "digest": "7b0e…"}
  ]
}
```

- `record_digest` is the record's digest, which `commands.md` beside this file describes under the record comment.
- `writing_checks` is the writing checks section of this skill's own text, read when the command runs. The command fails and names the file when the file holds no such section.
- `record` is the whole record. It is there to be read, and nothing in it is edited in place.
- `sections` gives each section's path as `field`, its `text`, and `digest`, the SHA-256 digest of that text as UTF-8.

Exit 0 written, 1 the record does not fit the schema, 2 unreadable or unparseable, the output file cannot be written, or the skill's text states no writing checks.

## The response

`prose-response.schema.json` beside this file defines the response.

```json
{
  "record_digest": "9f2c…",
  "proposed": 2,
  "replacements": [
    {"field": "/summary", "section_digest": "5d41…", "text": "The editor's wording."},
    {"field": "/changes/0/text", "section_digest": "7b0e…", "text": "The editor's wording.", "corrected": "The author's wording."}
  ],
  "questions": [
    {"field": "/risk/rows/0/evidence", "question": "Which test shows that it did not happen?"}
  ]
}
```

The editor writes these:

- `record_digest`, copied from the request.
- One entry in `replacements` for each section it reworded. `section_digest` is that section's `digest`, copied from the request.
- `proposed`, the number of replacements it returned. Once an entry is gone, nothing can check that number beyond its not being lower than the number of entries left.
- One entry in `questions` for each section it could not reword without inventing a fact. `questions` may be left out.

The author then decides, and edits the response in two ways only:

- To reject a replacement, delete its entry. Leave `proposed` as it is.
- To change a replacement, add `corrected` with the wording to apply. Leave `text` as the editor wrote it.

The script cannot judge meaning. Read each replacement against its section for a claim made stronger, an exception dropped, or deferred work that is no longer mentioned.

## `apply-prose`

```bash
uv run scripts/change_record.py apply-prose record.json response.json
```

`apply-prose` checks the whole response before it writes anything. One refused replacement refuses the response, wherever it stands in the list, and the record file stays byte for byte as it was. A refusal prints the JSON result on stderr, in the form `lint` prints. The record must fit the schema, as it must for `extract-prose`. The response is refused under these codes:

| Code | What is refused |
| --- | --- |
| `response-schema` | A response that does not fit its schema. A fault inside an entry names the entry's section. |
| `stale-record` | A `record_digest` that is not the record's digest. The response was written against another record. |
| `stale-section` | A `section_digest` that is not the digest of the section's text now. A second replacement for one section fails here too. |
| `not-rewritable` | A `field` that names no section. |
| `protected-value` | Applied wording that drops or changes a protected value its section holds. The message names the value. |
| `proposed-count` | More entries in `replacements` than `proposed` says the editor returned. |
| `one-pass` | A response that holds a replacement, while the record's revision is one a rewrite pass produced. |
| a code of `lint` | A result that fails `lint`. The findings are the ones `lint` reports for the record with the replacements applied. |

When nothing is refused, `apply-prose` writes the record file once:

- Each replaced section holds `corrected` where the entry has one, and `text` where it has none.
- `record.revision` is one higher.
- `record.rewrites` gains an entry. It gives the `revision` the pass produced, and each applied section with the digest of its old text and of its new. It counts `proposed`, `pruned`, `corrected` and `applied`. `pruned` is `proposed` less the entries left. `corrected` counts the entries whose `corrected` differs from their `text`.

`apply-prose` then prints one line for each question. A response with no replacement is valid, whether it only asks questions or the author rejected every replacement. It writes nothing and leaves no entry.

Exit 0 applied or nothing to apply, 1 refused, 2 unreadable or unparseable, or the record file cannot be written.

## Protected values

A replacement keeps every protected value its section's text holds. These are protected:

- a code span, with its backticks
- a URL
- a tracker id, a criterion or decision id, and a pull request number such as `#843`
- a commit id of seven hex characters or more, with a digit among them
- a number, and the digits inside a word such as `v2`
- a word the schema lists as a disposition, an outcome or a status, such as `fixed`, `Deferred` or `in flight`, in any letter case
- a value of `commit.attribution` that the text quotes
- in `pr.title` and `commit.subject`, the type, the component and the id in the closing brackets

A value may move within its section, and a value given twice may be given once. Sentence punctuation after a URL or an id is no part of it. A reference to a section of a spec is held to its number, so the word before the number may change.

The listed words are common ones. A section that says a run follows a fixed sequence must keep the word `fixed`, and an author who wants it gone edits the record by hand.

## One pass for each revision

Each rewrite entry records the revision its pass produced. While the record's revision is one an entry records, `apply-prose` refuses every response that holds a replacement. The next pass waits for a later revision. `publish` gives the record one when it posts an edit the author made after the rewritten revision was posted.

A response with no replacement uses no pass, and this rule never refuses one.

## Known limits

These checks are a net, and the author's read of each replacement is the safeguard. The protected-value check passes each of these:

- a URL that changes only in a closing parenthesis at its end
- a number that changes only in its sign, or in the parts of an exponent
- a commit id that holds no digit
- a tracker id with no dotted suffix, from a project other than the record's own
- a code span that runs across a line break

A heads-up row counts as a generator's only with the space after its colon, which is how every generator writes one. A replacement that restates its section's text is applied and counted like any other.
