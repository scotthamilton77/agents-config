# Grilling-UI prototype, round 4 — build report

Round 4 answers O2, the one thing REACTIONS.md left deliberately deferred: **how the UI and the grilling
agent actually talk**. The canned agent that lived inside the prototype file for three rounds is gone. In
its place is a localhost mail slot, and the r4 page is driven by whatever is attached to it.

Deliverables, all in `docs/prototypes/grilling-ui/`:

| File | What it is |
|------|------------|
| `grill-bridge.py` | 235 lines, Python 3 stdlib only. Two in-memory queues, static file service, `--self-test`. |
| `grilling-ui-prototype-r4.html` | 2757 lines (r3 was 2743). r3 with the fake scheduler cut out and a bridge client in its place. |
| `BRIDGE.md` | The wire protocol: endpoints, both taxonomies, a real curl transcript. |
| `fake-agent.py` | 186 lines. Plays the agent side over the real wire — informational, elicitative, conflict, thread reply. |
| `BUILD-REPORT-R4.md` | This. |

`grilling-ui-prototype.html`, `-r2`, `-r3`, `REACTIONS.md` and the three earlier build reports are untouched.

---

## What the seam turned out to be

r3 was better factored for this than the brief assumed. Two functions in the page shell were the entire
fake agent, and both had exactly one caller:

- `dispatch()` reduced the action, then called `Grill.agentPlan(S, newEvents)` and handed the result to a
  `setTimeout`-style scheduler. **Replaced by** one `POST /bridge/events` of those same new events.
- `pump()`, on a 200ms interval, delivered due jobs as `Grill.reduce(S, {type: "agentResponse", updates})`.
  **Replaced by** a 500ms poll of `GET /bridge/updates?since=N` feeding that identical action.

Nothing else moved. The auto-apply taxonomy, the inbox, the pending locks, notifications, bubbles, threads,
the conflict machinery — all of it sits downstream of `agentResponse` and cannot tell the difference. The
`agentPlan` choreography itself still exists inside the module and is still exercised by the self-check; the
page just never calls it.

The scenario walkthroughs and the choreography table were removed rather than bypassed. Both described the
canned agent's canned behaviour ("Answer D3 — and hold the agent back so you can get there first"), which no
longer exists; leaving them as dead buttons would have been worse than deleting them. What replaces them is a
short bridge panel: what crosses the wire, and how to start it.

## The one thing that genuinely did not fit

**r3 generates the agent's thread replies synchronously, inside the reducer.** `newThread`, `threadSeed` and
`threadSay` each emit *two* turns — the human's and the agent's, the latter from `seedTurn`/`freeTurn`. There
was no update kind for an agent speaking in a thread, because the agent never had to: it was the same code.

A real agent cannot work that way, and the brief requires the fake driver to send a thread reply. So the
module gained two things, both additive:

- A `thread-turn` **update** kind, whose body is identical in shape to the `thread-turn` **event** that
  already existed. It appends turns to a named thread; naming a thread that does not exist does nothing.
  It auto-applies unconditionally — talking is not deciding.
- A `setLiveAgent(on)` flag. **Off** (the default) is round-3 behaviour exactly, canned replies and all,
  which is what the self-check exercises. **On** — set once by the r4 page — makes those three actions emit
  the human turn alone and wait for the wire.

This is the only place I extended the taxonomy rather than derived it, and it is flagged here because it is
the seam most likely to be wrong. The alternative — leave the canned reply in and let the real one arrive
after it — produces two agents talking in one thread, which is worse.

The rest of the update taxonomy in `BRIDGE.md` is read straight out of `applyUpdate` and `autoApplies`:
`informational`, `add-node`/`elicit-node`, `revise`, `settle`, `unsettle`, `invalidate`, `resolve-stale`,
`elicit-alert`. Nothing invented, nothing renamed.

## `basedOnSeq`, and the choice inside it

R7 decides at *arrival* whether an update may apply itself, and conflict detection turns on `basedOnSeq` —
the state sequence the update was written against. With a canned agent this was stamped automatically. With
a real one it has to cross the wire, so every UI event carries its `seq` and the agent stamps its reply with
the `seq` of the event it is answering.

