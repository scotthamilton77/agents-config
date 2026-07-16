// vizsuite/views/treemap.js — the estate-treemap view module (spec §6.1),
// obeying the §4.2 view-module interface: render(container, scene, state) →
// handle, with handle.destroy(); a fresh container per render, deterministic
// pre-settled layout (d3.treemap runs once, synchronously, before first
// paint). `handle.reencode(state)` is this module's encoding-only refresh
// hook — weight/theme changes repaint tile colors without ever touching a
// tile's x/y/width/height (spec §4.2: "encoding-only changes … never re-run
// layout").
//
// Registers itself on `window.vizViews`, the registry app.js reads to mount
// every known view; this file assumes nothing about load order relative to
// app.js beyond that both run before `main()` calls `render()`.
(function () {
  "use strict";

  window.vizViews = window.vizViews || {};

  // ---- Root-files grouping (spec §6.1): loose files at repo root (no "/" in
  // their path) live under a synthetic "(root)" directory node — a real,
  // collapsible tree node, not a rendering special case. Its identity key is
  // `ROOT_GROUP_PATH`, a NUL-prefixed sentinel no real git path can ever
  // equal (git paths cannot contain a NUL byte), so it can never collide with
  // — or silently absorb — an actual top-level directory that happens to be
  // named "(root)"; that real directory keeps its own ordinary path and
  // renders as a second, distinct tile. `ROOT_GROUP_INDEX_KEY` is likewise
  // NUL-prefixed so it can never collide with a real directory's bare name in
  // `_index`. ----
  var ROOT_GROUP_NAME = "(root)";
  var ROOT_GROUP_PATH = "\u0000(root)";
  var ROOT_GROUP_INDEX_KEY = "\u0000(root)-group";

  // The full path (or, for the synthetic root group, its display name) for
  // human-facing text — aria-labels and the fill-screen control's label need
  // the full path; tile/breadcrumb text elsewhere already uses `.name` (the
  // synthetic node's own name is already the clean "(root)" string).
  function displayPathFor(data) {
    return data.path === ROOT_GROUP_PATH ? ROOT_GROUP_NAME : data.path;
  }

  // ---- Flat scene.files paths → a nested dir/file tree. Every node keeps a
  // `parent` pointer (root's is null) so a focused directory's ancestor
  // chain can be walked directly off the tree, never re-derived by splitting
  // path strings (which would mishandle the root-group's NUL-prefixed path,
  // among other things). ----
  function buildTree(files) {
    var root = {
      name: "",
      path: "",
      isFile: false,
      parent: null,
      children: [],
      _index: Object.create(null)
    };

    function ensureRootGroup() {
      var existing = root._index[ROOT_GROUP_INDEX_KEY];
      if (!existing) {
        existing = {
          name: ROOT_GROUP_NAME,
          path: ROOT_GROUP_PATH,
          isFile: false,
          parent: root,
          children: [],
          _index: Object.create(null)
        };
        root._index[ROOT_GROUP_INDEX_KEY] = existing;
        root.children.push(existing);
      }
      return existing;
    }

    files.forEach(function (file) {
      var parts = file.path.split("/");
      if (parts.length === 1) {
        var rootGroup = ensureRootGroup();
        rootGroup.children.push({
          name: parts[0],
          path: file.path,
          isFile: true,
          parent: rootGroup,
          file: file
        });
        return;
      }
      var node = root;
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        var isLeaf = i === parts.length - 1;
        if (isLeaf) {
          node.children.push({
            name: part,
            path: file.path,
            isFile: true,
            parent: node,
            file: file
          });
          continue;
        }
        var existing = node._index[part];
        if (!existing) {
          existing = {
            name: part,
            path: node.path ? node.path + "/" + part : part,
            isFile: false,
            parent: node,
            children: [],
            _index: Object.create(null)
          };
          node._index[part] = existing;
          node.children.push(existing);
        }
        node = existing;
      }
    });
    return root;
  }

  // ---- Bottom-up aggregation: a directory's heat is the *worst-offender*
  // (max) over its descendants — hiding detail behind a collapse never hides
  // risk (spec §6.1) — and `inPr`/`count` drive the default-collapse rule
  // and tile sizing respectively. ----
  function annotate(node, computeHeat) {
    if (node.isFile) {
      node.heat = computeHeat(node.file.attributes || {});
      node.inPr = Boolean(node.file.attributes && node.file.attributes.in_pr);
      node.count = 1;
      return;
    }
    var maxHeat = 0;
    var hasPr = false;
    var count = 0;
    node.children.forEach(function (child) {
      annotate(child, computeHeat);
      maxHeat = Math.max(maxHeat, child.heat);
      hasPr = hasPr || child.inPr;
      count += child.count;
    });
    node.heat = maxHeat;
    node.inPr = hasPr;
    node.count = count || 1;
  }

  // ---- Default collapse (spec §6.1): a group with no PR-touched
  // descendant starts collapsed, at every depth; root is never collapsible. ----
  function collectDefaultCollapsed(node, collapsed) {
    if (node.isFile) {
      return;
    }
    node.children.forEach(function (child) {
      collectDefaultCollapsed(child, collapsed);
    });
    if (node.path && !node.inPr) {
      collapsed[node.path] = true;
    }
  }

  // ---- path → node lookup, every node except the true estate root (whose
  // path is "") — resolves a persisted or focused path string back to a real
  // tree node without re-walking the tree from scratch each time. ----
  function indexTreeByPath(node, index) {
    if (node.path) {
      index[node.path] = node;
    }
    if (node.children) {
      node.children.forEach(function (child) {
        indexTreeByPath(child, index);
      });
    }
  }

  // Ancestor chain from (but excluding) the true estate root down to `node`,
  // in breadcrumb reading order — walked via the real tree's `parent`
  // pointers, never by splitting `node.path` (which would mishandle the
  // root-group's NUL-prefixed sentinel).
  function collectAncestorChain(node) {
    var chain = [];
    var current = node;
    while (current && current.path !== "") {
      chain.unshift(current);
      current = current.parent;
    }
    return chain;
  }

  // ---- Prune the tree for layout: a collapsed directory becomes a leaf
  // (sized by its file count, colored by its rolled-up heat) so the treemap
  // reflows — siblings absorb the freed space (spec §6.1). `isLayoutRoot` is
  // true only for the top node handed to this render pass (the whole estate,
  // or — while a directory is focused — that directory) so it is never
  // itself treated as collapsed regardless of its own entry in `collapsed`:
  // it has just become the effective root filling the canvas, and its own
  // collapse bookkeeping is left untouched for when focus pops back out. ----
  function pruneForLayout(node, collapsed, isLayoutRoot) {
    if (node.isFile) {
      return {
        name: node.name,
        path: node.path,
        isFile: true,
        collapsed: false,
        heat: node.heat,
        inPr: node.inPr,
        value: 1,
        orig: node
      };
    }
    var isCollapsed = !isLayoutRoot && Boolean(node.path) && Boolean(collapsed[node.path]);
    if (isCollapsed) {
      return {
        name: node.name,
        path: node.path,
        isFile: false,
        collapsed: true,
        heat: node.heat,
        inPr: node.inPr,
        count: node.count,
        // Nominal, sub-linear sizing — collapse is an attention-allocation
        // act (spec §6.1): a collapsed group must actually shrink (never
        // keep its expanded footprint) so siblings absorb the freed space.
        // A mild log scale still hints "more hidden here" without ever
        // approaching the group's expanded, file-count-proportional area.
        value: Math.max(1, Math.log2(node.count + 1)),
        orig: node
      };
    }
    return {
      name: node.name,
      path: node.path,
      isFile: false,
      collapsed: false,
      heat: node.heat,
      inPr: node.inPr,
      children: node.children.map(function (child) {
        return pruneForLayout(child, collapsed, false);
      }),
      orig: node
    };
  }

  function layoutTreemap(root, width, height) {
    var hierarchyRoot = d3
      .hierarchy(root, function (d) {
        return d.children;
      })
      .sum(function (d) {
        return d.value || 0;
      })
      .sort(function (a, b) {
        return b.value - a.value;
      });
    d3
      .treemap()
      .size([width, height])
      .paddingOuter(2)
      .paddingTop(function (d) {
        return d.children ? 16 : 0;
      })
      .paddingInner(1)
      .round(true)(hierarchyRoot);
    return hierarchyRoot;
  }

  // ---- Heat color scale (spec §4.3): the ramp anchors are `:root` custom
  // properties, resolved fresh so a theme change (media query or the
  // `data-viz-theme` stamp) picks up its own twin on the next reencode. ----
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

  // Label color chosen by luminance of the underlying fill, per theme (spec §4.3).
  function labelColorFor(colorString) {
    var rgb = d3.rgb(colorString);
    var luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
    return luminance > 0.6 ? "var(--viz-label-on-light-fill)" : "var(--viz-label-on-dark-fill)";
  }

  // ---- Encoding-only repaint: background + label color from the current
  // heat scale, and label-declutter (hide labels tiles too small to hold
  // them) — never touches x0/y0/x1/y1 (no layout re-run). ----
  function applyEncoding(selection, heatScale) {
    selection.each(function (d) {
      var wrapper = d3.select(this);
      var isLeafLike = d.data.isFile || d.data.collapsed;
      var label = wrapper.select(".viz-tile-label");
      if (isLeafLike) {
        var color = heatScale(d.data.heat);
        wrapper.style("background-color", color);
        label.style("color", labelColorFor(color));
      } else {
        wrapper.style("background-color", null);
        label.style("color", null);
      }
      var width = d.x1 - d.x0;
      var height = d.y1 - d.y0;
      var minHeight = d.data.isFile ? 12 : 18;
      label.classed("viz-tile-label--hidden", width < 26 || height < minHeight);
    });
  }

  // Click-vs-drag(-vs-double-click) threshold (~4px, spec §4.2), via the
  // shared `window.vizShared.wireClickVsDragActivation` (also used by the
  // ledger row and the sonar ring mark — see views/_shared.js): reads the
  // *live* bound datum at activation time (never a captured snapshot), so a
  // tile that has survived several re-layouts always acts on its current
  // data. A directory tile's kind (file vs. directory) never changes across
  // its lifetime — a given path is either a blob or a tree, never both — so
  // deciding once, at wiring time, whether to offer double-activation is
  // safe: file tiles never get it (their single-click drill-open keeps firing
  // with zero added latency, exactly as before this option existed);
  // directory tiles do, promoting the directory to the fill-screen focus
  // root (spec §6.1).
  function wireTileInteractions(el, handlers) {
    var initialDatum = d3.select(el).datum();
    var isDir = !initialDatum.data.isFile;
    window.vizShared.wireClickVsDragActivation(el, {
      onActivate: function () {
        var current = d3.select(el).datum();
        if (current.data.isFile) {
          handlers.onFileClick(current.data);
        } else {
          handlers.onDirClick(current.data);
        }
      },
      onDoubleActivate: isDir
        ? function () {
            var current = d3.select(el).datum();
            if (!current.data.isFile) {
              handlers.onDirFocus(current.data);
            }
          }
        : undefined
    });
  }

  // Accessible name for a tile (a11y), set via the `aria-label` attribute —
  // repo-derived path strings flow through d3's `.attr()` (never innerHTML), so
  // the textContent/attribute-only binding invariant holds. Recomputed in the
  // merged attr chain on every render so a directory's collapsed/expanded flip
  // updates its announced state.
  function tileAriaLabel(d) {
    var data = d.data;
    if (data.isFile) {
      return data.path;
    }
    if (data.collapsed) {
      return displayPathFor(data) + " (collapsed directory, " + data.count + " files)";
    }
    return displayPathFor(data) + " (directory)";
  }

  function wireFocusButton(button, wrapperNode, handlers) {
    // The button is its own activation target — never let its own events
    // also trigger the tile's own click-vs-drag activation (collapse
    // toggle), the same guard views/ledger.js uses for its diff-link nested
    // inside an activatable row.
    ["click", "keydown", "pointerdown", "pointerup"].forEach(function (type) {
      button.addEventListener(type, function (evt) {
        evt.stopPropagation();
      });
    });
    button.addEventListener("click", function () {
      var current = d3.select(wrapperNode).datum();
      handlers.onDirFocus(current.data);
    });
  }

  function buildTileContent(wrapper, d, handlers) {
    if (d.data.isFile) {
      wrapper.append("span").attr("class", "viz-tile-label").text(function (d) { return d.data.name; });
      return;
    }
    if (d.data.collapsed) {
      var label = wrapper.append("span").attr("class", "viz-tile-label");
      label.append("span").attr("class", "viz-collapse-glyph");
      label.append("span").text(function (d) {
        return " " + d.data.name + " (" + d.data.count + ")";
      });
      return;
    }
    var header = wrapper.append("div").attr("class", "viz-tile-header");
    header.append("span").attr("class", "viz-collapse-glyph");
    header
      .append("span")
      .attr("class", "viz-tile-label")
      .text(function (d) {
        return d.data.name;
      });
    // Explicit fill-screen control (spec §6.1), alongside double-clicking the
    // tile itself — only ever present on an *expanded* directory's own header
    // (a collapsed directory has no header at all; double-click on its leaf-
    // style tile is still its own path to focus).
    var focusBtn = header
      .append("button")
      .attr("type", "button")
      .attr("class", "viz-tile-focus-btn")
      .text("Focus")
      .attr("aria-label", function (d) {
        return "Fill the screen with " + displayPathFor(d.data);
      });
    wireFocusButton(focusBtn.node(), wrapper.node(), handlers);
  }

  function renderTiles(stageEl, layoutRoot, collapsed, heatScale, handlers) {
    var rect = stageEl.getBoundingClientRect();
    var width = rect.width || stageEl.clientWidth || 960;
    var height = rect.height || stageEl.clientHeight || 600;
    var pruned = pruneForLayout(layoutRoot, collapsed, true);
    var hierarchyRoot = layoutTreemap(pruned, width, height);
    var nodes = hierarchyRoot.descendants().filter(function (d) {
      return d.depth > 0;
    });

    var sel = d3
      .select(stageEl)
      .selectAll("div.viz-tile")
      .data(nodes, function (d) {
        return d.data.path;
      });

    sel.exit().remove();

    var entered = sel.enter().append("div");
    var merged = entered.merge(sel);

    merged
      .attr("class", function (d) {
        return "viz-tile " + (d.data.isFile ? "viz-tile--file" : "viz-tile--dir");
      })
      .attr("data-path", function (d) {
        return d.data.path;
      })
      .attr("data-collapsed", function (d) {
        return d.data.collapsed ? "true" : "false";
      })
      .attr("data-in-pr", function (d) {
        return d.data.inPr ? "true" : "false";
      })
      // Keyboard reachability + screen-reader semantics (a11y): tiles are
      // focusable buttons with an accessible name. Re-applied every render so
      // rebuilt/toggled tiles keep the contract.
      .attr("role", "button")
      .attr("tabindex", "0")
      .attr("aria-label", tileAriaLabel)
      .style("left", function (d) {
        return d.x0 + "px";
      })
      .style("top", function (d) {
        return d.y0 + "px";
      })
      .style("width", function (d) {
        return Math.max(0, d.x1 - d.x0) + "px";
      })
      .style("height", function (d) {
        return Math.max(0, d.y1 - d.y0) + "px";
      });

    // Content is rebuilt on every full render (mount, collapse toggle,
    // resize) — cheap at estate scale and the only way a persisting
    // directory tile's chrome can flip between its expanded/collapsed shape.
    merged.each(function (d) {
      var wrapper = d3.select(this);
      wrapper.selectAll("*").remove();
      buildTileContent(wrapper, d, handlers);
    });

    entered.each(function () {
      wireTileInteractions(this, handlers);
    });

    applyEncoding(merged, heatScale);
  }

  // ---- Breadcrumb strip (spec §6.1): visible only while a directory is
  // focused as the temporary layout root. "Whole estate" always pops focus
  // entirely; every other crumb re-focuses on that ancestor (a partial pop);
  // the last crumb (the current focus) is plain text, not a no-op button. ----
  function renderBreadcrumb(breadcrumbEl, pathIndex, focusPath, onNavigate) {
    while (breadcrumbEl.firstChild) {
      breadcrumbEl.removeChild(breadcrumbEl.firstChild);
    }
    var focusNode = focusPath ? pathIndex[focusPath] : null;
    if (!focusNode || focusNode.isFile) {
      breadcrumbEl.hidden = true;
      return;
    }
    breadcrumbEl.hidden = false;

    var homeCrumb = document.createElement("button");
    homeCrumb.type = "button";
    homeCrumb.setAttribute("class", "viz-btn");
    homeCrumb.textContent = "Whole estate";
    homeCrumb.addEventListener("click", function () {
      onNavigate(null);
    });
    breadcrumbEl.appendChild(homeCrumb);

    var chain = collectAncestorChain(focusNode);
    chain.forEach(function (ancestor, index) {
      var sep = document.createElement("span");
      sep.setAttribute("class", "viz-treemap-crumb-sep");
      sep.textContent = "/";
      breadcrumbEl.appendChild(sep);

      if (index === chain.length - 1) {
        var current = document.createElement("span");
        current.setAttribute("class", "viz-treemap-crumb--current");
        current.textContent = ancestor.name;
        breadcrumbEl.appendChild(current);
        return;
      }
      var crumb = document.createElement("button");
      crumb.type = "button";
      crumb.setAttribute("class", "viz-btn");
      crumb.textContent = ancestor.name;
      crumb.addEventListener("click", function () {
        onNavigate(ancestor.path);
      });
      breadcrumbEl.appendChild(crumb);
    });
  }

  // ---- Collapse/focus persistence (spec §6.1): localStorage, feature-
  // detected exactly like app.js's annotation store (in-memory fallback, no
  // crash on file:// or disabled storage) — a fixed per-repo key (no PR
  // number in it, matching the annotation store's own per-repo scoping), so a
  // reviewer's collapse/focus choices carry over between PR artifacts of the
  // same repo. ----
  function makeTreemapStateStore(repoNwo) {
    var key = "viz:" + repoNwo + ":pr:treemap-state";
    // A NUL-suffixed probe key so the availability check never reads or
    // clobbers the one real key this store ever touches.
    var probeKey = key + "\u0000probe";
    var available = false;
    try {
      window.localStorage.setItem(probeKey, "1");
      window.localStorage.removeItem(probeKey);
      available = true;
    } catch (err) {
      available = false;
    }
    var memoryValue = null;

    function load() {
      var raw = available ? window.localStorage.getItem(key) : memoryValue;
      if (!raw) {
        return null;
      }
      try {
        var parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : null;
      } catch (err) {
        return null;
      }
    }

    function save(state) {
      var raw = JSON.stringify(state);
      if (available) {
        try {
          window.localStorage.setItem(key, raw);
          return;
        } catch (err) {
          // Fall through to the in-memory fallback (e.g. quota exceeded).
        }
      }
      memoryValue = raw;
    }

    function clear() {
      if (available) {
        try {
          window.localStorage.removeItem(key);
        } catch (err) {
          // ignore — nothing else to fall back to for a removal
        }
      }
      memoryValue = null;
    }

    return { load: load, save: save, clear: clear };
  }

  window.vizViews.treemap = {
    render: function (container, scene, state) {
      var tree = buildTree(scene.files);
      var current = state;
      annotate(tree, current.computeHeat);

      var pathIndex = Object.create(null);
      indexTreeByPath(tree, pathIndex);

      var collapsed = Object.create(null);
      collectDefaultCollapsed(tree, collapsed);

      var stateStore = makeTreemapStateStore(scene.repo_nwo);
      var focusPath = null;

      // Merge the persisted collapse/expand deltas and focus root over the
      // freshly-computed defaults (spec §6.1) — a path the current scene no
      // longer has (or that is no longer a directory) is pruned silently
      // rather than applied.
      var persisted = stateStore.load();
      if (persisted) {
        var delta =
          persisted.collapseDelta && typeof persisted.collapseDelta === "object"
            ? persisted.collapseDelta
            : {};
        Object.keys(delta).forEach(function (path) {
          var node = pathIndex[path];
          if (!node || node.isFile) {
            return;
          }
          if (delta[path]) {
            collapsed[path] = true;
          } else {
            delete collapsed[path];
          }
        });
        if (typeof persisted.focusRoot === "string") {
          var focusNode = pathIndex[persisted.focusRoot];
          if (focusNode && !focusNode.isFile) {
            focusPath = persisted.focusRoot;
          }
        }
      }

      var heatScale = makeHeatColorScale();

      // ---- Chrome: a reset control and the focus breadcrumb strip, flow-
      // laid-out above the absolutely-positioned tile stage — scoped to this
      // view's own container, so switching to another view removes them
      // along with everything else this module owns (spec §4.2). ----
      var controlsRow = document.createElement("div");
      controlsRow.setAttribute("class", "viz-treemap-controls");
      var resetBtn = document.createElement("button");
      resetBtn.id = "viz-treemap-reset";
      resetBtn.type = "button";
      resetBtn.setAttribute("class", "viz-btn");
      resetBtn.textContent = "Reset view";
      controlsRow.appendChild(resetBtn);
      container.appendChild(controlsRow);

      var breadcrumbEl = document.createElement("div");
      breadcrumbEl.id = "viz-treemap-breadcrumb";
      breadcrumbEl.setAttribute("class", "viz-treemap-breadcrumb");
      breadcrumbEl.hidden = true;
      container.appendChild(breadcrumbEl);

      var stageEl = document.createElement("div");
      stageEl.setAttribute("class", "viz-treemap-stage");
      container.appendChild(stageEl);

      function persistState() {
        var defaults = Object.create(null);
        collectDefaultCollapsed(tree, defaults);
        var delta = {};
        Object.keys(collapsed).forEach(function (path) {
          if (!defaults[path]) {
            delta[path] = true;
          }
        });
        Object.keys(defaults).forEach(function (path) {
          if (!collapsed[path]) {
            delta[path] = false;
          }
        });
        stateStore.save({ collapseDelta: delta, focusRoot: focusPath });
      }

      function setFocus(path) {
        focusPath = path;
        persistState();
        fullRender();
      }

      var handlers = {
        onDirClick: function (data) {
          if (collapsed[data.path]) {
            delete collapsed[data.path];
          } else {
            collapsed[data.path] = true;
          }
          persistState();
          fullRender();
        },
        onDirFocus: function (data) {
          setFocus(data.path);
        },
        onFileClick: function (data) {
          current.openDrill(data);
        }
      };

      function fullRender() {
        var layoutRoot = tree;
        if (focusPath) {
          var focusNode = pathIndex[focusPath];
          if (focusNode && !focusNode.isFile) {
            layoutRoot = focusNode;
          }
        }
        renderTiles(stageEl, layoutRoot, collapsed, heatScale, handlers);
        renderBreadcrumb(breadcrumbEl, pathIndex, focusPath, setFocus);
      }

      resetBtn.addEventListener("click", function () {
        collapsed = Object.create(null);
        collectDefaultCollapsed(tree, collapsed);
        focusPath = null;
        stateStore.clear();
        fullRender();
      });

      fullRender();

      var resizeDebounceTimer = null;
      var resizeHandler = function () {
        if (resizeDebounceTimer) {
          clearTimeout(resizeDebounceTimer);
        }
        resizeDebounceTimer = setTimeout(function () {
          resizeDebounceTimer = null;
          fullRender();
        }, 150);
      };
      window.addEventListener("resize", resizeHandler);

      return {
        destroy: function () {
          if (resizeDebounceTimer) {
            clearTimeout(resizeDebounceTimer);
          }
          window.removeEventListener("resize", resizeHandler);
          d3.select(container).selectAll("*").remove();
        },
        reencode: function (newState) {
          current = newState;
          annotate(tree, current.computeHeat);
          heatScale = makeHeatColorScale();
          var selection = d3.select(stageEl).selectAll("div.viz-tile");
          selection.each(function (d) {
            d.data.heat = d.data.orig.heat;
          });
          applyEncoding(selection, heatScale);
        }
      };
    }
  };
})();
