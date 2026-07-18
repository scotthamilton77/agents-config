// vizsuite/views/_shared.js — cross-view helpers shared via `window.vizShared`.
//
// Each view module (and app.js) is its own IIFE, so none of them share
// lexical scope with one another even though html.py concatenates them into
// one `<script>` element (spec §4.6's views bundle) — `window` is the only
// channel available, the same pattern `window.vizViews` already uses as the
// view registry. This file's name sorts first among `templates/static/views/
// *.js` (leading underscore), so it always finishes defining `window.vizShared`
// before any other view file's own top-level code runs; every current call
// site only *uses* it from inside a `render()` body anyway, which app.js
// invokes after the whole bundle (views + app.js itself) has finished
// loading, so load order here is a belt-and-braces guarantee, not the only
// thing making this safe.
//
// wireClickVsDragActivation: the click-vs-drag-vs-keyboard activation
// scaffold shared by the treemap tile, the ledger row, and the sonar ring
// mark (spec §4.2's ~4px movement threshold + Enter/Space keyboard
// operability, read at pointerup/keydown time — never a captured snapshot).
// `options.onActivate()` fires on a qualifying click or Enter/Space;
// `options.isExempt(evt)`, if given, opts an event out of activation (the
// ledger row's diff-link guard) — omitted, every candidate event activates.
//
// Activation is always synchronous — there is deliberately NO deferred
// (debounced double-click) path in this helper. An earlier revision deferred
// `onActivate()` behind a timer to make room for a double-click gesture, and
// the pending timer leaked activations through every gesture edge
// (keyboard, nested controls, drag-after-click, pointercancel). Fill-screen
// focus is an explicit per-tile control in the treemap instead (spec §6.1).
//
// isDependencyGraphUnavailable: the shared "is the dependency graph
// unavailable?" predicate for the graph-shaped views (constellation, file
// sonar). The answer is NOT "scene.edges is empty" — an *available*
// load-bearing (centrality) axis over a repo with no cross-file imports
// legitimately yields zero edges, and those views must still render (isolated
// PR nodes / a center-only neighborhood) rather than claim unavailability.
// The one true signal is the Python heat model listing "load_bearing" in
// render_config.unavailable_axes (scene/heat.py), which happens exactly when
// the centrality axis fail-softs (graphify absent/stale/torn).
//
// makeLocalStorageStore: the feature-detected localStorage probe/fallback
// pattern (spec §4.5) — a real write always lands somewhere (an in-memory map
// when storage is unavailable or a runtime write fails, e.g. quota exceeded),
// and `onFallback` fires the first time a *runtime* write falls back, so a
// caller can surface a non-persistence warning that boot-time feature
// detection alone would miss (storage can be available at page-load and fail
// later). Originally duplicated between app.js's annotation store and
// treemap.js's collapse/focus-state store (fidelity F3) — both now rebase
// on this one factory.
//
// buildMeterRow/buildMiniBar/axisColorVar: the per-axis colored bar building
// blocks shared by the drill drawer, the hover score card, and the ledger's
// compact mini-bars (spec §4.5 "mirroring scene colors") — one color token
// per axis (`--viz-axis-*`, scene.css), used consistently everywhere an axis
// value is rendered as a bar.
//
// buildDiffLink/showTooltip/hideTooltip/moveTooltip/buildScoreCard: the
// per-file diff-link builder (hoisted out of views/ledger.js, spec §6.1 G3)
// and the hover score-card tooltip (spec §4.5), both reused by the treemap
// and the ledger.
(function () {
  "use strict";

  window.vizShared = window.vizShared || {};

  // The three §6.2 input axes only (the combined heat is derived
  // separately and is NOT included here), in the same order/names as
  // `vizsuite.scene.heat._INPUT_AXES` (mirrored in app.js's own HEAT_AXES,
  // which now reads this shared constant instead of duplicating it).
  var HEAT_AXES = ["complexity", "load_bearing", "consequence"];
  window.vizShared.HEAT_AXES = HEAT_AXES;

  function makeLocalStorageStore(prefix) {
    // A NUL-suffixed probe key so the availability check never reads or
    // clobbers a real key under this prefix (no valid repo path, and no
    // fixed non-path key this module mints, ever contains a NUL byte).
    var probeKey = prefix + "\u0000probe";
    var available = false;
    try {
      window.localStorage.setItem(probeKey, "1");
      window.localStorage.removeItem(probeKey);
      available = true;
    } catch (err) {
      available = false;
    }
    // The in-memory overlay holds two kinds of entry localStorage never got:
    // fallback writes (a runtime setItem failed, e.g. quota) and removal
    // tombstones (a runtime removeItem failed while the value still sits in
    // localStorage). TOMBSTONE is a unique sentinel distinguishing "removed
    // after a runtime fallback" from "never written" — getItem/keys consult
    // the overlay first so writes and removals read back consistently once a
    // runtime failure has diverged the overlay from localStorage.
    var memory = Object.create(null);
    var TOMBSTONE = {};
    var fallbackHandler = null;
    var fallbackNotified = false;

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

    function getItem(key) {
      // Consult the overlay first: a fallback write or a removal tombstone
      // recorded after a runtime failure must win over the (stale or still-
      // present) localStorage entry, so values written after a fallback stay
      // readable and tombstoned removals stay removed.
      if (Object.prototype.hasOwnProperty.call(memory, key)) {
        return memory[key] === TOMBSTONE ? null : memory[key];
      }
      if (available) {
        return window.localStorage.getItem(key);
      }
      return null;
    }

    function setItem(key, value) {
      if (available) {
        try {
          window.localStorage.setItem(key, value);
          // localStorage is authoritative for this key again; drop any stale
          // overlay entry (a prior fallback write or tombstone) so it can't
          // shadow the fresh value.
          delete memory[key];
          return;
        } catch (err) {
          // Fall through to the in-memory overlay (e.g. quota exceeded) and
          // surface the non-persistence warning via the caller's handler.
          notifyFallback();
        }
      }
      memory[key] = value;
    }

    function removeItem(key) {
      if (available) {
        try {
          window.localStorage.removeItem(key);
          delete memory[key];
          return;
        } catch (err) {
          // The value is still in localStorage; record a tombstone so the
          // removal is reflected once getItem/keys fall back to the overlay.
          notifyFallback();
          memory[key] = TOMBSTONE;
          return;
        }
      }
      delete memory[key];
    }

    function keys() {
      var out = [];
      var seen = Object.create(null);
      if (available) {
        for (var i = 0; i < window.localStorage.length; i++) {
          var k = window.localStorage.key(i);
          if (k && k.indexOf(prefix) === 0 && memory[k] !== TOMBSTONE) {
            out.push(k);
            seen[k] = true;
          }
        }
      }
      // Merge overlay keys (fallback writes localStorage never got), deduped
      // against the localStorage pass and excluding tombstoned removals.
      for (var mk in memory) {
        if (
          Object.prototype.hasOwnProperty.call(memory, mk) &&
          memory[mk] !== TOMBSTONE &&
          !seen[mk]
        ) {
          out.push(mk);
        }
      }
      return out;
    }

    return {
      available: available,
      getItem: getItem,
      setItem: setItem,
      removeItem: removeItem,
      keys: keys,
      onFallback: onFallback
    };
  }

  window.vizShared.makeLocalStorageStore = makeLocalStorageStore;

  // ---- Per-axis color tokens (spec §4.5 "mirroring scene colors") — one
  // `--viz-axis-*` custom property per axis (scene.css), plus a neutral
  // token for the combined-heat row; unknown axes fall back to `--viz-fg`
  // rather than rendering an unstyled bar. ----
  var AXIS_COLOR_VARS = {
    complexity: "var(--viz-axis-complexity)",
    load_bearing: "var(--viz-axis-load-bearing)",
    consequence: "var(--viz-axis-consequence)",
    heat: "var(--viz-axis-heat)"
  };

  function axisColorVar(axis) {
    return AXIS_COLOR_VARS[axis] || "var(--viz-fg)";
  }

  window.vizShared.axisColorVar = axisColorVar;

  // A labeled row: axis name, a filled bar (0-1 → 0-100%), and the numeric
  // value — the drill drawer's per-axis breakdown and the hover score card's
  // shared building block.
  function buildMeterRow(axis, label, value) {
    var row = document.createElement("div");
    row.setAttribute("class", "viz-meter-row");
    row.setAttribute("data-axis", axis);

    var labelEl = document.createElement("span");
    labelEl.setAttribute("class", "viz-meter-label");
    labelEl.textContent = label;
    row.appendChild(labelEl);

    var barEl = document.createElement("span");
    barEl.setAttribute("class", "viz-meter-bar");
    var fillEl = document.createElement("span");
    fillEl.setAttribute("class", "viz-meter-fill");
    var pct = Math.max(0, Math.min(1, value || 0)) * 100;
    fillEl.style.width = pct + "%";
    fillEl.style.backgroundColor = axisColorVar(axis);
    barEl.appendChild(fillEl);
    row.appendChild(barEl);

    var valueEl = document.createElement("span");
    valueEl.setAttribute("class", "viz-meter-value");
    valueEl.textContent = (value || 0).toFixed(2);
    row.appendChild(valueEl);

    return row;
  }

  window.vizShared.buildMeterRow = buildMeterRow;

  // A bare fill-only bar, no label/value text — the ledger row's compact
  // per-axis mini-bars (spec §4.5), same color tokens as buildMeterRow.
  function buildMiniBar(axis, value) {
    var barEl = document.createElement("span");
    barEl.setAttribute("class", "viz-meter-mini");
    barEl.setAttribute("data-axis", axis);
    barEl.setAttribute("aria-hidden", "true");
    var fillEl = document.createElement("span");
    fillEl.setAttribute("class", "viz-meter-mini-fill");
    var pct = Math.max(0, Math.min(1, value || 0)) * 100;
    fillEl.style.width = pct + "%";
    fillEl.style.backgroundColor = axisColorVar(axis);
    barEl.appendChild(fillEl);
    return barEl;
  }

  window.vizShared.buildMiniBar = buildMiniBar;

  // ---- Per-file diff link (spec §6.1 G3), hoisted out of views/ledger.js so
  // the drill drawer can reuse it too (fidelity F3). GitHub's per-file anchor
  // on a PR's "Files changed" tab is `pull/<n>/files#diff-<sha256hex(path)>`
  // (current, undocumented scheme). Computing that hash needs SubtleCrypto,
  // which only exists in a secure context (https, or http://localhost) —
  // never on a `file://` origin, which is exactly how these artifacts are
  // normally opened (spec §4.1). Rather than vendor a hand-rolled SHA-256
  // implementation for an anchor-only affordance, this degrades: a PR-file
  // caller gets the bare `.../pull/<n>/files` link synchronously (correct,
  // just not scrolled to the right file), then the `href` upgrades in place
  // to the anchored form if-and-when a digest resolves. `repo_nwo` absent/
  // empty (the PR verb couldn't resolve the GitHub remote), or a non-PR
  // file, never fabricates a URL — returns `null` instead. ----
  function sha256HexOrNull(text) {
    var subtle = window.crypto && window.crypto.subtle;
    if (!subtle || typeof subtle.digest !== "function" || typeof TextEncoder === "undefined") {
      return null;
    }
    var bytes = new TextEncoder().encode(text);
    return subtle.digest("SHA-256", bytes).then(function (buffer) {
      var view = new Uint8Array(buffer);
      var hex = "";
      for (var i = 0; i < view.length; i++) {
        var byteHex = view[i].toString(16);
        hex += byteHex.length === 1 ? "0" + byteHex : byteHex;
      }
      return hex;
    });
  }

  function buildDiffLink(scene, path, inPr) {
    if (!inPr || !scene.repo_nwo) {
      return null; // no PR diff for a context file; never fabricate a URL without repo_nwo
    }
    var base = "https://github.com/" + scene.repo_nwo + "/pull/" + scene.pr_number + "/files";
    var anchor = document.createElement("a");
    anchor.setAttribute("class", "viz-diff-link");
    anchor.href = base;
    anchor.target = "_blank";
    anchor.rel = "noopener";
    anchor.setAttribute("aria-label", "View diff for " + path + " on GitHub");
    anchor.textContent = "Diff";
    // The anchor is its own activation target — never let its own events
    // also trigger the host's row/tile-open handler (see
    // wireClickVsDragActivation callers). Stopping the pointer events too
    // (not just click/keydown) closes the gap a `.closest("a")` exemption
    // alone leaves when `evt.target` has no `.closest` (a non-Element target).
    function stopPropagation(evt) {
      evt.stopPropagation();
    }
    ["click", "keydown", "pointerdown", "pointerup"].forEach(function (type) {
      anchor.addEventListener(type, stopPropagation);
    });

    var digest = sha256HexOrNull(path);
    if (digest) {
      digest.then(
        function (hex) {
          anchor.href = base + "#diff-" + hex;
        },
        function () {
          // Fail soft: if hashing rejects, keep the unanchored /files link
          // rather than surfacing an unhandled promise rejection.
        }
      );
    }
    return anchor;
  }

  window.vizShared.buildDiffLink = buildDiffLink;

  // ---- Hover score card (spec §4.5): a single shared tooltip element,
  // mounted once and reused across every view/re-render — pointer-events:
  // none, follows the cursor, flips near viewport edges (prototype anatomy:
  // #tooltip). Content is rebuilt on every `showTooltip` call from
  // repo-derived data bound via textContent/`.value` only (never innerHTML),
  // matching the templating layer's DOM-bind invariant (spec §4.6). ----
  var tooltipEl = null;

  function ensureTooltipEl() {
    if (!tooltipEl) {
      tooltipEl = document.createElement("div");
      tooltipEl.id = "viz-tooltip";
      tooltipEl.setAttribute("class", "viz-tooltip");
      tooltipEl.hidden = true;
      document.body.appendChild(tooltipEl);
    }
    return tooltipEl;
  }

  function positionTooltip(evt) {
    var el = tooltipEl;
    if (!el) {
      return;
    }
    var pad = 14;
    var w = el.offsetWidth;
    var h = el.offsetHeight;
    var x = evt.clientX + pad;
    var y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) {
      x = evt.clientX - w - pad;
    }
    if (y + h > window.innerHeight - 8) {
      y = evt.clientY - h - pad;
    }
    el.style.left = x + "px";
    el.style.top = y + "px";
  }

  function showTooltip(evt, buildContent) {
    var el = ensureTooltipEl();
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
    buildContent(el);
    el.hidden = false;
    positionTooltip(evt);
  }

  function moveTooltip(evt) {
    if (tooltipEl && !tooltipEl.hidden) {
      positionTooltip(evt);
    }
  }

  function hideTooltip() {
    if (tooltipEl) {
      tooltipEl.hidden = true;
    }
  }

  window.vizShared.showTooltip = showTooltip;
  window.vizShared.moveTooltip = moveTooltip;
  window.vizShared.hideTooltip = hideTooltip;

  // The tooltip/drawer-shared content builder: path, one meter row per heat
  // axis, the combined heat, and — for a PR file whose attributes carry
  // churn (spec §4.5 PR diff stats) — a trailing +adds/−dels line. `attributes`
  // is a file's raw scene attributes; `heatValue` is the already-computed
  // combined heat for this file (the caller's own `computeHeat`/annotated
  // node value — never recomputed here, so this always matches the tile/row
  // color it is describing).
  function buildScoreCard(container, path, attributes, heatValue) {
    var pathEl = document.createElement("div");
    pathEl.setAttribute("class", "viz-tooltip-path");
    pathEl.textContent = path;
    container.appendChild(pathEl);

    HEAT_AXES.forEach(function (axis) {
      var value = typeof attributes[axis] === "number" ? attributes[axis] : 0;
      container.appendChild(buildMeterRow(axis, axis, value));
    });
    container.appendChild(buildMeterRow("heat", "heat", heatValue));

    if (attributes.in_pr && typeof attributes.added === "number") {
      var churnEl = document.createElement("div");
      churnEl.setAttribute("class", "viz-tooltip-churn");
      var deleted = typeof attributes.deleted === "number" ? attributes.deleted : 0;
      churnEl.textContent = "+" + attributes.added + "/−" + deleted;
      container.appendChild(churnEl);
    }
  }

  window.vizShared.buildScoreCard = buildScoreCard;

  function wireClickVsDragActivation(el, options) {
    var onActivate = options.onActivate;
    var isExempt = options.isExempt;
    // Opt-in double-click suppression (default off, so every other caller —
    // treemap tile, ledger row, sonar — keeps activating synchronously). When
    // provided, a pointer click's activation is DEFERRED by a window (ms) and
    // cancelled if a `dblclick` lands inside it, so a double-click gesture
    // (constellation's un-pin) does not also fire the primary activation. The
    // option is either a fixed number of ms, or a function evaluated at
    // pointerup that returns the window for THIS gesture (0/false = activate
    // instantly) — letting a caller defer only when the double-click gesture is
    // actually meaningful for the target. Only the pointer path defers —
    // keyboard activation (Enter/Space) has no double-press gesture and must
    // stay instant.
    var dblclickWindowMs = options.dblclickWindowMs;
    var pendingTimers = [];
    // Cancel every deferred activation still waiting on its window. Called when
    // a `dblclick` lands (the gesture is a double-click, so the primary action
    // must NOT fire) and on each new pointerdown (a second press — a drag or a
    // second click — must not let the prior press's stale activation fire
    // mid-gesture).
    function clearPendingActivations() {
      pendingTimers.forEach(clearTimeout);
      pendingTimers.length = 0;
    }
    var startX = 0;
    var startY = 0;
    var moved = false;
    // `armed` gates activation on a pointerdown that actually started on this
    // element, rejecting a stray pointerup from a gesture begun elsewhere
    // (whose `moved` would still read false).
    var armed = false;

    el.addEventListener("pointerdown", function (evt) {
      // A new press starts here; drop any activation still deferred from the
      // previous click so a drag-after-click (or a slow second click) never
      // fires the stale primary action mid-gesture.
      clearPendingActivations();
      startX = evt.clientX;
      startY = evt.clientY;
      moved = false;
      armed = true;
      // Capture the pointer so every pointermove/pointerup for this gesture
      // retargets to `el` even after the pointer leaves its bounds. Without
      // capture, a press near the edge followed by a drag off `el` stops
      // tracking movement (leaving `moved=false`) and never delivers the
      // gesture's pointerup, so `armed` stays true and a later stray pointerup
      // over `el` would wrongly activate. Capture releases implicitly on
      // pointerup/pointercancel, so no releasePointerCapture call is needed.
      if (el.setPointerCapture) {
        el.setPointerCapture(evt.pointerId);
      }
    });
    el.addEventListener("pointermove", function (evt) {
      if (!armed) {
        return;
      }
      if (Math.abs(evt.clientX - startX) > 4 || Math.abs(evt.clientY - startY) > 4) {
        moved = true;
      }
    });
    el.addEventListener("pointerup", function (evt) {
      if (!armed) {
        return;
      }
      armed = false;
      if (moved) {
        return;
      }
      if (isExempt && isExempt(evt)) {
        return;
      }
      // Resolve the window for THIS gesture: a function is evaluated now (at
      // pointerup) so the caller can decide per-gesture; a number is fixed.
      var windowMs =
        typeof dblclickWindowMs === "function" ? dblclickWindowMs(evt) : dblclickWindowMs;
      if (!windowMs) {
        onActivate();
        return;
      }
      // Defer: hold activation open for the double-click window; a `dblclick`
      // (fired after the second pointerup) clears every pending timer, so a
      // double-click gesture activates zero times instead of twice.
      var timer = setTimeout(function () {
        var idx = pendingTimers.indexOf(timer);
        if (idx !== -1) {
          pendingTimers.splice(idx, 1);
        }
        onActivate();
      }, windowMs);
      pendingTimers.push(timer);
    });
    if (dblclickWindowMs) {
      el.addEventListener("dblclick", clearPendingActivations);
    }
    // A cancelled gesture (browser-initiated, e.g. scroll takeover) must not
    // leave the helper armed for a later stray pointerup.
    el.addEventListener("pointercancel", function () {
      armed = false;
    });
    // Enter/Space activate like a click (a11y); "Spacebar" is the legacy
    // IE/Edge key value. Space must preventDefault or the page scrolls.
    el.addEventListener("keydown", function (evt) {
      if (evt.key !== "Enter" && evt.key !== " " && evt.key !== "Spacebar") {
        return;
      }
      if (isExempt && isExempt(evt)) {
        return;
      }
      evt.preventDefault();
      onActivate();
    });
  }

  window.vizShared.wireClickVsDragActivation = wireClickVsDragActivation;

  // "load_bearing" is the centrality axis's key (mirrored in app.js's
  // HEAT_AXES and heat.py's _INPUT_AXES); its presence in unavailable_axes is
  // the fail-soft marker. render_config.unavailable_axes is always present in
  // the envelope (assemble.py), but the read is null-safe to match the views'
  // defensive style.
  function isDependencyGraphUnavailable(scene) {
    var unavailableAxes =
      (scene.render_config && scene.render_config.unavailable_axes) || [];
    return unavailableAxes.indexOf("load_bearing") !== -1;
  }

  window.vizShared.isDependencyGraphUnavailable = isDependencyGraphUnavailable;
})();
