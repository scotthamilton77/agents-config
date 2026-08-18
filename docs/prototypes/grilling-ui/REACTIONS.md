# Owner reactions — prototype round 1

Usability reactions from clicking through, per variant. Model-level items apply to all variants.

## Variant A (map)

Bugs:
- A1. Reopen on a settled decision (right panel) does not unlock the answer controls — reopen must reveal the full answer UI (options + free text), since reopen and answer are one operation.

Usability:
- A2. After settling a decision, auto-advance the panel to the next best open decision — never force a map click to continue.
- A3. The free-text "answer in your own words" box should always hold focus, so type/dictate works with zero clicks; clicking is only for going off-path.
- A4. Map nodes need a hover overlay showing the decision's question summary.

## Model-level (applies everywhere)

- M1. Per-decision discussion threads: a "thread" button on any decision opens a slide-out that is its own contextual conversation with the agent — resumable, isolated from other decisions' threads. Seed buttons: "Zoom Out" (larger context), "Why?" (why is this question relevant), "Trade-offs" (pros/cons per option), "Ramifications" (downstream impact per option) — plus free multi-turn chat. Inconsequential to the grilling by default.
- M2. Folding is explicit and thread-level, not node-level: the agent's structured response per message carries `foldable` and, when foldable, the impacted decisions and how — structural map changes (node added, node detached/moot) or state changes (unsettled, implicitly settled for reason X, options/recommendation revised). On fold, the agent receives a handoff summary of the thread (plus a reference to the full conversation) and updates the grilling state.
- M3. Async agent protocol: submitted decisions go to the agent in the background. Agent responses are structured map/state updates that are QUEUED, not auto-applied — a visual pending-updates indicator applies them on click. Response kinds: informational (nuance acknowledged; unread = pulsing mail icon on the node, stops pulsing once seen) and elicitative (needs clarification/acknowledgement; becomes a new decision node or a flashing alert on the node that opens a thread).
- M4. Multiple threads per node: viewable (closed), continuable (never concluded), or relitigatable (new thread informed by current state + the old thread). Concluding a thread is always explicit (dynamic button ok); conclusion may go synchronous when the thread's potential map impact is disruptive.
- M5. Agent-mandated threads: the agent can pre-declare that an option — or any answer at all — on a decision requires a side thread, auto-initiated, and that concluding that thread is the only way to settle the decision. The decision panel must telegraph this before the user commits.
- M6. Invalidate ≠ delete: an invalidated node leaves the flow but stays on the board for (re)litigation.
- M7. Semantic undo: consequential changes (reopening a node whose answer had implications) engage the agent to reassess the map — a plain undo is only valid for the literally-last user action.

## Resolved in discussion (round 1, post-[a])

- R1. Pending queue never locks the user: user actions apply locally and immediately. A queued agent update touching a node the user has since changed is a conflict; a conflict BLOCKS that node's downstream nodes (even already-answered ones). Clicking the conflicted node opens its thread directly, with the first "user" message auto-generated to seed the discussion (prior answer, what the agent update needs judged: clarification vs re-decisioning) — the UI does not try to render the conflict itself.
- R2. Whole-plan discussion happens by returning to the orchestrating harness conversation (Claude Code); building that into the UI is a later enhancement. Plan-level threads with park-without-fold semantics ARE wanted: same non-polluting mechanics as node threads, maintained as grilling-experience state. Side threads plausibly run as forked teammate subagents so parked/discarded threads never pollute the grilling agent's context.
- R3. Stale-cascade demoted to provisional: UI instantly marks descendants "possibly affected — reassessment pending"; the agent's structured response confirms, clears, or restructures. Race conditions belong to the interaction-model mechanics discussion. Optimism is justified: accepting an agent-recommended answer is rarely consequential until it defogs something, and fogged nodes are non-interactive until the agent unlocks them; free-form answers and thread folds are the consequential paths, but they are slow on the user side, so the agent tends to catch up while the user thinks/reads/types.
- R4. Auto-advance: prefer a just-unblocked child of the decision just settled, else oldest frontier item; agent may override with an explicit "recommended next" in its response structure.

- R5. Notifications list is THE attention surface: one inbox with typed entries (pending-update / informational / elicitative / suggested-thread), each deep-linking to its node; suggested threads suppressed while their node is locked; node-level pulse/flash indicators remain as secondary cues.
- R6. "Living document" is not a UI view. The session's source of truth is the interaction event log — the totality of the collaboration, including parked/discarded threads and decision changes, valuable (a) as debugging/investigation data and (b) as a mining source for specs/designs/requirements/ACs, where the process context matters. A processed, clean decision log (result without process) is a separate projection for agents that must consume the outcome without the journey in context. Persistence and mining are post-prototype concerns; the prototype keeps the event log in memory only.

## Round 2 — owner reactions (r2 prototype)

