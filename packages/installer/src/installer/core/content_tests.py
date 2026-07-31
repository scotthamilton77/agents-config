"""Discovery and execution of the test suites shipped inside ``src/``.

Skills ship real code — a launcher, an SSE repair proxy, a prompt emitter, a
verdict validator — and each ships a test suite beside it. Until this module
existed no target ran any of them, so a regression in shipped code reached
``main`` with CI green and surfaced as a broken delegation at use time, on
someone else's machine.

Three rules, all mechanical and all anti-drift:

1. **Every suite runs.** Suites are discovered by name, never enumerated, so a
   new skill's tests are picked up without editing the Makefile. A suite whose
   extension has no registered runner is a failure, not a skip — an unrunnable
   convention must be loud, since a silently-skipped suite is the exact failure
   this module exists to prevent.
2. **Every shipped script has a suite.** A non-test ``.py``/``.js``/``.sh`` file
   under ``src/`` must have a sibling named ``<stem>_test.*`` or
   ``test_<stem>.*``. Adding code to a skill therefore requires adding tests for
   it, rather than requiring someone to notice that none arrived. Both naming
   conventions are accepted here because both are accepted as suites: a
   contributor who writes ``test_foo.py`` for ``foo.py`` has tests, and telling
   them otherwise would be the gate lying.
3. **Every suite proves it ran.** Exit code alone cannot tell a suite that
   passed from one that collected nothing, because every runner here exits 0
   for an empty run. Each registered runner therefore declares the marker its
   language prints on a clean pass, and a suite that exits 0 without emitting
   one is a failure. This is what makes a green run mean something.

Discovery walks the filesystem rather than the staging plan on purpose:
``.installignore`` keeps test artifacts out of the *deployed* fileset, which
says nothing about whether they should run. Anything under ``src/`` runs.

That is why this gate's fileset is wider than ``content_lint``'s, which reports
on the staged tree instead. The two are not meant to converge: whether a shipped
script has a passing suite is a property of the source file, while the admission
bar and the surface budget are properties of what deploys.

The divergence is bounded from the other side, but only down to a depth:
``content_lint`` walks ``src/`` until it reaches a directory staging reads whole
— a namespace — and fails on anything above that line it cannot account for.
Below that line it stops, so a skill's own interior is this module's alone. The
residual is therefore everything inside a staged namespace, directories as well
as files.

``.installignore`` sits on both sides of that line and this module honours
neither half. Below the line it prunes, keeping matching source out of the
deployed fileset; above it, it declares a directory source-side so
``content_lint`` does not report it. What it prunes still runs here either way,
because whether a suite should run says nothing about whether it should ship —
which is why ``BUILD_DIRS``, not that manifest, is what both gates share.

Execution is I/O, so it routes through the ``SuiteRunner`` port — the real
implementation shells out, and tests inject a fake rather than spawning
processes.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Runner:
    """How to launch a suite written in one language, and how that language
    announces that it actually ran.

    The two halves are declared together deliberately. A runner registered with
    an argv alone can only be judged by its exit code, and every framework here
    exits 0 for a run that collected nothing — so admitting a language without
    its marker admits the hole this module exists to close. Registering a fourth
    extension therefore forces its author to answer both questions at once.

    ``clean_pass`` must capture the number of passing tests in group 1, so a run
    that reported zero can be told from one that reported some.
    """

    argv: tuple[str, ...]
    clean_pass: re.Pattern[str]


# Extension -> the runner that launches and judges it. The suite path is
# appended to ``argv``.
RUNNERS: dict[str, Runner] = {
    # ``uv run --script`` forces PEP 723 script mode, so a suite resolves its
    # own inline dependencies instead of inheriting whatever project environment
    # the gate happens to run inside — and a suite that forgot its inline
    # metadata fails loudly rather than silently importing the wrong thing.
    #
    # The marker is pytest's ``-q`` summary line, anchored at line start: a run
    # with failures leads with "1 failed, 54 passed", which does not match. A
    # suite that discarded ``pytest.main``'s return value and exited 0 anyway is
    # therefore caught here instead of being reported as a pass.
    ".py": Runner(
        argv=("uv", "run", "--script"),
        clean_pass=re.compile(r"^(\d+) passed\b", re.MULTILINE),
    ),
    # The TAP reporter is pinned rather than left to default. Node's default
    # swings between ``spec`` and ``tap`` by version and by whether stdout is a
    # terminal, and this gate always captures output — an unpinned reporter
    # would make the marker a property of the contributor's node build. TAP's
    # ``# pass N`` is specified, so pinning it makes the marker stable.
    ".js": Runner(
        argv=("node", "--test", "--test-reporter=tap"),
        clean_pass=re.compile(r"^# pass (\d+)$", re.MULTILINE),
    ),
    # bash ships no test framework, so the convention is this repo's: a shell
    # suite ends by printing its own tally. Declaring it here is what keeps the
    # table total — the alternative, exempting bash from rule 3, is a language
    # that can pass by printing nothing at all.
    ".sh": Runner(
        argv=("bash",),
        clean_pass=re.compile(r"^PASS=(\d+) FAIL=0$", re.MULTILINE),
    ),
}

# Directory names never descended into: build output and caches, which can hold
# vendored files matching the suite-name patterns.
#
# Public because ``content_lint`` reads it too. That gate reports a directory
# under ``src/`` staging never reads, and without this it would fail the build
# over a directory this one refuses to even walk — the two gates disagreeing
# about what is out of scope, which is the defect class they were both built to
# close. One definition, so they cannot drift.
BUILD_DIRS = frozenset({"node_modules", "__pycache__", ".venv"})

_TEST_SUFFIX = "_test"
_TEST_PREFIX = "test_"

# A shipped suite is a handful of assertions over one small script; nothing here
# legitimately runs for minutes. Without a bound, one suite that waits on a port
# or reads stdin hangs `make ci` until the job-level kill, which reports as an
# infrastructure timeout rather than as the suite that caused it.
_SUITE_TIMEOUT = 120

# The exit code reported for a suite the runner had to kill. 124 is the
# conventional `timeout(1)` code, and any non-zero value makes `SuiteResult.ok`
# false — a hang is a failing suite, not an exception that aborts the run and
# hides every suite behind it.
_TIMEOUT_RETURNCODE = 124


@dataclass(frozen=True, slots=True)
class Suite:
    """One discovered test suite and the runner that launches and judges it."""

    path: Path
    runner: Runner


@dataclass(frozen=True, slots=True)
class SuiteResult:
    """The outcome of running one suite. ``output`` is the merged stdout/stderr,
    printed by the caller only when the suite failed."""

    suite: Suite
    returncode: int
    output: str

    @property
    def failure(self) -> str | None:
        """Why this suite did not pass, or ``None`` if it did.

        Two ways a suite reaches exit 0 without having proved anything, and both
        read as a pass to CI and to anyone skimming a green log: it collected no
        tests, or it ran them, saw failures, and discarded its framework's
        return value. The runner's marker distinguishes both from a real pass.
        """
        if self.returncode != 0:
            return f"exited {self.returncode}"
        match = self.suite.runner.clean_pass.search(self.output)
        if match is None:
            return (
                "exited 0 without reporting a clean pass — expected output matching "
                f"{self.suite.runner.clean_pass.pattern}"
            )
        if int(match.group(1)) == 0:
            return "exited 0 having run no tests"
        return None

    @property
    def ok(self) -> bool:
        return self.failure is None


class SuiteRunner(Protocol):
    """The execution seam. Real runs shell out; tests inject a fake."""

    def run(self, suite: Suite) -> SuiteResult: ...  # pragma: no cover


def _decode(captured: bytes | str | None) -> str:
    """The partial output a killed suite left behind, as text.

    ``TimeoutExpired`` carries whatever was buffered at the kill, and does not
    honour ``text=True`` consistently across platforms — it can hand back bytes.
    Decoding is lossy on purpose: a truncated multibyte character at the cut
    point must not turn a reported timeout into a decode traceback.
    """
    if captured is None:
        return ""
    if isinstance(captured, bytes):
        return captured.decode("utf-8", errors="replace")
    return captured


class SubprocessRunner:
    """Runs a suite as a child process from its own directory.

    Suites resolve fixtures and the module under test relative to their own
    location, so the working directory is the suite's parent, never the repo
    root. The path handed to the runner is absolutised for exactly that reason:
    a discovery-relative path would be re-resolved against that new working
    directory and land nowhere.
    """

    def run(self, suite: Suite) -> SuiteResult:
        target = suite.path.resolve()
        try:
            proc = subprocess.run(  # noqa: S603  # argv is built from the RUNNERS table and discovered paths
                [*suite.runner.argv, str(target)],
                capture_output=True,
                text=True,
                check=False,
                cwd=target.parent,
                timeout=_SUITE_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            # Whatever the suite managed to emit before the kill is the only
            # clue to where it hung, so it is reported rather than discarded.
            partial = _decode(exc.stdout) + _decode(exc.stderr)
            return SuiteResult(
                suite=suite,
                returncode=_TIMEOUT_RETURNCODE,
                output=f"{partial}timed out after {_SUITE_TIMEOUT}s\n",
            )
        return SuiteResult(
            suite=suite, returncode=proc.returncode, output=proc.stdout + proc.stderr
        )


def _is_suite_name(stem: str) -> bool:
    return stem.endswith(_TEST_SUFFIX) or stem.startswith(_TEST_PREFIX)


def _paired_suite_stems(stem: str) -> tuple[str, str]:
    """The suite names that count as coverage for a script called ``stem``.

    Both conventions ``_is_suite_name`` recognises, because the two checks must
    agree: recognising ``test_foo.py`` as a suite while demanding ``foo_test.*``
    before ``foo.py`` counts as covered tells a contributor who wrote real tests
    that they have none.
    """
    return (stem + _TEST_SUFFIX, _TEST_PREFIX + stem)


def _walk(src_root: Path) -> list[Path]:
    """Every file under ``src_root``, skipping build/cache directories.

    Dot-directories are descended into: the tool trees themselves are
    ``.agents``/``.claude``/``.codex``, so skipping them would skip everything.
    """
    out: list[Path] = []
    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        # Matched against the path BELOW src_root: a checkout that happens to
        # live under a directory named .venv must not silently skip the tree.
        if BUILD_DIRS.intersection(path.relative_to(src_root).parts):
            continue
        out.append(path)
    return out


def discover_suites(src_root: Path) -> tuple[list[Suite], list[str]]:
    """Find every test suite under ``src_root`` and every script missing one.

    Returns ``(suites, violations)``. A missing ``src_root`` yields ``([], [])``
    — nothing shipped is nothing to run.
    """
    if not src_root.is_dir():
        return [], []

    files = _walk(src_root)
    suite_stems = {(path.parent, path.stem) for path in files if _is_suite_name(path.stem)}

    suites: list[Suite] = []
    violations: list[str] = []
    for path in files:
        if _is_suite_name(path.stem):
            runner = RUNNERS.get(path.suffix)
            if runner is None:
                violations.append(
                    f"{path}: test suite has no registered runner for '{path.suffix}' "
                    f"(known: {', '.join(sorted(RUNNERS))}) — it would never run"
                )
                continue
            suites.append(Suite(path=path, runner=runner))
        elif path.suffix in RUNNERS and not any(
            (path.parent, stem) in suite_stems for stem in _paired_suite_stems(path.stem)
        ):
            wanted = " or ".join(f"{stem}.*" for stem in _paired_suite_stems(path.stem))
            violations.append(f"{path}: shipped script has no sibling {wanted} test suite")

    return suites, violations


def run_suites(suites: list[Suite], *, runner: SuiteRunner) -> list[SuiteResult]:
    """Run every suite, in discovery order. Never short-circuits on the first
    failure: one red suite must not hide the state of the rest."""
    return [runner.run(suite) for suite in suites]
