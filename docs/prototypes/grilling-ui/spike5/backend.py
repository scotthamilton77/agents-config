#!/usr/bin/env python3
"""Server-authoritative grilling backend — round-5 spike.

Round 4 put a dumb mail slot between a page that owned the board and an agent
that watched it. This inverts that: the backend owns an append-only event log on
disk, projects it into the two context images the grillers read, mints its own
agents, and serves the page as a viewer that may arrive late, reload, or leave.

    python3 backend.py --self-test
    python3 backend.py --session /tmp/grill-a --handoff handoff.json
    python3 backend.py --session /tmp/grill-a            # resume; log wins

Stdlib only. LLM turns go out over two mechanisms:
  fast tier — an HTTP chat-completions call with tool use (`respond` / `upgrade_me`)
  heavy tier — the `claude` CLI in print mode, resumed by session id
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLAUDE_BIN = "/Users/scott/.local/bin/claude"
# Fast tier goes over OpenRouter's OpenAI-compatible endpoint, because the direct
# Anthropic API path is deliberately closed: ANTHROPIC_API_KEY is exported empty
# on purpose, since a populated key would override the subscription and bill per
# token. Claude-model turns therefore go through the CLI (heavy tier, below) and
# everything else routes here. Do not "fix" this by populating the key.
FAST_MODEL = "google/gemini-2.5-flash"
HEAVY_CLI_MODEL = "sonnet"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# What the page is allowed to put in the log. Anything else gets a rejection
# receipt rather than the round-4 silent no-op (W6).
UI_KINDS = {"ui-hello", "answer", "thread-created", "thread-turn", "note"}
# Turns that owe the human an answer, and therefore light the status lane.
# A thread-created is answerable only when a human actually said something in it
# — the page also opens agent-authored threads (mandates), which owe no reply.
ANSWERABLE = {"answer", "thread-created", "thread-turn"}
# Kinds the page emits that the log records without the backend reacting.
IGNORED_UI_KINDS = {
    "thread-open", "thread-park", "thread-fold", "thread-dismissed", "thread-abandoned",
    "answer-held", "answer-release", "answer-abandoned", "queued", "applied", "dismissed",
    "conflict-raised", "conflict-resolved", "note-read", "auto-pref", "banner", "provisional",
}
# Kinds the BACKEND authors into the same log; the page never posts these.
AGENT_KINDS = {"agent-status", "dispatch", "tool-call", "session-start", "session-resume",
               "informational", "elicit-alert", "revise", "settle", "unsettle", "invalidate",
               "resolve-stale", "elicit-node", "add-node"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def auto_thread(node_id):
    """Every turn belongs to some thread. Answering a decision opens no thread of
    its own, so replies to an answer land in the decision's implicit one — one
    derivation, used by the accept path, the driver and the projector alike."""
    return "auto-" + str(node_id)


def lane_of(ev):
    return {"threadId": ev.get("threadId") or auto_thread(ev.get("nodeId")),
            "nodeId": ev.get("nodeId")}


def turns_of(e):
    """[(who, text)] for any turn-bearing event.

    The page speaks in `turns[]` — always, for both thread-created and
    thread-turn. Backend-authored replies carry a bare `text`. One reader for
    both, because writing the backend against only the second shape is exactly
    how the real UI path came to be rejected while the scripted one passed.
    """
    if e.get("turns"):
        return [(t.get("who") or "human", t.get("text") or "") for t in e["turns"]]
    # `src` is stamped at append time, so an event still being validated has
    # none — and an inbound UI event is a human by definition. Only the
    # backend's own replies are the agent.
    return [("agent" if e.get("src") == "agent" else "human", e.get("text") or "")]


def human_text(ev):
    """What the human said, latest last. Empty means nobody is owed a reply."""
    said = [t for who, t in turns_of(ev) if who == "human"]
    return (said[-1] if said else "").strip()


# --------------------------------------------------------------------------
# projection — a pure fold over the log, so replay is provably deterministic
# --------------------------------------------------------------------------

def project(log, plan):
    """(log, plan) -> (image1, image2). No clock, no randomness, no I/O."""
    decisions = {}
    order = []
    for d in plan["decisions"]:
        decisions[d["id"]] = {
            "id": d["id"], "short": d["short"], "title": d["title"],
            "question": d["body"], "prereqs": d.get("prereqs", []),
            "options": [{"id": o["id"], "text": o["text"]} for o in d["options"]],
            "answer": None, "answered_by": None, "answered_at": None,
        }
        order.append(d["id"])

    threads = {}
    history = {d: [] for d in order}
    for e in log:
        k, seq, ts = e.get("kind"), e.get("seq"), e.get("ts")
        nid = e.get("nodeId")
        if k == "answer" and nid in decisions:
            a = e.get("answer") or {}
            text = a.get("text")
            if not text:
                opt = a.get("optionId")
                match = [o for o in decisions[nid]["options"] if o["id"] == opt]
                text = match[0]["text"] if match else "(option %s)" % opt
            decisions[nid].update(answer=text, answered_by=e.get("src"), answered_at=ts)
            history[nid].append({"seq": seq, "ts": ts, "what": "answered: " + text})
        elif k in ("thread-turn", "thread-created"):
            tid = e.get("threadId") or auto_thread(nid)
            t = threads.setdefault(tid, {"threadId": tid, "nodeId": nid, "turns": []})
            if k == "thread-created":
                t["tkind"] = e.get("tkind")            # user / mandate / pending
                t["title"] = e.get("title")
                t["requiresAction"] = e.get("requiresAction", False)
            for who, text in turns_of(e):
                t["turns"].append({"who": who, "tier": e.get("tier"),
                                   "seq": seq, "ts": ts, "text": text})
                if nid in history:
                    label = who if who == "human" else "agent(%s)" % e.get("tier")
                    history[nid].append({"seq": seq, "ts": ts,
                                         "what": "%s in thread %s: %s" % (label, tid, text[:400])})
        elif k == "note" and nid in decisions:
            history[nid].append({"seq": seq, "ts": ts, "what": "note: " + e.get("text", "")})

    def status(d):
        if d["answer"]:
            return "settled"
        return "open" if all(decisions[p]["answer"] for p in d["prereqs"] if p in decisions) else "blocked"

    snapshot = []
    for i in order:
        d = dict(decisions[i])
        d["status"] = status(decisions[i])
        snapshot.append(d)

    last = log[-1] if log else {}
    image1 = {
        "image": 1, "epoch": last.get("epoch"), "seq": last.get("seq", 0),
        "plan": plan["statement"], "decisions": snapshot,
        "frontier": [d["id"] for d in snapshot if d["status"] == "open"],
        "settled": [d["id"] for d in snapshot if d["status"] == "settled"],
        "threads": threads,
    }
    image2 = dict(image1)
    image2["image"] = 2
    image2["history"] = history
    return image1, image2


# --------------------------------------------------------------------------
# session — the log is the source of truth; everything else is derived
# --------------------------------------------------------------------------

class Session:
    def __init__(self, path, handoff_path=None, driver=None):
        self.dir = os.path.abspath(path)
        os.makedirs(self.dir, exist_ok=True)
        self.log_path = os.path.join(self.dir, "log.jsonl")
        self.lock = threading.RLock()
        self.driver = driver
        self.log = []
        self.seen = {}          # client idempotency key -> seq it landed at (W3/W7)
        self.status_since = {}

        if os.path.exists(self.log_path):
            with open(self.log_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.log.append(json.loads(line))
        for e in self.log:
            if e.get("cid"):
                self.seen[e["cid"]] = e["seq"]

        if self.log:
            self.plan = self.log[0]["plan"]
        else:
            if not handoff_path:
                raise SystemExit("empty session and no --handoff to seed it from")
            with open(handoff_path) as fh:
                self.handoff = json.load(fh)
            self.plan = self.handoff["plan"]

        # A restart mints a NEW epoch on a CONTINUING seq. That pairing is the
        # point: epoch identifies the process a client is talking to, seq
        # identifies the position in a log that outlives every process (W1/W2).
        self.epoch = "e-" + uuid.uuid4().hex[:8]
        self.next_seq = (self.log[-1]["seq"] + 1) if self.log else 1
        if not self.log:
            self._append("server", {
                "kind": "session-start", "plan": self.plan,
                "handoff": {k: v for k, v in self.handoff.items() if k != "plan"},
                "label": "session seeded from handoff",
            })
        else:
            self._append("server", {"kind": "session-resume",
                                    "label": "backend restarted; log replayed",
                                    "replayed_events": len(self.log)})
        self.refresh_images()

    # -- append-only writing -------------------------------------------------

    def _append(self, src, body):
        """Assign the epoch and the ONE authoritative seq, then fsync. Caller holds lock."""
        e = dict(body)
        e["seq"] = self.next_seq
        e["epoch"] = self.epoch
        e["src"] = src
        e.setdefault("ts", now())
        self.next_seq += 1
        self.log.append(e)
        with open(self.log_path, "a") as fh:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if e.get("cid"):
            self.seen[e["cid"]] = e["seq"]
        return e["seq"]

    def append(self, src, body):
        with self.lock:
            seq = self._append(src, body)
            self.refresh_images()
            return seq

    def refresh_images(self):
        self.image1, self.image2 = project(self.log, self.plan)
        for name, img in (("image1.json", self.image1), ("image2.json", self.image2)):
            tmp = os.path.join(self.dir, name + ".tmp")
            with open(tmp, "w") as fh:
                json.dump(img, fh, indent=2, sort_keys=True)
            os.replace(tmp, os.path.join(self.dir, name))

    # -- the accept path -----------------------------------------------------

    def accept(self, ev, epoch):
        """One UI event in, one uniform receipt out. Rejections are receipts too (W6)."""
        cid = ev.get("cid")
        if not isinstance(cid, str) or not cid:
            return {"cid": cid, "status": "rejected", "reason": "missing cid (idempotency key)"}
        with self.lock:
            if cid in self.seen:
                return {"cid": cid, "status": "duplicate", "seq": self.seen[cid],
                        "reason": "already applied at seq %d" % self.seen[cid]}
            if epoch != self.epoch:
                return {"cid": cid, "status": "rejected", "reason": "epoch mismatch",
                        "server_epoch": self.epoch, "sent_epoch": epoch}
            kind = ev.get("kind")
            if kind not in UI_KINDS:
                return {"cid": cid, "status": "rejected", "reason": "unknown kind: %r" % (kind,)}
            if kind == "answer":
                nid = ev.get("nodeId")
                if not any(d["id"] == nid for d in self.plan["decisions"]):
                    return {"cid": cid, "status": "rejected", "reason": "unknown nodeId: %r" % (nid,)}
                if not (ev.get("answer") or {}).get("optionId") and not (ev.get("answer") or {}).get("text"):
                    return {"cid": cid, "status": "rejected", "reason": "answer carries neither optionId nor text"}
            # A thread event has to carry a turn from somebody. Only a HUMAN turn
            # owes a reply, so an agent-authored mandate thread is recorded and
            # left alone rather than answered.
            owed = ""
            if kind in ("thread-turn", "thread-created"):
                if not turns_of(ev)[0][1].strip():
                    return {"cid": cid, "status": "rejected", "reason": "thread event carries no turn"}
                owed = human_text(ev)

            seq = self._append("ui", ev)

            # THE STATUS LANE. Mechanical, synchronous, inside the same lock as
            # the accept, before one byte goes to any model. This is the whole
            # answer to W4/L1: the human learns the turn landed at transport
            # speed, and learns the agent is working before the agent knows it.
            answerable = kind in ANSWERABLE and (kind == "answer" or owed)
            if answerable:
                lane = dict(lane_of(ev), in_reply_to=seq)
                self._append("server", dict(lane, kind="agent-status", phase="received",
                                            label="turn accepted"))
                self._append("server", dict(lane, kind="agent-status", phase="composing",
                                            tier="fast", label="fast tier composing"))
            self.refresh_images()

        if answerable and self.driver:
            threading.Thread(target=self.driver, args=(self, ev, seq), daemon=True).start()
        return {"cid": cid, "status": "accepted", "seq": seq, "epoch": self.epoch}

    def updates_since(self, cursor):
        with self.lock:
            return [e for e in self.log if e["seq"] > cursor and e["src"] != "ui"]

    def state(self):
        with self.lock:
            return {"ok": True, "epoch": self.epoch, "seq": self.next_seq - 1,
                    "plan": self.plan["statement"], "image1": self.image1,
                    "log_length": len(self.log)}


# --------------------------------------------------------------------------
# agent drive
# --------------------------------------------------------------------------

GRILLER_SYSTEM = """You are the grilling agent for a design session. The human is
stress-testing a plan with you. You see the CURRENT board as a context image —
it is projected from the session's event log, so it is authoritative; there is no
other state you are missing.

