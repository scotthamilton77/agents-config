"""Test fakes for the subprocess boundary (§7.6).

The gh/git adapters reach the outside world through a single seam — the
:class:`~prgroom.proc.CommandRunner` Protocol. These fakes structurally satisfy
that Protocol so adapter tests inject recorded responses instead of mocking code
we own. This is the spec's "mock only at the system boundary" discipline: the
boundary is the subprocess call, and a runner is the smallest honest stand-in
for it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from prgroom.proc import CommandResult


class RecordedRunner:
    """A :class:`CommandRunner` fake that replays queued results in FIFO order.

    Each :meth:`run` pops the next recorded :class:`CommandResult` and records
    the argv it was called with, so a test can both feed a recorded
    gh/git response and assert the adapter built the right command line. Running
    dry (more calls than recorded results) raises — a silent empty result would
    mask an adapter issuing an unexpected extra call.
    """

    def __init__(self, results: Sequence[CommandResult]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # matches the Protocol's keyword name
        timeout: float | None = None,  # noqa: ARG002  # recorded runner ignores timeout
    ) -> CommandResult:
        self.calls.append(list(argv))
        self.inputs.append(input)
        if not self._results:
            msg = f"RecordedRunner exhausted: unexpected call {list(argv)!r}"
            raise AssertionError(msg)
        return self._results.pop(0)


class TimeoutRunner:
    """A :class:`CommandRunner` fake that always raises ``TimeoutExpired``.

    Models the network-timeout boundary failure the git adapter must classify
    as ``RUNTIME_GIT_TRANSIENT`` (and the gh adapter could see too).
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: ARG002  # part of the Protocol signature; unused here
        timeout: float | None = None,
    ) -> CommandResult:  # pragma: no cover - never returns; raises below
        self.calls.append(list(argv))
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout or 0.0)
