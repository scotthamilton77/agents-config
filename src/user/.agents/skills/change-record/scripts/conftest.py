"""Fence every suite in this directory off from the network, GitHub and the tracker.

pytest loads this file for each suite beside it, so a new suite is fenced
without asking for it. Under the fence the search path holds a shim directory,
the interpreter and git, and every proxy variable points at a closed local
port. A call to an executable the test did not shim fails, and so does an HTTP
request from any client that honours the proxy variables.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# Port 9 is the discard service, which no current system runs, so a connection
# to it is refused at once. Choosing a free port at run time would need a socket.
CLOSED_PROXY = "http://127.0.0.1:9"


def _wrap(path: Path, target: str) -> None:
    """Write an executable at ``path`` that runs ``target`` with the same arguments.

    A link to the interpreter would lose the environment the interpreter was
    installed into. Putting the real executable's directory on the search path
    would bring in every other program that directory holds. A wrapper in a
    directory of its own avoids both.
    """
    path.write_text(f'#!/bin/sh\nexec {shlex.quote(target)} "$@"\n', encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture(scope="session", autouse=True)
def _fence(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Hold the fence for the whole run and yield the shim directory.

    The fence spans the session because pytest sets up a module or session
    fixture before any per-test one, and such a fixture must not run outside it.
    """
    git = shutil.which("git")
    assert git, "the suites need git on the search path"
    tools = tmp_path_factory.mktemp("tools")
    _wrap(tools / "python3", sys.executable)
    _wrap(tools / "git", git)
    shims = tmp_path_factory.mktemp("shims")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PATH", f"{shims}{os.pathsep}{tools}")
        # Clients disagree on which spelling they read, so both are set.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            patch.setenv(name, CLOSED_PROXY)
            patch.setenv(name.lower(), CLOSED_PROXY)
        patch.setenv("NO_PROXY", "")
        patch.setenv("no_proxy", "")
        yield shims


@pytest.fixture(autouse=True)
def shim_dir(_fence: Path) -> Iterator[Path]:
    """Return the shim directory, and empty it when the test ends.

    A test that needs ``gh`` or ``work`` writes an executable of that name
    here. Emptying the directory keeps a shim one test wrote from answering a
    call another test makes.
    """
    yield _fence
    for shim in _fence.iterdir():
        shim.unlink()
