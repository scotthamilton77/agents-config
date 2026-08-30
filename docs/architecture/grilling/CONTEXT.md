# CONTEXT — the grilling domain

> The vocabulary of a grilling session: the board the human drives, the agents
> that answer on it, the log underneath, and the review that ends it. It follows
> the root glossary's rule — an entry states a term's meaning and points at
> whatever owns its mechanics, and stops before enumerating fields, thresholds or
> steps. The root `CONTEXT.md` remains authoritative for the repository's own
> vocabulary; where a word appears in both, the entry here says so.
>
> Two merged specs whose slices are not yet built — the pending-analysis spec,
> `docs/specs/2026-08-30-grilling-board-pending-analysis.md`, and its
> terminal-review child, `docs/specs/2026-08-30-grilling-board-terminal-review.md`
> — propose vocabulary this file records as proposals rather than as settled
> meaning. Every such entry says which is which.

---

**The map and its images**

## Map

The plan under grilling, as a graph of decisions with the prerequisites between
them. It is what the human answers and what the board renders. Only one agent
may change it — the grill-master — but the human changes it too, by answering,
and their gestures are what the grill-master's turns respond to.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md`.

## Board

The map as the human sees it, together with the threads, the queue and the
notices around it. The board is a renderer and never an authority: it reads the
projection the backend hands it and asserts no state of its own, which is why a
reload asserts nothing and recovers everything.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D1) for the authority
rule; `packages/grillui/src/grillui/page/script.js` for what the surface does
with it.

## Decision

One question on the map. The same shape states a decision in the briefing and on
the board; what the board owns — its status, the answer given, and why it last
moved — exists only in the projections, because a briefing that carried one would
be asserting board state nobody has decided.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Option

One answer on offer for a decision, in the human's voice, labelled so that free
text and thread turns can cite it. The board bounds how many a decision may
carry, and the skill that writes them states the bound.

Contract: `src/user/.agents/skills/grill-with-ui/SKILL.md`, which is what writes
them; `packages/grillui/src/grillui/schemas.py` validates the shape.

## Trade-off (`pcr`)

What an option is expected to buy, cost and force downstream — what it buys, what
it costs, what it forces downstream, which is the reading the `grill-with-ui`
skill states for the three parts; `pcr` is the acronym over them, and this entry
is where the acronym is expanded. It is the human's only route on the board to
the reasoning behind an option. An option carrying none shows no trade-off and is
otherwise unaffected: what an option puts in question is the mark's business, not
the trade-off's.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U19);
`src/user/.agents/skills/grill-with-ui/SKILL.md` states the three parts.

## Marked (`puts_in_question`)

The plan author's prediction that taking a particular option puts named
decisions in question — that they may die, change what they ask, or come to turn
on something else. A mark is a prediction and never a dependency: until the
option is taken it moves nothing, and taking it is what obliges the grill-master
to rule on each decision named.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D37, §5.7).

Conflict: three surfaces state what a mark is — the v1 spec's §8.2, the schema's
`Option` documentation and the handoff-assembling skill — and only the phrase
"rules on" is asserted across all three. Agreement beyond that phrase is
reviewed rather than tested, which GMR-A8 says in as many words.

## Plan author

Whoever authored the node a decision or option stands on, and with it the marks
and the seed prompt it carries. It is a role attached to a node rather than a
second agent, and it is not another name for the grill-master: the handoff's
author holds it for the plan the session opens on, and the grill-master holds it
only for the nodes it adds or revises. Whoever holds it, a mark is a prediction
the grill-master then rules on.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D37) for who
authors a mark, GUI-D47 for the sentence every thread agent is told;
`packages/grillui/src/grillui/tiers.py` states it.

## Pre-mark

The page showing, while the human has an option in hand, every decision that
option would put in question. It is the mark made visible before anything is
taken: presentation state alone, crossing no wire and appending nothing, so a
reload with nothing in hand comes back to a board without it. One option is in
hand at a time. Not to be confused with *pre-ruling*, which is cached judgment.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U25).

## Prereq

A decision another decision waits on. A prereq stops holding its dependent once
it has left the flow, by either route — reading settlement as the only way
through would gate every dependent of an invalidated decision for the rest of
the session.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D43).

## Frontier

The set of decisions answerable right now. It is the board's word on what may be
answered, computed in code and never re-derived by the page. The frontier is
also what drives a session — nobody schedules the human, the frontier does.

Contract: `packages/grillui/src/grillui/projector.py`.

## Design tree

The plan as the conversational `grilling` skill holds it: every decision
branching into the decisions that hang off it. It is the same structure the
board renders as the map, in the medium that has no board — which is why the
frontier is computed the same way in both.

Contract: `src/user/.agents/skills/grilling/SKILL.md`.

## Round

One pass over the question frontier in the conversational `grilling` skill: the
whole frontier asked at once, then a wait for the human's answers before the
next. It is the conversational analogue of the board's turn-taking, and it has
no counterpart on the board — the board's frontier is standing rather than
batched, so the round does not cross into the grill-master's brief.

