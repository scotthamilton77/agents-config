# Grilling-UI prototype — build report

Deliverable: `/Users/scott/src/projects/agents-config/docs/prototypes/grilling-ui/grilling-ui-prototype.html`
(one file, 1052 lines, 57 KB, no frameworks, no CDN, no network calls, light theme only).

## The state module's public surface

- `initial()` — a fresh session over the canned plan: 16 decisions, 1 side thread.
- `reduce(state, action)` — the only mutator, pure. Actions: `answer`, `openThread`, `threadNext`, `parkThread`, `foldThread`, `reset`.
- `statusOf(state, id)` — `settled` | `open` | `blocked` | `stale` | `stale-blocked` | `fogged`.
- `frontier(state)` — ids answerable right now (`open` plus `stale`).
- `nodeView(state, id)` — one node with status, depth, prereqs, options and fog resolved; the only thing the page reads per node.
- `layers(state)` — ids grouped by prerequisite depth; drives the map columns and the outline order.
- `answerText`, `counts`, `depthOf`, `isSettled`, `isFogged` — selectors.

Answering and reopening are the same operation on purpose: `answer` on an already-settled node is a reopen, and it cascades only when the resulting answer text actually changed.

## Evidence per acceptance criterion

**AC1 — node self-check.** The module is fenced by `//---GRILL-MODULE-START---` / `//---GRILL-MODULE-END---` and self-checks when run outside a browser. Exact command run from the repository root, and its result:

```
node -e "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const p=s.split('//---GRILL-MODULE-START---');if(p.length!==2)throw new Error('marker collision: '+p.length);const m=p[1].split('//---GRILL-MODULE-END---')[0];if(m.length<5000)throw new Error('slice too small: '+m.length);fs.writeFileSync('/tmp/grill-module.js',m);" \
  docs/prototypes/grilling-ui/grilling-ui-prototype.html && node /tmp/grill-module.js
```

```
grilling state module self-check: OK (16 decisions, 1 side thread)
EXIT=0
```

The two guards in that command are not decoration. The first version of the extractor spliced the wrong region, wrote a 13-byte fragment that happened to be a valid JavaScript string literal, and exited 0 with no output — a green that proved nothing. The marker-count and slice-length checks make that failure loud, and the self-check prints on success so an empty run cannot be mistaken for a pass.

Asserts cover: initial frontier is the two roots; answering unblocks dependents and reports them as newly surfaced; fog graduates only when its gating decision settles; a changed reopen cascades staleness downstream (direct dependent `stale`, deeper dependent `stale-blocked`, graduated fog sinks back to `fogged`); an unchanged reopen cascades nothing; parking a thread leaves `state.nodes` byte-identical; a parked thread can be picked back up; folding applies the conclusion to `D5` and cascades to `D7`.

**AC2 — three variants, switcher, reload-stable.** Verified in Chrome. `←`/`→` and the pill-bar arrows both cycle, with wrap-around confirmed in both directions (`A → C` on prev, `C → A` on next); the label tracks (`A — Map`, `B — Queue`, `C — Document`). Variant lives in the URL hash (`#variant=B`) and survived a reload.

Caveat worth knowing: the browser extension available here refuses to navigate to `file://`, so verification ran against a throwaway local static server which was stopped afterwards. The hash was chosen precisely because it is origin-independent — `file://` has a null origin and rejects `history.pushState`/`replaceState`, which is what a `?variant=` query param would have needed. The file contains no `pushState`/`replaceState` call, no `type="module"` script, and no external or network reference of any kind (grep-verified), so nothing in it depends on a non-null origin. The literal double-click case is the one thing not machine-verified.

The variants are structurally different, not restyled: **A** is a 2D node-link map with a docked question panel and fog banked at the right edge; **B** is a frontier queue column beside a chronological ledger whose every settled row reopens in place, with the tree demoted to a collapsible chip strip; **C** is a living outline where settled decisions read as spec prose at their tree position, open questions are embedded inline where they belong, and threads sit in the margin.

**AC3 — five interaction moments, in every variant.** All exercised through the real DOM controls:
- one-click recommended answer — the primary control on every card/panel (mouse-clicked in A, confirmed present on every queue card in B and every inline question in C);
- alternative — clicked `D1`'s second option, answer text changed accordingly;
- free text — typed into the textarea and submitted, `D2` settled on the typed string;
- reopen and cascade — reopening `D3` with a different option left `D3` settled, `D5` `stale` and back on the frontier, `D7`/`D11` `stale-blocked`, `D16` back to `fogged`;
- side thread park (`state.nodes` unchanged, nothing stale) and fold-back (`D5` rewritten with the thread's conclusion, `D7` → `stale`, `D16` → `fogged`).

Nine end-to-end runs (3 scenarios × 3 variants) drove every step button to completion with identical end states and no console errors.

**AC4 — guided scenarios.** Each scenario is a tab; each step is a real button dispatching real actions, enabled strictly in order. Starting a scenario dispatches `reset` first — confirmed by observing `settled: 0` at the start of scenario 2 after scenario 1 had settled seven decisions. Free play is available at all times, including after a walkthrough finishes.

**AC5 — light theme, intro, marker.** Single light palette, one accent (indigo `#4f46e5`); no dark styles anywhere. `PROTOTYPE — THROWAWAY` pill and the intro paragraph naming the question sit above the variant region in all three.

## Changed while building

The side-thread affordance started out inside the answer controls, which meant it only appeared when its anchor node was the top card of the queue — the thread was unreachable in variant B under most states, and unreachable in variant A once its anchor settled. It is now its own fragment rendered on any node in any status, which is what "branch a thread off any node" actually requires.

## Where the brief's model felt wrong

- **Reopen and answer are one operation, and the brief treats them as two.** Nothing distinguishes them except whether an answer already existed. Modelling them separately would have produced two code paths with the same cascade logic. Worth knowing before this shape goes into real code.
- **Transitive staleness leaves a state the brief doesn't name.** Reopening cascades to *every* descendant, so a grandchild ends up stale while its parent is also stale — stale but not answerable. I called it `stale-blocked`. The alternative (stale only the direct dependents, propagate on each re-answer) shows the cascade travelling one layer at a time, which is prettier but conservatively wrong: it leaves a grandchild reading as settled on an answer whose premise is already in doubt. The current choice is the honest one, but it means a single reopen can grey out most of the map at once, which felt heavier in the map variant than in the other two.
- **Re-confirming with an unchanged answer still clears staleness without re-validating downstream.** That is what makes recovery feel good in scenario 2, but it is a real modelling claim: it assumes the only thing that can invalidate a decision is a changed ancestor answer.
- **Fog is not a status so much as a mask over one.** A fogged node has a depth, prerequisites and options like any other; fog only hides them. That worked out cleanly, but it does mean fog is reversible — folding the side thread sends `D16` back into fog after it had graduated, which is correct by the model and may or may not be what a real session should show.
- **Variant A's side thread is the weakest of the three.** The brief asked for a branched overlay or sub-map; what the dock panel plus a highlighted anchor node gives you is closer to variant B's drawer than to anything spatial. A genuine sub-map would want the thread's turns laid out as their own small graph hanging off the anchor. Worth deciding whether that matters before judging A against C on side-thread handling, because C's margin threads are the strongest treatment here by some distance.

## Left undone

- No persistence, by design — reload restarts the session (the variant choice is the only thing in the URL).
- Nothing was committed to git, and no path outside this directory was touched.
