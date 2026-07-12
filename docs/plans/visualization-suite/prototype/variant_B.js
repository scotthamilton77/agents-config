// PROTOTYPE — wipe me
(function () {
  function meterHtml(label, v) {
    const pct = Math.round((v || 0) * 100);
    return `<div class="meter"><span>${label}</span><div class="bar"><i style="width:${pct}%"></i></div><span>${(v || 0).toFixed(2)}</span></div>`;
  }

  function findContainingDir(filePath, dirNodeByPath) {
    const parts = filePath.split('/');
    for (let i = Math.min(parts.length - 1, 4); i >= 1; i--) {
      const candidate = parts.slice(0, i).join('/');
      if (dirNodeByPath.has(candidate)) return dirNodeByPath.get(candidate);
    }
    return dirNodeByPath.get('(root)') || null;
  }

  function topGroupKey(path) {
    return path.split('/')[0] || '(root)';
  }

  // Seed nodes on a circle, grouped by top-level directory, so the first
  // layout starts well-spread instead of scrunched at the center.
  function seedOnCircle(nodes, width, height) {
    const groups = new Map();
    nodes.forEach(n => {
      const key = n.kind === 'dir'
        ? topGroupKey(n.rec.path)
        : (n.dir ? topGroupKey(n.dir.rec.path) : '(root)');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    });
    const groupKeys = Array.from(groups.keys());
    const cx = width / 2, cy = height / 2;
    const outerR = Math.max(40, Math.min(width, height) * 0.38);
    groupKeys.forEach((key, gi) => {
      const groupNodes = groups.get(key);
      const baseAngle = (gi / groupKeys.length) * 2 * Math.PI;
      const arc = (2 * Math.PI / groupKeys.length) * 0.8;
      groupNodes.forEach((n, ni) => {
        const t = groupNodes.length > 1 ? (ni / (groupNodes.length - 1)) - 0.5 : 0;
        const angle = baseAngle + t * arc;
        // deterministic radius from node index (principle 12: reproducible layout)
        const r = outerR * (0.55 + 0.45 * ((ni * 0.6180339887) % 1));
        n.x = cx + r * Math.cos(angle);
        n.y = cy + r * Math.sin(angle);
      });
    });
  }

  // Module-level view state — survives rerenders (weight change, theme toggle,
  // drill open/close). Node positions are keyed by node id so an unchanged
  // node set never re-triggers a layout simulation.
  let zoomTransform = null; // current d3.zoomIdentity-shaped transform
  const pinnedById = new Map(); // node id -> {x, y}
  const nodePos = new Map(); // node id -> {x, y}, last known settled/dragged position
  let prevNodeSetKey = null;
  let zoomBehavior = null;

  function offsetTipEvent(evt) {
    // Push the tooltip well clear of the node's own local neighborhood.
    return { clientX: evt.clientX + 60, clientY: evt.clientY - 80 };
  }

  function legendRow(swatchHtml, label) {
    return `<div style="display:flex;align-items:center;gap:6px;line-height:1.4">` +
      `<span style="display:inline-flex;align-items:center;justify-content:center;width:22px;flex:0 0 22px">${swatchHtml}</span>` +
      `<span>${label}</span></div>`;
  }

  function buildLegendHtml() {
    const sizeSwatch = `<svg width="22" height="14"><circle cx="5" cy="7" r="2.5" fill="var(--muted)"/><circle cx="16" cy="7" r="5.5" fill="var(--muted)"/></svg>`;
    const colorSwatch = `<span style="display:block;width:20px;height:8px;border-radius:3px;background:linear-gradient(90deg, var(--heat-0), var(--heat-1), var(--heat-2), var(--heat-3), var(--heat-4))"></span>`;
    const edgeSwatch = `<svg width="22" height="14"><line x1="1" y1="11" x2="21" y2="11" stroke="var(--muted)" stroke-width="1"/><line x1="1" y1="5" x2="21" y2="5" stroke="var(--muted)" stroke-width="3"/></svg>`;
    const ringSwatch = `<svg width="22" height="14"><circle cx="11" cy="7" r="5" fill="var(--heat-2)" stroke="var(--pr-mark)" stroke-width="2"/></svg>`;
    const satSwatch = `<svg width="22" height="14"><circle cx="5" cy="7" r="4" fill="var(--muted)"/><line x1="9" y1="7" x2="17" y2="7" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2,2"/><circle cx="19" cy="7" r="2.5" fill="var(--heat-2)" stroke="var(--pr-mark)" stroke-width="1.5"/></svg>`;
    return [
      legendRow(sizeSwatch, 'Size = load-bearing (in-degree)'),
      legendRow(colorSwatch, 'Color = composite heat'),
      legendRow(edgeSwatch, 'Edge width = coupling strength'),
      legendRow(ringSwatch, 'Ringed dot = changed in PR'),
      legendRow(satSwatch, 'Satellites = PR’s changed files'),
    ].join('');
  }

  PROTO.registerVariant('B', {
    name: 'Dependency constellation',
    render(el, ctx) {
      const { DATA, computeHeat, heatColor, showTip, hideTip, showDrill, tipHtml, esc } = ctx;
      // Measure fresh every render — never cache dimensions in module state.
      const width = el.clientWidth || 800;
      const height = el.clientHeight || 600;

      const allDirs = DATA.dirs || [];
      let dirNodes = allDirs
        .filter(d => !((d.files || 0) < 2 && (d.changed || 0) === 0 && (d.centrality || 0) < 0.05))
        .map(d => ({
          id: 'dir:' + d.path,
          kind: 'dir',
          rec: d,
          r: 4 + 14 * Math.sqrt(d.centrality || 0),
        }));

      let dirNodeByPath = new Map(dirNodes.map(n => [n.rec.path, n]));

      let dirEdgeLinks = (DATA.dir_edges || [])
        .filter(e => dirNodeByPath.has(e.source) && dirNodeByPath.has(e.target))
        .map(e => ({
          source: dirNodeByPath.get(e.source).id,
          target: dirNodeByPath.get(e.target).id,
          n: e.n || 1,
        }));

      const changedFiles = (DATA.files || []).filter(f => f.changed);
      const satelliteNodes = changedFiles.map(f => ({
        id: 'file:' + f.path,
        kind: 'file',
        rec: f,
        r: 5,
        dir: findContainingDir(f.path, dirNodeByPath),
      }));

      // Noise reduction: drop dir nodes with no dir_edges touching them and no
      // changed files tethered inside them — they're just floaters.
      const connectedDirIds = new Set();
      dirEdgeLinks.forEach(e => { connectedDirIds.add(e.source); connectedDirIds.add(e.target); });
      satelliteNodes.forEach(s => { if (s.dir) connectedDirIds.add(s.dir.id); });

      const droppedCount = dirNodes.filter(n => !connectedDirIds.has(n.id)).length;
      dirNodes = dirNodes.filter(n => connectedDirIds.has(n.id));
      dirNodeByPath = new Map(dirNodes.map(n => [n.rec.path, n]));
      const survivingIds = new Set(dirNodes.map(n => n.id));
      dirEdgeLinks = (DATA.dir_edges || [])
        .filter(e => dirNodeByPath.has(e.source) && dirNodeByPath.has(e.target))
        .map(e => ({
          source: dirNodeByPath.get(e.source).id,
          target: dirNodeByPath.get(e.target).id,
          n: e.n || 1,
        }))
        .filter(e => survivingIds.has(e.source) && survivingIds.has(e.target));

      const tetherLinks = satelliteNodes
        .filter(s => s.dir && survivingIds.has(s.dir.id))
        .map(s => ({ source: s.id, target: s.dir.id, tether: true }));

      const nodes = [...dirNodes, ...satelliteNodes];
      const links = [...dirEdgeLinks, ...tetherLinks];

      // Decide whether the surviving node set actually changed since the last
      // render. If not, skip the simulation entirely and reuse stored positions.
      const nodeSetKey = nodes.map(n => n.id).sort().join('|');
      const needsLayout = nodeSetKey !== prevNodeSetKey;

      if (needsLayout) {
        seedOnCircle(nodes, width, height);
      } else {
        nodes.forEach(n => {
          const stored = nodePos.get(n.id);
          if (stored) { n.x = stored.x; n.y = stored.y; }
        });
      }

      // Re-apply pinned positions from prior interaction (keyed by node id).
      nodes.forEach(n => {
        const pinned = pinnedById.get(n.id);
        if (pinned) {
          n.x = pinned.x; n.y = pinned.y;
          n.fx = pinned.x; n.fy = pinned.y;
        }
      });

      // Light theme's --line (#cbd5e1) reads too faint for edges at low zoom;
      // darken the stroke on light, keep --line as-is on dark.
      const isLight = document.documentElement.getAttribute('data-theme') !== 'dark';
      const linkStroke = isLight ? '#94a3b8' : 'var(--line)';

      // All inline styling lives on our own inner container, never on el —
      // the shell strips el's inline styles before every render.
      const container = d3.select(el).append('div')
        .style('position', 'relative')
        .style('width', '100%')
        .style('height', '100%');

      const svg = container.append('svg')
        .attr('width', width).attr('height', height)
        .attr('viewBox', `0 0 ${width} ${height}`)
        .style('cursor', 'grab');

      const root = svg.append('g').attr('class', 'zoom-root');

      const linkSel = root.append('g').attr('class', 'links')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', linkStroke)
        .attr('stroke-width', d => d.tether ? 1 : 1 + Math.log1p(d.n))
        .attr('stroke-dasharray', d => d.tether ? '3,3' : null)
        .attr('opacity', d => d.tether ? 0.75 : 0.65);

      const nodeSel = root.append('g').attr('class', 'nodes')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => d.r)
        .attr('fill', d => heatColor(computeHeat(d.rec)))
        .attr('stroke', d => d.kind === 'file' ? 'var(--pr-mark)' : 'var(--panel-2)')
        .attr('stroke-width', d => d.kind === 'file' ? 2 : 1)
        .style('cursor', 'pointer')
        .on('mousemove', (evt, d) => {
          if (d.kind === 'file') {
            showTip(offsetTipEvent(evt), tipHtml(d.rec));
          } else {
            const dir = d.rec;
            showTip(offsetTipEvent(evt), `<div class="path">${esc(dir.path)}</div>` +
              `<div style="margin-top:4px;color:var(--muted)">${dir.files || 0} files · ${dir.changed || 0} changed</div>` +
              meterHtml('complexity', dir.complexity) +
              meterHtml('load-bearing', dir.centrality) +
              meterHtml('consequence', dir.consequence));
          }
        })
        .on('mouseleave', () => hideTip())
        .on('click', (evt, d) => {
          if (d.kind === 'dir') focusOnNode(d);
          if (d.kind === 'file') {
            showDrill(d.rec);
          } else {
            const dir = d.rec;
            showDrill({ path: dir.path, centrality: dir.centrality, consequence: dir.consequence, complexity: dir.complexity, changed: false });
          }
        })
        .on('dblclick', (evt, d) => {
          evt.stopPropagation();
          if (pinnedById.has(d.id)) {
            pinnedById.delete(d.id);
            d.fx = null; d.fy = null;
            // Minimal reheat — just enough to let this one node drift free,
            // not a full replot of the graph.
            if (!sim.alpha() || sim.alpha() < 0.05) sim.alpha(0.1).restart();
          }
        });

      const topDirNodes = dirNodes.slice()
        .sort((a, b) =>
          ((b.rec.centrality || 0) + ((b.rec.changed || 0) > 0 ? 1 : 0)) -
          ((a.rec.centrality || 0) + ((a.rec.changed || 0) > 0 ? 1 : 0)))
        .slice(0, 20);
      const labelNodes = [...topDirNodes, ...satelliteNodes];

      const labelSel = root.append('g').attr('class', 'labels')
        .selectAll('text')
        .data(labelNodes)
        .join('text')
        .text(d => (d.rec.path.split('/').pop() || d.rec.path))
        .attr('font-size', d => d.kind === 'file' ? 8 : 9)
        .attr('fill', 'var(--muted)')
        .style('pointer-events', 'none')
        .attr('text-anchor', 'middle');

      function ticked() {
        linkSel
          .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        nodeSel.attr('cx', d => d.x).attr('cy', d => d.y);
        labelSel.attr('x', d => d.x).attr('y', d => d.y - d.r - 4);
        nodes.forEach(n => nodePos.set(n.id, { x: n.x, y: n.y }));
      }

      const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id)
          .distance(d => d.tether ? 18 : 60)
          .strength(d => d.tether ? 0.8 : 0.25))
        .force('charge', d3.forceManyBody().strength(d => d.kind === 'file' ? -30 : -120))
        .force('collide', d3.forceCollide().radius(d => d.r + 3))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .alphaDecay(0.05)
        .on('tick', ticked);

      if (needsLayout) {
        // Settle synchronously before first paint so the graph never shows a
        // scrunched, still-relaxing frame.
        sim.stop();
        for (let i = 0; i < 300; i++) sim.tick();
        prevNodeSetKey = nodeSetKey;
      }
      // Stop the timer either way — dragging is the only thing allowed to
      // reheat it from here on.
      sim.stop();
      ticked();

      nodeSel.call(d3.drag()
        .on('start', (evt, d) => {
          // Low alphaTarget: enough for the dragged node's own links/collisions
          // to respond, not enough to visibly re-plot the whole graph while
          // the mouse is merely held down.
          if (!evt.active) sim.alphaTarget(0.05).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (evt, d) => { d.fx = evt.x; d.fy = evt.y; })
        .on('end', (evt, d) => {
          if (!evt.active) { sim.alphaTarget(0); sim.stop(); }
          // Pin permanently where dropped instead of springing back.
          d.fx = evt.x; d.fy = evt.y;
          pinnedById.set(d.id, { x: evt.x, y: evt.y });
          nodePos.set(d.id, { x: evt.x, y: evt.y });
        }));

      // Zoom + pan, applied to the root <g>, state kept in module scope.
      zoomBehavior = d3.zoom()
        .scaleExtent([0.3, 6])
        .on('zoom', (evt) => {
          zoomTransform = evt.transform;
          root.attr('transform', zoomTransform);
        });

      svg.call(zoomBehavior);
      if (zoomTransform) {
        svg.call(zoomBehavior.transform, zoomTransform);
      } else {
        zoomTransform = d3.zoomIdentity;
      }

      function focusOnNode(d) {
        const scale = Math.max(zoomTransform ? zoomTransform.k : 1, 1.5);
        const t = d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-d.x, -d.y);
        svg.transition().duration(500).call(zoomBehavior.transform, t);
      }

      // Reset-view control, overlaid top-right of the stage.
      container.append('button')
        .text('Reset view')
        .style('position', 'absolute')
        .style('top', '8px')
        .style('right', '8px')
        .style('z-index', '5')
        .style('font-size', '11px')
        .style('padding', '4px 8px')
        .style('background', 'var(--panel-2)')
        .style('border', '1px solid var(--line)')
        .style('color', 'var(--text)')
        .style('border-radius', '6px')
        .style('cursor', 'pointer')
        .on('click', () => {
          zoomTransform = d3.zoomIdentity;
          svg.transition().duration(400).call(zoomBehavior.transform, zoomTransform);
        });

      if (droppedCount > 0) {
        container.append('div')
          .text(`${droppedCount} unconnected directories hidden`)
          .style('position', 'absolute')
          .style('bottom', '8px')
          .style('left', '8px')
          .style('z-index', '5')
          .style('font-size', '11px')
          .style('color', 'var(--muted)');
      }

      // Always-visible legend key, bottom-left, above the proto badge line.
      container.append('div')
        .style('position', 'absolute')
        .style('bottom', '34px')
        .style('left', '8px')
        .style('z-index', '5')
        .style('font-size', '10.5px')
        .style('color', 'var(--muted)')
        .style('background', 'var(--panel)')
        .style('border', '1px solid var(--line)')
        .style('border-radius', '6px')
        .style('padding', '6px 8px')
        .style('display', 'flex')
        .style('flex-direction', 'column')
        .style('gap', '3px')
        .html(buildLegendHtml());
    },
  });
})();
