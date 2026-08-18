# Live grilling over the bridge — session report

Session ran against the round-4 prototype on `127.0.0.1:8378`. Board: the canned
16-decision nightly overnight-build pipeline. Ended on the idle condition — 18
minutes with no events after the human's last action (event cursor stuck at 27,
bridge still healthy at `{"events": 27, "updates": 8}`). No background processes
left running.

I sent 8 updates and the human produced 27 events. Six decisions moved: D1, D2,
D3, D4, D17 answered, D6 invalidated.

---

## 1. The design conversation

### D1 — work-item source (answered: the revised option a)

The human opened with a thread on D1 saying only "Zoom Out?". I answered that D1
looks like a freshness question and is not — what it actually fixes is whether
the night's work set is a closed set, and that three later decisions (D10's
"zero eligible items remain" wake condition, D14's budget check, D16's per-item
gate budget) are only expressible against a known denominator. I also flagged
that option (c), the hand-curated queue, silently deletes D3: if you curated the
list, the eligibility filter has nothing left to decide.

They came back with something neither option covered: *"I'd want the night's
discovered work to be automatically picked up if ready."* That is not option (b)
— (b) is a live query over the whole tracker, whereas they wanted work the run
itself discovers to re-enter the queue the same night.

I pushed on two things. First, the sharp one: "if ready" routes through D3, whose
option (a) requires enumerated acceptance criteria. For discovered work those
criteria are written by the agent that found the bug, at 2am, unreviewed — so the
pipeline authors its own criteria and then certifies itself against them. That is
the same self-certification loop D5's option (c) exists to reject, entering
through D1 where D5 cannot see it. Second: a queue that feeds itself has no fixed
point (A discovers B, B discovers C), which kills D10's termination condition.

I proposed bounding the lane — depth one, plus a per-night cap — so the night
keeps a countable end (N snapshot items plus at most K discoveries).

**What I sent:** a `thread-turn` carrying an `impact` with three updates: a
`revise` rewriting D1 to four options with the bounded lane as the
recommendation, an `add-node` for D17, and an `informational` on D3 recording
that D3 now has to rule on agent-authored criteria. They folded it; all three
applied. They then answered D1 with the new option (a).

### D10 — pre-emptive revise (unanswered, applied)

D1's answer made D10's option (a) wrong as written: "zero eligible items remain"
is no longer a stable state once the queue can refill. I revised D10 so the wake
condition reads "the snapshot is exhausted AND the discovery lane is empty or
capped out". Paired it with an `informational` on D4 noting that the depth rule
and the spent-cap count need a home, that the claim record is the only structure
that can carry them, and that a lock file cannot and "no claim" cannot count.

### D3 — eligibility filter (answered free-text)

They took the recommendation but wrote: *"we should discuss how to mitigate the
self-authored criteria acceptance… let's add it in the grilling map: how does
discovered work get quality acceptance criteria that we can trust, or else
identified as needing a human."*

**The map cannot mint that node** — `add-node` only accepts D17 and D18, and D18
is a different question hanging off D2. So I raised an `elicit-alert` on D3
(`requiresAction: false`, so it did not block their settled answer) with an `ask`
offering four routes, and told them in one line why it was a thread and not a
node.

My argument, in short: separating authorship (a second agent writes the criteria)
works but costs a whole extra agent per discovery at 2am; requiring criteria to
be mechanically falsifiable is lintable but a confidently wrong criterion passes
it cleanly; the one I recommended is gating on the provenance of the evidence —
a discovery is same-night eligible only if it left a failing check behind, so the
criterion is not authored at all, it is observed (this red check is now green).
That has two properties the others lack: the discovering agent cannot flatter
itself because it wrote nothing, and producing a red check costs real work, which
makes the discovery lane self-limiting against a run that would discover its way
to sunrise.

They never answered the ask.

### D4 — claim mechanism (answered a) — deliberate silence

They picked the tracker claim record, consistent with the note I had already
left. Nothing to add; I stayed silent.

### D2 — why wake at all (answered c: never wake) → D6 invalidated

This is the answer with teeth. I sent an `informational` recording the trade
honestly — never waking means the run cannot buy its way out of a block at 3am,
so throughput is bounded by how much work was pre-authorised before bed, and that
is the trade the pipeline exists to make. Then the part that is not free: with no
wake there is no circuit breaker, so the only thing containing a night that goes
wrong is the landing rule. "Never wake" is safe exactly as long as nothing the
run does before morning is irreversible — which promotes D11 and D12 from
merge-workflow preferences into the whole of the safety story.

