# Error codes

Every code either script emits. Both write one JSON object to stdout and never a traceback, so a
caller parses the same shape on success and on failure.

## `emit_prompts.py`

Refusals print `{"emitted": false, "errors": [{"code", "message"}]}` and exit 2.

| Code | Condition |
| --- | --- |
| `no-spec` | No `--spec` given, or the document is missing, unreadable, or empty. |
| `spec-contains-marker` | The document carries an untrusted-content marker of its own. Fencing it would rewrite the text its revision names, so the round refuses rather than attack something the record cannot name. |
| `no-lenses` | The lens registry declares no lens. A round that sends no attacker at anything would otherwise report itself emitted, which reads as coverage nobody obtained. |
| `no-out-dir` | No `--out-dir` given, or it could not be created. The output names are fixed, so a round with nowhere named truncates whatever wears them in the directory it ran from. |
| `unsafe-output-path` | The out-dir is a link, an output name is held by a link of either kind or by something that is not a plain file, or a parent of the out-dir is missing. Writing would take the whole document somewhere the round never named. |
| `bad-arguments` | The command line could not be parsed. |
| `emitter-failure` | Anything else that escaped, reported rather than raised so stdout stays a contract. |

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
| `no-spec` | `--spec` was given without a document. |
| `spec-unreadable` | The document is not where the record says. The record names it relative to its own directory; `--spec` overrides that when it has moved. |
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
| `stale-revision` | The document has changed into a revision no acceptance accounts for. Attack the new revision, or re-adjudicate the proposals against it. |
| `ordering-violation` | The round is unfinished and `--implementation-started` was declared. The attack runs before that work, never alongside it. |
