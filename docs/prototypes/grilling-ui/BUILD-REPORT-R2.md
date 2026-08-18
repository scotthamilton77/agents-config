# Grilling-UI prototype, round 2 — build report

Deliverable: `/Users/scott/src/projects/agents-config/docs/prototypes/grilling-ui/grilling-ui-prototype-r2.html`
(one file, 1891 lines, 111 KB, no frameworks, no CDN, no network calls, light theme only, hash-free URL).

Round 1 asked which surface. This one asks whether the conversation model works: a fake but genuinely
asynchronous agent whose replies arrive seconds late as structured updates, queue in a mailbox, and change
nothing until they are applied.

## The state module's public surface

- `initial()` / `reduce(state, action)` — the log is the state; `reduce` appends events and refolds the whole thing.
- Actions: `answer`, `applyPending`, `agentResponse`, `seen`, `newThread`, `openThread`, `threadSeed`, `threadSay`, `parkThread`, `foldThread`, `relitigate`, `reset`.
- `agentPlan(state, events)` — the choreography: what the agent sends back for the events just added, and after how long. The page owns only the clock.
- `statusOf(s, id)` — `settled` | `open` | `blocked` | `stale` | `stale-blocked` | `fogged` | `reassessing` | `conflicted` | `conflict-blocked` | `awaiting-thread` | `invalidated`.
- `frontier(s)`, `nextFocus(s, justSettled)` — what is answerable, and what to focus after a settle.
- `columnOrder(s)` — tree order for the column; a function of prerequisite depth only, so it cannot re-sort as a side-effect.
- `nodeView(s, id)` — one node with status, fog, answer, threads, unread mail and conflict resolved.
- `pending(s)` — mailbox entries, each already flagged with whether it conflicts.
- `notifications(s)` — the typed inbox, with suggested threads suppressed while their node is blocked.
- `historyOf(s, id)` — that node's slice of the one session log.
- `layers`, `counts`, `answerText`, `threadsOf`, `isSettled`, `isFogged`, `depthOf` — selectors.

Shape note: an in-memory event log with state folded from it was the suggested fit and it held. Per-node
history is `events.filter(touches this node)` and the raw session log is the same array — there is no second
bookkeeping structure to keep in step. One update-applier serves both the mailbox and the synchronous fold.

## Evidence per acceptance criterion

**AC1 — the node self-check runs green.** Exact command, run from the repository root:

```
node -e "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const p=s.split('//---GRILL-MODULE-START---');if(p.length!==2)throw new Error('marker collision: '+p.length);const m=p[1].split('//---GRILL-MODULE-END---')[0];if(m.length<5000)throw new Error('slice too small: '+m.length);fs.writeFileSync('/tmp/grill-r2-module.js',m);" \
  docs/prototypes/grilling-ui/grilling-ui-prototype-r2.html && node /tmp/grill-r2-module.js; echo "EXIT=$?"
```

```
grilling r2 state module self-check: OK (16 base decisions, 2 agent-addable, 22 events in the last session)
EXIT=0
```

Both guards from round 1 are kept — the marker count must be exactly two, and the slice must exceed 5000
bytes — because round 1's first extractor sliced a valid 13-byte fragment and exited 0 with no output. The
self-check still prints on success, so an empty run cannot pass for a green one.

Asserts cover the six required cases and four more: an already-answered downstream decision is
`conflict-blocked` by an upstream conflict and cannot be answered; queued updates leave `state.nodes`
byte-identical until applied; provisional staleness stays provisional until the agent's response is applied,
which confirms the direct dependent and clears the deeper one; a fold's declared impact is queued to the
mailbox and lands only on apply; the same thread is parked (nodes byte-identical), reopened, given another
turn and folded; a mandated thread holds the answer, survives a park without settling, and settles the
decision only on conclusion. Plus: fog lifts when its gating decision settles; a disruptive fold applies
without touching the mailbox; an invalidated node leaves the flow, stays in `order`, and stops blocking its
dependents; the agent materialises a new decision; per-node history is a strict subset of the session log.

