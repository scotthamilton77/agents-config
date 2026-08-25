"""What both CLI shims share: where a scenario's script is, and how a call is recorded.

A shim is a real executable on the backend's PATH, so the seat it stands in for
is reached the way the real one is -- one process per turn, argv built by the
driver, stdin closed by the driver, cwd set by the driver. Nothing here imports
the package under test: a shim that could see the driver's own constants would
assert the driver against itself, and the contract it is checking is exactly the
thing that must be stated twice.

**A violated contract is recorded, never exited on.** A shim that failed hard
would look to the backend like a seat that could not be reached, and the
scenario would then walk the unreachable-seat ladder -- proving the wrong thing
about the wrong path. So a violation rides in the call record and the scenario
asserts on it, which also means one scenario can deliberately break the contract
and show the check firing.

The script and the record both live under the session directory the scenario
names in the environment, so two scenarios never read each other's turns.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Where a scenario puts this run's scripted turns and where the calls are
# recorded back. Named in the environment because a shim is handed nothing else:
# the driver builds the argv, and there is no room in it for the harness.
SCRIPT_ENV = "GRILLUI_E2E_DIR"


def directory() -> Path:
    """The scenario's own scratch directory, as the environment states it."""
    found = os.environ.get(SCRIPT_ENV)
    if not found:
        missing = f"{SCRIPT_ENV} is unset: this shim was run outside a scenario"
        raise SystemExit(missing)
    return Path(found)


def turns(name: str) -> list[dict[str, Any]]:
    """The turns this seat is scripted to take, in order."""
    path = directory() / f"{name}-script.json"
    if not path.is_file():
        return []
    loaded: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def record(name: str, call: dict[str, Any]) -> int:
    """Append what this call was given, and answer which call it is.

    The index is read off the record rather than kept anywhere, so the count
    survives the process boundary the way the scenario's own reading of it does:
    each turn is its own process, and there is nothing between them to remember.
    """
    path = directory() / f"{name}-calls.jsonl"
    written = path.read_text(encoding="utf-8") if path.is_file() else ""
    index = len([line for line in written.splitlines() if line.strip()])
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"index": index, **call}) + "\n")
    return index


def stdin_is_closed() -> bool:
    """Whether the caller closed this process's standard input.

    Asked of the file descriptor rather than by reading it. `codex exec` reads
    its prompt from a piped stdin, so a driver that left the stream open hangs
    the turn -- and a shim that proved that by reading would hang in exactly the
    same way instead of reporting it.
    """
    try:
        return os.fstat(0).st_rdev == Path(os.devnull).stat().st_rdev
    except OSError:
        return False


def flag_value(argv: list[str], flag: str) -> str | None:
    """What was passed to a flag, or nothing where the flag is absent."""
    if flag not in argv:
        return None
    index = argv.index(flag)
    return argv[index + 1] if index + 1 < len(argv) else None


def settings(argv: list[str]) -> list[str]:
    """Every `-c key=value` this invocation carried."""
    return [
        argv[index + 1] for index, one in enumerate(argv) if one == "-c" and index + 1 < len(argv)
    ]


def emit(turn: dict[str, Any], lines: list[str]) -> None:
    """Print what this turn prints and exit as it was scripted to exit."""
    sys.stdout.write("".join(line + "\n" for line in lines))
    sys.stdout.flush()
    said = turn.get("stderr")
    if said:
        sys.stderr.write(str(said))
    raise SystemExit(int(turn.get("exit", 0)))
