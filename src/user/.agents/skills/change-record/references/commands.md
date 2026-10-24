# The script's subcommands

Run each from the skill's directory, as `uv run scripts/change_record.py` followed by the subcommand. `context`, `discovered`, `campaign`, `lint --pr`, `publish` and `merge` read the repository of the working directory. Run those six from inside that repository, and give the script by its path.

## The result a fault is reported in

`lint` prints one JSON result to stdout. It is `{"valid": true}`, or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`. `path` names the field at fault, `code` names the rule it broke, and `message` says what to change. `lint-rules.md` beside this file lists every code.

`render` prints the same result on stderr when it refuses a record. Its stdout holds the artifact and nothing else.

`publish` and `merge` print the same result on stderr when they refuse, and when a call fails.

`extract-prose` and `apply-prose` print the same result on stderr when they refuse a record or a response. `dispatch-prose` prints it there when a file it reads is missing.

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

`campaign` reads GitHub through `gh`, and every call is a read. Run it from inside the pull request's repository, because `gh` reads the repository of the working directory. It checks each verdict with the validator the `review-verdict` skill ships. It asks that skill's `round_status` whether the latest round is terminal-clean. It loads both from that skill's directory beside this one. It names each review it skips on stderr, with the reason.

`campaign` computes everything first and writes the record file once. The file stays exactly as it was when the record cannot be read or does not fit the schema, when the `review-verdict` skill is not there, when a `gh` call fails or cannot be run, and when a call's answer does not have the shape that call's answer has. The message on stderr quotes the call at fault. A second run over an unchanged pull request writes nothing and says so.

Exit 0 the record holds the part, 2 anything failed.

## `lint`

```bash
uv run scripts/change_record.py lint [--pr NUMBER] record.json
```

`lint` checks structure against the schema first, under the code `schema`. Once the structure is valid, it checks the rules a program can decide. They cover the glosses, stated emptiness, the lengths the templates give, the groups each commit type carries, one reply for each fixed finding, the stamps, and the phrases that `lint-phrases.json` lists.

With `--pr`, `lint` also checks the record's reach flag against the pull request's changed paths, which it reads through `gh`.

With `--pr`, `lint` then checks the pull request's body against the newest record comment, which `publish` posts. This check compares what GitHub holds and does not read the record file. A pull request with no record comment passes it, because there is nothing to compare. Otherwise one of three findings can follow:

- `record-comment`: the record in the newest comment's fold does not read as JSON, does not fit the schema, does not hash to the digest in the comment's marker, or names another pull request than the marker.
- `stale-pointer`: the body is not the render of that record, and it points at an older record comment. A publish that lost a race reads this way too. Two comments then carry one revision, and the body names the one with the lower id.
- `stale-body`: the body is not the render of that record with the body's own decisions block, and it points at no older record comment. A body edited by hand reads this way.

A body that is the render passes whatever its decisions block links to.

Under `--pr`, `lint` makes these calls, in order, and every one is a read:

1. `gh api "repos/{owner}/{repo}/pulls/NUMBER/files?per_page=100&page=N"`, from page 1 until a page is empty
2. `gh api "repos/{owner}/{repo}/pulls/NUMBER"`, for the body
3. `gh api "repos/{owner}/{repo}/issues/NUMBER/comments?per_page=100&page=N"`, from page 1 until a page is empty

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
- A body that shows more than 400 words above its horizontal rule draws one line on stderr. The line opens with `warning:` and gives the count and the bound. The body is still written and the exit status is still 0, because lines the script filled count toward the bound and the author cannot shorten those. The count leaves out everything inside a fold. A word is a run of characters with no space in it that holds a letter or a digit.

### `render commit`

A field of the commit message that holds a Markdown table, a `<details>` fold, a fenced block or an HTML comment is refused, and the result names the field. `lint` reports a fold, a comment and a fenced `json` block under `machine-content`. `render` reports a table and any other fenced block under `commit-markup`. It reports prose whose wrapped form opens a line with `---` under the same code, because git reads such a line as the end of the message.

### `render reply`

`--finding ID` names the reply entry by its finding id. When two entries share a finding id, add `--claim` and, if the claim is shared too, `--artifact-class`. A command that matches no entry, or more than one, is refused under the code `reply-entry`.

## `publish`

```bash
uv run path/to/scripts/change_record.py publish [--dry-run | --create] record.json
```

`publish` posts the record on its pull request and sets the pull request body from it. The pull request is the one `pr.number` names, in the repository of the working directory. A record whose `pr.number` is not set has no pull request to post on, so the run stops with exit 2 unless `--create` is given.

`publish` checks every reason to refuse before it writes anything. It works in this order:

1. It runs `lint`. A record that fails gets the lint result, and no call is made.
2. It reads the pull request and every comment on it, and finds the newest record comment.
3. On a pull request with no record comment, it runs `context`, `discovered` and `campaign` over a copy of the record. The record must already be what each of them writes. A part that differs is refused under the code `stale-part`, and the finding names the part and the generator to run again. A stamp set by hand therefore does not pass.
4. It refuses a record comment or a body longer than 65,536 characters, which is the most GitHub takes. The code is `too-long`, and the finding gives the length. A decisions block carried over from the current body counts toward the body's length.
5. It creates the record comment, then sets the body, then writes the record file.

The body is the record as `render body` renders it, with the current body's decisions block carried over and with the line that points at the record comment. A body or a commit message that `render` refuses is refused here under the same code.

In the record file, the `record` group gains the comment's id as `comment_id`, the revision, the digest, and the pull request's head commit as `head_sha`. `pr.head_sha` is the commit the gates ran at, and `publish` leaves it alone.

`publish` never edits or deletes a comment. Its only writes to GitHub are one new comment and one edit of the body.

`publish` runs `campaign` as it runs with no `--app`. A record whose campaign was filled with `--app`, on a pull request where another bot account also posted a verdict, is refused at the third step.

### Publishing again

When the record's digest equals the newest record comment's, `publish` posts no comment. It sets the body only when the body differs from the render that points at that comment. It writes the record file only when the file's `record` group does not name that comment yet. A run that stopped after the comment and before the body is therefore finished by running `publish` again.

When the digest differs, `publish` posts a new comment at the next revision and sets the body to point at it. The third step is skipped, because the pull request has a record comment.

### `--dry-run`

With `--dry-run`, `publish` makes every read and every check, then prints the record comment and the body to stdout, the comment first. It writes nothing to GitHub and leaves the record file as it was. One line on stderr gives the revision and says whether the comment and the body are new.

When the comment is already posted, the output is that comment as GitHub holds it, then the body with that comment's URL. When a run would post a new comment, the comment has no URL yet. The line that points at it then shows the pull request's URL followed by `#issuecomment-0000000000`, where a real run puts the new comment's id. The body's length is measured with those ten zeros, because a comment's id is ten digits long today.

