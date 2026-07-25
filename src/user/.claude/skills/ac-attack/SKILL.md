---
name: ac-attack
description: Attack a document's acceptance criteria with a panel of adversarial lenses, then check that the resulting record closes the round. Use when criteria have been drafted or revised and work is about to be claimed against them.
admission:
  prevents: Criteria that read complete and are not, because the failure modes nobody named stay unnamed until the code exists — and by then a review can only audit coverage of the cases the criteria already list, so the missing case ships.
  cost: A document's criteria cannot go to implementation until an attacker has run per lens over the whole document and every proposal they return carries a written disposition committed beside it.
  remove_when: Attack rounds stop producing accepted proposals across a run of documents, or the criteria-drafting step starts producing criteria that survive an attack unchanged.
---

Criteria that read complete rarely are. This skill attacks them: a panel of adversarial lenses
reads the document, each names behaviours its criteria let through, and every proposal comes back
adjudicated into the criteria or rejected on the record.

The attack runs before the work starts, and that ordering is the point: once code exists, a review
can check that the tests cover the failure cases the criteria name but cannot invent the ones
nobody thought of. Those get invented here, while adding one is still an edit to a document.

## Attack lenses

| Lens | What it attacks |
| --- | --- |
| `criteria-holes` | Behaviours that satisfy every stated criterion and are still wrong. |
| `edge-cases` | The taxonomy walk — inverse, empty and boundary, dependency failure, repeated and concurrent invocation, idempotency — naming the cases no criterion tests. |
| `absent-requirements` | Obligations the document takes on that no criterion covers. |

Mandates are data in `lenses.json`, with each lens's `tier` naming the model capability it needs
and `transport` the route its prompt goes out on: send each emitted `<lens>.md` to a model of that
tier over that route. One attacker runs per lens, alone, exhaustive within its lens and silent
outside it — a single attacker asked for everything satisfices, returning two holes where a panel
returns seven. The panel mixes tiers and reaches another vendor's model, because blind spots
correlate inside a vendor.

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
or empty document refuses as `no-spec`. A document carrying an untrusted-content marker of its own
refuses as `spec-contains-marker`: fencing it would mean rewriting it, and the round would then
attack text its revision does not name.

A revision names content, not history: `sha256:` plus the digest of the document's bytes, or the
equivalent 40-hex object id, recomputable from the document in front of you.

## What a prompt contains

Fixed instructions first — the lens's mandate, the requirement to report every hole of that lens
findable this round (a withheld proposal is a defect in the attack) and to say so explicitly when
it finds none, and the exact-JSON output contract. The document follows inside a marked section the
instructions declare to be data. No other lens's mandate appears, and no house rulebook text does.

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
outcome, all three non-blank. A concern cannot name them; an item that leaves one blank is
malformed and is dropped, not adjudicated.

## The attack record

Committed beside the attacked document as `<document-basename>-ac-attack.json`. Every top-level
field below is required; the shape, including which disposition fields a given verdict needs, is
fixed by `attack-record.schema.json`.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "proposals"\|"empty"}`, one per lens that reported. A silent or errored lens has no entry and the round is unfinished — coverage is read off the record, never inferred from an empty proposal list. |
| `proposals` | The union of the reports, each carrying its producing lens. Position is the stable index. Every report is held against them: a lens reporting empty contributes none, one reporting proposals contributes at least one. |
| `dispositions` | `{"index", "disposition": "accepted"\|"rejected", "rationale"?, "revision"?, "covering_ac"?}`. |

- Every proposal index carries exactly one disposition.
- **Accepted** names the `revision` that now carries the proposal — necessarily a different one,
  since accepting and changing nothing leaves it unadjudicated — and the `covering_ac` in it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result, not a degenerate one: every lens reporting empty closes the round.

A record accounts for the revision attacked plus every revision an acceptance names, and stays
current while the document hashes to any one of them — so the edits an acceptance drives never
invalidate the round that drove them, while an unrelated later edit does, having faced no attacker.

## Checking the round

```bash
uv run check_record.py path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is `{"clean": …, "complete": …, "errors": [{"code", "index"?, "message"}]}` with keys and
errors sorted. `complete` says the round is closed: every lens reported, every proposal
adjudicated, every acceptance carried into a named revision, and the record current against the
document. `clean` adds that nothing was proposed. Exit 0 complete, 1 not, 2 on unusable input.

| Code | Condition |
| --- | --- |
| `no-record` / `unreadable` / `invalid-json` / `schema` / `checker-failure` | No record was named, or it is missing, undecodable, not JSON, not shaped like a record, or the check could not run. |
| `spec-unreadable` | The attacked document is not where the record says. `--spec` points at it. |
| `lens-missing` / `duplicate-lens` / `unknown-lens` | The lens reports do not match the declared set one for one. |
| `unknown-proposal-lens` / `contradicted-empty-report` / `contradicted-proposals-report` | A proposal names a lens outside the declared set, a lens reporting empty has proposals attributed to it, or one reporting proposals contributed none. |
| `unadjudicated-proposal` | A proposal has no disposition. |
| `duplicate-disposition` / `unknown-proposal-index` | A disposition names an index twice, or names one that does not exist. |
| `unincorporated-acceptance` | An acceptance names no incorporating revision and criterion, or names the revision it attacked. |
| `missing-rationale` | A rejection states no reason. |
| `stale-revision` | The document has changed into a revision no acceptance accounts for. |
| `ordering-violation` | The round is unfinished and implementation was declared started. |

`--implementation-started` declares what the invoker observed: the first work item that changes the
system this document describes has been claimed. Writing or revising the document is not that. The
checker reads only the record, the document, and that declaration; it consults no tracker, writes
nothing, and answers the same way every time.
