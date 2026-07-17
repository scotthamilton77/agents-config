"""HTML embedding boundary: the script-safe serializer and the inlined scene.

Spec test item 7 (complete): a scene field containing ``</script>`` must
survive inline embedding without terminating the `<script>` element, and
hostile strings in paths, Tier-2 fact notes ("stories"), and other
repo/agent-derived content render inert — never interpolated into HTML, only
ever escaped JSON text.
"""

from __future__ import annotations

import json

from vizsuite.scene.model import (
    Fact,
    FileNode,
    Fingerprints,
    Provenance,
    ProvenanceKind,
    RenderConfig,
    Scene,
    StaleGraph,
)
from vizsuite.templates.html import _fill_template, render_html, scene_to_script_json

_SCENE_OPEN = '<script id="viz-scene" type="application/json">'

_HOSTILE_STRINGS = (
    "</textarea><script>alert(1)</script>",
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
)


def _scene(
    *files: FileNode,
    facts: tuple[Fact, ...] = (),
    render_config: RenderConfig | None = None,
) -> Scene:
    return Scene(
        schema_version="1",
        generated_at="2020-01-01T00:00:00+00:00",
        generator="vizsuite/0.1.0",
        pr_number=1,
        files=tuple(files),
        fingerprints=Fingerprints(base_oid="base000", head_oid="head111"),
        facts=facts,
        render_config=render_config
        if render_config is not None
        else RenderConfig(default_weights={}),
    )


