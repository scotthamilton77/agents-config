---
name: review-panel
description: Fan out one class-contract review round over a change and assemble the round verdict. Use for any review target — a pull request, a diff or commit range, a single commit, uncommitted files, a package, or a whole document — and for re-review after a claimed fix.
admission:
  prevents: One reviewer judging a whole change against every dimension at once, which splits its attention and returns one or two findings where an exhaustive pass finds five — and re-review rounds that re-litigate settled findings because nothing carried the earlier dispositions forward.
  cost: A round costs one model call per lens instead of one per change, and cannot start until the invoker declares the claim, the retained categories, and a disposition for every earlier mechanical finding.
  remove_when: A single reviewer pass measurably matches a panel's finding count on the same diffs, or the panel fan-out moves into the review service itself.
---

A round is a panel of single-lens reviewers. This skill routes: it maps the target to artifact
classes, picks each class's lenses, fans out one reviewer per lens at the declared tier and
transport, and assembles the reports into the round verdict. It holds no lens expertise itself —
depth belongs to the reviewer.

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
`transport` is that diversity claim, not a routing guarantee: when it is down the lens fails over to
the other transport, and the verdict records what actually ran it (`harvest.md`).

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

If `uv` is not installed, install `jsonschema` yourself and run `python3 emit_prompts.py ...`
instead — that dependency is the script's only one.

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
| `emitter-failure` | Any other fault while emitting — an unreadable contracts file, a contract entry missing a field a prompt needs, an unwritable output directory. Alone among these it can strike mid-write: the rest are decided before the output directory exists, while this one can leave it holding some `<lens>.md` files and no `round.json`. Clear it before retrying — a partial round reads as a smaller panel. |

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
route by which a house-specific standard reaches the reviewer, because a lens that states no test
has nothing decidable to judge against.

## Assembling the round verdict

Collect one report per lens, then build the envelope the review-verdict skill defines: `lenses`
gets one entry per lens the class declares, green ones included, so coverage is read off the
artifact and never inferred from an empty findings list. Each entry records the vendor, transport
and model that *actually* produced the report, never the route `contracts.json` declared for it.
`findings` is the union across lenses; `prior_dispositions` is the ledger from `round.json`.
Terminal-clean means a complete round that came out `clean`, with zero mechanical findings across
every lens; a halted round is neither.

A dispatch that returns no report is two different problems. A dead route — provider, auth, credit,
connection — fails the lens over to the transport it was not declared on, and its single entry
carries the substitution with that route's verbatim error; a failover that dies too halts the run,
abandoning every remaining dispatch for a `halted` verdict naming the routes that ran out and
everything they cost the round. A live route returning unusable output may instead be re-dispatched, and
without a report the lens has no entry and the round is incomplete — fail closed. Every failover is
reported to the operator, not merely recorded in the verdict. `harvest.md` holds the rest: how to
tell those two failures apart, how tolerantly to read a report, what to do with a mechanical
finding carrying no evidence, and the vendor-collapse count to make before the verdict is written.
