# The grilling-UI bridge — wire protocol

How the round-4 prototype page and a grilling agent talk to each other. This is
everything an agent with only Bash and `curl` needs in order to play the agent
side correctly.

The bridge (`grill-bridge.py`) is a **mail slot with no opinions**: two
append-only queues, a read cursor each, static file service for this directory,
and no grilling semantics anywhere. Every decision about what an update *does* —
whether it applies itself, whether it waits in the inbox, whether it locks a
decision — is made by the page when the update arrives, not by the bridge and
not by the agent.

```
python3 grill-bridge.py            # 127.0.0.1:8378, Ctrl-C to stop
python3 grill-bridge.py 9001       # another port
python3 grill-bridge.py --self-test
```

Nothing persists. The queues live in process memory and die with the process.

---

## Endpoints

| Method | Path | Who calls it | What it does |
|--------|------|--------------|--------------|
| `POST` | `/bridge/events` | the UI | append user events |
| `GET` | `/bridge/events?since=N` | the agent | read user events from cursor `N` |
| `POST` | `/bridge/updates` | the agent | append structured updates |
| `GET` | `/bridge/updates?since=N` | the UI | read updates from cursor `N` |
| `GET` | `/bridge/status` | anyone | `{"events": n, "updates": m}` |
| `POST` | `/bridge/reset` | anyone | empty both queues |
| `GET` | anything else | a browser | static file out of this directory |

**Posting.** The body may be `{"events": [...]}`, `{"updates": [...]}`, a bare
JSON array, or a single object. All four are the same thing; the wrapper key is
ignored. An empty post is a `400` rather than a silent no-op. The reply is
`{"ok": true, "accepted": n, "next": cursor}`.

**Reading.** `?since=N` returns everything after cursor `N`, newest last:

```json
{"ok": true, "since": 0, "next": 3, "items": [{"seq": 1, "body": {…}}, …]}
```

Read is non-destructive — the cursor lives in the caller, so a re-read is
harmless and two readers never race for a message. Poll `?since=<the last
"next" you saw>`. There is no long poll; poll every few hundred milliseconds.

---

## What the UI sends (events)

Every event is one entry from the session's own event log — the same objects the
prototype folds its state from, published verbatim. An agent does not have to
understand all of them; it has to understand the ones it answers.

Every event carries `kind`, usually `nodeId`, a human-readable `label`, and
**`seq`** — its position in the session log. `seq` is the number you stamp your
reply with (see `basedOnSeq` below).

### The ones an agent answers

| `kind` | Carries | Means |
|--------|---------|-------|
| `ui-hello` | `plan`, `seq`, `nodes[]` | The page connected. `nodes[]` is the whole board: `id`, `short`, `title`, `question`, `prereqs`, `status`, `answer`, `options[]`. Sent once per page load — **read this first**, it is the only place the questions and option texts appear. |
| `answer` | `nodeId`, `answer`, `source` | A decision was answered or changed. `answer` is `{"free": false, "optionId": "a"}` or `{"free": true, "text": "…"}`. Only act on `source: "user"` — `"agent"` is your own `settle` coming back. |
| `thread-created` | `threadId`, `nodeId`, `turns[]`, `title` | A thread was opened by the user saying something in it. The last turn is theirs and is waiting for you. |
| `thread-turn` | `threadId`, `nodeId`, `turns[]` | Something more was said in an existing thread. If `turns[turns.length-1].who === "human"`, you are being spoken to. |
| `provisional` | `nodeIds[]`, `because` | An answer changed and the decisions below it are marked "the agent is reassessing this". They stay that way until you send a `resolve-stale`. |

### The rest, for context

`answer-held` and `answer-release` (a mandated thread holding a selection),
`answer-abandoned`, `queued` / `applied` / `dismissed` (what happened to one of
your updates), `conflict-raised` / `conflict-resolved`, `thread-open`,
`thread-park`, `thread-fold`, `thread-dismissed`, `thread-abandoned`,
`note-read`, `auto-pref`, `banner`.

