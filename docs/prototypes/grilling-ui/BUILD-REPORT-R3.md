# Grilling-UI prototype, round 3 — build report

Deliverable: `/Users/scott/src/projects/agents-config/docs/prototypes/grilling-ui/grilling-ui-prototype-r3.html`
(one file, 2661 lines, 122 KB, no frameworks, no CDN, no network calls, light theme, `grillproto3.*` localStorage).

Round 2 asked whether an asynchronous agent is workable at all. This round is your round-2 pass, built: the
agent's replies now land by themselves unless they would overwrite or undermine a decision you made, and
those — only those — wait in the inbox and lock the decision they target.

## Evidence per acceptance criterion

**AC1 — the node self-check runs green.** Exact command, run from the repository root:

```
node -e "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const p=s.split('//---GRILL-MODULE-START---');if(p.length!==2)throw new Error('marker collision: '+p.length);const m=p[1].split('//---GRILL-MODULE-END---')[0];if(m.length<5000)throw new Error('slice too small: '+m.length);fs.writeFileSync('/tmp/grill-r3-module.js',m);" \
  docs/prototypes/grilling-ui/grilling-ui-prototype-r3.html && node /tmp/grill-r3-module.js; echo "EXIT=$?"
```

```
grilling r3 state module self-check: OK (16 base decisions, 2 agent-addable, 9 events in the last session)
EXIT=0
```

Both round-1 guards are kept — exactly two markers, slice over 5000 bytes — and the check still prints on
success, so an empty run cannot pass for a green one. The page script is separately parse-checked with
`node --check` (it cannot be executed outside a browser); that passes too.

The seven cases the brief required are asserted, plus the round-2 set. Auto-apply taxonomy: an informational
update applies with the checkbox off, an added node applies with it on and queues with it off, and
`autoApplies` returns false for a revision of an *answered* decision while returning true for the same
revision of an unanswered one. Pending-target lock: a queued invalidation puts `D10` off the frontier and
`reduce(answer D10)` returns the identical state. Dismiss-via-thread: `discussPending` opens the thread,
`dismissUpdate` empties the inbox, releases the lock, and leaves no notification. Notification-only-on-apply:
no notification exists for `D10` while queued, one exists after applying. Mandate: concluding settles on the
held answer, abandoning reverts the selection and returns the decision to open, and you can answer again
afterwards. Elicitation lock: `D7` settled with an action-required thread refuses a new answer until the
thread concludes or is dismissed. Empty thread: `newThread` with neither seed nor text returns the identical
state and creates nothing.

**AC2 — coverage of every identifier.**

