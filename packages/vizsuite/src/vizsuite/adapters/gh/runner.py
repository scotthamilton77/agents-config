"""The gh subprocess port — the fake's seam.

`GhRunner` is the interface every reconcile test replaces with
`tests/fakes.ScriptedGhRunner`; `SubprocessGhRunner` is the sole implementation
that actually shells out to real `gh`. The port returns a *raw* `GhResult`
(returncode + stdout + stderr) exactly like ``workcli``'s `BdRunner.run` — every
shape decision lives in `gh/parse.py` (`parse_pr_view`), so the failure/drift
logic is unit-tested against scripted `GhResult`s. The reconcile/extract tests
never touch the real `gh` binary (a `gh api graphql` call needs auth +
network); `test_adapters_gh_runner.py` proves the argv/cwd wiring by
monkeypatching `subprocess.run` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vizsuite.adapters.subprocess_util import run

# One `gh api graphql` query per PR carries everything the reconciler needs in a
# single round trip: the immutable OIDs, base ref name, the two *un-truncated*
# scalar counts (changedFiles / commits.totalCount — the scalar path sidesteps
# the `first:100` cap a list read would impose, plan §3.5, F4), and the
# PR-metadata garnish (author/review-state/timestamps, spec §4.4). A second
# `gh pr view --json` call would cost a redundant network round trip for data
# already present in this response. `{owner}`/`{repo}` are gh's current-repo
# placeholders, substituted by gh in `-F` field values.
_PR_QUERY = (
    "query($owner:String!,$repo:String!,$number:Int!){"
    "repository(owner:$owner,name:$repo){"
    "nameWithOwner "
    "pullRequest(number:$number){"
    "baseRefOid headRefOid baseRefName changedFiles commits{totalCount}"
    "author{login} reviewDecision createdAt updatedAt mergedAt"
    "}}}"
)


@dataclass(frozen=True)
class GhResult:
    returncode: int
    stdout: str
    stderr: str


class GhRunner(Protocol):
    def pr_graphql(self, pr_number: int) -> GhResult: ...  # pragma: no cover


class SubprocessGhRunner:
    """Drives the real `gh` binary against an injected `repo_root` (default
    ``"."``) — never the process's actual working directory — so `gh`'s own
    owner/repo inference reads the repo the caller means, not wherever the
    process happens to be. One graphql query per PR; raw result out."""

    def __init__(self, repo_root: str = ".") -> None:
        self._root = repo_root

    def pr_graphql(self, pr_number: int) -> GhResult:
        completed = run(
            [
                "gh",
                "api",
                "graphql",
                "-F",
                "owner={owner}",
                "-F",
                "repo={repo}",
                "-F",
                f"number={pr_number}",
                "-f",
                f"query={_PR_QUERY}",
            ],
            cwd=self._root,
            timeout=60,
            check=False,
        )
        return GhResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
