"""Discovery and execution of the test suites shipped inside ``src/``.

Skills ship real code — a launcher, an SSE repair proxy, a prompt emitter, a
verdict validator — and each ships a test suite beside it. Until this module
existed no target ran any of them, so a regression in shipped code reached
``main`` with CI green and surfaced as a broken delegation at use time, on
someone else's machine.

Two rules, both mechanical and both anti-drift:

1. **Every suite runs.** Suites are discovered by name, never enumerated, so a
   new skill's tests are picked up without editing the Makefile. A suite whose
   extension has no registered runner is a failure, not a skip — an unrunnable
   convention must be loud, since a silently-skipped suite is the exact failure
   this module exists to prevent.
2. **Every shipped script has a suite.** A non-test ``.py``/``.js``/``.sh`` file
   under ``src/`` must have a sibling named ``<stem>_test.*``. Adding code to a
   skill therefore requires adding tests for it, rather than requiring someone
   to notice that none arrived.

Discovery walks the filesystem rather than the staging plan on purpose:
``.installignore`` keeps test artifacts out of the *deployed* fileset, which
says nothing about whether they should run. Anything under ``src/`` runs.

Execution is I/O, so it routes through the ``SuiteRunner`` port — the real
implementation shells out, and tests inject a fake rather than spawning
processes.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Extension -> argv prefix the suite path is appended to.
#
# ``uv run --script`` forces PEP 723 script mode, so a suite resolves its own
# inline dependencies instead of inheriting whatever project environment the
# lint happens to run inside — and a suite that forgot its inline metadata
# fails loudly rather than silently importing the wrong thing.
RUNNERS: dict[str, tuple[str, ...]] = {
    ".py": ("uv", "run", "--script"),
    ".js": ("node", "--test"),
    ".sh": ("bash",),
}

# Directory names never descended into: build output and caches, which can hold
# vendored files matching the suite-name patterns.
_SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".venv"})

_TEST_SUFFIX = "_test"
_TEST_PREFIX = "test_"


@dataclass(frozen=True, slots=True)
class Suite:
    """One discovered test suite and the argv that runs it."""

    path: Path
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuiteResult:
    """The outcome of running one suite. ``output`` is the merged stdout/stderr,
    printed by the caller only when the suite failed."""

    suite: Suite
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SuiteRunner(Protocol):
    """The execution seam. Real runs shell out; tests inject a fake."""

    def run(self, suite: Suite) -> SuiteResult: ...  # pragma: no cover


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
        proc = subprocess.run(  # noqa: S603  # argv is built from the RUNNERS table and discovered paths
            [*suite.argv, str(target)],
            capture_output=True,
            text=True,
            check=False,
            cwd=target.parent,
        )
        return SuiteResult(
            suite=suite, returncode=proc.returncode, output=proc.stdout + proc.stderr
        )


def _is_suite_name(stem: str) -> bool:
    return stem.endswith(_TEST_SUFFIX) or stem.startswith(_TEST_PREFIX)


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
        if _SKIP_DIRS.intersection(path.relative_to(src_root).parts):
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
            argv = RUNNERS.get(path.suffix)
            if argv is None:
                violations.append(
                    f"{path}: test suite has no registered runner for '{path.suffix}' "
                    f"(known: {', '.join(sorted(RUNNERS))}) — it would never run"
                )
                continue
            suites.append(Suite(path=path, argv=argv))
        elif path.suffix in RUNNERS and (path.parent, path.stem + _TEST_SUFFIX) not in suite_stems:
            violations.append(
                f"{path}: shipped script has no sibling {path.stem}{_TEST_SUFFIX}.* test suite"
            )

    return suites, violations


def run_suites(suites: list[Suite], *, runner: SuiteRunner) -> list[SuiteResult]:
    """Run every suite, in discovery order. Never short-circuits on the first
    failure: one red suite must not hide the state of the rest."""
    return [runner.run(suite) for suite in suites]
