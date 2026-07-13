"""Minimal scene assembler (slice 1): estate nodes → `Scene`, no heat.

Slice 3 merges the complexity/consequence axes and slice 5 folds in provenance,
fingerprints, and the schema gate. Here the assembler is a pure function of its
inputs — the clock is injected as `generated_at` rather than read from a module
global, so assembly is deterministic and testable.
"""

from __future__ import annotations

from vizsuite.scene.model import FileNode, Scene


def assemble(
    estate_map: dict[str, str],
    *,
    pr_number: int,
    generated_at: str,
    generator: str,
    schema_version: str = "1",
) -> Scene:
    """Assemble the estate `{path: blob_sha}` into a `Scene`.

    `generated_at` is the caller-supplied build stamp (the only non-deterministic
    input); every other field is derived from the estate, so two assemblies of
    the same estate differ only in that stamp (spec test item 6).
    """
    files = tuple(
        FileNode(path=path, checksum=blob_sha) for path, blob_sha in sorted(estate_map.items())
    )
    return Scene(
        schema_version=schema_version,
        generated_at=generated_at,
        generator=generator,
        pr_number=pr_number,
        files=files,
    )
