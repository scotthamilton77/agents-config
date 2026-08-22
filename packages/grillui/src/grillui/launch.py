"""The launch path: one command that opens a session and returns its result.

Launching is a single foreground command on purpose. The agent that starts a
grilling hands the human a URL and then has nothing to do until the human is
finished, so the wait is the command not having returned yet -- there is no
status to poll, and a poll would burn a turn on transport to learn what process
exit already says.

Loopback is the whole of the trust boundary. The process binds `127.0.0.1`, so
a connection from anywhere else does not reach it in the first place; the
refusal here is what makes that a property of the application rather than of
one bind call, and it answers a request whose client is not this machine
without reading the board at all.

The port is negotiated rather than assumed: a second session on a machine
already serving one takes the next free port and says which, because the
alternative is a launch that fails on a number nobody chose.

The human's end-session gesture is what ends the run, and what the launch prints
then is the terminal result and the paths beside it -- never the log, the thread
turns or the dispatches, all of which stay in the session directory for anyone
who wants them.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import signal
import socket
import sys
import webbrowser
from typing import TYPE_CHECKING

import uvicorn
from fastapi.responses import JSONResponse

from grillui.api import create_app
from grillui.capture import capture, write_result
from grillui.drivers import FastDriver
from grillui.session import open_session
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import TextIO

    from starlette.types import ASGIApp, Receive, Scope, Send

    Runner = Callable[[ASGIApp, int, Callable[[], None]], None]

DEFAULT_PORT = 8765
LOOPBACK = "127.0.0.1"
PORT_SEARCH_SPAN = 64

LAST_PORT = 65535
NON_LOOPBACK_STATUS = 403
NON_LOOPBACK_DETAIL = "this session is served to loopback clients only"


def is_loopback(host: str) -> bool:
    """Whether an address is this machine talking to itself.

    Anything unparseable is not: a hostname reaching here means something
    rewrote the client address, and a name is not evidence about where a
    connection came from.
    """
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LoopbackOnly:
    """Refuse any request that did not come from this machine's loopback.

    Wrapped around the board rather than added inside it: which clients may
    reach a session is a property of how it was launched, and the board's own
    refusals are all about what a client said rather than where it is.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not is_loopback(_client_host(scope)):
            refusal = JSONResponse({"detail": NON_LOOPBACK_DETAIL}, status_code=NON_LOOPBACK_STATUS)
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)


def free_port(preferred: int, *, host: str = LOOPBACK) -> int:
    """The preferred port, or the next one after it that binds.

    Probed by binding rather than by asking anything: a port is free when the
    kernel hands it over, and every other answer is a guess. The bind is
    released before the server takes it, which leaves a window another process
    could win -- a launch that lost that race fails loudly at startup, which is
    the same thing a caller would have seen from a port they named themselves.
    """
    if not 0 < preferred <= LAST_PORT:
        outside = f"port {preferred} is outside 1-{LAST_PORT}"
        raise ValueError(outside)
    span_end = min(preferred + PORT_SEARCH_SPAN, LAST_PORT + 1)
    for port in range(preferred, span_end):
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    exhausted = f"no free port between {preferred} and {span_end - 1}"
    raise OSError(exhausted)


def session_url(port: int) -> str:
    """Where the human points a browser."""
    return f"http://{LOOPBACK}:{port}/"


def report(directory: Path, *, out: TextIO) -> int:
    """Write the session's terminal result and print it.

    The result is the whole of what leaves the directory. It carries references
    to the log and the images rather than their contents, so what a caller reads
    is a briefing over a grilling and not the grilling itself.
    """
    result = capture(directory)
    path = write_result(directory, result)
    # Stdout is the same bytes as the result file: one artifact, two places,
    # so piping stdout somewhere and reading the file cannot disagree.
    print(path.read_text(encoding="utf-8"), file=out)
    return 0


class _ReadyServer(uvicorn.Server):
    """A server that says when its socket is answering.

    The main loop is the signal: it is entered once the listening socket exists
    and is not entered at all by a server that failed to bind or whose startup
    asked to exit, so a caller hooked here hears about a server a browser can
    reach and never about one that could not start.

    The callback runs off the event loop, because handing a URL to the desktop
    is blocking work and the board has to be answering by the time the tab asks.
    """

    def __init__(self, config: uvicorn.Config, on_ready: Callable[[], None]) -> None:
        super().__init__(config)
        self._on_ready = on_ready

    async def main_loop(self) -> None:
        ready = asyncio.get_running_loop().run_in_executor(None, self._on_ready)
        ready.add_done_callback(_report_ready_failure)
        await super().main_loop()


def _report_ready_failure(done: asyncio.Future[None]) -> None:
    """A failed ready hook is said, not swallowed.

    The hook runs off the loop and nothing awaits it, so without this its
    exception would vanish; the server keeps serving either way, because a
    browser that did not open is the human's problem to notice, not a reason
    to end the session.
    """
    if not done.cancelled() and (error := done.exception()) is not None:
        print(f"grillui: opening the browser failed: {error}", file=sys.stderr, flush=True)


def serve_forever(app: ASGIApp, port: int, on_ready: Callable[[], None]) -> None:
    """Run the board until the process is stopped, saying when it starts answering."""
    _ReadyServer(uvicorn.Config(app, host=LOOPBACK, port=port), on_ready).run()


def stop_this_process() -> None:  # pragma: no cover
    """End the run, the way a Ctrl-C in the terminal would.

    An interrupt rather than an exit: the server owns the shutdown, so in-flight
    requests -- the human's own end-session gesture among them -- are answered
    before the process goes.
    """
    os.kill(os.getpid(), signal.SIGINT)


def launch(
    directory: Path,
    port: int = DEFAULT_PORT,
    handoff: Path | None = None,
    *,
    open_browser: bool = False,
    run: Runner = serve_forever,
    open_url: Callable[[str], bool] = webbrowser.open,
    stop: Callable[[], None] = stop_this_process,
    out: TextIO | None = None,
) -> int:
    """Open the session, hand the human its URL, and return its result.

    The URL is printed before the server takes the process over, so the human
    has it while the session is running rather than after it ends. Everything
    after `run` returns is the session being over.

    Opening a browser at that URL is opt-in, because a launch is usually driven
    by an agent on the human's behalf and a tab nobody asked for is noise on
    someone else's desktop. Asked for, it opens exactly once, and only once the
    board can answer -- a tab opened before the socket exists renders a refused
    connection, and a server that never started opens nothing at all.

    The human's end-session gesture is what ends the run: a session that has
    ended has nothing left to serve, and leaving the process up would leave the
    agent that launched it waiting on an exit that never comes.
    """
    stream = sys.stdout if out is None else out
    log = open_session(directory, handoff)
    board = create_app(log, FastDriver(TierConfig.from_env()), on_end=stop)
    bound = free_port(port)
    url = session_url(bound)
    print(url, file=stream, flush=True)

    def hand_over() -> None:
        if open_browser:
            open_url(url)

    run(LoopbackOnly(board), bound, hand_over)
    return report(directory, out=stream)


def _client_host(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else ""


__all__ = [
    "DEFAULT_PORT",
    "LoopbackOnly",
    "free_port",
    "is_loopback",
    "launch",
    "report",
    "session_url",
]
