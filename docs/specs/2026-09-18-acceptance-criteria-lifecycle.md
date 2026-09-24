# Acceptance-criteria lifecycle

**Date:** 2026-09-18
**Status:** Draft for review. No attack or review is claimed for this document.
**Work item:** `agents-config-9k9.425` (the lifecycle-spec split).
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions
D3, D4, D7, D8 and D11.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`.

## Problem statement

Criteria can reach implementation through a spec, a tracker item, or an
amendment made during review. Independent copies in the spec, tracker, and
review input can disagree. A completed attack on one version says nothing
about criteria changed afterward.

The lifecycle must let an implementer obtain the authoritative contract and
let a reviewer establish which version was judged. It must also prevent
ordinary workflow transitions from silently using missing or stale evidence.

## Solution and scope

The tracker acceptance field selects the contract for an item. Consumers
render that selection through the facade instead of retyping it. A closed
attack record supports an attestation for a particular document and revision.
Claim, review, posting, and delivery check the relevant current state.

This document owns authority, reference resolution, attack records,
attestation, amendment, and enforcement. The quality contract owns what makes
criteria sufficient and what observations establish their success. The
lifecycle verifies references and evidence state; it does not mechanically
judge the meaning or completeness of criteria.

## User stories

1. As an implementer, I want one rendering of my assigned criteria and a clear
   refusal when the required attack has not closed.
2. As a spec author, I want children to reference my criteria without creating
   text copies that drift.
3. As a ticket author, I want criteria without a spec to use the same attack
   process and evidence rules.
4. As a reviewer, I want amendments to invalidate evidence for the old
   contract before another round uses the new one.
5. As a reader of a verdict, I want to see exactly the criteria that were
   judged, with freshness checked when the verdict is posted.

## Lifecycle decisions

### LIFE-D1: The field selects; the renderer resolves

The item acceptance field contains full text, criterion IDs from its named
spec, or both. The spec remains the authoring source for cited text. The
canonical contract is the field's selection after resolution. There is no
separate editable review copy.

`work acceptance render ID` emits Markdown containing the description under
its own heading and the resolved criteria under an acceptance-criteria
heading. Description text is context and is never parsed as criteria. The
rendering depends only on the description, acceptance field, and named spec.
Notes, titles, and other item metadata do not affect it.

Resolution follows these rules:

- Ignore blank lines. On an item naming a spec, a line containing only one
  criterion ID or comma-separated criterion IDs cites those entries in order.
  Whitespace around IDs is ignored. Other lines are text. Without a named
  spec, every line is text.
- Read cited entries with spec-lint's entry grammar, preserving the full
  entry and its continuation text. A criterion-shaped line starts another
  entry. Resolve citations once and preserve field order.
- Emit the existing `- **ID** text` bullet grammar. Explicit IDs survive;
  text without an ID receives a deterministic positional ID derived from the
  item ID and its nonblank position. Every emitted ID meets spec-lint's
  pattern. IDs minted this way are stable while that ordered input is unchanged.
- Refuse unresolved or duplicate IDs, including collisions between explicit,
  resolved, and generated IDs. Refuse a missing, unreadable, or unparseable
  named spec. Errors name the ID or path and cause. An empty cited entry
  contributes no criterion.
- Resolve relative spec paths from the repository root. A working-directory
  change does not change the result.

The workcli and spec-lint grammars remain marked counterparts with a common
round-trip fixture. This is a compatibility obligation across repositories.
Component specs define the exact generated-ID spelling and refusal payloads
within these observable constraints.

### LIFE-D2: One document is attacked for each item

An item is **spec-born** when every nonblank acceptance line consists solely
of citations into its named spec under LIFE-D1. Its attackable document is
that whole spec. Selection and child coverage are judged by the quality review
of the spec and its slice assignments. An empty selection remains unclaimable
even if the spec was attacked.

An item with any full-text line is **tracker-born**. Its attackable document
is its rendering, saved at `.work/attacks/<item-id>.md`. The attack record
lives beside that file at `.work/attacks/<item-id>-ac-attack.json`. Spec-born
records likewise live beside their specs under the checker's existing naming
convention. Both paths reuse the existing attack process.

For tracker-born work, the attack path renders, attacks, checks the closed
record, commits both files, and attests before the item reaches a transition
requiring attestation. A later use of unchanged files and valid evidence
reuses the record. It does not run a new model round just to reproduce it.

The generated directory is tracked and exempt from authored-prose doc-lint.
Its introduction includes a tracked placeholder, so the exemption never
names an absent directory. An agent fixes a stale rendering by updating the
item and rendering again; editing the generated file is not an amendment.

### LIFE-D3: Attestation binds to the attacked content

`work acceptance attacked ID --record PATH` records an attestation in an item
note. The marker contains a parseable timestamp and the digest of the attacked
document's bytes. Paths locate the document and its canonical record; they are
not part of that digest. Renaming a document preserves its attestation when
its content is unchanged and the references and record's filename binding are
updated together. A rename alone requires no new attack. The facade component
spec owns the marker's encoding.

The verb refuses without writing a marker if the record is unreadable or
unparseable, is not the canonical record beside the item's document, has an
undispositioned proposal, names inconsistent accepted revisions, or does not
close at the document's current digest. A tracker-born file must also equal
a fresh rendering. With no accepted proposals, the closing revision is the
attacked revision. Repeating or concurrently requesting the same attestation
leaves one marker.

The attack path calls this verb only after the existing checker succeeds.
The facade checks binding and closure; it does not duplicate the checker's
semantic or lens judgments. At a consuming boundary, the facade computes the
current document revision. For tracker-born items it computes a fresh
rendering rather than trusting the committed snapshot. A malformed marker
does not count; an unreadable marker source causes a named refusal.

This attestation records an account of a review. It cannot prove that a model
performed the review or that accepted proposals were implemented honestly.
Hand-authored marker notes and deletion of records after attestation remain
outside this trust boundary. The branch diff and review account expose them;
this design does not introduce tamper-proof evidence.

### LIFE-D4: Amendments invalidate evidence before reuse

Changing tracker-born acceptance text or description changes the rendering
and invalidates its attestation when the bytes change. Changing a spec's bytes
invalidates the spec's record and every spec-born item's attestation against
that revision. Changing a spec-born item's description does not invalidate
its attack because that description is not the attacked document.

An amendment uses the existing `work acceptance set --why` trail where the
field changes. The agent rerenders when needed, attacks the amended document,
commits the updated files, and attests again before using the amended contract.
The doctrine is "before use, and again after amendment." It also applies to
dispatch briefs and to changes prompted by a criteria-indicting review halt.

A full attack round is required after an attacked document changes. This
conservative rule also invalidates records for editorial changes and changes
to unrelated criteria within an attacked spec. Semantic or delta-scoped
invalidation is outside this version of the design.

Each operation checks the state it reads. A later concurrent amendment is
caught by the next consuming boundary. This design does not promise a
transaction spanning tracker changes, git, review emission, and posting.

### LIFE-D5: Gates act at defined transitions

Creation and discovery may hold rough or empty criteria. The following table
defines leaf behavior. All rendering refusals name their cause.

| Boundary | Nonempty, resolvable criteria | Current attestation |
| --- | --- | --- |
| Claim an open `feat` or `bugfix` | Required | Required unless `--trivial` |
| Claim an open `spike`, `chore`, or `decision` | Required | Not required |
| Deliver a leaf with `--pr` | Required, including `--trivial` | Required unless `--trivial` |
| Emit a review round naming an item | Required | Required unless `--trivial` |
| Post a verdict naming an item | Required | Required unless `--trivial` |

The claim gate guards the transition from open to in progress through every
verb that can make it. An already-in-progress claim remains a no-op. Installing
the facade does not rewrite existing items; later review and delivery still
apply their gates. Empty criteria name `work acceptance set` as the remedy;
missing attestation names the attack step. No gate classifies criterion prose.

Structural children have no noun. A design child remains outside the claim
and delivery gates; the spec it delivers is checked by the record gate when
its record is present. An implementation placeholder remains unclaimable and
is retired when the spec manifest expands. An item with neither a recognized
noun nor a recognized structural role is refused by type.

### LIFE-D6: Review and posting use the rendered contract

The review-panel criteria input must equal a fresh rendering when its claim
names an item. Emission records those judged bytes with the round. The verdict
poster accepts criteria only when they match both that recorded input and a
fresh rendering at posting time. A re-attacked amendment still needs a new
review of the amended criteria; freshness alone cannot validate an old verdict.

Both consumers refuse an empty rendering, a missing required attestation, or
a failure to obtain the current rendering. Neither falls back to an unchecked
file. The poster extracts criteria only from the acceptance-criteria section.
A target with no tracker item keeps the existing supplied-file path. The
invoker remains responsible for naming the work item; no PR-to-item discovery
service is added here.

### LIFE-D7: CI checks the committed account

A whole-repo gate invokes the source-tree attack checker with
`--implementation-started` for every tracked attack record in the checkout.
It reports all invalid records in one run. Invalid includes an open round,
missing required lens, stale revision, malformed record, and missing attacked
document. Missing checker or failed enumeration is an error. Ignored files,
untracked scratch records, and sibling worktrees are outside this inventory.
An empty inventory passes.

CI cannot see an uncommitted tracker edit. Until a fresh rendering is committed,
the live claim, emission, posting, and delivery checks catch that amendment.
After the changed document is committed, CI stays red until its record closes
at the new revision. The gate does not discover absent records, including
records deleted after attestation.

The checker uses its current required-lens registry. A change adding a lens
must update existing committed records before the new requirement is enforced
on the default branch. This migration cost is distinct from attacking open
tracker items, which occurs when they next reach a gated transition.

### LIFE-D8: Adoption uses the existing tools

Render, attest, and claim/delivery changes belong to the workcli repository.
The attack path, review emitter, and verdict poster check the installed facade
version before invoking new verbs. Each names the version shipping the verbs
it uses. An absent, failed, or unparseable version is refused by name;
semantic-version precedence decides whether a reported version is sufficient.
Facade delivery is complete only when the installed command reports that
version. Installation remains the user's action.

The attack and review skills remain Claude-only. Other tools hand those rounds
to a Claude Code session through the existing delivery workflow. This design
adds no cross-tool scheduler. Briefs cite the quality standard and the before-use
amendment rule. The shared quality standard is owned by its companion spec.

## Testing decisions

Use the workcli fake backend to observe command results and writes. Exercise
rendering through its public verb and parse its output with the existing
spec-lint and verdict consumers. Test review freshness at emission and posting
with controlled item revisions. Test the CI target in temporary git repositories
containing tracked, ignored, missing, and malformed records. No test deploys
configuration or rewrites the user's tracker.

Component child specs retain these public contracts and add the exact wire
formats and fixtures their implementation needs. They are required before
scaffolding their slice. Those details may not weaken the parent invariants or
move a significant product decision into implementation.

## Acceptance criteria

- **LIFE-A1** A caller rendering cited criteria receives their complete spec
  entries in field order, independent of the working directory. Comma-separated
  IDs and the same IDs on separate lines produce identical criteria output,
  including for children delivered before the renderer ships.
- **LIFE-A2** A caller rendering text or mixed text and citations receives
  stable, unique criterion IDs in the existing consumer grammar.
- **LIFE-A3** A rendering with an invalid reference or ID collision is refused
  with the offending ID or spec path and cause.
- **LIFE-A4** Existing criteria consumers recover only the rendering's criteria
  section, even when the description contains criterion-shaped text.
- **LIFE-A5** Repeated renders with unchanged description, criteria, and named
  spec are byte-equal despite changes to notes, title, or other metadata.
- **LIFE-A6** A valid closed record for the current document produces one
  attestation for its content revision, including after repeated or concurrent
  requests to attest that same record.
- **LIFE-A7** Attesting a record that violates the binding or closure conditions
  in LIFE-D3 is refused without writing a marker.
- **LIFE-A8** A tracker-born amendment that changes its rendering makes its
  prior attestation unusable, even while the committed rendering is stale.
- **LIFE-A9** Changing an attacked spec's content leaves its spec-born children
  unattested until the new revision is attacked and each child attests against it.
- **LIFE-A10** Renaming an attacked document without changing its bytes
  preserves each citing item's attestation once its references and the
  record's filename binding are updated, without another attack round.
- **LIFE-A11** Claiming a noun-bearing leaf with empty or unresolvable criteria
  refuses the transition and names the remedy or resolution failure.
- **LIFE-A12** Claiming an open leaf applies exactly the noun and triviality
  attestation rules in LIFE-D5, without judging criterion prose.
- **LIFE-A13** PR delivery refuses a leaf with empty or unresolvable criteria,
  including a trivial or already-in-progress leaf.
- **LIFE-A14** PR delivery refuses every nontrivial leaf without current
  attestation and accepts that requirement after a valid attestation.
- **LIFE-A15** Structural and unrecognized items follow the role-specific
  claim and delivery behavior in LIFE-D5 rather than inheriting a noun exemption.
- **LIFE-A16** Review emission for an item refuses any input that differs from
  its current eligible rendering; an eligible matching input becomes the
  round's recorded criteria.
- **LIFE-A17** Posting refuses criteria unless they match both the round's
  judged input and the item's current eligible rendering, including after
  an amendment has been re-attacked.
- **LIFE-A18** The CI gate reports every invalid tracked record and its cause
  in one run, including the record and document paths for a missing document.
- **LIFE-A19** The CI gate refuses to report success when its checker is
  unavailable or its tracked-record inventory cannot be enumerated.
- **LIFE-A20** The CI gate ignores records outside the current tracked checkout
  and succeeds when the resulting inventory is empty.
- **LIFE-A21** A consumer requiring a new facade verb refuses an insufficient
  or unestablished installed version before calling that verb and names the
  required version or version-read failure.
- **LIFE-A22** A tracker-born attack workflow produces committed current
  rendering and record files before attestation is required, and reuses them
  unchanged on a second invocation while their evidence remains current.
- **LIFE-A23** A spec-delivery child stores assigned IDs as citations, so an
  edit to a cited spec entry changes its rendering without editing the child.

### Edge-case taxonomy

| Criteria | Inverse and boundary cases | Dependency failure | Repetition and concurrency |
| --- | --- | --- | --- |
| LIFE-A1 to LIFE-A5, LIFE-A23 | Empty entries, comma-separated citations, mixed fields, duplicate and generated IDs, description headings | Missing or unreadable spec | Equal input renders equally; later edits are new input |
| LIFE-A6 to LIFE-A10 | Empty proposal list, rejected-only round, malformed marker, unchanged content after rename | Unreadable record, document, or markers | Same attestation is idempotent; content amendments invalidate by the state each operation reads |
| LIFE-A11 to LIFE-A15 | Attested and unattested nouns, trivial leaves, structural roles, already-in-progress claim | Rendering or marker lookup fails | In-progress claim stays a no-op; later boundaries recheck current state |
| LIFE-A16 to LIFE-A17 | Empty input, matching old input after amendment, no-item target | Facade cannot return a rendering | Amendment between judgment and posting refuses the post |
| LIFE-A18 to LIFE-A20 | Valid, invalid, absent, ignored and untracked records | Checker or enumeration unavailable | Repeated checks over the same tree have equal results; checks write nothing |
| LIFE-A21 | Shipping version, earlier version and prerelease, later version | Missing or malformed version response | Version checks are reads and change no item state |
| LIFE-A22 | Current files, stale rendering, open record | Attack or checker fails before attestation | Unchanged current files and marker are reused; competing changes require a fresh state check |

## Ordered slice list

- **S1: Render and references** (LIFE-A1, LIFE-A2, LIFE-A3, LIFE-A4, LIFE-A5,
  LIFE-A23). Specify and implement the facade renderer, spec-child citations,
  and criteria-section parsing in the existing consumers.
- **S2: Attestation and invalidation** (LIFE-A6, LIFE-A7, LIFE-A8, LIFE-A9,
  LIFE-A10). Specify and implement the facade's content binding after S1.
- **S3: Attack workflow and compatibility** (LIFE-A21, LIFE-A22). Specify the
  version-check interface and tracker-item path after S2. Introduce the tracked
  directory and its doc-lint exemption together. Later consumers reuse the check.
- **S4: Claim and delivery** (LIFE-A11, LIFE-A12, LIFE-A13, LIFE-A14, LIFE-A15).
  Enable the facade transitions after the attack path is available.
- **S5: Repository record gate** (LIFE-A18, LIFE-A19, LIFE-A20). Add the CI gate
  and required-record migration after S3. It can land independently of S4.
- **S6: Review consumers** (LIFE-A16, LIFE-A17). Specify and implement emission
  and posting against the rendered criteria and attestation after S3. Include
  the before-use amendment instruction in the briefing and review paths.

## Continuations

These entries name the component scopes. Use `work promote` on each resulting
feature before implementation to create its design child and blocked
implementation placeholder. Each child spec supplies its implementation
manifest and the dependencies above. Delivering that design does not discharge
the parent implementation criteria or change their open evidence rows.

- feat: AC lifecycle rendering and references — AC: LIFE-A1, LIFE-A2, LIFE-A3,
  LIFE-A4, LIFE-A5, LIFE-A23
- feat: AC lifecycle attestation and invalidation — AC: LIFE-A6, LIFE-A7,
  LIFE-A8, LIFE-A9, LIFE-A10
- feat: AC lifecycle attack workflow and compatibility — AC: LIFE-A21, LIFE-A22
- feat: AC lifecycle claim and delivery gates — AC: LIFE-A11, LIFE-A12,
  LIFE-A13, LIFE-A14, LIFE-A15
- feat: AC lifecycle repository record gate — AC: LIFE-A18, LIFE-A19, LIFE-A20
- feat: AC lifecycle review consumers — AC: LIFE-A16, LIFE-A17

## Out of scope

Criterion quality, a new tracker backend field, automatic installation,
cross-system transactions, cryptographic proof of review, PR-to-item lookup,
semantic or delta-scoped invalidation, and backfilling every open tracker item
are outside this design. The gate over present records does not prove that
every document in the repository has an attack record.

## Evidence

All criteria describe future implementation. No prior attack record attests
to this document or discharges these criteria. The ledger retains `observed:`
for manual observations and supporting evidence. For new work, the quality
contract requires a test or mechanically checkable probe for blocking
completion. Ledger validity and a closed attack record do not establish that
the implementation meets its criteria.

- LIFE-A1 | open
- LIFE-A2 | open
- LIFE-A3 | open
- LIFE-A4 | open
- LIFE-A5 | open
- LIFE-A6 | open
- LIFE-A7 | open
- LIFE-A8 | open
- LIFE-A9 | open
- LIFE-A10 | open
- LIFE-A11 | open
- LIFE-A12 | open
- LIFE-A13 | open
- LIFE-A14 | open
- LIFE-A15 | open
- LIFE-A16 | open
- LIFE-A17 | open
- LIFE-A18 | open
- LIFE-A19 | open
- LIFE-A20 | open
- LIFE-A21 | open
- LIFE-A22 | open
- LIFE-A23 | open
