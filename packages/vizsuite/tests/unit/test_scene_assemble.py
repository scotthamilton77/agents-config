"""Scene assembly: fingerprint manifest + full-envelope shape (plan slice 5).

`assemble()` stamps a `Fingerprints` manifest whose `files` mirror the
estate's own git-blob-SHA checksums (one pinned hash domain, §0.1 — not a
second `git hash-object`/`hashlib` recomputation) plus the reconciled PR's
`base_oid`/`head_oid`. The manifest — like every other field derived from the
estate/OIDs — is a pure function of its inputs, so it is byte-identical across
two assemblies of the same head. The envelope also carries `descriptors`,
`recommendations`, and `events` — always empty for V1, but present in the
serialized shape so a later slice (.2.2/.2.3) never breaks the contract.
"""

from __future__ import annotations

from vizsuite.scene.assemble import assemble
from vizsuite.scene.model import (
    AttributeDescriptor,
    Edge,
    FileStory,
    RenderConfig,
    StaleGraph,
    scene_to_json,
)

_ESTATE = {"src/a.py": "sha_a", "src/b.py": "sha_b"}


def test_fingerprints_carry_oids_and_mirror_estate_blob_shas():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    assert scene.fingerprints.base_oid == "base000"
    assert scene.fingerprints.head_oid == "head111"
    # the per-file checksum IS the estate blob SHA — one pinned hash domain,
    # not a second recomputation.
    assert scene.fingerprints.files == _ESTATE


def test_fingerprints_are_identical_across_two_assemblies_of_the_same_head():
    scene_a = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )
    scene_b = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2099-12-31T23:59:59+00:00",  # the stamp varies...
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    # ...but the fingerprint manifest does not: it is a pure function of the
    # estate and the reconciled OIDs, never the build clock.
    assert scene_a.fingerprints == scene_b.fingerprints


def test_scene_json_carries_the_full_envelope_shape():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    payload = scene_to_json(scene)

    fingerprints = payload["fingerprints"]
    assert isinstance(fingerprints, dict)
    assert fingerprints["base_oid"] == "base000"
    assert fingerprints["head_oid"] == "head111"
    assert fingerprints["files"] == _ESTATE
    # recommendations/events are always empty for V1 (spec §4.4); descriptors
    # has no populated attribute to describe until .2.2 wires heat axes in.
    assert payload["descriptors"] == []
    assert payload["recommendations"] == []
    assert payload["events"] == []
    assert payload["facts"] == []


def test_populated_descriptor_serializes_with_its_name_unit_and_direction():
    descriptor = AttributeDescriptor(name="complexity", unit="0-1", direction="higher_is_hotter")
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        descriptors=[descriptor],
    )

    payload = scene_to_json(scene)

    assert payload["descriptors"] == [
        {"name": "complexity", "unit": "0-1", "direction": "higher_is_hotter"}
    ]


def test_attributes_thread_into_matching_file_nodes_by_path():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        attributes={
            "src/a.py": {
                "complexity": 0.2,
                "load_bearing": 0.5,
                "consequence": 0.0,
                "heat": 0.3,
                "in_pr": True,
            }
        },
    )

    by_path = {node.path: node.attributes for node in scene.files}
    assert by_path["src/a.py"] == {
        "complexity": 0.2,
        "load_bearing": 0.5,
        "consequence": 0.0,
        "heat": 0.3,
        "in_pr": True,
    }
    # a file with no entry in the attribute map keeps the pre-.2.2 empty shape.
    assert by_path["src/b.py"] == {}


def test_story_thread_into_matching_file_node_and_round_trips_through_json():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        stories={
            "src/a.py": FileStory(
                change_summary="Tightened the retry backoff window.",
                why_hot=("Touches the shared retry loop.", "No test coverage on the new branch."),
                what_to_check=("Confirm the backoff cap still matches the SLA doc.",),
            )
        },
    )

    by_path = {node.path: node.story for node in scene.files}
    assert by_path["src/a.py"] == FileStory(
        change_summary="Tightened the retry backoff window.",
        why_hot=("Touches the shared retry loop.", "No test coverage on the new branch."),
        what_to_check=("Confirm the backoff cap still matches the SLA doc.",),
    )
    # a file with no entry in the story map keeps story=None (never fabricated).
    assert by_path["src/b.py"] is None

    payload = scene_to_json(scene)
    files_by_path = {f["path"]: f for f in payload["files"]}
    assert files_by_path["src/a.py"]["story"] == {
        "change_summary": "Tightened the retry backoff window.",
        "why_hot": ["Touches the shared retry loop.", "No test coverage on the new branch."],
        "what_to_check": ["Confirm the backoff cap still matches the SLA doc."],
    }
    # absent story = absent key, never a null/empty placeholder.
    assert "story" not in files_by_path["src/b.py"]


