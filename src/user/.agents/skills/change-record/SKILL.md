---
name: change-record
description: The shape of a pull request description, a commit message and a reply to a review finding, and the JSON change record all three are written from. Use when writing or revising any of the three, or when checking a change record. Not for sentence-level prose quality, which is `readable-prose`, and not for the verdict a review round emits, which is `review-verdict`.
admission:
  prevents: A pull request description the owner cannot read standalone (bare ids, no placement in the milestone tree, no risk or blast radius, discovered work unlisted), a merge commit carrying repeated trailers from the squash setting, and review replies that restate campaign status instead of what changed.
  cost: One shared skill loaded when a pull request, commit or reply is written; one PEP 723 script and its suite under content-tests; one pull request comment per description revision; one Codex dispatch per rewrite pass; a change to the repository's squash settings.
  remove_when: Twenty consecutive merged pull requests pass the record lint with the skill not loaded, or the owner's clarifying questions on pull request descriptions stop over that run.
---

Every change is described in the pull request body, in the commit message, and in each reply to a review finding. A change record is one JSON document that holds everything those three artifacts say, with each fact in one field. Write the record first. Then write each artifact from it, in the shape of its template. The body and the commit message then cannot disagree on a fact. A reader finds the same thing in the same place on every pull request.

## The record

`references/record.schema.json` defines every field. `references/fields.md` says what each group holds, who writes it, and which fields hold wording an editor may change. `examples/pr-843.json` is a worked record for a feature pull request that went through eight review rounds.

The author writes most of the record. Three parts hold facts that are copied and never composed. `where_this_fits` comes from the tracker and from GitHub. `campaign` comes from the posted review verdicts. The filed rows of `discovered` come from the tracker. Nothing in this skill fills those parts, so take their facts from the tracker's and GitHub's own output. The `record` group is bookkeeping the author leaves alone.

Check a record before writing from it. From this skill's directory:

```bash
uv run scripts/change_record.py lint path/to/record.json
```

`lint` checks structure against the schema. It reports a missing required field, a field the schema does not define, and a value of the wrong type. Stdout is JSON: `{"valid": true}`, or `{"valid": false, "errors": [{"code", "path", "message"}, …]}` with `path` naming the field at fault. Exit 0 valid, 1 invalid, 2 unreadable or unparseable. `lint` does not read the prose, so the rules below are the author's to hold.

## The three artifacts

Each template is a file under `references/`. In a template, `${a.b}` stands for the record field at that path. A line whose slot passes through a list, written `[]`, appears once per entry.

### The pull request body: `references/pr-body.md`

The body is for a human and carries no JSON. Everything above the horizontal rule is a one-pager of at most 400 words. Everything below is evidence a reader opens on purpose.

- **Summary.** It has no heading. It gives the problem, then what is true now, then what remains, in three to five sentences.
- **Heads-up.** Anything that should lower a reader's confidence, one sentence each. Write `None.` when there is nothing.
- **Where this fits.** The author writes one line, saying which slice of its parent item this pull request is. The rest comes from the tracker and from GitHub.
- **Discovered work.** A row is filed and names its tracker item, or is not filed, or is in flight and names the other pull request. An in-flight row says what this pull request told the other one. Write a single `None.` row when nothing was found.
- **Verification.** Each gate with its exit status and where it ran, then what was not run and why.

What each commit type carries:

| Type | Sections |
| --- | --- |
| `feat`, `fix`, `refactor`, `perf`, `test` | Every section. The blast-radius diagrams appear only when the change reaches outside its own package. |
| `spec` | Every section. The blast radius is the items the spec will mint. Criteria is one line saying whether the criteria were attacked and where the attack record is. |
| `docs`, `chore`, `build`, `ci`, `style`, `revert` | Heads-up, a one-row Risk table, Changes, Discovered work and Verification. No Criteria. |

### The commit message: `references/commit-message.txt`

- The subject is `<type>(<component>): <what is true after this merges> [<short id>]`, at most 100 characters. The component is the thing a reader would search for. A tracker id is never the component. The short id is the work item's id without its project prefix.
- The work item appears twice. The first body line names it in a sentence for the human. The `Work-item` trailer names it for git, which reads trailers only from the last paragraph.
- Why is two or three sentences and Change is three or four. Why, Change and Verification total 80 to 150 words. A trivial change omits all three and keeps the work-item line and the trailers.
- The trailers are `Work-item`, `Co-authored-by` and one session trailer whose key the authoring tool defines. Nothing else is a trailer.
- The message carries no table, `<details>` fold, fenced block or HTML comment.

### The review reply: `references/review-reply.txt`

- One reply goes on each finding that changed code or prose. It is 40 to 90 words, and its Change line is one or two sentences ending with the commit when there is one.
- The outcome is Fixed, Superseded, Rejected or Deferred. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. A deferral names the item that inherits the finding.
- A rejection gets a reply only when a reviewer asks on the thread. That reply gives the evidence against the finding.
- Campaign status is stated once, in the body's Verification section, and never in a reply.

## Writing checks

All seven apply to the summary, Heads-up, Risk and Changes. The first four also apply below the horizontal rule. The commit message is read alone in the log and each reply is read alone on its thread, so gloss an id again on its first use in each.

1. A stranger can read it. Every work item, criterion, decision, section and pull request number carries a gloss on first use. Every house term is defined where it first appears or replaced with a common word.
2. Problem, then change, then what remains. No history of how the text got here.
3. One clause per sentence.
4. Say the number, then what it means.
5. Verbs do the work.
6. No commentary about the document. Nothing says "this section describes" or "note that".
7. A caveat gets its own Heads-up row. It never rides in a clause.
