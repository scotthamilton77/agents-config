# What `lint` checks

`lint` checks a record's structure against the schema first. It reports each fault under the code `schema`. The rules below run once the structure is valid. Each finding carries its rule's code, the path of the field at fault, and a message that says what to change.

| Code | What fails |
| --- | --- |
| `bare-id` | An id whose first use has no gloss. |
| `unstated-empty` | An empty `heads_up`, an empty `discovered.rows`, a risk table with no row, a criteria table with no row on a type that carries one, or a `verification` that lists no gate and nothing not run. |
| `none-beside-entry` | `None.` beside another entry in `heads_up`, `discovered.rows` or `verification.not_run`. |
| `discovered-row` | A filed row that names no item, an in-flight row that names no pull request, or a row with an empty reason. |
| `summary-length` | A summary of fewer than three or more than five sentences. |
| `commentary` | A phrase of commentary about the document, in any text the author wrote. |
| `machine-content` | A `<details>` fold, an HTML comment or a fenced `json` block, in any field. |

In `heads_up` and `verification.not_run`, an entry is `None.` with or without space around it. `discovered.rows` takes the entry only as written, and the schema checks that.

## The text the author wrote

The `bare-id` and `commentary` rules read the text the author wrote. That is every text field of the record apart from three kinds:

- a generated part and the text of a filed discovered row, which hold the tracker's wording or GitHub's
- a gate's command and a diagram's source, which are quoted and cannot be reworded
- the bracketed id that closes the title and the commit subject

The `machine-content` rule reads every field, generated parts included.

## Ids and glosses

`lint` reads five shapes as an id:

- a tracker id with a dotted suffix, such as `proj-a1b.3` or `a1b.3`
- a hyphenated capital-letter id, such as `AB-C12`
- a short capital-letter id, such as `X7`
- a pull request number, such as `#12`
- a numbered section, such as `section 4.2`

A gloss is a parenthetical, in one of two places. It can follow the id, as in `X7 (the retry bound)`, and then it holds at least one word that is not itself an id. It can hold the id, as in `the retry is bounded (X7)`, and then the words around the id say what it is. Backticks around an id do not excuse it. A parenthetical after a list of ids glosses only the last of them.

Only the first use of an id needs its gloss. `lint` finds the first use in each of three texts, because each is read alone: the title with the body, the commit message, and each reply. It reads the fields of a text in the order the text's template shows them.

Some cells set an id beside its own gloss. `lint` takes such an id as introduced for the text below the cell. These cells are a line of the tracker tree, a pull request the body builds on or runs beside, a row of the scope table, the item or pull request of a discovered row, the id column of the criteria table, and the work-item line of the commit message.

`lint` cannot tell whether a gloss explains its id. That judgement stays with the author.

## Sentences

A sentence ends at a full stop, a question mark or an exclamation mark that is followed by a space or by the end of the text. A full stop inside a number, a file name or a code span ends nothing. Neither does the one in "e.g." or "i.e.". Any other abbreviation followed by a space counts as an end, so spell it out.

## Commentary and machine content

The phrases of commentary are in `lint-phrases.json` beside this file, under `document_commentary`. `lint` matches each phrase whole, in any letter case.

A fenced `json` block is a fence that opens on a line of its own and names `json` as its language. A code span that starts a line opens no fence. A fence quoted inside another fenced block is that block's content.

A phrase or a construct inside a code span passes. To write about one, quote it in backticks.
