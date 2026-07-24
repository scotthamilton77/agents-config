"""`State -> dashboard.html`: a pure, deterministic projection.

`render_dashboard` never touches the wall clock or the filesystem -- it is a
straight `State -> str` function (renderer spec: "a pure function of folded
state. Same state, same bytes."). All interactivity (lane collapse, the
auto-refresh toggle, review-detail tooltips) is client-side JS baked into the
static template below; the only per-render input is the JSON payload spliced
into the inlined `<script id="grind-dashboard">` block, with every `<` escaped as
`\\u003c` per the serialization contract (renderer spec, "Contract") so a
work-item title containing literal HTML can never break out of the block.

The renderer only lays out typed fields already computed by the fold --
review counts, item/lane status, parking reason -- it never re-derives domain
facts from prose (renderer spec, "Input"). Two fields the reference prototype
(`docs/prototypes/grind-dashboard/variation-a.html`) shows but `State` has no
typed home for are deliberately dropped here rather than invented:

- Per-finding detail (severity/summary/disposition list). `review_verdict`'s
  payload carries `findings[]`, but the fold (`grind.fold._h_review_verdict`)
  only derives `open_threads`/`wont_fix_count` from it and does not retain
  the list on `ItemReview` -- there is nothing to project. The required
  review affordances (round badge hidden at done, stalemate pill, full-label
  open-threads pill with a `detail` tooltip, wont-fix count) do not need it.
- Per-item free-text notes and a `waiting-human` "why" box. `Item` carries no
  generic `note` field, and item-level "why" text is not stored on the item
  as an attention entry it (`fold._h_item_waiting_human` folds it into
  `state.attention`) -- the attention banner already surfaces it, so an
  item-level echo would be domain re-derivation, not layout. `blocked_note`
  *is* a typed field and is rendered.
"""

from __future__ import annotations

import json

from grind.derive import lane_status
from grind.model import (
    AttentionEntry,
    Item,
    ItemReview,
    JsonValue,
    Lane,
    Observation,
    PrRef,
    State,
)
from grind.serialize import park_fields


def _pr_json(pr: PrRef | None) -> JsonValue:
    if pr is None:
        return None
    return {"number": pr.number, "url": pr.url}


def _review_json(review: ItemReview) -> JsonValue:
    # `round is None` means no review round has ever landed on this item --
    # the fold's default `ItemReview()`, not "round zero". Rendering it would
    # fabricate a badge for work that was never reviewed.
    if review.round is None:
        return None
    return {
        "round": review.round,
        "kind": review.kind,
        "detail": review.detail,
        "stalemate": review.stalemate,
        "open_threads": review.open_threads,
        "wont_fix_count": review.wont_fix_count,
    }


def _item_json(item: Item) -> JsonValue:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "pr": _pr_json(item.pr),
        "review": _review_json(item.review),
        "blocked_on": list(item.blocked_on),
        "blocked_note": item.blocked_note,
    }


def _lane_json(state: State, lane: Lane) -> JsonValue:
    queue = [state.items[item_id] for item_id in lane.item_ids if item_id in state.items]
    return {
        "id": lane.id,
        "name": lane.name,
        "agent": lane.agent,
        "model": lane.model,
        "effort": lane.effort,
        "status": lane_status(state, lane),
        "queue": [_item_json(item) for item in queue],
    }


def _attention_json(entry: AttentionEntry) -> JsonValue:
    return {"text": entry.text, "item": entry.item}


def _observation_json(obs: Observation) -> JsonValue:
    return {"ts": obs.ts, "level": obs.level, "message": obs.message, "item": obs.item}


def _lesson_json(obs: Observation) -> JsonValue:
    return {"ts": obs.ts, "message": obs.message, "item": obs.item}


def _parking_json(item_id: str, item: Item) -> JsonValue:
    return {"id": item_id, "title": item.title, **park_fields(item.parked)}