| ID | How this build satisfies it |
|----|------------------------------|
| U1 | Checkbox in the top bar, default on, persisted at `grillproto3.autoApply`. Verified: toggling writes `false`, and after Reset the key is gone and the default is back on. |
| U2 | `autoApplies` returns true for `informational` before it consults the checkbox. Verified in the browser with auto-apply off: the note still landed. |
| U3 | Notifications open filtered to unread, with an "Everything" toggle; choice persisted at `grillproto3.unreadOnly`. Each entry keeps its own "Go to it" and a "Mark as read". |
| U4 | Notifications are built from `s.notes`, which is appended only on an `applied` event. Queued changes appear in the inbox alone. Verified both ways on the same update: nothing while pending, an entry after applying, and still nothing after dismissing. |
| U5 | Inbox rows carry "Discuss it", which opens a `pending`-kind thread; inside it, "Dismiss it" withdraws the change and releases the lock. Scenario 2 walks exactly this path. |
| U6 | A click outside the panel closes the inbox and notification panels (thread panels stay, deliberately — they are on the left so you can work beside them). Verified. |
| U7 | Informational notes also push a bubble to the upper right. They stack; only the top one's clock runs, so they pop one at a time; the top one shows its countdown; hovering the stack pauses it and mouse-out resumes; clicking marks read and dismisses. Deadlines are wall-clock, not an accumulated countdown, so a throttled background tab cannot freeze them. |
| U8 | A queued update marks its target with a 📥 badge and a ring on the map, a `locked` pill and a full notice in the block, and `blockLock` takes the node off the frontier and refuses answers. Verified end to end on `D6 = c → D10`. |
| U9 | `elicit-alert` is auto-apply eligible, so `D7`'s alert is visible the moment it arrives rather than behind a manual apply. |
| U10 | An unread note renders on the *collapsed* block with a "Mark as read" button, and the map's ✉ badge jumps focus there without expanding anything. Verified: block stayed collapsed, note visible, badge cleared on read. |
| U11 | Badges are 24px (27px for the mandate ⚖) circular targets that overhang the node corner. They were `<button>`s nested inside the node's own button, which the HTML parser hoists out of it — they rendered detached in the top-left of the canvas. Now spans; verified inside their nodes at the right size. |
| U12 | Every badge carries its own hover explanation, and the node hover card ends with an "attention" list naming each outstanding item, so ✉ and ⚠ on one node are never a guess. |
| U13 | An explicit ⌃/⌄ control in the corner of every block; verified 16 controls for 16 blocks. Expansion is a tri-state, so an explicit choice survives the status-based default. |
| U14 | The settled block gets a `justsettled` class that animates the compaction, and the column scrolls with `behavior: "smooth"` on auto-advance. Verified the class is present at the moment of settling. |
| U15 | Action-required threads render at the *top* of the block under a "blocking" tag, and lock the options and the free text. Verified: the blocking notice is the first element in `#col-D7`, and answering is refused. |
| U16 | Every option carries `pcr` — what it buys, what it costs, what it forces later — shown in a hover card. Authored for all 54 options across the 18 decisions; agent-generated options fall back to a generic triple. |
| U17 | Mandated decisions get a 3px cyan border and tinted fill on the map, a tinted block with a 22px ⚖ in the header, a ⚖ map badge, and a two-line notice saying that choosing comes first and concluding the thread is what settles it. |
| U18 | Threads open on the left (`.slide.left`), so the column stays visible. **Pop-out works**: ⧉ opens the thread in its own window that live-mirrors the parent every 600ms and sends actions back through `window.opener`. It needs a genuine user gesture — synthetic clicks are refused by the popup blocker — and on refusal the panel stays put with a note. Verified by a real mouse click: window opened, styled, showed the turns, and mirrored a message sent from the parent. |
| U19 | The panel opens on a draft; `newThread` with nothing said returns no events. Verified: open, close, zero threads. |
| T1 | Per-message foldable captions are gone. Fold-readiness is `foldReady(thread)` — the last agent turn carrying an impact — and it gates the Fold button; the declared impact sits behind a "what folding would do" disclosure next to it. |
| T2 | The thread textbox takes focus when the thread opens. This needed a fix: the round-2 focus-restore branch was winning, so a just-opened panel now claims the caret once, and only once, leaving mid-typing alone. Verified: typing survived an agent update landing, text and caret intact. |
| T3 | Cmd/Ctrl+Enter sends in threads and decision free-text alike; plain Enter inserts a newline. Both verified. A ⌘↵ hint sits beside every box. |
| T4 | Seed buttons render only before the thread has a human turn. Mid-thread the agent replies with an option set — recommendation first, each option with the same hover trade-offs as a decision option. |
| T5 | Titles generate from the first thing said (`titleFrom`) and show in the per-decision thread list. Verified: "D5 — Trade-offs on Proof of completion" and a free-text thread titled from its own words. |
| R7 | `autoApplies` is the whole taxonomy, and it runs at *arrival*, not at generation — the board may have moved while the update was in flight. Eligible: add-node, elicit-alert, resolve-stale, and revise/settle on an undecided node. Never: unsettle, invalidate, or anything targeting a decided node. Informational ignores the checkbox. Caveat (a) is U8; caveat (b) is U10. |
| R8 | Semantics unchanged — downstream of a conflict is still unanswerable. Paint softened: only the conflicted node is red; downstream is pale dashed grey reading "waiting on D5"; the untouched frontier is fully normal. Verified on screen with one conflicted node, eight quiet ones, and D6/D9 live. |
| R9 | A changed answer marks descendants provisional and they read "the agent is reassessing this" until its update resolves each. The client rule is a stand-in; the copy says the agent is judging it. |
| R10 | Mandated threads offer "Conclude" and "Abandon the answer" — no park. Abandoning reverts the selection, returns the decision to open, and lets you answer again. |

