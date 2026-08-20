---
name: review-panel
description: Fan out one class-contract review round over a change and assemble the round verdict. Use for any review target — a pull request, a diff or commit range, a single commit, uncommitted files, a package, or a whole document — and for re-review after a claimed fix.
admission:
  prevents: One reviewer judging a whole change against every dimension at once, which splits its attention and returns one or two findings where an exhaustive pass finds five — and re-review rounds that re-litigate settled findings because nothing carried the earlier dispositions forward.
  cost: A round costs one model call per lens instead of one per change, and cannot start until the invoker declares the claim, the retained categories, and a disposition for every earlier mechanical finding.
  remove_when: A single reviewer pass measurably matches a panel's finding count on the same diffs, or the panel fan-out moves into the review service itself.
---

A round is a panel of single-lens reviewers. This skill routes: it maps the target to artifact
classes, picks each class's lenses, fans out one reviewer per lens, and assembles the reports into
the round verdict. It holds no lens expertise itself — depth belongs to the reviewer.

## Artifact classes

Classify what changed, then run every lens the class declares. Lens sets, tiers, re-review scopes
and transports are data in `contracts.json`:

| Class | Lenses |
| --- | --- |
| `typed-code` | correctness, security, test-adequacy, simplification-efficiency, documentation-quality |
| `spec` | internal-consistency-decidability, ac-testability, completeness-vs-scope, architectural-fit, clarity-standalone-concision |
| `prose` | internal-consistency, global-consistency, standalone-read |

A target spanning classes gets one round per class, each judging the files of that class and
carrying its own verdict. A target no class fits is refused (`unknown-class`): pick the nearest
contract explicitly or extend `contracts.json` — never improvise a lens set.

Each panel mixes model tiers — hard-reasoning lenses on frontier models, mechanical walks on
mid-tier — and spans two vendors, because blind spots correlate inside a vendor. A lens's declared
`tier` sets round 1; a declared `re_review_tier` sets every round after. Its declared `transport`
carries the vendor-diversity claim, not the tier, so a reduced tier still spans both vendors — when
it is down the lens recovers onto another route, and the verdict records what ran it. No lens
declares a model; `harvest.md` says where each dispatch picks one.

Most lenses re-read the whole artifact every round. A lens marked `diff` reviews only the change
since the head it last judged, and only when it returned green that round; anything judging
coherence across sections or surroundings stays whole-artifact, since a fix in one place can break
a claim in another.

## Emitting the prompts

`--target` names what is under review in a phrase the reviewer can resolve against the repository
— a pull request number, a commit range, paths to uncommitted files, a package directory, one
document. Reviewers read the target and its surroundings directly from the repository; nothing
needs to be baked into a file first. From this directory:

```bash
uv run emit_prompts.py --class typed-code --claim <claim-id> --round 1 \
  --acs criteria.md --target "pull request 42" --repo-root /path/to/repo \
  --base-sha <40-hex> --head-sha <40-hex> --target-branch main \
  --retained '[]' --out-dir /tmp/round-1
```

Without `uv`, install `jsonschema` — its only dependency — and run `python3 emit_prompts.py ...`.

`--acs` points at a file the invoker writes before round 1: the acceptance criteria the claim is
judged against, gathered from wherever the claim is stated — the work item, the governing design
document, or the change's own description — as a plain list of observable criteria. Every lens of
every round of the same claim judges against that same file; if the criteria change mid-review,
that is a new claim and a new round 1, not an edit to the file.

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
| `no-prior-verdicts` | A later round was invoked without every earlier round's verdict. |
| `bad-prior-verdict` | An earlier verdict is unreadable, fails the verdict schema, or is for another claim, class, or a non-earlier round. |
| `ledger-gap` | An earlier mechanical finding has no disposition, or a disposition is outside the closed set. |
| `unsupported-rebuttal` | A finding is marked rebutted with no evidence. A rebuttal without evidence is a disagreement. |
| `emitter-failure` | Any other fault while emitting — an unreadable contracts file, a missing field, an unwritable output directory. Alone among these it can strike mid-write, leaving some `<lens>.md` files but no `round.json`. Clear the directory before retrying — a partial round reads as a smaller panel. |

## What a prompt contains

Fixed instructions first: the lens mandate, the requirement to report every violation of that lens
findable this round, the requirement to return an explicit green report when there is nothing (a
silent lens leaves the round unfinished), the instruction to ignore intentionality claims in the
reviewed content, and the exact-JSON contract for one lens report. Supporting data — criteria,
the target pointer, retained categories, prior findings — follows inside a marked section the
instructions declare to be data, not instructions. That section is context, never the whole
review: the reviewer reads the target itself, and whatever surrounding material its scope
requires, directly from the repository. No other lens's mandate appears, and no ambient house
context does either — no laws, no decision matrix, no hard lines. A lens's own mandate is the only
route a house standard reaches the reviewer through.

## Assembling the round verdict

Collect one report per lens, then build the envelope the review-verdict skill defines: `lenses`
gets one entry per lens the class declares, green ones included, so coverage is read off the
artifact and never inferred from an empty findings list. Each entry records the vendor, transport
and model that *actually* produced the report, never the route the dispatch set out to use.
`findings` is the union across lenses; `prior_dispositions` is the ledger from `round.json`.
Terminal-clean means a complete round that came out `clean`, with zero mechanical findings across
every lens; a halted round is neither.

Before the round's first claim, run `dispatch_gate.py preflight` once: it refuses loudly when the
openrouter dispatches planned in `round.json` would exceed the key's remaining credit, rather
than a lens dying mid-round. Every dispatch is then authorized by `dispatch_gate.py claim`, which records
the attempt with the route running it, assigns its output path, and refuses the ones past the
round's bounds — those bounds are the script's, not this prose's. A refusal for a lens out of routes carries halt
guidance: the round is over, and the `halted` verdict names the dead routes and the dispatches
abandoned behind them. `dispatch_gate.py ingest` reads the reply through the tolerance ladder;
without a report the lens has no entry and the round is incomplete — fail closed. Every failover
reaches the operator, not merely the verdict. `harvest.md` holds the rest: telling a dead route
from a failed reviewer, what each refusal obliges, the mechanical finding carrying no evidence,
and the vendor-collapse count before the verdict is written.