Contract: `src/user/.agents/skills/grilling/SKILL.md`.

## Settled

The status of a decision the human has answered. Only the human settles one, and
revisiting one already settled re-answers it by the same path. A settled
decision travels in every dispatch of every kind, because a projection that
trimmed one would lose a human decision with nothing downstream able to detect
the loss.

Contract: `packages/grillui/src/grillui/projector.py` for the status;
`packages/grillui/src/grillui/dispatch.py` for what every dispatch carries.

## Fog

The masking of a decision whose declared prerequisite has not come through. Fog
is derived from the board rather than asserted by anyone, and it lifts the same
two ways a prereq stops holding.

Contract: `packages/grillui/src/grillui/projector.py`.

## Stale

The status of a settled decision whose support was withdrawn — an answer resting,
at any remove, on an answer that has been taken back. Staleness travels through
prerequisites and stops at a decision that has left the flow, which rests on
nothing and so supports nothing.

Contract: `packages/grillui/src/grillui/projector.py`.

## Lock

A hold on an open decision that keeps it off the frontier until the human deals
with what is holding it, and a lock is always somebody's — the board names the
holder rather than leaving the human to infer it. Four kinds hold one today: an
agent's queued proposal on the decision, an alert it raised, a mandated thread
holding the answer the human picked, and any open thread the agent flagged as
requiring action. The drafts propose two more, an impact task weighing the
decision and an open review discussion. Fog is not a lock: a decision waiting on
an unmet prerequisite is *fogged*, a status of its own with nobody holding it.

Contract: `packages/grillui/src/grillui/projector.py` for the board's own lock;
`packages/grillui/src/grillui/page/script.js` for the thread-side holds.

Design: the pending-analysis spec (PND-D5) for the task holder; the
terminal-review draft (TRV-D2) for the review discussion.

## Mandate

A property of a decision declaring that any answer to it opens a side thread,
and that the thread's conclusion is the only way the decision settles. The
answer is held rather than applied until then.

Contract: `packages/grillui/src/grillui/schemas.py`.

Conflict: the v1 spec also uses *mandate* for a clause of an agent's brief — the
facilitation mandate a thread agent carries (GUI-D44, GMR-A1), which is a clause
of a role's brief and not a property of any decision. Unrelated mechanisms
sharing a word.

## History

The record of what happened to each decision and why, carried on the second
image and nowhere else. It exists so that an agent asked why the board moved
quotes the record instead of composing a cause, and so it carries who proposed a
move and what was ruled rather than leaving either to be inferred.

Contract: `packages/grillui/src/grillui/projector.py` records it;
`packages/grillui/src/grillui/schemas.py` holds the shape.

## Rationale

The reasoning carried by whatever last changed a decision's status, kept on the
decision itself. It is what makes a block and its justification one item rather
than two, so the human deciding whether to apply an invalidation reads the
argument for it in the same place.

Contract: `packages/grillui/src/grillui/projector.py`.

## Image 1

The current map snapshot, folded from the log: the whole board as it stands. It
is what the page renders and what every agent reasons from, and it is a pure
projection — the same log always yields the same bytes. The image files on disk
are derived caches and never a recovery source.

Contract: `packages/grillui/src/grillui/projector.py`.

## Image 2

Image 1 plus the history of each decision. It is the reverse handoff: the
grill-master is given it whole on every dispatch, and there is no elision path
and no budget that could create one.

Contract: `packages/grillui/src/grillui/projector.py`.

## Thread projection

Image 2 as one thread's agent is given it: its own thread in full, every other
live thread reduced to enough to know it exists and what it was about. It is not
elision — no decision, answer or history is dropped, only the running
conversation of a thread this agent is not having.

Contract: `packages/grillui/src/grillui/projector.py`.

## Catch-up

What a thread set aside is handed when it is picked up again: the map events that
landed on the board while it was away. It is projected and never composed — an
entry is there because folding the log through it changed the decisions — so a
catch-up naming something the log does not carry is corruption of the same kind
a short image 2 is.

Contract: `packages/grillui/src/grillui/projector.py` folds it;
`packages/grillui/src/grillui/schemas.py` holds the shape.

## Map event

An entry that moves a decision, and that is the whole of the definition: one
exactly when folding the log through it changes image 1's decisions. It is
measured rather than listed, because a list of kinds would be a second
definition of what changed the map and would disagree with the projector the
first time a kind lands one way and waits the other.

Contract: `packages/grillui/src/grillui/projector.py`.

## Handoff

The single file that crosses the gap from the agent that launched a session to
the backend running it: who is grilling what, why now, how hard to push, and the
plan itself. It is read once. Once the briefing has been appended to the log the
file has no authority at all — editing it mid-session changes nothing.

Contract: `src/user/.agents/skills/grill-with-ui/SKILL.md` writes it;
`packages/grillui/src/grillui/schemas.py` validates it.

## `stop_when`

The briefing's statement of what would make the grilling complete. It is the
load-bearing field: an agent asked to find weaknesses finds them indefinitely,
so a session without a stated ending never has one. It is what the grill-master
judges against, and judging it met is as far as an agent goes.

