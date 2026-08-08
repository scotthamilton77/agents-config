"""Close-walk: the containment-closure tail shared by `close` and `deliver`.

Close + close-walk + note happen as ONE facade call: a parent whose last open
child closes is exhausted and closes with it, recursively, so a fully
delivered tree never strands its containers open.

The walk closes a parent only where child exhaustion is the whole truth about
that parent, and it has two boundaries. Milestones are the first -- a
milestone never auto-closes on child exhaustion; closing one is always a
deliberate, explicit close call. A parent carrying scope of its own is the
second: closing its children establishes nothing about that scope, so the
walk holds it open and reports what is unfinished rather than inferring a
completion nobody checked. Neither boundary governs an id the caller names --
a stated close is the caller's own claim, and it is never re-adjudicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.lifecycle import DELIVERED_MARKER, has_marker, is_container
from workcli.model import Item

CLOSE_WALK_MARKER = "[work] close-walk: all children closed"

HELD_REASON = "carries scope of its own, and no delivery is recorded against it"


@dataclass(frozen=True)
class HeldParent:
    """One parent the walk declined to close, and why.

    Carries the item's own title and criteria alongside the reason so a
    caller can act on the hold as it stands: the criteria are the terms the
    parent's completion is judged in, and re-reading the item to find them is
    the round trip this record exists to spare.
    """

    id: str
    title: str
    reason: str
    acceptance: str | None
    resolve: str

    def as_payload(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "title": self.title,
            "reason": self.reason,
            "acceptance": self.acceptance,
            "resolve": self.resolve,
        }


@dataclass(frozen=True)
class WalkResult:
    walked: list[str]  # auto-closed ids, in walk order
    held: list[HeldParent]  # exhausted parents the walk refused to close


def _own_scope_is_done(item: Item) -> bool:
    """Whether nothing of `item`'s own remains before it can be called done.

    Two ways that holds. A declared container has no scope of its own -- it
    is structural, its children ARE its scope, so exhausting them completes
    it. Anything else is a leaf that acquired children, and a leaf's own
    scope is discharged by `deliver`, which records the delivery marker.
    Declared state, never child count: same test `claim` and `deliver`
    already dispatch on.

    The marker case is narrow but real. `deliver` records it and then closes,
    so a delivered parent is normally already closed when a walk reaches it;
    the open-and-marked state is the crash window between those two writes,
    which `deliver`'s own replay path exists for. Reading the marker is what
    keeps this a statement about completion rather than about shape.
    """
    return is_container(item) or has_marker(item.notes, DELIVERED_MARKER)


def _held(item: Item) -> HeldParent:
    return HeldParent(
        id=item.id,
        title=item.title,
        reason=HELD_REASON,
        acceptance=item.acceptance,
        resolve=(
            f"deliver {item.id} with evidence once its own scope is done, or close "
            f"{item.id} explicitly -- a close the caller names is never held"
        ),
    )


def close_walk(backend: Backend, ids: list[str]) -> WalkResult:
    """Walk each closed id's parent chain, closing exhausted parents.

    A parent closes iff it is not a milestone, not already closed, every
    child is closed, and its own scope is done; each auto-close appends
    `CLOSE_WALK_MARKER` and the walk recurses upward. An exhausted parent
    whose own scope is not done is reported held instead, once per parent
    however many of its children this call closes.

    The three older stops stay silent, and deliberately so: a milestone is
    the designed boundary, an already-closed parent is a no-op, and an open
    sibling means the parent is simply not eligible yet. A hold is the one
    stop where the tree looks finished and the walk declines anyway, which is
    the only one a caller can be surprised by. Closing sibling ids in one
    call converges on either outcome: the second sibling's walk meets the
    already-closed parent, or the already-held one, and stops without a
    duplicate note or a duplicate hold (idempotency).
    """
    walked: list[str] = []
    held: list[HeldParent] = []
    held_ids: set[str] = set()
    for start in backend.batch_get(ids):
        current = start
        while current.parent is not None:
            parent = backend.get(current.parent)
            if parent.type == "milestone" or parent.status == "closed":
                break
            children = backend.batch_get(parent.children)
            if any(child.status != "closed" for child in children):
                break
            if not _own_scope_is_done(parent):
                if parent.id not in held_ids:
                    held_ids.add(parent.id)
                    held.append(_held(parent))
                break
            backend.close([parent.id])
            backend.append_note(parent.id, CLOSE_WALK_MARKER)
            walked.append(parent.id)
            current = parent
    return WalkResult(walked=walked, held=held)


def walk_payload(result: WalkResult) -> dict[str, JsonValue]:
    """`result` as envelope `data` keys -- each omitted when it has nothing to say."""
    payload: dict[str, JsonValue] = {}
    if result.walked:
        payload["walked"] = cast("list[JsonValue]", list(result.walked))
    if result.held:
        payload["held"] = cast("list[JsonValue]", [entry.as_payload() for entry in result.held])
    return payload
