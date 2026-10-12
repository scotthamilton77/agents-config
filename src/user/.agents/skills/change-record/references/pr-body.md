${summary}

## Heads-up
- ${heads_up[]}

{{#pr.type=feat,fix,perf,refactor,spec,test}}
## Where this fits
${where_this_fits.ancestry[].id}  ${where_this_fits.ancestry[].title} (${where_this_fits.ancestry[].type})
    this PR: ${work_item.slice}
{{#where_this_fits}}
Builds on: ${where_this_fits.builds_on}. Concurrent: ${where_this_fits.concurrent}.
{{/where_this_fits}}
{{#where_this_fits.scope}}
<details><summary>Scope of the owning item</summary>

| Slice | What it covers | Status |
| --- | --- | --- |
| ${where_this_fits.scope[].slice} | ${where_this_fits.scope[].covers} | ${where_this_fits.scope[].status} (#${where_this_fits.scope[].pr}) |
</details>
{{/where_this_fits.scope}}

{{/pr.type}}
## Risk
| What could go wrong | Who or what is exposed | How we know it did not | What to do if it did |
| --- | --- | --- | --- |
| ${risk.rows[].failure} | ${risk.rows[].exposed} | ${risk.rows[].evidence} | ${risk.rows[].recovery} |
{{#pr.type=feat,fix,perf,refactor,spec,test}}
{{#blast_radius}}
<details><summary>Blast radius</summary>

{{#blast_radius.reach_graph}}
```mermaid
${blast_radius.reach_graph}
```

{{/blast_radius.reach_graph}}
{{#blast_radius.task_flow}}
```mermaid
${blast_radius.task_flow}
```
{{/blast_radius.task_flow}}
{{#blast_radius.mints}}

| Item the spec mints | What it is |
| --- | --- |
| ${blast_radius.mints[].id} | ${blast_radius.mints[].what} |
{{/blast_radius.mints}}
</details>
{{/blast_radius}}
{{/pr.type}}

## Changes
- **${changes[].topic}.** ${changes[].text}
{{#design_notes}}
<details><summary>Design notes</summary>

${design_notes}
</details>
{{/design_notes}}

## Discovered work
| Item | Status | What it is | Why not in this PR |
| --- | --- | --- | --- |
| ${discovered.rows[].item} | ${discovered.rows[].status} (#${discovered.rows[].pr}) | ${discovered.rows[].what} | ${discovered.rows[].reason} |

---

## Verification
- ${verification.gates[].gate}: exit ${verification.gates[].exit_status}, run standalone from ${verification.gates[].location} at ${pr.head_sha}.
- Not run: ${verification.not_run[]}

{{#campaign.reviewers}}
### Review campaign
| Reviewer | Rounds | Findings | Fixed | Rejected | Deferred |
| --- | --- | --- | --- | --- | --- |
| ${campaign.reviewers[].reviewer} | ${campaign.reviewers[].rounds} | ${campaign.reviewers[].findings} | ${campaign.reviewers[].fixed} | ${campaign.reviewers[].rejected} | ${campaign.reviewers[].deferred} |

{{#campaign.terminal_sha}}
Terminal-clean at ${campaign.terminal_sha}. Approval is a machine attestation of that head.
{{/campaign.terminal_sha}}
{{#campaign.findings}}
<details><summary>Findings by round</summary>

| Round | Id | Finding in plain words | Disposition | Reason | Commit |
| --- | --- | --- | --- | --- | --- |
| ${campaign.findings[].round} | ${campaign.findings[].id} (claim ${campaign.findings[].claim_id}, ${campaign.findings[].artifact_class}) | ${campaign.findings[].claim} | ${campaign.findings[].disposition} | ${campaign.findings[].reason} | ${campaign.findings[].commit} |
</details>
{{/campaign.findings}}

{{/campaign.reviewers}}
{{#pr.type=feat,fix,perf,refactor,spec,test}}
{{#criteria}}
## Criteria
{{#pr.type=spec}}
${criteria}
{{/pr.type}}
{{#pr.type=feat,fix,perf,refactor,test}}
| Criterion | What it promises | Evidence |
| --- | --- | --- |
| ${criteria[].id} | ${criteria[].promise} | ${criteria[].evidence} |
{{/pr.type}}

{{/criteria}}
{{/pr.type}}
<details><summary>Proposed commit message</summary>

```text
${commit_message}
```
</details>

{{#decisions}}
${decisions}

{{/decisions}}
{{#record_comment_url}}
Rendered from change record ${record_comment_url}, revision ${record.revision}.
{{/record_comment_url}}
Generated with ${commit.attribution.tool} · ${commit.attribution.session_url}
