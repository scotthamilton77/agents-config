"""The terminal result: what a finished grilling leaves behind.

Capture reads a session directory and nothing else. It never needs the process
that ran the session, which is what lets it be invoked three ways -- by the
backend on end-session, by the main agent after the session returns, or by a
fresh agent pointed at a directory whose log is already terminal-ready.

Everything structural here is pure code over the log: the decisions and their
answers, what is still open and what stopped it, the threads, the session's own
identity, and how it ended. Running it twice over a fixed log yields byte-
identical output, because the fold it rests on has no clock, no randomness and
no I/O.

`summary` is the one field code does not write. It goes through the summarizer
seam, whose v1 default builds a bounded briefing out of the structured parts
already computed -- no agent call, and deterministic like everything else. The
single agent pass plugs into that same seam without any other part of this
module learning that an agent exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from grillui.log import IMAGE1_FILE, IMAGE2_FILE, LOG_FILE, RESULT_FILE, read_entries
from grillui.projector import conclusion_of, fold
from grillui.schemas import (
    PROPOSABLE_KINDS,
    SESSION_END_KIND,
    SESSION_START_KIND,
    CapturedDecision,
    CapturedThread,
    Decision,
    Image2,
    LogEntry,
    OpenItem,
    References,
    TerminalResult,
    TerminalSession,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    Summarizer = Callable[[TerminalResult], str]

ENDED_BY_HUMAN = "ended by the human"
NOT_FORMALLY_ENDED = "captured from a log carrying no session-end entry"


def default_summary(result: TerminalResult) -> str:
    """A briefing built from the structured parts, and never a transcript.

    Deterministic on purpose: the v1 default has to hold the seam open without
    making the result depend on a model being reachable, so what it says is
    counted rather than composed.
    """
    settled = [decision for decision in result.decisions if decision.status == "settled"]
    return (
        f"{result.session.title or result.session.id}: "
        f"{len(settled)} of {len(result.decisions)} decisions settled, "
        f"{len(result.open_items)} left open, "
        f"{len(result.threads)} side threads. {result.stop_reason}."
    )


def capture(directory: Path, *, summarize: Summarizer = default_summary) -> TerminalResult:
    """Fold the session directory's log into its terminal result.

    The log is the only thing read. The images are referenced rather than
    opened, because they are derived caches and a capture that trusted one
    would report a board no log ever held.
    """
    entries = read_entries(directory / LOG_FILE)
    image = fold(entries[-1].epoch if entries else "", entries)
    start = _first(entries, SESSION_START_KIND)
    end = _last(entries, SESSION_END_KIND)
    settled = {item.id for item in image.settled}

    result = TerminalResult(
        session=_session(directory, start, end, entries),
        references=References(log=LOG_FILE, image1=IMAGE1_FILE, image2=IMAGE2_FILE),
        decisions=[_captured(node) for node in image.decisions],
        open_items=[
            OpenItem(id=node.id, blocker=_blocker(node, settled, _waiting_on(image)))
            for node in image.decisions
            if node.status != "settled"
        ],
        threads=[
            CapturedThread(
                id=thread.id,
                title=thread.title,
                state=thread.state,
                conclusion=conclusion_of(thread),
            )
            for thread in image.threads
        ],
        summary="",
        stop_reason=_stop_reason(end),
    )
    return result.model_copy(update={"summary": summarize(result)})


def write_result(directory: Path, result: TerminalResult) -> Path:
    """Persist the terminal result beside the log it was folded from."""
    path = directory / RESULT_FILE
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path


def _session(
    directory: Path, start: LogEntry | None, end: LogEntry | None, entries: list[LogEntry]
) -> TerminalSession:
    """The session's identity, taken from the briefing the log carries.

    Read from `session-start` rather than from `handoff.json`: the handoff file
    lost its authority the moment that entry landed, and a capture run may find
    it edited or gone. The directory name is the fallback for a log that never
    carried a briefing, since that is what the session's id is by definition.
    """
    briefed = _mapping(start.payload.get("session")) if start else {}
    ended = end.timestamp if end else (entries[-1].timestamp if entries else "")
    return TerminalSession(
        id=_text(briefed, "id") or directory.name,
        title=_text(briefed, "title"),
        created=_text(briefed, "created") or (entries[0].timestamp if entries else ""),
        ended=ended,
    )


def _captured(node: Decision) -> CapturedDecision:
    return CapturedDecision(
        id=node.id,
        title=node.title,
        answer=_answer(node),
        status=node.status,
        rationale=node.rationale or "",
    )


def _answer(node: Decision) -> str | None:
    if node.answer is None:
        return None
    return node.answer.text or node.answer.option


def _waiting_on(image: Image2) -> set[str]:
    """Decisions with a change queued against them when the session ended.

    A lock has two sources and they say different things to whoever reads the
    result: an alert is the agent flagging a question, and a queued proposal is
    a change the human never got to. Reporting both as an alert would send them
    looking for a warning nobody sent.
    """
    return {
        item.target
        for item in image.pending
        if item.target and not item.superseded and item.kind in PROPOSABLE_KINDS
    }


def _blocker(node: Decision, settled: set[str], waiting: set[str]) -> str:
    """What stopped this decision, in the order that decides which one to say.

    A decision can be blocked several ways at once -- fogged behind an
    unanswered prerequisite it also lists -- and the human reading the result
    needs the reason that actually has to move first, not a list.
    """
    if node.status == "invalidated":
        return node.rationale or "invalidated"
    if node.status == "stale":
        return "rests on an answer that was withdrawn"
    if node.id in waiting:
        return "a proposed change is waiting on it"
    if node.locked:
        return "locked by a blocking alert"
    if node.status == "fogged":
        return f"fogged until {node.fog_until!r} is settled"
    unmet = [prereq for prereq in node.prereqs if prereq not in settled]
    if unmet:
        return "waits on " + ", ".join(repr(prereq) for prereq in unmet)
    return "answerable and unanswered"


def _stop_reason(end: LogEntry | None) -> str:
    if end is None:
        return NOT_FORMALLY_ENDED
    stated = end.payload.get("stop_reason")
    return stated if isinstance(stated, str) and stated else ENDED_BY_HUMAN


def _first(entries: list[LogEntry], kind: str) -> LogEntry | None:
    return next((entry for entry in entries if entry.kind == kind), None)


def _last(entries: list[LogEntry], kind: str) -> LogEntry | None:
    return next((entry for entry in reversed(entries) if entry.kind == kind), None)


def _mapping(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, dict) else {}


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


__all__ = ["capture", "default_summary", "write_result"]
