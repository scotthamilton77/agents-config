// vizsuite/views/constellation.js — the dependency constellation view module
// (spec §6.1: "build, evaluation-gated" §11 — shipped inlined but never
// mounted by default; app.js registers it behind a default-off experimental
// toggle). Obeys the §4.2 view-module interface: render(container, scene,
// state) → handle, with handle.destroy() and handle.reencode(state).
//
// Node model (prototype anatomy `variant_B.js`, structural parity): two
// kinds of node, both derived client-side from the scene JSON (no Python
// changes) —
//   - dir super-nodes: every directory (gen_data.py's `dir_of`: up to 4 path
//     segments, deepest level capped) over the *whole estate* (scene.files),
//     with per-dir metrics the MAX over its member files' complexity/
//     load_bearing/consequence, plus files/changed counts. A dir with too
//     little going on (fewer than 2 files AND no changed files AND
//     load_bearing < 0.05) never becomes a node at all (noise threshold); a
//     surviving dir with no coupling edge and no tethered satellite is
//     still dropped (connectivity prune) and counted toward the "N
//     unconnected directories hidden" caption.
//   - satellites: every in-PR (changed) file is always a fixed-size node,
//     tethered by a dashed line to its containing dir node (walking up to 4
//     path-segment ancestors, per `findContainingDir`, falling back to the
//     synthetic "(root)" dir) — never gated by the connectivity prune above,
//     since a satellite's own presence is what makes its dir "connected".
// Dir-dir coupling edges are the scene's deduped file-level dependency edges
// (this view never encodes import direction) rolled up to distinct
// (dir, dir) pairs, excluding same-dir pairs, weighted by how many file
// edges rolled into each pair.
//
// Layout (spec §4.2 "deterministic pre-settled layout … force simulations
// run N ticks synchronously with a fixed seed"): d3-force (bundled as part
// of the vendored d3 7.9.0, confirmed via forceSimulation/forceLink/
// forceManyBody/forceCenter/randomSource all present) runs FIXED_TICKS
// iterations synchronously via `simulation.tick(N)` before this module ever
// appends a node to the DOM — never the timer-driven async ticking d3-force
// examples normally rely on (`.stop()` right after construction cancels
// that). `LAYOUT_SEED` is injected via `simulation.randomSource(mulberry32(
// LAYOUT_SEED))`, set before any `.force(...)` call so every force that
// consumes randomness (forceManyBody's Barnes-Hut jitter, forceCollide) reads
// our controlled sequence rather than the library's own internal default —
// explicit determinism, not a reliance on an undocumented library default.
// Node order feeds d3-force's index-based initial phyllotaxis spiral, so the
// node list is sorted by id before layout runs (spec test item 6: the same
// scene always settles the same graph). `handle.reencode(state)` repaints
// node fill colors only — it never re-creates the simulation or touches
// node.x/node.y (spec §4.2 "no re-sim on slider drag"), and interaction
// (drag/pin, zoom/pan transform) never runs a fresh simulation tick either —
// there is no persistent simulation after the initial synchronous settle.
//
// Interaction parity (fidelity, prototype anatomy `variant_B.js`):
//   - Hover score card: the same shared tooltip (views/_shared.js
//     showTooltip/buildScoreCard) the treemap tile and ledger row use, for
//     file/satellite nodes; a dir node gets its own bespoke (hover-only —
//     a dir has no story/diff to drill into) tooltip built from its rolled-up
//     stats, via the same shared meter-row building block.
//   - Zoom/pan: a `.viz-constellation-viewport` clipping window wraps the
//     layout stage; d3.zoom drives its CSS transform (scaleExtent [0.3, 6]),
//     never the layout itself — panning/zooming is purely a view transform,
//     so it composes with the "no re-sim" contract above for free. Node
//     interactions (drag, click, hover) must never also pan the canvas —
//     `zoomFilter` rejects any non-wheel gesture that started on a node.
//   - Drag-to-reposition + pin-on-drop: dragging a node moves node.x/node.y
//     (and its incident edge endpoints) directly; because there is no
//     persistent simulation to spring it back, a dropped node simply stays
//     wherever it lands — "pinned" is the resting state, not a flag to
//     maintain. Double-click restores the node's originally-settled
//     position (`node.origX`/`node.origY`, captured right after
//     layoutGraph()) — the closest faithful analog available to the
//     prototype's "un-pin + brief reheat", since this module deliberately
//     has no persistent simulation to reheat.
//   - Click-to-focus: a dir node's activation animates center+zoom to it
//     (min scale 1.5, ~500ms); a file/satellite node's activation opens the
//     drill panel, unchanged from before dir nodes existed.
//
// Legend (spec §4.5 "legend completeness"): rendered *inside* this module's
// own container, never into the shared `#viz-legend` app.js owns for
// treemap/ledger — the view-module contract forbids styling/rendering
// outside the fresh container a view was handed (spec §4.2). The prototype's
// five entries (size, color, edge width, ringed dot, satellites) are what is
// actually rendered here — every entry has a real referent.
//
// Every repo-derived string (a file/dir path) is bound via `textContent`/
// `title`/`aria-label` attribute, never `innerHTML`, matching the DOM-bind
// invariant the other view modules hold.
(function () {
  "use strict";

  window.vizViews = window.vizViews || {};

  var FIXED_TICKS = 300;
  // Any fixed constant works; changing it changes the settled layout but
  // never removes its determinism (spec §4.2).
  var LAYOUT_SEED = 1337;
  var DRAG_THRESHOLD = 4; // px; same click-vs-drag threshold as wireClickVsDragActivation
  // Double-click un-pin window (ms): a node click's activation (dir focus /
  // file drill) is deferred by this window and cancelled when the un-pin
  // dblclick lands, so the un-pin gesture never also opens the drill (whose
  // viewport resize would otherwise shift the baseline mid-gesture). Scoped to
  // constellation nodes only — every node here carries the dblclick un-pin
  // gesture. Keyboard activation is unaffected (stays instant).
  var DBLCLICK_ACTIVATION_WINDOW_MS = 275;

  // ---- Node sizing (prototype anatomy `variant_B.js`): a dir's radius grows
  // with its rolled-up load-bearing score; a satellite is always the same
  // small fixed size (it is the tethered detail, never the focal point). ----
  var DIR_RADIUS_BASE = 4;
  var DIR_RADIUS_SCALE = 14;
  var SATELLITE_RADIUS = 5;

  // ---- Dir noise threshold (prototype anatomy: gen_data.py's dir_of +
  // variant_B.js's dirNodes filter): a directory with too few files, no
  // changes, and negligible load-bearing never becomes a node — it would be
  // pure clutter. ----
  var NOISE_MIN_FILES = 2;
  var NOISE_MIN_CENTRALITY = 0.05;

  // The synthetic root-group directory (files at repo root, no "/" in their
  // path) — a NUL-prefixed sentinel key (a real git path can never contain a
  // NUL byte) so it can never collide with an actual top-level directory
  // that happens to be named "(root)" (same guard views/treemap.js's own
  // ROOT_GROUP_PATH uses for its synthetic root node).
  var ROOT_DIR_NAME = "(root)";
  var ROOT_DIR_PATH = "\u0000(root)";

  // ---- Seeded PRNG (mulberry32): injected via `simulation.randomSource`
  // so the layout is a pure, reproducible function of the node/edge set,
  // independent of whatever internal random source d3-force ships with by
  // default (spec §4.2's fixed-seed requirement, made explicit rather than
  // assumed). ----
  function mulberry32(seed) {
    var state = seed >>> 0;
    return function () {
      state = (state + 0x6d2b79f5) | 0;
      var t = Math.imul(state ^ (state >>> 15), 1 | state);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function basename(path) {
    var parts = path.split("/");
    return parts[parts.length - 1];
  }

  function numberOr0(value) {
    return typeof value === "number" ? value : 0;
  }

  // A dir path never surfaces its NUL sentinel to the DOM — this is the one
  // place that translation happens, mirroring views/treemap.js's own
  // displayPathFor for its synthetic root group.
  function dirDisplayPath(path) {
    return path === ROOT_DIR_PATH ? ROOT_DIR_NAME : path;
  }

  // ---- dir_of (prototype anatomy: gen_data.py lines ~221-223): a file's
  // containing directory, capped at 4 path segments deep — a file 6 levels
  // deep still aggregates into its 4th-level ancestor, not a very-long,
  // very-specific leaf directory. A root-level file (no "/" in its path)
  // aggregates into the synthetic "(root)" dir. ----
  function dirOf(path) {
    var parts = path.split("/");
    var segCount = Math.min(parts.length - 1, 4);
    var dir = parts.slice(0, segCount).join("/");
    return dir || ROOT_DIR_PATH;
  }

  // ---- findContainingDir (prototype anatomy: variant_B.js): a satellite's
  // tether target. `dir_of(path)`'s own dir may have been dropped by the
  // noise threshold, so this walks shorter path prefixes looking for the
  // nearest *surviving* ancestor dir, falling back to the root dir (which
  // may itself be absent, e.g. every file lives in some real directory). ----
  function findContainingDir(path, dirNodeByPath) {
    var parts = path.split("/");
    for (var i = Math.min(parts.length - 1, 4); i >= 1; i--) {
      var candidate = parts.slice(0, i).join("/");
      if (dirNodeByPath[candidate]) {
        return dirNodeByPath[candidate];
      }
    }
    return dirNodeByPath[ROOT_DIR_PATH] || null;
  }

  // ---- Per-dir aggregation (prototype anatomy: gen_data.py lines ~225-233):
  // MAX over member files' heat axes, plus file/changed counts — over the
  // *whole estate* (scene.files), never just the PR files, so a dir's
  // rolled-up context reflects everything living under it. ----
  function computeDirStats(files) {
    var stats = Object.create(null);
    files.forEach(function (file) {
      var dirPath = dirOf(file.path);
      var attributes = file.attributes || {};
      var entry = stats[dirPath];
      if (!entry) {
        entry = {
          path: dirPath,
          files: 0,
          changed: 0,
          complexity: 0,
          load_bearing: 0,
          consequence: 0
        };
        stats[dirPath] = entry;
      }
      entry.files += 1;
      if (attributes.in_pr) {
        entry.changed += 1;
      }
      entry.complexity = Math.max(entry.complexity, numberOr0(attributes.complexity));
      entry.load_bearing = Math.max(entry.load_bearing, numberOr0(attributes.load_bearing));
      entry.consequence = Math.max(entry.consequence, numberOr0(attributes.consequence));
    });
    return stats;
  }

  function isNoiseDir(stats) {
    return (
      stats.files < NOISE_MIN_FILES && stats.changed === 0 && stats.load_bearing < NOISE_MIN_CENTRALITY
    );
  }

  function makeDirNode(stats) {
    return {
      id: "dir:" + stats.path,
      kind: "dir",
      path: stats.path,
      stats: stats,
      attributes: {
        complexity: stats.complexity,
        load_bearing: stats.load_bearing,
        consequence: stats.consequence
      },
      r: DIR_RADIUS_BASE + DIR_RADIUS_SCALE * Math.sqrt(stats.load_bearing || 0)
    };
  }

  function makeSatelliteNode(file, dirNode) {
    return {
      id: "file:" + file.path,
      kind: "file",
      path: file.path,
      file: file,
      attributes: file.attributes || {},
      inPr: true,
      r: SATELLITE_RADIUS,
      dir: dirNode
    };
  }

  // Deduped by unordered pair (this view never encodes import direction, the
  // same "either direction" stance file sonar takes for its blast-radius
  // hops) — an A→B/B→A pair (or an exact repeat) rolls up as one file edge,
  // not two.
  function buildDedupedFileEdges(rawEdges) {
    var seenPairs = Object.create(null);
    var edges = [];
    rawEdges.forEach(function (edge) {
      var key =
        edge.source < edge.target
          ? edge.source + "\0" + edge.target
          : edge.target + "\0" + edge.source;
      if (seenPairs[key]) {
        return;
      }
      seenPairs[key] = true;
      edges.push({ source: edge.source, target: edge.target });
    });
    return edges;
  }

  // ---- Dir-dir coupling edges (prototype anatomy: gen_data.py lines
  // ~235-239): roll the deduped file-level edges up to distinct dir pairs,
  // excluding same-dir pairs (an edge wholly inside one directory says
  // nothing about coupling *between* directories), weighted by how many
  // file edges rolled into each pair. Each endpoint resolves through the
  // same nearest-surviving-ancestor walk satellites use (findContainingDir),
  // so an edge rooted in a noise-pruned leaf dir rolls up to that leaf's
  // surviving ancestor instead of silently vanishing; the same-dir check
  // runs on the *resolved* dirs, so an edge between two pruned subdirs of
  // one surviving ancestor correctly reads as intra-dir. The connectivity
  // prune (in buildGraph) runs as a second pass over this result. ----
  function rollUpDirEdges(fileEdges, dirNodeByPath) {
    var counts = Object.create(null);
    var order = [];
    fileEdges.forEach(function (edge) {
      var srcDir = findContainingDir(edge.source, dirNodeByPath);
      var tgtDir = findContainingDir(edge.target, dirNodeByPath);
      if (!srcDir || !tgtDir || srcDir === tgtDir) {
        return;
      }
      var a = srcDir.path;
      var b = tgtDir.path;
      var lo = a < b ? a : b;
      var hi = a < b ? b : a;
      var key = lo + "\0" + hi;
      if (!counts[key]) {
        counts[key] = { source: lo, target: hi, n: 0 };
        order.push(key);
      }
      counts[key].n += 1;
    });
    return order.map(function (key) {
      var entry = counts[key];
      return {
        source: dirNodeByPath[entry.source].id,
        target: dirNodeByPath[entry.target].id,
        n: entry.n,
        tether: false
      };
    });
  }

  // ---- scene.files + scene.edges → { nodes, edges, droppedDirCount } for
  // the layout. Always builds a graph: the "dependency graph unavailable"
  // state is decided by the caller from render_config.unavailable_axes (the
  // load-bearing axis fail-softed), NOT from an empty edge set — dir
  // coupling edges derive from that same dependency graph, so the whole
  // structural view depends on it exactly as file-level edges did before. ----
  function buildGraph(scene) {
    var dirStats = computeDirStats(scene.files);
    var dirPaths = Object.keys(dirStats).sort();

    var allDirNodes = dirPaths
      .filter(function (path) {
        return !isNoiseDir(dirStats[path]);
      })
      .map(function (path) {
        return makeDirNode(dirStats[path]);
      });

    var dirNodeByPath = Object.create(null);
    allDirNodes.forEach(function (node) {
      dirNodeByPath[node.path] = node;
    });

    var fileEdges = buildDedupedFileEdges(scene.edges || []);
    var dirEdges = rollUpDirEdges(fileEdges, dirNodeByPath);

    var satelliteNodes = scene.files
      .filter(function (file) {
        return Boolean(file.attributes && file.attributes.in_pr);
      })
      .map(function (file) {
        return makeSatelliteNode(file, findContainingDir(file.path, dirNodeByPath));
      })
      .sort(function (a, b) {
        return a.path < b.path ? -1 : a.path > b.path ? 1 : 0;
      });

    // Connectivity prune (spec: unconnected dir nodes hidden): a dir that
    // survived the noise threshold above still needs a real relationship to
    // the rest of the graph — a coupling edge, or at least one tethered
    // satellite — or it is dropped and counted toward the "N unconnected
    // directories hidden" caption.
    var connectedDirIds = Object.create(null);
    dirEdges.forEach(function (edge) {
      connectedDirIds[edge.source] = true;
      connectedDirIds[edge.target] = true;
    });
    satelliteNodes.forEach(function (sat) {
      if (sat.dir) {
        connectedDirIds[sat.dir.id] = true;
      }
    });

    var survivingDirNodes = allDirNodes.filter(function (node) {
      return Boolean(connectedDirIds[node.id]);
    });
    var droppedDirCount = allDirNodes.length - survivingDirNodes.length;
    var survivingIds = Object.create(null);
    survivingDirNodes.forEach(function (node) {
      survivingIds[node.id] = true;
    });

    var finalDirEdges = dirEdges.filter(function (edge) {
      return survivingIds[edge.source] && survivingIds[edge.target];
    });
    var tetherLinks = satelliteNodes
      .filter(function (sat) {
        return sat.dir && survivingIds[sat.dir.id];
      })
      .map(function (sat) {
        return { source: sat.id, target: sat.dir.id, tether: true };
      });

    // Sorted so the node list — and therefore d3-force's index-based initial
    // phyllotaxis spiral — is a pure function of the node identities, never
    // of incidental scene.files/scene.edges iteration order.
    var nodes = survivingDirNodes.concat(satelliteNodes).sort(function (a, b) {
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
    var edges = finalDirEdges.concat(tetherLinks);

    return { nodes: nodes, edges: edges, droppedDirCount: droppedDirCount };
  }

  // ---- Pre-settled force layout (spec §4.2): runs to completion
  // synchronously, before this module ever paints a node. ----
  function layoutGraph(nodes, edges) {
    var side = Math.max(320, Math.round(Math.sqrt(nodes.length) * 90) + 140);

    var simulation = d3
      .forceSimulation(nodes)
      .randomSource(mulberry32(LAYOUT_SEED))
      // Cancel d3-force's own timer-driven async ticking immediately — this
      // view only ever advances the simulation via the synchronous
      // `.tick(FIXED_TICKS)` call below.
      .stop()
      .force(
        "link",
        d3
          .forceLink(edges)
          .id(function (d) {
            return d.id;
          })
          .distance(function (d) {
            return d.tether ? 18 : 60;
          })
          .strength(function (d) {
            return d.tether ? 0.8 : 0.25;
          })
      )
      .force(
        "charge",
        d3.forceManyBody().strength(function (d) {
          return d.kind === "file" ? -30 : -120;
        })
      )
      .force("center", d3.forceCenter(side / 2, side / 2))
      .force(
        "collide",
        d3.forceCollide(function (d) {
          return d.r + 3;
        })
      )
      .alpha(1)
      .alphaDecay(1 - Math.pow(0.001, 1 / FIXED_TICKS));

    simulation.tick(FIXED_TICKS);
    simulation.stop();

    // Defensive containment, not a determinism mechanism (the tick sequence
    // above already is fully deterministic): forceCenter pulls the
    // barycenter toward the stage center but places no hard wall, so a
    // sparse graph can still settle a hair outside the box without this.
    nodes.forEach(function (node) {
      node.x = Math.min(side - node.r, Math.max(node.r, node.x));
      node.y = Math.min(side - node.r, Math.max(node.r, node.y));
    });

    return side;
  }

  // ---- Unavailable state (spec: matches file sonar's "dependency graph
  // unavailable" pattern and reuses its CSS class). ----
  function renderUnavailable(container) {
    var message = document.createElement("div");
    message.id = "viz-constellation-unavailable";
    message.setAttribute("class", "viz-sonar-unavailable viz-constellation-unavailable");
    message.textContent =
      "Dependency graph unavailable — this artifact was built without a fresh " +
      "graphify build, so the constellation cannot be computed.";
    container.appendChild(message);
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  // Returns the created `{ edge, lineEl }` pairs so the caller can index
  // incident lines per node id for live repositioning during drag — the
  // svg itself is never needed again once appended.
  function renderEdges(stage, side, edges) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "viz-constellation-edges");
    svg.setAttribute("width", String(side));
    svg.setAttribute("height", String(side));
    var entries = edges.map(function (edge) {
      // Post-layout, d3.forceLink has replaced these string endpoints with
      // node object references (standard d3-force behavior) — the fresh
      // edge objects buildGraph() made are what absorbed that mutation,
      // never scene.edges itself.
      var line = document.createElementNS(SVG_NS, "line");
      line.setAttribute(
        "class",
        "viz-constellation-edge" + (edge.tether ? " viz-constellation-edge--tether" : "")
      );
      line.setAttribute("x1", String(edge.source.x));
      line.setAttribute("y1", String(edge.source.y));
      line.setAttribute("x2", String(edge.target.x));
      line.setAttribute("y2", String(edge.target.y));
      // Coupling-edge width scales with rolled-up count (spec: "edge width =
      // coupling strength"); a tether is always a thin fixed line.
      line.style.strokeWidth = (edge.tether ? 1 : 1 + Math.log1p(edge.n || 1)) + "px";
      svg.appendChild(line);
      return { edge: edge, lineEl: line };
    });
    stage.appendChild(svg);
    return entries;
  }

  function updateEdgeEndpoint(lineEl, role, node) {
    if (role === "source") {
      lineEl.setAttribute("x1", String(node.x));
      lineEl.setAttribute("y1", String(node.y));
    } else {
      lineEl.setAttribute("x2", String(node.x));
      lineEl.setAttribute("y2", String(node.y));
    }
  }

  // ---- Heat color scale (spec §4.3, cosmetic parity fidelity): a 5-stop
  // piecewise LAB ramp (prototype anatomy: variant_B.js's `rebuildRamp`,
  // `d3.piecewise(d3.interpolateLab, [...])`) — LAB interpolation is
  // perceptually smoother than the treemap/ledger's 3-stop RGB scale, and
  // the two extra intermediate stops give this view's much larger heat-color
  // range (every dir + every satellite, vs. a handful of drill-panel bars) a
  // higher-resolution ramp. Anchors are still the shared `--viz-heat-*`
  // custom properties (resolved fresh on every render/reencode so a theme
  // change picks up its own twin) — extended with two intermediate stops
  // rather than a bespoke palette, so this view's ramp stays a strict
  // refinement of the shared cold/mid/hot anchors, never a competing one. ----
  var HEAT_RAMP_STOPS = [
    "--viz-heat-cold",
    "--viz-heat-cold-mid",
    "--viz-heat-mid",
    "--viz-heat-mid-hot",
    "--viz-heat-hot"
  ];

  function makeHeatColorScale() {
    var style = getComputedStyle(document.documentElement);
    var stops = HEAT_RAMP_STOPS.map(function (token) {
      return style.getPropertyValue(token).trim();
    });
    var ramp = d3.piecewise(d3.interpolateLab, stops);
    return function (heat) {
      return ramp(Math.max(0, Math.min(1, heat)));
    };
  }

  function applyEncoding(entries, heatScale, computeHeat) {
    entries.forEach(function (entry) {
      var heat = computeHeat(entry.node.attributes);
      var color = heatScale(heat);
      entry.el.style.backgroundColor = color;
      // The label rides above the mark over the stage background (not on the
      // node fill), so its color is a fixed muted CSS value, not a
      // fill-contrast computation — nothing to repaint on reencode.
      // The aria-label's heat figure must track the same reencode a weight
      // change drives, or a screen-reader user reads a stale value while a
      // sighted user sees the fill already updated.
      entry.el.setAttribute("aria-label", nodeAriaLabel(entry.node, heat));
    });
  }

  function nodeAriaLabel(node, heat) {
    if (node.kind === "dir") {
      return (
        dirDisplayPath(node.path) +
        " (directory, " +
        node.stats.files +
        " files, " +
        node.stats.changed +
        " changed), heat " +
        heat.toFixed(2)
      );
    }
    return node.path + " (changed in this PR), heat " + heat.toFixed(2);
  }

  function applyNodePosition(el, node) {
    el.style.left = node.x + "px";
    el.style.top = node.y + "px";
  }

  // A label sits centered just above its node mark (prototype anatomy
  // variant_B.js's `labelSel` at `y = d.y - d.r - 4`). Placed in the same
  // transformed stage as the node, so it pans/zooms with the layout and
  // follows the node when dragged (see wireDrag's reposition). CSS
  // translate(-50%, -100%) centers it horizontally and anchors its bottom
  // edge at this top coordinate.
  function applyLabelPosition(labelEl, node) {
    labelEl.style.left = node.x + "px";
    labelEl.style.top = node.y - node.r - 4 + "px";
  }

  // ---- Label culling (spec: cosmetic parity fidelity, prototype anatomy
  // variant_B.js's separate `labelNodes` selection): only the top-20 dir
  // nodes by (load_bearing + a changed-in-PR bonus) plus every satellite are
  // labeled — everything else is unlabeled (still identifiable via hover and
  // its aria-label). Ranked by load_bearing/changed only, both weight-
  // independent, so a weight-slider drag never re-ranks or re-culls labels
  // (only applyEncoding's recolor runs on reencode). ----
  var LABEL_TOP_DIR_COUNT = 20;

  function computeLabeledIds(nodes) {
    var dirNodes = nodes.filter(function (node) {
      return node.kind === "dir";
    });
    var ranked = dirNodes.slice().sort(function (a, b) {
      return labelRank(b) - labelRank(a);
    });
    var labeled = Object.create(null);
    ranked.slice(0, LABEL_TOP_DIR_COUNT).forEach(function (node) {
      labeled[node.id] = true;
    });
    nodes.forEach(function (node) {
      if (node.kind === "file") {
        labeled[node.id] = true;
      }
    });
    return labeled;
  }

  function labelRank(dirNode) {
    return (dirNode.stats.load_bearing || 0) + (dirNode.stats.changed > 0 ? 1 : 0);
  }

  // ---- Node DOM + click-vs-drag/hover wiring (spec §4.2's activation
  // scaffold, the same one the treemap tile and ledger row use). `handlers`
  // is `{ onActivate(node), onHoverShow(evt, node), onHoverMove(evt),
  // onHoverHide() }` — supplied by render() so this stays agnostic of
  // drill/focus/tooltip wiring specifics. A node outside `labeledIds` gets no
  // label element at all (not merely a hidden one) — still fully
  // identifiable via its `title`/aria-label and the hover card. ----
  function renderNodes(stage, nodes, labeledIds, handlers) {
    var entries = [];
    nodes.forEach(function (node) {
      var displayPath = node.kind === "dir" ? dirDisplayPath(node.path) : node.path;
      var el = document.createElement("div");
      el.setAttribute("class", "viz-constellation-node");
      el.setAttribute("data-kind", node.kind);
      el.setAttribute("data-path", displayPath);
      el.setAttribute("data-in-pr", node.kind === "file" ? "true" : "false");
      el.setAttribute("title", displayPath);
      // Keyboard reachability + screen-reader semantics (a11y), same
      // contract as the treemap tile, ledger row, and sonar ring mark.
      // aria-label (with its heat figure) is applyEncoding's job, called
      // right after this for both the initial render and every reencode —
      // one source of truth instead of a value here that reencode would
      // otherwise have to remember to overwrite.
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      applyNodePosition(el, node);
      el.style.width = 2 * node.r + "px";
      el.style.height = 2 * node.r + "px";

      var label = null;
      if (labeledIds[node.id]) {
        // The visual label rides ABOVE the mark as a separate stage sibling,
        // never a child of the node div — .viz-constellation-node clips
        // overflow (needed for the round mark), so a label nested inside the
        // ~4px content box of a satellite would be invisible. Presentational
        // only: the node element already carries the path via title/aria-label,
        // so aria-hidden keeps a screen reader from reading it twice.
        label = document.createElement("span");
        label.setAttribute("class", "viz-constellation-node-label");
        label.setAttribute("aria-hidden", "true");
        label.textContent = basename(displayPath);
        applyLabelPosition(label, node);
        stage.appendChild(label);
      }

      window.vizShared.wireClickVsDragActivation(el, {
        onActivate: function () {
          handlers.onActivate(node);
        },
        // Defer + cancel-on-dblclick so the un-pin gesture (see wireDrag's
        // dblclick handler) does not also fire dir focus / file drill.
        dblclickWindowMs: DBLCLICK_ACTIVATION_WINDOW_MS
      });
      el.addEventListener("pointerenter", function (evt) {
        handlers.onHoverShow(evt, node);
      });
      el.addEventListener("pointermove", function (evt) {
        handlers.onHoverMove(evt);
      });
      el.addEventListener("pointerleave", function () {
        handlers.onHoverHide();
      });

      stage.appendChild(el);
      entries.push({ node: node, el: el, labelEl: label });
    });
    return entries;
  }

  // ---- Drag-to-reposition + pin-on-drop (spec: drag must coexist with, not
  // replace, wireClickVsDragActivation's own click-vs-drag distinguishing —
  // these are separate listeners on the same element, so both run off the
  // same pointer gesture without interfering with each other). `getScale()`
  // reads the *live* zoom scale so a drag delta (in screen px) converts back
  // to the node's own untransformed coordinate space — otherwise a dragged
  // node would drift away from the cursor at any zoom level but 1. ----
  function wireDrag(entry, incidentLines, getScale) {
    var node = entry.node;
    var el = entry.el;
    var startX = 0;
    var startY = 0;
    var dragging = false;
    var active = false;

    function reposition() {
      applyNodePosition(el, node);
      // The label is a separate stage sibling, so a drag/un-pin must move it
      // in lockstep with the node (a culled node has no label — see
      // renderNodes).
      if (entry.labelEl) {
        applyLabelPosition(entry.labelEl, node);
      }
      incidentLines.forEach(function (incident) {
        updateEdgeEndpoint(incident.lineEl, incident.role, node);
      });
    }

    el.addEventListener("pointerdown", function (evt) {
      startX = evt.clientX;
      startY = evt.clientY;
      dragging = false;
      active = true;
      // Capture the pointer so pointermove/pointerup keep targeting `el` even
      // after the cursor leaves it mid-gesture (small nodes + fast drags
      // otherwise silently freeze tracking). Mirrors wireClickVsDragActivation
      // in _shared.js; capture releases implicitly on pointerup/pointercancel.
      if (el.setPointerCapture) {
        el.setPointerCapture(evt.pointerId);
      }
    });
    el.addEventListener("pointermove", function (evt) {
      if (!active) {
        return;
      }
      var dx = evt.clientX - startX;
      var dy = evt.clientY - startY;
      if (!dragging && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
        dragging = true;
      }
      if (!dragging) {
        return;
      }
      var scale = getScale();
      node.x += dx / scale;
      node.y += dy / scale;
      startX = evt.clientX;
      startY = evt.clientY;
      reposition();
    });
    function endDrag() {
      active = false;
      dragging = false;
    }
    el.addEventListener("pointerup", endDrag);
    el.addEventListener("pointercancel", endDrag);
    // Double-click un-pins: this module's layout is a one-shot pre-settled
    // simulation with no persistent forces to release a node back into (the
    // simulation is stopped and discarded right after layoutGraph() settles
    // it — spec §4.2's "no re-sim" contract) — so "un-pin" here means
    // snapping the node back to its originally-settled position
    // (node.origX/origY), the closest faithful analog to the prototype's
    // live-simulation reheat-on-unpin available under this contract.
    el.addEventListener("dblclick", function (evt) {
      evt.stopPropagation();
      node.x = node.origX;
      node.y = node.origY;
      reposition();
    });
  }

  // ---- Zoom/pan gesture filter: wheel always zooms (regardless of pointer
  // target); a double-click never zooms (explicit, so a node's own
  // double-click-to-unpin never also resets the view); any other gesture
  // that started on a node belongs to that node's own drag, not the canvas
  // pan — node dragging must never also pan the canvas. Otherwise mirrors
  // d3-zoom's own documented default filter (`(!event.ctrlKey ||
  // event.type === 'wheel') && !event.button`). ----
  function zoomFilter(event) {
    if (event.type === "dblclick") {
      return false;
    }
    if (event.type !== "wheel") {
      var target = event.target;
      if (target && typeof target.closest === "function" && target.closest(".viz-constellation-node")) {
        return false;
      }
    }
    return (!event.ctrlKey || event.type === "wheel") && !event.button;
  }

  // ---- Dir hover tooltip (prototype anatomy: variant_B.js's dir `mousemove`
  // branch) — hover-only, never a drill: a dir has no story/diff to show, so
  // fabricating a drill-panel record for it would be inventing content the
  // scene never attached. Built from the same shared meter-row block the
  // file score card uses (views/_shared.js), so a dir's bars mirror a file's
  // exactly. ----
  function buildDirTooltip(container, node, heatValue) {
    window.vizShared.buildScoreCard(container, dirDisplayPath(node.path), node.attributes, heatValue);

    var countsEl = document.createElement("div");
    countsEl.setAttribute("class", "viz-constellation-dir-counts");
    countsEl.textContent = node.stats.files + " files · " + node.stats.changed + " changed";
    var pathEl = container.querySelector(".viz-tooltip-path");
    container.insertBefore(countsEl, pathEl.nextSibling);
  }

  function svgEl(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs).forEach(function (key) {
      el.setAttribute(key, attrs[key]);
    });
    return el;
  }

  function buildSizeSwatch() {
    var svg = svgEl("svg", { width: "22", height: "14" });
    svg.appendChild(svgEl("circle", { cx: "5", cy: "7", r: "2.5", fill: "var(--viz-muted)" }));
    svg.appendChild(svgEl("circle", { cx: "16", cy: "7", r: "5.5", fill: "var(--viz-muted)" }));
    return svg;
  }

  function buildColorSwatch() {
    var span = document.createElement("span");
    span.setAttribute("class", "viz-constellation-legend-color");
    return span;
  }

  function buildEdgeWidthSwatch() {
    var svg = svgEl("svg", { width: "22", height: "14" });
    svg.appendChild(
      svgEl("line", { x1: "1", y1: "11", x2: "21", y2: "11", stroke: "var(--viz-muted)", "stroke-width": "1" })
    );
    svg.appendChild(
      svgEl("line", { x1: "1", y1: "5", x2: "21", y2: "5", stroke: "var(--viz-muted)", "stroke-width": "3" })
    );
    return svg;
  }

  function buildSatelliteSwatch() {
    var svg = svgEl("svg", { width: "22", height: "14" });
    svg.appendChild(svgEl("circle", { cx: "5", cy: "7", r: "4", fill: "var(--viz-muted)" }));
    svg.appendChild(
      svgEl("line", {
        x1: "9",
        y1: "7",
        x2: "17",
        y2: "7",
        stroke: "var(--viz-muted)",
        "stroke-width": "1",
        "stroke-dasharray": "2,2"
      })
    );
    svg.appendChild(
      svgEl("circle", {
        cx: "19",
        cy: "7",
        r: "2.5",
        fill: "var(--viz-heat-mid)",
        stroke: "var(--viz-fg)",
        "stroke-width": "1.5"
      })
    );
    return svg;
  }

  function legendItem(swatchEl, labelText) {
    var item = document.createElement("span");
    item.setAttribute("class", "viz-constellation-legend-item");
    item.appendChild(swatchEl);
    var label = document.createElement("span");
    label.textContent = labelText;
    item.appendChild(label);
    return item;
  }

  // ---- Legend (spec §4.5): the prototype's five entries — every encoding
  // this view actually renders (size, color, edge width, the PR-ring, and
  // the satellite tether), never an orphan entry. ----
  function buildLegend(container) {
    var legend = document.createElement("div");
    legend.setAttribute("class", "viz-constellation-legend");

    legend.appendChild(legendItem(buildSizeSwatch(), "Size = load-bearing (in-degree)"));
    legend.appendChild(legendItem(buildColorSwatch(), "Color = composite heat"));
    legend.appendChild(legendItem(buildEdgeWidthSwatch(), "Edge width = coupling strength"));

    var ring = document.createElement("span");
    ring.setAttribute("class", "viz-constellation-legend-ring");
    legend.appendChild(legendItem(ring, "Ringed dot = changed in PR"));

    legend.appendChild(legendItem(buildSatelliteSwatch(), "Satellites = the PR's changed files"));

    container.appendChild(legend);
  }

  function makeDestroy(container) {
    return function () {
      window.vizShared.hideTooltip();
      while (container.firstChild) {
        container.removeChild(container.firstChild);
      }
    };
  }

  window.vizViews.constellation = {
    render: function (container, scene, state) {
      var stage = document.createElement("div");
      stage.setAttribute("class", "viz-constellation-inner");
      container.appendChild(stage);

      if (window.vizShared.isDependencyGraphUnavailable(scene)) {
        renderUnavailable(stage);
        return {
          destroy: makeDestroy(container),
          // The unavailable state renders no encodings, so there is nothing to
          // repaint — but the handle still carries reencode to satisfy the
          // §4.2 view-module contract shape every other branch returns.
          reencode: function () {}
        };
      }

      var graph = buildGraph(scene);
      buildLegend(stage);

      var viewport = document.createElement("div");
      viewport.setAttribute("class", "viz-constellation-viewport");
      stage.appendChild(viewport);

      var visual = document.createElement("div");
      visual.setAttribute("class", "viz-constellation-stage");
      var side = layoutGraph(graph.nodes, graph.edges);
      visual.style.width = side + "px";
      visual.style.height = side + "px";
      viewport.appendChild(visual);

      // Captured once, right after the settle — the un-pin (dblclick)
      // target position for every node (see wireDrag above).
      graph.nodes.forEach(function (node) {
        node.origX = node.x;
        node.origY = node.y;
      });

      var edgeEntries = renderEdges(visual, side, graph.edges);
      var incidentByNodeId = Object.create(null);
      edgeEntries.forEach(function (entry) {
        var srcId = entry.edge.source.id;
        var tgtId = entry.edge.target.id;
        (incidentByNodeId[srcId] || (incidentByNodeId[srcId] = [])).push({
          lineEl: entry.lineEl,
          role: "source"
        });
        (incidentByNodeId[tgtId] || (incidentByNodeId[tgtId] = [])).push({
          lineEl: entry.lineEl,
          role: "target"
        });
      });

      var current = state;
      var heatScale = makeHeatColorScale();

      // ---- Zoom/pan (spec: scaleExtent [0.3, 6], wheel zoom + background
      // drag pans, double-click zoom disabled, transform persisted across
      // reencode — trivially true since reencode() never touches
      // `zoomTransform` below). The layout box (`side`) is sized from node
      // count, independent of the viewport's own on-screen size, so
      // "identity" here means this render's own computed centered baseline
      // (the layout's barycenter, side/2,side/2, centered in the viewport) —
      // not literal d3.zoomIdentity, which would just show the layout box's
      // top-left corner. The viewport's on-screen size DOES change when the
      // drill drawer opens/closes (scene.css narrows #viz-root via
      // .viz-drill-open), so the baseline is recomputed on viewport resize
      // (see the ResizeObserver below) and Reset view restores whatever the
      // current baseline is. ----
      var zoomTransform = d3.zoomIdentity;
      var zoomBehavior = d3
        .zoom()
        .scaleExtent([0.3, 6])
        .filter(zoomFilter)
        .on("zoom", function (event) {
          zoomTransform = event.transform;
          visual.style.transform =
            "translate(" + zoomTransform.x + "px," + zoomTransform.y + "px) scale(" + zoomTransform.k + ")";
        });

      // Centered baseline for the current viewport size — recomputed on resize
      // (below) because the drill drawer narrows the viewport after mount.
      function computeBaseTransform() {
        var rect = viewport.getBoundingClientRect();
        var width = rect.width || viewport.clientWidth || side;
        var height = rect.height || viewport.clientHeight || side;
        return d3.zoomIdentity.translate((width - side) / 2, (height - side) / 2);
      }
      var baseTransform = computeBaseTransform();

      // True while the stage is still parked exactly on the computed baseline
      // (no user pan/zoom since the last baseline apply). d3 assigns the target
      // transform's numeric fields verbatim, so exact equality is reliable here.
      function atBaseline() {
        return (
          zoomTransform.k === baseTransform.k &&
          zoomTransform.x === baseTransform.x &&
          zoomTransform.y === baseTransform.y
        );
      }

      d3.select(viewport).call(zoomBehavior).on("dblclick.zoom", null);
      d3.select(viewport).call(zoomBehavior.transform, baseTransform);

      // Recenter when the viewport resizes (drill drawer open/close). If the
      // user is still on the baseline, slide to the freshly centered baseline;
      // if they have panned/zoomed away, leave their transform untouched but
      // retarget Reset view to the new baseline. Feature-guarded like the
      // setPointerCapture guard above.
      var resizeObserver = null;
      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(function () {
          var wasBaseline = atBaseline();
          baseTransform = computeBaseTransform();
          if (wasBaseline) {
            d3.select(viewport).call(zoomBehavior.transform, baseTransform);
          }
        });
        resizeObserver.observe(viewport);
      }

      function focusOnNode(node) {
        var rect = viewport.getBoundingClientRect();
        var width = rect.width || viewport.clientWidth || side;
        var height = rect.height || viewport.clientHeight || side;
        var scale = Math.max(zoomTransform.k, 1.5);
        var next = d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-node.x, -node.y);
        d3.select(viewport).transition().duration(500).call(zoomBehavior.transform, next);
      }

      var resetBtn = document.createElement("button");
      resetBtn.id = "viz-constellation-reset";
      resetBtn.type = "button";
      resetBtn.setAttribute("class", "viz-btn viz-constellation-reset");
      resetBtn.textContent = "Reset view";
      resetBtn.addEventListener("click", function () {
        d3.select(viewport).transition().duration(400).call(zoomBehavior.transform, baseTransform);
      });
      viewport.appendChild(resetBtn);

      // Pruning affordance (spec: "N unconnected directories hidden") — only
      // present when the connectivity prune actually dropped something.
      if (graph.droppedDirCount > 0) {
        var hiddenCaption = document.createElement("div");
        hiddenCaption.setAttribute("class", "viz-constellation-hidden-caption");
        hiddenCaption.textContent = graph.droppedDirCount + " unconnected directories hidden";
        viewport.appendChild(hiddenCaption);
      }

      // File/satellite click keeps the existing openDrill path unchanged; a
      // dir click has no story/diff to drill into, so it only focuses.
      function onActivate(node) {
        if (node.kind === "dir") {
          focusOnNode(node);
          return;
        }
        current.openDrill({ path: node.path, orig: { file: node.file } });
      }
      function onHoverShow(evt, node) {
        window.vizShared.showTooltip(evt, function (el) {
          var heat = current.computeHeat(node.attributes);
          if (node.kind === "dir") {
            buildDirTooltip(el, node, heat);
          } else {
            window.vizShared.buildScoreCard(el, node.path, node.attributes, heat);
          }
        });
      }
      function onHoverMove(evt) {
        window.vizShared.moveTooltip(evt);
      }
      function onHoverHide() {
        window.vizShared.hideTooltip();
      }

      var labeledIds = computeLabeledIds(graph.nodes);
      var entries = renderNodes(visual, graph.nodes, labeledIds, {
        onActivate: onActivate,
        onHoverShow: onHoverShow,
        onHoverMove: onHoverMove,
        onHoverHide: onHoverHide
      });
      entries.forEach(function (entry) {
        wireDrag(entry, incidentByNodeId[entry.node.id] || [], function () {
          return zoomTransform.k;
        });
      });
      applyEncoding(entries, heatScale, current.computeHeat);

      var destroyContainer = makeDestroy(container);
      return {
        destroy: function () {
          if (resizeObserver) {
            resizeObserver.disconnect();
          }
          destroyContainer();
        },
        reencode: function (newState) {
          current = newState;
          heatScale = makeHeatColorScale();
          applyEncoding(entries, heatScale, current.computeHeat);
        }
      };
    }
  };
})();
