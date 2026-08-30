/* =====================================================================
   The wire, the board it reads, and the surface over both.
   ===================================================================== */

/* ---------------- what this page may say ----------------
   Every kind this page emits, the channel class it goes out on, and the
   payload keys it may carry. `send` refuses anything else, so this table is
   what the page does rather than what it claims to do — and it is the one
   text a contract check reads to learn the page's own vocabulary. Written as
   JSON for that reason; keep the prose outside the fence. */
//---PAGE-EMISSIONS-START---
var EMISSIONS = {
  "answer":         { "channel": "map",    "payload": ["target", "answer", "transfer", "from_thread"] },
  "thread-created": { "channel": "thread", "payload": ["turns", "decision", "kind", "title", "requires_action", "transfer"] },
  "thread-turn":    { "channel": "thread", "payload": ["turns", "transfer"] },
  "thread-fold":    { "channel": "thread", "payload": [] },
  "thread-park":    { "channel": "thread", "payload": [] },
  "thread-close":   { "channel": "thread", "payload": [] },
  "apply":          { "channel": "map",    "payload": ["pending"] },
  "dismiss":        { "channel": "map",    "payload": ["pending"] },
  "session-end":    { "channel": "map",    "payload": [] }
};
//---PAGE-EMISSIONS-END---

/* ---------------- the backend's vocabulary, as this page reads it ----------------
   Not a taxonomy of its own: which of an agent's changes waited is decided by
   the backend at arrival and read off the queue. These two lists only tell a
   queue entry that is a change from one that is a message. A check pins them
   to the backend's own sets, because a page splitting the queue on a stale
   list would file a waiting change as a notice and let its decision be
   answered around. */
//---BACKEND-VOCABULARY-START---
var PROPOSABLE_KINDS = ["add-node", "revise", "invalidate", "settle", "unsettle", "resolve-stale"];
var NOTICE_KINDS = ["informational", "elicit-alert"];
var MAP_MUTATION_KINDS = ["add-node", "invalidate", "revise", "settle", "unsettle", "resolve-stale", "elicit-alert", "fold"];
var STATUS_PHASES = ["accepted", "composing", "replied", "error", "transferred"];
var AGENT_ACTORS = ["grill-master", "thread-agent"];
var CLAIM_STATES = ["granted", "refused", "superseded"];
// The three payload keys this page reads a tier off, spelled the backend's way.
// `TIER_KEY` is how a reply says which tier composed it and how the lane names
// the tier it is waiting on; `RECOMMENDATION_KEY` is the escalation advice a
// fast reply carries when it met one of the conditions; `TRANSFER_FLAG` is the
// key on the human's own turn that puts that channel on the expert tier, and
// the backend reads their half of the mode back off exactly this key. The other
// half is the lane's `transferred` phase, which both sides read the same way.
var TIER_KEY = "tier";
// The two tiers, spelled as the log spells them. The page labels a turn by what
// it finds under the key, so a stale spelling here is a turn the human is told
// nothing about while the log says plainly which tier answered.
var FAST_TIER = "fast";
var HEAVY_TIER = "heavy";
var RECOMMENDATION_KEY = "recommendation";
var TRANSFER_FLAG = "transfer";
// The key an answer names the thread it was armed from by. Payload content like
// the three above, so nothing validates it on the way past: a stale spelling
// here is an answer that settles the decision and leaves its thread open.
var FROM_THREAD_KEY = "from_thread";
//---BACKEND-VOCABULARY-END---
// Named by position rather than restated, so this page cannot hold a claim
// state the backend has no word for.
var CLAIM_GRANTED = CLAIM_STATES[0], CLAIM_REFUSED = CLAIM_STATES[1], CLAIM_SUPERSEDED = CLAIM_STATES[2];

/* ---------------- channel state, in the two layers it has ----------------
   The connection lifecycle is the transport's: one origin, one process, one
   answer, so every channel reports the same one. The protocol state is each
   channel's own and is moved only by that channel's traffic — which is the
   point, because one thread stalling says nothing about the map or about any
   other thread.

   Both tables are the backend's copy of the same contract, and a pair neither
   names is refused rather than guessed: a channel quietly staying where it was
   renders as a working indicator for a state this model does not have. Written
   as JSON for the same reason the emissions table is. */
//---CHANNEL-STATE-START---
var TRANSPORT_STATES = ["disconnected", "connecting", "connected", "error"];
var PROTOCOL_STATES = ["idle", "sending", "awaiting-ack", "agent-owes", "receiving"];
var TRANSPORT_SEVERITY = ["connected", "connecting", "disconnected", "error"];
var PROTOCOL_SEVERITY = ["idle", "sending", "receiving", "agent-owes", "awaiting-ack"];
var TRANSPORT_TABLE = {
  "disconnected": { "open": "connecting", "reached": "connected", "unreachable": "disconnected", "refused": "error" },
  "connecting":   { "open": "connecting", "reached": "connected", "unreachable": "disconnected", "refused": "error" },
  "connected":    { "open": "connected",  "reached": "connected", "unreachable": "disconnected", "refused": "error" },
  "error":        { "open": "connecting", "reached": "connected", "unreachable": "disconnected", "refused": "error" }
};
var PROTOCOL_TABLE = {
  "idle":         { "submit": "sending", "settled": "idle", "owed": "agent-owes", "arriving": "receiving", "closed": "idle" },
  "sending":      { "dispatched": "awaiting-ack" },
  "awaiting-ack": { "submit": "sending", "settled": "idle", "owed": "agent-owes", "arriving": "receiving", "closed": "idle" },
  "agent-owes":   { "submit": "sending", "settled": "agent-owes", "owed": "agent-owes", "arriving": "receiving", "closed": "idle" },
  "receiving":    { "submit": "sending", "settled": "receiving", "owed": "agent-owes", "arriving": "receiving", "closed": "idle" }
};
//---CHANNEL-STATE-END---

var MAP = "map";
var APPLY_KIND = "apply";
var SESSION_END_KIND = "session-end";
var SESSION_START_KIND = "session-start";
var DISMISS_KIND = "dismiss";
var STATUS_KIND = "status";
var PHASE_COMPOSING = "composing";
var PHASE_REPLIED = "replied";
var PHASE_ERROR = "error";
// The lane saying the escalation policy moved a channel to the expert tier. The
// page reads it exactly where it reads the human's own transfer gesture: it is
// the same fact about the same channel, said by the backend instead.
var PHASE_TRANSFERRED = "transferred";

/* ---------------- the board, and what has happened ---------------- */

// Image 1, exactly as the state read returned it. Nothing here is computed.
var BOARD = { epoch: "", seq: 0, decisions: [], frontier: [], settled: [], threads: [], pending: [] };
// Every log entry this page has read. It is not a second board: it is read for
// what image 1 does not carry — a queued change's own text, the status lane,
// and which decisions the human has moved since a change was written.
var LOG = [];
// Which log positions have already been read. The cursor is the backend's and
// is authoritative; this sits beside it, because an entry judged twice is a
// notification the human is shown twice.
var SEEN = {};
var WIRE = {
  base: "", epoch: null, cursor: 0, hydrated: false, inflight: false,
  sent: 0, got: 0, rejected: 0, lastRejection: null,
  // What the lane says each channel is waiting on, by channel. Per channel
  // rather than one slot, because two threads and the map take turns at the
  // same time: a single slot shows the last turn announced and hides the rest,
  // and the one the human is waiting on is as likely as not the hidden one.
  status: {}, doctor: false, doctorKnown: false
};
// Events this page has put on the wire that have not come back down the update
// read. Depth, not a list of grievances: an event is out of here the moment the
// log carries it or a receipt refuses it, so what is left is the work the page
// asked for and cannot yet see the effect of.
var OUTBOX = {};
// A session ends once, on the human's own gesture, and what follows it is a
// record rather than a conversation: nothing this page says afterwards is
// recorded, so the surface stops offering to say it.
//
// Read off the log this page already holds, and set on the receipt as well. A
// launched backend stops the moment the terminal entry is durable, so the update
// read that would carry that entry may never answer -- and a page left waiting
// for it would render an ended session as a broken backend and invite the human
// to restart something that finished.
var ENDED = false;
function sessionOver() {
  return ENDED || LOG.some(function (e) { return e.kind === SESSION_END_KIND; });
}
// The thread that is about the board rather than about the plan: one per
// session, anchored to no decision, and named the same by every window so a
// reload and a pop-out find the one that already exists rather than opening a
// second.
var HELP_THREAD = "t-help";
// The other session-scoped thread: where the human asks for a change to the map
// itself — invalidate this run of decisions, revise that one, add the one that
// is missing. It anchors no decision because the request is rarely about one,
// and folding it is what puts the request in front of the grill-master, which
// is the only agent that may propose a map update. One per session, named the
// same way and for the same reason as the help thread.
var MAP_THREAD = "t-map";
var MAP_THREAD_TITLE = "Ask for a map change";
// What the session was opened with, read off the log's own opening entry. Two
// things here are not on image 1 and are not board state: what this session is
// called, and whether anything was shipped that could answer a question about
// the board. Both were said once, at the start, and the log is where the page
// already holds what was said.
function briefing() {
  var opening = LOG.filter(function (e) { return e.kind === SESSION_START_KIND; })[0];
  return (opening && opening.payload) || {};
}
function sessionTitle() {
  var named = (briefing().session || {}).title;
  return named ? String(named) : "Grilling session";
}
// No reference material, no help control. The control promises an agent that
// knows this board; without the material behind it the human would get the
// same guesswork they could have had by asking anywhere else, dressed up as
// the one place that knows.
function helpOffered() { return !!briefing().help_reference; }
// A refusal of this page's own: a gesture it will not put on the wire, said
// where a backend's refusal is said. Held apart from `WIRE.lastRejection`,
// which is the backend's answer -- attributing a refusal to the backend for
// something never sent is this page inventing an answer nobody gave.
var HELDBACK = null;
function refuse(text) { HELDBACK = text; render(); }
// One transport, however many channels ride it, and one protocol state per
// channel. The map channel exists from the start because the board is always a
// conversation someone could be having; a thread's channel is noted the moment
// the board mentions the thread or this page sends on it.
var CHANNELS = { transport: TRANSPORT_STATES[0], protocol: { map: PROTOCOL_STATES[0] } };
// Notifications are the record of what has LANDED, observed as it lands. A
// change still waiting is not in here — it is in the inbox alone. The list is
// deliberately empty on a reload: a page arriving mid-session must not announce
// a morning's worth of history as news.
var NOTES = [];
// This window's standing with the backend: which session it is talking to, and
// whether this is the window that session answers. One main window per session,
// because two windows over one board both answer decisions on it and the human
// ends up reading one while the agent replies to the other.
//
// `holder` is this window's own name, and it is the whole of the claim: the same
// name presented again is the same window, which is what makes a reload free and
// what a pop-out rides. It lives in SESSION storage rather than local storage on
// purpose — session storage is the one origin store scoped to a single window,
// so it survives this window's reload and is not there for a second window to
// find and present as its own.
var CLAIM = { token: "", state: "", holder: "" };
var CLAIM_KEY = "grillui:claim";
function claimHolder() {
  if (CLAIM.holder) return CLAIM.holder;
  var stored = null;
  try { stored = window.sessionStorage.getItem(CLAIM_KEY); } catch (e) {}
  CLAIM.holder = stored || PAGE_ID;
  return CLAIM.holder;
}
// Whether the board may be drawn at all. A refused or superseded window shows
// the reason and nothing else: a board with a warning over it is still a board,
// and the human would answer decisions on it.
function boardShown() { return CLAIM.state !== CLAIM_REFUSED && CLAIM.state !== CLAIM_SUPERSEDED; }
// Present this window's name and take what the backend says. The same call is
// the first claim, the reload, the reconnect and — with the flag — the human's
// explicit take-over, so there is one path to keep true rather than four.
//
// A failed request changes nothing here. Only an answer moves the claim: a page
// that read a network blink as a supersede would hide a working board over a
// dropped packet.
function claim(takeover) {
  return srvPost("/claim", { holder: claimHolder(), takeover: !!takeover }).then(function (c) {
    var was = CLAIM.state;
    CLAIM.token = c.token;
    CLAIM.state = c.state;
    wire("reached");
    if (c.state === CLAIM_GRANTED) {
      try { window.sessionStorage.setItem(CLAIM_KEY, CLAIM.holder); } catch (e) {}
      // Coming into the session — first claim, take-over, or a restarted
      // backend handing it back — the board is re-read rather than assumed.
      if (was !== CLAIM_GRANTED) WIRE.hydrated = false;
    }
    if (c.state !== was) render();
  }, wireFailed);
}
// Which of the things the agent has said the human has already read. Read-state
// is presentation state — the page owns it, it never crosses the wire, and the
// server-authority rule does not reach it — but it is not session-local, because
// the surfaces it clears are not: the ✉ markers come off the queue in image 1,
// which comes back on every reload. Without this, marking everything read and
// reloading would restore every marker the human just dealt with.
//
// Keyed by the update's own id, which is the backend's derivation and stable for
// the life of the log. Scoped to the session token rather than to the epoch,
// because these ids name log entries and the log outlives any one process: an
// epoch-scoped set is thrown away by a restart that invalidated nothing, and
// every marker the human already dealt with lights up again. The token is also
// what keeps two sessions that reuse a loopback port out of each other's
// read-state, which the epoch did by accident and this does on purpose.
var READ = {};
function readKey() { return "grillui:read:" + CLAIM.token; }
function loadRead() {
  try { READ = JSON.parse(window.localStorage.getItem(readKey()) || "{}") || {}; }
  catch (e) { READ = {}; }
}
function saveRead() {
  // Storage can be full, or disabled outright. Losing read-state is a worse
  // notification experience and nothing more, so it is never allowed to take
  // the board down with it.
  try { window.localStorage.setItem(readKey(), JSON.stringify(READ)); } catch (e) {}
}
// What this window has started and has not committed: an answer held against a
// mandated thread, and which waiting change each discussion thread was opened to
// judge. Neither crosses the wire and neither is board content -- but both are
// lost work when a reload drops them, and the loss is silent: the held answer
// disappears while the thread that was holding it goes on blocking the decision,
// and a discussion forgets the change it exists to adjudicate while its apply
// and dismiss controls are still on screen.
//
// SESSION storage, for the reason the claim holder is there: it is the one origin
// store scoped to a single window, so this window's reload finds it and a second
// window cannot present it as its own. Keyed by the claim token like the read
// state, so two sessions on one loopback port never read each other's.
function loadWindow(name, fallback) {
  try { return JSON.parse(window.sessionStorage.getItem("grillui:" + name + ":" + CLAIM.token) || "") || fallback; }
  catch (e) { return fallback; }
}
function saveWindow(name, value) {
  try { window.sessionStorage.setItem("grillui:" + name + ":" + CLAIM.token, JSON.stringify(value)); } catch (e) {}
}
function saveHeld() { saveWindow("held", UI.held); }
function saveDiscussing() { saveWindow("discussing", UI.discussing); }
function isRead(id) { return !!READ[id]; }
function markRead(id) {
  if (!id) return;
  READ[id] = true;
  saveRead();
}
var UI = {
  // `armed` is what a taken proposal left behind, per decision: which thread
  // offered it and which option it built on. It rides the next answer that
  // decision sends and goes with the draft it filled -- nothing about it is on
  // the log until the human presses an answer control.
  // `overOpt` and `keyedOpt` are the two live ways to have an option in hand --
  // the pointer on its control and the caret on it. Page-local like the rest of
  // this object, and unlike `held` they are not written to the window store: an
  // option a pointer was resting on is not something a reload can still be
  // holding.
  focus: null, open: {}, drafts: {}, panel: null, held: {}, armed: {},
  overOpt: null, keyedOpt: null,
  lastFocus: null, lastPanelKey: null, centerNext: true, justSettled: null,
  fresh: [], touched: [], autoshut: {}, advanceFrom: null,
  bubbles: [], bubbleSeen: {}, bubbleSig: null, bubbleTick: 0, ptr: null,
  popped: {}, draftBase: {}, popFail: false, diag: false, discussing: {},
  // The completion offer, which is presentation and lives nowhere else: whether
  // the overlay is up, whether it was dismissed onto the pulsing control, and
  // what the board's finished-ness last read as. A reload starts all three back
  // here, which is right -- a board that is not finished has nothing to carry.
  done: false, pulse: false, wasDone: false
};
// One page instance: an idempotency key is stable for a retry and distinct
// across reloads, because a reload's events are genuinely new and a resend is
// not.
var PAGE_ID = "p" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
var KEYS = 0;

// A failure that was answered and a failure that was not are different states,
// because they are different problems: something is listening and broken,
// against nothing is listening at all. The flag rides the error so the caller
// can say which without asking the wire a second time.
function answered(r) {
  var e = new Error("server returned " + r.status);
  e.answered = true;
  return e;
}
function unanswered(e) { e.answered = false; throw e; }

function srvGet(path, query) {
  var q = query ? "?" + query : "";
  return fetch(WIRE.base + path + q).then(function (r) {
    if (r.status === 409) { var e = new Error("epoch"); e.stale = true; throw e; }
    if (!r.ok) throw answered(r);
    return r.json();
  }, unanswered);
}
function srvPost(path, body) {
  return fetch(WIRE.base + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body === undefined ? "" : JSON.stringify(body)
  }).then(function (r) {
    if (!r.ok) throw answered(r);
    return r.json();
  }, unanswered);
}

/* ---------------- the two layers, stepped ----------------
   Every move goes through one step, so a state either end of this page reaches
   is one the table named. A move the table does not have raises here rather
   than being absorbed, which is the difference between a bug that surfaces
   where it happened and an indicator that is quietly wrong. */
