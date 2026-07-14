// vizsuite/views/sonar.js — the file-sonar drill module (spec §6.1: file
// sonar as a *drill*, not a top-level view — the top-level sonar was retired
// because its angular layout implied adjacency relationships the data never
// asserted). Draws concentric blast-radius rings centered on the drilled
// file, computed purely from `scene.edges`: hop-1 = its direct dependency
// neighbors in either direction, hop-2 = their neighbors, and so on. The
// containment question (how many hops away is X?) survives; angle within a
// ring carries no meaning — nodes are laid out in alphabetical path order
// purely for label spacing, never to imply a relationship the edge set
// didn't assert.
//
// Exposes `window.vizSonar.render(container, scene, centerPath) → handle`
// (handle.destroy()): a smaller, purpose-built sibling of the
// `window.vizViews` view-module contract (spec §4.2) — it mounts inside an
// app.js-owned drill-panel container rather than the shared root, so it
// isn't registered as a switchable top-level view. Every repo-derived string
// (a file path) is bound via `textContent`/attribute, never `innerHTML`,
// matching the DOM-bind invariant (spec §4.6/§9) the other view modules hold.
(function () {
  "use strict";

  var RING_GAP = 46; // px between hop rings

  // ---- scene.edges → an undirected adjacency map: "hop-1" is a direct
  // dependency neighbor "in either direction" (spec §6.1), so both endpoints
  // of every edge see each other regardless of import direction. ----
  function buildAdjacency(edges) {
    var adjacency = Object.create(null);
    function link(a, b) {
      if (!adjacency[a]) {
        adjacency[a] = [];
      }
      if (adjacency[a].indexOf(b) === -1) {
        adjacency[a].push(b);
      }
    }
    edges.forEach(function (edge) {
      link(edge.source, edge.target);
      link(edge.target, edge.source);
    });
    return adjacency;
  }

  // ---- BFS hop distance from `centerPath` over the adjacency map; returns
  // `{ path: hop }` including the center itself at hop 0. A center with no
  // edges of its own yields just `{ [centerPath]: 0 }` — the "empty
  // neighborhood" case, distinct from "no edge data at all" (decided by the
  // caller before this ever runs). ----
  function computeHops(adjacency, centerPath) {
    var hopOf = Object.create(null);
    hopOf[centerPath] = 0;
    var queue = [centerPath];
    for (var head = 0; head < queue.length; head++) {
      var current = queue[head];
      var neighbors = adjacency[current] || [];
      for (var i = 0; i < neighbors.length; i++) {
        var next = neighbors[i];
        if (!(next in hopOf)) {
          hopOf[next] = hopOf[current] + 1;
          queue.push(next);
        }
      }
    }
    return hopOf;
  }

  // ---- hopOf → [{hop, paths: [...sorted]}], hop 1..maxHop, center excluded.
  // Alphabetical order within a ring is a layout convenience only (label
  // spacing) — angular position is never a second encoding channel (spec
  // §6.1 retires angular adjacency). ----
  function groupByHop(hopOf) {
    var byHop = Object.create(null);
    var maxHop = 0;
    Object.keys(hopOf).forEach(function (path) {
      var hop = hopOf[path];
      if (hop === 0) {
        return;
      }
      if (!byHop[hop]) {
        byHop[hop] = [];
      }
      byHop[hop].push(path);
      maxHop = Math.max(maxHop, hop);
    });
    var groups = [];
    for (var hop = 1; hop <= maxHop; hop++) {
      groups.push({ hop: hop, paths: (byHop[hop] || []).slice().sort() });
    }
    return groups;
  }

  function basename(path) {
    var parts = path.split("/");
    return parts[parts.length - 1];
  }

  // ---- Unavailable state (spec: "when scene.edges is empty … the
  // affordance shows a 'dependency graph unavailable' state — never an
  // empty ring set, never a crash"). ----
  function renderUnavailable(container) {
    var message = document.createElement("div");
    message.id = "viz-sonar-unavailable";
    message.setAttribute("class", "viz-sonar-unavailable");
    message.textContent =
      "Dependency graph unavailable — this artifact was built without a fresh " +
      "graphify build, so blast-radius rings cannot be computed.";
    container.appendChild(message);
  }

  function renderRings(container, groups, centerPath, onRecenter) {
    var stage = document.createElement("div");
    stage.id = "viz-sonar-rings";
    stage.setAttribute("class", "viz-sonar-stage");
    var stageRadius = (groups.length + 1) * RING_GAP;
    var size = stageRadius * 2;
    stage.style.width = size + "px";
    stage.style.height = size + "px";

    // Decorative guide circles, one per populated hop ring — purely
    // spatial, never a second encoding channel.
    groups.forEach(function (group) {
      var guide = document.createElement("div");
      guide.setAttribute("class", "viz-sonar-ring-guide");
      guide.setAttribute("data-hop", String(group.hop));
      var diameter = group.hop * RING_GAP * 2;
      guide.style.width = diameter + "px";
      guide.style.height = diameter + "px";
      stage.appendChild(guide);
    });

    function placeNode(el, radius, angle) {
      el.style.left = stageRadius + radius * Math.cos(angle) + "px";
      el.style.top = stageRadius + radius * Math.sin(angle) + "px";
    }

    function buildNode(path, hop) {
      var node = document.createElement("div");
      node.setAttribute("class", hop === 0 ? "viz-sonar-node viz-sonar-node--center" : "viz-sonar-node");
      node.setAttribute("data-path", path);
      node.setAttribute("data-hop", String(hop));
      node.setAttribute("title", path);
      var label = document.createElement("span");
      label.setAttribute("class", "viz-sonar-node-label");
      label.textContent = basename(path);
      node.appendChild(label);
      return node;
    }

    var center = buildNode(centerPath, 0);
    placeNode(center, 0, 0);
    stage.appendChild(center);

    groups.forEach(function (group) {
      var radius = group.hop * RING_GAP;
      var count = group.paths.length;
      group.paths.forEach(function (path, index) {
        var angle = (2 * Math.PI * index) / count - Math.PI / 2;
        var node = buildNode(path, group.hop);
        // Keyboard reachability + screen-reader semantics (a11y), same
        // contract as the treemap tile and ledger row.
        node.setAttribute("role", "button");
        node.setAttribute("tabindex", "0");
        node.setAttribute("aria-label", "Recenter blast radius on " + path);
        placeNode(node, radius, angle);
        window.vizShared.wireClickVsDragActivation(node, {
          onActivate: function () {
            onRecenter(path);
          }
        });
        stage.appendChild(node);
      });
    });

    container.appendChild(stage);
  }

  window.vizSonar = {
    render: function (container, scene, centerPath) {
      var edges = scene.edges || [];
      // `null` (never an empty adjacency map) marks "no edge data at all" —
      // the unavailable state — distinct from a real, populated adjacency in
      // which the current center just happens to have no neighbors.
      var adjacency = edges.length > 0 ? buildAdjacency(edges) : null;
      var inner = null;

      // Fresh container per (re)center (spec §4.2): the previous render's
      // marks are fully removed before the next one is built, so recentering
      // never leaves a stale mark behind.
      function mount(path) {
        if (inner && inner.parentNode) {
          inner.parentNode.removeChild(inner);
        }
        inner = document.createElement("div");
        inner.setAttribute("class", "viz-sonar");
        container.appendChild(inner);

        if (!adjacency) {
          renderUnavailable(inner);
          return;
        }
        var groups = groupByHop(computeHops(adjacency, path));
        renderRings(inner, groups, path, mount);
      }

      mount(centerPath);

      return {
        destroy: function () {
          if (inner && inner.parentNode) {
            inner.parentNode.removeChild(inner);
          }
          inner = null;
        }
      };
    }
  };
})();
