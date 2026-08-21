"""The launch path: who may reach the board, which port it lands on, and what
the launching agent is left holding when the session is over.

The server itself is stubbed throughout. A launch that stood a real socket up
would be testing uvicorn; what is this package's is everything around the run --
the address the board refuses, the port it settles on, the URL it hands over,
and the fact that the result is produced by the run having ended rather than by
anything watching a clock.
"""

from __future__ import annotations

import io
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import SpyDriver, driven, event, handoff_doc, post, write_handoff

from grillui.api import create_app
from grillui.launch import (
    LOOPBACK,
    NON_LOOPBACK_STATUS,
    LoopbackOnly,
    free_port,
    is_loopback,
    launch,
    report,
    session_url,
)
from grillui.log import RESULT_FILE, SessionLog
from grillui.schemas import SESSION_END_KIND
from grillui.session import open_session

from fastapi.testclient import TestClient  # isort: skip

if TYPE_CHECKING:
    from starlette.types import ASGIApp

OFF_MACHINE = "10.11.12.13"
THREAD = "t-compaction"
TURN_TEXT = "TURN-TEXT-THE-HUMAN-TYPED-INTO-A-THREAD"
DISPATCH_TEXT = "DISPATCH-PROMPT-TEXT-THE-BACKEND-SENT-AN-AGENT"


def served(session_dir: Path, client_host: str) -> TestClient:
    """A client over a launched board, presenting one address."""
    app: ASGIApp = LoopbackOnly(create_app(SessionLog(session_dir)))
    return TestClient(app, client=(client_host, 51000))


def started(session_dir: Path) -> Path:
    """A session directory briefed and ready to launch."""
    return write_handoff(session_dir, handoff_doc())


# ── GUI-D28 / GUI-A51: loopback only ──


def test_a_request_from_off_the_loopback_is_refused(session_dir: Path) -> None:
    """
    Given a launched board
    When a request arrives from an address that is not this machine
    Then it is refused, and the board is not read.

    Binding loopback is what keeps such a connection from arriving at all; this
    is the same rule stated where a rewritten client address cannot get around
    it.
    """
    response = served(session_dir, OFF_MACHINE).get("/status")

    assert response.status_code == NON_LOOPBACK_STATUS
    assert "loopback" in response.json()["detail"]


def test_a_loopback_request_is_served(session_dir: Path) -> None:
    """
    Given a launched board
    When the request comes from loopback
    Then it is answered as the board would answer it unwrapped.

    The refusal has to be about the address and nothing else: a guard that also
    changed what a local page sees would be a different backend.
    """
    response = served(session_dir, LOOPBACK).get("/status")

    assert response.status_code == 200
    assert response.json()["seq"] == 0


@pytest.mark.parametrize(
    ("host", "local"),
    [("127.0.0.1", True), ("127.0.0.53", True), ("::1", True), ("10.0.0.4", False), ("", False)],
)
def test_only_this_machines_own_addresses_count_as_loopback(host: str, local: bool) -> None:
    """
    Given an address presented as a request's client
    When it is judged
    Then only the loopback range answers true, and an unparseable address does
         not.

    A client address that is not an address at all means something rewrote it,
    and a name is not evidence about where a connection came from.
    """
    assert is_loopback(host) is local


# ── GUI-D28 / GUI-A51: the port ──


def test_the_next_free_port_is_taken_when_the_preferred_one_is_occupied() -> None:
    """
    Given a port already bound on loopback
    When a launch prefers that port
    Then it settles on a later one that binds.

    Two sessions on one machine is the ordinary case, and the second must not
    fail on a number nobody chose.
    """
    with socket.socket() as taken:
        taken.bind((LOOPBACK, 0))
        taken.listen()
        occupied = taken.getsockname()[1]

        chosen = free_port(occupied)

    assert chosen > occupied
    with socket.socket() as probe:
        probe.bind((LOOPBACK, chosen))


def test_the_preferred_port_is_kept_when_nothing_holds_it() -> None:
    """
    Given a free port
    When a launch prefers it
    Then that is the port it takes.

    Fallback is a fallback: a launch that walked past a free default would make
    the documented port a lie.
    """
    with socket.socket() as free:
        free.bind((LOOPBACK, 0))
        available = free.getsockname()[1]

    assert free_port(available) == available


# ── GUI-D28 / GUI-A51: the URL ──


