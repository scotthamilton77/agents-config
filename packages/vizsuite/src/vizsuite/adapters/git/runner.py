"""The git subprocess port — the fake's seam.

`GitRunner` is the interface every contract test replaces with
`tests/fakes.ScriptedGitRunner`; `SubprocessGitRunner` is the sole
implementation that actually shells out to real `git`. Slice 1 needs only
`ls_tree`; slice 2 extends this same file with `cat_object_exists`/`rev_list`/
`diff_name_only`/`fetch_pr`/`fetch_base`/`churn_for_commits`, and slice 3 adds
`archive_tar`.

`ls_tree` reads the immutable commit *tree object* (`git ls-tree -r <rev>`),
never the mutable index (`git ls-files`), so every consumer sees a property of
the snapshot rather than the operator's checkout state.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
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


class ModifiedFileRow(NamedTuple):
    """One PyDriller `ModifiedFile` reduced to the fields churn needs.

    `new_path` is ``None`` for a pure delete, `old_path` is ``None`` for a pure
    add; the churn extractor keys by ``new_path or old_path``. Line counts are the
    per-commit deltas that get summed across the PR's commit set.
    """

    new_path: str | None
    old_path: str | None
    added: int
    deleted: int


class GitRunner(Protocol):
    def ls_tree(self, rev: str) -> list[LsTreeRow]: ...  # pragma: no cover
    def cat_object_exists(self, oid: str) -> bool: ...  # pragma: no cover
    def rev_list(self, base: str, head: str) -> list[str]: ...  # pragma: no cover
    def diff_name_only(self, base: str, head: str) -> list[str]: ...  # pragma: no cover
    def archive_tar(self, oid: str) -> bytes: ...  # pragma: no cover
    def fetch_pr(self, pr_number: int) -> None: ...  # pragma: no cover
    def fetch_base(self, base_ref: str) -> None: ...  # pragma: no cover
    def churn_for_commits(
        self, commit_oids: Sequence[str]
    ) -> list[ModifiedFileRow]: ...  # pragma: no cover


class SubprocessGitRunner:
    """Drives real `git`. Every read is against the immutable object DB — the tree
    object (`ls_tree`), commit objects (`rev_list`, `churn_for_commits`), or the
    merge-base diff (`diff_name_only`) — never the operator's working tree."""

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        completed = subprocess.run(
            ["git", "ls-tree", "-r", rev],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [_parse_ls_tree_line(line) for line in completed.stdout.splitlines() if line]

    def cat_object_exists(self, oid: str) -> bool:
        # `git cat-file -e <oid>` exits 0 iff the object is present locally.
        completed = subprocess.run(
            ["git", "cat-file", "-e", oid],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.returncode == 0

    def rev_list(self, base: str, head: str) -> list[str]:
        completed = subprocess.run(
            ["git", "rev-list", f"{base}..{head}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [line for line in completed.stdout.splitlines() if line]

    def diff_name_only(self, base: str, head: str) -> list[str]:
        # 3-dot: the merge-base..head net diff, matching GitHub's "Files changed".
        completed = subprocess.run(
            ["git", "diff", f"{base}...{head}", "--name-only"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [line for line in completed.stdout.splitlines() if line]

    def archive_tar(self, oid: str) -> bytes:
        # `git archive` serializes the commit *tree object* to a tar on stdout —
        # binary bytes, so no `text=True`. The snapshot scc scans (slice 3) is
        # extracted from this tar, never the operator's working tree, so a dirty
        # checkout cannot leak into the artifact (the Path-C invariant).
        completed = subprocess.run(
            ["git", "archive", "--format=tar", oid],
            capture_output=True,
            timeout=120,
            check=True,
        )
        return completed.stdout

    def fetch_pr(self, pr_number: int) -> None:  # pragma: no cover - needs a remote PR ref
        subprocess.run(
            ["git", "fetch", "origin", f"pull/{pr_number}/head"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def fetch_base(self, base_ref: str) -> None:  # pragma: no cover - needs a remote
        subprocess.run(
            ["git", "fetch", "origin", base_ref],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def churn_for_commits(self, commit_oids: Sequence[str]) -> list[ModifiedFileRow]:
        # Read each commit *object* by SHA via `Git.get_commit` — not
        # `Repository(only_commits=...)`, whose branch-traversal filter silently
        # yields nothing for a commit unreachable from the checked-out HEAD (the
        # normal PR-head case: the head is not merged into the current branch). This
        # reads the object DB directly, so churn is a property of the snapshot, not
        # the checkout. Imported lazily so the estate-only path never pays the cost.
        from pydriller import Git as PyDrillerGit

        git_repo = PyDrillerGit(".")
        rows: list[ModifiedFileRow] = []
        for oid in commit_oids:
            for modified in git_repo.get_commit(oid).modified_files:
                rows.append(
                    ModifiedFileRow(
                        new_path=modified.new_path,
                        old_path=modified.old_path,
                        added=modified.added_lines,
                        deleted=modified.deleted_lines,
                    )
                )
        return rows


def _parse_ls_tree_line(line: str) -> LsTreeRow:
    """Parse one `git ls-tree -r` line into an `LsTreeRow`.

    Line shape is ``<mode> SP <obj_type> SP <object> TAB <path>`` — the single
    TAB separates the metadata columns from the path, so a path containing
    spaces stays intact.
    """
    meta, _, path = line.partition("\t")
    mode, obj_type, blob_sha = meta.split()
    return LsTreeRow(mode=mode, obj_type=obj_type, blob_sha=blob_sha, path=path)
