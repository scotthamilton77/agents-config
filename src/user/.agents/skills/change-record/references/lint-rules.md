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
| `unfilled` | A field the author fills that is still empty: the title, the head commit, the work item's gloss or slice, the list of changes, or a field of the attribution. |
| `commit-subject` | A commit subject over 100 characters or on more than one line, with a type that is not a commit type or not the record's, with no component, a tracker id as its component or a component that is not the record's, with no colon and space after the component, with no word of wording, or without a space and the work item's short id in brackets at its end. |
| `commit-body` | A commit body missing one of its three sections, a `why` outside two to three sentences, a `change` outside three to four, an empty `verification`, or a total outside 80 to 150 words. Also a message with no body and no `trivial` reason, and one with both. |
| `required-group` | A group the record's type or reach calls for, missing or in the wrong form: no criteria table on a type that carries one, a criteria on a `spec` that is not one line saying whether the criteria were attacked, more than one risk row on a type that takes one, or a missing diagram when the change reaches outside its package. A `spec` that reaches outside its package holds the items it mints in place of the diagrams, and fails when it names none. |
| `reach` | Under `--pr` only: a record that says the change stays inside its package, when the pull request's changed paths span more than one top-level component. |
| `reply` | A reply outside 40 to 90 words, with a Change line that is empty or longer than two sentences, a Deferred reply that does not name the inheriting item, a Rejected reply with no URL, or one with no host or no path, for the comment that asked for it, or a phrase of campaign status. |
| `reply-count` | A finding the campaign marks fixed that has no reply, or more than one. |
| `stale-stamp` | A generated part whose content its stamp does not cover, or that has no stamp. |
| `line-break` | A line break in a field an artifact sets on one line: the title, the work item's id, gloss or slice, or a field of the attribution. A line break in the commit subject is reported under `commit-subject`. |
| `session-key` | A session trailer key that holds anything but letters, digits and hyphens. |
| `commit-markup` | Under `render` and `publish` only: a field of the commit message that holds a Markdown table, a `<details>` fold, a fenced block or an HTML comment, or prose whose wrapped form opens a line with `---`. |
| `decisions-block` | Under `render body` and `publish` only: an existing body that holds one of the two markers around a decisions block, holds one of them twice, or holds them out of order. |
| `reply-entry` | Under `render reply` only: no reply entry, or more than one, matches the finding the command names. |
| `stale-part` | Under `publish` only: a generated part that its generator would now write differently, on a pull request with no record comment yet. |
| `too-long` | Under `publish` only: a record comment or a pull request body longer than 65,536 characters. |

In `heads_up` and `verification.not_run`, an entry is `None.` with or without space around it. `discovered.rows` takes the entry only as written, and the schema checks that.

## The text the author wrote

The `bare-id` and `commentary` rules read the text the author wrote. That is every text field of the record apart from two kinds:

- a generated part and the text of a filed discovered row, which hold the tracker's wording or GitHub's
- a gate's command and a diagram's source, which are quoted and cannot be reworded

Both rules read a field whole. The `bare-id` rule alone passes over the work item's short id where it stands by itself in the brackets closing the title or the commit subject. Any other id in those brackets is read, and so is an id among other words there.

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

Some cells set an id beside its own gloss. `lint` takes such an id as introduced for the text below the cell. These cells are a line of the tracker tree, a pull request the body builds on or runs beside, a row of the scope table, the id of an item a spec mints, the item or pull request of a discovered row, the id column of the criteria table, and the work-item line of the commit message.

`lint` cannot tell whether a gloss explains its id. That judgement stays with the author.

## Sentences

A sentence ends at a full stop, a question mark or an exclamation mark that is followed by a space or by the end of the text. A full stop inside a number, a file name or a code span ends nothing. Neither does the one in "e.g." or "i.e.". Any other abbreviation followed by a space counts as an end, so spell it out.

## Words

A word is a run of characters with no space in it. A number, a file name and a hyphenated compound each count as one word.

## A new record

