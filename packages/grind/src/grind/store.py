"""events.jsonl I/O: the write-path torn-tail repair, append, and read-back.

The write-path repair belongs here, not in `grind.log` (spec "Torn tail":
"the write path repairs before it appends"; `grind.log`'s docstring calls this
"a later bead" -- this module is that bead). `grind.log` stays the read-only,
defense-in-depth half: it tolerates an unrepaired torn tail for a log read
before any write-path call has touched it (e.g. `status` on a freshly-crashed
grind), but never writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from grind.jsonio import NonFiniteJsonError, loads
from grind.log import fold_log, parse_event_log
from grind.model import JsonValue, RawEvent, State

EVENTS_FILENAME = "events.jsonl"
QUARANTINE_FILENAME = "events.quarantine"
STATE_FILENAME = "state.json"


@dataclass(frozen=True)
class TornTailRepair:
    """One write-path repair (spec "Torn tail"): `quarantined` distinguishes a
    durable-but-unterminated event (repaired in place, `quarantined=False`)
    from a genuinely unparsable fragment (moved to the quarantine sidecar,
    `quarantined=True`)."""

    quarantined: bool
    reason: str


def events_path(dir_: Path) -> Path:
    return dir_ / EVENTS_FILENAME


def quarantine_path(dir_: Path) -> Path:
    return dir_ / QUARANTINE_FILENAME


def state_path(dir_: Path) -> Path:
    return dir_ / STATE_FILENAME


def read_raw_log(dir_: Path) -> str:
    path = events_path(dir_)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def is_log_nonempty(dir_: Path) -> bool:
    return read_raw_log(dir_).strip() != ""


def repair_torn_tail(dir_: Path) -> TornTailRepair | None:
    """Repair an unterminated final line before the next append (spec "Torn tail").

    A crash mid-append can leave a truncated final line; simply dropping it at
    fold time (`grind.log`'s defense-in-depth) doesn't make the log appendable
    again, since the next append would concatenate onto the fragment. This
    inspects the log's final byte: a line that still parses as a complete JSON
    object is a durable transition that only lost its trailing newline, so the
    repair is appending the missing newline. An unparsable fragment is moved to
    the append-only `events.quarantine` sidecar (never deleted) and the log
    truncated back to its last complete line. Returns `None` when the log
    already ends in a newline (or doesn't exist) -- no repair needed.
    """
    path = events_path(dir_)
    if not path.exists():
        return None
    raw = path.read_bytes()
    if raw == b"" or raw.endswith(b"\n"):
        return None

    last_newline = raw.rfind(b"\n")
    head = raw[: last_newline + 1]  # everything through the prior newline, or b"" if none
    tail = raw[last_newline + 1 :]

    try:
        parsed: JsonValue = loads(tail.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, NonFiniteJsonError):
        parsed = None

    if isinstance(parsed, dict):
        path.write_bytes(raw + b"\n")
        return TornTailRepair(
            quarantined=False,
            reason="torn_tail: final line was a complete event missing its trailing newline",
        )

    with quarantine_path(dir_).open("ab") as sidecar:
        sidecar.write(tail if tail.endswith(b"\n") else tail + b"\n")
    path.write_bytes(head)
    return TornTailRepair(
        quarantined=True,
        reason="torn_tail: final line did not parse as an event and was quarantined",
    )


def append_event(dir_: Path, event: RawEvent) -> TornTailRepair | None:
    """Repair a torn tail (if any), then append `event` as one JSON line."""
    dir_.mkdir(parents=True, exist_ok=True)
    repair = repair_torn_tail(dir_)
    with events_path(dir_).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True, allow_nan=False))
        fh.write("\n")
    return repair


def load_events(dir_: Path) -> list[RawEvent]:
    """The parsed event list, tolerating an unrepaired torn tail (dropped, not raised)."""
    text = read_raw_log(dir_)
    if text.strip() == "":
        return []
    return parse_event_log(text).events


def fold_dir(dir_: Path) -> State:
    """Refold from zero over the on-disk log (spec: "the fold refolds from zero
    on every command")."""
    return fold_log(read_raw_log(dir_))


def write_state(dir_: Path, payload: dict[str, JsonValue]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    with state_path(dir_).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
