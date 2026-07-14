"""Typed scene dataclasses — the inlined-JSON contract every view will read.

Slice 1 shipped the minimum: a shared envelope (`schema_version`,
`generated_at`, `generator`) plus a per-suite payload of estate file nodes
`{path, checksum, attributes:{}}`, where `checksum` is the git blob SHA. Slice 5
hardens this into the full §4.4 envelope: `fingerprints` (the input-hash
manifest the scene was built from), `descriptors` (self-describing attribute
metadata), per-fact `Provenance` on two independent axes (source/verdict and
freshness), `recommendations`/`events` reserved empty for V1/V3. No `Any` at
the boundary: `scene_to_json` parses the typed model down to a
`dict[str, JsonValue]` once, and serialization is deterministic (files and
facts sorted by key) so the same inputs always produce byte-identical scene
JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from vizsuite.envelope import JsonValue


@dataclass(frozen=True)
class FileNode:
    path: str
    checksum: str  # git blob SHA at the snapshot (spec §0.1 / §3.5.1)
    attributes: dict[str, JsonValue] = field(default_factory=dict)  # heat axes land in .2.2/§6.2


class ProvenanceKind(StrEnum):
    """The source/verdict axis of per-fact provenance (spec §4.4)."""

    ENCODED = "encoded"
    INFERRED = "inferred"
    ACCEPTED = "accepted"


class Freshness(StrEnum):
    """The staleness axis of per-fact provenance (spec §4.4).

    Independent of `ProvenanceKind`: an accepted fact can be doubted without
    losing its recorded acceptance (spec test item 8).
    """

    FRESH = "fresh"
    DOUBTED = "doubted"


@dataclass(frozen=True)
class Provenance:
    """Per-fact provenance on two independent axes, plus mandatory citations.

    `citations` are the inputs (bead ids, passages, graph regions) the fact
    was derived from (spec §5.2: "input citations are mandatory at inference
    time"). Empty citations fail the assembler's schema gate exactly like a
    missing `Provenance` does — both are the same violation class.
    """

    kind: ProvenanceKind
    freshness: Freshness = Freshness.FRESH
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fact:
    """A Tier-2/Tier-3-touched fact attached to the scene (spec §4.4).

    `provenance` is `None` for an incoming fact `assemble()` has not yet
    validated — a `Scene` never carries a `Fact` with `provenance=None` or
    empty citations; the schema gate rejects it loudly instead of defaulting
    or silently dropping it (spec test item 8). `note` is the fact's narrative
    payload (e.g. a drill story) and is repo/agent-derived, hostile-input-safe
    only via the templating/escaping boundary (spec test item 7) — never
    sanitized here.
    """

    id: str
    note: str
    provenance: Provenance | None = None


@dataclass(frozen=True)
class AttributeDescriptor:
    """Self-describing metadata for one scene attribute (spec §4.4)."""

    name: str
    unit: str
    direction: str


@dataclass(frozen=True)
class Fingerprints:
    """The input-hash manifest the scene was built from (spec §4.4/§5.4).

    `files` mirrors each `FileNode.checksum` (the estate's git blob SHAs) as
    the manifest's own record — one pinned hash domain (§0.1/§3.5.1), not a
    second recomputation. `base_oid`/`head_oid` identify the reconciled PR
    snapshot; `tool_versions` is reserved for extractor tool versions (none
    are wired as of slice 5 — no scene consumer needs them yet).
    """

    base_oid: str
    head_oid: str
    tool_versions: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scene:
    schema_version: str
    generated_at: str  # the one non-deterministic field; isolated for the determinism gate
    generator: str
    pr_number: int
    files: tuple[FileNode, ...]
    fingerprints: Fingerprints
    descriptors: tuple[AttributeDescriptor, ...] = ()  # no scene attribute needs one until .2.2
    facts: tuple[Fact, ...] = ()  # Tier-2/3 facts; empty until .2.2/.2.3 have a producer
    recommendations: tuple[JsonValue, ...] = ()  # always empty for V1 (spec §4.4)
    events: tuple[JsonValue, ...] = ()  # reserved for V3 (spec §4.4/§8); always empty here


def _provenance_to_json(provenance: Provenance) -> dict[str, JsonValue]:
    return {
        "kind": str(provenance.kind),
        "freshness": str(provenance.freshness),
        "citations": list(provenance.citations),
    }


def _fact_to_json(fact: Fact) -> dict[str, JsonValue]:
    return {
        "id": fact.id,
        "note": fact.note,
        "provenance": _provenance_to_json(fact.provenance) if fact.provenance is not None else None,
    }


def _descriptor_to_json(descriptor: AttributeDescriptor) -> dict[str, JsonValue]:
    return {"name": descriptor.name, "unit": descriptor.unit, "direction": descriptor.direction}


def _fingerprints_to_json(fingerprints: Fingerprints) -> dict[str, JsonValue]:
    return {
        "base_oid": fingerprints.base_oid,
        "head_oid": fingerprints.head_oid,
        "tool_versions": dict(fingerprints.tool_versions),
        "files": dict(fingerprints.files),
    }


def scene_to_json(scene: Scene) -> dict[str, JsonValue]:
    """Serialize a `Scene` to a plain JSON-shaped mapping, files/facts sorted by key.

    Sorting here (not at the call site) makes the scene payload a deterministic
    function of its inputs, so `templates.html.render_html` is byte-stable modulo
    the `generated_at` stamp (spec test item 6).
    """
    files_json: list[JsonValue] = [
        {"path": node.path, "checksum": node.checksum, "attributes": node.attributes}
        for node in sorted(scene.files, key=lambda node: node.path)
    ]
    facts_json: list[JsonValue] = [
        _fact_to_json(fact) for fact in sorted(scene.facts, key=lambda fact: fact.id)
    ]
    descriptors_json: list[JsonValue] = [
        _descriptor_to_json(descriptor) for descriptor in scene.descriptors
    ]
    return {
        "schema_version": scene.schema_version,
        "generated_at": scene.generated_at,
        "generator": scene.generator,
        "pr_number": scene.pr_number,
        "files": files_json,
        "fingerprints": _fingerprints_to_json(scene.fingerprints),
        "descriptors": descriptors_json,
        "facts": facts_json,
        "recommendations": list(scene.recommendations),
        "events": list(scene.events),
    }