An agent that forgets is the interesting case. The page reads a missing `basedOnSeq` as **0** — "based on
nothing" — so anything touching an already-answered decision conflicts and waits in the inbox. That is the
conservative reading and it errs toward interrupting the user, but the alternative (defaulting to the current
seq) silently disables the only thing standing between a human decision and an agent overwriting it. Stated
loudly in `BRIDGE.md`; worth a second opinion.

---

## Evidence per acceptance criterion

### AC1 — the bridge self-test passes, and a broken one fails

```
$ python3 grill-bridge.py --self-test
GRILL-BRIDGE SELF-TEST OK (12 checks, both directions round-tripped)
EXIT=0
```

The self-test starts the real server on an ephemeral 127.0.0.1 port and drives it over real HTTP: post an
event, read it back at `since=0`, confirm `since=1` is empty (the cursor advanced), the same both ways for
updates, the two queues do not leak into each other, `/bridge/status` agrees, a static file comes off the
same port, `/bridge/reset` empties both, and an empty post is refused with a 400. A counter asserts all
twelve ran, so a short-circuited run cannot exit 0 silently.

Sabotage: one character in `Slot.since`, so the cursor is ignored and every read returns everything.

```
$ sed 's/return self.items\[n:\], len(self.items)/return self.items[:], len(self.items)/' \
    grill-bridge.py > /tmp/grill-bridge-sabotaged.py
$ python3 /tmp/grill-bridge-sabotaged.py --self-test
    assert _req(base, "/bridge/events?since=1")["items"] == [], "the cursor did not advance"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: the cursor did not advance
EXIT=1
```

### AC2 — the r4 state module extracts and self-checks standalone

Same marker-fence method as r3, same two guards (exactly two markers, slice over 5000 bytes). Run from this
directory:

```
$ node -e "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const p=s.split('//---GRILL-MODULE-START---');if(p.length!==2)throw new Error('marker collision: '+p.length);const m=p[1].split('//---GRILL-MODULE-END---')[0];if(m.length<5000)throw new Error('slice too small: '+m.length);fs.writeFileSync('/tmp/grill-r4-module.js',m);" \
    grilling-ui-prototype-r4.html && node /tmp/grill-r4-module.js
grilling r4 state module self-check: OK (16 base decisions, 2 agent-addable, 9 events in the last session, live-agent thread turns covered)
EXIT=0
```

The module is 80,011 bytes. Every round-3 assertion still runs unchanged; group 13 is new and covers the
round-4 surface: canned mode still answers on the spot (2 turns), live mode does not (1 turn, `who: "human"`),
a second thing said adds one turn rather than two, a `thread-turn` update auto-applies, lands in the thread it
names, carries its fold-readiness with it, queues nothing, and changes nothing at all when it names a thread
that does not exist.

Both script blocks in the page also pass `node --check` (80,063 and 59,931 bytes) — the page script cannot be
executed outside a browser.

The module stayed DOM-free and network-free. Every `fetch` in the file is outside the fence:

```
$ grep -nE 'fetch\(|bridgeURL' grilling-ui-prototype-r4.html
1746:function bridgeURL(p) { return BRIDGE.base + p; }
1749:  return fetch(bridgeURL(path), {
1780:  fetch(bridgeURL("/bridge/updates?since=" + BRIDGE.cursor)).then(function (r) {
```

(The fence closes at line 1696, above all three.)

### AC3 — the whole loop, headless, no browser

`/tmp/r4-loop-check.js` is a stand-in for the page: it extracts the **real** r4 module by the marker fence,
runs it under node, and does exactly what `dispatch()` and `bridgePoll()` do — posts the events the module
produces, polls updates back, and folds them in with the same `agentResponse` action and the same
`basedOnSeq` defaulting. There is no browser and no DOM anywhere in it.

