# Objections and the attack record

What an attacker returns, and what the round is written down as. The machine-readable shape is
`attack-record.schema.json`; this is what the fields mean and why they are held to it.

## An objection

```json
{"lens": "what-if", "target_ac": "A3",
 "ground": {"rule": "what-if-questions", "reason": "why the criteria break it"},
 "objection": "what the criteria let through",
 "obligation": "O1.2",
 "scenario": {"given": "input or starting state", "when": "the action",
              "expect": "the observable outcome"}}
```

`target_ac` is the criterion attacked, or `"none"` when nothing covers
the ground. `ground.rule` is the ID of the acceptance-criteria rule the criteria break, and it is
one the producing lens enforces, since those are the only rules its prompt carried; `ground.reason`
says why. `obligation` is optional, for a lens whose instructions name obligations or their parts. The
attacker states the objection and the author answers it: an accepted objection names the criterion
the author wrote, which the attacker never drafts because it lacks the author's context.

The `scenario` is the line between a testable claim and a concern: a starting state, an action,
an observable outcome, all non-blank — a concern cannot name them. An item leaving one blank is
malformed, and is dropped rather than adjudicated.

A lens whose every item is dropped returned nothing usable, which is not nothing found: it gets no
entry, and the round closes by running that lens again rather than by recording it empty. Recording
it empty would claim it looked and found nothing, which is a different result and one the gate
reads as coverage obtained.

Two lenses naming one hole contribute two objections. The union is of the reports, not of the
holes: folding one into the other leaves a lens reporting objections with none attributed to it,
which reads as a report the record lost. Adjudicate the pair together and reject the second
against the first if that is the judgement — a rejection is a result and costs one rationale.

Unioning the reports adds an `id` to each objection, distinct within the round — an attacker sees
its own lens and not the round, so it cannot pick one that is distinct across the union. That id is
what a disposition names. Dropping a malformed objection is what makes it necessary: positions
renumber, and a disposition keyed on position would then adjudicate an objection it was never written
against, crediting one hole with another's criterion while the round still reads closed.

## Assembling the union and the record

`assemble_record.py` builds the record in two steps, with the author's adjudication between them.
The union step takes the round file and one `--report <lens>=<path>` per lens the round names, and
writes `union.json` and `dispositions.skeleton.json` beside the round file. Copy the skeleton, fill
in every entry, and make every accepted edit to the document. The assemble step then takes the
union, the filled file and the document, and writes the record beside the document. Stdout is
`{"assembled": true, …}` with the paths written; the union step adds `repairs` and `dropped`, and
your report to the user discloses both, since the record keeps no trace of them. A refusal is
`{"assembled": false, "errors": [{"code", "message", "lens"?}]}`, exit 2, and writes nothing. Every
code is in `errors.md`.

The union step reads each lens's raw output for the JSON object carrying `report` or
`objections`, and reads one repeated verbatim once. The output may be that object alone, the object fenced in prose, or a
Codex envelope whose `rawOutput` holds it. Each objection it keeps is numbered `<lens>-<n>`, counting
only that lens's kept objections in the order the lens returned them, so the same outputs always
yield the same ids. A rerun lens can renumber its objections, which is why every skeleton entry
repeats the objection's text: the assemble step refuses an entry whose text is not the one the union
holds under that id, so a verdict never lands on an objection it was not written against.

The union step changes a report only where the change cannot alter what it claims, and lists
each change on stdout under `repairs`, naming the lens, the id of any objection changed, and what
changed:

- A key the output shape does not declare is dropped, at any level of the report or an objection.
- A blank optional `obligation` is dropped.
- A missing `lens`, on the report or an objection, is set to the lens whose output it came from.
- A missing `objections` is set to an empty list, and a missing `report` to `objections` when the
  list holds any and `empty` when it does not.
- A ground rule the lens does not enforce is replaced by the one rule it does, when it enforces
  exactly one. The prompt carried only that rule, so the objection can only have meant it.
- Workings from a lens whose front matter does not require them are dropped.