`init` writes a record that the schema accepts, with every field the author fills left empty. `lint` then names each of those fields, and nothing else. A list that takes `None.` is reported under `unstated-empty`. An empty summary is reported under `summary-length`, an empty subject under `commit-subject`, and a missing commit body under `commit-body`. Every other empty field is reported under `unfilled`.

A new record holds no generated part and no reply. Its reach flag, `risk.reaches_outside_package`, starts false, because a flag has no empty value. Set it when the change reaches outside its package.

## Line breaks

A line ends at a line feed or a carriage return. Nine fields are set on one line and never hold one: `pr.title`, `commit.subject`, `work_item.id`, `work_item.gloss`, `work_item.slice`, and the four fields of `commit.attribution`. Each is a fact or is one line by form, so no artifact can set a break in it and stay what it is. A break in the subject, the id, the gloss or an attribution value would also move the lines git reads the commit message's trailers from.

`lint` reports a break in the commit subject under `commit-subject`, with the rest of the subject's form, and a break in any of the other eight under `line-break`. One fault draws one finding.

Every other text field may hold a line break. `artifacts.md` beside this file says how `render` sets one.

The session trailer's key, `commit.attribution.session_key`, holds letters, digits and hyphens alone. Git reads a trailer's key from those characters. A last paragraph with one line git cannot read as a trailer loses all three trailers.

## The commit message

The subject is one line of the form `type(component): what is true after this merges [short id]`. Its parts are the type, the component in parentheses, a colon and a space, at least one word of wording, a space, and the short id in the brackets that close the line. `lint` checks each part on its own, so a finding names the part that is missing.

- Its length is counted in characters, and 100 characters pass.
- It holds no line feed and no carriage return.
- The type is one of the types the schema lists for `pr.type`, and it is the record's own `pr.type`.
- The component is the record's own `pr.component`. A component with the shape of a tracker id fails whatever the record says. That shape is the first one listed under ids above.
- The short id is the work item's full id after its last hyphen, so `proj-a1b.3` gives `a1b.3`. An id with no hyphen is its own short id.

A message has all three body sections or none of them. In a body, `why` is two or three sentences, `change` is three or four, and `verification` is at least one. The three total 80 to 150 words. The work-item line, the labels and the trailers are not counted. `lint` counts the words only when all three sections are there. A message with no body gives its reason in `commit.trivial`, and a message never has both.

## Groups by type and reach

- A `feat`, `fix`, `refactor`, `perf` or `test` record holds `criteria` as a table.
- A `spec` record holds `criteria` as one line of text that says whether the criteria were attacked. `lint` checks that the line is there, is one line, and holds the word `attacked` outside a code span, as in "were attacked" or "were not attacked". Where the attack record is stays with the author, because criteria that were not attacked have no record to point at.
- A `docs`, `chore`, `build`, `ci`, `style` or `revert` record holds exactly one risk row.
- A record whose `risk.reaches_outside_package` is true holds both `blast_radius.reach_graph` and `blast_radius.task_flow`. A record whose flag is false needs neither.
- A `spec` record whose flag is true holds `blast_radius.mints` in place of the two diagrams, with at least one item that says what it is. A spec changes no package, and what it reaches is the tracker, through the items it mints. On any other type the items stand in for no diagram.

`lint` refuses no group for being more than its type's body shows. A `docs` record that holds `criteria` passes, and its body leaves the criteria out. `artifacts.md` beside this file says what each type's body carries.

`lint --pr NUMBER` checks the flag against the pull request itself. It reads the pull request's list of files from GitHub through `gh api`, a page at a time, in the working directory's repository. A renamed file counts under its old path and its new one. A path's top-level component is its first segment. That is the directory at the root that holds the path, or the file itself when it sits at the root. A path under a `docs` directory at the root counts toward no component, because documentation describes a component and is not one. A record whose flag is false fails, under `reach`, when the paths span more than one component. A pull request that changes one component and its documentation therefore passes, and so does one that changes documentation alone.

This check is coarse. Two packages under one top-level directory count as one component, so a pass does not prove the flag. When `gh` cannot be run, exits with an error, or gives a page that is no list of files, `lint` reports the code `gh-failed` and exits 2, because it has decided nothing.

