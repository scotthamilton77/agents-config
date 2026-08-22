# Grilling UI v1 — the session backend, its protocol, and its surface

**Date:** 2026-08-18
**Status:** Implementation spec.

## 0. What this document is

**A grilling is an interactive design interrogation.** A human brings a plan; an agent
adversarially questions it, decision by decision, until every decision is either settled
or explicitly parked with a named blocker. The human is a single designer working with
agents — the person who owns the design and answers the questions. Nobody else is in the
room.

**What v1 delivers.** One backend process per grilling session, owning an append-only
event log on disk; a browser page that renders the session's board and writes human
gestures back; a two-tier agent drive the backend mints and schedules; side threads with
their own agents; and a session directory that survives the process, so a grilling can be
paused, resumed, and captured into a durable result.

**Upstream of this document** is the work mandate: an interactive HTML grilling experience
with a live question map, decisions the human can revisit, and side threads for anything
that needs more than an answer — prototype-validated before implementation, light theme
only. **Downstream** are the continuation entries at the end of this document, each a unit
of implementation work claiming the requirements it discharges.

**A fresh implementing agent needs this document plus the binding UX reference —
`docs/prototypes/grilling-ui/grilling-ui-prototype-r5.html` and
`docs/prototypes/grilling-ui/REACTIONS.md` — and nothing else.** This document states the
contract; the reference page demonstrates the surface, and the ledger states what the owner
asked of it.

**Vocabulary.** The *grill-master* is the driving agent: it owns the map and is the only
agent that authors changes to it. A *thread agent* serves one side thread. The *backend*
(equivalently, the *orchestrator*) is the coded process — never an agent. On the board: a
decision is *settled* once answered; the *frontier* is the set of decisions answerable now;
*fog* masks decisions whose prerequisites are unmet; a *thread* is a side conversation
anchored to a decision or to the session itself, *parked* when set aside as a loose end
that the human may return to, *closed* when the human is done with it, and *folded* when its
conclusion is applied to the board — *fold-readiness* is the agent declaring that a thread
has reached an applicable conclusion. A thread agent *proposes an answer* when the
conversation has converged on what answers the thread's own decision: an offer the human
arms, edits and takes, changing no map and settling nothing until they do. A *channel* is
one conversational lane between the page and an agent: one for the map, one per thread. In
the handoff file, *impetus* is why the grilling was requested, *posture* is how
adversarially to grill, and *stop_when* is the condition under which the grill-master
should treat the grilling as complete.

---

## 1. Architecture

**GUI-D1 — The session is server-authoritative; the page is a renderer.** One backend
process owns one grilling session. It holds an append-only on-disk event log which is the
single source of truth, mints an epoch at process start, and assigns the single
authoritative sequence number on every entry. Nothing else — not the page, not an agent —
may assert state. Agents read projections and receive receipts; the page reads projections
and receives receipts. A client that believes something the log does not say is wrong by
construction. Without that rule, a page that reconnects and republishes its own initial
board is byte-indistinguishable from a genuine reset, and everything settled since is lost
with no way to tell that it happened.

**GUI-D2 — The session directory is the session's identity; epoch identifies one
process's tenure over it; sequence identifies the position.** A session is its directory
— log, images, handoff, terminal result — and outlives any process serving it. A restart
mints a new epoch on a continuing sequence. Every message in either direction carries the
epoch. A client presenting a stale epoch is told so — refused on write with an
`epoch mismatch` receipt naming both epochs, and refused on read with HTTP 409 — and
self-heals by re-reading session state rather than by guessing. Sequence numbers are
never reset and never assigned by a client; a client's own counter may travel as opaque
data for its own joins, and has no ordering authority.

**GUI-D3 — Two context images, both projections of the log.** Image 1 is the current map
snapshot: every decision with its status, options, answer and prereqs, plus the frontier,
the settled set, the thread bodies and the pending-update queue. Image 2 is image 1 plus
per-decision evolution history — the ordered record of what happened to each decision and
why. Projection is a pure fold over the log with no clock, no randomness and no I/O, so
the same log always yields byte-identical images and an image rebuilt from disk alone
matches one held in memory. Writing the images to disk is a separate persistence step
downstream of the fold; only that step performs I/O. **The image files are derived caches,
never a recovery source** — every rebuild re-folds the log. **Reverse handoff is image 2.**
Agents are never given deltas to reconstruct state from: the grill-master is given image 2,
and a thread agent its projection of it (§8.8).

**GUI-D4 — Dispatch context crosses whole.** Every grill-master dispatch carries the whole
of image 2, byte-complete; every thread-agent dispatch carries the whole of its thread
projection (GUI-D24, §8.8). There is no elision path in v1 and no budget that can create
one: a projector that trims settled decisions out of a dispatch silently loses human
decisions, and nothing downstream can detect the loss — the agent simply proceeds without
a decision the human made minutes earlier. Every dispatch of either kind contains every
settled decision's id and answer text; a dispatch that omits any part of its owed
projection must never happen, and is treated as data corruption.

**GUI-D5 — Append and project must not fail together.** The appender writes the log entry
durably before any projection runs, and the projector must tolerate any log the appender
accepted. A projection error leaves the log intact and surfaces as an error on the status
lane; it never takes the session down and never blocks acceptance of the next event.

## 2. Session lifecycle: the handoff inversion

**GUI-D6 — The main agent writes a handoff file, launches the backend, and steps aside.**
The backend is its own agent harness: it mints its own grill-master and thread agents, and
the browser is a viewer that may arrive late and leave early. A page that owned the board
instead, with an agent attached to a mail slot, cannot survive the browser leaving and
cannot arbitrate between two of them.

**GUI-D7 — The handoff file is the whole of what crosses the gap, and it is read once.**
Its normative shape is the handoff schema in the schema section below: session identity,
`impetus`, `context`, `constraints`, a `grilling_brief` carrying `posture` and `stop_when`,
and a `plan` whose `decisions` are the board's node shape. Those five briefing fields are
load-bearing: without `stop_when` in particular the session never terminates, because an
agent asked to find weaknesses finds them indefinitely. After the backend appends
`session-start`, the handoff file has no further authority — editing it mid-session changes
nothing, and a backend whose log is non-empty ignores it entirely.

**GUI-D8 — Two skills bracket the session.** A `grill-with-ui` skill assembles the handoff
from either impetus — a bare "grill me on this work item", or a design grown out of a
longer conversation — launches the backend, and receives the result. A capture skill
produces the session's terminal result. What returns to the main agent is the terminal
result plus references to the persisted log and images, never a transcript dump.

**GUI-D9 — The session is pausable and resumable from file state alone.** Killing the
backend mid-session and restarting it against the same session directory re-folds the
board, the answers, the thread history and the images from the log — the log is the
recovery source, and any image file present is discarded and rebuilt. A post-restart agent
dispatch carries pre-restart context because the agent is reconstituted from image 2 rather
than from process memory. No resume pointer lives in the handoff; resuming is not a
handoff.

**GUI-D10 — Session end is a human gesture; `stop_when` is what the agent may propose.**
The page carries an explicit end-session action. On it the backend appends a terminal
entry, invokes the capture step, and writes the terminal result into the session directory
alongside the log and the images. An agent that judges `stop_when` satisfied says so to
the human; it does not end the session itself.

**GUI-D29 — Park and close are the two thread-lifecycle gestures, and both are
non-destructive.** Parking a thread sets it aside as a loose end: it is carried to the end
of the session as still open, and the grill-master may raise it again. Closing one declares
the human done with it: a closed thread is never woven into the terminal result's open
items, never listed as a loose end and never raised by an agent, while staying readable on
the board and reopening into an ordinary open thread that takes turns again. Neither
gesture removes anything — the log is append-only, and both cross as page-emitted gesture
kinds in the closed set of §8.3. The terminal result distinguishes the two (§8.7), on a
live end-session and a capture run alike, because a thread the human finished with and a
thread they meant to return to are different facts about the session. Both act on the
thread itself; the panel's close control (GUI-U4) merely dismisses the view and is
neither gesture.

**GUI-D23 — Capture is a code-heavy skill operating on a session directory.** Its core is
the clean decision-log projection: pure code folding the log into the structured part of
the terminal result, with a single agent pass on top for the prose summary. It is
invocable three ways — by the backend on end-session, by the main agent after the session
returns, or by a fresh agent session pointed at a session directory whose log is already
terminal-ready ("we grilled this last week, go capture it"). It reads the session directory
and nothing else, and it never needs the process that ran the session.

**GUI-D28 — The launch path.** The backend serves loopback only, on a default port with a
per-session override, taking the next free port when the default is occupied.
The backend prints the resulting URL; `grill-with-ui` hands that URL to the human, and
nothing opens a browser at it unless the launch was asked to with `--open` — a launch is
usually driven by an agent on the human's behalf, and a tab nobody asked for is noise.

## 3. Agent drive

**GUI-D11 — The fast tier facilitates discussion; it never manufactures information.** The
fast tier is a non-Claude model over OpenRouter, at roughly one second and $0.0002–$0.0008
per turn. The heavy tier is a Claude model driven as `claude -p --resume` CLI turns, which
bills the owner's subscription, at $0.576 for the cold first turn and $0.054 thereafter,
6.5 s standalone and 12–34 s under load; those figures are a floor for a heavier default,
not a ceiling. The fast tier's mandate is quick discussion: answer from the context it was
given, fast, and never assert anything that context does not support. The moment a question
crosses into reasoning, decisioning or implied design, it stops short of deciding and
recommends a handoff to the heavy tier as metadata on its reply — **and who acts on that
recommendation is the session's escalation policy** (GUI-D35). No agent escalates itself
under either policy: the recommendation is a condition the backend evaluates against the
transcript (GUI-D12), never the model's opinion of its own reach, and an agent asserting a
transfer in its own reply moves no channel. Whatever triggers the transfer hands the heavy
tier the channel's accumulated thread rather than only the last message. Both tiers' model
ids are configuration, and so is the effort the heavy tier thinks at; the escalation target
is a Claude model, configured by default to think hard rather than to answer quickly, and
Fable is excluded from v1.

**GUI-D12 — The escalation recommendation is a criterion evaluated against the transcript,
never a self-assessment of competence.** A fast model asked to judge whether a question exceeds its
own ability judges generously and answers anyway — including on a question the human has
explicitly said they cannot resolve. Checkable conditions are what make the recommendation
fire correctly, and they are the sole basis of the metadata GUI-D11 mandates.
V1 conditions, all transcript-evaluable: the human asked for a
commitment rather than another question, on a decision with two or more dependents; the
human has rejected a reframing of the question, or says the trade-off itself is what they
cannot resolve; three or more decisions must be weighed at once. Asking a sharpening
question back is the ordinary move and is not an escalation.

**GUI-D35 — Whether a met condition needs the human's gesture is session configuration, and
it defaults to needing it.** The escalation policy sits beside the model ids and the heavy
tier's effort, and takes one of two values. Under `gated`, the default, a met condition
highlights the transfer control and nothing moves until the human activates it. Under
`autonomous`, the backend itself puts that channel into expert mode the moment a fast reply
meets a condition, so the next turn on that channel goes to the heavy tier carrying the
accumulated thread — the same channel mode and the same transfer the human's activation
produces, reached without the gesture. The policy is standing rather than one-shot: a
later reply meeting a condition on a channel the human sent back to the fast tier escalates
it again. Hard-wiring one behaviour instead is refused in both directions — a session where
the human takes every recommendation pays a confirmation gesture per turn for nothing, and
a session where they are still learning what the heavy tier is worth has money spent on
their behalf by a condition they never saw fire. **The escalation is attributed, not
silent.** The status lane carries a backend-authored transfer entry on that channel — a
phase on the lane's own status kind (GUI-D13) — naming the condition and that the policy
moved it — the phase is `transferred`, and its detail names the condition — and the heavy
turn that follows carries `transfer_source: "policy"` beside its existing
`followed_transfer` flag. A human gesture writes no source: the flag alone already names
the human, so a session under `gated` writes the log it writes today, byte for byte. Both
are fields on what the log already records rather than a new event kind, because a
transfer is a property of how a turn came to be taken and the kind vocabulary of §8.3 is
closed. Per channel, as GUI-D11's transfers already are: an autonomous escalation on one
thread leaves every other channel where it was.

