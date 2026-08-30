# CONTEXT — the grilling domain

> The vocabulary of a grilling session: the board the human drives, the agents
> that answer on it, the log underneath, and the review that ends it. It follows
> the root glossary's rule — an entry states a term's meaning and points at
> whatever owns its mechanics, and stops before enumerating fields, thresholds or
> steps. The root `CONTEXT.md` remains authoritative for the repository's own
> vocabulary; where a word appears in both, the entry here says so.
>
> Two drafts under review at the time of writing — the pending-analysis spec and
> its terminal-review child, both dated 2026-08-30 and living on the branch
> spec-9k9.315-pending-analysis — propose vocabulary this file records as
> proposals rather than as settled meaning. Every such entry says which is which.

## Map

The plan under grilling, as a graph of decisions with the prerequisites between
them. It is what the human answers, what the board renders, and the thing the
grill-master and only the grill-master authors changes to. A grilling session is
finished when every decision on the map has come to rest — answered by the human,
or invalidated by an answer that mooted it.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md`.

## Board

The map as the human sees it: the graph beside one column of decision blocks,
with the threads, the inbox and the notices around it. The board is a renderer
and never an authority — it reads the projection the backend hands it and asserts
no state of its own, so a reload asserts nothing and recovers everything. Prose
that says "the board does X" is a claim about the backend's answer as much as
about the page.

Contract: `packages/grillui/src/grillui/page/script.js`.

## Decision

One question on the map, carrying the options on offer, the prerequisites it
waits on, and — once the board owns it — its status, the answer given and the
rationale for whatever last moved it. The same shape states a decision in the
handoff and in both images; the board-side fields exist only in the images,
because a briefing that carried one would be asserting board state nobody has
decided.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Option

One answer on offer for a decision, in the human's voice, labelled in order so
that free text and thread turns can cite it by label. The first option is the
author's recommendation. Two or three is the board's rule and not the renderer's:
one option is a decision made rather than posed, and a fourth is a decision that
was never narrowed.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Trade-off (`pcr`)

The three statements an option may carry — what it buys, what it costs, and what
it forces downstream. It is the human's only route on the board to the reasoning
behind an option, and it rides behind that option's own small icon rather than
behind the decision block. An option that carries none renders no icon and owns
no overlay. The acronym is never expanded in any artifact; the trio is.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U19).

## Marked (`puts_in_question`)

The plan author's prediction that taking a particular option puts named
decisions in question — that they may die, change what they ask, or come to turn
on something else. A mark is a prediction and never a dependency: until the
option is taken it changes no status, places no hold and is display data alone,
and taking it is what obliges the grill-master to rule on each decision named. An
id resolving to no node is ignored rather than refused, since one stale hint
should not reject a whole plan.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D37, §5.7).

Conflict: `packages/grillui/src/grillui/schemas.py` and the `grill-with-ui`
skill each restate the sentence, and only the phrase "rules on" is mechanically
asserted across the three — agreement beyond it is reviewed, not tested.

## Prereq

A decision another decision waits on. A prereq holds its dependent until it is
settled *or* invalidated: an invalidated decision will never settle, so reading
`settled` as the only way through would gate every dependent for the rest of the
session. Every prereq id must resolve to another node in the same plan and the
graph may not cycle, because a dangling prereq strands a decision the frontier
can never reach.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D43).

## Frontier

The set of decisions answerable right now: open, unlocked, and no longer held by
anything. It is the board's word on what may be answered, computed in code and
never a second time by the page. The frontier is also what drives a session —
nobody schedules the human, the frontier does — and it advances by the ordinary
answer path with no agent turn involved.

Contract: `packages/grillui/src/grillui/projector.py`.

## Settled

The status of a decision the human has answered. An answer records an option, or
text in the human's own words, or both; only the human settles a decision, and
revisiting one already settled re-answers it by the same path. A settled decision
stays in every dispatch of every kind, because a projection that trimmed one
would lose a human decision with nothing downstream able to detect the loss.

Contract: `packages/grillui/src/grillui/projector.py`.

## Fog

The masking of a decision whose declared prerequisite is not yet through. Fog is
derived from the board rather than asserted by anyone, and it lifts the two ways
a prereq does. A fogged decision is not at rest and holds the board open.

Contract: `packages/grillui/src/grillui/projector.py`.

## Stale

The status of a settled decision whose support was withdrawn — an answer resting,
at any remove, on an answer that has been unsettled. Staleness travels
transitively through prerequisites and stops at an invalidated decision, which
rests on nothing and supports nothing. A stale decision is not at rest either;
adjudicating it back out is an agent's move on a change the human already made.

Contract: `packages/grillui/src/grillui/projector.py`.

## Lock

Anything that takes a decision off the frontier without settling it. A queued
proposal locks the decision it targets, so nobody answers a question that has a
change waiting on it; a blocking alert locks one the same way. A lock is always
somebody's — an agent's proposal, or an alert it raised — and the board names what
is holding rather than leaving the human to infer it.

Contract: `packages/grillui/src/grillui/projector.py`.

## Mandate

A property of a decision declaring that any answer to it opens a side thread, and
that the thread's conclusion is the only way the decision settles. The answer is
held rather than applied until the thread concludes; abandoning it drops the
answer and returns the decision to open. A mandated thread concludes or is
abandoned and is never parked.

Contract: `packages/grillui/src/grillui/schemas.py`.

## First image

The current map snapshot: the whole board as it stands, folded from the log. It
is what the page renders and what every agent reasons from, and it is a pure
projection — the same log always yields the same bytes, and an image rebuilt from
disk matches one held in memory. The image files on disk are derived caches and
never a recovery source.

Contract: `packages/grillui/src/grillui/projector.py`.

## Second image

The first image plus the per-decision history of what happened to each decision
and why. It is the reverse handoff: the grill-master is handed it whole on every
dispatch, byte-complete, and a thread agent is handed a projection of it. There
is no elision path and no budget that could create one.

Contract: `packages/grillui/src/grillui/projector.py`.

## Handoff

The single file that crosses the gap from the agent that launched a session to
the backend running it: the session's identity, why it is being grilled, what the
grill-master cannot infer, what it must not propose, how hard to push, when to
stop, and the plan itself. It is read once. Once the backend has appended the
briefing to the log the file has no authority at all — editing it mid-session
changes nothing, and a backend whose log is non-empty never opens it.

Contract: `src/user/.agents/skills/grill-with-ui/SKILL.md` assembles it;
`packages/grillui/src/grillui/schemas.py` validates it.

## Session

One grilling from briefing to terminal result. Its identity is its directory
rather than any process: a session outlives the backend serving it, survives a
kill and a restart, and can be captured a week later by a reader who has only the
files. One human drives one session, and only the human ends one.

Contract: `packages/grillui/src/grillui/session.py`.

## Session directory

Everything a grilling leaves behind, in one place: the log, the images, the
briefing, the terminal result, and the recorded dispatch contexts. It is the
session's identity and the whole of what a later reader needs, which is why
capture reads it and nothing else.

Contract: `packages/grillui/README.md`.

## Turn

One agent invocation that answers one gesture and exits. Agents here are
temporal: nothing stays resident between turns, nothing polls, and the backend
alone decides when any agent gets one. A turn is announced, tiered and closed on
the channel it runs on, and a turn whose process died is closed out by the
successor rather than left waiting forever. *Turn* also names one thing said in a
thread, by the human or by an agent.

Contract: `packages/grillui/src/grillui/lane.py`.

## Gesture

Something the human did on the board — answering a decision, saying something in
a thread, folding, parking or closing one, applying or dismissing a queue entry,
calling the doctor, ending the session. Gestures are the only things that move
the board on the human's behalf, and the closed set of them is derived from the
page's own emission table rather than from a list anybody wrote separately.

Contract: `packages/grillui/src/grillui/page/script.js`.

## Judgment

What a grill-master turn is for: ruling on what a gesture costs the rest of the
plan, rather than facilitating a conversation. The distinction is load-bearing
because it decides both what the agent is told it is doing and which seat takes
the turn. A brief that told the map's author to stop short of deciding would be
telling it to abstain from the one thing its turn exists to do.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D44).

## Judgment class

The reading of a gesture, made off the board before any model is called, that
says this turn is a judgment rather than clerical work. The judgment classes are
closed and each is legible from the board alone; a judgment gesture goes straight
to the expert seat with no first-rung turn recorded, and everything else stays on
the first rung. Classing is never a model's opinion of its own reach, and it
writes nothing that outlives the gesture.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Dispatch

One agent being given a turn: the context assembled, recorded to disk, and handed
to a seat. Which agent a dispatch is for is decided from the channel rather than
passed in, because a caller free to name the agent is free to name the wrong one.
Every dispatch is recorded, so what a model was given and what the audit shows
are the same bytes.

Contract: `packages/grillui/src/grillui/dispatch.py`.

## Dispatch context

What one dispatch carries: the briefing, the board, and the channel's own
conversation. It crosses whole. A context that would omit any part of what it
owes raises rather than being written, because the omission is data corruption —
an agent proceeding without a decision the human made minutes ago, with no
receipt or later read able to reveal which part went missing.

Contract: `packages/grillui/src/grillui/dispatch.py`.

## Channel

One lane between the page and an agent: the map's, on which the human makes
gestures and the grill-master returns documents, and one conversational lane per
thread. A channel is a context, and two never merge. What is true of a channel
splits into the transport's connection lifecycle, which is shared, and the
channel's own protocol state, which is not — so one thread stalling says nothing
about any other.

Contract: `packages/grillui/src/grillui/channels.py`.

## Tier

A rung, not a model. There are two and only two — the first rung and the expert
above it — and the number is not configuration: a channel whose first rung was
already the expert would have nowhere to hand a turn up to. Every surface keys on
the rung: the status lane names it, a turn's attribution carries it, and the page
labels each agent turn by the tier that produced it.

Contract: `packages/grillui/src/grillui/tiers.py`.

## First rung

The tier a channel's turns are taken on until something moves them up. It is
named `fast` everywhere the log and the lane speak, which is a statement about
position rather than about speed — the map's first-rung seat is a reasoning model
that is not fast at all.

Contract: `packages/grillui/src/grillui/tiers.py`.

Conflict: the rung's name reads as a claim about latency that
`docs/specs/2026-08-23-grill-master-role.md` (GUI-D46) explicitly does not make.

## Seat

Who occupies a rung on one channel: a transport, a model, and an effort where the
transport takes one. The seat on the first rung is per-channel configuration —
the map's is weighted for ruling and a thread's for discussing — and the expert
seat is one shared configuration for every channel. A seat is what a session may
re-choose without a code change; the rung is not.

Contract: `packages/grillui/src/grillui/tiers.py`.

## Expert

The heavier, slower seat above the first rung, shared by every channel. It is
where a judgment gesture is composed directly, where a failed or incomplete
first-rung turn is re-asked, and where the human's transfer sends a channel. It
is the top: from the expert seat there is no rung above, so a failure there is
recorded rather than handed anywhere.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D45, GUI-D46).

## Transfer

The human's gesture moving one channel to the expert tier, or back. It is per
channel and always available, it carries the accumulated conversation with it,
and it names the action it performs rather than the state it is in. An agent
asserting a transfer in its own reply moves nothing.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U11, GUI-U22).

## Hand-up

The backend re-asking one gesture on the expert seat because the first-rung turn
did not discharge it — a reply that never validated after its retry, or one that
left an obliged decision unruled. It is per gesture and writes nothing that
outlives it, which is what distinguishes it from a transfer: the next clerical
gesture is first-rung again with no entry to undo.

Contract: `packages/grillui/src/grillui/lane.py`.

## Escalation policy

Whether a met escalation condition needs the human's gesture. It is session
configuration with two values and it defaults to needing one. Hard-wiring either
behaviour is refused in both directions — a human who takes every recommendation
pays a confirmation per turn for nothing, and one still learning what the expert
is worth has money spent on their behalf by a condition they never saw fire. A
policy move is attributed on the channel's own status lane, never silent.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Distrust counter

The per-session count of the human saying wordlessly that a first-rung turn was
wrong — dismissing its proposal, or having it pressed to the expert after the
fact. It exists because the human's other gestures on the map channel carry no
text for a transcript condition to read. Once the count crosses its threshold the
policy moves the map channel up and leaves it there; the way back down is the
human's own transfer control. The threshold is a default nobody has defended
under fire, and the observation that would lower the claim is recorded with it.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D48).

## Grill-master

The agent that authors the map: it rules on what every human gesture does to the
rest of the plan, keeps the map honest after each one, and is the only agent that
may change the map. It is a responder and never an initiator — the frontier
drives, not the grill-master — and it speaks to the human only in notices. It
judges when the stop condition is met and says so; ending the session is not its
gesture.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D44).

## Map author

The grill-master's role, named as what it is for. The phrase matters because the
role and the tier are briefed independently: the role part of a standing brief
says what the turn is for and the tier part says how it is taken, and keying the
role to the tier is what once told the map's author to stop short of deciding on
the turn whose whole work was a ruling.

Contract: `packages/grillui/src/grillui/tiers.py`.

Conflict: `docs/specs/2026-08-18-grilling-ui-v1.md` once called the grill-master
"the driving agent", which collides with the backend's own name for itself; the
grill-master role ruling drops that word in favour of *author*.

## Thread agent

The agent serving one side thread. It dialogues with what the human actually
said, recommends and never authors a map change, and says plainly that it cannot
when asked for one — naming the fold as the route that can. It is given the same
board the grill-master is, plus its own thread's turns, and it reads a board that
moved by quoting the record rather than by inferring a cause.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D24, GUI-D39, GUI-D47).

## Backend

The coded process that owns one session — never an agent. It holds the log, mints
the epoch, assigns every sequence, decides when any agent gets a turn, and serves
the page. *Orchestrator* is the same thing under another name. Nothing else may
assert state: a client that believes something the log does not say is wrong by
construction.

Contract: `packages/grillui/AGENTS.md`.

## Document

The one shape every grill-master turn comes back in: the notice the human reads,
the map mutations proposed, the withdrawals, the rulings, and whether the stop
condition is met. There is no prose mode. A reply that does not validate is
refused, retried once on the same seat, and then walks the ladder — it is never
shown to the human as the bytes it arrived in.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D45, §8.10).

## Ruling

The grill-master's verdict on one decision a gesture put in question, with one
line of why. Rulings are how an obligation is discharged, and the check reads them
in code: a verdict that moves a decision is credited only when the same document
also carries the update that moves it, and a verdict that a decision survives is
credited on its sentence alone. No check reads what a `why` means; what the board
does instead is show it, on the decision it rules on.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Stands

The ruling that a decision survives the gesture intact. It is a credited answer
and not a silence, which is the whole point of its existence: a vocabulary that
admitted only death pressed the agent to kill decisions that were alive, and
produced an invalidation whose own rationale said the decision must now be
answered. A `stands` mints a notice targeted at its decision, so the reasoning
renders where the decision is.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D38, GUI-D45).

Conflict: the pending-analysis draft proposes that a `stands` notice arrive
already read, so that an unread mark always means something moved; the merged
artifacts raise it like any other targeted notice.

## Invalidate

Taking a decision out of the flow, carrying the rationale for doing so in the
same item. It is the heaviest thing an agent can do short of unsettling a
decision, which is why the reasoning rides with it rather than arriving as a note
on a neighbour — the human must not read the block and its justification as two
unrelated things. It always waits for the human's apply, and applying one obliges
the next map turn to rule on whatever was resting on it.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Revise

Changing what a decision asks. Supplied fields replace and omitted ones stand, so
a revise says what changed rather than restating the node. It is the way out for
a decision that survives a gesture once what died is dropped from it — which is
why the ruling vocabulary has three verdicts and not one.

Contract: `packages/grillui/src/grillui/projector.py`.

## Add-node

Putting a new decision on the map, with its question, its options and its
prerequisites. Its id is minted by the backend from the position the entry lands
at rather than chosen by the author, and the receipt echoes the node the fold will
later materialise — two readers of one node is how a receipt and a board come to
disagree. A new question overwrites nothing, so an add-node lands rather than
queuing.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Superseded

An author withdrawing its own earlier queue entry. The entry stays in the queue
marked rather than vanishing, and the page drops it from the surface. Superseding
is an author revising itself: a response naming somebody else's entry is ignored.
Where the human already acted on the entry, the withdrawal and the board
disagree, and that goes back to the authoring agent — the only party that knows
what the rewrite was for.

Contract: `packages/grillui/src/grillui/projector.py`.

## Basis

The board position a turn reasoned from, carried on the mutations it proposes.
Where the backend rewrites a supplied basis, the receipt says so: an undocumented
rewrite makes the agent's next turn reason from a board it did not author.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D21).

## Task

**Proposed, not built.** In the pending-analysis draft, one unit of judgment
weighed for one target: keyed by that target over the state upstream of it, at
most one live at a time, superseded rather than queued when upstream moves again.
Its purpose is to make an agent's judgment an unsettled prerequisite, so that a
decision a ruling in flight may move is unanswerable while everything not
downstream stays open. Its modes distinguish weighing a decision's impact from
re-evaluating a review entry.

Design: the pending-analysis draft, PND-D1.

## Pre-ruling

**Proposed, not built.** In the same draft, a task run ahead of the gesture that
would need it — an option's impact on its marked neighbours, computed in the
background so the happy path costs no wait. A pre-ruling is stale once the board
has moved under it, and a stale one is recomputed rather than consumed.

Design: the pending-analysis draft, PND-D6.

Conflict: *pre-ruling* and *pre-mark* name different things one word apart — the
first is cached judgment, the second is the page's display of an option's mark.

## Answer

The human's statement of record on a decision: an option, text in their own
words, or an option with a note riding along. The answer is theirs and not an
agent's — a proposal taken from a thread fills the box and marks the option, and
the human still presses the control that records it, because every converged
answer observed in practice is a qualification in the human's idiom rather than
the agent's sentence taken whole.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D33).

## Apply

The human's gesture landing a queued proposal on the board. It applies what the
authoring agent wrote, unedited by design, and it names the entry by id so what
lands is what the agent proposed. Nothing an agent says rewrites the board
without it.

Contract: `packages/grillui/src/grillui/projector.py`.

Conflict: the pending-analysis draft carves one exception — a task's result may
change its own target directly — which the merged artifacts do not have.

## Dismiss

The human's gesture ending a queued proposal without applying it. The entry
leaves the queue having changed nothing. On the map channel it is also the one
wordless way the human says a turn was wrong, which is what the distrust counter
reads.

Contract: `packages/grillui/src/grillui/projector.py`.

## Inbox

The board's surface for the queue: what is waiting on the human's gesture. It is
told apart from the notification lane by that one property — the inbox holds what
needs an action, and the lane holds what has already happened.

Contract: `src/user/.agents/skills/grill-with-ui/references/help.md`.

## Pending

The queue of what the human has not dealt with yet: the notices they were told
and the map mutations an agent proposed and the board has not taken. The two
share one array because they are the same question to the human and the same
question to the agent, which is dispatched the queue as the board the human is
actually looking at. Answering a decision is dealing with the notices standing on
it.

Contract: `packages/grillui/src/grillui/schemas.py`.

Conflict: the pending-analysis draft uses *pending* in its prose for a decision
under analysis — the opposite state, one nobody may act on — and names the field
`waiting` on the log and the images to avoid exactly this collision. The queue
meaning is the merged one.

## Waiting

**Proposed, not built.** In the pending-analysis draft, the state of a decision
whose impact is being weighed: off the frontier, unanswerable, and named on the
board together with what it waits on, which seat, and since when. The word was
chosen for the log, the images and the thread-agent legend precisely because
*pending* was taken.

Design: the pending-analysis draft.

## Proposal

A map mutation an agent authored that the board has not taken. An agent's update
lands by itself only where landing cannot overwrite what the human decided;
everything else waits. That test is drawn against the board at arrival rather
than at authorship, because the board may have moved while the update was in
flight, and the fold walking the log in order is the only place where "at
arrival" is a fact rather than a guess.

Contract: `packages/grillui/src/grillui/projector.py`.

## Notice

Something an agent said that is addressed to the human. It joins the queue,
carries a control that opens a thread on it, and — where it is about a particular
decision — renders on that decision rather than in a lane of its own. *Notice* is
also the kind of thread opened from one, which anchors to whatever decision the
notice targeted.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U9, GUI-U15).

## Informational

The update kind a notice travels as: it moves no decision and tells the human
something. It is how the grill-master's prose reaches the board at all, since the
map channel has no composer the human can type into, and it is how a `stands`
ruling's reasoning reaches the decision it is about.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Thread

A side conversation with its own agent and its own memory, anchored to a decision
or to the session itself. What is said in one is not in another. A thread has to
be spoken in before it exists — closing an empty pane creates nothing — and its
agent is handed the whole board plus every other live thread reduced to a stub,
reading a stub's full body only when it turns out to matter.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D24).

## Fold

Two things one word. On a thread, *fold* is the human's gesture concluding it and
handing the conclusion to the grill-master, which is the only route by which
anything said in a thread reaches the map. On the log, a *fold* is one gesture
carrying an ordered set of sub-updates applied all of them or none, so there is
no state in which half of it landed. In the projector, *the fold* is the pure
function that turns the log into the images.

Contract: `packages/grillui/src/grillui/projector.py`.

Conflict: the three senses are all live and all current; nothing disambiguates
them but the sentence they sit in.

## Park

Setting a thread aside as a loose end the human may come back to. It is
non-destructive and takes nothing away: the thread stays readable, it is carried
to the end of the session as still open, and an agent may raise it again. It is
distinguished from *close* deliberately, because a thread somebody finished with
and one they meant to return to are different facts about the session.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D29).

Conflict: the root `CONTEXT.md` defines *park* as a tracker state with a typed
reason. The two are unrelated mechanisms sharing a word.

## Conflict

A disagreement the board cannot resolve on its own and hands back to the agent
that caused it: an author withdrawing a queue entry the human had already acted
on. Neither the page nor the backend adjudicates one — only the authoring agent
knows what the rewrite was for, and a backend guessing would rewrite the human's
answer on a rule nobody wrote. Each is handed back once.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Converged answer

The offer a thread agent makes when the conversation has reached what answers the
thread's own decision: the answer in the human's words, the option it builds on
where one fits, and one line of why. It is an offer and never a question, it
restates only what the human already said, and it is live exactly while it rides
the thread's most recent turn. Taking it arms the decision's own controls; the
human still answers.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D31, GUI-D33).

Conflict: this is a *proposal* in the ordinary English sense and is deliberately
not a queue entry — routing it through the queue would block the very answer it
proposes.

## Doctor

The escape hatch when the board and the conversation have drifted apart: an
explicit control sending the grill-master over the whole map and everything
queued with an instruction to reassess. The board is held immutable behind a
notice while the dispatch is outstanding; the backend reports that state rather
than enforcing it, because refusing a write would need a rejection reason and
that vocabulary is closed.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U12).

## Log

The append-only record that is the session's single source of truth. Every
projection is folded from it, every recovery re-reads it, and nothing is ever
rewritten. The briefing is seeded through it rather than around it, which is what
leaves the handoff file with no authority once the session has started.

Contract: `packages/grillui/src/grillui/log.py`.

## Appender

The one way anything reaches the log. It assigns the sequence, writes durably
before anything else can observe the entry, and answers every write with a typed
receipt. It never folds a projection. The sole-author rule is structural because
of it: a thread agent's map mutation is refused here, and no driver holds a second
route to the board.

Contract: `packages/grillui/src/grillui/log.py`.

## Epoch

One process's tenure over a session. A restart mints a new one on a continuing
sequence, and every message in either direction carries it. A client presenting a
stale epoch is told so and self-heals by re-reading state rather than by guessing.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D2).

## Sequence

The position of an entry in the log. It is assigned by the backend alone, strictly
increasing, never reset and never client-supplied. A client's own counter may
travel as opaque data for its own joins and has no ordering authority.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D2).

## Payload

The content of a log entry, whose shape its kind decides. The asymmetry with the
envelope is deliberate: an unrecognised field on the envelope is a refusal, while
an unrecognised field inside a payload is carried through untouched, because the
envelope is this protocol's own vocabulary and a payload is content two ends may
extend ahead of each other.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Receipt

The typed answer every write gets: accepted with the position assigned, duplicate
naming where the key already landed, or rejected naming the reason. There is no
acknowledgement that does not say what happened — an "ok" over a silent no-op is
what lets an agent tell a human something is on the board when it is not. The
rejection vocabulary is closed, and callers switch on it.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Projector

The pure fold from the log into the images: no clock, no randomness, no I/O. It
is also where each update kind's meaning lives — what a revise, an invalidate, an
unsettle or an alert does to a decision — and where an agent's update is judged
against the board at arrival to decide whether it lands or waits. It tolerates
any entry the appender accepted, because a projector that raised on one would
take the session down with it.

Contract: `packages/grillui/src/grillui/projector.py`.

## Status lane

The mechanical record of what is happening to a turn, emitted inside the same
lock that accepted the human's gesture and before any byte leaves the process. No
status entry is ever produced by a model and no code path may make one wait on
one — including the failure path, so an unreachable seat surfaces in milliseconds
instead of as an unbounded silence. It is what lets the page say a message landed.

Contract: `packages/grillui/src/grillui/lane.py`.

## Capture

Folding a session directory into its terminal result, with nothing serving it. It
is invocable by the backend at end-session, by the agent that launched the
session, or by a fresh reader pointed at last week's grilling. Everything
structural is pure code over the log and reproduces byte for byte; the prose
summary is the one part code does not write.

Contract: `packages/grillui/src/grillui/capture.py`, and the `grill-capture`
skill.

Conflict: the root `CONTEXT.md` lists *Capture* as retired vocabulary from the
pre-specification pipeline. The two are unrelated.

## Terminal result

What a finished grilling leaves behind and the whole of what the launching agent
receives beside file references: the session's identity, every decision with its
answer and status, what is still open and what blocks each one, the threads with
their conclusions, and a prose summary. It is never a transcript — the transcript
is referenced, not carried.

Contract: `packages/grillui/src/grillui/capture.py`.

## Gate

Here, the mechanical check a write passes before anything is appended: a fault
the closed rejection vocabulary names comes back as a typed receipt, and a fault
it does not name is refused at the envelope for the whole batch. The name is
shared with the repository's own sense of *gate* — a mechanical check whose
verdict is its exit status — and the two are different mechanisms.

Contract: `packages/grillui/src/grillui/schemas.py`; root `CONTEXT.md` for the
repository sense.

## Review

**Proposed, not built.** In the terminal-review draft, the phase a board enters
once the frontier empties: the expert enumerates acceptance criteria and
edge-case rows, the human disposes of each, and the completion offer is withheld
until every one is accepted. It exists because the board otherwise ends on a
prose stop condition and leaves the readiness gate downstream nothing to read,
where the conversational `grilling` skill ends on enumerated criteria.

Design: the terminal-review draft, TRV-D1.

Conflict: *review* elsewhere in this repository means adversarial code review and
its verdict artifact; the two share only the word.

## Entry

Two things one word, both current. On the log, an *entry* is one appended line.
In the terminal-review draft, an *entry* is one item of the review phase — a
criterion or a taxonomy row — which the human disposes of and which links back to
the decisions it derives from.

Contract: `packages/grillui/src/grillui/schemas.py` for the log sense; the
terminal-review draft for the review sense.

## Criterion

**Proposed, not built.** In the terminal-review draft, one acceptance criterion
enumerated at the end of a session, carrying a stable id and naming the decisions
it derives from, so that a criterion traces to the choice behind it. It is a
record kind on the log rather than a decision, and it may be authored by the
expert or by the human.

Design: the terminal-review draft; the root `CONTEXT.md` for what an acceptance
criterion is in this repository generally.

## Taxonomy row

**Proposed, not built.** In the terminal-review draft, one edge-case category
applied to one criterion — resolved with text, or ruled out with a reason. The
categories are the closed set the `grilling` skill already works through, and a
criterion missing one with no ruling blocks completion.

Design: the terminal-review draft, TRV-A6.

## Disposition

**Proposed, not built.** In the terminal-review draft, where the human has got to
on one review entry. Accept and discuss are the controls; rejection is a
conclusion of a discussion and never a control of its own, so a rejection always
has a recorded reason. Every entry's disposition is carried into the terminal
result as it stood, including the ones still unresolved when the session ended.

Design: the terminal-review draft, TRV-D3.
