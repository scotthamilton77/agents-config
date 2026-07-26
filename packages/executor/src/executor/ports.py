"""The two injected ports and their real, subprocess-backed implementations.

S9T1-D1: the executor reaches the runtime and the tracker only through their
CLI JSON envelopes, behind `RuntimePort` and `TrackerPort`. Everything above
this module takes ports as arguments, which is what lets the whole unit suite
run with both faked and neither binary on PATH.

`SubprocessRunner` is the only class here that spawns a process; both real
ports sit on the injected `Runner` seam above it, so their envelope handling is
testable without a real `grind` or `work`.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeGuard, cast, runtime_checkable

from executor.envelope import ErrorCode, ExecutorError, JsonValue
from executor.state import RunState, parse_state

# Marks an ExecutorError raised *after* the runtime durably wrote the event:
# the write happened, the transition did not. The two are separate facts and a
# report that conflates them contradicts the event log — an audit reading
# `event_appended: false` against a log that holds the event is worse served
# than by no field at all. Internal to the port/enact seam; it never reaches
# the envelope under this name.
EVENT_WAS_WRITTEN = "_event_was_written"

_TIMEOUT_S = 120
# The exit code a shell reports for "command not found"; reused here so a
# missing binary is reported as a failed call rather than as an exception
# escaping the port.
_NOT_FOUND = 127


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str

    def transcript(self, argv: Sequence[str]) -> str:
        """argv, exit code and both streams -- what an operator needs to
        remediate without re-running the command themselves."""
        streams = " ".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part)
        return f"`{' '.join(argv)}` exited {self.exit_code}: {streams or '(no output)'}"


@runtime_checkable
class Runner(Protocol):
    """The subprocess seam. One method, so a test double is three lines."""

    def run(self, argv: Sequence[str]) -> CommandResult: ...  # pragma: no cover


class SubprocessRunner:
    """The real runner. A missing binary and a timeout are returned as failed
    results, not raised: every failure in this package reaches the caller as an
    `ExecutorError` carrying a code, and a bare `FileNotFoundError` would not."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        try:
            proc = subprocess.run(  # fixed argv, no shell
                list(argv), capture_output=True, text=True, timeout=_TIMEOUT_S, check=False
            )
        except FileNotFoundError as exc:
            return CommandResult(_NOT_FOUND, "", f"not found: {exc}")
        except subprocess.TimeoutExpired:
            return CommandResult(_NOT_FOUND, "", f"timed out after {_TIMEOUT_S}s")
        except OSError as exc:
            # A resolved binary can still fail to launch -- no execute
            # permission, a bad executable format, a exhausted process table.
            # Those are transport problems, and letting one escape would have
            # the CLI reduce it to a non-retryable internal error, hiding the
            # actionable reason.
            return CommandResult(_NOT_FOUND, "", f"cannot launch: {exc}")
        return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")


@dataclass(frozen=True)
class StalenessVerdict:
    """`grind check`'s answer. `stale` is a verdict, never a failure."""

    stale: bool
    age_s: float
    last_event_ts: str | None


@runtime_checkable
class RuntimePort(Protocol):
    """Read the fold, append an event, probe staleness. No decision lives
    behind this port -- the runtime reports facts."""

    def state(self) -> RunState: ...  # pragma: no cover

    def append(
        self, event_type: str, payload: Mapping[str, JsonValue]
    ) -> None: ...  # pragma: no cover

    def staleness(self, max_age: str | None = None) -> StalenessVerdict: ...  # pragma: no cover


@runtime_checkable
class TrackerPort(Protocol):
    """The facade verbs the S9T1-D12 table names, plus `sync`.

    Every argument is a tracker handle, never a run-local slug -- routing
    happens above this port, so a port implementation never has to know the
    difference.
    """

    def claim(self, handle: str) -> None: ...  # pragma: no cover

    def park(self, handle: str, *, reason: str, note: str) -> None: ...  # pragma: no cover

    def redispatch(self, handle: str) -> None: ...  # pragma: no cover

    def abandon(self, handle: str) -> None: ...  # pragma: no cover

    def close(self, handle: str) -> None: ...  # pragma: no cover

    def sync(self) -> None: ...  # pragma: no cover


def _is_ok_envelope(decoded: JsonValue) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(decoded, dict) and decoded.get("ok") is True


def _envelope_message(decoded: JsonValue, fallback: str) -> str:
    """The nested `error.message` both facades emit, when there is one."""
    if isinstance(decoded, dict):
        error = decoded.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message != "":
                return message
    return fallback


def _decode(
    result: CommandResult,
    argv: Sequence[str],
    *,
    subprocess_code: ErrorCode,
    envelope_code: ErrorCode,
) -> JsonValue:
    """Both CLIs promise exactly one JSON envelope on stdout, failures included.

    A reply that is not JSON is only an envelope fault when the process
    otherwise succeeded; when it also exited non-zero, the process failure is
    the more useful diagnosis and wins.
    """
    try:
        return cast("JsonValue", json.loads(result.stdout))
    except json.JSONDecodeError:
        if result.exit_code != 0:
            raise ExecutorError(subprocess_code, result.transcript(argv)) from None
        raise ExecutorError(
            envelope_code, f"unparseable reply: {result.transcript(argv)}"
        ) from None


def _anomaly_reason(reply: Mapping[str, JsonValue], fallback: str = "no reason given") -> str:
    """The runtime's own account of why the event did not apply."""
    anomaly = reply.get("anomaly")
    if isinstance(anomaly, dict):
        reason = anomaly.get("reason")
        if isinstance(reason, str) and reason != "":
            return reason
    return fallback