## Replies

A reply's words are those of its `change` and `verification`. The labels, the outcome and the commit are not counted. A reply takes 40 to 90 words, and its `change` takes one or two sentences.

A review finding is named by three things together: its claim id, its artifact class and its finding id. Finding ids start again with each claim and each class, so the id alone can name two findings. A reply answers the campaign finding whose three parts equal its own `claim_id`, `artifact_class` and `finding_id`. A reply that leaves one out answers no campaign finding.

Each finding the campaign marks `fixed` takes exactly one reply. A finding with another disposition, or with none yet, needs no reply.

A Deferred reply names the item that inherits the finding. When the campaign finding carries a `work_item`, the reply names that id. Otherwise the reply names some tracker item. That is an id with a dotted suffix, or an id that opens with the project prefix of the record's own work item.

A Rejected reply gives, in `request_url`, the URL of the reviewer's comment that asked for it. The URL opens with `http://` or `https://` and names a host and a path on it, so a bare host fails. `lint` holds it to no one host, and cannot tell whether the URL is a reviewer's comment.

The phrases of campaign status are in `lint-phrases.json`, under `campaign_status`. `lint` matches each phrase whole, in any letter case, in `change` and in `verification`.

## Stamps

Each generated part carries a stamp, which `lint` recomputes. `where_this_fits.digest` covers that group without its `digest`. `campaign.digest` covers that group without its `digest`. `discovered.filed_digest` covers the filed rows, in the order the record holds them.

A stamp is the SHA-256 digest, in hex, of the content written as JSON with every object's keys sorted, with no space after a comma or a colon, and with each character outside ASCII written as itself, encoded as UTF-8. Reordering keys or reformatting the file therefore changes nothing. Changing a value, or the order of a list, makes the stamp stale.

A part the record does not hold needs no stamp. The filed rows need one as soon as the record has a filed row.

The script fills all three generated parts. `context` writes `where_this_fits` with its stamp, `discovered` writes the filed rows with theirs, and `campaign` writes `campaign` with its own. `generators.md` beside this file describes all three. A stale stamp on a part clears when its generator runs again.

A part that was copied by hand, where its generator could not run, is stamped from this skill's directory:

```bash
python3 -c 'import json, sys; sys.path.insert(0, "scripts"); import change_record as c; p = sys.argv[1]; r = c.stamp_generated(json.load(open(p))); open(p, "w").write(json.dumps(r, indent=2, ensure_ascii=False) + "\n")' path/to/record.json
```

That command stamps every generated part the record holds. Run it only after copying a part from its source, and never to pass an edit of your own, because a stamp says the content is the source's.

## A record that cannot be read

When `lint` cannot read the record at all, it exits 2 with one finding that has no path. The code is `unreadable` for a file it cannot open or decode, and `invalid-json` for text that is not JSON. The code is `not-utf-8` for a record that holds text UTF-8 cannot hold. A JSON escape for half of a surrogate pair is such text, and the finding names the field. That record is refused before any rule runs, because nothing after the lint could write it.

## Commentary and machine content

The phrases of commentary are in `lint-phrases.json` beside this file, under `document_commentary`. `lint` matches each phrase whole, in any letter case. In a phrase of either list in that file, `<number>` stands for any number.

A phrase or a construct inside a code span passes, whatever else the span holds. To write about one, quote it in backticks on one line. A code span opens and closes on the same line. A span that wraps across a line end is not read as a span, because a fold or a fence that starts a line inside it is a real one. A backtick after a backslash opens no span. A phrase of campaign status inside a code span in a reply passes in the same way.

A fenced `json` block is a line that opens a fence and names `json` as its language. The line may sit inside a quote or a list item. A line ends at a line feed or a carriage return, and at no other character. A code span that starts a line opens no fence.

`lint` judges each line alone. A `json` fence therefore fails even where another fenced block quotes it, and a fold or an HTML comment inside a fenced block fails as it would outside one. To show a fence, quote its opening inline.
