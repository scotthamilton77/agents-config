# The generators

Three subcommands fill the parts of a record that hold facts from the tracker and from GitHub. The author types none of those parts.

| Subcommand | Fills | Reads |
| --- | --- | --- |
| `context` | `where_this_fits`, with its stamp | the tracker through `work`, and GitHub through `gh` |
| `discovered` | the filed rows of `discovered`, with their stamp | the tracker through `work` |
| `campaign` | `campaign`, with its stamp | GitHub through `gh` |

`commands.md` beside this file gives the command lines, where to run them and their exit statuses. This file says how each part is derived.

Every call any of them makes is a read. None writes to the tracker or to GitHub.

All three copy text that other people wrote: a title, a reason, or a reviewer's claim and evidence. A text that holds a `<details>` fold, an HTML comment or a line that opens a `json` fence is written with that construct quoted as a code span. The reader then sees the same characters, and a generated part never fails `lint` under `machine-content`. When a span cannot quote the construct where it stands, the whole line is quoted. A fold whose tag breaks onto a second line has its first line quoted.

A text is copied with any line break it holds. The pull request body shows such a break as a space where the text stands on a line, and as `<br>` in a table cell, so every line and every row stays whole. A byte in an answer that is not UTF-8 is replaced with the mark for an unreadable character. A title that holds half of a surrogate pair cannot be written at all, so the run fails and names the field. A review verdict that holds one is skipped as unreadable, as the `campaign` section below says.

All three check every answer before they read it. An answer must have the shape its call's answer has: a list where a list belongs, each entry with the fields the generator reads, and each field of its own type. An answer about several items must hold each item asked for once, and no other. An answer that fails the check stops the run. It is never read as an empty result.

## `context`

`context` computes four things and writes them together.

**Ancestry.** The chain runs from the item with no parent down to the work item. Each step reads the parent field of the item below it. An id that looks like a path is never read as one, because an item can move without its id changing. Each entry holds the item's id, its title and the tracker's type for it.

**The owning item.** The owning item is the work item's parent. A work item with no parent is its own owning item. So is a work item whose parent is the root of the tree, because the root's children are every piece of work in the project.

**The scope table.** The table has one row per child of the owning item, in id order. Each row holds the child's id, its title and one status:

| Status | When |
| --- | --- |
| `this PR` | The child is the record's work item. |
| `done` | The child is closed. |
| `in flight` | An open pull request names the child. The row carries that pull request's number. |
| `open` | Anything else. |

The statuses are tried in that order, so a closed child is `done` even when an open pull request names it. A pull request names an item when its title closes with the item's id in brackets, short or full, as in `fix(gate): a pin survives a retry [a1b.3]`. When two open pull requests name one child, the row carries the lower number, whichever form of the id each uses. An owning item with no child gets a single row, which is the work item as `this PR`.

**Builds on.** These are the merged pull requests that delivered the owning item's closed children. The number comes from the delivery the tracker recorded in the child's notes, written as a number, as a number after `#`, or as a pull request's URL. `context` asks GitHub about each one. A merged pull request is listed with its title, and one that closed without merging is left out. A child that is still open adds nothing, even when one of its pull requests has merged.

A delivery can name a repository, as `owner/name#12` does and as a URL does. Such a delivery counts only when the repository is the working directory's own, which `context` asks GitHub for. The same number in another repository is another pull request. It is left out and is never looked up here. A delivery that names no repository is a pull request of this one.

**Concurrent.** These are the open pull requests, other than the record's own, that touch a path the record's pull request touches. Each is listed with its title. A renamed file counts under its old path and its new one. `context` reads the list of open pull requests a page at a time until a page comes back empty, and reads each pull request's files the same way.

An empty `builds_on` or `concurrent` list means none.

### A record with no pull request number

A pull request's files come from GitHub, so `context` cannot look for concurrent pull requests until `pr.number` is set. Until then it leaves `concurrent` empty. When another pull request is open, it also adds a row to `heads_up` that opens with `context:` and says the open pull requests were not checked. Every other part is filled as usual. Set `pr.number` once the pull request is open and run `context` again. That run fills `concurrent` and takes the row out.

A generator's `heads_up` row takes the place of a `None.` entry. When the row goes and no other entry is left, `None.` comes back.

## `discovered`

`discovered` writes one filed row for each tracker item whose discovered-from edge points at the record's work item. The row holds the item's id in `item`, its title in `what`, and in `reason` the reason its triage record gives for the scope call.

The triage record is the `## Triage` heading in the item's description with the scope line straight under it. The last one in the description counts. One quoted inside a fenced block is an example and does not count.

The filed rows come first, in id order. Every not-filed and in-flight row stays as the author wrote it, in the order the author wrote it. Each run replaces the filed rows, so a row whose item is no longer discovered from the work item goes.

A `None.` entry goes when a filed row arrives. `discovered` never writes `None.`, because only the author can say that the pull request found nothing.

An item with a discovered-from edge and no triage record in its description makes `discovered` fail, naming the item. So does an item whose only triage record is a quoted example. File discovered work with `work discover`, which writes the triage record.

