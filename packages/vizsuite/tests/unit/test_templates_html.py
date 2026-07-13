"""HTML embedding boundary: the script-safe serializer and the inlined scene.

Spec test item 7 (embedding half): a scene field containing ``</script>`` must
survive inline embedding without terminating the `<script>` element.
"""

from __future__ import annotations

import json

from vizsuite.scene.model import FileNode, Scene
from vizsuite.templates.html import _fill_template, render_html, scene_to_script_json

_SCENE_OPEN = '<script id="viz-scene" type="application/json">'


def _scene(*files: FileNode) -> Scene:
    return Scene(
        schema_version="1",
        generated_at="2020-01-01T00:00:00+00:00",
        generator="vizsuite/0.1.0",
        pr_number=1,
        files=tuple(files),
    )


def _inlined_scene_block(html: str) -> str:
    start = html.index(_SCENE_OPEN) + len(_SCENE_OPEN)
    end = html.index("</script>", start)
    return html[start:end]


def test_scene_to_script_json_escapes_angle_brackets_and_amp():
    serialized = scene_to_script_json({"x": "</script>&<b>"})

    assert "</script>" not in serialized
    assert "\\u003c/script\\u003e" in serialized
    assert "\\u0026" in serialized
    # The escapes are valid JSON, so the value round-trips losslessly.
    assert json.loads(serialized) == {"x": "</script>&<b>"}


def test_scene_field_with_script_close_tag_survives_inline():
    hostile = "a/</script><script>alert(1)</script>.py"
    html = render_html(_scene(FileNode(path=hostile, checksum="deadbeef")))

    # The hostile string never appears verbatim (it is escaped everywhere).
    assert hostile not in html

    # The inlined scene block ends at *our* closing tag, after the escaped
    # payload — proof the data did not terminate the element early — and the
    # payload round-trips through JSON.parse back to the original string.
    block = _inlined_scene_block(html)
    assert "\\u003c/script\\u003e" in block
    scene_data = json.loads(block)
    assert [node["path"] for node in scene_data["files"]] == [hostile]


def test_fill_template_substitution_is_order_independent():
    # An asset (or repo-derived path) that happens to contain a *later*
    # placeholder token must be inserted verbatim, never reinterpreted as a
    # slot. A chained str.replace() would clobber it on the scene-json pass;
    # the single-pass re.sub() cannot, because injected content is never
    # re-scanned.
    hostile_css = "body::after { content: '__VIZ_SCENE_JSON__'; }"
    out = _fill_template(css=hostile_css, d3="/* d3 */", scene_json='{"pr_number":7}')

    # the css's literal token survived (was not substituted as the scene slot)...
    assert "content: '__VIZ_SCENE_JSON__';" in out
    # ...and the real scene json was injected exactly once, at the template slot.
    assert out.count('{"pr_number":7}') == 1


def test_render_inlines_vendored_d3_and_scene_css_and_estate_paths():
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert html.startswith("<!DOCTYPE html>")
    assert "d3js.org v7.9.0" in html  # vendored d3 inlined
    assert ".viz-file" in html  # scene css inlined
    # estate paths are present (inside the inlined JSON scene)
    assert "src/app.py" in html
    assert "README.md" in html
    # the bootstrap binds each repo-derived path through d3's `.text` (which sets
    # textContent), never `innerHTML` interpolation — the binding invariant.
    # (`innerHTML` appears inside vendored d3 itself; the invariant is about our
    # own code, so we assert the binding call, not a global substring absence.)
    assert ".text(function (d) { return d.path; })" in html
