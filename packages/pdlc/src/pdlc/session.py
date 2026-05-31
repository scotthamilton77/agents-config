"""The Session primitive — one worker invocation.

A Session is a first-class entity with its own identity and lifecycle
(pending -> running -> exited -> reaped). For the tracer the worker never
forks for real, but the Session record threads through DISPATCH and REAP
exactly as it would with a real worker, so the seam is honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pdlc.lifecycle import LifecycleStage


class SessionStatus(StrEnum):
    """The Session lifecycle. `crashed` exists for the failure scenarios; the
    happy path only visits pending -> running -> exited -> reaped."""

    PENDING = "pending"
    RUNNING = "running"
    EXITED = "exited"
    REAPED = "reaped"
    CRASHED = "crashed"


@dataclass(slots=True)
class Session:
    """One worker invocation targeting one gate. `config_hash` is pinned at
    dispatch (before fork) and re-validated at reap; `report_path` is where
    the worker's gate-evidence YAML lands."""

    id: str
    objective_id: str
    lifecycle_stage: LifecycleStage
    attempt_number: int
    config_hash: str
    status: SessionStatus = SessionStatus.PENDING
    supervisor_id: str | None = None
    artifact_dir: Path | None = None
    worktree_path: Path | None = None
    report_path: Path | None = None
    exit_code: int | None = None