function step(layer, table, state, event) {
  var moves = table[state] || {};
  if (!(event in moves)) {
    throw new Error("the " + layer + " layer has no move from " + state + " on " + event);
  }
  return moves[event];
}
// The wire moved. No channel's protocol state moves with it: the turns an agent
// owed before a drop are still owed after it, and clearing them would tell the
// human their message had been dealt with because their network blinked.
function wire(event) {
  var next = step("transport", TRANSPORT_TABLE, CHANNELS.transport, event);
  if (next === CHANNELS.transport) return;
  CHANNELS.transport = next;
  render();
}
function wireFailed(e) { wire(e && e.answered ? "refused" : "unreachable"); }
// Noting a channel is not a reset: the board is re-read every poll, so every
// open thread is offered again each time, and a reset would return a channel
// waiting on an agent to idle roughly once a second.
function openChannel(name) {
  if (!(name in CHANNELS.protocol)) CHANNELS.protocol[name] = PROTOCOL_STATES[0];
}
function onChannel(name, event) {
  openChannel(name);
  CHANNELS.protocol[name] = step("protocol", PROTOCOL_TABLE, CHANNELS.protocol[name], event);
}
// The channels one batch touches, each once: a batch carrying two events for
// one channel is still one write on it.
function batchChannels(events) {
  var seen = {}, out = [];
  events.forEach(function (e) {
    if (!seen[e.channel]) { seen[e.channel] = true; out.push(e.channel); }
  });
  return out;
}
function channelViews() {
  return Object.keys(CHANNELS.protocol).map(function (name) {
    return { channel: name, connection: CHANNELS.transport, protocol: CHANNELS.protocol[name] };
  });
}
function severityOf(view) {
  return [TRANSPORT_SEVERITY.indexOf(view.connection), PROTOCOL_SEVERITY.indexOf(view.protocol)];
}
// One light over however many channels shows the worst of them, the wire ranked
// before the conversation. A light showing an idle map while a thread's write is
// unacknowledged reads as everything being fine.
function worstChannel() {
  return channelViews().reduce(function (worst, view) {
    if (!worst) return view;
    var a = severityOf(worst), b = severityOf(view);
    return b[0] > a[0] || (b[0] === a[0] && b[1] > a[1]) ? view : worst;
  }, null);
}
function connected() { return CHANNELS.transport === "connected"; }
// What one arriving entry says about the channel it is on. The lane's own
// entries are the whole of who-owes-whom: this page does not decide which agent
// answers a gesture, so it does not decide which channel is waiting either --
// it reads the channel the backend addressed the announcement to.
function track(entry) {
  // An event of this page's own, seen in the log, is an event no longer in
  // flight. Cleared here rather than on the receipt, because a receipt says the
  // backend took it and this says the board can be read for what it did.
  delete OUTBOX[entry.idempotency_key];
  if (entry.kind === STATUS_KIND) {
    var phase = entry.payload.phase;
    if (phase === PHASE_COMPOSING) {
      onChannel(entry.channel, "owed");
      // The wait is timed from the entry itself, not from when this page read
      // it, so a reload mid-turn comes back with the clock the human had rather
      // than one restarted at zero.
      WIRE.status[entry.channel] = { tier: entry.payload[TIER_KEY] || "", since: Date.parse(entry.timestamp) };
    } else if (phase === PHASE_REPLIED || phase === PHASE_ERROR) {
      onChannel(entry.channel, "closed");
      delete WIRE.status[entry.channel];
    }
    // `accepted` is the gesture being acknowledged where the human made it, and
    // for a fold that is not the channel the turn runs on. Starting a clock
    // there would leave a thread counting up forever against a turn the map
    // owes and the thread does not.
    return;
  }
  if (AGENT_ACTORS.indexOf(entry.actor) >= 0) onChannel(entry.channel, "arriving");
}
// The channels an agent owes a turn on, oldest wait first — the whole of what
// the waiting indicator has to say and the order it has to say it in.
function owed() {
  return Object.keys(WIRE.status).map(function (name) {
    return { channel: name, tier: WIRE.status[name].tier, waited: elapsed(WIRE.status[name].since) };
  }).sort(function (a, b) { return b.waited - a.waited; });
}
// The protocol states in which a channel is owed a turn. `sending` is not one of
// them: an unacknowledged write is the outbox's business, and a wait announced
// before the backend has taken the turn is a wait on nothing. Read off the
// channel model rather than off the lane, because a turn the lane has not yet
// named a tier for is still a turn the human is waiting on.
var OWED_PROTOCOL = ["awaiting-ack", "agent-owes", "receiving"];
function owedOn(channel) { return OWED_PROTOCOL.indexOf(CHANNELS.protocol[channel]) >= 0; }
// Clamped, because the timestamp is the backend's clock and the now is this
// browser's. A wait that reads as negative is a page saying the reply arrived
// before it was asked for.
function elapsed(since) { return Math.max(0, Math.round((Date.now() - since) / 1000)); }
// One wording for one wait, whether the row is being drawn or ticked in place.
// Two sites formatting the same clock drift, and a diagnostic disagreeing with
// itself is the thing the per-channel row exists to rule out.
function waitedText(st) { return elapsed(st.since) + "s" + (st.tier ? " · " + st.tier + " tier" : ""); }
function outboxDepth() { return Object.keys(OUTBOX).length; }

/* One event, built and checked against the table above rather than trusted
   against it: a kind, a channel class or a payload key the table does not name
   never becomes an event at all, so the declaration and the emission sites
   cannot drift apart. Every emission site in this file is a call to this. */
function ev(kind, channel, payload) {
  var rule = EMISSIONS[kind];
  payload = payload || {};
  if (!rule) throw new Error("this page does not emit " + kind);
  if (rule.channel === "map" ? channel !== MAP : channel === MAP) {
    throw new Error(kind + " does not go out on channel " + channel);
  }
  Object.keys(payload).forEach(function (k) {
    if (rule.payload.indexOf(k) < 0) throw new Error(kind + " carries no " + k);
  });
  // A kind that declares the transfer key is a kind the human speaks a turn in,
  // and every one of those turns says which tier the human has put its channel
  // on. Stamped here rather than at the emission sites so the declaration is
  // again what decides: the table says which kinds carry the flag, and no
  // gesture that is not a turn — a fold, a park, a queue verb — can acquire one.
  if (rule.payload.indexOf(TRANSFER_FLAG) >= 0) payload[TRANSFER_FLAG] = onExpert(channel);
  KEYS += 1;
  return { kind: kind, actor: "human", channel: channel,
           idempotency_key: PAGE_ID + ":" + KEYS, payload: payload };
}

/* The only place an event leaves this page. Takes a batch because some human
   gestures are one act with two events in them, and half of one landing is not
   a state the human ever asked for. */
function send() {
  var out = Array.prototype.slice.call(arguments);
  if (!out.length || !WIRE.epoch || WIRE.doctor || sessionOver()) return;
  var ending = out.filter(function (e) { return e.kind === SESSION_END_KIND; })[0];
  WIRE.sent += out.length;
  out.forEach(function (e) { OUTBOX[e.idempotency_key] = true; });
  var touched = batchChannels(out);
  // Every channel in the batch is sending, then away, then answered. Who owes a
  // turn afterwards is not decided here: the lane says so, on the channel the
  // turn runs on, and for a fold that is not the channel the human clicked in.
  touched.forEach(function (name) { onChannel(name, "submit"); });
  var posted = srvPost("/events", { epoch: WIRE.epoch, events: out });
  touched.forEach(function (name) { onChannel(name, "dispatched"); });
  posted.then(function (receipts) {
    touched.forEach(function (name) { onChannel(name, "settled"); });
    wire("reached");
    receipts.forEach(function (r) {
      // A refusal is an event that will never appear in the log, so it leaves
      // the outbox here — otherwise the depth counts messages nothing is ever
      // going to consume and reads as a backlog that does not exist.
      if (r.status !== "accepted") delete OUTBOX[r.idempotency_key];
      // The backend took the ending. Noted here rather than waited for on the
      // update read, which a stopping backend may never answer.
      // The ending is the one event whose landing this page will never read
      // back, because reading is what it stops. Left in the outbox it would
      // stand there as a permanent backlog of one.
      if (ending && r.idempotency_key === ending.idempotency_key && r.status === "accepted") {
        ENDED = true;
        delete OUTBOX[r.idempotency_key];
        // The session is over, so the tab it ran in has nothing left to do. A
        // browser refuses to close a tab this page did not open -- which is
        // every tab a human opened themselves -- and refuses it silently, with
        // nothing thrown to catch. So the ended surface is what most humans are
        // actually left looking at, and it tells them the tab is theirs to close.
        window.close();
      }
      if (r.status !== "rejected") return;
      WIRE.rejected += 1;
      // A refusal the human cannot see is a message they believe they sent.
      WIRE.lastRejection = r;
      if (r.reason === "epoch mismatch") WIRE.hydrated = false;
    });
    // Rendered here rather than left to the next poll: a refused write appends
    // nothing, so there is no arriving entry to bring the banner with it and
    // the human would be looking at a message they think they sent.
    render();
    poll();
  }, function (e) {
    touched.forEach(function (name) { onChannel(name, "settled"); });
    // A refused POST wrote nothing; an unreachable one may have. The first
    // leaves the outbox, the second stays in it until the log settles the
    // question, because a page that cleared it would be claiming to know.
    if (e && e.answered) out.forEach(function (o) { delete OUTBOX[o.idempotency_key]; });
    wireFailed(e);
  });
}

/* The board, asked for rather than asserted. This is what a reload gets, what
   a page arriving late gets, and what a page whose epoch went stale gets —
   one answer, so reconnecting can never look like a reset. */
function hydrate() {
  wire("open");
  return srvGet("/state").then(function (st) {
    WIRE.epoch = st.epoch;
    BOARD = st.image1;
    // The one moment a reload has to look like the session the human left
    // rather than a new one — so the read-state comes back here, keyed by the
    // token the claim answered with before any of this was read.
    loadRead();
    UI.held = loadWindow("held", {});
    UI.discussing = loadWindow("discussing", {});
    noteThreads();
    // The log up to here is read as a lookup table, not as news: a page
    // arriving mid-session must not announce a morning's worth of changes as
    // if they had just happened.
    return srvGet("/updates", "epoch=" + encodeURIComponent(st.epoch) + "&cursor=0").then(function (u) {
      LOG = u.entries;
      SEEN = {};
      u.entries.forEach(function (e) { SEEN[e.seq] = true; });
      // Read for channel state as well as as a lookup table, and it has to be:
      // a reload while an agent is composing must come back still waiting on
      // it. Every finished turn's own closing entry is in here too, so replaying
      // the record lands each channel exactly where the record left it.
      u.entries.forEach(track);
      WIRE.cursor = u.seq;
      WIRE.hydrated = true;
      if (!UI.focus) UI.focus = (BOARD.frontier[0] || (BOARD.decisions[0] || {}).id || null);
      wire("reached");
      render();
    });
  });
}
// Every thread on the board is a channel, whether or not this page has spoken
// on it, so the diagnostic lists them all rather than only the ones it happens
// to have sent something to.
function noteThreads() {
  BOARD.threads.forEach(function (t) { openChannel(t.id); });
}

function poll() {
  // The board is read by the window that holds the session and by no other. A
  // refused or superseded window has nothing to poll for: it is not going to
  // draw what it reads.
  if (CLAIM.state !== CLAIM_GRANTED) return;
  // A closed log has nothing further to say, and reading on would leave a
  // dead-backend indicator flickering over a session that ended on purpose.
  if (sessionOver()) return;
  if (WIRE.inflight) return;
  WIRE.inflight = true;
  // Released when the whole cycle is over, never partway: a second poll that
  // started while this one sat between the update read and the state read
  // would read the same entries again and judge them against a board that had
  // moved past them.
  var done = function () { WIRE.inflight = false; };
  if (!WIRE.hydrated) {
    hydrate().then(done, function (e) { done(); wireFailed(e); });
    return;
  }
  srvGet("/updates", "epoch=" + encodeURIComponent(WIRE.epoch) + "&cursor=" + WIRE.cursor)
    .then(function (u) {
      wire("reached");
      if (!u.entries.length) { done(); return refreshDoctor(); }
      WIRE.cursor = u.seq;
      WIRE.got += u.entries.length;
      var arrived = u.entries.filter(function (e) { return !SEEN[e.seq]; });
      arrived.forEach(function (e) { SEEN[e.seq] = true; });
      LOG = LOG.concat(arrived);
      // The board is re-read rather than folded from what just arrived: the
      // state read is the only thing that decides what the board says.
      return srvGet("/state").then(function (st) {
        BOARD = st.image1;
        noteThreads();
        advance();
        UI.fresh = [];
        UI.touched = [];
        arrived.forEach(track);
        arrived.forEach(function (e, i) { observe(e, arrived, i); });
        WIRE.doctorKnown = false;
        done();
        return refreshDoctor();
      }, function (e) { done(); wireFailed(e); });
    }, function (e) {
      done();
      // The backend is telling us it is not the process we started with.
      // Re-read state rather than carry a stale board forward, and assert
      // nothing on the way.
      if (e && e.stale) { WIRE.hydrated = false; poll(); return; }
      wireFailed(e);
    });
}
// The doctor check is a control, not board content: it says whether the board
// is frozen against a reassessment in flight, which is what the page holds its
// modal against. It is polled rather than read from the log because the freeze
// is a property of this process and never of the record.
// The auto-advance the last answer asked for, now that the board it depends on
// is here: a child the answer just unblocked, else the oldest thing waiting.
function advance() {
  if (!UI.advanceFrom) return;
  var next = nextFocus(UI.advanceFrom);
  if (next && next !== UI.advanceFrom) focusOn(next);
  UI.advanceFrom = null;
}
function refreshDoctor() {
  return srvGet("/doctor").then(function (d) {
    var changed = d.outstanding !== WIRE.doctor || !WIRE.doctorKnown;
    WIRE.doctor = d.outstanding;
    WIRE.doctorKnown = true;
    if (changed) render();
  }, function () { WIRE.doctorKnown = false; });
}

/* ---------------- reading the log for what image 1 does not carry ---------------- */

// The sub-updates an entry carries, each wearing the id the backend gives it. A
// fold and an apply hold theirs in a list; everything else is one update wearing
// the entry's own kind.
//
// `uid` is the backend's own derivation, restated here rather than invented: the
// entry's idempotency key for a single update, and key#index for a sub-update of
// a fold-shaped entry. The index counts every object in `updates`, including one
// this page then drops for naming no kind — an index taken after the filter would
// name a different update than the queue does, and the two only disagree on the
// malformed entry nobody is looking at.
function updatesIn(entry) {
  var key = entry.idempotency_key;
  if (entry.kind === "fold" || entry.kind === APPLY_KIND) {
    var out = [];
    (entry.payload.updates || []).forEach(function (u, i) {
      if (!u || typeof u !== "object" || !u.kind) return;
      var one = {};
      Object.keys(u).forEach(function (k) { one[k] = u[k]; });
      one.uid = key + "#" + i;
      out.push(one);
    });
    return out;
  }
  var one = { kind: entry.kind };
  Object.keys(entry.payload).forEach(function (k) { one[k] = entry.payload[k]; });
  one.uid = key;
  return [one];
}
function entryAt(seq) {
  return LOG.filter(function (e) { return e.seq === seq; })[0] || null;
}
// The bytes behind a queue entry: the update its author actually wrote. Image 1
// says what is waiting, not what it would do, so the text comes from the log.
// Matched on the id, which is the one thing that names exactly one update — a
// fold carrying two revises of the same decision has two entries the queue can
// tell apart and a kind-and-target match cannot.
function sourceOf(item) {
  var e = entryAt(item.authored_at);
  if (!e) return null;
  return updatesIn(e).filter(function (u) { return u.uid === item.id; })[0] || null;
}
// When a queue entry was written, in the operating system's time zone. The queue
// carries the sequence it was authored at and no clock; the log carries the
// clock, so the two are read together.
function stampOf(item) {
  var e = entryAt(item.authored_at);
  return e ? stamp(e.timestamp) : "";
}
// How one update reads to the human, whichever end it is met from -- a queue
// entry the inbox is showing, or an entry the log just delivered. One reader,
// because the same change described two ways in the inbox and in the
// notification for it reads as two changes.
function summarise(item) {
  return summariseUpdate(sourceOf(item) || { kind: item.kind, target: item.target });
}
function summariseUpdate(u) {
  if (u.text) return u.text;
  if (u.why) return u.why;
  if (u.kind === "add-node") return "A new decision: " + (u.title || u.target);
  return u.kind + " on " + (u.target || "the board");
}
// A queued change whose target the human moved after it was written. Applying
// it now would overwrite the change they made while it waited, so the backend
// refuses it — this is the same measurement, made where the human can see it.
function conflicted(item) {
  if (!item.target) return false;
  return LOG.some(function (e) {
    return e.actor === "human" && e.seq > item.authored_at &&
      updatesIn(e).some(function (u) { return u.target === item.target; });
  });
}
// What folding this thread would hand over: its last turn, when an agent wrote
// it. That is the same reading the backend makes of a folded thread — the
// conclusion it dispatches to the grill-master is the last turn's text — so the
// control is armed exactly when there is a conclusion to hand over, and the
// preview quotes what will actually cross. A thread whose last turn is the
// human's has none: folding there would hand the grill-master their own words
// back, so the next thing the human says disarms it again until the agent
// answers.
function foldReady(threadId) {
  var t = thread(threadId), turns = (t && t.turns) || [];
  var last = turns[turns.length - 1];
  return last && AGENT_ACTORS.indexOf(last.who) >= 0 ? last : null;
}

/* ---------------- which tier each channel is on ----------------
   The mode is not on image 1 and is not held anywhere on the backend: it is the
   last thing the log said about that channel, and the backend reads it back the
   same way at the moment it routes the next turn. So this page reads it from the
   record too, rather than remembering what it clicked — a reload, a second
   window and a restarted backend all then agree about which tier a channel is
   on, because all three are reading one fact.

   Two things say it, and the later one wins: the human's own turn carrying the
   transfer key, and the lane's `transferred` entry, which is the escalation
   policy moving the channel with nobody pressing anything. An agent's own reply
   says nothing about it in either direction.

   `TRANSFER` is the gap between a click and the turn that carries it. Activation
   forces the *next* turn, so the click alone forces nothing; what it does is
   decide what the next turn will say, and that intent lives here until the log
   speaks after it — which is why the click is stamped with where the log stood
   when it was made. A click whose turn was refused keeps its intent, because
   nothing landed after it; a click the policy then overtook loses it, because
   the control must name where the channel is now and not the tier it has left. */
var TRANSFER = {};
function loggedMode(channel) {
  for (var i = LOG.length - 1; i >= 0; i--) {
    var e = LOG[i];
    if (e.channel !== channel || !e.payload) continue;
    if (e.actor === "human" && TRANSFER_FLAG in e.payload) {
      return { on: e.payload[TRANSFER_FLAG] === true, at: i };
    }
    if (e.kind === STATUS_KIND && e.payload.phase === PHASE_TRANSFERRED) return { on: true, at: i };
  }
  return { on: false, at: -1 };
}
function onExpert(channel) {
  var said = loggedMode(channel), meant = TRANSFER[channel];
  return meant && meant.since > said.at ? meant.on : said.on;
}
// What an agent turn is called, read off that turn's own attribution and never
// off the channel it sits on. The channel's mode says where the channel is now;
// reading it here would relabel every turn taken before a transfer as the tier
// that came after it, and the transcript is the human's only evidence that the
// transfer changed anything.
//
// A turn nobody attributed gets no label rather than a guessed one — the human's
// turns, the backend's, and anything an older session recorded before tiers were
// written down.
function tierLabel(tier) {
  return tier === HEAVY_TIER ? "expert agent" : tier === FAST_TIER ? "fast agent" : "";
}
// The tier an entry attributed itself to, for the map channel's turns: those
// reach the page as queue items and notifications rather than as projected
// turns, so the attribution is read back off the entry that authored them.
function tierAt(seq) {
  var e = entryAt(seq);
  return (e && e.payload && e.payload[TIER_KEY]) || null;
}
function toggleTransfer(channel) { TRANSFER[channel] = { on: !onExpert(channel), since: LOG.length }; render(); }
// The escalation advice on this channel's latest agent reply, or nothing. A
// property of the last reply rather than of the session, so the next reply that
// meets no condition is what takes the highlight away — advice about a question
// two turns ago is not advice about this one.
//
// An agent actor and an attributed payload, both: the lane's own `composing`
// entry names a tier as well, so a filter on either half alone would be reading
// the status lane instead of a reply.
function recommended(channel) {
  for (var i = LOG.length - 1; i >= 0; i--) {
    var e = LOG[i];
    if (e.channel !== channel || AGENT_ACTORS.indexOf(e.actor) < 0) continue;
    if (!e.payload || !(TIER_KEY in e.payload)) continue;
    return e.payload[RECOMMENDATION_KEY] || null;
  }
  return null;
}

/* ---------------- selectors over the board ---------------- */

