#!/usr/bin/env python3
"""Build a self-contained Backlog Landscape HTML from the live bd export.

All layout coordinates (lanes, epic containers, node dots, edge bezier paths)
are precomputed here and injected as a JSON payload. The client only pans,
zooms, filters, searches, and runs the what-if token overlap — no client-side
layout.
"""
import argparse
import json
import math
import html
from collections import Counter, defaultdict

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--graph", required=True, help="build_graph.py output JSON path")
_parser.add_argument("--out", required=True, help="landscape HTML output path")
_args = _parser.parse_args()

SRC = _args.graph
OUT = _args.out

# ---- palette: Paul Tol 'muted' qualitative (colorblind-safe) + grey ---------
TRACK_COLORS = {
    "installer":         "#332288",  # indigo
    "prgroom":           "#44AA99",  # teal
    "workcli":           "#999933",  # olive
    "pdlc-orchestrator": "#CC6677",  # rose
    "holding-place":     "#DDCC77",  # sand
    "vizsuite":          "#AA4499",  # purple
    "skills-discipline": "#117733",  # green
    "portability":       "#88CCEE",  # cyan
    "ops-meta":          "#882255",  # wine
    "unknown":           "#999999",  # grey
}

# ---- geometry knobs ---------------------------------------------------------
MARGIN = 40
LANE_W = 2680
BAND_H = 34
CELL = 28
PAD = 9
HEADER = 24
GAP = 20
BOTTOM_PAD = 26
MIN_W = 150
R_BY_PRIO = {0: 11.0, 1: 9.0, 2: 7.5, 3: 6.0, 4: 5.0}
MILE_CODE = ["M0", "M1", "M2", "M3", "M4", "M5", "PORT"]


def prio_r(p):
    return R_BY_PRIO.get(p, 6.0)


def grid_cols(n):
    if n <= 1:
        return 1
    if n <= 4:
        return n
    return max(1, min(8, math.ceil(math.sqrt(n))))


def clean_title(t):
    # milestone titles: strip leading "Milestone " noise, keep readable
    t = t.replace("Milestone ", "")
    return t


