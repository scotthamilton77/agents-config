"""EscalationSink abstraction (§5).

The CLI never calls ``bd label add`` directly from contract code; escalation
routing goes through a :class:`Sink` so prgroom works with or without beads.
Three adapters are envisaged (§5): ``stderr`` (default), ``file`` (JSONL for
external watchers), and ``bd`` (v2, deferred). The foundation ships stderr + file.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol, runtime_checkable

from prgroom.prsession.pr_ref import PRRef

if TYPE_CHECKING:
    from prgroom.prsession.state import ReviewItem


class Severity(StrEnum):
    """Escalation severity. Part of the file-sink JSONL wire contract."""

    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class Escalation:
    """One escalation event (§5). ``item`` is the optional triggering review item."""

    pr: PRRef
    reason: str
    severity: Severity
    item: ReviewItem | None = None

    def to_jsonable(self) -> dict[str, object]:
        """Flat, public-safe dict for the file sink's JSONL line."""
        payload: dict[str, object] = {
            "pr": self.pr.display(),
            "reason": self.reason,
            "severity": self.severity.value,
        }
        if self.item is not None:
            payload["item_gh_id"] = self.item.identity.gh_id
        return payload


@runtime_checkable
class Sink(Protocol):
    """Records ("files", verb-sense) an :class:`Escalation`. Implemented by the
    stderr / file / (later) bd adapters."""

    def emit(self, escalation: Escalation) -> None: ...  # pragma: no cover


class StderrSink:
    """Default sink (chat/interactive). Pretty-prints to a stream (stderr by default)."""

    def __init__(self, *, stream: IO[str] | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def emit(self, escalation: Escalation) -> None:
        self._stream.write(
            f"prgroom escalation [{escalation.severity.value}] "
            f"{escalation.pr.display()}: {escalation.reason}\n"
        )


class FileSink:
    """File sink. Appends one JSON line per escalation; used by external watchers / cron."""

    def __init__(self, *, path: Path) -> None:
        self._path = path

    def emit(self, escalation: Escalation) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(escalation.to_jsonable()) + "\n")