Contract: `src/user/.agents/skills/grilling/SKILL.md` states it;
`docs/specs/2026-08-23-grill-master-role.md` says who judges it;
`packages/grillui/src/grillui/schemas.py` holds the field.

## Posture

The briefing's statement of how hard to push and on what axis — the field beside
`stop_when`, and the other half of what shapes an agent's manner. Where
`stop_when` says when to stop, posture says how to press until then.

Contract: `src/user/.agents/skills/grill-with-ui/SKILL.md` writes it;
`packages/grillui/src/grillui/schemas.py` holds the field.

## Session

One grilling from briefing to terminal result. Its identity is its directory
rather than any process: a session outlives the backend serving it, survives a
restart, and can be captured later by a reader who has only the files.

Contract: `packages/grillui/src/grillui/session.py`.

## Session directory

Everything a grilling leaves behind, in one place — the log, the projections,
the briefing, the result, and the record of what each agent was given. It is the
session's identity and the whole of what a later reader needs.

Contract: `packages/grillui/src/grillui/session.py`;
`packages/grillui/src/grillui/dispatch.py` for the recorded dispatches.

## Session start

The log entry that opens a session, carrying the validated briefing. Seeding the
board through the log rather than around it is what makes the log the only
recovery source, and what leaves the handoff file with no authority the moment
this entry lands. Nobody but the backend may write one.

Contract: `packages/grillui/src/grillui/session.py`.

## Session end

The entry that closes a session, and the human's gesture alone. An agent's
attempt to write one is refused and appends nothing; an agent that judges the
stopping condition met says so and leaves the ending to them. A session may be
ended with work still unfinished — end is a gesture, never an inference from the
board being at rest.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D10).

## Completion offer

What the page shows once it reads the board as finished: an overlay saying
nothing on the board is waiting on the human, and offering to end the session.
Completion is announced rather than assumed, and the offer is never the ending —
dismissing it returns the human to the board, and end stays their gesture. The
criterion owns what *finished* means.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U17).

---

**Turns, seats and dispatch**

## Turn

One agent invocation that answers one gesture and exits. Agents here are
temporal: nothing stays resident between turns, nothing polls, and the backend
alone decides when any agent gets one. *Turn* also names one thing said in a
thread, by the human or by an agent.

Contract: `packages/grillui/src/grillui/lane.py`.

## Gesture

Something the human did on the board. Gestures are the only things that move the
board on the human's behalf, and the closed set of them is derived from the
page's own emission table rather than from a list anybody wrote separately.

Contract: `packages/grillui/src/grillui/page/script.js`.

## Judgment

What a grill-master turn is for: ruling on what a gesture costs the rest of the
plan, rather than facilitating a conversation. The distinction decides both what
the agent is told it is doing and which seat takes the turn — a brief telling the
map's author to stop short of deciding would be telling it to abstain from the
one thing its turn exists to do.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D44).

## Judgment class

The reading of a gesture, made off the board before any model is called, that
says this turn needs judgment rather than clerical work and so goes straight to
the expert seat. The classes are closed and each is legible from the board
alone. Classing is never a model's opinion of its own reach, and it writes
nothing that outlives the gesture — which is why a clerical gesture is not held
at the expert seat by a judgment one before it, though it still goes there if
the channel is in expert mode for another reason.

Contract: `packages/grillui/src/grillui/escalation.py` decides the class;
`packages/grillui/src/grillui/lane.py` decides which seat a turn actually takes.

## Clerical

A gesture that is not a judgment: everything outside the closed set of judgment
classes, which stays on the first rung. The class is the whole distinction — a
clerical gesture is not held at the expert seat by a judgment one before it,
because classing writes nothing that outlives the gesture.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Reshape step

The procedure every grill-master turn follows, carried verbatim in its brief on
both tiers: what a turn does beyond settling the decision in front of it. It is
in the brief rather than in code because no gate can read whether a turn
reshaped the map or merely answered it, and it is the only part of the
conversational skill's method that crosses to the board — the tree, the frontier,
the round and the recommendation are the board's own.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (§5.3).

## Dispatch

One agent being given a turn: the context assembled, recorded to disk, and
handed to a seat. Which agent a dispatch is for is decided from the channel
rather than passed in, because a caller free to name the agent is free to name
the wrong one.

Contract: `packages/grillui/src/grillui/dispatch.py`.

## Dispatch context

What one dispatch carries. It crosses whole: a context that would omit any part
of what it owes raises rather than being written, because the omission is data
corruption — an agent proceeding without a decision the human made minutes ago,
with nothing downstream able to reveal which part went missing.

Contract: `packages/grillui/src/grillui/dispatch.py`.

## Channel

One lane between the page and an agent: the map's, and one per thread. A channel
is a context, and two never merge. What is true of a channel splits into the
transport's connection lifecycle, which is shared, and the channel's own
protocol state, which is not — so one thread stalling says nothing about any
other.

Contract: `packages/grillui/src/grillui/channels.py`.

## Tier

