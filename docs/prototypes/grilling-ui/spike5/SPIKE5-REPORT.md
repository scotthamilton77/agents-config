# Spike 5 — a backend that is its own agent harness

The question: can a standalone backend process own a grilling session end to end —
read a handoff file, drive real LLM agents over two mechanisms, stream a status
lane that never waits on a model, escalate between tiers mid-session, and survive
its own death?

**Yes, all five, measured.** The load-bearing numbers are the two ends of the
latency range: the status lane fires in **0–1 ms**, a fast-tier reply lands in
**~1 s**, a heavy-tier reply in **12–34 s**. Round 4's live agent took 20–90 s
with nothing on screen in between. That gap is the entire user-visible problem,
and it turns out to be free to close — the lane is transport, not judgement.

Total LLM spend for the whole spike: **~$0.70**.

---

## Verdicts

| Spike question | Verdict | The number that decides it |
|---|---|---|
| Handoff viable? | **Yes** | 25 KB file seeds a 16-decision board; after `session-start` it is never read again |
| API drive viable? | **Yes**, over OpenRouter (the only API path this environment opens) | 4 turns, 0.97–1.32 s, $0.0002–0.0008 each |
| CLI resume viable? | **Yes**, definitively | `--resume` retains context; 6.5 s standalone, 12–34 s under load |
| `upgrade_me` viable? | **Yes**, with a caveat | fired twice, both times correctly — but only after the escalation rule became a *criterion* |
| Restart-resume viable? | **Yes** | 4 restarts; log, images, answers and thread history all intact from disk alone |

---

## AC1 — self-test

```
$ python3 backend.py --self-test
  ok  seed appended session-start at seq 1
  ...
  ok  image2 carries per-decision history and image1 does not

SPIKE5 BACKEND SELF-TEST CLEAN — 32/32 checks passed
$ echo $?
0
```

32 checks over: event append and replay determinism (same log → byte-identical
images; images rebuilt from disk alone → byte-identical again), epoch and seq
assignment, idempotent duplicate handling, six distinct rejection receipts, and
the restart path (new epoch, continuing seq, preserved answers and history).

**The short-circuit guard is real and it fired.** The run counts executed checks
and compares against a constant; my first run miscounted and the suite failed
loudly at exit 1 rather than reporting a clean pass over 27 of 30 checks. An
early `return` cannot produce exit 0.

## AC2 — headless wire check: status before latency

`wirecheck.py` is the UI stand-in. Every line is stamped from the moment the
human turn was POSTed.

```
$ python3 wirecheck.py --node D1 --thread t1 --turn "I'm leaning toward option (a)..."
epoch=e-e5e068c0  cursor=1

T+0.000  POST human turn  cid=wire-1787089924877
T+0.002  receipt: {"cid": "...", "status": "accepted", "seq": 2, "epoch": "e-e5e068c0"}
T+0.002  [status] seq=3 phase=received  tier=None  turn accepted
T+0.002  [status] seq=4 phase=composing tier=fast  fast tier composing
T+1.288  [REPLY]  seq=5 tier=fast model=google/gemini-2.5-flash latency=1.09s cost=0.0002958
           How does freezing the list at launch impact the pipeline's ability to
           address urgent issues or newly identified high-priority work items?
T+1.288  [status] seq=6 phase=done tier=fast
```

Measured from the log's own timestamps, across all six turns of the session:

| Leg | Range |
|---|---|
| turn accepted → status emitted | **0.0–1.0 ms** |
| status `composing` → fast-tier reply | **0.97–1.32 s** |
| status `composing` → heavy-tier reply | **13.45 s** and **34.46 s** |

Three to four orders of magnitude. The lane is emitted synchronously inside the
same lock as the accept, before one byte leaves the process — so it is not
"usually fast", it is *structurally* incapable of waiting on a model.

The strongest evidence for that is an accident. The very first live run was still
pointed at the Anthropic API, which this environment deliberately keeps closed
(see the standing constraint below), and the transcript reads:

```
T+0.002  [status] seq=3 phase=received  turn accepted
T+0.003  [status] seq=4 phase=composing tier=fast
T+0.003  [status] seq=5 phase=error     RuntimeError: ANTHROPIC_API_KEY is not set
```

A total agent failure surfaced as a status event in 3 ms instead of an infinite
silent wait. That is W4 and L1 answered at the same time.

### Uniform receipts, idempotency and epoch, on the live wire

```
$ curl -sX POST .../session/events -d '{"epoch":"e-cb4e3f17","events":[{"cid":"dup-demo","kind":"note","nodeId":"D3","text":"first"}]}'
{"receipts": [{"cid": "dup-demo", "status": "accepted", "seq": 44, ...}]}

$ # same cid again, different body
{"receipts": [{"cid": "dup-demo", "status": "duplicate", "seq": 44, "reason": "already applied at seq 44"}]}

$ # unknown kind, unknown node
{"receipts": [{"cid": "r1", "status": "rejected", "reason": "unknown kind: 'detonate'"},
              {"cid": "r2", "status": "rejected", "reason": "unknown nodeId: 'D99'"}]}

$ # stale epoch
{"receipts": [{"cid": "r3", "status": "rejected", "reason": "epoch mismatch",
               "server_epoch": "e-cb4e3f17", "sent_epoch": "e-stale00"}]}

$ curl -s -o /dev/null -w "%{http_code}" ".../session/updates?since=0&epoch=e-stale00"
409
```

Round 4's `ok/accepted` on a silent no-op (W6) is gone: every event gets a typed
receipt, and a rejection names its reason.

## AC3 — `upgrade_me`, for real

```
T+0.000  POST human turn  cid=wire-1787089967679
T+0.003  [status] seq=14 phase=received
T+0.003  [status] seq=15 phase=composing tier=fast
T+1.027  [tool ] seq=16 tier=fast tool=upgrade_me (fast-tier latency 0.99s)
           reason: The human has already rejected a reframing of the question, and
           states that the trade-off itself is what they cannot resolve.
           Additionally, they state that the decision impacts three other decisions.
T+1.027  [status] seq=17 phase=upgrading tier=heavy
T+34.529 [REPLY] seq=18 tier=heavy model=cli:sonnet latency=33.46s cost=0.5759898
           **Commit: (a).** The principle isn't "does the pipeline look stuck" —
           it's "did it produce a falsifiable artifact of progress before it stopped."
```

Both attributions are in the log: seq 16 `src=agent tier=fast
model=google/gemini-2.5-flash`, seq 18 `src=agent tier=heavy model=cli:sonnet
upgraded_from=fast`. The re-dispatch carried the accumulated thread, not just the
last message.

**The caveat, and it is the most transferable finding here.** The first attempt
did not escalate. My system prompt said to escalate "when the question turns on
judgement you cannot supply at your weight" and warned that escalation is not
free. Faced with a question the human had *explicitly* said they could not
resolve, the fast tier answered anyway — with a reframing the human had already
rejected. A fast model asked to judge its own competence judges it generously.

Replacing the vibe with three checkable conditions — the human asked me to
*commit* rather than ask; the human has rejected a reframing; three or more
decisions are in play — made it escalate on the next turn, and its stated reason
quoted the conditions back. **Tier policy has to be a criterion the model can
evaluate against the transcript, not a self-assessment of ability.**

## AC4 — the CLI question, answered

`claude -p --resume <session_id>` **works as a turn mechanism.** Context is
retained and the session id is stable.

```
$ SID=4a44e380-d0da-4b47-b4e8-ed62e83dcd9e
$ echo "Remember this codeword: PELICAN-7. Reply with just: noted." \
    | claude -p --session-id "$SID" --model haiku --output-format json
  → exit 0, result "noted.", 6.41 s wall

$ echo "What was the codeword I gave you? Reply with just the codeword." \
    | claude -p --resume "$SID" --model haiku --output-format json
  → exit 0, result "PELICAN-7", 6.55 s wall, session_id unchanged
```

Three things worth carrying forward:

1. **The prompt must come from stdin whenever a variadic flag is on the line.**
   `--disallowedTools <tools...>` swallows the positional prompt and the CLI dies
   with `Input must be provided either through stdin or as a prompt argument`.
   This cost the first run.