**AC2 — coverage of every identifier in REACTIONS.md.**

| ID | How this build satisfies it |
|----|------------------------------|
| A1 | Expanding a settled item renders the full answer UI (options + free text) with `Currently:` above it. Reopen and answer are one operation — `answer` on a settled node is the reopen. |
| A2 | `nextFocus` runs after every settle and moves the column and map focus; no map click is needed to continue. |
| A3 | The focused decision's textarea takes keyboard focus on every focus change, and re-takes it whenever nothing else holds it. Drafts and caret position survive the re-render an agent update triggers mid-typing (verified: text, caret at 6, and focus all intact after a reply landed). The only global key handler is Escape, and it returns early inside a text field. |
| A4 | Hovering a map node shows a dark overlay card with the D#, status, title, question summary and current answer. |
| B1 | Picking an option while reopened settles and collapses in one motion (`pick` dispatches, then clears the expansion). |
| B2 | `columnOrder` is prerequisite depth then declaration order — a pure function of tree shape. Answering, reopening and folding cannot move an item. The column header says so. |
| B3 | Every answerable item is expanded with its full option list; there is no collapsed "accept recommendation" card. |
| B4 | A 🕘 button on every item opens that decision's change history without reopening it. Fold and update effects pulse the changed items (`.touched`, `.fresh`), and every history line is the event's own label. |
| B5 | One blended column: answerable expanded, settled collapsed to a one-line summary in place. |
| C1 | The D# is on every map node, every column item, every inbox entry, every pending row, every thread header and every "waiting on …" line. |
| C2 | A fold declares its impact before you commit (the "If folded:" note, or the orange disruptive note), the impacted nodes pulse, and the history records what changed. |
| C3 | The notifications inbox is the attention surface; the map's per-node pulse/flash badges are secondary cues. |
| M1 | Per-decision slide-out threads with the four seed buttons plus free text, one per decision or many, resumable, isolated. Inconsequential until concluded. |
| M2 | Each agent turn carries `foldable` and, when foldable, its declared impact — structural (node added) or state (unsettle / settle-with-reason / options revised) — rendered under the turn. Fold is thread-level and uses the latest foldable turn's impact. |
| M3 | Agent responses are structured updates that queue in a mailbox behind a visible pending indicator and apply on click. Informational replies pulse a ✉ on the node until read; elicitative ones either materialise a decision or raise a flashing ⚠ that opens a thread. |
| M4 | Multiple threads per node: folded ones stay viewable, parked ones are continuable, and any concluded thread can be relitigated into a new thread seeded from it plus current state. Conclusion is always explicit, and the D7 proof-rule thread's conclusion is declared disruptive and applies synchronously. |
| M5 | D12 (merge authority) is agent-mandated. The panel telegraphs it before you commit; answering holds the answer rather than settling it; concluding the thread is the only thing that settles the decision. |
| M6 | An `invalidate` update takes D10 out of the flow. It stays in `order`, still renders, stops blocking D14, and can be relitigated. |
| M7 | There is no plain undo. Reopening a decision with a changed answer engages the agent: descendants go "possibly affected — reassessment pending" locally, and the agent's later response resolves each one. |
| R1 | User actions apply locally and immediately. A queued update touching a node changed after it was generated is a conflict; the node goes `conflicted`, its whole downstream subtree goes `conflict-blocked` including already-answered nodes, and clicking it opens the thread with an auto-drafted first user message naming the prior answer and what needs judging. The UI never renders the diff. |
| R2 | Out of scope by its own text — whole-plan discussion returns to the harness conversation, and building it into the UI is a later enhancement. Its park-without-fold mechanics are implemented at node level, which is what a plan-level thread would reuse. |
| R3 | Staleness is provisional on the user side and resolved by the agent: `reassessing` is not on the frontier, and only a `confirmed` verdict makes a node `stale` and answerable again. |
| R4 | `nextFocus` prefers the agent's `recommendNext` when it is answerable, then a just-unblocked child of what was settled, then the oldest frontier item. |
| R5 | One inbox, four entry types (pending-update / informational / elicitative / suggested-thread), each with a "Go to it" deep link; suggested threads are suppressed while their node is blocked, stale-blocked, fogged or conflict-blocked. |
| R6 | The event log is the source of truth and everything else is a projection of it; per-node history is a filter over that one list. In memory only — persistence and mining are deferred by its own text. |
| S1 | Map canvas beside one blended column, side by side. |
| S2 | The map scrolls both axes, pans by mouse drag, and auto-centres on the focused node; clicking a map node focuses its column entry and scrolls it into view. Bidirectional. |

