# Grind dashboard — UI prototypes

Three radically different single-file renderings of one shared fixture state,
built to the prototyping plan in `docs/specs/2026-07-19-grind-dashboard-renderer.md`
(input State shape per `docs/specs/2026-07-19-event-sourced-grind-runtime.md`).
Open `index.html` to switch between them from one page; each variation also
stands alone from `file://`.

## The chosen design

**Variation A — Control Room**, amended with the mission-brief header line from
Variation C (the topbar carries `state.mission` beneath the title). Recorded in
the renderer spec's UX section; B and C are retained for reference.

## The fixture

`fixture-state.json` is one fold `State` built to exercise everything the UX
section requires:

- **All nine statuses** — items cover queued / in-progress / pr-open /
  in-review / merged / done / blocked / waiting-human; `standing-down` appears
  as the status of Lane 6 (it is lane-only vocabulary per the runtime spec).
- **All four parking kinds** — discovered-work, human-gated, later-wave, deferred.
- **Active review with findings and open threads** — `wgclw.30.1` (codex round 2,
  3 open threads, 1 wont-fix, 4 findings with severities + dispositions).
- **A stalemate** — `wgclw.31.2` (codex round 4, 0 open threads, `stalemate:
  true`, waiting-human with a `why`, mirrored in the attention list).
- **Paused-banner variant flag** — `pause.paused: true` with reason and a
  resume checklist. To see the running variant, flip `paused` to `false` in an
  inlined `STATE` block (or in the fixture before re-splicing).
- **Seven lanes** (≥6) to exercise horizontal overflow, plus long titles.
- **LESSON and ERROR observations** — two lessons feed the lessons panel; the
  ERROR observation's attention entry is in the attention list, as the fold
  would have placed it.
- **Serialization probe** — `disc-3`'s title contains the literal text
  `</script>`. In `fixture-state.json` it is raw (so CI can prove the renderer
  escapes it); in each HTML it is inlined with every `<` escaped as the
  JSON escape `\\u003c`.
  All three dashboards render it as inert text — view-source on the state
  block shows the escaped form.
- `merged_ledger` / `closed_ledger` are present for State fidelity; per UX
  requirement 6 **no variation renders a Merged or Closed panel**.

## Variation A — Control Room (`variation-a.html`)

**Thesis:** the dashboard is a wall monitor — at a glance you should read the
whole grind from across the room. **Axes:** column-per-lane kanban ·
icon-forward (large status glyphs, colored column-top strips, small text
pills) · control-room density (12.5px base, tight cards, everything visible at
once: findings, blockers, observations tickertape). Parking, lessons, and the
observation log dock in a three-panel strip under the board. Collapsed lanes
are exactly half width (170px vs 340px) and show icon + id + title + PR# only.

## Variation B — Ops Review (`variation-b.html`)

**Thesis:** the dashboard is a document you read top-to-bottom over coffee —
calm beats dense, words beat glyphs. **Axes:** row-per-lane horizontal
swimlanes · text-forward (status words in small caps, prose review lines,
spelled-out agent ownership; icons accompany, never carry alone) · calm and
spacious (15px base, serif headings, generous whitespace). Each lane's item
strip scrolls horizontally on overflow rather than squeezing cards; the
observation log tucks into a `<details>` disclosure; lessons render as
margin-note quotes. Collapsed lanes compress to a ~half-height band of slim
chips (icon + id + title + PR#) — the row-layout analogue of the 50% rule.

## Variation C — Mission Log (`variation-c.html`)

**Thesis:** the dashboard is a mission brief plus a ship's log — summarize
first, drill on demand. **Axes:** summary-grid with drill-down · neither
column- nor row-board: a clickable stat-deck (all nine statuses counted,
click to filter the register), an operations register grouped by lane with
per-item drill-down drawers (findings table, review detail, related log
entries), and a chronological observation timeline in the rail. Status lamps
(PAUSED / ATTENTION ×N / RUNNING) headline the brief. Collapsed lane groups
show half-width slim rows (icon + id + title + PR#). Medium density,
monospace accents.

## Shared contract behavior (all three)

- Light theme only; self-contained `file://` pages; no fetches, no CDNs.
- Last-generated timestamp comes from `state.last_generated` (the log's last
  event ts), never a wall clock.
- Red ATTENTION banner, hidden when empty; pause banner when `pause.paused`.
- Horizontal scroll on overflow (A: the board; B: each lane's item strip;
  C: the register table) — lanes never squeeze into illegibility.
- Unknown statuses degrade to a neutral gray pill + question-mark icon; the
  board never breaks.
- 15s auto-refresh with a visible toggle and countdown; the reload is a no-op
  `location.reload()` in these static prototypes.
- Per-lane collapse toggles on **every** lane; `done` lanes auto-collapse by
  default. Collapse and refresh prefs persist in `localStorage`, keyed per
  variation (`grindproto.{a,b,c}.*`) so exploring one never disturbs another.
- Review-thread pills read as full labels ("1 open thread" / "N open threads")
  with `review.detail` in the `title` tooltip; round badges never render on
  `done` items (a high round count survives as a LESSON).
- PR links derive from the repo slug; `wgclw.32.1` demonstrates the explicit
  `url` override; all hrefs are scheme-checked.
