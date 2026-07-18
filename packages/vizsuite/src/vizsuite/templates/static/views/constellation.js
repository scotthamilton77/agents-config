// vizsuite/views/constellation.js — the dependency constellation view module
// (spec §6.1: "build, evaluation-gated" §11 — shipped inlined but never
// mounted by default; app.js registers it behind a default-off experimental
// toggle). Obeys the §4.2 view-module interface: render(container, scene,
// state) → handle, with handle.destroy() and handle.reencode(state).
//
// Node set (spec §6.1 "PR files + context graph"): every PR-touched file
// (attributes.in_pr) is always a node, even with zero edges of its own — an
// isolated PR file still belongs on the graph; a context (non-PR) file is a
// node only when scene.edges actually connects it to something, otherwise it
// isn't part of "the graph" at all. `scene.files` is the *whole estate*
// (assemble.py), so building the node set from PR files ∪ edge endpoints —
// never from every scene.files entry — is what keeps this a small, legible
// PR-shape subgraph instead of a second treemap.
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
// node list is sorted by path before layout runs (spec test item 6: the same
// scene always settles the same graph). `handle.reencode(state)` repaints
// node fill colors only — it never re-creates the simulation or touches
// node.x/node.y (spec §4.2 "no re-sim on slider drag"), and interaction
// (drag/pin, zoom/pan transform) never runs a fresh simulation tick either —
// there is no persistent simulation after the initial synchronous settle.
//
// Interaction parity (fidelity, prototype anatomy `variant_B.js`):
//   - Hover score card: the same shared tooltip (views/_shared.js
//     showTooltip/buildScoreCard) the treemap tile and ledger row use.
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
//   - Click-to-focus: an explicit `focusOnNode` zoom-to mechanism (min scale
//     1.5, ~500ms), wired to node activation once dir nodes exist.
//
// Legend (spec §4.5 "legend completeness"): rendered *inside* this module's
// own container, never into the shared `#viz-legend` app.js owns for
// treemap/ledger — the view-module contract forbids styling/rendering
// outside the fresh container a view was handed (spec §4.2), and this view's
// encodings (heat fill, the PR-ring, the dependency edge line) differ from
// treemap/ledger's, so a legend of its own is the only way to keep every
// entry backed by a real referent.
//
// Every repo-derived string (a file path) is bound via `textContent`/
// `title`/`aria-label` attribute, never `innerHTML`, matching the DOM-bind
// invariant the other view modules hold.
(function () {
  "use strict";

  window.vizViews = window.vizViews || {};

  var FIXED_TICKS = 300;
  // Any fixed constant works; changing it changes the settled layout but
  // never removes its determinism (spec §4.2).
  var LAYOUT_SEED = 1337;
  var NODE_RADIUS = 13; // px; approximates the CSS node mark's 1.7rem box for layout math only
  var DRAG_THRESHOLD = 4; // px; same click-vs-drag threshold as wireClickVsDragActivation

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

  // ---- scene.files + scene.edges → { nodes, edges } for the layout. Always
  // builds a graph: the "dependency graph unavailable" state is decided by the
  // caller from render_config.unavailable_axes (the load-bearing axis
  // fail-softed), NOT from an empty edge set. An available axis with zero
  // cross-file edges still yields the PR-file node set (isolated nodes), the
  // legitimately-empty rendering — same disambiguation file sonar makes. ----
  function buildGraph(scene) {
    var rawEdges = scene.edges || [];

    var fileByPath = Object.create(null);
    scene.files.forEach(function (file) {
      fileByPath[file.path] = file;
    });

    var nodeSet = Object.create(null);
    var nodePaths = [];
    function addNode(path) {
      if (!nodeSet[path]) {
        nodeSet[path] = true;
        nodePaths.push(path);
      }
    }

    // PR files are always nodes, even isolated ones (spec: "PR files +
    // context graph" — a PR-touched file belongs on the graph regardless of
    // whether this run's edge set happens to connect it to anything).
    scene.files.forEach(function (file) {
      if (file.attributes && file.attributes.in_pr) {
        addNode(file.path);
      }
    });

    // Context files are nodes only via an edge (that's what makes them part
    // of "the graph" rather than the whole estate); dedup by unordered pair
    // so an A→B/B→A pair (or an exact repeat) draws one line, not two
    // indistinguishable overlapping ones — this view never encodes import
    // direction (same "either direction" stance file sonar takes for its
    // blast-radius hops).
    var seenPairs = Object.create(null);
    var edges = [];
    rawEdges.forEach(function (edge) {
      addNode(edge.source);
      addNode(edge.target);
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

    // Sorted so the node list — and therefore d3-force's index-based initial
    // phyllotaxis spiral — is a pure function of the node identities, never
    // of incidental scene.files/scene.edges iteration order.
    var nodes = nodePaths
      .slice()
      .sort()
      .map(function (path) {
        // A context path absent from scene.files would be a scene data-
        // integrity bug upstream (every edge endpoint should be a tracked
        // estate path per assemble.py) — default to an empty-attribute file
        // rather than crash, so the graph still renders the node's identity.
        var file = fileByPath[path] || { path: path, checksum: "", attributes: {} };
        var attributes = file.attributes || {};
        return {
          id: "file:" + path,
          kind: "file",
          path: path,
          file: file,
          inPr: Boolean(attributes.in_pr)
        };
      });

    return { nodes: nodes, edges: edges };
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
          .distance(64)
          .strength(0.5)
      )
      .force("charge", d3.forceManyBody().strength(-160))
      .force("center", d3.forceCenter(side / 2, side / 2))
      .force("collide", d3.forceCollide(NODE_RADIUS + 8))
      .alpha(1)
      .alphaDecay(1 - Math.pow(0.001, 1 / FIXED_TICKS));

    simulation.tick(FIXED_TICKS);
    simulation.stop();

    // Defensive containment, not a determinism mechanism (the tick sequence
    // above already is fully deterministic): forceCenter pulls the
    // barycenter toward the stage center but places no hard wall, so a
    // sparse graph can still settle a hair outside the box without this.
    nodes.forEach(function (node) {
      node.x = Math.min(side - NODE_RADIUS, Math.max(NODE_RADIUS, node.x));
      node.y = Math.min(side - NODE_RADIUS, Math.max(NODE_RADIUS, node.y));
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
      // `{source, target}` copies buildGraph() made are what absorbed that
      // mutation, never scene.edges itself, so sonar's later reads of
      // scene.edges (string source/target) are untouched.
      var line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("class", "viz-constellation-edge");
      line.setAttribute("x1", String(edge.source.x));
      line.setAttribute("y1", String(edge.source.y));
      line.setAttribute("x2", String(edge.target.x));
      line.setAttribute("y2", String(edge.target.y));
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

  // ---- Heat color scale (spec §4.3): mirrors the treemap view's own scale
  // (same `:root` custom-property anchors), resolved fresh on every render
  // and reencode so a theme change picks up its own twin. ----
  function makeHeatColorScale() {
    var style = getComputedStyle(document.documentElement);
    var cold = style.getPropertyValue("--viz-heat-cold").trim();
    var mid = style.getPropertyValue("--viz-heat-mid").trim();
    var hot = style.getPropertyValue("--viz-heat-hot").trim();
    return d3
      .scaleLinear()
      .domain([0, 0.5, 1])
      .range([cold, mid, hot])
      .interpolate(d3.interpolateRgb)
      .clamp(true);
  }

  function labelColorFor(colorString) {
    var rgb = d3.rgb(colorString);
    var luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
    return luminance > 0.6 ? "var(--viz-label-on-light-fill)" : "var(--viz-label-on-dark-fill)";
  }

  function applyEncoding(entries, heatScale, computeHeat) {
    entries.forEach(function (entry) {
      var heat = computeHeat(entry.node.file.attributes || {});
      var color = heatScale(heat);
      entry.el.style.backgroundColor = color;
      entry.labelEl.style.color = labelColorFor(color);
      // The aria-label's heat figure must track the same reencode a weight
      // change drives, or a screen-reader user reads a stale value while a
      // sighted user sees the fill already updated.
      entry.el.setAttribute("aria-label", nodeAriaLabel(entry.node, heat));
    });
  }

  function nodeAriaLabel(node, heat) {
    return (
      node.path +
      (node.inPr ? " (changed in this PR)" : " (context file)") +
      ", heat " +
      heat.toFixed(2)
    );
  }

  function applyNodePosition(el, node) {
    el.style.left = node.x + "px";
    el.style.top = node.y + "px";
  }

  // ---- Node DOM + click-vs-drag/hover wiring (spec §4.2's activation
  // scaffold, the same one the treemap tile and ledger row use). `handlers`
  // is `{ onActivate(node), onHoverShow(evt, node), onHoverMove(evt),
  // onHoverHide() }` — supplied by render() so this stays agnostic of
  // drill/focus/tooltip wiring specifics. ----
  function renderNodes(stage, nodes, handlers) {
    var entries = [];
    nodes.forEach(function (node) {
      var el = document.createElement("div");
      el.setAttribute("class", "viz-constellation-node");
      el.setAttribute("data-path", node.path);
      el.setAttribute("data-in-pr", node.inPr ? "true" : "false");
      el.setAttribute("title", node.path);
      // Keyboard reachability + screen-reader semantics (a11y), same
      // contract as the treemap tile, ledger row, and sonar ring mark.
      // aria-label (with its heat figure) is applyEncoding's job, called
      // right after this for both the initial render and every reencode —
      // one source of truth instead of a value here that reencode would
      // otherwise have to remember to overwrite.
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      applyNodePosition(el, node);

      var label = document.createElement("span");
      label.setAttribute("class", "viz-constellation-node-label");
      label.textContent = basename(node.path);
      el.appendChild(label);

      window.vizShared.wireClickVsDragActivation(el, {
        onActivate: function () {
          handlers.onActivate(node);
        }
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
      incidentLines.forEach(function (incident) {
        updateEdgeEndpoint(incident.lineEl, incident.role, node);
      });
    }

    el.addEventListener("pointerdown", function (evt) {
      startX = evt.clientX;
      startY = evt.clientY;
      dragging = false;
      active = true;
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

  // ---- Legend (spec §4.5): every encoding this view renders, in its own
  // container — heat fill, the PR-ring, and the dependency edge line. ----
  function buildLegend(container) {
    var legend = document.createElement("div");
    legend.setAttribute("class", "viz-constellation-legend");

    var heatStops = [
      { token: "heat-cold", label: "low attention" },
      { token: "heat-mid", label: "medium attention" },
      { token: "heat-hot", label: "high attention" }
    ];
    heatStops.forEach(function (stop) {
      var item = document.createElement("span");
      item.setAttribute("class", "viz-constellation-legend-item");
      var swatch = document.createElement("span");
      swatch.setAttribute("class", "viz-constellation-legend-swatch");
      swatch.style.background = "var(--viz-" + stop.token + ")";
      var label = document.createElement("span");
      label.textContent = stop.label;
      item.appendChild(swatch);
      item.appendChild(label);
      legend.appendChild(item);
    });

    var prItem = document.createElement("span");
    prItem.setAttribute("class", "viz-constellation-legend-item");
    var prRing = document.createElement("span");
    prRing.setAttribute("class", "viz-constellation-legend-ring");
    var prLabel = document.createElement("span");
    prLabel.textContent = "file changed in this PR";
    prItem.appendChild(prRing);
    prItem.appendChild(prLabel);
    legend.appendChild(prItem);

    var edgeItem = document.createElement("span");
    edgeItem.setAttribute("class", "viz-constellation-legend-item");
    var edgeLine = document.createElement("span");
    edgeLine.setAttribute("class", "viz-constellation-legend-line");
    var edgeLabel = document.createElement("span");
    edgeLabel.textContent = "file dependency";
    edgeItem.appendChild(edgeLine);
    edgeItem.appendChild(edgeLabel);
    legend.appendChild(edgeItem);

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
      // top-left corner. Reset view restores exactly this same baseline. ----
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

      var viewportRect = viewport.getBoundingClientRect();
      var viewportWidth = viewportRect.width || viewport.clientWidth || side;
      var viewportHeight = viewportRect.height || viewport.clientHeight || side;
      var baseTransform = d3.zoomIdentity.translate(
        (viewportWidth - side) / 2,
        (viewportHeight - side) / 2
      );

      d3.select(viewport).call(zoomBehavior).on("dblclick.zoom", null);
      d3.select(viewport).call(zoomBehavior.transform, baseTransform);

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

      function onActivate(node) {
        current.openDrill({ path: node.path, orig: { file: node.file } });
      }
      function onHoverShow(evt, node) {
        window.vizShared.showTooltip(evt, function (el) {
          window.vizShared.buildScoreCard(
            el, node.path, node.file.attributes || {}, current.computeHeat(node.file.attributes || {})
          );
        });
      }
      function onHoverMove(evt) {
        window.vizShared.moveTooltip(evt);
      }
      function onHoverHide() {
        window.vizShared.hideTooltip();
      }

      var entries = renderNodes(visual, graph.nodes, {
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

      return {
        destroy: makeDestroy(container),
        reencode: function (newState) {
          current = newState;
          heatScale = makeHeatColorScale();
          applyEncoding(entries, heatScale, current.computeHeat);
        }
      };
    }
  };
})();