House rules:
- Be concise. Two or three sentences. One sharp question beats three soft ones.
- Attack the reasoning, never the human.
- You have exactly two tools and must call exactly one. `respond` says something
  to the human. `upgrade_me` hands this turn to a heavier model.

Escalate with `upgrade_me` when ANY of these holds — this is a rule, not a
feeling, and "I could probably manage" is not a reason to skip it:
  1. The human has asked you to COMMIT to a recommendation (not to ask a
     question back) on a decision with two or more dependents.
  2. The human has already rejected a reframing of the question, or says the
     trade-off itself is what they cannot resolve.
  3. Answering well requires weighing consequences across three or more
     decisions at once.
Otherwise `respond`. Asking a sharpening question back is a `respond`, and it is
the right move most of the time — escalation costs real money and real seconds.

Handoff brief:
{brief}
"""


def _context_block(session, ev):
    """What a griller is given: image 2, trimmed to what this turn is about."""
    img = session.image2
    nid = ev.get("nodeId")
    settled = [d for d in img["decisions"] if d["status"] == "settled"]
    # Settled decisions are trimmed out of the detail below, so their answers
    # have to survive here. Listing bare ids loses exactly the thing a griller
    # needs to stay consistent with what the human already decided.
    lines = ["PLAN: " + img["plan"], "ALREADY SETTLED:"]
    lines += ["  %s (%s) — %s" % (d["id"], d["short"], d["answer"]) for d in settled] or ["  (nothing yet)"]
    lines.append("FRONTIER: " + (", ".join(img["frontier"]) or "(none)"))
    for d in img["decisions"]:
        if d["id"] == nid or d["status"] == "open":
            lines.append("\n[%s] %s — %s\n  Q: %s" % (d["id"], d["short"], d["status"], d["question"]))
            for o in d["options"]:
                lines.append("  (%s) %s" % (o["id"], o["text"]))
            if d["answer"]:
                lines.append("  ANSWERED: " + d["answer"])
    if nid and img["history"].get(nid):
        lines.append("\nHISTORY OF %s (regenerated from the event log, not from memory):" % nid)
        for h in img["history"][nid]:
            lines.append("  seq %s — %s" % (h["seq"], h["what"]))
    tid = lane_of(ev)["threadId"]
    if tid in img["threads"]:
        lines.append("\nTHREAD %s SO FAR:" % tid)
        for t in img["threads"][tid]["turns"]:
            lines.append("  %s: %s" % (t["who"], t["text"]))
    return "\n".join(lines)


def fast_call(payload):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


TOOLS = [
    {"type": "function", "function": {
        "name": "respond",
        "description": "Post your reply into the grilling session. This is what the human reads.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                       "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "upgrade_me",
        "description": ("Escalate this turn to the heavy tier. Use only when the question turns on "
                        "judgement you cannot supply at your weight."),
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}},
                       "required": ["reason"]}}},
]


def heavy_turn(session, prompt):
    """Mechanism (b): the claude CLI in print mode, resumed by session id.

    The session's CLI conversation id lives in meta.json, so the CLI's own
    context accumulates across turns — but note the prompt still carries the
    board from image 2, because the CLI session is a cache, never the truth.
    """
    meta_path = os.path.join(session.dir, "meta.json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    sid = meta.get("cli_session_id")
    args = [CLAUDE_BIN, "-p", "--model", HEAVY_CLI_MODEL, "--output-format", "json"]
    args += ["--resume", sid] if sid else ["--session-id", (sid := str(uuid.uuid4()))]
    env = dict(os.environ)
    # Subscription billing depends on no API key being in scope. The variable is
    # already exported empty for exactly this reason; stripping it keeps that
    # intent explicit and holds if someone ever sets a real one.
    env.pop("ANTHROPIC_API_KEY", None)
    t0 = time.time()
    p = subprocess.run(args, input=prompt, capture_output=True, text=True, env=env, timeout=600)
    dt = time.time() - t0
    if p.returncode != 0:
        raise RuntimeError("claude CLI exit %d: %s" % (p.returncode, p.stderr[:400]))
    out = json.loads(p.stdout)
    meta["cli_session_id"] = out.get("session_id", sid)
    json.dump(meta, open(meta_path, "w"), indent=2)
    return out.get("result", ""), dt, out


def live_driver(session, ev, in_reply_to):
    """Fast tier first; escalate to the heavy tier only when it asks to."""
    lane = dict(lane_of(ev), in_reply_to=in_reply_to)
    try:
        brief = session.log[0].get("handoff", {}).get("grilling_brief", {})
        ctx = _context_block(session, ev)
        human = human_text(ev) or "I answered %s. Push back if that is wrong." % ev.get("nodeId")
        # What we asked the model is part of the session, not a detail of this
        # process. Logging it is what makes "the turn after a restart carried the
        # history" checkable rather than asserted.
        fast_prompt = ctx + "\n\nTHE HUMAN JUST SAID:\n" + human
        session.append("server", dict(lane, kind="dispatch", tier="fast", model=FAST_MODEL,
                                      prompt=fast_prompt))
        t0 = time.time()
        resp = fast_call({
            "model": FAST_MODEL, "max_tokens": 700, "tools": TOOLS, "tool_choice": "required",
            "messages": [
                {"role": "system", "content": GRILLER_SYSTEM.format(brief=json.dumps(brief, indent=2))},
                {"role": "user", "content": fast_prompt}],
        })
        fast_dt = time.time() - t0
        cost = (resp.get("usage") or {}).get("cost")
        calls = (resp["choices"][0]["message"] or {}).get("tool_calls") or []
        if not calls:
            raise RuntimeError("fast tier returned no tool call")
        name = calls[0]["function"]["name"]
        cargs = json.loads(calls[0]["function"]["arguments"] or "{}")

        if name == "respond":
            session.append("agent", dict(lane, kind="thread-turn", tier="fast",
                                         model=FAST_MODEL, text=cargs.get("text", ""),
                                         latency_s=round(fast_dt, 2), cost_usd=cost))
            session.append("server", dict(lane, kind="agent-status", phase="done", tier="fast"))
            return

        # upgrade_me — the same question, re-dispatched with accumulated context.
        session.append("agent", dict(lane, kind="tool-call", tier="fast", model=FAST_MODEL,
                                     tool="upgrade_me", reason=cargs.get("reason", ""),
                                     latency_s=round(fast_dt, 2), cost_usd=cost))
        session.append("server", dict(lane, kind="agent-status", phase="upgrading", tier="heavy",
                                      label="fast tier escalated: " + cargs.get("reason", "")[:200]))
        prompt = (GRILLER_SYSTEM.format(brief=json.dumps(brief, indent=2))
                  + "\n\n" + ctx
                  + "\n\nTHE HUMAN JUST SAID:\n" + human
                  + "\n\nA faster model escalated this to you because: "
                  + cargs.get("reason", "")
                  + "\n\nAnswer the human directly in two or three sentences. No preamble.")
        session.append("server", dict(lane, kind="dispatch", tier="heavy",
                                      model="cli:" + HEAVY_CLI_MODEL, prompt=prompt))
        text, heavy_dt, raw = heavy_turn(session, prompt)
        session.append("agent", dict(lane, kind="thread-turn", tier="heavy",
                                     model="cli:" + HEAVY_CLI_MODEL, text=text,
                                     latency_s=round(heavy_dt, 2),
                                     upgraded_from="fast", cost_usd=raw.get("total_cost_usd")))
        session.append("server", dict(lane, kind="agent-status", phase="done", tier="heavy"))
    except Exception as exc:                                    # noqa: BLE001 — spike
        session.append("server", dict(lane, kind="agent-status", phase="error",
                                      label="%s: %s" % (type(exc).__name__, exc)))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    session = None
    static_dirs = []

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        args = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        s = self.session
        if path == "/session/state":
            return self._send(200, s.state())
        if path == "/session/updates":
            if args.get("epoch") and args["epoch"] != s.epoch:
                return self._send(409, {"ok": False, "error": "epoch mismatch",
                                        "epoch": s.epoch, "reload": True})
            cur = int(args.get("since", 0))
            items = s.updates_since(cur)
            return self._send(200, {"ok": True, "epoch": s.epoch, "since": cur,
                                    "next": items[-1]["seq"] if items else cur, "items": items})
        if path in ("/session/image1", "/session/image2"):
            return self._send(200, s.image1 if path.endswith("1") else s.image2)
        if path == "/session/log":
            return self._send(200, {"ok": True, "items": s.log})
        return self._static(path)

    def _static(self, path):
        name = os.path.basename(path.strip("/")) or "grilling-ui-prototype-r5.html"
        for d in self.static_dirs:
            f = os.path.join(d, name)
            if os.path.isfile(f):
                body = open(f, "rb").read()
                ctype = "text/html" if name.endswith(".html") else "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        self._send(404, {"ok": False, "error": "not found: " + name})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as exc:
            return self._send(400, {"ok": False, "error": "bad JSON: %s" % exc})
        if self.path != "/session/events":
            return self._send(404, {"ok": False, "error": "no such endpoint"})
        evs = body.get("events") or []
        if not evs:
            return self._send(400, {"ok": False, "error": "nothing to post"})
        epoch = body.get("epoch")
        receipts = [self.session.accept(e, epoch) for e in evs]
        return self._send(200, {"ok": True, "epoch": self.session.epoch,
                                "seq": self.session.next_seq - 1, "receipts": receipts})


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test():
    import shutil
    import tempfile

    checks = []

    def ck(name, cond, detail=""):
        checks.append(name)
        if not cond:
            raise AssertionError("FAILED %s %s" % (name, detail))
        print("  ok  %s" % name)

    tmp = tempfile.mkdtemp(prefix="spike5-selftest-")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        sdir = os.path.join(tmp, "s1")
        s = Session(sdir, handoff_path=os.path.join(here, "handoff.json"), driver=None)

        # -- seq/epoch assignment -------------------------------------------
        ck("seed appended session-start at seq 1", s.log[0]["seq"] == 1 and s.log[0]["kind"] == "session-start")
        r1 = s.accept({"cid": "c1", "kind": "answer", "nodeId": "D1",
                       "answer": {"optionId": "a"}}, s.epoch)
        ck("first UI event accepted", r1["status"] == "accepted", r1)
        r2 = s.accept({"cid": "c2", "kind": "thread-turn", "threadId": "t1", "nodeId": "D1",
                       "text": "Why is a frozen list better?"}, s.epoch)
        ck("thread turn accepted", r2["status"] == "accepted", r2)
        seqs = [e["seq"] for e in s.log]
        ck("seq is dense, strictly increasing, one per entry",
           seqs == list(range(1, len(s.log) + 1)), seqs)
        ck("every entry carries the session epoch",
           all(e["epoch"] == s.epoch for e in s.log))

        # -- the status lane fires mechanically ------------------------------
        lane = [e for e in s.log if e["kind"] == "agent-status"]
        ck("status lane emitted received+composing per answerable turn",
           [e["phase"] for e in lane] == ["received", "composing"] * 2, [e["phase"] for e in lane])
        turn = [e for e in s.log if e["seq"] == r2["seq"]][0]
        ck("status lane sits immediately after its turn in the log",
           s.log[turn["seq"]]["kind"] == "agent-status"
           and s.log[turn["seq"]]["in_reply_to"] == r2["seq"])

        # -- the page's vocabulary, read off the page ---------------------------
        # wirecheck posts shapes I invented; the page posts its own. Reading the
        # kinds out of the real file is what makes a page-only kind impossible to
        # miss again — the whole reason thread-created reached production broken.
        page = os.path.join(here, "grilling-ui-prototype-r5.html")
        module = open(page, encoding="utf8").read().split("---GRILL-MODULE-END---")[0]
        # Scoped to `{kind: "x", nodeId|threadId` — an event object, not the
        # shell's panel kinds or a tkind value. Precision over recall on purpose:
        # a check that cries wolf gets muted, and this shape already covers the
        # kinds that carry a decision or a thread, which is where the risk is.
        emitted = set(re.findall(r'\{\s*kind:\s*"([a-z-]+)"\s*,\s*(?:nodeId|threadId|nodeIds)\b', module))
        unknown = emitted - UI_KINDS - IGNORED_UI_KINDS - AGENT_KINDS
        ck("every kind the page emits is known to the backend", not unknown, sorted(unknown))
        ck("the page really does emit thread-created", "thread-created" in emitted)

        # -- the page's SHAPE: turns[], never text ------------------------------
        made = s.accept({"cid": "tc1", "kind": "thread-created", "threadId": "D2-t", "nodeId": "D2",
                         "tkind": "user", "title": "Why wake at all",
                         "turns": [{"who": "human", "text": "Who exactly gets woken?"}]}, s.epoch)
        ck("a page-shaped thread-created is accepted", made["status"] == "accepted", made)
        ck("its human turn is projected", s.image1["threads"]["D2-t"]["turns"][0]["text"]
           == "Who exactly gets woken?", s.image1["threads"].get("D2-t"))
        ck("the thread carries its tkind", s.image1["threads"]["D2-t"].get("tkind") == "user")
        ck("a page-shaped turn is what the driver would be given",
           human_text({"turns": [{"who": "agent", "text": "a"}, {"who": "human", "text": "b"}]}) == "b")

        # An agent-authored mandate thread is recorded but owes no reply.
        before = len([e for e in s.log if e["kind"] == "agent-status"])
        mand = s.accept({"cid": "tc2", "kind": "thread-created", "threadId": "D12-m", "nodeId": "D12",
                         "tkind": "mandate", "requiresAction": True,
                         "turns": [{"who": "agent", "text": "Your selection is held."}]}, s.epoch)
        ck("a mandate thread is accepted", mand["status"] == "accepted", mand)
        ck("a mandate thread lights no status lane",
           len([e for e in s.log if e["kind"] == "agent-status"]) == before)
        ck("a thread event with no turns at all is rejected",
           s.accept({"cid": "tc3", "kind": "thread-created", "threadId": "z", "nodeId": "D2",
                     "turns": [{"who": "human", "text": "  "}]}, s.epoch)["status"] == "rejected")

        # -- a reply that names no thread still projects (answers open none) ---
        s.append("agent", dict(lane_of({"nodeId": "D1"}), kind="thread-turn", tier="fast",
                               text="Why does simplicity outweigh missing urgent work?"))
        ck("threadless agent reply lands in the decision's implicit thread",
           "auto-D1" in s.image1["threads"], list(s.image1["threads"]))
        ck("images stay JSON-serialisable with sorted keys",
           isinstance(json.dumps(s.image2, sort_keys=True), str))

        # -- idempotency ------------------------------------------------------
        before = len(s.log)
        dup = s.accept({"cid": "c1", "kind": "answer", "nodeId": "D1",
                        "answer": {"optionId": "c"}}, s.epoch)
        ck("duplicate cid gets a duplicate receipt", dup["status"] == "duplicate", dup)
        ck("duplicate cid appended nothing", len(s.log) == before, (before, len(s.log)))
        ck("duplicate receipt names the original seq", dup["seq"] == r1["seq"], dup)
        ck("the duplicate did not overwrite the answer",
           s.image1["decisions"][0]["answer"].startswith("A snapshot query"),
           s.image1["decisions"][0]["answer"])

        # -- rejection receipts ----------------------------------------------
        for name, ev, ep, frag in [
            ("unknown kind", {"cid": "x1", "kind": "detonate", "nodeId": "D1"}, s.epoch, "unknown kind"),
            ("unknown nodeId", {"cid": "x2", "kind": "answer", "nodeId": "D99",
                                "answer": {"optionId": "a"}}, s.epoch, "unknown nodeId"),
            ("contentless answer", {"cid": "x3", "kind": "answer", "nodeId": "D2",
                                    "answer": {}}, s.epoch, "neither optionId nor text"),
            ("empty thread turn", {"cid": "x4", "kind": "thread-turn", "threadId": "t1",
                                   "nodeId": "D1", "text": "   "}, s.epoch, "carries no turn"),
            ("stale epoch", {"cid": "x5", "kind": "answer", "nodeId": "D2",
                             "answer": {"optionId": "a"}}, "e-deadbeef", "epoch mismatch"),
            ("missing cid", {"kind": "answer", "nodeId": "D2", "answer": {"optionId": "a"}},
             s.epoch, "missing cid"),
        ]:
            before = len(s.log)
            r = s.accept(ev, ep)
            ck("rejected: " + name,
               r["status"] == "rejected" and frag in r["reason"] and len(s.log) == before, r)

        # -- replay determinism ----------------------------------------------
        a1, a2 = project(s.log, s.plan)
        b1, b2 = project(s.log, s.plan)
        ck("projection is pure (same log twice -> identical images)",
           json.dumps(a1, sort_keys=True) == json.dumps(b1, sort_keys=True)
           and json.dumps(a2, sort_keys=True) == json.dumps(b2, sort_keys=True))

        disk = [json.loads(l) for l in open(s.log_path) if l.strip()]
        ck("on-disk log matches the in-memory log",
           json.dumps(disk, sort_keys=True) == json.dumps(s.log, sort_keys=True))
        d1, d2 = project(disk, s.plan)
        ck("images rebuilt from disk alone are identical",
           json.dumps(d1, sort_keys=True) == json.dumps(a1, sort_keys=True)
           and json.dumps(d2, sort_keys=True) == json.dumps(a2, sort_keys=True))

        # -- restart: new epoch, continuing seq, state intact -----------------
        old_epoch, old_len = s.epoch, len(s.log)
        old_answer = s.image1["decisions"][0]["answer"]
        s2 = Session(sdir, driver=None)
        ck("restart replayed the whole log", len(s2.log) == old_len + 1, (old_len, len(s2.log)))
        ck("restart minted a new epoch", s2.epoch != old_epoch)
        ck("restart continued the seq", s2.log[-1]["seq"] == old_len + 1)
        ck("restart appended session-resume", s2.log[-1]["kind"] == "session-resume")
        ck("restart preserved the answer", s2.image1["decisions"][0]["answer"] == old_answer)
        ck("restart preserved thread history",
           any("Why is a frozen list better?" in h["what"] for h in s2.image2["history"]["D1"]))
        ck("restart re-armed idempotency (pre-restart cid still deduped)",
           s2.accept({"cid": "c1", "kind": "answer", "nodeId": "D1",
                      "answer": {"optionId": "b"}}, s2.epoch)["status"] == "duplicate")
        ck("a client on the OLD epoch is rejected, not silently accepted",
           s2.accept({"cid": "c9", "kind": "answer", "nodeId": "D2",
                      "answer": {"optionId": "a"}}, old_epoch)["status"] == "rejected")

        ck("images are on disk", os.path.exists(os.path.join(sdir, "image1.json"))
           and os.path.exists(os.path.join(sdir, "image2.json")))
        ck("image2 carries per-decision history and image1 does not",
           "history" in s2.image2 and "history" not in s2.image1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    EXPECTED = 41
    if len(checks) != EXPECTED:
        raise AssertionError("ran %d checks, expected %d — the run short-circuited"
                             % (len(checks), EXPECTED))
    print("\nSPIKE5 BACKEND SELF-TEST CLEAN — %d/%d checks passed" % (len(checks), EXPECTED))
    return 0


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--session")
    ap.add_argument("--handoff")
    ap.add_argument("--port", type=int, default=8379)
    ap.add_argument("--no-llm", action="store_true", help="serve without minting agents")
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    if not a.session:
        ap.error("--session is required")

    here = os.path.dirname(os.path.abspath(__file__))
    s = Session(a.session, handoff_path=a.handoff, driver=None if a.no_llm else live_driver)
    Handler.session = s
    Handler.static_dirs = [here, os.path.abspath(a.session)]
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("session %s  epoch %s  seq %d  ->  http://127.0.0.1:%d/grilling-ui-prototype-r5.html"
          % (s.dir, s.epoch, s.next_seq - 1, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
