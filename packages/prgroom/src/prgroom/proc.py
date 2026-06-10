"""The subprocess-runner injection seam (§7.6).

The gh and git adapters do not call :func:`subprocess.run` directly. Every
external command goes through the :class:`CommandRunner` Protocol, so the single
system boundary is injectable: production wires :class:`SubprocessRunner`; tests
inject a recorded-response fake. This mirrors the ``Clock`` / ``Randomness``
seams in :mod:`prgroom.deps` — the concrete runner **structurally satisfies**
the Protocol (no inheritance); ``mypy --strict`` checks the fit.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The captured outcome of one external command — the boundary's data shape."""

    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class CommandRunner(Protocol):
    """Runs one external command and returns its captured result.

    The adapters depend on this, never on :mod:`subprocess` directly, so the
    boundary is a single injectable seam.
    """

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # stdlib name; matches subprocess.run's keyword
        timeout: float | None = None,
    ) -> CommandResult: ...  # pragma: no cover


class SubprocessRunner:
    """Production runner. Wraps :func:`subprocess.run`; the real system boundary.

    Always non-raising on a non-zero exit (``check=False``) — the adapters
    classify failures from the returncode + stderr themselves, mapping to the
    structured :class:`~prgroom.errors.ErrorCode` registry rather than letting a
    raw ``CalledProcessError`` escape.
    """

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # stdlib name; matches subprocess.run's keyword
        timeout: float | None = None,
    ) -> CommandResult:
        completed = subprocess.run(  # noqa: S603  # argv is internally built (gh/git verb + typed args), never shell-interpolated user input; this IS the sanctioned boundary
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            input=input,
            timeout=timeout,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
