// vizsuite/views/ledger.js — the attention-ledger view module (spec §6.1),
// obeying the §4.2 view-module interface: render(container, scene, state) →
// handle, with handle.destroy(). `handle.reencode(state)` re-sorts and
// rebuilds the row list in place — ranking is weight-dependent, so a slider
// change can reorder every row. That reorder is *not* the "never re-run
// layout" case §4.2 protects: that guards a settled *spatial* layout (the
// treemap's tile x/y/width/height), not a flat list's own paint order,
// which the spec explicitly allows to reflow on re-rank.
//
// Diff-link decision (spec §6.1 "attention ledger" / G3): GitHub's per-file
// anchor on a PR's "Files changed" tab is `pull/<n>/files#diff-<sha256hex
// (path)>` (current, undocumented scheme). Computing that hash needs
// SubtleCrypto, which only exists in a secure context (https, or
// http://localhost) — never on a `file://` origin, which is exactly how
// these artifacts are normally opened (spec §4.1: double-click, offline,
// detached from any session). Rather than vendor a hand-rolled SHA-256
// implementation for an anchor-only affordance, this module degrades: every
// PR-file row gets the bare `.../pull/<n>/files` link synchronously (correct,
// just not scrolled to the right file), then upgrades `href` in place to the
// anchored form if-and-when a digest resolves. A `file://` artifact keeps the
// still-useful bare-tab link forever; a served/https copy (this repo's
// playwright checks, or a shared internal copy) gets the precise per-file
// anchor a tick later. `repo_nwo` absent/empty (the PR verb couldn't resolve
// the GitHub remote) never fabricates a URL — the file name renders unlinked
// instead, same as any context (non-PR) file, which has no diff to link to.
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

  // Returns a Promise<string> (lowercase hex sha256) when SubtleCrypto is
  // available in this context, or `null` synchronously when it is not, so
  // the caller never blocks first paint on the digest.
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
    if (!row.inPr || !scene.repo_nwo) {
      return holder; // no PR diff for a context file; never fabricate a URL without repo_nwo
    }
    var base = "https://github.com/" + scene.repo_nwo + "/pull/" + scene.pr_number + "/files";
    var anchor = document.createElement("a");
    anchor.setAttribute("class", "viz-ledger-diff-link");
    anchor.href = base;
    anchor.target = "_blank";
    anchor.rel = "noopener";
    anchor.setAttribute("aria-label", "View diff for " + row.file.path + " on GitHub");
    anchor.textContent = "Diff";
    // The anchor is its own activation target — never let its click/keydown
    // also trigger the row's drill-open handler (see wireRowActivation).
    anchor.addEventListener("click", function (evt) {
      evt.stopPropagation();
    });
    anchor.addEventListener("keydown", function (evt) {
      evt.stopPropagation();
    });
    holder.appendChild(anchor);

    var digest = sha256HexOrNull(row.file.path);
    if (digest) {
      digest.then(function (hex) {
        anchor.href = base + "#diff-" + hex;
      });
    }
    return holder;
  }

  // Click-vs-drag threshold (~4px, spec §4.2), mirroring the treemap tile
  // pattern; reads the live bound row at pointerup/keydown rather than a
  // captured snapshot, matching the same anti-staleness contract.
  function wireRowActivation(el, onActivate) {
    var startX = 0;
    var startY = 0;
    var moved = false;
    function fromLink(evt) {
      return Boolean(evt.target.closest && evt.target.closest("a"));
    }
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
    el.addEventListener("pointerup", function (evt) {
      if (moved || fromLink(evt)) {
        return;
      }
      onActivate();
    });
    // Enter/Space activate like a click (a11y); "Spacebar" is the legacy
    // IE/Edge key value. A link inside the row handles its own activation.
    el.addEventListener("keydown", function (evt) {
      if (evt.key !== "Enter" && evt.key !== " " && evt.key !== "Spacebar") {
        return;
      }
      if (fromLink(evt)) {
        return;
      }
      evt.preventDefault();
      onActivate();
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
    el.setAttribute(
      "aria-label",
      row.file.path + (row.inPr ? " (changed in this PR)" : "") + ", heat " + row.heat.toFixed(2)
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

    var heatEl = document.createElement("span");
    heatEl.setAttribute("class", "viz-ledger-heat");
    heatEl.textContent = row.heat.toFixed(2);
    el.appendChild(heatEl);

    el.appendChild(buildDiffLinkHolder(scene, row));

    wireRowActivation(el, function () {
      // The shape openDrill expects (spec: `fileNode.path` +
      // `fileNode.orig.file.attributes`) — the same shape the treemap's
      // pruned leaf nodes carry; built fresh here rather than duplicating
      // any tree-building machinery the ledger doesn't need.
      openDrill({ path: row.file.path, orig: { file: row.file } });
    });

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