def _number(value: JsonValue) -> float | None:
    # `bool` is an `int` subclass, and `true` is not an age.
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class GrindRuntime:
    """`RuntimePort` over the `grind` console script.

    `grind_dir` is passed through as `--dir` when set. Leaving it unset hands
    the decision to the runtime's own ambient resolution, which is what a
    caller running inside a grind directory wants.
    """

    def __init__(self, runner: Runner, *, grind_dir: str | None = None) -> None:
        self._runner = runner
        self._grind_dir = grind_dir

    def _argv(self, *args: str) -> list[str]:
        argv = ["grind", *args]
        if self._grind_dir is not None:
            argv.extend(["--dir", self._grind_dir])
        return argv

    def _call(self, *args: str, verdict_in_exit_code: bool = False) -> dict[str, JsonValue]:
        """Run one runtime command and return its `ok: true` envelope.

        A non-zero exit is a failure everywhere except the one verb whose exit
        code carries a verdict rather than an outcome (S9T1-A3 scopes that to
        `grind check`). Ignoring the exit code generally would let a wrapper
        or post-command failure read as success, and the executor would go on
        to enact the other side of the pairing.
        """
        argv = self._argv(*args)
        result = self._runner.run(argv)
        decoded = _decode(
            result,
            argv,
            subprocess_code=ErrorCode.RUNTIME_SUBPROCESS,
            envelope_code=ErrorCode.RUNTIME_ENVELOPE,
        )
        failed = not _is_ok_envelope(decoded) or (
            result.exit_code != 0 and not verdict_in_exit_code
        )
        if failed:
            raise ExecutorError(
                ErrorCode.RUNTIME_SUBPROCESS,
                _envelope_message(decoded, result.transcript(argv)),
            )
        assert isinstance(decoded, dict)  # noqa: S101  # proven by _is_ok_envelope above
        return decoded

    def state(self) -> RunState:
        return parse_state(self._call("status", "--full").get("state"))

    def append(self, event_type: str, payload: Mapping[str, JsonValue]) -> None:
        """Append one event, refusing the runtime's accept-and-flag outcome.

        An event that is well-shaped but illegal from the entity's current
        state is still written, as `ok: true` with `applied: false` and an
        anomaly record -- the runtime records a flag, not a transition.
        Reading only `ok` would let the executor report a pairing it did not
        enact, so the flag becomes a typed failure here. The event is on disk
        either way; that is what the message says.
        """
        reply = self._call("log", event_type, "--json", json.dumps(dict(payload)))
        applied = reply.get("applied")
        if applied is True:
            return
        if applied is False:
            raise ExecutorError(
                ErrorCode.USAGE,
                f"the runtime recorded {event_type} as an anomaly rather than a transition: "
                f"{_anomaly_reason(reply)}",
                {EVENT_WAS_WRITTEN: True},
            )
        # Absent or mistyped: an incompatible or corrupt runtime. Treating
        # "not false" as applied would report a transition on no evidence at
        # all, which is the failure this check exists to prevent.
        raise ExecutorError(
            ErrorCode.RUNTIME_ENVELOPE,
            f"the runtime's reply to {event_type} carries no usable `applied` flag: {applied!r}",
        )

    def staleness(self, max_age: str | None = None) -> StalenessVerdict:
        """`grind check` exits 1 on a stale verdict while emitting `ok: true`.

        The verdict rides the envelope; the exit code is a second, redundant
        copy of it. Because `_call` reads the envelope and never the exit code,
        a stale grind cannot surface here as a crashed subprocess.
        """
        args = ("check",) if max_age is None else ("check", "--max-age", max_age)
        decoded = self._call(*args, verdict_in_exit_code=True)
        ts = decoded.get("last_event_ts")
        return StalenessVerdict(
            stale=decoded.get("stale") is True,
            age_s=_number(decoded.get("age_s")) or 0.0,
            last_event_ts=ts if isinstance(ts, str) else None,
        )


class WorkTracker:
    """`TrackerPort` over the `work` console script -- the only tracker
    interface this package has. The backend behind the facade is the facade's
    business; nothing here names it."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def _call(self, argv: Sequence[str], *, code: ErrorCode) -> None:
        result = self._runner.run(argv)
        # No dedicated code exists for a garbled facade reply (S9T1-D11 gives
        # the tracker side one code), so both faults report as the same
        # retryable transport failure.
        decoded = _decode(result, argv, subprocess_code=code, envelope_code=code)
        # No facade verb carries a verdict in its exit code, so a non-zero exit
        # is a failure whatever the envelope says.
        if not _is_ok_envelope(decoded) or result.exit_code != 0:
            raise ExecutorError(code, _envelope_message(decoded, result.transcript(argv)))

    def claim(self, handle: str) -> None:
        self._call(["work", "claim", handle], code=ErrorCode.TRACKER_SUBPROCESS)

    def park(self, handle: str, *, reason: str, note: str) -> None:
        self._call(
            ["work", "park", handle, "--reason", reason, "--note", note],
            code=ErrorCode.TRACKER_SUBPROCESS,
        )

    def redispatch(self, handle: str) -> None:
        self._call(["work", "redispatch", handle], code=ErrorCode.TRACKER_SUBPROCESS)

    def abandon(self, handle: str) -> None:
        self._call(["work", "abandon", handle], code=ErrorCode.TRACKER_SUBPROCESS)

    def close(self, handle: str) -> None:
        self._call(["work", "close", handle], code=ErrorCode.TRACKER_SUBPROCESS)

    def sync(self) -> None:
        """A failed sync is its own code: the mutations already landed, and the
        repair is running `work sync` again, never re-running the command that
        made them (S9T1-D9)."""
        self._call(["work", "sync"], code=ErrorCode.SYNC_FAILED)
