# Harvesting a round

What to do around dispatching the lenses and writing the verdict. Each rule settles a case the
invoker would otherwise improvise, and an improvised rule is one nobody can audit afterwards.

## The records a round runs on

Three records exist before prompts are emitted, written by the invoker and retained afterwards as
campaign records beside the verdicts — the trend analyst reads across them. A mixed target adds a
campaign-level record before any of them: the circuit plan — the ordered grouping of its class
partitions into circuits, with rationale. `references/circuits.md` is its doctrine, including the
re-arm cap and the spec-code class's cannot-ship rationale.

**Gate evidence** — one execution record per profile precondition: gate name, exit status, the
head SHA it ran at. Produce it by running the profile's gates and recording what actually
happened; the emitter refuses assertion-shaped evidence and stale heads.

**The staffing record** — the staffed subset, a rationale per excluded roster lens, the
recommending model, and the decision. Get the recommendation from the dispatch that
`contracts.json` pins under `pins.staffing_recommender`. That pin names the provider, the tier,
the effort and the tool grant, and the model is the routing table's cell for that provider and
tier. The pinned provider sits outside the reviewing session's own vendor family. The
recommender has no failover seat. A dead run on it, which the ladder below defines, is re-run
once at the next lower effort the routing table lists for its model. A second dead run, a first
one at the lowest effort the table lists, or a dead route stops the campaign and asks the human,
because nothing else can stand in for a staffing decision. Interactively,
present it to the user and record their edit as the decision; non-interactively, record the
recommendation and proceed. A sweep round's staffing decision subtracts only from the
class's frontier seats, decision `sweep-contract`, unbounded by the profile's force ceiling, mid
seats excluded with that standing rationale. A subtracted frontier seat's rationale must be
target-shaped — name what in the campaign's changes gives the seat nothing to judge; that the
campaign looks clean justifies nothing, since clean-looking delta rounds are the blindness the
sweep exists to compensate. A zero-seat decision with justification is the terminal record.

**The checkpoint record** — due after every second consecutive non-clean round; the emitter
refuses the next round without it. Dispatch a Fable-high trend analysis over the retained records
— per-lens finding trends, fix history, severity direction — at the pin `contracts.json` holds
under `pins.trend_checkpoint`. A dead run on it gets the one re-run the recommender's does, and
a failure past that is a dispatch failure. That dispatch is standing-authorized;
if the authorization is ever withdrawn, the checkpoint resolves as escalate-to-human.
Record the returned verdict with the evidence it cites; record a dispatch failure as origin
`dispatch-failure` carrying the escalation verdict — the machine fails toward the human, never
toward silent continuation.

A checkpoint fired by the circuit re-arm cap admits only the terminate verdicts — a continue
verdict from one is invalid and resolves as escalate-to-human. Every terminate verdict, from any
checkpoint, carries a **churn diagnosis**: recommendations upstream (criteria, staffing, class
contracts, the spec itself) and/or panel-side (lens selection, the circuit plan, sequencing) for
reducing the churn observed. A terminate verdict without one is invalid exactly as an uncited
verdict is, and resolves as escalate-to-human. The upstream-defect halt is exempt — its
indictment already names the remediation.

## Transport is symmetric

The `transport` in `contracts.json` is a claim about vendor diversity, not about today's
credentials. **Any lens may run on any transport that is actually up.** An `openrouter` lens runs
as the Codex delegation skill's read-only run when OpenRouter is down; a `codex` lens runs through the
`openrouter-claude-subagent` skill when the codex credential has expired. Neither direction is the
exceptional one, because either transport can be down while the other works.

What you may not do is run the lens and say nothing. Whenever a lens runs on something other than
its declared entry, its verdict entry carries `substitution` naming what it moved off — the
declared transport, the model the displaced attempt ran on, or both when both changed — plus the
reason, and, when the swap was forced rather than chosen, the dead route's error verbatim in
`transport_error`. A round that lost diversity silently is indistinguishable from one that kept it.

## Choosing the model, the effort and the tools