def main():
    data = json.load(open(SRC))
    milestones = sorted(data["milestones"], key=lambda m: m["order"])
    beads = [b for b in data["beads"] if b.get("type") != "milestone"]
    by_id = {b["id"]: b for b in beads}
    epic_ids = {b["id"] for b in beads if b["type"] == "epic"}
    mile_ids = {m["id"] for m in milestones}
    mile_by_id = {m["id"]: m for m in milestones}

    def nearest_epic(bid):
        # Walk the parent chain past non-epic intermediates (feature/task)
        # to the nearest ancestor epic, so a grandchild like
        # agents-config-y9mm.6.1 (under feature agents-config-y9mm.6, under
        # epic agents-config-y9mm) still lands inside its epic container
        # instead of the detached loose-floater box.
        seen = set()
        cur = by_id.get(bid, {}).get("parent")
        while cur and cur not in seen:
            if cur in epic_ids:
                return cur
            seen.add(cur)
            cur = by_id.get(cur, {}).get("parent")
        return None

    # non-epic descendants (direct or through non-epic intermediates) per epic
    epic_children = defaultdict(list)
    for b in beads:
        if b["type"] == "epic":
            continue
        ep = nearest_epic(b["id"])
        if ep:
            epic_children[ep].append(b)

    # ---- assign each renderable bead to a lane key --------------------------
    LANE_ORDER = [m["id"] for m in milestones] + ["UNANCHORED"]

    def lane_key(b):
        m = b.get("milestone")
        return m if m in mile_ids else "UNANCHORED"

    lane_epics = defaultdict(list)      # lane -> [epic bead]
    lane_floaters = defaultdict(list)   # lane -> [non-epic float bead]
    for b in beads:
        lk = lane_key(b)
        if b["type"] == "epic":
            lane_epics[lk].append(b)
        else:
            if nearest_epic(b["id"]):
                continue  # lives inside its ancestor epic container
            lane_floaters[lk].append(b)

    # ---- build layout item boxes -------------------------------------------
    # An "item" is either an epic container or the loose-floater pseudo-box.
    nodes_out = []      # leaf + epic-child dots
    epics_out = []      # container rects
    center = {}         # id -> (cx, cy) for edge endpoints

    def size_container(kids):
        n = len(kids)
        cols = grid_cols(n)
        rows = max(1, math.ceil(n / cols)) if n else 1
        w = max(MIN_W, cols * CELL + 2 * PAD)
        h = HEADER + rows * CELL + PAD
        return cols, rows, w, h

    def size_floatbox(items):
        n = len(items)
        cols = grid_cols(n)
        rows = max(1, math.ceil(n / cols))
        w = max(MIN_W, cols * CELL + 2 * PAD)
        h = HEADER + rows * CELL + PAD
        return cols, rows, w, h

    lanes_out = []
    cursor_y = MARGIN
    canvas_w = MARGIN * 2 + LANE_W

    for lk in LANE_ORDER:
        if lk == "UNANCHORED":
            code, title, status = "—", "Unanchored (no milestone)", "open"
        else:
            m = mile_by_id[lk]
            code = MILE_CODE[m["order"]]
            title = clean_title(m["title"])
            status = m["status"]

        lane_x = MARGIN
        lane_y = cursor_y
        content_x0 = lane_x
        content_y0 = lane_y + BAND_H + 8

        # gather items: epics (by child-count desc) then float box
        items = []
        for e in sorted(lane_epics[lk], key=lambda e: -len(epic_children[e["id"]])):
            cols, rows, w, h = size_container(epic_children[e["id"]])
            items.append(("epic", e, cols, rows, w, h))
        floats = lane_floaters[lk]
        if floats:
            cols, rows, w, h = size_floatbox(floats)
            items.append(("float", floats, cols, rows, w, h))

        # shelf packing within LANE_W
        x = content_x0
        y = content_y0
        shelf_h = 0
        max_bottom = content_y0
        for kind, obj, cols, rows, w, h in items:
            if x + w > content_x0 + LANE_W and x > content_x0:
                x = content_x0
                y += shelf_h + GAP
                shelf_h = 0
            ix, iy = x, y

            if kind == "epic":
                e = obj
                tr = e.get("track") or "unknown"
                epics_out.append({
                    "id": e["id"], "x": ix, "y": iy, "w": w, "h": h,
                    "track": tr, "status": e["status"], "type": "epic",
                    "title": e["title"], "priority": e.get("priority", 2),
                    "labels": e.get("labels") or [], "desc": e.get("desc") or "",
                    "milestone": e.get("milestone"),
                    "closed": bool(e.get("closed_container")),
                    "cx": ix + w / 2, "cy": iy + h / 2,
                })
                center[e["id"]] = (ix + w / 2, iy + h / 2)
                # place child dots
                kids = epic_children[e["id"]]
                for i, k in enumerate(kids):
                    r = i // cols
                    c = i % cols
                    cx = ix + PAD + c * CELL + CELL / 2
                    cy = iy + HEADER + r * CELL + CELL / 2
                    nodes_out.append(mk_node(k, cx, cy, epic_id=e["id"]))
                    center[k["id"]] = (cx, cy)
            else:  # float box
                fx = {
                    "id": "__float__" + lk, "x": ix, "y": iy, "w": w, "h": h,
                    "track": "unknown", "status": "float", "type": "floatbox",
                    "title": "loose · no epic (%d)" % len(obj),
                    "priority": 2, "labels": [], "desc": "",
                    "milestone": None, "closed": False,
                    "cx": ix + w / 2, "cy": iy + h / 2,
                }
                epics_out.append(fx)
                for i, k in enumerate(obj):
                    r = i // cols
                    c = i % cols
                    cx = ix + PAD + c * CELL + CELL / 2
                    cy = iy + HEADER + r * CELL + CELL / 2
                    nodes_out.append(mk_node(k, cx, cy))
                    center[k["id"]] = (cx, cy)

            x = ix + w + GAP
            shelf_h = max(shelf_h, h)
            max_bottom = max(max_bottom, iy + h)

        lane_bottom = max_bottom + BOTTOM_PAD
        lane_h = lane_bottom - lane_y

        # per-lane counts
        lc = Counter()
        lane_beads = [b for b in beads if lane_key(b) == lk]
        for b in lane_beads:
            lc[b["status"]] += 1

        lanes_out.append({
            "key": lk, "code": code, "title": title, "status": status,
            "x": lane_x, "y": lane_y, "w": LANE_W, "bandH": BAND_H,
            "laneH": lane_h,
            "counts": {"open": lc.get("open", 0),
                       "in_progress": lc.get("in_progress", 0),
                       "blocked": lc.get("blocked", 0),
                       "deferred": lc.get("deferred", 0),
                       "closed": lc.get("closed", 0)},
            "total": len(lane_beads),
        })
        cursor_y = lane_bottom + GAP

    canvas_h = cursor_y + MARGIN

    # ---- edges (non parent-child only) -------------------------------------
    edges_out = []
    for e in data["edges"]:
        if e["type"] == "parent-child":
            continue
        a, b = e["from"], e["to"]
        if a not in center or b not in center:
            continue
        x1, y1 = center[a]
        x2, y2 = center[b]
        ta = track_of(by_id, a)
        tb = track_of(by_id, b)
        cross = ta != tb
        # quadratic bezier, control offset perpendicular to the chord
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1
        nx, ny = -dy / dist, dx / dist
        off = min(120, dist * 0.18)
        cx, cy = mx + nx * off, my + ny * off
        d = "M %.1f %.1f Q %.1f %.1f %.1f %.1f" % (x1, y1, cx, cy, x2, y2)
        edges_out.append({"from": a, "to": b, "type": e["type"],
                          "cross": cross, "d": d,
                          "tip": [round(x2, 1), round(y2, 1),
                                  round(cx, 1), round(cy, 1)]})

    # ---- global stats -------------------------------------------------------
    per_track = defaultdict(lambda: Counter())
    for b in beads:
        per_track[b.get("track") or "unknown"][b["status"]] += 1
    stats = {}
    for tr, c in per_track.items():
        stats[tr] = {"open": c.get("open", 0),
                     "in_progress": c.get("in_progress", 0),
                     "blocked": c.get("blocked", 0),
                     "deferred": c.get("deferred", 0),
                     "closed": c.get("closed", 0),
                     "total": sum(c.values())}

    status_totals = Counter(b["status"] for b in beads)

    payload = {
        "generated": data.get("generated"),
        "canvasW": canvas_w, "canvasH": canvas_h,
        "tracks": [{"name": t, "color": TRACK_COLORS[t]}
                   for t in TRACK_COLORS if t in {b.get("track") or "unknown" for b in beads}],
        "trackColors": TRACK_COLORS,
        "lanes": lanes_out,
        "epics": epics_out,
        "nodes": nodes_out,
        "edges": edges_out,
        "stats": stats,
        "statusTotals": dict(status_totals),
        "counts": {"beads": len(beads), "epics": len(epic_ids),
                   "edgesDrawn": len(edges_out)},
    }

    # sanity: payload must be valid json (round-trips)
    txt = json.dumps(payload, ensure_ascii=False)
    json.loads(txt)  # assert parses
    txt = txt.replace("</", "<\\/")  # safe inside <script> block

    html_doc = TEMPLATE.replace("__PAYLOAD__", txt)
    with open(OUT, "w") as f:
        f.write(html_doc)

    print("wrote", OUT)
    print("nodes=%d epics/boxes=%d edges=%d lanes=%d canvas=%dx%d"
          % (len(nodes_out), len(epics_out), len(edges_out),
             len(lanes_out), canvas_w, canvas_h))


