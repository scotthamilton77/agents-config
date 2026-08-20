---
name: review-panel
description: Fan out one class-contract review round over a change and assemble the round verdict. Use for any review target — a pull request, a diff or commit range, a single commit, uncommitted files, a package, or a whole document — and for re-review after a claimed fix.
admission:
  prevents: One reviewer judging a whole change against every dimension at once, which splits its attention and returns one or two findings where an exhaustive pass finds five — and the measured campaign pathologies downstream of it — re-litigated settled findings, ungoverned fix passes re-minting the defect classes they fix, and campaigns with no termination contract ending by improvised human ruling.
  cost: A round costs one model call per staffed lens, and cannot start until the invoker supplies the claim, the criteria, green gate evidence at the reviewed head, the round's staffing record, the retained categories, and a disposition for every earlier mechanical finding.
  remove_when: A single reviewer pass measurably matches a panel's finding count on the same diffs, or the panel fan-out moves into the review service itself.
---

A round is a panel of single-lens reviewers. This skill routes: it resolves the target to a
profile, checks the profile's gates ran, staffs the round, fans out one reviewer per staffed lens,
and assembles the reports into the round verdict. It holds no lens expertise — depth belongs to
the reviewer. Lens sets, mandates, tiers, transports, and the profile table are data in
`contracts.json`; every mandate states what makes an instance worth reporting.

## Classes and profiles

Classes stay coarse — `typed-code`, `spec`, `prose` — and each declares its lens roster. The
target's artifact type resolves against the profile table: each row carries default staffing, a
force ceiling staffing may subtract below but never exceed, a precondition set, and a no-gate
marker — the only route to an empty precondition set. Minimum rows: prototype (the no-gate row,
zero-force default), changelog (mechanical-only), agent-instruction-prose (mandates derived from
the writing-skills discipline), spec, general-docs, typed-code. The emitter validates the table
before use. An unlisted type names a listed profile explicitly with a reason, both recorded; a
target no profile resolves is refused — never improvise a lens set.

A mixed target partitions by class — one staffed round and one verdict per class present, each
finding attributed to exactly one partition; a justified zero-lens partition contributes its
terminal record in place of a verdict.

Panels mix tiers (`frontier` hard reasoning, `mid` mechanical walks, `re_review_tier` pricing
later rounds) and span two vendors — blind spots correlate inside one. `transport` is the
diversity claim, not a routing guarantee: a dead route fails over and the verdict records what
ran.

## The precondition gate

Emission refuses a target lacking recorded evidence that its profile's gates ran green at the
reviewed head: one execution record per gate — name, exit status, head SHA — never a bare
assertion. A failed, malformed, or missing record refuses naming the gate; evidence bound to
another head refuses as stale. The verb is bounce upstream: the panel neither reviews around the
gap nor re-derives mechanical verification. A no-gate profile passes on empty evidence.

## Staffing

Every round's emission consumes a per-round staffing record: the staffed subset (subtract-only
from the roster), the recommending model (foreign, mid-tier — it recommends which lenses
apply), a rationale per excluded roster lens, and, interactively, the user's final edit as the
recorded decision. The emitter checks the record against the roster and the force ceiling;
the verdict validator checks lens coverage against the record. A zero-lens decision with a
justification is itself the terminal record, and no verdict exists; a zero-lens outcome from a
missing or failed recommendation is refused instead.

## Rounds and scope

Round 1 reads the whole artifact. Rounds ≥2 are delta-scoped: each surviving lens reads the change
since the head it last judged, plus the settled ledger; a newly staffed lens reads full; a lens
whose delta is empty is not staffed that round. Accretion forces a full rescope: net growth since
the last full read beyond the emitter's edge-tested triviality boundary, or the staffing record's
own full-rescope override when a finding broke an original assumption.

Terminal-clean through deltas requires exactly one whole-artifact sweep after a zero-blocking
round: `--sweep` staffs the class's frontier-tier seats regardless of earlier subtraction, framed
blocking-only ("confirm no blocking defect exists" — a verdict, not a findings hunt), ledger
loaded. A class with no frontier seat escalates to the human. A clean, complete full round
1 whose staffing retained every frontier seat is terminal directly.

