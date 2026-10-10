# Make change artifacts readable and parseable

**2026-10-08.** Adopt three compact templates through the existing readable-prose skill. Put the PR’s outcome, place in the project, risk, verification and discovered work above optional detail. Keep commit metadata in terminal trailers. Make review replies identify the remedy and its evidence. Change squash defaults so they stop concatenating the branch’s editing history.

## 1. Diagnosis

The repository already has a [readable-prose standard](../../src/user/.agents/skills/readable-prose/SKILL.md) and [communication rules](../../AGENTS.md). Neither defines these three artifact formats. Searches of .github, src, docs, scripts and packages found no dedicated commit or PR template and no commitlint configuration. A vendored skill-authoring reference contains example commit messages, rather than a repository contract. Local hooks check package gates and invoke tracker integration. There is no commit-msg hook or configured commit.template.

The commit sample is the 200 commits ending at [the audited head](https://github.com/scotthamilton77/agents-config/commit/c3f11fcecda60d88ac65d7d05a3d7da296026a83), spanning August 22 to October 8. PRs are the twelve latest by mergedAt, retrieved with gh pr list and then sorted by merge time. Counts include squash-generated content and attribution. Word counts split on whitespace.

| Artifact | Consistent | Drift or missing structure |
| --- | --- | --- |
| Commits, 200 | 199 use lowercase type prefixes. Types: feat 61, fix 56, chore 36, docs 25, spec 17, test 3, refactor 1. | 191 have scopes; 190 use tracker IDs and one uses delegation. 110 descriptions begin with “the”, “a” or “an”, commonly describing a state instead of naming an action. Subject lengths: minimum 27, median 91, maximum 147 characters; 176 exceed 72 and 56 exceed 100. Bodies: median 238.5 words, maximum 2,574; four are empty. |
| Commit trailers | Git interpret-trailers recognizes Co-authored-by in 191 commits and Co-Authored-By in two. | Embedded coauthor lines total 830 across 193 commits. Claude-Session appears 671 times across 192 commits, but only two terminal blocks expose it to Git’s parser. Spelling and placement both drift. |
| PR descriptions, 12 | All describe changes and verification. All include Claude attribution. | Median 609.5 words; range 257–1,401. There are 46 distinct level-two headings. All twelve contain a first-use tracker or criterion reference without an inline plain-language gloss. None explains the complete actual ancestor chain. None has a dedicated risk or blast-radius heading. None has a systematic created/updated discovery table. |
| Review replies | PR 843 has 30 inline comments, comprising 15 roots and 15 author replies. All replies identify a fixed disposition and commit. Fourteen mention tests. | Reply lengths: 56–218 words, median 93. All fifteen repeat campaign status. A superseded finding still receives a fixed label. Editing history competes with the remedy. |

PR body measurements, ordered by merge time:

| PR | Words | First level-two heading |
| --- | ---: | --- |
| 777 | 481 | What this changes |
| 807 | 622 | What the branch delivers |
| 843 | 808 | What |
| 846 | 341 | What changes |
| 839 | 733 | What changed |
| 837 | 257 | What changes |
| 835 | 502 | What changed |
| 834 | 533 | What changed and why |
| 838 | 1,290 | Behaviour |
| 833 | 597 | What changes |
| 832 | 1,401 | What changes |
| 831 | 1,335 | What changes |

Across all sections, What changes occurs five times, Evidence ledger four times, and Criteria → tests (red before, green after) three times. Gate, Gates and headings with a head SHA express the same purpose under different names.

“Unglossed” means a reference lacks a description at its first occurrence. This does not mean the entire PR lacks useful explanation. Several bodies state costs or limitations. One Known open section lists two follow-ups. Three Bugs sections discuss existing items.

PR 843 is the most-reviewed sample member by total REST inline-comment count. PR 807 has more root comments, sixteen, but no inline replies. These measures do not identify human interventions because replies can use the owner’s credentials.

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

These are defaults for agent-authored artifacts. A host project’s contribution policy takes precedence. A prohibition on AI-written messages means a human must write them.

### Commit message

```text
<type>(<component>): <imperative result>

Why
<The previous problem and who it affected.>

Change
<The resulting behavior and the important tradeoff.>

Verification
<The check, observed result and material limitation.>

Work-item: <full-id> (<short purpose>)
Co-authored-by: <actual contributor name and email>
```

The fixed body section names are Why, Change and Verification. Aim for 80–150 body words. A trivial change may omit the body when the subject fully explains it. Keep relevant verification in the PR.

Use commitlint’s eleven types, plus the existing spec type for design contracts. Use feat for new behavior and fix for defects. Scopes name components such as installer, prgroom, grillui, skills or docs. Tracker IDs belong in trailers. Target 72 subject characters; enforce 100. These limits are proposed choices.

Use one Work-item trailer per associated item. The value contains its full ID and purpose, so machines extract the ID and readers understand it. Omit it when no tracker exists. Coauthorship is optional and must follow the host policy. Preserve genuine human authorship. Never invent sign-offs.

For a breaking change, add `!` and a BREAKING CHANGE footer stating the affected interface and migration. Allow ordinary required trailers such as human Signed-off-by. Parse them separately from body sections. Do not copy review rounds, full test lists or session transcripts into a commit.

### PR description

```markdown
## Executive summary
<Problem, affected reader or user, and resulting behavior.>

**Project context:** <Item and each actual ancestor, with purpose.>
**Scope:** <Affected components, users and data.>
**Risk:** <Concrete failure consequence, mitigation and recovery.>
**Verification:** <Reviewed head, decisive checks and results.>
**Follow-ups:** <Created/updated counts and unresolved consequence, or None.>

## Discovered work
| Action | Work item | Description | Why outside this PR |
| --- | --- | --- | --- |
| Created or Updated | <full-id> | <purpose and recorded change> | <specific reason> |

## Details
<Optional design reasoning and linked verification evidence.>
```

Executive summary ends at the next heading. Cap it at 300 words. This is the operational definition of one page because screen and print layouts vary. Write connected sentences. Keep the six fixed fields visible. The summary must answer the owner’s questions without opening Details.

For Project context, follow parent fields with work show until the milestone or root. State each node’s purpose and this PR’s contribution. Include the item itself. Do not infer parentage from dotted IDs or invent an epic. If an ancestor cannot be read, identify the missing context explicitly.

For example, agents-config-9k9.315.5 (the grilling-board result-update slice) belongs to agents-config-9k9.315 (the pending-analysis design container), which belongs to agents-config-9k9 (the Harness rework milestone). Its context should explain how controlling result updates supports safe board decisions and the larger autonomous workflow. This chain has no separate epic.

Risk names what happens if the change is wrong. State who or what is exposed, the prevention evidence and how recovery works. For instruction changes, include every tool receiving the changed guidance. For specs, identify decisions implementation will inherit. Avoid unsupported “low risk” and “no risk”.

Verification records the exact head and observed checks. Summarize their behavioral coverage. Link detailed evidence through durable repository or CI URLs. An untracked local scratch path is insufficient evidence for a later reader. Record pending human acceptance separately from a clean machine review.

Discovered work lists every item created or updated because of the PR’s investigation or review. Use full IDs and descriptions. Explain the actual boundary, dependency or separate design cycle. Existing owning-item status updates need not be called discoveries. If none exist, write “None.” In-scope work remains due unless a permitted deferral applies. Preserve any facade-generated discovery manifest verbatim in Details.

Details is optional. Link criterion evidence with each criterion’s meaning. Preserve all automation-owned blocks byte-for-byte outside the authored sections. Do not emit an empty Decisions block because its existing writer owns that heading and its contents.

Only two content variants earn a place: implementation summaries explain behavior before and after; spec summaries explain the decision and what remains unimplemented. Both use the same headings. Dependency and release bots retain their own formats.

### Review reply

```text
Outcome: Fixed.
Change: <Concern answered and resulting behavior> (<commit link>).
Verification: <Reproducer or other check, with observed result>.
```

Use one reply per finding that caused a code or prose change. Target 40–90 words. Keep Outcome, Change and Verification fixed. Explain every referenced criterion locally. Give a prose fix a specific inspection or lint result instead of inventing a test.

If a revised contract removes the reported behavior, use “Outcome: Superseded.” Explain what disappeared and verify its absence. Do not label that as a repaired defect. Preserve existing idempotency markers. Keep campaign status once in the PR’s Verification field. Bookkeeping and unchanged dispositions stay in the review inventory under the repository’s current rule.

| Owner complaint | Answering section |
| --- | --- |
| Cryptic prose and unexplained IDs | Commit Why/Change; PR Executive summary; reply Change; full-ID glosses throughout. |
| Missing project context | Executive summary’s Project context, using verified ancestry. |
| Verbosity and loose format | Bounded Executive summary, fixed fields and optional Details. |
| Missing risk and blast radius | Scope and Risk, with consequences, mitigation and recovery. |
| Missing discovered work | Follow-ups summary and Discovered work table. |

### Placement and adoption

Keep the canonical templates as supporting references inside [the existing shared readable-prose skill](../../src/user/.agents/skills/readable-prose/). Extend its trigger to commits and review replies. The [shared source tree](../../src/user/.agents/AGENTS.md) reaches all supported tools and other repositories after the owner installs it. Its present deployed Codex copy exists; these proposed templates do not yet exist.

Generate this repository’s .github/PULL_REQUEST_TEMPLATE.md from the canonical reference. Avoid independently maintained copies. Admission review and token caps apply before shipping changed guidance. Test the expanded trigger and template application against baseline failures before deployment. Add mechanical validation of headings, required fields, length, trailer grammar and discovery rows. Grammar, useful context and honest risk still require review. Begin with warnings and evaluate whether human clarification decreases before making structural checks blocking.

## 4. Settings and tooling, ranked by cost

1. **Lowest: change squash defaults.** Current settings are COMMIT_OR_PR_TITLE and COMMIT_MESSAGES. Use PR_TITLE and BLANK to prevent concatenation. At an explicitly authorized merge, supply a concise commit body and trailers through gh pr merge --body-file. BLANK alone loses context. [API](https://docs.github.com/en/rest/repos/repos#update-a-repository), [CLI](https://cli.github.com/manual/gh_pr_merge)
2. **Low: control automatic attribution.** Set Claude attribution.pr to empty and sessionUrl to false. Preserve required disclosure in the authored description. Customize attribution.commit only after choosing the host’s policy. Do not replace real contributors. [Settings](https://code.claude.com/docs/en/settings-reference#attribution)
3. **Low: configure commitlint.** Add spec to the preset’s types and enforce the proposed header limit. Validate terminal trailers with Git. Do not re-lint historical commits.
4. **Medium: validate artifacts and merge text.** Check mutable PR bodies on edits. Validate the final squash message separately because local hooks do not govern GitHub-generated commits. Preserve sentinel blocks and exempt bot-owned formats. Pin review and merge checks to the reviewed head.

These are proposals. No setting, hook or deployed instruction was changed.

## 5. Considered and rejected

- **Copy the PR body into the squash commit:** imports tables, mutable review records and automation blocks.
- **Use tracker IDs as scopes:** provides linkage while withholding component meaning.
- **Make every commit carry the PR’s full context:** repeats the hierarchy and increases reading cost.
- **Add a new global writing rule or skill:** duplicates the existing prose standard and expands the instruction surface.
- **Invent hidden JSON metadata now:** introduces synchronization without a demonstrated consumer. Fixed fields, discovery rows and terminal trailers cover the proposed parsing needs.
- **Require exhaustive test names or review chronology:** hides decisive evidence and belongs in linked records.
- **Treat attribution as approval or certification:** does not prove understanding, correctness or merge authorization.