A rung, not a model. The number of rungs is not configuration: a channel whose
lowest rung was already the expert would have nowhere to hand a turn up to.
Every surface keys on the rung — the status lane names it, and each agent turn is
labelled by the tier that produced it.

Contract: `packages/grillui/src/grillui/tiers.py`.

## First rung

The tier a channel's turns are taken on until something moves them up. Its name
in the log is a statement about position rather than about speed.

Contract: `packages/grillui/src/grillui/tiers.py`.

Conflict: the name reads as a claim about latency that
`docs/specs/2026-08-23-grill-master-role.md` (GUI-D46) explicitly does not make —
the map's first-rung seat is a reasoning model, not a fast one. The board still
labels the seat "fast agent"; `agents-config-9k9.327` rules on which the label
follows.

## Seat

Who occupies a rung on one channel: a transport, a model, and an effort where
the transport takes one. The seat on the first rung is per-channel configuration,
weighted for what that channel's turns are for. A seat is what a session may
re-choose without a code change; the rung is not.

Contract: `packages/grillui/src/grillui/tiers.py`.

## Expert

The heavier, slower seat above the first rung, shared by every channel. It is
where a judgment gesture is composed, where a first-rung turn that failed to
discharge its gesture is re-asked, and where the human's transfer sends a
channel. It is the top: a failure there is recorded rather than handed anywhere.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D45, GUI-D46).

## Transfer

The human's gesture moving one channel to the expert tier, or back. It is per
channel and carries the accumulated conversation with it. An agent asserting a
transfer in its own reply moves nothing.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U11, GUI-U22).

## Hand-up

The backend re-asking one gesture at the expert seat because the first-rung turn
did not discharge it. The expert's turn is on the log like any other, attributed
to its seat, so the record shows two turns for the one gesture. What a hand-up
does not do is move the channel — the next gesture starts on the first rung
again — which is what distinguishes it from a transfer. The sources also call it
the *post-reply press*, and the lane calls the act of doing it *pressing* or
*insisting*.

Contract: `packages/grillui/src/grillui/lane.py`;
`docs/specs/2026-08-23-grill-master-role.md` (GUI-D48) for the other name.

## Coverage

What the check on a grill-master reply reads: whether every decision the dispatch
named was ruled on. It is never correctness — a ruling the backend would disagree
with is not a ruling missing — which is what lets the check run in code with no
prose parsing. A `stands` is credited by its reasoning, and an `invalidate` or a
`revise` only where the same document carries that update against that decision.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Escalation

A turn, or a whole channel, going to the expert seat instead of the first rung.
Four mechanisms do it and the artifacts keep them apart: the human's *transfer*
moves a channel; the *escalation policy* moves one on the human's behalf; a
*hand-up* re-asks one gesture; a *judgment class* sends one gesture there before
any first-rung turn. Only the first two outlive the gesture. Each has its own
entry; this one exists because the four are routinely called by the one word.

Contract: `packages/grillui/src/grillui/lane.py` decides which seat a turn takes.

## Escalation policy

Whether a met escalation condition needs the human's gesture. It is session
configuration and it defaults to needing one. Hard-wiring either behaviour is
refused in both directions — a human who takes every recommendation pays a
confirmation for nothing, and one still learning what the expert is worth has
money spent on their behalf by a condition they never saw fire. A policy move is
attributed on the channel's own status lane, never silent.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Distrust counter

The count of a first-rung map turn having been found wanting, from either of two
signals: the human dismissing it, which is their one wordless way of saying it
was wrong, and the backend pressing it to the expert seat because it left a named
decision unruled. It exists because the human's other gestures on the map channel
carry no text for a transcript condition to read. Once the count is high enough
the policy moves the map channel up and leaves it there; the way back down is the
human's own transfer control. The count itself is the running process's and starts
again after a restart — what survives is the move, which is in the log.

Contract: `packages/grillui/src/grillui/lane.py`;
`docs/specs/2026-08-23-grill-master-role.md` (GUI-D48) for the design.

Conflict: GUI-D48 calls the counter "per session and sticky", where the
implementation makes only the resulting transfer durable —
`agents-config-9k9.320`.

Conflict: the lane writes the distrust move onto the status lane
unconditionally, where the transcript-condition path in
`packages/grillui/src/grillui/drivers.py` writes its move only under the
autonomous policy — one mechanism named by *Escalation policy*, two gatings.
`agents-config-9k9.324` rules on which gating is right.

## Grill-master

The agent that authors the map: it rules on what every human gesture does to the
rest of the plan, keeps the map honest after each one, and is the only *agent*
that may change the map. It is a responder and never an initiator — the frontier
drives, not the grill-master — and it speaks to the human only in notices. Also
called the **map author**, which is the same role named by what it is for, and
*the agent that owns the map* on the board's own controls and in the help
material, which is the phrase the human is shown; the
role and the tier are briefed independently, which is why the name matters. The
map's first shape is not its work: the agent running the `grill-with-ui` skill
assembles the handoff, and the grill-master authors every change from there.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D44).

## Thread agent

