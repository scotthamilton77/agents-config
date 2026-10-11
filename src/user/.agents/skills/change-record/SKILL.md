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

The author writes most of the record. Three parts hold facts that are copied and never composed. `context` fills `where_this_fits` from the tracker and from GitHub. `discovered` fills the filed rows of `discovered` from the tracker. `references/generators.md` describes both. Nothing fills `campaign` yet, so copy it from the posted review verdicts. Each part carries a stamp over its content, and `references/lint-rules.md` shows how to set one by hand. The `record` group is bookkeeping the author leaves alone.

## The script

Run the script from this skill's directory. `references/commands.md` gives each subcommand's arguments, its output and its exit statuses.

```bash
uv run scripts/change_record.py init --type feat --component NAME --work-item ID record.json
uv run scripts/change_record.py lint [--pr NUMBER] record.json
uv run scripts/change_record.py render body record.json --output body.md
uv run scripts/change_record.py render commit record.json
uv run scripts/change_record.py render reply record.json --finding ID
```

- `init` starts a record with the author's fields empty. It never replaces a file.
- `lint` checks the record against the schema, then against the writing rules a program can decide. It names each fault by field and by rule. `references/lint-rules.md` lists every rule under its code and says how `lint` counts and matches. With `--pr` it also checks the record's reach flag against the pull request's changed paths.
- `render` fills one artifact's template from the record. It runs `lint` first and writes nothing for a record that fails. It never calls GitHub. When the pull request already has a body, pass that body with `--existing-body`, because another tool may keep a decisions block there and `render` carries it over.

## The three artifacts

Each artifact has a template under `references/`: `pr-body.md`, `commit-message.txt` and `review-reply.txt`. `render` fills those files, so a template is the exact form of its artifact. `references/artifacts.md` gives the rules for what each artifact says, and how to read a template. Read it before filling a record, because `lint` holds the record to most of those rules.

The body is for a human and carries no JSON. Everything above its horizontal rule is a one-pager of at most 400 words. Everything below is evidence a reader opens on purpose. What each commit type carries:

| Type | Sections |
| --- | --- |
| `feat`, `fix`, `refactor`, `perf`, `test` | Every section. The blast-radius diagrams appear only when the change reaches outside its own package. |
| `spec` | Every section. The blast radius is the items the spec will mint. Criteria is one line saying whether the criteria were attacked and where the attack record is. |
| `docs`, `chore`, `build`, `ci`, `style`, `revert` | Heads-up, a one-row Risk table, Changes, Discovered work and Verification. No Criteria. |

## Writing checks

All seven apply to the summary, Heads-up, Risk and Changes. The first four also apply below the horizontal rule. The commit message is read alone in the log and each reply is read alone on its thread, so gloss an id again on its first use in each. `lint` decides part of the first check and part of the sixth. Everything else here is the author's to hold. For `lint`, a gloss is a parenthetical that follows the id, as in `X7 (the retry bound)`, or holds it, as in `the retry is bounded (X7)`.

1. A stranger can read it. Every work item, criterion, decision, section and pull request number carries a gloss on first use. Every house term is defined where it first appears or replaced with a common word.
2. Problem, then change, then what remains. No history of how the text got here.
3. One clause per sentence.
4. Say the number, then what it means.
5. Verbs do the work.
6. No commentary about the document. Nothing says "this section describes" or "note that".
7. A caveat gets its own Heads-up row. It never rides in a clause.