`applied` and `dismissed` are your receipts: `dismissed` means the user argued
you out of a change and you should not resend it.

---

## What the agent sends (updates)

This is the entire taxonomy the page consumes. There is no other kind; an
unknown `kind` is silently dropped.

Every update needs a **unique `id`**, almost always a **`nodeId`**, a one-line
**`summary`** (this is the text the user sees in the inbox and in the
notification), and **`basedOnSeq`**.

### `basedOnSeq` — the one field that is easy to get wrong

Set it to the `seq` of the event you are replying to. It says *"this was written
against the board as it stood at step N"*. The page compares it against the log:
if the user has answered that decision since, your update is a **conflict** and
goes to the inbox instead of landing.

Omitting it is not neutral — the page reads a missing `basedOnSeq` as `0`,
meaning "based on nothing", so anything touching an answered decision will
conflict. Stamp it.

### The kinds

| `kind` | Extra fields | What it does | Waits for permission? |
|--------|--------------|--------------|-----------------------|
| `informational` | `text`, optional `recommendNext` | Leaves a note on the decision — an unread ✉ on its card and a bubble in the corner. Changes nothing. | **Never.** Applies even with auto-apply switched off. Do not send an information-free acknowledgement; a note with nothing in it is a task you handed the user for no reason. |
| `elicit-node` / `add-node` | — | Materialises a new decision. `nodeId` must be one the board knows how to add: **`D17`** (the cost of a live re-query, hanging off `D1`) or **`D18`** (what "blocked" means, hanging off `D2`). Any other id does nothing at all. | No — a new question undermines nothing. |
| `revise` | `options[]` | Replaces a decision's option list. Each option is `{"id", "text", "pcr": [buys, costs, forces]}`; `options[0]` is the recommendation, and `pcr` is the three-line hover card. | Only if the decision is **unanswered**. Otherwise it waits in the inbox and locks the decision. |
| `settle` | `text` | Answers a decision on the user's behalf, marked as decided by the agent. | Only if unanswered. |
| `unsettle` | — | Marks an answered decision as needing re-confirming. | **Always waits.** It undermines a human decision. |
| `invalidate` | — | Takes a decision out of the flow (it stays on the board for relitigation). | **Always waits**, and locks the node until the user lets it land or argues it away. |
| `resolve-stale` | `resolutions[]` | Adjudicates the `provisional` set: `[{"nodeId": "D9", "verdict": "confirmed"}, {"nodeId": "D11", "verdict": "cleared"}]`. `confirmed` marks it stale, `cleared` releases it. `nodeId` on the update is the decision that changed. | No. |
| `elicit-alert` | `threadId`, `title`, `turns[]`, `requiresAction` | Raises a thread on a decision. `requiresAction: true` **blocks that decision** until the thread concludes or is dismissed, and renders at the top of its block. `false` is a suggested thread, which stays out of the notification list while its node is blocked. | No — an alert is raised as early as possible. |
| `thread-turn` | `threadId`, `turns[]`, optional `retitle` | You, speaking in a thread that already exists. `threadId` must name a live thread; naming one that does not exist does nothing. | No — talking is not deciding. |

### Turns

A turn is `{"who": "agent", "text": "…"}` plus, optionally:

- **`impact`** — `{"summary", "detail", "updates": [...]}`. This is what makes a
  thread *foldable*: until one of your turns carries an `impact`, the Fold
  button is disabled. `updates` is a list in this same taxonomy, applied when
  the user folds — routed by the same rules, so an impact touching an answered
  decision still waits in the inbox.
- **`disruptive: true`** — the fold applies immediately and synchronously rather
  than through the inbox. For rewrites that move the whole board at once.
- **`ask`** — a question rendered as decision options rather than prose:
  `{"prompt": "…", "options": [{"id", "text", "rec": true, "pcr": […]}]}`.

---

