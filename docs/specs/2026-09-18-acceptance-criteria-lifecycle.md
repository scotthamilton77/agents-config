# Acceptance-criteria lifecycle

**Date:** 2026-09-18
**Status:** Draft. Its criteria attack record sits beside it as
`2026-09-18-acceptance-criteria-lifecycle-ac-attack.json`.
**Work item:** `agents-config-9k9.425` (the lifecycle-spec split).
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions
D3, D4, D7, D8 and D11.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`.
**Terminology:** `CONTEXT.md`; "spec" here means a spec document.

## Problem statement

Criteria can reach implementation through a spec, a work item, or an
amendment made during review. Independent copies in the spec, tracker, and
review input can disagree. A completed attack on one version says nothing
about criteria changed afterward.

The lifecycle must let an implementer obtain the authoritative contract and
let a reviewer establish which version was judged. It must also prevent
ordinary workflow transitions from silently using missing or stale evidence.

## Solution and scope

A work item's acceptance field selects its contract. Consumers render that
selection through the facade instead of retyping it. An attestation ties the
item to the content revision covered by a closed attack record. Claim, review,
posting, and delivery check the relevant current state.

This document owns criterion authority, reference resolution, attack records,
attestation, amendment, and enforcement. The quality contract owns criterion
sufficiency and evidence of success. The lifecycle checks references and
evidence state; it does not judge criterion meaning or completeness.

## User stories

1. As an implementer, I want one criteria rendering for my work item and a clear
   refusal when the required attack has not closed.
2. As a spec author, I want work items implementing my spec's slices to cite
   their assigned criteria without creating text copies that drift.
3. As a work item author, I want criteria stated without a spec to use the same
   attack process and evidence rules.
4. As a reviewer, I want amendments to invalidate evidence for the old
   contract before another round uses the new one.
5. As a reader of a verdict artifact, I want to see exactly the criteria judged,
   with freshness checked when the verdict is posted.

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
An item names its spec through a named-spec marker in its notes. Facade verbs
write that marker, and `work acceptance set --spec` is one of them. When an
item's notes hold several such markers, the last one names its spec. The marker
lives in a note because the acceptance field would make the item tracker-born
under LIFE-D2, the description is not the attacked document under LIFE-D4, and
this design adds no tracker field. The facade component spec owns the marker's
encoding. No note other than a named-spec marker affects the rendering, and
neither do titles or other item metadata.

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
  change does not change the result. Refuse a named spec whose path is
  absolute or leads outside the repository root, naming the path and cause.

The workcli and spec-lint grammars remain marked counterparts with a common
round-trip fixture. This is a compatibility obligation across repositories.
Component specs define the exact generated-ID spelling and refusal payloads
within these observable constraints.

### LIFE-D2: One document is attacked for each item

An item is **spec-born** when every nonblank acceptance line consists solely
of citations into its named spec under LIFE-D1. Its attackable document is
that whole spec. Selection and work-item coverage are judged by the quality review
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
undispositioned objection, names inconsistent accepted revisions, or does not
close at the document's current digest. A tracker-born file must also equal
a fresh rendering. With no accepted objections, the closing revision is the
attacked revision. Repeating or concurrently requesting the same attestation
leaves one marker.

The attack path calls this verb only after the existing checker succeeds.
The facade checks binding and closure; it does not duplicate the checker's
semantic or lens judgments. At a consuming boundary, the facade computes the
current document revision. For tracker-born items it computes a fresh
rendering rather than trusting the committed snapshot. A malformed marker
does not count; an unreadable marker source causes a named refusal.

This attestation records an account of a review. It cannot prove that a model
performed the review or that accepted objections were implemented honestly.
Hand-authored marker notes and deletion of records after attestation remain
outside this trust boundary. The branch diff and review account expose them;
this design does not introduce tamper-proof evidence.

### LIFE-D4: Amendments invalidate evidence before reuse

Changing tracker-born acceptance text or description changes the rendering
and invalidates its attestation when the bytes change. Changing a spec's bytes
invalidates the spec's record and every spec-born item's attestation against
that revision. Changing a spec-born item's description does not invalidate
its attack because that description is not the attacked document. A
tracker-born item's attestation depends on its spec only through its
rendering. A spec change that leaves that rendering unchanged leaves the
attestation current.

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
defines leaf behavior. A leaf is any item the facade does not declare a
container. Having children does not make an item a container, and the facade
already refuses to claim one. All rendering refusals name their cause.

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

Structural children of a spec container have no noun. A design child remains
outside claim and delivery gates; its spec is checked by the record gate when
its record is present. An implementation placeholder remains unclaimable and
is retired when the spec manifest expands. PR delivery refuses it as well.
Delivering its design child with `--spec` still reconciles it. An item with
neither a recognized noun nor a recognized structural role is refused by type.

### LIFE-D6: Review and posting use the rendered contract

The review-panel criteria input must equal a fresh rendering when its claim
names an item. Emission records those judged bytes with the round. The verdict
poster accepts criteria only when they match both that recorded input and a
fresh rendering at posting time. Posting compares content, not amendment
history. An amendment that changes the criteria still needs a new review of
the amended criteria after it is re-attacked; freshness alone cannot validate
an old verdict. Criteria restored to exactly the judged bytes, with their
attack record closed at those bytes, let the old verdict post under the same
checks as criteria never amended. Posting refuses a round that has no
recorded judged input, and a new review round is the remedy.

Both consumers refuse an empty rendering, a missing required attestation, or
a failure to obtain the current rendering. Neither falls back to an unchecked
file. The poster extracts criteria only from the acceptance-criteria section.
A target with no work item keeps the existing supplied-file path. The
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

Component child specs define wire formats and fixtures before scaffolding.
They retain these public contracts and may not weaken parent invariants or
leave significant product decisions to implementation.

## Acceptance criteria

- **LIFE-A1** A caller rendering cited criteria receives each nonempty cited
  entry complete, in field order, independent of the working directory.
  Comma-separated IDs, the same IDs on separate lines, and IDs with surrounding
  whitespace produce identical criteria output. These results hold for a work
  item created before the renderer ships once one `work acceptance set --spec`
  call names its spec, with no other change to the item.
- **LIFE-A2** A caller rendering text or mixed text and citations receives
  stable, unique criterion IDs in the existing consumer grammar, and every ID
  that a text line states explicitly survives unchanged.
- **LIFE-A3** A rendering with an invalid reference or ID collision is refused
  with the offending ID or spec path and cause.
- **LIFE-A4** A rendering keeps the whole description, including any
  criterion-shaped text in it, under its own heading and out of the
  acceptance-criteria section.
- **LIFE-A5** Repeated renders with unchanged description, criteria, and named
  spec are byte-equal despite changes to title, other metadata, or any note
  other than a named-spec marker. When an item's notes hold several named-spec
  markers, the last one names its spec.
- **LIFE-A6** A valid closed record for the current document produces one
  attestation for its content revision, including after repeated or concurrent
  requests to attest that same record.
- **LIFE-A7** Attesting a record that violates the binding or closure conditions
  in LIFE-D3 is refused without writing a marker.
- **LIFE-A8** A tracker-born amendment that changes its rendering makes its
  prior attestation unusable, even while the committed rendering is stale.
- **LIFE-A9** Changing an attacked spec's content leaves citing spec-born work
  items unattested until the new revision is attacked and each item attests to it.
  Changing only a spec-born item's description leaves its attestation current.
- **LIFE-A10** Renaming an attacked document without changing its bytes
  preserves each citing item's attestation once its references and the
  record's filename binding are updated, without another attack round.
- **LIFE-A11** Claiming an open noun-bearing leaf with empty or unresolvable
  criteria refuses the transition. Claiming a leaf already in progress remains
  a no-op, with no refusal.
- **LIFE-A12** Every verb that moves an open leaf to in progress applies exactly
  the noun and triviality attestation rules in LIFE-D5.
- **LIFE-A13** PR delivery refuses a noun-bearing leaf with empty or
  unresolvable criteria, including a trivial or already-in-progress leaf.
- **LIFE-A14** PR delivery refuses every nontrivial noun-bearing leaf without
  current attestation and accepts that requirement after a valid attestation.
- **LIFE-A15** A design child passes claim and delivery without the criteria
  and attestation gates.
- **LIFE-A16** Review emission for an item refuses exactly when it cannot
  obtain a fresh rendering, when its input differs from that rendering, or
  when LIFE-D5's review row does not admit that rendering, and the refusal
  names its cause. A refused facade version check is one way of failing to
  obtain the rendering. Otherwise the input becomes the round's recorded
  criteria.
- **LIFE-A17** For a verdict naming a work item whose round has recorded
  judged input, posting refuses exactly when it cannot obtain a fresh
  rendering, when the verdict's criteria differ from that input or from that
  rendering, or when LIFE-D5's posting row does not admit that rendering, and
  the refusal names its cause. A refused facade version check is one way of
  failing to obtain the rendering. The comparison reads content, not amendment
  history.
  Criteria restored to exactly the judged bytes after an amendment, with their
  attack record closed at those bytes, are therefore not refused for having
  been amended.
- **LIFE-A18** The CI gate reports every invalid tracked record and its cause
  in one run, including the record and document paths for a missing document.
- **LIFE-A19** The CI gate refuses to report success when its checker is
  unavailable or its tracked-record inventory cannot be enumerated.
- **LIFE-A20** The CI gate ignores records outside the current tracked checkout
  and succeeds when the resulting inventory is empty and its checker is
  available.
- **LIFE-A21** A consumer requiring a new facade verb refuses an insufficient
  or unestablished installed version before calling that verb and names the
  required version or version-read failure. A sufficient installed version
  proceeds to call the verb. The version check itself changes no item state.
- **LIFE-A22** A tracker-born attack workflow renders the item to
  `.work/attacks/<item-id>.md`, attacks it, and commits that rendering with its
  record at `.work/attacks/<item-id>-ac-attack.json` only after the checker
  reports the record complete. It then attests, so the item's next gated
  transition finds a current attestation.
- **LIFE-A23** A work item created by spec delivery stores its assigned IDs as
  citations, not as copied text.
- **LIFE-A24** Claim and delivery refuse an otherwise eligible noun-bearing
  leaf only for empty or unresolvable criteria or for a required attestation
  that is not current. These are the acceptance conditions LIFE-D5 lists. The
  check claims and then delivers a leaf of each noun in LIFE-D5's table whose
  criteria are nonempty, resolvable and currently attested, and every step
  succeeds. Its fixture varies the wording across the placeholder words TODO
  and TBD, a one-word criterion, a long multi-sentence criterion, non-ASCII
  text, Markdown markup, and criterion-shaped description text.
- **LIFE-A25** An implementation placeholder is refused at claim.
- **LIFE-A26** An item with neither a recognized noun nor a recognized
  structural role is refused by type at claim and at delivery.
- **LIFE-A27** Editing a cited spec entry changes the rendering of every item
  citing it, with no edit to those items.
- **LIFE-A28** The workcli renderer and spec-lint parse the shared round-trip
  fixture, which exercises every resolution rule in LIFE-D1, to the same
  entries.
- **LIFE-A29** An item with any full-text acceptance line is attacked as its
  rendering, even when other lines cite its spec. An item whose every nonblank
  line is a citation is attacked as its whole spec.
- **LIFE-A30** A fresh checkout holds the `.work/attacks/` directory, and
  doc-lint does not treat the files in it as authored prose.
- **LIFE-A31** A consuming boundary ignores a malformed attestation marker, and
  refuses by name when the marker source cannot be read.
- **LIFE-A32** Dispatch briefs cite the quality standard and the rule that
  amended criteria are attacked again before use.
- **LIFE-A33** Claim and delivery refusals name their cause: `work acceptance
  set` for empty criteria, the failing ID or path for unresolvable criteria,
  and the attack step for a missing attestation.
- **LIFE-A34** A second invocation of the tracker-born attack workflow, with
  unchanged files and current evidence, reuses them without a new attack round.
- **LIFE-A35** Review emission for a target naming no work item keeps the
  existing supplied-file path.
- **LIFE-A36** Two runs of the CI gate over an unchanged checkout report the same
  result. That result is the gate's exit status together with the set of
  invalid records it reports, each with its cause. The order in which the gate
  lists those records is not part of the result.
- **LIFE-A37** An attack or checker failure in the tracker-born workflow leaves
  no committed rendering or record and no attestation, and the next invocation
  runs the round again.
- **LIFE-A38** A verdict posted for a work item shows its reader every
  criterion the round recorded as judged, with each ID and text as recorded,
  including criteria that no finding cites.
- **LIFE-A39** Existing criteria consumers given a rendering recover only the
  entries in its acceptance-criteria section, even when its description
  contains criterion-shaped text.
- **LIFE-A40** The instructions that follow a criteria-indicting review halt
  cite the quality standard and the rule that amended criteria are attacked
  again before use.
- **LIFE-A41** A run of the CI gate, passing or failing, leaves the checkout's
  tracked, untracked and ignored files unchanged.
- **LIFE-A42** A rendering that cites a spec entry holding no text beyond its
  ID emits no criterion for that entry.
- **LIFE-A43** Posting a verdict that names a work item refuses when the
  verdict's round has no recorded judged input, and the refusal names that
  missing input as its cause.
- **LIFE-A44** An invocation of the tracker-born attack workflow that finds its
  committed rendering equal to a fresh rendering, and its committed record
  reported complete by the checker and closed at that rendering, but no
  current attestation, attests from that record without a new attack round.
  The item's next gated transition then finds a current attestation.
- **LIFE-A45** A rendering whose named spec path is absolute, or is relative
  and leads outside the repository root, is refused with that path and cause.
  The refusal holds even when a readable, parseable spec exists at that
  location.
- **LIFE-A46** When the only change is an edit to a tracker-born item's named
  spec that alters none of the entries the item cites, the item's fresh
  rendering stays byte-equal to its attested rendering. Its next consuming
  boundary therefore finds its attestation current, with no new attack round.
- **LIFE-A47** PR delivery refuses an implementation placeholder, and the
  refusal names the placeholder role as its cause.
- **LIFE-A48** Delivering a design child with `work deliver --spec` reconciles
  its sibling implementation placeholder against the manifest of the spec that
  `--spec` names. The reconciled item no longer holds the placeholder role.
  The placeholder refusals at claim and at PR delivery do not block this
  reconciliation.
- **LIFE-A49** A review emission refused for an item's empty criteria names
  `work acceptance set` as the remedy. One refused for a missing required
  attestation names the attack step as the remedy.
- **LIFE-A50** A verdict post refused for an item's empty criteria names
  `work acceptance set` as the remedy. One refused for a missing required
  attestation names the attack step as the remedy.

### What-if questions

| Criteria | Inverse and boundary cases | Dependency failure | Repetition and concurrency |
| --- | --- | --- | --- |
| LIFE-A1 to LIFE-A5, LIFE-A23, LIFE-A27, LIFE-A28, LIFE-A39, LIFE-A42, LIFE-A45 | Empty entries, comma-separated citations, mixed fields, duplicate and generated IDs, description headings, absolute or out-of-repository spec paths | Missing or unreadable spec | Equal input renders equally; later edits are new input |
| LIFE-A6 to LIFE-A10, LIFE-A31, LIFE-A46 | Empty objection list, rejected-only round, malformed marker, unchanged content after rename, spec edits outside cited entries | Unreadable record, document, or markers | Same attestation is idempotent; content amendments invalidate by the state each operation reads |
| LIFE-A11 to LIFE-A15, LIFE-A24 to LIFE-A26, LIFE-A33, LIFE-A47, LIFE-A48 | Attested and unattested nouns, trivial leaves, structural roles, already-in-progress claim, placeholder delivery and reconciliation | Rendering or marker lookup fails | In-progress claim stays a no-op; later boundaries recheck current state |
| LIFE-A16, LIFE-A17, LIFE-A32, LIFE-A35, LIFE-A38, LIFE-A40, LIFE-A43, LIFE-A49, LIFE-A50 | Empty input, old input restored after amendment, round with no recorded input, criteria no finding cites, no-item target | Facade cannot return a rendering, or its version check refuses | A criteria change between judgment and posting refuses the post; restored judged bytes post |
| LIFE-A18 to LIFE-A20, LIFE-A36, LIFE-A41 | Valid, invalid, absent, ignored and untracked records | Checker or enumeration unavailable | Repeated checks over the same tree have equal results; checks write nothing |
| LIFE-A21 | Shipping version, earlier version and prerelease, later version | Missing or malformed version response | Version checks are reads and change no item state |
| LIFE-A22, LIFE-A29, LIFE-A30, LIFE-A34, LIFE-A37, LIFE-A44 | Current files, stale rendering, open record, committed files without attestation | Attack or checker fails before commit; attestation fails after commit | Unchanged current files and marker are reused; competing changes require a fresh state check |

## Ordered slice list

- **S1: Render and references** (LIFE-A1, LIFE-A2, LIFE-A3, LIFE-A4, LIFE-A5,
  LIFE-A23, LIFE-A27, LIFE-A28, LIFE-A39, LIFE-A42, LIFE-A45). Specify and
  implement the facade renderer, work-item citations, and criteria-section
  parsing in the existing consumers.
- **S2: Attestation and invalidation** (LIFE-A6, LIFE-A7, LIFE-A8, LIFE-A9,
  LIFE-A10, LIFE-A31, LIFE-A46). Specify and implement the facade's content
  binding after S1.
- **S3: Attack workflow and compatibility** (LIFE-A21, LIFE-A22, LIFE-A29,
  LIFE-A30, LIFE-A34, LIFE-A37, LIFE-A44). Specify the
  version-check interface and tracker-born path after S2. Introduce the tracked
  directory and its doc-lint exemption together. Later consumers reuse the check.
- **S4: Claim and delivery** (LIFE-A11, LIFE-A12, LIFE-A13, LIFE-A14, LIFE-A15,
  LIFE-A24, LIFE-A25, LIFE-A26, LIFE-A33, LIFE-A47, LIFE-A48).
  Enable the facade transitions after the attack path is available.
- **S5: Repository record gate** (LIFE-A18, LIFE-A19, LIFE-A20, LIFE-A36,
  LIFE-A41). Add the CI gate and required-record migration after S3. It can
  land independently of S4.
- **S6: Review consumers** (LIFE-A16, LIFE-A17, LIFE-A32, LIFE-A35, LIFE-A38,
  LIFE-A40, LIFE-A43, LIFE-A49, LIFE-A50). Specify and implement emission and
  posting against the rendered criteria and attestation after S3. Include the
  before-use amendment instruction in the briefing and review paths.

## Continuations

Use `work promote` on each resulting feature before implementation. Its spec
container holds a design child and blocked implementation placeholder. The
child spec supplies the implementation manifest and dependencies above. It
names a verification child for any parent outcome spanning slices, as the
quality contract requires. Delivering the design does not discharge parent
criteria or change their open evidence rows.

- feat: AC lifecycle rendering and references — AC: LIFE-A1, LIFE-A2, LIFE-A3,
  LIFE-A4, LIFE-A5, LIFE-A23, LIFE-A27, LIFE-A28, LIFE-A39, LIFE-A42,
  LIFE-A45
- feat: AC lifecycle attestation and invalidation — AC: LIFE-A6, LIFE-A7,
  LIFE-A8, LIFE-A9, LIFE-A10, LIFE-A31, LIFE-A46
- feat: AC lifecycle attack workflow and compatibility — AC: LIFE-A21, LIFE-A22,
  LIFE-A29, LIFE-A30, LIFE-A34, LIFE-A37, LIFE-A44
- feat: AC lifecycle claim and delivery gates — AC: LIFE-A11, LIFE-A12,
  LIFE-A13, LIFE-A14, LIFE-A15, LIFE-A24, LIFE-A25, LIFE-A26, LIFE-A33,
  LIFE-A47, LIFE-A48
- feat: AC lifecycle repository record gate — AC: LIFE-A18, LIFE-A19, LIFE-A20,
  LIFE-A36, LIFE-A41
- feat: AC lifecycle review consumers — AC: LIFE-A16, LIFE-A17, LIFE-A32,
  LIFE-A35, LIFE-A38, LIFE-A40, LIFE-A43, LIFE-A49, LIFE-A50

## Out of scope

Criterion quality, a new tracker backend field, automatic installation,
cross-system transactions, cryptographic proof of review, PR-to-item lookup,
semantic or delta-scoped invalidation, and backfilling every open work item
are outside this design. The gate over present records does not prove that
every document in the repository has an attack record.
