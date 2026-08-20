---
name: review-verdict
description: The typed JSON envelope a code-review round emits. Use when authoring or validating a review verdict, or when deciding whether a round is complete and free of blocking findings.
admission:
  prevents: Review results that live only in conversation — untyped and unauditable, so a reader cannot tell whether the verdict is stale, was posted by the reviewer it claims, or silently skipped a lens or an unresolved earlier finding.
  cost: Every review round must emit a JSON artifact and validate it against this schema before its result counts.
  remove_when: The merge-eligibility evaluator enforces this contract mechanically end to end, including the cross-artifact checks a person performs by hand today.
---

A review verdict is the machine-readable result of one code-review round, keyed to the git head
commit it reviewed: what was looked at, through which lenses, and what is still outstanding.

## Envelope

All fields are required except `halt`.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | `"3"` | Version of this contract. |
| `artifact_class` | string | What was reviewed; selects the roster staffing draws from. |
| `round` | integer ≥ 1 | Which round this is for the claim. |
| `base_sha` | 40-hex | Commit the diff was taken against. |
| `head_sha` | 40-hex | Reviewed head. The verdict is valid only for this commit. |
| `claim_id` | non-blank string | The completion claim this round adjudicates. |
| `retained_categories` | array of strings | Carried forward from earlier rounds; empty asserts "nothing retained". |
| `staffing_record` | object | The staffing decision the round was dispatched from. |
| `lenses` | array | One entry per staffed lens, green ones included. At least one unless the round halted. |
| `prior_dispositions` | array | What happened to each earlier mechanical finding. Empty on round 1. |
| `verdict` | `"clean"`, `"findings"`, `"halted"` | Round-level result. |
| `findings` | array | Empty when `clean`, non-empty when `findings`, unconstrained on a halt. |
| `halt` | object | Present exactly when `verdict` is `"halted"`. |

Digests are `sha256:` plus 64 lowercase hex characters.

### Staffing record

`staffing_record` carries `digest`, the digest of the staffing record's raw bytes, plus an optional
non-blank `path` hint. The digest identifies the record this round is answerable to; one edited
afterwards no longer matches. Checking that record against the class roster is the panel's job, not
this envelope's.

### Lens entry

Each entry carries `lens`, its own `verdict` of `clean` or `findings` — only the round halts, never
a single lens — and `vendor`, `transport` and `model`, recording what **actually** produced the
report, never what the lens registry declared. A lens reports exactly once; a second entry for it is
rejected (`duplicate-lens`), because two attempts reported as two lenses inflate coverage.

An optional `substitution` appears only when a lens ran on something other than its declared entry,
holding `declared_transport`, `declared_model`, a mandatory non-blank `reason`, and
`transport_error` — verbatim what the declared route returned, since only that string identifies
the provider error a stop policy matches on.

**Vendor diversity is derived, never stored.** One distinct `vendor` across `lenses` means the panel
collapsed — a reader's observation, not a validation error.

### Finding

A finding carries an `id` unique within the artifact, its `lens`, a `type` of `mechanical` (blocks)
or `advisory` (never blocks; routes to the backlog), the `ac` it judges against, a `claim`, and
`evidence` such as `tests/test_parser.py::test_trailing fails at this head`. `evidence` is mandatory
and non-blank for `mechanical` — omitted, empty and whitespace-only all fail — and optional for
`advisory`.

`downgraded_from: "mechanical"` marks an advisory the harvester demoted because the lens called it
mechanical with no evidence. Only an advisory may carry it; it keeps the demotion countable.

### Prior disposition

An entry carries `round`, the finding `id`, a `disposition`, and where required `evidence` and
`work_item`. `disposition` is `fixed`, `rebutted`, `advisory-deferred`, or `transferred`.

`evidence` is required and non-blank for `rebutted`, and for `fixed` when `artifact_class` is
`typed-code`, where it names the test and the fails-without/passes-with observation. Classes with
no test gate leave it optional on `fixed`.

`transferred` moves a pre-existing, non-blocking defect out of the campaign, and requires both
`evidence` carrying the provenance basis — a base-side reference showing the defect predates the
change — and `work_item`, the id it was filed as. Either half alone lets a live defect leave
unowned. `work_item` is optional on the other dispositions.

### Halt

`reason` selects the shape. A transport failure:

```json
{"reason": "transport-failure",
 "failures": [{"lens": "security", "transport": "openrouter", "error": "402 Insufficient credits"},
              {"lens": "security", "transport": "codex", "error": "401 Missing bearer auth"}],
 "abandoned_lenses": ["test-adequacy"]}
```

`failures` carries at least two entries — a dispatch died on its route and the failover died too —
each naming its `lens`, `transport` and the verbatim `error`. A failure a successful failover
recovered from belongs on that lens's `substitution` instead.

An upstream defect, where a finding indicts the criteria the round measures against:

```json
{"reason": "upstream-defect", "indicted_finding": "f3",
 "indicted_artifact": "docs/specs/parser-rewrite.md",
 "artifact_digest": "sha256:7e2b…", "abandoned_lenses": []}
```

No further round is run: each would measure against a ruler known to be bent. `artifact_digest` is
the indicted artifact's content at the halt, and a resume recomputes it — unchanged means the ruler
is still bent and the request is refused. It carries no `failures`; nothing failed in transport.

`abandoned_lenses` is required on both shapes, naming the staffed lenses the round never dispatched;
present even when empty.

A halted round is never clean and never complete, and `verdict` says so outright rather than leaving
it inferred from a missing lens entry. Its findings are real and still not a verdict on the change.

## Where a verdict is posted

Outside the reviewed branch, never as a file in the diff: preferably a check run named
`review-verdict` carrying the JSON, or degraded, the JSON as the body of the reviewing App's
approving review. Both are App-posted and keyed to a SHA, so a payload posted by any other identity
is not a verdict, and one whose `head_sha` is not the current head is stale and treated as absent.

## When a round is complete

A `halted` verdict is incomplete by construction. For every other verdict, hand-verify all five
against the pull request:

1. **Base sync** — `base_sha` equals the merge base of the branch and its target; a mismatch means
   the reviewer read an unsynced checkout.
2. **Retention declared** — `retained_categories` is explicitly present, empty or not.
3. **Live and authentic** — schema-valid, App-posted, `head_sha` equal to the current head.
4. **Lens coverage** — `lenses` covers exactly the staffed set in the referenced staffing record.
   Silence never counts as a clean lens; a lens that died and was never re-dispatched leaves the
   round incomplete.
5. **Ledger coverage** — `prior_dispositions` accounts for every `mechanical` finding from every
   prior round's posted verdict.

**Terminal-clean** = a complete round whose `verdict` is `clean`, carrying zero `mechanical`
findings. A halted round is never terminal-clean, however few findings it holds. The schema checks
one artifact's shape; these five compare it against the world, so a person checks them by hand.

## Validating

From this directory (without `uv`: `pip install jsonschema`, then run it under `python3`):

```bash
uv run validate_verdict.py path/to/verdict.json [--staffing path/to/staffing.json]
```

The staffing record is a second positional or the value of `--staffing`. Given one, the validator
also checks that its bytes hash to the digest the verdict names, and that the reported lenses are
exactly the set it staffs; given none, it checks the envelope alone.

Stdout is JSON: `{"valid": true}` or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`.
Error codes are `unreadable`, `invalid-json`, `schema`, `duplicate-finding-id`, `duplicate-lens`,
`staffing-digest-mismatch`, `lens-not-staffed`, and `staffing-coverage-gap`. Exit 0 valid,
1 invalid, 2 unreadable or unparseable. Output is deterministic.
