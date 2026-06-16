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

    def diff(self) -> TreeDiff:
        return diff_trees(self.home_a, self.home_b)


def _run(
    cmd: list[str], home: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # Override HOME for isolation and pin the locale so any locale-sensitive sort
    # (bash ALL-RULES uses ``LC_ALL=C sort``) is reproducible across machines/CI.
    # ``extra_env`` injects parity seams (e.g. INSTALLER_PLUGINS_SRC) into both
    # installers identically.
    env = {**os.environ, "HOME": str(home), "LC_ALL": "C", "LANG": "C"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, hermetic HOME
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_S,
        check=False,
    )


def run_parity(
    tmp_path: Path,
    *,
    args: list[str],
    seed: SeedFn | None = None,
    plugins_src: Path | None = None,
    repeat: int = 1,
    env_overrides: dict[str, str] | None = None,
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

    ``env_overrides`` (optional) is merged into both installers' environments
    identically — e.g. a pinned minimal ``PATH`` so auto-detection probes
    (``command -v``/``which``) are deterministic regardless of what the host has
    installed.
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
    if env_overrides:
        extra_env.update(env_overrides)
    # Discard the warm-up runs; capture only the final run's exit/stderr. For
    # repeat=1 the loop runs zero times, so behaviour is unchanged.
    for _ in range(repeat - 1):
        _run([_BASH, str(_INSTALL_SH), *args], home_a, extra_env=extra_env)
        _run([sys.executable, str(_INSTALL_PY), *args], home_b, extra_env=extra_env)

    bash = _run([_BASH, str(_INSTALL_SH), *args], home_a, extra_env=extra_env)
    python = _run([sys.executable, str(_INSTALL_PY), *args], home_b, extra_env=extra_env)

    return ParityResult(
        home_a=home_a,
        home_b=home_b,
        bash_returncode=bash.returncode,
        python_returncode=python.returncode,
        bash_stderr=bash.stderr,
        python_stderr=python.stderr,
    )