2. **Cost is front-loaded, heavily.** Turn 1 wrote 32,369 cache-creation tokens
   (the harness system prompt and CLAUDE.md) for $0.065; turn 2 read the same 32k
   from cache for $0.0044. Inside the backend the same shape appeared at sonnet
   weight: first heavy turn **$0.576 / 33.5 s**, second **$0.054 / 12.2 s** — a
   10× cost drop and a 2.7× speedup purely from resuming.
3. **Therefore the cache TTL is an architectural constraint, not a billing
   detail.** A griller session held open across a slow human's thinking pays the
   session-open tax again when the 5m/1h cache lapses. "One process per session"
   is the right call, and it now has a number attached: roughly half a dollar per
   cold heavy-tier session.

The backend strips `ANTHROPIC_API_KEY` from the CLI subprocess environment
(mirroring the user's own shell function), so heavy-tier turns bill the
subscription rather than silently moving onto an API meter. This is the intended
routing for every Claude-model turn here, not a workaround — see the standing
environment constraint below.

## AC5 — restart-resume

Pre-kill, mid-flight, 26 events with D1 settled and two live threads:

```
$ pgrep -f "backend.py --session /tmp/spike5-sess"   → 25252
$ wc -l < log.jsonl                                  → 26
$ md5 -q log.jsonl                                   → 83576b8a543e9b5109b337bc1d09eb1f
$ curl -s .../session/state
  epoch e-b8d31eb4  seq 26  settled ['D1']  frontier ['D2','D3','D4']

$ kill -9 25252
$ pgrep -f "backend.py --session /tmp/spike5-sess"   → no backend process
$ curl -s -m 3 .../session/state                     → connection refused
```

**(i) the log and images are intact** — after the kill, `log.jsonl` is still 26
lines at md5 `83576b8a...`, and `image1.json` / `image2.json` are still on disk.

**(ii) a reload gets the current board** — restart, then ask:

```
$ python3 backend.py --session /tmp/spike5-sess --port 8379
session /tmp/spike5-sess  epoch e-1d3f88e3  seq 27

epoch  : e-1d3f88e3   <- NEW epoch, new process
seq    : 27           <- CONTINUED, not reset to 0
settled: ['D1']
D1     : A snapshot query against the tracker taken at launch, frozen for the night.
threads: {'t1': 2, 't2': 4, 'auto-D1': 1}
```

New epoch on a continuing sequence is the pairing that kills W1/W2: the epoch
says *which process you are talking to*, the seq says *where you are in a log
that outlives every process*. A page holding the old epoch is told so — 409 on
read, `epoch mismatch` receipt on write — instead of silently carrying a stale
board forward.

**(iii) the post-restart turn carries pre-restart context.** The backend logs
every prompt it dispatches, so this is checkable rather than assertable. The
heavy dispatch at seq 34 — after the restart at seq 27 — contains, verbatim:

```
THREAD t2 SO FAR:
  human: Here is the thing I actually can't resolve. Option (a) says only wake me for
  decisions the pipeline isn't authorised to make. ...
  agent: The core issue is trust in the pipeline's judgment. ... What verifiable signal
  can the pipeline emit that proves it has made a decision to park ...
  human: You just asked me another question instead of answering. Stop. ...
  agent: **Commit: (a).** The principle isn't "does the pipeline look stuck" — it's
  "did it produce a falsifiable artifact of progress before it stopped." ...
```

Every one of those turns is from seq 10–18, i.e. before the restart. The agent
was not resumed from process memory — it was reconstituted from image 2, which
was itself regenerated from the log. The heavy tier then answered *about* that
history: "**Commit: (a), unchanged.** The falsifiable-artifact principle needs a
fixed baseline to diff against…".

## AC6 — rounds 1–4 untouched

The prototype tree is **untracked** in git (`?? docs/prototypes/grilling-ui/`),
so `git diff` cannot be the baseline. The available proof is size plus mtime,
against the directory listing taken before I created anything:

Every one of the 13 round-1..4 files has the byte size it had in that first
listing, and the newest mtime among them is `2026-08-18T16:16:20`
(`REACTIONS.md`), while `spike5/` was created at `2026-08-18T17:46:22`. Nothing
in the tree was written during this run. Everything I produced is inside
`spike5/`, plus scratch under `/tmp`.

---

## What the architecture answers

| Round-4 finding | How round 5 answers it |
|---|---|
| **W1** hello re-asserts the initial board, indistinguishable from a reset | The page no longer publishes a board. It GETs `/session/state`. A reconnect cannot assert anything. |
| **W2** envelope seq and body seq diverge; `basedOnSeq` ambiguous | One server-assigned seq on every entry, agent and UI alike. The page's own seq travels as `clientSeq` data, and receipts give it a join back. |
| **W3/W7** reconnect re-processes backlog; no dedupe anywhere | Per-event idempotency key, deduped server-side; the cursor resumes from `/session/state`. Demonstrated live. |
| **W4** bridge-reachable and agent-present indistinguishable | Two separate indicators, fed by a status lane that fires in 0–1 ms. |
| **W5** agent must reconstruct state from deltas | Agents never see deltas. They see image 2, projected from the log. |
| **W6** acceptance says nothing about honouring; silent no-ops | Uniform typed receipts including rejections, with reasons. |
| **L1** acknowledgment, working animation, incrementing timer | The lane, plus a page chip with a 1 s ticker. |
| **L3** task-appropriate models with explicit escalation | Two tiers and `upgrade_me`, exercised. |

## What felt wrong

- **The context image is a lossy projection and it lost something real.** My
  first version trimmed settled decisions out of the prompt to save tokens, and
  the post-restart heavy dispatch went out *without D1's answer in it* — the
  decision the human had just settled. It produced a correct reply only because
  the human's own message happened to mention D1. Fixed (settled answers now ship
  as a compact `ALREADY SETTLED:` block, verified present in the next dispatch),
  but the general hazard stands: **the projection is where a server-authoritative
  design silently loses context, and nothing downstream can detect the loss.**
  Image 2 needs a completeness contract, not just a size budget.
