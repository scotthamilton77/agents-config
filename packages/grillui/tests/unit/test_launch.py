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
import os
import signal
import socket
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from conftest import TIMEOUT, SpyDriver, driven, event, handoff_doc, post, write_handoff

from grillui.api import create_app
from grillui.drivers import FastDriver, HeavyDriver
from grillui.launch import (
    LOOPBACK,
    NON_LOOPBACK_STATUS,
    LoopbackOnly,
    RunStop,
    free_port,
    is_loopback,
    launch,
    report,
    session_url,
)
from grillui.log import RESULT_FILE, SessionLog
from grillui.schemas import FAST_TIER, HEAVY_TIER, SESSION_END_KIND, TRANSFER_FLAG
from grillui.session import open_session
from grillui.tiers import HEAVY_MODEL_ENV, REQUEST_TIMEOUT_ENV

from fastapi.testclient import TestClient  # isort: skip

if TYPE_CHECKING:
    from collections.abc import Callable

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


def test_the_url_is_printed_before_the_session_runs_and_no_browser_opens(
    session_dir: Path,
) -> None:
    """
    Given a launch that was not asked to open anything
    When it starts serving
    Then the URL it bound is on stdout before the server took the process over,
         and no browser was opened.

    The URL is only useful while the session is running, so printing it after
    the run would be printing it after the human needed it. Opening a tab is a
    separate question, and its answer here is no: the caller is usually an agent
    working on someone else's behalf, and the desktop is not its to interrupt.
    """
    opened: list[str] = []
    seen: list[str] = []
    stream = io.StringIO()

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda _app, _port, ready, _stop: (seen.append(stream.getvalue()), ready())[0],
        open_url=lambda url: bool(opened.append(url)),
        out=stream,
    )

    url = stream.getvalue().splitlines()[0]
    assert url.startswith(f"http://{LOOPBACK}:")
    assert seen == [f"{url}\n"]
    assert opened == []


def test_the_browser_opens_once_the_board_answers_and_not_before(session_dir: Path) -> None:
    """
    Given a launch asked to open a browser
    When the server reports it is accepting connections
    Then the browser is opened at that point -- once, after the report and
         before the run returns.

    A tab opened before the socket exists renders a refused connection, so the
    open has to wait on the server rather than on the launch having got as far
    as calling it.
    """
    order: list[str] = []
    stream = io.StringIO()

    def run(_app: ASGIApp, _port: int, ready: Callable[[], None], _stop: RunStop) -> None:
        order.append("accepting")
        ready()
        order.append("stopped")

    launch(
        session_dir,
        handoff=started(session_dir),
        open_browser=True,
        run=run,
        open_url=lambda url: bool(order.append(f"opened {url}")),
        out=stream,
    )

    url = stream.getvalue().splitlines()[0]
    assert order == ["accepting", f"opened {url}", "stopped"]


def test_a_server_that_never_starts_opens_nothing(session_dir: Path) -> None:
    """
    Given a launch asked to open a browser whose server fails to start
    When the failure surfaces
    Then no browser was opened.

    The port probe releases its bind before the server takes it, so a launch can
    lose that race and fail at startup. A tab pointed at a server that never
    bound is worse than no tab: it says the session is broken when it never ran.
    """
    opened: list[str] = []

    def refuse(_app: ASGIApp, _port: int, _ready: Callable[[], None], _stop: RunStop) -> None:
        lost = "address already in use"
        raise OSError(lost)

    with pytest.raises(OSError, match="address already in use"):
        launch(
            session_dir,
            handoff=started(session_dir),
            open_browser=True,
            run=refuse,
            open_url=lambda url: bool(opened.append(url)),
            out=io.StringIO(),
        )

    assert opened == []


def end_session(url: str) -> httpx.Response:
    """The human's end-session gesture, over the wire the page uses."""
    epoch = httpx.get(url + "status", timeout=10).json()["epoch"]
    return httpx.post(
        url + "events",
        timeout=10,
        json={
            "epoch": epoch,
            "events": [event(SESSION_END_KIND, actor="human", key="end", stop_reason="settled")],
        },
    )


