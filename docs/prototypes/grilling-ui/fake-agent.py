#!/usr/bin/env python3
"""A canned grilling agent that plays its side over the real bridge.

Polls UI events off the bridge and posts structured updates back, covering the
four shapes that matter: an informational note, an elicitative alert that
blocks its decision, a conflicting revision that must queue in the inbox, and
a reply inside a thread. It is the stand-in you attach before wiring up a real
agent, and the thing to read when writing one.

PROTOTYPE -- THROWAWAY. No pip dependencies; no state on disk.

    python3 grill-bridge.py &            # in one shell
    python3 fake-agent.py                # in another, Ctrl-C to stop
    python3 fake-agent.py --exit-after 3 # stop once 3 updates have been posted
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

GENERIC_PCR = ["What it buys you.", "What it costs.", "What it forces later."]


def post(base, path, body):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read())


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return json.loads(resp.read())


def informational(uid, node, seq):
    return {"kind": "informational", "id": uid, "nodeId": node, "basedOnSeq": seq,
            "recommendNext": "D3",
            "summary": "Informational: a consequence of what you just chose.",
            "text": "Recorded. I am not asking you to change it — only noting that everything "
                    "downstream of %s now reads this as its premise, so it is the expensive "
                    "thing to revisit later." % node}


def elicit_alert(uid, node, seq):
    """Elicitative: needs judging, and blocks the decision until it concludes."""
    return {"kind": "elicit-alert", "id": uid, "nodeId": node, "basedOnSeq": seq,
            "threadId": "T-live-" + node, "requiresAction": True,
            "summary": "The agent needs something judged before %s is locked." % node,
            "title": "Does your proof rule notice a test that asserts nothing?",
            "turns": [{"who": "agent",
                       "text": "Before this locks I want to test the layer above it. Does anything "
                               "in your rule notice a test that passes because it asserts nothing? "
                               "I have locked %s while this is open — an answer either side of the "
                               "question means something different." % node},
                      {"who": "agent",
                       "text": "If nothing does, it is a proof about the suite, not about the work. "
                               "The cheapest repair is a reader that never saw the plan.",
                       "impact": {"summary": "Adds a fresh-context reviewer to the proof rule.",
                                  "detail": "Nothing settled downstream moves.",
                                  "updates": []}}]}


def conflicting_revision(uid, node, seq, options):
    """Deliberately stamped as generated one step BEFORE the answer it is
    replying to, which is exactly the race R7 routes to the inbox."""
    revised = [{"id": "z", "text": "Bounded by the constraint the agent raised while you were answering.",
                "pcr": GENERIC_PCR}] + [{"id": o["id"], "text": o["text"]} for o in options]
    return {"kind": "revise", "id": uid, "nodeId": node, "basedOnSeq": max(0, seq - 1),
            "summary": "Revises %s's options — raised before your answer landed." % node,
            "options": revised}


def thread_reply(uid, node, thread_id, seq):
    return {"kind": "thread-turn", "id": uid, "nodeId": node, "threadId": thread_id, "basedOnSeq": seq,
            "summary": "The agent replied in the thread on %s." % node,
            "turns": [{"who": "agent",
                       "text": "Taking that seriously: the version of this I would defend is the "
                               "narrow one. Say the word and I will fold it in as a constraint on "
                               "%s rather than as a new question." % node,
                       "impact": {"summary": "Folds the constraint into %s's options." % node,
                                  "detail": "Adds one option and makes it the recommendation. "
                                            "Nothing settled downstream moves.",
                                  "updates": [{"kind": "revise", "nodeId": node,
                                               "summary": "Options on %s revised by this thread." % node,
                                               "options": [{"id": "z",
                                                            "text": "Bounded by the constraint set out in this thread.",
                                                            "pcr": GENERIC_PCR}]}]}}]}


class FakeAgent:
    def __init__(self, base):
        self.base = base
        self.cursor = 0
        self.n = 0
        self.board = {}
        self.covered = set()

    def uid(self, tag):
        self.n += 1
        return "W%d-%s" % (self.n, tag)

    def options_for(self, node):
        return self.board.get(node, {}).get("options", [])

    def react(self, ev):
        """One UI event in, zero or more updates out. This is the whole agent."""
        kind = ev.get("kind")
        seq = ev.get("seq", 0)

        if kind == "ui-hello":
            self.board = {n["id"]: n for n in ev.get("nodes", [])}
            print("  board received: %d decisions, plan: %s" % (len(self.board), ev.get("plan", "")[:60]))
            return []

        if kind == "answer" and ev.get("source") == "user":
            node = ev.get("nodeId")
            if node == "D7":
                self.covered.add("elicitative")
                return [elicit_alert(self.uid("e"), node, seq)]
            if node == "D5":
                self.covered.add("conflict")
                return [conflicting_revision(self.uid("r"), node, seq, self.options_for(node))]
            self.covered.add("informational")
            return [informational(self.uid("i"), node, seq)]

        # A thread the user just opened, or spoke in again. In live mode the UI
        # sends the human turn alone and waits for this.
        if kind in ("thread-created", "thread-turn"):
            turns = ev.get("turns") or []
            if not turns or turns[-1].get("who") != "human":
                return []
            self.covered.add("thread-reply")
            return [thread_reply(self.uid("t"), ev.get("nodeId"), ev.get("threadId"), seq)]

        return []

    def step(self):
        j = get(self.base, "/bridge/events?since=%d" % self.cursor)
        self.cursor = j["next"]
        posted = 0
        for item in j["items"]:
            ev = item["body"]
            ups = self.react(ev)
            if not ups:
                continue
            print("  <- %-14s %-4s   -> %s" % (ev.get("kind"), ev.get("nodeId") or "",
                                               ", ".join(u["kind"] for u in ups)))
            post(self.base, "/bridge/updates", {"updates": ups})
            posted += len(ups)
        return posted


def main(argv):
    ap = argparse.ArgumentParser(description="canned grilling agent, over the real bridge")
    ap.add_argument("--base", default="http://127.0.0.1:8378")
    ap.add_argument("--exit-after", type=int, default=0, help="stop after posting N updates (0 = run forever)")
    ap.add_argument("--timeout", type=float, default=120.0, help="give up after N seconds of waiting")
    a = ap.parse_args(argv)

    agent = FakeAgent(a.base)
    print("fake agent attached to %s — polling for events" % a.base)
    posted, deadline = 0, time.time() + a.timeout
    try:
        while True:
            try:
                posted += agent.step()
            except urllib.error.URLError as e:
                print("  bridge unreachable (%s) — retrying" % e.reason, file=sys.stderr)
            if a.exit_after and posted >= a.exit_after:
                break
            if time.time() > deadline:
                print("timed out after %.0fs with %d updates posted" % (a.timeout, posted), file=sys.stderr)
                return 1 if a.exit_after else 0
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    print("posted %d updates; covered: %s" % (posted, ", ".join(sorted(agent.covered)) or "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