Mailbox / notifications:
- U1. Auto-apply non-conflicting updates: a UI checkbox, default ON, value remembered in localStorage. (Example: D1 option b generating an added D17 needed no permission.)
- U2. Informational updates NEVER need an apply — always auto-apply; the notification alone is the record.
- U3. Notifications default to unread-only, with a filter to show already-seen ones (each still offering "go to it"); filter choice remembered in localStorage.
- U4. Inbox vs notifications was unintuitive: the same event produced an inbox item and a notification whose "go to it" just led back to the inbox. Rule: a notification exists only for APPLIED (including auto-applied) changes; pending changes live in the inbox alone.
- U5. Inbox items must be discussable before applying: open a thread on the pending change, and inside the thread be able to DISMISS the change (drilling into rationale may talk the agent out of it).
- U6. The inbox/notification side panel auto-closes on outside click.
- U7. Purely informational notifications also surface as temporary bubble overlays, upper right: click = mark read + dismiss; stack vertically; a bubble's TTL (~3s) only starts when it reaches the top of the stack so they pop one at a time; hover pauses the timer (mouse-out resumes); the top bubble shows its countdown.
- U8. A pending update targeting a node (e.g. D6 option c → pending invalidation of D10) marks that node visually on the map AND in its decision block, and the node is not decidable until the update is applied — or discussed and dismissed.
- U9. Elicitative alerts that don't conflict (D7's case) auto-apply so the alert becomes visible ASAP, rather than hiding behind a manual apply.
- U10. "Go to it" for an informational notification on a settled decision lands on a collapsed block with the information invisible. Wanted: the unread info visible on the collapsed block with a "mark as read" button (no reopen required), plus a flashing icon on the map node that jumps to the same view.

Map / decision blocks:
- U11. Map-node alert icons are too small to click.
- U12. Node hover must indicate unread/unprocessed items; hovering a specific icon explains it (mail vs lightning on the same node was indistinguishable).
- U13. Decision blocks need an explicit expand/collapse control (corner of each block); today collapse hides behind "leave as it is" and expand behind map-click or "expand to change it".
- U14. Auto-advance is too sudden: fast animation of the block compacting and the list scrolling, so the motion reads.
- U15. When a settled decision has threads requiring user action, option selection (and free text) must be LOCKED until those threads conclude; blocking elicitation threads render at the TOP of the block, visibly marked as blocking.
- U16. Each agent-supplied option gets a brief pros/cons/ramifications hover overlay.
- U17. Mandated-thread decisions (D12) need much stronger visual distinction than a small note — big icon / different background, on the block AND the map node. (Also: that the thread comes after choosing was not obvious.)
- U18. Thread panel must not obscure the decision it discusses: threads open on the LEFT; stretch goal — "pop out" a thread into its own browser window so several run at once without blocking the main UI.
- U19. Opening a thread panel and closing it without sending anything must NOT create a thread.

Threads:
- T1. Kill per-message foldable/not-foldable captions. The agent's response declares when the thread is fold-ready; only then does the Fold button enable, and that response carries the likely impact, shown via an expansion control in/next to the Fold button.
- T2. Thread textbox always holds focus.
- T3. Cmd+Enter sends (threads and decision free-text alike); Enter alone inserts a newline. (Configurable later.)
- T4. Seed buttons (Zoom Out / Why? / Trade-offs / Ramifications) show only when STARTING a thread; hidden once it's going. Mid-thread, the AGENT may present options with a recommendation when it asks the user a question — rendered like decision options, each with pros/cons/ramifications.
- T5. Thread titles auto-generate from content and show in the per-decision thread list.

Implementation note (for the eventual skill, not the prototype):
- N1. The deployed skill must include reference material about the UI's behaviour and pointers to the backend functionality, so the harness agent can answer "why can't I do X / the UI is blocking Y / Z happened and looks broken" directly in chat.

## Resolved in discussion (round 2, post-owner-pass)

- R7. Auto-apply taxonomy: eligible (checkbox on) — add-node, defog, options/recommendation revisions on undecided nodes, non-conflicting elicitative alerts; informational always auto-applies. Never auto-apply: anything touching a decision the user already made (invalidation, unsettle, revision of an answered node) — those stay in the inbox with the U8 target-node lock. The line is "does it overwrite or undermine a human decision," not "is it a conflict." Caveats: (a) nodes with pending not-yet-applied changes/folds MUST show visually on the map and in their decision blocks — doubly important once auto-apply exists; (b) an informational update to a decided node requiring no action auto-applies but must show a clear unread indicator; agents should be discouraged from information-free "informational" replies — an acknowledgement needs no prose for the user to read (this half is an agent-protocol/skill concern, see N1).
- R8. Conflict blast: soften the paint, keep the semantics. Downstream of a conflict is not answerable, but only the conflicted node gets the loud red; downstream shows quiet "waiting on D#" dimming, and the untouched frontier stays fully live and visually normal.
- R9. Reassessment basis: in the real system the agent judges each descendant from the actual answer change — no client heuristic is authoritative. The prototype keeps a stand-in rule but labels affected nodes "reassessing…" until the agent's update resolves each: provisional locally, adjudicated by the agent.
- R10. Mandated threads never offer park — only conclude, or abandon-the-answer (reverting the option selection and returning the decision to open). Park exists for optional exploration only.

