---
name: ac-attack
description: Attack a document's acceptance criteria with a panel of adversarial lenses, then check that the resulting record closes the round. Use when criteria have been drafted or revised and work is about to be claimed against them.
admission:
  prevents: Criteria that read complete and are not, because the failure modes nobody named stay unnamed until the code exists — and by then a review can only audit coverage of the cases the criteria already list, so the missing case ships.
  cost: A document's criteria cannot go to implementation until an attacker has run per lens over the whole document and every proposal they return carries a written disposition committed beside it.
  remove_when: Attack rounds stop producing accepted proposals across a run of documents, or the criteria-drafting step starts producing criteria that survive an attack unchanged.
---

Criteria that read complete rarely are. This skill attacks them: a panel of adversarial lenses
reads the document, each names behaviours its criteria let through, and every proposal that comes
back is either adjudicated into the criteria or rejected on the record.

The attack runs before the work starts, and that ordering is the point. Once code exists, a review
can check whether the tests cover the failure cases the criteria name — it cannot invent the cases
nobody thought of. This is where those get invented, while adding one is still an edit to a
document.

## Attack lenses

| Lens | What it attacks |
| --- | --- |
| `criteria-holes` | Behaviours that satisfy every stated criterion and are still wrong. |
| `edge-cases` | The taxonomy walk — inverse, empty and boundary, dependency failure, repeated and concurrent invocation, idempotency — naming the cases no criterion tests. |
| `absent-requirements` | Obligations the document takes on that no criterion covers. |

Mandates, model tiers and transports are data in `lenses.json`. One attacker runs per lens, alone,
exhaustive within its lens and silent outside it: a single attacker asked for everything satisfices
and returns two holes where a panel returns seven. The panel mixes tiers, and at least one lens
runs on another vendor's model, because blind spots correlate inside a vendor.

## Emitting the prompts

The attacked artifact is the whole document, never an extracted list of criteria. Criteria mean
what the document's definitions and scope say they mean; an attacker handed the bare list has
nothing to judge them against and returns a vacuous empty round. From this directory:

```bash
uv run emit_prompts.py --spec path/to/document.md --out-dir /tmp/attack
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the document, the revision
attacked, and each lens with its tier and transport. Stdout is `{"emitted": true, "prompts": […]}`.
A missing, unreadable, or empty document refuses instead: `{"emitted": false, "errors": [{"code":
"no-spec", "message": …}]}`, exit 2.

A revision names content, not history: `sha256:` followed by the digest of the document's bytes, or
the equivalent 40-hex object id, so any reader can recompute it from the document in front of them.

## What a prompt contains

Fixed instructions first — the lens's mandate, the requirement to report every hole of that lens
findable this round (a withheld proposal is a defect in the attack), the requirement to report
explicitly when it finds nothing, and the exact-JSON output contract. The document follows inside a
marked section the instructions declare to be data, not instructions. No other lens's mandate
appears, and no house rulebook text does either.

## Proposals

```json
{"lens": "edge-cases", "target_ac": "A3",
 "hole": "what the criteria let through",
 "proposed_ac": "the new criterion, stated as an observable claim",
 "red_test_sketch": {"given": "input or starting state", "when": "the action",
                     "expect": "the observable outcome"}}
```

`target_ac` is the criterion attacked, or `"none"` when nothing covers the ground. The test sketch
is the line between a testable claim and a concern: a starting state, an action, and an observable
outcome, all three non-blank. A concern cannot name them. An item that leaves one blank is
malformed and is dropped, not adjudicated.

## The attack record

Committed beside the attacked document as `<document-basename>-ac-attack.json`. Every field is
required; the shape is fixed by `attack-record.schema.json`.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "proposals"\|"empty"}`, one per lens that reported. A lens that errored or returned unreadable output has no entry and the round is unfinished — coverage is read off the record, never inferred from an empty proposal list. |
| `proposals` | The union of the reports, each carrying its producing lens. Position is the stable index. |
| `dispositions` | `{"index", "disposition": "accepted"\|"rejected", "rationale", "revision"?, "covering_ac"?}`. |

- Every proposal index carries exactly one disposition.
- **Accepted** names the `revision` of the document that now carries the proposal — necessarily a
  different one, since accepting a proposal and changing nothing leaves it unadjudicated — and the
  `covering_ac` in that revision which carries it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result, not a degenerate one: every lens reporting empty closes the round.

The revisions a record accounts for are the one attacked plus every revision an acceptance names.
The record stays current while the document's content hashes to one of them — which is why the
edits an acceptance drives never invalidate the round that drove them, while an unrelated later
edit does, having faced no attacker.

## Checking the round

```bash
uv run check_record.py path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is `{"clean": …, "complete": …, "errors": [{"code", "index"?, "message"}]}` with keys and
errors sorted. `complete` says the round is closed: every lens reported, every proposal
adjudicated, every acceptance carried into a named revision, and the record current against the
document on disk. `clean` adds that nothing was proposed. Exit 0 complete, 1 not, 2 when the record
cannot be read or does not fit the schema.

| Code | Condition |
| --- | --- |
| `unreadable` / `invalid-json` / `schema` | The record is missing, undecodable, not JSON, or not shaped like a record. |
| `spec-unreadable` | The attacked document is not where the record says. `--spec` points at it. |
| `lens-missing` / `duplicate-lens` / `unknown-lens` | The lens reports do not match the declared set one for one. |
| `unadjudicated-proposal` | A proposal has no disposition. |
| `duplicate-disposition` / `unknown-proposal-index` | A disposition names an index twice, or names one that does not exist. |
| `unincorporated-acceptance` | An acceptance names no incorporating revision and criterion, or names the revision it attacked. |
| `missing-rationale` | A rejection states no reason. |
| `stale-revision` | The document has changed into a revision no acceptance accounts for. |
| `ordering-violation` | The round is unfinished and implementation was declared started. |

`--implementation-started` is how the invoker declares what it observed: the work item that changes
the system this document describes has been claimed. Writing or revising the document is not
implementation — the boundary is the first work item that changes the system it describes. The
checker reads only the record, the document, and that declaration; it consults no tracker, writes
nothing, and gives the same answer every time it is asked.