def _dashboard_state_json(state: State) -> dict[str, JsonValue]:
    return {
        "title": state.title,
        "repo": state.repo,
        "mission": state.mission,
        "last_generated": state.last_event_ts,
        "pause": {
            "paused": state.paused,
            "reason": state.pause_reason,
            "resume_checklist": list(state.resume_checklist),
        },
        "attention": [_attention_json(a) for a in state.attention],
        "lanes": [_lane_json(state, lane) for lane in state.lanes.values()],
        "parking_lot": [_parking_json(i, item) for i, item in state.parking_lot().items()],
        "observations": [_observation_json(o) for o in state.observations],
        "lessons": [_lesson_json(o) for o in state.lessons],
    }


def _inline_state_json(payload: dict[str, JsonValue]) -> str:
    """The serialization contract: a real JSON serializer, every `<` escaped
    as `\\u003c` -- a raw splice of a work-item title carrying `</script>`
    would close the block early and execute (renderer spec, "Contract")."""
    text = json.dumps(payload, sort_keys=True, allow_nan=False)
    return text.replace("<", "\\u003c")


def render_dashboard(state: State) -> str:
    """The self-contained `dashboard.html` for `state` -- deterministic:
    same `State`, same bytes (no wall-clock reads anywhere in this path)."""
    state_json = _inline_state_json(_dashboard_state_json(state))
    return _PAGE_TEMPLATE.replace("__GRIND_STATE_JSON__", state_json)


