"""A real backend on a real port, three scripted seats, and a browser on the board.

What makes this end-to-end rather than a larger unit test is that nothing here
assembles the backend. The scenario writes a handoff, sets the environment, and
calls the same `launch` a human's `grillui serve` calls -- so the session opens
through `open_session`, the seats are resolved through `TierConfig.from_env` and
`seat_driver`, and the board is wrapped in the same loopback refusal. A harness
that built `create_app` by hand would leave exactly that wiring untested, which
is the wiring no unit test crosses.

Three seats and three ways of scripting them:

- the **threads' seat** is an OpenRouter transport pointed at a stub in this
  process, which is why the endpoint had to become configuration -- a session
  reaches it through the seat every other turn goes through;
- the **map's seat** is `codex`, and the **expert seat** is `claude`; both are
  real executables on the backend's PATH, one process per turn, reading their
  scripted turns out of the session directory and recording every call back into
  it.

Every seat is scripted, so no scenario reaches a network or a real CLI. A turn
the script does not cover fails the turn rather than hanging it: the stub
answers 500 and the shims exit non-zero, and either way the lane's error phase
is what the scenario reads.

Assertions are made on the log file's bytes -- the ground truth the unit suite,
the page, the capture step and a restarted process all read -- and on the page
only where the fact is a rendered one.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from grillui.launch import RunStop, launch
from grillui.log import HANDOFF_FILE, LOG_FILE, read_entries
from grillui.tiers import API_BASE_ENV, API_KEY_ENV

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from grillui.schemas import LogEntry

SHIM_DIR = Path(__file__).parent / "shims"
# The same key the shims read. Stated here rather than imported from them,
# because they are executables the backend runs and not a module this imports.
SCRIPT_ENV = "GRILLUI_E2E_DIR"
SCRATCH = "e2e"

# A key that reaches nothing. The transport refuses a turn outright without one,
# which would prove the refusal path rather than the seat; this is enough to get
# past that check and is not a credential.
STUB_KEY = "e2e-scripted-seat-no-credential"

# How long a turn is given before the scenario calls it stuck. Every seat here
# is a local process or a local socket, so the budget is about scheduling rather
# than about a model.
TURN_TIMEOUT = 20.0
POLL = 0.05

NEVER_STARTED = "the backend never started answering"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class Completion:
    """One scripted answer from the threads' seat, in OpenRouter's own shape.

    `prompt_tokens` is absent by default, which is the honest default: a
    provider that reported no usage costs the turn its measurement and nothing
    else, and a scenario about the measurement says so.
    """

    text: str
    prompt_tokens: int | None = None
    status: int = 200


class OpenRouterStub:
    """A completions endpoint on loopback, answering from a queue.

    In this process rather than behind a shim, because the seat that reaches it
    is in this process too: the FastDriver's transport is the only part of the
    session that talks to it, and a queue of Python objects is a smaller thing
    to keep correct than a third scripted executable.

    Every request is recorded whole -- the path, the bearer, and the body with
    the system message and the prompt inside it -- because half of what a
    scenario asserts is what a seat was given rather than what it said.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.scripted: list[Completion] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                status, answer = stub._answer(
                    self.path, body, self.headers.get("authorization", "")
                )
                encoded = json.dumps(answer).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args: Any) -> None:
                """The scenario's output is the assertion, not a request log."""

        self._server = ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def api_base(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def script(self, *completions: Completion | str) -> None:
        """What this seat says, turn by turn."""
        with self._lock:
            self.scripted += [
                one if isinstance(one, Completion) else Completion(one) for one in completions
            ]

    def _answer(self, path: str, body: Any, bearer: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            index = len(self.calls)
            self.calls.append({"path": path, "body": body, "authorization": bearer})
            if index >= len(self.scripted):
                # A turn nobody scripted. Answered as a failed turn rather than
                # left to hang, so the scenario reads an error phase in
                # milliseconds instead of a timer that counts up.
                return 500, {"error": f"no completion {index} is scripted"}
            completion = self.scripted[index]
        answer: dict[str, Any] = {"choices": [{"message": {"content": completion.text}}]}
        if completion.prompt_tokens is not None:
            answer["usage"] = {"prompt_tokens": completion.prompt_tokens}
        return completion.status, answer

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def system_of(self, index: int) -> str:
        """The standing brief the seat was given on one call."""
        return str(self.calls[index]["body"]["messages"][0]["content"])

    def prompt_of(self, index: int) -> str:
        """The composed prompt the seat was given on one call."""
        return str(self.calls[index]["body"]["messages"][1]["content"])


@contextmanager
def environment(values: Mapping[str, str]) -> Iterator[None]:
    """Set what a launch is configured by, and put it back afterwards.

    The process environment rather than an argument, because that is what
    `TierConfig.from_env` reads and what a shim inherits -- the same two readers
    a real launch has.
    """
    before = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, was in before.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


@dataclass
class Session:
    """One running backend over one session directory.

    Held rather than returned piecemeal because a scenario asks all of it: what
    the log says, what each seat was given, what the board serves, and what the
    launch printed when the human ended it.
    """

    directory: Path
    url: str
    stub: OpenRouterStub
    out: StringIO
    stop: RunStop
    served: threading.Thread
    env: dict[str, str] = field(default_factory=dict)
    _configured: Any = None
    # Where the log stood when `settled` last returned, so the next gesture is
    # waited for rather than assumed to have already happened.
    _settled_at: int = 0

    @property
    def scratch(self) -> Path:
        return self.directory / SCRATCH

    def entries(self) -> list[LogEntry]:
        """The log file's bytes, read the way every other reader reads them."""
        return read_entries(self.directory / LOG_FILE)

    def state(self) -> dict[str, Any]:
        read: dict[str, Any] = httpx.get(self.url + "state").json()
        return read

    def board(self) -> dict[str, Any]:
        found: dict[str, Any] = self.state()["image1"]
        return found

    def image2(self) -> dict[str, Any]:
        read: dict[str, Any] = httpx.get(self.url + "image2").json()
        return read

    def script_codex(self, *turns: Mapping[str, Any]) -> None:
        _write_script(self.scratch, "codex", turns)

    def script_claude(self, *turns: Mapping[str, Any]) -> None:
        _write_script(self.scratch, "claude", turns)

    def codex_calls(self) -> list[dict[str, Any]]:
        return _read_calls(self.scratch, "codex")

    def claude_calls(self) -> list[dict[str, Any]]:
        return _read_calls(self.scratch, "claude")

    def dispatches(self) -> list[dict[str, Any]]:
        """Every context an agent was given, in the order they were recorded."""
        directory = self.directory / "dispatches"
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]

    def settled(self) -> None:
        """Wait until the gesture just made has landed and left no turn running.

        Both halves are load-bearing, and the second one alone is a trap. A
        click reaches the log through a browser, an HTTP round trip and an
        append; wait only for "no channel is mid-turn" and the answer is yes
        before the gesture has arrived, so the scenario races ahead and reads a
        board nothing has happened to yet. That failure is invisible on a fast
        machine and arrives as a mystery on a slow one.

        So the log is required to have moved past where it stood when this last
        returned, and only then is the lane's own pairing rule waited on -- a
        `composing` with no `replied` or `error` after it is a turn still
        running. Every gesture a scenario makes appends at least the human's own
        entry, so "the log moved" is a fact about the gesture rather than a
        guess about timing.
        """
        deadline = time.monotonic() + TURN_TIMEOUT
        while time.monotonic() < deadline:
            entries = self.entries()
            landed = entries[-1].seq if entries else 0
            if landed > self._settled_at and not _open_turns(entries):
                self._settled_at = landed
                return
            time.sleep(POLL)
        entries = self.entries()
        stuck = (
            f"nothing landed past seq {self._settled_at}"
            if (entries[-1].seq if entries else 0) <= self._settled_at
            else f"a turn never closed: {_open_turns(entries)}"
        )
        raise AssertionError(stuck)

    def close(self) -> None:
        """End the run the way the end-session gesture does, and wait for it.

        The configuration is put back only once the last turn is over. A turn
        runs long after the call that started the backend returned, and a
        harness that restored `PATH` on the way out of that call would hand the
        seats back to whatever binaries the machine has -- which is a scenario
        spending a real account and reporting it as a scripted seat.
        """
        self.stop()
        self.served.join(timeout=TURN_TIMEOUT)
        if self._configured is not None:
            self._configured.__exit__(None, None, None)
            self._configured = None


def _open_turns(entries: Sequence[LogEntry]) -> dict[str, str]:
    open_turns: dict[str, str] = {}
    for entry in entries:
        if entry.kind != "status":
            continue
        phase = entry.payload.get("phase")
        if phase == "composing":
            open_turns[entry.channel] = str(entry.payload.get("text", ""))
        elif phase in {"replied", "error"}:
            open_turns.pop(entry.channel, None)
    return open_turns


def _write_script(scratch: Path, name: str, turns: Sequence[Mapping[str, Any]]) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / f"{name}-script.json").write_text(
        json.dumps([dict(one) for one in turns]), encoding="utf-8"
    )