An objection whose scenario leaves `given`, `when` or `expect` blank is dropped and listed under
`dropped`. Any other drift refuses the lens, since repairing it would mean guessing what the
attacker meant: a rule outside a lens enforcing several, a blank `target_ac`, `objection` or ground
field, a scenario part or `obligation` that is not text, an objection attributed to another lens, a
report whose `report` is neither `objections` nor `empty` or disagrees with its list, an object
naming one key twice, two different reports in one output, and workings that are missing, break
the schema beside the lens's prompt, discharge a part by a criterion they do not list, or leave a
part or criterion unaccounted for with no objection naming it. A refused lens is run again.

`assemble_record.py assemble` joins the union with the filled skeleton. Each entry sets
`disposition` to `accepted` with a `covering_ac`, or to `rejected` with a `rationale`. An acceptance's
`revision` is the digest of the document's bytes when the step runs, in the `sha256:` notation the
emitter stamps. An entry may leave `revision` out. One it supplies must be that digest, or the
entry is refused.

## The record

Committed beside the attacked document, named for it without its extension: `ledger.md` gets
`ledger-ac-attack.json`. The check enforces that pair rather than trusting it — the two names are
all that binds a record to its document, so one standing under another document's name would
otherwise close a round over a document no attacker in it read. Only the last extension comes off,
so two documents in one directory whose names differ only there — `ledger.md` beside `ledger.txt` —
want one record name between them, and the second round written takes the first's place with
nothing to say it did. Rename one before attacking both. Every top-level field is required.

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1"`. |
| `spec_path` | The attacked document as a bare basename. The record is committed beside it and the checker searches only the record's own directory, so a path leading out of it names a document no attacker in the round read, and an absolute one resolves only on the machine that wrote it. |
| `spec_revision` | The revision attacked. |
| `lenses` | `{"lens", "report": "objections"\|"empty", "workings"?}`, one per lens that reported. A silent or errored lens has no entry and the round is unfinished — coverage is read off the record, never inferred from silence. A lens whose front matter requires workings carries them here, valid against the `workings.schema.json` beside its prompt; each part they leave undischarged is owed an objection from that lens naming it in `obligation`, and each listed criterion discharging no part one naming it in `target_ac`. |
| `objections` | The union of the reports, each carrying its producing lens and its `id`. Reports are held against them: a lens reporting empty contributes none, one reporting objections at least one. |
| `dispositions` | `{"id", "disposition": "accepted"\|"rejected", "rationale"?, "revision"?, "covering_ac"?}`. |

- Every objection id carries exactly one disposition.
- **Accepted** names the `revision` now carrying the objection and the `covering_ac` in it. That
  revision is necessarily other than the one attacked — accepting an objection and changing nothing
  leaves it unadjudicated — and it is the same revision for every acceptance, since the document
  reached exactly one state once all of them were in it.
- **Rejected** states a `rationale`. Out of scope is a judgement, and a judgement gets written down.
- **Nothing found** is a result: every lens reporting empty closes the round.

A revision names content, not history, and is recomputable from the document in front of you. One
record picks one notation and writes every revision in it: revisions compare as strings, so one
content written both ways would read as two, and the check refuses the record rather than guess
which was meant.

Which notation is already decided for you. The emitter stamps the revision it attacked as `sha256:`
plus the digest of the document's bytes, so a record built from `round.json` starts in that
notation and every acceptance in it is written the same way — `shasum -a 256` prints that digest as
its first field, as does `sha256sum` where that is the name.

The equivalent 40-hex git object id is the other notation, for a record that uses it throughout.
Take it with `git hash-object --no-filters`: without that flag git runs the repository's clean
filters first, so under a `* text=auto` attribute a document with CRLF endings hashes as though its
endings were LF — a revision naming content the file on disk does not hold, which the check reads
as a document that moved on and no edit can reconcile. Either command ends its output with a
newline; write the revision without it, since one that keeps it reads as a different revision and
an acceptance that changed nothing would pass as an incorporation.
