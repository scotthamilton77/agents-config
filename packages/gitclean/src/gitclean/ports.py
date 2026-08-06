"""The subprocess seam. The only module in the package that shells out.

Everything above this file is pure: it receives ``CommandResult`` values and
returns data. That is what makes the classification rules testable without a
fixture repo, and it is why ``ScriptedCommands`` fails loudly on an unscripted
call -- a silent default would let a test pass while the real tool asks git a
question nobody predicted.

It is also where an argument is spelled for git. The two constructors below
are the only places a name the repository chose gets the spelling that keeps
git from reading it as an option, and they live here rather than beside either
caller because both the read stage and the write stage need them and neither
may import the other.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_DEFAULT_TIMEOUT = 60


def git_argv(*command: str, name: str | None = None) -> list[str]:
    """The only place a name out of the repository is put into a git argv.

    A repo-derived name can be spelled exactly like an option. `refs/heads/-m`
    is a legal ref -- `git branch` will not create one, but `update-ref` will
    and a remote can push one -- and `git branch -D -m` is a rename, not a
    deletion. Two spellings survive that, and which one applies is a property
    of the name rather than of the caller, so it is decided here:

    - a full `refs/...` path, which no git command parses as an option, and
    - the `--` terminator, for names that have to stay short.

    Both exist because `bundle create` hands its arguments to rev-list, where
    `--` introduces a pathspec: terminating there yields `Refusing to create
    empty bundle` rather than protection. `branch -D` is the mirror image --
    it rejects a full ref path and takes only the short name -- so neither
    spelling covers every call site and neither can be the single rule. The
    same split is why only a name in the last position can be terminated at
    all: `--` protects everything after it and nothing before, so a name
    followed by another argument goes in as a full ref path or not at all.

    What neither spelling does is bound where git will look. `--` ends option
    parsing; it does not stop git accepting a path in the repository position,
    and nothing in an argv does. Only where the name came from covers that.

    Passing through one constructor is what makes the option case impossible to
    forget: a new call site has nowhere else to put the name. Commands carrying
    no repo-derived name come through here too, so the rule is "every git call
    in this package", which a test can check -- rather than "every git call
    that a reader judged to carry a name", which is the judgement that missed
    two."""
    if name is None:
        return list(command)
    if name.startswith("refs/"):
        return [*command, name]
    return [*command, "--", name]


def git_rev(name: str) -> str:
    """A repo-derived branch name spelled for a rev expression it is only part
    of -- `<rev>^{tree}`, `<a>..<b>` -- where neither argv spelling is offered.

    A composed rev occupies one argument with no room to terminate anything
    inside it, and the commands that take one spend `--` on a pathspec anyway.
    `rev-parse` will not even consume a terminator: both `--` and
    `--end-of-options` come back from it as a literal line of output rather
    than being read as one. So the protection left is the other spelling,
    applied within the expression -- a full ref path, which cannot begin with
    `-`.

    Applied only when the short name would otherwise be misread, because
    `refs/heads/` is the wrong prefix for half of what reaches here. A
    remote-tracking branch's short name always leads with its remote --
    `origin/feat`, never a bare `feat` -- so it already resolves to the ref it
    names, while prefixing it would ask for a local branch that is usually not
    there and occasionally is somebody else's."""
    return f"refs/heads/{name}" if name.startswith("-") else name


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

    def scratch_dir(self) -> AbstractContextManager[Path]: ...  # pragma: no cover


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

    @contextmanager
    def scratch_dir(self) -> Iterator[Path]:
        """Somewhere to unpack a bundle into, gone again by the time this
        returns.

        Asking whether an archive restores means restoring it, and the answer
        is only worth having if the restore lands somewhere empty -- a repository
        that already holds the objects answers yes for the wrong reason. It
        cannot go beside the bundle either: the salvage directory is what a
        person is told to look in, and a restore is not part of the salvage.

        The directory is removed on the way out, including when the restore
        failed. What that costs is the failed attempt's evidence, and the
        transcript already carries it."""
        with tempfile.TemporaryDirectory(prefix="gitclean-restore-") as scratch:
            yield Path(scratch)


class ScriptedCommands:
    """Test fake. Answers are keyed by the argv prefix that identifies the
    question, so tests read as 'when git is asked X, say Y' rather than as a
    call-order transcript that breaks on every refactor.

    An unmatched call raises, naming the argv. Returning a benign default
    instead would let a test go green while production asks git something the
    test never anticipated -- the exact failure this fake exists to prevent.
    """

    scratch = Path("/scratch")
    """Where a restore is told to unpack. Fixed, so the argv the restore probe
    builds is one a test can script."""

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

    def write_text(self, path: Path, content: str) -> None:
        self.files[str(path)] = content

    @contextmanager
    def scratch_dir(self) -> Iterator[Path]:
        """A fixed path, so the argv of a restore is one a test can script.

        Nothing is created: the fake answers git's questions and must not touch
        the filesystem to do it."""
        yield self.scratch


def ok(stdout: str = "", *, stderr: str = "") -> CommandResult:
    """Terse constructor for scripted success."""
    return CommandResult(argv=(), returncode=0, stdout=stdout, stderr=stderr)


def fail(stderr: str = "", *, code: int = 1, stdout: str = "") -> CommandResult:
    """Terse constructor for scripted failure."""
    return CommandResult(argv=(), returncode=code, stdout=stdout, stderr=stderr)