`discovered` writes the stamp on every run, over an empty list when no item was found.

## `campaign`

`campaign` reads the pull request's reviews and builds the part from the verdicts they carry.

**Which reviews count.** A review carries a verdict when its body ends in a fenced `json` block, which is how the reviewing App posts one. Every other review is passed over without a message. Of the reviews that carry a verdict, one counts when a bot account posted it, and `--app` narrows that to one login. A review by any other author is skipped. So is a review that is not a submitted review that still stands, which is one GitHub reports as pending or as dismissed. Each skipped review is named on stderr with the reason, so no verdict goes uncounted without a word.

**Which verdicts are unreadable.** A verdict the reviewing App posted is skipped as unreadable in five cases. It cannot be loaded as JSON. It is nested too deeply to read. It holds half of a surrogate pair. The `review-verdict` skill's validator rejects it. Or one of its identifiers holds a `<details>` fold, an HTML comment or a `json` fence. The identifiers are the claim id, the artifact class, a reviewer's name, a finding's id and the work item a disposition names. The record takes them as they are written, because a reply is matched to its finding by them, so they cannot be quoted the way a claim is.

**Reviewer rows.** There is one row per reviewer that a counted verdict names. `rounds` gives the lowest and the highest round the reviewer ran in, across every claim and artifact class. It reads `1 to 4`, or one number when the two are equal. The range does not say that the reviewer ran every round between them. `findings` counts each finding the reviewer raised once. `fixed`, `rejected` and `deferred` count those findings by their latest disposition. `rebutted` counts as rejected, and `advisory-deferred` and `transferred` count as deferred. A finding that no verdict gives a disposition to is counted under `findings` alone, so the three columns can total less than it.

**Findings.** There is one entry per finding, in the order the verdicts raised them. A finding is named by its verdict's claim id and artifact class together with its own id. The entry gives the round the finding first appeared in, its claim, its latest disposition, and the evidence given with that disposition as the reason. A finding with no disposition carries neither a disposition nor a reason.

**The commit.** A finding's `commit` comes from the pull request author's reply on the finding's own thread, which the reviewing App opens with an inline comment. `campaign` reads the commit from one of two places in that reply. The first is in parentheses at the end of the reply's `Change:` line. The second, for a reply with no such line, is straight after the word "commit". When the author replies more than once, the latest reply that names a commit decides. The `commit` is empty for a finding with no thread and for a reply that names no commit in either place. It is empty for every finding when the pull request author's account is gone, because no reply is then the author's. `campaign` copies no commit from the record's `replies`, and it changes no entry there, so an outcome the author chose stays.

**The terminal commit.** `campaign` leaves `terminal_sha` empty. Whether a round was complete is a rule the `review-verdict` skill states, and that skill ships no function that decides it.

### An empty campaign

`campaign` adds one row to `heads_up` when it counts no verdict. The row opens with `campaign:`.

- When no review carried a verdict that counts, the row reads `campaign: No review round has run on this pull request.`
- When every verdict the reviewing App posted was unreadable, the row gives their count, as in `campaign: 2 reviews carry verdicts that could not be read, so no review round is counted.`

The row behaves as the row `context` writes does. It takes the place of a `None.` entry, and the next run that counts a verdict takes it out. When it goes and no other entry is left, `None.` comes back.

## Running again

A second run over unchanged sources leaves the file byte for byte as it was. Run a generator again when its sources change. That is when the pull request opens, when a sibling item closes or a sibling pull request merges, when new work is filed, and when a review round is posted or answered.

A hand edit of a generated part fails `lint` under `stale-stamp`. Running the part's generator again replaces the edit and clears the finding.

## The calls each one makes

`context` makes these, in order:

1. `work --format json show ID`, once for the work item and once for each item above it
2. `work --format json list --parent ID`, for the owning item
3. `gh api "repos/{owner}/{repo}/pulls?state=open&per_page=100&page=N"`, from page 1 until a page is empty
4. `gh repo view --json nameWithOwner,url`, once, when a closed child's delivery names a repository
5. `gh pr view NUMBER --json number,state,title`, once for each pull request of this repository that a closed child was delivered by
6. `gh api "repos/{owner}/{repo}/pulls/NUMBER/files?per_page=100&page=N"`, from page 1 until a page is empty, for the record's pull request and then for each other open one

`context` skips step 6 when the record has no number or no other pull request is open.

`discovered` makes these, in order:

1. `work --format json dep list ID`, for the work item
2. `work --format json show ID ...`, once, for every discovered item together

`discovered` skips step 2 when no item was discovered.

`campaign` makes these, in order:

1. `gh api "repos/{owner}/{repo}/pulls/NUMBER"`, for the pull request's author
2. `gh api "repos/{owner}/{repo}/pulls/NUMBER/reviews?per_page=100&page=N"`, from page 1 until a page is empty
3. `gh api "repos/{owner}/{repo}/pulls/NUMBER/comments?per_page=100&page=N"`, the same way, for the author's replies

`campaign` reads no issue comment.