**AC3 — scenarios and free play.** All four scenarios were driven start to finish by clicking their own step
buttons in Chrome, on the final build: 9/9, 7/7, 11/11, 11/11. Zero console messages of any kind across a
page load and a full four-scenario run. Steps that depend on a reply the agent has not sent yet disable
themselves and show "waiting for the agent…", so the walkthroughs cannot outrun the fake latency.

Every choreographed behaviour was also reached in free play by its documented trigger, driving the real
controls: elicitative new node (`D1 = b` → D17 open; `D2 = b` → D18 open), invalidate (`D6 = c` → D10
`invalidated`, still on the board, D14 unblocked), conflict (`D3` then `D5` before applying → D5 `conflicted`
with eight downstream nodes blocked, thread seeded with a `who: "human"` turn), informational (✉ on D1,
cleared by reading it in the inbox), elicitative alert and the synchronous disruptive fold (`D7 = a` → T-proof;
folding rewrote D5 immediately, queued nothing, and left D7 `stale`), defog (settling D7 opens D16; settling
D12 opens D15), mandated thread (`D12` → `awaiting-thread`, park does not settle, fold settles it on the held
answer), and the fold-through-mailbox route (a user thread's `Trade-offs` impact queued one update that
landed only on apply). Threads also took free text, and a folded thread offered relitigation.

Two moments in the transcript that look like failures and were not: an eval timed out at 45s while the tab was
hidden and Chrome throttled the timer driving the fake agent — the scenario resumed and completed when the
tab came back, and the page now pumps on `visibilitychange` so it recovers on its own; and a second run
reported "10/9" because a stalled driver loop from the timed-out eval was still running alongside a new one.
Neither is a page defect, but the throttling is worth knowing before judging the latency feel in a background tab.

**AC4 — round-1 files unmodified.** `git status --porcelain` reports only `?? docs/prototypes/grilling-ui/`.
Note what that does *not* prove: the whole directory is untracked, so git has no baseline for the round-1
files and cannot show them as modified either way. The real evidence is that their hashes and mtimes are
byte-identical before and after this build:

```
f01f56b8aaf8bebd7079819562a15bb3138d42554e41da3e0785463a4318bfec  BUILD-REPORT.md          (Aug 16 12:15)
a7c97c7775289dbe80977fb0201efe8187f15b1977573f54ef37eba36bff7236  grilling-ui-prototype.html (Aug 16 12:12)
27426a985d54134cb4984823d5869b68fa1b489ebe1395c376969b9621dc7908  REACTIONS.md             (Aug 16 19:47)
```

The only new files are `grilling-ui-prototype-r2.html` and this report, both in the grilling-ui directory.
Nothing was committed, no installer was run, and the throwaway static server used for browser verification
(the extension will not navigate to `file://`) was stopped afterwards.

## The fake agent's choreography

The same table ships in a collapsible note on the page, so the owner can find each moment in free play.