def _encoded_fact(fact_id: str, note: str) -> Fact:
    return Fact(
        id=fact_id,
        note=note,
        provenance=Provenance(kind=ProvenanceKind.ENCODED, citations=("evidence",)),
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
    out = _fill_template(
        css=hostile_css,
        d3="/* d3 */",
        app="/* app */",
        views="/* views */",
        scene_json='{"pr_number":7}',
    )

    # the css's literal token survived (was not substituted as the scene slot)...
    assert "content: '__VIZ_SCENE_JSON__';" in out
    # ...and the real scene json was injected exactly once, at the template slot.
    assert out.count('{"pr_number":7}') == 1


def test_render_inlines_vendored_d3_scene_css_app_and_treemap_bundles():
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert html.startswith("<!DOCTYPE html>")
    assert "d3js.org v7.9.0" in html  # vendored d3 inlined
    assert ".viz-treemap {" in html  # scene css inlined (treemap styles)
    # the app + treemap JS bundles are inlined (item 6: bundle markers) —
    # each source file's own identifying banner comment proves it landed.
    assert "vizsuite/app.js" in html
    assert "vizsuite/views/treemap.js" in html
    # the treemap view's mount id is a stable string constant (spec §4.6
    # verification hook), present in the inlined app.js source even though the
    # element itself is created at runtime, not by the Python template.
    assert "viz-view-treemap" in html
    # estate paths are present (inside the inlined JSON scene)
    assert "src/app.py" in html
    assert "README.md" in html
    # the treemap binds each repo-derived file/dir name through d3's `.text`
    # (which sets textContent), never `innerHTML` interpolation — the binding
    # invariant. (`innerHTML` appears inside vendored d3 itself; the invariant
    # is about our own code, so we assert the binding call, not a global
    # substring absence.)
    assert ".text(function (d) { return d.data.name; })" in html


def test_render_inlines_treemap_interaction_playwright_hooks():
    # The treemap's reset-view control and focus breadcrumb strip are stable
    # playwright hooks (spec §4.6) — JS source, so inlined regardless of scene
    # content, same convention as every other conditionally-rendered feature's
    # id (viz-drill-sonar-toggle, viz-constellation-toggle, ...).
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert "viz-treemap-reset" in html
    assert "viz-treemap-breadcrumb" in html


def test_render_inlines_ledger_view_bundle_and_playwright_hooks():
    # Slice 3 (spec §6.1 attention ledger): the ledger view module is its own
    # file under templates/static/views/, picked up by the same dynamic glob
    # that already inlines treemap.js (item 6: bundle markers) — no change to
    # `_read_views_bundle` needed, so this pins the *contract*, not the glob.
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert "vizsuite/views/ledger.js" in html
    # Stable ids used as playwright verification hooks (spec §4.6): the
    # ledger's list mount, the separated/mixed toggle, and the treemap↔ledger
    # view switcher app.js now renders into the control row.
    assert "viz-ledger-list" in html
    assert "viz-ledger-mode-toggle" in html
    assert "viz-view-switch-treemap" in html
    assert "viz-view-switch-ledger" in html


def test_render_inlines_sonar_view_bundle_and_playwright_hooks():
    # Slice 5 (spec §6.1 file sonar, as a drill — not a top-level view): the
    # sonar module is its own file under templates/static/views/, picked up
    # by the same dynamic glob that already inlines treemap.js and ledger.js
    # (item 6: bundle markers) — no change to `_read_views_bundle` needed, so
    # this pins the *contract*, not the glob.
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert "vizsuite/views/sonar.js" in html
    # Stable ids used as playwright verification hooks (spec §4.6): the
    # drill panel's "open sonar" toggle + mount app.js now wires in, and the
    # sonar module's own rings/unavailable states and ring-mark class.
    assert "viz-drill-sonar-toggle" in html
    assert "viz-drill-sonar-mount" in html
    assert "viz-sonar-rings" in html
    assert "viz-sonar-unavailable" in html
    assert "viz-sonar-node" in html


def test_render_inlines_constellation_view_bundle_and_playwright_hooks():
    # Slice 6 (spec §6.1 dependency constellation, evaluation-gated per §11):
    # the constellation module is its own file under templates/static/views/,
    # picked up by the same dynamic glob that already inlines treemap.js,
    # ledger.js, and sonar.js (item 6: bundle markers) — no change to
    # `_read_views_bundle` needed, so this pins the *contract*, not the glob.
    # It ships inlined but never auto-mounted: app.js registers it behind a
    # default-off experimental toggle (spec §6.1 "gated concretely").
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    assert "vizsuite/views/constellation.js" in html
    # Stable ids used as playwright verification hooks (spec §4.6): the
    # default-off experimental toggle, the view-switch button it registers on
    # demand, the view's own mount id (a stable string constant present in
    # the inlined app.js source even though the element itself is created at
    # runtime), and the module's node-mark + unavailable-state classes.
    assert "viz-constellation-toggle" in html
    assert "viz-view-switch-constellation" in html
    assert "viz-view-constellation" in html
    assert "viz-constellation-node" in html
    assert "viz-constellation-unavailable" in html
    # The toggle's stable, action-naming label (spec §4.5 toggle convention:
    # the accessible name never flips with state) is the exact wording the
    # spec's "gated concretely" section names verbatim.
    assert "Show dependency constellation (experimental)" in html


def test_render_inlines_f3_drawer_meter_tooltip_and_axis_bar_hooks():
    # Fidelity F3 (drawer + content fidelity, spec §4.5): the drill drawer's
    # stage-shrink class, the shared per-axis meter row/mini-bar building
    # blocks, the hoisted diff-link class, and the hover score-card tooltip
    # element are all JS/CSS source — inlined regardless of scene content,
    # same convention as every other stable id/class (viz-drill-sonar-toggle,
    # viz-treemap-reset, ...).
    html = render_html(
        _scene(
            FileNode(path="src/app.py", checksum="aaa"),
            FileNode(path="README.md", checksum="bbb"),
        )
    )

    # Drawer conversion: the stage-shrink class app.js toggles on #viz-root.
    assert "viz-drill-open" in html
    # Per-axis meter rows (drill drawer + hover score card) and the ledger's
    # compact mini-bars — the shared building blocks in views/_shared.js.
    assert "viz-meter-row" in html
    assert "viz-meter-mini" in html
    # The per-axis color tokens those two share (scene.css).
    assert "--viz-axis-complexity" in html
    assert "--viz-axis-load-bearing" in html
    assert "--viz-axis-consequence" in html
    # The diff link, hoisted out of views/ledger.js into views/_shared.js so
    # the drawer can reuse it too.
    assert "viz-diff-link" in html
    assert "vizsuite/views/_shared.js" in html
    # PR diff stats chips in the drawer.
    assert "viz-drill-stats" in html
    assert "viz-drill-stat" in html
    # The shared hover score-card tooltip.
    assert "viz-tooltip" in html
    # The ledger's compact per-axis mini-bars wrapper.
    assert "viz-ledger-axis-bars" in html


def test_render_inlines_f4_drill_story_hooks():
    # Fidelity F4 (Tier-2 drill-story channel, spec §6.2): the story section's
    # stable hooks are JS/CSS source — inlined regardless of scene content,
    # same convention as every other conditionally-rendered feature's hook
    # (viz-drill-sonar-toggle, viz-stale-graph-badge, ...).
    html = render_html(_scene(FileNode(path="src/app.py", checksum="aaa")))

    assert "viz-drill-story" in html
    assert "viz-drill-story-headline" in html
    assert "viz-drill-story-why" in html
    assert "viz-drill-story-check" in html
    # "Why it's hot" / "What to check" section headings.
    assert "Why it's hot" in html
    assert "What to check" in html


def test_stale_graph_badge_hook_is_inlined_and_scene_data_is_conditional():
    # F1 (spec §6.2 labeled-stale opt-in): the badge's stable playwright hook
    # (spec §4.6) is JS source, so it is inlined regardless of scene content —
    # same convention as every other conditionally-rendered feature's id
    # (viz-drill-sonar-toggle, viz-constellation-toggle, ...). What actually
    # varies with the scene is the embedded `render_config.stale_graph` data
    # the badge logic reads at runtime to decide whether to render.
    stale_scene = _scene(
        FileNode(path="src/app.py", checksum="aaa"),
        render_config=RenderConfig(
            default_weights={"complexity": 0.4, "load_bearing": 0.35, "consequence": 0.25},
            stale_graph=StaleGraph(built_at_commit="deadbeef123", commits_behind=4),
        ),
    )
    html = render_html(stale_scene)

    assert "viz-stale-graph-badge" in html

    scene_data = json.loads(_inlined_scene_block(html))
    assert scene_data["render_config"]["stale_graph"] == {
        "built_at_commit": "deadbeef123",
        "commits_behind": 4,
    }

    fresh_html = render_html(_scene(FileNode(path="src/app.py", checksum="aaa")))
    fresh_scene_data = json.loads(_inlined_scene_block(fresh_html))
    assert "stale_graph" not in fresh_scene_data["render_config"]


def test_hostile_strings_in_paths_and_fact_notes_render_inert():
    # Item 7 (complete): hostile strings in *paths* (a repeat of the slice-1
    # embedding case, now exercised alongside the new channel) and in a
    # Tier-2 fact's *note* (the "story"/annotation narrative payload) must
    # both render inert — never interpolated as HTML, only ever escaped JSON
    # text that round-trips losslessly through `JSON.parse`.
    for hostile in _HOSTILE_STRINGS:
        html = render_html(
            _scene(
                FileNode(path=f"src/{hostile}.py", checksum="deadbeef"),
                facts=(_encoded_fact("f1", hostile),),
            )
        )

        assert hostile not in html
        block = _inlined_scene_block(html)
        scene_data = json.loads(block)
        assert scene_data["files"][0]["path"] == f"src/{hostile}.py"
        assert scene_data["facts"][0]["note"] == hostile
