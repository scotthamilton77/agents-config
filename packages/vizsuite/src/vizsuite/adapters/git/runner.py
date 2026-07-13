"""The git subprocess port — the fake's seam.

`GitRunner` is the interface every contract test replaces with
`tests/fakes.ScriptedGitRunner`; `SubprocessGitRunner` is the sole
implementation that actually shells out to real `git`. Slice 1 needs only
`ls_tree`; slice 2 extends this same file with `rev_parse`/`cat_object_exists`/
`rev_list`/`diff_name_only`/`fetch_pr`/`fetch_base`/`churn_for_commits`, and
slice 3 adds `archive_tar`.

`ls_tree` reads the immutable commit *tree object* (`git ls-tree -r <rev>`),
never the mutable index (`git ls-files`), so every consumer sees a property of
the snapshot rather than the operator's checkout state.
"""

from __future__ import annotations

import subprocess
from typing import NamedTuple, Protocol


class LsTreeRow(NamedTuple):
    """One `git ls-tree -r` row: ``<mode> <obj_type> <blob_sha>\\t<path>``.

    A NamedTuple so consumers can unpack positionally
    (``for mode, obj_type, blob_sha, path in git.ls_tree(rev)``) exactly as the
    estate extractor does, while staying fully typed at the boundary.
    """

    mode: str
    obj_type: str
    blob_sha: str
    path: str


class GitRunner(Protocol):
    def ls_tree(self, rev: str) -> list[LsTreeRow]: ...  # pragma: no cover


class SubprocessGitRunner:
    """Drives real `git`. `ls_tree` reads the immutable tree object at `rev`."""

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        completed = subprocess.run(
            ["git", "ls-tree", "-r", rev],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [_parse_ls_tree_line(line) for line in completed.stdout.splitlines() if line]


def _parse_ls_tree_line(line: str) -> LsTreeRow:
    """Parse one `git ls-tree -r` line into an `LsTreeRow`.

    Line shape is ``<mode> SP <obj_type> SP <object> TAB <path>`` — the single
    TAB separates the metadata columns from the path, so a path containing
    spaces stays intact.
    """
    meta, _, path = line.partition("\t")
    mode, obj_type, blob_sha = meta.split()
    return LsTreeRow(mode=mode, obj_type=obj_type, blob_sha=blob_sha, path=path)