```
$ python3 grill-bridge.py 8378 &
$ python3 fake-agent.py --exit-after 4 --timeout 40 &
$ node /tmp/r4-loop-check.js
events posted: 4   updates received: 4
R4 WIRE LOOP OK (informational, elicitative, conflict, thread reply — 5 groups, no browser)
EXIT=0
```

The agent's own view of the same exchange:

```
fake agent attached to http://127.0.0.1:8378 — polling for events
  board received: 16 decisions, plan: Design a nightly autonomous overnight-build pipeline: which
  <- answer         D1     -> informational
  <- answer         D5     -> revise
  <- answer         D7     -> elicit-alert
  <- thread-created D3     -> thread-turn
posted 4 updates; covered: conflict, elicitative, informational, thread-reply
```

What the stand-in asserts after the round trip, in the module's own state:

1. **Informational** — applied on arrival, readable on `D1`, exactly one informational notification.
2. **Elicitative** — the alert raised thread `T-live-D7` with `requiresAction`, `blockLock(S, "D7")` is
   `elicitation`, and answering D7 again returns the identical state (the lock holds).
3. **Conflict** — the revision of D5, stamped one step before the answer it replies to, is the only thing in
   the inbox, is flagged `conflicts`, locks D5, and has **not** modified D5's options.
4. **Thread reply** — the thread the user opened holds human-then-agent, and `foldReady` is true because the
   agent's turn carried an impact.
5. **The loop closes** — applying the conflicting change raises the conflict thread on D5.

### AC4 — the BRIDGE.md transcript is real

Every command in the transcript was run against a live bridge on 8378 and the output pasted verbatim. I then
replayed the whole transcript a second time and diffed it against the document line by line:

```
missing after fix: none — every replayed line appears verbatim
```

That check caught one prettified line: I had pasted an em-dash where the real response emits `\u2014`. The
document now carries the escape, as the wire does.

### AC5 — hygiene

**No external or CDN reference.** Every URL in `grilling-ui-prototype-r4.html` is 127.0.0.1, and there are
three, two of which are prose telling you how to start the bridge:

```
$ grep -nE 'https?://|//cdn|unpkg|jsdelivr|googleapis|<script[^>]+src=|<link[^>]+href=|@import' grilling-ui-prototype-r4.html
16:    open http://127.0.0.1:8378/grilling-ui-prototype-r4.html
1743:  base: (location.protocol === "http:" ? "" : "http://127.0.0.1:8378"),
2375:    '<code>http://127.0.0.1:8378/grilling-ui-prototype-r4.html</code>. BRIDGE.md is the wire protocol; '
```

Served over http the base is empty, so every bridge call is a same-origin relative path. The absolute
127.0.0.1 fallback exists only for a page opened from `file://`, where it would otherwise have no origin to
resolve against.

**Light theme only.** `grep -cE 'prefers-color-scheme|dark'` → `0`.

**Earlier rounds byte-identical.** Hashes taken before the build and verified after:

```
$ shasum -a 256 -c /tmp/r4-baseline-hashes.txt
grilling-ui-prototype.html: OK
grilling-ui-prototype-r2.html: OK
grilling-ui-prototype-r3.html: OK
REACTIONS.md: OK
BUILD-REPORT.md: OK
BUILD-REPORT-R2.md: OK
BUILD-REPORT-R3.md: OK
```

`git status --short` reports `?? ./` — this whole directory is untracked, so the hashes are the evidence, not
the diff. Nothing outside `docs/prototypes/grilling-ui/` was touched except `/tmp` scratch. No server is
running: both `grill-bridge.py` and `fake-agent.py` were killed before this report was written.

### Explicitly out of scope

**The r4 page has not been opened in a browser.** Browser-level verification is the orchestrator's, in
Chrome. What is proven here is that the module, the wire, the bridge and the agent driver form a working
loop headlessly, and that the page's two script blocks parse. What is *not* proven is that the page renders,
that the bridge panel reads well, or that the offline banner looks like anything. Do not read the greens
above as a claim that it looks right.

---

## Judgment calls

1. **Cursor, not destructive pop.** The brief says FIFO queues; the bridge is append-only with a read cursor
   held by the caller. Same ordering, but a re-poll is harmless, a page reload can replay from 0, and two
   readers never race for a message. It also makes the curl transcript reproducible, which AC4 needs.
