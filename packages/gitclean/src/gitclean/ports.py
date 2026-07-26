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

    def write_text(self, path: Path, content: str) -> None: ...  # pragma: no cover

    def create_archive(self, source: Path, dest: Path) -> CommandResult: ...  # pragma: no cover

    def list_archive(self, path: Path) -> CommandResult: ...  # pragma: no cover


def _inside(inner: Path, outer: Path) -> bool:
    try:
        inner.resolve().relative_to(outer.resolve())
    except (ValueError, OSError):
        return False
    return True


def _self_exclusion(source: Path, dest: Path) -> list[str]:
    """Keep tar from archiving its own output directory.

    A caller is free to point --salvage-dir inside the very worktree being
    salvaged. The directory is created before tar runs, so without this it is
    captured as an empty directory in the archive of the tree it is saving."""
    if not _inside(dest.parent, source):
        return []
    relative = dest.parent.resolve().relative_to(source.resolve())
    # A salvage directory one level down is excluded whole; one that *is* the
    # worktree root cannot be, so only the archive file itself is skipped.
    if str(relative) == ".":
        return [f"--exclude=./{dest.name}"]
    return [f"--exclude=./{relative}"]


def _staging_path(source: Path, dest: Path) -> Path | None:
    """Where to write the archive so tar never writes into what it is reading.

    None when the destination already sits outside the source and tar can
    write straight to it.

    Excluding the output from the archive's *contents* is not enough: the
    directory still changes while tar walks it, and GNU tar exits 1 on
    `file changed as we read it`. BSD tar -- what ships on macOS -- says
    nothing, so this is invisible until the suite runs on Linux. Staging
    beside the source directory removes the race rather than tolerating it,
    and stays on the same filesystem so the move into place is a rename."""
    if not _inside(dest.parent, source):
        return None
    return source.parent / f".{dest.name}.gitclean-partial"


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

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def create_archive(self, source: Path, dest: Path) -> CommandResult:
        """Archive a whole directory, symlinks kept AS symlinks.

        tar rather than a file-by-file copy for three reasons that each cost
        work when got wrong: `shutil.copy2` follows symlinks by default, so an
        untracked link to ~/.ssh/id_rsa would copy the key's bytes into the
        salvage directory; it crashes outright on a dangling link; and a copy
        driven by `git ls-files` cannot see ignored files, which is where a
        .env lives. `.git` is excluded because it is reconstructible and, in
        the main worktree, would drag in the whole object store."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        excludes = ["--exclude=./.git", *_self_exclusion(source, dest)]
        staged = _staging_path(source, dest)
        written = staged if staged is not None else dest

        result = self._run(["tar", "-czf", str(written), "-C", str(source), *excludes, "."], None)

        if staged is None:
            return result
        if not result.ok:
            staged.unlink(missing_ok=True)
            return result
        try:
            shutil.move(str(staged), str(dest))
        except OSError as exc:
            # The archive exists but not where the caller will look for it, so
            # this is a failed salvage: the deletion it would authorise must
            # not proceed.
            staged.unlink(missing_ok=True)
            return CommandResult(
                argv=result.argv,
                returncode=1,
                stdout=result.stdout,
                stderr=f"could not move the archive into {dest.parent}: {exc}",
            )
        return result

    def list_archive(self, path: Path) -> CommandResult:
        return self._run(["tar", "-tzf", str(path)], None)


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
        archive_create: CommandResult | None = None,
        archive_list: CommandResult | None = None,
    ) -> None:
        self._git = dict(git or {})
        self._gh = dict(gh or {})
        self._has_gh = has_gh
        self.files: dict[str, str] = dict(files or {})
        self.transcript: list[tuple[str, ...]] = []
        # Same discipline as the command tables: an unscripted archive call
        # raises rather than defaulting, because a salvage that silently
        # "succeeded" in a test is the failure this fake exists to catch.
        self._archive_create = archive_create
        self._archive_list = archive_list
        self.archives: list[tuple[str, str]] = []

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

    def write_text(self, path: Path, content: str) -> None:
        self.files[str(path)] = content

    def create_archive(self, source: Path, dest: Path) -> CommandResult:
        self.transcript.append(("tar", "-czf", str(dest), "-C", str(source)))
        self.archives.append((str(source), str(dest)))
        if self._archive_create is None:
            raise AssertionError(f"ScriptedCommands has no archive answer for: {source} -> {dest}")
        return self._archive_create

    def list_archive(self, path: Path) -> CommandResult:
        self.transcript.append(("tar", "-tzf", str(path)))
        if self._archive_list is None:
            raise AssertionError(f"ScriptedCommands has no archive listing for: {path}")
        return self._archive_list


def ok(stdout: str = "", *, stderr: str = "") -> CommandResult:
    """Terse constructor for scripted success."""
    return CommandResult(argv=(), returncode=0, stdout=stdout, stderr=stderr)


def fail(stderr: str = "", *, code: int = 1, stdout: str = "") -> CommandResult:
    """Terse constructor for scripted failure."""
    return CommandResult(argv=(), returncode=code, stdout=stdout, stderr=stderr)