def test_render_config_and_repo_nwo_thread_into_the_serialized_envelope():
    render_config = RenderConfig(
        default_weights={"complexity": 0.4, "load_bearing": 0.35, "consequence": 0.25},
        unavailable_axes=("load_bearing",),
    )
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        render_config=render_config,
        repo_nwo="octocat/hello-world",
    )

    assert scene.render_config == render_config
    assert scene.repo_nwo == "octocat/hello-world"

    payload = scene_to_json(scene)
    assert payload["render_config"] == {
        "default_weights": {"complexity": 0.4, "load_bearing": 0.35, "consequence": 0.25},
        "unavailable_axes": ["load_bearing"],
    }
    assert payload["repo_nwo"] == "octocat/hello-world"


def test_edges_default_to_empty_when_graphify_is_unavailable():
    # Fail-soft: an unavailable centrality axis carries empty edges (see
    # test_extract_centrality.py), and a Scene assembled without any edges
    # input defaults to the same empty tuple — never crash, never stale edges.
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    assert scene.edges == ()
    assert scene_to_json(scene)["edges"] == []


def test_edges_thread_through_assemble_and_serialize_sorted_and_deterministically():
    # Deliberately reverse-ordered input to prove scene_to_json sorts, not the caller.
    edges = [
        Edge(source="b.py", target="a.py", kind="dependency"),
        Edge(source="a.py", target="b.py", kind="dependency"),
    ]
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        edges=edges,
    )

    assert scene.edges == tuple(edges)
    payload = scene_to_json(scene)
    assert payload["edges"] == [
        {"source": "a.py", "target": "b.py", "kind": "dependency"},
        {"source": "b.py", "target": "a.py", "kind": "dependency"},
    ]

    # Byte-stable across two assemblies of the same edges — only the stamp varies.
    scene_b = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2099-12-31T23:59:59+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        edges=edges,
    )
    assert scene_to_json(scene_b)["edges"] == payload["edges"]


def test_render_config_stale_graph_serializes_only_when_present():
    render_config = RenderConfig(
        default_weights={"complexity": 0.4, "load_bearing": 0.35, "consequence": 0.25},
        stale_graph=StaleGraph(built_at_commit="deadbeef123", commits_behind=4),
    )
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        render_config=render_config,
    )

    payload = scene_to_json(scene)
    render_config_json = payload["render_config"]
    assert isinstance(render_config_json, dict)
    assert render_config_json["stale_graph"] == {
        "built_at_commit": "deadbeef123",
        "commits_behind": 4,
    }


def test_render_config_stale_graph_commits_behind_none_serializes_as_null():
    render_config = RenderConfig(
        default_weights={},
        stale_graph=StaleGraph(built_at_commit="deadbeef123", commits_behind=None),
    )
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        render_config=render_config,
    )

    payload = scene_to_json(scene)
    render_config_json = payload["render_config"]
    assert isinstance(render_config_json, dict)
    stale_graph_json = render_config_json["stale_graph"]
    assert isinstance(stale_graph_json, dict)
    assert stale_graph_json["commits_behind"] is None


def test_render_config_stale_graph_key_absent_when_fresh():
    # Fresh (no `stale_graph`) render configs never carry the key at all — not
    # even as a null — so a consumer can key its badge purely off presence.
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
        render_config=RenderConfig(default_weights={}),
    )

    payload = scene_to_json(scene)
    render_config_json = payload["render_config"]
    assert isinstance(render_config_json, dict)
    assert "stale_graph" not in render_config_json


def test_render_config_and_repo_nwo_default_when_omitted():
    scene = assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="g",
        base_oid="base000",
        head_oid="head111",
    )

    payload = scene_to_json(scene)
    assert payload["render_config"] == {"default_weights": {}, "unavailable_axes": []}
    assert payload["repo_nwo"] == ""
