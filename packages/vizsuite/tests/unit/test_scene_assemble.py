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
from vizsuite.scene.model import AttributeDescriptor, scene_to_json

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