I then sent an `invalidate` on D6: "how are you physically woken at 3am" has no
antecedent once nothing justifies a wake, and the board would otherwise have
walked them straight into that contradiction. This is the one blocking update I
sent all session and I think it was the right call — they let it land.

### D17 — re-query cost (answered a) — deliberate silence

"Re-query only between items, never mid-item, cap at one query per item."
Coherent with the bounded lane and it makes the night terminate cleanly, so I
said nothing. (I never saw D17's question or option texts — see findings.)

### Closing move

With the human quiet for ~8 minutes and the D3 thread carrying an `ask` but no
`impact` — therefore unfoldable, so they could not conclude it — I added one turn
with an `impact` that lands the provenance rule as a durable note on D3, and
offered to rewrite it if they preferred another option. I also pointed out that
D17's between-items boundary is free custody for the evidence check: the run is
already stopping there, so the gate adds no new stopping point. No response.

---

## 2. TRANSPORT FINDINGS

Ordered by how much damage each one can do.

### F1 (severe) — `ui-hello` republishes the INITIAL board mid-session, and is indistinguishable from a reset

At envelope seq 16, well into the session, the page emitted a fresh `ui-hello`
with a completely pristine board: 16 nodes, every `status` back to
`open`/`blocked`/`fogged`, every `answer` null, original three-option lists, no
D17. I concluded the page had reloaded and that everything settled was gone, and
reported that to my parent as a headline finding.

**It was wrong.** The very next event carried body `seq: 17`, contiguous with the
pre-hello log, and it was an answer on D2 — so the session had never restarted.
`ui-hello` carries the board's *initial definition*, republished at arbitrary
points, not live state.

This is the worst trap in the protocol, because both readings are catastrophic
and the wire gives you nothing to tell them apart at the moment of arrival:

- Trust a mid-session hello → you throw away every answer the human has settled
  and start re-grilling decided questions.
- Ignore a hello → you miss a real reload and stamp `basedOnSeq` against a dead log.

The only tell I found is the body `seq` of the *next* event, which arrives an
unbounded time later. BRIDGE.md actively invites the wrong reading: it describes
`nodes[]` as "the whole board" carrying `status` and `answer` (fields that are
therefore always stale after the first hello), and says the hello is "sent once
per page load", which is not what the wire does.

**Wanted:** either a monotonic session/epoch id on every event so a genuine reset
is unambiguous, or a hello that carries live state, or — cheapest — a documented
statement that `status`/`answer` in a hello are decorative and must never be
folded into agent state after the first one.

### F2 (severe) — envelope `seq` and body `seq` diverge, and `basedOnSeq` is undefined between them

BRIDGE.md's worked example has `{"seq": 1, "body": {… "seq": 1 …}}` — the two
equal — and says "`seq` … is the number you stamp your reply with". On the live
wire they are not equal and never were:

| envelope seq | body seq | event |
|---|---|---|
| 1, 2, 3 | 0, 0, 0 | three `ui-hello` |
| 4, 5 | 1, 1 | `thread-created T-D1-0`, duplicated |
| 6 | 3 | human's thread turn |
| 16 | 0 | the mid-session `ui-hello` |
| 17 | 17 | answer on D2 |

I guessed body `seq` on the theory that the page compares `basedOnSeq` against
its own session log, and that guess held for the whole session. But it was a
guess, and the doc's only worked example is the one case where the ambiguity is
invisible. **This should be one sentence in BRIDGE.md and it is not there.**

Corroboration that body `seq` is the right one: when the fold applied my impact
updates, the `applied` receipts echoed them with `basedOnSeq` rewritten from the
3 I sent to 5 — the fold's own log position. So the page does resolve stamps
against its own log, and it rewrites them at fold time. That rewrite is also
undocumented.

### F3 (moderate) — events are re-published, and there is no dedupe anywhere

`ui-hello` arrived four times; `thread-created T-D1-0` arrived twice with an
identical body (envelope 4 and 5, both body `seq: 1`). Nothing in the transport
deduplicates, and the brief's warning about re-reading from cursor 0 is only half
the hazard — you can double-react while polling forward correctly. Every agent
has to build identity tracking on `(kind, body.seq, nodeId/threadId)` itself. Had
I reacted to envelope 5, I would have double-posted a substantial thread turn.

### F4 (moderate) — the body `seq` stream has holes, so the log I stamp against is one I only partly see

Observed body seqs: 0, 1, 3, 5, 6, 8, 9, 10, 13, 14, 15, 17, 18–24, 27, 28, 29.
Missing: 2, 4, 7, 11, 12, 16, 25, 26. Those are page-internal log entries (my
updates arriving, queue transitions) that are never published. So `basedOnSeq` is
stamped against positions in a log the agent can only sample. In practice it
works, but it means an agent cannot reason about "has anything happened since
N" from the event stream alone.

### F5 (moderate) — receipts are not uniformly published, so "did my update land?" is often unanswerable

Fold-time impact updates produced `applied` events for all three (A-2-r1/r2/r3),
and the D6 `invalidate` produced one. But my directly-posted `revise` on D10 and
`informational` on D4 produced **no receipt at all** — only a later `note-read`.
I still do not know whether D10's option list was actually replaced. BRIDGE.md
presents `applied`/`dismissed`/`queued` as "your receipts", which reads as a
guarantee; it is not one. An agent that wants to know the board's real state
after its own write has no way to ask — there is no `GET /bridge/state`.

### F6 (moderate) — `add-node` materialises content the agent cannot read

I successfully added D17 and the human answered it — and I never learned D17's
question text or its option list. I only saw the answer label ("Re-query only
between items, never mid-item, and cap it at one query per item") and had to
reverse-engineer the question. If a later decision had needed to be revised
against D17's options, I could not have written the revision. A node the agent
can create but cannot read is a hole in the state model.

### F7 (moderate) — the missing update kind: I could not create the decision the human explicitly asked for

The human asked, in as many words, to add a question to the grilling map. I could
not. `add-node` accepts exactly two hardcoded ids, and neither was his question.
This is the prototype's canned-board limitation rather than the wire's, but from
the agent's seat it reads as a missing capability, and the failure mode is the
dangerous kind: BRIDGE.md says any other id "does nothing at all" — **a silent
no-op**. Had I not read that sentence carefully I would have posted `add-node
D19`, seen `{"ok": true, "accepted": 1}`, and told the human it was on the board.
The bridge acknowledging an update says nothing about the page honouring it.

**Wanted:** a real `add-node` taking a question, options and prereqs; failing
that, a rejection receipt rather than silence.

### F8 (minor) — no way to express a decision that has no node

The human's criteria-provenance question is a genuine design decision with four
real options, and the best representation available was an `elicit-alert` thread
with an `ask`, landing as an `informational` note on a neighbouring node when
folded. That works, but a decision recorded as a note on someone else's card is
strictly weaker than a node — it has no status, cannot block anything, and
nothing downstream can be revised against it.

### F9 (minor) — `invalidate` has no body text

`invalidate` carries only `summary`, one line. Invalidating a decision is the
heaviest thing an agent can do short of `unsettle`, and it is the one kind with
no room to explain itself. I had to pair it with a separate `informational` on a
different node so the reasoning arrived alongside the block, which means the
human sees the justification and the block as two unrelated items. Give
`invalidate` a `text` field.

### F10 (minor) — `basedOnSeq` semantics when replying to a stale event

Late in the session I wanted to add an impact to a thread whose last human turn
was at body seq 14, while the log stood at 29. The doc says stamp "the event you
are replying to" (14), but the board I was actually reasoning about was the one
at 29. I stamped 29. For `informational` and `thread-turn` it does not matter
because neither ever waits — but for a `revise` it would decide whether the
update lands or conflicts, and the doc gives no rule for "replying to an old
event about the current board".

### F11 (minor) — one notification per update, regardless of kind

Every update I sent generated a notification the human had to clear, including
`thread-turn`s that were already visible inside an open thread. At one point they
cleared seven at once (`note-read` for n-A-1 through n-A-4 and the r-suffixed
impact children). An impact carrying three updates cost three separate
notifications on top of the thread turn that delivered it. BRIDGE.md warns
against information-free notes but the transport itself is generating the noise.

### F12 (minor, harness-side) — no long poll

"Poll every few hundred milliseconds" is not viable for an agent that pays a tool
round-trip per poll. I ran a bounded shell loop against `/bridge/status` (cheaper
than the full event read) and only fetched events when the count moved.
Human-latency gaps ran 15s to 200s, so per-turn polling would have burned the
context window on empty reads. A long-poll or an SSE endpoint would make the
agent side substantially cheaper.

### What worked cleanly

Worth saying, because most of the above is friction: the fold mechanism is
excellent. Attaching an `impact` with three heterogeneous updates to a
conversational turn, and having the human's single fold gesture apply a
board rewrite, a new node and a note — atomically, with receipts for all three —
is the best part of this protocol. `elicit-alert` with `requiresAction: false`
was exactly the right instrument for "this matters but does not block you", and
the `ask` field rendering options inside a thread let me pose a real decision
that the board had no node for. The `pcr` buys/costs/forces triple is a genuinely
good forcing function on the *agent* — writing three honest lines per option
caught at least one option I had phrased too favourably.

### Where my latency actually came from

The brief asked me to answer open threads "reasonably fast", and I did not always.
Measured from the event landing on the bridge to my update being posted, my
replies ran roughly 20–90 seconds. Almost none of that was polling.

The breakdown, largest first:

1. **Composition time, ~80% of it.** The long turns are long. The D1 fold impact
   was four options with twelve `pcr` lines, plus an `add-node` and an
   `informational`, hand-written as one JSON document. The D3 `elicit-alert` was
   four `ask` options with their own `pcr` triples. That is a minute of writing
   whichever way you cut it, and it is the cost of the thing being *real*
   judgement rather than canned strings — the fake agent is fast precisely
   because it is not thinking.
2. **Tool round-trip overhead.** Every poll, every read and every post is a
   separate tool call with its own latency. A single reaction is minimum three
   round-trips: detect, read, post. There is no way to compress that.
3. **Poll cadence, the smallest slice.** I polled `/bridge/status` every 3
   seconds inside a bounded shell loop and only fetched `/bridge/events` when the
   count moved, so detection cost was at most 3s. The doc's "poll every few
   hundred milliseconds" is unusable for an agent that pays a tool round-trip per
   poll — at that rate the context window fills with empty reads.
   Status-polling in shell was the workaround and it worked well; **it should be
   the documented pattern**, because the naive reading of BRIDGE.md leads an
   agent straight into burning its context on nothing.

The one place this genuinely hurt: the human's very first message was `"Zoom
Out?"` in an open thread with no typing indicator on their side, and they waited
~40 seconds looking at an empty panel. BRIDGE.md advises answering "at human
latency, not instantly — a second or three", which is exactly backwards for a
real agent. The problem is not that we are too fast; it is that we are slow and
silent. **The missing primitive is a typing/thinking indicator** — a
zero-content update kind the agent can fire in one cheap round-trip the moment it
picks up a thread turn, so the human sees "the agent is composing" instead of
nothing. That is the single highest-value addition to this protocol.

### Consolidated: update kinds I wanted and did not have

- **A thinking/typing indicator** (above). Highest value; would have fixed the
  worst moment of the session.
- **A real `add-node`** taking a question, options and prereqs, instead of two
  hardcoded ids — this is the one that made me unable to do what the human
  directly asked for (F7).
- **`text` on `invalidate`** (F9). The heaviest kind is the one with no room to
  explain itself.
- **A state read** — `GET /bridge/state` — so an agent can confirm what actually
  landed instead of inferring from receipts that may not come (F5).
- **A rejection receipt for unrecognised updates.** Silent no-op plus
  `{"ok": true, "accepted": 1}` is how an agent ends up confidently telling a
  human something is on the board when it is not (F7).

---

## 3. Left unresolved on the board

- **The D3 criteria-provenance thread (`T-D3-AC`) is open and unanswered.** The
  human asked for it explicitly. Four options are on the table via the `ask`,
  my recommendation is (a) evidence-provenance, and the thread is now foldable —
  folding records the rule as a note on D3. Nothing has been decided.
- **The human's actual request — a new node for it — was never satisfied**, and
  cannot be on this board (F7).
- **D10 is now incoherent and I left it that way.** I revised its options after
  D1, but the human then answered D2 with "never wake" and let me invalidate D6.
  D10 asks when accumulated failure justifies a wake, which under D2=c is fixed
  at "never". It needs the same invalidation D6 got; I held off rather than fire
  two blocking updates in a row, and the human left before it surfaced.
- **D14's prereq chain runs through D10**, so budget exhaustion is unreachable
  until D10 is resolved one way or the other.
- **Unknown whether my D10 revise and D4 note actually applied** (F5) — no
  receipt was ever published for either.
- **Nine decisions untouched:** D5, D7, D8, D9, D11, D12, D13, D15, D16. D11 and
  D12 are the important ones — my D2 note argued they now carry the entire safety
  story, since a never-waking pipeline has no circuit breaker and only the
  landing rule contains a bad night.
