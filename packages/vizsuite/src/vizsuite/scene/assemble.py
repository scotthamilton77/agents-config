"""Scene assembler: estate nodes + fingerprints + Tier-2/3 facts → `Scene`.

Slice 5 hardens the envelope: every assembly stamps a `Fingerprints` manifest
(the PR's `base_oid`/`head_oid` plus the estate's own blob-SHA checksums — one
pinned hash domain, §0.1) and runs the **schema gate**: any attached Tier-2/3
`Fact` missing provenance or citations is refused with a loud typed error
before a `Scene` is ever constructed — no silent default, no dropped fact.
`.2.2` threads the cross-axis heat fusion (`scene.heat.combine`) into each
file's `attributes`, plus `render_config`/`repo_nwo` into the envelope. The
assembler stays a pure function of its inputs — the clock is injected as
`generated_at` rather than read from a module global, so assembly is
deterministic and testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from vizsuite.envelope import ErrorCode, JsonValue, VizError
from vizsuite.scene.model import (
    AttributeDescriptor,
    Edge,
    Fact,
    FileNode,
    FileStory,
    Fingerprints,
    RenderConfig,
    Scene,
)


def _validate_facts(facts: Sequence[Fact]) -> None:
    """Refuse any Tier-2/3 fact lacking provenance or citations (spec test item 8).

    A missing `Provenance` and a present-but-citation-less one are the same
    violation class: both mean the fact cannot be traced to its inputs, so
    neither may reach an assembled `Scene`.
    """
    for fact in facts:
        if fact.provenance is None or not fact.provenance.citations:
            raise VizError(
                ErrorCode.SCHEMA_INVALID,
                "Tier-2/3 fact is missing provenance or citations",
                detail={"fact_id": fact.id},
            )


def assemble(
    estate_map: dict[str, str],
    *,
    pr_number: int,
    generated_at: str,
    generator: str,
    base_oid: str,
    head_oid: str,
    schema_version: str = "1",
    tool_versions: dict[str, str] | None = None,
    facts: Sequence[Fact] = (),
    descriptors: Sequence[AttributeDescriptor] = (),
    attributes: dict[str, dict[str, JsonValue]] | None = None,
    stories: dict[str, FileStory] | None = None,
    render_config: RenderConfig | None = None,
    repo_nwo: str = "",
    edges: Sequence[Edge] = (),
) -> Scene:
    """Assemble the estate `{path: blob_sha}` plus fingerprints/facts into a `Scene`.

    `generated_at` is the caller-supplied build stamp (the only non-deterministic
    input); every other field is derived from the estate/OIDs/facts, so two
    assemblies of the same inputs differ only in that stamp (spec test item 6)
    and carry an identical `fingerprints.files` manifest (spec test item: the
    per-file checksum is the estate blob SHA, deterministic across assemblies).
    Raises `VizError(SCHEMA_INVALID)` before constructing anything if any `fact`
    fails the schema gate. `attributes` (keyed by path, as produced by
    `scene.heat.combine`) attaches each file's heat-axis values to its matching
    `FileNode`; a path with no entry keeps the pre-.2.2 empty attribute map.
    `edges` (typically the centrality axis's two-tier file-dependency pairs,
    tagged `kind="dependency"` and their per-edge `provenance` by the caller)
    threads onto the scene as-is — `scene_to_json` is the sort point, not this
    function.
    `stories` (keyed by path, Tier-2 §6.2 drill-story payloads) attaches to
    each matching `FileNode`; a path with no entry keeps `story=None` — no
    generator exists yet (bead .2.4), so callers only pass this when they
    already have a payload in hand.
    """
    _validate_facts(facts)

    file_attributes = attributes or {}
    file_stories = stories or {}
    files = tuple(
        FileNode(
            path=path,
            checksum=blob_sha,
            attributes=dict(file_attributes.get(path, {})),
            story=file_stories.get(path),
        )
        for path, blob_sha in sorted(estate_map.items())
    )
    fingerprints = Fingerprints(
        base_oid=base_oid,
        head_oid=head_oid,
        tool_versions=dict(tool_versions or {}),
        files=dict(estate_map),
    )
    return Scene(
        schema_version=schema_version,
        generated_at=generated_at,
        generator=generator,
        pr_number=pr_number,
        files=files,
        fingerprints=fingerprints,
        descriptors=tuple(descriptors),
        facts=tuple(facts),
        edges=tuple(edges),
        render_config=render_config
        if render_config is not None
        else RenderConfig(default_weights={}),
        repo_nwo=repo_nwo,
    )
