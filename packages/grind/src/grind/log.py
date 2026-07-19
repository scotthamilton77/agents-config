"""Reading `events.jsonl` text into events, and composing that with `fold`.

This module only *reads*. The write-path repair described in the spec's
"Torn tail" section (moving an unparsable fragment to `events.quarantine`,
appending the missing newline to a complete-but-unterminated line) belongs to
the CLI's append path (a later bead) -- this module is the defense-in-depth
half: it tolerates a torn tail when reading a log no repair has touched yet
(e.g. `status` on a freshly-crashed grind), per spec: "the fold still
tolerates a non-parsing last line (drops it, reports the torn_tail anomaly)".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from grind.fold import fold
from grind.jsonio import NonFiniteJsonError, loads
from grind.model import AnomalyRecord, AttentionEntry, JsonValue, Observation, RawEvent, State


class LogCorruptionError(ValueError):
    """A non-tail line failed to parse as a JSON object.

    Only the log's final line gets torn-tail tolerance (a crash mid-append
    can only ever truncate the line being written, never an earlier one) --
    corruption anywhere else is a real integrity problem, not a crash
    artifact, so this raises instead of silently dropping data.
    """


@dataclass
class ParsedLog:
    events: list[RawEvent] = field(default_factory=list)
    torn_tail: bool = False


def parse_event_log(text: str) -> ParsedLog:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline produces one empty trailing element

    events: list[RawEvent] = []
    torn_tail = False
    last_index = len(lines) - 1
    for index, line in enumerate(lines):
        if line.strip() == "":
            continue
        try:
            parsed: JsonValue = loads(line)
        except (json.JSONDecodeError, NonFiniteJsonError) as exc:
            if index == last_index:
                torn_tail = True
                continue
            raise LogCorruptionError(f"malformed event log line {index}: {line!r}") from exc
        if not isinstance(parsed, dict):
            raise LogCorruptionError(f"event log line {index} is not a JSON object: {line!r}")
        events.append(parsed)

    return ParsedLog(events=events, torn_tail=torn_tail)


def fold_log(text: str) -> State:
    """Parse `text` and fold it, annotating the result with a torn-tail anomaly if found."""
    parsed = parse_event_log(text)
    state = fold(parsed.events)
    if parsed.torn_tail:
        message = "torn_tail: log's final line did not parse and was dropped"
        # A torn tail is a non-event anomaly (no ts/item/lane -- the dropped
        # fragment never parsed into an event), so consumers of the fold's
        # anomaly projection see it alongside event anomalies, distinct from a
        # plain ERROR observation (spec: the reader "reports the torn_tail
        # anomaly").
        state.anomalies.append(
            AnomalyRecord(ts=None, type="torn_tail", item=None, lane=None, reason=message)
        )
        state.observations.append(Observation(level="ERROR", message=message))
        state.attention.append(AttentionEntry(text=message, auto=True))
    return state