def test_a_real_server_hands_over_a_url_that_answers_and_ends_on_the_gesture(
    session_dir: Path,
) -> None:
    """
    Given a launch asked to open a browser, over the real server
    When the opener is handed a URL and ends the session through it
    Then the request is answered at that moment, the end-session receipt is an
         acceptance the client is handed before the server goes, and the launch
         returns the terminal result having succeeded.

    Every other test here stubs the server, and none of them can see the two
    failures this guards. A browser opened while the socket did not yet exist
    puts a refused connection on screen; only a real bind settles that ordering.
    And a backend that ends its own run by interrupting itself hands the
    interrupt to its caller once the server gives the handler back, so the
    launch dies on the line after the run instead of printing what it captured.
    The interrupt is left armed here on purpose -- that is the arrangement under
    which the process this test runs in is the one that would take it.
    """
    answered: list[int] = []
    receipts: list[dict[str, Any]] = []

    def open_and_end(url: str) -> bool:
        answered.append(httpx.get(url, timeout=10).status_code)
        ended = end_session(url)
        answered.append(ended.status_code)
        receipts.extend(ended.json())
        return True

    stream = io.StringIO()
    status = launch(
        session_dir,
        handoff=started(session_dir),
        open_browser=True,
        open_url=open_and_end,
        out=stream,
    )

    assert status == 0
    assert answered == [200, 200]
    assert [receipt["status"] for receipt in receipts] == ["accepted"]
    assert "summary" in stream.getvalue()


def test_a_ctrl_c_the_backend_did_not_send_aborts_without_a_result(session_dir: Path) -> None:
    """
    Given a real server that the human interrupts
    When the interrupt is not the backend answering an end-session gesture
    Then the run aborts and prints no result.

    A Ctrl-C is someone abandoning the session, not finishing it. Ending the run
    on the gesture must not turn every interrupt into a terminal result, which
    would report a grilling as settled because the human walked away from it.
    """
    stream = io.StringIO()

    def interrupt_the_run(url: str) -> bool:
        assert httpx.get(url, timeout=10).status_code == 200
        os.kill(os.getpid(), signal.SIGINT)
        return True

    with pytest.raises(KeyboardInterrupt):
        launch(
            session_dir,
            handoff=started(session_dir),
            open_browser=True,
            open_url=interrupt_the_run,
            out=stream,
        )

    printed = stream.getvalue()
    assert printed.startswith(f"http://{LOOPBACK}:")
    assert printed.splitlines()[1:] == [], "the URL was printed, and nothing after it"
    assert not (session_dir / RESULT_FILE).exists()


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
        run=lambda _app, port, _ready, _stop: bound.append(port),
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
        run=lambda app, _port, _ready, _stop: apps.append(app),
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

    def exit_now(_app: ASGIApp, _port: int, _ready: Callable[[], None], _stop: RunStop) -> None:
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
    stop = RunStop()
    stop.arm(lambda: stopped.append(True))

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port, _ready, _stop: apps.append(app),
        open_url=lambda _url: True,
        stop=stop,
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
        run=lambda _app, _port, _ready, _stop: None,
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
        run=lambda app, _port, _ready, _stop: apps.append(app),
        open_url=lambda _url: True,
        stop=RunStop(),
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

    def refuse_to_die() -> None:
        death = "the process refused to die"
        raise RuntimeError(death)

    failing_stop = RunStop()
    failing_stop.arm(refuse_to_die)

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port, _ready, _stop: apps.append(app),
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


