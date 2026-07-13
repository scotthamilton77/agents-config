"""Estate extractor: blob rows minus curated excludes → {path: blob_sha}."""

from __future__ import annotations

from vizsuite.adapters.git.runner import LsTreeRow
from vizsuite.extract.estate import estate


def _blob(path: str, sha: str) -> LsTreeRow:
    return LsTreeRow(mode="100644", obj_type="blob", blob_sha=sha, path=path)


def test_blob_rows_map_path_to_blob_sha():
    rows = [
        _blob("src/app.py", "aaaa111"),
        _blob("README.md", "bbbb222"),
    ]
    git = _ScriptedRows(rows)

    result = estate(git, "HEAD")

    assert result == {"src/app.py": "aaaa111", "README.md": "bbbb222"}
    assert git.calls == [("ls_tree", "HEAD")]


def test_excluded_dir_prefixes_and_lock_suffixes_are_dropped():
    rows = [
        _blob("src/app.py", "keep1"),
        _blob("graphify-out/graph.json", "drop1"),  # excluded dir prefix
        _blob(".beads/x.json", "drop2"),
        _blob(".viz/out/pr-1.html", "drop3"),
        _blob("archive/old.py", "drop4"),
        _blob("uv.lock", "drop5"),  # excluded suffix (lockfile)
        _blob("web/package-lock.json", "drop6"),
        _blob("vendor/d3.min.js", "drop7"),  # generated
    ]

    result = estate(_ScriptedRows(rows), "HEAD")

    assert result == {"src/app.py": "keep1"}


def test_non_blob_rows_never_appear():
    rows = [
        _blob("src/app.py", "keep"),
        LsTreeRow(mode="040000", obj_type="tree", blob_sha="tree_sha", path="src"),
        LsTreeRow(mode="160000", obj_type="commit", blob_sha="submod_sha", path="vendor/sub"),
    ]

    result = estate(_ScriptedRows(rows), "HEAD")

    assert result == {"src/app.py": "keep"}


class _ScriptedRows:
    """A minimal GitRunner returning fixed ls-tree rows and recording the rev."""

    def __init__(self, rows: list[LsTreeRow]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, str]] = []

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        self.calls.append(("ls_tree", rev))
        return list(self._rows)
