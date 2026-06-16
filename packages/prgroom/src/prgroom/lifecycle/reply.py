"""``reply_pr`` — the foundation no-op skeleton for the ``reply`` verb (§3.3).

The run-loop wires the §3.3 pipeline against a **no-op skeleton** of ``_reply`` (the
pipeline-slotting pin): it occupies the ``_push → _rereview → _reply → _resolve`` slot
so the loop's ordering and write discipline are exercised end-to-end, but renders and
posts nothing. The full template-matrix reply (rendering per-item responses and
posting them via the gh API) lands in the deterministic-verbs bead.

Keeping it a real, idempotent passthrough — rather than omitting the slot — means the
run-loop's pipeline list and its per-step write discipline need no change when the
real ``reply`` arrives; only this body is filled in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prgroom.prsession.state import PRGroomingState


def reply_pr(state: PRGroomingState) -> PRGroomingState:
    """No-op skeleton: return ``state`` unchanged (§3.3 pipeline-slotting pin).

    Caller must hold the per-ref lock (see ``lock()``). Idempotent by construction —
    every item is left exactly as received, so the run-loop's ``_reply`` slot is a
    safe passthrough until the deterministic-verbs bead fills it in.
    """
    return state
