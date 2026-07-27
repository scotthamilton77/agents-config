# Error codes

Every code either script emits. Both write one JSON object to stdout and never a traceback, so a
caller parses the same shape on success and on failure.

## `emit_prompts.py`

Refusals print `{"emitted": false, "errors": [{"code", "message"}]}` and exit 2.

| Code | Condition |
| --- | --- |
| `no-spec` | No `--spec` given, or the document is missing, unreadable, or empty. |
| `spec-contains-marker` | The document carries an untrusted-content marker of its own. Fencing it would rewrite the text its revision names, so the round refuses rather than attack something the record cannot name. |
| `no-lenses` | The lens registry does not yield one usable attacker per declared lens: it names none; omits a key an entry owes (`lens`, `mandate`, `tier`, `transport`) or leaves one blank, which is a lens that cannot do its job while the round claims it ran; names one lens twice, and a lens's name is its prompt's filename, so the second mandate would overwrite the first; or names one that is not a bare filename, whose prompt would land outside the owner-only directory the round created. Each would report an emitted round while an attacker it declared never ran. |
| `no-out-dir` | No `--out-dir` given, or it could not be created — including when a parent of it does not exist, since the round creates one directory and no parent along the way. The output names are fixed, so a round with nowhere named truncates whatever wears them in the directory it ran from. |
| `unsafe-output-path` | The out-dir is a symbolic link, or an output name is held by a link of either kind or by something that is not a plain file — writing would take the whole document somewhere the round never named. Also when the `--spec` document is itself the file standing at an output name: a plain file there is overwritten as ordinary re-emission, so a round pointed at the directory the document sits in would destroy the artifact under attack and report itself emitted. Name an out-dir that does not hold the document. |
| `bad-arguments` | The command line could not be parsed. |
| `emitter-failure` | Anything else that escaped, reported rather than raised so stdout stays a contract. Every refusal above is decided before any file is written, and every prompt is rendered before any is written, so a refused round leaves nothing behind. A write that fails partway — the disk filling, say — is the one case that can, and `round.json` is written last, so a directory without it holds no round. Read the exit status rather than the directory. |

## `check_record.py`

Results print `{"clean", "complete", "errors": [{"code", "id"?, "message"}], "document"?,
"revision"?}`. Exit 0 complete, 1 not complete, 2 unusable input.

| Code | Condition |
| --- | --- |
| `no-record` | No record was named. An unnamed record is not an unattacked one. |
| `unreadable` / `invalid-json` | The record is missing, undecodable, or not JSON. |
| `schema` | The record is the wrong shape, including a disposition missing the fields its verdict requires — `revision` and `covering_ac` on an acceptance, `rationale` on a rejection. |
| `bad-arguments` | The command line could not be parsed. |
| `checker-failure` | Anything else that escaped, reported rather than raised so stdout stays a contract. |
| `no-spec` | `--spec` was given without a document, or the attacked document holds nothing but whitespace. The emitter refuses that document before a prompt goes out, so no round in hand read one, and closing a round over an empty stub clears work to start against criteria nobody wrote. |
| `spec-unreadable` | The document is not where the record says. The record names it relative to its own directory; `--spec` overrides that when it has moved. |
| `spec-not-a-bare-filename` | The record's `spec_path` reaches out of the record's own directory, or is absolute. A record is committed beside the document it names, so its basename is what finds it; anything else decides the round against a document the record does not sit next to, and resolves only on the machine that wrote it. |
| `untrimmed-revision` | A revision keeps the newline `git hash-object` prints. That newline compares unequal to the same content written without it, so an acceptance that changed nothing would pass as an incorporation. In practice this is the only surrounding whitespace that reaches here: every other form fails the schema's pattern first and is reported as `schema`. |
| `no-lenses` | The bundled lens registry is one the emitter would refuse to emit from — see its row above. Coverage is read off that registry, so a round in hand cannot have come from a registry like this, and reading coverage off it credits the record with attackers that never ran. |
| `mixed-revision-notation` | The record writes revisions in both notations, so one content would read as two revisions and an acceptance that changed nothing could pass as an incorporation. |
| `lens-missing` | A declared lens has no report. A lens that errored or returned unreadable output leaves the round unfinished, and an empty proposal list never stands in for a report. |
| `duplicate-lens` | A lens reports more than once. Coverage is read off one entry per lens. |
| `unknown-lens` | A report names a lens that is not declared. |
| `unknown-proposal-lens` | A proposal is attributed to a lens that is not declared. |
| `contradicted-empty-report` | A lens reports empty, yet proposals are attributed to it. |
| `contradicted-proposals-report` | A lens reports proposals, yet none are attributed to it — a proposal it made and the record lost is a hole nobody adjudicates. |
| `duplicate-proposal-id` | Two proposals carry one id, so a disposition naming it adjudicates neither. |
| `unadjudicated-proposal` | A proposal has no disposition. The round closes only once every proposal is accepted or rejected. |
| `duplicate-disposition` | One proposal is adjudicated more than once. |
| `unknown-proposal-id` | A disposition names a proposal the round does not hold. |
| `unincorporated-acceptance` | An acceptance names the revision it attacked. Accepting a proposal without changing the document leaves it unadjudicated. |
| `stale-revision` | The document is not carrying every revision the record accounts for: in a round that accepted something, one an acceptance names; in a round that accepted nothing, the revision attacked. Either the document moved on after the round, and the new revision must be attacked or the proposals re-adjudicated against it — or an accepted proposal's incorporation never landed, and the edit is missing. A record whose acceptances name several different revisions always lands here: the document can only be in one state, so acceptances name the revision it reached once every accepted proposal was in it. |
| `ordering-violation` | `--implementation-started` was declared and this run did not close the round — including when it could not read far enough to judge one, since a record that cannot be read has certainly not closed anything. The attack runs before that work, never alongside it. |
