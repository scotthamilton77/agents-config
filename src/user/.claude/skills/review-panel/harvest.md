# Harvesting a round

What to do around dispatching the lenses and writing the verdict. Every rule here exists because
a round hit the case and the invoker had to improvise; an improvised rule is one nobody can audit
afterwards.

## The records a round runs on

Three records exist before prompts are emitted, written by the invoker and retained afterwards as
campaign records beside the verdicts — the trend analyst reads across them.

**Gate evidence** — one execution record per profile precondition: gate name, exit status, the
head SHA it ran at. Produce it by running the profile's gates and recording what actually
happened; the emitter refuses assertion-shaped evidence and stale heads.

**The staffing record** — the staffed subset, a rationale per excluded roster lens, the
recommending model, and the decision. Get the recommendation from a foreign mid-tier model — the
routing table's mid tier, outside the reviewing session's own vendor family. Interactively,
present it to the user and record their edit as the decision; non-interactively, record the
recommendation and proceed. A sweep round's staffing decision subtracts only from the
class's frontier seats, decision `sweep-contract`, unbounded by the profile's force ceiling, mid
seats excluded with that standing rationale. A subtracted frontier seat's rationale must be
target-shaped — name what in the campaign's changes gives the seat nothing to judge; that the
campaign looks clean justifies nothing, since clean-looking delta rounds are the blindness the
sweep exists to compensate. A zero-seat decision with justification is the terminal record.

**The checkpoint record** — due after every second consecutive non-clean round; the emitter
refuses the next round without it. Dispatch a Fable-high trend analysis over the retained records
— per-lens finding trends, fix history, severity direction. The review-panel iteration-strategy
design record (2026-08-20), adopted by the owner, is the standing authorization this dispatch
cites; if that authorization is ever withdrawn, the checkpoint resolves as escalate-to-human.
Record the returned verdict with the evidence it cites; record a dispatch failure as origin
`dispatch-failure` carrying the escalation verdict — the machine fails toward the human, never
toward silent continuation.

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

It walks the tolerance ladder — the whole body as JSON, then a single fenced block, then an object
found in the body with the surrounding text ignored — and prints the report it recovered. Output
from a dispatch it never authorized is refused rather than read, so a dispatch that went around
the gate shows up as a hole in the ledger instead of as a lens entry. A claimed path holding no
file at all is refused as a transport failure, not a reviewer one: the route wrote nothing.

Some transports wrap the reviewer's output in their own harness log lines — a banner before it, an
exit line after it, and command echoes that may themselves contain braces. **Ingest the claimed
path exactly as the transport wrote it.** The ladder reads past that wrapper, so hand-stripping it
first buys nothing and edits the evidence: a body trimmed by hand is no longer what the route
returned, and the ledger records the trimmed version as the reviewer's.

Past the ladder the output is **unparseable**: the lens has no entry and the round is incomplete
unless it is re-dispatched with reason `unusable-output`. Tolerance stops there on purpose.
Reconstructing a report by hand from prose makes the harvester the reviewer, and nothing
downstream can tell the difference.

## Assembling the round

Assembly is `assemble_verdict.py`, never hand-written JSON: it reads `round.json`, the gate's
attempts ledger, one ingested report per staffed lens, and a routes file naming the vendor,
transport, and model that actually produced each report, substitutions included. Coverage fails
closed — a missing report, a report for an unstaffed lens, and output from a dispatch the gate
never authorized all refuse rather than assemble.

It resolves the two judgment-shaped cases mechanically. A finding marked `mechanical` with no
evidence is downgraded to `advisory` with `downgraded_from` set — never dropped, never left
mechanical: an unevidenced mechanical cannot be acted on anyway, and the marker keeps the
demotion countable, so a lens producing them repeatedly is visible as unreliable. A finding
exactly re-citing a settled ledger item is suppressed, each match recorded in `suppressions.json`
beside the verdict, so the filter is auditable rather than silent.

Its summary prints the distinct-vendor count. One means the panel collapsed onto a single vendor,
and blind spots correlate inside a vendor — say so wherever the verdict is reported, the clean
round especially; it does not make the round incomplete, only weaker in a way the next reader
deserves to know without asking. `--indict <finding-id>=<artifact-path>` assembles the
upstream-defect halt when a finding indicts the criteria themselves.

A findings round then emits its fix dispatch — `emit_fix_dispatch.py --verdict <path> --out
<path>` — every mechanical finding referenced in full plus the four fix clauses; hand it to the
fixer whole. A clean round emits none.