**AC3 — scenarios and free play.** All five scenarios were driven start to finish by clicking their own step
buttons: 7/7, 6/6, 9/9, 8/8, 7/7. **Zero console errors or warnings across every run and every free-play
probe.** Steps that depend on an undelivered reply disable themselves and show "waiting for the agent…", and
scenario 3 holds the agent deliberately so the conflict is reproducible rather than a race you might win.

Every choreographed behaviour was also reached in free play by its documented trigger: `D2 = b` materialised
D18; `D8 = a` raised the suggested thread on D13 and it stayed out of notifications until D13 unblocked, then
appeared; `D7 = a` locked D7 and defogged D16; `D11 = a` had the agent settle D14 (`by: "agent"`, notified as
an auto-applied change); `D6 = c` queued the invalidation and locked D10; auto-apply off queued an ordinary
add-node. Browser verification ran over a throwaway `python3 -m http.server` on 8777, stopped afterwards —
the Chrome extension refuses to navigate to `file://`, so that one delivery path is argued rather than
observed: the page issues no network requests, uses no modules and loads no external resources, and both
`localStorage` and `window.open` are wrapped so a refusal degrades instead of breaking.

**AC4 — earlier rounds untouched.** Hashes taken before the build and again after it, byte-identical:

```
a7c97c7775289dbe80977fb0201efe8187f15b1977573f54ef37eba36bff7236  grilling-ui-prototype.html
1d93440bd14bfb28931d08a63e3cc0916832d1239fb6bd0d92274ed2546f7f6e  grilling-ui-prototype-r2.html
584f416e73b4714a08cfb45ce5912995d97c1fe7da870b09a3bcf064e8c5788d  REACTIONS.md
fd7583027007cbe167d45faf0a470072f78a0f9f566b9b9e8ae510d2d51dfe55  BUILD-REPORT-R2.md
f01f56b8aaf8bebd7079819562a15bb3138d42554e41da3e0785463a4318bfec  BUILD-REPORT.md
```

The only new files are `grilling-ui-prototype-r3.html` and this report, both in the grilling-ui directory.
Every localStorage key is namespaced `grillproto3.*` — every `file://` page shares one origin in Chrome, so
an unnamespaced key would collide with anything else opened from disk — and Reset clears exactly those keys
(verified: two keys before, none after).

## State-module surface delta from r2

- New actions: `setAutoApply`, `abandonAnswer`, `discussPending`, `dismissUpdate`, `dismissThread`, `readNote`.
- `applyPending` takes an optional `updateId`, so one change can be released without the rest.
- `newThread` takes `seed` or `text` and returns no events without one; `threadSeed`/`threadSay` unchanged.
- New selectors: `blockLock(s, id)` (the one answer to "why can't I decide this"), `foldReady(t)`, `autoApplies(s, u)`, `unreadCount(s)`.
- `pending(s)` is the inbox; `notifications(s)` is now built from `s.notes`, appended only on `applied`.
- `initial(autoApply)` seeds the preference so the page can restore it from localStorage.
- State gains `autoApply`, `notes`, `read`; mailbox entries gain a `dismissed` status; threads gain `requiresAction` and `updateId`.
- Turns lost `foldable`; they carry `impact` (fold-readiness) and optionally `ask` (an agent option set).

