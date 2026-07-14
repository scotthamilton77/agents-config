"""The gh subprocess port — the fake's seam.

`GhRunner` is the interface every reconcile test replaces with
`tests/fakes.ScriptedGhRunner`; `SubprocessGhRunner` is the sole implementation
that actually shells out to real `gh`. The port returns a *raw* `GhResult`
(returncode + stdout + stderr) exactly like ``workcli``'s `BdRunner.run` — every
shape decision lives in `gh/parse.py` (`parse_pr_view`), so the failure/drift
logic is unit-tested against scripted `GhResult`s and the only uncovered code is
the thin `subprocess.run` line (a `gh api graphql` call needs auth + network, so
CI never runs it — the gate uses fakes, plan §3.4.1).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

# One `gh api graphql` query for the PR's immutable OIDs, base ref name, and the
# two *un-truncated* scalar counts (changedFiles / commits.totalCount) — the
# scalar path sidesteps the `first:100` cap that `gh pr view --json files,commits`
# imposes (plan §3.5, F4). `{owner}`/`{repo}` are gh's current-repo placeholders,
# substituted by gh in `-F` field values.
_PR_QUERY = (
    "query($owner:String!,$repo:String!,$number:Int!){"
    "repository(owner:$owner,name:$repo){"
    "pullRequest(number:$number){"
    "baseRefOid headRefOid baseRefName changedFiles commits{totalCount}"
    "}}}"
)

# `gh pr view --json` fields for the PR-metadata garnish (author/review-state/
# timestamps, spec §4.4) — a separate, widened call from `_PR_QUERY`: this one
# is metadata only, never part of the reconciler's drift-critical scalar join.
_PR_META_FIELDS = "author,reviewDecision,createdAt,updatedAt,mergedAt"


@dataclass(frozen=True)
class GhResult:
    returncode: int
    stdout: str
    stderr: str


class GhRunner(Protocol):
    def pr_graphql(self, pr_number: int) -> GhResult: ...  # pragma: no cover
    def pr_meta(self, pr_number: int) -> GhResult: ...  # pragma: no cover


class SubprocessGhRunner:
    """Drives the real `gh` binary. One graphql query per PR; raw result out."""

    def pr_graphql(self, pr_number: int) -> GhResult:  # pragma: no cover - needs gh auth+network
        completed = subprocess.run(
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
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return GhResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )

    def pr_meta(self, pr_number: int) -> GhResult:  # pragma: no cover - needs gh auth+network
        completed = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", _PR_META_FIELDS],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return GhResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
