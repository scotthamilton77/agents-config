"""The git adapter — worktree plumbing via the ``git`` subprocess (§3.4, §7.6).

``GitCli`` shells out to ``git`` (rev-parse, rev-list, push, stash) through the
injected :class:`~prgroom.proc.CommandRunner` boundary and maps failures onto
the existing :class:`~prgroom.errors.ErrorCode` registry. The registry defines
exactly two git outcomes, so the classification is a clean dichotomy:

* a recognized **push rejection** (non-fast-forward, protected branch, hook
  decline) -> ``RUNTIME_PUSH_REJECTED`` (terminal — a blind retry is futile)
* **any other** non-zero exit or a boundary ``TimeoutExpired`` (network blip,
  transient lock) -> ``RUNTIME_GIT_TRANSIENT`` (retry on the next cadence)

There is deliberately no third "git-terminal" code in the registry; the
non-rejection branch is the registry's only non-rejection git code, so unknown
failures fall to transient rather than inventing a code.

``GitCli`` **structurally satisfies** :class:`GitClient` (no inheritance);
``mypy --strict`` checks the fit.
"""

from __future__ import annotations

import subprocess
from typing import Protocol, runtime_checkable

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.proc import CommandRunner

# Substrings git emits when a push is rejected by the remote. These are terminal
# (manual reconciliation required); everything else non-zero is transient.
_PUSH_REJECTED_MARKERS = (
    "[rejected]",
    "[remote rejected]",
    "non-fast-forward",
    "protected branch",
    "hook declined",
    "failed to push",
)


@runtime_checkable
class GitClient(Protocol):
    """The worktree-git surface the lifecycle verbs depend on (§3.4)."""

    def head_sha(self) -> str: ...  # pragma: no cover

    def rev_list(self, range_: str) -> list[str]: ...  # pragma: no cover

    def push(self, remote: str, branch: str) -> None: ...  # pragma: no cover

    def stash(self) -> None: ...  # pragma: no cover


def _transient(detail: str) -> PrgroomError:
    return PrgroomError(
        tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_GIT_TRANSIENT, detail=detail
    )


def _classify_git_failure(stderr: str) -> PrgroomError:
    """Map a failed ``git`` invocation to its registry error (§3.6/§3.7)."""
    if any(marker in stderr for marker in _PUSH_REJECTED_MARKERS):
        return PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_PUSH_REJECTED,
            detail=stderr.strip(),
        )
    return _transient(stderr.strip())


class GitCli:
    """git adapter. Structurally satisfies :class:`GitClient`."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def head_sha(self) -> str:
        return self._run(["git", "rev-parse", "HEAD"]).strip()

    def rev_list(self, range_: str) -> list[str]:
        out = self._run(["git", "rev-list", range_])
        return out.split()

    def push(self, remote: str, branch: str) -> None:
        self._run(["git", "push", remote, branch])

    def stash(self) -> None:
        self._run(["git", "stash"])

    def _run(self, argv: list[str]) -> str:
        try:
            result = self._runner.run(argv)
        except subprocess.TimeoutExpired as exc:
            # A hung network op never returns a code; it is unambiguously transient.
            detail = f"git timed out: {' '.join(argv)}"
            raise _transient(detail) from exc
        if result.returncode != 0:
            raise _classify_git_failure(result.stderr)
        return result.stdout