No lens declares a model. `contracts.json` carries the lens rosters, the profile table and the
seat pins, and never a model. A lens's seat in a round is its transport, its tier this round and
its scope this round. A pin is the effort and the tool grant that seat is dispatched with. You
pick none of the three values yourself. Start from the lens's entry in this round's `round.json`,
never from the roster: the roster gives the tier a lens declares, and a later round may run it at
another.

- **The model** is the cell of the `choosing-a-delegate` skill's model routing table for the
  lens's provider and its `tier_this_round` in `round.json`. Transport `codex` is the table's
  provider `openai`, and transport `openrouter` is its provider `openrouter`. The entry's
  `tier` field only repeats the tier the roster declares. After round 1, a lens with a
  re-review tier runs at that lower tier, and `tier_this_round` says so. An entry reading
  `"transport": "openrouter"`, `"tier": "frontier"` and `"tier_this_round": "mid"` therefore
  dispatches the table's `openrouter` model at `mid`.
- **The effort and the tool grant** are the lens's `effort` and `tools` fields in `round.json`,
  which the emitter copied from its seat's pin. The tools value `read-only-sandbox` means the
  Codex runtime's read-only sandbox. A list names the only tools the OpenRouter launcher is
  granted. No grant includes a shell, so that reviewer reads the change from the diff file its
  prompt names, which the emitter wrote beside the prompt.

A lens whose route died fails over to its failover seat: the other transport's seat at the same
tier and scope. Its pin is the entry under `pins.lenses.<transport>.<tier>.<scope>` in
`contracts.json`, and its model is the table's cell for the other provider at that tier.
Failover reads `contracts.json` and never re-runs the emitter.

The routing table is the source of truth for every provider's ids, prices, context windows and
accepted reasoning efforts. All of them move underneath a remembered pick, because vendors
reprice and retire models without notice. A free-hand effort fails expensively. A model whose
reasoning cannot be capped will strand a whole-artifact lens inside a thinking block and return
no report at all, burning a full lens latency before the failover starts. A free-hand tool grant
fails the other way, with an exploratory walk billed at frontier prices.

The gate does not enforce the pin. It accepts and records an unlisted model on purpose, so that
a deliberate choice is possible and is visible afterwards. It records each attempt's effort
without comparing it to the pin, and it records no tool grant. The discipline is yours.

## Every dispatch is claimed first

The gate authorizes each dispatch, records it, and refuses the ones past the bound. Run it from
this directory before every dispatch of a lens, the first one included:

```bash
uv run dispatch_gate.py claim --out-dir /tmp/round-1 --lens correctness \
  --transport codex --model <model> --effort high --reason initial
```

An authorized answer carries the `output_path` this attempt writes its raw output to — one path
per attempt, so an attempt that wrote nothing reads as nothing rather than as the previous
attempt's report — and, for a recovery, the `backoff_seconds` to wait first. Run the claim from
the directory the reviewer will read: the gate records the working directory it was invoked in,
and a review of the wrong tree is the failure that leaves no trace of itself.

The answer also carries `stderr_path`, beside the output path. **The invoking shell redirects both
streams**, because the reviewer's own output records no tool use on either transport and its
stderr is the only place a read is written down:

```bash
<dispatch> > "${OUT}" 2> "${ERR}"
```

Retain that file even when the run looks perfect. A clean report whose stderr was never captured
is refused at ingest, and the dispatch has to be paid for a second time.

A lens whose prompt carries the whole target and whose run is granted no tools has no read to
record, and that is honest — a document lens reading text quoted inline, or a whole-artifact row
with no tool grant. The invoker knows it before dispatching, so the claim declares it:

```bash
uv run dispatch_gate.py claim --out-dir /tmp/round-1 --lens criteria-holes \
  --transport codex --model <model> --effort medium --reason initial --target-inline
```

The waiver is recorded on the claim and reads back out of the ledger. Declaring it for a lens that
did get tools buys a clean entry nobody checked, which is the thing this gate exists to refuse.

An `attempts-exhausted` refusal (exit 2) ends that lens. A claim refused as `off-ladder`, or for
a missing or malformed flag, spends no attempt: correct it and claim again. However many attempts
it took, a lens ends with exactly one entry, for the attempt that produced the report, carrying
the `substitution` record above. Two entries for one lens is a validation error, not a fuller
record: it double-counts coverage.

