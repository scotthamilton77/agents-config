---
name: ac-attack
description: Attack a document's acceptance criteria with a panel of adversarial lenses, then check that the resulting record closes the round. Use when criteria have been drafted or revised and work is about to be claimed against them.
admission:
  prevents: Criteria that read complete and are not, because the failure modes nobody named stay unnamed until the code exists — and by then a review can only audit coverage of the cases the criteria already list, so the missing case ships.
  cost: A document's criteria cannot go to implementation until an attacker has run per lens over the whole document and every proposal they return carries a written disposition committed beside it.
  remove_when: Attack rounds stop producing accepted proposals across a run of documents, or the criteria-drafting step starts producing criteria that survive an attack unchanged.
---

Criteria that read complete rarely are. This skill attacks them: a panel of adversarial lenses
reads the document, each naming behaviours its criteria let through, and every proposal comes back
adjudicated into the criteria or rejected on the record.

Running before the work starts is the point: once code exists, a review can check that the tests
cover the failure cases the criteria name but cannot invent the ones nobody thought of. Those get
invented here, while adding one is still an edit to a document.

## Attack lenses

| Lens | What it attacks |
| --- | --- |
| `criteria-holes` | Behaviours that satisfy every stated criterion and are still wrong. |
| `edge-cases` | The taxonomy walk — inverse, empty and boundary, dependency failure, repeated and concurrent invocation, idempotency — naming cases no criterion tests. |
| `absent-requirements` | Obligations the document takes on that no criterion covers. |

Mandates are data in `lenses.json`, each lens's `tier` naming the model capability it needs and
`transport` the route its prompt goes out on: an `openrouter` lens through the
`openrouter-claude-subagent` skill, a `codex` lens through the codex command-line tool. When one
transport is down, run its lenses over the other and say so when reporting the round — the panel
has lost its vendor diversity, and blind spots correlate within a vendor. One attacker runs per
lens, alone, exhaustive within it and silent outside: asked for everything, one attacker satisfices,
returning two holes where a panel returns seven.

## Emitting the prompts

The attacked artifact is the whole document, never an extracted list of criteria: criteria mean
what the document's definitions and scope say they mean, and an attacker handed the bare list has
nothing to judge them against, returning a vacuous empty round. From this directory:

```bash
uv run emit_prompts.py --spec path/to/document.md --out-dir /tmp/attack
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the document, the revision
attacked, and each lens with its tier and transport. A prompt carries that lens's mandate, the
requirement to report every hole it can find and to say so explicitly when it finds none, the
exact-JSON output contract, and then the whole document in a section the instructions declare to be
data. No other lens's mandate appears, and no house rulebook text.

Stdout is `{"emitted": true, "prompts": […]}`; a refusal is
`{"emitted": false, "errors": [{"code", "message"}]}`, exit 2, every code in `errors.md`. `--spec`
and `--out-dir` are both required — the output names are fixed, so a round with nowhere named would
truncate whatever wears them in the directory it ran from. That one directory is created
owner-only, as is every file in it, since a prompt carries the whole document.

A revision names content, not history: `sha256:` plus the digest of the document's bytes, or the
equivalent 40-hex object id, recomputable from the document in front of you. One record picks one
notation and writes every revision in it: revisions compare as strings, so the same content in both
notations would read as two revisions.

## Proposals

```json
{"lens": "edge-cases", "target_ac": "A3",
 "hole": "what the criteria let through",
 "proposed_ac": "the new criterion, stated as an observable claim",
 "red_test_sketch": {"given": "input or starting state", "when": "the action",
                     "expect": "the observable outcome"}}
```

`target_ac` is the criterion attacked, or `"none"` when nothing covers the ground. The test sketch
is the line between a testable claim and a concern: a starting state, an action, an observable
outcome, all non-blank — a concern cannot name them. An item leaving one blank is malformed, and is
dropped rather than adjudicated.

Unioning the reports adds an `id` to each proposal, distinct within the round — an attacker sees its
own lens and not the round, so it cannot pick one. That id is what a disposition names: dropping a
malformed proposal renumbers positions, and a disposition keyed on position would then adjudicate a
proposal it was never written against.

## The attack record

Committed beside the attacked document as `<document-basename>-ac-attack.json`. Every top-level
field below is required; the shape, including which disposition fields each verdict needs, is fixed
by `attack-record.schema.json`.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document, named relative to this record — they are committed side by side, so its basename. An absolute path resolves only on the machine that wrote it. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "proposals"\|"empty"}`, one per lens that reported. A silent or errored lens has no entry and the round is unfinished — coverage is read off the record, never inferred from silence. |
| `proposals` | The union of the reports, each carrying its producing lens and its `id`. Reports are held against them: a lens reporting empty contributes none, one reporting proposals at least one. |
| `dispositions` | `{"id", "disposition": "accepted"\|"rejected", "rationale"?, "revision"?, "covering_ac"?}`. |

- Every proposal id carries exactly one disposition.
- **Accepted** names the `revision` now carrying the proposal — necessarily a different one, since
  accepting and changing nothing leaves it unadjudicated — and the `covering_ac` in it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result, not a degenerate one: every lens reporting empty closes the round.

## Checking the round

```bash
uv run check_record.py path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is
`{"clean": …, "complete": …, "errors": [{"code", "id"?, "message"}], "document"?, "revision"?}`,
keys and errors sorted. `complete` says the round is closed: every lens reported, every proposal
adjudicated, every acceptance carried into a named revision, and the document still hashing to the
revision attacked or to one an acceptance names — so the edits an acceptance drives never invalidate
the round that drove them, while an unrelated later edit does, having faced no attacker. `clean`
adds that nothing was proposed. `document` and `revision` name the file the verdict was decided
against and what it hashes to. Exit 0 complete, 1 not, 2 on unusable input. Every code the check
can return, and what each one means, is in `errors.md`.

`--implementation-started` declares what the invoker observed: the first work item that changes the
system this document describes has been claimed. Revising the document is not that. The checker
reads only the record, the document, and that declaration; it consults no tracker, writes nothing,
and answers the same way every time.

The record **attests** that the round happened as written; the checker does not verify that it did.
A revision is a hash and the content it names is not recoverable from it, so an acceptance naming a
revision the document no longer carries cannot be checked against anything, and an author naming
one that never existed still closes the round. What is enforced is that the account is internally
whole and that the document in front of the checker is one the record accounts for. The result
names the file it read, so a round closed against a copy handed to `--spec` is visible as one: read
that pair as part of the verdict, because a `complete` round over the wrong file evidences nothing.
