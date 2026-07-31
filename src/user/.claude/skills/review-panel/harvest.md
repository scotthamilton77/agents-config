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
its declared entry, its verdict entry carries `substitution` with the declared transport or model
and the reason. A round that lost diversity silently is indistinguishable from one that kept it.

## Re-dispatching a lens that could not run

A lens that errors, times out, or returns output no tolerant read can parse **may be re-dispatched
inside the same round** — on the same route, or on a substitute model or transport. The round is
not restarted and the other lenses are not re-run.

The lens ends with exactly one entry, describing the attempt that produced the report it carries,
with `substitution` filled in if that attempt was not the declared route. Two entries for one lens
is a validation error, not a fuller record: it double-counts coverage.

If re-dispatch also fails, the lens has **no** entry and the round is incomplete. That is the
contract working. Fail closed — never write a `clean` entry for a lens that never reported.

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
