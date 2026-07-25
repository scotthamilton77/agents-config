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

Mandates are data in `lenses.json`, with each lens's `tier` naming the model capability it needs
and `transport` the route its prompt goes out on: send each emitted `<lens>.md` to a model of that
tier over that route. One attacker runs per lens, alone, exhaustive within it and silent
outside — asked for everything, one attacker satisfices, returning two holes where a panel returns
seven. The panel mixes tiers and reaches another vendor's model: blind spots correlate in a vendor.

## Emitting the prompts

The attacked artifact is the whole document, never an extracted list of criteria: criteria mean
what the document's definitions and scope say they mean, and an attacker handed the bare list has
nothing to judge them against, returning a vacuous empty round. From this directory:

```bash
uv run emit_prompts.py --spec path/to/document.md --out-dir /tmp/attack
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the document, the revision
attacked, and each lens with its tier and transport. Stdout is `{"emitted": true, "prompts": […]}`;
a refusal is `{"emitted": false, "errors": [{"code", "message"}]}`, exit 2. A missing, unreadable,
or empty document refuses as `no-spec`. One carrying an untrusted-content marker refuses as
`spec-contains-marker`: fencing it would rewrite it, and the round would then attack text its
revision does not name.

A prompt carries the whole document, so every file written is owner-only, as is an output directory
the round creates — one already there keeps the permissions its owner gave it. An output name held
by a link or anything but a plain file refuses as `unsafe-output-path` rather than being written
through.

A revision names content, not history: `sha256:` plus the digest of the document's bytes, or the
equivalent 40-hex object id, recomputable from the document in front of you. One record picks one
notation and writes every revision in it: revisions compare as strings, so the same content in both
notations would read as two revisions.

## What a prompt contains

Fixed instructions first — the lens's mandate, the requirement to report every hole of that lens
findable this round (a withheld proposal is a defect in the attack) and to say so explicitly when
it finds none, and the exact-JSON output contract. The document follows in a marked section the
instructions declare to be data. No other lens's mandate appears, and no house rulebook text.

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

## The attack record

Committed beside the attacked document as `<document-basename>-ac-attack.json`. Every top-level
field below is required; the shape, including which disposition fields each verdict needs, is fixed
by `attack-record.schema.json`.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "proposals"\|"empty"}`, one per lens that reported. A silent or errored lens has no entry and the round is unfinished — coverage is read off the record, never inferred from silence. |
| `proposals` | The union of the reports, each carrying its producing lens. Position is the stable index. Reports are held against them: a lens reporting empty contributes none, one reporting proposals at least one. |
| `dispositions` | `{"index", "disposition": "accepted"\|"rejected", "rationale"?, "revision"?, "covering_ac"?}`. |

- Every proposal index carries exactly one disposition.
- **Accepted** names the `revision` now carrying the proposal — necessarily a different one, since
  accepting and changing nothing leaves it unadjudicated — and the `covering_ac` in it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result, not a degenerate one: every lens reporting empty closes the round.

A record accounts for the revision attacked plus every revision an acceptance names, and stays
current while the document hashes to any one of them — so the edits an acceptance drives never
invalidate the round that drove them, while an unrelated later edit does, having faced no attacker.

## Checking the round

```bash
uv run check_record.py path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is `{"clean": …, "complete": …, "errors": [{"code", "index"?, "message"}]}`, keys and errors
sorted. `complete` says the round is closed: every lens reported, every proposal adjudicated, every
acceptance carried into a named revision, and the record current against the document. `clean` adds
that nothing was proposed. Exit 0 complete, 1 not, 2 on unusable input.

| Code | Condition |
| --- | --- |
| `no-record` / `unreadable` / `invalid-json` / `schema` / `checker-failure` | No record named, or it is missing, undecodable, not a record, or the check could not run. |
| `spec-unreadable` | The document is not where the record says. `--spec` points at it. |
| `mixed-revision-notation` | The record writes revisions in both notations, so equal content would compare unequal. |
| `lens-missing` / `duplicate-lens` / `unknown-lens` | The lens reports do not match the declared set one for one. |
| `unknown-proposal-lens` / `contradicted-empty-report` / `contradicted-proposals-report` | A proposal names an undeclared lens; a lens reporting empty has proposals; a lens reporting proposals has none. |
| `unadjudicated-proposal` | A proposal has no disposition. |
| `duplicate-disposition` / `unknown-proposal-index` | A disposition names an index twice, or names one that does not exist. |
| `unincorporated-acceptance` | An acceptance names no incorporating revision and criterion, or names the revision it attacked. |
| `missing-rationale` | A rejection states no reason. |
| `stale-revision` | The document has changed into a revision no acceptance accounts for. |
| `ordering-violation` | The round is unfinished and implementation was declared started. |

`--implementation-started` declares what the invoker observed: the first work item that changes the
system this document describes has been claimed. Revising the document is not that. The checker
reads only the record, the document, and that declaration; it consults no tracker, writes nothing,
and answers the same way every time.
