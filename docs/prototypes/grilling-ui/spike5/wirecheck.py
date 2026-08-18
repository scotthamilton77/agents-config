#!/usr/bin/env python3
"""UI stand-in: post a turn, watch the wire, print a timestamped transcript.

The point of this script is the gap it measures. It prints, for every event the
backend publishes, the wall-clock delta from the moment the human turn was
posted — so "the status lane never waits on a model" is a number on the page,
not a claim in a document.

    python3 wirecheck.py --turn "..." --node D1 --thread t1
"""

import argparse
import json
import os
import time
import urllib.request

BASE = os.environ.get("SPIKE5_BASE", "http://127.0.0.1:8379")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turn", required=True)
    ap.add_argument("--node", default="D1")
    ap.add_argument("--thread", default="t1")
    ap.add_argument("--cid", default=None)
    ap.add_argument("--as-page", action="store_true",
                    help="post what the PAGE posts — thread-created with turns[] — "
                         "rather than the flat thread-turn this script invented")
    ap.add_argument("--epoch", default=None, help="force an epoch, to show a rejection")
    ap.add_argument("--wait", type=float, default=180)
    a = ap.parse_args()

    st = get("/session/state")
    epoch = a.epoch or st["epoch"]
    cursor = st["seq"]
    print("epoch=%s  cursor=%d" % (epoch, cursor))

    cid = a.cid or ("wire-%d" % int(time.time() * 1000))
    # The page opens a thread with `thread-created` and always speaks in
    # `turns[]`. Posting the flat shape is what let a broken real-UI path pass.
    ev = ({"cid": cid, "kind": "thread-created", "threadId": a.thread, "nodeId": a.node,
           "tkind": "user", "title": "thread on " + a.node,
           "turns": [{"who": "human", "text": a.turn}]}
          if a.as_page else
          {"cid": cid, "kind": "thread-turn", "threadId": a.thread,
           "nodeId": a.node, "text": a.turn})
    t0 = time.time()
    print("\nT+0.000  POST human turn  cid=%s  kind=%s" % (cid, ev["kind"]))
    r = post("/session/events", {"epoch": epoch, "events": [ev]})
    print("T+%.3f  receipt: %s" % (time.time() - t0, json.dumps(r["receipts"][0])))
    if r["receipts"][0]["status"] != "accepted":
        return

    seen = set()
    deadline = t0 + a.wait
    while time.time() < deadline:
        j = get("/session/updates?since=%d" % cursor)
        for it in j["items"]:
            if it["seq"] in seen:
                continue
            seen.add(it["seq"])
            cursor = max(cursor, it["seq"])
            dt = time.time() - t0
            if it["kind"] == "agent-status":
                print("T+%.3f  [status] seq=%d phase=%s tier=%s %s"
                      % (dt, it["seq"], it["phase"], it.get("tier"), it.get("label", "")))
                if it["phase"] in ("done", "error"):
                    print("\ntotal wall: %.3fs" % dt)
                    return
            elif it["kind"] == "tool-call":
                print("T+%.3f  [tool ] seq=%d tier=%s tool=%s (fast-tier latency %ss)\n           reason: %s"
                      % (dt, it["seq"], it["tier"], it["tool"], it.get("latency_s"), it.get("reason")))
            elif it["kind"] == "thread-turn":
                print("T+%.3f  [REPLY] seq=%d tier=%s model=%s latency=%ss cost=%s"
                      % (dt, it["seq"], it["tier"], it.get("model"),
                         it.get("latency_s"), it.get("cost_usd")))
                print("           %s" % it["text"].replace("\n", "\n           "))
            else:
                print("T+%.3f  [%s] seq=%d" % (dt, it["kind"], it["seq"]))
        time.sleep(0.25)
    print("\ntimed out after %.1fs" % a.wait)


if __name__ == "__main__":
    main()
