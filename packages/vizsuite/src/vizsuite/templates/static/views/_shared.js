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
// `options.onDoubleActivate()` (optional; used by the treemap's directory
// fill-screen focus, spec §6.1): a second qualifying pointer activation
// arriving within
// `DOUBLE_ACTIVATE_WINDOW_MS` of the first fires this instead of a second
// `onActivate()` — mirroring the reacted-to prototype's own debounce-the-
// single-click-then-cancel-on-a-second-click treatment (docs/plans/
// visualization-suite/prototype/variant_A.js), so a double-click's single-
// click side effect never also fires. Every existing call site (the ledger
// row, the sonar ring mark) omits this option, so `onActivate()` keeps firing
// synchronously for them — this branch is purely additive. Keyboard
// activation (Enter/Space) never participates in this debounce: it always
// fires `onActivate()` immediately, since a keyboard user reaches the
// double-activate behavior via its own dedicated control instead.
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
(function () {
  "use strict";

  window.vizShared = window.vizShared || {};

  // A second qualifying pointer activation within this window of the first
  // counts as a double-activation rather than two singles — the same ~300ms
  // ballpark most desktop OSes use for double-click detection.
  var DOUBLE_ACTIVATE_WINDOW_MS = 320;

  function wireClickVsDragActivation(el, options) {
    var onActivate = options.onActivate;
    var onDoubleActivate = options.onDoubleActivate;
    var isExempt = options.isExempt;
    var startX = 0;
    var startY = 0;
    var moved = false;
    // `armed` gates activation on a pointerdown that actually started on this
    // element, rejecting a stray pointerup from a gesture begun elsewhere
    // (whose `moved` would still read false).
    var armed = false;
    // Pending single-activate timer (only ever set when `onDoubleActivate`
    // is given — every other call site's `onActivate` still fires inline,
    // with zero added latency, exactly as before this option existed).
    var pendingActivateTimer = null;

    function firePointerActivate() {
      if (!onDoubleActivate) {
        onActivate();
        return;
      }
      if (pendingActivateTimer !== null) {
        clearTimeout(pendingActivateTimer);
        pendingActivateTimer = null;
        onDoubleActivate();
        return;
      }
      pendingActivateTimer = setTimeout(function () {
        pendingActivateTimer = null;
        // The element may have been removed from the DOM (e.g. a resize or
        // collapse re-render pruned this tile) between the first click and
        // this timer firing — never act on a stale, detached element.
        if (el.isConnected === false) {
          return;
        }
        onActivate();
      }, DOUBLE_ACTIVATE_WINDOW_MS);
    }

    el.addEventListener("pointerdown", function (evt) {
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
      firePointerActivate();
    });
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
      // A pointer click may have scheduled a deferred onActivate() just
      // before this keypress — fire once, not twice: the keyboard activation
      // supersedes the pending pointer one.
      if (pendingActivateTimer !== null) {
        clearTimeout(pendingActivateTimer);
        pendingActivateTimer = null;
      }
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