def track_of(by_id, i):
    b = by_id.get(i)
    return (b.get("track") if b else None) or "unknown"


def mk_node(b, cx, cy, epic_id=None):
    return {
        "id": b["id"], "x": round(cx, 1), "y": round(cy, 1),
        "r": prio_r(b.get("priority", 2)),
        "track": b.get("track") or "unknown",
        "status": b["status"], "priority": b.get("priority", 2),
        "type": b["type"], "title": b["title"],
        "epic": epic_id,
        "milestone": b.get("milestone"),
        "labels": b.get("labels") or [],
        "desc": b.get("desc") or "",
        "closed": bool(b.get("closed_container")),
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agents-config — Backlog Landscape</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#1a1d21; --muted:#5b626b;
  --line:#d7dbe0; --band:#eceef1; --chip:#eef0f3; --accent:#F5A623;
  --danger:#E5484D; --shadow:rgba(20,24,30,.12); --nodeStroke:#2b2f36;
  --edge:#9aa2ac; --edgeCross:#111418;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0e1116; --panel:#171b21; --ink:#e8ebef; --muted:#9aa2ad;
    --line:#2b313a; --band:#1d222a; --chip:#232932; --accent:#FFB43A;
    --danger:#FF6369; --shadow:rgba(0,0,0,.5); --nodeStroke:#e8ebef;
    --edge:#5a626d; --edgeCross:#e8ebef;
  }
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);
  font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:flex;flex-direction:column;overflow:hidden}
header{padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel);
  display:flex;flex-wrap:wrap;align-items:center;gap:14px}
.h-title{font-size:16px;font-weight:700;letter-spacing:.2px}
.h-sub{color:var(--muted);font-size:12px}
.badge{background:var(--chip);border:1px solid var(--line);border-radius:20px;
  padding:2px 10px;font-size:11px;color:var(--muted)}
.badge b{color:var(--ink)}
.wrap{flex:1;display:flex;min-height:0}
.side{width:288px;flex:none;border-right:1px solid var(--line);background:var(--panel);
  overflow-y:auto;padding:12px}
.side h3{margin:14px 0 6px;font-size:11px;text-transform:uppercase;
  letter-spacing:.6px;color:var(--muted)}
.side h3:first-child{margin-top:0}
.row{display:flex;align-items:center;gap:7px;padding:2px 0;cursor:pointer;user-select:none}
.row input{margin:0}
.sw{width:12px;height:12px;border-radius:3px;border:1px solid var(--nodeStroke);flex:none}
.cnt{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums;font-size:11px}
.stage{flex:1;position:relative;min-width:0;background:var(--bg)}
svg{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
svg.drag{cursor:grabbing}
.node{stroke:var(--nodeStroke);stroke-width:1;vector-effect:non-scaling-stroke}
.node[data-status="in_progress"]{stroke:var(--accent);stroke-width:3}
.node[data-status="blocked"]{stroke:var(--danger);stroke-width:3}
.node[data-status="closed"]{stroke:var(--muted);stroke-dasharray:2 2}
.dim{opacity:.35}
.hide{display:none}
.fade{opacity:.08}
.hl{stroke:var(--ink);stroke-width:3}
.epicRect{fill-opacity:.10;stroke-width:1.4;vector-effect:non-scaling-stroke}
.epicRect[data-status="closed"]{stroke-dasharray:5 4;fill-opacity:.05}
.floatRect{fill:none;stroke:var(--muted);stroke-width:1;stroke-dasharray:3 4;
  vector-effect:non-scaling-stroke;opacity:.7}
.epicLbl{font-size:11px;font-weight:600;fill:var(--ink)}
.floatLbl{font-size:11px;fill:var(--muted);font-style:italic}
.laneBand{fill:var(--band)}
.laneEdge{stroke:var(--line);stroke-width:1;vector-effect:non-scaling-stroke;fill:none}
.laneCode{font-size:15px;font-weight:800;fill:var(--ink)}
.laneTitle{font-size:12px;fill:var(--muted)}
.laneCnt{font-size:11px;fill:var(--muted);font-variant-numeric:tabular-nums}
.edge{fill:none;stroke:var(--edge);stroke-width:1;vector-effect:non-scaling-stroke;opacity:.5}
.edge.cross{stroke:var(--edgeCross);stroke-width:1.8;stroke-dasharray:6 4;opacity:.85}
.edge.efade{opacity:.05}
.pillS{display:inline-block;padding:1px 7px;border-radius:20px;font-size:10px;
  border:1px solid var(--line);background:var(--chip);color:var(--muted)}
#tip{position:absolute;pointer-events:none;z-index:20;max-width:320px;
  background:var(--panel);border:1px solid var(--line);border-radius:8px;
  box-shadow:0 6px 22px var(--shadow);padding:8px 10px;font-size:12px;display:none}
