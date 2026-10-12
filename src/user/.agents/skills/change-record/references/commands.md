# The script's subcommands

Run each from the skill's directory, as `uv run scripts/change_record.py` followed by the subcommand.

## The result a fault is reported in

`lint` prints one JSON result to stdout. It is `{"valid": true}`, or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`. `path` names the field at fault, `code` names the rule it broke, and `message` says what to change. `lint-rules.md` beside this file lists every code.

`render` prints the same result on stderr when it refuses a record. Its stdout holds the artifact and nothing else.

## `init`

```bash
uv run scripts/change_record.py init --type TYPE --component NAME --work-item ID record.json
```

`init` writes a new record that the schema accepts, with every field the author fills left empty. `lint` then names each of those fields. `init` never replaces a file.

Exit 0 written, 1 a file is already there, 2 the file cannot be written or the call is wrong.

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