- **A projection bug takes the whole session down at write time, not read time.**
  An agent reply to an answered decision belongs to no thread, so it projected
  under a `None` key and `json.dump(sort_keys=True)` raised — *after* the entry
  was already durably appended. The log was fine; the images were stale; the
  session looked broken. Root-caused to one derivation (`auto_thread`) now shared
  by the accept path, the driver and the projector, with a regression check. The
  general lesson: **append and project must not fail together, and the projector
  must tolerate any log the appender accepted.**
- **The status lane makes it very easy to ship an agent that never speaks.** With
  `received → composing` on screen instantly, a silent 34-second heavy turn feels
  fine. That is the feature, but it also removes the pressure that would
  otherwise force the reply to be fast.
- **`--no-llm` exists and nothing forces you off it.** A backend that mints no
  agents serves a board that looks completely healthy.

## Deliberately not done

- **The page is not browser-verified.** Out of scope for me per the brief; the
  orchestrator drives it in Chrome. What I did verify: it is served (HTTP 200,
  172,422 bytes), its JavaScript parses (`node --check`), and the pure state
  module's own 
  self-check still passes unchanged (`grilling r4 state module self-check: OK`).
  The repoint touched the wire layer only — the reducer, inbox, locks,
  notifications, bubbles and threads are round 3, untouched. **Everything about
  its rendering, including whether the status chip and the epoch re-hydration
  behave on screen, is unverified.**
- No multi-session or multi-tenant work (L8): one process, one session directory.
- No `revise` / `invalidate` / `resolve-stale` from the agent side. The tool
  surface is `respond` and `upgrade_me`, which is what the spike questions needed.
- The heavy tier is `sonnet` via CLI, not opus — it keeps mechanism (b) inside the
  escalation path and keeps the bill honest.

## Files