## A worked exchange

Run against a live bridge. This is the actual transcript, not an illustration.

```
$ curl -s http://127.0.0.1:8378/bridge/reset -X POST -d "{}"
{"ok": true, "reset": true}

$ curl -s http://127.0.0.1:8378/bridge/status
{"ok": true, "events": 0, "updates": 0}
```

The UI answers a decision. (The page does this itself; here it is by hand.)

```
$ curl -s http://127.0.0.1:8378/bridge/events -H "Content-Type: application/json" -d '{"events": [{"kind": "answer", "nodeId": "D1", "seq": 1, "source": "user", "answer": {"free": false, "optionId": "a"}, "label": "answered — A snapshot query against the tracker taken at launch."}]}'
{"ok": true, "accepted": 1, "next": 1}
```

The agent picks it up. This is the poll to sit in a loop on.

```
$ curl -s "http://127.0.0.1:8378/bridge/events?since=0"
{"ok": true, "since": 0, "next": 1, "items": [{"seq": 1, "body": {"kind": "answer", "nodeId": "D1", "seq": 1, "source": "user", "answer": {"free": false, "optionId": "a"}, "label": "answered \u2014 A snapshot query against the tracker taken at launch."}}]}
```

The agent answers it. Note `basedOnSeq: 1` — the `seq` of the event above.

```
$ curl -s http://127.0.0.1:8378/bridge/updates -H "Content-Type: application/json" -d '{"updates": [{"kind": "informational", "id": "W1-i", "nodeId": "D1", "basedOnSeq": 1, "recommendNext": "D3", "summary": "Informational: a consequence of freezing the queue.", "text": "Recorded: anything filed after the run starts waits for tomorrow night."}]}'
{"ok": true, "accepted": 1, "next": 1}
```

The UI collects it, and the second poll shows the cursor has moved.

```
$ curl -s "http://127.0.0.1:8378/bridge/updates?since=0"
{"ok": true, "since": 0, "next": 1, "items": [{"seq": 1, "body": {"kind": "informational", "id": "W1-i", "nodeId": "D1", "basedOnSeq": 1, "recommendNext": "D3", "summary": "Informational: a consequence of freezing the queue.", "text": "Recorded: anything filed after the run starts waits for tomorrow night."}}]}

$ curl -s "http://127.0.0.1:8378/bridge/updates?since=1"
{"ok": true, "since": 1, "next": 1, "items": []}

$ curl -s http://127.0.0.1:8378/bridge/status
{"ok": true, "events": 1, "updates": 1}
```

The page comes off the same port, and a post with nothing in it is refused.

```
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8378/grilling-ui-prototype-r4.html
200

$ curl -s -w " HTTP %{http_code}\n" http://127.0.0.1:8378/bridge/events -d '{"events": []}'
{"ok": false, "error": "nothing to post"} HTTP 400
```

---

## Playing the agent well

- **Read `ui-hello` before saying anything.** It is the only message carrying the
  questions and the option texts; everything after it is a delta.
- **Stamp `basedOnSeq` from the event you are answering.** Conflict detection is
  the whole safety mechanism and it runs on that number.
- **Answer at human latency, not instantly.** A second or three. Instant replies
  make the surface feel synchronous, which is the thing this design is not.
- **Prefer the kinds that do not interrupt.** `informational`, `elicit-node`,
  `elicit-alert` and `revise`-on-an-unanswered-node all land by themselves.
  `unsettle` and `invalidate` stop the user until they deal with you — worth it
  for an invalidation, never worth it for something small.
- **A `dismissed` receipt is an answer.** The user argued and won. Do not resend.
- **You cannot open a thread by posting a `thread-turn`** — the thread has to
  exist first, either because the user opened it or because you sent an
  `elicit-alert` that created it.

`fake-agent.py` in this directory is a working example of all of the above:
poll, react, post, covering an informational note, an elicitative alert, a
deliberately conflicting revision, and a thread reply.
