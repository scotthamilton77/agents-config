# Make change artifacts readable and parseable

**2026-10-10.** Use concise summaries with visible confidence limits and expandable evidence. Put the work item in the PR title and immediately below the commit subject. Show ancestry, related PRs, risk consequences and every known discovery. Keep review dispositions separate from approval. This revision retains the October 8 research sample.


## 1. Diagnosis

The repository already has a [readable-prose standard](../../src/user/.agents/skills/readable-prose/SKILL.md) and [communication rules](../../AGENTS.md). Neither defines these three artifact formats. Searches of .github, src, docs, scripts and packages found no dedicated commit or PR template and no commitlint configuration. A vendored skill-authoring reference contains example commit messages, rather than a repository contract. Local hooks check package gates and invoke tracker integration. There is no commit-msg hook or configured commit.template.

The commit sample is the 200 commits ending at [the audited head](https://github.com/scotthamilton77/agents-config/commit/c3f11fcecda60d88ac65d7d05a3d7da296026a83), spanning August 22 to October 8. PRs are the twelve latest by mergedAt, retrieved with gh pr list and then sorted by merge time. Counts include squash-generated content and attribution. Word counts split on whitespace.

| Artifact | Consistent | Drift or missing structure |
| --- | --- | --- |
| Commits, 200 | 199 use lowercase type prefixes. Types: feat 61, fix 56, chore 36, docs 25, spec 17, test 3, refactor 1. | 191 have scopes; 190 use tracker IDs and one uses delegation. 110 descriptions begin with “the”, “a” or “an”, commonly describing a state instead of naming an action. Subject lengths: minimum 27, median 91, maximum 147 characters; 176 exceed 72 and 56 exceed 100. Bodies: median 238.5 words, maximum 2,574; four are empty. |
| Commit trailers | Git interpret-trailers recognizes Co-authored-by in 191 commits and Co-Authored-By in two. | Embedded coauthor lines total 830 across 193 commits. Claude-Session appears 671 times across 192 commits, but only two terminal blocks expose it to Git’s parser. Spelling and placement both drift. |
| PR descriptions, 12 | All describe changes and verification. All include Claude attribution. | Median 609.5 words; range 257–1,401. There are 46 distinct level-two headings. All twelve contain a first-use tracker or criterion reference without an inline plain-language gloss. None explains the complete actual ancestor chain. None has a dedicated risk or blast-radius heading. None has a systematic created/updated discovery table. |
| Review replies | PR 843 has 30 inline comments, comprising 15 roots and 15 author replies. All replies identify a fixed disposition and commit. Fourteen mention tests. | Reply lengths: 56–218 words, median 93. All fifteen repeat campaign status. A superseded finding still receives a fixed label. Editing history competes with the remedy. |

Across the twelve PRs, What changes occurs five times, Evidence ledger four times, and Criteria → tests three times. “Unglossed” means a reference lacks a description at its first occurrence. Several PRs describe limitations, but they do not provide a consistent confidence summary.

Three passages show distinct problems:

- The commit for [PR 830](https://github.com/scotthamilton77/agents-config/pull/830) says “a ruling changes its own decision directly, and everything wider waits in the inbox showing before and after”. “Its own” lacks an explicit referent. “Everything wider” does not name the affected changes. The last phrase has an unclear attachment.
- [PR 807](https://github.com/scotthamilton77/agents-config/pull/807) contains “How the text got here”. Its eight chronological bullets require reconstructing the final state from revisions and review rounds.
- A [reply on PR 843](https://github.com/scotthamilton77/agents-config/pull/843#discussion_r4212288726) says “the restated design settles it by construction”. The reader must find the revised contract and infer why deletion answers the original finding.

The [reply writer](../../packages/prgroom/src/prgroom/lifecycle/reply.py) patches a Decisions section between `<!-- prgroom:decisions:start -->` and `<!-- prgroom:decisions:end -->`. It also emits per-entry markers and reply-idempotency comments. These markers have readers and writers in the current source. The [charter](../specs/2026-07-21-harness-rework-way-forward.md) permits review threads during the transition. Its eventual thin-PR model does not prohibit a concise human summary. The reply code still allows deferred thread replies, while the root delivery rule permits replies only for changed artifacts. The proposed reply contract follows the root rule.

## 2. External practice

- Use a standalone summary and explain the problem, result and reasons. Update the description when scope changes. References need summaries. [Google](https://google.github.io/eng-practices/review/developer/cl-descriptions.html)
- Prefer imperative summaries and complete sentences. Describe user impact and non-obvious costs. Go uses package prefixes; Linux asks commit references to include their summaries. [Go](https://go.dev/doc/contribute#commit_messages), [Linux](https://docs.kernel.org/process/submitting-patches.html)
- Conventional Commits defines type, optional scope, breaking-change syntax and footers. It does not mandate every type or a length limit. Commitlint’s preset supplies eleven types and a 100-character header limit. A stricter limit is a local choice. [Specification](https://www.conventionalcommits.org/en/v1.0.0/), [preset](https://github.com/conventional-changelog/commitlint/blob/master/%40commitlint/config-conventional/src/index.ts)
- Parse metadata from a terminal trailer block separated by a blank line. Grepping colon-bearing lines also counts embedded historical messages. Breaking-change footers require Conventional Commits handling. [Git](https://git-scm.com/docs/git-interpret-trailers)
- Reply with technical reasons and improve the lasting artifact when confusion reveals missing explanation. [Google’s handling-comments guide](https://google.github.io/eng-practices/review/developer/handling-comments.html)
- AI policies are project-specific. Kubernetes requires disclosure but prohibits AI-written commit messages, AI-assisted replies and AI attribution trailers. The kernel forbids agents from certifying human sign-off. curl’s 2025 guidance permits verified assistance. Ghostty’s policy, updated in 2026, requires outside contributors to disclose tool and extent. [Kubernetes](https://www.kubernetes.dev/docs/guide/pull-requests/#ai-guidance), [kernel](https://docs.kernel.org/process/coding-assistants.html), [curl](https://curl.se/dev/contribute.html#on-ai-use-in-curl), [Ghostty](https://github.com/ghostty-org/ghostty/blob/main/AI_POLICY.md)
- Attribution provides traceability. Copilot names the initiating human as coauthor and links session logs. Claude Code separately controls commit attribution, PR attribution and session URLs. Neither supplies verification. [Copilot](https://docs.github.com/en/copilot/responsible-use/agents), [Claude settings](https://code.claude.com/docs/en/settings-reference#attribution)
- Preserve bot-owned structures. release-please consumes commit-override blocks. Dependabot parses metadata from commit YAML and body text. Renovate favors additive customization. Changesets stores release intent in committed files. There is no shared hidden-comment schema. [release-please](https://github.com/googleapis/release-please#how-can-i-fix-release-notes), [Dependabot](https://github.com/dependabot/fetch-metadata/blob/main/src/dependabot/update_metadata.ts), [Renovate](https://docs.renovatebot.com/configuration-templates/#pr-body), [Changesets](https://changesets.dev/faq)

## 3. Proposal

These templates serve human readers, later agents and parsers. Host contribution policies take precedence. A prohibition on AI-written messages requires human authorship.

### Commit message

```text
<type>(<component>): <imperative result>

Work-item: <full-id> (<purpose>)

Why
<Previous problem and affected reader or user.>

Change
<Resulting behavior and important tradeoff.>

Verification
<Decisive check, observed result and material limitation.>

<Required authorship or certification trailers, if any.>
```

Use the fixed names Work-item, Why, Change and Verification. Put one Work-item line per owning item immediately below the subject. Omit it when there is no tracker. Discovery items belong in the PR unless this commit also delivers them.

Use commitlint’s eleven types plus the repository’s existing spec type. Scopes name components. Target 72 subject characters; enforce 100. Aim for 80–150 body words. A self-explanatory trivial change may omit the three prose sections.

The top Work-item field is deliberately a body field. Git interpret-trailers cannot extract it there. A linkage parser must read that fixed location. Keep actual coauthor, human sign-off and breaking-change trailers in the terminal block. Never invent certification. A breaking change uses `!` and a BREAKING CHANGE footer describing the interface and migration.

### PR description

```markdown
Title: <type>(<full-work-id>): <plain-language result>

## Executive summary
<Problem, affected person and result.>

### Things you need to know
<Confidence limits, unsettled decisions and environment caveats.>

### Project context
<Owning item’s purpose, broader goal and this PR’s contribution.>
<details>
<summary>Ancestry, completed scope and remaining work</summary>

#### Where this fits
<Verified ancestor tree, with each node’s ID and purpose.>
<Already delivered / This PR / Concurrent / Still due scope table.>
<Related PRs: predecessor or concurrent; purpose and relationship.>

</details>

### Scope
<Affected components, users and data.>
<details>
<summary>Changes by topic</summary>

<Topical change descriptions and optional technical reasoning.>

</details>

### Risk
<Most important failure consequence and mitigation limit.>
<details>
<summary>Consequences, mitigation and blast radius</summary>

| Area | Blast radius | If this is wrong | Mitigation and its limit |
| --- | --- | --- | --- |
| <interface> | <people and systems> | <consequence> | <evidence> |

<Optional architecture and user-task diagrams.>

</details>

### Verification
<Decisive checks, results and review coverage.>
<details>
<summary>Criteria, review rounds and finding details</summary>

<Criteria table: ID and meaning / delivery claim / evidence and limit.>
<Review table: reviewer task / rounds / findings / fixed / rejected / deferred.>
<Per-round details: finding and key / disposition / reason / fix commit.>

</details>

### Follow-ups
<Recorded discoveries, unfiled work and consequences.>
<details>
<summary>Discovered work: filed, unfiled and communicated</summary>

| Record status | Item or communication | What was discovered | Why outside this PR |
| --- | --- | --- | --- |
| <created, updated, unfiled, coordinated or excluded> | <ID and purpose, or no ID recorded> | <finding and action> | <actual reason or reason missing> |

</details>
```

The title supplies linkage and a readable result. List additional owning items in Project context. The title’s work-ID scope is specific to PRs. Commits retain component scopes.

Keep the collapsed content, including Things you need to know, under 300 words. Use complete sentences and one idea per sentence. Each reference carries its meaning at first use. Expandable details sit beside the summary they explain. Never hide a confidence limit there.

Project context follows actual parent fields through work show. Explain every ancestor through the milestone or root. Do not infer parentage from dotted IDs. Identify partial delivery explicitly. Related PRs explain dependencies and coordination; they are not ancestors. State their status at the PR’s review boundary.

Scope groups changes by topic. Technical detail explains the decisions rather than repeating the changed-file list. Implementation changes describe resulting behavior. Specification changes identify decisions and unimplemented work. Both keep the same section names.

Risk states who suffers if the change is wrong. The table names exposed interfaces, consequence, prevention evidence and remaining uncertainty. Diagrams trace affected dependencies and user tasks. Distinguish current behavior from future workflows. Include recovery only when it gives a concrete operational action. A generic “revert” adds little.

Things you need to know includes unreviewed final edits, missing coverage, unsettled criteria, inaccessible evidence and environment-dependent checks. Verification records successful checks separately. Attach revisions and durable links to the claims they support.

Criteria rows spell out the obligation and observation. Distinguish implementation evidence from a delivered design contract. A complete attack record does not establish a fresh attack after an amendment.

For reviews, a lens is a reviewer assigned a specific task. Count finding keys, not comments or commits. Separate circuits, deduplicate reposted rounds, and exclude superseded campaigns from current totals. Show accepted/fixed, rejected with reasons, deferred, superseded and unknown dispositions. Expand each round to expose findings and introducing fix commits. Say when only a later verified revision is known. App approval is not a quality-review round.

Follow-ups includes created items, updated discoveries, unfiled defects and observations, communicated handoffs, parallel work and explicit scope exclusions. Planned continuation belongs in the scope table. Distinguish “not filed” from “filing unknown”. Explain the recorded reason for omission; missing reasons stay visible. Use “None” only when the inventory is complete. Preserve facade-generated discovery manifests verbatim.

Preserve automation-owned sentinel blocks byte-for-byte. Do not create an empty Decisions section; the existing writer owns it.

### Review reply

```text
Outcome: Fixed.
Change: <Concern answered and resulting behavior> (<fix commit link>).
Verification: <Reproducer or inspection and observed result>.
```

Use one 40–90-word reply per finding that caused a code or prose change. Explain referenced criteria locally. A prose correction can use inspection evidence. If a revised contract removes the challenged behavior, use “Outcome: Superseded” and verify its absence. Keep unchanged dispositions in the review inventory, following the repository’s existing rule. Preserve reply-idempotency markers. Campaign status belongs in the PR’s review table.

| Owner complaint | Answering section |
| --- | --- |
| Cryptic prose and unexplained IDs | Readable result, full-ID glosses, Why/Change and reply Change. |
| Missing project context | Project context, Where this fits, scope breakdown and related PRs. |
| Verbosity and loose format | Bounded visible summary and expandable detail beside each field. |
| Missing risk and blast radius | Visible Risk, consequence table and architecture/task diagrams. |
| Missing discovered work | Follow-ups and the filed/unfiled/communication inventory. |

### Placement and adoption

Keep canonical templates as references in the existing [shared readable-prose skill](../../src/user/.agents/skills/readable-prose/). Extend its trigger to commits and review replies. This tree deploys to all supported tools and follows agents into other repositories. The proposed references are not deployed.

Generate the repository PR template from that source. Admission review, token limits and skill-trigger tests precede deployment. Encourage adoption with lint warnings for structure, length, linkage, disposition totals and missing deferral reasons. Promote checks only after measuring reduced human clarification. Review still judges readability and honest risk.

## 4. Settings and tooling, ranked by cost

1. **Lowest: change squash defaults.** Current settings are COMMIT_OR_PR_TITLE and COMMIT_MESSAGES. Use PR_TITLE and BLANK to stop concatenating commit history. At an authorized merge, supply the component-scoped subject and concise body through gh pr merge --subject and --body-file. The PR title is not the canonical commit subject. [API](https://docs.github.com/en/rest/repos/repos#update-a-repository), [CLI](https://cli.github.com/manual/gh_pr_merge)
2. **Low: control attribution.** Set Claude attribution.pr to empty and sessionUrl to false. Keep required disclosure in the authored description. Choose commit attribution according to host policy. [Settings](https://code.claude.com/docs/en/settings-reference#attribution)
3. **Low: configure commitlint.** Add spec and the header limit. Parse terminal authorship trailers with Git. Read tracker linkage from the first body field. Exempt historical commits.
4. **Medium: reuse review records.** Render per-lens totals and per-round dispositions from existing verdict envelopes. Join actual fix commits without inferring missing dispositions.
5. **Medium: validate mutable PRs and squash text.** Check edited bodies, linkage and reviewed revisions. Preserve bot sentinels and bot-owned formats. GitHub squash commits bypass local hooks.

No settings, hooks or deployed instructions were changed.

## 5. Considered and rejected

- **Copy the PR into the squash commit:** imports mutable review records and automation blocks.
- **Tracker IDs as commit scopes:** obscures components. PR titles carry linkage separately.
- **A new global writing rule:** duplicates the existing prose skill.
- **Duplicate top and bottom tracker fields:** creates two authoritative values. Parse the single top field.
- **Hidden JSON without a consumer:** introduces synchronization costs. Existing verdict records already hold review structure.
- **Flat exhaustive summaries or file indexes:** bury the decision. Expand detail beside the relevant summary.
- **Generic rollback and unsupported risk labels:** provide no concrete consequence or operational help.
- **Treat deferred findings as rejected or fixed:** conceals remaining work.
