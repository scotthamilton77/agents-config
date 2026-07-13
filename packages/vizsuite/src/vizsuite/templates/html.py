"""Self-contained HTML rendering: script-safe scene embedding + minimal template.

Two invariants, both load-bearing from PR #1 (spec §4.6):

1. **Embedding boundary** — the inlined scene JSON is emitted via
   `scene_to_script_json`: a repo-derived string containing ``</script>`` must
   never terminate the `<script>` element (stored XSS upstream of all DOM-level
   escaping). Achieved by escaping ``<``, ``>``, ``&`` to their ``\\uXXXX``
   forms, which `JSON.parse` reads back losslessly.
2. **DOM binding** — every repo-derived string (file paths today, stories later)
   is bound into the DOM via `textContent` (d3's ``.text``), never
   `innerHTML` interpolation, so there is no stored-self-XSS window between this
   slice and slice 5.

The template inlines the vendored d3 and the scene CSS from package data so the
artifact is a single portable file.
"""

from __future__ import annotations

import importlib.resources
import json
import re

from vizsuite.envelope import JsonValue
from vizsuite.scene.model import Scene, scene_to_json

# Placeholder tokens are substituted in a single pass (see `_fill_template`), so
# injected content is never re-scanned: an asset or a repo-derived path that
# happens to contain a token string is inserted verbatim, never reinterpreted as
# a placeholder slot.
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>viz — PR artifact</title>
<style>
/*__VIZ_CSS__*/
</style>
</head>
<body>
<h1 id="viz-title"></h1>
<div id="viz-root"></div>
<footer id="viz-footer">
This artifact embeds data extracted from the repository.
Generated at <span id="viz-generated-at"></span>.
</footer>
<script>
/*__VIZ_D3__*/
</script>
<script id="viz-scene" type="application/json">__VIZ_SCENE_JSON__</script>
<script>
(function () {
  "use strict";
  var scene = JSON.parse(document.getElementById("viz-scene").textContent);
  document.getElementById("viz-title").textContent = "viz — PR #" + scene.pr_number;
  document.getElementById("viz-generated-at").textContent = scene.generated_at;
  d3.select("#viz-root")
    .selectAll("div.viz-file")
    .data(scene.files)
    .join("div")
    .attr("class", "viz-file")
    .text(function (d) { return d.path; });
})();
</script>
</body>
</html>
"""


def scene_to_script_json(scene: JsonValue) -> str:
    """Serialize the scene for inlining inside `<script>` (plan §3.5.3).

    A repo-derived string containing ``</script>`` must never terminate the
    element (stored XSS via the embedding path, upstream of all DOM-level
    escaping — spec §4.6). `<`, `>`, `&` only ever occur inside JSON string
    values, so replacing them with their `\\uXXXX` escapes yields still-valid
    JSON that `JSON.parse` reads back losslessly.
    """
    raw = json.dumps(scene, sort_keys=True, separators=(",", ":"))
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(scene: Scene) -> str:
    """Render a `Scene` to one self-contained HTML string.

    Pure function of the `Scene`: the same scene always renders byte-identically
    (spec test item 6), so `generated_at` is the only field that varies run to
    run and it lives inside the scene.
    """
    scene_json = scene_to_script_json(scene_to_json(scene))
    css = _read_static("scene.css")
    d3 = _read_static("d3.min.js")
    return _fill_template(css=css, d3=d3, scene_json=scene_json)


def _fill_template(*, css: str, d3: str, scene_json: str) -> str:
    """Fill the template placeholders in a single ``re.sub`` pass.

    One pass (never chained ``str.replace``) makes substitution
    order-independent: each placeholder in the template is replaced exactly once
    and injected content is never re-scanned, so an asset or a repo-derived path
    that happens to contain a token string is inserted verbatim rather than
    reinterpreted as a slot (spec §4.6). The scene JSON is the only repo-derived
    input, so this makes the embedding safe by construction, not by ordering.
    """
    replacements = {
        "/*__VIZ_CSS__*/": css,
        "/*__VIZ_D3__*/": d3,
        "__VIZ_SCENE_JSON__": scene_json,
    }
    pattern = re.compile("|".join(re.escape(token) for token in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)], _TEMPLATE)


def _read_static(name: str) -> str:
    """Read a vendored asset from package data (works installed and from source)."""
    resource = importlib.resources.files("vizsuite").joinpath(f"templates/static/{name}")
    return resource.read_text(encoding="utf-8")
