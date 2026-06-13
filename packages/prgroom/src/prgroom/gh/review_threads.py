"""Shared REST→GraphQL review-thread key bridge (§8.1, §8.2).

poll and snapshot both ingest review comments over REST, which exposes only each
comment's ``databaseId``. But a review item's ``Identity.thread_id`` is defined as
the GraphQL ``reviewThreads`` node id (``PRRT_*``) — the same id ``resolveReviewThread``
consumes — and the snapshot must key threads by it for §8.2 recurrence to match.
:func:`fetch_thread_id_map` runs the one GraphQL query that bridges the key-spaces:
it returns each thread's node id with its comments' ``databaseId``s, inverted into
``{str(databaseId) -> node id}``. Both callers map their REST comment ids through it.

Pagination: ``first:100`` on threads and on each thread's comments. A comment beyond
that cap is simply absent from the map, degrading to ``thread_id == ""`` (the §8.2
floor) rather than mis-keying — lifting the cap (``gh api --paginate`` / GraphQL
cursors) is a tracked cross-layer follow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef

_THREAD_ID_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      reviewThreads(first:100){
        nodes{ id comments(first:100){ nodes{ databaseId } } }
      }
    }
  }
}
"""


def fetch_thread_id_map(gh: GhClient, ref: PRRef) -> dict[str, str]:
    """Map each REST review-comment ``databaseId`` (str) to its GraphQL thread node id.

    One GraphQL ``reviewThreads`` read. A degenerate/empty response yields an empty
    map (the callers degrade ``thread_id`` to ``""``); GraphQL transport/`errors[]`
    failures surface from the adapter as ``RUNTIME_GRAPHQL_FAILED`` before reaching here.
    """
    data = gh.graphql(_THREAD_ID_QUERY, {"owner": ref.owner, "repo": ref.repo, "pr": ref.number})
    # Envelope levels are guarded because a 200 can carry a hollow data block (a
    # vanished PR returns a null pullRequest). Per-thread fields below are indexed
    # directly: the query pins them non-null (reviewThreads.id is ID!, comments is a
    # non-null connection), and an errors[] payload is already mapped to
    # RUNTIME_GRAPHQL_FAILED upstream before reaching here.
    pr = (data.get("repository") or {}).get("pullRequest") or {}
    nodes = (pr.get("reviewThreads") or {}).get("nodes") or []
    out: dict[str, str] = {}
    for thread in nodes:
        node_id = str(thread["id"])
        for comment in thread["comments"]["nodes"]:
            # databaseId is nullable in GraphQL (e.g. a pending review comment has no
            # REST representation) — such a comment contributes no key to the map.
            database_id = comment.get("databaseId")
            if database_id is not None:
                out[str(database_id)] = node_id
    return out