#tip .t{font-weight:600;margin-bottom:3px}
#tip .m{color:var(--muted);font-size:11px}
#detail{position:absolute;top:10px;right:10px;width:320px;max-height:calc(100% - 20px);
  overflow-y:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;
  box-shadow:0 8px 30px var(--shadow);padding:12px 14px;z-index:15;display:none}
#detail .x{float:right;cursor:pointer;color:var(--muted);font-size:16px;line-height:1}
#detail .did{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--muted)}
#detail h4{margin:6px 0 4px;font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.5px}
#detail .dt{font-weight:600;font-size:13px;margin:2px 0 6px}
#detail .desc{white-space:pre-wrap;font-size:12px;color:var(--ink)}
.deplink{color:var(--accent);cursor:pointer;text-decoration:underline;
  font-family:ui-monospace,Menlo,monospace;font-size:11px}
.lbl{display:inline-block;background:var(--chip);border:1px solid var(--line);
  border-radius:4px;padding:0 5px;margin:1px 2px 1px 0;font-size:10px;color:var(--muted)}
.ctl{display:flex;align-items:center;gap:6px;margin:4px 0}
input[type=text],input[type=search]{width:100%;padding:6px 8px;border:1px solid var(--line);
  border-radius:6px;background:var(--bg);color:var(--ink);font-size:12px}
input[type=range]{width:100%}
button{background:var(--chip);border:1px solid var(--line);color:var(--ink);
  border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer}
button:hover{border-color:var(--muted)}
.match{margin:3px 0;padding:4px 6px;border:1px solid var(--line);border-radius:6px;
  cursor:pointer;font-size:11px;background:var(--bg)}
.match:hover{border-color:var(--accent)}
.match .mt{font-weight:600}
.match .mm{color:var(--muted);font-size:10px}
.demoNote{font-size:10px;color:var(--muted);font-style:italic;margin:2px 0 6px}
.statTbl{width:100%;border-collapse:collapse;font-size:10px}
.statTbl th,.statTbl td{padding:2px 3px;text-align:right;border-bottom:1px solid var(--line)}
.statTbl th:first-child,.statTbl td:first-child{text-align:left}
.statTbl thead th{color:var(--muted);font-weight:600}
.legRing{display:inline-flex;align-items:center;gap:5px;margin-right:12px;font-size:11px;color:var(--muted)}
.dotdemo{width:12px;height:12px;border-radius:50%;display:inline-block;border:1px solid var(--nodeStroke)}
.zbar{position:absolute;left:10px;bottom:10px;display:flex;gap:6px;z-index:15}
.hint{position:absolute;right:10px;bottom:10px;color:var(--muted);font-size:10px;z-index:14}
</style>
</head>
<body>
<header>
  <div>
    <div class="h-title">agents-config — Backlog Landscape</div>
    <div class="h-sub">Grooming view · generated <span id="gen"></span> · live bd export</div>
  </div>
  <div id="ribbon" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  <div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <span class="badge" id="deferBadge"></span>
    <span class="badge"><b id="nBeads"></b> beads</span>
    <span class="badge"><b id="nEdges"></b> dep edges</span>
  </div>
</header>
<div class="wrap">
  <aside class="side">
    <h3>Tracks (fill color)</h3>
    <div id="trackList"></div>
    <div class="ctl"><button id="allTracks">all</button><button id="noTracks">none</button></div>

    <h3>Status</h3>
    <div id="statusList"></div>

    <h3>Priority ≥ P<span id="prioVal">4</span> (larger = higher)</h3>
    <input type="range" id="prio" min="0" max="4" value="4" step="1">
    <div class="h-sub" style="font-size:10px">slider left = show all · right = only P0</div>

    <h3>Edges</h3>
    <label class="row"><input type="checkbox" id="crossOnly"> cross-track only</label>
    <label class="row"><input type="checkbox" id="hideEdges"> hide all edges</label>

    <h3>Search</h3>
    <input type="search" id="search" placeholder="dim non-matches…">
    <div id="searchOut" class="h-sub"></div>

    <h3>Dreaming Process — demo</h3>
    <div class="demoNote">Preview of the future placement-assistant: type a proposed bead; it token-scores against every title/desc and suggests where it fits.</div>
    <input type="text" id="whatif" placeholder="Propose a new bead…">
    <div id="whatifParents" class="h-sub" style="margin-top:6px"></div>
    <div id="whatifOut"></div>

    <h3>Counts by track</h3>
    <table class="statTbl" id="statTbl"></table>
  </aside>

  <div class="stage" id="stage">
    <svg id="svg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
      <defs>
        <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
                markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="var(--edge)"/>
        </marker>
        <marker id="ahx" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8"
                markerHeight="8" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="var(--edgeCross)"/>
        </marker>
      </defs>
      <g id="gLanes"></g>
      <g id="gEdges"></g>
      <g id="gEpics"></g>
      <g id="gNodes"></g>
    </svg>
    <div id="tip"></div>
    <div id="detail"></div>
    <div class="zbar">
      <button id="zin">+</button><button id="zout">−</button><button id="zreset">reset view</button>
    </div>
    <div class="hint">drag to pan · wheel to zoom · click a node for details</div>
  </div>
</div>

<script id="DATA" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById('DATA').textContent);
const SVGNS = "http://www.w3.org/2000/svg";
const PRIO_LBL = ["P0","P1","P2","P3","P4"];
const STATUS_ORDER = ["open","in_progress","blocked","deferred","closed"];
const STATUS_DEFAULT_ON = {open:true,in_progress:true,blocked:true,deferred:false,closed:false};

