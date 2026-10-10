# Change records: one linted record behind the PR body, the commit message and the review reply

**Date:** 2026-10-10
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D16 removal conditions, D20 admission records). Draft. The criteria have not been attacked.
**Work item:** `agents-config-9k9.484` (this spec's container), design child `agents-config-9k9.484.1`, implementation placeholder `agents-config-9k9.484.2`.
**Related:** the `readable-prose` skill (sentence quality, which this spec does not restate); the `review-panel` skill's dispositions section and the `review-verdict` envelope (the campaign data this spec reads); prgroom's reply writer and its Decisions block (a bot-owned region of the PR body this spec preserves).
**Design inputs:** `.claude-scratch/git-doc-templates-proposal-v2.md` and its mock `.claude-scratch/git-doc-templates-mock-v2.html` (the templates, rendered over pull requests 838, 839, 843 and 846); `docs/reference/2026-10-10-gpt-prose-rewriter-implementation-brief.md` (the rewrite pass, adopted in part).
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Agents write three artifacts for every change: the pull request description, the commit message and the replies on review findings. No template governs any of them. The `readable-prose` skill governs sentences, and one sentence in the root `AGENTS.md` governs replies. Everything else is improvised per PR.

The owner reads the result and has to ask. On the twelve most recent merged PRs, every description used a tracker id, criterion id or decision id on first mention with no words saying what it is. None said where the change sits in the milestone's tree. None had a risk or blast-radius section. None listed the work the author discovered and did not do. Across the twelve there were 46 distinct level-two headings, so no two read alike. Commit subjects ran to a median of 91 characters, and the repository's squash setting concatenates every branch commit into the merge commit, so a merged commit carries the same attribution trailers four or five times. Replies restate the campaign's status and bury what changed.

The cost lands on the one person this harness is meant to free. The prime directive asks whether a change reduces human interventions per merged PR. A description the owner can read once and approve is the direct answer.

## 2. Scope

In scope: the template for each of the three artifacts; a JSON change record that is the single source each artifact renders from; a schema and a lint over that record; generators that fill the record's factual sections from the tracker and from GitHub; publication of the record as an append-only PR comment with the body rendered from it; a merge command that supplies the rendered commit message; a bounded rewrite pass over the record's prose fields on a cheaper model; the repository squash settings; one sentence each in the `review-panel` skill and the root `AGENTS.md` pointing at the new skill.

Out of scope: a commit or PR hook that enforces the lint. The skill is adopted first and a hook is added only if lint failures are observed on merged PRs after ten PRs; that observation is recorded in the Continuations section as not filed. Also out: Claude Code's attribution settings; a commitlint configuration; the verdict envelope's own format; PRs opened by Dependabot or release bots, which the templates leave untouched; the ordering of comments GitHub displays.

## 3. The artifacts

The three templates below are the contract. The skill ships them as reference files, and the renderer produces them from the record. Fenced blocks here are illustrations; the renderer's golden files are the exact form.

### 3.1 The PR body

```markdown
<Summary, no heading. The problem, then what is true now, then what remains.
Three to five sentences. Every id glossed on first use.>

## Heads-up
- <Anything that should lower a reader's confidence. One sentence each.>
- None.    (written when there is nothing)

## Where this fits
<ancestry from the milestone down to the owning item, one line each: id, title, role>
    this PR: <which slice of the owning item>
Builds on: <merged PRs, each glossed>. Concurrent: <open PRs touching the same paths, each glossed>.
<details><summary>Scope of the owning item</summary>
<table: slice, what it covers, status: done / this PR / open / in flight (#PR)>
</details>

## Risk
<table: what could go wrong, who or what is exposed, how we know it did not, what to do if it did>
<details><summary>Blast radius</summary>
<fenced Mermaid block: reach graph from the changed component outward, edges labelled by kind of impact>
<fenced Mermaid block: the affected task flow with the changed steps marked>
</details>

## Changes
- **<Topic>.** <What is different now, in words.>
<details><summary>Design notes</summary>
<Why this approach. Rejected alternatives and what breaks under them.>
</details>

## Discovered work
<table: item, status (filed / not filed / in flight, informed), what it is, why not in this PR>

---

## Verification
- <gate>: exit <n>, run standalone from <where> at <head sha>.
- Not run: <what, and why>. ("None.")

### Review campaign
<table: reviewer, rounds, findings, fixed, rejected, deferred>
Terminal-clean at <sha>. Approval is a machine attestation of that head.
<details><summary>Findings by round</summary>
<table: round, id, finding in plain words, disposition, reason, commit>
</details>

## Criteria
<table: criterion, what it promises, evidence>

<details><summary>Proposed commit message</summary>
<the commit message, exactly as the merge will use it>
</details>

<prgroom Decisions block, carried byte-for-byte when present; never authored>

Rendered from change record <comment link>, revision <n>.
🤖 Generated with Claude Code · <session url>
```

The body is for the human. It carries no JSON and no fold of machine content. Everything above the horizontal rule is the one-pager; everything below is evidence a reader opens on purpose.

Variants by commit type. A `feat`, `fix`, `refactor`, `perf` or `test` PR carries every section; the blast-radius diagrams are required only when the change reaches outside its own package. A `spec` PR's blast radius is the items the spec will mint, and its Criteria section is one line saying whether the criteria were attacked and where the record is. A `docs` or `chore` PR carries Heads-up, a one-row Risk table, Changes and Verification, and omits Criteria. Discovered work is required for every type; a PR that found nothing writes a single row reading "None."

### 3.2 The commit message

```text
<type>(<component>): <what is true after this merges> [<short tracker id>]

Work item <full tracker id>, <what the item is for>.

Why
<The problem and who it affected. Two or three sentences.>

Change
<What is different now. Three or four sentences. No file names unless the
reader must go there.>

Verification
<The decisive check and its observed result. What was not run.>

Work-item: <full tracker id>
Co-authored-by: <model> <noreply@anthropic.com>
Claude-Session: <url>
```

The subject is at most 100 characters. The type is one of commitlint's eleven plus this repository's `spec`. The component is the thing a reader would grep for, such as `review-panel` or `installer`, never a tracker id. The short tracker id sits in brackets at the end so a one-line log still carries it.

The work item appears twice, once per reader. The first body line is a plain sentence for the human: the full id, a comma, and what the item is for. The `Work-item:` trailer in the last paragraph is for git, because `git interpret-trailers` reads only the last paragraph. The two are rendered from one record field, so they cannot disagree.

The body is 80 to 150 words. A trivial change may omit the body; the trailers stay. The trailers are `Work-item`, `Co-authored-by` and `Claude-Session`, and nothing else.

### 3.3 The review reply

```text
Outcome: Fixed | Superseded | Rejected | Deferred.
Change: <What is different now, in one or two sentences.> (<commit>)
Verification: <The check and what it showed. For a prose fix, the lint or the
re-read. For a rejection, the evidence against the finding.>
```

A reply is 40 to 90 words. One reply goes on each finding that changed code or prose, and one on each rejection. A deferral names the item that inherits the finding. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. Rejected gives evidence, never a bare disagreement. Campaign status is stated once, in the PR body's Verification section, and never in a reply.

### 3.4 Writing checks

These apply to the summary, Heads-up, Risk and Changes, and the first four apply below the fold as well. The lint enforces the ones it can. The author and the rewrite pass hold the rest.

1. A stranger can read it. Every work item, criterion, decision, section and PR number carries a gloss on first use. Every house term is defined where it first appears or replaced with a common word.
2. Problem, then change, then what remains. No history of how the text got here.
3. One clause per sentence.
4. Say the number, then what it means.
5. Verbs do the work.
6. No commentary about the document. Nothing says "this section describes" or "note that".
7. A caveat is a Heads-up row, not a clause.

## 4. Decisions

### CR-D1. The record is the source and every artifact is a rendering

A JSON change record, validated by a JSON Schema the skill ships, holds everything the three artifacts say. The PR body, the commit message and each reply are rendered from it by one script. An agent never writes a PR body by hand. The reasons: a record can be linted before anything reaches GitHub; a rewrite pass can edit prose fields without touching facts; the commit message and the body cannot drift apart; and the campaign table and the ancestry are generated from their sources instead of typed.

The refuted alternative is a Markdown template the agent fills in. It is lintable only by regex over prose, it offers the rewrite pass no boundary between fact and wording, and nothing stops the agent from improvising a heading. That is the state the twelve PRs in section 1 are in.

### CR-D2. The record lives in an append-only PR comment, found by a marker

Each revision of the record is posted as its own PR-level comment. The comment opens with an HTML comment marker naming the schema version, the PR number, the revision and the record's digest, followed by the record in a collapsed fold. A later revision is a new comment, never an edit of an earlier one. The PR body carries one line naming the comment and revision it was rendered from.

Each GitHub comment has the same 65,536-character cap as the body. Keeping the record out of the body gives the human artifact the whole budget and gives the machine artifact its own. The sequence of record comments is the description's history, which the body itself does not carry; that matches the house rule that an artifact states the current decision and git is the changelog. Marker lookup is how prgroom already finds its own comments, and verdict envelopes are found the same way, so a third marked comment kind adds no new mechanism.

The refuted alternative is a collapsed fold of JSON at the end of the body. It spends body budget, it puts machine content in front of the human reader, and a hand edit of the body can silently change the record.

### CR-D3. The PR body is never the squash commit body, and the squash setting flips last

At an authorized merge, the rendered commit message is supplied explicitly through `gh pr merge --squash --body-file`, by a `merge` subcommand that reads it from the newest record comment. An explicit body overrides the repository's squash default, so the pipeline produces clean merge commits under the current `COMMIT_MESSAGES` setting from the day slice P lands. A PR body carries tables, folds, Mermaid and a bot-owned block, none of which belong in `git log`.

The repository's squash settings become `PR_TITLE` and `BLANK` only as the last act of the whole spec. A repository setting is live for every session the moment it flips, and no branch or review covers it. Under `BLANK`, a plain `gh pr merge --squash` from a session that does not know the skill produces a merge commit with a title and no body: no work-item line, no attribution trailers. So the flip waits for evidence that merges have stopped omitting the message: the merge command is written into the delivery contract first, and the setting changes only after five consecutive squash merges on `main` carry a `Work-item` trailer. The current setting's repeated trailers are the lesser harm until then.

### CR-D4. A new shared skill, `change-record`, beside `readable-prose`

The skill lives in the shared tree so it follows agents to every tool. It is not folded into `readable-prose`, because that skill governs sentences and loads when a document is drafted, while this one governs shape, carries a schema and a script, and loads when a PR, commit or reply is written. Two concerns in one skill would make either harder to retire on its own removal condition. The one piece of code lives beside the templates it serves.

### CR-D5. Generated sections are generated

Where this fits, the scope table, the filed rows of Discovered work, and the whole Review campaign section are written by the script from the tracker and from GitHub, never typed by the agent. The agent writes one line in Where this fits, naming which slice this PR is, and the not-filed and in-flight rows of Discovered work, which only the agent knows. Ancestry follows parent fields through `work show`; it is never inferred from a dotted id. A generated section the agent could edit by hand would drift the moment it was convenient.

### CR-D6. The rewrite pass proposes per-section replacements and the author decides

The rewrite editor is a Codex dispatch, starting on `gpt-6-luna` at low effort. It receives the whole record, the list of editable fields and the writing checks. It returns a list of replacements, each naming the record digest and the section digest it was written against, and may return a question for a section it cannot rewrite without inventing a fact. It never returns a rewritten record or a rewritten body.

Editable fields are those the schema marks `x-rewritable`: the summary, Heads-up rows, the Risk table's prose cells, Changes and design notes, the commit body's three prose sections, and reply text. Everything else is protected: ids, ancestry, URLs, commands, shas, counts, statuses, criterion obligations, dispositions, attribution and the Decisions block. The commit subject's wording is editable; its type, component and bracketed id are not.

The script refuses a stale, malformed or out-of-allowlist response without touching the record, and refuses a replacement that drops or changes a protected value found in the original text. Meaning is the author's check, not the script's: the script cannot tell "the gate reported exit 0" from "the change is verified", so the author reads each diff for a strengthened claim, a dropped exception or erased deferred work, and prunes the response to the replacements it accepts before applying. One pass, no retry loop. The record's revision history is the audit; rejected proposals are dropped.

The 36-run model experiment in the GPT brief is not adopted. The cheaper measurement is the author's correction count over the first ten real PRs; effort steps up to medium and then to `gpt-6.1-sol` only if corrections do not fall.

### CR-D7. Campaign data comes from the verdict envelopes

The campaign table and the findings list are computed from the verdict envelopes prgroom posts, which already carry the round, the head sha, the reviewers that ran, every finding's id and claim, and every prior disposition. The fix commit for a finding comes from the author's reply when a reply names one, and is otherwise blank; the envelope does not carry it, and the author's reply is the only durable place it is written. The table counts distinct finding ids, not comments or commits. A disposition of `rebutted` renders as Rejected, `fixed` as Fixed, and `advisory-deferred` or `transferred` as Deferred; Superseded is chosen by the author in the record and never by the script.

### CR-D8. The pipeline never writes a review comment and never edits a comment it did not post

The verdict envelopes and the author's replies stay where they are. The script's only GitHub writes are creating a record comment and setting the PR body. The prgroom Decisions block inside the body is carried byte-for-byte on every render. This holds by construction, so nothing a future change does to the templates can disturb a verdict.

### CR-D9. No hook until drift is observed

The skill, its lint and the one-sentence pointers in `review-panel` and the root `AGENTS.md` are the whole enforcement for the first ten merged PRs. A pre-commit or pre-PR hook is a second mechanism and is added only on the observation that merged PRs fail the lint after the skill is in place. The observation and its threshold are recorded in Continuations.

## 5. The record

The record is one JSON document. Its field groups, with their owner, are:

| Group | Holds | Written by | Rewritable |
| --- | --- | --- | --- |
| `pr` | number, title, type, component, head sha | agent at init, `publish` for the number | title wording only |
| `work_item` | full id, gloss, which slice this PR is | agent | gloss |
| `summary`, `heads_up` | the one-pager's opening and its caveats | agent | yes |
| `where_this_fits` | ancestry, builds-on, concurrent, scope table | `context` | no |
| `risk`, `blast_radius` | the risk rows, two Mermaid sources | agent | prose cells only |
| `changes`, `design_notes` | topical changes and reasoning | agent | yes |
| `discovered` | filed, not-filed and in-flight rows | `discovered` for filed rows, agent for the rest | reason cells only |
| `verification` | gates with exit status and location, not-run list | agent | no |
| `campaign` | reviewer rows, terminal sha, findings | `campaign` | no |
| `criteria` | id, promise in plain words, evidence | agent | promise wording only |
| `commit` | subject, why, change, verification prose | agent | prose, and the subject's wording |
| `replies` | per finding: outcome, change, verification | agent | prose |
| `record` | schema version, revision, digest, comment id | `publish` | no |

The schema marks each rewritable field with `x-rewritable: true`. The lint reads the schema for that list, so the allowlist and the schema cannot disagree.

The record comment's first line is `<!-- change-record v<schema> pr=<n> rev=<k> sha256=<digest> -->`, where the digest is over the record's canonical JSON with the `record` group removed. The body's pointer line names the comment's URL and the revision.

## 6. Slices and acceptance criteria

Seven slices, each one pull request, each small enough that the owner can vet it by reading one script, one schema or one set of golden files and running one command. Suite criteria run under `content-tests`, which discovers the skill's test file beside its script. Where a criterion needs the tracker or GitHub, the suite puts a shim named `work` or `gh` on `PATH` that replays recorded output; no suite reaches the network. Each criterion states the obligation, then its check.

### Slice L: the skill, the schema, `init` and `lint`

What the owner vets: the skill text, the schema, the four example records, and `lint` run over them.

- **CR-L1** A record missing any required field group, or carrying a field the schema does not define, fails `lint` with the field named; each of the four example records built from pull requests 838, 839, 843 and 846 passes. Check: suite, one case per required group removed, one unknown top-level field, one unknown nested field, and the four fixtures.
- **CR-L2** A rewritable field whose text names a tracker id, criterion id, decision id or PR number with no gloss on that id's first use in the record fails `lint`, naming the field and the id; the same id glossed on first use and bare on a later use passes. Check: suite, one case per id shape (a dotted tracker id, a hyphenated criterion id, a bare `D16`, a `#843`), each as a failing bare first use and a passing glossed first use, and one case where the first use is in `summary` and the later bare use is in `changes`.
- **CR-L3** A commit subject fails `lint` when it exceeds 100 characters, when its type is outside commitlint's eleven plus `spec`, when it has no component, or when it lacks the bracketed short id at its end; a 100-character subject of the right form passes. Check: suite, one case each, with the failure naming the rule broken.
- **CR-L4** A record states emptiness explicitly: an empty `heads_up`, an empty `discovered` or a `risk` table with no row fails `lint`, and a single `None.` entry passes for `heads_up` and `discovered`. Check: suite, one case each way.
- **CR-L5** A `discovered` row fails `lint` when its status is filed and it names no item id, when its status is in flight and it names no PR, or when any row has an empty reason. Check: suite, one case each.
- **CR-L6** A record fails `lint` when its summary has fewer than three or more than five sentences, when its commit body is present and outside 80 to 150 words, or when any reply is outside 40 to 90 words; a record with no commit body passes the body check. Check: suite, the boundary values on each side of every limit.
- **CR-L7** A rewritable field containing a phrase of document commentary from the skill's list, such as "this section" or "note that", fails `lint` naming the phrase; the same phrase inside a fenced code span passes. Check: suite, one case per listed phrase and one fenced case.
- **CR-L8** `init` given a type, a component and a work item id writes a record that passes schema validation and fails `lint` on exactly the fields the author must fill, each named; running `init` where a record already exists refuses and leaves the file unchanged. Check: suite, one run and one rerun.
- **CR-L9** The skill deploys to the shared tree: `content-lint` run standalone at the landed head exits 0, and the staged shared tree for each supported tool contains the skill directory with its schema, its templates and its script. Check: `make content-lint` exit status, and the staging listing in the evidence row.

### Slice R: `render`

What the owner vets: the rendered body, commit message and replies for the four fixtures, diffed against the golden files.

- **CR-R1** Rendering each of the four fixtures produces a body byte-identical to its golden file, whose level-two headings in order are Heads-up, Where this fits, Risk, Changes, Discovered work, Verification and Criteria, and whose text above the first horizontal rule is at most 400 words for the three implementation PRs. Check: suite, golden diff and a heading walk.
- **CR-R2** Rendering with an existing body that holds a prgroom Decisions block between its sentinels reproduces that block byte-for-byte at the template's position, including a block that itself contains a `<details>` fold and a marker comment; rendering with no such block emits no Decisions heading. Check: suite, two cases.
- **CR-R3** The rendered commit message has the work-item sentence as its first body line, and `git interpret-trailers --parse` run over it returns exactly `Work-item`, `Co-authored-by` and `Claude-Session`, with the `Work-item` value equal to the record's full id. Check: suite, runs `git interpret-trailers` on each fixture's output.
- **CR-R4** The rendered commit message contains no Markdown table, no `<details>`, no fenced block and no HTML comment. Check: suite, pattern absence on all four fixtures.
- **CR-R5** A reply rendered from a finding entry is three lines beginning `Outcome:`, `Change:` and `Verification:`, the outcome word is one of Fixed, Superseded, Rejected and Deferred, and a finding with no commit renders `Change:` with no trailing parenthesis. Check: suite, one case per outcome and one with no commit.
- **CR-R6** `render` on a record that fails `lint` writes nothing and exits non-zero with the lint output. Check: suite.
- **CR-R7** Two renders of one record are byte-identical, and a render after a no-op rewrite of the record file (reserialized, same content) is byte-identical to the first. Check: suite.

### Slice X: `context` and `discovered`

What the owner vets: the two generators run against a live work item, compared to `work show` by eye.

- **CR-X1** `context` given a work item id writes the ancestry from the milestone down to the item, each entry with id, title and type, by following parent fields; when a dotted id disagrees with the parent field, the output follows the field. Check: suite, a `work` shim whose chain has one item whose dotted prefix is not its parent.
- **CR-X2** `context` writes the scope table from the owning item's children: each child's title and a status of done (closed), this PR (the record's item), in flight (an open PR names it) or open. Check: suite, a `work` shim with one child in each state and a `gh` shim listing one open PR.
- **CR-X3** `context` writes builds-on as the PRs recorded on the owning item's closed children and concurrent as the open PRs, other than this one, that touch a path this PR touches, each with the PR's title as its gloss. Check: suite, shims with two closed children carrying PR numbers, two open PRs of which one shares a path.
- **CR-X4** `context` on an id the tracker does not know exits non-zero naming the id and leaves the record unchanged. Check: suite.
- **CR-X5** `discovered` writes one filed row per item whose discovered-from edge points at this PR's work item, with the item's id, title, and its triage record's scope reason as the reason, and leaves every not-filed and in-flight row the author wrote in place. Check: suite, a shim with two discovered items and a record already holding one not-filed row; the output holds three rows in the order filed, not filed, in flight.
- **CR-X6** A second run of `context` or of `discovered` with unchanged inputs leaves the record byte-identical, and the author's one line naming the slice survives both runs. Check: suite.

### Slice C: `campaign`

What the owner vets: `campaign` run over the captured comments of pull request 843, compared to the table in the mock.

- **CR-C1** `campaign` given a PR number reads every comment carrying a verdict envelope and writes one row per reviewer that appears in any envelope, with the rounds it ran as a range, and its counts of distinct finding ids, fixed, rejected and deferred, where rebutted counts as rejected and advisory-deferred and transferred count as deferred. Check: suite, the captured comments of pull request 843 as the fixture, against the expected rows.
- **CR-C2** The findings list has one entry per distinct finding id with the round it first appeared, its id, its claim, its latest disposition, and the commit from the author's reply on that finding when the reply names one, else empty. Check: suite, the same fixture, including one finding whose reply names a commit and one whose reply does not.
- **CR-C3** A PR with no envelope comment yields an empty campaign and a `heads_up` row saying no review round has run. Check: suite, a `gh` shim returning comments with no envelope.
- **CR-C4** A comment whose envelope fails the `review-verdict` schema is skipped and named on stderr, and the remaining envelopes are counted. Check: suite, the fixture with one envelope's `verdict` field removed.
- **CR-C5** The terminal sha is the head sha of the latest envelope when that envelope's verdict is clean; otherwise the field is empty and a `heads_up` row says the latest round is not clean. Check: suite, one case each.
- **CR-C6** A second run of `campaign` over unchanged comments leaves the record byte-identical. Check: suite.

### Slice P: `publish` and `lint --pr`

What the owner vets: `publish` run in dry-run against a real PR, printing the comment and body it would write.

- **CR-P1** `publish` on a PR with no record comment creates one comment whose first line is the marker with revision 1 and the record's digest and whose body holds the record in a fold, then sets the PR body to the render with a pointer line naming that comment and revision; the record file's `record` group gains the comment id and revision. Check: suite, a `gh` shim recording calls.
- **CR-P2** `publish` on a PR with an existing record comment creates a new comment at the next revision and makes no edit or delete call on any comment. Check: suite, shim with one prior record comment; the recorded calls hold one create and one body edit.
- **CR-P3** `publish` with a record whose digest equals the newest record comment's makes no GitHub write. Check: suite.
- **CR-P4** `lint --pr` exits non-zero when the body's pointer names a lower revision than the newest record comment, or when the body differs from rendering the newest record with the body's current Decisions block; it exits 0 when they agree. Check: suite, three cases.
- **CR-P5** The newest record comment is found by marker, not by position: a verdict comment and an author reply posted after it do not change which comment `publish` and `lint --pr` read. Check: suite, interleaved comments in the shim.
- **CR-P6** `publish` refuses before any write when the rendered body or the record comment would exceed 65,536 characters, naming the size. Check: suite, one oversize record.
- **CR-P7** The only GitHub writes `publish` makes are one issue comment create and one PR body edit: the shim records no review, review comment, or comment edit call across every case in this slice. Check: suite, an assertion over the shim's call log in each case.
- **CR-P8** `merge` given a PR number renders the commit message from the newest record comment and runs `gh pr merge --squash --body-file` with it, so the merge commit's body is the rendered message whatever the repository's squash default; it refuses before merging when `lint --pr` fails or when no record comment exists, naming the reason. Check: suite, a `gh` shim recording the merge call's body file content, and one refusal case each.

### Slice W: the rewrite pass

What the owner vets: the editor's instruction text, one request and response pair for a fixture, and the applied diff.

- **CR-W1** `extract-prose` writes a request holding the record's digest, every field the schema marks `x-rewritable` with its current text and section digest, and the writing checks; no field outside that list appears as editable. Check: suite, the request's section list equals the schema's list for all four fixtures.
- **CR-W2** `apply-prose` refuses a response whose record digest differs from the record's, whose section digest differs from the section's current text, or that fails the response schema, naming the section, and leaves the record byte-identical. Check: suite, one case each.
- **CR-W3** `apply-prose` refuses a replacement for a field the schema does not mark rewritable, naming it, with no mutation. Check: suite.
- **CR-W4** `apply-prose` refuses a replacement whose text drops or changes a protected value present in the original section text, where protected values are tracker ids, criterion and decision ids, PR numbers, URLs, shas, numbers and backticked spans; the refusal names the value. Check: suite, one seeded case per kind.
- **CR-W5** Applying a response the author has pruned to the accepted replacements changes exactly those sections and bumps the revision, the result passes `lint`, and the record's revision entry names each applied section with its old and new digests. Check: suite, a response with three replacements of which one is pruned.
- **CR-W6** Running `apply-prose` a second time with the same response refuses on section digest and mutates nothing. Check: suite.
- **CR-W7** The editor's instruction file states the output contract and the three prohibitions (a strengthened claim, a dropped exception, erased deferred work), and one Codex run per fixture on `gpt-6-luna` at low effort returns a response that passes `apply-prose`'s structural checks for all four fixtures. Check: four recorded runs, one per fixture, at the stated model and effort, kept under the skill's `evals/` directory; the threshold is four of four structurally valid.
- **CR-W8** The owner judges the applied prose. For each of the four fixtures, the owner reads the applied diff and records accept or reject per section against the writing checks in section 3.4; the slice is delivered when the owner has recorded a judgment for every section, whatever its direction, and the corrections the owner made are counted in the evidence row. Check: `observed:` evidence row naming the owner, the date and the revision judged.

### Slice G: wiring

What the owner vets: three one-line diffs and one `gh api` read.

- **CR-G1** The `review-panel` skill's dispositions section states, in one sentence, that a reply on a finding takes the change-record reply form, and the skill's existing suites pass unchanged. Check: `content-tests` exit 0 at the landed head, and the sentence present.
- **CR-G2** The root `AGENTS.md` delivery contract names the change record as the PR body's source, `lint` as the check that runs before `gh pr create`, and the `merge` subcommand as how an instructed merge runs, and `doc-lint` exits 0. Check: `make doc-lint` exit status.
- **CR-G3** The repository's squash settings read `PR_TITLE` and `BLANK`, changed only after five consecutive squash merges on `main` carry a `Work-item` trailer. Check: `git log --first-parent main -5` showing the trailer on each, then `gh api repos/scotthamilton77/agents-config --jq '{squash_merge_commit_title,squash_merge_commit_message}'`, both recorded in one `observed:` row; this is the owner's action, not the agent's.

## 7. Order, and what each step costs the owner

| Order | Slice | Lands | Owner vets by |
| --- | --- | --- | --- |
| 1 | L | skill text, schema, templates, `init`, `lint`, four fixtures | reading the skill and schema; `lint` over the fixtures |
| 2 | R | `render`, golden files | diffing the rendered fixtures against the mock |
| 3 | X | `context`, `discovered` | one live run against this spec's own item |
| 3 | C | `campaign` | one run over pull request 843 against the mock's table |
| 4 | P | `publish`, `lint --pr`, `merge` | a dry run against a real PR |
| 5 | W | `extract-prose`, `apply-prose`, editor brief, four recorded runs | reading four applied diffs (CR-W8) |
| 6 | G | two sentences, then one setting | reading two diffs; running the setting change once five merges carry the trailer |

Slices X and C are independent and may run in parallel. Slice P needs L and R. Slice W needs L. Slice G is last because its sentences point at a skill that must already be deployed.

The first PR to use the pipeline end to end is slice P's own, which publishes its record with the tool it ships.

## 8. Owner decisions pending

- The `admit-request` verdict on the `change-record` skill. The admission record is on `agents-config-9k9.484`; the gate runs when slice L opens.
- The squash settings change (CR-G3) is a repository setting only the owner changes, and it waits for the five-merge observation.
- Whether the record comment and replies post from the author's account, as replies do today. The spec assumes yes.

## Continuations

- feat: The change-record skill, its schema, the record lint and the init stub — AC: CR-L1, CR-L2, CR-L3, CR-L4, CR-L5, CR-L6, CR-L7, CR-L8, CR-L9
- feat: The renderer produces the PR body, the commit message and the replies from a change record — AC: CR-R1, CR-R2, CR-R3, CR-R4, CR-R5, CR-R6, CR-R7
- feat: The context and discovered generators fill the record from the tracker and from GitHub — AC: CR-X1, CR-X2, CR-X3, CR-X4, CR-X5, CR-X6
- feat: The campaign generator fills the review campaign from the verdict envelopes — AC: CR-C1, CR-C2, CR-C3, CR-C4, CR-C5, CR-C6
- feat: Publish posts the record as a marked append-only comment, renders the body from it, and merge supplies the commit message — AC: CR-P1, CR-P2, CR-P3, CR-P4, CR-P5, CR-P6, CR-P7, CR-P8
- feat: The rewrite pass proposes per-section prose replacements that the author accepts or prunes — AC: CR-W1, CR-W2, CR-W3, CR-W4, CR-W5, CR-W6, CR-W7, CR-W8
- chore: The review-panel skill, the root AGENTS.md and the squash settings point at the change record — AC: CR-G1, CR-G2, CR-G3

Not filed: a pre-commit or pre-PR hook enforcing the record lint. File it only if, among the first ten PRs merged after slice G lands, any merged PR's body fails `lint --pr`; the count is read from those PRs' record comments.
