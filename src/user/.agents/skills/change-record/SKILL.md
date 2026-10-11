---
name: change-record
description: The shape of a pull request description, a commit message and a reply to a review finding, and the JSON change record all three are written from. Use when writing or revising any of the three, or when checking a change record. Not for sentence-level prose quality, which is `readable-prose`, and not for the verdict a review round emits, which is `review-verdict`.
admission:
  prevents: A pull request description the owner cannot read standalone (bare ids, no placement in the milestone tree, no risk or blast radius, discovered work unlisted), a merge commit carrying repeated trailers from the squash setting, and review replies that restate campaign status instead of what changed.
  cost: One shared skill loaded when a pull request, commit or reply is written; one PEP 723 script and its suite under content-tests; one pull request comment per description revision; one Codex dispatch per rewrite pass; a change to the repository's squash settings.
  remove_when: Twenty consecutive merged pull requests pass the record lint with the skill not loaded, or the owner's clarifying questions on pull request descriptions stop over that run.
---

Every change is described in the pull request body, in the commit message, and in each reply to a review finding. A change record is one JSON document that holds everything those three artifacts say, with each fact in one field. Write the record first. Then render each artifact from it, and never write one of the three by hand. The body and the commit message then cannot disagree on a fact. A reader finds the same thing in the same place on every pull request.

## The record

`references/record.schema.json` defines every field. `references/fields.md` says what each group holds, who writes it, and which fields hold wording an editor may change. `examples/pr-843.json` is a worked record for a feature pull request that went through eight review rounds.

The author writes most of the record. Three parts hold facts that are copied and never composed. `where_this_fits` comes from the tracker and from GitHub. `campaign` comes from the posted review verdicts. The filed rows of `discovered` come from the tracker. Nothing in this skill fills those parts, so take their facts from the tracker's and GitHub's own output. Each part carries a stamp over its content, and `references/lint-rules.md` shows how to set it. The `record` group is bookkeeping the author leaves alone.

Start a record with `init`, and check it with `lint` before writing from it. From this skill's directory:

```bash
uv run scripts/change_record.py init --type feat --component NAME --work-item ID path/to/record.json
uv run scripts/change_record.py lint [--pr NUMBER] path/to/record.json
```

`init` leaves the author's fields empty and never replaces a file. `lint` then names each empty field.

Stdout is JSON: `{"valid": true}`, or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`. `path` names the field at fault and `code` names the rule it broke. Exit 0 valid, 1 invalid, 2 unreadable or unparseable.

`lint` checks structure against the schema first, under the code `schema`. Once the structure is valid, it checks the rules a program can decide. They cover the glosses, stated emptiness, the lengths the templates below give, the groups each commit type carries, one reply for each fixed finding, the stamps, and the phrases that `references/lint-phrases.json` lists. `references/lint-rules.md` lists each rule under its code and says how `lint` counts and matches. With `--pr`, `lint` also checks the record's reach flag against the pull request's changed paths, which it reads through `gh`.

## The three artifacts

`render` fills a template file under `references/` from the record, so each template is the exact form of its artifact:

```bash
uv run scripts/change_record.py render body record.json --output body.md
uv run scripts/change_record.py render commit record.json
uv run scripts/change_record.py render reply record.json --finding <finding id>
```

`render` runs `lint` first. A record that fails gets the lint result on stderr, exit 1, and nothing written. The artifact goes to stdout, or to the file `--output` names. `render` never calls GitHub. When the pull request already has a body, save it to a file and pass `--existing-body`. Another tool may keep a decisions block in that body, and `render` carries the block over unchanged.

In a template, `${a.b}` stands for the record field at that path. A line whose slot passes through a list, written `[]`, appears once per entry. The lines between `{{#a.b}}` and `{{/a.b}}` appear only when the record holds a value there. Text in parentheses around a slot is left out when the record has nothing for that slot.

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

- One reply goes on each finding that changed code or prose. It is 40 to 90 words, and its Change line is one or two sentences ending with the commit when there is one. Its entry names the finding by `claim_id`, `artifact_class` and `finding_id` together.
- The outcome is Fixed, Superseded, Rejected or Deferred. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. A deferral names the item that inherits the finding.
- A rejection gets a reply only when a reviewer asks on the thread. That reply gives the evidence against the finding.
- Campaign status is stated once, in the body's Verification section, and never in a reply.

## Writing checks

All seven apply to the summary, Heads-up, Risk and Changes. The first four also apply below the horizontal rule. The commit message is read alone in the log and each reply is read alone on its thread, so gloss an id again on its first use in each. `lint` decides part of the first check and part of the sixth. Everything else here is the author's to hold. For `lint`, a gloss is a parenthetical that follows the id, as in `X7 (the retry bound)`, or holds it, as in `the retry is bounded (X7)`.

1. A stranger can read it. Every work item, criterion, decision, section and pull request number carries a gloss on first use. Every house term is defined where it first appears or replaced with a common word.
2. Problem, then change, then what remains. No history of how the text got here.
3. One clause per sentence.
4. Say the number, then what it means.
5. Verbs do the work.
6. No commentary about the document. Nothing says "this section describes" or "note that".
7. A caveat gets its own Heads-up row. It never rides in a clause.
