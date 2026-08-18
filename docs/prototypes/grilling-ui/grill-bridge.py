#!/usr/bin/env python3
"""Session-scoped localhost mail slot between the grilling UI and an agent.

Two append-only logs -- UI->agent events and agent->UI updates -- read with a
cursor, plus static file service for the prototype directory off the same
port. No grilling semantics live here: the bridge never looks inside a
payload, it only hands it to the other side in order.

PROTOTYPE -- THROWAWAY. Process memory only; everything dies with the process.

    python3 grill-bridge.py [port]      # default 8378, 127.0.0.1 only
    python3 grill-bridge.py --self-test # in-process round trip, both queues
"""

import argparse
import functools
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
MARKER = "GRILL-BRIDGE SELF-TEST OK"


class Slot:
    """One direction of the mail slot.

    Append-only with a read cursor rather than a destructive pop: a poll that
    times out or a page that reloads can re-read from any cursor, and two
    readers never race each other for a message.
    """

    def __init__(self):
        self.items = []
        self.lock = threading.Lock()

    def put(self, payloads):
        with self.lock:
            for p in payloads:
                self.items.append({"seq": len(self.items) + 1, "body": p})
            return len(self.items)

    def since(self, n):
        with self.lock:
            return self.items[n:], len(self.items)

    def clear(self):
        with self.lock:
            self.items = []

    def __len__(self):
        with self.lock:
            return len(self.items)


def normalize(body):
    """Accept {"events":[..]}, {"updates":[..]}, a bare list, or one object."""
    if body is None:
        raise ValueError("empty body")
    if isinstance(body, dict):
        for k in ("events", "updates", "items"):
            if k in body:
                body = body[k]
                break
    if isinstance(body, dict):
        body = [body]
    if not isinstance(body, list):
        raise TypeError("expected a JSON list, or an object wrapping one")
    if not body:
        raise ValueError("nothing to post")
    return body


class Bridge(SimpleHTTPRequestHandler):
    # Class attributes: one pair of queues per process, shared by every request
    # thread. That is the whole persistence model.
    events = Slot()
    updates = Slot()

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        # The page may be opened from file://, whose origin is "null".
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _slot(self, path):
        return {"/bridge/events": self.events, "/bridge/updates": self.updates}.get(path)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/bridge/status":
            return self._json({"ok": True, "events": len(self.events), "updates": len(self.updates)})
        slot = self._slot(u.path)
        if slot is None:
            return SimpleHTTPRequestHandler.do_GET(self)
        raw = parse_qs(u.query).get("since", ["0"])[0]
        try:
            since = max(0, int(raw))
        except ValueError:
            return self._json({"ok": False, "error": "since must be an integer, got %r" % raw}, 400)
        items, total = slot.since(since)
        self._json({"ok": True, "since": since, "next": total, "items": items})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/bridge/reset":
            self.events.clear()
            self.updates.clear()
            return self._json({"ok": True, "reset": True})
        slot = self._slot(u.path)
        if slot is None:
            return self._json({"ok": False, "error": "no such endpoint: %s" % u.path}, 404)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            payloads = normalize(json.loads(raw or b"null"))
        except (ValueError, TypeError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        self._json({"ok": True, "accepted": len(payloads), "next": slot.put(payloads)})

    def log_message(self, fmt, *args):
        # The UI polls twice a second; logging that buries everything else.
        if self.command == "GET" and self.path.startswith("/bridge/"):
            return
        SimpleHTTPRequestHandler.log_message(self, fmt, *args)


def serve(port):
    return ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Bridge, directory=str(HERE)))


def _req(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=5) as resp:
        return json.loads(resp.read())


def self_test():
    Bridge.events.clear()
    Bridge.updates.clear()
    srv = serve(0)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    checked = 0
    try:
        ev = {"kind": "answer", "nodeId": "D1", "answer": {"optionId": "a"}, "source": "user"}
        assert _req(base, "/bridge/events", {"events": [ev]})["accepted"] == 1
        checked += 1
        got = _req(base, "/bridge/events?since=0")
        assert [i["body"] for i in got["items"]] == [ev], got
        checked += 1
        assert got["next"] == 1 and got["items"][0]["seq"] == 1, got
        checked += 1
        assert _req(base, "/bridge/events?since=1")["items"] == [], "the cursor did not advance"
        checked += 1

        up = {"kind": "informational", "id": "U1-i", "nodeId": "D1",
              "summary": "Informational: noted.", "text": "Recorded."}
        assert _req(base, "/bridge/updates", {"updates": [up]})["accepted"] == 1
        checked += 1
        got2 = _req(base, "/bridge/updates?since=0")
        assert [i["body"] for i in got2["items"]] == [up], got2
        checked += 1

        # The two directions are separate slots and must not leak into each other.
        assert _req(base, "/bridge/events?since=0")["next"] == 1, "an update landed in the event queue"
        checked += 1
        st = _req(base, "/bridge/status")
        assert st["events"] == 1 and st["updates"] == 1, st
        checked += 1

        # Static files come off the same port as the queues.
        with urllib.request.urlopen(base + "/grill-bridge.py", timeout=5) as r:
            assert MARKER.encode() in r.read(), "static file service did not return this file"
        checked += 1

        assert _req(base, "/bridge/reset", {})["reset"] is True
        checked += 1
        assert _req(base, "/bridge/status")["events"] == 0, "reset left the event queue behind"
        checked += 1

        # A post with nothing in it is refused, not silently accepted.
        try:
            _req(base, "/bridge/events", {"events": []})
            raise AssertionError("an empty post was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 400, e
        checked += 1
    finally:
        srv.shutdown()
        srv.server_close()
    assert checked == 12, "only %d of 12 checks ran -- the run short-circuited" % checked
    print("%s (%d checks, both directions round-tripped)" % (MARKER, checked))


def main(argv):
    ap = argparse.ArgumentParser(description="localhost mail slot for the grilling UI prototype")
    ap.add_argument("port", nargs="?", type=int, default=8378, help="default 8378")
    ap.add_argument("--self-test", action="store_true", help="round-trip both queues in process and exit")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    srv = serve(a.port)
    print("grill bridge on http://127.0.0.1:%d  (serving %s)" % (srv.server_address[1], HERE))
    print("  UI:    POST /bridge/events   GET /bridge/updates?since=N")
    print("  agent: GET  /bridge/events?since=N   POST /bridge/updates")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
