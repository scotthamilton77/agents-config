# The three artifacts

`render` fills one template per artifact from the record. The templates sit beside this file: `pr-body.md`, `commit-message.txt` and `review-reply.txt`. A template is the exact form of its artifact, so read it for the order and the wording of every heading and label. This file gives the rules for what the author writes into each.

## Reading a template

- `${a.b}` stands for the record field at that path.
- A line whose slot passes through a list, written `[]`, appears once per entry of that list.
- The lines between `{{#a.b}}` and `{{/a.b}}` appear only when the record holds a value at that path. A group the record does not hold therefore takes its heading or its fold with it. So does a group whose every value is empty, such as a blast radius with two empty diagrams.
- A slot that stands alone on its line is a block, and its value keeps its own lines. Any other slot is set on the template's line.
- A blank line of a template is left out where the line before it is blank. Lines that vanish between two blank lines therefore leave one blank line behind.
- Text in parentheses around one slot or more is left out, parentheses included, when the record has nothing for any slot inside them.

Three slots name no record field. `${commit_message}` is the rendered commit message. `${decisions}` is the decisions block carried over from the pull request's existing body. `${record_comment_url}` is the comment the record is posted in.

## Line breaks

A line ends at a line feed or a carriage return, alone or as a pair. What an artifact does with a line break depends on the field that holds it.

| Field | A line break in it |
| --- | --- |
| `pr.title`, `commit.subject`, `work_item.id`, `work_item.gloss`, `work_item.slice`, and the four fields of `commit.attribution` | `lint` refuses it, under `commit-subject` for the subject and `line-break` for the rest. Each is a fact or is one line by form. A break there would change the fact, or would move the lines git reads the trailers from. |
| Any value set in a table cell | It becomes `<br>`, so the value stays in its row. |
| `design_notes` and the two diagram sources | It stays. Each is a block and keeps its own lines. |
| `commit.why`, `commit.change` and `commit.verification` | It reads as a space. Each is one paragraph, which `render` wraps at 72 columns. |
| Every other field, such as the summary, a heads-up entry, a change, and a reply's `change` and `verification` | It reads as one space, together with the space around it. The template gives the field one line or one paragraph. |

## The pull request body: `pr-body.md`

- **Summary.** It has no heading. It gives the problem, then what is true now, then what remains, in three to five sentences.
- **Heads-up.** Anything that should lower a reader's confidence, one sentence each. Write `None.` when there is nothing.
- **Where this fits.** The author writes one line, saying which slice of its parent item this pull request is. The rest comes from the tracker and from GitHub.
- **Discovered work.** A row is filed and names its tracker item, or is not filed, or is in flight and names the other pull request. An in-flight row says what this pull request told the other one. Write a single `None.` row when nothing was found.
- **Verification.** Each gate with its exit status and where it ran, then what was not run and why.

`render` writes some values in a form of its own:

- A list that holds only `None.` renders as one bullet, or as one table row, that reads `None.`.
- A reference to another pull request reads `#12 (its gloss)`. An empty list of them reads `none`.
- A row in flight shows its pull request beside its status, as `in flight (#12)`.
- In a table cell, a `|` is escaped and a line break becomes `<br>`, as the table above says.
- The findings table shows each disposition as Fixed, Rejected or Deferred. A finding reads Superseded when the author's reply to that finding says so.
- A row of the findings table names its finding's claim and artifact class beside the finding's id, as `lens.r1.f1 (claim a1b.3, prose)`, when the campaign's findings come from more than one claim or more than one class. Finding ids start again with each claim and each class, so two rows could otherwise carry one id. A campaign with one claim and one class shows the id alone.
- The decisions block another tool keeps in the body is carried over byte for byte, in the place the template gives it.

## The commit message: `commit-message.txt`

- The subject is `<type>(<component>): <what is true after this merges> [<short id>]`, at most 100 characters. The component is the thing a reader would search for. A tracker id is never the component. The short id is the work item's id without its project prefix.
- The work item appears twice. The first body line names it in a sentence for the human. The `Work-item` trailer names it for git, which reads trailers only from the last paragraph.
- Why is two or three sentences and Change is three or four. Why, Change and Verification total 80 to 150 words. A trivial change omits all three and keeps the work-item line and the trailers.
- The trailers are `Work-item`, `Co-authored-by` and one session trailer whose key the authoring tool defines. Nothing else is a trailer.
- The message carries no table, `<details>` fold, fenced block or HTML comment. `render` refuses a field that holds one. One quoted in a code span is a literal, so it passes.
- `render` wraps Why, Change and Verification at 72 columns. It never wraps the subject, the work-item line or a trailer. It never splits a code span, and a span longer than a line takes a line of its own.
- `render` reads the wrapped message with the readers `lint` uses, and refuses prose whose wrapped form holds a construct. Three backticks or tildes in running prose open a fenced block where they come first on a line. Three hyphens standing alone end the message for git where they come first on a line, and the trailers below them are lost.

## The review reply: `review-reply.txt`

- One reply goes on each finding that changed code or prose. It is 40 to 90 words, and its Change line is one or two sentences ending with the commit when there is one. Its entry names the finding by `claim_id`, `artifact_class` and `finding_id` together.
- The outcome is Fixed, Superseded, Rejected or Deferred. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. A deferral names the item that inherits the finding.
- A rejection gets a reply only when a reviewer asks on the thread. That reply gives the evidence against the finding.
- Campaign status is stated once, in the body's Verification section, and never in a reply.
- The commit follows the Change line in parentheses. A reply whose entry names no commit ends its Change line without one.
- A reply is three lines whatever its entry holds, because a line break in `change` or `verification` reads as a space.
