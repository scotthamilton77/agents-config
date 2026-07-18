// vizsuite/app.js — shared view-shell harness (spec §4.2/§4.5): parses the
// inlined scene, builds the weight-slider control row, legend, drill panel
// and annotation baseline, wires the theme toggle, and mounts every
// registered view (window.vizViews, populated by the views bundle that is
// inlined immediately before this script) into a fresh container.
//
// Every repo-derived string (file/dir names, paths, notes) is bound via
// `textContent`/`.value` (or d3's `.text()`, which sets `textContent`) —
// never `innerHTML` — matching the DOM-bind invariant locked by the
// templating layer (spec §4.6).
(function () {
  "use strict";

  var IDS = {
    storageWarning: "viz-storage-warning",
    controls: "viz-controls",
    legend: "viz-legend",
    root: "viz-root",
    drillPanel: "viz-drill-panel",
    treemapView: "viz-view-treemap",
    ledgerView: "viz-view-ledger",
    constellationView: "viz-view-constellation",
    constellationToggle: "viz-constellation-toggle",
    staleGraphBadge: "viz-stale-graph-badge",
    header: "viz-header"
  };

  // Stable, action-naming accessible name (spec §4.5 toggle convention: the
  // aria-label never flips with state) for the constellation's default-off
  // experimental control (spec §6.1/§11 "gated concretely" — the module
  // ships inlined but is never mounted unless a reviewer opts in).
  var CONSTELLATION_TOGGLE_LABEL = "Show dependency constellation (experimental)";
  var CONSTELLATION_VIEW_OPTION = {
    name: "constellation",
    label: "Constellation",
    id: "viz-view-switch-constellation"
  };

  // The three §6.2 input axes, in the same order/names as
  // `vizsuite.scene.heat._INPUT_AXES` — the JS recompute below mirrors that
  // module's weighted-average formula exactly. Sourced from views/_shared.js
  // (window.vizShared.HEAT_AXES) rather than duplicated here.
  var HEAT_AXES = window.vizShared.HEAT_AXES;

  // ---- Heat math: Σ(wᵢ·vᵢ)/Σ(wᵢ) over the *active* axes only (an
  // unavailable axis is excluded from both the sum and the normalizer, so
  // the remaining axes renormalize — spec §6.2, mirrors `scene.heat.combine`
  // exactly). ----
  function computeHeatFactory(weights, unavailableAxes) {
    var active = Object.keys(weights).filter(function (axis) {
      return unavailableAxes.indexOf(axis) === -1;
    });
    var weightTotal = active.reduce(function (sum, axis) {
      return sum + weights[axis];
    }, 0);
    return function (attributes) {
      if (weightTotal <= 0) {
        return 0;
      }
      var weightedSum = active.reduce(function (sum, axis) {
        var value = typeof attributes[axis] === "number" ? attributes[axis] : 0;
        return sum + weights[axis] * value;
      }, 0);
      return weightedSum / weightTotal;
    };
  }

  // ---- Annotation store (spec §4.5/§5.8 baseline): localStorage, feature-
  // detected, with an in-memory fallback so the copy-as-JSON button always
  // works even when the origin (a bare `file://` artifact) disables storage.
  // Notes key on `viz:<repo_nwo>:pr:<file-path>` — V1 has no Tier-2 fact ids,
  // so the file is the annotatable unit. Rebased on the shared localStorage
  // factory (views/_shared.js), which treemap.js's collapse/focus-state
  // store now also uses (fidelity F3). ----
  function makeAnnotationStore(repoNwo) {
    var prefix = "viz:" + repoNwo + ":pr:";
    var store = window.vizShared.makeLocalStorageStore(prefix);

    function keyFor(path) {
      return prefix + path;
    }

    function get(path) {
      return store.getItem(keyFor(path)) || "";
    }

    function set(path, value) {
      if (value) {
        store.setItem(keyFor(path), value);
      } else {
        store.removeItem(keyFor(path));
      }
    }

    function getAll() {
      var out = {};
      store.keys().forEach(function (key) {
        out[key] = store.getItem(key);
      });
      return out;
    }

    return {
      available: store.available,
      get: get,
      set: set,
      getAll: getAll,
      onFallback: store.onFallback
    };
  }

  // ---- Theme (spec §4.3): an explicit `data-viz-theme` stamp beats the OS
  // preference both ways; absent a stamp, OS `prefers-color-scheme` decides. ----
  function currentThemeName() {
    var stamped = document.documentElement.getAttribute("data-viz-theme");
    if (stamped) {
      return stamped;
    }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function wireThemeToggle(button, onChange) {
    function applyLabel() {
      button.textContent = currentThemeName() === "dark" ? "Light mode" : "Dark mode";
    }
    button.addEventListener("click", function () {
      var next = currentThemeName() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-viz-theme", next);
      applyLabel();
      onChange();
    });
    applyLabel();
  }

  // ---- Control row (spec §4.2/§4.5: flow layout only, never absolute
  // positioning) — one slider per heat axis, disabled when unavailable,
  // plus the live mix readout. ----
  function updateMixReadout(mixReadoutEl, weights, unavailableAxes) {
    while (mixReadoutEl.firstChild) {
      mixReadoutEl.removeChild(mixReadoutEl.firstChild);
    }
    var active = HEAT_AXES.filter(function (axis) {
      return unavailableAxes.indexOf(axis) === -1;
    });
    var total = active.reduce(function (sum, axis) {
      return sum + (weights[axis] || 0);
    }, 0);
    active.forEach(function (axis) {
      var share = total > 0 ? (weights[axis] || 0) / total : 0;
      var item = document.createElement("span");
      item.textContent = axis + " " + Math.round(share * 100) + "%";
      mixReadoutEl.appendChild(item);
    });
  }

  function buildControls(container, weights, unavailableAxes, onWeightChange) {
    var sliderRow = document.createElement("div");
    sliderRow.setAttribute("class", "viz-slider-row");

    HEAT_AXES.forEach(function (axis) {
      var isUnavailable = unavailableAxes.indexOf(axis) !== -1;
      var item = document.createElement("div");
      item.setAttribute("class", "viz-slider-item");
      item.setAttribute("data-axis", axis);
      item.setAttribute("data-unavailable", isUnavailable ? "true" : "false");

      var labelId = "viz-slider-label-" + axis;
      var label = document.createElement("label");
      label.id = labelId;
      label.textContent = axis + (isUnavailable ? " (unavailable this run)" : "");

      var input = document.createElement("input");
      input.type = "range";
      input.min = "0";
      input.max = "1";
      input.step = "0.01";
      input.className = "viz-slider-input";
      input.setAttribute("aria-labelledby", labelId);
      input.setAttribute("data-axis", axis);
      input.value = String(typeof weights[axis] === "number" ? weights[axis] : 0);
      input.disabled = isUnavailable;

      var valueEl = document.createElement("span");
      valueEl.setAttribute("class", "viz-slider-value");
      valueEl.textContent = Number(input.value).toFixed(2);

      input.addEventListener("input", function () {
        weights[axis] = Number(input.value);
        valueEl.textContent = Number(input.value).toFixed(2);
        onWeightChange();
      });

      item.appendChild(label);
      item.appendChild(input);
      item.appendChild(valueEl);
      sliderRow.appendChild(item);
    });

    container.appendChild(sliderRow);

    var mixReadout = document.createElement("div");
    mixReadout.id = "viz-mix-readout";
    mixReadout.setAttribute("class", "viz-mix-readout");
    container.appendChild(mixReadout);
    updateMixReadout(mixReadout, weights, unavailableAxes);

    var themeButton = document.createElement("button");
    themeButton.id = "viz-theme-toggle";
    themeButton.type = "button";
    themeButton.setAttribute("class", "viz-btn");
    container.appendChild(themeButton);

    var copyButton = document.createElement("button");
    copyButton.id = "viz-copy-notes";
    copyButton.type = "button";
    copyButton.setAttribute("class", "viz-btn");
    copyButton.textContent = "Copy notes as JSON";
    container.appendChild(copyButton);

    var copyStatus = document.createElement("span");
    copyStatus.id = "viz-copy-status";
    copyStatus.setAttribute("class", "viz-slider-value");
    container.appendChild(copyStatus);

    return {
      mixReadout: mixReadout,
      themeButton: themeButton,
      copyButton: copyButton,
      copyStatus: copyStatus
    };
  }

  function wireCopyNotesButton(button, statusEl, annotationStore) {
    button.addEventListener("click", function () {
      var notes = annotationStore.getAll();
      var payload = JSON.stringify(notes, null, 2);
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        statusEl.textContent = "Copy unsupported in this browser.";
        return;
      }
      navigator.clipboard.writeText(payload).then(
        function () {
          statusEl.textContent = "Copied " + Object.keys(notes).length + " note(s).";
        },
        function () {
          statusEl.textContent = "Copy failed — clipboard write was denied.";
        }
      );
    });
  }

  // ---- Stale-graph badge (spec §6.2 `--allow-stale-graph` opt-in): a header
  // badge naming the exact build commit the load-bearing axis was scored
  // from, so an accepted-stale graph is never mistaken for a fresh one.
  // Present only when `scene.render_config.stale_graph` is present — a fresh
  // or unavailable axis carries no `stale_graph`, so no badge renders. ----
  function staleGraphBadgeText(staleGraph) {
    var shortSha = String(staleGraph.built_at_commit).slice(0, 7);
    var text = "graph @ " + shortSha + " (stale";
    if (typeof staleGraph.commits_behind === "number") {
      var noun = staleGraph.commits_behind === 1 ? "commit" : "commits";
      text += ", " + staleGraph.commits_behind + " " + noun + " behind PR head";
    }
    return text + ")";
  }

  function appendStaleGraphBadge(headerEl, staleGraph) {
    if (!staleGraph) {
      return;
    }
    var badge = document.createElement("div");
    badge.id = IDS.staleGraphBadge;
    badge.setAttribute("class", "viz-stale-graph-badge");
    badge.textContent = staleGraphBadgeText(staleGraph);
    headerEl.appendChild(badge);
  }

  // ---- Legend (spec §4.5: every encoding present in the scene appears
  // here; no orphan entries) — the heat scale, the PR-touched marker, and
  // the default-collapsed marker are the only encodings this view renders. ----
  function buildLegend(container, staleGraph) {
    var heatStops = [
      { token: "heat-cold", label: "low attention" },
      { token: "heat-mid", label: "medium attention" },
      { token: "heat-hot", label: "high attention (collapsed groups show the worst offender)" }
    ];
    heatStops.forEach(function (stop) {
      var item = document.createElement("span");
      item.setAttribute("class", "viz-legend-item");
      var swatch = document.createElement("span");
      swatch.setAttribute("class", "viz-legend-swatch");
      swatch.style.background = "var(--viz-" + stop.token + ")";
      var label = document.createElement("span");
      label.textContent = stop.label;
      item.appendChild(swatch);
      item.appendChild(label);
      container.appendChild(item);
    });

    var prItem = document.createElement("span");
    prItem.setAttribute("class", "viz-legend-item");
    var prBadge = document.createElement("span");
    prBadge.setAttribute("class", "viz-legend-badge");
    var prLabel = document.createElement("span");
    prLabel.textContent = "file changed in this PR";
    prItem.appendChild(prBadge);
    prItem.appendChild(prLabel);
    container.appendChild(prItem);

    var collapseItem = document.createElement("span");
    collapseItem.setAttribute("class", "viz-legend-item");
    var collapseGlyph = document.createElement("span");
    collapseGlyph.textContent = "▸";
    var collapseLabel = document.createElement("span");
    collapseLabel.textContent =
      "collapsed group (no PR-touched files by default) — area ∝ file count, compressed";
    collapseItem.appendChild(collapseGlyph);
    collapseItem.appendChild(collapseLabel);
    container.appendChild(collapseItem);

    if (staleGraph) {
      var staleItem = document.createElement("span");
      staleItem.setAttribute("class", "viz-legend-item");
      var staleSwatch = document.createElement("span");
      staleSwatch.setAttribute("class", "viz-legend-badge viz-legend-badge--stale");
      var staleLabel = document.createElement("span");
      staleLabel.textContent =
        staleGraphBadgeText(staleGraph) + " — accepted via --allow-stale-graph";
      staleItem.appendChild(staleSwatch);
      staleItem.appendChild(staleLabel);
      container.appendChild(staleItem);
    }
  }

  // ---- Sonar affordance (spec §6.1: file sonar as a drill, not a top-level
  // view) — a toggle button in the drill panel opens the sonar rendering as
  // a full-canvas overlay (round-2 fix) over `rootEl` (`#viz-root`, the main
  // scene area) rather than squeezed inside the ~370px drawer — real edge
  // density needs the room the drawer can't give it. The overlay is its own
  // fresh container per open (spec §4.2), never a child of the drawer, so it
  // survives the drawer's own DOM wipe on a later openDrill call — see the
  // explicit teardown in makeOpenDrill below. The dependency-graph-
  // unavailable state (the load-bearing axis fail-softed, per
  // render_config.unavailable_axes) is handled by `window.vizSonar` itself,
  // which renders the "unavailable" state (or, for a file with zero edges of
  // its own, an explicit empty-neighborhood state) in place of rings — the
  // affordance is always present and always safe to open.
  function appendSonarAffordance(panelEl, rootEl, scene, fileNode, drillState) {
    var toggle = document.createElement("button");
    toggle.id = "viz-drill-sonar-toggle";
    toggle.type = "button";
    toggle.setAttribute("class", "viz-btn");
    toggle.setAttribute("aria-pressed", "false");
    // Stable accessible name (never flips with state, per spec §4.5 toggle
    // convention) — only the visible text + aria-pressed change.
    toggle.setAttribute("aria-label", "Show dependency blast radius for this file");
    toggle.textContent = "Show blast radius";
    panelEl.appendChild(toggle);

    // Shared close path for the toggle's own "Hide" click, the overlay's own
    // close button, and Escape (wireDrillPanelClose below) — every close
    // fully destroys the sonar render and removes the overlay, rather than
    // merely hiding it, so the "fresh container per open" contract holds
    // for every trigger, not just a drawer rebuild.
    function closeOverlay() {
      if (drillState.sonarHandle && typeof drillState.sonarHandle.destroy === "function") {
        drillState.sonarHandle.destroy();
      }
      drillState.sonarHandle = null;
      if (drillState.sonarOverlayEl && drillState.sonarOverlayEl.parentNode) {
        drillState.sonarOverlayEl.parentNode.removeChild(drillState.sonarOverlayEl);
      }
      drillState.sonarOverlayEl = null;
      drillState.closeSonarOverlay = null;
      toggle.setAttribute("aria-pressed", "false");
      toggle.textContent = "Show blast radius";
    }

    toggle.addEventListener("click", function () {
      var expanded = toggle.getAttribute("aria-pressed") === "true";
      if (expanded) {
        closeOverlay();
        return;
      }
      // Same success-gated-UI-state contract as mountView: a missing sonar
      // module (`window.vizSonar` absent) never flips the toggle to "pressed"
      // over an empty overlay.
      if (!window.vizSonar || typeof window.vizSonar.render !== "function") {
        return;
      }

      var overlay = document.createElement("div");
      overlay.id = "viz-blast-overlay";
      overlay.setAttribute("class", "viz-blast-overlay");
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-label", "Dependency blast radius for " + fileNode.path);

      var closeBtn = document.createElement("button");
      closeBtn.id = "viz-blast-overlay-close";
      closeBtn.type = "button";
      closeBtn.setAttribute("class", "viz-btn viz-blast-overlay-close");
      closeBtn.textContent = "Close blast radius";
      closeBtn.addEventListener("click", closeOverlay);
      overlay.appendChild(closeBtn);

      var mount = document.createElement("div");
      mount.id = "viz-drill-sonar-mount";
      mount.setAttribute("class", "viz-drill-sonar-mount");
      overlay.appendChild(mount);

      rootEl.appendChild(overlay);
      drillState.sonarOverlayEl = overlay;
      drillState.closeSonarOverlay = closeOverlay;
      drillState.sonarHandle = window.vizSonar.render(mount, scene, fileNode.path);

      toggle.setAttribute("aria-pressed", "true");
      toggle.textContent = "Hide blast radius";
    });
  }

  function appendBulletList(storySection, titleText, items, listClass) {
    if (!items || items.length === 0) {
      return;
    }
    var titleEl = document.createElement("h3");
    titleEl.textContent = titleText;
    storySection.appendChild(titleEl);
    var listEl = document.createElement("ul");
    listEl.setAttribute("class", listClass);
    items.forEach(function (item) {
      var itemEl = document.createElement("li");
      itemEl.textContent = item;
      listEl.appendChild(itemEl);
    });
    storySection.appendChild(listEl);
  }

  // ---- Drill panel (spec §4.2/§4.5): a full-height right-docked drawer
  // (fidelity F3 — converted from an earlier floating overlay card, prototype
  // anatomy `#drill`/`showDrill`); Escape closes; the notes textarea binds
  // via `.value`, never `innerHTML`. `onOpenChange(open)` toggles the
  // stage-shrink class on `#viz-root` and lets the treemap re-run its layout
  // against the narrower container (see `viz:drill-panel-toggled` in
  // views/treemap.js) — the drawer never overlays the diagram. ----
  function makeOpenDrill(
    panelEl, rootEl, scene, annotationStore, weights, unavailableAxes, drillState, onOpenChange
  ) {
    return function (fileNode) {
      // A prior file's (or the same file's, on a weight-change refresh)
      // sonar render is about to be discarded — destroy it explicitly rather
      // than relying on the panel DOM removal below (spec §4.2: destroy the
      // outgoing content, no leaked marks when recentering/reopening). The
      // blast-radius overlay (round-2 fix) lives under `rootEl`, not
      // `panelEl`, so wiping the panel's children alone would leave it
      // behind — remove it explicitly too.
      if (drillState.sonarHandle && typeof drillState.sonarHandle.destroy === "function") {
        drillState.sonarHandle.destroy();
      }
      drillState.sonarHandle = null;
      if (drillState.sonarOverlayEl && drillState.sonarOverlayEl.parentNode) {
        drillState.sonarOverlayEl.parentNode.removeChild(drillState.sonarOverlayEl);
      }
      drillState.sonarOverlayEl = null;
      drillState.closeSonarOverlay = null;

      // Remember the open node so a weight change can recompute the
      // weight-dependent breakdown in place (spec §4.5) — see onWeightChange.
      drillState.node = fileNode;

      while (panelEl.firstChild) {
        panelEl.removeChild(panelEl.firstChild);
      }

      var closeBtn = document.createElement("button");
      closeBtn.id = "viz-drill-panel-close";
      closeBtn.type = "button";
      closeBtn.setAttribute("class", "viz-btn");
      closeBtn.textContent = "Close";
      closeBtn.addEventListener("click", function () {
        drillState.node = null;
        panelEl.hidden = true;
        onOpenChange(false);
      });
      panelEl.appendChild(closeBtn);

      var heading = document.createElement("h2");
      heading.textContent = fileNode.path;
      panelEl.appendChild(heading);

      var attributes =
        (fileNode.orig && fileNode.orig.file && fileNode.orig.file.attributes) || {};
      var isInPr = Boolean(attributes.in_pr);

      // PR diff stats (spec §4.5, prototype `.stat` chips) + the shared
      // per-file diff link (views/_shared.js, hoisted out of views/ledger.js)
      // — both silently absent for a context file or when the churn/repo_nwo
      // data isn't there (never fabricated).
      var statsRow = document.createElement("div");
      statsRow.setAttribute("class", "viz-drill-stats");
      if (isInPr && typeof attributes.added === "number") {
        var deleted = typeof attributes.deleted === "number" ? attributes.deleted : 0;
        var churnChip = document.createElement("span");
        churnChip.setAttribute("class", "viz-drill-stat");
        churnChip.textContent = "+" + attributes.added + "/−" + deleted;
        statsRow.appendChild(churnChip);
      }
      var diffLink = window.vizShared.buildDiffLink(scene, fileNode.path, isInPr);
      if (diffLink) {
        statsRow.appendChild(diffLink);
      }
      if (statsRow.childNodes.length > 0) {
        panelEl.appendChild(statsRow);
      }

      var activeAxes = HEAT_AXES.filter(function (axis) {
        return unavailableAxes.indexOf(axis) === -1;
      });
      var weightTotal = activeAxes.reduce(function (sum, axis) {
        return sum + (weights[axis] || 0);
      }, 0);

      HEAT_AXES.forEach(function (axis) {
        var isUnavailable = unavailableAxes.indexOf(axis) !== -1;
        var raw = typeof attributes[axis] === "number" ? attributes[axis] : 0;
        var share =
          isUnavailable || weightTotal <= 0 ? 0 : (weights[axis] || 0) / weightTotal;

        // Per-axis colored bar (spec §4.5 "mirroring scene colors"), plus the
        // existing raw × weight% = contribution breakdown text row beneath it
        // — the bar is new anatomy, the contribution math is unchanged.
        panelEl.appendChild(
          window.vizShared.buildMeterRow(axis, axis + (isUnavailable ? " (unavailable)" : ""), raw)
        );

        var row = document.createElement("div");
        row.setAttribute("class", "viz-drill-row");
        var label = document.createElement("span");
        label.textContent = axis + (isUnavailable ? " (unavailable)" : "");
        var value = document.createElement("span");
        value.textContent =
          raw.toFixed(2) + " × " + Math.round(share * 100) + "% = " + (raw * share).toFixed(2);
        row.appendChild(label);
        row.appendChild(value);
        panelEl.appendChild(row);
      });

      var heatRow = document.createElement("div");
      heatRow.setAttribute("class", "viz-drill-row");
      var heatLabel = document.createElement("span");
      heatLabel.textContent = "combined heat";
      var heatValue = document.createElement("span");
      // Recompute from `attributes` + the current `weights` rather than the
      // captured `fileNode.heat`: a full treemap re-render (collapse/resize)
      // builds fresh nodes via pruneForLayout(), so the captured snapshot can
      // go stale. Reusing computeHeatFactory keeps this readout consistent with
      // the per-axis shares above and the tile colors (same math, live weights).
      var combinedHeat = computeHeatFactory(weights, unavailableAxes)(attributes);
      heatValue.textContent = combinedHeat.toFixed(2);
      heatRow.appendChild(heatLabel);
      heatRow.appendChild(heatValue);
      panelEl.appendChild(heatRow);

      // Tier-2 drill story (spec §6.2 drill-story channel, prototype
      // anatomy: showDrill's `f.story` branch) — headline + "Why it's hot" +
      // "What to check" bullets, rendered only when the scene attached a
      // story to this file. Mechanically-catchable content (deleted
      // assertions, lint-class findings) is excluded from stories at
      // GENERATION time (bead .2.4, not built yet) — this render side never
      // filters, it only shows what's there. All content is bound via
      // textContent, never innerHTML (spec §4.5 drill-panel DOM-bind
      // invariant) — repo/agent-derived story text is untrusted.
      var story = fileNode.orig && fileNode.orig.file && fileNode.orig.file.story;
      if (story) {
        var storySection = document.createElement("div");
        storySection.id = "viz-drill-story";
        storySection.setAttribute("class", "viz-drill-story");

        var headlineEl = document.createElement("div");
        headlineEl.setAttribute("class", "viz-drill-story-headline");
        headlineEl.textContent = story.change_summary;
        storySection.appendChild(headlineEl);

        appendBulletList(storySection, "Why it's hot", story.why_hot, "viz-drill-story-why");
        appendBulletList(
          storySection, "What to check", story.what_to_check, "viz-drill-story-check"
        );

        panelEl.appendChild(storySection);
      }

      appendSonarAffordance(panelEl, rootEl, scene, fileNode, drillState);

      var notes = document.createElement("textarea");
      notes.setAttribute("class", "viz-drill-notes");
      notes.value = annotationStore.get(fileNode.path);
      notes.addEventListener("input", function () {
        annotationStore.set(fileNode.path, notes.value);
      });
      panelEl.appendChild(notes);

      panelEl.hidden = false;
      onOpenChange(true);
    };
  }

  function wireDrillPanelClose(panelEl, drillState, onOpenChange) {
    document.addEventListener("keydown", function (evt) {
      if (evt.key !== "Escape") {
        return;
      }
      // Round-2 fix: the blast-radius overlay sits "on top" of the drawer
      // (spec: "drawer stays open beside it") — the first Escape closes
      // just the overlay; a second Escape then closes the drawer, same as
      // before the overlay existed.
      if (drillState.sonarOverlayEl && typeof drillState.closeSonarOverlay === "function") {
        drillState.closeSonarOverlay();
        return;
      }
      if (!panelEl.hidden) {
        drillState.node = null;
        panelEl.hidden = true;
        onOpenChange(false);
      }
    });
  }

  function dispatchThemeChanged() {
    document.dispatchEvent(new CustomEvent("viz:theme-changed"));
  }

  // ---- View switcher (spec §6.1: treemap ↔ ledger) — a control-row toggle
  // between the registered top-level views. Mutually exclusive by design:
  // only one view is ever mounted (spec §4.2's "fresh container per
  // render" means switching destroys the outgoing view before mounting the
  // next, never layering a second view's DOM on top). ----
  var VIEW_SWITCH_OPTIONS = [
    { name: "treemap", label: "Treemap", id: "viz-view-switch-treemap" },
    { name: "ledger", label: "Ledger", id: "viz-view-switch-ledger" }
  ];

  function buildViewSwitcher(container, onSelect) {
    var wrapper = document.createElement("div");
    wrapper.id = "viz-view-switcher";
    wrapper.setAttribute("class", "viz-view-switcher");
    wrapper.setAttribute("role", "group");
    wrapper.setAttribute("aria-label", "View");

    var buttons = {};

    // Registers one switch button on demand — the constellation's
    // default-off experimental toggle calls this only once a reviewer opts
    // in (spec §6.1/§11), so the treemap↔ledger switcher stays the only
    // thing a reviewer sees by default.
    function addOption(option) {
      var button = document.createElement("button");
      button.type = "button";
      button.id = option.id;
      button.setAttribute("class", "viz-btn viz-view-switch");
      button.setAttribute("aria-pressed", "false");
      button.textContent = option.label;
      button.addEventListener("click", function () {
        onSelect(option.name);
      });
      wrapper.appendChild(button);
      buttons[option.name] = button;
    }

    function removeOption(name) {
      var button = buttons[name];
      if (!button) {
        return;
      }
      if (button.parentNode) {
        button.parentNode.removeChild(button);
      }
      delete buttons[name];
    }

    VIEW_SWITCH_OPTIONS.forEach(addOption);
    container.appendChild(wrapper);

    return {
      addOption: addOption,
      removeOption: removeOption,
      setActive: function (name) {
        Object.keys(buttons).forEach(function (optionName) {
          buttons[optionName].setAttribute("aria-pressed", optionName === name ? "true" : "false");
        });
      }
    };
  }

  // ---- Constellation experimental toggle (spec §6.1/§11 "gated
  // concretely"): a default-off, clearly-labeled control that registers the
  // constellation as a third switchable view only on demand — mounting is
  // never automatic, so the default artifact never pays its layout/render
  // cost. Toggling off while it is the active view falls back to the
  // treemap, the same "always land on a real view" contract mountView's
  // success-gating already protects. ----
  function appendConstellationToggle(container, viewSwitcher, onToggle) {
    var toggle = document.createElement("button");
    toggle.id = IDS.constellationToggle;
    toggle.type = "button";
    toggle.setAttribute("class", "viz-btn");
    toggle.setAttribute("aria-pressed", "false");
    toggle.setAttribute("aria-label", CONSTELLATION_TOGGLE_LABEL);
    toggle.textContent = CONSTELLATION_TOGGLE_LABEL;
    container.appendChild(toggle);

    var enabled = false;
    toggle.addEventListener("click", function () {
      enabled = !enabled;
      toggle.setAttribute("aria-pressed", enabled ? "true" : "false");
      toggle.textContent = enabled
        ? "Hide dependency constellation (experimental)"
        : CONSTELLATION_TOGGLE_LABEL;
      if (enabled) {
        viewSwitcher.addOption(CONSTELLATION_VIEW_OPTION);
      } else {
        viewSwitcher.removeOption(CONSTELLATION_VIEW_OPTION.name);
      }
      onToggle(enabled);
    });
  }

  function main() {
    var scene = JSON.parse(document.getElementById("viz-scene").textContent);
    document.getElementById("viz-title").textContent = "viz — PR #" + scene.pr_number;
    document.getElementById("viz-generated-at").textContent = scene.generated_at;

    var weights = {};
    HEAT_AXES.forEach(function (axis) {
      var defaults = scene.render_config && scene.render_config.default_weights;
      if (defaults && typeof defaults[axis] === "number") {
        weights[axis] = defaults[axis];
      }
    });
    var unavailableAxes =
      (scene.render_config && scene.render_config.unavailable_axes) || [];
    var staleGraph = (scene.render_config && scene.render_config.stale_graph) || null;

    var annotationStore = makeAnnotationStore(scene.repo_nwo);

    var elements = {
      storageWarning: document.getElementById(IDS.storageWarning),
      controls: document.getElementById(IDS.controls),
      legend: document.getElementById(IDS.legend),
      root: document.getElementById(IDS.root),
      drillPanel: document.getElementById(IDS.drillPanel),
      header: document.getElementById(IDS.header)
    };
    appendStaleGraphBadge(elements.header, staleGraph);

    if (!annotationStore.available) {
      elements.storageWarning.textContent =
        "Notes are not being saved (localStorage is unavailable on this origin). " +
        "Use “Copy notes as JSON” before closing this tab.";
      elements.storageWarning.hidden = false;
    }

    // Shared by every localStorage-backed store's onFallback handler (the
    // annotation store below, and the treemap's collapse/focus-state store —
    // views/treemap.js reaches this via `state.notifyStorageFallback`) so a
    // runtime write failure (e.g. quota exceeded) always surfaces the same
    // visible banner, whichever store hit it.
    function surfaceStorageFallback(message) {
      elements.storageWarning.textContent = message;
      elements.storageWarning.hidden = false;
    }

    // Storage was available at page-load but a later write failed (e.g. quota
    // exceeded) — reveal the same banner so the reviewer sees that notes have
    // stopped persisting mid-session.
    annotationStore.onFallback(function () {
      surfaceStorageFallback(
        "Notes have stopped being saved (a localStorage write failed — the " +
          "browser storage quota may be full). " +
          "Use “Copy notes as JSON” before closing this tab."
      );
    });

    var mountedViews = [];

    // Shared drill-panel state: `node` holds the currently-open file node (or
    // null when closed) so a weight change can refresh the open breakdown;
    // `sonarHandle` holds the currently-mounted sonar drill (or null), so it
    // can be torn down before the panel rebuilds (spec §4.2). `sonarOverlayEl`
    // / `closeSonarOverlay` (round-2 fix) track the full-canvas blast-radius
    // overlay, which lives outside the drawer under `#viz-root` and so needs
    // its own explicit teardown (see makeOpenDrill and wireDrillPanelClose).
    var drillState = {
      node: null,
      sonarHandle: null,
      sonarOverlayEl: null,
      closeSonarOverlay: null
    };

    // Drawer conversion (fidelity F3): the drawer never overlays the diagram
    // — `#viz-root`'s `viz-drill-open` class shrinks it (scene.css), and the
    // `viz:drill-panel-toggled` event lets the treemap re-run its layout
    // against the new width (views/treemap.js) — a real dimension change,
    // not the "encoding-only" case reencode() covers.
    function onDrillOpenChange(open) {
      elements.root.classList.toggle("viz-drill-open", open);
      document.dispatchEvent(
        new CustomEvent("viz:drill-panel-toggled", { detail: { open: open } })
      );
    }

    var openDrill = makeOpenDrill(
      elements.drillPanel,
      elements.root,
      scene,
      annotationStore,
      weights,
      unavailableAxes,
      drillState,
      onDrillOpenChange
    );

    function onWeightChange() {
      updateMixReadout(controls.mixReadout, weights, unavailableAxes);
      reencodeAll();
      // reencodeAll() repaints tiles and refreshes each node's heat in place;
      // if the drill panel is open its shares + combined-heat math is now
      // stale, so re-render it from the same node (no duplicated math).
      if (drillState.node !== null && !elements.drillPanel.hidden) {
        openDrill(drillState.node);
      }
    }

    function reencodeAll() {
      var state = currentState();
      mountedViews.forEach(function (handle) {
        if (handle && typeof handle.reencode === "function") {
          handle.reencode(state);
        }
      });
    }

    function currentState() {
      return {
        weights: weights,
        unavailableAxes: unavailableAxes,
        computeHeat: computeHeatFactory(weights, unavailableAxes),
        theme: currentThemeName(),
        openDrill: openDrill,
        notifyStorageFallback: surfaceStorageFallback
      };
    }

    var controls = buildControls(elements.controls, weights, unavailableAxes, onWeightChange);
    wireThemeToggle(controls.themeButton, function () {
      document.dispatchEvent && dispatchThemeChanged();
    });
    wireCopyNotesButton(controls.copyButton, controls.copyStatus, annotationStore);
    buildLegend(elements.legend, staleGraph);
    wireDrillPanelClose(elements.drillPanel, drillState, onDrillOpenChange);

    document.addEventListener("viz:theme-changed", reencodeAll);

    var activeView = null;

    function unmountActiveView() {
      if (!activeView) {
        return;
      }
      if (activeView.handle && typeof activeView.handle.destroy === "function") {
        activeView.handle.destroy();
      }
      if (activeView.container.parentNode) {
        activeView.container.parentNode.removeChild(activeView.container);
      }
      mountedViews = [];
      activeView = null;
    }

    function mountView(name, mountId) {
      var registered = window.vizViews && window.vizViews[name];
      if (!registered || typeof registered.render !== "function") {
        return false;
      }
      // Only one view mounted at a time (spec §6.1 view switcher): destroy
      // the outgoing view before handing out a fresh container (spec §4.2 —
      // never a shared mount point, so a view never inherits another
      // render's leftover DOM/state).
      unmountActiveView();
      var container = document.createElement("div");
      container.id = mountId;
      container.setAttribute("class", "viz-" + name);
      elements.root.appendChild(container);
      var handle = registered.render(container, scene, currentState());
      mountedViews.push(handle);
      activeView = { name: name, container: container, handle: handle };
      return true;
    }

    var viewMountIds = {
      treemap: IDS.treemapView,
      ledger: IDS.ledgerView,
      constellation: IDS.constellationView
    };
    var viewSwitcher = buildViewSwitcher(elements.controls, function (name) {
      // Only reflect the switch in the toggle when the view actually
      // mounted; a no-op mount (missing view module) would otherwise leave
      // the switcher indicating a view that never replaced the current one.
      if (mountView(name, viewMountIds[name])) {
        viewSwitcher.setActive(name);
      }
    });

    appendConstellationToggle(elements.controls, viewSwitcher, function (enabled) {
      if (enabled) {
        return;
      }
      // Toggling off while the constellation is the active view falls back
      // to the treemap — the view switcher just lost its button for the
      // view currently on screen, so this is not merely cosmetic cleanup.
      if (activeView && activeView.name === "constellation") {
        mountView("treemap", viewMountIds.treemap);
        viewSwitcher.setActive("treemap");
      }
    });

    mountView("treemap", IDS.treemapView);
    viewSwitcher.setActive("treemap");
  }

  main();
})();
