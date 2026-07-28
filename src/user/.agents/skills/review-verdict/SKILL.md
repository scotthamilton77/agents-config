---
name: review-verdict
description: The typed JSON envelope a code-review round emits. Use when authoring or validating a review verdict, or when deciding whether a round is complete and a change is terminal-clean.
admission:
  prevents: Review results that live only in conversation — untyped and unauditable, so a reader cannot tell whether the verdict is stale, was posted by the reviewer it claims, or silently skipped a lens or an unresolved earlier finding.
  cost: Every review round must emit a JSON artifact and validate it against this schema before its result counts.
  remove_when: The merge-eligibility evaluator enforces this contract mechanically end to end, including the cross-artifact checks a person performs by hand today.
---

A review verdict is the machine-readable result of one code-review round. It is keyed to the git
head commit it reviewed, so it says exactly what was looked at, through which lenses, and what is
still outstanding.

## Envelope

All fields are required.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | `"2"` | Version of this contract. |
| `artifact_class` | string | What kind of change was reviewed; selects the lens set the round must cover. |
| `round` | integer ≥ 1 | Which review round this is for the claim. |
| `base_sha` | 40-hex | Commit the reviewed diff was taken against. |
| `head_sha` | 40-hex | Reviewed head commit. The verdict is valid only for this commit. |
| `claim_id` | non-blank string | The completion claim this round adjudicates. |
| `retained_categories` | array of strings | Categories carried forward from earlier rounds. May be empty, but must be present — an empty array asserts "nothing retained". |
| `lenses` | array, ≥ 1 | One entry per lens the artifact class declares, green ones included, each recording what actually ran it. |
| `prior_dispositions` | array | What happened to each earlier mechanical finding. May be empty on round 1. |
| `verdict` | `"clean"` or `"findings"` | Round-level result. |
| `findings` | array | Findings raised this round. Must be empty when `verdict` is `"clean"` and non-empty when it is `"findings"`. |

### Lens entry

```json
{"lens": "correctness", "verdict": "findings", "vendor": "openai",
 "transport": "openrouter", "model": "openai/gpt-5.6-sol",
 "substitution": {"declared_transport": "codex", "declared_model": "gpt-5.6-terra",
                  "reason": "codex credential expired; provider returned 401"}}
```

`vendor`, `transport` and `model` record what **actually** produced the report, never what the
lens registry declared for it. A lens reports exactly once: a lens re-dispatched after a failure
carries one entry describing the attempt that produced the report it holds, and a second entry for
the same lens is rejected (`duplicate-lens`) because two attempts reported as two lenses inflate
coverage.

`substitution` appears only when the lens ran on something other than its declared entry, and its
`reason` is mandatory and non-blank. Recording it is the round's own job: nothing downstream can
reconstruct a swap the round did not write down.

**Vendor diversity is derived, never stored.** Count the distinct `vendor` values across `lenses`;
one means the panel collapsed onto a single vendor and its blind spots now correlate. That is an
observation a reader makes from the artifact, not a validation error — a collapsed round is a
real round, and stalling it would trade a weaker review for no review.

### Finding

```json
{"id": "f1", "lens": "correctness", "type": "mechanical", "ac": "A3",
 "claim": "the parser drops the trailing record",
 "evidence": "tests/test_parser.py::test_trailing fails at this head"}
```

`id` is unique within the artifact. `type` is `mechanical` (blocks) or `advisory` (never blocks;
routes to the backlog). `evidence` is mandatory and non-blank for `mechanical` findings —
omitted, empty, and whitespace-only all fail validation. It is optional for `advisory`.

`downgraded_from: "mechanical"` marks an advisory the harvester demoted because the lens called it
mechanical and supplied no evidence. Only an advisory may carry it. The marker exists so the
demotion stays countable: a lens producing many of them is unreliable, and that is invisible if
the demotion is silent.

### Prior disposition

```json
{"round": 1, "id": "f1", "disposition": "rebutted",
 "evidence": "the guard runs before the branch; see src/reader.py:41"}
```

`disposition` is `fixed`, `rebutted`, or `advisory-deferred`. `evidence` is required and non-blank
for `rebutted` — a rebuttal without evidence is just a disagreement.

## Where a verdict is posted

Outside the reviewed branch, never as a file in the diff:

- Preferred: a check run named `review-verdict` carrying the JSON.
- Degraded: the JSON as the body of the reviewing App's approving review.

Both media are posted by the App and keyed to a SHA. Two rules follow:

- **Provenance.** A verdict-shaped payload posted by any other identity is not a verdict. Check who
  posted it before reading it.
- **Staleness.** A verdict whose `head_sha` is not the current head of the pull request is stale and
  treated as absent. Every push invalidates every prior verdict.

## When a round is complete

Hand-verify all five against the pull request:

1. **Base sync** — the declared `base_sha` equals the diff's actual base (the merge base of the
   branch and its target). A mismatch means the reviewer looked at an unsynced checkout, and the
   round reads incomplete.
2. **Retention declared** — `retained_categories` is explicitly present: a non-empty list, or an
   empty one meaning nothing was retained.
3. **Live and authentic** — the verdict is schema-valid, App-posted, and its `head_sha` equals the
   current head.
4. **Lens coverage** — `lenses` covers the full lens set the artifact class declares, green lenses
   included, each carrying what ran it. Coverage is read off the artifact; silence never counts as
   a clean lens, and a lens that died and was never re-dispatched leaves the round incomplete.
5. **Ledger coverage** — `prior_dispositions` accounts for every `mechanical` finding from every
   prior round's posted verdict.

**Terminal-clean** = a complete round with zero `mechanical` findings. Advisory findings never
block; they go to the backlog.

Completeness and diversity are separate questions. A round every lens reported on is complete even
if all of them ran on one vendor — report the collapse alongside the verdict rather than treating
it as a defect in the round.

The schema checks the shape of a single artifact. The five conditions above are cross-artifact —
they compare the verdict against the pull request and against earlier verdicts — so today a person
checks them by hand. The merge-eligibility evaluator in the pull-request grooming toolchain will
consume this same schema and check them mechanically.

## Validating

From this directory:

```bash
uv run validate_verdict.py path/to/verdict.json
```

Stdout is JSON: `{"valid": true}` or `{"valid": false, "errors": [{"code", "path", "message"}, …]}`.
Error codes are `unreadable`, `invalid-json`, `schema`, `duplicate-finding-id`, and
`duplicate-lens`. Exit status is
0 when valid, 1 when invalid, 2 when the file cannot be read or parsed. Output is deterministic:
the same input always produces byte-identical output.