The agent serving one side thread. It dialogues with what the human actually
said, recommends and never authors a map change, and says plainly that it cannot
when asked for one. It reads a board that moved by quoting the record rather
than by inferring a cause.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D24, GUI-D39, GUI-D47).

## Board legend

The part of a thread agent's brief that tells it how to read a board that moved:
what a decision's status, rationale and history mean, so it quotes the record
rather than composing a cause. Every composed thread-agent prompt carries it, on
both tiers — a legend the heavier seat could infer is still cheaper to state than
a turn spent inferring it wrong.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GMR-A6, GUI-D47).

## Backend

The coded process that owns one session — never an agent. It holds the log,
decides when any agent gets a turn, and serves the page. *Orchestrator* is the
same thing under another name. Nothing else may assert state: a client that
believes something the log does not say is wrong by construction.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D1).

## Map document

The one shape every grill-master turn comes back in. There is no prose mode: a
reply that does not validate is refused and never shown to the human as the bytes
it arrived in. The shape exists because a turn whose rulings went missing into a
typo is the failure it was written to end.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (§8.10).

## Map mutation

A change to the map, authored by an agent. Only the grill-master may author one,
and the rule is structural rather than a prompt: the log refuses a map mutation
from any other channel, wherever it came from.

Contract: `packages/grillui/src/grillui/schemas.py` judges the submission;
`packages/grillui/src/grillui/log.py` is the appender that refuses it.

## Ruling

The grill-master's verdict on one decision a gesture put in question, with the
reasoning behind it. Rulings are how an obligation is discharged, and the check
reads them in code rather than reading prose. No check reads what the reasoning
*means*; what the board does instead is show it, on the decision it rules on.

Contract: `packages/grillui/src/grillui/escalation.py`.

## Mootness obligation

What the gesture a turn is taken on owes the rest of the board: the decisions
that gesture was authored to kill, riding the dispatch as its own field. Two
gestures owe one — an answer taking an option that marks what it puts in
question, and an invalidate the human applied. It is composed from what the board
already carries rather than inferred from prose, and it rides its own field
because a rule an agent has to find in the board is one the first rung does not
find.

Contract: `packages/grillui/src/grillui/escalation.py` composes it;
`packages/grillui/src/grillui/schemas.py` holds the shape.

## Stands

The ruling that a decision survives the gesture intact. It is a credited answer
and not a silence, which is the whole point of its existence: a vocabulary that
admitted only death pressed the agent to kill decisions that were alive, and
produced an invalidation whose own rationale said the decision must now be
answered.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D38, GUI-D45).

Conflict: the pending-analysis spec proposes that a `stands` notice arrive
already read, where the merged artifacts raise it like any other — until
`agents-config-9k9.315.9` builds that slice.

## Invalidate

Taking a decision out of the flow, carrying the reasoning for doing so in the
same item. It is the heaviest thing an agent can do short of unsettling a
decision, and it always waits for the human. Applying one obliges the next map
turn to rule on whatever was resting on it.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Revise

Changing what a decision asks. A revise says what changed rather than restating
the node. It is the way out for a decision that survives a gesture once what
died is dropped from it — which is why the ruling vocabulary has three verdicts
and not one.

Contract: `packages/grillui/src/grillui/projector.py`.

## Unsettle

Taking a decision's answer back: it returns to open and everything resting on it
goes stale. Like an invalidate it always waits for the human, because undermining
a decision they answered is their call and not an agent's.

Contract: `packages/grillui/src/grillui/projector.py`.

## Resolve-stale

The verdict on a decision whose support was withdrawn: it leaves stale, settled
again if its answer survived the withdrawal and open if it did not. It lands
without waiting, because it is the agent adjudicating a change the human already
made rather than proposing one of its own.

Contract: `packages/grillui/src/grillui/projector.py`.

## Add-node

Putting a new decision on the map. Its id is minted by the backend rather than
chosen by the author, and the receipt echoes the node the projection will later
materialise — two readers of one node is how a receipt and a board come to
disagree. A new question overwrites nothing, so an add-node lands rather than
queuing.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Superseded

An author withdrawing its own earlier queue entry. Superseding is an author
revising itself: a response naming somebody else's entry is ignored. Where the
human already acted on the entry, the withdrawal and the board disagree, and
that becomes a conflict.

Contract: `packages/grillui/src/grillui/projector.py`.

## Basis

The board position a turn reasoned from, carried on the mutations it proposes.
Where the backend rewrites a supplied basis, the receipt says so: an
undocumented rewrite makes the agent's next turn reason from a board it did not
author.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D21).

## Impact task

**Proposed, not built.** In the pending-analysis spec, one unit of judgment
weighed for one target decision, so that an agent's judgment becomes an
unsettled prerequisite: a decision a ruling in flight may move is unanswerable
while everything not downstream stays open. The draft calls the genus a *task*
and gives it a second mode, the *review task*, over a review entry rather than a
decision.

Design: the pending-analysis spec, PND-D1.

## Pre-ruling

**Proposed, not built.** In the same draft, a task run ahead of the gesture that
would need it, so the expected path costs no wait. A pre-ruling the board has
moved under is recomputed rather than consumed.

