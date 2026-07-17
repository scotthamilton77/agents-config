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
class FileStory:
    """Tier-2 per-file drill story (spec §6.2 drill-story channel).

    `change_summary` is the one-line accent-colored headline; `why_hot` and
    `what_to_check` are bullet lists rendered under their own headings in the
    drill drawer (prototype anatomy, pr-shape-proto-v3.html `showDrill`).
    Mechanically-catchable content — deleted assertions, lint-class findings —
    is excluded from stories; that rule is enforced at GENERATION time (bead
    .2.4, not yet built), never here. A `FileNode` with no story simply omits
    this field (`None`) — never a story with empty/fabricated bullets.
    """

    change_summary: str
    why_hot: tuple[str, ...] = ()
    what_to_check: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileNode:
    path: str
    checksum: str  # git blob SHA at the snapshot (spec §0.1 / §3.5.1)
    attributes: dict[str, JsonValue] = field(default_factory=dict)  # heat axes (§6.2), via .2.2
    story: FileStory | None = None  # Tier-2 drill story (§6.2), via .2.10; absent = no payload


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
class Edge:
    """A directed top-level file-dependency edge (spec §4.4 typed-edge shape).

    `kind` is the edge-kind vocabulary tag (spec §4.4 encoding-spine); V1's
    only source is the EXTRACTED centrality axis, so `kind` is always
    `"dependency"` here.
    """

    source: str
    target: str
    kind: str


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
class StaleGraph:
    """The visible staleness label for an explicitly-accepted stale graph (spec §6.2).

    Present on `RenderConfig.stale_graph` only when the caller opted into the
    labeled-stale centrality path (`viz pr --allow-stale-graph`) and the
    graphify build actually was stale — never a marker with no stale graph
    behind it. `commits_behind` is `None` when the count itself could not be
    computed (e.g. the build commit is unknown locally) — a soft failure of
    the count, not of the build.
    """

    built_at_commit: str
    commits_behind: int | None


@dataclass(frozen=True)
class RenderConfig:
    """Slider/legend render hints for the cross-axis heat mix (spec §4.5/§6.2).

    `default_weights` seeds each weight slider's starting position;
    `unavailable_axes` disables the slider(s) whose axis could not be computed
    (e.g. a stale/absent graphify build) — never silently reporting a stale
    value as current (spec §6.2). `stale_graph` is set only when the
    load-bearing axis was computed from an explicitly-accepted stale graph
    (spec §6.2's labeled-stale path); a fresh or unavailable axis never
    carries one.
    """

    default_weights: dict[str, float]
    unavailable_axes: tuple[str, ...] = ()
    stale_graph: StaleGraph | None = None


@dataclass(frozen=True)
class Scene:
    schema_version: str
    generated_at: str  # the one non-deterministic field; isolated for the determinism gate
    generator: str
    pr_number: int
    files: tuple[FileNode, ...]
    fingerprints: Fingerprints
    descriptors: tuple[AttributeDescriptor, ...] = ()  # heat axes' metadata, via .2.2 (§4.4)
    facts: tuple[Fact, ...] = ()  # Tier-2/3 facts; empty until .2.3 has a producer
    edges: tuple[Edge, ...] = ()  # EXTRACTED file-dependency edges (§4.4), via .2.2 centrality
    recommendations: tuple[JsonValue, ...] = ()  # always empty for V1 (spec §4.4)
    events: tuple[JsonValue, ...] = ()  # reserved for V3 (spec §4.4/§8); always empty here
    render_config: RenderConfig = field(default_factory=lambda: RenderConfig(default_weights={}))
    repo_nwo: str = ""  # spec §6.2/G3; populated once the PR verb threads it through


def provenance_to_json(provenance: Provenance) -> dict[str, JsonValue]:
    return {
        "kind": str(provenance.kind),
        "freshness": str(provenance.freshness),
        "citations": list(provenance.citations),
    }


def _file_story_to_json(story: FileStory) -> dict[str, JsonValue]:
    return {
        "change_summary": story.change_summary,
        "why_hot": list(story.why_hot),
        "what_to_check": list(story.what_to_check),
    }


def _fact_to_json(fact: Fact) -> dict[str, JsonValue]:
    return {
        "id": fact.id,
        "note": fact.note,
        "provenance": provenance_to_json(fact.provenance) if fact.provenance is not None else None,
    }


def _descriptor_to_json(descriptor: AttributeDescriptor) -> dict[str, JsonValue]:
    return {"name": descriptor.name, "unit": descriptor.unit, "direction": descriptor.direction}


def _edge_to_json(edge: Edge) -> dict[str, JsonValue]:
    return {"source": edge.source, "target": edge.target, "kind": edge.kind}


def _fingerprints_to_json(fingerprints: Fingerprints) -> dict[str, JsonValue]:
    return {
        "base_oid": fingerprints.base_oid,
        "head_oid": fingerprints.head_oid,
        "tool_versions": dict(fingerprints.tool_versions),
        "files": dict(fingerprints.files),
    }


def _render_config_to_json(render_config: RenderConfig) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "default_weights": dict(render_config.default_weights),
        "unavailable_axes": list(render_config.unavailable_axes),
    }
    if render_config.stale_graph is not None:
        payload["stale_graph"] = {
            "built_at_commit": render_config.stale_graph.built_at_commit,
            "commits_behind": render_config.stale_graph.commits_behind,
        }
    return payload


def scene_to_json(scene: Scene) -> dict[str, JsonValue]:
    """Serialize a `Scene` to a plain JSON-shaped mapping, files/facts sorted by key.

    Sorting here (not at the call site) makes the scene payload a deterministic
    function of its inputs, so `templates.html.render_html` is byte-stable modulo
    the `generated_at` stamp (spec test item 6).
    """
    files_json: list[JsonValue] = []
    for node in sorted(scene.files, key=lambda node: node.path):
        file_json: dict[str, JsonValue] = {
            "path": node.path,
            "checksum": node.checksum,
            "attributes": node.attributes,
        }
        if node.story is not None:
            file_json["story"] = _file_story_to_json(node.story)
        files_json.append(file_json)
    facts_json: list[JsonValue] = [
        _fact_to_json(fact) for fact in sorted(scene.facts, key=lambda fact: fact.id)
    ]
    descriptors_json: list[JsonValue] = [
        _descriptor_to_json(descriptor) for descriptor in scene.descriptors
    ]
    edges_json: list[JsonValue] = [
        _edge_to_json(edge)
        for edge in sorted(scene.edges, key=lambda edge: (edge.source, edge.target, edge.kind))
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
        "edges": edges_json,
        "recommendations": list(scene.recommendations),
        "events": list(scene.events),
        "render_config": _render_config_to_json(scene.render_config),
        "repo_nwo": scene.repo_nwo,
    }