def _read_calls(scratch: Path, name: str) -> list[dict[str, Any]]:
    path = scratch / f"{name}-calls.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def start(
    directory: Path,
    handoff: Mapping[str, Any] | None = None,
    *,
    config: Mapping[str, str] | None = None,
    stub: OpenRouterStub | None = None,
) -> Session:
    """Launch a backend over this directory and wait until the board answers.

    `handoff` seeds a new session and is not read again; a directory that
    already holds a log resumes from it, which is the same rule a restarted
    backend follows and is what one scenario is about.

    `config` is the session's own configuration, on top of the three settings
    every scenario needs: the stub's endpoint, a bearer that reaches nothing,
    and a PATH holding the shims and nothing else.

    That PATH is the guard rather than a convenience. Prepending the shims would
    leave a real `codex` or `claude` reachable the moment a setting was wrong or
    a lookup missed, and a scenario that reached one would spend a real account
    and read as a passing scripted seat -- which is exactly what happened while
    this was being built. A PATH with nowhere else to look cannot do that: the
    only thing either driver spawns is the seat, and an unreachable one fails
    the turn in milliseconds instead.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SCRATCH).mkdir(parents=True, exist_ok=True)
    if handoff is not None:
        (directory / HANDOFF_FILE).write_text(json.dumps(dict(handoff)), encoding="utf-8")
    stub = OpenRouterStub() if stub is None else stub
    settings = {
        API_BASE_ENV: stub.api_base,
        API_KEY_ENV: STUB_KEY,
        SCRIPT_ENV: str(directory / SCRATCH),
        "PATH": f"{SHIM_DIR}{os.pathsep}{_interpreter_dir(directory / SCRATCH)}",
        **dict(config or {}),
    }
    out = StringIO()
    stop = RunStop()
    port = free_port()
    # Held for the whole tenure rather than across the call that starts it: the
    # seats are resolved on the way up, but the turns run later and every one of
    # them re-reads this environment.
    keep = environment(settings)
    keep.__enter__()
    served = threading.Thread(
        target=lambda: launch(directory, port, out=out, stop=stop), daemon=True
    )
    served.start()
    url = f"http://127.0.0.1:{port}/"
    session = Session(directory, url, stub, out, stop, served, dict(settings), keep)
    try:
        _wait_until_serving(url, served)
    except AssertionError:
        session.close()
        raise
    return session


def _interpreter_dir(scratch: Path) -> Path:
    """A directory holding one `python3` and nothing else.

    The shims are `#!/usr/bin/env python3` scripts, so their shebang is resolved
    against the PATH they inherit -- which is why a PATH that holds only the
    shims makes every seat exit 127. This gives the shebang exactly one thing to
    find, and it is the interpreter already running, so the scenario's own
    environment is what the shims run on.
    """
    bin_dir = scratch / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    interpreter = bin_dir / "python3"
    if not interpreter.exists():
        interpreter.symlink_to(sys.executable)
    return bin_dir


def _wait_until_serving(url: str, served: threading.Thread) -> None:
    deadline = time.monotonic() + TURN_TIMEOUT
    while time.monotonic() < deadline:
        if not served.is_alive():
            raise AssertionError(NEVER_STARTED)
        try:
            if httpx.get(url + "status", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(POLL)
    raise AssertionError(NEVER_STARTED)
