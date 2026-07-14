"""Scene assembler: estate nodes + fingerprints + Tier-2/3 facts → `Scene`.

Slice 3 merged the complexity/consequence heat axes at the `viz pr` verb level
(threading them into scene node attributes is `.2.2`); slice 5 hardens the
envelope itself: every assembly stamps a `Fingerprints` manifest (the PR's
`base_oid`/`head_oid` plus the estate's own blob-SHA checksums — one pinned
hash domain, §0.1) and runs the **schema gate**: any attached Tier-2/3 `Fact`
missing provenance or citations is refused with a loud typed error before a
`Scene` is ever constructed — no silent default, no dropped fact. The
assembler stays a pure function of its inputs — the clock is injected as
`generated_at` rather than read from a module global, so assembly is
deterministic and testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from vizsuite.envelope import ErrorCode, VizError
from vizsuite.scene.model import (
    AttributeDescriptor,
    Fact,
    FileNode,
    Fingerprints,
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
) -> Scene:
    """Assemble the estate `{path: blob_sha}` plus fingerprints/facts into a `Scene`.

    `generated_at` is the caller-supplied build stamp (the only non-deterministic
    input); every other field is derived from the estate/OIDs/facts, so two
    assemblies of the same inputs differ only in that stamp (spec test item 6)
    and carry an identical `fingerprints.files` manifest (spec test item: the
    per-file checksum is the estate blob SHA, deterministic across assemblies).
    Raises `VizError(SCHEMA_INVALID)` before constructing anything if any `fact`
    fails the schema gate.
    """
    _validate_facts(facts)

    files = tuple(
        FileNode(path=path, checksum=blob_sha) for path, blob_sha in sorted(estate_map.items())
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
    )