| Trigger | Response |
|---|---|
| `D1` = recommended | informational on D1, plus a "recommended next" of D3 |
| `D1` = live query (b) | elicitative: materialises D17, re-query cost |
| `D2` = any blocked item (b) | elicitative: materialises D18, what "blocked" means |
| `D2` = recommended | informational on D2 |
| `D3` = anything | revises D5's options — the update that conflicts if D5 is answered before it lands |
| `D5` = anything | informational on D5, recommends D7 next |
| `D6` = escalating call (c) | invalidates D10 |
| `D7` = recommended | elicitative alert on D7 → T-proof, whose fold is disruptive and synchronous |
| `D8` = recommended | suggested thread on D13, suppressed from the inbox until D13 unblocks |
| `D11` = anything | settles a future node: D14 decided by the agent |
| `D12` = anything | mandated thread T-auth, opened immediately |
| any changed reopen | descendants provisional; agent confirms the direct dependents and clears the deeper ones |
| settling D7 / D12 | fog lifts off D16 / D15 |

Latency is 1.1–4.0s, derived from a hash of the decision and option so it varies per trigger but reproduces
run to run. "Impatient? deliver now" flushes it.

## Left undone, and uncertain

- **An invalidated node cannot be brought back.** You can open a thread on one (M6 says relitigate), but no
  update kind revives it, so folding that thread cannot return it to the flow. The vocabulary is missing a verb.
- **Apply is all-or-nothing.** The mailbox panel lists each update and flags the conflicting ones, but there is
  no per-update apply. R1 says the indicator applies them on click, so this follows the text; it becomes a
  question once four updates are queued and one of them is a conflict you would rather deal with later.
- Free-text turns get one generic canned reply; `Zoom Out` and `Why?` are hand-written for D5, D7 and D12 and
  templated elsewhere.
- The disruptive-fold banner persists until another banner replaces it. No dismiss.
- Ordering hazard the brief flagged as a stop condition did not materialise: updates apply in mailbox order,
  `add-node` always precedes anything targeting the added node, and an update naming a node that does not
  exist is a no-op rather than a crash. Worth knowing that the safety here is by construction, not by design.

## Design feedback — where the model felt wrong or underspecified

1. **The conflict blast radius is brutal, and it is the thing to judge first.** One conflict on D5 blocked nine
   decisions, seven of them already answered. R1 asks for exactly this, and it is defensible — those answers
   rest on a premise now in dispute. But on screen the board goes pink and the session stops until you deal
   with the conflict, which is the opposite of "the pending queue never locks the user". A softer reading is
   available: block *answering* downstream while leaving the answers readable and the rest of the frontier
   live. Worth deciding deliberately rather than inheriting from this build.
2. **R3 says the agent confirms, clears or restructures, but not on what basis.** I invented a policy — confirm
   the direct dependents, clear everything deeper — because the UI needed one. This is the single most
   load-bearing invention in the build, and a real agent's answer would vary per node. Everything about how
   recoverable a reopen feels comes from this rule.
3. **M2 puts `foldable` on the message and the fold on the thread, which leaves "which impact folds?" open.** I
   take the latest foldable turn. Accumulating every foldable turn's impact is equally readable from the text
   and would behave very differently in a long thread.
4. **Parking a mandated thread is a quiet dead end.** M5 says concluding is the only way to settle; M4 says park
   is always available. Together they let you park the mandated thread and leave the decision holding an
   answer that will never settle, with nothing on screen calling that a problem. Either park should release
   the held answer, or mandated threads should not offer park.
5. **The conflict thread asks you to distinguish clarification from re-decisioning, but only offers two
   outcomes** — park keeps yours, fold takes theirs. There is no "both, merged", which is what a clarification
   usually deserves. The auto-drafted seed message promises a nuance the controls cannot express.
6. **Informational replies accumulate.** Only suggested threads have a suppression rule. After a real session
   the inbox would be mostly read-later noise, and there is no expiry, no grouping and no "mark all read".
7. **Reopen == answer makes the history honest but flat.** Every re-answer looks the same in the log, so
   "changed my mind" and "re-confirmed unchanged" are distinguishable only by reading the answer text. If the
   event log is going to be mined later (R6), that distinction probably wants to be in the event.
8. **The agent's "recommended next" arrives through the mailbox, so it can retarget your focus minutes after
   it was decided.** I only move focus on a settle, never on an apply, which keeps applying updates from
   yanking you elsewhere. It is a judgement call the reactions do not cover.
