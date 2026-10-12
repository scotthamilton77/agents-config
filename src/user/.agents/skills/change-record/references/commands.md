# The script's subcommands

Run each from the skill's directory, as `uv run scripts/change_record.py` followed by the subcommand. `context`, `discovered`, `campaign` and `lint --pr` read the repository of the working directory. Run those four from inside that repository, and give the script by its path.

## The result a fault is reported in

`lint` prints one JSON result to stdout. It is `{"valid": true}`, or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`. `path` names the field at fault, `code` names the rule it broke, and `message` says what to change. `lint-rules.md` beside this file lists every code.

`render` prints the same result on stderr when it refuses a record. Its stdout holds the artifact and nothing else.

## `init`

```bash
uv run scripts/change_record.py init --type TYPE --component NAME --work-item ID record.json
```

`init` writes a new record that the schema accepts, with every field the author fills left empty. `lint` then names each of those fields. `init` never replaces a file.

Exit 0 written, 1 a file is already there, 2 the file cannot be written or the call is wrong.

## `context` and `discovered`

```bash
uv run path/to/scripts/change_record.py context record.json
uv run path/to/scripts/change_record.py discovered record.json
```

`context` fills `where_this_fits`, and `discovered` fills the filed rows of `discovered`. Each writes its part with the stamp `lint` checks. `generators.md` beside this file says how each part is derived and which calls each subcommand makes.

Neither takes an id on the command line. Both read the work item from the record's `work_item.id`, and `context` reads the pull request from `pr.number`. Both read the tracker through `work`, and `context` reads GitHub through `gh`. Every call is a read. Run both from inside the pull request's repository, because `work` and `gh` read the repository of the working directory.

Each computes everything first and writes the record file once. The file stays exactly as it was when the record cannot be read or does not fit the schema, when the tracker does not know the work item, when a `work` or `gh` call fails or cannot be run, and when a call's answer does not have the shape that call's answer has. The message on stderr quotes the call at fault. A second run over unchanged sources writes nothing and says so.

Exit 0 the record holds the part, 2 anything failed.

## `campaign`

```bash
uv run path/to/scripts/change_record.py campaign [--pr NUMBER] [--app LOGIN] record.json
```

`campaign` fills the record's `campaign` part from the review verdicts posted on the pull request, and writes it with the stamp `lint` checks. `generators.md` beside this file says how the part is derived and which calls the subcommand makes.

- `--pr NUMBER` names the pull request. Leave it out once the record's `pr.number` holds the number. A `--pr` that names a different pull request from the record's is refused.
- `--app LOGIN` counts only the reviews that login posted. Without it, a review counts when a bot account posted it. Give it in a repository where more than one bot posts reviews.

`campaign` reads GitHub through `gh`, and every call is a read. Run it from inside the pull request's repository, because `gh` reads the repository of the working directory. It checks each verdict with the validator the `review-verdict` skill ships, which it loads from that skill's directory beside this one. It names each review it skips on stderr, with the reason.

`campaign` computes everything first and writes the record file once. The file stays exactly as it was when the record cannot be read or does not fit the schema, when the `review-verdict` skill is not there, when a `gh` call fails or cannot be run, and when a call's answer does not have the shape that call's answer has. The message on stderr quotes the call at fault. A second run over unchanged reviews writes nothing and says so.

Exit 0 the record holds the part, 2 anything failed.

## `lint`

```bash
uv run scripts/change_record.py lint [--pr NUMBER] record.json
```

`lint` checks structure against the schema first, under the code `schema`. Once the structure is valid, it checks the rules a program can decide. They cover the glosses, stated emptiness, the lengths the templates give, the groups each commit type carries, one reply for each fixed finding, the stamps, and the phrases that `lint-phrases.json` lists.

With `--pr`, `lint` also checks the record's reach flag against the pull request's changed paths, which it reads through `gh`.

Exit 0 valid, 1 invalid, 2 unreadable or unparseable, or `gh` failed under `--pr`.

## `render`

```bash
uv run scripts/change_record.py render body record.json [--existing-body FILE] [--comment-url URL] [--output FILE]
uv run scripts/change_record.py render commit record.json [--output FILE]
uv run scripts/change_record.py render reply record.json --finding ID [--claim ID] [--artifact-class NAME] [--output FILE]
```

`render` fills one template from the record. It writes the artifact to stdout, or to the file `--output` names. It reads nothing from GitHub or the tracker and writes nothing to them.

`render` runs `lint` first. A record that fails renders nothing: no output file is created, and one that is already there is left as it was.

Exit 0 rendered, 1 refused, 2 unreadable, unparseable or called wrongly.

### `render body`

- `--existing-body FILE` is the pull request's current body, saved to a file. `gh pr view NUMBER --json body --jq .body` prints it. Another tool may keep a decisions block in that body, between two markers. `render` carries the block over byte for byte and writes none of its own.
- A body that holds one of the two markers, holds one twice, or holds them out of order is refused under the code `decisions-block`. `render` never treats such a body as one with no block.
- `--comment-url URL` is the comment the record is posted in. It adds the line that points at that comment and gives the record's revision. Without it the body has no such line, which is the form a pull request is opened with.
- The body carries the commit message in a fold, so a record whose commit message is refused has its body refused too.

### `render commit`

A field of the commit message that holds a Markdown table, a `<details>` fold, a fenced block or an HTML comment is refused, and the result names the field. `lint` reports a fold, a comment and a fenced `json` block under `machine-content`. `render` reports a table and any other fenced block under `commit-markup`. It reports prose whose wrapped form opens a line with `---` under the same code, because git reads such a line as the end of the message.

### `render reply`

`--finding ID` names the reply entry by its finding id. When two entries share a finding id, add `--claim` and, if the claim is shared too, `--artifact-class`. A command that matches no entry, or more than one, is refused under the code `reply-entry`.