2. **Both queues on one port, with the static files.** One process to start, one thing to kill, and the page
   is same-origin with its own bridge so there is no CORS story at all in the normal path. `Access-Control-Allow-Origin: *`
   is set anyway, for the case where someone opens the page from disk.
3. **Scenarios deleted rather than disabled.** They drove the canned agent, which no longer exists.
4. **The offline state is a banner, not a modal.** With no bridge the board stays fully usable — you can
   answer, thread, fold, and everything is recorded in the session log. What you do not get is a reply. That
   felt more honest than freezing the UI, but it does mean a user who never notices the banner will think the
   agent is merely slow.
5. **`fake-agent.py` covers the four shapes on fixed nodes** (D7 → elicitative, D5 → conflict, everything
   else → informational, any thread turn → reply) rather than reproducing r3's whole choreography. It is a
   test fixture and an example, not a replacement grilling agent.
6. **`render()` now no-ops before the DOM exists.** The bridge is polled from the moment the script runs and
   the shell markup is below it, so a fast reply could land before parsing finished. The state is folded
   either way; `DOMContentLoaded` draws it.

## What felt wrong in the model

1. **The event log was designed as a record and is now also a protocol.** R6 makes the interaction event log
   the session's source of truth — debugging data, mining material. Publishing it verbatim on the wire is
   what made this round small, but the two jobs will diverge: the moment an event needs a field only the
   agent cares about, the log starts carrying transport concerns. Worth deciding whether the wire format is
   the log or a projection of it before this stops being a prototype.

2. **The agent is told what happened, never what the board looks like.** After `ui-hello` it receives only
   deltas, so it has to fold the same state the UI does to know what D9's options currently say. For a
   canned driver that is fine. For a real agent it means either re-implementing the reducer or asking — and
   there is no ask. A `GET /bridge/snapshot` would fix it, but the bridge holds no state by design, so the
   snapshot would have to be pushed by the UI, which starts turning a mail slot into a session store.

3. **Threads are the part of the model most changed by a real agent, and the least examined.** Every round so
   far has had thread replies appear instantly, because they were generated in the same call stack. Now they
   take as long as the agent takes, and a thread is the one surface where the user is *waiting on a reply*
   rather than working around one. There is no typing indicator, no pending-turn placeholder, nothing. The
   thread just sits there with your message in it. That is the single thing I would look at first in Chrome.

4. **`basedOnSeq` puts a correctness-critical field in the agent's hands.** Conflict detection is the whole
   protection for a human decision, and it now depends on a remote party stamping a number honestly. The
   conservative default limits the damage of forgetting, but not of stamping the current seq to make an
   inconvenient conflict go away. A bridge that stamped arrival order itself would be more robust — at the
   cost of the bridge knowing something about grilling, which is the line this round drew.

5. **Nothing expresses "the agent is gone".** `BRIDGE.up === false` means the *bridge* is unreachable. A
   running bridge with nothing attached looks exactly like a healthy connection with a thoughtful agent, and
   the UI will wait forever. The bridge could expose a last-seen-agent timestamp cheaply; it does not.

## Left undone

- No browser run, per the brief (above).
- No long poll — the UI polls twice a second. Fine on localhost, visibly wasteful anywhere else.
- The bridge has no auth, no origin check beyond binding 127.0.0.1, and no size limit on a post. It is a
  throwaway on loopback; none of that is defensible for anything else.
- `Grill.agentPlan` and the whole canned choreography are still in the module, unused by the page. They are
  load-bearing for the self-check, so removing them would mean rewriting the round-3 assertions. Dead weight
  in the deployed sense, live weight in the test sense.
- `fake-agent.py` never sends `settle`, `unsettle`, `invalidate`, `resolve-stale` or `elicit-node`, so those
  five paths are documented and module-tested but have not crossed the wire. The `provisional` → `resolve-stale`
  round trip in particular is the one I would exercise next, because it is the only update kind that answers
  an event the *user* did not directly cause.
