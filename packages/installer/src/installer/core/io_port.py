"""I/O seam for the installer.

Every prompt, diff, header, and log line in the installer is routed
through `IOPort` so that test code can substitute `ScriptedIO` and unit-
test the engine without a terminal. `TerminalIO` is the real
implementation backed by `rich`; `ScriptedIO` is a recording fake driven
by pre-loaded per-method answer queues.

See `docs/specs/2026-05-19-w1qls.1.3-io-port-design.md` for the rationale
behind every design decision in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from rich.console import Console

# ───────────────────────── Value types ─────────────────────────


@dataclass(frozen=True, slots=True)
class PerItemResult:
    """Return type of `IOPort.confirm_per_item`.

    `decisions` carries only the items the user answered (label → keep?);
    on a quit-mid-loop the dict is incomplete. `quit` makes the
    incomplete case explicit so consumers branch on `.quit` rather than
    comparing `len(decisions)` to the input length."""

    decisions: dict[str, bool]
    quit: bool


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """One record per call to `ScriptedIO`. The transcript is the test's
    primary assertion surface — channel, message, verbose flag, and a
    channel-specific payload. Payload semantics:

      - output channels (info/ok/warn/err/header): None
      - diff: (old: bytes, new: bytes) tuple
      - confirm: the bool answer popped from the queue
      - confirm_three_way: the str answer popped from the queue
      - confirm_per_item: the PerItemResult popped from the queue
    """

    channel: Literal[
        "info", "ok", "warn", "err", "header",
        "diff",
        "confirm", "confirm_three_way", "confirm_per_item",
    ]
    message: str
    verbose: bool = False
    payload: object | None = None


class ScriptExhaustedError(RuntimeError):
    """Raised when ScriptedIO is asked for a prompt answer beyond its
    pre-loaded queue. Message names which queue ran dry, the prompt that
    triggered the over-pop, and the last few transcript entries - so a
    test failure is self-diagnosing without rerunning under a debugger."""


# ───────────────────────── Protocol ─────────────────────────


@runtime_checkable
class IOPort(Protocol):
    """Single injectable abstraction for every prompt, diff, header, and
    log line in the installer. No module other than this one may import
    `rich` or call `print` / `input` directly."""

    def info(self, message: str, *, verbose: bool = False) -> None: ...
    def ok(self, message: str, *, verbose: bool = False) -> None: ...
    def warn(self, message: str, *, verbose: bool = False) -> None: ...
    def err(self, message: str, *, verbose: bool = False) -> None: ...
    def header(self, message: str, *, verbose: bool = False) -> None: ...

    def show_diff(self, label: str, old: bytes, new: bytes) -> None: ...

    def confirm(self, message: str, *, default: bool = False) -> bool: ...
    def confirm_three_way(
        self,
        message: str,
        *,
        choices: tuple[str, str, str],
        default: str | None = None,
    ) -> str: ...
    def confirm_per_item(
        self,
        message: str,
        *,
        items: list[str],
    ) -> PerItemResult: ...

    def is_interactive(self) -> bool: ...


# ───────────────────────── TerminalIO (stub) ─────────────────────────


class TerminalIO:
    """Real I/O implementation backed by rich. Stub for Slice 1 - methods
    raise NotImplementedError; Slice 3 (Tasks 5-6) implements them.

    Holds two Console instances (stdout + stderr) and a verbose flag so
    `err()` can route to stderr and verbose-tagged output can be
    suppressed by default. Console injection at construction time keeps
    unit tests from touching real terminal I/O."""

    def __init__(
        self,
        *,
        stdout: Console | None = None,
        stderr: Console | None = None,
        verbose: bool = False,
    ) -> None:
        self._out = stdout if stdout is not None else Console()
        self._err = stderr if stderr is not None else Console(stderr=True)
        self._verbose = verbose

    def info(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def ok(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def warn(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def err(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def header(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def show_diff(self, label: str, old: bytes, new: bytes) -> None:
        raise NotImplementedError

    def confirm(self, message: str, *, default: bool = False) -> bool:
        raise NotImplementedError

    def confirm_three_way(
        self,
        message: str,
        *,
        choices: tuple[str, str, str],
        default: str | None = None,
    ) -> str:
        raise NotImplementedError

    def confirm_per_item(
        self,
        message: str,
        *,
        items: list[str],
    ) -> PerItemResult:
        raise NotImplementedError

    def is_interactive(self) -> bool:
        raise NotImplementedError


# ───────────────────────── ScriptedIO (stub) ─────────────────────────


class ScriptedIO:
    """Test fake. Stub for Slice 1 - methods raise NotImplementedError;
    Slice 2 (Tasks 3-4) implements them. The transcript list is
    initialized empty so `isinstance(io, IOPort)` works without invoking
    any prompt."""

    def __init__(
        self,
        *,
        confirms: list[bool] | None = None,
        three_ways: list[str] | None = None,
        per_items: list[PerItemResult] | None = None,
        interactive: bool = True,
    ) -> None:
        self._confirms = list(confirms) if confirms is not None else []
        self._three_ways = list(three_ways) if three_ways is not None else []
        self._per_items = list(per_items) if per_items is not None else []
        self._interactive = interactive
        self.transcript: list[TranscriptEntry] = []

    def info(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def ok(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def warn(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def err(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def header(self, message: str, *, verbose: bool = False) -> None:
        raise NotImplementedError

    def show_diff(self, label: str, old: bytes, new: bytes) -> None:
        raise NotImplementedError

    def confirm(self, message: str, *, default: bool = False) -> bool:
        raise NotImplementedError

    def confirm_three_way(
        self,
        message: str,
        *,
        choices: tuple[str, str, str],
        default: str | None = None,
    ) -> str:
        raise NotImplementedError

    def confirm_per_item(
        self,
        message: str,
        *,
        items: list[str],
    ) -> PerItemResult:
        raise NotImplementedError

    def is_interactive(self) -> bool:
        raise NotImplementedError
