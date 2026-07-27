# Proposals and the attack record

What an attacker returns, and what the round is written down as. The machine-readable shape is
`attack-record.schema.json`; this is what the fields mean and why they are held to it.

## A proposal

```json
{"lens": "edge-cases", "target_ac": "A3",
 "hole": "what the criteria let through",
 "proposed_ac": "the new criterion, stated as an observable claim",
 "red_test_sketch": {"given": "input or starting state", "when": "the action",
                     "expect": "the observable outcome"}}
```

`target_ac` is the criterion attacked, or `"none"` when nothing covers the ground.

The test sketch is the line between a testable claim and a concern: a starting state, an action,
an observable outcome, all non-blank — a concern cannot name them. An item leaving one blank is
malformed, and is dropped rather than adjudicated.

A lens whose every item is dropped returned nothing usable, which is not nothing found: it gets no
entry, and the round closes by running that lens again rather than by recording it empty. Recording
it empty would claim it looked and found nothing, which is a different result and one the gate
reads as coverage obtained.

Unioning the reports adds an `id` to each proposal, distinct within the round — an attacker sees
its own lens and not the round, so it cannot pick one that is distinct across the union. That id is
what a disposition names. Dropping a malformed proposal is what makes it necessary: positions
renumber, and a disposition keyed on position would then adjudicate a proposal it was never written
against, crediting one hole with another's criterion while the round still reads closed.

## The record

Committed beside the attacked document, named for it without its extension: `ledger.md` gets
`ledger-ac-attack.json`. Every top-level field is required.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document as a bare basename. The record is committed beside it and the checker searches only the record's own directory, so a path leading out of it names a document no attacker in the round read, and an absolute one resolves only on the machine that wrote it. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "proposals"\|"empty"}`, one per lens that reported. A silent or errored lens has no entry and the round is unfinished — coverage is read off the record, never inferred from silence. |
| `proposals` | The union of the reports, each carrying its producing lens and its `id`. Reports are held against them: a lens reporting empty contributes none, one reporting proposals at least one. |
| `dispositions` | `{"id", "disposition": "accepted"\|"rejected", "rationale"?, "revision"?, "covering_ac"?}`. |

- Every proposal id carries exactly one disposition.
- **Accepted** names the `revision` now carrying the proposal and the `covering_ac` in it. That
  revision is necessarily other than the one attacked — accepting a proposal and changing nothing
  leaves it unadjudicated — and it is the same revision for every acceptance, since the document
  reached exactly one state once all of them were in it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result: every lens reporting empty closes the round.

A revision names content, not history: `sha256:` plus the digest of the document's bytes, or the
equivalent 40-hex object id, recomputable from the document in front of you. Write it with no
surrounding whitespace — `git hash-object` ends its output with a newline, and a revision that
keeps it reads as a different revision, so an acceptance that changed nothing would pass as an
incorporation. One record picks one notation and writes every revision in it: revisions compare as
strings, so one content written both ways would read as two.