### `--create`

With `--create`, `publish` opens the pull request when the record's `pr.number` is not set. This is the way a pull request is opened. It reads the current branch from git. When a pull request is already open for that branch, it takes that one and opens no second. Otherwise it runs `gh pr create` with the record's title, and with the render that has no pointing line as the body.

No generated part can be current before the pull request exists, because `campaign` reads the pull request and `context` reads its paths. `publish --create` therefore runs the three generators into the record, in place of the check in the third step. It does so for a record that named no pull request, whether or not the pull request it takes already holds a record comment. It does so too on any first publish. The record file is written as soon as the number is known, and again once the parts are filled.

The filled record is linted again before the comment is created, because a generator can bring in what `lint` refuses, such as a fixed finding with no reply. A record that then fails is refused with the lint's findings, and no comment is posted. The pull request stays open, and the file keeps the number and the filled parts. Fix the record and run `publish --create` again.

A run that stops after the pull request is open is finished by running `publish --create` again. That run takes the number from the file, or finds the open pull request by its branch, and goes on from there. A record that already names its pull request is published there, and nothing is opened.

A record whose comment or body is already over the limit opens no pull request. The body with its pointing line is measured once the pull request exists. `--create` and `--dry-run` do not go together.

### The record comment

A record comment's first line is the marker:

`<!-- change-record v1 pr=NUMBER rev=REVISION sha256=DIGEST -->`

The marker names the schema version, the pull request, the revision and the record's digest. The record follows in a `<details>` fold, as one line of JSON with sorted keys in a fenced `json` block. In the comment, the record's `record` group carries the revision, the digest and the head commit. It carries no `comment_id`, because a comment cannot name its own id.

The digest is the SHA-256 digest of the record without its `record` group. That content is written as a stamp's content is, which `lint-rules.md` beside this file describes. Reordering keys changes nothing in the digest, and neither does publishing, which changes only the `record` group. Any other change gives another digest.

The newest record comment is found by its marker and never by its place among the comments. `publish` reads every page of the pull request's comments, until a page comes back empty. A comment counts when its first line is the marker alone and the marker names this pull request. A marker quoted further down a comment does not count. The newest is the comment with the highest revision, compared as a number, so revision 10 follows revision 9. When two comments carry one revision, the one with the higher id is the newest.

The body points at the comment it was rendered from, in this line:

`Rendered from change record URL, revision REVISION.`

### The calls `publish` makes

`publish` makes these, in order:

1. `gh api "repos/{owner}/{repo}/pulls/NUMBER"`, for the current body, the head commit and the pull request's URL
2. `gh api "repos/{owner}/{repo}/issues/NUMBER/comments?per_page=100&page=N"`, from page 1 until a page is empty
3. every call `context`, `discovered` and `campaign` make, which `generators.md` beside this file lists, ending with `gh api "repos/{owner}/{repo}/compare/BASE...HEAD"` when `campaign` counts a verdict
4. `gh api "repos/{owner}/{repo}/issues/NUMBER/comments" --method POST -F body=@-`, with the comment on standard input
5. `gh api "repos/{owner}/{repo}/pulls/NUMBER" --method PATCH -F body=@-`, with the body on standard input

The first three are reads. `publish` skips step 3 when the pull request has a record comment, step 4 when the newest record comment holds the record's digest, and step 5 when the body is already the render.

Under `--create`, on a record with no `pr.number`, these come before the five, in order:

1. `git branch --show-current`
2. `gh pr list --head BRANCH --state open --json number`
3. `gh pr create --head BRANCH --title TITLE --body-file -`, with the body on standard input, when no pull request is open for the branch

A call that fails or cannot be run stops the run, and so does an answer that does not have the shape that call's answer has. The message quotes the call. Nothing is written to GitHub after it. Without `--create` the record file is written last, so a failed call leaves it unchanged. Under `--create` the file keeps the number once the pull request is known, and the filled parts once the generators have run.

Exit 0 published, 1 refused, 2 unreadable or unparseable, or a call failed.

## `merge`

```bash
uv run path/to/scripts/change_record.py merge NUMBER
```

`merge` squash-merges pull request `NUMBER` with the commit message that its newest record comment renders. It takes no record file, because the record on the pull request is the one that was reviewed. The merge commit's subject is the rendered subject, and its body is the rest of the rendered message, whatever the pull request's title is.

`merge` decides nothing about whether a merge is allowed. It approves nothing, and it uses no administrator rights. A merge that GitHub refuses fails as any call does.

`merge` checks every reason to refuse before it asks for the merge. The checks that need no further read come first, and the first one that applies is the one reported.

| Code | `merge` refuses when |
| --- | --- |
| `no-record-comment` | The pull request has no record comment. |
| `record-comment`, `stale-pointer`, `stale-body`, or any code of `lint` | The record in the newest comment, or the body, fails what `lint --pr` checks. |
| `empty-campaign` | That record's campaign counts no review round. |
| `not-terminal-clean` | The campaign names no terminal commit, because its latest round did not end it clean. |
| `head-moved` | The pull request's head is not the commit the record was published at. |
| `head-not-cleared` | The pull request's head is not the campaign's terminal commit. |
| `reach` | The record's reach flag does not fit the changed paths, which are read at this point. |
| `stale-campaign` | `campaign`, run now, gives another campaign than the record holds. A review round posted after the record was published reads this way. Run `campaign` and `publish` again. |

`merge` reads the head from the pull request itself and trusts no head a record carries. It hands that head to GitHub with the merge, so a commit pushed after the checks is not merged. `merge` runs `campaign` as it runs with no `--app`.

`merge` makes these calls, in order:

1. `gh api "repos/{owner}/{repo}/pulls/NUMBER"`, for the body and the head
2. `gh api "repos/{owner}/{repo}/issues/NUMBER/comments?per_page=100&page=N"`, from page 1 until a page is empty
3. `gh api "repos/{owner}/{repo}/pulls/NUMBER/files?per_page=100&page=N"`, from page 1 until a page is empty
4. every call `campaign` makes, which `generators.md` beside this file lists
5. `gh pr merge NUMBER --squash --match-head-commit HEAD --subject SUBJECT --body-file -`, with the message's body on standard input

The first four are reads, and the fifth is the only write. A call that fails stops the run, and the message quotes the call.

Exit 0 merged, 1 refused, 2 a call failed.

## `extract-prose`, `dispatch-prose` and `apply-prose`

```bash
uv run scripts/change_record.py extract-prose record.json [--output FILE]
uv run scripts/change_record.py dispatch-prose request.json
uv run scripts/change_record.py apply-prose record.json response.json
```

The three are the rewrite pass over the record's wording. `extract-prose` writes a request that lists each field an editor may reword, with its text and the digest of that text. `dispatch-prose` prints the model and the effort to run the editor at, and the paths of the editor's instruction file and of the request. `apply-prose` applies the replacements of a response to the record. It checks the whole response first, and one refused replacement leaves the record file as it was. All three only read and write files.

`rewriting.md` beside this file gives the request, the dispatch, the response, every refusal, the values a replacement must keep, and the rule of one pass for each revision.

`extract-prose` exits 0 written, 1 the record does not fit the schema, 2 unreadable, unparseable or unwritable. `dispatch-prose` exits 0 printed, 2 the pin file or the instruction file is missing, or the pin file names no model or no effort. `apply-prose` exits 0 applied or nothing to apply, 1 refused, 2 unreadable or unparseable.
