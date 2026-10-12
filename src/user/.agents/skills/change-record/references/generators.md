# The generators

Two subcommands fill the parts of a record that hold facts from the tracker and from GitHub. The author types neither part.

| Subcommand | Fills | Reads |
| --- | --- | --- |
| `context` | `where_this_fits`, with its stamp | the tracker through `work`, and GitHub through `gh` |
| `discovered` | the filed rows of `discovered`, with their stamp | the tracker through `work` |

Run each from inside the repository the pull request belongs to. `work` and `gh` both read the repository of the working directory. Give the script by its path in this skill's directory:

```bash
uv run path/to/scripts/change_record.py context path/to/record.json
uv run path/to/scripts/change_record.py discovered path/to/record.json
```

Neither takes an id on the command line. Both read the work item from `work_item.id`, and `context` reads the pull request from `pr.number`. A generated part therefore always describes the record's own work item.

Every call either one makes is a read. Neither writes to the tracker or to GitHub.

Both copy titles and reasons that other people wrote. A title that holds a `<details>` fold, an HTML comment or a line that opens a `json` fence is written with that construct quoted as a code span. The reader then sees the same characters, and a generated part never fails `lint` under `machine-content`. When a span cannot quote the construct where it stands, the whole line is quoted.

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

The statuses are tried in that order, so a closed child is `done` even when an open pull request names it. A pull request names an item when its title closes with the item's id in brackets, short or full, as in `fix(gate): a pin survives a retry [a1b.3]`. When two open pull requests name one child, the row carries the lower number. An owning item with no child gets a single row, which is the work item as `this PR`.

**Builds on.** These are the merged pull requests that delivered the owning item's closed children. The number comes from the delivery the tracker recorded in the child's notes, written as a number, as a number after `#`, or as a pull request's URL. `context` asks GitHub about each one. A merged pull request is listed with its title, and one that closed without merging is left out. A child that is still open adds nothing, even when one of its pull requests has merged. A number is looked up in the working directory's repository.

**Concurrent.** These are the open pull requests, other than the record's own, that touch a path the record's pull request touches. Each is listed with its title. A renamed file counts under its old path and its new one. `context` reads the list of open pull requests a page at a time until a page comes back empty, and reads each pull request's files the same way.

An empty `builds_on` or `concurrent` list means none.

### A record with no pull request number

A pull request's files come from GitHub, so `context` cannot look for concurrent pull requests until `pr.number` is set. Until then it leaves `concurrent` empty. When another pull request is open, it also adds a row to `heads_up` that opens with `context:` and says the open pull requests were not checked. Every other part is filled as usual. Set `pr.number` once the pull request is open and run `context` again. That run fills `concurrent` and takes the row out.

A generator's `heads_up` row takes the place of a `None.` entry. When the row goes and no other entry is left, `None.` comes back.

## `discovered`

`discovered` writes one filed row for each tracker item whose discovered-from edge points at the record's work item. The row holds the item's id in `item`, its title in `what`, and in `reason` the reason its triage record gives for the scope call.

The filed rows come first, in id order. Every not-filed and in-flight row stays as the author wrote it, in the order the author wrote it. Each run replaces the filed rows, so a row whose item is no longer discovered from the work item goes.

A `None.` entry goes when a filed row arrives. `discovered` never writes `None.`, because only the author can say that the pull request found nothing.

An item with a discovered-from edge and no triage record in its description makes `discovered` fail, naming the item. File discovered work with `work discover`, which writes the triage record.

`discovered` writes the stamp on every run, over an empty list when no item was found.

## When a call fails

Each generator computes everything first and writes the record file once. It exits 2 and leaves the file exactly as it was when any of these happens:

- the tracker does not know the work item
- a `work` or `gh` call exits with an error, or cannot be run
- an answer lacks a field the generator reads
- the record cannot be read, or does not fit the schema

The message on stderr quotes the call that failed, so it names the id the call was given. Exit 0 means the record holds the part.

## Running again

A second run over unchanged sources leaves the file byte for byte as it was, and says so. Run a generator again when its sources change: when the pull request opens, when a sibling item closes or a sibling pull request merges, and when new work is filed.

A hand edit of a generated part fails `lint` under `stale-stamp`. Running the part's generator again replaces the edit and clears the finding.

## The calls each one makes

`context` makes these, in order:

1. `work --format json show ID`, once for the work item and once for each item above it
2. `work --format json list --parent ID`, for the owning item
3. `gh api "repos/{owner}/{repo}/pulls?state=open&per_page=100&page=N"`, from page 1 until a page is empty
4. `gh pr view NUMBER --json number,state,title`, once for each pull request a closed child was delivered by
5. `gh api "repos/{owner}/{repo}/pulls/NUMBER/files?per_page=100&page=N"`, from page 1 until a page is empty, for the record's pull request and then for each other open one

`context` skips step 5 when the record has no number or no other pull request is open.

`discovered` makes these, in order:

1. `work --format json dep list ID`, for the work item
2. `work --format json show ID ...`, once, for every discovered item together

`discovered` skips step 2 when no item was discovered.