def test_the_url_is_printed_and_opened_before_the_session_runs(session_dir: Path) -> None:
    """
    Given a launch
    When it starts serving
    Then the URL it bound is on stdout and was handed to the browser, both
         before the server took the process over.

    The URL is only useful while the session is running, so printing it after
    the run would be printing it after the human needed it.
    """
    opened: list[str] = []
    seen: list[str] = []
    stream = io.StringIO()

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda _app, _port: seen.append(stream.getvalue()),
        open_url=lambda url: bool(opened.append(url)),
        out=stream,
    )

    url = stream.getvalue().splitlines()[0]
    assert url.startswith(f"http://{LOOPBACK}:")
    assert opened == [url]
    assert seen == [f"{url}\n"]


def test_the_port_the_server_is_given_is_the_port_in_the_url(session_dir: Path) -> None:
    """
    Given a launch
    When it hands the app to the server
    Then the port it binds is the one it told the human about.

    A URL naming a port the server never took sends the human to nothing.
    """
    bound: list[int] = []

    stream = io.StringIO()
    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda _app, port: bound.append(port),
        open_url=lambda _url: True,
        out=stream,
    )

    assert stream.getvalue().splitlines()[0] == session_url(bound[0])


def test_the_board_the_server_is_handed_refuses_non_loopback(session_dir: Path) -> None:
    """
    Given a launch
    When the app reaches the server
    Then it is the guarded one.

    The guard is only real if it is what gets served; a launch that built one
    and ran another would pass every test above and ship an open board.
    """
    apps: list[ASGIApp] = []

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port: apps.append(app),
        open_url=lambda _url: True,
        out=io.StringIO(),
    )

    remote = TestClient(apps[0], client=(OFF_MACHINE, 51000))
    assert remote.get("/status").status_code == NON_LOOPBACK_STATUS


# ── GUI-D22 / GUI-A42: the wait is the process ──


