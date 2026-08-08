"""Fixtures + guards for the real-bd integration suite.

Every install is a throwaway .beads under pytest tmp_path, bound to bd via
BEADS_DIR so bd's upward .beads discovery can never reach the repo's real DB.
The suite skips wholesale when bd is not on PATH.

Two separate bindings keep an install isolated, and they isolate different
things. BEADS_DIR binds the bd SUBPROCESS to this install's database. The
`--config` path `driver_for` puts on every call binds the IN-PROCESS track
layer to this suite's own config -- see `_write_track_config` for why the
second one is not redundant.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from workcli.adapters.bd.runner import BdRunner, SubprocessBdRunner
from workcli.cli import main

_SEED_PREFIX = "itest"

# The one track name this suite may create under. It is the fixture's OWN
# vocabulary, not the ambient repository's -- `_write_track_config` explains
# the distinction and why it matters. Tests name it explicitly on every
# `work create <noun>`; import it rather than spelling the string again.
ITEST_TRACK = "itest-track"

_TRACK_CONFIG = f"""\
# Written per-install by the integration conftest. Owned by this suite.
[tracks]
names = ["{ITEST_TRACK}"]
enforcement = "required"
"""


def resolve_bd() -> str:
    """Absolute path to the bd binary. When bd is absent this raises pytest.skip
    at call time — skipping the calling test, or (called from the session-scoped
    bd_binary fixture) every test that needs a real bd."""
    bd = shutil.which("bd")
    if bd is None:
        pytest.skip("bd not on PATH; the real-bd integration suite requires it")
    return bd


def assert_off_repo(path: Path) -> None:
    """Refuse if `path` is inside any git repo (belt: bd walks UP for .beads,
    so a repo-nested install could reach a real .beads or commit bd's self-init
    into an enclosing checkout). tmp_path is off-repo, so this passes normally."""
    resolved = path.resolve()
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / ".git").exists():
            raise RuntimeError(
                f"refusing to run bd under {resolved}: ancestor {ancestor} is inside a git repo; "
                "the integration harness must install into an off-repo temp dir"
            )


@pytest.fixture(scope="session")
def bd_binary() -> str:
    return resolve_bd()


def _bd_env(install: Path) -> dict[str, str]:
    """Inherit the ambient env, force non-interactive, and BIND bd to this temp
    .beads so its upward-walk discovery can never reach the repo's real DB."""
    return {
        **os.environ,
        "BD_NON_INTERACTIVE": "1",
        "BEADS_DIR": str(install / ".beads"),
    }


def _run_bd(bd_binary: str, install: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Raw bd call for fixture setup/seeding (NOT the code under test). Loud on
    failure: a non-zero init/seed fails the suite with a named diagnostic."""
    proc = subprocess.run(  # noqa: S603
        [bd_binary, *args],
        cwd=install,
        env=_bd_env(install),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"fixture bd {' '.join(args)} failed (rc={proc.returncode}):\n{proc.stderr}"
        )
    return proc


def _bd_init(bd_binary: str, install: Path) -> None:
    assert_off_repo(install)  # guard BEFORE any bd call
    _run_bd(bd_binary, install, "init", "--prefix", _SEED_PREFIX)


def _write_track_config(install: Path) -> Path:
    """Write this install's OWN project-config.toml and return its path.

    WHERE THIS SUITE'S TRACK COMES FROM: this file, named explicitly as
    `--config` on every `work` call, and never the ambient repository's
    project-config.toml. The distinction is load-bearing. The track layer
    resolves its config by walking UP from `Path.cwd()`, and this suite drives
    production `main()` IN-PROCESS -- so that walk starts at pytest's own
    working directory, inside this repository, however completely bd itself is
    bound to an off-repo install by BEADS_DIR. Left alone the suite silently
    adopts the repository's own [tracks] table: its track names and its
    enforcement setting would decide what these tests are allowed to create,
    and editing that table would turn this suite red. `--config` overrides the
    upward search outright, which closes it.

    Enforcement is pinned to "required" deliberately. The create gate must be
    LIVE here, so every `work create <noun>` in this suite has to name its
    track exactly as a real caller does; relaxing it to "advisory" would let
    the suite pass without ever exercising the gate.
    """
    config_path = install / "project-config.toml"
    config_path.write_text(_TRACK_CONFIG, encoding="utf-8")
    return config_path


def driver_for(runner: BdRunner, install: Path) -> Callable[[Sequence[str]], dict]:
    """Return a callable that drives the PRODUCTION main() against this install
    and returns the parsed stdout envelope.

    Every call carries this install's own `--config`, so no `work` invocation
    in this suite can reach the ambient repository's track configuration.
    Public because the crash-recovery tests wrap the real runner in a
    fault-injecting one and need the same binding on their own calls.
    """
    config_path = _write_track_config(install)

    def drive(argv: Sequence[str]) -> dict:
        out, err = io.StringIO(), io.StringIO()
        main(["--config", str(config_path), *argv], runner=runner, out=out, err=err)
        return json.loads(out.getvalue())

    return drive


def _make_driver(bd_binary: str, install: Path) -> Callable[[Sequence[str]], dict]:
    return driver_for(
        SubprocessBdRunner(bd_binary=bd_binary, cwd=str(install), env=_bd_env(install)),
        install,
    )


@pytest.fixture
def fresh_install(bd_binary: str, tmp_path: Path) -> Path:
    """A pristine bd install per test (for mutation/lifecycle/crash sequences)."""
    _bd_init(bd_binary, tmp_path)
    return tmp_path


@pytest.fixture
def driver(bd_binary: str, fresh_install: Path) -> Callable[[Sequence[str]], dict]:
    return _make_driver(bd_binary, fresh_install)


@pytest.fixture(scope="session")
def read_only_install(bd_binary: str, tmp_path_factory: pytest.TempPathFactory):
    """One shared, seeded install for read/happy-path assertions. Seeded via RAW
    bd. Yield-based teardown re-asserts the three seed titles still exist, so a
    stray write-verb that DELETES a seed fails loudly rather than poisoning later
    read tests. Note the guard is a subset check: it catches deletion of a named
    seed, not an in-place mutation (retitle/close/label) or an added item."""
    install = tmp_path_factory.mktemp("read_only_beads")
    _bd_init(bd_binary, install)
    _run_bd(
        bd_binary,
        install,
        "create",
        "--title",
        "seed-alpha",
        "--type",
        "task",
        "--priority",
        "2",
        "--labels",
        "seed",
    )
    _run_bd(
        bd_binary,
        install,
        "create",
        "--title",
        "seed-beta",
        "--type",
        "task",
        "--priority",
        "1",
    )
    parent = _run_bd(
        bd_binary,
        install,
        "create",
        "--title",
        "seed-parent",
        "--type",
        "epic",
        "--priority",
        "2",
        "--json",
    ).stdout
    parent_id = json.loads(parent)["id"]
    _run_bd(
        bd_binary,
        install,
        "create",
        "--title",
        "seed-child",
        "--type",
        "task",
        "--priority",
        "2",
        "--parent",
        parent_id,
    )

    yield install

    titles = {i["title"] for i in json.loads(_run_bd(bd_binary, install, "list", "--json").stdout)}
    assert {"seed-alpha", "seed-beta", "seed-child"} <= titles, (
        "a read test DELETED a read_only seed item — read fixtures must stay read-only"
    )


@pytest.fixture
def read_only_driver(bd_binary: str, read_only_install: Path) -> Callable[[Sequence[str]], dict]:
    return _make_driver(bd_binary, read_only_install)