## Changed choreography

Same table ships collapsed on the page. Changes from r2: `D4 = a` now returns an informational note so three
answered in a row stack three bubbles; `D7`'s alert is marked action-required, so it *blocks* D7 rather than
merely suggesting; `D3`'s revision of D5 applies itself while D5 is unanswered and waits once it is answered;
`D6 = c` never applies itself. Everything else is unchanged.

## Left undone, and uncertain

- **`settle` on an undecided node auto-applies.** R7's line is "does it overwrite or undermine a human
  decision", and the agent settling a question you have not answered does neither — so `D11 → D14` lands
  without asking. It is the one place the stated line felt too permissive to me; the agent decides something
  for you and only a notification records it. Easy to move to the inbox if you disagree.
- **`resolve-stale` auto-applies.** R7 does not name it and R9 implies it should flow. Confirming a
  descendant is stale technically undermines an answer you gave — but the reassessment exists only because
  you changed something, so queueing it would make every reopen require an inbox trip. Flagged rather than
  hidden.
- **An action-required thread can be dismissed** ("No action needed"). R10 removed park from mandated
  threads; without an equivalent escape, an elicitation thread you disagree with would lock its decision
  forever. Parking one deliberately does not release the lock.
- **A queued update targeting a node that does not exist yet** (auto-apply off, `D1 = b → D17`) locks
  nothing, because there is no block to lock. Correct, but it means the inbox is the only mark for that case.
- Free-text turns get one canned reply plus one option set; `Zoom Out` and `Why?` are hand-written for D5,
  D7 and D12 and templated elsewhere.
- Closing a thread panel leaves focus on `<body>` until the next render, so the decision box does not
  immediately reclaim the caret. Self-corrects on the next interaction.
- An invalidated node still cannot be brought back — carried over from r2, the vocabulary has no revive verb.

## Design feedback — where the items fought each other

1. **U8 and U1 pull in opposite directions, and U8 wins too often.** Auto-apply exists to stop the agent
   asking permission; the lock exists to stop it moving under you. But a locked decision is a *harder* stop
   than r2's queue ever was — in r2 you could ignore the mailbox and keep working, and now a single queued
   invalidation makes D10 unanswerable until you deal with it. It is right for an invalidation. It would be
   wrong for something small, and the taxonomy has no notion of small.
2. **"Informational" is doing two jobs.** U2 says it always applies and U10 says it must be readable and
   dismissable on a settled block — which makes it a message with a read state, i.e. a task. Three bubbles
   stacking is genuinely pleasant; three unread ✉ badges sitting on settled decisions an hour later is the
   r2 inbox problem wearing a different hat. Your own note under R7 (discourage information-free replies) is
   the real fix and it is an agent-protocol concern, not a UI one.
3. **U15's lock has no expressible disagreement.** A blocking thread can be concluded or dismissed, but
   "I have read this and I am keeping my answer" is only reachable by dismissing, which reads as "no action
   needed" — not the same statement. The conflict thread has the same gap r2 noted (park keeps yours, fold
   takes theirs, nothing merges).
4. **R10's abandon is cleaner than park but loses the work.** Abandoning reverts the selection *and* leaves
   the thread abandoned; re-answering reopens the same thread with its turns intact, which is good, but
   there is no way to keep the thread going while releasing the held answer.
5. **T4's mid-thread option set is the best thing in this round and it is under-used.** Rendering the
   agent's question as options with trade-offs makes a thread feel like the decision surface rather than a
   chat window. It fires once, on the first free-text turn. It probably wants to be the *default* shape of
   an agent question in a thread.
6. **U17 marks D12 from the very start**, including while it is still blocked and unreachable. That
   telegraphs the mandate early (which M5 wants) but puts a loud ⚖ on the board for a question you cannot
   ask yet. Worth deciding whether the mark belongs to the decision or to its reachable state.
