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
(function () {
  "use strict";

  window.vizShared = window.vizShared || {};

  function wireClickVsDragActivation(el, options) {
    var onActivate = options.onActivate;
    var isExempt = options.isExempt;
    var startX = 0;
    var startY = 0;
    var moved = false;
    // `armed` gates activation on a pointerdown that actually started on this
    // element, rejecting a stray pointerup from a gesture begun elsewhere
    // (whose `moved` would still read false).
    var armed = false;

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
      onActivate();
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
      onActivate();
    });
  }

  window.vizShared.wireClickVsDragActivation = wireClickVsDragActivation;
})();