// ---- indexes --------------------------------------------------------------
const nodeById = {};           D.nodes.forEach(n=>nodeById[n.id]=n);
const epicById = {};           D.epics.forEach(e=>epicById[e.id]=e);
const centerById = {};
D.nodes.forEach(n=>centerById[n.id]=[n.x,n.y]);
D.epics.forEach(e=>{ if(!e.id.startsWith("__float__")) centerById[e.id]=[e.cx,e.cy]; });
// adjacency of drawn dep edges
const outAdj = {}, inAdj = {};
D.edges.forEach(e=>{
  (outAdj[e.from]=outAdj[e.from]||[]).push(e);
  (inAdj[e.to]=inAdj[e.to]||[]).push(e);
});
const trackColor = D.trackColors;

// ---- filter state ---------------------------------------------------------
const state = {
  tracks: new Set(D.tracks.map(t=>t.name)),
  status: new Set(STATUS_ORDER.filter(s=>STATUS_DEFAULT_ON[s])),
  prio: 4,            // show priority <= prio number (P4=all)
  crossOnly:false, hideEdges:false, search:"", selected:null
};

// ---- SVG render (from precomputed coords) ---------------------------------
const svg=document.getElementById('svg');
const gLanes=document.getElementById('gLanes');
const gEdges=document.getElementById('gEdges');
const gEpics=document.getElementById('gEpics');
const gNodes=document.getElementById('gNodes');
svg.setAttribute('viewBox',`0 0 ${D.canvasW} ${D.canvasH}`);

function el(tag,attrs){const e=document.createElementNS(SVGNS,tag);
  for(const k in attrs)e.setAttribute(k,attrs[k]);return e;}
