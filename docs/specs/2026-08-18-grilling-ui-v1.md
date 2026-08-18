# Grilling UI v1 — the session backend, its protocol, and its surface

**Date:** 2026-08-18
**Status:** Implementation spec for `agents-config-9k9.221`. Supersedes the prototype
transport (`BRIDGE.md`, rounds 1–4) wherever the two disagree.

**Provenance.** Every requirement here was ratified by the owner across five prototype
rounds. The reaction ledger, the wire findings and the measured spike evidence live in
`docs/prototypes/grilling-ui/REACTIONS.md`, `LIVE-SESSION-REPORT.md` and
`spike5/SPIKE5-REPORT.md`; the working copies are untracked, and the binding copies are
committed on branch `prototype/grilling-ui` — rounds 1–3 at `04a88809`, round 4 at
`c8146beb`, spike 5 at `661fc5f0`. **The binding UX reference for v1 is the round-3 page
as evolved by rounds 4 and 5** (`grilling-ui-prototype-r3.html` at `04a88809`,
`-r4.html` at `c8146beb`, `-r5.html` at `661fc5f0`). This spec states the contract; those
reports hold the evidence, and `spike5/backend.py` at `661fc5f0` is prior art for the
protocol semantics — reference implementation, not a design to copy verbatim.

---

## 1. Architecture

**GUI-D1 — The session is server-authoritative; the page is a renderer.** One backend
process owns one grilling session. It holds an append-only on-disk event log which is the
single source of truth, mints a session epoch at process start, and assigns the single
authoritative sequence number on every entry. Nothing else — not the page, not an agent —
may assert state. Agents read projections and receive receipts; the page reads
projections and receives receipts. A client that believes something the log does not say
is wrong by construction, which is what kills the round-4 trap where a page reconnect
republished a pristine board indistinguishable from a genuine reset.

**GUI-D2 — Epoch identifies the process, sequence identifies the position.** A restart
mints a new epoch on a continuing sequence. Every message in either direction carries the
epoch. A client presenting a stale epoch is told so — refused on write with an
`epoch mismatch` receipt naming both epochs, and refused on read with HTTP 409 — and
self-heals by re-reading session state rather than by guessing. Sequence numbers are
never reset and never assigned by a client; a client's own counter may travel as opaque
data for its own joins, and has no ordering authority.

**GUI-D3 — Two context images, both projections of the log.** Image 1 is the current map
snapshot: every decision with its status, options, answer and prereqs, plus the frontier,
the settled set and the thread bodies. Image 2 is image 1 plus per-decision evolution
history — the ordered record of what happened to each decision and why. Projection is a
pure fold over the log with no clock, no randomness and no I/O, so the same log always
yields byte-identical images and an image rebuilt from disk alone matches one held in
memory. **Reverse handoff is image 2.** Agents are given image 2 and never given deltas
to reconstruct state from.

**GUI-D4 — Image 2 carries a completeness contract, not just a size budget.** The spike's
first projector trimmed settled decisions out of a dispatch to save tokens, and a
dispatched agent lost a decision the human had settled minutes earlier — a loss nothing
downstream can detect. Therefore: every settled decision's id and answer text is present
in every agent dispatch, unconditionally and independently of any budget. Anything the
projection does elide is elided explicitly, with a marker in the dispatched context naming
what class of content was dropped and how many entries. A dispatch that silently omits
required content is a defect of the same class as a corrupt log.

**GUI-D5 — Append and project must not fail together.** The appender writes the log entry
durably before any projection runs, and the projector must tolerate any log the appender
accepted. A projection error leaves the log intact and surfaces as an error on the status
lane; it never takes the session down and never blocks acceptance of the next event.

## 2. Session lifecycle: the handoff inversion

**GUI-D6 — The main agent writes a handoff file, launches the backend, and steps aside.**
The backend is its own agent harness: it mints its own grilling agents, and the browser is
a viewer that may arrive late and leave early. This inverts round 4, where the page owned
the board and an agent attached to a mail slot.

