"""Scripted adapter fakes: the seams every contract test drives runners through.

No live git/scc/gh, no real subprocess — ever. Slice 1 ships `ScriptedGitRunner`
(the only adapter it exercises); the scc/gh scripted fakes land in slices 3/2
alongside their real runner protocols (you cannot mirror a protocol that does
not exist yet). Each fake records every call so a test can assert on both the
returned data and what the code under test actually asked the adapter for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vizsuite.adapters.git.runner import LsTreeRow


@dataclass
class ScriptedGitRunner:
    """Feeds a scripted `git ls-tree` result; records every call's revision.

    - `.ls_tree_rows`: the rows every `ls_tree(rev)` call returns.
    - `.calls`: each invocation as ``(method, rev)`` — the assertion surface for
      what the code under test asked git for (e.g. that estate reads ``HEAD`` in
      slice 1, the resolved head OID in slice 2).
    """

    ls_tree_rows: list[LsTreeRow] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        self.calls.append(("ls_tree", rev))
        return list(self.ls_tree_rows)


def blob(path: str, blob_sha: str = "0" * 40) -> LsTreeRow:
    """Build a `blob` `LsTreeRow` (the common case) for fixtures."""
    return LsTreeRow(mode="100644", obj_type="blob", blob_sha=blob_sha, path=path)