function esc(s){return (s||"").replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// lanes
D.lanes.forEach(L=>{
  gLanes.appendChild(el('rect',{x:L.x,y:L.y,width:L.w,height:L.laneH,
    rx:10,class:'laneEdge',fill:'none'}));
  gLanes.appendChild(el('rect',{x:L.x,y:L.y,width:L.w,height:L.bandH,
    rx:10,class:'laneBand'}));
  const code=el('text',{x:L.x+14,y:L.y+22,class:'laneCode'});code.textContent=L.code;
  gLanes.appendChild(code);
  const ti=el('text',{x:L.x+14+ (L.code.length>2?54:40),y:L.y+22,class:'laneTitle'});
  ti.textContent=L.title;gLanes.appendChild(ti);
  const c=L.counts;
  const cn=el('text',{x:L.x+L.w-12,y:L.y+22,'text-anchor':'end',class:'laneCnt'});
  cn.textContent=`${L.total} beads · ${c.open} open · ${c.in_progress} wip · ${c.deferred} deferred`;
  gLanes.appendChild(cn);
});

// edges
const edgeEls=[];
D.edges.forEach(e=>{
  const p=el('path',{d:e.d,class:'edge'+(e.cross?' cross':''),
    'marker-end':e.cross?'url(#ahx)':'url(#ah)'});
  p.__e=e; gEdges.appendChild(p); edgeEls.push(p);
});

// epic + float containers
const epicEls=[];  // {id} epic rect/label pairs only -- floatboxes are a
                    // grouping affordance, not a filterable bead, and stay
                    // visible regardless of track/status/priority state
D.epics.forEach(E=>{
  if(E.type==='floatbox'){
    gEpics.appendChild(el('rect',{x:E.x,y:E.y,width:E.w,height:E.h,rx:8,class:'floatRect'}));
    const t=el('text',{x:E.x+8,y:E.y+15,class:'floatLbl'});t.textContent=E.title;
    gEpics.appendChild(t);
    return;
  }
  const col=trackColor[E.track]||trackColor.unknown;
  const r=el('rect',{x:E.x,y:E.y,width:E.w,height:E.h,rx:8,class:'epicRect',
    fill:col,stroke:col});
  r.setAttribute('data-status',E.status);
  r.__id=E.id; r.classList.add('hit');
  gEpics.appendChild(r);
  const t=el('text',{x:E.x+8,y:E.y+15,class:'epicLbl'});
  let lab=E.title; const maxc=Math.max(10,Math.floor((E.w-14)/6.2));
  if(lab.length>maxc)lab=lab.slice(0,maxc-1)+'…';
  t.textContent=lab; t.__id=E.id; t.classList.add('hit');
  gEpics.appendChild(t);
  epicEls.push({e:E,els:[r,t]});
});

// nodes
const nodeEls=[];
D.nodes.forEach(n=>{
  const c=el('circle',{cx:n.x,cy:n.y,r:n.r,fill:trackColor[n.track]||trackColor.unknown,
    class:'node'});
  c.setAttribute('data-status',n.status);
  c.__n=n; gNodes.appendChild(c); nodeEls.push(c);
});

// ---- viewBox pan/zoom -----------------------------------------------------
let vb={x:0,y:0,w:D.canvasW,h:D.canvasH};
function applyVB(){svg.setAttribute('viewBox',`${vb.x} ${vb.y} ${vb.w} ${vb.h}`);}
function fit(){
  const r=svg.getBoundingClientRect();
  const ar=r.width/r.height, car=D.canvasW/D.canvasH;
  vb={x:0,y:0,w:D.canvasW,h:D.canvasH};
  if(ar>car){vb.w=D.canvasH*ar; vb.x=(D.canvasW-vb.w)/2;}
  else{vb.h=D.canvasW/ar; vb.y=(D.canvasH-vb.h)/2;}
  applyVB();
}
fit();
window.addEventListener('resize',fit);

svg.addEventListener('wheel',ev=>{
  ev.preventDefault();
  const r=svg.getBoundingClientRect();
  const mx=vb.x+(ev.clientX-r.left)/r.width*vb.w;
  const my=vb.y+(ev.clientY-r.top)/r.height*vb.h;
  const f=ev.deltaY<0?0.85:1.176;
  const nw=Math.min(D.canvasW*2.5,Math.max(180,vb.w*f));
  const nh=nw*(vb.h/vb.w);
  vb.x=mx-(mx-vb.x)*(nw/vb.w);
  vb.y=my-(my-vb.y)*(nh/vb.h);
  vb.w=nw; vb.h=nh; applyVB();
},{passive:false});

let drag=null;
svg.addEventListener('pointerdown',ev=>{
  if(ev.target.__n||ev.target.__id) return; // let clicks through
  drag={sx:ev.clientX,sy:ev.clientY,vx:vb.x,vy:vb.y};
  svg.classList.add('drag'); svg.setPointerCapture(ev.pointerId);
});
svg.addEventListener('pointermove',ev=>{
  if(!drag)return;
  const r=svg.getBoundingClientRect();
  vb.x=drag.vx-(ev.clientX-drag.sx)/r.width*vb.w;
  vb.y=drag.vy-(ev.clientY-drag.sy)/r.height*vb.h;
  applyVB();
});
function endDrag(){drag=null;svg.classList.remove('drag');}
svg.addEventListener('pointerup',endDrag);
svg.addEventListener('pointercancel',endDrag);

document.getElementById('zin').onclick=()=>zoomC(0.8);
document.getElementById('zout').onclick=()=>zoomC(1.25);
document.getElementById('zreset').onclick=fit;
function zoomC(f){const cx=vb.x+vb.w/2,cy=vb.y+vb.h/2;
  const nw=Math.min(D.canvasW*2.5,Math.max(180,vb.w*f)),nh=nw*(vb.h/vb.w);
  vb.x=cx-nw/2; vb.y=cy-nh/2; vb.w=nw; vb.h=nh; applyVB();}
function panTo(id){
  const c=centerById[id]; if(!c)return;
  const nw=Math.max(vb.w<700?vb.w:640, 640), nh=nw*(vb.h/vb.w);
  vb.w=nw; vb.h=nh; vb.x=c[0]-nw/2; vb.y=c[1]-nh/2; applyVB();
}

// ---- tooltip --------------------------------------------------------------
const tip=document.getElementById('tip');
function showTip(n,ev){
  tip.innerHTML=`<div class="t">${esc(n.title)}</div>
    <div class="m"><code>${n.id}</code> · ${n.type} · ${PRIO_LBL[n.priority]||'P?'} · ${n.status}</div>
    <div class="m">track: ${n.track}${n.labels&&n.labels.length?' · '+n.labels.slice(0,4).map(esc).join(', '):''}</div>`;
  tip.style.display='block';
  const r=svg.getBoundingClientRect();
  let x=ev.clientX-r.left+14, y=ev.clientY-r.top+14;
  if(x+330>r.width)x=ev.clientX-r.left-330;
  tip.style.left=x+'px'; tip.style.top=y+'px';
}
function hideTip(){tip.style.display='none';}

// ---- detail panel ---------------------------------------------------------
const detail=document.getElementById('detail');
function bead(id){return nodeById[id]||epicById[id];}
function depItem(e,dir){
  const other=dir==='out'?e.to:e.from;
  const b=bead(other);
  const lab=b?esc(b.title):other;
  return `<div><span class="pillS">${e.type}</span>
    <span class="deplink" data-pan="${other}">${other}</span> ${lab?('· '+lab.slice(0,46)):''}</div>`;
}
function openDetail(id){
  const n=bead(id); if(!n)return;
  state.selected=id;
  const outs=(outAdj[id]||[]), ins=(inAdj[id]||[]);
  const mlabel=n.milestone?(D.lanes.find(l=>l.key===n.milestone)||{}).code||n.milestone:'—';
  detail.innerHTML=`<span class="x" id="dclose">×</span>
    <div class="did">${n.id} · ${n.type} · ${PRIO_LBL[n.priority]||'P?'} · ${n.status}</div>
    <div class="dt">${esc(n.title)}</div>
    <div class="h-sub">track <b>${n.track}</b> · milestone <b>${mlabel}</b>${n.epic&&bead(n.epic)?(' · epic '+n.epic):''}</div>
    ${n.labels&&n.labels.length?`<h4>Labels</h4><div>${n.labels.map(l=>`<span class="lbl">${esc(l)}</span>`).join('')}</div>`:''}
    ${n.desc?`<h4>Description</h4><div class="desc">${esc(n.desc)}</div>`:''}
    <h4>Depends on / points to (${outs.length})</h4>${outs.length?outs.map(e=>depItem(e,'out')).join(''):'<div class="h-sub">none</div>'}
    <h4>Depended on by (${ins.length})</h4>${ins.length?ins.map(e=>depItem(e,'in')).join(''):'<div class="h-sub">none</div>'}`;
  detail.style.display='block';
  document.getElementById('dclose').onclick=()=>{detail.style.display='none';state.selected=null;highlight(null);};
  detail.querySelectorAll('[data-pan]').forEach(a=>{
    a.onclick=()=>{const t=a.getAttribute('data-pan');panTo(t);if(bead(t))openDetail(t);highlight(t);};
  });
  highlight(id);
}

// highlight a node's edges/neighbours
function highlight(id){
  if(!id){edgeEls.forEach(p=>p.classList.remove('efade','hl'));nodeEls.forEach(c=>c.classList.remove('hl'));applyFilters();return;}
  const nbr=new Set([id]);
  (outAdj[id]||[]).forEach(e=>nbr.add(e.to));
  (inAdj[id]||[]).forEach(e=>nbr.add(e.from));
  edgeEls.forEach(p=>{
    const on=(p.__e.from===id||p.__e.to===id);
    p.classList.toggle('hl',on); p.classList.toggle('efade',!on && !p.classList.contains('hide'));
  });
  nodeEls.forEach(c=>c.classList.toggle('hl',c.__n.id===id));
}

// ---- events on nodes/epics ------------------------------------------------
svg.addEventListener('mousemove',ev=>{
  const t=ev.target;
  if(t.__n){showTip(t.__n,ev);} else if(t.__id&&epicById[t.__id]){showTip(epicById[t.__id],ev);} else hideTip();
});
svg.addEventListener('click',ev=>{
  const t=ev.target;
  if(t.__n){openDetail(t.__n.id);}
  else if(t.__id&&epicById[t.__id]){openDetail(t.__id);}
});

// ---- filtering ------------------------------------------------------------
function nodeVisible(n){
  if(!state.tracks.has(n.track))return false;
  if(!state.status.has(n.status))return false;
  if(n.priority>state.prio)return false;
  return true;
}
function epicVisible(E){
  if(!state.tracks.has(E.track))return false;
  if(!state.status.has(E.status))return false;
  if(E.priority>state.prio)return false;
  return true;
}
function applyFilters(){
  // nodes
  nodeEls.forEach(c=>{
    const n=c.__n; const vis=nodeVisible(n);
    c.classList.toggle('hide',!vis);
    c.classList.toggle('dim',vis && n.status==='deferred');
    if(vis && state.search){
      const hit=(n.title+' '+n.id+' '+(n.labels||[]).join(' ')+' '+n.desc).toLowerCase().includes(state.search);
      c.classList.toggle('fade',!hit);
    } else c.classList.remove('fade');
  });
  // epic containers (floatboxes are exempt -- see epicEls comment)
  epicEls.forEach(({e,els})=>{
    const vis=epicVisible(e);
    els.forEach(el=>el.classList.toggle('hide',!vis));
  });
  // edges
  edgeEls.forEach(p=>{
    const e=p.__e;
    let show=!state.hideEdges;
    if(show && state.crossOnly && !e.cross)show=false;
    if(show){ const a=bead(e.from),b=bead(e.to);
      const aVisible=n=>n.type==='epic'?epicVisible(n):nodeVisible(n);
      const av=a&&aVisible(a), bv=b&&aVisible(b);
      if(!av||!bv)show=false; }
    p.classList.toggle('hide',!show);
  });
  if(state.selected)highlight(state.selected);
}

// ---- side panel build -----------------------------------------------------
document.getElementById('gen').textContent=D.generated;
document.getElementById('nBeads').textContent=D.counts.beads;
document.getElementById('nEdges').textContent=D.counts.edgesDrawn;
const defer=D.statusTotals.deferred||0, closed=D.statusTotals.closed||0;
document.getElementById('deferBadge').innerHTML=
  `<b>${defer}</b> deferred + <b>${closed}</b> closed hidden by default`;

// track list
const tl=document.getElementById('trackList');
D.tracks.forEach(t=>{
  const tot=(D.stats[t.name]||{}).total||0;
  const row=document.createElement('label');row.className='row';
  row.innerHTML=`<input type="checkbox" checked><span class="sw" style="background:${t.color}"></span>
    ${t.name}<span class="cnt">${tot}</span>`;
  row.querySelector('input').onchange=e=>{
    if(e.target.checked)state.tracks.add(t.name);else state.tracks.delete(t.name);applyFilters();};
  tl.appendChild(row);
});
document.getElementById('allTracks').onclick=()=>{state.tracks=new Set(D.tracks.map(t=>t.name));
  tl.querySelectorAll('input').forEach(i=>i.checked=true);applyFilters();};
document.getElementById('noTracks').onclick=()=>{state.tracks=new Set();
  tl.querySelectorAll('input').forEach(i=>i.checked=false);applyFilters();};

// status list
const sl=document.getElementById('statusList');
STATUS_ORDER.forEach(s=>{
  const tot=D.statusTotals[s]||0;
  if(tot===0 && s!=='blocked') { /* still show blocked capability? skip zero non-blocked */ }
  const row=document.createElement('label');row.className='row';
  const on=STATUS_DEFAULT_ON[s];
  row.innerHTML=`<input type="checkbox" ${on?'checked':''}>${s.replace('_',' ')}
    <span class="cnt">${tot}</span>`;
  row.querySelector('input').onchange=e=>{
    if(e.target.checked)state.status.add(s);else state.status.delete(s);applyFilters();};
  sl.appendChild(row);
});

// priority slider
const prio=document.getElementById('prio'), prioVal=document.getElementById('prioVal');
prio.oninput=()=>{state.prio=+prio.value;prioVal.textContent=prio.value;applyFilters();};

document.getElementById('crossOnly').onchange=e=>{state.crossOnly=e.target.checked;applyFilters();};
document.getElementById('hideEdges').onchange=e=>{state.hideEdges=e.target.checked;applyFilters();};

// search
const searchOut=document.getElementById('searchOut');
document.getElementById('search').oninput=e=>{
  state.search=e.target.value.trim().toLowerCase();
  applyFilters();
  if(!state.search){searchOut.textContent='';return;}
  const hits=D.nodes.filter(n=>nodeVisible(n)&&
    (n.title+' '+n.id+' '+(n.labels||[]).join(' ')+' '+n.desc).toLowerCase().includes(state.search));
  searchOut.innerHTML=`${hits.length} match${hits.length===1?'':'es'}`+
    (hits.length&&hits.length<=25?': '+hits.slice(0,25).map(n=>`<span class="deplink" data-pan="${n.id}">${n.id}</span>`).join(' '):'');
  searchOut.querySelectorAll('[data-pan]').forEach(a=>a.onclick=()=>{panTo(a.getAttribute('data-pan'));openDetail(a.getAttribute('data-pan'));});
};

// ---- ribbon (per-track quick totals) --------------------------------------
const ribbon=document.getElementById('ribbon');
const totalOpen=D.nodes.filter(n=>n.status==='open').length;
D.tracks.slice().sort((a,b)=>((D.stats[b.name]||{}).total||0)-((D.stats[a.name]||{}).total||0))
  .slice(0,5).forEach(t=>{
  const s=D.stats[t.name]||{};
  const b=document.createElement('span');b.className='badge';
  b.innerHTML=`<span class="sw" style="display:inline-block;background:${t.color};vertical-align:-1px"></span>
    ${t.name} <b>${s.open||0}</b>/${s.in_progress||0}/${s.deferred||0}`;
  b.title=`${t.name}: open ${s.open||0} · wip ${s.in_progress||0} · blocked ${s.blocked||0} · deferred ${s.deferred||0}`;
  ribbon.appendChild(b);
});

// ---- stat table -----------------------------------------------------------
const st=document.getElementById('statTbl');
st.innerHTML=`<thead><tr><th>track</th><th>op</th><th>wip</th><th>bl</th><th>def</th></tr></thead><tbody>`+
  D.tracks.map(t=>{const s=D.stats[t.name]||{};
    return `<tr><td><span class="sw" style="display:inline-block;background:${t.color};vertical-align:-1px"></span> ${t.name}</td>
      <td>${s.open||0}</td><td>${s.in_progress||0}</td><td>${s.blocked||0}</td><td>${s.deferred||0}</td></tr>`;}).join('')+
  `</tbody>`;

// ---- what-if / Dreaming Process demo (client token overlap) ----------------
const STOP=new Set("the a an of to and or for in on with by is are be as at from into via that this it its use using not no do".split(" "));
function tok(s){return (s||"").toLowerCase().split(/[^a-z0-9]+/).filter(w=>w.length>2&&!STOP.has(w));}
const CORPUS=D.nodes.concat(D.epics.filter(e=>e.type==='epic'))
  .map(n=>({n,toks:new Set(tok(n.title+' '+(n.desc||'')+' '+(n.labels||[]).join(' ')))}));
const whatifOut=document.getElementById('whatifOut');
const whatifParents=document.getElementById('whatifParents');
let lastHi=[];
document.getElementById('whatif').oninput=e=>{
  const q=tok(e.target.value);
  lastHi.forEach(id=>{const c=nodeEls.find(x=>x.__n.id===id);if(c)c.classList.remove('hl');});
  lastHi=[];
  if(q.length===0){whatifOut.innerHTML='';whatifParents.innerHTML='';return;}
  const qs=new Set(q);
  const scored=CORPUS.map(c=>{
    let ov=0; qs.forEach(w=>{if(c.toks.has(w))ov++;});
    const sc=ov/Math.sqrt((c.toks.size||1));
    return {n:c.n,ov,sc};
  }).filter(x=>x.ov>0).sort((a,b)=>b.sc-a.sc||b.ov-a.ov).slice(0,8);
  if(!scored.length){whatifOut.innerHTML='<div class="h-sub">no token overlap yet…</div>';whatifParents.innerHTML='';return;}
  // likely parent epics: epics containing the most matches, plus any epic
  // that is itself a direct token match (its own strongest candidate)
  const epicScore={};
  scored.forEach(x=>{
    const ep=x.n.type==='epic'?x.n.id:x.n.epic;
    if(ep&&epicById[ep]){epicScore[ep]=(epicScore[ep]||0)+x.sc;}
  });
  const topEp=Object.entries(epicScore).sort((a,b)=>b[1]-a[1]).slice(0,3);
  whatifParents.innerHTML= topEp.length?('<b>Likely parent epics:</b><br>'+topEp.map(([id,s])=>{
    const ep=epicById[id];const ml=(D.lanes.find(l=>l.key===ep.milestone)||{}).code||'—';
    return `<span class="deplink" data-pan="${id}">${id}</span> ${esc(ep.title.slice(0,34))} <span class="mm">[${ml}]</span>`;
  }).join('<br>')):'<span class="h-sub">no epic pattern</span>';
  whatifOut.innerHTML=scored.map(x=>{
    const n=x.n;const ml=(D.lanes.find(l=>l.key===n.milestone)||{}).code||'—';
    const ep=n.type==='epic'?'(itself an epic)':(n.epic&&epicById[n.epic]?epicById[n.epic].title.slice(0,26):'(loose)');
    return `<div class="match" data-pan="${n.id}">
      <div class="mt">${esc(n.title.slice(0,54))}</div>
      <div class="mm">${n.track} · epic ${esc(ep)} · ${ml} · overlap ${x.ov}</div></div>`;
  }).join('');
  lastHi=scored.map(x=>x.n.id);
  lastHi.forEach(id=>{const c=nodeEls.find(x=>x.__n.id===id);if(c)c.classList.add('hl');});
  [whatifOut,whatifParents].forEach(box=>box.querySelectorAll('[data-pan]').forEach(a=>{
    a.onclick=()=>{const t=a.getAttribute('data-pan');panTo(t);if(bead(t))openDetail(t);};
  }));
};

applyFilters();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