_STYLE = """
:root {
  --bg: #eef0f4; --panel: #ffffff; --panel-2: #f4f6f9; --border: #d3d9e1;
  --text: #171c24; --text-dim: #4d5766; --accent: #2f5fd6; --red: #c62828;
  --lane-w: 340px; --lane-w-collapsed: 170px;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 12.5px; line-height: 1.45; padding: 14px 18px 24px;
}
a { color: var(--accent); }
a:focus-visible, button:focus-visible, input:focus-visible + span {
  outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px;
}
.st-queued        { --c: #6e7681; --cbg: rgba(110,118,129,0.13); }
.st-in-progress   { --c: #2f5fd6; --cbg: rgba(47,95,214,0.12); }
.st-pr-open       { --c: #7c3aed; --cbg: rgba(124,58,237,0.12); }
.st-in-review     { --c: #9a6c00; --cbg: rgba(154,108,0,0.13); }
.st-merged        { --c: #1e8e3e; --cbg: rgba(30,142,62,0.12); }
.st-done          { --c: #0f7b3f; --cbg: rgba(15,123,63,0.18); }
.st-blocked       { --c: #c62828; --cbg: rgba(198,40,40,0.12); }
.st-waiting-human { --c: #b45309; --cbg: rgba(180,83,9,0.13); }
.st-standing-down { --c: #64748b; --cbg: rgba(100,116,139,0.16); }
.st-unknown       { --c: #8a94a3; --cbg: rgba(138,148,163,0.14); }
.icon { vertical-align: -2px; }
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; margin-bottom: 12px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px;
}
.brand { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.topbar .mission {
  flex-basis: 100%; margin: 2px 0 0; color: var(--text-dim); font-size: 12px;
  line-height: 1.45; max-width: 1000px;
}
.topbar .mission.hidden { display: none; }
.brand .sigil {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700; font-size: 11px; letter-spacing: 1px;
  background: #171c24; color: #fff; border-radius: 4px; padding: 3px 7px;
}
h1 {
  font-size: 17px; margin: 0; font-weight: 650; letter-spacing: 0.1px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.topmeta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.repo-chip, .gen-chip {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; color: var(--text-dim);
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; padding: 3px 7px;
}
.refresh-control {
  display: flex; align-items: center; gap: 7px;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; padding: 4px 9px;
}
.refresh-control label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
#refresh-status { font-variant-numeric: tabular-nums; min-width: 74px; color: var(--text-dim); }
#pause-banner, #attention-banner {
  display: none; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; border-left-width: 5px;
}
#pause-banner.show, #attention-banner.show { display: block; }
#pause-banner { background: #fff7e6; border: 1px solid #d9a514; color: #6b4e00; }
#attention-banner { background: #fdeaea; border: 1px solid var(--red); color: #7a1a1a; }
#pause-banner h2, #attention-banner h2 {
  margin: 0 0 6px; font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
}
#pause-banner h2 { color: #8a6500; }
#attention-banner h2 { color: var(--red); }
#pause-banner ol, #attention-banner ul { margin: 0; padding-left: 20px; }
#pause-banner li, #attention-banner li { margin-bottom: 4px; }
.attn-item-chip {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10.5px;
  background: #fff; border: 1px solid rgba(198,40,40,0.4); border-radius: 3px;
  padding: 0 5px; margin-left: 5px;
}
.board { display: flex; gap: 10px; overflow-x: auto; align-items: stretch; padding-bottom: 10px; margin-bottom: 14px; }
.lane {
  flex: 0 0 var(--lane-w); min-width: var(--lane-w);
  background: var(--panel); border: 1px solid var(--border); border-top: 3px solid var(--c, var(--border));
  border-radius: 8px; display: flex; flex-direction: column;
}
.lane.collapsed { flex-basis: var(--lane-w-collapsed); min-width: var(--lane-w-collapsed); background: var(--panel-2); }
.lane-head { display: flex; align-items: center; gap: 7px; padding: 9px 10px 7px; }
.lane-head .lane-icon { color: var(--c); flex: none; display: inline-flex; }
.lane-titles { min-width: 0; flex: 1 1 auto; }
.lane-titles h2 {
  margin: 0; font-size: 13px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.lane-sub { color: var(--text-dim); font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lane.collapsed .lane-sub { display: none; }
.lane.collapsed .lane-head .pill { display: none; }
.lane-toggle {
  flex: none; border: 1px solid var(--border); background: var(--panel); color: var(--text-dim);
  border-radius: 5px; width: 22px; height: 22px; cursor: pointer; font-size: 13px; padding: 0;
}
.lane-toggle:hover { background: var(--panel-2); color: var(--text); }
.lane-body { padding: 2px 10px 10px; display: flex; flex-direction: column; gap: 8px; }
.queue-empty { color: var(--text-dim); font-size: 11.5px; font-style: italic; padding: 4px 2px; }
.pill {
  display: inline-flex; align-items: center; gap: 4px; padding: 1px 7px; border-radius: 999px;
  font-size: 10.5px; font-weight: 600; background: var(--cbg); color: var(--c); white-space: nowrap;
}
.pill-round { background: rgba(47,95,214,0.10); color: var(--accent); font-variant-numeric: tabular-nums; }
.pill-round.is-stalemate { background: rgba(198,40,40,0.12); color: var(--red); }
.pill-stalemate { background: var(--red); color: #fff; text-transform: uppercase; letter-spacing: 0.6px; font-size: 9.5px; }
.pill-threads { background: rgba(154,108,0,0.12); color: #9a6c00; cursor: help; border-bottom: 1px dotted #9a6c00; }
.pill-wontfix { background: rgba(110,118,129,0.14); color: #525c69; }
.chip {
  display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border);
  background: var(--panel-2); color: var(--text-dim);
}
.chip-blocker { border-color: rgba(198,40,40,0.45); color: var(--red); background: rgba(198,40,40,0.07); }
.park {
  font-family: inherit; font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
  text-transform: uppercase; border-radius: 3px; padding: 2px 6px;
}
/* Coloured by axis + category, not per reason: the eye's question of a
   parking lot is "why is this stuck", and the answer has three shapes. */
.park-machine    { background: rgba(154,108,0,0.13); color: #9a6c00; }
.park-human      { background: rgba(190,18,60,0.11); color: #be123c; }
.park-scheduling { background: rgba(67,56,202,0.11); color: #4338ca; }
.park-unknown    { background: rgba(138,148,163,0.15); color: #6e7681; }
.item { border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: 6px; padding: 7px 9px; background: #fff; }
.item-top { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
.item-top .icon { color: var(--c); flex: none; }
.item-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10.5px;
  color: var(--text-dim); flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pr-link { font-size: 11px; text-decoration: none; font-variant-numeric: tabular-nums; flex: none; }
.pr-link:hover { text-decoration: underline; }
.pr-plain { color: var(--text-dim); font-size: 11px; }
.item-title { font-weight: 600; font-size: 12px; margin-bottom: 5px; overflow-wrap: break-word; }
.item-badges { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.item-note { color: var(--text-dim); font-size: 11px; margin-top: 5px; }
.item-blockers { margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; font-size: 10.5px; color: var(--text-dim); }
.item-slim { display: flex; align-items: center; gap: 5px; padding: 4px 2px; border-bottom: 1px dashed var(--border); }
.item-slim:last-child { border-bottom: none; }
.item-slim .icon { color: var(--c); flex: none; }
.item-slim .item-id { flex: none; max-width: 62px; }
.item-slim .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.item-slim .pr-link, .item-slim .pr-plain { font-size: 10.5px; }
.dock { display: flex; gap: 10px; flex-wrap: wrap; }
.dock-panel { flex: 1 1 300px; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.dock-panel h2 {
  margin: 0 0 8px; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase;
  color: var(--text-dim); display: flex; align-items: center; gap: 7px;
}
.count-tag {
  font-size: 10px; font-weight: 700; background: var(--panel-2); border: 1px solid var(--border);
  color: var(--text-dim); padding: 0 7px; border-radius: 999px;
}
.obs-list, .parking-list, .lesson-list { list-style: none; margin: 0; padding: 0; }
.obs-list { max-height: 170px; overflow-y: auto; }
.obs-list li {
  display: flex; gap: 7px; align-items: baseline; padding: 3px 0; border-bottom: 1px dashed rgba(0,0,0,0.06); font-size: 11px;
}
.obs-list li:last-child { border-bottom: none; }
.obs-list .ts {
  flex: none; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9.5px; color: #8a94a3;
}
.lvl { flex: none; font-size: 9px; font-weight: 800; letter-spacing: 0.5px; border-radius: 3px; padding: 1px 5px; }
.lvl-INFO { background: rgba(47,95,214,0.11); color: var(--accent); }
.lvl-WARN { background: rgba(154,108,0,0.13); color: #9a6c00; }
.lvl-ERROR { background: rgba(198,40,40,0.13); color: var(--red); }
.lvl-LESSON { background: rgba(15,118,110,0.13); color: #0f766e; }
.parking-list li {
  display: flex; gap: 8px; align-items: baseline; padding: 6px 8px; border: 1px solid var(--border);
  border-radius: 6px; margin-bottom: 6px; background: #fff;
}
.parking-list .pt { flex: 1 1 auto; min-width: 0; }
.parking-list .pt .pid {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10px; color: var(--text-dim); margin-right: 6px;
}
.parking-list .pn { display: block; color: var(--text-dim); font-size: 10.5px; margin-top: 2px; }
.lesson-list li {
  padding: 6px 8px; border-left: 3px solid #0f766e; background: rgba(15,118,110,0.06);
  border-radius: 0 6px 6px 0; margin-bottom: 6px; font-size: 11.5px;
}
.lesson-list .lts {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9.5px; color: #8a94a3; margin-right: 6px;
}
.lesson-list .litem {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10px; color: #0f766e;
}
"""

