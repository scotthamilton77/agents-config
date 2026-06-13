"""``cluster_pr`` — the lock-held ``_cluster`` lifecycle internal (§3.2, §5).

``cluster_pr`` is the APPLY side of the cluster path: 8.7's pure
:func:`~prgroom.agent.cluster.run_cluster` computes the clustering; this internal
calls it and APPLIES the result by setting each item's ``cluster_id``. It mirrors
:func:`~prgroom.lifecycle.poll.poll_pr`'s shape — works on a deepcopy of the
in-memory :class:`PRGroomingState`, never reads/writes the store itself (the
caller owns ``store.write``), and returns the mutated copy.

Cluster is the cheap grouping pass (§5): it decides **no** disposition and makes
**no** phase change (the §3.2 cluster row). It operates on items with
``cluster_id == ""`` that are not yet processed (``disposition is None``), and is
idempotent — a no-op when every item is already clustered (§3.3 idempotency
contract).

prgroom does the gh/git legwork for the light PR-context file the cluster
contract passes (``pr_context_path``): the PR title/body + recent commits + the
poll-derived CI summary, written under the caller-provided scratch dir.
``decided_by`` is part of the uniform ``run_cluster``/``run_fix`` signature;
clustering decides no disposition, so ``run_cluster`` ignores it (it is threaded
through for signature symmetry with the fix path).
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

from prgroom.agent.cluster import run_cluster
from prgroom.agent.contracts import ClusterInput
from prgroom.lifecycle.snapshot import gh_get

if TYPE_CHECKING:
    from pathlib import Path

    from prgroom.agent.contracts import ClusterContract
    from prgroom.config import PrgroomConfig
    from prgroom.deps import Deps
    from prgroom.gh.client import GhClient
    from prgroom.git.client import GitClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState, ReviewItem

_PR_CONTEXT_FILENAME = "pr_context.json"


def cluster_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    deps: Deps,
    config: PrgroomConfig,
    dispatcher: ClusterContract,
    decided_by: str,
    scratch_dir: Path,
) -> PRGroomingState:
    """Cluster the unclustered items, applying the assignments to a state copy.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state`` so the caller's object is never mutated; returns the copy for the
    caller to persist. Idempotent: a no-op when every item is already clustered.
    No disposition, no phase change (§3.2 cluster row).
    """
    del config  # cluster reads no config knob today; kept for signature symmetry
    state = copy.deepcopy(state)
    pending = _unclustered_unprocessed(state.items)
    if not pending:
        return state

    context_path = _write_pr_context(ref, gh, git, scratch_dir, ci_state=state.quiescence.ci_state)
    req = ClusterInput(pr=ref, items=pending, pr_context_path=str(context_path))
    result = run_cluster(req, dispatcher, now=deps.clock.now(), decided_by=decided_by)

    for item in pending:
        cluster_id = result.assignments.get(item.identity.gh_id)
        if cluster_id is not None:
            item.cluster_id = cluster_id
    return state


def _unclustered_unprocessed(items: list[ReviewItem]) -> list[ReviewItem]:
    """Items eligible for clustering: not yet clustered AND not yet processed (§5).

    Cluster operates on ``cluster_id == ""`` items, but an already-dispositioned
    item is processed work — never re-cluster it even if its ``cluster_id`` was
    left empty, so it is excluded here too.
    """
    return [item for item in items if item.cluster_id == "" and item.disposition is None]


def _write_pr_context(
    ref: PRRef, gh: GhClient, git: GitClient, scratch_dir: Path, *, ci_state: str
) -> Path:
    """Write the light PR-context file the cluster contract passes (§5).

    A read-only gh GET (PR resource: title/body/base) + a git ``log`` of recent
    commits over ``origin/<base>..HEAD`` + the poll-derived ``ci_state`` form a
    compact context the cheap cluster model groups against. ``ci_state`` is the
    combined-status poll already resolved into ``state.quiescence.ci_state`` (§4.1),
    reused here so the context needs no extra gh round-trip. A 404 (vanished
    PR/repo) maps to a terminal error via the shared
    :func:`~prgroom.lifecycle.snapshot.gh_get`; other gh/git errors propagate.
    """
    pr = gh_get(gh, ref, f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
    base_ref = str((pr.get("base") or {}).get("ref") or "")
    range_ = f"origin/{base_ref}..HEAD" if base_ref else "HEAD"
    context = {
        "title": str(pr.get("title") or ""),
        "body": str(pr.get("body") or ""),
        "recent_commits": git.log(range_),
        "ci_state": ci_state,
    }
    path = scratch_dir / _PR_CONTEXT_FILENAME
    path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    return path
