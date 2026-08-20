"""Starting, resuming and ending one grilling session.

**The handoff crosses the gap once.** The main agent writes it, the backend
validates it, and the backend appends `session-start` carrying the validated
briefing whole. From that instant the file has no authority: editing it
mid-session changes nothing, and a backend whose log is non-empty never opens it
at all. The check is ordered that way deliberately -- the log is consulted
before the handoff is, so there is no path on which a resumed session reads a
file that has been edited under it.

**The board is seeded through the log, never by re-reading the handoff.** One
`session-start` entry carries the briefing, and the projector folds the plan out
of it, so a fresh process re-folding `log.jsonl` alone reproduces the seeded
board. The briefing's five load-bearing fields ride in that same entry, which is
what keeps `stop_when` available to a process that never saw the file.

**A refused handoff initialises nothing.** Validation runs before the session
directory is created, because a directory holding an empty log is a session as
far as the rule above is concerned -- a backend restarted against it would find
the log empty, read the handoff again, and quietly accept the briefing it had
already refused.

**Ending is a human gesture.** The backend appends the terminal entry when the
human's `session-end` arrives, then invokes capture. Capture is fault-isolated
the way image persistence is: a failure surfaces on the status lane and leaves
the terminal entry and the session directory intact, because the log is the
record and the result file is derived from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from grillui.capture import capture, default_summary, write_result
from grillui.log import HANDOFF_FILE, LOG_FILE, SessionLog
from grillui.persistence import project_and_persist, report_failure
from grillui.schemas import SESSION_START_KIND, Handoff, HandoffDecision, fault_summary

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from grillui.capture import Summarizer


class HandoffRefusedError(ValueError):
    """A briefing the backend will not start a session on.

    Every refusal names the field it is about. "Refused" alone sends the author
    back to diff their file against a schema; the field name is a one-line fix.
    """

    def __init__(self, problem: str) -> None:
        super().__init__(f"handoff refused -- {problem}")


def read_handoff(path: Path) -> Handoff:
    """Validate one handoff file, or refuse it naming what is wrong.

    A partial briefing is refused rather than defaulted. Without `stop_when` in
    particular the session never terminates, because an agent asked to find
    weaknesses finds them indefinitely -- so a missing field is not a gap the
    backend may fill in on the author's behalf.
    """
    if not path.is_file():
        missing = f"no handoff file at {str(path)!r}"
        raise HandoffRefusedError(missing)
    try:
        handoff = Handoff.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise HandoffRefusedError(fault_summary(error, "handoff")) from error
    except ValueError as error:
        # Everything malformed lands in the clause above; this one is the file
        # that is not text at all, which `read_text` refuses before any schema
        # is reached.
        unreadable = f"{str(path)!r} could not be read"
        raise HandoffRefusedError(unreadable) from error
    problem = _graph_problem(handoff.plan.decisions)
    if problem is not None:
        raise HandoffRefusedError(problem)
    return handoff


def open_session(directory: Path, handoff_path: Path | None = None) -> SessionLog:
    """Mint a tenure over one session directory, seeding it if it is new.

    Resuming is not a handoff: a directory whose log already holds entries is
    re-folded from that log and the handoff file is not read. A new directory is
    seeded from a validated briefing, and refusing one leaves nothing behind.

    The images are rewritten either way, before anything else can read them: any
    image file already present is a derived cache from a previous tenure, and
    discarding it is what makes the log the only recovery source. That is also
    what leaves a backend launched with no page attached holding a persisted
    board rather than one that only exists once somebody looks.
    """
    handoff = None
    if not _resumable(directory):
        handoff = read_handoff(handoff_path or (directory / HANDOFF_FILE))
    log = SessionLog(directory)
    if handoff is not None:
        log.record(SESSION_START_KIND, handoff.model_dump(by_alias=True, exclude_none=True))
    project_and_persist(log)
    return log


def end_session(log: SessionLog, *, summarize: Summarizer = default_summary) -> Path | None:
    """Capture the session the human has just ended, returning the result path.

    Called once the terminal entry is durable, so a capture that fails costs the
    result file and nothing else: the log still says the session ended, and a
    later capture run over the same directory can produce the result the failed
    one did not.
    """
    try:
        return write_result(log.directory, capture(log.directory, summarize=summarize))
    except Exception as error:
        report_failure(log, "capture failed", error)
        return None


def _resumable(directory: Path) -> bool:
    """Whether this directory is a session already under way.

    A log file with nothing in it is not: an interrupted start leaves one behind
    and there is no board in it to resume.
    """
    path = directory / LOG_FILE
    return path.is_file() and path.stat().st_size > 0


def _graph_problem(decisions: Sequence[HandoffDecision]) -> str | None:
    """What the decision graph says that the per-field shapes cannot.

    Both faults here are silent in a running session rather than loud: a prereq
    naming no node leaves a decision that can never become answerable, and a
    cycle leaves every decision in it waiting on the others forever. The human
    sees a board that simply never opens up, with nothing saying why.
    """
    seen: set[str] = set()
    for index, decision in enumerate(decisions):
        if decision.id in seen:
            return f"plan.decisions.{index}.id: {decision.id!r} is not unique within the plan"
        seen.add(decision.id)
    for index, decision in enumerate(decisions):
        for prereq in decision.prereqs:
            if prereq not in seen:
                return (
                    f"plan.decisions.{index}.prereqs: {prereq!r} resolves to no decision "
                    f"in the plan"
                )
    return _cycle_problem(decisions)


def _cycle_problem(decisions: Sequence[HandoffDecision]) -> str | None:
    unmet = {decision.id: set(decision.prereqs) for decision in decisions}
    while True:
        ready = [node for node, prereqs in unmet.items() if not prereqs]
        if not ready:
            break
        for node in ready:
            del unmet[node]
        for prereqs in unmet.values():
            prereqs.difference_update(ready)
    if unmet:
        return f"plan.decisions: prereqs cycle through {sorted(unmet)}"
    return None
