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
// node.x/node.y (spec §4.2 "no re-sim on slider drag").
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
// `title`/`aria-label` attribute, never `innerHTML` — matching the DOM-bind
// invariant the other view modules hold.
(function () {
  "use strict";

  window.vizViews = window.vizViews || {};

  var FIXED_TICKS = 300;
  // Any fixed constant works; changing it changes the settled layout but
  // never removes its determinism (spec §4.2).
  var LAYOUT_SEED = 1337;
  var NODE_RADIUS = 13; // px; approximates the CSS node mark's 1.7rem box for layout math only

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
            return d.path;
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

  function renderEdges(stage, side, edges) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "viz-constellation-edges");
    svg.setAttribute("width", String(side));
    svg.setAttribute("height", String(side));
    edges.forEach(function (edge) {
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
    });
    stage.appendChild(svg);
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

  function renderNodes(stage, nodes, openDrill) {
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
      el.style.left = node.x + "px";
      el.style.top = node.y + "px";

      var label = document.createElement("span");
      label.setAttribute("class", "viz-constellation-node-label");
      label.textContent = basename(node.path);
      el.appendChild(label);

      window.vizShared.wireClickVsDragActivation(el, {
        onActivate: function () {
          openDrill({ path: node.path, orig: { file: node.file } });
        }
      });

      stage.appendChild(el);
      entries.push({ node: node, el: el, labelEl: label });
    });
    return entries;
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
          destroy: makeDestroy(container)
        };
      }

      var graph = buildGraph(scene);
      buildLegend(stage);

      var visual = document.createElement("div");
      visual.setAttribute("class", "viz-constellation-stage");
      var side = layoutGraph(graph.nodes, graph.edges);
      visual.style.width = side + "px";
      visual.style.height = side + "px";
      stage.appendChild(visual);

      renderEdges(visual, side, graph.edges);

      var current = state;
      var heatScale = makeHeatColorScale();
      var entries = renderNodes(visual, graph.nodes, current.openDrill);
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
