"""Contract tests for OrchestratorStateRepo's dispatch-gating policy.

`active_session_for` decides whether a new worker may be dispatched: a
pending or running Session is in-flight and blocks dispatch; a reaped Session
does not. That policy is the no-double-dispatch invariant, pinned here.
"""

from __future__ import annotations

from pdlc.lifecycle import LifecycleStage
from pdlc.session import Session, SessionStatus
from pdlc.state_repo import OrchestratorStateRepo


def _session(status: SessionStatus) -> Session:
    return Session(
        id=f"session-{status}",
        objective_id="obj-1",
        lifecycle_stage=LifecycleStage.IMPLEMENTING,
        attempt_number=1,
        config_hash="cfg",
        status=status,
    )


def test_running_session_blocks_dispatch() -> None:
    repo = OrchestratorStateRepo()
    running = _session(SessionStatus.RUNNING)
    repo.put_session(running)

    assert repo.active_session_for("obj-1") is running


def test_reaped_session_does_not_block_dispatch() -> None:
    repo = OrchestratorStateRepo()
    repo.put_session(_session(SessionStatus.REAPED))

    assert repo.active_session_for("obj-1") is None
