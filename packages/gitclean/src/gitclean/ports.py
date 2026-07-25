"""The subprocess seam. The only module in the package that shells out.

Everything above this file is pure: it receives ``CommandResult`` values and
returns data. That is what makes the classification rules testable without a
fixture repo, and it is why ``ScriptedCommands`` fails loudly on an unscripted
call -- a silent default would let a test pass while the real tool asks git a
question nobody predicted.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_DEFAULT_TIMEOUT = 60


@dataclass(frozen=True, slots=True)
class CommandResult:
    """One command's full outcome, kept whole.

    stdout and stderr are retained even on success because an anomaly found
    two steps later still needs the transcript of what led there."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def out(self) -> str:
        return self.stdout.strip()

    def transcript(self) -> tuple[str, ...]:
        """Reader-facing rendering: the command, its exit code, and its output.

        Empty streams are omitted rather than shown as blank headings."""
        lines = [f"$ {' '.join(self.argv)}", f"exit: {self.returncode}"]
        if self.stdout.strip():
            lines.append("stdout:\n" + self.stdout.rstrip())
        if self.stderr.strip():
            lines.append("stderr:\n" + self.stderr.rstrip())
        return tuple(lines)


@runtime_checkable
class CommandPort(Protocol):
    """Injected process runner for the two CLIs gitclean speaks."""

    def git(
        self, args: Sequence[str], *, cwd: Path | None = None
    ) -> CommandResult: ...  # pragma: no cover

    def gh(
        self, args: Sequence[str], *, cwd: Path | None = None
    ) -> CommandResult: ...  # pragma: no cover

    def has_gh(self) -> bool: ...  # pragma: no cover

    def read_text(self, path: Path) -> str | None: ...  # pragma: no cover

    def write_text(self, path: Path, content: str) -> None: ...  # pragma: no cover

    def copy_file(self, src: Path, dest: Path) -> None: ...  # pragma: no cover

    def exists(self, path: Path) -> bool: ...  # pragma: no cover


class SubprocessCommands:
    """Real ``CommandPort``: git and gh via subprocess, plus the filesystem
    writes salvage needs."""

    def __init__(self, *, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    def _run(self, argv: list[str], cwd: Path | None) -> CommandResult:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                cwd=str(cwd) if cwd else None,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                argv=tuple(argv),
                returncode=124,
                stdout="",
                stderr=f"timed out after {self._timeout}s",
            )
        except (FileNotFoundError, OSError) as exc:
            return CommandResult(argv=tuple(argv), returncode=127, stdout="", stderr=str(exc))
        return CommandResult(
            argv=tuple(argv),
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

    def git(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
        return self._run(["git", *args], cwd)

    def gh(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
        return self._run(["gh", *args], cwd)

    def has_gh(self) -> bool:
        return shutil.which("gh") is not None

    def read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def copy_file(self, src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    def exists(self, path: Path) -> bool:
        return path.exists()


class ScriptedCommands:
    """Test fake. Answers are keyed by the argv prefix that identifies the
    question, so tests read as 'when git is asked X, say Y' rather than as a
    call-order transcript that breaks on every refactor.

    An unmatched call raises, naming the argv. Returning a benign default
    instead would let a test go green while production asks git something the
    test never anticipated -- the exact failure this fake exists to prevent.
    """

    def __init__(
        self,
        *,
        git: dict[str, CommandResult | list[CommandResult]] | None = None,
        gh: dict[str, CommandResult | list[CommandResult]] | None = None,
        has_gh: bool = True,
        files: dict[str, str] | None = None,
    ) -> None:
        self._git = dict(git or {})
        self._gh = dict(gh or {})
        self._has_gh = has_gh
        self.files: dict[str, str] = dict(files or {})
        self.copies: list[tuple[str, str]] = []
        self.transcript: list[tuple[str, ...]] = []

    @staticmethod
    def _match(
        table: dict[str, CommandResult | list[CommandResult]], argv: tuple[str, ...]
    ) -> CommandResult | None:
        joined = " ".join(argv)
        for key in sorted(table, key=len, reverse=True):
            if joined.startswith(key):
                slot = table[key]
                if isinstance(slot, list):
                    if not slot:
                        return None
                    return slot.pop(0)
                return slot
        return None

    def _dispatch(
        self,
        table: dict[str, CommandResult | list[CommandResult]],
        tool: str,
        args: Sequence[str],
    ) -> CommandResult:
        argv = (tool, *args)
        self.transcript.append(argv)
        found = self._match(table, tuple(args))
        if found is None:
            raise AssertionError(f"ScriptedCommands has no answer for: {' '.join(argv)}")
        return CommandResult(
            argv=argv,
            returncode=found.returncode,
            stdout=found.stdout,
            stderr=found.stderr,
        )

    def git(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,  # noqa: ARG002  # protocol parameter; the fake is cwd-blind
    ) -> CommandResult:
        return self._dispatch(self._git, "git", args)

    def gh(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,  # noqa: ARG002  # protocol parameter; the fake is cwd-blind
    ) -> CommandResult:
        return self._dispatch(self._gh, "gh", args)

    def has_gh(self) -> bool:
        return self._has_gh

    def read_text(self, path: Path) -> str | None:
        return self.files.get(str(path))

    def write_text(self, path: Path, content: str) -> None:
        self.files[str(path)] = content

    def copy_file(self, src: Path, dest: Path) -> None:
        self.copies.append((str(src), str(dest)))

    def exists(self, path: Path) -> bool:
        return str(path) in self.files


def ok(stdout: str = "", *, stderr: str = "") -> CommandResult:
    """Terse constructor for scripted success."""
    return CommandResult(argv=(), returncode=0, stdout=stdout, stderr=stderr)


def fail(stderr: str = "", *, code: int = 1, stdout: str = "") -> CommandResult:
    """Terse constructor for scripted failure."""
    return CommandResult(argv=(), returncode=code, stdout=stdout, stderr=stderr)