def test_the_launch_returns_on_backend_exit_and_never_on_a_timer(
    session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a launch whose backend exit is stubbed
    When the stubbed server returns
    Then the result is produced after that return and not before, and nothing
         slept while waiting.

    The agent that launched the session waits by not having returned yet. A poll
    would pay a round-trip to learn what process exit already says, and would
    make the wait a timer's business rather than the session's.
    """

    def never(_seconds: float) -> None:
        polled = "the launch waited on a clock instead of on the process"
        raise AssertionError(polled)

    monkeypatch.setattr(time, "sleep", never)
    stream = io.StringIO()
    during: list[str] = []

    def exit_now(_app: ASGIApp, _port: int) -> None:
        during.append(stream.getvalue())

    assert launch(session_dir, handoff=started(session_dir), run=exit_now, out=stream) == 0
    assert during == [stream.getvalue().splitlines()[0] + "\n"]
    assert "summary" in stream.getvalue()


def test_the_human_ending_the_session_stops_the_run(session_dir: Path) -> None:
    """
    Given a launched session
    When the human's end-session gesture is accepted
    Then the run is asked to stop.

    This is the exit the launching agent is waiting on. A backend still serving
    a session that ended leaves that agent waiting on nothing, which is the one
    way a wait with no timer can fail.
    """
    apps: list[ASGIApp] = []
    stopped: list[bool] = []

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port: apps.append(app),
        open_url=lambda _url: True,
        stop=lambda: stopped.append(True),
        out=io.StringIO(),
    )
    client = TestClient(apps[0], client=(LOOPBACK, 51000))
    ended = client.post(
        "/events",
        json={
            "epoch": client.get("/status").json()["epoch"],
            "events": [event(SESSION_END_KIND, actor="human", key="end")],
        },
    ).json()

    assert ended[0]["status"] == "accepted"
    assert stopped == [True]


# ── GUI-D8 / GUI-A29: the result, and nothing else ──


def test_what_the_launch_prints_is_the_result_and_never_the_transcript(
    session_dir: Path,
) -> None:
    """
    Given a session whose log holds thread turns and whose directory holds a
          recorded dispatch
    When the launch returns
    Then what it printed is the terminal result and its file references, with no
         turn and no dispatch prompt anywhere in it.

    The transcript stays in the session directory. Handing it back would spend
    the launching agent's context on the grilling it deliberately stepped out
    of.
    """
    log = open_session(session_dir, started(session_dir))
    client = driven(log, SpyDriver())
    post(
        client,
        log.epoch,
        event(
            "thread-created",
            actor="human",
            channel=THREAD,
            key="open-thread",
            decision="d1",
            kind="mandate",
            title="Compaction policy",
            turns=[{"who": "human", "text": TURN_TEXT}],
        ),
    )
    post(
        client,
        log.epoch,
        event(SESSION_END_KIND, actor="human", key="end", stop_reason="settled enough"),
    )
    (session_dir / "dispatches").mkdir(exist_ok=True)
    (session_dir / "dispatches" / "map-1.json").write_text(DISPATCH_TEXT, encoding="utf-8")
    del client

    stream = io.StringIO()
    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda _app, _port: None,
        open_url=lambda _url: True,
        out=stream,
    )

    printed = stream.getvalue()
    assert TURN_TEXT not in printed
    assert DISPATCH_TEXT not in printed
    assert "settled enough" in printed
    assert "log.jsonl" in printed


def test_the_result_is_written_beside_the_log_as_well_as_printed(session_dir: Path) -> None:
    """
    Given a session directory
    When it is captured
    Then the printed result is the one left on disk.

    What the launching agent quotes and what the next reader opens have to be
    the same object, or the references it carries point at a different session
    than the summary describes.
    """
    open_session(session_dir, started(session_dir))
    stream = io.StringIO()

    assert report(session_dir, out=stream) == 0

    written = (session_dir / RESULT_FILE).read_text(encoding="utf-8")
    assert '"references"' in written
    assert "grill-1" in stream.getvalue()


def test_a_port_past_the_top_of_the_range_is_an_honest_refusal() -> None:
    """
    Given the highest port there is, already occupied
    When a launch prefers it
    Then the answer is the no-free-port refusal, not a crash past 65535.

    The probe stops at the top of the port range instead of walking off it,
    and a preference outside the range is refused by name.
    """
    with socket.socket() as taken:
        try:
            taken.bind((LOOPBACK, 65535))
            taken.listen()
        except OSError:
            pass  # someone else holds it, which occupies it just as well
        with pytest.raises(OSError, match="no free port"):
            free_port(65535)
    for outside in (0, -1, 65536):
        with pytest.raises(ValueError, match="outside"):
            free_port(outside)


def test_stdout_and_the_result_file_are_the_same_bytes(session_dir: Path) -> None:
    """
    Given a session whose log is terminal-ready
    When the result is reported
    Then stdout is byte-identical to the result file, plus print's newline.

    One artifact in two places: a caller piping stdout somewhere and a caller
    reading the file must not be able to disagree.
    """
    apps: list[ASGIApp] = []
    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port: apps.append(app),
        open_url=lambda _url: True,
        stop=lambda: None,
        out=io.StringIO(),
    )
    client = TestClient(apps[0], client=(LOOPBACK, 51000))
    client.post(
        "/events",
        json={
            "epoch": client.get("/status").json()["epoch"],
            "events": [event(SESSION_END_KIND, actor="human", key="end")],
        },
    )
    out = io.StringIO()
    assert report(session_dir, out=out) == 0
    assert out.getvalue() == (session_dir / RESULT_FILE).read_text(encoding="utf-8") + "\n"


def test_a_failing_stop_hook_does_not_poison_the_end_receipt(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a launched session whose stop hook raises
    When the human's end-session gesture is accepted
    Then the receipt is still an acceptance, the ending is still durable,
         and the failure is said aloud rather than swallowed.

    The ending is the human's and is already written; a hook the launcher
    supplied cannot turn it into a transport failure after the fact.
    """
    apps: list[ASGIApp] = []

    def failing_stop() -> None:
        death = "the process refused to die"
        raise RuntimeError(death)

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port: apps.append(app),
        open_url=lambda _url: True,
        stop=failing_stop,
        out=io.StringIO(),
    )
    client = TestClient(apps[0], client=(LOOPBACK, 51000))
    ended = client.post(
        "/events",
        json={
            "epoch": client.get("/status").json()["epoch"],
            "events": [event(SESSION_END_KIND, actor="human", key="end")],
        },
    )

    assert ended.status_code == 200
    assert ended.json()[0]["status"] == "accepted"
    assert (session_dir / RESULT_FILE).exists()
    assert "stop hook failed" in capsys.readouterr().err