**GUI-D13 — The status lane is mechanical and structurally cannot wait on a model.** The
instant a human turn is accepted, and inside the same lock as the append, the backend
emits status entries — accepted, then composing with its tier — before one byte leaves the
process. That is 0–1 ms against 1 s for a fast reply and 12–34 s for a heavy one. The lane
also carries agent failure: an agent that cannot be reached at all surfaces as an error
phase in milliseconds rather than as an unbounded silence. No status entry is ever
produced by a model, and no code path may make one wait on one.

**GUI-D14 — Only a human turn is owed a reply.** The page also opens agent-authored
threads (a mandate thread whose only turn is the agent's). Those are recorded and left
alone; the lane fires and a dispatch happens only when a human turn is present, so the
backend never answers itself. Answerability is separate from acceptance.

**GUI-D15 — The grill-master's resume chain stays in one process at a time.** A cold
heavy-tier session costs about half a dollar, so the cache TTL is an architectural input:
one process per session is what keeps the resumed-turn discount (a 10× cost drop and a 2.7×
speedup), and a session held open across a long human silence pays the cold-start tax again
when the cache lapses. Implementations may not spread the grill-master's heavy turns across
concurrent processes; a restart under GUI-D9 hands the whole session to a successor process
and pays the cold-start tax once, which is expected and allowed. Thread agents are outside
this rule: they run in separate contexts, concurrently, by design (GUI-D24).

**GUI-D24 — Every side thread is its own channel with its own agent context.** A thread
agent is given the thread projection (§8.8): image 2 with its own thread's turns in full
and every other non-parked thread reduced to a stub — anchor decision id, title, status,
and the applied conclusion when folded; parked threads are absent. Its instructions direct
it to consult the stubs and read another thread's full body through the backend's read
surface only when a stub is relevant to its work. Threads default to the fast tier and
escalate per-thread by the same mechanism as the map channel (GUI-D11, GUI-U11). Thread
agents may run concurrently with each other and with a grill-master turn.

**GUI-D25 — The grill-master is the sole agent author of map mutations.** Thread agents
recommend; they never emit map updates, and a map update arriving on a thread channel is
rejected. When the human folds a thread's conclusion into the map, the backend dispatches
the grill-master carrying that conclusion, and the grill-master returns the structured map
mutation; taking a thread's proposed answer is not a fold but the human answering the
decision (GUI-D33), and dispatches nothing. Routing
it that way is what keeps the grill-master's own conversational context
informed of how the map evolves — a mutation authored anywhere else changes the board
behind the agent that has to reason about it next. Some thread conclusions fold as context
or notification only, with no map update at all; the grill-master decides which, and says
so in its response.

**GUI-D30 — A thread agent dialogues with what the human said; it never fishes for
continuation.** Its turn engages the statements the human actually made and stops there.
It asks a question in two cases only: to clarify what the human is asking, and to surface
something the human is not considering but should be. A closing question appended to keep
the conversation moving is refused — it reads as the agent having nothing left to say, and
it hands the human the work of ending every thread by declining an invitation. This binds
the thread-agent prompt on both tiers.

**GUI-D31 — A thread agent offers its decision's answer as a proposal riding the turn that
reached it.** Where a thread converges on what answers its own anchor decision, the agent's
reply document carries a `proposed_answer` object beside its prose (§8.9): the anchor
decision, the option it builds on where one fits and null where none does, the answer text
in the human's own words, and one line of why the thread reached it. The object rides the
turn's own log entry as a payload key and the projection puts it on that turn (§8.5), the
way superseding rides the turn that supersedes — an offer is something a turn makes while
it says its piece, and the kind vocabulary of §8.3 stays closed. **A proposal is live when
it rides the thread's most recent turn**, which is the whole of the staleness rule: a
second proposal on a later turn retires the first, a human turn retires both, and a
proposal on a thread nobody has spoken in since is the one on offer. Only a thread agent
on a decision-anchored thread may make one, and only for that thread's own anchor: the
grill-master already asserts answers through `settle` under the queue's rules, and a
session-scoped thread (GUI-U16) anchors no decision, so a proposal from either — or one
naming any decision other than the anchor — is dropped, and the turn carries a line naming
the decision offered and why the board did not take it, in place of the object's own bytes:
a reply recognisably offering an answer is never shown to the human as raw JSON, and a
half-shaped reply document carrying one is answered the same way.
**Dropping rather than rejecting is the rule
here and only here**: refusing the write would throw away what the agent said to the human
over a malformed offer nobody has seen yet. Carrying the proposal as an update inside the
turn's `updates` list instead is refused, because that list is map mutations and a thread
channel's map mutation is rejected outright (GUI-D25) — the offer would be unsendable from
the only actor allowed to make it.

**GUI-D32 — The thread agent proposes only what the human has already said, and never asks
whether to.** Its prompt states the condition: the human's own turns carry the answer —
they have stated the qualification themselves, or accepted in their own words one the agent
put to them — and restating that is the whole of the drafting licence. Composing an answer
the human has not endorsed is the agent deciding and calling it convergence. The offer is
the affordance and never a question: the turn says what it takes the thread to have
settled and stops, because *shall I write this back?* is the closing question GUI-D30
refuses under another name, and it hands the human the work of declining. One proposal per
turn, on the anchor decision, built on an option the decision already has or on none —
proposing a new option is a map change and the grill-master's (GUI-D25). Prompting the
agent to test for convergence explicitly, by asking each turn whether the thread has
reached an answer, is refused: it is fishing with a different question, and it trains the
human to spend every turn saying no.

**GUI-D36 — A thread picked back up after being set aside is caught up mechanically, and it
does not resume a chain older than the interval.** A thread set aside by park or close
(GUI-D29) and then reopened has been away while the board moved: decisions it reasoned from
are settled, unsettled, invalidated, revised or newly added, another thread's conclusion among
them where the grill-master turned one into a change (GUI-D25). Its first dispatch after the
reopening carries a **catch-up** — the map events of the interval, in order, folded out of the
log (§8.8) and placed in the dispatch context, so it reaches whichever tier takes that turn. It
is a projection like every other: nothing in it is composed, summarised or inferred by a model,
and a catch-up naming an event the log does not carry is the same corruption a short image 2 is.

**The interval is bounded by gestures, not by wall time**: it runs from the set-aside gesture to
the next human turn on that thread — the turn that reopens it (GUI-D29). Today that turn exists
for a closed thread alone: a parked thread is raised again only as a loose end the agent names,
never by a turn, so it has no interval and no dispatch this rule can fire on. The rule is stated
over the gesture rather than over `close` so that it holds unchanged should park ever take a
reopening turn of its own.

**A map event is an entry that moves a decision, and that is the whole of the definition**: an
entry is one exactly when folding the log through it changes image 1's `decisions` (GUI-D3). A
settle, an add-node, and a revise, unsettle or invalidate that lands are map events at the
sequence they land at; one that waits in the human's queue is a map event at the `apply` entry
that lands it and never at the entry that queued it; and an entry moving no decision — a
status-lane entry, a thread turn, a park, a close, a thread fold, a fold whose every sub-update
queues — is not one, whatever it says. A catch-up entry therefore always names a decision, and an
entry moving several contributes one catch-up entry per decision it moved. Enumerating kinds
instead is refused: a list is a second definition of what changed the map, and it disagrees with
the projector the first time a kind lands one way here and waits the other way there — the human
would be reading a board the catch-up does not describe.

**One fact governs both halves — the interval moved a decision, or it did not.** Where it did,
the catch-up rides that dispatch and the channel's heavy-tier chain is not resumed: the turn
opens a cold chain from the thread's full transcript, which crosses in the dispatch already,
plus the catch-up, and the channel's later turns resume that new chain. Where the interval moved
no decision there is no catch-up and the chain resumes as on any other turn. Resuming the older
chain instead is refused: its accumulated reasoning was formed against a board that has since
moved, and the board crossing whole on the next turn does not correct it — a snapshot states
what is true and never what changed, so a chain already carrying a dozen older snapshots has no
reason to read the newest as a correction rather than as more of the same. Opening a cold chain
on every turn is refused for the opposite reason: it pays the cold-start tax on every thread
turn in the session and forfeits the resume discount GUI-D15 is built to hold, to fix a chain
that is not stale. **The human is told nothing.** No notification is raised (GUI-U15) and no
board element appears; a cold turn on a channel the heavy tier drives is still an expert turn
and still labelled one (GUI-U21), and that label is the whole of what any of this is visible as.

## 4. Protocol

**GUI-D16 — Every write carries an idempotency key and gets a uniform typed receipt.** The
receipt states `accepted` with the assigned sequence, `duplicate` naming the sequence the
key already landed at, or `rejected` naming the reason. There is no acknowledgement that
does not say what happened: an `ok`/`accepted` over a silent no-op is the named
anti-pattern, and it is what lets an agent tell a human something is on the board when it
is not. Rejection reasons v1 must distinguish: missing idempotency key, epoch mismatch,
unknown event kind, unknown node id, an answer carrying neither an option nor text, a
thread event carrying no turn, and a map mutation authored by a thread agent (GUI-D25).

**GUI-D17 — A rejected human action is visible on the page.** The page raises a banner
naming the reason and stating plainly that the message was not recorded and no agent will
answer it, with a dismiss control. A counter is not a surface.

**GUI-D18 — The endpoint set.** A cheap status check returning epoch and current sequence
alone, touching neither log nor images; a state read returning epoch, current sequence and
image 1; an update read taking a cursor and refusing a stale epoch with 409; reads for
image 1 and image 2; and one write endpoint taking a batch of events under an epoch and
returning one receipt per event. Beside the board endpoints sits a session-control surface
for the main-window token — claim, reload retention and take-over — which is connection
control, not board events, and writes nothing into the board record. The state read is what
a page or an agent uses to recover after any doubt, which is why a reconnect asserts
nothing.

**GUI-D19 — The update kinds v1 must carry:**

- The thinking indicator. It is not a kind an agent sends: the status lane of GUI-D13 fires
  it mechanically the moment a turn is picked up, and it is named here so no implementer
  reintroduces it as an agent-authored update.
- A real add-node taking a question, options and prereqs, minting an open node id rather
  than accepting only pre-baked ones, and echoing the materialised node back so the
  agent can later revise other decisions against it.
- Invalidate carrying its own rationale text. Invalidating a decision is the heaviest
  thing an agent can do short of unsettling one, and shipping the reasoning as a separate
  note on a neighbouring node makes the human read the block and its justification as two
  unrelated items.
- Revise, informational, elicit-alert (with a flag for whether it blocks), settle,
  unsettle and resolve-stale, plus the thread kinds below.

Confirming what landed is not an update kind: it is the state read of GUI-D18.

**GUI-D20 — Thread events speak the page's shape.** `thread-created` and `thread-turn`
both carry their content in a `turns[]` array of who/text pairs; `thread-created`
additionally carries its kind, its title and whether it requires action. Backend-authored
replies may carry bare text. One reader handles both shapes, shared by the accept path,
the projector and the driver — a backend written against only one of them passes a scripted
check and rejects the real page.

**GUI-D21 — The atomic fold.** One human gesture applies a conversational turn's declared
impact — a revise, an add-node and an informational together — atomically, with a receipt
for each. Where a basis sequence supplied by the agent is rewritten at fold time, the
receipt states what was applied, as sent or as amended; an undocumented rewrite makes the
agent's next turn reason from a board it did not author.

**GUI-D22 — The orchestrator decides when any agent gets a turn.** Agents are temporal
processes: a heavy turn is one `claude -p --resume` invocation, a fast turn is one API call.
Each runs its turn and exits. No agent-side polling loop exists anywhere — an agent paying
a round-trip per poll burns its turn on transport, and sub-second polling advice must not
appear in any agent-facing material this work ships. The cheap status endpoint of GUI-D18
remains, for the page. The main agent that launched the backend waits on process exit, a
harness function; it does not poll.

**GUI-D26 — Every grill-master dispatch carries the pending queue, and the grill-master may
supersede its own pending updates.** The dispatch context includes the current queue of
updates the human has not yet accepted or applied, so the grill-master reasons about the
board the human is actually looking at. A response may supersede pending updates it
authored earlier: the backend marks the superseded ones and the page drops them from the
pending surface. If the human applied a superseded update before the rewrite landed, that
conflict goes back to the grill-master for reconciliation — neither the page nor the
backend resolves it, because only the authoring agent knows what the rewrite was for. The
common flow is this self-healing one; the escape hatch when it is not enough is the map
doctor (GUI-U12).

**GUI-D27 — Channel state is two layers.** The connection lifecycle belongs to the
transport: `disconnected`, `connecting`, `connected`, `error`. The protocol state belongs
to each channel — one for the map, one per thread: `idle`, `sending`, `awaiting-ack`,
`agent-owes`, `receiving`. Each channel manages its own idempotency and sequencing state,
so one thread stalling says nothing about any other. What is fixed here is the layer split
and the two vocabularies; the transition table is the implementing work's to state.

**GUI-D33 — Taking a proposal arms the decision's answer; the human still answers it.**
The apply-decision control fills the board's own answer controls and nothing else: it
inserts the proposed text into that decision's own-words box after anything already there
rather than over it, so no draft of the human's is discarded by an agent's, and where the
proposal names an option it marks that option's control as the one that records it. Which
control the human then presses is what the answer becomes, and both already exist
(GUI-U5): the option's own control records that option with the box as its note, and the
own-words control records the text alone. That is what lets a proposal built on an option
be taken as the qualification without it, which is how a converged answer that cites its
option only in prose gets recorded. It appends no event, settles nothing, and leaves the
text editable — the answer is the human's statement of record, and every converged answer
observed in practice is a qualification in the human's own idiom rather than the agent's
sentence taken whole. Firing the answer directly on activation is refused: it puts words on
the board the human has not read, and on a decision already settled it would overwrite
their own answer on one click. What the arming leaves behind is provenance — the thread's
id attached to that decision's draft, riding the next answer submitted for that decision as
`from_thread` (§8.9) and discarded with the draft. **The answer that carries it settles the
decision and closes its thread in one entry.** The decision settles by the ordinary answer
path, so the frontier advances by the existing rule and no grill-master dispatch is
involved; the thread reaches GUI-D29's closed state — a line item, not a loose end,
reopening on a further human turn — and records the applied answer text as its conclusion,
so the terminal result names what the thread produced instead of null. It is not GUI-D25's
`folded`: that state is for a conclusion the grill-master turned into a map change, and
this one changes no map. Emitting the close as a second event beside the answer is refused:
two events half-land, and the human is left looking at a settled decision whose thread asks
to be closed again. An answer citing a thread that does not exist is refused as an unknown
thread id, and one citing a thread anchored to another decision is refused with a reason of
its own, added to GUI-D16's closed vocabulary; both append nothing. A proposal taken onto
an already-settled decision re-answers it by that same path, which is what revisiting a
decision already does.

**GUI-D34 — A converged answer is not a queue item.** It never enters the pending queue of
GUI-D26, and there is no dismiss gesture for one: an offer nobody takes is retired by the
next turn on its thread, and spending a log entry on declining it would need an undo the
moment the human changed their mind mid-conversation. Routing it through the queue instead
breaks four ways at once. A queued proposal places a hold on its target decision, so the
offer would block the very answer it proposes — the human could not answer the decision
while a proposal to answer it waited. The queue carries map mutations authored by the
grill-master, so a thread agent's entry in it would arrive as a `settle` and violate the
sole-author rule of GUI-D25 — an agent asserting an answer, where this is the human giving
one. Applying a queue entry applies what the authoring agent wrote, unedited by design, and
the qualification the human adds has no seat in that gesture. And every queue entry travels
in every grill-master dispatch, so a conversational offer on one thread would reach the map
channel as an outstanding board change the grill-master could reason about and supersede,
when no board change was ever proposed.

**GUI-D37 — An option may name the decisions it would put in question, and that naming is
display data.** An option in the map data may carry `puts_in_question`, an array of decision
ids the grill-master expects that option to put in question downstream, authored when it
adds or revises the node and absent from an option that predicts nothing. The page is its
only reader: it changes no status, places no hold, enters no projection but the option it
rides on, and reaches a dispatch as nothing but the bytes of that node. What moves a
decision on the board is still `invalidate` carrying its rationale (GUI-D19), queued like
every other withdrawal and applied by the human (GUI-D26) — the board never shows a decision
invalidated by a pre-mark. Ids resolving to no node are ignored rather than refused, in a
handoff plan and on an agent-authored `add-node` or `revise` alike: a dangling `prereqs` id
must be refused because it strands a decision the frontier can never reach, while a dangling
pre-mark marks nothing, and refusing it would let one stale hint reject a whole plan.
**Writing the pre-mark to the log as a pending invalidate is refused.** A queue entry locks
its target (GUI-D26), so the human could not answer the very decision they were warned
about; it travels in every grill-master dispatch as an outstanding change no agent proposed;
and it needs a dismiss gesture and an undo the moment the human moves to another option. The
queue carries what an agent decided, and a selection is not a decision. **Dispatching the
grill-master to pre-invalidate on selection is refused too.** It spends a model turn on a
gesture the human makes several times per decision, and its answer arrives after theirs —
the warning is worth something only before the answer, and a turn is not that fast — so it
lands on a board that has already moved, having put an invalidate in the log for an option
nobody took.

## 5. The UI surface

The binding reference is `docs/prototypes/grilling-ui/grilling-ui-prototype-r5.html`, read
against the reaction ledger at `docs/prototypes/grilling-ui/REACTIONS.md`. V1 changes it as
follows, and changes nothing else.

- **GUI-U1 — Waiting is always visible.** Whenever the human sends anything an agent owes a
  reply to — a thread turn, an answer awaiting reaction — the page shows that the message
  reached the backend, that work is in progress, and an incrementing timer of how long the
  human has been waiting. This is fed by the mechanical status lane, so it appears
  immediately rather than when a model gets around to it.
- **GUI-U2 — Every message carries a timestamp rendered in the operating system's time
  zone**, thread turns and notifications alike.
- **GUI-U3 — Agent responses are concise by default**, two or three sentences, with
  verbosity only when the human asks for detail. This is a constraint on the grill-master's
  and the thread agents' system prompts as much as on the page.
- **GUI-U26 — Agent turns are written for a human reading once.** Plain, professional
  sentences, the answer before the reasoning, and no term the decision does not need — where
  one is unavoidable it is explained in the same sentence. Like GUI-U3 this is a constraint
  on the shipped system prompts, and it is stated to every role on both tiers rather than
  only to the tier that reasons longest: a rule copied per role is a rule that goes missing
  from the next one.
- **GUI-U4 — Thread panels have a floating header and footer** — title with close and
  pop-out controls pinned at the top, prompt box and action buttons pinned at the bottom —
  so neither scrolls out of view in a long thread.
- **GUI-U18 — A decision's seed prompts are controls on its thread pane.** Where a decision
  carries `talk` (§8.2), its thread pane renders one control per seed field, and activating
  one sends that seed text as the human's turn on the thread. Seed text with no control on
  the surface is data nothing consumes.
- **GUI-U5 — Decisions offer two to three best options, labelled a/b/c** so free text and
  thread turns can reference them by label. Three is a ceiling, not a target. Alongside
  choosing an option and writing free text, the human can select an option *and* attach a
  note.
- **GUI-U19 — Each option's trade-off rides behind that option's own icon.** Where an
  option carries `pcr` (§8.2), a small icon sits beside that option and is the whole of the
  hover target; hovering it raises an overlay carrying that option's three statements —
  what it buys, what it costs, what it forces downstream. An option carrying no `pcr`
  renders no icon and owns no overlay. The decision block is never itself the target: a
  block-sized target fires on every pass of the pointer towards a control inside it, so the
  overlay covers the options at the moment the human is reaching for one. The overlay obeys
  the hover discipline of GUI-U6.
- **GUI-U25 — The option in hand marks what it would put in question, and the mark is the
  page's alone.** While the human has an option in hand — the pointer or the keyboard on that
  option's own control, an option a taken proposal marked (GUI-D33), or an option standing as a
  held answer behind a mandated thread — every decision that option's `puts_in_question` (§8.2)
  names wears a provisional mark, on the map and on its own block, reading as *the option you
  are holding would put this in question*. The mark is presentation state in the sense of
  GUI-U10: it crosses no wire, appends nothing, and a reload with nothing in hand comes back to
  a board without it. One option is in hand at a time, and the sources rank: the pointer on an
  option's control, else keyboard focus on one, else an armed option, else a held one, and
  within armed or held the most recently armed or held wins — the pointer leaving or focus
  moving falls back to the next source that holds, and the marks are that one option's,
  replaced rather than unioned. It clears when the option in hand changes, when none is, and
  when the answer lands — after an answer the board says what image 1 says and nothing more.
  It is drawn distinctly from both states it could be read as: a pending
  hold (GUI-D26), which is a change the agent authored and the human must apply or dismiss, and
  `stale`, which is a decision already undermined. A decision wearing only the pre-mark is on
  the frontier and answerable as it was, and no notification is raised (GUI-U15). GUI-U19's
  small hover target is a rule about an overlay, which occludes the options it is raised over;
  this mark is drawn away from the pointer and occludes nothing, so the whole of an option's
  control is its target. Splitting the answer into a select step and a send step, to give the
  mark a longer interval to live in, is refused: the option's control *is* the answer control
  (GUI-U5) and GUI-D33 rests on that, so the split adds a press to every answer on the board to
  lengthen a warning whose whole value is that it arrives before the first one.
- **GUI-U20 — A decision taller than its pane keeps its header in view.** While any part of
  a decision is in view in the decisions pane, a floating header carrying that decision's id
  and title stays pinned at the top of the pane; it releases when the decision has scrolled
  fully out of view, and when the decision is settled and collapsed. Without it a human
  reading an option list screens below the question it answers has nothing on the page
  naming which decision they are about to answer.
- **GUI-U6 — Hover overlays always hide on click**, and return only on a fresh mouse-enter
  of a zone that owns one.
- **GUI-U7 — One main window per session, enforced by the backend.** The backend mints a
  session token; the first main window claims it and a second main window connecting to the
  same session is refused with a visible explanation. The claim survives a reload of the
  claiming window — the token lives in the page's origin storage scoped to the session — so
  reloading is never a lockout. A genuinely lost claim is recovered by an explicit take-over
  action on the refusing window: taking over invalidates the previous claim, and a
  superseded window that reconnects degrades to a visible you-have-been-superseded notice
  rather than a working board. Pop-out windows are the sanctioned exception and ride the
  parent's token. Concurrent *different* sessions run as separate backend processes.
- **GUI-U8 — The connection indicator splits into three signals**: whether the backend is
  reachable, whether an agent is attached and currently owes a response (the priority
  signal), and the outbox depth of events not yet consumed. A healthy backend with no agent
  must never look identical to a healthy backend with a working one. The indicator
  amalgamates every channel of GUI-D27 worst-state-wins, and expands on demand into a
  diagnostic view showing each channel's own connection and protocol state.
- **GUI-U9 — Informational messages are as concise as possible and carry a Discuss button**
  that opens a thread seeded from the message.
- **GUI-U10 — The notifications window has a mark-all-read control.** Notification
  read-state is presentation state: the page owns it and persists it locally. It is not
  board state, it does not cross the wire, and the server-authority rule of GUI-D1 does not
  reach it.
- **GUI-U15 — The board is the primary display of state; the notification lane carries
  only what the board does not.** A notification is raised only for content authored for
  the human that is not already rendered as board state. Fold receipts, status-lane
  mechanics and internal events are hidden outright rather than summarised into a
  notification — an internal payload on that lane has no reader, and a lane that echoes
  the board teaches the human to stop looking at it. Agent framing about a particular
  decision renders on that decision rather than as a notification. The inbox remains the
  lane for items the human must act on.
- **GUI-U11 — Transfer to expert is a control on every channel**, the map's and each
  thread's, and it is always active. It is visually highlighted when the agent's reply
  metadata recommends escalation (GUI-D11), and under the `gated` policy the human's
  activation is what moves the channel (GUI-D35). Activating it forces the
  next turn on that channel to the heavy tier, carrying the accumulated thread. While the
  heavy tier is driving that channel, activating it sends the next turn on that channel to
  the fast tier instead;
  what the control reads in either position is GUI-U22's.
  A thread pane carries the control from its first paint, before anything has been said in
  it and whether or not the thread exists yet — the human decides who they are asking
  before they ask, and a control that arrives with the first reply arrives one turn after
  the turn it was wanted for. On a thread nothing has created, the mode is carried onto the
  thread the first turn opens, whose name the draft never had. Park, close and fold are not
  offered there: a thread gesture naming no thread is refused, and the pane's own dismissal
  is what closing a draft means.
- **GUI-U21 — Every agent turn is labelled by the tier that produced it.** On a thread and
  on the map channel alike, an agent turn renders as *fast agent* or *expert agent*, read
  from the tier attribution that turn itself carries (§8.3, §8.5). The channel's current
  mode is never the source: reading the mode would relabel every turn taken before a
  transfer as the tier that came after it, and the transcript is the human's only evidence
  that the transfer changed anything.
- **GUI-U22 — The transfer control names the action it performs, not a state.** Its label
  is *Transfer to expert* while the channel is on the fast tier and *Return to fast agent*
  while the heavy tier drives it, styled identically in both positions and carrying no state
  colouring in either — the channel's tier is already legible from the per-turn labels of
  GUI-U21. Rendering it as a state indicator instead — the label naming the tier the channel
  would move to, coloured like a mandate — is refused: a coloured state word on a control
  reads as *where the channel is now*, so the human infers the opposite of what activating
  it does.
- **GUI-U24 — A channel the policy moved says so where it moved, and nowhere else.** Under
  `autonomous` (GUI-D35) the transfer appears on that channel's status lane, naming the
  condition that fired, and the transfer control flips to *Return to fast agent* (GUI-U22)
  with the human having pressed nothing — the control's position follows the channel's mode
  as the lane states it, never the human's own last click, which after a policy transfer
  names the tier the channel has left. No notification is raised: the move is board state
  and the lane already carries it (GUI-U10, GUI-U15). The control stays active throughout,
  so returning the channel to the fast tier is the same gesture it always was.
- **GUI-U23 — A live proposal renders beneath the turn that made it, with one control.**
  The agent's turn is followed by what it proposes — the option it builds on, the answer
  text, and its one-line reason — and an apply-decision control naming the decision it
  would arm. It appears on the thread's most recent turn only (GUI-D31); an earlier turn's
  retired proposal stays readable as part of what was said and carries no control. The
  control renders on an open thread only: parking or closing the thread (GUI-D29) hides it
  while the proposal stays live in the log — though a closed thread reopens only on a
  human turn, which retires the offer it follows (GUI-D31), so a fresh one is needed — and
  a session ended with a proposal nobody took carries it nowhere — the terminal result
  (§8.7) lists decisions and threads, never offers. Activating it brings the anchor
  decision into view with its own-words box filled and the named option's control marked
  (GUI-D33); the human presses one of those two existing controls to answer. Where that
  decision is already settled the control says so, because the human is about to replace
  an answer they gave. Where the decision cannot be answered
  right now — fogged, locked, or held behind another thread — the control is inert and
  names the hold, since arming a box the board will not accept from does nothing the human
  can act on.
- **GUI-U12 — The map doctor is an explicit control** that dispatches the grill-master with
  a reassess-everything instruction over the full map and the pending queue. While it runs
  the page is in immutable mode behind a modal telling the human to wait; the board is
  writable again when the response lands.

- **GUI-U16 — The header names the session and offers help.** The page renders the
  handoff's session title as its header title, and no backend-ownership prose ships in the
  header. An upper-right Help control opens a side thread anchored to the session rather
  than to a decision — a thread whose anchor decision id is null (§8.5), which is the whole
  of the extension the thread model needs for it. The orchestrator primes that thread's
  agent with the UI-behaviour reference material the skill ships (GUI-P1), so it answers
  how to drive the board rather than grilling the design.
- **GUI-U17 — Completion is announced, not assumed.** When every decision is settled the
  page presents an overlay stating that the human has answered every open question, and
  offering an end-session action and a dismiss action. Dismissing returns the human to the
  board and pulses the main end-session control's border, so the offer stays findable
  without a second overlay. End-session attempts to close the tab; where the browser
  refuses to close a tab the page did not open, the page falls back to its inert
  session-over state, carrying a line telling the human the tab can now be closed. Ending
  the session remains the human's gesture (GUI-D10).

- **GUI-U13 — Light theme only.** The page ships a single light palette; no dark-theme
  styles ship in v1.

**GUI-U14 — The carried-forward reference contract.**
Everything else the reference page does — the map beside a single blended column of
answerable and settled decisions, bidirectional focus sync, the auto-apply taxonomy drawn
at "does this overwrite a human decision", the inbox/notification split, pending-update
target locks, the softened conflict paint, agent-adjudicated reassessment, mandated
threads without park, thread fold-readiness with impact preview, bubble overlays, and the
scroll discipline of one scroll intent per human action — is carried forward as specified
by the ledger and demonstrated by the reference page. Reimplementation is not licence to
redesign.

## 6. What v1 does not do

Each item below is deferred, not rejected, with the observation that would pull it in.

- **Elision machinery.** Image 2 crosses whole (GUI-D4); there is no path that drops
  content from a dispatch and no marker vocabulary for one. Trigger: a real session whose
  image 2 approaches the context limit of a tier in use.
- **A tracker bridge.** Separate artifacts, no shared data model, overlap in vocabulary
  only. Trigger: someone wants a session's unfinished map exported as tracker items.

## 7. Placement

**GUI-P1 — The backend ships as a uv package; the skills ship through the admission gate.**
The backend, the projector, the tier drivers and the CLI land as a new uv package under
`packages/`, carrying the standard per-package quality gates and going on PATH through the
installer's CLI package list. The UI surface ships inside that package and is served by the
backend — it is not a deployed skill asset, because it is a program the backend serves
rather than instructions an agent reads. `grill-with-ui` and the capture skill are deployed
skills and must clear the `admit-request` gate on their own merits. The skill ships
reference material about the UI's behaviour and the backend's capabilities, so the
grill-master and the help thread's agent (GUI-U16) can answer "why is the UI blocking me /
why can't I do X" directly in chat instead of guessing.

## 8. Normative schemas

Every schema below is a contract on the bytes, not a suggestion. A field is **required**
unless marked optional; an unknown envelope field is a rejection, not a courtesy. These
schemas are normative for envelopes, images and projections; a payload's per-kind field
schema is the implementing slice's to state, under the protocol decisions above as its
contract. Acceptance criteria bind to these definitions.

### 8.1 The handoff file

One JSON file, written once by the main agent, read once by the backend.

- `handoff_version` — integer. Must be `1`.
- `session` — object:
  - `id` — string. The session directory name and the log's scope. Filesystem-safe.
  - `title` — string. Human-readable session title.
  - `created` — string, ISO-8601 timestamp with time zone.
  - `author` — string. What wrote the handoff.
- `impetus` — string, one paragraph: why this plan is being grilled now.
- `context` — string: what the grill-master cannot infer from the tree.
- `constraints` — array of strings; may be empty. What the grill-master must not propose.
- `help_reference` — optional string. Reference material about driving the board itself,
  handed to the session-scoped help thread's agent (GUI-U16) and to no other dispatch;
  absent, the page offers no Help control.
- `grilling_brief` — object:
  - `posture` — string. How hard to push, and on what axis.
  - `stop_when` — string. The session's termination condition.
- `plan` — object:
  - `statement` — string, one sentence: what is being designed.
  - `decisions` — array of decision nodes (§8.2), non-empty.

A handoff missing any required field is refused with an error naming the field; the
backend does not start a session on a partial briefing. After `session-start` is appended,
the file has no authority (GUI-D7).

### 8.2 The decision node

The same shape in the handoff, in image 1 and in image 2. Board-side status fields exist
only in the images.

- `id` — string, unique within the plan.
- `short` — string. The map label; short enough to render on a node.
- `title` — string. The decision's question as a title.
- `prereqs` — array of decision ids; may be empty. Every id must resolve to another node in
  the same plan, and the graph must be acyclic.
- `body` — string. The question as the human will read it.
- `options` — array of 2–3 option objects (GUI-U5). `options[0]` is the recommendation.
  - `id` — string, the render label: `a`, `b`, `c` in order.
  - `text` — string. The answer, in the human's voice.
  - `pcr` — optional array of exactly three strings: what the option buys, what it costs,
    what it forces downstream.
  - `puts_in_question` — optional array of decision ids the option is expected to put in
    question downstream; the page's to render (GUI-D37), and an id resolving to no node in
    the plan is ignored rather than refused.
- `mandate` — optional object declaring that any answer opens a side thread whose
  conclusion is the only way to settle the decision: `threadId`, `scope`, `title`, `notice`,
  all strings.
- `talk` — optional object of seed text: `why` and `zoom`, each an optional string, since
  each is its own control and either alone is a usable seed. An object carrying neither is
  no talk at all.
- `fogUntil` — optional decision id; `fogTitle` — optional string shown while fogged.
- In the images only: `status` — one of `open`, `settled`, `invalidated`, `stale`, `fogged`;
  `answer` — object or null, carrying `option` (option id or null) and `text` (string or
  null), at least one of which is non-null when `status` is `settled`.

### 8.3 The event log entry

One JSON object per line, appended durably and never rewritten.

- `seq` — integer, assigned by the backend, strictly increasing by one from the session's
  first entry, never reset and never client-supplied (GUI-D2).
- `epoch` — string. The tenure under which the entry was appended.
- `kind` — string. The closed v1 set is the union of the update kinds GUI-D19 mandates,
  the thread kinds of GUI-D20, the page-emitted gesture kinds (derived from the page
  source, GUI-A13), the status-lane kinds of GUI-D13, and the lifecycle kinds
  `session-start` and `session-end`; the implementing slice states the concrete list and
  each kind's payload schema.
- `idempotency_key` — string, required on every client-originated entry, unique within the
  session. Backend-authored entries (status lane, lifecycle) carry a backend-minted key.
- `timestamp` — string, ISO-8601 with millisecond precision, from the backend clock at
  append time.
- `actor` — string: `human`, `grill-master`, `thread-agent` or `backend`.
- `channel` — string: `map`, or the thread id the entry belongs to.
- `payload` — object, shape determined by `kind`. Opaque to sequencing and to the appender.

### 8.4 The receipt

One receipt per submitted event, returned in submission order.

- `status` — string: `accepted`, `duplicate` or `rejected`.
- `idempotency_key` — string, echoed from the submission; null when the rejection reason
  is a missing idempotency key.
- `epoch` — string, the backend's current epoch.

Per variant:

- `accepted` — `seq` (integer, the assigned sequence) and `applied`: an object stating
  `kind` (the update kind applied), `target` (the node or thread id it landed on), `as`
  (`sent` or `amended`), and — required when `as` is `amended` — `amendments`, naming what
  was rewritten field by field (GUI-D21).
- `duplicate` — `seq` (integer, the sequence the key already landed at). Nothing is
  appended.
- `rejected` — `reason` (string, one of the GUI-D16 reasons) and optional `detail`
  (string); an
  `epoch mismatch` rejection carries both the server epoch and the presented one. Nothing
  is appended.

### 8.5 Image 1

The current map snapshot: a pure fold, byte-identical for a given log.

- `epoch` — string; `seq` — integer, the log position this image folds.
- `decisions` — array of decision nodes (§8.2) in board order, carrying their image-only
  status and answer fields.
- `frontier` — array of decision ids answerable now.
- `settled` — array of objects: `id` (string) and `answer` (string, the answer text).
- `threads` — array of objects: `id`, `decision` (decision id or null), `kind`, `title`,
  `requires_action` (boolean), `state` (`open`, `parked`, `closed` or `folded`), and
  `turns` — array of objects: `who` (the §8.3 actor enum), `text` (string), `timestamp`
  (string), and `tier` — optional string, `fast` or `heavy`, present exactly when `who` is
  `grill-master` or `thread-agent` and absent when it is `human` or `backend`. It is what
  makes a turn's tier label (GUI-U21) survive a
  reload: a page rejoining a session reads the board from this image rather than from the
  log entries it was not there for, and a turn projected without its tier can no longer be
  labelled by anything but the channel's current mode. A turn may additionally carry
  `proposal` — the converged-answer object of §8.9, present only on a `thread-agent` turn
  on a decision-anchored thread. Every proposal a turn made projects; which one is live is
  position, not a field (GUI-D31).
- `pending` — array of objects: `id`, `target` (decision id), `kind`, `superseded`
  (boolean), and `authored_at` (sequence integer). This is the queue GUI-D26 dispatches.
  `id` is derived from the authoring entry rather than minted beside it: for an entry
  carrying a single update it is that entry's idempotency key, and for a fold-shaped entry
  — a `fold` or an `apply` — it is `<idempotency key>#<index>`, where the index is the
  sub-update's position in the entry's `updates` array counted before any filtering. The
  derivation is normative because the id is the only stable name a queue entry has, and
  two readers need it: a page persisting presentation state against a queue entry across
  a reload, and anything telling an applied update from a dismissed one in the log. A
  minted id would be stable within one fold and mean nothing to a second reader of the
  same log.

### 8.6 Image 2

Image 1 in full, plus one field:

- `history` — object keyed by decision id; each value is an ordered array of objects:
  `seq` (integer), `timestamp` (string), `kind` (string), `actor` (string), `why` (string,
  the rationale carried by the event that caused the change).

Image 2 is the reverse handoff and crosses to the grill-master whole (GUI-D4).

### 8.7 The terminal result

Written into the session directory at end-session, and the whole of what the main agent
receives beside file references (GUI-D8).

- `session` — object: `id`, `title`, `created`, `ended`, all strings.
- `references` — object: `log`, `image1`, `image2`, all paths relative to the session
  directory.
- `decisions` — array of objects: `id`, `title`, `answer` (string or null), `status` (the
  §8.2 status enum), and `rationale` (string, drawn from the log). Pure code produces this
  array (GUI-D23).
- `open_items` — array of objects: `id` and `blocker` (string) for every decision unsettled
  at end.
- `threads` — array of objects: `id`, `title`, `state` (the §8.5 state enum), and
  `conclusion` (string or null). A parked thread is one of the session's open loose ends
  and a closed thread is a line item only (GUI-D29).
- `summary` — string. The single agent pass's prose, bounded to a briefing and never a
  transcript. It may raise a parked thread as unfinished business; it never raises a closed
  one.
- `stop_reason` — string: how the session ended.

### 8.8 The thread projection

Image 2, transformed for one thread's agent (GUI-D24):

- The dispatched thread appears in full, exactly as in image 2.
- Every other thread whose `state` is not `parked` is replaced by a stub: `id`, `decision`
  (anchor decision id or null), `title`, `state`, and `conclusion` — the applied conclusion
  text, required when `state` is `folded` and absent otherwise.
- Parked threads are omitted entirely.
- Everything else — decisions, history, frontier, settled, pending — is image 2's,
  unchanged.

The projection is a pure fold with the same determinism guarantee as the images (GUI-D3).

A dispatch reopening a set-aside thread additionally carries that interval's catch-up
(GUI-D36): an ordered array of objects — `seq` (integer), `kind` (string), `target` (string, the
decision the entry moved) and `why` (string, the rationale the entry carried and empty where it
carried none) — one per decision moved, in log order, over the map events between the set-aside
gesture and the reopening turn, folded from the log under the same determinism guarantee.

### 8.9 The converged-answer proposal

Two shapes, fixed here rather than left to the implementing slice, because three readers
have to agree on them: the driver reading an agent's reply, the projector putting the offer
on a turn, and the page arming an answer from it.

**In the reply document**, `proposed_answer` is a third key beside `text` and `updates`, and
a document carrying it and prose is a declaring reply like any other:

- `decision` — string. The proposing thread's own anchor decision id; any other value, or
  any value at all from a thread anchoring none, drops the proposal (GUI-D31).
- `option` — string or null: an option id the anchor decision already carries, or null
  where the converged answer stands on none. An id the decision does not carry drops the
  proposal.
- `text` — string, non-empty. The answer in the human's own words, as the thread reached it.
- `because` — string, one line: why the thread converged here. It is shown to the human
  beside the offer and is not part of the answer.

An unusable proposal is dropped and the turn is recorded — carrying what the agent said
where the document had prose, and, either way, one line naming the decision offered and why
the board did not take it. The reply's own bytes are never what the human is shown, and the
write is never rejected. The fence a model wraps the document in is presentation and is read
through whether or not the opening line also carries the object's first characters.

**On the answer**, `from_thread` is an optional string on the `answer` gesture's payload,
beside `target` and `answer`: the id of the thread the answer was armed from. It names a
thread that exists and whose anchor decision is the answered decision, and it is what
closes that thread in the same entry (GUI-D33). Absent, the answer is an ordinary one and
closes nothing.

## 9. Acceptance criteria

Every requirement this spec states is discharged by at least one criterion below.

| Requirement | Criteria |
|---|---|
| GUI-D1 | GUI-A8, GUI-A20 |
| GUI-D2 | GUI-A5, GUI-A6 |
| GUI-D3 | GUI-A1, GUI-A2, GUI-A5 |
| GUI-D4 | GUI-A3 |
| GUI-D5 | GUI-A24 |
| GUI-D6 | GUI-A27, GUI-A42, GUI-A52 |
| GUI-D7 | GUI-A26, GUI-A27 |
| GUI-D8 | GUI-A25, GUI-A29 |
| GUI-D9 | GUI-A5 |
| GUI-D10 | GUI-A28 |
| GUI-D11 | GUI-A12, GUI-A33, GUI-A34, GUI-A53, GUI-A54 |
| GUI-D12 | GUI-A12, GUI-A33 |
| GUI-D13 | GUI-A10 |
| GUI-D14 | GUI-A11 |
| GUI-D15 | GUI-A5, GUI-A36 |
| GUI-D16 | GUI-A7, GUI-A8 |
| GUI-D17 | GUI-A9 |
| GUI-D18 | GUI-A6, GUI-A19, GUI-A20, GUI-A30 |
| GUI-D19 | GUI-A13, GUI-A16, GUI-A17, GUI-A31 |
| GUI-D20 | GUI-A13, GUI-A14 |
| GUI-D21 | GUI-A18 |
| GUI-D22 | GUI-A42 |
| GUI-D23 | GUI-A28, GUI-A32 |
| GUI-D24 | GUI-A3, GUI-A36 |
| GUI-D25 | GUI-A37 |
| GUI-D26 | GUI-A38, GUI-A39 |
| GUI-D27 | GUI-A41 |
| GUI-D28 | GUI-A51 |
| GUI-D29 | GUI-A55 |
| GUI-D30 | GUI-A64 |
| GUI-D31 | GUI-A65, GUI-A66, GUI-A84, GUI-A85 |
| GUI-D32 | GUI-A70 |
| GUI-D33 | GUI-A67, GUI-A68 |
| GUI-D34 | GUI-A69 |
| GUI-D35 | GUI-A71, GUI-A72, GUI-A73, GUI-A74 |
| GUI-D36 | GUI-A75, GUI-A76, GUI-A77, GUI-A78 |
| GUI-D37 | GUI-A79, GUI-A80, GUI-A81, GUI-A82 |
| GUI-U1 | GUI-A21 |
| GUI-U2 | GUI-A22 |
| GUI-U3 | GUI-A43 |
| GUI-U4 | GUI-A44 |
| GUI-U5 | GUI-A45 |
| GUI-U6 | GUI-A46 |
| GUI-U7 | GUI-A19 |
| GUI-U8 | GUI-A23, GUI-A41 |
| GUI-U9 | GUI-A47 |
| GUI-U10 | GUI-A48 |
| GUI-U11 | GUI-A33, GUI-A34, GUI-A35, GUI-A86, GUI-A87 |
| GUI-U12 | GUI-A40 |
| GUI-U13 | GUI-A50 |
| GUI-U14 | GUI-A49 |
| GUI-U15 | GUI-A56 |
| GUI-U16 | GUI-A57 |
| GUI-U17 | GUI-A58 |
| GUI-U18 | GUI-A59 |
| GUI-U19 | GUI-A60 |
| GUI-U20 | GUI-A61 |
| GUI-U21 | GUI-A62 |
| GUI-U22 | GUI-A63 |
| GUI-U23 | GUI-A67 |
| GUI-U24 | GUI-A73, GUI-A74 |
| GUI-U25 | GUI-A81, GUI-A82 |
| GUI-U26 | GUI-A83 |
| GUI-P1 | GUI-A25 |

Each criterion is mechanically checkable and convertible to a red test.

- **GUI-A1** Projection is deterministic: folding a fixed log twice yields byte-identical
  images, and images rebuilt from the on-disk log alone are byte-identical to the
  in-memory ones.
- **GUI-A2** Image 2 carries per-decision history and image 1 does not, over the same log,
  and both validate against their schemas.
- **GUI-A3** Every agent dispatch context contains image 2 in full, byte-identical to the
  image folded at dispatch time. The check reads the backend's own recorded dispatch
  prompts and fails if any byte of image 2 is absent, including every settled decision's id
  and answer text.
- **GUI-A5** Killing the backend mid-session and restarting it against the same directory
  yields a new epoch on a continuing sequence, with settled answers, frontier and thread
  history unchanged; deleting the image files before restart changes nothing, because the
  board is re-folded from the log; the next heavy dispatch after restart contains verbatim
  turns from before the restart.
- **GUI-A6** A write presenting a stale epoch is refused with an `epoch mismatch` receipt
  naming the server and sent epochs; an update read with a stale epoch returns HTTP 409.
- **GUI-A7** Re-posting an event with an already-seen idempotency key returns a
  `duplicate` receipt naming the original sequence and appends nothing, even when the body
  differs. An ordinary first-time write returns `accepted` carrying the assigned sequence
  and its `applied` object.
- **GUI-A8** Each rejection reason in GUI-D16 has a test producing exactly that typed
  receipt, and no rejected event appears in the log.
- **GUI-A9** A rejected human action renders a page-level banner naming the reason and
  stating the message was not recorded, verified in a browser rather than by inspecting
  the code that constructs it.
- **GUI-A10** The accepted and composing status entries are appended under the same lock
  as the human turn, at the two sequence numbers that follow it, before any driver is
  invoked — the dispatching tier's own first sight of the log already holds them — with no
  model call on the path, and composing names the dispatching tier; a run configured with
  an unreachable agent still produces the accepted and error status entries the same way.
- **GUI-A11** An agent-authored thread with no human turn produces no status lane entry
  and no dispatch, while a human turn in the same thread produces both.
- **GUI-A12** For each of the three GUI-D12 conditions, a scripted transcript satisfying it
  produces a reply whose recommendation metadata names that condition; a transcript
  satisfying none produces a reply carrying no recommendation. Under the default `gated`
  policy no transcript escalates a turn without a human activation, and both tiers'
  attributions — tier, model, and that a heavy turn followed a transfer — are in the log.
- **GUI-A13** Every event kind the page emits is known to the backend. The check derives
  the kind set by reading the page's own emission sites out of the shipped page source,
  not from a list the test author wrote, and it is mutation-checked: removing one kind from
  the backend's accepted set turns the suite red naming exactly that kind.
- **GUI-A14** Every scripted stand-in used to verify the page contract derives its message
  shapes from the page's own emissions. A `thread-created` and a `thread-turn` posted in
  the page's `turns[]` form are both accepted and both project into the thread's turn list;
  a stand-in that posts a shape the page never emits fails the check. A `thread-created`'s
  kind, title and requires-action metadata all project, and a backend-authored bare-text
  reply projects into the same turn list.
- **GUI-A16** Add-node mints a node from a question, options and prereqs supplied by the
  agent, echoes the materialised node back in its receipt, and the new node is answerable
  and revisable in the same session.
- **GUI-A17** Invalidate carries rationale text, and that text reaches the page attached
  to the invalidation rather than as a separate note on another node.
- **GUI-A18** One fold gesture carrying a revise, an add-node and an informational applies
  all three or none, with a receipt per update stating what was applied and whether it was
  amended.
- **GUI-A19** A second main window claiming an already-claimed session token is refused
  with a rendered explanation; a reload of the claiming window retains the claim; an
  explicit take-over from a second window succeeds and a reconnecting superseded window
  renders the superseded notice, not a working board; a pop-out presenting the parent
  token is admitted; two backends on different session directories run concurrently
  without interference. No session-control action appends a board event.
- **GUI-A20** A page whose epoch is stale recovers current state through the state read
  without human intervention and without asserting any board content of its own, verified
  by reloading the page mid-session in a browser.
- **GUI-A21** The waiting indicator appears on every turn an agent owes, carries an
  incrementing timer, and is driven by status-lane entries — verified in a browser against
  a deliberately slow heavy-tier turn.
- **GUI-A22** Every message and notification renders a timestamp in the operating system's
  time zone, verified in a browser under a non-UTC `TZ`.
- **GUI-A23** The connection indicator distinguishes backend-unreachable,
  agent-owes-a-response and outbox-depth as three separate signals, each exercised; a
  healthy backend with no attached agent renders distinctly from one whose agent is
  attached and idle.
- **GUI-A24** Killing the image-persistence step's output path (an unwritable image file)
  leaves the log intact and complete, surfaces the failure on the status lane, and does
  not refuse the next event; the fold itself performs no I/O to fail on. An accepted entry
  the projector cannot fold surfaces the same way: status-lane error, log intact, next
  event still accepted.
- **GUI-A25** The deployed skills carry a complete admission record and the UI-behaviour
  reference material; the package's own gate and the repository gate both pass on the
  branch that ships them. The package lives under `packages/` with its CLI registered in
  the installer's CLI package list, and the UI is served by the backend process rather
  than deployed as a skill asset.
- **GUI-A26** A handoff conforming to the handoff schema seeds the board with every
  decision, prereq and option it names; a handoff missing any required field, carrying an
  unknown field, or naming a prereq that resolves to no node is refused with a message
  naming the field, and no session directory is initialised.
- **GUI-A27** A backend started against a directory whose log is non-empty ignores the
  handoff file entirely: editing the handoff mid-session and restarting changes no board
  content, and the edited text appears nowhere in any dispatch.
- **GUI-A28** The end-session action appends a terminal entry to the log, invokes the
  capture step, and leaves a terminal result in the session directory validating against
  its schema; a session whose capture step fails still has its terminal log entry. A
  `session-end` submitted by an agent is rejected and appends nothing.
- **GUI-A29** What `grill-with-ui` returns is the terminal result plus file references and
  nothing else — the check fails if any thread turn or dispatch prompt text appears in the
  returned value.
- **GUI-A30** The status endpoint returns epoch and current sequence, opens neither the log
  file nor an image file (verified by instrumenting file access during the call), and its
  response is stable under a session with a large log. The image 1 and image 2 endpoints
  return schema-valid images, and a batch of N events returns N receipts in submission
  order.
- **GUI-A31** Revise, informational, settle, unsettle, resolve-stale and elicit-alert are
  each accepted, projected
  into image 1, and rendered; elicit-alert's blocking flag is honoured, with the blocking
  variant locking its decision and the non-blocking variant not.
- **GUI-A32** The capture step's decision-log projection is pure code over the log:
  running it twice on a fixed terminal-ready log yields byte-identical structured output,
  and a fresh process pointed at that session directory alone — no backend running, no
  prior context — produces a complete terminal result.
- **GUI-A33** A fast-tier reply that meets a GUI-D12 condition carries escalation
  recommendation metadata that reaches the page, and the page highlights that channel's
  transfer-to-expert control; a reply meeting none carries no such metadata and leaves the
  control unhighlighted.
- **GUI-A34** Activating transfer-to-expert forces the next turn on that channel to the
  heavy tier, and the heavy dispatch contains the channel's accumulated thread rather than
  only the last message; the log attributes the turn to the heavy tier.
- **GUI-A35** While a channel is in expert mode, activating the control returns the next
  turn on that channel to the fast tier — verified in a browser. The control is present and
  active on the map channel and every open thread channel, idle ones included.
- **GUI-A36** Two thread channels take turns concurrently while the map channel is also in
  flight; each thread agent's dispatch contains its own thread's turns and no other
  thread's; escalating one thread leaves the others on the fast tier; and the grill-master's
  heavy turns are all issued by one process at a time.
- **GUI-A37** A map mutation submitted on a thread channel is rejected with the typed
  reason and appended nowhere. Accepting a thread conclusion dispatches the grill-master
  with that conclusion, and the resulting map mutation is attributed to the grill-master; a
  conclusion the grill-master folds as context only produces no map mutation and a response
  that says so.
- **GUI-A38** Every grill-master dispatch context contains the pending queue as of dispatch
  time, with each pending update's id, target and kind — checked against the backend's own
  recorded dispatch prompts.
- **GUI-A39** A grill-master response superseding one of its own pending updates causes the
  backend to mark that update superseded and the page to drop it from the pending surface;
  if the human applied it first, the backend dispatches the conflict back to the
  grill-master and neither the page nor the backend rewrites the board on its own.
- **GUI-A40** The map doctor control dispatches the grill-master with the full map and the
  pending queue, the page refuses every board mutation behind a modal while the dispatch is
  outstanding, and the board becomes writable again when the response lands — verified in a
  browser.
- **GUI-A41** A thread channel in `awaiting-ack` while the map channel is `idle` renders the
  amalgamated connection indicator at the worst channel's state, and the diagnostic
  expansion shows both channels with their own connection and protocol states; a transport
  drop moves every channel's connection layer without changing their protocol states.
- **GUI-A42** No agent-facing code path polls: the shipped agent instructions and drivers
  contain no polling loop, each heavy turn is one invocation that exits, and the main agent
  returns when the backend process exits rather than on a timer. A test that stubs the
  backend's exit proves the main agent was waiting on it.
- **GUI-A43** Every shipped agent system prompt carries the concision constraint, and a
  scripted turn under it returns at most three sentences absent an explicit request for
  detail.
- **GUI-A44** A thread panel scrolled to the bottom of a long thread still shows its title
  with close and pop-out controls and its prompt box with action buttons, verified in a
  browser.
- **GUI-A45** A decision renders two or three options labelled `a`, `b`, `c` in order, and
  submitting an option together with a note records both on the answer.
- **GUI-A46** A visible hover overlay disappears on click and does not return until a fresh
  mouse-enter of a zone that owns one, verified in a browser.
- **GUI-A47** An informational message renders with a Discuss control, and activating it
  opens a thread whose first turn is seeded from that message.
- **GUI-A48** Mark-all-read clears every unread marker, survives a page reload, and emits
  no write to the backend — verified by asserting no event was appended.
- **GUI-A49** Every behaviour GUI-U14 lists is present in the reimplemented page and
  conforms to the reference page's demonstrated behaviour, verified in a browser against
  the reference.
- **GUI-A50** The shipped page contains no dark-theme styles and renders the single light
  palette, verified by inspection of the shipped stylesheet and in a browser.
- **GUI-A51** The backend refuses non-loopback connections, takes the next free port when
  the default is occupied, and reports the resulting URL; `grill-with-ui` opens that URL
  and prints it.
- **GUI-A52** A backend launched against a handoff with no page attached starts the
  session and folds its images; a page arriving late renders the full board from the state
  read; a page that leaves while an agent turn is in flight stops nothing — the reply
  lands in the log and a returning page renders it.
- **GUI-A53** Both tiers' model ids come from configuration: changing the fast-tier id
  changes the model the log attributes the next fast turn to, the default configuration
  names a non-Claude fast tier and a Claude heavy tier, and no configuration this work
  ships names a Fable model.
- **GUI-A54** A fast-tier turn asked for a fact its dispatch context does not contain
  replies without asserting one — it says what it lacks or recommends escalation —
  verified by a scripted turn whose context omits the fact and an assertion check on the
  reply.
- **GUI-A55** Parking a thread and closing one both leave its turns readable on the board
  and append rather than remove, and a closed thread reopens into an open thread that takes
  a further turn. Over one session carrying one of each, the terminal result names the
  parked thread as an open loose end and the closed thread as a line item that no open item
  and no agent-raised item names — asserted identically on the live end-session result and
  on a capture run over the same session directory.
- **GUI-A56** A fold receipt, a status-lane entry and an agent's internal event each raise
  no notification, while an agent message written for the human that the board does not
  already render raises exactly one; an item requiring the human to act lands in the inbox
  and not the notification lane, and agent framing about a decision renders on that
  decision. Verified in a browser.
- **GUI-A57** The page renders the handoff's session title as its header title and the
  header carries no backend-ownership prose; the Help control opens a thread whose anchor
  decision is null, and that thread's recorded dispatch context carries the UI-behaviour
  reference material. Verified in a browser and against the backend's own recorded
  dispatch context.
- **GUI-A58** Settling the last open decision presents the completion overlay carrying an
  end-session and a dismiss action; dismissing it returns a writable board with the main
  end-session control's border pulsing; end-session where the browser refuses to close the
  tab leaves the page in its inert session-over state stating the tab can be closed.
  Verified in a browser.
- **GUI-A59** A decision carrying `talk` renders one control per seed field on its thread
  pane, and activating one posts that seed text as a human turn on that thread; a decision
  carrying no `talk` renders no such control. Verified in a browser.
- **GUI-A60** An option carrying `pcr` renders one icon beside that option, and hovering
  the icon raises an overlay carrying that option's three statements; hovering the decision
  block anywhere the icon is not raises none, and an option carrying no `pcr` renders no
  icon. The overlay hides on click and returns only on a fresh mouse-enter of the icon.
  Verified in a browser.
- **GUI-A61** A decision taller than the decisions pane, scrolled until its own header is
  above the pane's top edge, still renders a floating header carrying that decision's id and
  title; scrolling the decision fully out of view releases it, and so does settling and
  collapsing it. Verified in a browser.
- **GUI-A62** Over a fixture log carrying one `fast` and one `heavy` agent turn on the same
  channel, the page labels the first *fast agent* and the second *expert agent*, on a thread
  and on the map channel alike, and the labels are identical when the same log is rendered
  with the channel in each mode. A page joining that session after both turns renders the
  same labels, which is what the projected turn's `tier` (§8.5) is for. Verified in a
  browser.
- **GUI-A63** The transfer control reads *Transfer to expert* on a channel driven by the
  fast tier and *Return to fast agent* on one driven by the heavy tier, with the same
  styling in both positions and no state colouring in either — verified in a browser and
  against the shipped stylesheet.
- **GUI-A64** Every shipped thread-agent prompt states the no-fishing rule and the two cases
  a question is allowed in, asserted against the prompt the driver actually composes rather
  than against a constant read out of the source; and over one live session's thread turns,
  no turn ends in a question outside those two cases.
- **GUI-A65** A thread agent's reply document carrying a `proposed_answer` records the
  turn's prose and projects the proposal onto that turn with its decision, option, text and
  reason. The same document drops its proposal — recording the prose, appending no
  rejection and rendering no control — when it comes from the grill-master, from a thread
  whose anchor decision is null, when it names any decision other than the thread's anchor,
  or when it names an option that decision does not carry. The check is mutation-tested:
  removing the anchor test turns the suite red naming that case.
- **GUI-A66** Over a fixture of four converged threads taken from a real session, each
  convergence is expressible as one proposal and taking it records exactly what the
  proposal carried. The four are the shapes that occur: an existing option plus a
  qualification narrowing what it means, an existing option plus a qualification adding
  work downstream, an answer that names its option only in its prose, and an answer
  standing on no option at all. The two that name an option record an answer carrying both
  `option` and `text`; the two that do not record `option` as null and `text` alone. A
  clean option swap is an answer recording an `option` with empty `text`; a fixture whose
  four cases are all clean option swaps fails the check.
- **GUI-A67** The apply-decision control renders beneath the thread's most recent turn when
  that turn carries a proposal and nowhere else — not on an earlier turn whose proposal a
  later one retired, and not on a thread whose most recent turn is the human's. Activating
  it inserts the proposed text into the anchor decision's own-words box after text already
  present rather than replacing it, marks the named option's control, leaves the text
  editable, and appends no event — asserted by checking that the log grew by nothing.
  Pressing the marked option then records option and text together; pressing the own-words
  control records the text alone. Where the anchor decision is settled the control says so,
  and where a hold is on it the control is inert and names the hold. Verified in a
  browser.
- **GUI-A68** Submitting an armed answer appends one `answer` entry carrying `from_thread`;
  that single entry settles the decision, moves its thread to `closed`, and advances the
  frontier by the ordinary rule, with no second event and no grill-master dispatch in the
  log. The terminal result reports that thread's conclusion as the applied answer text
  rather than null, on a live end-session and a capture run alike. Taking a proposal onto
  an already-settled decision re-answers it by the same path. An answer whose `from_thread`
  names no thread is rejected as an unknown thread id, and one naming a thread anchored to
  another decision is rejected with its own typed reason; neither appends anything.
- **GUI-A69** A live proposal creates no pending-queue entry, appears in no grill-master
  dispatch context as a pending update, and places no hold on its anchor decision — the
  decision stays answerable by every ordinary route while the proposal stands, verified by
  answering it with an unrelated option while the offer is live. No dismiss gesture exists
  for a proposal: over a fixture where one thread carries two agent turns each proposing,
  only the later turn renders a control and no log entry declines the earlier one.
- **GUI-A70** Every shipped thread-agent prompt states the convergence condition, the
  restatement-only licence and that the offer is never put as a question — asserted against
  the prompt the driver composes rather than a constant read out of the source. Over one
  live session's thread turns, no turn carrying a proposal also asks whether to apply it.
- **GUI-A71** A session configured with no escalation policy runs `gated`: a fast reply
  meeting a GUI-D12 condition carries its recommendation, the log records no transfer, and
  the next turn on that channel is taken by the fast tier.
- **GUI-A72** Under `autonomous`, a fast reply meeting a condition takes the next turn on
  that channel to the heavy tier, whose dispatch carries the channel's accumulated thread
  rather than only the last message, while the next turn on every other channel stays fast;
  a reply meeting no condition leaves its own channel on the fast tier.
- **GUI-A73** An autonomous escalation is attributed in the log: a backend-authored status
  entry on that channel carries the `transferred` phase naming the condition, the heavy turn
  that follows carries `transfer_source: "policy"` where a human-activated transfer carries
  no `transfer_source` and its `followed_transfer` flag is unchanged in shape, an agent
  reply asserting a transfer under either policy moves no channel, and the move appends no
  notification-bearing entry.
- **GUI-A74** After an autonomous escalation the human's control still governs: activating
  it returns the next turn on that channel to the fast tier, and a later reply meeting a
  condition escalates that channel again.
- **GUI-A75** A thread reopened after a set-aside gesture is dispatched with a catch-up exactly
  when at least one entry in the interval between that gesture and the reopening turn changes
  image 1's decisions, and the catch-up carries one entry per decision moved per such entry, in
  log order, each naming that decision and the sequence, kind and rationale the log carries, with
  nothing from outside the interval and nothing composed. Over a fixture whose interval carries
  thread turns, status entries, a park, a thread fold and an update left waiting in the queue, no
  catch-up is produced; applying that queued update inside the interval produces one carrying it
  at the sequence of the apply. The check is mutation-tested: reading the queueing sequence
  instead turns the suite red naming that case.
- **GUI-A76** Where the interval moved a decision, the reopening turn on a heavy-tier channel is
  invoked with no resume identifier and its prompt carries the thread's turns in full beside the
  catch-up. Where that turn's driver returns a session id, that id — and no earlier one — is
  what the next turn on that channel resumes; where it returns none, the channel holds no resume
  record — the record the cold turn set aside is discarded when the turn is opened, not kept
  for a null to fall back on. Asserted against the arguments the driver builds and against the
  per-channel chain record, whose other channels are left as they were.
- **GUI-A77** Where no entry in the interval moved a decision, the reopening dispatch carries no
  catch-up and the turn is invoked with the resume identifier the channel already held, exactly
  as an ordinary turn on a thread nobody set aside.
- **GUI-A78** Reopening a thread raises nothing for the human: over a fixture reopening a thread
  across an interval that moved a decision, no notification is produced, the board projects no
  element it does not project over the same session without the interval, and the log grows by
  the reopening turn, its status entries and the reply alone. The turn's tier label (GUI-U21) is
  the whole of the difference the human can see.
- **GUI-A79** An option carrying `puts_in_question` survives the whole path: a handoff plan
  carrying one loads, an agent-authored `add-node` and `revise` carrying one are accepted, and
  the field projects onto that option in image 1 and image 2, while an option carrying none
  projects without it. An id naming no decision on the board is neither a plan-validation
  error nor a rejection reason — the same fixture with one id replaced by a name nothing
  answers to loads, is accepted, and projects unchanged — while a dangling `prereqs` id in
  that same fixture is still refused.
- **GUI-A80** Nothing about a pre-mark reaches the log. The page-derived kind check (GUI-A13)
  finds no kind for it and no grill-master dispatch context carries it as a pending update;
  over one fixture session driven identically twice, once with `puts_in_question` on every
  option and once with it stripped from all of them, the two logs carry the same entries in
  the same order and the two boards differ in nothing but that field. No decision reaches
  `invalidated` or `stale` by way of a pre-mark: the only routes to either remain the applied
  `invalidate` and `unsettle` of GUI-D19.
- **GUI-A81** Holding an option whose `puts_in_question` names two of the board's decisions
  marks exactly those two, on the map and on their own blocks, and marks no third; an id
  naming no node marks nothing and raises no error. The mark is told apart from a pending
  hold and from `stale` on a fixture carrying one of each at once, a decision wearing only
  the pre-mark is still on the frontier and still answers, and no notification appears.
  Verified in a browser.
- **GUI-A82** The mark follows what is in hand and outlives nothing: when the option in hand
  changes by GUI-U25's ranking — a higher source arriving, or the pointer leaving so a lower
  one holds — the new option's marks replace the old, a lower source arriving beneath a held
  pointer changes nothing, leaving nothing in hand clears them, and
  pressing the option's control to answer leaves a board whose marks are what image 1 alone
  accounts for — the named decisions are not invalidated, and become so only once the
  grill-master's `invalidate` is applied. A reload taken while an option was in hand comes
  back unmarked. Verified in a browser.
- **GUI-A83** Every standing brief a driver composes — the grill-master's and a thread
  agent's, on the fast tier and on the heavy one — carries the register rule: plain
  sentences, the answer before the reasoning, and no term the decision does not need.
- **GUI-A84** One declaring reply document reads the same in all three layouts a model
  writes it in: the object alone, the object under a fence, and the object on the fence's
  own opening line. All three yield the document's prose and the proposal it carried.
- **GUI-A85** An offer the board cannot take reaches the human as a line naming the decision
  it was for and why it was refused, never as the reply's own JSON. On a thread anchoring no
  decision the line is the whole of the turn; on a thread anchored to another decision what
  the agent said stands ahead of it. Neither entry carries the offer.
- **GUI-A86** A thread pane opened before the human has said anything in it carries the
  transfer-to-expert control wholly inside the viewport at first paint, on a thread an agent
  opened and on a draft nothing has created alike, in the slide-out and in a popped-out
  window. Measured as a bounding box against the window, so a control rendered below the
  fold of the pane fails the same way one never rendered does. Verified in a browser.
- **GUI-A87** Transfer activated on a draft is the tier that draft's first turn is taken on:
  the mode recorded under the draft's channel reaches the thread the turn opens, whose name
  the draft never had, and the backend reads it back off that thread's channel and off no
  other.

## 10. Open questions for the implementing work

- **The heavy tier's default model.** V1 makes the model configuration with a Claude
  default; the cost figures in GUI-D11 are a floor for a heavier one. The first real session
  should settle which default is right on cost-per-useful-turn.
- **Whether something better replaces the launch floor.** The v1 launch path is decided
  (GUI-D28); the open question is only whether a better hand-off to the browser replaces
  it.
- **The weight of capture's single agent pass.** The capture step's shape is decided
  (GUI-D23) and its structured output is pure code; what remains open is which tier writes
  the prose summary, whose quality bar differs from a grilling turn's.

## Continuations

- feat: Backend core: event log, epoch and sequence assignment, uniform receipts, idempotency,
  and the state, update and status endpoints — AC: GUI-D1, GUI-D2, GUI-D16, GUI-D18, GUI-A6,
  GUI-A7, GUI-A8, GUI-A30.
- feat: Projector and context images, with the completeness contract and the append/project
  isolation — AC: GUI-D3, GUI-D4, GUI-D5, GUI-A1, GUI-A2, GUI-A3, GUI-A24.
- feat: Status lane and answerability, including the agent-authored-thread case — AC: GUI-D13,
  GUI-D14, GUI-A10, GUI-A11.
- feat: Two-tier agent drive: the fast tier's facilitation mandate, criterion-based escalation,
  the grill-master's single-process resume chain, and orchestrator-scheduled turns — AC:
  GUI-D11, GUI-D12, GUI-D15, GUI-D22, GUI-A12, GUI-A42, GUI-A43, GUI-A53, GUI-A54.
- feat: Update kinds: add-node with echo, invalidate with rationale, the thinking indicator,
  settle/unsettle/resolve-stale/elicit-alert, thread shapes and the atomic fold — AC: GUI-D19,
  GUI-D20, GUI-D21, GUI-A16, GUI-A17, GUI-A18, GUI-A31.
- feat: Page repoint onto the v1 protocol, with visible rejection surfacing, the page-derived
  kind check, the stand-in rule and the carried-forward reference contract — AC: GUI-D17,
  GUI-U14, GUI-A9, GUI-A13, GUI-A14, GUI-A20, GUI-A49.
- feat: UI mandates: waiting indicator, timestamps, concise responses, floating thread chrome,
  labelled options with notes, hover-hide-on-click, connection indicator, concise
  informationals with Discuss, mark-all-read, light theme — AC: GUI-U1, GUI-U2, GUI-U3,
  GUI-U4, GUI-U5, GUI-U6, GUI-U8, GUI-U9, GUI-U10, GUI-U13, GUI-A21, GUI-A22, GUI-A23,
  GUI-A44, GUI-A45, GUI-A46, GUI-A47, GUI-A48, GUI-A50.
- feat: Single-main-window enforcement and concurrent sessions — AC: GUI-U7, GUI-A19.
- feat: Handoff assembly against its schema, session lifecycle and restart-resume — AC: GUI-D6,
  GUI-D7, GUI-D9, GUI-D10, GUI-A5, GUI-A26, GUI-A27, GUI-A28, GUI-A52.
- feat: The capture skill, `grill-with-ui`, the launch path, and the terminal result through the
  admission gate — AC: GUI-D8, GUI-D23, GUI-D28, GUI-A25, GUI-A29, GUI-A32, GUI-A51.
- feat: Thread agents with their own contexts and the sole-author rule for map mutations — AC:
  GUI-D24, GUI-D25, GUI-A36, GUI-A37.
- feat: Pending-queue consistency, supersede handling and the map doctor — AC: GUI-D26, GUI-U12,
  GUI-A38, GUI-A39, GUI-A40.
- feat: The channel state model and its diagnostic surface — AC: GUI-D27, GUI-A41.
- feat: The transfer-to-expert control across the map and thread channels — AC: GUI-U11, GUI-A33,
  GUI-A34, GUI-A35.
- feat: Thread lifecycle: the park and close gestures, their board behaviour, and the
  terminal result's loose-end distinction — AC: GUI-D29, GUI-A55.
- feat: Board-first notification policy — AC: GUI-U15, GUI-A56.
- feat: The session header and its help thread — AC: GUI-U16, GUI-A57.
- feat: The completion overlay and end-session emphasis — AC: GUI-U17, GUI-A58.
- bugfix: The decision seed-prompt controls — AC: GUI-U18, GUI-A59.
- feat: The per-option trade-off overlay behind each option's own hover icon — AC: GUI-U19,
  GUI-A60.
- feat: The sticky decision header over a decision taller than its pane — AC: GUI-U20,
  GUI-A61.
- feat: Per-turn tier labelling on threads and on the map channel — AC: GUI-U21, GUI-A62.
- feat: The transfer control's action labelling — AC: GUI-U22, GUI-A63.
- feat: The thread agent's questioning rule — AC: GUI-D30, GUI-A64.
- feat: The converged-answer proposal on a thread turn: the reply-document key, its
  projection onto the turn, the liveness rule, and the thread-agent prompt that reaches one
  — AC: GUI-D31, GUI-D32, GUI-D34, GUI-A65, GUI-A66, GUI-A69, GUI-A70.
- feat: Applying a converged answer: the control beneath the turn, the armed answer
  controls, and the answer that carries its provenance and closes its thread — AC: GUI-D33,
  GUI-U23, GUI-A67, GUI-A68.
- feat: Autonomous escalation as a session policy: the configured default, the backend-driven
  transfer on a met condition, its attribution, and the control that still returns the
  channel — AC: GUI-D35, GUI-U24, GUI-A71, GUI-A72, GUI-A73, GUI-A74.
- feat: Catching up a reopened thread: the interval's catch-up in its first dispatch, and the
  heavy-tier chain that is opened cold rather than resumed — AC: GUI-D36, GUI-A75, GUI-A76,
  GUI-A77, GUI-A78.
- feat: Option-level downstream pre-marking: the option's `puts_in_question` field, its
  passage through the schemas and the images, and the provisional mark the page raises on the
  option the human has in hand — AC: GUI-D37, GUI-U25, GUI-A79, GUI-A80, GUI-A81, GUI-A82.
- chore: Packaging: the uv package, its gates, and the CLI on PATH — AC: GUI-P1.
- chore: The register every agent turn is written in — AC: GUI-U26, GUI-A83.

## Evidence

How each criterion above is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser cannot be discharged by `test:` — a test that never
opens one proves something else.

- GUI-A1 | open
- GUI-A2 | open
- GUI-A3 | open
- GUI-A5 | open
- GUI-A6 | open
- GUI-A7 | open
- GUI-A8 | open
- GUI-A9 | open
- GUI-A10 | test: packages/grillui/tests/unit/test_lane.py::test_the_lane_lands_with_the_human_turn_rather_than_with_the_reply
- GUI-A11 | open
- GUI-A12 | open
- GUI-A13 | open
- GUI-A14 | open
- GUI-A16 | open
- GUI-A17 | open
- GUI-A18 | open
- GUI-A19 | open
- GUI-A20 | open
- GUI-A21 | open
- GUI-A22 | open
- GUI-A23 | open
- GUI-A24 | open
- GUI-A25 | open
- GUI-A26 | open
- GUI-A27 | open
- GUI-A28 | open
- GUI-A29 | open
- GUI-A30 | open
- GUI-A31 | open
- GUI-A32 | open
- GUI-A33 | open
- GUI-A34 | open
- GUI-A35 | open
- GUI-A36 | open
- GUI-A37 | open
- GUI-A38 | open
- GUI-A39 | open
- GUI-A40 | open
- GUI-A41 | open
- GUI-A42 | open
- GUI-A43 | open
- GUI-A44 | open
- GUI-A45 | open
- GUI-A46 | open
- GUI-A47 | open
- GUI-A48 | open
- GUI-A49 | open
- GUI-A50 | open
- GUI-A51 | open
- GUI-A52 | open
- GUI-A53 | open
- GUI-A54 | open
- GUI-A55 | open
- GUI-A56 | open
- GUI-A57 | open
- GUI-A58 | open
- GUI-A59 | open
- GUI-A60 | open
- GUI-A61 | probe: packages/grillui/tests/browser/sticky_header_probe.py::main
- GUI-A62 | open
- GUI-A63 | open
- GUI-A64 | open
- GUI-A65 | test: packages/grillui/tests/unit/test_convergence.py::test_a_proposal_riding_a_turn_records_the_prose_and_projects_onto_that_turn
- GUI-A66 | test: packages/grillui/tests/unit/test_convergence.py::test_each_convergence_of_the_fixture_session_is_one_proposal_recording_what_it_carried
- GUI-A67 | probe: packages/grillui/tests/browser/apply_decision_probe.py::main
- GUI-A68 | test: packages/grillui/tests/unit/test_convergence.py::test_an_answer_carrying_from_thread_settles_and_closes_in_one_entry
- GUI-A69 | test: packages/grillui/tests/unit/test_convergence.py::test_a_live_proposal_queues_nothing_and_holds_nothing
- GUI-A70 | open
- GUI-A71 | test: packages/grillui/tests/unit/test_transfer.py::test_a_session_with_no_policy_configured_leaves_a_met_condition_to_the_human
- GUI-A72 | test: packages/grillui/tests/unit/test_transfer.py::test_under_the_autonomous_policy_a_met_condition_takes_that_channel_to_the_expert
- GUI-A73 | test: packages/grillui/tests/unit/test_transfer.py::test_a_policy_escalation_is_named_on_the_lane_and_on_the_turn_it_bought
- GUI-A74 | test: packages/grillui/tests/unit/test_transfer.py::test_the_human_takes_a_policy_transfer_back_and_a_later_condition_escalates_again
- GUI-A75 | test: packages/grillui/tests/unit/test_catch_up.py::test_applying_that_queued_update_inside_the_interval_is_one_entry_at_the_apply
- GUI-A76 | test: packages/grillui/tests/unit/test_catch_up.py::test_a_moved_interval_opens_the_heavy_turn_cold_with_the_thread_in_full
- GUI-A77 | test: packages/grillui/tests/unit/test_catch_up.py::test_an_unchanged_interval_resumes_the_chain_the_channel_already_held
- GUI-A78 | test: packages/grillui/tests/unit/test_catch_up.py::test_reopening_a_thread_raises_nothing_to_the_human
- GUI-A79 | test: packages/grillui/tests/unit/test_update_kinds.py::test_an_options_pre_mark_reaches_both_images_as_authored
- GUI-A80 | test: packages/grillui/tests/unit/test_session.py::test_two_sessions_driven_alike_log_the_same_entries_with_the_pre_mark_or_without
- GUI-A81 | probe: packages/grillui/tests/browser/pre_mark_probe.py::main
- GUI-A82 | probe: packages/grillui/tests/browser/pre_mark_probe.py::main
- GUI-A83 | test: packages/grillui/tests/unit/test_tiers.py::test_every_brief_a_driver_composes_carries_the_register_rule
- GUI-A84 | test: packages/grillui/tests/unit/test_drivers.py::test_a_declaring_reply_is_read_through_whatever_fence_it_arrived_in
- GUI-A85 | test: packages/grillui/tests/unit/test_drivers.py::test_an_offer_on_a_thread_anchoring_nothing_is_a_notice_and_not_raw_bytes
- GUI-A86 | probe: packages/grillui/tests/browser/thread_controls_probe.py::main
- GUI-A87 | test: packages/grillui/tests/unit/test_page.py::test_a_transfer_pressed_before_a_thread_exists_is_the_tier_its_first_turn_takes
