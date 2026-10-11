# The three artifacts

`render` fills one template per artifact from the record. The templates sit beside this file: `pr-body.md`, `commit-message.txt` and `review-reply.txt`. A template is the exact form of its artifact, so read it for the order and the wording of every heading and label. This file gives the rules for what the author writes into each.

## Reading a template

- `${a.b}` stands for the record field at that path.
- A line whose slot passes through a list, written `[]`, appears once per entry of that list.
- The lines between `{{#a.b}}` and `{{/a.b}}` appear only when the record holds a value at that path. A group the record does not hold therefore takes its heading or its fold with it.
- Text in parentheses around a slot is left out, parentheses included, when the record has nothing for that slot.

Three slots name no record field. `${commit_message}` is the rendered commit message. `${decisions}` is the decisions block carried over from the pull request's existing body. `${record_comment_url}` is the comment the record is posted in.

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
- In a table cell, a `|` is escaped and a line break becomes `<br>`.
- The findings table shows each disposition as Fixed, Rejected or Deferred. A finding reads Superseded when the author's reply to that finding says so.
- The decisions block another tool keeps in the body is carried over byte for byte, in the place the template gives it.

## The commit message: `commit-message.txt`

- The subject is `<type>(<component>): <what is true after this merges> [<short id>]`, at most 100 characters. The component is the thing a reader would search for. A tracker id is never the component. The short id is the work item's id without its project prefix.
- The work item appears twice. The first body line names it in a sentence for the human. The `Work-item` trailer names it for git, which reads trailers only from the last paragraph.
- Why is two or three sentences and Change is three or four. Why, Change and Verification total 80 to 150 words. A trivial change omits all three and keeps the work-item line and the trailers.
- The trailers are `Work-item`, `Co-authored-by` and one session trailer whose key the authoring tool defines. Nothing else is a trailer.
- The message carries no table, `<details>` fold, fenced block or HTML comment. `render` refuses a field that holds one. One quoted in a code span is a literal, so it passes.
- `render` wraps Why, Change and Verification at 72 columns. It never wraps the subject, the work-item line or a trailer.

## The review reply: `review-reply.txt`

- One reply goes on each finding that changed code or prose. It is 40 to 90 words, and its Change line is one or two sentences ending with the commit when there is one. Its entry names the finding by `claim_id`, `artifact_class` and `finding_id` together.
- The outcome is Fixed, Superseded, Rejected or Deferred. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. A deferral names the item that inherits the finding.
- A rejection gets a reply only when a reviewer asks on the thread. That reply gives the evidence against the finding.
- Campaign status is stated once, in the body's Verification section, and never in a reply.
- The commit follows the Change line in parentheses. A reply whose entry names no commit ends its Change line without one.
