# Proposal: one shape for commits, PR descriptions and review replies

Date: 2026-10-08. Status: proposal, nothing deployed. Source session: git-doc-templates.

## Diagnosis

Nothing in this repository or in the deployed surface prescribes the shape of a commit message, a pull request description or a review reply. The `readable-prose` skill governs sentence quality, and one sentence in AGENTS.md says which review findings earn a reply. Everything else is emergent.

What the last 200 commits and 12 merged PRs look like:

| Artifact | What is consistent | What drifts |
| --- | --- | --- |
| Commit subject | `type(tracker-id): outcome sentence`. Types: feat 60, fix 57, chore 36, docs 25, spec 17, test 3, refactor 1. | Length: median 91 chars, p90 112, max 147. commitlint's conventional preset caps at 100. |
| Commit body | Prose explaining why, 4 to 20 lines. | Squash merges concatenate every branch commit, so trailers repeat up to four times (#806). Cause: the repo setting `squash_merge_commit_message = COMMIT_MESSAGES`. |
| Trailers | `Co-authored-by`, `Claude-Session` on nearly every commit. | Casing split (`Co-Authored-By` 597, `Co-authored-by` 191). Invented evidence trailers: `Gates:`, `Verified:`, `Validation:`, `Criteria:`, `Quality:`, `Prose:`, `Lifecycle:`. |
| PR body | Good content: what, why, criteria, gates, exclusions. | 35 distinct H2 names for about six ideas. 270 to 1310 words, no summary a human can stop after. |
| Review reply | `**fixed** (round N). Reproduced: … Test … Commit …`, driven by the panel's typed disposition vocabulary. | None worth fixing. |

The owner's reading problems, added 2026-10-08, and what causes each:

| Problem | Cause in the current output |
| --- | --- |
| Cryptic, grammatically strained prose with a high cognitive load | Titles are written as "outcome sentences" that compress a whole decision into one clause. Example: "the verification-contract rule judges a criterion's check, and coverage alone asks whether a commitment has one". The nuance belongs in a paragraph, not a title. |
| References the reader cannot resolve: work item ids, section ids, decision ids, criterion ids with no gloss | AGENTS.md already asks for a gloss on every id. Nothing structural enforces it, so bare `A17`, `DEL-G5`, `9k9.408` and `§7.3` appear in every PR. |
| No sense of where the PR sits in the larger work | No section asks for it. The tracker knows the parent chain for every item, and nobody reads it into the PR. |
| Verbosity and loose format defeat skimming | No bound on what comes first. Evidence tables, scenario transcripts and gate output sit at the same level as the summary. |
| Risk and blast radius are not stated | No section asks for it. Admission records carry a `cost` field, but it measures tokens and effort, not what breaks if the change is wrong. |
| Discovered and updated work is not listed | `work discover` records provenance (`--discovered-from`), and the PR never surfaces it. The "Not in this change" sections that exist name exclusions without items or rationale. |

The PR body also has one machine consumer already: prgroom splices a sentinel-bounded `## Decisions` block into it. No recent PR carries one, but the slot exists and a template must not collide with it.

## What external practice agrees on

Sources: Conventional Commits 1.0, `git interpret-trailers`, Google CL descriptions, Kubernetes and Go contribution guides, the Linux kernel's coding-assistants policy, curl, ghostty's AI policy, Copilot's `Agent-Logs-Url` trailer, release-please, Dependabot, git-cliff.

- The first line stands alone. Type or area prefix, then a summary a stranger understands.
- The body says why and what problem it solves. It survives link rot, so essentials go inline. Google says it outright: links rot, put the point in the text.
- Machine data lives in trailers (`Key: value`, last paragraph) or a fenced block. Never in prose.
- Closing and relating are different verbs: `Fixes`/`Closes` versus `Refs`/`Updates`.
- AI attribution is a trailer naming the tool and a link to the session. The human keeps the sign-off.
- Verification is stated, with numbers. The kernel goes furthest: say what was not built, not run, not tested.
- Every review comment gets a disposition. Fixing the code beats explaining it in a thread.
- Type-specific templates exist (Kubernetes `/kind`, Google's three examples), selected by a label or a query parameter, not a picker.

## The proposal

Five moves, cheapest first. The first two are settings and cost no code.

### 1. Make the PR body the squash commit body

Change two repository settings: `squash_merge_commit_title = PR_TITLE` and `squash_merge_commit_message = PR_BODY`. One artifact then carries the record. The PR title is the commit subject by construction, trailers appear once, and branch commits become working notes. This removes the #806 shape entirely.

Consequence to accept: the merged commit body is Markdown with H2 headers and a `<details>` fold. `git interpret-trailers --parse` still finds the trailer block, and `git log` readers in this repo already read Markdown.

### 2. Fix the trailer vocabulary

Trailers carry identity and linkage, never evidence. The allowed set:

```
Co-authored-by: <model name> <noreply@anthropic.com>
Claude-Session: <url>
Fixes: <tracker id or #issue>        closes the item
Refs: <tracker id or #issue>         relates without closing
```

`Co-authored-by` in GitHub's own casing. `Gates:`, `Verified:`, `Criteria:` and the rest move into the body's Verification section. A trailer block with an invented key is what `git interpret-trailers` and git-cliff both misparse.

### 3. The title is a plain sentence a stranger understands

`type(tracker-id): <what is true after this merges>`, at most 100 characters, in words that need no tracker to decode. One clause. The second clause, the reason, and the measured result go in the lead paragraph.

Before: `feat(9k9.405.14): the verification-contract rule judges a criterion's check, and coverage alone asks whether a commitment has one`
After: `feat(9k9.405.14): the attack panel stops filing coverage gaps under the wrong rule`

The outcome-sentence habit came from wanting the title to state the claim the PR is judged against. The Criteria table below does that job better, because it has room.

### 4. One PR body shape: a one-pager, then a fold

Everything above the fold is what a human reads to decide whether to open the diff. It is capped at roughly 300 words and contains no table wider than two columns. Everything below the fold is evidence a reviewer or a script reads. Fixed H2 names, fixed order. Fixed names are readable-prose rule 7 applied to pull requests: a reader finds the same thing in the same place, and a script finds a section by its heading.

```markdown
<Lead paragraph, no heading. First sentence restates the title in full words.
Then: the problem, why this approach, and the measured result if there is one.
Three to six sentences. Every id is glossed on first use:
`agents-config-9k9.405.14 (the verification-contract rule fix)`.>

## Where this fits
agents-config-9k9 (harness rework milestone)
└ agents-config-9k9.405 (acceptance-criteria standard and its attack panel)
  └ agents-config-9k9.405.14 (this change)
<One or two sentences: what landed before this in the chain, and what this
unblocks next. Written for a reader who has never opened the tracker.>

## Risk
- **Blast radius:** <what this touches: this repo only / the deployed surface
  in every project / the installer / a package on PATH>.
- **If this is wrong:** <the concrete bad outcome a user or agent would see>.
- **Mitigation:** <the test, gate, measurement or review that bounds it>.
- **Rollback:** <revert the commit / also requires X>.

## Changes
- <behaviour or file group>: <what is different now, in words>
- <...>

## Discovered work
| Item | New or updated | What it is | Why not in this PR |
| --- | --- | --- | --- |
| agents-config-9k9.470 | new | <one-line gloss> | <scope reason: separate concern / blocked on X / out of this item's criteria> |
<"None." when nothing was filed. An exclusion with no item filed goes here too,
with "not filed" in the Item column and the reason in the last column.>

<details>
<summary>Evidence</summary>

## Criteria
| Criterion | What it promises | Evidence |
| --- | --- | --- |
| A1 | <one-line restatement in plain words> | <test name, measurement, or scenario> |

## Verification
- `make ci`: exit 0, run standalone from the worktree root at <head sha>.
- <other gate>: exit <n>, <where>.
- Not run: <what, and why>. ("None" is a valid answer.)

<scenario transcripts, measurements, review-round summary>

</details>

## Decisions
<reserved; prgroom writes here between its sentinels. Omit when empty.>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
<session url>
```

Variants by the commit type the title already carries:

| Type | Risk | Discovered work | Criteria | Verification |
| --- | --- | --- | --- | --- |
| `feat`, `fix`, `refactor`, `perf`, `test` | all four fields | required, "None." allowed | required; a `fix` row names the test that fails without and passes with | required, with "Not run" |
| `spec` | all four fields; blast radius is usually "the items this spec will mint" | required | replaced by one line: criteria attacked or not, and the record | `doc-lint` exit, plus what was checked by hand |
| `docs`, `chore` (prose) | one line | optional | omitted | `doc-lint` exit; a revision of existing text names the meaning-check report |
| dependency bumps (Dependabot) | untouched | | | |

Readability rules, in addition to `readable-prose`:

- **Gloss every id on first use, everywhere.** Work item, criterion, decision, section, PR number. `A17 (the three-attempt bound on dead runs)`, never `A17` alone. The Criteria table's middle column exists for this reason. A reader with no tracker access and no spec open can read the whole one-pager.
- **The one-pager has no evidence in it.** Tables of criteria, transcripts, counts of runs, gate output: below the fold. The lead paragraph may carry one measured result as a sentence.
- **Plain words over house terms.** Where a house term is unavoidable, define it in the sentence that uses it. "Quiescence (no blocking findings left)" on first use.
- **One clause per sentence in the lead and in Risk.** This is where the strain shows most, because the writer is compressing.
- **No section grows a sibling.** A new idea goes under the nearest existing heading, or it is a sentence, not a section.
- **Length follows from the rules.** No word target below the fold.

### 5. Generate the two sections that come from the tracker

"Where this fits" and "Discovered work" are facts the tracker holds, and an agent writing them by hand is the source of bare ids and wrong glosses. This repo's principle is code over prose, so a small script produces both blocks from the facade:

- Walk `work show <id>` up the `parent` field to the milestone, printing each id with its title, which is the gloss.
- List every item whose provenance names this item (`work discover --discovered-from <id>` writes that edge), with title and the triage record's scope reason, which is the "why not here" column.

The agent then writes only the lead, Risk, Changes and the evidence. The script is a candidate `work` verb or a sibling script in the skill, and it is the one piece of this proposal that has to run through the tracker facade's own process. If the facade cannot express the provenance query, that gap goes in a note on `agents-config-9k9` per the standing rule.

### 6. Codify the review-reply form that already exists

```
**<disposition>** (round N). <one sentence of evidence>. <test or measurement>. Commit <sha>.
```

Disposition is one of the panel's four: `fixed`, `rebutted`, `advisory-deferred`, `transferred`. A `fixed` reply on code names the test and the fails-without, passes-with observation. A `rebutted` reply gives the evidence. A deferred or transferred reply names the work item with a gloss. Under 80 words. The same gloss rule applies: `fails A17 (the three-attempt bound)`, not `fails A17`.

One clarification to AGENTS.md: it says only items that change the code get a reply. A `rebutted` finding changes no code and still earns one, because the reviewer and the next reader need the reasoning where the finding is. Bookkeeping and meta comments stay silent as written.

## Where it lives

The shape has to reach agents in every project, so it is a deployed asset, not a `.github/pull_request_template.md`. Agents create PRs with `gh pr create --body-file`, so GitHub's template would never be read by the author that matters.

Proposed: one shared skill under `src/user/.agents/skills/`, working name `change-record`, holding moves 2, 3, 4 and 6 and the variants, with the generator from move 5 beside it or behind a `work` verb. It is plain text with no tool-specific capability, so it belongs in the shared tree. It loads when a commit, PR description or review reply is about to be written. It is a sibling of `readable-prose`, which keeps owning sentence quality; this skill owns shape and the gloss rule.

Admission record draft for `admit-request`:

- prevents: a PR the owner cannot read without opening the tracker and the spec beside it; a one-pager that does not exist because evidence and summary sit at the same level; risk and discovered work that go unstated; 35 heading vocabularies for six ideas; evidence hidden in invented trailers that trailer parsers reject; a squash commit repeating its trailers once per branch commit.
- cost: one skill load, about 800 tokens, at PR and commit time. One generator script with its tests. A one-time settings change on the repository.
- remove_when: twenty consecutive merged PRs carry the headings in order, every id glossed, Risk and Discovered work filled, and no invented trailer, with the skill not loaded.

Move 1 is a repository setting, not an asset, and needs no admission.

## Not proposed

- A commit-msg lint hook. commitlint adds a Node dependency; a Python check in content-tests is twenty lines. Neither has a consumer today. Add one only if the skill alone does not hold the shape after ten PRs. A bare-id check (an id with no parenthesised gloss after it) would be the first lint worth writing, because it is the defect a human notices last and resents most.
- A `.github/pull_request_template.md` for this repo. Humans rarely open PRs here by hand. Cheap to add later.
- A tracker-id trailer. The scope already carries the short id, and no consumer reads a trailer. Add `Work:` only when `work deliver` or git-cliff wants it.
- YAML or JSON blocks in the PR body. A table with fixed headers is parseable and a human reads it unaided.
- A separate risk register or a severity scale. Four free-text fields under one heading are enough until a reader asks for a comparison across PRs.
