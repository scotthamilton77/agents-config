"""The JobSupervisor — orchestrator-side ownership of worker Sessions.

In production the supervisor forks a sandboxed worker into its own process
group and reports terminal status across orchestrator restarts. For the
tracer it is **real-thin**: it creates the per-Session artifact dir and
sandbox worktree for real, then runs a synchronous *canned* worker that
writes a passing gate-evidence YAML — no subprocess fork. The Session
lifecycle and the gate-evidence-on-disk seam are exercised honestly; only the
worker's interior is stubbed.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from pdlc.gate_evidence import GateEvidence, write_evidence
from pdlc.lifecycle import GATE_ID_BY_STAGE
from pdlc.session import Session

_GATE_VERSION = "tracer-v1"
_REPORT_FILENAME = "gate-evidence.yml"


@dataclass(frozen=True, slots=True)
class SupervisorLease:
    """Returned by `lease`; carries the identity and filesystem handles the
    orchestrator records on the Session at the running transition."""

    supervisor_id: str
    artifact_dir: Path
    worktree_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class TerminalStatus:
    """Worker terminal status, queried at REAP."""

    exit_code: int
    report_path: Path


class JobSupervisor:
    """Spawns (canned) workers and remembers their terminal status. `root` is
    the orchestrator's working directory; artifacts and worktrees live under
    it."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._next = 0
        self._evidence_clock = 0
        self._terminal: dict[str, TerminalStatus] = {}

    def lease(self, session: Session) -> SupervisorLease:
        """Fork (synchronously, canned) the worker for `session`, write its
        passing gate evidence, and return the lease."""
        self._next += 1
        supervisor_id = f"supervisor-{self._next}"
        artifact_dir = self._root / "artifacts" / session.id
        worktree_path = self._root / "worktrees" / session.id
        worktree_path.mkdir(parents=True, exist_ok=True)
        report_path = artifact_dir / _REPORT_FILENAME

        self._evidence_clock += 1
        write_evidence(
            report_path,
            GateEvidence(
                gate_id=GATE_ID_BY_STAGE[session.lifecycle_stage],
                gate_version=_GATE_VERSION,
                objective_id=session.objective_id,
                session_id=session.id,
                attempt_number=session.attempt_number,
                started_ts=self._evidence_clock,
                ended_ts=self._evidence_clock,
                verdict="pass",
            ),
        )
        self._terminal[supervisor_id] = TerminalStatus(exit_code=0, report_path=report_path)
        return SupervisorLease(
            supervisor_id=supervisor_id,
            artifact_dir=artifact_dir,
            worktree_path=worktree_path,
            report_path=report_path,
        )

    def terminal_status(self, supervisor_id: str) -> TerminalStatus:
        return self._terminal[supervisor_id]

    def cleanup_worktree(self, worktree_path: Path) -> None:
        """Remove a Session's sandbox worktree. Idempotent: a second call on
        an already-removed path is a no-op, per Integration Stage C."""
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
