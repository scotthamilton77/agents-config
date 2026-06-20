"""Runner for the golden-master parity harness.

Runs ``scripts/install.sh`` (bash) and ``scripts/install.py`` (Python) into two
separate HOME trees by overriding the ``HOME`` env var — both installers resolve
their destination from ``$HOME`` — then exposes a comparison-type-aware diff. The
runs are hermetic: nothing outside the per-run temp HOME is touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tests.golden_master._diff import TreeDiff, diff_trees

# ``_runner.py`` lives at ``<repo>/packages/installer/tests/golden_master/_runner.py``;
# the fourth parent is the repo root that holds ``scripts/`` and ``src/``.
REPO_ROOT = Path(__file__).resolve().parents[4]
_INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
_INSTALL_PY = REPO_ROOT / "scripts" / "install.py"
_BASH = shutil.which("bash") or "bash"
_RUN_TIMEOUT_S = 120

# Populates a HOME dir with pre-install state; applied identically to both homes.
SeedFn = Callable[[Path], None]


@dataclass(frozen=True)
class ParityResult:
    """Outcome of one parity run: the two HOME trees plus each installer's exit."""

    home_a: Path  # bash install.sh
    home_b: Path  # python install.py
    bash_returncode: int
    python_returncode: int
    bash_stderr: str
    python_stderr: str
    bash_stdout: str
    python_stdout: str

    def diff(self) -> TreeDiff:
        return diff_trees(self.home_a, self.home_b)


def _build_env(home: Path, extra_env: dict[str, str] | None) -> dict[str, str]:
    """Hermetic environment for an installer subprocess.

    Inherits the ambient env (for PATH etc.), then PINS every input the
    installers read so a leaked ambient value can't make a run non-hermetic:
    HOME isolates the install, LC_ALL/LANG fix locale-sensitive sorts (bash
    ALL-RULES uses ``LC_ALL=C sort``), and INSTALLER_PLUGINS_SRC defaults to ""
    — which both installers treat as unset, so a value a developer or CI runner
    exported can never bleed into a default scenario. ``extra_env`` overrides
    last (e.g. a fixture plugin tree for plugin scenarios).
    """
    env = {
        **os.environ,
        "HOME": str(home),
        "LC_ALL": "C",
        "LANG": "C",
        "INSTALLER_PLUGINS_SRC": "",
        # install.sh owns a prgroom `uv tool install` step that install.py has no
        # counterpart for (design §7.2). Left on, only the bash side would create
        # a uv-managed `prgroom` console script under home_a's uv tool-bin dir — a
        # spurious parity divergence — and it would need a real (slow, networked)
        # wheel build, breaking hermeticity. The master toggle pins it off for
        # BOTH installers (inert for install.py, which has no prgroom step).
        "INSTALLER_PRGROOM": "0",
    }
    if extra_env:
        env.update(extra_env)
    return env


def _run(
    cmd: list[str], home: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, hermetic env
        cmd,
        cwd=REPO_ROOT,
        env=_build_env(home, extra_env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_S,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    """Raise if a run failed, so a warm-up run's exit code can't be silently
    masked by the later captured run (only the final run's result is returned)."""
    if result.returncode != 0:
        msg = f"{label} failed (rc={result.returncode}): {result.stderr}"
        raise RuntimeError(msg)


def run_parity(
    tmp_path: Path,
    *,
    args: list[str],
    seed: SeedFn | None = None,
    plugins_src: Path | None = None,
    repeat: int = 1,
    env: dict[str, str] | None = None,
) -> ParityResult:
    """Run both installers with ``args`` into fresh homes under ``tmp_path``.

    ``seed`` (optional) populates pre-install state and is applied identically to
    both homes so any divergence is attributable to the installers, not the setup.

    ``plugins_src`` (optional) sets ``INSTALLER_PLUGINS_SRC`` for both installers,
    pointing them at a fixture plugin tree via the inert source seam.

    ``repeat`` (default 1, treated as a floor) runs each installer that many
    times into its home; the returned result reflects the *last* run.
    ``repeat=2`` exercises re-install idempotency — the second run lands on a
    tree the first already created.

    ``env`` (optional) overrides extra environment for both installers — e.g. a
    pinned ``PATH`` that isolates tool auto-detection deterministically. It is
    applied after ``plugins_src`` (so it can override that too) on top of the
    ``HOME``/locale pins ``_build_env`` always applies.
    """
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"
    home_a.mkdir()
    home_b.mkdir()
    if seed is not None:
        seed(home_a)
        seed(home_b)

    extra_env: dict[str, str] = {}
    if plugins_src is not None:
        extra_env["INSTALLER_PLUGINS_SRC"] = str(plugins_src)
    if env:
        extra_env.update(env)
    # Run the warm-up rounds for their filesystem effect; capture only the final
    # run's exit/stderr below. A warm-up failure still raises (it must not be
    # masked by a later run). For repeat=1 the loop runs zero times.
    for i in range(repeat - 1):
        warm_a = _run([_BASH, str(_INSTALL_SH), *args], home_a, extra_env=extra_env)
        warm_b = _run([sys.executable, str(_INSTALL_PY), *args], home_b, extra_env=extra_env)
        _require_ok(warm_a, f"bash warm-up run {i + 1}")
        _require_ok(warm_b, f"python warm-up run {i + 1}")

    bash = _run([_BASH, str(_INSTALL_SH), *args], home_a, extra_env=extra_env)
    python = _run([sys.executable, str(_INSTALL_PY), *args], home_b, extra_env=extra_env)

    return ParityResult(
        home_a=home_a,
        home_b=home_b,
        bash_returncode=bash.returncode,
        python_returncode=python.returncode,
        bash_stderr=bash.stderr,
        python_stderr=python.stderr,
        bash_stdout=bash.stdout,
        python_stdout=python.stdout,
    )