function node(id) { return BOARD.decisions.filter(function (d) { return d.id === id; })[0] || null; }
function thread(id) { return BOARD.threads.filter(function (t) { return t.id === id; })[0] || null; }
function live(item) { return !item.superseded; }
// The inbox: what has NOT landed. The queue's own kind is what tells a waiting
// change from a message the human was already given.
function proposals() {
  return BOARD.pending.filter(function (p) { return live(p) && PROPOSABLE_KINDS.indexOf(p.kind) >= 0; });
}
function notices() {
  return BOARD.pending.filter(function (p) { return live(p) && NOTICE_KINDS.indexOf(p.kind) >= 0; });
}
// Which decisions a message from the agent is read on: the one it names, and
// when it names none, the ones its own entry changed in the same breath. A
// reply that speaks and changes the board arrives as one entry, and the prose
// half of it is framing for the other half — so it belongs on what it framed
// rather than in a lane of its own.
//
// Derived from the log rather than remembered from the arrival, because the
// board has to read the same after a reload as before one: the queue survives a
// reload and anything this page noticed at arrival does not.
//
// A home is a decision the board is carrying now, which is what makes "the
// board already shows this" measured rather than assumed: a message about
// something the board has no block for has nowhere to be read, and goes to the
// lane.
function noticeHomes(item) {
  var out = [];
  var add = function (id) { if (id && node(id) && out.indexOf(id) < 0) out.push(id); };
  if (item.target) { add(item.target); return out; }
  var e = entryAt(item.authored_at);
  (e ? updatesIn(e) : []).forEach(function (u) {
    if (MAP_MUTATION_KINDS.indexOf(u.kind) >= 0) add(u.target);
  });
  return out;
}
function noticesOn(id) {
  return notices().filter(function (n) { return noticeHomes(n).indexOf(id) >= 0; });
}
// A notice the human has not read yet. The message itself stays on the board
// once read — it is board content and this page does not delete board content —
// but the marker that says look at this comes off, which is the whole of what
// being read means here.
function unreadNotices(id) {
  return (id === undefined ? notices() : noticesOn(id)).filter(function (n) { return !isRead(n.id); });
}
function proposalsOn(id) {
  return proposals().filter(function (p) { return p.target === id; });
}
function settledIds() {
  var m = {};
  BOARD.settled.forEach(function (s) { m[s.id] = s.answer; });
  return m;
}
// Whether a prereq has stopped holding what rests on it: answered, or gone from
// the flow. An invalidated prereq never settles, so a dependent still shown as
// waiting on it waits for the rest of the session. The board's own frontier
// reads it the same way, and this is the page saying the same thing rather than
// a second rule.
function cleared(p, done) {
  return (p in done) || (node(p) || {}).status === "invalidated";
}
// Whether the board itself says this decision can be answered now. The frontier
// is the backend's answer to that and the page does not compute a second one.
function answerable(id) { return BOARD.frontier.indexOf(id) >= 0; }
// Whether this decision takes an answer right now. The frontier is the board's
// word on that, and a settled decision is off it -- but replacing an answer
// already given is exactly what taking a proposal onto a settled decision is,
// so an armed one takes an answer again. Only that decision, and only while the
// arming stands: every other settled decision is still the agent's to reopen.
function takesAnswer(id) {
  var d = node(id);
  return answerable(id) || !!(UI.armed[id] && d && d.status === "settled");
}
// What is holding this decision, and which of the two kinds of hold it is.
// The board's own lock — a waiting change, or a blocking alert — comes back as
// `locked`; the queue is what says which. An unfinished thread the agent
// declared action-required is the page's own hold, because a decision whose
// open question is unanswered is not one to change around.
function holdOn(id) {
  var d = node(id);
  if (!d) return null;
  var waiting = proposalsOn(id);
  if (waiting.length) return { kind: "pending", items: waiting };
  // An answer held against a mandated thread is a hold of its own: the pick is
  // made and only the conclusion applies it, so nothing may be answered around
  // it in the meantime.
  if (mandateHolding(id)) return { kind: "elicitation", threads: [d.mandate.threadId] };
  var blocking = blockingThreads(id);
  if (blocking.length) return { kind: "elicitation", threads: blocking };
  if (d.locked) return { kind: "elicitation", threads: [] };
  return null;
}
function conflictOn(id) {
  return proposalsOn(id).filter(conflicted)[0] || null;
}
function threadsOf(id) {
  return BOARD.threads.filter(function (t) { return t.decision === id; }).map(function (t) { return t.id; });
}
function mandateThread(d) { return d.mandate ? thread(d.mandate.threadId) : null; }
// A mandated decision cannot settle on a click: the answer is held here, unsent,
// until the thread concludes. Held rather than posted because the board must not
// carry an answer nobody has committed to.
function mandateHolding(id) {
  var d = node(id);
  if (!d || !d.mandate || d.status === "settled") return false;
  var t = mandateThread(d);
  return !!UI.held[id] && !(t && t.state === "folded");
}
function mandateOpen(d) {
  if (!d.mandate || d.status === "settled") return false;
  var t = mandateThread(d);
  return !(t && t.state === "folded");
}
// A blocking thread: one the agent said requires action and that has not ended.
// A decision's own mandated thread is never one of them. What that thread holds
// is the answer, which is already the mandate's hold and is already refused
// around; counting it here as well would lock the decision out of being picked
// again after the human abandoned a pick, leaving a thread that must conclude on
// an answer that can no longer be made.
function blockingThreads(id) {
  var d = node(id), mandated = d && d.mandate ? d.mandate.threadId : null;
  return threadsOf(id).filter(function (tid) {
    var t = thread(tid);
    return tid !== mandated && t.requires_action && t.state === "open";
  });
}
// Whether an option is still on the decision. Asked before an answer goes out
// that was picked some time ago: the options are the agent's to revise.
function optionOn(id, option) {
  var d = node(id);
  return !!d && d.options.some(function (o) { return o.id === option; });
}

function statusOf(id) {
  var d = node(id);
  if (!d) return "blocked";
  if (d.status === "settled" || d.status === "invalidated" || d.status === "fogged") return d.status;
  if (conflictOn(id)) return "conflicted";
  if (mandateHolding(id)) return "awaiting-thread";
  // A locked decision keeps its own status and wears the lock; a decision the
  // frontier has not reached is waiting on what it rests on.
  if (d.locked || answerable(id)) return d.status;
  return d.status === "stale" ? "stale-blocked" : "blocked";
}
function waitingOn(id) {
  var d = node(id), done = settledIds();
  var open = d.prereqs.filter(function (p) { return !cleared(p, done); });
  var stuck = open.filter(function (p) { return conflictOn(p); })[0];
  return { list: open, conflict: stuck || null };
}
// The answer as one line. An option answered with a note is both, in that order:
// showing only the note would hide which option was taken, and showing only the
// option would drop the reason the human wrote down for taking it.
function answerTextOf(id) {
  var d = node(id);
  if (!d || !d.answer) return null;
  if (!d.answer.option) return d.answer.text;
  var o = d.options.filter(function (x) { return x.id === d.answer.option; })[0];
  var lab = labelOf(d, d.answer.option);
  var chosen = (lab ? lab + ") " : "") + (o ? o.text : d.answer.option);
  return d.answer.text ? chosen + " — " + d.answer.text : chosen;
}
function depthOf(id, seen) {
  var d = node(id);
  seen = seen || {};
  if (!d || !d.prereqs.length || seen[id]) return 0;
  seen[id] = true;
  return 1 + Math.max.apply(null, d.prereqs.map(function (p) { return node(p) ? depthOf(p, seen) : 0; }));
}
function layers() {
  var out = [];
  BOARD.decisions.forEach(function (d) {
    var k = depthOf(d.id);
    (out[k] = out[k] || []).push(d.id);
  });
  return out;
}
// Column order: tree structure, depth first, board order within a depth. Never
// reordered by answering, folding or applying.
function columnOrder() {
  var out = [];
  layers().forEach(function (ids) { if (ids) out = out.concat(ids); });
  return out;
}
// Per-decision history, read off the one session log rather than a second
// record of it.
function historyOf(id) {
  var out = [];
  LOG.forEach(function (e) {
    updatesIn(e).forEach(function (u) {
      if (u.target === id) out.push({ seq: e.seq, actor: e.actor, kind: u.kind, why: u.why || u.text || "" });
    });
  });
  return out;
}
// Prefer a child just unblocked by what was settled, else the oldest thing on
// the frontier.
function nextFocus(justSettled) {
  var f = BOARD.frontier;
  if (!f.length) return null;
  if (justSettled) {
    var child = f.filter(function (id) { return node(id).prereqs.indexOf(justSettled) >= 0; })[0];
    if (child) return child;
  }
  return f[0];
}
// The next answerable decision after the one in focus, wrapping at the end. The
// frontier is the board's own word on what can be answered and its own order,
// so this walks it rather than computing a second answer; a focus sitting off
// the frontier starts the walk at its head.
function nextOpen() {
  var f = BOARD.frontier;
  if (!f.length) return null;
  return f[(f.indexOf(UI.focus) + 1) % f.length];
}
// Why there is nowhere to go, told apart. A board with nothing left to answer
// has either finished or stalled, and a human told only that the control is
// dead cannot tell whether to end the session or go unblock something. The
// finished reading is the board's one reading, not a second one written here.
function nextOpenWhy() {
  return boardFinished() ? "nothing is left open" : "everything still open is waiting";
}
// The walk itself. There is no bare-key shortcut beside it: every focus move
// hands the caret to the focused decision's note box, so a second press of a
// bare letter would land in what the human is writing rather than on the board.
function goNextOpen() {
  var id = nextOpen();
  if (id) { focusOn(id); render(); }
}

/* ---------------- what landed, observed as it lands ---------------- */

// One notification, named by the update it reports rather than by its position
// in this list. The id is the update's own, so the same thing seen twice — as a
// queue entry the board still carries and as the notification announcing it —
// is one thing to mark read, and marking it read outlives the reload that
// empties this list and leaves the queue standing.
//
// `at` is the log entry's clock, not this page's: a notification says when the
// agent did the thing, and a page arriving late must not restamp a morning's
// work with the moment it happened to read it.
// `seq` is the entry the message came out of, kept so the lane can name the tier
// that said it: a map turn with nothing on the board to attach to is read here
// and nowhere else, and an unlabelled one is an agent turn the human cannot tell
// the tier of.
function noteFor(id, kind, target, text, type, at, seq) {
  return { id: id, kind: kind, type: type, target: target || null, text: text, at: at, seq: seq };
}
// Whether a human queue gesture arrived after this entry in the same batch.
// The queue is read once per batch, so an agent's change that a later gesture
// in that batch resolved would be measured against a board already past it --
// and a change the human dismissed would be marked as one that arrived.
// Judgement is withheld rather than guessed.
function resolvedLater(batch, index) {
  for (var i = index + 1; i < batch.length; i++) {
    var later = batch[i];
    if (later.actor === "human" && (later.kind === APPLY_KIND || later.kind === DISMISS_KIND)) return true;
  }
  return false;
}
// One arriving entry, read for what it means to the human. The board it changed
// has already been re-read; nothing here decides anything about the board.
//
// The board is the primary display of state, and the notification lane carries
// only what the board does not. So one message reaches the lane — the agent
// speaking to the human with nothing on the board to attach it to — and
// everything else raises marks on the board and no notification at all.
function observe(entry, batch, index) {
  // The lane is read for channel state, which happens before this and on the
  // reload path too. It is never news: nobody wants a notification saying an
  // agent started typing.
  if (entry.kind === STATUS_KIND) return;
  // The apply gesture is the human's, and it is what lands the changes they
  // were looking at — so its updates are news, and the proposals it resolved
  // were deliberately not.
  if (entry.actor === "human" && entry.kind !== APPLY_KIND) return;
  updatesIn(entry).forEach(function (u) {
    if (NOTICE_KINDS.indexOf(u.kind) >= 0) {
      // A message the board has somewhere to put is read there. Announcing it
      // as well is the lane echoing the board, and a lane that echoes the board
      // is one the human learns to stop opening.
      var homes = noticeHomes({ target: u.target || null, authored_at: entry.seq });
      homes.forEach(function (id) { UI.touched.push(id); });
      if (!homes.length) {
        NOTES.push(noteFor(u.uid, u.kind, u.target, u.text || "", "informational", entry.timestamp, entry.seq));
      }
      return;
    }
    if (MAP_MUTATION_KINDS.indexOf(u.kind) < 0) return;
    var waiting = BOARD.pending.some(function (p) {
      return p.authored_at === entry.seq && p.kind === u.kind && (p.target || null) === (u.target || null);
    });
    // A change that landed is on the board, in the decision's own block and in
    // its history. A receipt restating it is the board said twice, so what an
    // arriving change raises is the mark on the decision it moved and nothing
    // in the lane.
    if (u.target) UI.touched.push(u.target);
    if (waiting || (entry.actor !== "human" && resolvedLater(batch, index))) return;
    if (u.kind === "add-node" && u.target) UI.fresh.push(u.target);
  });
}
// What the human is waiting for, in one line: that the message got there, that a
// tier has it, and how long it has been. The clock is the lane's own, so it
// starts the moment the backend said a tier picked the turn up rather than when
// a model gets around to answering.
function laneText() {
  var turns = owed();
  if (!turns.length) return "";
  var first = turns[0];
  return "delivered · " + (first.tier ? first.tier + " tier " : "") + "composing on " +
    (first.channel === MAP ? "the map" : first.channel) + "… " + first.waited + "s" +
    (turns.length > 1 ? " (+" + (turns.length - 1) + " more)" : "");
}
// Everything the agent has said that the human has not read: what has landed and
// is in the notification list, and what is on the board as a queued notice. The
// two are one count because they are one question — is there anything I have not
// looked at — and two counts would disagree on the reload that empties one.
function unreadNotes() {
  return NOTES.filter(function (n) { return !isRead(n.id); });
}
function unreadIds() {
  var ids = unreadNotes().map(function (n) { return n.id; });
  unreadNotices().forEach(function (n) { if (ids.indexOf(n.id) < 0) ids.push(n.id); });
  return ids;
}
function unreadCount() { return unreadIds().length; }
// No event, no epoch, no wire. Read-state is the page's, and this is the whole
// of what the control does.
function markAllRead() {
  unreadIds().forEach(function (id) { READ[id] = true; });
  saveRead();
  render();
}

/* ---------------- gestures ---------------- */