**GUI-D7 — The handoff file is the whole of what crosses the gap, and it is read once.**
Its v1 shape is `spike5/HANDOFF.md` at `661fc5f0`: session identity, `impetus`, `context`,
`constraints`, a `grilling_brief` carrying `posture` and `stop_when`, and a `plan` whose
`decisions` are the prototype node shape (id, short label, title, prereqs, body, options
with an optional buys/costs/forces triple, `options[0]` being the recommendation). Those
five briefing fields are load-bearing: without `stop_when` in particular the session never
terminates, because an agent asked to find weaknesses finds them indefinitely. After the
backend appends `session-start`, the handoff file has no further authority — editing it
mid-session changes nothing, and a backend whose log is non-empty ignores it entirely.

**GUI-D8 — Two skills bracket the session.** A new `grill-with-ui` skill assembles the
handoff from either impetus — a bare "grill me on `<work-item>`", or a design grown out of
a longer conversation — launches the backend, and receives the result. A capture step
inside the grilling agent produces the session's terminal result. What returns to the main
agent is the terminal result plus references to the persisted log and images, never a
transcript dump.

**GUI-D9 — The session is pausable and resumable from file state alone.** Killing the
backend mid-session and restarting it against the same session directory restores the
board, the answers, the thread history and the images from the log, and a post-restart
agent dispatch carries pre-restart context because the agent is reconstituted from image 2
rather than from process memory. No resume pointer lives in the handoff; resuming is not a
handoff.

**GUI-D10 — Session end is a human gesture; `stop_when` is what the agent may propose.**
The page carries an explicit end-session action. On it the backend appends a terminal
entry, invokes the capture step, and writes the terminal result into the session directory
alongside the log and the images. An agent that judges `stop_when` satisfied says so to
the human; it does not end the session itself.

## 3. Agent drive

**GUI-D11 — Two tiers and an escalation tool.** The fast tier is a non-Claude model over
OpenRouter, measured at roughly one second and $0.0002–$0.0008 per turn. The heavy tier is
a Claude model driven as `claude -p --resume` CLI turns, which bills the owner's
subscription; measured cost is $0.576 for the cold first turn and $0.054 thereafter, at
6.5 s standalone and 12–34 s under load. Those figures were measured at Sonnet weight, so
they are a floor for a heavier default. The fast tier holds one tool beyond its reply,
`upgrade_me`, which hands the current turn to the heavy tier carrying the accumulated
thread rather than only the last message. Both tiers' model ids are configuration; the
escalation target is a Claude model and Fable is excluded from v1.

**GUI-D12 — Escalation policy is a criterion evaluated against the transcript, never a
self-assessment of competence.** A fast model asked to judge whether a question exceeds
its own ability judges generously and answers anyway; the spike observed exactly that, on
a question the human had explicitly said they could not resolve. Replacing the judgement
call with checkable conditions made escalation fire correctly. V1 conditions, all
transcript-evaluable: the human asked for a commitment rather than another question, on a
decision with two or more dependents; the human has rejected a reframing of the question,
or says the trade-off itself is what they cannot resolve; three or more decisions must be
weighed at once. Asking a sharpening question back is the ordinary move and is not an
escalation.

**GUI-D13 — The status lane is mechanical and structurally cannot wait on a model.** The
instant a human turn is accepted, and inside the same lock as the append, the backend
emits status entries — accepted, then composing with its tier — before one byte leaves the
process. Measured at 0–1 ms against 1 s for a fast reply and 12–34 s for a heavy one. The
lane also carries agent failure: a griller that cannot be reached at all surfaces as an
error phase in milliseconds rather than as an unbounded silence. No status entry is ever
produced by a model, and no code path may make one wait on one.