## Emitting the prompts

`--target` names the change in a phrase the reviewer resolves against the repository and reads
directly, surroundings included. `--acs` is the criteria file every lens
of every round judges against; changed criteria mean a new claim and a new round 1. From this
directory:

```bash
uv run emit_prompts.py --class typed-code --artifact-type typed-code --claim <id> --round 1 \
  --acs criteria.md --gate-evidence gates.json --staffing staffing-1.json \
  --target "pull request 42" --repo-root /path/to/repo --base-sha <40-hex> --head-sha <40-hex> \
  --target-branch main --retained '[]' --out-dir /tmp/round-1
```

One `<lens>.md` prompt lands per staffed lens, plus `round.json`: the profile resolution, the
staffing reference by digest, per-lens scope with delta bases, the ledger, and the consumed
checkpoints. Re-review adds `--round <n>`, every earlier `--prior-verdict`, `--disposition`, and
each due `--checkpoint`. Prompts put fixed instructions first, fence every interpolated datum as
declared data, and carry no other lens's mandate and no ambient house context — a lens's own
mandate is the only route a house standard reaches the reviewer.

The emitter refuses a round it knows is unsound — `{"emitted": false, "errors": [{code,
message}]}`, exit 2 — naming the unsynced base, missing gate or checkpoint, broken staffing or
profile table, ledger gap, unsupported rebuttal, fix, or transfer, terminated campaign, or a
resume over an unchanged ruler.

## Dispositions and termination

Every earlier mechanical finding needs a disposition: `fixed`, `rebutted`, `advisory-deferred`, or
`transferred`. `rebutted` requires evidence; `fixed` on a typed-code mechanical finding requires
evidence naming the test and the fails-without/passes-with observation; `transferred` moves a
pre-existing, non-blocking finding out, carrying the provenance basis and the work item that
inherits it — a blocking finding is not transferable. A finding indicting the criteria themselves
assembles the round `halted` with the upstream-defect reason; emission refuses to resume until
the indicted artifact changes.

A trend checkpoint is due after every second consecutive non-clean round, the first after round 2,
never after a clean round. It is a Fable-high trend-analysis dispatch over the campaign's retained
records; the review-panel iteration-strategy design record (2026-08-20), adopted by the owner, is
the standing authorization that dispatch cites. Its verdict — continue two rounds with staffing
advice, terminate-bounce-upstream, or terminate-escalate-human — must cite the campaign
evidence; an uncited verdict or failed dispatch resolves as escalation, severity rising
while count falls forbids continuation, and the next staffing record cites the checkpoint. No
numeric round cap exists.

## Fix dispatch, harvest, and assembly

A findings round emits its dispatch via `emit_fix_dispatch.py --verdict <path> --out <path>`:
every mechanical finding referenced in full, advisories listed as non-blocking, and the four
clauses — smallest net change; mutation evidence for code fixes; replacement-first for prose,
growth beyond the shared triviality boundary justified and paid for with a diff-scoped
consistency read next round; the narration sweep. A clean round emits none.

Run `dispatch_gate.py preflight` once, then `claim` before every dispatch and `ingest` on every
reply. `assemble_verdict.py` builds the schema-v3 envelope from `round.json`, the gate's attempts
ledger, one ingested report per staffed lens, and the routes that actually ran them: coverage
fails closed, an unauthorized dispatch is refused, an unevidenced mechanical finding is downgraded
to advisory with the demotion marked, and a finding exactly re-citing a settled ledger item is
suppressed with the match recorded beside the verdict — auditable, never silent. It prints the
distinct-vendor count (one means the panel collapsed) and `--indict` turns a criteria-indicting
finding into the upstream-defect halt. `harvest.md` holds the operating
doctrine: the round's records, transports and failover, telling a dead route from a failed
reviewer, and what each refusal obliges.
