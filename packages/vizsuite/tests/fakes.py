"""Scripted adapter fakes: the seams every contract test drives runners through.

No live git/scc/gh, no real subprocess — ever. Slice 1 ships `ScriptedGitRunner`
(the only adapter it exercises); the scc/gh scripted fakes land in slices 3/2
alongside their real runner protocols (you cannot mirror a protocol that does
not exist yet). Each fake records every call so a test can assert on both the
returned data and what the code under test actually asked the adapter for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from vizsuite.adapters.gh.runner import GhResult
from vizsuite.adapters.git.runner import LsTreeRow, ModifiedFileRow


@dataclass
class ScriptedGitRunner:
    """Feeds scripted git results; records every call flat as ``(method, *args)``.

    - `.ls_tree_rows`: the rows every `ls_tree(rev)` call returns.
    - `.churn_rows`: the rows every `churn_for_commits(oids)` call returns.
    - `.calls`: each invocation as ``(method, *string_args)`` — the assertion
      surface for what the code under test asked git for (e.g. that estate reads
      ``HEAD`` in slice 1, the resolved head OID in slice 2). Recorded flat and
      all-`str` so the tuple stays homogeneous.
    """

    ls_tree_rows: list[LsTreeRow] = field(default_factory=list)
    churn_rows: list[ModifiedFileRow] = field(default_factory=list)
    # Reconcile seam: OIDs cat_object_exists reports present, the OIDs a fetch
    # makes present (empty ⇒ a fetch resolves nothing → SNAPSHOT_MISMATCH), the
    # local net diff, and the local commit set.
    present_oids: set[str] = field(default_factory=set)
    fetch_brings: set[str] = field(default_factory=set)
    diff_files: list[str] = field(default_factory=list)
    rev_list_oids: list[str] = field(default_factory=list)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        self.calls.append(("ls_tree", rev))
        return list(self.ls_tree_rows)

    def churn_for_commits(self, commit_oids: Sequence[str]) -> list[ModifiedFileRow]:
        self.calls.append(("churn_for_commits", *commit_oids))
        return list(self.churn_rows)

    def cat_object_exists(self, oid: str) -> bool:
        self.calls.append(("cat_object_exists", oid))
        return oid in self.present_oids

    def diff_name_only(self, base: str, head: str) -> list[str]:
        self.calls.append(("diff_name_only", base, head))
        return list(self.diff_files)

    def rev_list(self, base: str, head: str) -> list[str]:
        self.calls.append(("rev_list", base, head))
        return list(self.rev_list_oids)

    def fetch_pr(self, pr_number: int) -> None:
        self.calls.append(("fetch_pr", str(pr_number)))
        self.present_oids |= self.fetch_brings

    def fetch_base(self, base_ref: str) -> None:
        self.calls.append(("fetch_base", base_ref))
        self.present_oids |= self.fetch_brings


@dataclass
class ScriptedGhRunner:
    """Feeds one scripted `gh api graphql` raw result; records the PR asked for.

    Reconcile parses this raw `GhResult` through the real `parse_pr_view`, so a
    test exercises the actual parse path (not a hand-built `PrView`). Build the
    `GhResult` with `gh_pr_result(...)`.
    """

    result: GhResult
    calls: list[tuple[str, int]] = field(default_factory=list)

    def pr_graphql(self, pr_number: int) -> GhResult:
        self.calls.append(("pr_graphql", pr_number))
        return self.result


def gh_pr_result(
    *,
    base_oid: str = "base000",
    head_oid: str = "head111",
    base_ref: str = "main",
    changed_files: int,
    commit_count: int,
) -> GhResult:
    """Build a successful `gh api graphql` `GhResult` for a PR (the common fixture)."""
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "baseRefOid": base_oid,
                    "headRefOid": head_oid,
                    "baseRefName": base_ref,
                    "changedFiles": changed_files,
                    "commits": {"totalCount": commit_count},
                }
            }
        }
    }
    return GhResult(returncode=0, stdout=json.dumps(payload), stderr="")


def blob(path: str, blob_sha: str = "0" * 40) -> LsTreeRow:
    """Build a `blob` `LsTreeRow` (the common case) for fixtures."""
    return LsTreeRow(mode="100644", obj_type="blob", blob_sha=blob_sha, path=path)
