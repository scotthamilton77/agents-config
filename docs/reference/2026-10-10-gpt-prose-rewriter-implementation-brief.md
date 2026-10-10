# GPT’s recommendations for the prose rewriter

## Objective

Implement a bounded GPT editing stage between Claude’s structured change record and the mechanical rendering of PR descriptions, commit messages and review replies. The stage should improve readability while preserving the author’s meaning. Select the cheapest model and effort that meet that standard in a recorded experiment.

## Context

The owner prefers GPT’s clearer sentences and explanations. Claude has the implementation context that GPT may lack. GPT should propose edits; Claude should decide whether those edits preserve the work’s meaning.

Resolve and report your actual repository or worktree root before editing. The reference repository is `/Users/scott/src/projects/agents-config`. These existing comparison artifacts are read-only:

- `/Users/scott/src/projects/agents-config/docs/reference/2026-10-10-change-artifact-templates-r2.md`
- `/Users/scott/src/projects/agents-config/docs/reference/2026-10-10-pr-template-examples-r2.html`
- `/Users/scott/src/projects/agents-config/.claude-scratch/git-doc-templates-mock.html`

Treat the proposed interface and model sufficiency below as hypotheses. Verify the existing implementation, repository rules, model access and current model documentation before building on them. Integrate with the chosen artifact pipeline. Avoid creating a competing source of truth or a new orchestration framework.

## Constraints and recommended design

### The rewriter’s function

GPT edits wording, sentence structure and organization within explicitly allowed prose fields. It receives the complete structured record, original prose, relevant evidence summaries and writing instructions. It does not need the entire authoring conversation.

It must preserve both the structured facts and meanings expressed only in the original prose. If those sources conflict or omit necessary context, it returns a question. It does not investigate the repository, invent facts, resolve design questions or change scope.

Protect IDs, ancestry, URLs, commands, revisions, counts, statuses, criterion obligations, review dispositions, attribution and automation-owned blocks. The renderer owns fixed headings and metadata. A subject’s descriptive wording may be editable; its type, scope and tracker linkage remain protected.

Make uncertainty explicit. “The PR reports the gate passed” must not become “The change is verified.” “Activity shows a read” must not become “The reviewer understood the change.” Preserve exclusions, ownership, conditions, exceptions, timing and unresolved work.

The writing instructions should require complete sentences, one idea per sentence, named actors and direct verbs. Spell out references when the record supplies their meaning. Remove strained grammar, unexplained shorthand, noun stacks and editing history. Do not use em dashes. Do not shorten a passage by deleting a qualification.

### Suggested interface

Use a versioned structured request and response. Reuse the existing format if it expresses this contract.

The request carries the source-record digest, an allowlist of editable sections, the complete record, original section text, relevant fact references and the writing standard.

The response proposes complete replacements for selected sections. It does not return a replacement record or a rewritten PR as one unstructured blob. An empty replacement list is valid.

A suitable response shape is:

```json
{
  "schema_version": 1,
  "source_record_digest": "<digest of the input record>",
  "replacements": [
    {
      "section_id": "<allowed section identifier>",
      "original_section_digest": "<digest of the original text>",
      "replacement_text": "<proposed prose>",
      "preserved_fact_ids": ["<existing fact reference>"],
      "meaning_notes": "<why the edit preserves the meaning>"
    }
  ],
  "questions": [
    {
      "section_id": "<affected section>",
      "question": "<missing information or contradiction>"
    }
  ]
}
```

Fact references and meaning notes help inspection. They are the editor’s assertions, not proof of semantic equivalence. Define permitted fields and validation behavior explicitly.

### Recommended process flow

1. Claude writes the structured source record and initial prose. The initial lint checks required content and record structure.
2. GPT proposes section replacements using that exact record revision.
3. Mechanical validation checks the response schema, source and section digests, editable-section allowlist, fact-reference validity and protected values. Invalid output leaves the source unchanged.
4. Claude compares each proposal with the original context. It accepts it, rejects it with a specific reason, or makes the smallest correction needed to restore meaning. Unresolved questions block affected sections.
5. Accepted text becomes a new source-record revision. Preserve proposals and author decisions in a separate audit record. Keep this editing history out of the published artifacts.
6. Mechanical renderers produce the PR description, commit message and review replies as separate views. They use different detail budgets. The commit renderer does not copy the PR body wholesale.
7. Final lint checks the rendered views, required confidence limits and automation-owned blocks. Publishing follows the existing authorization rules.