7. **The bubbles and the notification panel disagree about what "read" means.** A bubble that times out
   leaves the note unread (deliberate — you may not have looked); a bubble you click marks it read. So
   walking away from the screen produces a pile of unread notes, and sitting in front of it produces none.
   That is defensible, but it makes the unread count a measure of attendance rather than of attention.

## Fix round (F1–F8)

Owner's first pass stalled on eight defects. All fixed in place in the r3 file; module self-check re-run
(`grilling r3 state module self-check: OK (16 base decisions, 2 agent-addable, 9 events in the last session)`,
`EXIT=0`), page re-parsed with `node --check`, and all five scenarios re-driven end to end — 7/6/9/8/7 steps,
zero console errors.

Three of the eight were one root cause, and two more were the same bug in a second place.

| ID | What changed | Verified by |
|----|--------------|-------------|
| F1 | The stack was rewriting its own DOM every 150ms, which destroyed the element under the cursor (so the hover flag could never clear, and mouse-out never resumed) and replaced the button between mousedown and mouseup (so clicks never fired). The DOM is now written only when the set of bubbles changes; hover is read from CSS `:hover` instead of a flag, and the tick decrements by real elapsed time. | Real pointer: hovered 2.5s → `left` frozen at 1977ms and the drain reported `paused`; moved away → drain `running`, stack went 3→1→0; real click → note marked read (unread 1→0) and the bubble dismissed. |
| F2 | Numeric countdown replaced by a CSS-animated drain bar (`@keyframes drain`, 3s linear) that pauses off the same `:hover`. No numerals anywhere on the bubble. | Bubble text has no `\d+s`; the bar element animates `drain`, computed `animation-play-state` flips paused/running with the pointer. |
| F3 | Two causes. (a) `answer()` fired two focus intents per click — dispatch auto-advanced, then the helper focused the answered decision again; it now only looks at what you answered if no auto-advance happened. (b) The settled block's compaction animated `max-height`, so the layout was still resizing while the scroll measured where to go, landing the next decision above the top edge; the cue is now opacity/transform with no layout effect. `centerOn` additionally no-ops when the target is already fully visible, and otherwise clamps so the target lands fully in view. | Settling D1: one scroll, D3 fully visible, and the agent response landing moved nothing (652→652). Settling D3: D5 fully visible at 1082 (top 1283, bottom 1712, view 1082..1722), not clipped. |
| F4 | Same root as F3: `scroll-behavior: smooth` on the column turned every render's scroll-restore into an animation fighting the previous one, so unrelated re-renders drifted the panel. Removed; intentional scrolls set `scrollTop` directly. | Opening notifications: 1082→1082. Opening the inbox: 1082→1082. |
| F5 | The popped-out window repainted its whole body every 600ms — the same click-eating bug as F1, which is why a real click on Dismiss did nothing while a scripted one worked. `draw()` now compares the rendered HTML and only writes when it changed. | In the popup: 0 DOM writes across 2.6s idle (was one every 600ms), exactly 1 when state changed; dismiss set the thread to `dismissed`, released D7's lock, and the popup showed "This thread is dismissed". |
| F6 | The lock was real but quiet, and scenario 2 step 3 opened the inbox panel — which covers the decision column — over the thing it was pointing at. Added a 🔒 to the map node's own label and to the block header, spelled the pill out as "🔒 locked · a change is waiting", and split the step so you look at the locked decision before the panel covers it. | Scenario 2 step 3: map node reads `D10 Wake threshold 🔒 ❓📥` with the `pendlocked` ring; block shows the header 🔒, the pill, and the notice; no right-hand panel open. Screenshot confirms. |
| F7 | Same root as F4 — opening the blocking thread re-rendered, and the smooth restore drifted the panel. No scroll intent is raised by opening any thread. | Opening T-proof from the map ⚠ badge: 2653→2653. From the block's "Open it": 2653→2653. |
| F8 | Settled blocks were already collapsed by default, but clicking a map node force-expanded its block permanently (`UI.open[id] = true`), so the board filled up with expanded settled decisions as you navigated. Focusing no longer expands anything; the ⌃/⌄ control is the only way to force a block open. | After answering four decisions, every settled block collapsed; clicking D1's map node left it collapsed. End of scenario 5: all settled blocks collapsed. |

