"""§8.1 complete-PR-snapshot assembly + §8.2 recurrence derivation.

The fix agent NEVER calls ``gh`` (§8.1: runtime swappability, auth containment,
rate-limit centralisation, reproducibility). prgroom does the gh/git legwork
**immediately before each cluster's fix dispatch** (minimising staleness) and
dumps everything to the two files the fix contract already passes —
``pr_detail_path`` and ``branch_state_path`` (see :class:`SnapshotPaths`):

* ``pr_detail_path`` (JSON): the PR **description** (with the ``## Decisions``
  block read verbatim — writing it is bead 8.12, here we only READ it), the PR
  **labels**, **every review thread with its full reply-chain**, the
  **prior-round dispositions** for already-processed items (kind / rationale /
  commits / decided_by, from ``prsession`` state), and the per-item
  **recurrence** (§8.2).
* ``branch_state_path`` (text): the recent commits (``git log``) + the
  diff-since-base summary (``git diff --stat``), scoped to ``origin/<base>..HEAD``
  where ``<base>`` is the gh PR resource's ``base.ref``.

The two ephemeral working dirs the fix contract needs (``memory_dir`` scratch,
``response_outbox_dir``) are created here too and carried on the result.

8.2 boundary: prgroom **detects, it does not interpret** (§8.2). The recurrence
signal is **derived at snapshot time, not persisted** (§2 schema unchanged). The
MVP §2 schema retains exactly one :class:`~prgroom.prsession.state.Disposition`
per item and no first-seen-round, so ``attempt_count`` reports the schema floor
(``1``) and ``first_seen_round`` reports the current round as the only available
proxy — both sharpen once disposition-history tracking lands (reported as a
schema gap, not invented here).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prgroom.agent.recurrence import Recurrence
from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh.client import GhNotFoundError

if TYPE_CHECKING:
    from prgroom.gh.client import GhClient
    from prgroom.git.client import GitClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState, ReviewItem

# Sentinel markers prgroom owns the ``## Decisions`` block between (§8.3). Here we
# only READ the block into the snapshot; writing it is bead 8.12.
DECISIONS_START = "<!-- prgroom:decisions:start -->"
DECISIONS_END = "<!-- prgroom:decisions:end -->"

_PR_DETAIL_FILENAME = "pr_detail.json"
_BRANCH_STATE_FILENAME = "branch_state.txt"


class SnapshotPaths:
    """The assembled snapshot's file paths, ephemeral dirs, and per-item recurrence.

    ``pr_detail_path`` / ``branch_state_path`` are the two files the fix contract
    passes to the agent; ``memory_dir`` / ``response_outbox_dir`` are the ephemeral
    working dirs it writes into; ``recurrence`` maps a cluster item's ``gh_id`` to
    its §8.2 :class:`~prgroom.agent.recurrence.Recurrence` (only items carrying a
    prior disposition appear).
    """

    __slots__ = (
        "branch_state_path",
        "memory_dir",
        "pr_detail_path",
        "recurrence",
        "response_outbox_dir",
    )

    def __init__(
        self,
        *,
        pr_detail_path: str,
        branch_state_path: str,
        memory_dir: str,
        response_outbox_dir: str,
        recurrence: dict[str, Recurrence],
    ) -> None:
        self.pr_detail_path = pr_detail_path
        self.branch_state_path = branch_state_path
        self.memory_dir = memory_dir
        self.response_outbox_dir = response_outbox_dir
        self.recurrence = recurrence


def extract_decisions_block(body: str) -> str:
    """Return the ``## Decisions`` block (between sentinels) verbatim, else ``""``.

    The block is read-only here (writing it is bead 8.3/8.12). A body missing
    either sentinel — or with them out of order — has no block, so this returns
    the empty string rather than guessing a boundary.
    """
    start = body.find(DECISIONS_START)
    if start == -1:
        return ""
    end = body.find(DECISIONS_END, start)
    if end == -1:
        return ""
    return body[start + len(DECISIONS_START) : end].strip()


def derive_recurrence(
    item: ReviewItem,
    state: PRGroomingState,
    *,
    threads: dict[str, list[dict[str, Any]]],
) -> Recurrence | None:
    """Derive the §8.2 recurrence signal for one item, or ``None`` if no prior.

    Returns ``None`` when the item carries no prior disposition (a fresh item has
    no recurrence). Otherwise builds the signal from what the §2 schema actually
    retains:

    * ``prior_disposition`` / ``prior_commits`` — from the item's single recorded
      :class:`~prgroom.prsession.state.Disposition` (schema-backed).
    * ``reopened`` — true iff a reply on the item's thread is newer than the
      disposition's ``decided_at`` (deterministic from the snapshot's thread
      reply-chains).
    * ``attempt_count`` — ``1`` (the MVP schema retains one disposition; a true
      count needs history tracking — reported as a schema gap).
    * ``first_seen_round`` — ``state.round`` (the schema has no first-seen field;
      the current round is the only available proxy — reported as a schema gap).
    """
    disposition = item.disposition
    if disposition is None:
        return None
    reopened = _thread_reopened(item, disposition.decided_at, threads)
    return Recurrence(
        reopened=reopened,
        attempt_count=1,
        prior_disposition=disposition.kind.value,
        prior_commits=tuple(disposition.commits),
        first_seen_round=state.round,
    )


def _thread_reopened(
    item: ReviewItem, decided_at: datetime, threads: dict[str, list[dict[str, Any]]]
) -> bool:
    """True iff the item's thread has a reply newer than its disposition (§8.2)."""
    thread_id = item.identity.thread_id
    if not thread_id:
        return False
    for comment in threads.get(thread_id, []):
        raw = comment.get("created_at")
        if not isinstance(raw, str) or not raw:
            continue
        if datetime.fromisoformat(raw.replace("Z", "+00:00")) > decided_at:
            return True
    return False