_SCRIPT = """
"use strict";

var STATE = __GRIND_STATE_JSON__;

var KNOWN_STATUSES = [
  "queued", "in-progress", "pr-open", "in-review", "merged",
  "done", "blocked", "waiting-human", "standing-down"
];
function statusCls(status) {
  var k = String(status || "").toLowerCase();
  return KNOWN_STATUSES.indexOf(k) >= 0 ? "st-" + k : "st-unknown";
}
var ICONS = {
  "queued": '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>',
  "in-progress": '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M8 2.5A5.5 5.5 0 0 1 8 13.5Z" fill="currentColor"/>',
  "pr-open": '<circle cx="5" cy="4.5" r="2" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
    '<circle cx="5" cy="11.5" r="2" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
    '<circle cx="11" cy="8" r="2" fill="currentColor"/>' +
    '<path d="M5 6.5v3M6.8 8h2.2" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  "in-review": '<path d="M1.8 8C4 4.8 12 4.8 14.2 8 12 11.2 4 11.2 1.8 8Z" fill="none" ' +
    'stroke="currentColor" stroke-width="1.8"/><circle cx="8" cy="8" r="1.9" fill="currentColor"/>',
  "merged": '<circle cx="5" cy="4" r="1.9" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
    '<circle cx="5" cy="12" r="1.9" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
    '<circle cx="11.5" cy="12" r="1.9" fill="currentColor"/>' +
    '<path d="M5 6v4M5 9.5c0 1.6 2 1 4 1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  "done": '<circle cx="8" cy="8" r="6.4" fill="currentColor"/>' +
    '<path d="M5.1 8.3l2 2 3.8-4.2" fill="none" stroke="#ffffff" stroke-width="1.9" ' +
    'stroke-linecap="round" stroke-linejoin="round"/>',
  "blocked": '<circle cx="8" cy="8" r="5.8" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M4.2 11.8 11.8 4.2" stroke="currentColor" stroke-width="2"/>',
  "waiting-human": '<circle cx="8" cy="5" r="2.5" fill="currentColor"/>' +
    '<path d="M3.2 13.4c.4-2.8 2.4-4.2 4.8-4.2s4.4 1.4 4.8 4.2" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  "standing-down": '<path d="M4.5 14V2.6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
    '<path d="M4.5 3.2h7.6l-2.2 2.9 2.2 2.9H4.5Z" fill="currentColor"/>',
  "unknown": '<circle cx="8" cy="8" r="5.8" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M6.4 6.3c.3-1.1 1-1.7 1.7-1.7 1 0 1.7.6 1.7 1.5 0 1.3-1.7 1.5-1.7 2.8" fill="none" ' +
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>' +
    '<circle cx="8.1" cy="11.5" r="1" fill="currentColor"/>'
};
function iconName(status) {
  var k = String(status || "").toLowerCase();
  return KNOWN_STATUSES.indexOf(k) >= 0 ? k : "unknown";
}
function iconSvg(status, size) {
  var s = size || 14;
  return '<svg class="icon" width="' + s + '" height="' + s + '" viewBox="0 0 16 16" ' +
    'aria-hidden="true" focusable="false">' + (ICONS[iconName(status)] || ICONS.unknown) + '</svg>';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function text(s) { return s === null || s === undefined ? "" : String(s); }

function safeHref(url) {
  try {
    // Return the RESOLVED href, not the input: a relative override like
    // "/org/repo/pull/7" passes the scheme check via the GitHub base but
    // would otherwise resolve against this file:// page when clicked.
    var resolved = new URL(url, "https://github.com");
    return (resolved.protocol === "https:" || resolved.protocol === "http:") ? resolved.href : null;
  } catch (e) { return null; }
}
// Explicit `pr.url` wins (scheme-checked); else derive from the repo slug;
// else no link at all -- plain-text number (renderer spec, "Contract").
function prUrl(pr, repo) {
  if (!pr) return null;
  if (typeof pr.url === "string" && pr.url.trim() !== "") {
    var safe = safeHref(pr.url.trim());
    if (safe) return safe;
  }
  if (repo) return "https://github.com/" + repo + "/pull/" + pr.number;
  return null;
}
function prLink(pr, repo) {
  if (!pr || pr.number === null || pr.number === undefined) return "";
  var url = prUrl(pr, repo);
  var label = "#" + escapeHtml(pr.number);
  return url
    ? '<a class="pr-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + label + '</a>'
    : '<span class="pr-plain">' + label + '</span>';
}

// Round badge hides at `done` (a high round count survives as a LESSON, not
// a badge on finished work); open-threads reads as a full label with the
// review detail as its tooltip; wont-fix rides its own pill.
function reviewBits(review, itemStatus) {
  if (!review) return "";
  var out = "";
  var stale = !!review.stalemate;
  if (String(itemStatus).toLowerCase() !== "done") {
    out += '<span class="pill pill-round' + (stale ? " is-stalemate" : "") + '">' +
      escapeHtml(review.kind || "review") + " \\u00b7 round " + (Number(review.round) || 0) + "</span>";
  }
  if (stale) out += '<span class="pill pill-stalemate">stalemate</span>';
  var n = Number(review.open_threads) || 0;
  if (n > 0) {
    var label = n === 1 ? "1 open thread" : n + " open threads";
    var tip = review.detail ? ' title="' + escapeHtml(review.detail) + '"' : "";
    out += '<span class="pill pill-threads"' + tip + ">" + label + "</span>";
  }
  var wf = Number(review.wont_fix_count) || 0;
  if (wf > 0) out += '<span class="pill pill-wontfix">' + wf + (wf === 1 ? " wont-fix" : " wont-fix items") + "</span>";
  return out;
}

// The park vocabulary lives in one place (grind.model.PARK_REASONS) and the
// snapshot carries the derived axis/category, so this holds no copy of it.
function parkChip(p) {
  var cls = "park-unknown";
  if (p.axis === "scheduling") cls = "park-scheduling";
  else if (p.category === "machine") cls = "park-machine";
  else if (p.category === "human") cls = "park-human";
  return '<span class="park ' + cls + '">' + escapeHtml(p.reason || "unknown") + "</span>";
}

// Mission is a typed JsonValue, not guaranteed to be a plain string --
// render whatever shape it is without parsing its prose.
function missionText(m) {
  if (typeof m === "string") return m;
  if (m && typeof m === "object") {
    if (typeof m.goal === "string") {
      var oos = typeof m.out_of_scope === "string" ? " Out of scope: " + m.out_of_scope : "";
      return m.goal + oos;
    }
    try { return JSON.stringify(m); } catch (e) { return ""; }
  }
  return "";
}

// ---- per-lane collapse, persisted; a `done` lane auto-collapses by default ----
var LS_COLLAPSE = "grind.dashboard.collapsed.v1";
var collapsePrefs = {};
try { collapsePrefs = JSON.parse(localStorage.getItem(LS_COLLAPSE) || "{}") || {}; }
catch (e) { collapsePrefs = {}; }
function isCollapsed(lane) {
  if (Object.prototype.hasOwnProperty.call(collapsePrefs, lane.id)) return !!collapsePrefs[lane.id];
  return String(lane.status).toLowerCase() === "done";
}
function toggleLane(id) {
  var lane = (STATE.lanes || []).find(function (l) { return l.id === id; });
  if (!lane) return;
  collapsePrefs[id] = !isCollapsed(lane);
  try { localStorage.setItem(LS_COLLAPSE, JSON.stringify(collapsePrefs)); } catch (e) { /* no-op */ }
  renderBoard();
}

function renderItemExpanded(q) {
  var cls = statusCls(q.status);
  var html = '<article class="item ' + cls + '">' +
    '<div class="item-top">' + iconSvg(q.status) +
    '<span class="item-id">' + escapeHtml(q.id) + "</span>" + prLink(q.pr, STATE.repo) + "</div>" +
    '<div class="item-title">' + escapeHtml(text(q.title) || q.id) + "</div>" +
    '<div class="item-badges"><span class="pill ' + cls + '">' + escapeHtml(q.status) + "</span>" +
    reviewBits(q.review, q.status) + "</div>";
  if (q.blocked_note) html += '<div class="item-note">' + escapeHtml(q.blocked_note) + "</div>";
  if (q.blocked_on && q.blocked_on.length) {
    html += '<div class="item-blockers">blocked on ' +
      q.blocked_on.map(function (b) {
        return '<span class="chip chip-blocker">' + escapeHtml(b) + "</span>";
      }).join(" ") + "</div>";
  }
  return html + "</article>";
}

// Collapsed anatomy: status icon + work-item id + title + PR# only.
function renderItemSlim(q) {
  return '<div class="item-slim ' + statusCls(q.status) + '">' + iconSvg(q.status, 12) +
    '<span class="item-id">' + escapeHtml(q.id) + "</span>" +
    '<span class="t" title="' + escapeHtml(text(q.title) || q.id) + '">' +
    escapeHtml(text(q.title) || q.id) + "</span>" + prLink(q.pr, STATE.repo) + "</div>";
}

function renderBoard() {
  var board = document.getElementById("board");
  board.innerHTML = "";
  (STATE.lanes || []).forEach(function (lane) {
    var collapsed = isCollapsed(lane);
    var cls = statusCls(lane.status);
    var sec = document.createElement("section");
    sec.className = "lane " + cls + (collapsed ? " collapsed" : "");
    sec.setAttribute("aria-label", text(lane.name) || lane.id);
    var bodyId = "lane-body-" + escapeHtml(lane.id);
    var items = lane.queue || [];
    var body = items.length
      ? items.map(function (q) { return collapsed ? renderItemSlim(q) : renderItemExpanded(q); }).join("")
      : '<div class="queue-empty">queue empty</div>';
    sec.innerHTML =
      '<header class="lane-head">' +
      '<span class="lane-icon">' + iconSvg(lane.status, 16) + "</span>" +
      '<div class="lane-titles"><h2>' + escapeHtml(text(lane.name) || lane.id) + "</h2>" +
      '<div class="lane-sub">' + escapeHtml(text(lane.agent)) + " \\u00b7 " +
      escapeHtml(text(lane.model)) + " \\u00b7 " + escapeHtml(text(lane.effort)) + " effort</div></div>" +
      '<span class="pill ' + cls + '">' + escapeHtml(lane.status) + "</span>" +
      '<button type="button" class="lane-toggle" aria-expanded="' + (collapsed ? "false" : "true") + '" ' +
      'aria-controls="' + bodyId + '" title="' + (collapsed ? "Expand " : "Collapse ") +
      escapeHtml(text(lane.name) || lane.id) + '" data-lane="' + escapeHtml(lane.id) + '">' +
      (collapsed ? "\\u00bb" : "\\u00ab") + "</button>" +
      "</header>" +
      '<div class="lane-body" id="' + bodyId + '">' + body + "</div>";
    board.appendChild(sec);
  });
  board.querySelectorAll(".lane-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () { toggleLane(btn.getAttribute("data-lane")); });
  });
}

function renderDock() {
  var obs = (STATE.observations || []).slice().reverse();
  document.getElementById("obs-count").textContent = obs.length;
  document.getElementById("obs-list").innerHTML = obs.map(function (o) {
    return "<li><span class='ts'>" + escapeHtml(text(o.ts).replace("T", " ")) + "</span>" +
      '<span class="lvl lvl-' + escapeHtml(o.level || "INFO") + '">' + escapeHtml(o.level || "INFO") + "</span>" +
      "<span>" + escapeHtml(o.message) +
      (o.item ? ' <span class="chip">' + escapeHtml(o.item) + "</span>" : "") + "</span></li>";
  }).join("");

  var parked = STATE.parking_lot || [];
  document.getElementById("park-count").textContent = parked.length;
  document.getElementById("parking-list").innerHTML = parked.map(function (p) {
    return "<li>" + parkChip(p) +
      '<span class="pt"><span class="pid">' + escapeHtml(p.id) + "</span>" + escapeHtml(text(p.title) || p.id) +
      (p.note ? '<span class="pn">' + escapeHtml(p.note) + "</span>" : "") + "</span></li>";
  }).join("");

  var lessons = STATE.lessons || [];
  document.getElementById("lesson-count").textContent = lessons.length;
  document.getElementById("lesson-list").innerHTML = lessons.map(function (l) {
    return "<li><span class='lts'>" + escapeHtml(text(l.ts)) + "</span>" +
      (l.item ? '<span class="litem">' + escapeHtml(l.item) + "</span> " : "") +
      escapeHtml(l.message) + "</li>";
  }).join("");
}

function render() {
  document.title = (STATE.title || "Grind") + " \\u2014 Control Room";
  document.getElementById("title").textContent = STATE.title || "Grind";
  document.getElementById("repo").textContent = STATE.repo || "no repo slug";
  document.getElementById("last-generated").textContent = "log @ " + (STATE.last_generated || "\\u2014");

  var missionEl = document.getElementById("mission");
  var mission = missionText(STATE.mission);
  if (mission) { missionEl.textContent = mission; missionEl.classList.remove("hidden"); }
  else { missionEl.classList.add("hidden"); }

  var pause = STATE.pause;
  var pb = document.getElementById("pause-banner");
  if (pause && pause.paused) {
    pb.classList.add("show");
    document.getElementById("pause-reason").textContent = pause.reason || "";
    document.getElementById("pause-checklist").innerHTML =
      (pause.resume_checklist || []).map(function (c) { return "<li>" + escapeHtml(c) + "</li>"; }).join("");
  } else { pb.classList.remove("show"); }

  var attn = STATE.attention || [];
  var ab = document.getElementById("attention-banner");
  var al = document.getElementById("attention-list");
  if (attn.length) {
    ab.classList.add("show");
    al.innerHTML = attn.map(function (a) {
      return "<li>" + escapeHtml(a.text) +
        (a.item ? '<span class="attn-item-chip">' + escapeHtml(a.item) + "</span>" : "") + "</li>";
    }).join("");
  } else { ab.classList.remove("show"); al.innerHTML = ""; }

  renderBoard();
  renderDock();
}

render();

// ---- auto-refresh: 15s, visible toggle, persisted ----
var REFRESH_SECONDS = 15;
var LS_REFRESH = "grind.dashboard.autorefresh.v1";
var toggle = document.getElementById("refresh-toggle");
var statusEl = document.getElementById("refresh-status");
var countdown = REFRESH_SECONDS, tickTimer = null;
function updateStatusText() { statusEl.textContent = toggle.checked ? ("on \\u2014 " + countdown + "s") : "off"; }
function startTicking() {
  if (tickTimer) clearInterval(tickTimer);
  countdown = REFRESH_SECONDS;
  updateStatusText();
  tickTimer = setInterval(function () {
    countdown -= 1;
    if (countdown <= 0) { location.reload(); return; }
    updateStatusText();
  }, 1000);
}
function stopTicking() {
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = null;
  updateStatusText();
}
var savedRefresh = null;
try { savedRefresh = localStorage.getItem(LS_REFRESH); } catch (e) { savedRefresh = null; }
toggle.checked = savedRefresh === null ? true : savedRefresh === "true";
toggle.addEventListener("change", function () {
  try { localStorage.setItem(LS_REFRESH, toggle.checked ? "true" : "false"); } catch (e) { /* no-op */ }
  if (toggle.checked) startTicking(); else stopTicking();
});
if (toggle.checked) startTicking(); else stopTicking();
"""

