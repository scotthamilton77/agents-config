// PROTOTYPE — wipe me
(function () {
  // Module-level view state — survives rerenders (host clears `el` and calls
  // render() again on every weight/theme/variant change).
  const collapsed = new Set(); // full dir paths ("packages" or "packages/prgroom") currently collapsed
  let defaultsApplied = false; // has the "collapse groups with zero changed files" default run?
  let zoomStack = []; // path segments of the currently zoomed container; [] = whole estate
  const COLLAPSE_FRACTION = 0.025; // clamp for a collapsed group's share of the estate total

  function middleEllipsis(name, maxChars) {
    if (maxChars < 3) maxChars = 3;
    if (name.length <= maxChars) return name;
    const keep = maxChars - 1; // reserve 1 char for the ellipsis
    const head = Math.ceil(keep / 2);
    const tail = Math.floor(keep / 2);
    return name.slice(0, head) + '…' + name.slice(name.length - tail);
  }

  function endEllipsis(name, maxChars) {
    return name.length > maxChars ? name.slice(0, Math.max(0, maxChars - 1)) + '…' : name;
  }

  // Pick readable label text over a given (already-resolved) fill color.
  function labelColor(fillColor) {
    const l = d3.lab(fillColor).l; // 0 (dark) .. 100 (light)
    return l > 55 ? '#0f172a' : '#f8fafc';
  }

  function renderA(el, ctx) {
      const { DATA, computeHeat, heatColor, showTip, hideTip, showDrill } = ctx;
      const rerender = () => { el.innerHTML = ''; renderA(el, ctx); };

      const width = el.clientWidth || 800;
      const height = el.clientHeight || 600;

      // Build a nested hierarchy from file paths: dir/dir/file.ext
      const root = { name: '(estate)', children: new Map() };
      function insert(f) {
        const parts = f.path.split('/');
        let node = root;
        for (let i = 0; i < parts.length - 1; i++) {
          const seg = parts[i];
          if (!node.children.has(seg)) {
            node.children.set(seg, { name: seg, children: new Map() });
          }
          node = node.children.get(seg);
        }
        const fname = parts[parts.length - 1];
        node.children.set(fname + ' ' + f.path, { name: fname, file: f });
      }
      for (const f of DATA.files) insert(f);

      // Aggregate stats for a Map-tree node: file count, changed count, worst heat, total bytes.
      function groupStats(node) {
        const stats = { count: 0, changedCount: 0, worstHeat: 0, totalBytes: 0 };
        (function walk(n) {
          if (n.file) {
            stats.count++;
            if (n.file.changed) stats.changedCount++;
            stats.worstHeat = Math.max(stats.worstHeat, computeHeat(n.file));
            stats.totalBytes += Math.max(n.file.bytes || 1, 1);
            return;
          }
          for (const c of n.children.values()) walk(c);
        })(node);
        return stats;
      }

      // Apply the one-time default: top-level groups with zero changed files start
      // collapsed; groups with changed files start expanded. Only runs once so
      // manual toggles afterward are never clobbered by a rerender.
      if (!defaultsApplied) {
        for (const [name, node] of root.children) {
          const stats = groupStats(node);
          if (stats.changedCount === 0) collapsed.add(name);
        }
        defaultsApplied = true;
      }

      // Estate-wide byte total (always from the true root, regardless of zoom)
      // — a collapsed group's rect is clamped to a small slice of this, so
      // expanded siblings visibly absorb the space it gives up.
      const estateTotalBytes = groupStats(root).totalBytes;

      // Convert Map-based tree into plain objects d3.hierarchy can consume.
      // Collapse/zoom state is keyed by full path from the true estate root
      // (e.g. "packages/prgroom"), not bare name, so same-named dirs under
      // different parents never collide. `localDepth` resets to 0 at whatever
      // node is currently the layout root (whole estate or a zoomed subtree) —
      // depth 1 and depth 2 relative to *that* view get header affordances.
      function toPlain(node, localDepth, pathParts) {
        if (node.file) {
          return { name: node.name, file: node.file, value: Math.max(node.file.bytes || 1, 1) };
        }
        const fullPath = pathParts.join('/');
        if ((localDepth === 1 || localDepth === 2) && collapsed.has(fullPath)) {
          const stats = groupStats(node);
          return {
            name: node.name,
            value: Math.max(estateTotalBytes * COLLAPSE_FRACTION, 1),
            collapsedGroup: true,
            groupStats: stats,
            fullPath,
          };
        }
        const children = Array.from(node.children.values())
          .map(c => toPlain(c, localDepth + 1, pathParts.concat(c.name)));
        return { name: node.name, children, fullPath };
      }

      // Resolve which subtree we're laying out: the whole estate, or (if
      // zoomed) the Map-node reached by walking zoomStack, re-rooted. An
      // invalid stack (stale path after data/weight changes) resets to whole estate.
      let layoutSourceNode = root;
      for (const seg of zoomStack) {
        if (layoutSourceNode.children && layoutSourceNode.children.has(seg)) {
          layoutSourceNode = layoutSourceNode.children.get(seg);
        } else {
          zoomStack = [];
          layoutSourceNode = root;
          break;
        }
      }

      const plainRoot = toPlain(layoutSourceNode, 0, zoomStack.slice());

      const hierarchy = d3.hierarchy(plainRoot)
        .sum(d => d.value || 0)
        .sort((a, b) => (b.value || 0) - (a.value || 0));

      const treemapLayout = d3.treemap()
        .size([width, height])
        .paddingOuter(2)
        .paddingTop(d => (d.depth === 1 ? 16 : d.depth === 2 ? 13 : 1))
        .paddingInner(1)
        .round(true);

      treemapLayout(hierarchy);

      const svg = d3.select(el).append('svg')
        .attr('width', width)
        .attr('height', height)
        .style('display', 'block')
        .style('background', 'var(--bg)');

      const allNodes = hierarchy.descendants();
      const leaves = allNodes.filter(d => d.data.file);
      const collapsedNodes = allNodes.filter(d => d.data.collapsedGroup);
      const dirNodes = allNodes.filter(d => !d.data.file && !d.data.collapsedGroup && d.depth >= 1 && d.depth <= 2);

      // Directory background rects (chrome, not heat-colored) for depth 1-2 groupings.
      const dirbg = svg.append('g').selectAll('rect.dirbg')
        .data(dirNodes)
        .join('rect')
        .attr('class', 'dirbg')
        .attr('x', d => d.x0)
        .attr('y', d => d.y0)
        .attr('width', d => Math.max(0, d.x1 - d.x0))
        .attr('height', d => Math.max(0, d.y1 - d.y0))
        .attr('fill', 'var(--panel-2)')
        .attr('stroke', 'var(--line)')
        .attr('stroke-width', d => (d.depth === 1 ? 1.5 : 1))
        .attr('opacity', d => (d.depth === 1 ? 1 : 0.6))
        .attr('pointer-events', d => (d.depth === 1 || d.depth === 2 ? 'auto' : 'none'))
        .style('cursor', d => (d.depth === 1 || d.depth === 2 ? 'pointer' : 'default'));

      // Depth-1 and depth-2 headers both get collapse/zoom affordances, in the
      // whole-estate view and inside a zoomed view alike. Single-click collapse
      // is delayed so a dblclick (zoom) can cancel it — otherwise the first
      // click's rerender destroys the node before dblclick fires.
      {
        let clickTimer = null;
        dirbg.filter(d => d.depth === 1 || d.depth === 2)
          .on('click', (evt, d) => {
            clearTimeout(clickTimer);
            clickTimer = setTimeout(() => {
              const key = d.data.fullPath;
              if (collapsed.has(key)) collapsed.delete(key);
              else collapsed.add(key);
              rerender();
            }, 280);
          })
          .on('dblclick', (evt, d) => {
            clearTimeout(clickTimer);
            zoomStack = d.data.fullPath.split('/');
            rerender();
          });
      }

      // Collapsed top-level groups: one solid block, rolled-up worst-offender heat.
      const collapsedG = svg.append('g').selectAll('g.collapsedGroup')
        .data(collapsedNodes)
        .join('g')
        .attr('class', 'collapsedGroup')
        .attr('transform', d => `translate(${d.x0},${d.y0})`)
        .style('cursor', 'pointer')
        .on('click', (evt, d) => {
          collapsed.delete(d.data.fullPath);
          rerender();
        })
        .on('mousemove', (evt, d) => {
          const s = d.data.groupStats;
          showTip(evt, `<div class="path">${d.data.name}/</div>` +
            `<div style="margin-top:4px">${s.count} files, worst heat ${s.worstHeat.toFixed(2)}</div>` +
            (s.changedCount ? `<div style="margin-top:2px;color:var(--pr-mark)">${s.changedCount} changed</div>`
                             : `<div style="margin-top:2px;color:var(--muted)">no changes in this PR</div>`));
        })
        .on('mouseleave', hideTip);

      collapsedG.append('rect')
        .attr('width', d => Math.max(0, d.x1 - d.x0))
        .attr('height', d => Math.max(0, d.y1 - d.y0))
        .attr('fill', d => heatColor(d.data.groupStats.worstHeat))
        .attr('opacity', d => (d.data.groupStats.changedCount ? 0.95 : 0.8))
        .attr('stroke', d => (d.data.groupStats.changedCount ? 'var(--pr-mark)' : 'var(--line)'))
        .attr('stroke-width', d => (d.data.groupStats.changedCount ? 2 : 1));

      collapsedG.append('text')
        .attr('x', 6)
        .attr('y', 17)
        .attr('fill', d => labelColor(heatColor(d.data.groupStats.worstHeat)))
        .attr('font-size', 11)
        .attr('font-weight', 600)
        .attr('pointer-events', 'none')
        .text(d => {
          const w = d.x1 - d.x0;
          if (w < 30) return '';
          const maxChars = Math.floor(w / 6.2);
          return endEllipsis(d.data.name, maxChars);
        });

      collapsedG.append('text')
        .attr('x', 6)
        .attr('y', 31)
        .attr('fill', d => labelColor(heatColor(d.data.groupStats.worstHeat)))
        .attr('font-size', 10)
        .attr('pointer-events', 'none')
        .text(d => {
          const w = d.x1 - d.x0, h = d.y1 - d.y0;
          if (w < 60 || h < 30) return '';
          const s = d.data.groupStats;
          return s.changedCount ? `${s.count} files (${s.changedCount} changed)` : `${s.count} files`;
        });

      // File leaf cells, heat-colored.
      const leafG = svg.append('g').selectAll('g.leaf')
        .data(leaves)
        .join('g')
        .attr('class', 'leaf')
        .attr('transform', d => `translate(${d.x0},${d.y0})`);

      leafG.append('rect')
        .attr('width', d => Math.max(0, d.x1 - d.x0))
        .attr('height', d => Math.max(0, d.y1 - d.y0))
        .attr('fill', d => heatColor(computeHeat(d.data.file)))
        .attr('opacity', d => (d.data.file.changed ? 1 : 0.85))
        .attr('stroke', d => (d.data.file.changed ? 'var(--pr-mark)' : 'var(--line)'))
        .attr('stroke-width', d => (d.data.file.changed ? 2 : 0.5))
        .style('cursor', 'pointer')
        .on('mousemove', (evt, d) => showTip(evt, ctx.tipHtml(d.data.file)))
        .on('mouseleave', hideTip)
        .on('click', (evt, d) => showDrill(d.data.file));

      // File name labels — aggressively truncated (middle-ellipsis) and shown
      // at a lower minimum-area threshold, one font-size notch smaller.
      leafG.append('text')
        .attr('x', 3)
        .attr('y', 11)
        .attr('fill', d => labelColor(heatColor(computeHeat(d.data.file))))
        .attr('font-size', 9)
        .attr('pointer-events', 'none')
        .text(d => {
          const w = d.x1 - d.x0, h = d.y1 - d.y0;
          if (w < 20 || h < 10) return '';
          const name = d.data.name;
          const maxChars = Math.floor(w / 5);
          return middleEllipsis(name, maxChars);
        });

      // Directory labels (depth 1 and 2, where space allows).
      svg.append('g').selectAll('text.dirlabel')
        .data(dirNodes)
        .join('text')
        .attr('class', 'dirlabel')
        .attr('x', d => d.x0 + 3)
        .attr('y', d => d.y0 + (d.depth === 1 ? 11 : 9))
        .attr('fill', 'var(--muted)')
        .attr('font-size', d => (d.depth === 1 ? 10 : 9))
        .attr('font-weight', d => (d.depth === 1 ? 600 : 400))
        .attr('pointer-events', 'none')
        .text(d => {
          const w = d.x1 - d.x0;
          if (w < 26) return '';
          const name = d.data.name;
          const maxChars = Math.floor(w / (d.depth === 1 ? 6 : 5.2));
          return endEllipsis(name, maxChars);
        });

      // Overlay chrome (hint caption / breadcrumb) — plain HTML on top of the SVG.
      const overlay = d3.select(el).append('div')
        .style('position', 'absolute')
        .style('bottom', '8px')
        .style('right', '8px')
        .style('pointer-events', 'none')
        .style('display', 'flex')
        .style('justify-content', 'flex-end')
        .style('font-size', '11px')
        .style('color', 'var(--muted)')
        .style('background', 'var(--panel)')
        .style('border-radius', '6px')
        .style('padding', '2px 8px')
        .style('opacity', '0.92');

      if (zoomStack.length) {
        const crumb = overlay.append('div')
          .style('pointer-events', 'auto')
          .style('display', 'flex')
          .style('background', 'var(--panel)')
          .style('border', '1px solid var(--line)')
          .style('border-radius', '6px')
          .style('padding', '2px 8px');

        crumb.append('span')
          .style('cursor', 'pointer')
          .text('◂ whole estate')
          .on('click', () => { zoomStack = []; rerender(); });

        zoomStack.forEach((seg, i) => {
          crumb.append('span').text(' / ');
          crumb.append('span')
            .style('cursor', 'pointer')
            .text(seg)
            .on('click', () => { zoomStack = zoomStack.slice(0, i + 1); rerender(); });
        });
      } else {
        overlay.append('div')
          .text('click a group header to collapse/expand · double-click to zoom');
      }
  }

  PROTO.registerVariant('A', {
    name: 'Estate treemap',
    render: renderA,
  });
})();
