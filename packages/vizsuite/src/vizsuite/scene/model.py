"""Typed scene dataclasses — the inlined-JSON contract every view will read.

Slice-1 minimum (spec §4.4, plan §3.2): a shared envelope (`schema_version`,
`generated_at`, `generator`) plus a per-suite payload of estate file nodes
`{path, checksum, attributes:{}}`, where `checksum` is the git blob SHA. Slice 5
hardens this into the full §4.4 envelope (fingerprints, descriptors, per-fact
provenance, recommendations, reserved events). No `Any` at the boundary:
`scene_to_json` parses the typed model down to a `dict[str, JsonValue]` once, and
serialization is deterministic (files sorted by path) so the same estate always
produces byte-identical scene JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vizsuite.envelope import JsonValue


@dataclass(frozen=True)
class FileNode:
    path: str
    checksum: str  # git blob SHA at the snapshot (spec §0.1 / §3.5.1)
    attributes: dict[str, JsonValue] = field(default_factory=dict)  # heat axes land in .2.2/§6.2


@dataclass(frozen=True)
class Scene:
    schema_version: str
    generated_at: str  # the one non-deterministic field; isolated for the determinism gate
    generator: str
    pr_number: int
    files: tuple[FileNode, ...]


def scene_to_json(scene: Scene) -> dict[str, JsonValue]:
    """Serialize a `Scene` to a plain JSON-shaped mapping, files sorted by path.

    Sorting here (not at the call site) makes the scene payload a deterministic
    function of the estate, so `templates.html.render_html` is byte-stable modulo
    the `generated_at` stamp (spec test item 6).
    """
    files_json: list[JsonValue] = [
        {"path": node.path, "checksum": node.checksum, "attributes": node.attributes}
        for node in sorted(scene.files, key=lambda node: node.path)
    ]
    return {
        "schema_version": scene.schema_version,
        "generated_at": scene.generated_at,
        "generator": scene.generator,
        "pr_number": scene.pr_number,
        "files": files_json,
    }
