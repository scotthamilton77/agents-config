# grillui

The backend behind a grilling session's user interface: it serves the UI,
folds the session's decision log into the images the UI and the agents read,
and drives the grilling tiers. The design it is being built to is
`docs/specs/2026-08-18-grilling-ui-v1.md`.

## What exists

The session core, the projection, the lifecycle that brackets them, the two
tiers that take the turns, the side threads that run beside the map, and the
page the backend serves. One
process owns one session directory, whose fixed file names are `log.jsonl`,
`image1.json`, `image2.json`, `handoff.json` and `result.json`, alongside a
`dispatches/` directory holding one file per recorded agent dispatch; the
append-only log is the single source of truth, and the process mints an epoch
over it at startup and assigns every sequence number. Restarting against the
same directory mints a new epoch and continues the sequence it had reached.

```bash
grillui serve ./sessions/my-session --handoff ./briefing.json --port 8765
grillui serve ./sessions/my-session          # resumes; handoff.json is not read
```

A new session is briefed from a handoff file — named with `--handoff`, or
`handoff.json` inside the session directory. A directory whose log already holds
entries is resumed from that log and the handoff is not opened at all: the
briefing was seeded **through** the log at `session-start`, so editing the file
mid-session changes nothing and no recovery path consults it. A refused handoff
names the field that is wrong and initialises nothing, because a directory
holding an empty log would read as a session and the next start would accept the
briefing this one refused.

Both tiers take turns. The fast tier is a non-Claude model over OpenRouter and
the heavy tier is a Claude model driven as `claude -p --resume` turns; which
model each is comes from `GRILLUI_FAST_MODEL` and `GRILLUI_HEAVY_MODEL`, and the
fast tier reads its key from `OPENROUTER_API_KEY`. A turn is one invocation that
exits — nothing polls, and no agent process stays resident between turns. Which
tier takes a turn is a property of the channel: the map and each thread are on
the tier the human last put them on, read back off their own turns, so
escalating one thread moves nothing else.

Every side thread is its own channel with its own agent context. A thread agent
is handed the whole board and its own thread's turns, with every other live
thread reduced to a stub — anchor decision, title, state, and the conclusion if
it reached one — and parked threads left out; it reads another thread's body
through the read surface when a stub turns out to matter. Threads take their
turns concurrently, with each other and with the map, while the grill-master's
heavy turns stay on one process at a time.

The grill-master is the sole agent author of map mutations. A map update
arriving on a thread channel is refused with a typed receipt and appended
nowhere, whether it came over the wire or out of a driver's own reply. When the
human folds a thread, the backend dispatches the grill-master with that thread's
conclusion; it answers in prose, or in an object carrying prose and the updates
to apply, and those land as one atomic gesture attributed to the grill-master on
the map channel. A conclusion it takes as context only produces no map mutation
and a reply that says so.

Every grill-master dispatch carries the pending queue — the notices the human
has not dealt with yet, each with its id, its target and its kind — as it stood
when the dispatch was folded. Answering a decision is dealing with the notices
standing on it, and they leave the queue. A response may withdraw notices it
authored itself by naming their ids in `supersedes`: those stay in the queue
marked superseded, for the page to drop. When the human answered first, the
withdrawal and the board disagree, and that goes back to the grill-master as a
dispatch of its own — neither the page nor the backend rewrites the board,
because only the authoring agent knows what the rewrite was for. Each conflict
is handed back once.

The map doctor is the escape hatch when that self-healing is not enough. `POST
/doctor` sends the grill-master over the whole board and the queue with an
instruction to reassess everything; `GET /doctor` reports whether that dispatch
is still outstanding, which is what the page holds the board immutable against.
The backend reports that state and does not enforce it — refusing a write would
need a rejection reason, and that vocabulary is closed. A doctor turn that fails
releases the board anyway, and a second call while one is outstanding dispatches
nothing.

Twelve modules, and the separation between them is load-bearing:

- `schemas.py` — the wire, log and image shapes, the per-kind payload shapes,
  and the closed vocabulary of the nine reasons a write can be refused for.
  That vocabulary is what decides where a malformed payload lands: a fault one
  of the nine names comes back as a typed receipt, and a fault none of them
  names — an add-node with one option, an invalidate with no rationale — is
  refused at the envelope with a 422, for the batch whole and before anything is
  appended.
- `log.py` — the appender. It assigns the sequence, writes durably before
  anything else can observe the entry, and answers every write with a typed
  receipt: `accepted` with the sequence assigned, `duplicate` naming where the
  key already landed, or `rejected` naming the reason. It never folds a
  projection.
- `projector.py` — a pure fold over the log into the two context images: no
  clock, no randomness, no I/O. The same log therefore always yields
  byte-identical images, and an image rebuilt from disk matches one held in
  memory. It is also where each update kind's meaning lives — what a revise, an
  invalidate, an unsettle or a blocking alert does to a decision's status — and
  the module docstring is the table. The thread projection is folded here too,
  by the same rules: pure, reproducible, and reducing nothing but the bodies of
  threads the dispatched agent is not having.
- `persistence.py` — the only image I/O there is, downstream of the fold: it
  refreshes both image files after an accepted batch. The files are derived
  caches, never a recovery source, so a failure here surfaces as an error on
  the status lane and blocks neither the log nor the next event.
- `dispatch.py` — assembles an agent's dispatch context, records it under
  `dispatches/`, and refuses one that does not carry the whole of what it owes.
  There is no elision path: a dispatch that omits part of its owed projection
  is data corruption, not a saving. Which agent a context is for is decided
  here from the channel rather than passed in, because a caller free to name
  the agent is a caller free to name the wrong one.
