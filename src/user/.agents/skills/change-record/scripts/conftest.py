"""Fence every suite in this directory off from the network, GitHub and the tracker.

The fence goes up when this file is imported, and it stays up until the
process ends. pytest imports this file before it imports any suite beside it,
so a suite's module-level code runs inside the fence when pytest collects it.
A suite launched as a script runs that code once more, before pytest starts,
so each suite also imports this file ahead of everything else.

Under the fence the search path holds a shim directory, the interpreter and
git, and every proxy variable points at a closed local port. A call to an
executable the test did not shim fails, and so does an HTTP request from any
client that honours the proxy variables.
"""

from __future__ import annotations

import atexit
import os
import shlex
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Port 9 is the discard service, which no current system runs, so a connection
# to it is refused at once. Choosing a free port at run time would need a socket.
CLOSED_PROXY = "http://127.0.0.1:9"

# The variable that names the fence a process raised, as the process's id, a
# space, and the fence's directory. pytest imports this file afresh even when a
# suite imported it first, and the second copy finds the fence here in place of
# raising another over it. A child process inherits the variable, reads another
# process's id in it, and raises a fence of its own.
RAISED_BY = "CHANGE_RECORD_FENCE"


def _wrap(path: Path, target: str) -> None:
    """Write an executable at ``path`` that runs ``target`` with the same arguments.

    A link to the interpreter would lose the environment the interpreter was
    installed into. Putting the real executable's directory on the search path
    would bring in every other program that directory holds. A wrapper in a
    directory of its own avoids both.
    """
    path.write_text(f'#!/bin/sh\nexec {shlex.quote(target)} "$@"\n', encoding="utf-8")
    path.chmod(0o755)


def _raise_fence() -> Path:
    """Put the fence up, unless this process already has one, and return the shim directory."""
    process, _, root = os.environ.get(RAISED_BY, "").partition(" ")
    if process != str(os.getpid()) or not os.path.isdir(root):
        git = shutil.which("git")
        assert git, "the suites need git on the search path"
        root = tempfile.mkdtemp(prefix="change-record-fence-")
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        tools = Path(root, "tools")
        tools.mkdir()
        Path(root, "shims").mkdir()
        _wrap(tools / "python3", sys.executable)
        _wrap(tools / "git", git)
        os.environ[RAISED_BY] = f"{os.getpid()} {root}"
        os.environ["PATH"] = f"{Path(root, 'shims')}{os.pathsep}{tools}"
        # Clients disagree on which spelling they read, so both are set.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ[name] = CLOSED_PROXY
            os.environ[name.lower()] = CLOSED_PROXY
        os.environ["NO_PROXY"] = ""
        os.environ["no_proxy"] = ""
    return Path(root, "shims")


SHIMS = _raise_fence()


@pytest.fixture(autouse=True)
def shim_dir() -> Iterator[Path]:
    """Return the shim directory, and empty it when the test ends.

    A test that needs ``gh`` or ``work`` writes an executable of that name
    here. Emptying the directory keeps a shim one test wrote from answering a
    call another test makes.
    """
    yield SHIMS
    for shim in SHIMS.iterdir():
        shim.unlink()
