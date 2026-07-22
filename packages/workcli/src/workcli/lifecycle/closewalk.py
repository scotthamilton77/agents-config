"""Close-walk: the containment-closure tail shared by `close` and `deliver`
(S2-D5; V2 audit row close-on-merge).

D11 requires close + close-walk + note as ONE facade call: a parent whose
last open child closes is exhausted and closes with it, recursively, so a
fully delivered tree never strands its containers open. Milestones are the
walk boundary -- a milestone closes on its own acceptance section (charter
AC9), never on child exhaustion.
"""

from __future__ import annotations

from workcli.backend import Backend

CLOSE_WALK_MARKER = "[work] close-walk: all children closed"


def close_walk(backend: Backend, ids: list[str]) -> list[str]:
    """Walk each closed id's parent chain, closing exhausted parents.

    A parent closes iff it is not a milestone, not already closed, and every
    child is closed; each auto-close appends `CLOSE_WALK_MARKER` and the walk
    recurses upward. Returns the auto-closed ids in walk order. Closing
    sibling ids in one call converges: the second sibling's walk meets the
    already-closed parent and stops without a duplicate note (idempotency,
    S2-C4).
    """
    walked: list[str] = []
    for start in backend.batch_get(ids):
        current = start
        while current.parent is not None:
            parent = backend.get(current.parent)
            if parent.type == "milestone" or parent.status == "closed":
                break
            children = backend.batch_get(parent.children)
            if any(child.status != "closed" for child in children):
                break
            backend.close([parent.id])
            backend.append_note(parent.id, CLOSE_WALK_MARKER)
            walked.append(parent.id)
            current = parent
    return walked
