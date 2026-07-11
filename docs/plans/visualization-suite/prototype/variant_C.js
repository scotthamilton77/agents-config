// PROTOTYPE — wipe me
(function () {
  const REVIEW_BUDGET_MINUTES = 30;
  let mixMode = false; // false = Separated, true = Mixed — persists across rerenders

  function luminance(color) {
    let r, g, b;
    const hexM = /^#?([0-9a-f]{6})$/i.exec(color || '');
    const rgbM = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(color || '');
    if (hexM) {
      const n = parseInt(hexM[1], 16);
      r = (n >> 16) & 255; g = (n >> 8) & 255; b = n & 255;
    } else if (rgbM) {
      r = +rgbM[1]; g = +rgbM[2]; b = +rgbM[3];
    } else {
      return 0.5;
    }
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  }

  function meterRow(label, v) {
    const pct = Math.round((v || 0) * 100);
    return `<div class="meter"><span>${label}</span><div class="bar"><i style="width:${pct}%"></i></div><span>${(v || 0).toFixed(2)}</span></div>`;
  }

  function allocateMinutes(changed, computeHeat) {
    // Empty/placeholder dataset: no files to budget. Return early so the
    // even-split path never divides by changed.length (Infinity) below.
    if (changed.length === 0) return [];
    const heats = changed.map(f => Math.max(computeHeat(f), 0));
    const sum = heats.reduce((a, b) => a + b, 0);
    if (sum <= 0) {
      // No signal at all — split the budget evenly.
      const even = Math.max(1, Math.floor(REVIEW_BUDGET_MINUTES / changed.length));
      return changed.map(() => even);
    }
    return heats.map(h => Math.max(1, Math.round((h / sum) * REVIEW_BUDGET_MINUTES)));
  }

  function fileName(path) {
    const parts = path.split('/');
    return parts[parts.length - 1];
  }

  // Truncate from the middle so a distinguishing prefix (e.g. "test_") never
  // silently disappears the way trailing/centered truncation can.
  function truncMiddle(str, max) {
    if (str.length <= max) return str;
    const keep = Math.max(2, max - 1);
    const front = Math.ceil(keep / 2);
    const back = Math.floor(keep / 2);
    return str.slice(0, front) + '…' + str.slice(str.length - back);
  }

  function buildRow(f, opts, ctx) {
    const { rank, muted, showAddsDels, contextChip } = opts;
    const { computeHeat, heatColor, showTip, hideTip, showDrill } = ctx;
    const h = computeHeat(f);

    const row = document.createElement('div');
    row.style.cssText = `display:flex;gap:12px;align-items:center;padding:9px 18px;border-bottom:1px solid var(--line);cursor:pointer;${muted ? 'opacity:.62;' : ''}`;
    row.addEventListener('mousemove', evt => showTip(evt, ctx.tipHtml(f)));
    row.addEventListener('mouseleave', hideTip);
    row.addEventListener('click', () => showDrill(f));
    row.addEventListener('mouseenter', () => { row.style.background = 'var(--panel-2)'; });
    row.addEventListener('mouseleave', () => { row.style.background = ''; });

    const rankEl = document.createElement('div');
    rankEl.style.cssText = 'width:22px;flex:0 0 22px;text-align:right;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums;';
    rankEl.textContent = rank != null ? String(rank) : '·';
    row.appendChild(rankEl);

    const nameCol = document.createElement('div');
    nameCol.style.cssText = 'width:230px;flex:0 0 230px;min-width:0;';
    const nameEl = document.createElement('div');
    nameEl.style.cssText = 'font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    nameEl.textContent = fileName(f.path);
    const pathEl = document.createElement('div');
    pathEl.style.cssText = 'font-size:10.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    pathEl.textContent = f.path;
    nameCol.appendChild(nameEl);
    nameCol.appendChild(pathEl);
    row.appendChild(nameCol);

    const heatCol = document.createElement('div');
    heatCol.style.cssText = 'flex:1 1 auto;min-width:80px;';
    const heatBar = document.createElement('div');
    heatBar.style.cssText = 'height:10px;border-radius:5px;background:var(--line);overflow:hidden;';
    const heatFill = document.createElement('div');
    heatFill.style.cssText = `height:100%;width:${Math.round(h * 100)}%;background:${heatColor(h)};`;
    heatBar.appendChild(heatFill);
    heatCol.appendChild(heatBar);
    row.appendChild(heatCol);

    const heatVal = document.createElement('div');
    heatVal.style.cssText = 'width:32px;flex:0 0 32px;text-align:right;font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;';
    heatVal.textContent = h.toFixed(2);
    row.appendChild(heatVal);

    const metersCol = document.createElement('div');
    metersCol.style.cssText = 'width:210px;flex:0 0 210px;';
    metersCol.innerHTML =
      meterRow('complexity', f.complexity) +
      meterRow('load-bearing', f.centrality) +
      meterRow('consequence', f.consequence);
    row.appendChild(metersCol);

    const chipsCol = document.createElement('div');
    chipsCol.style.cssText = 'width:170px;flex:0 0 170px;text-align:right;';
    if (showAddsDels && f.changed) {
      const addsDels = document.createElement('span');
      addsDels.style.cssText = 'display:inline-block;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:11px;color:var(--pr-mark);margin-right:4px;';
      addsDels.textContent = `+${f.adds || 0}/−${f.dels || 0}`;
      chipsCol.appendChild(addsDels);
      if (f.status) {
        const statusChip = document.createElement('span');
        statusChip.style.cssText = 'display:inline-block;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:11px;color:var(--muted);margin-right:4px;';
        statusChip.textContent = f.status;
        chipsCol.appendChild(statusChip);
      }
      if (f.diff_url) {
        const diffLink = document.createElement('a');
        diffLink.href = f.diff_url;
        diffLink.target = '_blank';
        diffLink.rel = 'noopener noreferrer';
        diffLink.textContent = 'diff ↗';
        diffLink.style.cssText = 'display:inline-block;font-size:11px;color:var(--accent);text-decoration:none;';
        diffLink.addEventListener('click', evt => evt.stopPropagation());
        chipsCol.appendChild(diffLink);
      }
    }
    if (contextChip) {
      const ctxChip = document.createElement('span');
      ctxChip.style.cssText = 'display:inline-block;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:10.5px;color:var(--muted);letter-spacing:.03em;';
      ctxChip.textContent = 'context';
      chipsCol.appendChild(ctxChip);
    }
    row.appendChild(chipsCol);

    return row;
  }

  function renderLedger(el, ctx) {
      const { DATA, computeHeat, heatColor, showTip, hideTip, showDrill } = ctx;

      // Never style the shared #stage element — it leaks into other variants
      // on switch. All layout/scroll styling lives on this inner container.
      const stageEl = el;
      const wrap = document.createElement('div');
      wrap.style.cssText = 'overflow-y:auto;height:100%;background:var(--bg);padding-top:30px;';
      stageEl.appendChild(wrap);
      el = wrap;
      // Layout below is flex/percentage based (no cached px dimensions), so
      // drawer open/close and variant switches resize correctly for free.

      const changed = DATA.files.filter(f => f.changed);
      const changedSorted = changed.slice().sort((a, b) => computeHeat(b) - computeHeat(a));
      const minutesArr = allocateMinutes(changedSorted, computeHeat);
      const minutesByPath = new Map(changedSorted.map((f, i) => [f.path, minutesArr[i]]));

      // --- Mix toggle ---
      const toggleBar = document.createElement('div');
      toggleBar.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:10px 18px 0;';

      const toggleLabel = document.createElement('span');
      toggleLabel.style.cssText = 'font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;';
      toggleLabel.textContent = 'Ranking';
      toggleBar.appendChild(toggleLabel);

      function mkToggleBtn(text, mixed) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = text;
        const active = mixMode === mixed;
        btn.style.cssText = `font-size:11px;padding:4px 10px;border-radius:5px;cursor:pointer;border:1px solid var(--line);background:${active ? 'var(--accent)' : 'var(--panel-2)'};color:${active ? '#fff' : 'var(--text)'};`;
        btn.addEventListener('click', () => {
          if (mixMode !== mixed) {
            mixMode = mixed;
            stageEl.innerHTML = '';
            renderLedger(stageEl, ctx);
          }
        });
        return btn;
      }
      toggleBar.appendChild(mkToggleBtn('Separated', false));
      toggleBar.appendChild(mkToggleBtn('Mixed', true));
      el.appendChild(toggleBar);

      // --- Budget strip ---
      const strip = document.createElement('div');
      strip.style.cssText = 'padding:14px 18px 10px;border-bottom:1px solid var(--line);';

      const title = document.createElement('div');
      title.style.cssText = 'font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:8px;';
      title.textContent = `Review budget — ${REVIEW_BUDGET_MINUTES} minutes, allocated by heat`;
      strip.appendChild(title);

      const bar = document.createElement('div');
      bar.style.cssText = 'display:flex;width:100%;height:34px;border-radius:6px;overflow:hidden;border:1px solid var(--line);';

      const totalMinutes = minutesArr.reduce((a, b) => a + b, 0) || 1;

      changedSorted.forEach((f, i) => {
        const mins = minutesArr[i];
        const h = computeHeat(f);
        const segColor = heatColor(h);
        const segLight = luminance(segColor) > 0.55;
        const pct = mins / totalMinutes;
        const wide = pct > 0.06;
        const seg = document.createElement('div');
        // Full name + minutes always available via native tooltip, even when
        // the segment is too narrow (or too small a % of the budget) to
        // print a label without lying about the filename.
        seg.title = `${f.path} · ${mins}m`;
        seg.style.cssText = `flex:${mins} 0 0%;background:${segColor};min-width:2px;display:flex;align-items:center;justify-content:${wide ? 'flex-start' : 'center'};overflow:hidden;cursor:pointer;border-right:1px solid rgba(0,0,0,.35);`;
        const label = document.createElement('span');
        label.style.cssText = `font-size:10px;color:${segLight ? '#0f172a' : '#f8fafc'};font-weight:700;padding:0 5px;white-space:nowrap;`;
        if (wide) {
          // Rough chars-per-segment budget from its % share of the bar —
          // this is a heuristic (no measured px width), but middle-truncating
          // whatever budget we land on beats silently dropping a prefix.
          const nameBudget = Math.max(6, Math.round(pct * 100 * 1.3));
          label.textContent = `${truncMiddle(fileName(f.path), nameBudget)} · ${mins}m`;
        } else {
          label.textContent = `${mins}m`;
        }
        seg.appendChild(label);
        seg.addEventListener('mousemove', evt => showTip(evt, ctx.tipHtml(f)));
        seg.addEventListener('mouseleave', hideTip);
        seg.addEventListener('click', () => showDrill(f));
        bar.appendChild(seg);
      });
      strip.appendChild(bar);
      el.appendChild(strip);

      const unchanged = DATA.files.filter(f => !f.changed);
      const unchangedSorted = unchanged.slice().sort((a, b) => computeHeat(b) - computeHeat(a)).slice(0, 8);

      if (mixMode) {
        // --- Mixed: single ranking, changed + context, sorted purely by heat ---
        const combined = changedSorted.concat(unchangedSorted)
          .slice()
          .sort((a, b) => computeHeat(b) - computeHeat(a));

        const mixedHeader = document.createElement('div');
        mixedHeader.style.cssText = 'padding:12px 18px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);';
        mixedHeader.textContent = `Mixed ranking — ${changedSorted.length} changed + ${unchangedSorted.length} context, by heat`;
        el.appendChild(mixedHeader);

        combined.forEach((f, i) => {
          el.appendChild(buildRow(f, {
            rank: i + 1,
            muted: !f.changed,
            showAddsDels: !!f.changed,
            contextChip: !f.changed
          }, ctx));
        });
      } else {
        // --- Separated: This PR section, divider, Context section ---
        const changedHeader = document.createElement('div');
        changedHeader.style.cssText = 'padding:12px 18px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);';
        changedHeader.textContent = `This PR — ${changedSorted.length} changed files, ranked by heat`;
        el.appendChild(changedHeader);

        changedSorted.forEach((f, i) => {
          el.appendChild(buildRow(f, { rank: i + 1, muted: false, showAddsDels: true }, ctx));
        });

        // --- Divider ---
        const divider = document.createElement('div');
        divider.style.cssText = 'height:1px;background:var(--line);margin:18px 0 0;';
        el.appendChild(divider);

        // --- Context: hottest unchanged code ---
        const ctxHeader = document.createElement('div');
        ctxHeader.style.cssText = 'padding:12px 18px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);';
        ctxHeader.textContent = 'Context — hottest unchanged code';
        el.appendChild(ctxHeader);

        unchangedSorted.forEach((f, i) => {
          el.appendChild(buildRow(f, { rank: i + 1, muted: true, showAddsDels: false }, ctx));
        });
      }

      const spacer = document.createElement('div');
      spacer.style.height = '16px';
      el.appendChild(spacer);
  }

  PROTO.registerVariant('C', {
    name: 'Attention ledger',
    render: renderLedger
  });
})();