## A dispatch that came back with no report

Three failures look alike from outside and recover differently, so tell them apart before
claiming again — the reason you declare is what the gate bounds.

The launcher's own skill says which of four outcomes the run ended in. Usable output is ingested
under "Reading a lens report", whose read-evidence check may still send it back. A refused
invocation is yours to fix; it says nothing about the provider or the reviewer. A run the provider
did not serve is `transport-error`, the launcher's own clock included. Unusable output is
`unusable-output`, except the two signals the dead-run ladder below owns, a response that ended
inside the model's reasoning and a run your watchdog killed for silence, which are `dead-run`. A
run you stopped on purpose ends there with no claim.

**The route died** (`transport-error`). What came back describes the *transport*, not the review:
an HTTP status, an authentication or credit error, a refused connection, a dead broker or session
— or nothing at all, including no output file where one was claimed. An attempt your watchdog
killed for silence leaves nothing too, and it is a dead run.

**The reviewer failed** (`unusable-output`). A body came back that is the model's own output, and
no report survives the tolerance ladder under "Reading a lens report". The route worked; what
came over it is unusable.

**The run died** (`dead-run`). The model's response ended inside its reasoning and no report
came back. The launcher's own skill names the signal that marks it; on either transport, an
attempt your watchdog killed for silence is the same failure. Follow the ladder, one step per
dead run:

1. The same model, with the same tool grant, at the next lower effort the routing table lists
   for that model.
2. The failover seat at its pin, when the table lists no effort below the one that died or the
   step down also died.
3. A dead run on the failover seat ends the ladder: the lens is out of attempts and the round
   halts.

Whatever the failure, the next claim declares its reason and the failure verbatim, the proxy
line or the watchdog's kill line included:

```bash
uv run dispatch_gate.py claim --out-dir /tmp/round-1 --lens correctness \
  --transport openrouter --model <model> --effort low \
  --reason transport-error --evidence "402 Insufficient credits"
```

After a dead route, declare a route that has not just failed: the failover seat, dispatched at
its pin. A retry of the route that just said it is down is not a failover. The gate refuses a
`dead-run` claim that is not the ladder's next step, and its refusal names the step it accepts.

### When the gate refuses

An `attempts-exhausted` refusal carries halt guidance when the last failure on every route the
lens ran on was a dead route or a dead run. The guidance names each exhausted transport and model with its error. **The round is over.** Abandon every dispatch not
yet made. Do not retry, do not drop to a lesser model, and do not quietly finish the round with
the lenses that happened to work. Write the verdict with `verdict: "halted"`, a `halt` block
carrying every transport failure the round did not recover from, and every undispatched lens in
`abandoned_lenses`. A failure some lens did recover from by failing over belongs on that lens's
`substitution`, not here.

Stopping forfeits the budget already spent. Continuing forfeits that too, and buys a document that
reads like a review of a change most of the panel never opened.

Any other `attempts-exhausted` refusal closes that lens alone: it has **no** entry and the round
is incomplete. The round is not restarted and the other lenses are not re-run. That is the
contract working. Fail closed — never write a `clean` entry for a lens that never reported.

## Say a failover out loud

A substitution written into the verdict has been recorded, not reported. The verdict is where a
reader must go looking; the operator reads your summary. So every failover appears in what you tell them, and it
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
the gate shows up as a hole in the ledger instead of as a lens entry. A claimed path holding
nothing is refused as `no-output`, because the attempt wrote nothing. Claim again with reason
`dead-run` and the kill line as the evidence when your watchdog killed it for silence, and with
reason `transport-error` and the route's error otherwise.

Some transports wrap the reviewer's output in their own harness log lines — a banner before it, an
exit line after it, and command echoes that may themselves contain braces. **Ingest the claimed
path exactly as the transport wrote it.** The ladder reads past that wrapper, so hand-stripping it
first buys nothing and edits the evidence: a body trimmed by hand is no longer what the route
returned, and the ledger records the trimmed version as the reviewer's.

A transport may also replay the whole prompt on stdout ahead of the reviewer's output. The ladder
reads only what follows the line holding nothing but the prompt's closing untrusted-content marker,
and it never accepts the prompt's own report schema, so an echoed prompt yields the reviewer's
report or nothing. A finding that quotes that marker shares its line with the report around it, so
a reviewer may cite the marker freely.

