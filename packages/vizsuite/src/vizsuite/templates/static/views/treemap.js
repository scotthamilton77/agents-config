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

  // ---- Flat scene.files paths → a nested dir/file tree. ----
  function buildTree(files) {
    var root = { name: "", path: "", isFile: false, children: [], _index: Object.create(null) };
    files.forEach(function (file) {
      var parts = file.path.split("/");
      var node = root;
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        var isLeaf = i === parts.length - 1;
        if (isLeaf) {
          node.children.push({ name: part, path: file.path, isFile: true, file: file });
          continue;
        }
        var existing = node._index[part];
        if (!existing) {
          existing = {
            name: part,
            path: node.path ? node.path + "/" + part : part,
            isFile: false,
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

  // ---- Prune the tree for layout: a collapsed directory becomes a leaf
  // (sized by its file count, colored by its rolled-up heat) so the treemap
  // reflows — siblings absorb the freed space (spec §6.1). ----
  function pruneForLayout(node, collapsed) {
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
    var isCollapsed = Boolean(node.path) && Boolean(collapsed[node.path]);
    if (isCollapsed) {
      return {
        name: node.name,
        path: node.path,
        isFile: false,
        collapsed: true,
        heat: node.heat,
        inPr: node.inPr,
        value: node.count,
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
        return pruneForLayout(child, collapsed);
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

  // Click-vs-drag threshold (~4px, spec §4.2): reads the *live* bound datum
  // at pointerup (never a captured snapshot), so a tile that has survived
  // several re-layouts always acts on its current data.
  function wireTileInteractions(el, handlers) {
    var startX = 0;
    var startY = 0;
    var moved = false;
    el.addEventListener("pointerdown", function (evt) {
      startX = evt.clientX;
      startY = evt.clientY;
      moved = false;
    });
    el.addEventListener("pointermove", function (evt) {
      if (Math.abs(evt.clientX - startX) > 4 || Math.abs(evt.clientY - startY) > 4) {
        moved = true;
      }
    });
    el.addEventListener("pointerup", function () {
      if (moved) {
        return;
      }
      var current = d3.select(el).datum();
      if (current.data.isFile) {
        handlers.onFileClick(current.data);
      } else {
        handlers.onDirClick(current.data);
      }
    });
  }

  function buildTileContent(wrapper, d) {
    if (d.data.isFile) {
      wrapper.append("span").attr("class", "viz-tile-label").text(function (d) { return d.data.name; });
      return;
    }
    if (d.data.collapsed) {
      var label = wrapper.append("span").attr("class", "viz-tile-label");
      label.append("span").attr("class", "viz-collapse-glyph");
      label.append("span").text(function (d) {
        return " " + d.data.name + " (" + d.value + ")";
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
  }

  function renderTiles(container, tree, collapsed, heatScale, handlers) {
    var rect = container.getBoundingClientRect();
    var width = rect.width || container.clientWidth || 960;
    var height = rect.height || container.clientHeight || 600;
    var pruned = pruneForLayout(tree, collapsed);
    var hierarchyRoot = layoutTreemap(pruned, width, height);
    var nodes = hierarchyRoot.descendants().filter(function (d) {
      return d.depth > 0;
    });

    var sel = d3
      .select(container)
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
      buildTileContent(wrapper, d);
    });

    entered.each(function () {
      wireTileInteractions(this, handlers);
    });

    applyEncoding(merged, heatScale);
  }

  window.vizViews.treemap = {
    render: function (container, scene, state) {
      var tree = buildTree(scene.files);
      var current = state;
      annotate(tree, current.computeHeat);

      var collapsed = Object.create(null);
      collectDefaultCollapsed(tree, collapsed);

      var heatScale = makeHeatColorScale();

      var handlers = {
        onDirClick: function (data) {
          if (collapsed[data.path]) {
            delete collapsed[data.path];
          } else {
            collapsed[data.path] = true;
          }
          fullRender();
        },
        onFileClick: function (data) {
          current.openDrill(data);
        }
      };

      function fullRender() {
        renderTiles(container, tree, collapsed, heatScale, handlers);
      }

      fullRender();

      var resizeHandler = function () {
        fullRender();
      };
      window.addEventListener("resize", resizeHandler);

      return {
        destroy: function () {
          window.removeEventListener("resize", resizeHandler);
          d3.select(container).selectAll("*").remove();
        },
        reencode: function (newState) {
          current = newState;
          annotate(tree, current.computeHeat);
          heatScale = makeHeatColorScale();
          var selection = d3.select(container).selectAll("div.viz-tile");
          selection.each(function (d) {
            d.data.heat = d.data.orig.heat;
          });
          applyEncoding(selection, heatScale);
        }
      };
    }
  };
})();
