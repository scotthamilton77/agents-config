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

## A dispatch that came back with no report

Two failures look alike from outside and are handled oppositely, so tell them apart first.

**The route died.** What came back describes the *transport*, not the review: an HTTP status, an
authentication or credit error, a refused connection, a dead broker or session — or nothing at all.
The reviewer never ran. Judge this on the body rather than the exit status: a dead route shows up
as an exit 1 carrying a short provider error, and equally as an exit 0 carrying nothing.

**The reviewer failed.** A body came back that is the model's own output, and it does not survive
the tolerance ladder below — or the reviewer stalled mid-reasoning. The route worked; what came
over it is unusable.

### The route died: fail over, once

Fail the lens over to the transport it was **not** declared on — Codex for a lens declared on
OpenRouter, OpenRouter for a lens declared on Codex — on the same prompt, unchanged. This is not a
judgement call, and not a retry on the same route: that route has just told you it is down.

The lens ends with exactly one entry, for the attempt that produced the report, carrying the
`substitution` record above. Two entries for one lens is a validation error, not a fuller record:
it double-counts coverage.

### Both routes died: stop the run

If the failover also dies on a transport error — any error, any code, either vendor — the round is
over. Abandon every dispatch not yet made. Do not retry, do not drop to a lesser model, and do not
quietly finish the round with the lenses that happened to work.

Write the verdict with `verdict: "halted"`, a `halt` block naming both dead routes and their
verbatim errors, and every undispatched lens in `abandoned_lenses`.

Stopping forfeits the budget already spent. Continuing forfeits that too, and buys a document that
reads like a review of a change most of the panel never opened.

### The reviewer failed: re-dispatch, then fail closed

A lens whose reviewer returned unusable output **may be re-dispatched** inside the same round, on
the same route or another. The round is not restarted and the other lenses are not re-run. If the
re-dispatch fails too, the lens has **no** entry and the round is incomplete. That is the contract
working. Fail closed — never write a `clean` entry for a lens that never reported.

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

Models violate an exact-output contract in predictable, harmless ways. Read each report through
this ladder, in order, and stop at the first step that yields an object:

1. The whole body parses as JSON.
2. The body is a single fenced code block; strip the fence and parse what is inside.
3. Decode from the first `{` in the body and ignore any trailing text — this recovers a report
   behind a prose preamble.

Anything else is **unparseable**: the lens has no entry and the round is incomplete unless you
re-dispatch it. Tolerance stops here on purpose. Reconstructing a report by hand from prose makes
the harvester the reviewer, and nothing downstream can tell the difference.

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
