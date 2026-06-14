"""``resolve_pr`` — the lock-held ``_resolve`` lifecycle internal (§3.2).

``_resolve`` closes out the review threads the fix path addressed: for every
``review_thread`` item whose disposition is ``fixed`` or ``already_addressed`` and
that is not yet resolved, it calls the GraphQL ``resolveReviewThread`` mutation keyed
by the thread's node id (``Identity.thread_id``, a ``PRRT_*``) and marks the item
``resolved=True`` so a re-run is a no-op (the §3.3 idempotency contract).

A ``review_thread`` whose ``thread_id`` is empty is a *degraded* item — the poll
could not map its REST databaseId to a GraphQL node id (e.g. a hollow GraphQL
response). It cannot be resolved, so it is skipped with a warning and left
unresolved for a later poll to repair — never silently marked resolved.

Mirrors the other lock-held internals: works on a deepcopy, never touches the store
(the caller owns ``store.write``), makes no phase change (§3.2 resolve row), and sets
no ``state.last_error``. A no-op when no resolvable thread remains.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.lifecycle.warn import default_warn
from prgroom.prsession.enums import DispositionKind, ItemKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from prgroom.gh.client import GhClient
    from prgroom.prsession.state import PRGroomingState

# Only these dispositions warrant resolving the thread (§3.2 resolve row).
_RESOLVABLE = frozenset({DispositionKind.FIXED, DispositionKind.ALREADY_ADDRESSED})

_RESOLVE_MUTATION = """
mutation($threadId:ID!){
  resolveReviewThread(input:{threadId:$threadId}){
    thread { id isResolved }
  }
}
"""


def resolve_pr(
    state: PRGroomingState,
    *,
    gh: GhClient,
    warn: Callable[[str], None] = default_warn,
) -> PRGroomingState:
    """Resolve every fixed/already_addressed review thread not yet resolved.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state``; returns the copy for the caller to persist. A no-op when no resolvable
    thread remains. No phase change (§3.2 resolve row), no ``state.last_error``.
    """
    state = copy.deepcopy(state)
    # Partial-progress note: a mid-loop GraphQL failure propagates before the caller
    # writes state, so earlier items' server-side resolves are not persisted this
    # pass. That is safe — resolveReviewThread is idempotent server-side, and the
    # next run re-resolves the still-``resolved=False`` items harmlessly.
    for item in state.items:
        if item.kind is not ItemKind.REVIEW_THREAD or item.resolved:
            continue
        disposition = item.disposition
        if disposition is None or disposition.kind not in _RESOLVABLE:
            continue
        thread_id = item.identity.thread_id
        if not thread_id:
            warn(f"cannot resolve thread for {item.identity.gh_id}: no thread node id")
            continue
        gh.graphql(_RESOLVE_MUTATION, {"threadId": thread_id})
        item.resolved = True
    return state