Design: the pending-analysis spec, PND-D6.

Conflict: *pre-ruling* and *pre-mark* name different things one word apart — the
first is cached judgment, the second is the page's display of an option's mark.

---

**The human's gestures**

## Answer

The human's statement of record on a decision. The answer is theirs and not an
agent's: a proposal taken from a thread fills the box, and the human still
presses the control that records it, because every converged answer observed in
practice is a qualification in the human's idiom rather than the agent's
sentence taken whole.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D33).

## Apply

The human's gesture landing a queued proposal on the board. It applies what the
authoring agent wrote, unedited by design. Nothing an agent says rewrites the
board without it.

Contract: `packages/grillui/src/grillui/projector.py`.

Conflict: the pending-analysis spec carves one exception — a task's result may
change its own target directly — which the merged artifacts do not have until
`agents-config-9k9.315.5` builds that slice.

## Dismiss

The human's gesture ending a queued proposal without applying it. On the map
channel it is also the one wordless way the human says a turn was wrong, which
is what the distrust counter reads.

Contract: `packages/grillui/src/grillui/projector.py`.

## Inbox

The board's surface for the queued proposals alone: the map mutations waiting on
the human's gesture. It is not the surface for the whole queue — the notices in
the same queue render in the notification lane and on the decisions they are
about. The split is by what the item needs: the inbox holds what needs an action,
and the lane holds what has already happened.