```
spike5/
  HANDOFF.md                    the handoff format, v1
  handoff.json                  a real instance: the canned 16-decision plan
  backend.py                    the backend; --self-test is the gate
  wirecheck.py                  headless UI stand-in, timestamped
  grilling-ui-prototype-r5.html r4 repointed at the backend (not browser-verified)
  SPIKE5-REPORT.md              this file
```

Run it:

```
python3 backend.py --self-test
python3 backend.py --session /tmp/grill-a --handoff handoff.json
open http://127.0.0.1:8379/grilling-ui-prototype-r5.html
```

## Spend

| | |
|---|---|
| fast tier, 4 turns (OpenRouter, gemini-2.5-flash) | $0.0020 |
| heavy tier, 2 turns (claude CLI, sonnet) | $0.6301 |
| CLI resume probe (haiku, 2 turns) | $0.0695 |
| model capability probes | $0.0003 |
| **total** | **~$0.70** |

`google/gemini-2.5-flash` was chosen after probing three candidates: `gpt-4o-mini`
also emitted correct tool calls; `z-ai/glm-4.6` returned prose under forced tool
choice and was rejected.

## Standing environment constraint: the empty `ANTHROPIC_API_KEY`

`ANTHROPIC_API_KEY` is exported **with an empty value, deliberately.** A populated
key would override the Anthropic subscription and bill per token, so the empty
export is the mechanism that keeps Claude-model turns on the subscription. It is
not a misconfiguration and must not be populated.

The routing this forces is the routing this spike landed on, and it should be
treated as the house shape rather than a workaround:

- **The direct Anthropic API path is intentionally unavailable.** Do not design
  against it.
- **Claude-model turns bill the subscription via the `claude` CLI.** That is why
  the heavy tier here is `claude -p --resume` rather than an API call, and why
  `backend.py` explicitly strips the variable from the CLI subprocess environment
  — an empty value inherited into the CLI is fine, but the strip makes the
  intent legible and survives someone setting a real key later.
- **Non-Claude models route via OpenRouter.** That is the fast tier.

One operational note for anyone probing an environment this way: `env` lists an
empty export, so a presence grep reports the key as present. A credential check
has to test the value, not the name. My first pass got this wrong and the backend
caught it — see the AC2 transcript, where the miss surfaced as a status event in
3 ms rather than a hang.

---

# Fix round — the real UI path

Browser verification found what the headless check could not: **a user opening a
thread never reached the backend.** Root cause turned out to be larger than the
symptom, and the enlargement is the interesting part.

## Root cause: the backend was written against wirecheck's shape, not the page's

The reported defect was that `thread-created` is missing from `UI_KINDS`, so the
page's thread-open event is rejected. True, and fixed. But grepping the four
emission sites showed the page carries its content in **`turns[]`, always** —
and so does its `thread-turn`:

```js
return [{ kind: "thread-created", threadId: nid2, nodeId: a.id, tkind: "user", ..., turns: turns2 }];
return [{ kind: "thread-turn",    threadId: a.id, nodeId: t2.anchor,          turns: [hf], ... }];
```

The backend validated `ev.get("text","").strip()` and rejected anything without
it. So `thread-turn` from the real page was broken too — invisible only because
you cannot reach a thread turn without first opening a thread. Adding
`thread-created` to the accepted set alone would have moved the failure one step
later and left the page equally dead.

**AC2 passed while the real path was broken because `wirecheck.py` posted a shape
I invented.** A scripted stand-in that speaks its author's dialect tests the
author's assumptions, not the contract.

The fix is one reader, used by the accept path, the projector and the driver:

```python
def turns_of(e):
    if e.get("turns"):
        return [(t.get("who") or "human", t.get("text") or "") for t in e["turns"]]
    return [("agent" if e.get("src") == "agent" else "human", e.get("text") or "")]
```

`thread-created` and `thread-turn` now project through the same branch;
`thread-created` additionally records `tkind`, `title` and `requiresAction`.