_PAGE_TEMPLATE = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grind — Control Room</title>
<style>{_STYLE}</style>
</head>
<body>

<header class="topbar">
  <div class="brand">
    <span class="sigil">GRIND</span>
    <h1 id="title">Grind</h1>
  </div>
  <div class="topmeta">
    <span class="repo-chip" id="repo"></span>
    <span class="gen-chip" id="last-generated"
      title="Timestamp of the last folded event -- the board is as fresh as its log, never fresher."></span>
    <div class="refresh-control">
      <label><input type="checkbox" id="refresh-toggle"><span>auto-refresh</span></label>
      <span id="refresh-status">off</span>
    </div>
  </div>
  <p class="mission hidden" id="mission"></p>
</header>

<div id="pause-banner" role="status">
  <h2>⏸ Grind paused</h2>
  <p class="reason" id="pause-reason"></p>
  <ol id="pause-checklist"></ol>
</div>

<div id="attention-banner" role="alert">
  <h2>⚠ Attention — needs the human</h2>
  <ul id="attention-list"></ul>
</div>

<main class="board" id="board" aria-label="Lanes"></main>

<div class="dock">
  <section class="dock-panel" aria-label="Observations">
    <h2>Observations <span class="count-tag" id="obs-count">0</span></h2>
    <ul class="obs-list" id="obs-list"></ul>
  </section>
  <section class="dock-panel" aria-label="Parking lot">
    <h2>Parking lot <span class="count-tag" id="park-count">0</span></h2>
    <ul class="parking-list" id="parking-list"></ul>
  </section>
  <section class="dock-panel" aria-label="Lessons learned">
    <h2>Lessons learned <span class="count-tag" id="lesson-count">0</span></h2>
    <ul class="lesson-list" id="lesson-list"></ul>
  </section>
</div>

<script id="grind-dashboard">
// SERIALIZATION CONTRACT: every less-than sign in the STATE literal below is
// escaped as \\u003c before splicing, exactly as `grind render` emits it --
// a raw splice of a work-item title carrying `\\u003c/script>` would close
// this block early and execute (the `<` is escaped here for the same reason).
{_SCRIPT}
</script>

</body>
</html>
"""