Contract: `packages/grillui/src/grillui/projector.py` folds the queue;
`packages/grillui/src/grillui/page/script.js` renders both surfaces;
`docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U15) for a notice rendering on its
decision.

## Pending

The queue of what the human has not dealt with yet: the notices they were told
and the map mutations an agent proposed and the board has not taken. The two
share one queue because they are the same question to the human and the same
question to the agent, which is dispatched the queue as the board the human is
actually looking at. One queue, two surfaces: the proposals in the inbox and the
notices in the notification lane and on the decisions they name.

Contract: `packages/grillui/src/grillui/projector.py`.

## Waiting

A decision off the frontier and unanswerable, with what it waits on named beside
it. The board already labels a decision held by an unmet prerequisite or by an
unjudged conflict this way, and the pending-analysis spec extends the same sense
to a decision whose impact is being weighed. *Pending* is the human's queue of
what to act on; waiting is the opposite state, one nobody may act on, which is
why the two are different words.

Contract: `packages/grillui/src/grillui/page/script.js` for what the board labels
today; the pending-analysis spec (PND-D5) for the proposed extension.

## Proposal

A map mutation an agent authored that the board has not taken. An agent's update
lands by itself only where landing cannot overwrite what the human decided. That
test is drawn against the board at arrival rather than at authorship, because the
board may have moved while the update was in flight.

Contract: `packages/grillui/src/grillui/projector.py`.

## Notice

Something an agent said that is addressed to the human. It joins the queue and
carries a control that opens a thread on it, and where it is about a particular
decision it renders on that decision rather than in a lane of its own. Two update
kinds are notices — *informational* and *elicit-alert* — and they differ in whether
the decision is held while the human deals with it.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-U9, GUI-U15);
`packages/grillui/src/grillui/schemas.py` for the two kinds.

## Informational

The notice kind that only tells the human something: it moves no decision and
holds none. It is how the grill-master's prose reaches the board at all, since
the map channel has no composer the human can type into.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Elicit-alert

The notice kind that can take a lock: an alert against one decision, which says
for itself whether it blocks that decision or merely speaks about it. The sender
always says which, because a lock nobody asked for and one somebody did are
otherwise the same bytes. It never queues as a proposal —
raising an alert as early as possible is the point of one — but it counts as a map
mutation under the sole-author rule, since the hold it can place is the map
author's to place.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Thread

A side conversation with its own agent and its own memory, anchored to a decision
or to the session itself. What is said in one is not in another. A thread has to
be spoken in before it exists, and its agent is given the whole board plus its
own thread's turns as the thread projection.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D24).

## Seed prompt

A prepared first turn a decision carries for the thread about it, offered as a
control beside the box it stands in for. A decision that declares none renders
none — the row is what the plan author wrote and nothing the page invents — and the
full text is the label, because what a control sends is the only thing worth
knowing about it.

Contract: `packages/grillui/src/grillui/page/script.js`.

## Map thread

The one thread about the map itself rather than about any decision on it. It is
the route for a change spanning several decisions, which no thread on one of them
can reach: its agent turns the human's request into a statement of what should
change, and folding it is what puts that in front of the grill-master.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D40).

## Help thread

The one thread that is not about the plan at all, where the human asks how the
board itself works. It is the only dispatch given the board's own reference
material — an agent grilling a design has no use for it and would only be paying
for it.

Contract: `packages/grillui/src/grillui/dispatch.py`;
`src/user/.agents/skills/grill-with-ui/references/help.md` is the material.

## Notice thread

A thread opened from an agent's notice, anchored to whatever decision that notice
was about. The anchor is what lets its agent answer a question about why the
board moved from the record of that decision rather than from nothing.

Contract: `docs/specs/2026-08-23-grill-master-role.md` (GUI-D47).

## Fold (the thread gesture)

The human's gesture concluding a thread and handing the conclusion to the
grill-master. It is how a thread's conclusion becomes a change to the map — a
thread agent may recommend one and never make one. It is not the only way a
thread reaches the map: the human may also take a converged answer and answer the
decision themselves, which folds nothing and dispatches nobody.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D25, GUI-D41).

Conflict: one word, three live mechanisms — see *Fold (the log event)* and
*Fold (the projection)*. Nothing but context disambiguates them, and whether any
of the three is renamed is a ruling owed under `agents-config-9k9.315`.

## Park

Setting a thread aside as a loose end the human may come back to. It is
non-destructive: the thread stays readable, it is carried to the end of the
session as still open, and an agent may raise it again. It is distinguished from
*close* deliberately, because a thread somebody finished with and one they meant
to return to are different facts about the session.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D29).

Conflict: the root `CONTEXT.md` defines *park* as a tracker state with a typed
reason. Unrelated mechanisms sharing a word.

## Close

Declaring a thread finished. Like park it takes nothing away and the thread stays
readable, but a closed thread is a line item and never a loose end: it is not
woven into what the session left open and no agent raises it. Saying something in
one opens it again, because picking a thread back up *is* saying something in it.

Contract: `packages/grillui/src/grillui/projector.py`.

## Conflict

A disagreement the board cannot resolve on its own and hands back to the agent
that caused it: an author withdrawing a queue entry the human had already acted
on. Neither the page nor the backend adjudicates one — only the authoring agent
knows what the rewrite was for. Two other disagreements go by the same word and
have their own entries: *queue conflict* and *result conflict*.

Contract: `packages/grillui/src/grillui/projector.py` detects it;
`packages/grillui/src/grillui/lane.py` hands it back.

## Queue conflict

A queued proposal the board moved under: the human changed its target after it
was authored, so applying it now would overwrite the change they made while it
waited. That is refused rather than resolved — the proposal stays queued and what
to do about it is a conversation. The decision wears it, and until it is judged
its answer is readable but cannot change.

Contract: `packages/grillui/src/grillui/projector.py` marks the proposal;
`packages/grillui/src/grillui/page/script.js` shows it on the decision.

## Result conflict

**Proposed, not built.** In the pending-analysis spec, two task results that
were independent when they started and disagree when combined — two new nodes with
the same prerequisites, two sub-updates on one decision, or a pre-ruling whose
target was answered after its basis. One expert turn merges them into a single
proposal naming both sources, so the human adjudicates once rather than
reconciling two. The draft calls it simply a conflict; this glossary names it to
tell it from the other two.

Design: the pending-analysis spec, PND-D8, and its own account of which results
conflict.

## Converged answer

The offer a thread agent makes when the conversation has reached what answers the
thread's own decision. It is an offer and never a question, it restates only what
the human already said, and it is live exactly while it rides the thread's most
recent turn. Taking it arms the decision's own controls; the human still answers.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D31, GUI-D33).

Conflict: this is a *proposal* in the ordinary English sense and is deliberately
not a queue entry — routing it through the queue would block the very answer it
proposes.

## Doctor

The escape hatch when the board and the conversation have drifted apart: an
explicit control sending the grill-master over the whole board with an
instruction to reassess. The board is held immutable while the dispatch is
outstanding; the backend reports that state rather than enforcing it, because
refusing a write would need a rejection reason and that vocabulary is closed.

Contract: `packages/grillui/src/grillui/lane.py`.

## Claim

Which window a session belongs to. One main window drives a session and the
backend is what decides which; a second is refused with a rendered explanation
and takes over only on the human's explicit gesture. None of it reaches the log —
which window is driving is not part of the grilling — so a reload is never a
lockout and a restart hands the session back to whoever is still asking.

Contract: `packages/grillui/src/grillui/claim.py`.

---

**The log and projection**

## Log

The append-only record that is the session's single source of truth. Every
projection is folded from it, every recovery re-reads it, and nothing is ever
rewritten.

Contract: `packages/grillui/src/grillui/log.py`.

## Appender

The one way anything reaches the log. It assigns the position, writes durably
before anything else can observe the entry, and answers every write with a typed
receipt. It never folds a projection, and it is where an agent's map mutation on
the wrong channel is refused — which is what makes the sole-author rule
structural.

Contract: `packages/grillui/src/grillui/log.py`.

## Epoch

One process's tenure over a session. A restart mints a new one on a continuing
sequence, and every message in either direction carries it. A client presenting a
stale epoch is told so and self-heals by re-reading state rather than by guessing.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D2).

## Sequence

The position of an entry in the log. It is the backend's to assign, never reset
and never client-supplied. A client's own counter may travel as opaque data for
its own joins and has no ordering authority.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D2).

## Payload

The content of a log entry, whose shape its kind decides. The asymmetry with the
envelope is deliberate: an unrecognised field on the envelope is a refusal, while
one inside a payload is carried through untouched, because the envelope is this
protocol's own vocabulary and a payload is content two ends may extend ahead of
each other.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Receipt

The typed answer every write gets, saying what actually happened to it. There is
no acknowledgement that does not — an "ok" over a silent no-op is what lets an
agent tell a human something is on the board when it is not. The rejection
vocabulary is closed, and callers switch on it.

Contract: `packages/grillui/src/grillui/schemas.py`.

## Fold (the log event)

One gesture carrying an ordered set of sub-updates, applied all of them or none,
as a single entry — so there is no state in which half of it landed, and the
receipt says what became of each part.

Contract: `docs/specs/2026-08-18-grilling-ui-v1.md` (GUI-D21).

Conflict: one word, three live mechanisms — see *Fold (the thread gesture)* and
*Fold (the projection)*.

## Projector

The module that turns the log into the projections, and where each update kind's
meaning lives — what a revise, an invalidate or an unsettle does to a decision,
and whether an agent's update lands or waits. It tolerates any entry the appender
accepted, because a projector that raised on one would take the session down
with it.

Contract: `packages/grillui/src/grillui/projector.py`.

## Fold (the projection)

The pure function from the log to the images: no clock, no randomness, no I/O.
The same log always yields the same bytes, which is what makes an image rebuilt
from disk trustworthy and the image files a cache rather than a record.

Contract: `packages/grillui/src/grillui/projector.py`.

Conflict: one word, three live mechanisms — see *Fold (the thread gesture)* and
*Fold (the log event)*.

## Status lane

The mechanical record of what is happening to a turn, emitted by the backend and
never by a model. It is written the moment a turn is scheduled rather than when
one comes back, which is what lets the page say a message landed — and it carries
failure the same way, so an unreachable seat surfaces in milliseconds instead of
as an unbounded silence.

Contract: `packages/grillui/src/grillui/lane.py`.

## Capture

Folding a session directory into its terminal result, with nothing serving it. It
is invocable by the backend at end-session, by the agent that launched the
session, or by a fresh reader pointed at last week's grilling. Everything
structural is pure code over the log and reproduces byte for byte; the prose
summary goes through a seam, whose shipped default is deterministic code and
whose agent-written alternative is what the `grill-capture` skill supplies.

Contract: `packages/grillui/src/grillui/capture.py`.

Conflict: the root `CONTEXT.md` lists *Capture* under retired vocabulary, from an
unrelated retired pipeline.

## Terminal result

What a finished grilling leaves behind and the whole of what the launching agent
receives beside file references. It is never a transcript — the transcript is
referenced, not carried.

Contract: `packages/grillui/src/grillui/capture.py`.

## Gate

Here, the mechanical check a write passes before anything is appended. The name is
shared with the repository's own sense of *gate* — a mechanical check whose
verdict is its exit status — and the two are different mechanisms.

Contract: `packages/grillui/src/grillui/schemas.py`; root `CONTEXT.md` for the
repository sense.

---

**The review phase**

## Review

**Proposed, not built.** In the terminal-review spec, the phase a board enters
once the frontier empties: the expert enumerates acceptance criteria and
edge-case rows, and the human disposes of each. It exists because the board
otherwise ends on a prose stop condition and leaves the readiness gate downstream
nothing to read, where the conversational `grilling` skill ends on enumerated
criteria.

Design: the terminal-review spec, TRV-D1.

Conflict: *review* elsewhere in this repository means adversarial code review and
its verdict artifact; the two share only the word.

## Entry

Two things one word. On the log, an *entry* is one appended line.

Contract: `packages/grillui/src/grillui/schemas.py`.

**Proposed, not built.** In the terminal-review spec, an *entry* is also one item
of the review phase, which the human disposes of and which links back to the
decisions it derives from.

Design: the terminal-review spec.

## Criterion

One acceptance criterion for the plan under grilling, with a stable id and stated
so that it is directly expressible as a failing test. The conversational
`grilling` skill enumerates them today and does not end a session until it has —
an empty question frontier is necessary and not sufficient. **Proposed, not
built:** the terminal-review spec makes the same enumeration the board's, as a
record on the log naming the decisions each criterion derives from.

Contract: `src/user/.agents/skills/grilling/SKILL.md` for the live enumeration;
the terminal-review spec for the board's record kind; the root `CONTEXT.md` for
what an acceptance criterion is in this repository generally.

## Taxonomy row

One edge-case category applied to one criterion — resolved, or explicitly ruled
out with a reason. The categories are a closed set of five, and the
conversational `grilling` skill treats each row of it as a question on the
frontier today. **Proposed, not built:** the terminal-review spec makes the row
a disposable record on the board.

Contract: `src/user/.agents/skills/grilling/SKILL.md` for the categories and the
live use; the terminal-review spec for the board's record kind.

## Disposition

**Proposed, not built.** In the terminal-review spec, where the human has got to
on one review entry. Rejection is a conclusion of a discussion rather than a
control of its own, so a rejection always has a recorded reason.

Design: the terminal-review spec, TRV-D3.
