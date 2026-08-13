# Harvesting a round

What to do between dispatching the lenses and writing the verdict. Every rule here exists because
a round hit the case and the invoker had to improvise; an improvised rule is one nobody can audit
afterwards.

## Transport is symmetric

The `transport` in `contracts.json` is a claim about vendor diversity, not about today's
credentials. **Any lens may run on any transport that is actually up.** An `openrouter` lens runs
through the codex command-line tool when OpenRouter is down; a `codex` lens runs through the
`openrouter-claude-subagent` skill when the codex credential has expired. Neither direction is the
exceptional one, and neither transport is the more reliable one — both have been down while the
other worked.

What you may not do is run the lens and say nothing. Whenever a lens runs on something other than
its declared entry, its verdict entry carries `substitution` with the declared transport or model,
the reason, and — when the swap was forced rather than chosen — the dead route's error verbatim in
`transport_error`. A round that lost diversity silently is indistinguishable from one that kept it.

## Every dispatch is claimed first

The gate authorizes each dispatch, records it, and refuses the ones past the bound. Run it from
this directory before every dispatch of a lens, the first one included:

```bash
uv run dispatch_gate.py claim --out-dir /tmp/round-1 --lens correctness \
  --transport codex --model gpt-5.6-sol --reason initial
```

An authorized answer carries the `output_path` this attempt writes its raw output to — one path
per attempt, so an attempt that wrote nothing reads as nothing rather than as the previous
attempt's report — and, for a recovery, the `backoff_seconds` to wait first. Run the claim from
the directory the reviewer will read: the gate records the working directory it was invoked in,
and a review of the wrong tree is the failure that leaves no trace of itself.

A refusal (exit 2) ends that lens. However many attempts it took, a lens ends with exactly one
entry, for the attempt that produced the report, carrying the `substitution` record above. Two
entries for one lens is a validation error, not a fuller record: it double-counts coverage.

## A dispatch that came back with no report

Two failures look alike from outside and recover oppositely, so tell them apart before claiming
again — the reason you declare is what the gate bounds.

**The route died** (`transport-error`). What came back describes the *transport*, not the review:
an HTTP status, an authentication or credit error, a refused connection, a dead broker or session
— or nothing at all, including no output file where one was claimed. The reviewer never ran. Judge
this on the body rather than the exit status: a dead route shows up as an exit 1 carrying a short
provider error, and equally as an exit 0 carrying nothing.

**The reviewer failed** (`unusable-output`). A body came back that is the model's own output, and
no report survives the ladder below — or the reviewer stalled mid-reasoning. The route worked;
what came over it is unusable.

Either way, the next claim declares that reason and the failure verbatim:

```bash
uv run dispatch_gate.py claim --out-dir /tmp/round-1 --lens correctness \
  --transport openrouter --model moonshotai/kimi-k2.7-code \
  --reason transport-error --evidence "402 Insufficient credits"
```

Declare a route that has not just failed. A model can sit at capacity for the length of a round
while another model of the same vendor answers, so the alternative to a dead route is another
transport **or** another model on it — and a retry of the route that just said it is down is
neither.

### When the gate refuses

A refusal whose every recorded failure was transport-class carries halt guidance naming each
exhausted transport and model with its error. **The round is over.** Abandon every dispatch not
yet made. Do not retry, do not drop to a lesser model, and do not quietly finish the round with
the lenses that happened to work. Write the verdict with `verdict: "halted"`, a `halt` block
carrying every transport failure the round did not recover from, and every undispatched lens in
`abandoned_lenses`. A failure some lens did recover from by failing over belongs on that lens's
`substitution`, not here.

Stopping forfeits the budget already spent. Continuing forfeits that too, and buys a document that
reads like a review of a change most of the panel never opened.

Any other refusal closes that lens alone: it has **no** entry and the round is incomplete. The
round is not restarted and the other lenses are not re-run. That is the contract working. Fail
closed — never write a `clean` entry for a lens that never reported.

## Say a failover out loud

A substitution written into the verdict has been recorded, not reported. The verdict goes to a
check run; the operator reads your summary. So every failover appears in what you tell them, and it
appears even when the round comes out clean — a clean round that quietly lost a transport is the
case most likely to go unmentioned.

Per failover, name four things: the lens, the route that died, the route it ran on instead, and the
error **verbatim**. Verbatim matters more than it looks. "OpenRouter was unavailable" and "402
Insufficient credits" ask different things of whoever is reading, and only one of them can be acted
on.

A halted run leads with this, ahead of any finding. What the operator needs first is which
transports died and what they said.

## Reading a lens report

Models violate an exact-output contract in predictable, harmless ways, so a report is read through
the gate rather than by eye:

```bash
uv run dispatch_gate.py ingest --out-dir /tmp/round-1 \
  --output /tmp/round-1/correctness.attempt-1.out
```

It walks the tolerance ladder — the whole body as JSON, then a single fenced block, then the first
object in the body with any trailing text ignored — and prints the report it recovered. Output
from a dispatch it never authorized is refused rather than read, so a dispatch that went around
the gate shows up as a hole in the ledger instead of as a lens entry. A claimed path holding no
file at all is refused as a transport failure, not a reviewer one: the route wrote nothing.

Past the ladder the output is **unparseable**: the lens has no entry and the round is incomplete
unless it is re-dispatched with reason `unusable-output`. Tolerance stops there on purpose.
Reconstructing a report by hand from prose makes the harvester the reviewer, and nothing
downstream can tell the difference.

## A mechanical finding with no evidence

A lens sometimes marks a finding `mechanical` and supplies no evidence. The verdict schema rejects
that finding, so the harvester must resolve it rather than pass it through.

**Downgrade it to `advisory` and set `downgraded_from: "mechanical"`.** Do not drop it, and do not
discard the whole lens report over it — the claim may still be worth reading, and the other
findings in that report are unaffected.

This is deliberately the permissive branch, and it is worth knowing why: an unevidenced mechanical
finding cannot be acted on anyway, since there is nothing to reproduce. The marker keeps the
demotion countable, so a lens that produces them repeatedly is visible as unreliable rather than
quietly generating backlog.

## Before writing the verdict

Count the distinct `vendor` values across the lens entries. One means the panel collapsed onto a
single vendor, and blind spots correlate inside a vendor — say so wherever the verdict is
reported. It does not make the round incomplete; it makes the round weaker in a way the next
reader deserves to know without asking anyone.
