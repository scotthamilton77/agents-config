${summary}

## Heads-up
- ${heads_up[]}

## Where this fits
${where_this_fits.ancestry[].id}  ${where_this_fits.ancestry[].title} (${where_this_fits.ancestry[].type})
    this PR: ${work_item.slice}
Builds on: ${where_this_fits.builds_on}. Concurrent: ${where_this_fits.concurrent}.
<details><summary>Scope of the owning item</summary>

| Slice | What it covers | Status |
| --- | --- | --- |
| ${where_this_fits.scope[].slice} | ${where_this_fits.scope[].covers} | ${where_this_fits.scope[].status} |
</details>

## Risk
| What could go wrong | Who or what is exposed | How we know it did not | What to do if it did |
| --- | --- | --- | --- |
| ${risk.rows[].failure} | ${risk.rows[].exposed} | ${risk.rows[].evidence} | ${risk.rows[].recovery} |
<details><summary>Blast radius</summary>

```mermaid
${blast_radius.reach_graph}
```

```mermaid
${blast_radius.task_flow}
```
</details>

## Changes
- **${changes[].topic}.** ${changes[].text}
<details><summary>Design notes</summary>

${design_notes}
</details>

## Discovered work
| Item | Status | What it is | Why not in this PR |
| --- | --- | --- | --- |
| ${discovered.rows[].item} | ${discovered.rows[].status} | ${discovered.rows[].what} | ${discovered.rows[].reason} |

---

## Verification
- ${verification.gates[].gate}: exit ${verification.gates[].exit_status}, run standalone from ${verification.gates[].location} at ${pr.head_sha}.
- Not run: ${verification.not_run[]}

### Review campaign
| Reviewer | Rounds | Findings | Fixed | Rejected | Deferred |
| --- | --- | --- | --- | --- | --- |
| ${campaign.reviewers[].reviewer} | ${campaign.reviewers[].rounds} | ${campaign.reviewers[].findings} | ${campaign.reviewers[].fixed} | ${campaign.reviewers[].rejected} | ${campaign.reviewers[].deferred} |
Terminal-clean at ${campaign.terminal_sha}. Approval is a machine attestation of that head.
<details><summary>Findings by round</summary>

| Round | Id | Finding in plain words | Disposition | Reason | Commit |
| --- | --- | --- | --- | --- | --- |
| ${campaign.findings[].round} | ${campaign.findings[].id} | ${campaign.findings[].claim} | ${campaign.findings[].disposition} | ${campaign.findings[].reason} | ${campaign.findings[].commit} |
</details>

## Criteria
| Criterion | What it promises | Evidence |
| --- | --- | --- |
| ${criteria[].id} | ${criteria[].promise} | ${criteria[].evidence} |

<details><summary>Proposed commit message</summary>

```text
${commit_message}
```
</details>

${decisions}

Rendered from change record ${record_comment_url}, revision ${record.revision}.
Generated with ${commit.attribution.tool} · ${commit.attribution.session_url}