Start with one editing pass. Make retries bounded and explicit. If Claude substantially rewrites an accepted proposal, check that final text for readability again. Avoid an indefinite exchange between two editors.

### Model and effort experiments

The starting recommendation is `gpt-6-luna` with reasoning effort `low`. Compare these configurations:

| Configuration | Question |
| --- | --- |
| GPT-6 Luna, low | Is the cheapest proposed setting sufficient? |
| GPT-6 Luna, medium | Does additional effort materially reduce repairs or meaning changes? |
| GPT-6.1 Sol, low | Does a stronger model justify its additional cost? |

Use the same inputs, instructions and output contract for each configuration. The four existing examples cover PR 774 (read-evidence gate), PR 777 (prose-fix evidence), PR 807 (evaluation specifications) and PR 843 (reviewer settings and recovery). Their original descriptions are embedded in the HTML. Keep the GPT rewrites out of experiment inputs; they can serve as quality comparators.

Include difficult passages involving partial delivery, deferred findings, reported checks, environment caveats and unavailable evidence. Include commit and reply samples as well as PR sections.

Before running models, fix the cases, scoring rubric, repetition count and selection rule. A reasonable first experiment uses the four PR records with their related commit and reply samples, three configurations and three repetitions. Use existing authorized model access. Record any missing access instead of substituting a model silently.

Measure schema validity, protected-value preservation, material omissions, claim strengthening, author corrections, readability, latency, and billed tokens or available usage measures. Readability is human judgment; give the owner anonymized outputs to assess. Record the rubric and owner’s judgments. Token counts alone do not establish readability.

Select the cheapest configuration whose raw proposals have no observed material meaning changes, whose reviewed outputs meet the owner’s readability rubric, and whose repairs stay below the declared correction limit. Report errors in the raw proposals and the cost of repairing them. A cheap editor that repeatedly needs extensive repair is a poor default. These trials establish suitability on the sample, rather than general reliability.

Current documentation supports Luna/low as a starting point for fine-grained edits. Model sufficiency for this workflow remains unmeasured. Verify pricing and supported effort settings when running the experiment:

- https://developers.openai.com/api/docs/guides/model-selection
- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/models/gpt-6.1-sol

### Ownership and boundaries

Preserve the existing template and mock files. Put new implementation and experiment artifacts in appropriate new files. Follow repository instructions for tracker access, worktrees, admission, tests and delivery. Do not edit deployed configuration or install anything automatically.

Resolve routine implementation choices yourself. Report a missing resource, contradiction, destructive step or material expansion of scope before proceeding with the affected work. Continue independent work where possible.

## Acceptance criteria

- **The editor has bounded authority.** A fixture that attempts to replace a protected field or an unapproved section is refused without changing the source record.
- **Stale proposals cannot apply.** A response for a different record digest or section digest is refused without mutation. Malformed responses also leave the source unchanged.
- **Author decisions control application.** A mixed fixture containing accepted, rejected and questioned replacements applies only the explicitly accepted text. The audit record preserves each disposition and its reason.
- **Meaning checks cover the material risks.** Seeded edits that omit an exception, turn a reported check into a verified claim, or erase deferred work are rejected during the defined author-vetting check. Report that check’s evaluator and evidence. Structural validation alone does not satisfy this criterion.
- **Rendering preserves the contract.** Accepted source records produce the required artifact sections, tracker placement and unchanged automation blocks. Run the repository’s appropriate gates standalone and report their exit statuses. For code under packages or tested skills, follow the root requirement to run `make ci` from the actual working tree. Run `make doc-lint` for prose changes and directly inspect new files excluded from its tracked-file selection.
- **Selection has evidence.** The experiment retains inputs, outputs, settings, repetitions, evaluation decisions and cost or usage observations. The final recommendation follows the declared selection rule. If human readability judgment or model access is missing, model selection remains pending.

## Reporting contract

Deliver an implementation report with the resolved working root, interfaces produced, files changed, evidence for each acceptance criterion, gate exit statuses and experiment results. Explain the recommended default and fallback. List remaining uncertainty and discovered work, including anything not filed.

Make that report your final response to the owner. If your calling harness explicitly requires delivery through an agent-messaging tool, send the same report there as well. Do not infer authorization to publish or merge from this brief.

If the brief is ambiguous, self-contradictory or rests on a premise the evidence does not support, report the conflict rather than guessing. Assume there may be an error in the framing.