// An answer is an option, free text, or an option with a note on it. The third
// is the common one and used to be unsendable: the human picked b and then had
// nowhere to say why, so the reason went into a thread the answer does not carry
// or nowhere at all. Both fields ride, and the backend takes either or both.
function answerOf(payload) {
  if (payload.free) return { option: null, text: payload.text };
  return { option: payload.option, text: payload.note || null };
}
// What stops a proposal arming this decision, in the words the control wears,
// and null where nothing does. Arming a box the board will not accept from does
// nothing the human can act on, so the reason is on the control rather than
// behind a press that silently fails.
function armBlock(id) {
  var d = node(id);
  if (!d) return "it is not on the board";
  var lock = holdOn(id);
  if (lock) return lock.kind === "pending" ? "a change is waiting on it" : "a thread must conclude first";
  if (mandateOpen(d)) return "its mandated thread has to conclude first";
  var st = statusOf(id);
  if (st === "fogged") return "it is in the fog until " + d.fogUntil + " settles";
  if (st === "invalidated") return "it has left the flow";
  // Settled is not a block: the proposal replaces the answer, and the control
  // says so rather than refusing.
  if (d.status === "settled") return null;
  if (!answerable(id)) return "it is waiting on " + waitingOn(id).list.join(", ");
  return null;
}
// Taking a proposal fills the decision's own answer controls and does nothing
// else. The text goes in after whatever the human has already written rather
// than over it -- no draft of theirs is discarded by an agent's -- the option
// the offer builds on is marked as the control that would record it, and the
// thread's id is left on the decision to ride the next answer sent for it.
// Nothing is appended: which control the human presses is what the answer
// becomes, and firing it here would put words on the board they have not read.
function armAnswer(tid, id) {
  var t = thread(tid), d = node(id);
  if (!t || !d || armBlock(id)) return;
  // The live offer and no other: an earlier turn's proposal is retired, and a
  // window drawn before the last turn arrived may still be showing its control.
  var offer = (t.turns[t.turns.length - 1] || {}).proposal;
  if (!offer || offer.decision !== id || t.state !== "open") return;
  var draft = (UI.drafts[id] || "").trim();
  UI.drafts[id] = draft ? draft + "\n\n" + offer.text : offer.text;
  // Re-keyed rather than overwritten, so this map reads newest-last: which of
  // several armed options is the one in hand is a question about recency.
  delete UI.armed[id];
  UI.armed[id] = { thread: tid, option: offer.option || null };
  // The decision the human is about to answer, in view and open -- a settled one
  // is collapsed, and arming it out of sight would fill a box nobody is looking at.
  UI.panel = null;
  UI.open[id] = true;
  UI.autoshut[id] = false;
  focusOn(id);
  render();
}
function answerDecision(id, payload) {
  var d = node(id);
  // The frontier is the board's word on whether this can be answered, and a
  // hold is what the page will not answer around. Neither is re-derived: a
  // refusal the human never sees is the thing this page exists to avoid.
  if (!d || !takesAnswer(id) || holdOn(id)) return;
  // The warning was worth something only before the answer. Once one is sent the
  // board says what the board says, so the live sources let go here rather than
  // waiting for the pointer to move off a control that is about to be replaced.
  UI.overOpt = UI.keyedOpt = null;
  // A mandated decision holds the answer instead of sending it: concluding the
  // thread is the only thing that settles it, and nothing is asserted until
  // then.
  if (mandateOpen(d)) {
    // Re-keyed rather than overwritten, so this map reads newest-last: which of
    // several held answers is the one in hand is a question about recency. Both
    // halves of the re-key are made durable together, as one write.
    delete UI.held[id];
    UI.held[id] = payload; saveHeld();
    var t = mandateThread(d);
    var seed = seedForMandate(d, payload);
    // The thread is told what is being held, whether this is the pick that opens
    // it or one made after an earlier pick was abandoned. A thread never told
    // would be concluded by an agent discussing a leaning the human has changed.
    send(t
      ? ev("thread-turn", d.mandate.threadId, { turns: [{ who: "human", text: seed }] })
      : ev("thread-created", d.mandate.threadId, {
          turns: [{ who: "human", text: seed }],
          decision: id, kind: "mandate", title: d.mandate.title, requires_action: true
        }));
    UI.panel = { kind: "thread", id: d.mandate.threadId };
    render();
    return;
  }
  // An answer armed from a thread carries where it came from, and that one
  // entry settles the decision and closes the thread. The provenance goes with
  // the draft it filled: it belongs to this answer and to no later one.
  var armed = UI.armed[id];
  var out = { target: id, answer: answerOf(payload) };
  if (armed) out[FROM_THREAD_KEY] = armed.thread;
  send(ev("answer", MAP, out));
  UI.drafts[id] = "";
  delete UI.armed[id];
  settledFocus(id);
}
// The label an option answers to. Position, not the option's own id: a/b/c is
// what the free text and the threads refer to it by, and it has to mean the same
// thing on the button, in the seed and in whatever the human types.
function labelAt(i) { return "abc".charAt(i) || String(i + 1); }
function labelOf(d, optionId) {
  var i = d.options.map(function (o) { return o.id; }).indexOf(optionId);
  return i < 0 ? "" : labelAt(i);
}
function seedForMandate(d, payload) {
  var chosen = payload.free ? payload.text
    : labelOf(d, payload.option) + ") " +
      (d.options.filter(function (o) { return o.id === payload.option; })[0] || {}).text;
  return "I am leaning towards: “" + chosen + "”. " +
    (payload.note ? "My note on it: “" + payload.note + "” " : "") + d.mandate.notice +
    " Concluding this thread is what settles " + d.id + ".";
}
function settledFocus(id) {
  UI.justSettled = id;
  UI.open[id] = false;
  UI.autoshut[id] = true;
  // Where to go next is a question about the board *after* this answer, and
  // that board has not come back yet. Advancing on the old one lands on the
  // decision just answered, which reads as the click having done nothing.
  UI.advanceFrom = id;
  render();
}
function foldThread(tid) {
  var t = thread(tid);
  if (!t) return;
  var held = t.decision && UI.held[t.decision];
  if (t.kind === "mandate") {
    // A mandated thread concludes on the answer it is holding, so there is
    // nothing to conclude until one is picked. Folding it empty would leave the
    // decision unmandated and settleable by a plain click -- the route to an
    // answer the mandate exists to close.
    if (!held) {
      refuse("Pick an answer first. Concluding this thread is what applies it, so there is nothing to conclude yet.");
      return;
    }
    // The pick was made against the options as they stood, and the agent may
    // have revised them while the thread ran. An answer records whatever option
    // id it is sent, so one naming an option the decision no longer has settles
    // it onto something nobody can read. The pick goes, the words that came with
    // it are handed back, and the human picks again.
    if (held.option && !optionOn(t.decision, held.option)) {
      delete UI.held[t.decision];
      saveHeld();
      UI.drafts[t.decision] = held.note || "";
      refuse("The option you were holding is no longer on " + t.decision +
        " — it was revised while this thread ran. Nothing was recorded, and your note is back in the box: pick again from the options as they stand.");
      return;
    }
  }
  if (held) {
    // Concluding a mandated thread is what settles the decision, on the answer
    // that was held. One batch, because the two are one gesture.
    send(ev("thread-fold", tid, {}), ev("answer", MAP, { target: t.decision, answer: answerOf(held) }));
    delete UI.held[t.decision];
    saveHeld();
    UI.panel = null;
    settledFocus(t.decision);
    return;
  }
  send(ev("thread-fold", tid, {}));
  UI.panel = null;
  render();
}
function parkThread(tid) {
  send(ev("thread-park", tid, {}));
  UI.panel = null;
  render();
}
// Closing is the human saying they are done with the thread, and parking is
// the human saying they may come back to it. Only the second is carried to the
// end of the session as a loose end. Neither takes anything away: a closed
// thread stays readable, and saying something in one opens it again, which is
// why there is no re-open gesture to send.
function closeThread(tid) {
  send(ev("thread-close", tid, {}));
  UI.panel = null;
  render();
}
// Abandoning a mandated answer reverts the selection; the decision returns to
// the frontier having never carried an answer.
//
// The thread is left where it is rather than parked. It is the mandate's thread
// and not the answer's -- a mandate names one thread id, nothing creates that id
// twice, and a parked thread can be neither spoken in nor concluded. Parking it
// here left the next pick held against a conversation with no way forward and no
// way back except abandoning that pick too.
function abandonAnswer(id) {
  delete UI.held[id];
  saveHeld();
  UI.panel = null;
  focusOn(id);
  render();
}
// The gesture is sent and nothing is announced. What the apply landed becomes
// news when the apply itself comes back down the update read -- which is the
// only way to be sure it landed at all. Announcing it here would tell the human
// a change had been applied while the backend was refusing it for conflicting
// with the board.
function applyPending(ids) {
  if (!ids.length) return;
  send(ev("apply", MAP, { pending: ids }));
  UI.panel = null;
  render();
}
function dismissPending(ids) {
  if (!ids.length) return;
  send(ev("dismiss", MAP, { pending: ids }));
  UI.panel = null;
  render();
}
// Discussing a waiting change is an ordinary thread, seeded from the change.
// Nothing about it is settled until the human lets it land or the agent is
// talked out of it.
function discussPending(id) {
  var item = BOARD.pending.filter(function (p) { return p.id === id; })[0];
  if (!item) return;
  var tid = "t-pending-" + KEYS + "-" + (item.target || "board");
  send(ev("thread-created", tid, {
    turns: [{ who: "human", text: "Before I let this land on " + (item.target || "the board") + ": " +
      summarise(item) + " Talk me through why, because it changes something I already decided." }],
    decision: item.target, kind: "pending", title: "Should this change land on " + (item.target || "the board") + "?",
    requires_action: false
  }));
  UI.discussing[tid] = id;
  saveDiscussing();
  UI.panel = { kind: "thread", id: tid };
  render();
}
// Returns the thread it opened, so a caller that has to follow the new thread
// -- a popped window, which cannot see the panel the main one moves -- learns
// its name from the one place that mints it.
function startThread(id, text, from) {
  if (!text || !text.trim()) return null;
  // No decision anchor is a session-scoped thread: the human is asking about
  // the board or about the map as a whole, not about a question on it. It gets
  // the one name a session has for it, so a second visit finds the first
  // conversation rather than opening a second one beside it. Which of the two
  // it is comes from the draft's own name rather than from the missing anchor,
  // which both share, and the kind is what tells the backend which brief the
  // thread's agent takes.
  var session = !id;
  var map = session && from === MAP_THREAD;
  var tid = !session ? "t-" + id + "-" + KEYS + "-" + Math.random().toString(36).slice(2, 6)
    : map ? MAP_THREAD : HELP_THREAD;
  // `from` is the draft's own channel, which is not the name the thread gets.
  // The tier the human put the draft on is carried onto the minted name before
  // the turn is built, so a transfer pressed before there was anything to say is
  // the tier that first turn is taken on rather than a press that did nothing.
  if (from && TRANSFER[from]) TRANSFER[tid] = TRANSFER[from];
  send(ev("thread-created", tid, {
    turns: [{ who: "human", text: text.trim() }],
    decision: session ? null : id,
    kind: !session ? "user" : map ? "map" : "help",
    title: !session ? titleFrom(text, id) : map ? MAP_THREAD_TITLE : "How this board works",
    requires_action: false
  }));
  UI.panel = { kind: "thread", id: tid };
  render();
  return tid;
}
// Open a session-scoped thread if it exists, and otherwise stand a draft of it
// up. Opening one says nothing: nothing is created until the human types.
function openSessionThread(tid) {
  if (!thread(tid)) UI.draftFor = { thread: tid, decision: null };
  UI.panel = { kind: "thread", id: tid };
  render();
}
function sayInThread(tid, text) {
  if (!text || !text.trim()) return;
  send(ev("thread-turn", tid, { turns: [{ who: "human", text: text.trim() }] }));
  render();
}
// A seed prompt is the human's own turn, said for them. It goes out on the
// thread's channel like anything they typed — same event, same key, same
// outbox — so a seed is a shortcut for the human's hands and not a second way
// into the log. On a decision whose discussion has not started, saying one is
// what opens the thread, which is the state most seeds are written for.
function saySeed(tid, id, field) {
  var d = node(id), text = d && d.talk ? d.talk[field] : "";
  if (!text) return null;
  if (tid && thread(tid)) { sayInThread(tid, text); return tid; }
  return id ? startThread(id, text) : null;
}
// Finished means every decision the board is carrying has come to rest: either
// the human settled it, or an answer mooted it and the invalidate that says so
// has landed. An invalidated decision is a closed question, not a loose end --
// invalidation is how a killing answer closes what it kills -- so a board of
// one answer and eight invalidated is a finished board. Stale is a decision
// somebody still has to move, and fog lifts on its own once what it waits for
// is answered, so both hold the board open. That is the same reading the
// terminal result takes -- its open items are the decisions neither settled nor
// invalidated -- so a board this page calls finished is a board that would be
// written up with nothing left open. An empty board is not a finished one; it
// is a board nothing has been put on yet.
function boardFinished() {
  return BOARD.decisions.length > 0 && BOARD.decisions.every(function (d) {
    return d.status === "settled" || d.status === "invalidated";
  });
}
// How the finished board reads in the offer's own words: what was answered and
// what left the flow, counted, because a human told only that the board is
// clear cannot tell an answered question from a mooted one.
function completionTally() {
  var all = BOARD.decisions.length;
  var aside = BOARD.decisions.filter(function (d) {
    return d.status === "invalidated";
  }).length;
  if (!aside) return "Every decision on this board is settled";
  return all + (all === 1 ? " decision: " : " decisions: ") + (all - aside) + " answered, " +
    aside + " left the flow";
}
// The overlay announces the board *arriving* at that state rather than sitting
// in it, so it is armed on the crossing and disarmed by leaving. An agent
// adding an open node takes the board back out, which drops the overlay and the
// pulse together; settling that node announces the arrival again. Nothing here
// is remembered anywhere but this page, so a reload into an unfinished board
// carries neither.
function noteCompletion() {
  var done = !sessionOver() && boardFinished();
  if (done && !UI.wasDone) { UI.done = true; UI.pulse = false; }
  if (!done) { UI.done = false; UI.pulse = false; }
  UI.wasDone = done;
}
// The offer, worded as an offer: the human is told what is true and asked what
// they want, and neither answer is the one this page prefers. The end action is
// the top row's own control by act, so there is one gesture into ending a
// session and this is a second place to reach it rather than a second way.
function completionOffer() {
  return '<div class="scrim" id="completion"><div class="box"><h3>🏁 Every question is answered</h3>' +
    "<p>" + completionTally() + ". Nothing on this board is waiting on you. Ending the session " +
    "writes the result beside the log and hands it back. Nothing forces that now — the board is " +
    "yours to go back over.</p>" +
    '<div class="acts"><button class="btn primary" data-act="endsession">End the session</button>' +
    '<button class="btn" data-act="dismiss-completion">Back to the board</button></div></div></div>';
}
function endSession() {
  send(ev("session-end", MAP, {}));
  render();
}
function callDoctor() {
  if (sessionOver()) return;
  srvPost("/doctor").then(function (d) { WIRE.doctor = d.outstanding; render(); }, wireFailed);
}
function titleFrom(text, anchor) {
  var w = String(text).replace(/\s+/g, " ").trim().split(" ").slice(0, 8).join(" ");
  return anchor + " — " + w.replace(/[.,;:!?]$/, "");
}

/* ---------------- rendering ---------------- */

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c];
  });
}
var LABELS = {
  settled: "settled", open: "on the frontier", blocked: "waiting", stale: "needs re-confirming",
  "stale-blocked": "stale · waiting", fogged: "fog", conflicted: "conflict — needs judging",
  "conflict-blocked": "waiting on a conflict upstream",
  "awaiting-thread": "answer held · thread must conclude", invalidated: "left the flow"
};
function pill(status) { return '<span class="pill ' + status + '">' + LABELS[status] + "</span>"; }
// The trade-off an option carries, on its own icon beside that option, and
// nothing where an option carries none -- an icon on an option with nothing
// behind it is a promise of a reason that never arrives. The three statements
// ride on the icon, so the icon is what the overlay's one selector finds.
function pcrIcon(o) {
  var p = o.pcr || [];
  if (!p[0]) return "";
  return '<button type="button" class="pcricon" aria-label="what option ' + esc(o.text) +
    ' buys, costs and forces later"' +
    ' data-p="' + esc(p[0]) + '" data-c="' + esc(p[1] || "") + '" data-r="' + esc(p[2] || "") + '"' +
    ' data-otext="' + esc(o.text) + '">⇄</button>';
}
function stamp(iso) {
  if (!iso) return "";
  var d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}
function focusOn(id) { UI.focus = id; UI.centerNext = true; }

function answerControls(d, locked) {
  var h = "", dis = locked ? " disabled" : "";
  var current = answerTextOf(d.id);
  if (current) h += '<div class="prior"><strong>Currently:</strong> ' + esc(current) + "</div>";
  var held = UI.held[d.id];
  if (held) {
    var heldText = held.free ? held.text
      : labelOf(d, held.option) + ") " +
        (d.options.filter(function (o) { return o.id === held.option; })[0] || {}).text;
    h += '<div class="prior"><strong>Held, not applied:</strong> ' + esc(heldText) +
      (held.note ? " — " + esc(held.note) : "") + "</div>";
  }
  if (!d.options.length) return h + '<div class="muted">This decision offers no options yet.</div>';
  h += '<div class="rec-line">Recommended answer' + (locked ? " · locked" : "") + "</div>";
  // Every option wears its label, the recommended one included, because the
  // label is what the human writes down and says in a thread — and a
  // recommendation that had no label would be the one option nobody could name.
  h += optionButton(d, d.options[0], 0, "btn primary wide", "➡️ ", dis);
  h += '<div class="alts">';
  d.options.slice(1).forEach(function (o, i) {
    h += optionButton(d, o, i + 1, "btn wide sm", "", dis);
  });
  h += "</div>";
  // One box, two jobs: what you type is a free-text answer if you send it on its
  // own, and the note on an option if you then pick one. A second textarea for
  // the note would be a second empty box on every decision, and the human would
  // still have to work out which one they were in.
  h += '<div class="free"><textarea id="ft-' + esc(d.id) + '" data-draft="' + esc(d.id) + '" data-send="free" data-id="' + esc(d.id) +
    '" placeholder="…answer in your own words — or write a note, then pick an option to record both"' + dis + "></textarea>" +
    '<span class="hint">↵ send<br>⇧↵ newline</span>' +
    '<button class="btn sm" data-act="free" data-id="' + esc(d.id) + '"' + dis + ">Use this</button></div>";
  return h;
}
function optionButton(d, o, index, cls, lead, dis) {
  var armed = UI.armed[d.id];
  if (armed && armed.option === o.id) cls += " armed";
  return '<div class="optrow"><button class="' + cls + '" data-act="pick" data-id="' + esc(d.id) +
    '" data-opt="' + esc(o.id) + '" data-label="' + esc(labelAt(index)) + '"' + dis + ">" + lead +
    '<span class="olab">' + labelAt(index) + "</span>" + esc(o.text) + "</button>" +
    pcrIcon(o) + "</div>";
}

/* ---------- what the option in hand would put in question ---------- */
// A mark that is the page's alone: it crosses no wire, appends nothing, and a
// reload with nothing in hand comes back to a board without it. What actually
// moves a decision is still an invalidate the agent wrote and the human applied.
//
// One option is in hand at a time, and the sources rank: the pointer on an
// option's control, else the caret on one, else an armed option, else an answer
// held behind a mandated thread. So the pointer leaving falls back to whatever
// still holds, a lower source arriving under a higher one changes nothing, and
// the marks are that one option's rather than the union of everything in reach.
function optionOf(target) {
  var control = target && target.closest ? target.closest('[data-act="pick"]') : null;
  return control ? { id: control.dataset.id, option: control.dataset.opt } : null;
}
// The same naming read the other way: the control an option answers to, on the
// board as it stands now. Membership rather than a selector, because a decision
// id is the plan author's string and a selector would be a query built out of it.
function optionControl(hand) {
  var all = document.querySelectorAll('[data-act="pick"]');
  for (var i = 0; i < all.length; i++) {
    if (all[i].dataset.id === hand.id && all[i].dataset.opt === hand.option) return all[i];
  }
  return null;
}
// Newest-last, and only an entry that stands on an option: a free-text answer
// held behind a mandate predicts nothing, because no option authored it.
function lastOptionIn(map) {
  var ids = Object.keys(map), i = ids.length;
  while (i--) {
    if (map[ids[i]] && map[ids[i]].option) return { id: ids[i], option: map[ids[i]].option };
  }
  return null;
}
function optionInHand() {
  return UI.overOpt || UI.keyedOpt || lastOptionIn(UI.armed) || lastOptionIn(UI.held);
}
function preMarked() {
  var hand = optionInHand(), d = hand && node(hand.id);
  var picked = d && d.options.filter(function (o) { return o.id === hand.option; })[0];
  return (picked && picked.puts_in_question) || [];
}
// Painted onto the rendered board rather than rendered into it. The mark changes
// on every pass of the pointer, and re-rendering the column under a human
// reaching for an option would replace the control they were reaching for.
// Membership rather than a selector, so an id naming no node simply matches
// nothing and an id carrying selector punctuation is not a query at all.
function paintPreMarks() {
  var marked = preMarked(), drawn = document.querySelectorAll(".mnode, .item");
  for (var i = 0; i < drawn.length; i++) {
    drawn[i].classList.toggle("premark", marked.indexOf(drawn[i].dataset.id) >= 0);
  }
}
// Repainted only when the option in hand actually changed: the pointer crosses
// dozens of elements on the way to a control, and every one of them is a
// mouseover that hands this the same answer.
function inHand(slot, found) {
  var was = UI[slot], key = function (o) { return o ? o.id + "|" + o.option : null; };
  if (key(was) === key(found)) return;
  UI[slot] = found;
  paintPreMarks();
}
// One control, on every channel anyone speaks on: the map's and each open
// thread's. Never disabled — the moment the human most wants an expert is the
// moment the first rung is going badly, and a control that greys out while a turn
// is in flight is unavailable exactly then.
//
// The label names the action the press performs and never the state the channel
// is in, and the control looks the same on either tier. A state word wearing a
// colour reads as where the channel is now, so a human on the expert tier sees
// the way back and takes it for confirmation they arrived. Where the channel is
// now is the per-turn tier labels' to say, and they say it on the transcript
// the human is already reading.
function transferControl(channel) {
  var on = onExpert(channel), rec = recommended(channel);
  var why = rec ? "The agent recommends the expert tier — " + (rec.evidence || rec.condition)
    : on ? "This channel's next turn goes to the expert tier. Press to return this channel to the first rung."
    : "Send this channel's next turn to the expert tier, carrying everything said here.";
  return '<button class="btn sm transfer' + (rec ? " rec" : "") +
    '" data-act="transfer" data-channel="' + esc(channel) + '"' +
    ' data-mode="' + esc(on ? "expert" : "fast") + '"' +
    ' data-recommended="' + esc(rec ? "1" : "0") + '" title="' + esc(why) + '">' +
    (on ? "⚡ Return to fast agent" : "⚡ Transfer to expert") + "</button>";
}
function isExpanded(id) {
  var st = statusOf(id);
  var open = st === "open" || st === "stale" || st === "awaiting-thread" || st === "conflicted";
  if (UI.open[id] === true) return true;
  // A decision the page shut when it settled is a question again once it stops
  // being settled, and rendering it shut hides the controls the human now
  // needs. An explicit collapse is the human's and is remembered either way.
  if (UI.open[id] === false) return !!UI.autoshut[id] && open;
  return open;
}
// One agent message, wherever it is met on the column: which tier said it, the
// mark that says it is unread, when it was said, and the two things to do with
// it. One reader, because the same message written twice reads as two.
//
// The tier is read back off the entry that authored it rather than off a
// projected turn: a map-channel turn reaches the page as a queue item, and the
// queue names the sequence it came from.
function infoNote(n) {
  var unread = !isRead(n.id);
  return '<div class="infonote">' + (unread ? '<span class="unreadmark">●</span> ' : "") +
    "✉ <strong>" + esc(tierLabel(tierAt(n.authored_at)) || "Agent") + ", " +
    esc(n.kind === "elicit-alert" ? "alert" : "informational") +
    ":</strong> " + esc(summarise(n)) + ' <span class="did">' + esc(stampOf(n)) + "</span>" +
    '<div style="margin-top:6px"><button class="btn sm" data-act="discussnotice" data-uid="' + esc(n.id) + '">Discuss</button>' +
    (unread ? ' <button class="btn sm" data-act="marknote" data-nid="' + esc(n.id) + '">Mark as read</button>' : "") +
    "</div></div>";
}
function itemIcons(d, expanded) {
  var id = d.id;
  var h = '<span class="icons">';
  if (unreadNotices(id).length) h += '<button class="mail" data-act="focusnode" data-id="' + esc(id) + '" title="A message from the agent">✉</button>';
  var alert = blockingThreads(id)[0];
  if (alert) h += '<button class="alerting" data-act="openthread" data-tid="' + esc(alert) + '" title="The agent wants something judged">⚠</button>';
  if (proposalsOn(id).length) h += '<button data-act="inbox" title="A change is waiting on this decision">📥</button>';
  h += '<button data-act="history" data-id="' + esc(id) + '" title="Change history">🕘</button>';
  var ts = threadsOf(id);
  h += '<button data-act="threads" data-id="' + esc(id) + '" title="Threads on this decision">⑂' +
    (ts.length ? '<span class="did"> ' + ts.length + "</span>" : "") + "</button>";
  h += '<button data-act="toggle" data-id="' + esc(id) + '" title="' + (expanded ? "Collapse" : "Expand") + '">' +
    (expanded ? "⌃" : "⌄") + "</button></span>";
  return h;
}