A **clean** report is checked against the attempt's retained stderr before it is accepted, because
a reviewer that answers clean without opening the change costs the round a lens while looking like
its best one. What counts as a read depends on the transport. On `openrouter` the launcher's proxy
logs one line per API turn, and a run that called no tool forwards a single request, so anything
above one forward is a read. On `codex` both entry points count: the plugin job runner tags each
tool line with `[codex] `, and the command-line tool opens each call with a bare `exec` line and
reports the result beneath it. Only what follows the prompt's closing marker counts, so a target
that quotes these patterns cannot vouch for the reviewer that was sent to read it.

A clean report with nothing recorded is **unread** — its own refusal, and neither a transport
failure nor an unparseable body. Re-dispatch the lens with reason `unusable-output`. A findings
report is never refused this way: it names what it found, and what it found is the evidence.

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
beside the verdict, so the filter is auditable rather than silent. The citation it matches is
qualified: the assembler reads every id as `{lens}.r{round}.{id}` unless the reviewer already
wrote it that way, writes that id into the envelope, and keys the settled ledger the same, so
what suppresses a finding is the id the prompt showed the reviewer for that item. Dispositions,
indictments and re-citations all cite the envelope's id, and nothing is renumbered by hand.
Matching the bare id instead lets a settled `f1` swallow the next round's `f1`, since reviewers
number findings f1..fN fresh every round: a delta round's first finding from a lens
that found anything earlier wears a settled number, and the round assembles clean on a live
mechanical finding.

Its summary prints the distinct-vendor count. One means the panel collapsed onto a single vendor,
and blind spots correlate inside a vendor — say so wherever the verdict is reported, the clean
round especially; it does not make the round incomplete, only weaker in a way the next reader
deserves to know without asking. `--indict <finding-id>=<artifact-path>` assembles the
upstream-defect halt when a finding indicts the criteria themselves.

A findings round then emits its fix dispatch — `emit_fix_dispatch.py --verdict <path> --out
<path>` — every mechanical finding referenced in full plus the four fix clauses; hand it to the
fixer whole. A clean round emits none.

## Posting a pull request's verdict

When the target is a pull request, post the verdict to it as soon as it assembles and before the
fixer's work reaches the branch. A fix moves the head, and a verdict is only postable against the
head it judged — post late and the round's record is stranded off the commit it speaks about.

```bash
uv run prgroom_version.py --repo-root <repo-root>
prgroom post-verdict <pr> --verdict <path> --criteria <path>
```

The check runs first, every round, from this directory like the round's other scripts — which is
why it names the reviewed repository rather than reading the working directory. prgroom is installed
onto PATH by a human-run installer, so a fix that landed in the repository is not necessarily in the
tool: the check compares the installed release with the one that repository builds, and refuses when
the installed one is older, absent, or will not report a version. A refusal is a stop, not a
warning — the reinstall is a human's to do, and posting through a tool that predates the fix is how
a round reports a defect that is already closed.

That submits the reviewing App's comment-only review pinned to the reviewed head. The body is a
rendered summary of the round — the verdict word, the round, the lenses and what ran them, one entry
per finding — above a collapsed block holding the verdict's own bytes in a fenced `json` block.
Anything reading the envelope back off the review takes that block, not the whole body. Each finding
that names a file and line the diff touches also gets an inline comment, and that comment leads with
the finding's prose — what is wrong and what it rests on — above a collapsed block holding the
record itself. A human reads the line comment where it sits, so the sentence goes where the eye
lands and the JSON stays available underneath. Pass the round's criteria file so a finding citing a
criterion renders the criterion as a sentence rather than as an id the reader has to go look up. A
finding whose
location is a path with no line, a symbol, or a file the diff leaves alone lands in the body alone and is
named on stdout — read that list, because a finding nobody sees at the line is a finding the fixer
is likelier to skim past. It refuses when the live head has already moved, reposting the same
verdict at the same head posts nothing, and it never approves: the approval is a separate review,
decided separately and on its own evidence.

A verdict for any other target is not posted anywhere — it is a file you hand on directly.