**Answerability is separate from acceptance.** The page also opens
agent-authored threads (a `tkind: "mandate"` thread whose only turn is the
agent's). Those are recorded and left alone — the lane fires only when a human
turn is present, so the backend never answers itself.

## The machine-catch: read the vocabulary off the page

A fixture I hand-write drifts, and drifting was the whole failure. The self-test
now reads the emitted kinds out of `grilling-ui-prototype-r5.html` itself:

```python
emitted = set(re.findall(r'\{\s*kind:\s*"([a-z-]+)"\s*,\s*(?:nodeId|threadId|nodeIds)\b', module))
unknown = emitted - UI_KINDS - IGNORED_UI_KINDS - AGENT_KINDS
```

Scoped to event objects on purpose — it skips the shell's panel kinds and `tkind`
values, trading recall for a check that never cries wolf. Alongside it are five
shape checks driving the page's real `turns[]` form, plus the mandate case.

**Mutation-checked.** Reverting only the `UI_KINDS` line turns the suite red on
exactly the reported defect:

```
$ # UI_KINDS without "thread-created"
$ python3 backend.py --self-test ; echo $?
AssertionError: FAILED every kind the page emits is known to the backend ['thread-created']
1
$ # restored
SPIKE5 BACKEND SELF-TEST CLEAN — 41/41 checks passed
0
```

## Rejections are now visible

The page counted rejections and rendered nothing — the W6 silent no-op wearing a
receipt. A rejected human action now raises a banner naming the reason and saying
plainly that the message is not recorded and no agent will answer it, with a
dismiss button. `SERVER.lastRejection` holds it; `dismiss-rejection` clears it.

## Evidence: the real shapes, live

`wirecheck.py --as-page` posts what the page posts.

```
$ SPIKE5_BASE=http://127.0.0.1:8380 python3 wirecheck.py --as-page --node D2 --thread D2-t1 --turn "..."
T+0.000  POST human turn  cid=wire-1787091291285  kind=thread-created
T+0.002  receipt: {"cid": "...", "status": "accepted", "seq": 2, "epoch": "e-e4925000"}
T+0.003  [status] seq=3 phase=received
T+0.003  [status] seq=4 phase=composing tier=fast
T+1.034  [REPLY]  seq=6 tier=fast model=google/gemini-2.5-flash latency=1.02s cost=0.000345
           You are describing the "who decides" as an important constraint. What is the
           impact of either an individual or a team deciding authorization limits?
```

Page-shaped `thread-turn` (no `text` field) and the mandate case, by hand:

```
$ curl ... '{"kind":"thread-turn","threadId":"D2-t1","turns":[{"who":"human","text":"The repo owner decides..."}]}'
{"receipts": [{"cid": "pt1", "status": "accepted", "seq": 8, ...}]}

$ curl ... '{"kind":"thread-created","threadId":"D12-m","tkind":"mandate","turns":[{"who":"agent","text":"Your selection is held..."}]}'
{"receipts": [{"cid": "mand1", "status": "accepted", "seq": 12, ...}]}
```

Resulting log — note seq 12 produced **no** status lane, because no human is owed
a reply, while seq 2 and seq 8 both did:

```
 1 server session-start        8 ui     thread-turn
 2 ui     thread-created user   9 server agent-status received
 3 server agent-status received 10 server agent-status composing
 4 server agent-status composing 11 server dispatch     fast
 5 server dispatch     fast     12 ui     thread-created mandate
 6 agent  thread-turn  fast     13 agent  thread-turn  fast
 7 server agent-status done     14 server agent-status done
```

Projection:

```
D12-m  tkind=mandate  turns=[('agent', 'Your selection is held, not applied.')]
D2-t1  tkind=user     turns=[('human', 'Opening a thread the way the real UI does...'),
                             ('agent', 'You are describing the "who decides"...'),
                             ('human', 'The repo owner decides, at design time...'),
                             ('agent', "You've specified \"who\" and \"when\"...")]
```

## Fix-round status

- Self-test **41/41, exit 0** (was 32).
- Page JavaScript parses (`node --check`); the r4 state module is untouched.
- Rounds 1–4 still byte-identical: sizes unchanged, newest mtime
  `2026-08-18T16:16:20`, before `spike5/` existed.
- Browser re-verification remains the orchestrator's. The rejection banner in
  particular has never been rendered — I can show it is constructed and wired to
  a dismiss action, not that it looks right.