## Round 3 — owner reactions, first pass (fix round required before review continues)

Common theme: decision-panel scrolling must be disciplined — one scroll intent per USER action, never as a side-effect of agent events or panel opens, and never re-scrolling a target already fully in view.

- F1. Bubble hover pauses the countdown but mouse-out does not resume it; click does not mark-as-read-and-dismiss.
- F2. Bubble countdown shows fractional seconds — replace with a graphical indicator (shrinking bar or depleting pie), no numerals.
- F3. Scroll thrash on settle: panel scrolls to the next decision, then re-scrolls when the agent response/notification lands (often to the same item; D3 double-scrolled; D5 re-scrolled to sit above the panel's top edge, requiring manual correction). Skip scrolls whose target is already fully visible; a scroll must always leave its target fully in view.
- F4. Merely opening the inbox re-scrolls the decision panel.
- F5. Popped-out thread window: "dismiss" does nothing.
- F6. Scenario 2 step 6 says "the lock is gone" but no lock indicator was ever visible on D10 (U8's pending-lock rendering is missing or too subtle; only the dismissed thread showed).
- F7. Opening D7's blocking-warning thread (map warning icon, or the block's "open it") scrolls the decision pane back to D1.
- F8. Settled decisions should be COLLAPSED by default; expand only when something requires it (unread informational already renders on the collapsed card per U10).

## Round 3 — owner reactions, second pass (final fix round; owner confirms, then next steps)

- F9. An inbox/notification "show it" landing on an already-settled decision shows it collapsed; a "show me" navigation should land the decision EXPANDED.
- F10. Bubble timer sticks in the paused state: hover a bubble, click to dismiss it, and the next bubble that appears later renders paused until a fresh mouse-in/out.
- F11. Scenario 2 step 1: three bubbles show but the notification count is four — the applied-change notification never bubbled. Applied-change notifications should bubble like the rest (owner expectation).
- F12. Thread pop-out is missing for just-started threads with no messages yet — either enable it there (preserving U19: closing without ever sending still creates nothing) or state the reason it cannot be.

## Open, deliberately deferred

- O1. Parked-thread drift: a reopened parked thread's agent is stale relative to the evolved map/context and may assert uninformed things. Mitigations exist; resolve at implementation time, not now.
- O2. UI↔agent transport mechanics (how the grilling agent receives UI events and publishes structured updates) — not yet discussed by choice.

## Variant B (queue)

Bugs:
- B1. Reopen-in-place in the ledger is unintuitive: clicking an option updates both the answer text under the settled header and the "currently:" text under the close button, then takes two Close clicks (or one more option click, then close) to return to the decided view. Selecting an option while reopened should settle-and-close in one motion.
- B2. Reopening an item and selecting an option swaps the item with the one above it in the ledger (D1/D2 swap; with more items it still swaps with its neighbor, not a bump-to-top). Ledger ordering must be stable and intentional, never a side-effect.

Usability:
- B3. Only the top queue card shows its full options; cards below collapse to "Accept recommendation" + "other answers". That makes accept-recommendation a blind decision exactly when it is most prominent — a useless space optimization. Every answerable card shows its options.
- B4. Fold-back's effect was invisible: the changed D5 entry just moved in the ledger. Needs visual cues (animate/pulse changed items) AND a per-decision change history viewable without reopening the decision — possibly the ledger is conceptually immutable events, but if rendering it that way is cumbersome, the history-behind-a-node view is the minimum.
- B5. Consider collapsing the two columns (answerable-now + ledger) into ONE stack: decided items collapse to one-line summary blocks in place; expanding a decided item implicitly reopens it for change.

## A vs B synthesis (owner direction)

- S1. Keep A's map visual, blended with B5's single column: map canvas beside one combined stack. B's vertical tree strip is close but side-by-side is the interesting arrangement.
- S2. When horizontal space is tight: the map scrolls both axes, mouse-draggable, auto-centering on the node selected/active/focused in the right column; clicking a map node scrolls it into view and focuses it in the right column. Bidirectional focus sync.

## Variant C (document)

- C1. Hiding the D# identifiers in the main view breaks every cross-reference ("waiting on D5", "suggested thread · D7" become meaningless). Identifiers must stay visible wherever other UI text points at them.
- C2. Harder to navigate: folding the thread "into D5" gave no way to tell which bullet was D5 or what changed. (Same root as B4 — fold effects need visible diff + history.)
- C3. The suggested-thread margin panel feels disconnected. Better: a notifications list — items where the agent's processing warrants the user's attention, which may include suggested threads, but never for decisions that are still locked/blocked.

## Round-1 verdict (owner, after all three passes)

Winner is a hybrid, not any variant: A's map canvas (scrollable, drag-pannable, auto-centering on focus) beside ONE blended column of answerable + settled decisions (B5), bidirectional focus sync (S2), threads as per-decision slide-outs (M1), and C3's notifications list as the attention surface. C loses as an interaction surface (C1/C2); its margin-thread idea is superseded by the slide-out + notifications combination.