def test_a_failing_ready_hook_is_reported_and_does_not_stop_the_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Given the ready hook's future failed
    When its completion is reported
    Then the failure is printed to stderr and nothing is raised.

    The hook runs off the loop and nothing awaits it; a swallowed failure
    would leave the human waiting for a tab that was never going to open.
    """
    import asyncio

    from grillui.launch import _report_ready_failure

    loop = asyncio.new_event_loop()
    try:
        failed: asyncio.Future[None] = loop.create_future()
        failed.set_exception(OSError("no desktop"))
        _report_ready_failure(failed)
        fine: asyncio.Future[None] = loop.create_future()
        fine.set_result(None)
        _report_ready_failure(fine)
        cancelled: asyncio.Future[None] = loop.create_future()
        cancelled.cancel()
        _report_ready_failure(cancelled)
    finally:
        loop.close()
    err = capsys.readouterr().err
    assert "opening the browser failed: no desktop" in err
    assert err.count("opening the browser failed") == 1


# ── GUI-U11 / GUI-A34: the tiers a launched session actually has ──


def test_the_launched_board_is_given_a_heavy_expert_tier_on_the_one_configuration(
    session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a launch
    When it builds the board
    Then the board is handed a heavy expert tier beside the fast one, both on
         the single configuration the launch read out of the environment.

    A board launched without an expert tier has nowhere to escalate to: the
    human's transfer lands in the log and the control flips, but every turn
    still runs fast. The two tiers share one configuration object because they
    are one session's settings -- a heavy tier built from a second read could be
    billed to a model the launch never announced.
    """
    monkeypatch.setenv(HEAVY_MODEL_ENV, "claude-from-the-process")
    monkeypatch.setenv(REQUEST_TIMEOUT_ENV, "300")
    built: list[dict[str, Any]] = []
    real = create_app

    def recording(log: SessionLog, driver: Any = None, **rest: Any) -> Any:
        built.append({"driver": driver, **rest})
        return real(log, driver, **rest)

    monkeypatch.setattr("grillui.launch.create_app", recording)

    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda _app, _port, _ready, _stop: None,
        open_url=lambda _url: True,
        stop=RunStop(),
        out=io.StringIO(),
    )

    assert len(built) == 1
    fast, expert = built[0]["driver"], built[0]["expert"]
    assert isinstance(fast, FastDriver)
    assert isinstance(expert, HeavyDriver)
    assert expert.config is fast.config
    assert expert.config.heavy_model == "claude-from-the-process"
    # The expert is seated through the same door as every other seat, so the
    # session's timeout reaches it: an expert built by hand keeps the constant.
    assert isinstance(expert.cli, partial)
    assert expert.cli.keywords == {"timeout": 300.0}


def test_a_transfer_on_a_launched_board_takes_that_channels_next_turn_to_the_expert(
    session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a launched session whose thread has already had a turn on the fast
          tier
    When the human transfers that channel to the expert
    Then the next turn on it is taken by the expert tier, and the fast one is
         not asked again.

    Asserted through a board a launch built rather than through a lane a test
    assembled: the tier selection was already right, and what was missing was
    the launch ever handing it a tier to select.
    """
    fast, expert = SpyDriver(tier=FAST_TIER), SpyDriver(tier=HEAVY_TIER)
    real = create_app

    def spied(log: SessionLog, driver: Any = None, **rest: Any) -> Any:
        """The board the launch asked for, with each tier it named stood in for
        by a spy -- so a launch that named no expert tier gets a board with
        none, and nothing here reaches a model."""
        rest["expert"] = expert if rest.get("expert") is not None else None
        return real(log, fast if driver is not None else None, **rest)

    monkeypatch.setattr("grillui.launch.create_app", spied)
    apps: list[ASGIApp] = []
    launch(
        session_dir,
        handoff=started(session_dir),
        run=lambda app, _port, _ready, _stop: apps.append(app),
        open_url=lambda _url: True,
        stop=RunStop(),
        out=io.StringIO(),
    )
    client = TestClient(apps[0], client=(LOOPBACK, 51000))
    epoch = client.get("/status").json()["epoch"]

    post(
        client,
        epoch,
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
    assert fast.started.wait(TIMEOUT)
    post(
        client,
        epoch,
        event(
            "thread-turn",
            actor="human",
            channel=THREAD,
            key="escalate",
            turns=[{"text": "Weigh that against the archive cost."}],
            **{TRANSFER_FLAG: True},
        ),
    )

    assert expert.started.wait(TIMEOUT)
    assert len(fast.dispatches) == 1
