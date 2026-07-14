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
    ledgerView: "viz-view-ledger"
  };

  // The three §6.2 input axes, in the same order/names as
  // `vizsuite.scene.heat._INPUT_AXES` — the JS recompute below mirrors that
  // module's weighted-average formula exactly.
  var HEAT_AXES = ["complexity", "load_bearing", "consequence"];

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
  // so the file is the annotatable unit. ----
  function makeAnnotationStore(repoNwo) {
    var prefix = "viz:" + repoNwo + ":pr:";
    var available = false;
    // Probe key carries a NUL delimiter, which no valid repo path can
    // contain, so it can never collide with a note key (`prefix + <path>`).
    var probeKey = prefix + "\u0000probe";
    try {
      window.localStorage.setItem(probeKey, "1");
      window.localStorage.removeItem(probeKey);
      available = true;
    } catch (err) {
      available = false;
    }
    var memory = Object.create(null);
    var fallbackHandler = null;
    var fallbackNotified = false;

    // Fires the registered handler the first time a runtime write falls back
    // to the in-memory map (e.g. quota exceeded) so the UI can surface the
    // non-persistence warning that boot-time feature detection would miss.
    function notifyFallback() {
      if (fallbackNotified) {
        return;
      }
      fallbackNotified = true;
      if (typeof fallbackHandler === "function") {
        fallbackHandler();
      }
    }

    function onFallback(handler) {
      fallbackHandler = handler;
    }

    function keyFor(path) {
      return prefix + path;
    }

    function get(path) {
      var key = keyFor(path);
      if (available) {
        return window.localStorage.getItem(key) || "";
      }
      return memory[key] || "";
    }

    function set(path, value) {
      var key = keyFor(path);
      if (available) {
        try {
          if (value) {
            window.localStorage.setItem(key, value);
          } else {
            window.localStorage.removeItem(key);
          }
          return;
        } catch (err) {
          // Fall through to the in-memory map (e.g. quota exceeded) and
          // surface the non-persistence warning — notes stopped persisting
          // mid-session even though storage was available at page-load.
          notifyFallback();
        }
      }
      if (value) {
        memory[key] = value;
      } else {
        delete memory[key];
      }
    }

    function getAll() {
      var out = {};
      if (available) {
        for (var i = 0; i < window.localStorage.length; i++) {
          var k = window.localStorage.key(i);
          if (k && k.indexOf(prefix) === 0) {
            out[k] = window.localStorage.getItem(k);
          }
        }
      } else {
        for (var mk in memory) {
          if (Object.prototype.hasOwnProperty.call(memory, mk)) {
            out[mk] = memory[mk];
          }
        }
      }
      return out;
    }

    return {
      available: available,
      get: get,
      set: set,
      getAll: getAll,
      onFallback: onFallback
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

  // ---- Legend (spec §4.5: every encoding present in the scene appears
  // here; no orphan entries) — the heat scale, the PR-touched marker, and
  // the default-collapsed marker are the only encodings this view renders. ----
  function buildLegend(container) {
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
    collapseLabel.textContent = "collapsed group (no PR-touched files by default)";
    collapseItem.appendChild(collapseGlyph);
    collapseItem.appendChild(collapseLabel);
    container.appendChild(collapseItem);
  }

  // ---- Drill panel (spec §4.2/§4.5): opaque overlay; Escape closes; the
  // notes textarea binds via `.value`, never `innerHTML`. ----
  function makeOpenDrill(panelEl, annotationStore, weights, unavailableAxes, drillState) {
    return function (fileNode) {
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
      });
      panelEl.appendChild(closeBtn);

      var heading = document.createElement("h2");
      heading.textContent = fileNode.path;
      panelEl.appendChild(heading);

      var attributes =
        (fileNode.orig && fileNode.orig.file && fileNode.orig.file.attributes) || {};
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

      var notes = document.createElement("textarea");
      notes.setAttribute("class", "viz-drill-notes");
      notes.value = annotationStore.get(fileNode.path);
      notes.addEventListener("input", function () {
        annotationStore.set(fileNode.path, notes.value);
      });
      panelEl.appendChild(notes);

      panelEl.hidden = false;
    };
  }

  function wireDrillPanelClose(panelEl, drillState) {
    document.addEventListener("keydown", function (evt) {
      if (evt.key === "Escape" && !panelEl.hidden) {
        drillState.node = null;
        panelEl.hidden = true;
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
    VIEW_SWITCH_OPTIONS.forEach(function (option) {
      var button = document.createElement("button");
      button.type = "button";
      button.id = option.id;
      button.setAttribute("class", "viz-btn viz-view-switch");
      button.textContent = option.label;
      button.addEventListener("click", function () {
        onSelect(option.name);
      });
      wrapper.appendChild(button);
      buttons[option.name] = button;
    });
    container.appendChild(wrapper);

    return {
      setActive: function (name) {
        VIEW_SWITCH_OPTIONS.forEach(function (option) {
          var isActive = option.name === name;
          buttons[option.name].setAttribute("aria-pressed", isActive ? "true" : "false");
        });
      }
    };
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

    var annotationStore = makeAnnotationStore(scene.repo_nwo);

    var elements = {
      storageWarning: document.getElementById(IDS.storageWarning),
      controls: document.getElementById(IDS.controls),
      legend: document.getElementById(IDS.legend),
      root: document.getElementById(IDS.root),
      drillPanel: document.getElementById(IDS.drillPanel)
    };

    if (!annotationStore.available) {
      elements.storageWarning.textContent =
        "Notes are not being saved (localStorage is unavailable on this origin). " +
        "Use “Copy notes as JSON” before closing this tab.";
      elements.storageWarning.hidden = false;
    }

    // Storage was available at page-load but a later write failed (e.g. quota
    // exceeded) — reveal the same banner so the reviewer sees that notes have
    // stopped persisting mid-session.
    annotationStore.onFallback(function () {
      elements.storageWarning.textContent =
        "Notes have stopped being saved (a localStorage write failed — the " +
        "browser storage quota may be full). " +
        "Use “Copy notes as JSON” before closing this tab.";
      elements.storageWarning.hidden = false;
    });

    var mountedViews = [];

    // Shared drill-panel state: `node` holds the currently-open file node (or
    // null when closed) so a weight change can refresh the open breakdown.
    var drillState = { node: null };
    var openDrill = makeOpenDrill(
      elements.drillPanel, annotationStore, weights, unavailableAxes, drillState
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
        openDrill: openDrill
      };
    }

    var controls = buildControls(elements.controls, weights, unavailableAxes, onWeightChange);
    wireThemeToggle(controls.themeButton, function () {
      document.dispatchEvent && dispatchThemeChanged();
    });
    wireCopyNotesButton(controls.copyButton, controls.copyStatus, annotationStore);
    buildLegend(elements.legend);
    wireDrillPanelClose(elements.drillPanel, drillState);

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
        return;
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
    }

    var viewMountIds = { treemap: IDS.treemapView, ledger: IDS.ledgerView };
    var viewSwitcher = buildViewSwitcher(elements.controls, function (name) {
      mountView(name, viewMountIds[name]);
      viewSwitcher.setActive(name);
    });

    mountView("treemap", IDS.treemapView);
    viewSwitcher.setActive("treemap");
  }

  main();
})();