- `lane.py` — the status lane, the answerability decision, and the seam a tier
  plugs into. A human turn's `accepted` and `composing` entries are appended
  inside the same lock as the turn itself, before any driver is reached, so the
  page learns a message landed in under a millisecond rather than when a model
  gets around to it. Only a human turn is answered: an agent-authored thread is
  recorded and left alone, so the backend never answers itself. Every turn is
  answered on the channel it was spoken on but one: folding a thread is
  answered by the grill-master on the map, because it is the only agent that
  may act on a conclusion. The driver runs
  off the lock and off the request path — one invocation per turn, no polling —
  and a tier that cannot be reached surfaces as an `error` phase in
  milliseconds instead of an unbounded silence.
- `tiers.py` — what each tier is configured as and what it is told: the model
  ids, the shipped system prompts, and the assembly of one turn's prompt out of
  the briefing, the recorded board bytes and the channel's own conversation. The
  briefing is read from the session's opening log entry rather than the handoff
  file, so a process that never saw that file briefs its agents identically.
- `escalation.py` — the three conditions a fast reply's handoff recommendation
  is decided by, evaluated in code against the transcript and the board. It is
  never the model's assessment of its own competence: a fast model asked whether
  a question is beyond it judges generously and answers anyway. Recommending is
  all that happens here — moving a channel to the heavy tier is the human's
  gesture.
- `drivers.py` — the two tiers behind the `TurnDriver` seam, and their
  transports. Every reply carries its tier and model id into the log, a fast
  reply carries any recommendation, and a heavy reply records whether it
  followed a transfer. The heavy tier's chain identity is written into the
  session directory, so a restarted backend resumes the same conversation and
  pays the cold start once; one heavy turn runs at a time, because the discount
  lives in a cache one process holds. A turn that produces nothing usable
  raises, and the lane turns that into an error phase in milliseconds.
- `session.py` — starting, resuming and ending one session. It validates the
  handoff against its schema before the directory exists, appends the validated
  briefing as `session-start`, and rebuilds the images on every open so any
  image file left by a previous tenure is discarded rather than trusted. Ending
  is a human gesture: an agent's `session-end` is refused with a typed receipt
  and appends nothing.
- `capture.py` — the terminal result, folded from a session directory and
  nothing else, so the same operation serves the backend at end-session and a
  fresh reader pointed at last week's grilling. Everything structural is pure
  code over the log; the prose summary goes through a summarizer seam whose v1
  default counts the structured parts rather than composing them, so ending a
  session never waits on a model.
- `api.py` — the board endpoints. `/status` is answered from memory and opens
  no file, so it stays cheap whatever the log has grown to; `/state`, `/image1`
  and `/image2` fold; `/updates` refuses a stale epoch with 409; `/events`
  takes a batch under one epoch and returns one receipt per event in
  submission order, and returns them without waiting on the turn it scheduled.
  `/doctor` sits beside the board routes as a control rather than a board event:
  it writes nothing into the record, and the state it reports belongs to this
  process rather than to the log. `/` serves the page out of this package's own
  bytes, so a page and the protocol it speaks are always one build.
- `page/index.html` — the surface. One file, no build and no dependencies,
  which is what the reference prototype was and what a page served off disk can
  afford. Its board is the state read and nothing else: it never folds the log
  into decisions, statuses or a queue, and it never re-derives which of an
  agent's changes waited — that is the backend's answer, made when the change
  arrived, and the page renders the queue it is handed. It emits eight kinds
  through one checked constructor against a table it ships, so what it can say
  is readable out of its own source and is checked against the backend's
  accepted set by the suite.

The update kinds are complete. An add-node mints its node id from the sequence
it lands at — deterministic, because the receipt echoes the node the fold will
later materialise, and two readers of one node is how a receipt and a board come
to disagree. An invalidate carries its own rationale onto the decision it
blocks. A `fold` is one gesture carrying an ordered set of sub-updates, applied
all of them or none: the whole gesture is a single log entry, so there is no
state in which half of it landed, and its receipt says what became of each
sub-update — applied, refused with its own reason, or vetoed by a refused
sibling.

The page carries the reference surface forward onto this protocol: the map
beside one blended column with focus sync both ways, the inbox of changes that
have not landed against a notification list of what has, target locks on a
decision something is waiting on, conflict paint that is loud only on the
decision in dispute, mandated threads that conclude or are abandoned but never
parked, fold-readiness declared by the agent with its impact behind a control,
bubble overlays, and one scroll intent per human action. A refused write raises
a banner naming the typed reason and saying plainly that the message was not
recorded and no agent will answer it.

Not built yet: the transfer-to-expert control (a channel's tier is already
per-channel state, set by the transfer flag on the human's own turn and carried
into the dispatch, but no page surface raises the recommendation or activates
the transfer, and nothing yet flips the control's label back), session control
and single-main-window enforcement, the channel-state model and its diagnostic
surface, the single agent pass behind capture's summarizer seam, port fallback
and browser handoff, and the page's own polish mandates — the waiting indicator
and its timer, message timestamps everywhere, floating thread chrome,
hover-hide-on-click across every overlay, the three-way connection indicator,
and notification read-state with mark-all-read.

## Development

```bash
make ci-grillui     # the full gate: lint, format, types, coverage, audit, entry
make test-grillui   # faster inner loop
```