/* ---------- the map ---------- */
var POS = {};
function badge(cls, glyph, why, act, data) {
  return '<span class="badge ' + cls + '" data-why="' + esc(why) + '"' +
    (act ? ' data-act="' + esc(act) + '"' : "") + (data || "") + ">" + glyph + "</span>";
}
function renderMap() {
  var ls = layers(), maxDepth = ls.length - 1;
  var COL = 158, ROW = 88, X0 = 26, Y0 = 26, NW = 118, NH = 54;
  var fogCol = maxDepth + 1, slots = [];
  POS = {};
  BOARD.decisions.forEach(function (d) {
    var col = statusOf(d.id) === "fogged" ? fogCol : depthOf(d.id);
    slots[col] = slots[col] || [];
    slots[col].push(d.id);
  });
  var rows = 1;
  slots.forEach(function (ids, col) {
    if (!ids) return;
    rows = Math.max(rows, ids.length);
    ids.forEach(function (id, i) { POS[id] = { x: X0 + col * COL, y: Y0 + i * ROW }; });
  });
  var W = X0 + (fogCol + 1) * COL, H = Math.max(600, Y0 + rows * ROW + 20);

  var done = settledIds(), edges = "";
  BOARD.decisions.forEach(function (d) {
    d.prereqs.forEach(function (p) {
      var a = POS[p], b = POS[d.id];
      if (!a || !b) return;
      var fixed = cleared(p, done);
      edges += '<path d="M' + (a.x + NW) + "," + (a.y + NH / 2) + " C" + (a.x + NW + 40) + "," + (a.y + NH / 2) +
        " " + (b.x - 40) + "," + (b.y + NH / 2) + " " + b.x + "," + (b.y + NH / 2) +
        '" fill="none" stroke="' + (fixed ? "#94a3b8" : "#e2e8f0") + '" stroke-width="' + (fixed ? 1.4 : 1) + '"' +
        (fixed ? "" : ' stroke-dasharray="3 3"') + "/>";
    });
  });

  var counts = { settled: 0, open: 0, blocked: 0, stale: 0, fogged: 0, conflicted: 0, invalidated: 0 };
  var nodes = "";
  BOARD.decisions.forEach(function (d) {
    var id = d.id, st = statusOf(id), p = POS[id], lock = holdOn(id), wait = waitingOn(id);
    var key = st === "stale-blocked" ? "stale" : st === "awaiting-thread" ? "open" : st;
    if (key in counts) counts[key] += 1;
    var shown = wait.conflict && (st === "blocked" || st === "stale-blocked") ? "conflict-blocked" : st;
    var badges = "";
    if (unreadNotices(id).length) {
      badges += badge("b-mail mail", "✉", "A message from the agent about this decision — readable on the block, no need to reopen it.", "focusnode", ' data-id="' + esc(id) + '"');
    }
    var alert = blockingThreads(id)[0];
    if (alert) badges += badge("b-alert alerting", "⚠", "The agent raised a question that must be concluded before this decision can change.", "openthread", ' data-tid="' + esc(alert) + '"');
    if (proposalsOn(id).length) badges += badge("b-pending", "📥", "A change is waiting in the inbox for this decision. It cannot be decided until that is applied or dismissed.", "inbox", "");
    if (conflictOn(id)) badges += badge("b-conflict", "⚡", "Your answer and the agent's change disagree. The backend will refuse the change until one of you gives way.", "inbox", "");
    if (mandateOpen(d)) badges += badge("b-mandate", "⚖", "This decision cannot be settled by choosing. Its mandated thread has to conclude first.", "focusnode", ' data-id="' + esc(id) + '"');
    if (threadsOf(id).filter(function (t) { return thread(t).state === "parked"; }).length) {
      badges += badge("b-thread", "⑂", "A parked thread hangs off this decision. Nothing is blocked by it.", "threads", ' data-id="' + esc(id) + '"');
    }
    var fogged = st === "fogged";
    nodes += '<button class="mnode ' + shown + (mandateOpen(d) ? " mandated" : "") +
      (proposalsOn(id).length ? " pendlocked" : "") + (UI.focus === id ? " focused" : "") +
      (UI.fresh.indexOf(id) >= 0 ? " fresh" : "") + (UI.touched.indexOf(id) >= 0 ? " touched" : "") +
      '" style="left:' + p.x + "px;top:" + p.y + 'px" data-act="mapnode" data-id="' + esc(id) + '">' +
      '<span class="mid">' + (fogged ? "· · ·" : esc(id)) + "</span><br>" +
      esc(fogged ? "?" : d.short || id) +
      (lock ? " 🔒" : "") +
      (st === "open" ? " ❓" : st === "settled" ? " ✓" : st.indexOf("stale") === 0 ? " ⚠" : "") +
      (shown === "conflict-blocked" ? '<span class="waitfor">waiting on ' + esc(wait.conflict) + "</span>" : "") +
      '<span class="badges">' + badges + "</span></button>";
  });

  var fogX = X0 + fogCol * COL - 50, walkable = nextOpen();
  return '<div class="card"><h3>The board ' +
    '<button class="btn sm" data-act="nextopen" title="Focus the next decision that can be ' +
    'answered" ' + (walkable ? "" : "disabled") + ">Next open</button>" +
    (walkable ? "" : '<span class="muted nextwhy">' + esc(nextOpenWhy()) + "</span>") +
    '<span class="spacer"></span>' +
    '<span class="muted">drag to pan · click a node to focus it · hover an icon to see what it is</span></h3>' +
    '<div class="mapscroll" id="mapscroll"><div class="mapcanvas" style="width:' + W + "px;height:" + H + 'px">' +
    '<svg width="' + W + '" height="' + H + '">' + edges + "</svg>" + nodes +
    '<div class="fogbank" style="left:' + fogX + "px;width:" + (W - fogX) + 'px"></div>' +
    '<div class="foglabel" style="left:' + (fogX + 26) + 'px">fog</div></div></div>' +
    '<div class="maplegend"><span class="lg-settled">settled · ' + counts.settled + "</span>" +
    '<span class="lg-open">frontier · ' + counts.open + "</span>" +
    '<span class="lg-stale">stale · ' + counts.stale + "</span>" +
    '<span class="lg-conflict">conflict · ' + counts.conflicted + "</span>" +
    '<span class="lg-blocked">waiting · ' + counts.blocked + "</span>" +
    '<span class="lg-fogged">fog · ' + counts.fogged + "</span></div></div>";
}

/* ---------- the one blended column ---------- */
function renderColumn() {
  var h = '<div class="card"><h3>Decisions</h3><div class="column" id="column">';
  columnOrder().forEach(function (id) {
    var d = node(id), st = statusOf(id), expanded = isExpanded(id);
    var lock = holdOn(id), waiting = proposalsOn(id), wait = waitingOn(id);
    var mandated = mandateOpen(d), conflict = conflictOn(id);
    h += '<div class="item ' + (expanded ? "" : "collapsed ") + (UI.focus === id ? "focused " : "") +
      (mandated ? "mandated " : "") + (UI.justSettled === id ? "justsettled " : "") +
      (UI.touched.indexOf(id) >= 0 ? "touched " : "") + (UI.fresh.indexOf(id) >= 0 ? "fresh" : "") +
      '" id="col-' + esc(id) + '" data-act="focus" data-id="' + esc(id) + '">';
    h += '<div class="head">' + (mandated ? '<span class="bigmark">⚖</span>' : "") +
      (lock ? '<span class="bigmark">🔒</span>' : "") +
      '<span class="did">' + esc(id) + "</span><span class=\"t\">" + esc(d.title) + "</span>" +
      itemIcons(d, expanded) + "</div>";
    h += '<div style="margin-top:5px">' + pill(st) +
      (UI.fresh.indexOf(id) >= 0 ? ' <span class="pill new">new</span>' : "") +
      (lock ? ' <span class="pill locked">🔒 locked · ' +
        (lock.kind === "pending" ? "a change is waiting" : "a thread must conclude") + "</span>" : "") + "</div>";

    if (!expanded) {
      h += '<div class="oneline">' + esc(answerTextOf(id) ||
        (st === "fogged" ? "not a real question yet — sharpens once " + d.fogUntil + " settles"
          : st === "invalidated" ? "left the flow; still here to relitigate"
          : wait.list.length ? "waiting on " + wait.list.join(", ") : d.body)) + "</div>";
      if (waiting.length) h += '<div class="pend-notice">📥 <strong>A change is waiting on this decision.</strong> ' +
        esc(summarise(waiting[0])) + ' <button class="btn sm" data-act="inbox">Open the inbox</button></div>';
      if (blockingThreads(id).length) h += '<div class="blocking"><span class="tag">blocking</span>' +
        esc(thread(blockingThreads(id)[0]).title) + ' <button class="btn sm warn" data-act="openthread" data-tid="' +
        esc(blockingThreads(id)[0]) + '">Open it</button></div>';
      noticesOn(id).forEach(function (n) { h += infoNote(n); });
    } else {
      // A blocking thread goes at the TOP of the block, clearly marked.
      blockingThreads(id).forEach(function (tid) {
        h += '<div class="blocking"><span class="tag">blocking — this decision cannot change until it concludes</span>' +
          esc(thread(tid).title) + ' <button class="btn sm warn" data-act="openthread" data-tid="' + esc(tid) + '">Open it</button></div>';
      });
      if (waiting.length) {
        var one = waiting[0];
        h += '<div class="pend-notice">📥 <strong>A change is waiting on this decision.</strong> ' +
          esc(summarise(one)) +
          ' It is not applied, and this decision is locked until you let it land or talk the agent out of it.' +
          (conflicted(one) ? '<div class="c" style="margin-top:6px;color:var(--conflict-ink);font-weight:600">' +
            '⚡ You changed ' + esc(id) + " after this was written. Letting it land would overwrite that, so the backend will refuse it — discuss it or dismiss it.</div>" : "") +
          ' <div style="margin-top:7px"><button class="btn sm primary" data-act="applyone" data-uid="' + esc(one.id) + '">Let it land</button> ' +
          '<button class="btn sm" data-act="discuss" data-uid="' + esc(one.id) + '">Discuss it first</button> ' +
          '<button class="btn sm warn" data-act="dismissone" data-uid="' + esc(one.id) + '">Dismiss it</button></div></div>';
      }
      if (conflict) {
        h += '<div class="conflict-notice">The agent\'s change disagrees with your answer. Decisions downstream of ' + esc(id) +
          ' are waiting on it. <button class="btn sm" data-act="discuss" data-uid="' + esc(conflict.id) + '">Talk it through</button></div>';
      }
      if (mandated) {
        h += '<div class="mandate-notice"><span class="big">⚖</span><div><strong>This decision requires a thread.</strong> ' +
          esc(d.mandate.notice) + "</div></div>";
      }
      if (st === "awaiting-thread") {
        h += '<div class="mandate-notice"><span class="big">⏳</span><div><strong>Your answer is held, not applied.</strong> ' +
          '<button class="btn sm" data-act="openthread" data-tid="' + esc(d.mandate.threadId) + '">Open the mandated thread</button> — concluding it settles this decision. ' +
          '<button class="btn sm" data-act="abandon" data-id="' + esc(id) + '">Abandon the answer</button> puts it back to open.</div></div>';
      }
      h += '<div class="q-body">' + esc(d.body) + "</div>";
      if (st === "fogged" || st === "invalidated" || st === "blocked" || st === "stale-blocked") {
        h += '<div class="muted">' + (st === "fogged" ? "Not a real question yet. It sharpens once " + esc(d.fogUntil) + " settles."
          : st === "invalidated" ? "The agent took this out of the flow. It stays on the board — relitigate it by opening a thread."
          : wait.conflict ? "Waiting on " + esc(wait.conflict) + ". Its answer is still here and still readable; it just cannot change until that disagreement is judged."
          : "Waiting on " + esc(wait.list.join(", ")) + ".") + "</div>";
      } else {
        h += answerControls(d, !takesAnswer(id) || !!lock);
      }
      if (d.rationale) h += '<div class="rationale"><strong>Why:</strong> ' + esc(d.rationale) + "</div>";
      noticesOn(id).forEach(function (n) { h += infoNote(n); });
      threadsOf(id).forEach(function (tid) {
        if (blockingThreads(id).indexOf(tid) >= 0) return;
        var t = thread(tid);
        h += '<div class="parked-note">⑂ ' + esc(t.title || tid) + " — <em>" + t.state + "</em> " +
          '<button class="btn sm" data-act="openthread" data-tid="' + esc(tid) + '">' +
          (t.state === "open" ? "Open" : t.state === "folded" ? "View" : "Pick it back up") + "</button></div>";
      });
      h += '<div style="margin-top:9px"><button class="btn sm" data-act="newthread" data-id="' + esc(id) + '">⑂ Start a thread on ' + esc(id) + "</button></div>";
    }
    if (UI.open["hist-" + id]) {
      h += '<div class="hist"><strong style="font-size:12px">Change history — ' + esc(id) + "</strong>";
      var hist = historyOf(id);
      if (!hist.length) h += '<div class="muted">Nothing has happened to this decision yet.</div>';
      hist.forEach(function (e) {
        h += '<div><span class="s">#' + e.seq + "</span>" + esc(e.kind + " · " + e.actor + (e.why ? " — " + e.why : "")) + "</div>";
      });
      h += "</div>";
    }
    h += "</div>";
  });
  return h + "</div></div>";
}

