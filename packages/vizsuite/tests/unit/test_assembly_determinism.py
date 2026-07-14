"""Scene assembly + render determinism (spec test item 6).

Same scene + template → byte-identical HTML modulo the `generated_at` stamp.
`generated_at` is injected into `assemble` (never read from a hidden clock), so
the whole pipeline is a pure function of estate + stamp.
"""

from __future__ import annotations

from vizsuite.extract.centrality import CentralityAxis
from vizsuite.scene import heat
from vizsuite.scene.assemble import assemble
from vizsuite.scene.model import RenderConfig
from vizsuite.templates.html import render_html

# Deliberately out of sorted order to prove assemble sorts.
_ESTATE = {"src/b.py": "sha_b", "src/a.py": "sha_a", "README.md": "sha_r"}


def test_assemble_maps_estate_to_sorted_file_nodes():
    scene = assemble(
        _ESTATE,
        pr_number=7,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="vizsuite/0.1.0",
        base_oid="base000",
        head_oid="head111",
    )

    assert scene.pr_number == 7
    assert scene.generator == "vizsuite/0.1.0"
    assert scene.schema_version == "1"
    assert [node.path for node in scene.files] == ["README.md", "src/a.py", "src/b.py"]
    assert {node.path: node.checksum for node in scene.files} == _ESTATE
    assert all(node.attributes == {} for node in scene.files)


def test_render_is_deterministic_for_a_fixed_scene():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    assert render_html(scene) == render_html(scene)


def test_same_scene_same_html_modulo_stamp():
    stamp_a = "2020-01-01T00:00:00+00:00"
    stamp_b = "2099-12-31T23:59:59+00:00"
    html_a = render_html(
        assemble(
            _ESTATE,
            pr_number=1,
            generated_at=stamp_a,
            generator="g",
            base_oid="base000",
            head_oid="head111",
        )
    )
    html_b = render_html(
        assemble(
            _ESTATE,
            pr_number=1,
            generated_at=stamp_b,
            generator="g",
            base_oid="base000",
            head_oid="head111",
        )
    )

    # The stamp genuinely varies between runs...
    assert html_a != html_b
    # ...and it is the ONLY thing that varies: replacing it makes them identical.
    assert html_a.replace(stamp_a, "<STAMP>") == html_b.replace(stamp_b, "<STAMP>")


def test_heat_populated_scene_is_still_deterministic_modulo_stamp():
    # .2.2: attributes/render_config/repo_nwo are new inputs to assemble() — the
    # determinism guarantee must hold with them populated, not just the bare
    # pre-.2.2 shape the tests above cover.
    complexity_scores = {"src/a.py": 0.2, "src/b.py": 0.8, "README.md": 0.0}
    consequence_scores = {"src/a.py": 0.0, "src/b.py": 1.0, "README.md": 0.0}
    centrality = CentralityAxis.unavailable("graphify-out absent")
    heat_model = heat.combine(
        _ESTATE, complexity_scores, consequence_scores, centrality, pr_files={"src/a.py"}
    )
    render_config = RenderConfig(
        default_weights=heat_model.default_weights, unavailable_axes=heat_model.unavailable_axes
    )

    def _build(stamp: str) -> str:
        scene = assemble(
            _ESTATE,
            pr_number=1,
            generated_at=stamp,
            generator="g",
            base_oid="base000",
            head_oid="head111",
            attributes=heat_model.attributes,
            descriptors=heat_model.descriptors,
            render_config=render_config,
            repo_nwo="octocat/hello-world",
        )
        return render_html(scene)

    stamp_a = "2020-01-01T00:00:00+00:00"
    stamp_b = "2099-12-31T23:59:59+00:00"
    html_a = _build(stamp_a)
    html_b = _build(stamp_b)

    assert html_a != html_b
    assert html_a.replace(stamp_a, "<STAMP>") == html_b.replace(stamp_b, "<STAMP>")
