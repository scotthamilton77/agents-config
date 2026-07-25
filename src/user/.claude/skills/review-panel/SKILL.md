---
name: review-panel
description: Run one class-contract review round over a change — emit the per-lens reviewer prompts for an artifact class, then assemble the lens reports into the round verdict. Use when reviewing a pull request diff, or re-reviewing after a claimed fix.
admission:
  prevents: One reviewer judging a whole change against every dimension at once, which splits its attention and returns one or two findings where an exhaustive pass finds five — and re-review rounds that re-litigate settled findings because nothing carried the earlier dispositions forward.
  cost: A round costs one model call per lens instead of one per change, and cannot start until the invoker declares the claim, the retained categories, and a disposition for every earlier mechanical finding.
  remove_when: A single reviewer pass measurably matches a panel's finding count on the same diffs, or the panel fan-out moves into the review service itself.
---

A round is a panel of single-lens reviewers. Each lens gets its own prompt, its own reviewer, and
one mandate; the round verdict is the union of their reports. Depth inside a lens, never breadth
across lenses.

## Artifact classes

Pick the class that matches what changed, then run every lens it declares. Lens sets, tiers,
re-review scopes and transports are data in `contracts.json`; this is the shape of them:

| Class | Lenses |
| --- | --- |
| `typed-code` | correctness, security, test-adequacy, simplification-efficiency |
| `spec` | internal-consistency-decidability, ac-testability, completeness-vs-scope, clarity-standalone-read |
| `skill-config-prose` | instruction-correctness, robustness-injection, altitude-token-budget, standalone-read |

Each panel mixes model tiers — hard-reasoning lenses on frontier models, mechanical walks on
mid-tier — and spans two vendors, because blind spots correlate inside a vendor.

Most lenses re-read the whole artifact every round. A lens marked `diff` reviews only the change
since the head it last judged, and only when it returned green that round; anything judging
coherence across sections stays whole-artifact, since a fix in one place can break a claim in
another.

## Emitting the prompts

Write the diff to a file, then, from this directory:

```bash
uv run emit_prompts.py --class typed-code --claim <claim-id> --round 1 \
  --acs criteria.md --diff /tmp/change.diff --repo-root /path/to/repo \
  --base-sha <40-hex> --head-sha <40-hex> --target-branch main \
  --retained '[]' --out-dir /tmp/round-1
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the class, claim, commits,
retained categories, the lens list with its tier, transport and scope, and the disposition ledger.
Stdout is `{"emitted": true, "prompts": [...]}`.

Re-review after a claimed fix adds `--round <n>`, one `--prior-verdict <path>` per earlier posted
verdict, and `--disposition <path>` — a JSON array of `{"round", "id", "disposition", "evidence"}`
covering every earlier mechanical finding. Each lens then sees its own prior findings by round and
finding id, plus the round-global ledger of everything already settled; other lenses' full
histories stay out, their settled items travel everywhere.

## Refusals

The emitter refuses rather than producing a prompt it knows is unsound. Refusals print
`{"emitted": false, "errors": [{"code", "message"}]}` and exit 2:

| Code | Condition |
| --- | --- |
| `unknown-class` | The class names no contract. |
| `no-claim` | No claim was named. A push with no readiness or fix claim triggers no round. |
| `no-retained-declaration` | No retained categories were declared. `[]` is a valid declaration and is accepted; absence is not. |
| `no-acs` | No criteria file. A lens judges against stated criteria, not taste. |
| `base-out-of-sync` | The declared base is not the merge base of the checkout and the target branch — reviewing an unsynced tree manufactures phantom findings. |
| `no-prior-verdicts` | A later round was invoked without the earlier rounds' verdicts. |
| `bad-prior-verdict` | An earlier verdict is unreadable or does not satisfy the verdict schema. |
| `ledger-gap` | An earlier mechanical finding has no disposition. |
| `unsupported-rebuttal` | A finding is marked rebutted with no evidence. A rebuttal without evidence is a disagreement. |

## What a prompt contains

Fixed instructions first: the lens mandate, the requirement to report every violation of that lens
findable this round, the requirement to return an explicit green report when there is nothing (a
silent lens leaves the round unfinished), the instruction to ignore intentionality claims in the
reviewed content, and the exact-JSON contract for one lens report. All interpolated material —
criteria, diff pointer, retained categories, prior findings — follows inside a marked untrusted
fence that the instructions declare inert. No other lens's mandate appears, and no house rulebook
text does either.

## Assembling the round verdict

Collect one report per lens, then build the envelope the review-verdict skill defines: `lenses`
gets one entry per lens the class declares, green ones included, so coverage is read off the
artifact and never inferred from an empty findings list. A lens whose reviewer errored or returned
unparseable output has no entry, and the round is incomplete — fail closed and re-run that lens.
`findings` is the union across lenses; `prior_dispositions` is the ledger from `round.json`.
Terminal-clean means a complete round with zero mechanical findings across every lens.

Non-codex lenses run through the multi-vendor transport skill. When that transport is unavailable,
run every lens serially through the codex command-line tool instead, and note in the round that the
panel lost its vendor diversity.