/* ---------- slide-outs ---------- */
// Who said each thing, and for an agent which tier said it. The tier comes off
// the projected turn rather than off the channel, so a thread read back after a
// transfer still shows which turns the first-rung seat took and which the expert did
// — and a page that joined the session afterwards shows the same, because the
// projection is where it read the board from.
//
// An offer the turn made reads back as part of what was said. Every proposal a
// thread carried renders, retired ones included, because the retired ones are
// still things the agent put to the human. Only the live one carries a control:
// which offer is live is position -- the thread's most recent turn -- and a
// retired one is history the human can read and nothing they can take.
//
// The control renders on an open thread only. Parking or closing hides it while
// the offer stays live in the log, so reopening the thread shows it again.
function renderTurns(t) {
  var h = "", last = t.turns.length - 1;
  t.turns.forEach(function (turn, i) {
    h += '<div class="turn ' + esc(turn.who) + '"><div class="who">' +
      (turn.who === "human" ? "You" : turn.who === "backend" ? "Backend"
        : tierLabel(turn.tier) || "Agent") +
      (turn.timestamp ? ' <span class="did">' + esc(stamp(turn.timestamp)) + "</span>" : "") + "</div>" +
      "<p>" + esc(turn.text) + "</p>" +
      (turn.proposal ? offerBlock(t, turn.proposal, i === last && t.state === "open") : "") + "</div>";
  });
  return h;
}
// The wait, said at the foot of the turns. The header's clock is above the
// board and a human who has just sent a turn is inside the thread reading their
// own message, so the acknowledgement is put where they are looking. Its seconds
// are the lane's own -- the same clock the header and the diagnostic read,
// through the same wording -- because two formattings of one wait drift, and a
// thread disagreeing with the header is worse than a thread saying nothing.
//
// Whether it shows at all is the channel's protocol state and not the clock: a
// turn the backend has taken and no tier has picked up yet is owed with nothing
// to count, and says so in the state's own word rather than vanishing.
function waitMark(channel) {
  if (!owedOn(channel)) return "";
  var st = WIRE.status[channel];
  return '<div class="waitmark" data-channel="' + esc(channel) + '"' +
    (st ? ' data-waited="' + esc(elapsed(st.since)) + '"' : "") +
    '><span class="dots"><i></i><i></i><i></i></span><span class="mono' +
    (st ? " wclock" : "") + '">' +
    esc(st ? waitedText(st) : PROTOCOL_WORDS[CHANNELS.protocol[channel]]) + "</span></div>";
}
// What the turn proposed: the option it builds on, the answer in the human's
// own words, the one line of why -- and, on the live one, the control that arms
// it. The reason is shown beside the offer and is no part of the answer.
function offerBlock(t, offer, live) {
  var d = node(offer.decision), lab = d ? labelOf(d, offer.option) : "";
  var chosen = offer.option && d
    ? (d.options.filter(function (o) { return o.id === offer.option; })[0] || {}).text : "";
  return '<div class="offer"><div class="did">proposed answer · ' + esc(offer.decision) + "</div>" +
    (chosen ? '<div class="muted">builds on ' + esc(lab ? lab + ") " : "") + esc(chosen) + "</div>" : "") +
    "<p>" + esc(offer.text) + "</p>" +
    (offer.because ? '<div class="muted">' + esc(offer.because) + "</div>" : "") +
    (live ? armControl(t, offer) : "") + "</div>";
}
// One control, naming the decision it would arm. Where that decision is settled
// it says the answer it fills in would replace the one the human gave, and
// where the board will not take an answer on it the control is inert and names
// what is holding it -- a live control over a box nothing will accept from is
// the press that appears to do nothing.
function armControl(t, offer) {
  var d = node(offer.decision), block = armBlock(offer.decision);
  var label = block ? "Cannot take this — " + offer.decision + " " + block
    : d && d.status === "settled"
      ? "Take this answer — replaces your answer to " + offer.decision
      : "Take this answer — fills in " + offer.decision;
  return '<div style="margin-top:7px"><button class="btn sm' + (block ? "" : " primary") +
    '" data-act="arm" data-tid="' + esc(t.id) + '" data-id="' + esc(offer.decision) + '"' +
    (block ? " disabled" : "") + ">" + esc(label) + "</button></div>";
}
// A thread in three parts, and they are three parts rather than one column
// because two of them are pinned. The head is what the thread is and how to
// leave it; the body is the only thing that scrolls; the foot is how to answer.
// Everything below returns the three, and one wrapper decides where they sit —
// the pop-out window and the slide-out get the same pane.
function threadPane(head, body, foot) {
  return '<div class="threadpane"><div class="thead">' + head + "</div>" +
    '<div class="tbody">' + body + "</div>" +
    (foot ? '<div class="tfoot">' + foot + "</div>" : "") + "</div>";
}
// The seed prompts a decision carries, one control each, in the foot beside the
// box they stand in for. A decision that carries none renders none: the row is
// what the decision declared and nothing the page invents. The full text is the
// label, because what a control sends is the only thing worth knowing about it.
function seedControls(id, tid) {
  var d = id ? node(id) : null;
  if (!d || !d.talk) return "";
  var seeds = Object.keys(d.talk).filter(function (f) { return d.talk[f]; }).map(function (f) {
    return '<button class="btn sm" data-act="seed" data-field="' + esc(f) + '" data-id="' + esc(id) + '"' +
      (tid ? ' data-tid="' + esc(tid) + '"' : "") + ">💬 " + esc(d.talk[f]) + "</button>";
  });
  return seeds.length ? '<div class="thread-actions">' + seeds.join("") + "</div>" : "";
}
// Close sits beside park everywhere park is offered, because the two are the
// choice the human is making: come back to this, or be done with it. Only park
// is carried to the end of the session as a loose end.
function closeControl(tid) {
  return '<button class="btn sm" data-act="closethread" data-tid="' + esc(tid) +
    '">Close it — done with it, nothing left open</button>';
}
// The box a turn is typed into, and the one control that sends it. One reader,
// because an open thread and a closed one the human is picking back up take the
// same turn on the same channel — two copies is how they come to differ.
function sayBox(sayId, tid) {
  return '<div class="free"><textarea id="' + esc(sayId) + '" data-draft="__say" data-send="say" data-tid="' + esc(tid) +
    '" placeholder="…say something"></textarea><span class="hint">↵ send<br>⇧↵ newline</span>' +
    '<button class="btn sm" data-act="say" data-tid="' + esc(tid) + '">Send</button></div>';
}
// Which decision a thread that does not exist yet would be about. One reader,
// because the pane that renders the draft and the popped window that sends its
// first turn have to name the same decision -- and a popped document is a copy,
// so the anchor is worked out here rather than read back off the button.
function draftAnchor(tid) {
  return UI.draftFor && UI.draftFor.thread === tid ? UI.draftFor.decision : null;
}
// `chrome` is what the surrounding window pins beside the title — the slide-out
// has a close and a pop-out, the popped window has neither. It rides in the head
// rather than outside the pane so that it is pinned by the same rule as the
// title it sits on.
function threadBody(tid, forPop, chrome) {
  var t = thread(tid);
  var sayId = forPop ? "pop-say" : "ft-say";
  chrome = chrome || "";
  if (!t) {
    // Nothing exists until something is said in it. Closing this creates nothing.
    var anchor = draftAnchor(tid);
    var d = anchor ? node(anchor) : null;
    var help = tid === HELP_THREAD;
    var mapdraft = tid === MAP_THREAD;
    return threadPane(
      chrome + '<span class="pill new">new thread</span>' +
        '<h3 style="margin:10px 0 4px;font-size:16px">' +
        (help ? "How this board works" : mapdraft ? MAP_THREAD_TITLE
          : "Thread on " + esc(anchor || "the board") + (d ? " — " + esc(d.short) : "")) +
        "</h3>",
      '<div class="muted">' + (help
        ? "Ask anything about driving this board — what a control does, why something is blocked, " +
          "what happens when you answer. The agent here has the board's own reference material and " +
          "is not grilling your plan. Nothing you say here touches a decision."
        : mapdraft
        ? "Say what you want changed about the map itself — decisions that are now moot, one that is " +
          "wrong, one that is missing. The agent here works it into which decisions change and how; " +
          "handing that to the grill-master is what puts the changes in your inbox."
        : "Nothing exists yet. Close this and no thread is created — " +
          "the first thing you say is what opens it. It titles itself from what you say.") + "</div>",
      '<div class="free"><textarea id="' + esc(sayId) + '" data-draft="__say" data-send="draftsay" data-id="' + esc(anchor || "") +
        '" placeholder="…say something"></textarea><span class="hint">↵ send<br>⇧↵ newline</span>' +
        '<button class="btn sm" data-act="draftsay" data-id="' + esc(anchor || "") + '">Send</button></div>' +
        seedControls(anchor, null) +
        // The tier control belongs to a thread that has not been opened yet as
        // much as to one that has: the human decides who they are asking before
        // they ask, and a control that arrives only with the first reply arrives
        // one turn after the one turn it was wanted for. Park, close and fold are
        // not offered beside it — the backend refuses a thread gesture naming no
        // thread, and the head's ✕ is what closing a draft already means.
        '<div class="thread-actions">' + transferControl(tid) + "</div>"
    );
  }
  var ready = foldReady(tid);
  var pendingId = UI.discussing[tid] || null;
  var stillWaiting = pendingId && BOARD.pending.some(function (p) { return p.id === pendingId; });
  var head = chrome + '<span class="pill open">' + esc(t.kind || "thread") + " thread</span>" +
    '<h3 style="margin:10px 0 4px;font-size:16px">' + esc(t.title || tid) + "</h3>" +
    '<div class="muted">' +
    (t.decision ? "On " + esc(t.decision) + " · " + esc((node(t.decision) || {}).short || "") : "On the board") +
    (t.requires_action ? " · <strong>this thread is holding " + esc(t.decision) + "</strong>" : "") +
    ". Nothing here touches the decision until you conclude it.</div>";
  var body = renderTurns(t) + waitMark(tid);
  if (t.state !== "open") {
    // A closed thread keeps its box: saying something in one is how the human
    // picks it back up, and the turn itself is what opens it again.
    var closed = t.state === "closed";
    return threadPane(head,
      body + '<div class="parked-note">This thread is ' + esc(t.state) + ". It stays readable." +
        (closed ? " Say something here and it opens again." : "") + "</div>",
      closed ? sayBox(sayId, tid) : "");
  }
  var h = sayBox(sayId, tid);
  h += seedControls(t.decision, tid);

  h += '<div class="thread-actions">' + transferControl(tid);
  if (t.kind === "mandate") {
    // A mandated thread concludes, or the answer is abandoned. There is no park.
    h += '<button class="btn primary sm" data-act="fold" data-tid="' + esc(tid) + '">Conclude — settles ' + esc(t.decision) + "</button>" +
      '<button class="btn sm" data-act="abandon" data-id="' + esc(t.decision) + '">Abandon the answer — ' + esc(t.decision) + " returns to open</button>";
  } else if (stillWaiting) {
    h += '<button class="btn primary sm" data-act="applyone" data-uid="' + esc(pendingId) + '">Let it land</button>' +
      '<button class="btn sm warn" data-act="dismissone" data-uid="' + esc(pendingId) + '">Dismiss it — the change is dropped</button>';
  } else if (t.requires_action) {
    h += '<button class="btn primary sm" data-act="fold" data-tid="' + esc(tid) + '"' + (ready ? "" : " disabled") + ">Conclude it</button>" +
      '<button class="btn sm" data-act="park" data-tid="' + esc(tid) + '">No action needed — set it aside</button>' +
      closeControl(tid);
  } else {
    h += '<button class="btn sm" data-act="park" data-tid="' + esc(tid) + '">Park it — no effect, kept on the record</button>' +
      closeControl(tid) +
      // The map thread folds on the same readiness as any other: the turn it
      // hands over is the thread's last, so it arms once the agent has spoken
      // last, and the human's own request is never what the map owner acts on.
      (t.kind === "map"
        ? '<button class="btn primary sm" data-act="fold" data-tid="' + esc(tid) + '"' + (ready ? "" : " disabled") + ">Fold it — conclude and hand it to the grill-master</button>"
        : '<button class="btn primary sm" data-act="fold" data-tid="' + esc(tid) + '"' + (ready ? "" : " disabled") + ">Fold it — conclude and hand it to the agent</button>");
  }
  if (ready) {
    h += '<details class="foldimpact"><summary>what folding would do</summary><div class="body">' +
      "Hands this to the grill-master, as what the thread concluded: <strong>" +
      esc(ready.text || "") + "</strong></div></details>";
  } else if (t.kind !== "mandate" && t.kind !== "map" && !stillWaiting) {
    h += '<span class="muted">The agent has not answered yet — folding now would hand back your own words.</span>';
  }
  return threadPane(head, body, h + "</div>");
}
function renderThread(tid) {
  // Threads open on the LEFT so they never cover the decision they discuss. The
  // close and the pop-out go into the pane's own head, so they are pinned with
  // it rather than scrolling away with the first screen of turns.
  var chrome = '<button class="close" data-act="closepanel">✕</button>' +
    '<button class="popout" data-act="popout" data-tid="' + esc(tid) + '" title="Open this thread in its own window">⧉ pop out</button>' +
    (UI.popFail ? '<div class="parked-note">The browser refused a new window — the thread is still here.</div>' : "");
  return '<div class="slide left pane">' + threadBody(tid, false, chrome) + "</div>";
}
function renderNotifications() {
  var unread = unreadCount();
  var h = '<div class="slide"><button class="close" data-act="closepanel">✕</button>' +
    '<h3 style="font-size:16px">Notifications</h3>' +
    '<div class="muted" style="margin-bottom:10px">What the agent said that the board has nowhere to show. Changes are not in here: the ones that landed are on the board, ' +
    "and the ones waiting on you are in the inbox. This list starts empty on a reload: a session you come back to should not announce the morning's work as news. " +
    "What you have read is remembered.</div>" +
    '<div style="margin-bottom:12px"><button class="btn sm" data-act="markall"' + (unread ? "" : " disabled") +
    ">✓ Mark all read" + (unread ? " (" + unread + ")" : "") + "</button></div>";
  if (!NOTES.length) h += '<div class="muted">Nothing here.</div>';
  NOTES.slice().reverse().forEach(function (n) {
    var read = isRead(n.id);
    h += '<div class="inbox-item' + (read ? "" : " unread") + '"><span class="type t-' + n.type + '">' +
      n.type.replace(/-/g, " ") + "</span>" +
      '<div class="txt">' + (read ? "" : '<span class="unreadmark">●</span> ') +
      (tierLabel(tierAt(n.seq)) ? "<strong>" + esc(tierLabel(tierAt(n.seq))) + "</strong> · " : "") +
      "<strong>" + esc(n.target || "—") + "</strong> · " + esc(n.text) +
      '<div class="did" style="margin-top:3px">' + esc(stamp(n.at)) + "</div>" +
      '<div style="margin-top:6px"><button class="btn sm" data-act="notify" data-nid="' + esc(n.id) + '">Go to it</button>' +
      // A message from the agent is discussable wherever it is met. Reading it
      // in the notification list rather than on its decision is not a reason to
      // have to go and find it again to answer it.
      ' <button class="btn sm" data-act="discussnotice" data-uid="' + esc(n.id) + '">Discuss</button>' +
      (read ? "" : ' <button class="btn sm" data-act="marknote" data-nid="' + esc(n.id) + '">Mark as read</button>') +
      "</div></div></div>";
  });
  return h + "</div>";
}
// The one control that lets the whole queue land, written once. It renders
// twice — in the panel's head and at the foot of the list — and a count that
// disagreed between the two copies would be a second answer to how many changes
// are waiting.
function applyAllButton(n) {
  return '<button class="btn primary sm" data-act="applyall">Let all ' + n + " land</button>";
}
// The inbox: only what has NOT landed.
function renderInbox() {
  var ps = proposals();
  // Eight queued changes push the foot control below the fold, and a human who
  // never scrolls there applies eight rows by hand. The head copy is the one
  // that is on screen the moment the panel opens.
  var batch = ps.length > 1 ? applyAllButton(ps.length) : "";
  var h = '<div class="slide"><button class="close" data-act="closepanel">✕</button>' +
    '<div class="inbox-head"><h3 style="font-size:16px">Inbox — changes waiting on you</h3>' + batch + "</div>" +
    '<div class="muted" style="margin-bottom:12px">The backend queues a change when letting it land would overwrite or undermine something you decided. ' +
    'Each one locks the decision it targets until you let it land or talk the agent out of it.</div><div class="pending-list">';
  if (!ps.length) h += '<div class="muted">Empty. Everything the agent sent landed when it arrived.</div>';
  ps.forEach(function (p) {
    h += '<div class="pending-row"><strong>' + esc(p.target || "—") + '</strong> · <span class="did">' + esc(p.kind) + "</span><br>" +
      esc(summarise(p)) +
      (conflicted(p) ? '<div class="c">⚡ you changed ' + esc(p.target) +
        " after this was written — the backend will refuse it until one of you gives way</div>" : "") +
      '<div class="acts"><button class="btn primary sm" data-act="applyone" data-uid="' + esc(p.id) + '">Let it land</button>' +
      '<button class="btn sm" data-act="discuss" data-uid="' + esc(p.id) + '">Discuss it</button>' +
      '<button class="btn sm warn" data-act="dismissone" data-uid="' + esc(p.id) + '">Dismiss it</button>' +
      '<button class="btn sm" data-act="gotonode" data-id="' + esc(p.target) + '">Show me ' + esc(p.target) + "</button></div></div>";
  });
  h += "</div>";
  if (batch) h += '<div class="thread-actions">' + batch + "</div>";
  return h + "</div>";
}

/* ---------- bubbles ---------- */
// Every notification bubbles, because the lane only carries what the board has
// nowhere to render — there is no second class of note here to hold back.
function harvestBubbles() {
  NOTES.forEach(function (n) {
    if (isRead(n.id) || UI.bubbleSeen[n.id]) return;
    UI.bubbleSeen[n.id] = true;
    UI.bubbles.push({ id: n.id, target: n.target, text: n.text, type: n.type, at: n.at, left: 3000 });
  });
}
document.addEventListener("pointermove", function (e) { UI.ptr = { x: e.clientX, y: e.clientY }; });
function bubbleHovered() {
  var el = document.getElementById("bubbles");
  if (!el || !UI.ptr || !UI.bubbles.length) return false;
  var r = el.getBoundingClientRect();
  return UI.ptr.x >= r.left && UI.ptr.x <= r.right && UI.ptr.y >= r.top && UI.ptr.y <= r.bottom;
}
// Written only when the set changes. Rewriting it on a timer destroyed the
// element mid-click, which is why clicking a bubble did nothing.
function renderBubbles() {
  var el = document.getElementById("bubbles");
  if (!el) return;
  var sig = UI.bubbles.map(function (b) { return b.id; }).join(",");
  if (sig === UI.bubbleSig) return;
  UI.bubbleSig = sig;
  el.innerHTML = UI.bubbles.map(function (b, i) {
    return '<div class="bubble ' + (i ? "queued" : "top") + '" data-act="bubble" data-nid="' + esc(b.id) + '">' +
      '<div class="bh"><span>' + esc(b.target || "—") + " · " + esc(b.type.replace(/-/g, " ")) +
      '</span><span class="spacer"></span>' + (i ? "<span>waiting</span>" : "<span>" + esc(stamp(b.at)) + "</span>") + "</div>" +
      esc(b.text.length > 190 ? b.text.slice(0, 190) + "…" : b.text) +
      '<div style="opacity:.6;margin-top:5px;font-size:11px">click to mark read and dismiss</div>' +
      (i ? "" : '<div class="bar"><i></i></div>') + "</div>";
  }).join("");
}
// Only the top bubble's clock runs, so they pop one at a time. Elapsed real
// time, so a throttled tab cannot stall it; hovering the stack pauses it.
setInterval(function () {
  var el = document.getElementById("bubbles");
  var now = Date.now(), dt = now - (UI.bubbleTick || now);
  UI.bubbleTick = now;
  if (!UI.bubbles.length || !el) return;
  var held = bubbleHovered();
  el.classList.toggle("paused", held);
  if (held) return;
  UI.bubbles[0].left -= dt;
  if (UI.bubbles[0].left <= 0) { UI.bubbles.shift(); renderBubbles(); }
}, 150);

/* ---------- the connection indicator, and what is behind it ---------- */
// One line per state, in the human's words rather than the protocol's. The
// protocol name rides along beside it, because the name is what the diagnostic,
// the log and anyone reading this file all use.
var CONNECTION_WORDS = {
  disconnected: "no backend", connecting: "connecting", connected: "backend up", error: "backend erroring"
};
var PROTOCOL_WORDS = {
  idle: "nothing outstanding", sending: "sending", "awaiting-ack": "unacknowledged",
  "agent-owes": "waiting on the agent", receiving: "a reply is arriving"
};
// Three signals, and they are three because each one fails on its own and each
// one means something different to the human standing in front of it.
//
//   reachable — is there a backend. Nothing else is worth reading if there is
//     not, so it is ranked first and it is the transport's own answer.
//   agent — the priority signal. Whether an agent is attached at all, and
//     whether one owes a reply right now. A healthy backend with nothing
//     attached and a healthy backend with an agent thinking are the two states
//     that must never render alike: the first means nobody is coming, the
//     second means someone is on their way, and a human told the wrong one
//     either waits for nothing or gives up on something that was working.
//   outbox — how much this page has said that it cannot yet see the effect of.
//     Zero is the normal state; a number that stays up is a page talking into
//     a log it is not reading back.
//
// The amalgamation is still worst-state-wins across every channel — that is what
// the agent signal reads — and the diagnostic behind it is still per channel.
function agentSignal() {
  var turns = owed();
  if (turns.length) return { state: "owes", loud: "loud", dot: "busy", text: laneText() };
  // Attached is asked of the record rather than of a flag: a lane entry or a
  // turn an agent authored is an agent having been there. A session whose tier
  // is not configured produces neither, and says so rather than showing an idle
  // chip that a working session is indistinguishable from.
  if (!agentSeen()) return { state: "absent", loud: "bad", dot: "off", text: "no agent attached" };
  return { state: "idle", loud: "", dot: "up", text: "agent attached · idle" };
}
// Whether any agent has ever taken a turn in this session. Read off the log this
// page already holds: a status entry is the lane announcing a tier, and an entry
// an agent authored is one having answered.
function agentSeen() {
  return LOG.some(function (e) {
    return e.kind === STATUS_KIND || AGENT_ACTORS.indexOf(e.actor) >= 0;
  });
}
function renderIndicator() {
  var shown = worstChannel();
  var agent = agentSignal();
  var depth = outboxDepth();
  var reachable = connected();
  return '<button class="agentchip diagbtn' + (reachable && agent.state === "idle" && !depth ? "" : " loud") +
    '" data-act="diag" id="indicator"' +
    ' data-connection="' + esc(shown.connection) + '" data-protocol="' + esc(shown.protocol) + '"' +
    ' data-worst="' + esc(shown.channel) + '" data-agent="' + esc(agent.state) + '"' +
    ' data-outbox="' + esc(depth) + '" title="Every channel, and what each one is doing">' +
    '<span class="sig' + (reachable ? "" : " bad") + '" data-signal="reachable">' +
    '<span class="dot' + (reachable ? " up" : " bad") + '"></span>' + esc(CONNECTION_WORDS[shown.connection]) + "</span>" +
    '<span class="sig ' + agent.loud + '" data-signal="agent">' +
    '<span class="dot ' + agent.dot + '"></span>agent: <span id="lanetimer">' + esc(agent.text) + "</span></span>" +
    '<span class="sig' + (depth ? " loud" : "") + '" data-signal="outbox">outbox ' +
    (depth ? depth + " unconsumed" : "clear") + "</span>" +
    ' <span class="did">' + (UI.diag ? "▴" : "▾") + "</span></button>";
}
// The expansion: every channel with both of its layers, named as the protocol
// names them. The amalgamated light says something is happening; this says on
// which channel and in which of the two layers.
function renderDiagnostic() {
  if (!UI.diag) return "";
  var rows = channelViews().map(function (view) {
    // Each waiting channel carries its own clock, because the amalgamated one
    // shows the longest wait and the human is often asking about a different
    // one. The clock is the lane's, not this row's.
    var waiting = WIRE.status[view.channel];
    return '<div class="diagrow" data-channel="' + esc(view.channel) + '"' +
      (waiting ? ' data-waited="' + esc(elapsed(waiting.since)) + '"' : "") + ">" +
      '<span class="mono chan">' + esc(view.channel === MAP ? "map" : view.channel) + "</span>" +
      '<span class="lyr">connection <b class="mono">' + esc(view.connection) + "</b></span>" +
      '<span class="lyr">protocol <b class="mono' + (waiting ? " owes" : "") + '">' + esc(view.protocol) + "</b></span>" +
      (waiting ? '<span class="lyr">waiting <b class="mono owes wclock">' + esc(waitedText(waiting)) +
        "</b></span>" : "") + "</div>";
  }).join("");
  return '<div class="diag" id="diagnostic"><div class="diaghead">Channels — one for the map, one per thread. ' +
    "The connection is the transport's and is the same for all of them; the protocol state is each channel's own.</div>" +
    rows + '<div class="diagfoot mono">epoch ' + esc(String(WIRE.epoch).slice(0, 10)) +
    " · seq " + WIRE.cursor + " · " + WIRE.sent + " sent, " + WIRE.got + " received" +
    " · outbox " + outboxDepth() +
    (WIRE.rejected ? " · " + WIRE.rejected + " refused" : "") + "</div></div>";
}
// Every per-channel clock on the page, rewritten in place on the lane's beat --
// the open diagnostic's rows and the thread's own waiting marker. The board is
// only re-rendered when the log moves, and a channel waiting on an agent is by
// definition a log that is not moving, so anything drawn once shows the wait it
// started at for the whole of the wait it exists to time. In place rather than
// by re-rendering, for the same reason the lane's own clock is: a render once a
// second destroys whatever control the human is holding.
//
// One loop over both, because they carry the same wait about the same channel:
// a second loop is a second place for the two to come apart.
function tickWaitClocks() {
  var rows = document.querySelectorAll("#diagnostic .diagrow, .waitmark");
  for (var i = 0; i < rows.length; i++) {
    var waiting = WIRE.status[rows[i].getAttribute("data-channel")];
    var clock = rows[i].querySelector(".wclock");
    if (!waiting || !clock) continue;
    rows[i].setAttribute("data-waited", elapsed(waiting.since));
    clock.textContent = waitedText(waiting);
  }
}

