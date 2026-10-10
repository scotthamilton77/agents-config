# Change records: one linted record behind the PR body, the commit message and the review reply

**Date:** 2026-10-10
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D16 removal conditions, D20 admission records). Draft. The criteria are attacked after each amendment; the record covering the current text is `docs/specs/2026-10-10-change-record-ac-attack.json`.
**Work item:** `agents-config-9k9.484` (this spec's container), design child `agents-config-9k9.484.1`, implementation placeholder `agents-config-9k9.484.2`.
**Related:** the `readable-prose` skill (sentence quality, which this spec does not restate); the `review-panel` skill's dispositions section and the `review-verdict` envelope (the campaign data this spec reads); prgroom's reply writer and its Decisions block (a bot-owned region of the PR body this spec preserves).
**Design inputs:** `docs/reference/2026-10-10-change-record-proposal-r2.md` and its mock `docs/reference/2026-10-10-change-record-mock-r2.html` (the templates, rendered over pull requests 838, 839, 843 and 846); `docs/reference/2026-10-08-change-record-proposal-r1.md` (the diagnosis and the external survey); `docs/reference/2026-10-10-gpt-prose-rewriter-implementation-brief.md` (the rewrite pass, adopted in part); `docs/reference/2026-10-10-change-artifact-templates-r2.md` (a parallel proposal whose commit body and reply form this spec adopts).
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Agents write three artifacts for every change: the pull request description, the commit message and the replies on review findings. No template governs any of them. The `readable-prose` skill governs sentences, and one sentence in the root `AGENTS.md` governs replies. Everything else is improvised per PR.

The owner reads the result and has to ask. On the twelve most recent merged PRs, every description used a tracker id, criterion id or decision id on first mention with no words saying what it is. None said where the change sits in the milestone's tree. None had a risk or blast-radius section. None listed the work the author discovered and did not do. Across the twelve there were 46 distinct level-two headings, so no two read alike. Commit subjects ran to a median of 91 characters, and the repository's squash setting concatenates every branch commit into the merge commit, so a merged commit carries the same attribution trailers four or five times. Replies restate the campaign's status and bury what changed.

The cost lands on the one person this harness is meant to free. The prime directive asks whether a change reduces human interventions per merged PR. A description the owner can read once and approve is the direct answer.

## 2. Scope

In scope: the template for each of the three artifacts; a JSON change record that is the single source each artifact renders from; a schema and a lint over that record; generators that fill the record's factual sections from the tracker and from GitHub; publication of the record as an append-only PR comment with the body rendered from it; a merge command that supplies the rendered commit message; a bounded rewrite pass over the record's prose fields on a cheaper model; the repository squash settings; one sentence each in the `review-panel` skill and the root `AGENTS.md` pointing at the new skill.

Out of scope: a commit or PR hook that enforces the lint. The skill is adopted first, and the hook is added only if, among the first ten PRs merged after the wiring slice lands, a merged PR's body fails the record lint; the hook is minted from the Continuations manifest and deferred on minting, with that trigger in its description. Also out: Claude Code's attribution settings; a commitlint configuration; the verdict envelope's own format; PRs opened by Dependabot or release bots, which the templates leave untouched; the ordering of comments GitHub displays.

### 2.1 Terms

- **Work item, owning item, slice.** The work item is the tracker item a PR delivers; its full id is the tracker's, such as `agents-config-9k9.484`. Its short id is the full id with the project prefix removed up to and including the first hyphen, so `9k9.484`. The owning item is the work item's parent container. A slice is one child of an owning item, so the owning item's children are the slices and the record's work item is one of them.
- **Minting, the Continuations manifest, admission record.** Minting is creating a tracker item through the `work` facade. A spec's Continuations manifest is the bulleted list under its `## Continuations` heading, from which `work deliver` mints the spec's implementation items. An admission record is the statement every harness artifact carries of what it prevents or provides, what it costs and what observation would remove it.
- **Shared tree.** The directory under `src/user/.agents/` whose contents the installer deploys to every supported tool, as against a tool's own tree.
- **Review round, campaign, verdict envelope, terminal-clean.** A review round is one run of the review panel over a PR; the campaign is every round on that PR. Each round's result is a verdict envelope, a JSON document in the `review-verdict` skill's schema, posted by the reviewing GitHub App as a submitted pull request review pinned to the head it judged. A round is terminal-clean when the `review-verdict` skill's completeness rule accepts it and it carries no mechanical finding; that rule, not this spec, decides.

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
<table: item, status (filed / not filed / in flight), what it is, why not in this PR; for an in-flight row, "what it is" states what this PR told the other PR>

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
Generated with <the authoring tool> · <session url>
```

The body is for the human. It carries no JSON and no fold of machine content. Everything above the horizontal rule is the one-pager; everything below is evidence a reader opens on purpose.

Variants by commit type. A `feat`, `fix`, `refactor`, `perf` or `test` PR carries every section; the blast-radius diagrams are required only when the change reaches outside its own package. A `spec` PR's blast radius is the items the spec will mint, and its Criteria section is one line saying whether the criteria were attacked and where the record is. A `docs` or `chore` PR carries Heads-up, a one-row Risk table, Changes and Verification, and omits Criteria; `build`, `ci`, `style` and `revert` take the `chore` variant. Discovered work is required for every type; a PR that found nothing writes a single row reading "None."

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
Co-authored-by: <model> <the vendor's no-reply address>
<Tool>-Session: <url>
```

The subject is at most 100 characters. The type is one of commitlint's eleven plus this repository's `spec`. The component is the thing a reader would grep for, such as `review-panel` or `installer`, never a tracker id. The short tracker id (section 2.1) sits in brackets at the end so a one-line log still carries it.

The work item appears twice, once per reader. The first body line is a plain sentence for the human: the full id, a comma, and what the item is for. The `Work-item:` trailer in the last paragraph is for git, because `git interpret-trailers` reads only the last paragraph. The two are rendered from one record field, so they cannot disagree.

The body is 80 to 150 words, counting the Why, Change and Verification prose and not the work-item line or the labels. Why is two or three sentences, Change three or four. A trivial change may omit the body; the work-item line and the trailers stay. The trailers are `Work-item`, `Co-authored-by` and one session trailer whose key the authoring tool's harness defines, such as `Claude-Session` on Claude Code; the record carries the key and the value, so the skill works on every supported tool. Nothing else is a trailer.

### 3.3 The review reply

```text
Outcome: Fixed | Superseded | Rejected | Deferred.
Change: <What is different now, in one or two sentences.> (<commit>)
Verification: <The check and what it showed. For a prose fix, the lint or the
re-read. For a rejection, the evidence against the finding.>
```

A reply is 40 to 90 words. One reply goes on each finding that changed code or prose, as the delivery contract in the root `AGENTS.md` requires; a rejection is dispositioned in the author's inventory and reaches the PR through the next verdict envelope's dispositions, which the campaign table renders with their reasons, so it gets no reply unless a reviewer asks on the thread. A deferral names the item that inherits the finding. Superseded means the finding's target no longer exists because the design was restated, and the reply shows it is gone. Rejected, when a thread does call for it, gives evidence, never a bare disagreement. Campaign status is stated once, in the PR body's Verification section, and never in a reply.

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

A JSON change record, validated by a JSON Schema the skill ships, holds everything the three artifacts say. The PR body, the commit message and each reply are rendered from it by one script. An agent never writes a PR body by hand. The reasons: a record can be linted before anything reaches GitHub; a rewrite pass can edit prose fields without touching facts; the commit message and the body cannot disagree on a fact they share, because each fact is one field; and the campaign table and the ancestry are generated from their sources instead of typed.

The refuted alternative is a Markdown template the agent fills in. It is lintable only by regex over prose, it offers the rewrite pass no boundary between fact and wording, and nothing stops the agent from improvising a heading. That is the state the twelve PRs in section 1 are in.

### CR-D2. The record lives in an append-only PR comment, found by a marker

Each revision of the record is posted as its own PR-level comment. The comment opens with an HTML comment marker naming the schema version, the PR number, the revision and the record's digest, followed by the record in a collapsed fold. A later revision is a new comment, never an edit of an earlier one. The PR body carries one line naming the comment and revision it was rendered from.

Each GitHub comment has the same 65,536-character cap as the body. Keeping the record out of the body gives the human artifact the whole budget and gives the machine artifact its own. The sequence of record comments is the description's history, which the body itself does not carry; that matches the house rule that an artifact states the current decision and git is the changelog. Marker lookup is how prgroom already finds its own comments, and verdict envelopes are found by the collapsed JSON block in prgroom's submitted reviews, so a marked record comment adds no new mechanism.

The refuted alternative is a collapsed fold of JSON at the end of the body. It spends body budget, it puts machine content in front of the human reader, and a hand edit of the body can silently change the record.

### CR-D3. The PR body is never the squash commit body, and the squash setting flips last

At an authorized merge, the rendered commit message is supplied explicitly through `gh pr merge --squash --body-file`, by a `merge` subcommand that reads it from the newest record comment. An explicit body overrides the repository's squash default, so the pipeline produces clean merge commits under the current `COMMIT_MESSAGES` setting from the day slice P (publication and merge, section 6) lands. A PR body carries tables, folds, Mermaid and a bot-owned block, none of which belong in `git log`.

The repository's squash settings become `PR_TITLE` and `BLANK` only as the last act of slice G, after the delivery contract names the merge command and five merges have used it; slice W, which waits on an owner ruling, does not hold the flip. A repository setting is live for every session the moment it flips, and no branch or review covers it. Under `BLANK`, a plain `gh pr merge --squash` from a session that does not know the skill produces a merge commit with a title and no body: no work-item line, no attribution trailers. So the flip waits for evidence that merges have stopped omitting the message: the merge command is written into the delivery contract first, and the setting changes only after five consecutive squash merges on `main` carry a `Work-item` trailer. The current setting's repeated trailers are the lesser harm until then.

### CR-D4. A new shared skill, `change-record`, beside `readable-prose`

The skill lives in the shared tree so it follows agents to every tool. It is not folded into `readable-prose`, because that skill governs sentences and loads when a document is drafted, while this one governs shape, carries a schema and a script, and loads when a PR, commit or reply is written. Two concerns in one skill would make either harder to retire on its own removal condition. The one piece of code lives beside the templates it serves.

### CR-D5. Generated sections are generated

Where this fits, the scope table, the filed rows of Discovered work, and the whole Review campaign section are written by the script from the tracker and from GitHub, never typed by the agent. The agent writes one line in Where this fits, naming which slice this PR is, and the not-filed and in-flight rows of Discovered work, which only the agent knows. Ancestry follows parent fields through `work show`; it is never inferred from a dotted id. A generated section the agent could edit by hand would drift the moment it was convenient.

### CR-D6. The rewrite pass proposes per-section replacements and the author decides

The rewrite editor is a Codex dispatch, starting on `gpt-6-luna` at low effort. The charter's D5 seats foreign models in review, not authoring, and a proposed replacement is prose a foreign model wrote; whether the author's acceptance makes this a review-shaped seat is the owner's ruling, recorded on `agents-config-9k9.486` (the decision item), and slice W does not start until it is. It receives the whole record, the list of editable fields and the writing checks. It returns a list of replacements, each naming the record digest and the section digest it was written against, and may return a question for a section it cannot rewrite without inventing a fact. It never returns a rewritten record or a rewritten body.

Editable fields are those the schema marks `x-rewritable`: the summary, Heads-up rows, the Risk table's prose cells, Changes and design notes, the commit body's three prose sections, and reply text. Everything else is protected: ids, ancestry, URLs, commands, shas, counts, statuses, criterion obligations, dispositions, attribution and the Decisions block. The commit subject's wording is editable; its type, component and bracketed id are not.

The script refuses a stale, malformed or out-of-allowlist response without touching the record, and refuses a replacement that drops or changes a protected value found in the original text. Meaning is the author's check, not the script's: the script cannot tell "the gate reported exit 0" from "the change is verified", so the author reads each diff for a strengthened claim, a dropped exception or erased deferred work, and prunes the response to the replacements it accepts before applying. One pass, no retry loop. The record's revision history is the audit; rejected proposals are dropped.

The 36-run model experiment in the GPT brief is not adopted. The cheaper measurement is the author's correction count per PR, which each rewrite entry records. The rule: over the first ten real PRs, if the mean corrections per PR on PRs six to ten is not below the mean on PRs one to five, effort steps to medium for the next ten; the same comparison then decides the step to `gpt-6.1-sol`.

### CR-D7. Campaign data comes from the verdict envelopes

The campaign table and the findings list are computed from the verdict envelopes, read from the collapsed JSON block of each submitted pull request review the reviewing App posted, which already carry the round, the head sha, the reviewers that ran, every finding's id and claim, and every prior disposition. The fix commit for a finding comes from the author's reply when a reply names one, and is otherwise blank; the envelope does not carry it, and the author's reply is the only durable place it is written. The table counts distinct finding ids, not comments or commits. A disposition of `rebutted` renders as Rejected, `fixed` as Fixed, and `advisory-deferred` or `transferred` as Deferred; Superseded is chosen by the author in the record and never by the script. The terminal sha is set only from an envelope the `review-verdict` skill's own validator and completeness rule accept as terminal-clean; the script calls that validator and re-derives nothing.

### CR-D8. The pipeline never writes a review comment and never edits a comment it did not post

The verdict envelopes and the author's replies stay where they are. The script's only GitHub writes are creating a record comment and setting the PR body. The prgroom Decisions block inside the body is carried byte-for-byte on every render. The record comment and the replies post from the author's account, and verdicts post from the reviewing App.

### CR-D9. No hook until drift is observed

The skill, its lint and the one-sentence pointers in `review-panel` and the root `AGENTS.md` are the whole enforcement for the first ten merged PRs. A pre-commit or pre-PR hook is a second mechanism and is added only if, among the first ten PRs merged after the wiring slice lands, a merged PR's body fails the record lint. The hook is minted deferred from the Continuations manifest, and its description carries the observation and its threshold.

## 5. The record

The record is one JSON document. Its field groups, with their owner, are:

| Group | Holds | Written by | Rewritable |
| --- | --- | --- | --- |
| `pr` | number, title, type, component, head sha | agent at init, `publish` for the number | title wording only |
| `work_item` | full id, gloss, which slice this PR is | agent | gloss |
| `summary`, `heads_up` | the one-pager's opening and its caveats | agent | yes |
| `where_this_fits` | ancestry, builds-on, concurrent, scope table | `context` | no |
| `risk`, `blast_radius` | the risk rows, a flag saying whether the change reaches outside its package, two Mermaid sources | agent | prose cells only |
| `changes`, `design_notes` | topical changes and reasoning | agent | yes |
| `discovered` | filed, not-filed and in-flight rows | `discovered` for filed rows, agent for the rest | reason cells of not-filed and in-flight rows only; a filed row's reason is the tracker's |
| `verification` | gates with exit status and location, not-run list | agent | no |
| `campaign` | reviewer rows, terminal sha, findings | `campaign` | no |
| `criteria` | id, promise in plain words, evidence | agent | promise wording only |
| `commit` | subject, why, change, verification prose, or a trivial reason in place of the body | agent | prose, and the subject's wording |
| `replies` | per finding: outcome, change, verification | agent | prose |
| `record` | schema version, revision, digest, comment id, head sha at publish, rewrite entries | `publish`, `apply-prose` | no |

The schema marks each rewritable field with `x-rewritable: true`. The lint reads the schema for that list, so the allowlist and the schema cannot disagree. Each generated group carries the digest its generator stamped over its content, so a hand edit of a generated section fails the lint, and `publish` regenerates every generated group and refuses when the result differs from the record, so a stamp recomputed by hand does not pass either. A `heads_up` row a generator writes is prefixed with the generator's name, is not rewritable, and is removed or replaced by that generator's next run.

The record comment's first line is `<!-- change-record v<schema> pr=<n> rev=<k> sha256=<digest> -->`, where the digest is over the record's canonical JSON with the `record` group removed. The body's pointer line names the comment's URL and the revision.

## 6. Slices and acceptance criteria

Seven slices, each one pull request, each small enough that the owner can vet it by reading one script, one schema or one set of golden files and running one command. Suite criteria run under `content-tests`, which discovers the skill's test file beside its script. Where a criterion needs the tracker or GitHub, the suite puts a shim named `work` or `gh` on `PATH` that replays recorded output; no suite reaches the network. Each criterion states the obligation, then its check.

### Slice L: the skill, the schema, `init` and `lint`

What the owner vets: the skill text, the schema, the four example records, and `lint` run over them. The `admit-request` gate runs on the skill before this slice opens, and its verdict is recorded on the slice's work item; the admission record is on `agents-config-9k9.484`.

- **CR-L1** A record missing any required field group, carrying a field the schema does not define, or holding a value of the wrong type in a nested field fails `lint` with the field named; each of the four example records passes. The examples are built from pull requests 838 (expert weighing of a human's answers in the grilling UI), 839 (the routing-table inventory lint), 843 (review-seat effort and tool pins) and 846 (the verification-contract rule), all `feat` PRs. Check: suite, one case per required group removed, one unknown top-level field, one unknown nested field, one gate exit status given as an object instead of a number, one reply text given as an object, and the four fixtures.
- **CR-L2** An author-written text field, rewritable or not and in any group the generators do not own, whose text names a tracker id, criterion id, decision id or PR number with no gloss on that id's first use fails `lint`, naming the field and the id; the same id glossed on first use and bare on a later use passes. The body is one gloss scope and each reply is its own, since a reply is read alone. Check: suite, one case per id shape (a dotted tracker id, a hyphenated criterion id, a bare `D16`, a `#843`), each as a failing bare first use and a passing glossed first use, one case where the first use is in `summary` and the later bare use is in `changes`, one case where the bare first use is in a `verification` not-run entry, and one case where an id glossed in `summary` appears bare in a reply and fails.
- **CR-L3** A commit subject fails `lint` when it exceeds 100 characters, when its type is outside commitlint's eleven plus `spec`, when its type or component differs from the record's `pr.type` or `pr.component`, when it has no component, when its component matches the tracker id pattern, or when the bracketed id at its end is missing or is not the short id derived from the record's work item as section 2.1 defines; a 100-character subject of the right form passes. Check: suite, one case each, with the failure naming the rule broken.
- **CR-L4** A record states emptiness explicitly: an empty `heads_up`, an empty `discovered` or a `risk` table with no row fails `lint`, and a single `None.` entry passes for `heads_up` and `discovered`. Check: suite, one case each way.
- **CR-L5** A `discovered` row fails `lint` when its status is filed and it names no item id, when its status is in flight and it names no PR, or when any row other than the single `None.` entry has an empty reason. Check: suite, one case each, plus the `None.` entry passing.
- **CR-L6** A record fails `lint` when its summary has fewer than three or more than five sentences. Check: suite, the boundary values on each side of both limits.
- **CR-L7** An author-written prose field containing a phrase of document commentary from the skill's list, such as "this section" or "note that", or containing machine content, which is a `<details>` fold, an HTML comment or a fenced `json` block, fails `lint` naming the phrase or the construct; the same phrase inside a code span passes. Check: suite, one case per listed phrase, one per construct, and one code-span case.
- **CR-L8** `init` given a type, a component and a work item id writes a record that passes schema validation and fails `lint` on exactly the fields the author must fill, each named; running `init` where a record already exists refuses and leaves the file unchanged. Check: suite, one run and one rerun.
- **CR-L9** The skill deploys to the shared tree and its suite is discovered: `content-lint` run standalone at the landed head exits 0, the staged shared tree for each supported tool contains the skill directory with its schema, its templates and its script, and `content-tests` run standalone at the landed head names the skill's suite among those it ran. Check: `make content-lint` and `make content-tests` exit statuses, the staging listing and the suite name in the evidence row.
- **CR-L10** Required groups follow the record's type and reach: a record of type `feat`, `fix`, `refactor`, `perf` or `test` fails `lint` without a `criteria` group, a record of type `docs`, `chore`, `build`, `ci`, `style` or `revert` fails with one or with more than one `risk` row, a record of type `spec` fails unless `criteria` is the single line naming whether its criteria were attacked and where the record is, and a record whose `risk.reaches_outside_package` flag is true fails without both `blast_radius` sources while one whose flag is false passes without them. `lint --pr` fails a record whose flag is false when the PR's changed paths span more than one top-level component. Check: suite, one case per type, one per flag value, and one `--pr` case with a `gh` shim listing files in two components.
- **CR-L11** A `heads_up` or `discovered` list holding `None.` beside any other entry fails `lint`, naming the list. Check: suite, one case per list.
- **CR-L12** A commit body is present with `why` of two or three sentences, `change` of three or four, `verification` non-empty, and the three totalling 80 to 150 words, or it is absent and `commit.trivial` holds a reason; a body missing one of the three, a section outside its sentence range, a body outside the word range, or an absent body with no trivial reason fails `lint`. Check: suite, one case each, with the word and sentence boundaries on each side.
- **CR-L13** A reply fails `lint` when it is outside 40 to 90 words, when its Change line has more than two sentences, when its outcome is Deferred and its text does not name the work item the campaign's disposition for that finding carries, when its outcome is Rejected and the entry names no reviewer comment URL that asked for it, or when its text carries campaign status, which is any phrase from the skill's list such as "terminal-clean" or "round" followed by a number. Check: suite, the word boundaries on each side, a three-sentence Change line, one Deferred case each way, one Rejected case each way, and one case per listed phrase.
- **CR-L14** A record whose `campaign` holds a finding with disposition fixed and whose `replies` holds no entry or more than one entry for that finding's id fails `lint`, naming the finding; a rebutted, deferred or transferred finding needs no reply. Check: suite, one case per disposition and one duplicate-entry case.
- **CR-L15** Each generated group (`where_this_fits`, the filed rows of `discovered`, `campaign`) carries the digest its generator stamped over the group's content, and a record whose group content no longer matches its stamp fails `lint`, naming the group; a group with no stamp fails the same way. Check: suite, one hand-edited case per group and one unstamped case.
- **CR-L16** The suite runs under a `PATH` holding only the shim directory and the interpreter, and under an environment whose `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` point at a closed local port with `NO_PROXY` empty, so any `gh` or `work` call that misses a shim and any direct HTTP request fails the test that made it; the suite passes under that environment. Check: the suite's own runner sets that `PATH` and those variables, and two sentinel tests, one unshimmed call and one direct HTTP request, fail.
- **CR-L17** The renderer reads the three shipped template files at run time, so the reference an agent reads and the form the renderer produces cannot differ: changing a heading in the PR body template file changes the rendered body the same way. Check: suite, edit a copied template file's heading and assert the render follows.

### Slice R: `render`

What the owner vets: the rendered body, commit message and replies for the four fixtures, diffed against the golden files.

- **CR-R1** Rendering each of the four `feat` fixtures produces a body byte-identical to its golden file whose level-two headings in order are Heads-up, Where this fits, Risk, Changes, Discovered work, Verification and Criteria, and whose text above the first horizontal rule is at most 400 words; a minimal fixture of each of `fix`, `refactor`, `perf` and `test` renders the same heading set; a `docs` fixture and a `chore` fixture render the headings Heads-up, Risk, Changes, Discovered work and Verification with no Criteria heading and no blast-radius fold; a `spec` fixture, this spec's own record, renders Criteria as the one attack-status line and a blast radius naming the items the spec mints, matching its golden file. Check: suite, golden diff and a heading walk over eleven fixtures.
- **CR-R2** Rendering with an existing body that holds a prgroom Decisions block between its sentinels reproduces that block byte-for-byte at the template's position, including a block that itself contains a `<details>` fold and a marker comment; rendering with no such block emits no Decisions heading. Check: suite, two cases.
- **CR-R3** The rendered commit message's first body line is `Work item <full id>, <gloss>.` with the record's values, its body carries the labels Why, Change and Verification in that order, and `git interpret-trailers --parse` run over it returns exactly `Work-item`, `Co-authored-by` and the session trailer key the record names, with the `Work-item` value equal to the record's full id; a trivial record renders the first body line and the same trailers with no labelled sections. Check: suite, asserts the first body line and the label order, then runs `git interpret-trailers` on each fixture's output, one fixture carrying `Claude-Session`, one carrying another tool's key, and one trivial fixture.
- **CR-R4** The rendered commit message contains no Markdown table, no `<details>`, no fenced block and no HTML comment, and `render` refuses a record whose commit prose fields carry any of those, naming the field. Check: suite, pattern absence on all four fixtures and one refusal case per markup kind.
- **CR-R5** A reply rendered from a finding entry is three lines beginning `Outcome:`, `Change:` and `Verification:`, the outcome word is one of Fixed, Superseded, Rejected and Deferred, and a finding with no commit renders `Change:` with no trailing parenthesis. Check: suite, one case per outcome and one with no commit.
- **CR-R6** `render` on a record that fails `lint` writes nothing and exits non-zero with the lint output. Check: suite.
- **CR-R7** Two renders of one record are byte-identical, and a render after a no-op rewrite of the record file (reserialized, same content) is byte-identical to the first. Check: suite.
- **CR-R8** `render` given an existing body that holds exactly one of the two Decisions sentinels, or holds them out of order, refuses, naming the sentinel, and writes nothing; it never takes the no-block path on such a body. Check: suite, three cases: opening sentinel missing, closing sentinel missing, closing before opening.

### Slice X: `context` and `discovered`

What the owner vets: the two generators run against a live work item, compared to `work show` by eye.

- **CR-X1** `context` given a work item id writes the ancestry from the milestone down to the item, each entry with id, title and type, by following parent fields; when a dotted id disagrees with the parent field, the output follows the field. Check: suite, a `work` shim whose chain has one item whose dotted prefix is not its parent.
- **CR-X2** `context` writes the scope table from the owning item's children: each child's title and a status of done (closed), this PR (the record's work item), in flight (an open PR names it) or open. Check: suite, a `work` shim with one child in each state and a `gh` shim listing one open PR.
- **CR-X3** `context` writes builds-on as the PRs recorded on the owning item's closed children that GitHub reports as merged, each with the PR's title as its gloss; a PR closed without merging is left out. Check: suite, shims with two closed children carrying merged PR numbers and one carrying a PR closed unmerged.
- **CR-X4** `context` on an id the tracker does not know exits non-zero naming the id and leaves the record unchanged. Check: suite.
- **CR-X5** `discovered` writes one filed row per item whose discovered-from edge points at this PR's work item, with the item's id, title, and its triage record's scope reason as the reason, and leaves every not-filed and in-flight row the author wrote in place. Check: suite, a shim with two discovered items and a record already holding one not-filed row and one in-flight row; the output holds four rows in the order filed, not filed, in flight.
- **CR-X6** A second run of `context` or of `discovered` with unchanged inputs leaves the record byte-identical, and the author's one line naming the slice survives both runs. Check: suite.
- **CR-X7** When the owning item has no child other than the record's work item, no closed child carries a PR, and no open PR shares a path, `context` writes the scope table as a single row naming this PR, builds-on as `none` and concurrent as `none`, and the record passes `lint`. Check: suite, shims returning an owning item with that one child and an empty PR list.
- **CR-X8** `context` writes concurrent as the open PRs, other than this one, that touch a path this PR touches, each with the PR's title as its gloss; an open PR sharing no path is left out. Check: suite, shims with two open PRs of which one shares a path.

### Slice C: `campaign`

What the owner vets: `campaign` run over the captured comments of pull request 843, compared to the table in the mock.

- **CR-C1** `campaign` given a PR number reads every submitted pull request review by the reviewing App whose body carries a verdict envelope, across every page of reviews until the API returns an empty page, and writes one row per reviewer that appears in any envelope, with the rounds it ran as a range, and its counts of distinct finding ids, fixed, rejected and deferred, where rebutted counts as rejected and advisory-deferred and transferred count as deferred. Check: suite, the captured reviews of pull request 843 as the fixture split across three pages by the `gh` shim, against the expected rows; a fixture with an envelope-shaped issue comment confirms issue comments are not read.
- **CR-C2** The findings list has one entry per distinct finding id with the round it first appeared, its id, its claim, its latest disposition, that disposition's evidence text as the reason, and the commit from the author's reply on that finding when the reply names one, else empty. Check: suite, the same fixture, including one rebutted finding whose reason is asserted, one finding whose reply names a commit and one whose reply does not.
- **CR-C3** A PR with no envelope-bearing review yields an empty campaign and a `heads_up` row saying no review round has run; a PR whose every envelope was skipped yields an empty campaign and a row saying how many reviews carried envelopes the tool could not read; in both cases the row replaces a sole `None.` entry rather than joining it. Check: suite, a `gh` shim returning reviews with no envelope and one returning only rejected envelopes, each run over a record whose `heads_up` is `None.` and over one holding a real entry.
- **CR-C4** A review whose envelope the `review-verdict` skill's validator rejects, or whose author is not the reviewing App, is skipped and named on stderr, and the remaining envelopes are counted; the validator is the skill's own, called, not re-implemented. Check: suite, the fixture with one envelope's `verdict` field removed and one envelope posted under another login, and one case that substitutes the validator with a stub rejecting everything and asserts the campaign comes out empty.
- **CR-C5** The terminal sha is the head sha of the latest envelope that the `review-verdict` skill's completeness rule accepts and that carries no mechanical finding, an advisory-only findings round included; otherwise the field is empty and a `heads_up` row says the latest round is not terminal-clean, replacing a sole `None.` entry. Check: suite, one case each for a clean round, an advisory-only round, a round with a mechanical finding, and a halted round, the last two over a record whose `heads_up` is `None.`.
- **CR-C6** A second run of `campaign` over unchanged reviews leaves the record byte-identical, and no run of `campaign` changes a `replies` entry, so an author's Superseded outcome survives. Check: suite, a rerun, and a run over a record holding a Superseded reply for a finding the envelope marks fixed.
- **CR-C7** A `heads_up` row a generator wrote is removed by that generator's next run when its condition no longer holds: after a round becomes terminal-clean, `campaign` removes its not-terminal-clean row and sets the terminal sha, and a `None.` entry is restored when no other entry remains. Check: suite, two runs over reviews whose latest envelope changes from a mechanical finding to clean.
- **CR-C8** `campaign`, `context` and `discovered` make no GitHub write: across every case in slices X and C the `gh` shim's call log holds reads only. Check: suite, an assertion over the shim's call log in each case.

### Slice P: `publish` and `lint --pr`

What the owner vets: `publish` run in dry-run against a real PR, printing the comment and body it would write.

- **CR-P1** `publish` on a PR with no record comment regenerates every generated group and refuses, naming the group, when the result differs from the record; otherwise it creates one comment whose first line is the marker with revision 1 and the record's digest and whose body holds the record in a fold, then sets the PR body to the render with a pointer line naming that comment and revision; the record file's `record` group gains the comment id and revision. Check: suite, a `gh` shim recording calls, one case with a hand-edited generated group under a recomputed stamp that is refused.
- **CR-P2** `publish` on a PR with an existing record comment creates a new comment at the next revision and makes no edit or delete call on any comment. Check: suite, shim with one prior record comment; the recorded calls hold one create and one body edit.
- **CR-P3** `publish` with a record whose digest equals the newest record comment's posts no comment, and sets the body only when the body differs from the render with that comment's pointer, so a publish interrupted between its two writes is repaired by a rerun. Check: suite, one no-op case and one case where the comment exists and the body still names the previous revision.
- **CR-P4** `lint --pr` exits non-zero when the body's pointer names a lower revision than the newest record comment, or when the body differs from rendering the newest record with the body's current Decisions block; it exits 0 when they agree. Check: suite, three cases.
- **CR-P5** The newest record comment is found by marker and highest revision compared as integers, not by position: a verdict comment and an author reply posted after it do not change which comment `publish` and `lint --pr` read, and with record comments at revisions 9 and 10 the newest is 10. Check: suite, interleaved comments in the shim and a two-digit revision case.
- **CR-P6** `publish` refuses before any write when the rendered body or the record comment is longer than 65,536 characters, naming the size, including a body that crosses the limit only because of the Decisions block it carries; a body of exactly 65,536 characters is accepted. Check: suite, one oversize record, one small record with an oversize Decisions block, and one body at exactly the limit.
- **CR-P7** The only GitHub writes `publish` makes are one issue comment create and one PR body edit: the shim records no review, review comment, or comment edit call across every case in this slice. Check: suite, an assertion over the shim's call log in each case.
- **CR-P8** `merge` given a PR number renders the commit message from the newest record comment and runs `gh pr merge --squash` on that same PR number with `--subject` set to the rendered subject and `--body-file` set to the rendered body, so the merge commit's subject and body are the rendered message whatever the PR title and the repository's squash default; it refuses before merging when `lint --pr` fails or when no record comment exists, naming the reason. Check: suite, a `gh` shim recording the merge call's PR number, subject and body file content, and one refusal case each.
- **CR-P9** `publish` writes the PR's live head sha into the record, and `merge` refuses, naming the reason, when the campaign is empty, when its terminal sha is empty because no round is terminal-clean, or when the PR's live head differs from the record's head sha or from the terminal sha. Check: suite, a `gh` shim whose PR head advances after the record was published and after the last clean envelope, one empty-campaign case and one halted-round case; one case each.
- **CR-P10** When two record comments carry the same revision, the newest is the one with the higher comment id, and `lint --pr` fails a body whose pointer names the other, so a publish that lost the race is visible on its own PR. Check: suite, a shim holding two comments at one revision with different digests, and a body pointing at each.
- **CR-P11** The record digest is the sha256 of the record's canonical JSON, sorted keys, with the `record` group removed: reordering keys or changing the `record` group leaves it unchanged, and changing any other byte changes it. Check: suite, one case each.
- **CR-P12** `publish --dry-run` prints to stdout the record comment, marker line first, and the body it would write, and makes no GitHub write. Check: suite, stdout holds the marker line and the rendered body's first heading, and the shim's call log is empty after a dry run.
- **CR-P13** The pull request that delivers this slice has its body rendered and published by the `publish` it ships, with the pointer line naming a record comment on that PR. Check: `observed:` evidence row naming the PR and the comment.
- **CR-P14** `publish --create` on a record with no PR number opens the pull request with `gh pr create`, its title the record's title and its body the render without a pointer line, then posts the record comment and sets the body with the pointer as CR-P1 describes, and writes the PR number into the record; the skill names this as the way a PR is opened. Check: suite, a `gh` shim recording the create call's title and body, then the comment and body edit.

### Slice W: the rewrite pass

What the owner vets: the editor's instruction text, one request and response pair for a fixture, and the applied diff.

- **CR-W1** `extract-prose` writes a request holding the complete record as read-only context, the record's digest, the writing checks' text, and for every field the schema marks `x-rewritable` its current text and the sha256 of that text; no field outside that list appears as editable, and that list is exactly: `pr.title`, `work_item.gloss`, `summary`, author-written `heads_up` entries, `risk` prose cells, `changes`, `design_notes`, the reason cells of not-filed and in-flight `discovered` rows, `criteria` promise cells, `commit.subject` wording, `commit.why`, `commit.change`, `commit.verification`, and `replies` text. Check: suite, over all four fixtures, the request's sections equal that list, a filed row's reason and a generator-written `heads_up` row are absent from it, the full record is present, each section's text equals the record's, each digest recomputes, and the writing checks are present.
- **CR-W2** `apply-prose` refuses a response whose record digest differs from the record's, whose section digest differs from the section's current text, or that fails the response schema, naming the section, and leaves the record byte-identical, including when a valid replacement precedes the stale one in the same response; the response schema admits a `questions` list, and a response holding questions and no replacements is valid, applies nothing and prints the questions. Check: suite, one case each, one mixed-order case, and one questions-only case.
- **CR-W3** `apply-prose` refuses a replacement for a field the schema does not mark rewritable, naming it, with no mutation. Check: suite.
- **CR-W4** `apply-prose` refuses a replacement whose text drops or changes a protected value present in the original section text, where protected values are tracker ids, criterion and decision ids, PR numbers, URLs, shas, numbers, backticked spans, disposition and outcome words, status words from the schema's enumerations, attribution strings, and in the commit subject its type, its component and its bracketed id; the refusal names the value. Check: suite, one seeded case per kind, including a subject whose component is changed.
- **CR-W5** Applying a response the author has pruned to the accepted replacements changes exactly those sections and bumps the revision, the result passes `lint`, and the record's revision entry names each applied section with its old and new digests. Check: suite, a response with three replacements of which one is pruned.
- **CR-W6** Running `apply-prose` a second time with the same response refuses on section digest and mutates nothing. Check: suite.
- **CR-W7** The editor's instruction file states the output contract and the three prohibitions (a strengthened claim, a dropped exception, erased deferred work), and one Codex run per fixture on `gpt-6-luna` at low effort returns a response that passes `apply-prose`'s structural checks for all four fixtures. Check: four recorded runs, one per fixture, at the stated model and effort, kept under the skill's `evals/` directory; the threshold is four of four structurally valid. The runs wait on the ruling recorded on `agents-config-9k9.486`.
- **CR-W8** The owner judges the applied prose. For each of the four fixtures, the owner reads the applied diff and records, per section, accept or reject, the writing check from section 3.4 by number that the judgment rests on, and one sentence of basis; a rejected section is corrected and judged again; the slice is delivered when every section's latest judgment is accept, and the corrections made are counted in the evidence row. Check: `observed:` evidence row naming the owner, the date, the revision judged and the correction count.
- **CR-W9** Each rewrite entry records the revision it produced, and `apply-prose` refuses a response against a record whose current revision is one a rewrite entry produced, so one editing pass is admitted per author revision and an author edit, which bumps the revision, re-enables the pass. Check: suite, apply once, then apply a fresh valid response against the produced revision and assert refusal; bump the revision by an author edit and assert a third response applies.
- **CR-W10** Each rewrite entry carries the counts of replacements proposed, pruned by the author, corrected by the author (an applied text that differs from the proposed text) and applied, so the correction series over real PRs can be read from the record comments without any other log. Check: suite, a response with three replacements of which one is pruned and one is edited before applying yields proposed 3, pruned 1, corrected 1, applied 2.
- **CR-W11** The rewrite dispatch reads its model and effort from one pin file the skill ships, and the four recorded runs under `evals/` name the same pin, so the production dispatch and the evaluated one cannot differ silently. Check: suite, the dispatch command the skill emits names the pin file's model and effort, and a test compares the evals' recorded settings to the pin file.

### Slice G: wiring

What the owner vets: three one-line diffs and one `gh api` read.

- **CR-G1** The `review-panel` skill's dispositions section states, in one sentence, that a reply on a finding takes the change-record reply form, the sentence lands only after the `change-record` skill is deployed to the tool's own skills directory, and the skill's existing suites pass unchanged. Check: `content-tests` exit 0 at the landed head, the sentence present, and an `observed:` row listing the deployed skill directory before the slice's PR opened.
- **CR-G2** The root `AGENTS.md` delivery contract directs the author in three sentences: the PR body is rendered from a change record and never written by hand; `lint` runs and passes before `gh pr create`, or `publish --create` opens the PR; an instructed merge runs through the `merge` subcommand. `doc-lint` exits 0. Check: a test reads the delivery contract section and asserts each of the three sentences by its quoted text, and `make doc-lint` exit status.
- **CR-G3** The repository's squash settings read `PR_TITLE` and `BLANK`, changed only after five consecutive first-parent commits on `main`, each the squash merge of a merged pull request made after the commit that landed CR-G2's sentences, whose message is byte-identical to that PR's rendered commit message, so each carries a `Work-item` trailer once and no concatenated branch text. Check: one `observed:` row recording the five shas, their PR numbers from `gh pr list --state merged --search <sha>`, their dates, the byte comparison of each message against its record comment's render, and the date of the settings change after them, then `gh api repos/scotthamilton77/agents-config --jq '{squash_merge_commit_title,squash_merge_commit_message}'`; this is the owner's action, not the agent's.

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

Slices X and C are independent and may run in parallel. Slice P needs L and R. Slice W needs L and the ruling on `agents-config-9k9.486`; its item takes a dependency edge on that decision when it is minted. Slice G follows P, and its sentences land only after the owner's installer run has deployed the skill, confirmed by listing the tool's own skills directory.

The first PR to use the pipeline end to end is slice P's own, which publishes its record with the tool it ships.

## Continuations

- feat: The change-record skill, its schema, the record lint and the init stub — AC: CR-L1, CR-L2, CR-L3, CR-L4, CR-L5, CR-L6, CR-L7, CR-L8, CR-L9, CR-L10, CR-L11, CR-L12, CR-L13, CR-L14, CR-L15, CR-L16, CR-L17
- feat: The renderer produces the PR body, the commit message and the replies from a change record — AC: CR-R1, CR-R2, CR-R3, CR-R4, CR-R5, CR-R6, CR-R7, CR-R8
- feat: The context and discovered generators fill the record from the tracker and from GitHub — AC: CR-X1, CR-X2, CR-X3, CR-X4, CR-X5, CR-X6, CR-X7, CR-X8
- feat: The campaign generator fills the review campaign from the verdict envelopes — AC: CR-C1, CR-C2, CR-C3, CR-C4, CR-C5, CR-C6, CR-C7, CR-C8
- feat: Publish posts the record as a marked append-only comment, renders the body from it, and merge supplies the commit message — AC: CR-P1, CR-P2, CR-P3, CR-P4, CR-P5, CR-P6, CR-P7, CR-P8, CR-P9, CR-P10, CR-P11, CR-P12, CR-P13, CR-P14
- feat: The rewrite pass proposes per-section prose replacements that the author accepts or prunes — AC: CR-W1, CR-W2, CR-W3, CR-W4, CR-W5, CR-W6, CR-W7, CR-W8, CR-W9, CR-W10, CR-W11
- chore: The review-panel skill, the root AGENTS.md and the squash settings point at the change record — AC: CR-G1, CR-G2, CR-G3
- feat: A commit or PR hook enforces the record lint, deferred on minting — AC: Deferred with `work defer` as soon as it is minted. Opened only when, among the first ten PRs merged after the wiring slice lands, a merged PR's body fails `lint --pr`, read from those PRs' record comments. Criteria are written and attacked then, before any work starts.