Scroll discipline now holds as stated: across whole walkthroughs the number of scroll intents is 8, 4, 6, 1 and
5 for scenarios 1–5 — one per user action, none from agent responses, notifications, panels or thread opens.

One trade made deliberately, worth a look: **U14's smooth glide is gone.** Auto-advance now jumps directly to
the next decision. Every re-render replaces the column element, which kills an in-flight smooth scroll
part-way — that was half of F3's "sits above the top edge". The motion cue is the settled block's fade, which
no longer moves the layout. If the jump reads as harsh, the fix is to animate a wrapper that is not
re-rendered, which is a bigger change than this round wanted.

Nothing in F1–F8 was ambiguous, and I did not find one that was already correct behaviour. F5 is the only one
I could not reproduce before fixing it, because a scripted click is atomic and cannot be eaten by a repaint —
the mechanism was confirmed instead, and the repaint it depended on is gone.

## Fix round 2 (F9–F12)

Module self-check re-run green (`grilling r3 state module self-check: OK (16 base decisions, 2 agent-addable,
9 events in the last session)`, `EXIT=0`); all five scenarios re-driven end to end (7/6/9/8/7), zero console errors.

| ID | What changed | Verified by |
|----|--------------|-------------|
| F9 | "Go to it" (notifications) and "Show me D#" (inbox) now set the target's expansion when they navigate, so a settled decision lands open. It is navigation, not a reopen: the decision stays settled and the ⌃ control collapses it again. Not applied to the map's ✉ badge jump — U10 asks specifically that unread information be readable on the *collapsed* card with no reopen, and that still holds. | "Go to it" onto settled D1: collapsed before, expanded after, still `settled`, panel closed, ⌃ collapsed it back. Inbox "Show me D10": expanded, panel closed. |
| F10 | The pause was read from `#bubbles:hover`. Removing the hovered bubble by clicking it leaves Chrome's `:hover` latched on the container until the next mouse move, so the next bubble was born paused. Pause is now computed from the pointer's own last position against the live container rect each tick, and the CSS drain keys off a `.paused` class we set rather than `:hover`. | Owner's repro with a real pointer: hovered a bubble, clicked to dismiss it (1→0), moved the mouse away, triggered another — born with `paused` class false and drained 2000ms→gone without any fresh mouse-in/out. Genuine hover still pauses (verified separately last round, unchanged). |
| F11 | Applied-change notifications now bubble alongside informational ones. Still deliberately not bubbling: `elicitative`, `suggested-thread` and `conflict` — those need an action, they already flash on their node and wait in the list, and a bubble that times out after three seconds is the wrong carrier for something that must be dealt with. | Scenario 2 step 1: 4 notifications (3 informational + 1 applied-change), 4 bubbles, both types present. Was 3 of 4. |
| F12 | Pop-out enabled for a just-started thread. There was a real mechanism in the way — the popup mirrors by polling `opener.threadHTML(tid)` and a draft has no id — so the draft travels as `draft:<node>` and resolves to whatever that draft creates, recording the thread count at pop-out time so it can never resolve to a pre-existing thread on the same decision. The draft body is now shared by the panel and the popup. | Popped out a draft on D2 with a real click: 0 threads, popup showed the draft with its seed buttons and send box; seeding from the popup created the thread (anchor D2, self-titled) and the popup switched to mirroring it. U19 preserved: 0 threads before, 0 after popping out and closing without sending. |