/* ---------- the window that is not this session's ----------
   All this window gets. Not a banner over the board: a board with a warning on
   it is still a board, and the human answers decisions on it.

   The connection indicator is not here either, and that is the decision rather
   than an omission. A refused claim is a session-control state and says nothing
   about the wire — the backend answered, immediately and clearly, which is a
   healthy transport by every measure the indicator has. Reporting it there would
   put "nothing is listening" next to a reply that just arrived; and there are no
   channels to report on, because this window holds no session to have channels
   in. So the two never meet: the indicator keeps describing the wire, and this
   describes who the session belongs to. */
function renderNotice() {
  var superseded = CLAIM.state === CLAIM_SUPERSEDED;
  document.getElementById("shell").innerHTML =
    '<div class="intro"><h1>Grilling session</h1></div>' +
    '<div class="banner refusal" id="claimnotice" data-claim="' + esc(CLAIM.state) + '">' +
    (superseded
      ? "<strong>Another window took this session over.</strong> This is no longer the window the backend " +
        "answers, so the board is not shown here. Nothing you did is lost — every answer already accepted is " +
        "in the session log, and the window that took over is reading the same board."
      : "<strong>Another window already has this session.</strong> The backend serves one main window per " +
        "session, so two windows can never disagree about what you answered. The board is not shown here. " +
        "If that other window is gone, take the session over — it will stop working if it is not.") +
    ' <button class="btn sm" data-act="takeover">' +
    (superseded ? "Take it back" : "Take this session over") + "</button></div>";
  document.getElementById("overlay").innerHTML = "";
  document.getElementById("bubbles").innerHTML = "";
}

/* ---------- shell ---------- */
function renderShell() {
  var ps = proposals(), unread = unreadCount();
  // The agent's state is inside the indicator rather than beside it: a separate
  // chip saying `idle` next to a light saying a thread was waiting is two
  // answers to one question, and the human reads whichever is nearer.
  var top = '<div class="topbar">' + renderIndicator() +
    '<button class="pendbtn' + (ps.length ? "" : " none") + '" data-act="inbox">📥 ' +
    (ps.length ? ps.length + " change" + (ps.length > 1 ? "s" : "") + " waiting on you" : "inbox empty") + "</button>" +
    '<button class="inboxbtn" data-act="notifications" data-unread="' + esc(unread) + '">🔔 Notifications <span class="count">' + esc(unread) + "</span> unread</button>" +
    (unread ? '<button class="btn sm" data-act="markall" title="Clear every unread marker. Nothing is sent.">✓ Mark all read</button>' : "") +
    transferControl(MAP) +
    // Beside the doctor because both are the human addressing the map rather
    // than a decision on it: the doctor asks the agent to go and look, and this
    // one is where they say what they want changed and why.
    '<button class="btn sm" data-act="mapthread" title="Ask the grill-master for a change to it">🗺 Ask for a map change</button>' +
    '<button class="btn sm" data-act="doctor" title="Send the agent over the whole board and the queue">🩺 Map doctor</button>' +
    '<button class="btn sm' + (UI.pulse ? " pulsing" : "") + '" data-act="endsession">End the session</button>' +
    // Pushed to the right edge of the row rather than sitting at the end of the
    // run of controls: help is not one more thing to do with the board, and a
    // human looking for it looks at the corner.
    (helpOffered() ? '<button class="btn sm helpbtn" data-act="help" title="Ask how this board works">? Help</button>' : "") +
    "</div>";

  var banners = "";
  if (sessionOver()) {
    // Not the no-backend banner: the backend that served this session was asked
    // to stop by the ending itself, so telling the human to restart it would be
    // an invitation to reopen something they finished.
    banners += '<div class="banner">🏁 <strong>This session has ended.</strong> The terminal entry is in the log and ' +
      "the result was written beside it. What is below is the board as it stands, to read — nothing further is recorded here. " +
      "<strong>You can close this tab.</strong></div>";
  } else if (CHANNELS.transport === "disconnected" || CHANNELS.transport === "error") {
    banners += '<div class="banner">⚠ <strong>No backend.</strong> Nothing is answering — the session log and every answer already accepted are safe on disk, ' +
      "but nothing you do now is recorded and no reply will arrive. Restart it and this page will re-read the board by itself.</div>";
  }
  var rj = WIRE.lastRejection;
  if (rj) {
    // A refused action must be visible where the human is looking, and it must
    // say what a refusal means: nothing was written and nothing will answer it.
    banners += '<div class="banner refusal">⚠ <strong>The backend refused that.</strong> ' +
      esc(rj.reason) + (rj.detail ? " — " + esc(rj.detail) : "") +
      " Your message was <strong>not recorded</strong>, and <strong>no agent will answer it</strong>. " +
      '<button class="btn sm" data-act="dismiss-rejection">Dismiss</button></div>';
  }
  if (HELDBACK) {
    // This page's own refusal, said as plainly as the backend's and never
    // attributed to it: nothing was sent, so nothing refused it but this.
    banners += '<div class="banner refusal">⚠ <strong>Not sent.</strong> ' + esc(HELDBACK) +
      ' <button class="btn sm" data-act="dismiss-rejection">Dismiss</button></div>';
  }

  // The header names the session and nothing else. What the backend owns and
  // how the board is driven are the help thread's to answer when asked, not a
  // paragraph every human reads past on their way to the first decision.
  document.getElementById("shell").innerHTML =
    '<div class="intro"><h1>' + esc(sessionTitle()) + "</h1></div>" +
    banners + top + renderDiagnostic() +
    '<div class="surface">' + renderMap() + renderColumn() + "</div>";

  document.getElementById("overlay").innerHTML =
    // One scrim at a time: the doctor's holds the board read-only, and an offer
    // to finish stacked on top of it would be offering a gesture the page is
    // refusing anyway.
    (WIRE.doctor
      ? '<div class="scrim"><div class="box"><h3>🩺 The map doctor is working</h3>' +
        "<p>The agent is going over the whole board and everything in the queue. The board is read-only until it answers.</p></div></div>"
      : UI.done ? completionOffer() : "") +
    (!UI.panel ? "" :
      UI.panel.kind === "thread" ? renderThread(UI.panel.id) :
      UI.panel.kind === "notifications" ? renderNotifications() : renderInbox());
}

/* ---------- render, preserving what the human is doing ---------- */
// Every caret this page takes goes through here, and none of them may move the
// page. A bare focus() reveals its element by scrolling each scrollable
// ancestor and then the document, and the caret is taken on every re-render —
// so a poll tick, an arriving message and a click on a control at the top of
// the page each drag the decision log to whatever box the caret lands in, and
// the window with it. Where the board follows the human is centerOn's decision,
// made in one place.
function takeCaret(el, caret) {
  if (!el) return;
  el.focus({ preventScroll: true });
  if (caret !== undefined) { try { el.setSelectionRange(caret, caret); } catch (e) {} }
}
// A thread's turns scroll inside the panel rather than with the page, and that
// element is replaced on every re-render — so a thread follows the rule a chat
// log follows, or it follows none. Whoever is at the bottom is reading the
// conversation as it happens and stays at the bottom, so an arriving turn is on
// screen without a gesture; whoever has scrolled up is reading what is up there
// and holds their place, because an arrival is not a reason to take it away
// from them. A panel that has just opened counts as at the bottom: a thread
// opens at its newest turn.
var THREAD_STICK = 40;
function threadScroller() { return document.querySelector("#overlay .tbody"); }
function atThreadBottom(el) {
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight <= THREAD_STICK;
}
function render() {
  if (!document.getElementById("shell")) return;
  // The one gate on drawing the board, so there is no second path that can draw
  // it for a window the backend is not answering.
  if (!boardShown()) { renderNotice(); return; }
  var map = document.getElementById("mapscroll"), col = document.getElementById("column");
  var tb = threadScroller();
  var keep = { mx: map ? map.scrollLeft : 0, my: map ? map.scrollTop : 0, cy: col ? col.scrollTop : 0,
               ty: tb ? tb.scrollTop : 0, tbottom: atThreadBottom(tb) };
  var act = document.activeElement;
  var focusId = act && act.tagName === "TEXTAREA" ? act.id : null;
  var caret = focusId ? act.selectionStart : 0;
  // The caret is on a control rather than in a box. The render replaces every
  // control on the board, so an option the human tabbed to is destroyed under
  // them and the caret falls to the body -- which the default below reads as
  // nobody holding anything, and hands to the free-text box of whatever
  // decision is focused. Held by what names the control rather than by the
  // element, since the element this finds is not the one that comes back.
  var focusOpt = focusId ? null : optionOf(act);

  noteCompletion();
  harvestBubbles();
  renderShell();
  renderBubbles();
  sealSurface();

  document.querySelectorAll("textarea[data-draft]").forEach(function (ta) {
    var d = UI.drafts[ta.dataset.draft];
    if (d) ta.value = d;
  });
  var map2 = document.getElementById("mapscroll"), col2 = document.getElementById("column");
  if (map2) { map2.scrollLeft = keep.mx; map2.scrollTop = keep.my; }
  // Hold your place across a re-render. Always — the fresh element starts at 0,
  // and centerOn measures "is it already in view?" against where the panel is.
  if (col2) col2.scrollTop = keep.cy;

  if (UI.centerNext && UI.focus) { centerOn(UI.focus); UI.centerNext = false; }
  UI.justSettled = null;

  var panelKey = UI.panel ? UI.panel.kind + ":" + (UI.panel.id || "") : null;
  var panelJustOpened = panelKey !== UI.lastPanelKey && UI.panel && UI.panel.kind === "thread";
  // A place is only held for the panel it was measured in: switching threads
  // starts the new one at its newest turn like any other opening.
  var tb2 = threadScroller();
  if (tb2) {
    tb2.scrollTop = (panelKey === UI.lastPanelKey && !keep.tbottom) ? keep.ty : tb2.scrollHeight;
  }
  UI.lastPanelKey = panelKey;

  // A thread claims the caret the moment it opens — but only then, so a later
  // re-render never yanks it out of whatever is being typed.
  if (panelJustOpened && document.getElementById("ft-say")) {
    takeCaret(document.getElementById("ft-say"));
  } else if (focusId) {
    takeCaret(document.getElementById(focusId), caret);
  } else if (focusOpt) {
    takeCaret(optionControl(focusOpt));
  } else if (UI.panel && UI.panel.kind === "thread") {
    takeCaret(document.getElementById("ft-say"));
  } else if (UI.focus !== UI.lastFocus || document.activeElement === document.body) {
    // The focused decision's free-text box holds focus by default. Only ever
    // taken when nothing else holds it, so typing is never interrupted.
    var box = document.getElementById("ft-" + UI.focus);
    if (box && !UI.panel && !box.disabled) takeCaret(box);
  }
  UI.lastFocus = UI.focus;
  // Last, because a render replaces the elements the mark is painted on -- and
  // after the caret has been placed, since placing it is one of the things that
  // decides which option is in hand.
  paintPreMarks();
}
// The map auto-centres on whatever the column is focused on, and vice versa.
function centerOn(id) {
  var map = document.getElementById("mapscroll"), p = POS[id];
  if (map && p) {
    map.scrollLeft = Math.max(0, p.x - map.clientWidth / 2 + 58);
    map.scrollTop = Math.max(0, p.y - map.clientHeight / 2 + 26);
  }
  var col = document.getElementById("column"), item = document.getElementById("col-" + id);
  if (!col || !item) return;
  var top = item.offsetTop, bottom = top + item.offsetHeight;
  var viewTop = col.scrollTop, viewBottom = viewTop + col.clientHeight, pad = 10;
  // Already fully in view: no scroll at all.
  if (top >= viewTop && bottom <= viewBottom) return;
  // Otherwise land it FULLY in view — never clipped above the top edge.
  var target = (bottom - top > col.clientHeight || top < viewTop)
    ? top - pad
    : bottom - col.clientHeight + pad;
  // Set directly rather than animating: every re-render replaces this element,
  // so an in-flight smooth scroll is destroyed mid-way and lands wherever it
  // got to. The compaction cue carries the motion instead.
  col.scrollTop = Math.max(0, Math.min(target, col.scrollHeight - col.clientHeight));
}

/* ---------- the pop-out window ---------- */
// Which thread a popped window is on, and which decision the draft it opened on
// stands against, are the window's own: handed to it when it opens, kept there,
// never looked up here. Both used to be resolved out of this window's state at
// the moment of the click -- the anchor out of the single draft slot, which the
// main board overwrites the next time it opens a draft, and the created thread
// out of a map keyed by the draft's name, which every window on that name
// shares. One gesture on the board behind either back, and a popped Send landed
// on another decision's thread or on no decision at all.
window.threadHTML = function (tid) { return threadBody(tid, true); };
// Returns the thread the act opened, when it opened one, so the window that
// asked can follow it: the draft it was showing is that thread now, and nothing
// else can tell it so.
window.popAct = function (tid, anchor, act, text, field) {
  // The ending is refused here as well as at the main window's own handler:
  // this bridge is a second door into the same acts, and a gesture the page
  // takes and drops is a gesture the human watched themselves make.
  if (sessionOver() && WRITE_ACTS.indexOf(act) >= 0) return null;
  if (act === "transfer") toggleTransfer(tid);
  else if (act === "say") sayInThread(tid, text);
  // The first turn of a thread that does not exist yet, which is the same act
  // the pane's own Send is: it routes to the one function that opens a thread,
  // on the anchor this window came with. A copy of the draft pane drawn before
  // that turn went out sends the same act again, and that is a turn in the
  // thread it opened rather than a second thread.
  else if (act === "draftsay") return thread(tid) ? sayInThread(tid, text) : startThread(anchor, text, tid);
  // The seed's decision is read from the thread this window is showing, not
  // from the button: the popped document is a copy of the pane, and the only
  // thing it can be trusted to name is which seed was pressed. On a draft there
  // is no thread to read it off, and the anchor this window came with is the
  // decision.
  else if (act === "seed") return saySeed(tid, (thread(tid) || {}).decision || anchor, field);
  else if (act === "fold") foldThread(tid);
  else if (act === "park") parkThread(tid);
  else if (act === "closethread") closeThread(tid);
  else if (act === "abandon") abandonAnswer((thread(tid) || {}).decision);
  // The anchor is read off the thread this window is showing, like the seed's
  // decision: the popped document is a copy of the pane, and the arming lands
  // in the main window where the decision the human answers is.
  else if (act === "arm") armAnswer(tid, (thread(tid) || {}).decision);
  // Asked of the thread this window is showing rather than of the last
  // discussion the main window opened: two discussions are two threads, and a
  // pop-out acting on whichever was opened last resolves the wrong change.
  else if (act === "applyone" && UI.discussing[tid]) applyPending([UI.discussing[tid]]);
  else if (act === "dismissone" && UI.discussing[tid]) dismissPending([UI.discussing[tid]]);
};
function popOut(tid) {
  var w = null;
  try { w = window.open("", "grill_" + tid.replace(/[^A-Za-z0-9]/g, "_"), "width=560,height=840"); } catch (e) { w = null; }
  if (!w) { UI.popFail = true; render(); return; }
  UI.popFail = false;
  var css = document.querySelector("style").outerHTML;
  // draw() only touches the DOM when the HTML actually changed. Repainting on
  // every tick replaced the button between mousedown and mouseup, so a real
  // click never became a click event.
  // The id is escaped for the script context it is written into as well: a
  // closing script tag inside it would end the boot script where it sits. The
  // anchor rides in beside it, an authored id on the same terms -- and this is
  // the moment it is read, so what the window carries is the draft it was
  // opened on rather than whichever draft the board is standing on later.
  var boot = "(function(){var tid=" + JSON.stringify(tid).replace(/</g, "\\u003c") +
    ";var anchor=" + JSON.stringify(draftAnchor(tid) || null).replace(/</g, "\\u003c") + ";var last=null;" +
    "function draw(){var html;" +
    "try{html=window.opener.threadHTML(tid);}catch(e){document.getElementById('t').innerHTML='<p>The main window is gone. Close this one.</p>';return;}" +
    "if(html===last)return;last=html;" +
    "var ta=document.getElementById('pop-say');var v=ta?ta.value:'';var had=ta&&document.activeElement===ta;" +
    // The popped pane's turns scroll in the same box as the slide-out's and
    // follow the same rule, because it is the same pane in another window.
    "var tb=document.querySelector('.tbody');var ty=tb?tb.scrollTop:0;" +
    "var bot=!tb||tb.scrollHeight-tb.scrollTop-tb.clientHeight<=40;" +
    "document.getElementById('t').innerHTML=html;" +
    "var tb2=document.querySelector('.tbody');if(tb2)tb2.scrollTop=bot?tb2.scrollHeight:ty;" +
    "var t2=document.getElementById('pop-say');if(t2){t2.value=v;if(had)t2.focus({preventScroll:true});}}" +
    // The ending is the opener's to declare and this window's to wear. It is
    // applied on the tick rather than inside draw(), because draw() does
    // nothing at all when the pane's html has not changed -- and a session
    // ending changes the log, not necessarily the thread on screen.
    "function seal(){try{window.opener.sealSurface(document);}catch(x){}}" +
    "document.addEventListener('click',function(e){var el=e.target.closest('[data-act]');if(!el)return;" +
    "var ta=document.getElementById('pop-say');" +
    // The thread this window is on is this window's to keep: an act that opens
    // one hands it back, and from then on this window is on that thread.
    "var made=null;try{made=window.opener.popAct(tid,anchor,el.dataset.act,ta?ta.value:'',el.dataset.field);}catch(x){}if(made)tid=made;" +
    "if(ta&&(el.dataset.act==='say'||el.dataset.act==='draftsay'))ta.value='';setTimeout(draw,40);});" +
    // The chord is the opener's to decide, keystroke by keystroke, so this window
    // cannot drift onto a chord of its own. Sending is still a press of this
    // window's own send control, because that is what carries the thread it is on.
    "document.addEventListener('keydown',function(e){var go=false;try{go=window.opener.chordSend(e);}catch(x){}" +
    "if(go){var b=document.querySelector('[data-act=\"say\"],[data-act=\"draftsay\"]');if(b)b.click();}});" +
    "setInterval(function(){draw();seal();},600);draw();seal();})();";
  w.document.open();
  w.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Thread — ' + esc(tid) + "</title>" + css +
    // The popped window is the pane and nothing else, full height, so its
    // pinned head and foot are pinned to the window rather than to a box that
    // grows with the thread.
    "<style>html,body{height:100%;margin:0;background:#fff}#t{height:100%}</style></head><body><div id=\"t\"></div><scr" + "ipt>" + boot + "</scr" + "ipt></body></html>");
  w.document.close();
  UI.popped[tid] = true;
  UI.panel = null;
  render();
}

