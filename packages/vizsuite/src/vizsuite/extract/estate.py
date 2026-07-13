"""Estate scope extractor — the canonical file set (plan §3.5.2, spec §6.2).

The one file set every axis and the assembler consume: files present in a
revision's tree, minus curated excludes, mapped to their git blob SHA. Reads the
commit *tree object* (`git ls-tree -r <rev>`), never the mutable index, so the
estate is a property of the snapshot, not the checkout.
"""

from __future__ import annotations

from vizsuite.adapters.git.runner import GitRunner

ESTATE_EXCLUDES = ("graphify-out/", ".beads/", ".viz/", "archive/")  # dir prefixes
ESTATE_EXCLUDE_SUFFIXES = ("uv.lock", "package-lock.json", ".min.js")  # lock/generated


def _in_estate(path: str) -> bool:
    return not (
        any(path.startswith(prefix) for prefix in ESTATE_EXCLUDES)
        or any(path.endswith(suffix) for suffix in ESTATE_EXCLUDE_SUFFIXES)
    )


def estate(git: GitRunner, rev: str) -> dict[str, str]:
    """The canonical file set at an immutable revision → `{path: blob_sha}`.

    Blob rows only (submodule/tree rows are skipped), curated excludes dropped.
    Slice 1 passes ``rev="HEAD"`` (skeleton, pre-gh); slice 2+ passes the
    resolved head OID.
    """
    return {
        path: blob_sha
        for _mode, obj_type, blob_sha, path in git.ls_tree(rev)
        if obj_type == "blob" and _in_estate(path)
    }