def assemble_snapshot(
    state: PRGroomingState,
    cluster_items: list[ReviewItem],
    *,
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    scratch_dir: Path,
) -> SnapshotPaths:
    """Assemble the §8.1 complete snapshot for one cluster's fix dispatch.

    Reads the PR resource (base ref, body, labels) + review threads via ``gh``
    (read-only GETs) and the branch state via ``git`` (``log`` + ``diff --stat``
    over ``origin/<base>..HEAD``), then writes ``pr_detail_path`` (JSON) and
    ``branch_state_path`` (text) under ``scratch_dir`` and creates the ephemeral
    ``memory_dir`` / ``response_outbox_dir``. Returns the paths + per-item §8.2
    recurrence. A 404 on a required read maps to ``RUNTIME_GH_TERMINAL`` (the PR
    or repo vanished mid-run — a blind retry won't bring it back).
    """
    pr = _gh_get(gh, ref, f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
    base_ref = str((pr.get("base") or {}).get("ref") or "")
    body = str(pr.get("body") or "")
    labels = [str(label.get("name", "")) for label in (pr.get("labels") or [])]

    threads = _fetch_review_threads(gh, ref)
    recurrence = _build_recurrence(state, cluster_items, threads)

    detail = {
        "description": body,
        "decisions": extract_decisions_block(body),
        "labels": labels,
        "review_threads": _thread_chains(threads),
        "prior_dispositions": _prior_dispositions(state),
        "recurrence": {gh_id: rec.to_dict() for gh_id, rec in recurrence.items()},
    }

    pr_detail_path = scratch_dir / _PR_DETAIL_FILENAME
    pr_detail_path.write_text(json.dumps(detail, indent=2), encoding="utf-8")

    branch_state_path = scratch_dir / _BRANCH_STATE_FILENAME
    branch_state_path.write_text(_branch_state(git, base_ref), encoding="utf-8")

    memory_dir = Path(tempfile.mkdtemp(prefix="memory-", dir=scratch_dir))
    response_outbox_dir = Path(tempfile.mkdtemp(prefix="outbox-", dir=scratch_dir))

    return SnapshotPaths(
        pr_detail_path=str(pr_detail_path),
        branch_state_path=str(branch_state_path),
        memory_dir=str(memory_dir),
        response_outbox_dir=str(response_outbox_dir),
        recurrence=recurrence,
    )


def _build_recurrence(
    state: PRGroomingState,
    cluster_items: list[ReviewItem],
    threads: dict[str, list[dict[str, Any]]],
) -> dict[str, Recurrence]:
    """Per-item §8.2 recurrence for the cluster items that carry a prior disposition."""
    out: dict[str, Recurrence] = {}
    for item in cluster_items:
        rec = derive_recurrence(item, state, threads=threads)
        if rec is not None:
            out[item.identity.gh_id] = rec
    return out


def _branch_state(git: GitClient, base_ref: str) -> str:
    """The §8.1 branch-state text: recent commits + diff-since-base.

    Scoped to ``origin/<base>..HEAD``. A PR resource that omitted ``base.ref``
    (unexpected) degrades to ``HEAD`` so the read never builds a malformed range.
    """
    range_ = f"origin/{base_ref}..HEAD" if base_ref else "HEAD"
    log = git.log(range_)
    diff_stat = git.diff_stat(range_)
    return f"## Recent commits ({range_})\n{log}\n\n## Diff stat\n{diff_stat}\n"


def _prior_dispositions(state: PRGroomingState) -> list[dict[str, Any]]:
    """The §8.1 prior-round dispositions for every already-processed item."""
    out: list[dict[str, Any]] = []
    for item in state.items:
        disposition = item.disposition
        if disposition is None:
            continue
        out.append(
            {
                "gh_id": item.identity.gh_id,
                "kind": disposition.kind.value,
                "rationale": disposition.rationale,
                "commits": list(disposition.commits),
                "decided_by": disposition.decided_by,
            }
        )
    return out


def _fetch_review_threads(gh: GhClient, ref: PRRef) -> dict[str, list[dict[str, Any]]]:
    """Group every PR review comment into its thread's full reply-chain (§8.1).

    A top-level inline comment (no ``in_reply_to_id``) anchors a thread keyed by
    its own id; replies (``in_reply_to_id`` set) attach under their root. The key
    is a string id so it matches a :class:`Identity`'s ``thread_id`` when present,
    falling back to the root comment id otherwise.
    """
    raw = _gh_get(gh, ref, f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/comments")
    roots: dict[int, list[dict[str, Any]]] = {}
    by_id: dict[int, int] = {}  # comment id -> its thread root id
    for entry in raw:
        cid = int(entry["id"])
        parent = entry.get("in_reply_to_id")
        root = int(parent) if parent is not None else cid
        by_id[cid] = root
        roots.setdefault(root, [])
    for entry in raw:
        cid = int(entry["id"])
        roots[by_id[cid]].append(entry)
    return {str(root): comments for root, comments in roots.items()}


def _thread_chains(threads: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Render the grouped threads as the snapshot's ``review_threads`` array."""
    return [
        {
            "thread_id": thread_id,
            "comments": [
                {
                    "id": str(c.get("id", "")),
                    "author": str((c.get("user") or {}).get("login", "")),
                    "body": str(c.get("body") or ""),
                    "created_at": str(c.get("created_at") or ""),
                }
                for c in comments
            ],
        }
        for thread_id, comments in threads.items()
    ]


def _vanished_pr_terminal(ref: PRRef) -> PrgroomError:
    """Map a 404 on a required snapshot read to ``RUNTIME_GH_TERMINAL`` (§3.6).

    Mirrors ``poll.py``'s mapping: a mid-run 404 on the PR resource or its
    comments means the PR/repo vanished — terminal, since a blind retry can't
    bring it back. (The startup ``PRECONDITION_REPO_UNREACHABLE`` is out of scope.)
    """
    return PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER,
        code=ErrorCode.RUNTIME_GH_TERMINAL,
        detail=f"PR resource not found: {ref.display()}",
    )


def _gh_get(gh: GhClient, ref: PRRef, path: str) -> Any:
    """``gh.rest("GET", path)`` with a 404 mapped to terminal (vanished PR/repo)."""
    try:
        return gh.rest("GET", path)
    except GhNotFoundError as exc:
        raise _vanished_pr_terminal(ref) from exc