**GUI-D14 — Only a human turn is owed a reply.** The page also opens agent-authored
threads (a mandate thread whose only turn is the agent's). Those are recorded and left
alone; the lane fires and a dispatch happens only when a human turn is present, so the
backend never answers itself. Answerability is separate from acceptance.

**GUI-D15 — A cold heavy-tier session costs about half a dollar, so the cache TTL is an
architectural input.** One process per session is what keeps the resumed-turn discount
(a 10× cost drop and a 2.7× speedup); a session held open across a long human silence pays
the cold-start tax again when the cache lapses. Implementations may not spread a session's
heavy turns across processes.

## 4. Protocol

**GUI-D16 — Every write carries an idempotency key and gets a uniform typed receipt.** The
receipt states `accepted` with the assigned sequence, `duplicate` naming the sequence the
key already landed at, or `rejected` naming the reason. There is no acknowledgement that
does not say what happened: round 4's `ok/accepted` over a silent no-op is the named
anti-pattern, and it is what let an agent tell a human something was on the board when it
was not. Rejection reasons v1 must distinguish: missing idempotency key, epoch mismatch,
unknown event kind, unknown node id, an answer carrying neither an option nor text, and a
thread event carrying no turn.

**GUI-D17 — A rejected human action is visible on the page.** The page raises a banner
naming the reason and stating plainly that the message was not recorded and no agent will
answer it, with a dismiss control. A counter is not a surface.

**GUI-D18 — The endpoint set.** A state read returning epoch, current sequence and image 1;
an update read taking a cursor and refusing a stale epoch with 409; reads for image 1 and
image 2; and one write endpoint taking a batch of events under an epoch and returning one
receipt per event. The state read is what a page or an agent uses to recover after any
doubt, which is why a reconnect asserts nothing.

**GUI-D19 — The update kinds v1 must carry**, in the priority the live agent gave them:

- A zero-content thinking indicator the backend fires the moment a turn is picked up —
  the mechanical counterpart of the page's waiting indicator, and the highest-value
  addition the live session identified.
- A real add-node taking a question, options and prereqs, minting an open node id rather
  than accepting only pre-baked ones, and echoing the materialised node back so the
  agent can later revise other decisions against it.
- Invalidate carrying its own rationale text. Invalidating a decision is the heaviest
  thing an agent can do short of unsettling one, and shipping the reasoning as a separate
  note on a neighbouring node makes the human read the block and its justification as two
  unrelated items.
- Revise, informational, elicit-alert (with a flag for whether it blocks), settle,
  unsettle and resolve-stale, plus the thread kinds below.
- The state read of GUI-D18, so an agent can confirm what landed instead of inferring it
  from receipts that may not arrive.

**GUI-D20 — Thread events speak the page's shape.** `thread-created` and `thread-turn`
both carry their content in a `turns[]` array of who/text pairs; `thread-created`
additionally carries its kind, its title and whether it requires action. Backend-authored
replies may carry bare text. One reader handles both shapes, shared by the accept path,
the projector and the driver — writing the backend against only one of them is precisely
how the real UI path came to be rejected while a scripted check passed.

**GUI-D21 — The atomic fold survives unchanged.** One human gesture applies a
conversational turn's declared impact — a revise, an add-node and an informational
together — atomically, with a receipt for each. This is the mechanism the live session
rated the best part of the protocol, and v1 keeps it. Where the prototype rewrote an
agent-supplied basis sequence at fold time without saying so, the receipt now states what
was applied, as sent or as amended.

**GUI-D22 — Agents poll status, not events.** A grilling agent pays a round-trip per poll,
so the documented pattern is a cheap status check with a full read only when the cursor
moves. Sub-second polling advice is unusable and must not appear in any agent-facing
material this work ships.

## 5. The UI surface

The binding reference is the round-3 page as evolved by rounds 4 and 5, named above. V1
changes it as follows, and changes nothing else:

- **Waiting is always visible.** Whenever the human sends anything an agent owes a reply
  to — a thread turn, an answer awaiting reaction — the page shows that the message
  reached the backend, that work is in progress, and an incrementing timer of how long the
  human has been waiting. This is fed by the mechanical status lane, so it appears
  immediately rather than when a model gets around to it.
- **Every message carries a timestamp rendered in the operating system's time zone** —
  thread turns and notifications alike.
- **Agent responses are concise by default**, two or three sentences, with verbosity only
  when the human asks for detail. This is a constraint on the griller's system prompt as
  much as on the page.
- **Thread panels have a floating header and footer** — title with close and pop-out
  controls pinned at the top, prompt box and action buttons pinned at the bottom — so
  neither scrolls out of view in a long thread.
- **Decisions offer two to three best options, labelled a/b/c** so free text and thread
  turns can reference them by label. Three is a ceiling, not a target. Alongside choosing
  an option and writing free text, the human can select an option *and* attach a note.
- **Hover overlays always hide on click**, and return only on a fresh mouse-enter of a
  zone that owns one.
- **One main window per session, enforced by the backend.** The backend mints a session
  token; the first main window claims it and a second main window connecting to the same
  session is refused with a visible explanation. Pop-out windows are the sanctioned
  exception and ride the parent's token. Concurrent *different* sessions run as separate
  backend processes.
- **The connection indicator splits into three signals**: whether the backend is
  reachable, whether an agent is attached and currently owes a response (the priority
  signal), and the outbox depth of events not yet consumed. A healthy backend with no
  agent must never look identical to a healthy backend with a working one.
- **Informational messages are as concise as possible and carry a Discuss button** that
  opens a thread seeded from the message.
- **The notifications window has a mark-all-read control.**

Everything else the round-3 page does — the map beside a single blended column of
answerable and settled decisions, bidirectional focus sync, the auto-apply taxonomy drawn
at "does this overwrite a human decision", the inbox/notification split, pending-update
target locks, the softened conflict paint, agent-adjudicated reassessment, mandated
threads without park, thread fold-readiness with impact preview, bubble overlays, and the
scroll discipline of one scroll intent per human action — is carried forward as specified
by the ledger and demonstrated by the reference page. Reimplementation is not licence to
redesign.

## 6. What v1 does not do

Each item below is deferred, not rejected, with the observation that would pull it in.

- **Option metadata pre-marking downstream nodes.** Options that predictably put
  downstream decisions in question could carry that in the map data so the page marks
  those nodes pending immediately on selection. Trigger: the three-way connection
  indicator proves insufficient — humans still act on decisions the agent is about to
  invalidate.
- **Pop-out windows beyond thread pop-outs.** Trigger: a real session where the single
  main window is the binding constraint on running several threads at once.
- **Per-side-thread subagents with separate contexts.** V1 side threads share the two
  tiers and the session's images. Trigger: measured evidence that side-thread turns are
  polluting the main griller's context or that thread latency is dominated by context
  size.
- **Human-initiated escalation.** V1 escalation is the agent's `upgrade_me` under the
  criteria of GUI-D12; the human has no control that forces a turn to the heavy tier.
  Trigger: a session where the fast tier repeatedly fails to escalate on a question the
  human considers hard — that is first a defect in the criteria, and a human override is
  the remedy only if sharpening the criteria stops working.
- **Event-log mining and the clean decision-log projection.** Trigger: a consumer that
  needs session outcomes without the process — the first spec, requirements set or AC list
  someone wants generated from a session.
- **Parked-thread drift mitigation.** A reopened parked thread's agent is stale relative
  to the evolved map. Trigger: a session where a resumed parked thread asserts something
  the board contradicts.
- **A tracker bridge.** The wayfinder determination stands: separate artifacts, no shared
  data model, overlap in vocabulary only. Trigger: someone wants a session's unfinished
  map exported as tracker items.

## 7. Placement

**Proposed, for the implementing work to confirm.** The backend, the projector, the tier
drivers and the CLI land as a new uv package under `packages/`, carrying the standard
per-package quality gates and going on PATH through the installer's CLI package list. The
UI surface ships inside that package and is served by the backend — it is not a deployed
skill asset, because it is a program the backend serves rather than instructions an agent
reads. `grill-with-ui` and the capture skill are deployed skills and must clear the
`admit-request` gate on their own merits. The skill ships reference material about the
UI's behaviour and the backend's capabilities, so the grilling agent can answer "why is
the UI blocking me / why can't I do X" directly in chat instead of guessing.

## 8. Acceptance criteria

Each is mechanically checkable and convertible to a red test.

- **GUI-A1** Projection is deterministic: folding a fixed log twice yields byte-identical
  images, and images rebuilt from the on-disk log alone are byte-identical to the
  in-memory ones.
- **GUI-A2** Image 2 carries per-decision history and image 1 does not, over the same log.
- **GUI-A3** Every agent dispatch context contains the id and answer text of every settled
  decision at dispatch time. The check reads the backend's own recorded dispatch prompts,
  and fails if any settled id is absent — including when a token budget is set low enough
  to force elision.
- **GUI-A4** Any elision in a dispatch context is accompanied by a marker naming the
  elided class and its entry count; a dispatch that drops content without a marker fails.
- **GUI-A5** Killing the backend mid-session and restarting it against the same directory
  yields a new epoch on a continuing sequence, with settled answers, frontier and thread
  history unchanged; the next heavy dispatch after restart contains verbatim turns from
  before the restart.
- **GUI-A6** A write presenting a stale epoch is refused with an `epoch mismatch` receipt
  naming the server and sent epochs; an update read with a stale epoch returns HTTP 409.
- **GUI-A7** Re-posting an event with an already-seen idempotency key returns a
  `duplicate` receipt naming the original sequence and appends nothing, even when the body
  differs.
- **GUI-A8** Each rejection reason in GUI-D16 has a test producing exactly that typed
  receipt, and no rejected event appears in the log.
- **GUI-A9** A rejected human action renders a page-level banner naming the reason and
  stating the message was not recorded, verified in a browser rather than by inspecting
  the code that constructs it.
- **GUI-A10** Human turn accepted to status entry appended is under 10 ms measured from
  the log's own timestamps, with no model call on the path; a run configured with an
  unreachable agent still produces the accepted and error status entries in that window.
- **GUI-A11** An agent-authored thread with no human turn produces no status lane entry
  and no dispatch, while a human turn in the same thread produces both.
- **GUI-A12** With the escalation criteria of GUI-D12 in force, a scripted transcript
  satisfying one condition produces an `upgrade_me` call whose stated reason names that
  condition, and the heavy dispatch that follows contains the accumulated thread; a
  transcript satisfying none produces an ordinary reply. Both tiers' attributions — tier,
  model, and that the heavy turn was upgraded from the fast one — are in the log.
- **GUI-A13** Every event kind the page emits is known to the backend. The check derives
  the kind set by reading the page's own emission sites out of the shipped page source,
  not from a list the test author wrote, and it is mutation-checked: removing one kind from
  the backend's accepted set turns the suite red naming exactly that kind.
- **GUI-A14** Every scripted stand-in used to verify the page contract derives its message
  shapes from the page's own emissions. A `thread-created` and a `thread-turn` posted in
  the page's `turns[]` form are both accepted and both project into the thread's turn list;
  a stand-in that posts a shape the page never emits fails the check.
- **GUI-A15** The test suite exits non-zero when it executes fewer checks than it declares,
  so an early return or a swallowed failure cannot report a clean pass, and the clean-pass
  marker is printed only on a full run.
- **GUI-A16** Add-node mints a node from a question, options and prereqs supplied by the
  agent, echoes the materialised node back in its receipt, and the new node is answerable
  and revisable in the same session.
- **GUI-A17** Invalidate carries rationale text, and that text reaches the page attached
  to the invalidation rather than as a separate note on another node.
- **GUI-A18** One fold gesture carrying a revise, an add-node and an informational applies
  all three or none, with a receipt per update stating what was applied and whether it was
  amended.
- **GUI-A19** A second main window claiming an already-claimed session token is refused
  with a rendered explanation; a pop-out presenting the parent token is admitted; two
  backends on different session directories run concurrently without interference.
- **GUI-A20** A page whose epoch is stale recovers current state through the state read
  without human intervention and without asserting any board content of its own, verified
  by reloading the page mid-session in a browser.
- **GUI-A21** The waiting indicator appears on every turn an agent owes, carries an
  incrementing timer, and is driven by status-lane entries — verified in a browser against
  a deliberately slow heavy-tier turn.
- **GUI-A22** Every message and notification renders a timestamp in the operating system's
  time zone, verified in a browser under a non-UTC `TZ`.
- **GUI-A23** The connection indicator distinguishes backend-unreachable,
  agent-owes-a-response and outbox-depth as three separate signals, each exercised.
- **GUI-A24** Killing the projector's output path (an unwritable image file) leaves the log
  intact and complete, surfaces the failure on the status lane, and does not refuse the
  next event.
- **GUI-A25** The deployed skills carry a complete admission record and the UI-behaviour
  reference material; the package's own gate and the repository gate both pass on the
  branch that ships them.

## 9. Open questions for the implementing work

- **The heavy tier's default model.** The owner ruling names an escalation to Opus; the
  spike measured Sonnet deliberately to keep the bill honest, and every cost figure above
  is at Sonnet weight. V1 makes the model configuration with a Claude default, and the
  first real session should settle which default is right on cost-per-useful-turn.
- **How `grill-with-ui` hands the backend's address to the human's browser** — the spike
  used a fixed port on loopback. Port selection, collision behaviour with a second
  concurrent session, and how the URL reaches the human are unsettled mechanism.
- **Whether the capture step runs as a heavy-tier turn or as a separate agent.** The
  terminal result is the main agent's whole return value, and its quality bar is different
  from a grilling turn's.

## Continuations

- Backend core: event log, epoch and sequence assignment, uniform receipts, idempotency,
  state and update endpoints — GUI-D1, GUI-D2, GUI-D16, GUI-D18, GUI-A1, GUI-A6, GUI-A7,
  GUI-A8.
- Projector and context images, with the completeness contract and the append/project
  isolation — GUI-D3, GUI-D4, GUI-D5, GUI-A2, GUI-A3, GUI-A4, GUI-A24.
- Status lane and answerability, including the agent-authored-thread case — GUI-D13,
  GUI-D14, GUI-A10, GUI-A11.
- Two-tier agent drive with criterion-based `upgrade_me` — GUI-D11, GUI-D12, GUI-D15,
  GUI-A12.
- Update kinds: add-node with echo, invalidate with rationale, thinking indicator, thread
  shapes and the atomic fold — GUI-D19, GUI-D20, GUI-D21, GUI-A16, GUI-A17, GUI-A18.
- Page repoint onto the v1 protocol, with the page-derived kind check and the stand-in
  rule — GUI-A13, GUI-A14, GUI-A15, GUI-A20.
- UI mandates: waiting indicator, timestamps, floating thread chrome, labelled options
  with notes, hover-hide-on-click, connection indicator, concise informationals with
  Discuss, mark-all-read — GUI-A21, GUI-A22, GUI-A23.
- Single-main-window enforcement and concurrent sessions — GUI-A19.
- Handoff assembly, session lifecycle, restart-resume and the terminal result —
  GUI-D6, GUI-D7, GUI-D9, GUI-D10, GUI-A5.
- Deployed skills `grill-with-ui` and the capture step through the admission gate, with
  the UI-behaviour reference material — GUI-D8, GUI-A25.
- Packaging: the uv package, its gates, and the CLI on PATH — GUI-A25.
