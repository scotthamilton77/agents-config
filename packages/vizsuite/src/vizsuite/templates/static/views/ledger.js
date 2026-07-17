// vizsuite/views/ledger.js — the attention-ledger view module (spec §6.1),
// obeying the §4.2 view-module interface: render(container, scene, state) →
// handle, with handle.destroy(). `handle.reencode(state)` re-sorts and
// rebuilds the row list in place — ranking is weight-dependent, so a slider
// change can reorder every row. That reorder is *not* the "never re-run
// layout" case §4.2 protects: that guards a settled *spatial* layout (the
// treemap's tile x/y/width/height), not a flat list's own paint order,
// which the spec explicitly allows to reflow on re-rank.
//
// Diff-link decision (spec §6.1 "attention ledger" / G3): the per-file
// diff-link builder (GitHub's `pull/<n>/files#diff-<sha256hex(path)>` anchor
// scheme) is shared with the drill drawer via `window.vizShared.buildDiffLink`
// (hoisted to views/_shared.js, fidelity F3) — see that module for the full
// SubtleCrypto/`file://` degrade rationale.
(function () {
  "use strict";

  window.vizViews = window.vizViews || {};

  var IDS = {
    listMount: "viz-ledger-list",
    modeToggle: "viz-ledger-mode-toggle",
    sectionPr: "viz-ledger-section-pr",
    sectionContext: "viz-ledger-section-context",
    sectionAll: "viz-ledger-section-all"
  };

  // ---- scene.files → ranked rows (spec §6.1): one row per file, heat via
  // the shared computeHeat (never re-derived here), in_pr read straight off
  // the file's own attributes — the same flag the treemap reads for its
  // badge/outline. ----
  function computeRows(scene, computeHeat) {
    return scene.files.map(function (file) {
      var attributes = file.attributes || {};
      return {
        file: file,
        heat: computeHeat(attributes),
        inPr: Boolean(attributes.in_pr)
      };
    });
  }

  function byHeatDescThenPath(a, b) {
    if (b.heat !== a.heat) {
      return b.heat - a.heat;
    }
    if (a.file.path < b.file.path) {
      return -1;
    }
    if (a.file.path > b.file.path) {
      return 1;
    }
    return 0;
  }

  function buildDiffLinkHolder(scene, row) {
    var holder = document.createElement("span");
    holder.setAttribute("class", "viz-ledger-link");
    var link = window.vizShared.buildDiffLink(scene, row.file.path, row.inPr);
    if (link) {
      holder.appendChild(link);
    }
    return holder;
  }

  // Compact per-axis colored mini-bars (spec §4.5 "mirroring scene colors"),
  // same color tokens as the drill drawer and hover score card
  // (window.vizShared.axisColorVar) — one bare fill-only bar per heat axis,
  // no label/value text so the row stays compact.
  function buildAxisMiniBars(attributes) {
    var wrap = document.createElement("span");
    wrap.setAttribute("class", "viz-ledger-axis-bars");
    window.vizShared.HEAT_AXES.forEach(function (axis) {
      var value = typeof attributes[axis] === "number" ? attributes[axis] : 0;
      wrap.appendChild(window.vizShared.buildMiniBar(axis, value));
    });
    return wrap;
  }

  // Click-vs-drag threshold (~4px, spec §4.2), via the shared
  // `window.vizShared.wireClickVsDragActivation` (also used by the treemap
  // tile and the sonar ring mark — see views/_shared.js). A link inside the
  // row handles its own activation (see buildDiffLinkHolder's stopPropagation
  // wiring), so a pointerup/keydown originating from it is exempted here
  // rather than also opening the row's drill.
  function wireRowActivation(el, onActivate) {
    window.vizShared.wireClickVsDragActivation(el, {
      onActivate: onActivate,
      isExempt: function (evt) {
        return Boolean(evt.target.closest && evt.target.closest("a"));
      }
    });
  }

  // Hover score card (spec §4.5) — a disjoint event family (pointerenter/
  // move/leave) from wireRowActivation's own pointerdown/up/click/keydown,
  // so it never interferes with row activation or the diff link's own
  // stopPropagation guard.
  function wireRowTooltip(el, row) {
    el.addEventListener("pointerenter", function (evt) {
      window.vizShared.showTooltip(evt, function (container) {
        window.vizShared.buildScoreCard(
          container, row.file.path, row.file.attributes || {}, row.heat
        );
      });
    });
    el.addEventListener("pointermove", function (evt) {
      window.vizShared.moveTooltip(evt);
    });
    el.addEventListener("pointerleave", function () {
      window.vizShared.hideTooltip();
    });
  }

  function buildRow(scene, row, rank, openDrill) {
    var el = document.createElement("div");
    el.setAttribute("class", "viz-ledger-row");
    el.setAttribute("data-path", row.file.path);
    el.setAttribute("data-in-pr", row.inPr ? "true" : "false");
    // Keyboard reachability + screen-reader semantics (a11y), same contract
    // as the treemap's tiles.
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    var heatText = row.heat.toFixed(2);
    el.setAttribute(
      "aria-label",
      row.file.path + (row.inPr ? " (changed in this PR)" : "") + ", heat " + heatText
    );

    var rankEl = document.createElement("span");
    rankEl.setAttribute("class", "viz-ledger-rank");
    rankEl.textContent = String(rank);
    el.appendChild(rankEl);

    if (row.inPr) {
      // Reuses the legend's bordered-circle badge pattern (spec §4.5 legend
      // completeness — this is the same encoding, not a new one).
      var badge = document.createElement("span");
      badge.setAttribute("class", "viz-ledger-badge");
      badge.setAttribute("aria-hidden", "true");
      el.appendChild(badge);
    }

    var pathEl = document.createElement("span");
    pathEl.setAttribute("class", "viz-ledger-path");
    pathEl.textContent = row.file.path;
    el.appendChild(pathEl);

    el.appendChild(buildAxisMiniBars(row.file.attributes || {}));

    var heatEl = document.createElement("span");
    heatEl.setAttribute("class", "viz-ledger-heat");
    heatEl.textContent = heatText;
    el.appendChild(heatEl);

    el.appendChild(buildDiffLinkHolder(scene, row));

    wireRowActivation(el, function () {
      // The shape openDrill expects (spec: `fileNode.path` +
      // `fileNode.orig.file.attributes`) — the same shape the treemap's
      // pruned leaf nodes carry; built fresh here rather than duplicating
      // any tree-building machinery the ledger doesn't need.
      openDrill({ path: row.file.path, orig: { file: row.file } });
    });
    wireRowTooltip(el, row);

    return el;
  }

  function buildSection(scene, id, title, rows, openDrill) {
    var section = document.createElement("div");
    section.id = id;
    section.setAttribute("class", "viz-ledger-section");

    var heading = document.createElement("h3");
    heading.setAttribute("class", "viz-ledger-section-title");
    heading.textContent = title + " (" + rows.length + ")";
    section.appendChild(heading);

    rows.forEach(function (row, index) {
      section.appendChild(buildRow(scene, row, index + 1, openDrill));
    });
    return section;
  }

  window.vizViews.ledger = {
    render: function (container, scene, state) {
      var current = state;
      // "separated" (PR files ranked above context files, each section
      // ranked 1..N on its own) is the default view — a reviewer opening a
      // PR wants the changed files first; "mixed" is one flat ranking across
      // everything (spec §6.1).
      var mode = "separated";

      var toggleRow = document.createElement("div");
      toggleRow.setAttribute("class", "viz-ledger-toggle-row");
      var toggleButton = document.createElement("button");
      toggleButton.type = "button";
      toggleButton.id = IDS.modeToggle;
      toggleButton.setAttribute("class", "viz-btn");
      toggleButton.setAttribute("aria-pressed", "false");
      toggleButton.setAttribute("aria-label", "Mix PR and context files into one ranking");
      toggleRow.appendChild(toggleButton);
      container.appendChild(toggleRow);

      var listEl = document.createElement("div");
      listEl.id = IDS.listMount;
      listEl.setAttribute("class", "viz-ledger-list");
      container.appendChild(listEl);

      function updateToggleLabel() {
        toggleButton.textContent =
          mode === "separated" ? "Show mixed ranking" : "Show separated (PR / context)";
        toggleButton.setAttribute("aria-pressed", mode === "mixed" ? "true" : "false");
      }

      function renderAll() {
        // A rebuild (mode toggle, weight change) discards the current rows'
        // DOM without ever firing a real `pointerleave` on a hovered one —
        // hide unconditionally rather than leaving a dangling tooltip.
        window.vizShared.hideTooltip();
        while (listEl.firstChild) {
          listEl.removeChild(listEl.firstChild);
        }
        var rows = computeRows(scene, current.computeHeat).sort(byHeatDescThenPath);
        if (mode === "mixed") {
          listEl.appendChild(
            buildSection(scene, IDS.sectionAll, "All files", rows, current.openDrill)
          );
          return;
        }
        var prRows = rows.filter(function (row) {
          return row.inPr;
        });
        var contextRows = rows.filter(function (row) {
          return !row.inPr;
        });
        listEl.appendChild(
          buildSection(scene, IDS.sectionPr, "Changed in this PR", prRows, current.openDrill)
        );
        listEl.appendChild(
          buildSection(scene, IDS.sectionContext, "Context", contextRows, current.openDrill)
        );
      }

      toggleButton.addEventListener("click", function () {
        mode = mode === "separated" ? "mixed" : "separated";
        updateToggleLabel();
        renderAll();
      });

      updateToggleLabel();
      renderAll();

      return {
        destroy: function () {
          window.vizShared.hideTooltip();
          while (container.firstChild) {
            container.removeChild(container.firstChild);
          }
        },
        reencode: function (newState) {
          current = newState;
          renderAll();
        }
      };
    }
  };
})();