/* ---------- the ended surface ---------- */
// Every act that writes to the session. All of this page's writes funnel through
// `send`, which refuses once the session is over; this is the surface saying the
// same thing, so an ended board offers no control whose click would be swallowed.
var WRITE_ACTS = ["pick", "free", "say", "seed", "draftsay", "newthread", "discuss", "discussnotice",
  "fold", "park", "closethread", "abandon", "applyone", "applyall", "dismissone", "transfer",
  "doctor", "endsession"];
// Reading stays: the board, the map, the history, the inbox, the notifications
// and the read markers are all this window's own and go nowhere. What goes is
// the ability to say anything more into a log that has been closed.
// `doc` is which window is being sealed. A popped window is part of this
// session and takes the same ending, and it is sealed by the same reader rather
// than by a copy of this rule living over there: it draws its pane from here,
// so every redraw would otherwise hand back live controls.
function sealSurface(doc) {
  if (!sessionOver()) return;
  doc = doc || document;
  doc.querySelectorAll("[data-act]").forEach(function (el) {
    if (WRITE_ACTS.indexOf(el.dataset.act) >= 0) el.disabled = true;
  });
  doc.querySelectorAll("textarea").forEach(function (ta) { ta.disabled = true; });
}

/* ---------- events ---------- */
document.addEventListener("input", function (e) {
  if (!e.target.dataset || !e.target.dataset.draft) return;
  var id = e.target.dataset.draft;
  UI.drafts[id] = e.target.value;
  // Provenance goes with the draft it filled: a box emptied by hand has no
  // proposal left in it, so the next answer is the human's alone.
  if (!e.target.value.trim() && UI.armed[id]) { delete UI.armed[id]; render(); }
});
function sendFrom(ta) {
  if (!ta || !ta.value.trim()) return;
  var kind = ta.dataset.send;
  if (kind === "free") {
    answerDecision(ta.dataset.id, { free: true, text: ta.value.trim() });
    UI.drafts[ta.dataset.id] = "";
  } else if (kind === "say") {
    sayInThread(ta.dataset.tid, ta.value.trim());
    UI.drafts.__say = "";
  } else if (kind === "draftsay") {
    startThread(ta.dataset.id, ta.value.trim(), UI.draftFor && UI.draftFor.thread);
    UI.drafts.__say = "";
  }
  render();
}
// Enter sends, in threads and decision free-text alike. Shift+Enter is a newline,
// and so is a backslash typed right before Enter -- the backslash is eaten, the way
// the terminal beside this board does it. Cmd/Ctrl+Enter still sends. One reader,
// because the popped window asks this one rather than carrying its own copy: two
// copies of a chord is how one window comes to answer a key the other does not.
// Answers true when the key is a send.
function chordSend(e) {
  var t = e.target;
  if (!t || t.tagName !== "TEXTAREA" || !t.dataset.send || e.key !== "Enter") return false;
  // Enter mid-composition commits the IME's candidate. Sending there would post a
  // half-typed word and take the box away from someone still spelling it.
  if (e.isComposing || e.keyCode === 229) return false;
  if (e.metaKey || e.ctrlKey) { e.preventDefault(); return true; }
  if (e.shiftKey || e.altKey) return false;
  var at = t.selectionStart;
  if (at === t.selectionEnd && at > 0 && t.value.charAt(at - 1) === "\\") {
    e.preventDefault();
    t.value = t.value.slice(0, at - 1) + "\n" + t.value.slice(at);
    t.selectionStart = t.selectionEnd = at;
    // A value the human did not type still has to reach the draft store, through the
    // same input the keystrokes go through -- the next render restores the draft, and
    // an unheard change is a newline the board rubs out from under them.
    t.dispatchEvent(new Event("input", { bubbles: true }));
    return false;
  }
  e.preventDefault();
  return true;
}
document.addEventListener("keydown", function (e) {
  var t = e.target;
  if (chordSend(e)) { sendFrom(t); return; }
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  if (e.key === "Escape") { UI.panel = null; render(); }
});

document.addEventListener("click", function (e) {
  var el = e.target.closest("[data-act]");
  // The inbox and notification panels close when you click outside them.
  if (UI.panel && UI.panel.kind !== "thread" && !e.target.closest(".slide") &&
      !(el && ["inbox", "notifications", "discuss", "discussnotice", "gotonode"].indexOf(el.dataset.act) >= 0)) {
    UI.panel = null; render();
  }
  // Hover overlays always hide on click, and stay hidden for the zone that was
  // clicked until the pointer has left it and come back. Hiding alone was not
  // enough: `mouseover` fires again on the next movement inside the same node,
  // so the card the human just dismissed reappeared under their cursor without
  // them ever leaving the thing they had dismissed it on.
  hideHover(zoneOf(e.target));
  if (!el) return;
  var a = el.dataset.act, id = el.dataset.id, tid = el.dataset.tid, uid = el.dataset.uid;
  // A gesture arriving after the ending -- from a keyboard, a pop-out, or a
  // control drawn before the last render -- is turned away here as well as at
  // the surface. Acting on it would be the page swallowing something the human
  // watched themselves do.
  if (sessionOver() && WRITE_ACTS.indexOf(a) >= 0) return;
  switch (a) {
    // The human's explicit gesture, and the only thing that displaces a live
    // claim. Never inferred from silence: a window that is merely slow is
    // indistinguishable from one that is gone, and only the human can tell.
    case "takeover": claim(true); break;
    case "nextopen": goNextOpen(); break;
    case "mapnode": focusOn(id); render(); break;
    case "focusnode": focusOn(id); UI.panel = null; render(); break;
    // "Show me" is a navigation intent — it lands the decision open so there is
    // something to look at. Not a reopen: the collapse control still collapses it.
    case "gotonode": focusOn(id); UI.open[id] = true; UI.panel = null; render(); break;
    case "focus":
      if (e.target.tagName === "TEXTAREA" || e.target.closest("button")) return;
      focusOn(id); render();
      break;
    case "toggle":
      UI.open[id] = !isExpanded(id);
      UI.autoshut[id] = false;
      focusOn(id);
      render();
      break;
    // Whatever is in the decision's own box at the moment an option is picked is
    // the note on that option. It is one box on purpose: the human is already
    // typing there, and a second one would be an empty field they had to be told
    // about.
    case "pick": answerDecision(id, { option: el.dataset.opt, note: (UI.drafts[id] || "").trim() }); break;
    case "free": sendFrom(document.getElementById("ft-" + id)); break;
    case "arm": armAnswer(tid, id); break;
    case "history": UI.open["hist-" + id] = !UI.open["hist-" + id]; render(); break;
    case "threads": {
      var ts = threadsOf(id);
      if (ts.length) { UI.panel = { kind: "thread", id: ts[ts.length - 1] }; }
      else { UI.draftFor = { thread: "draft:" + id, decision: id }; UI.panel = { kind: "thread", id: "draft:" + id }; }
      render();
      break;
    }
    case "newthread":
      UI.draftFor = { thread: "draft:" + id, decision: id };
      UI.panel = { kind: "thread", id: "draft:" + id };
      render();
      break;
    case "help": openSessionThread(HELP_THREAD); break;
    case "mapthread": openSessionThread(MAP_THREAD); break;
    case "draftsay": sendFrom(document.getElementById("ft-say")); break;
    case "openthread": UI.panel = { kind: "thread", id: tid }; render(); break;
    case "say": sendFrom(document.getElementById("ft-say")); break;
    case "seed": saySeed(tid, id, el.dataset.field); break;
    case "park": parkThread(tid); break;
    case "closethread": closeThread(tid); break;
    case "fold": foldThread(tid); break;
    case "abandon": abandonAnswer(id); break;
    case "popout": popOut(tid); break;
    case "applyone": applyPending([uid]); break;
    case "applyall": applyPending(proposals().map(function (p) { return p.id; })); break;
    case "dismissone": dismissPending([uid]); break;
    case "discuss": discussPending(uid); break;
    case "discussnotice": discussNotice(uid); break;
    case "transfer": toggleTransfer(el.dataset.channel); break;
    case "diag": UI.diag = !UI.diag; render(); break;
    case "inbox": UI.panel = { kind: "inbox" }; render(); break;
    case "notifications": UI.panel = { kind: "notifications" }; render(); break;
    case "doctor": callDoctor(); break;
    case "endsession": endSession(); break;
    case "closepanel": UI.panel = null; render(); break;
    case "marknote": markRead(el.dataset.nid); render(); break;
    case "markall": markAllRead(); break;
    case "bubble":
      UI.bubbles = UI.bubbles.filter(function (b) { return b.id !== el.dataset.nid; });
      UI.bubbleSig = null;
      markRead(el.dataset.nid);
      render();
      break;
    case "notify": {
      var n = NOTES.filter(function (x) { return x.id === el.dataset.nid; })[0];
      if (!n) return;
      markRead(n.id);
      if (n.target) { focusOn(n.target); UI.open[n.target] = true; }
      UI.panel = null; render();
      break;
    }
    case "dismiss-rejection": WIRE.lastRejection = null; HELDBACK = null; render(); break;
    // Nothing is sent and nothing is decided: the offer comes down and the top
    // row's control carries it from here. Not in the write acts for that reason
    // -- an ended board never shows this overlay to dismiss.
    case "dismiss-completion": UI.done = false; UI.pulse = true; render(); break;
  }
});
// An agent's message is discussed as an ordinary thread, seeded from it —
// wherever the human happened to be reading it. The queue and the notification
// list name the same message by the same id, so one lookup covers both: the
// queue holds it while it is still on the board, and the notification holds it
// once the board has moved on.
function discussNotice(uid) {
  var item = BOARD.pending.filter(function (p) { return p.id === uid; })[0];
  var said = item ? summarise(item)
    : (NOTES.filter(function (n) { return n.id === uid; })[0] || {}).text;
  if (!said) return;
  var target = item ? item.target
    : (NOTES.filter(function (n) { return n.id === uid; })[0] || {}).target;
  var tid = "t-notice-" + KEYS + "-" + (target || "board");
  send(ev("thread-created", tid, {
    turns: [{ who: "human", text: "About what you said: “" + said + "”" }],
    decision: target, kind: "notice", title: titleFrom(said, target || "the board"),
    requires_action: false
  }));
  UI.panel = { kind: "thread", id: tid };
  render();
}

/* hover overlays: map nodes, their icons, and options */
var HOVER = null;
// The zone a click dismissed an overlay on. Held until the pointer leaves it, so
// that returning the overlay takes a fresh entry rather than the next twitch.
var MUTED = null;
// The three kinds of thing that own an overlay, resolved to the one element the
// overlay belongs to. One reader, so what the click mutes and what the hover
// checks are the same zone rather than two selectors that agree most of the time.
function zoneOf(target) {
  return target.closest("[data-why]") || target.closest("[data-p]") || target.closest(".mnode");
}
// What a zone is, rather than which element it currently is. Almost every click
// re-renders, which replaces the element under a cursor that has not moved —
// so an element held across that click is a detached node, matches nothing, and
// hands the overlay back on the first twitch. The identity has to be the thing
// on the board, and the owning node is in it because two badges may carry the
// same words on different decisions.
function zoneKey(el) {
  if (!el) return null;
  var owner = el.closest(".mnode");
  return (owner ? owner.dataset.id : "") + "|" +
    (el.dataset.why || el.dataset.otext || el.dataset.id || "");
}
function hideHover(zone) {
  if (HOVER) HOVER.style.display = "none";
  MUTED = zoneKey(zone);
}
function showHover(html, rect) {
  if (!HOVER) { HOVER = document.createElement("div"); HOVER.className = "hovercard"; document.body.appendChild(HOVER); }
  HOVER.innerHTML = html;
  HOVER.style.display = "block";
  // Measured, not guessed. The card is as tall as the words in it, and the
  // trade-off of the last option of a long decision is raised from the very
  // bottom of the pane -- where a guessed height puts the card off the screen
  // and the reason for the answer is unreadable exactly where it is longest.
  // The card is fixed to the viewport rather than to the pane, so what has to
  // be avoided is the window's edges and never the pane's overflow.
  var h = HOVER.offsetHeight, w = HOVER.offsetWidth;
  var top = rect.bottom + 8;
  if (top + h > window.innerHeight - 6) top = rect.top - h - 8;
  HOVER.style.top = Math.max(6, Math.min(top, window.innerHeight - h - 6)) + "px";
  HOVER.style.left = Math.max(6, Math.min(rect.left, window.innerWidth - w - 6)) + "px";
}
// One builder, so the overlay a pointer raises and the one a keyboard raises
// are the same overlay rather than two that drift apart.
function pcrCard(o) {
  return '<div class="hid">this option</div><div><strong>' + esc(o.dataset.otext) + "</strong></div>" +
    '<div class="pcr"><b>buys you</b>' + esc(o.dataset.p) + "</div>" +
    '<div class="pcr"><b>costs you</b>' + esc(o.dataset.c) + "</div>" +
    '<div class="pcr"><b>forces later</b>' + esc(o.dataset.r) + "</div>";
}
// The icon takes focus, so the trade-off is readable without a pointer at all.
// Focus raises what hover raises and leaving takes it away -- and leaving never
// mutes, because a zone muted by the focus moving off it would never come back.
document.addEventListener("focusin", function (e) {
  inHand("keyedOpt", optionOf(e.target));
  var o = e.target.closest("[data-p]");
  if (o && o.dataset.p && zoneKey(o) !== MUTED) showHover(pcrCard(o), o.getBoundingClientRect());
});
document.addEventListener("focusout", function (e) {
  // `relatedTarget` is where the caret went, so this is the same reading in both
  // directions: whatever now holds it is what is in hand, and nothing is.
  inHand("keyedOpt", optionOf(e.relatedTarget));
  if (e.target.closest("[data-p]") && HOVER) HOVER.style.display = "none";
});
document.addEventListener("mouseover", function (e) {
  inHand("overOpt", optionOf(e.target));
  // Still inside the zone whose overlay was clicked away: say nothing.
  if (MUTED && zoneKey(zoneOf(e.target)) === MUTED) return;
  var b = e.target.closest("[data-why]");
  if (b) { showHover('<div class="hid">what this icon means</div><div>' + esc(b.dataset.why) + "</div>", b.getBoundingClientRect()); return; }
  var o = e.target.closest("[data-p]");
  if (o && o.dataset.p) { showHover(pcrCard(o), o.getBoundingClientRect()); return; }
  var n = e.target.closest(".mnode");
  if (!n) return;
  var d = node(n.dataset.id);
  if (!d) return;
  var st = statusOf(d.id), att = [];
  if (unreadNotices(d.id).length) att.push("✉ a message from the agent");
  if (proposalsOn(d.id).length) att.push("📥 a change waiting in the inbox — this decision is locked");
  if (blockingThreads(d.id).length) att.push("⚠ a thread that must conclude before this can change");
  if (conflictOn(d.id)) att.push("⚡ a disagreement between your answer and a waiting change");
  if (mandateOpen(d)) att.push("⚖ settling this needs its mandated thread");
  var answer = answerTextOf(d.id);
  showHover('<div class="hid">' + (st === "fogged" ? "fogged" : esc(d.id)) + " · " + LABELS[st] + "</div>" +
    "<div><strong>" + esc(st === "fogged" ? d.fogTitle || "" : d.title) + "</strong></div>" +
    (st === "fogged" ? "" : "<div>" + esc(d.body.slice(0, 150)) + (d.body.length > 150 ? "…" : "") + "</div>") +
    (answer ? '<div style="opacity:.75;margin-top:4px">→ ' + esc(answer.slice(0, 110)) + "</div>" : "") +
    (att.length ? '<div class="att">' + att.map(function (x) { return "<div>" + x + "</div>"; }).join("") + "</div>" : ""),
    n.getBoundingClientRect());
});
document.addEventListener("mouseout", function (e) {
  // The pointer leaving the window raises no `mouseover` anywhere, so the option
  // it was resting on has to be let go of here.
  inHand("overOpt", optionOf(e.relatedTarget));
  // Leaving the muted zone for something that is not it is what re-arms it.
  // `relatedTarget` is where the pointer went, so drifting within one zone is
  // not a leave — and treating it as one would hand the overlay straight back.
  var left = zoneOf(e.target);
  if (MUTED && left && zoneKey(left) === MUTED) {
    var into = e.relatedTarget ? zoneOf(e.relatedTarget) : null;
    if (zoneKey(into) !== MUTED) MUTED = null;
  }
  if (HOVER && left) HOVER.style.display = "none";
});

/* drag to pan the map */
var DRAG = null;
document.addEventListener("mousedown", function (e) {
  var m = e.target.closest("#mapscroll");
  if (!m || e.target.closest(".mnode")) return;
  DRAG = { el: m, x: e.clientX, y: e.clientY, sl: m.scrollLeft, st: m.scrollTop };
  m.classList.add("grabbing");
  e.preventDefault();
});
document.addEventListener("mousemove", function (e) {
  if (!DRAG) return;
  DRAG.el.scrollLeft = DRAG.sl - (e.clientX - DRAG.x);
  DRAG.el.scrollTop = DRAG.st - (e.clientY - DRAG.y);
});
document.addEventListener("mouseup", function () {
  if (DRAG) DRAG.el.classList.remove("grabbing");
  DRAG = null;
});

// The claim comes first and the board second: this window learns which session
// it is talking to, and whether the session answers it, before it reads a thing.
// A refused window therefore never holds a board at all — it has never been sent
// one.
claim(false).then(poll);
setInterval(poll, 700);
// Re-presented on its own slower cadence, because a claim changes at most a
// couple of times in a session and this is only how a window finds out it was
// taken over. Separate from the board poll rather than folded into it: the board
// must not stop being read because a control call is slow, and the control must
// keep being asked by a window that has stopped reading the board.
setInterval(function () { claim(false); }, 1500);
// The lane's timer ticks without a full render, so a running clock never steals
// focus from the textbox that is meant to always hold it. Every clock on the
// page moves on this one beat: the diagnostic's per-channel rows and a thread's
// waiting marker are the same wait told per channel, and two beats would let
// them disagree with the header.
setInterval(function () {
  var el = document.getElementById("lanetimer");
  if (el) el.textContent = agentSignal().text;
  tickWaitClocks();
}, 1000);
// Browsers throttle timers in a background tab, so replies pile up while you
// are elsewhere. Collect them the moment you are back.
document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
document.addEventListener("DOMContentLoaded", render);
