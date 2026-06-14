"""``fix_pr`` — the lock-held ``_fix`` lifecycle internal (§3.2, §5, §8).

``fix_pr`` is the APPLY side of the fix path and the sharpest expression of the
compute/apply boundary: **the agent layer computes; the lifecycle applies.** For
each cluster it assembles the §8.1 complete PR snapshot (via
:func:`~prgroom.lifecycle.snapshot.assemble_snapshot` — the recurrence map and the
ephemeral ``memory_dir`` / ``response_outbox_dir` ride on the result), builds the
:class:`~prgroom.agent.contracts.FixInput`, calls 8.7's pure
:func:`~prgroom.agent.fix.run_fix`, then APPLIES the :class:`FixRunResult`:

* sets each item's :class:`~prgroom.prsession.state.Disposition` from
  ``result.dispositions``;
* emits every returned :class:`~prgroom.escalation.Escalation` via the injected
  :class:`~prgroom.escalation.Sink`;
* logs each ``result.unwritten`` path as a soft warning (§8.6 declared-but-missing
  is bookkeeping drift, not a breach) and logs ``result.deferred_memory`` as
  deferred (MVP routes only CONTEXTUAL→PR; §8.3).

It mirrors :func:`~prgroom.lifecycle.poll.poll_pr` — works on a deepcopy, never
touches the store (the caller owns ``store.write``), and returns the mutated copy.
Clusters are processed **serially** (MVP; §5). It makes **no** phase change
(§3.2 fix row: phase resolution is end-of-cycle, owned by the run aggregate verb) and does
**not** set ``state.last_error`` (FAILED dispositions carry their own rationale;
the end-of-cycle resolver reads them later). ``result.stashed`` is informational.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.agent.contracts import FixInput
from prgroom.agent.fix import run_fix
from prgroom.lifecycle.snapshot import assemble_snapshot
from prgroom.lifecycle.warn import default_warn

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from prgroom.agent.contracts import FixContract, MemoryEntry
    from prgroom.config import PrgroomConfig
    from prgroom.deps import Deps
    from prgroom.escalation import Sink
    from prgroom.gh.client import GhClient
    from prgroom.git.client import GitClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState, ReviewItem


def fix_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    deps: Deps,
    config: PrgroomConfig,
    dispatcher: FixContract,
    sink: Sink,
    decided_by: str,
    scratch_dir: Path,
    warn: Callable[[str], None] = default_warn,
) -> PRGroomingState:
    """Fix every clustered-unprocessed item, applying dispositions to a state copy.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state``; returns the copy for the caller to persist. Idempotent: a no-op
    when every item is already dispositioned. No phase change (§3.2 fix row), no
    ``state.last_error``. Clusters are dispatched serially (MVP).
    """
    del config  # fix reads no config knob today; kept for signature symmetry
    state = copy.deepcopy(state)
    clusters = _group_unprocessed_by_cluster(state.items)
    if not clusters:
        return state

    now = deps.clock.now()
    for cluster_id, cluster_items in clusters.items():
        _fix_one_cluster(
            state,
            cluster_id=cluster_id,
            cluster_items=cluster_items,
            ref=ref,
            gh=gh,
            git=git,
            dispatcher=dispatcher,
            sink=sink,
            now=now,
            decided_by=decided_by,
            scratch_dir=scratch_dir,
            warn=warn,
        )
    return state


def _fix_one_cluster(
    state: PRGroomingState,
    *,
    cluster_id: str,
    cluster_items: list[ReviewItem],
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    dispatcher: FixContract,
    sink: Sink,
    now: datetime,
    decided_by: str,
    scratch_dir: Path,
    warn: Callable[[str], None],
) -> None:
    """Assemble the snapshot, dispatch run_fix, and APPLY the result for one cluster.

    ``now`` is the caller's single clock reading (one timestamp shared across the
    fix cycle), so every disposition this cycle stamps the same ``decided_at``.
    """
    snapshot = assemble_snapshot(
        state, cluster_items, ref=ref, gh=gh, git=git, scratch_dir=scratch_dir
    )
    req = FixInput(
        pr=ref,
        cluster_id=cluster_id,
        item_gh_ids=[item.identity.gh_id for item in cluster_items],
        items=cluster_items,
        pr_detail_path=snapshot.pr_detail_path,
        branch_state_path=snapshot.branch_state_path,
        memory_dir=snapshot.memory_dir,
        response_outbox_dir=snapshot.response_outbox_dir,
    )
    result = run_fix(req, dispatcher, git, now=now, decided_by=decided_by)

    # Apply via a per-cluster map over THIS cluster's items only. run_fix returns
    # dispositions keyed by gh_id for exactly these items, and the codebase's natural
    # key is (kind, gh_id) — a state-wide gh_id map could mis-target an item from
    # another cluster/kind that happens to share a gh_id.
    by_gh = {item.identity.gh_id: item for item in cluster_items}
    for gh_id, disposition in result.dispositions.items():
        item = by_gh.get(gh_id)
        if item is not None:
            item.disposition = disposition
    for escalation in result.escalations:
        sink.emit(escalation)
    for path in result.unwritten:
        warn(f"fix: declared memory path was not written (unwritten): {path}")
    for entry in result.deferred_memory:
        warn(_deferred_memory_message(entry))


def _deferred_memory_message(entry: MemoryEntry) -> str:
    """A one-line notice for an accepted-but-deferred non-CONTEXTUAL memory entry (§8.3)."""
    return f"fix: deferred non-CONTEXTUAL memory entry (classification={entry.classification})"


def _group_unprocessed_by_cluster(items: list[ReviewItem]) -> dict[str, list[ReviewItem]]:
    """Group still-unprocessed clustered items by ``cluster_id``, preserving order.

    A cluster is built from items with ``disposition is None`` AND
    ``cluster_id != ""``. Unclustered items (``cluster_id == ""``) are left for a
    future cluster pass; already-dispositioned items are skipped (the idempotency
    contract). Insertion order is preserved so clusters dispatch deterministically.
    """
    groups: dict[str, list[ReviewItem]] = {}
    for item in items:
        if item.disposition is None and item.cluster_id != "":
            groups.setdefault(item.cluster_id, []).append(item)
    return groups
