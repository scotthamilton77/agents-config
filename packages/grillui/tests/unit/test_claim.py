"""One main window per session, measured at the wire.

Everything here is about a control that sits deliberately outside the record.
The board is an append-only log and every gesture on it lands there; which window
is driving is not a gesture on the board, and the checks below hold that line
from both sides -- the claim answers correctly, and the log does not move while
it does.

The claim is a name a window presents rather than a capability the backend hands
out, and that single decision is what makes a reload free, a pop-out sanctioned
and a second window refused: all three are the same question -- is this the name
that holds the session -- asked by three different windows. The tests are written
that way too, in terms of names rather than of browser mechanics, because the
browser mechanics are what the page's own checks and the browser run cover.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import event, post
from fastapi.testclient import TestClient

from grillui.api import create_app
from grillui.claim import CLAIM_STATES, GRANTED, REFUSED, SUPERSEDED, Claim, session_token
from grillui.log import LOG_FILE, SessionLog

FIRST = "window-one"
SECOND = "window-two"


def present(client: TestClient, holder: str, *, takeover: bool = False) -> dict[str, Any]:
    """One window presenting its name, exactly as the page does."""
    response = client.post("/claim", json={"holder": holder, "takeover": takeover})
    assert response.status_code == 200
    answer: dict[str, Any] = response.json()
    return answer


def state(client: TestClient, holder: str, *, takeover: bool = False) -> str:
    answer = present(client, holder, takeover=takeover)
    assert answer["state"] in CLAIM_STATES
    return str(answer["state"])


def log_entries(session_dir: Path) -> list[dict[str, Any]]:
    path = session_dir / LOG_FILE
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------- GUI-A19


def test_the_first_window_to_present_a_name_is_granted_the_session(client: TestClient) -> None:
    """Nobody holds a fresh session, so whoever asks first gets it.

    Granting on the first ask rather than on some registration step is what lets
    a restarted backend hand a session straight back to the window still asking
    for it, with nothing for the human to do.
    """
    assert state(client, FIRST) == GRANTED


def test_a_second_main_window_is_refused_with_a_reason_of_its_own(client: TestClient) -> None:
    """The clause this whole control exists for.

    Refused rather than queued, and refused by a name of its own rather than by
    silence or an error status: the page has to say *why* this window is not
    showing a board, and "another window has it" and "you were taken over" are
    different sentences with different next moves.
    """
    assert state(client, FIRST) == GRANTED
    assert state(client, SECOND) == REFUSED
    # And the refusal did not quietly move the session either -- the first window
    # still holds it after being asked about.
    assert state(client, FIRST) == GRANTED


def test_the_claiming_window_presenting_its_name_again_keeps_the_claim(
    client: TestClient,
) -> None:
    """A reload is not a second window, and must never be a lockout.

    The window presents the same name it stored, so the backend cannot tell a
    reload from any other re-presentation -- which is the point. Were the claim
    bound to anything the reload discards, the human would lock themselves out
    of their own session by pressing refresh.
    """
    assert state(client, FIRST) == GRANTED
    for _ in range(3):
        assert state(client, FIRST) == GRANTED


def test_a_pop_out_riding_the_parent_name_is_admitted(client: TestClient) -> None:
    """Pop-outs are the sanctioned exception, and they need no exception.

    A pop-out carries its parent's name, so it presents what the holder presents
    and is granted by the ordinary rule. A rule of its own -- a pop-out flag, a
    second kind of claim -- would be a second way to be admitted, and the only
    thing it could add is a way to be admitted wrongly.
    """
    parent, popout, stranger = FIRST, FIRST, SECOND
    assert state(client, parent) == GRANTED
    # The pop-out presents while the parent is still presenting, and neither
    # displaces the other: they are one window as far as the session is
    # concerned, which is what "rides the parent's token" means.
    assert state(client, popout) == GRANTED
    assert state(client, parent) == GRANTED
    assert state(client, stranger) == REFUSED, "riding a token did not open the session up"
    # And a pop-out belongs to the window that opened it: when the parent loses
    # the session, so does everything carrying its name.
    assert state(client, stranger, takeover=True) == GRANTED
    assert state(client, popout) == SUPERSEDED


def test_an_explicit_take_over_displaces_the_holder(client: TestClient) -> None:
    """The recovery path for a claim that is genuinely lost.

    Explicit because it cannot be inferred: a window that is gone and a window
    that is merely slow present identically -- which is nothing at all -- so an
    expiry would evict a working session for being quiet. Only the human can
    tell, so only the human does it.
    """
    assert state(client, FIRST) == GRANTED
    assert state(client, SECOND) == REFUSED
    assert state(client, SECOND, takeover=True) == GRANTED
    assert state(client, SECOND) == GRANTED


def test_a_superseded_window_is_told_it_was_superseded_and_not_merely_refused(
    client: TestClient,
) -> None:
    """The two refusals are different situations and read differently.

    A window that never held the session is looking at one somebody else opened.
    A superseded window held it, has a board on screen, and has to be told to
    stop showing it. Collapsing them would tell a human whose window just went
    quiet that they had opened a second window, which is not what happened.
    """
    assert state(client, FIRST) == GRANTED
    assert state(client, SECOND, takeover=True) == GRANTED
    assert state(client, FIRST) == SUPERSEDED
    # And the state is stable: the superseded window asking again is told the
    # same thing rather than drifting back to a plain refusal.
    assert state(client, FIRST) == SUPERSEDED


def test_a_superseded_window_can_be_given_the_session_back_only_by_asking_for_it(
    client: TestClient,
) -> None:
    """Taking it back is the same explicit gesture, made the other way.

    Nothing about being superseded is permanent -- the human may have taken over
    in the wrong window -- but nothing about it heals on its own either, because
    a claim that drifted back would mean two windows swapping the session between
    them while the human watched.
    """
    assert state(client, FIRST) == GRANTED
    assert state(client, SECOND, takeover=True) == GRANTED
    assert state(client, FIRST) == SUPERSEDED
    assert state(client, FIRST, takeover=True) == GRANTED
    assert state(client, SECOND) == SUPERSEDED


def test_a_window_presenting_no_name_at_all_is_refused_before_anything_is_decided(
    client: TestClient,
) -> None:
    """An empty name would match the next empty name.

    Every window presenting nothing would then be granted the same claim, which
    is the one outcome this control exists to prevent -- so it is refused as a
    malformed request rather than reasoned about.
    """
    assert client.post("/claim", json={"holder": "", "takeover": False}).status_code == 422
    assert client.post("/claim", json={"takeover": True}).status_code == 422


def test_no_session_control_action_appends_a_board_event(
    client: TestClient, log: SessionLog, session_dir: Path
) -> None:
    """The load-bearing separation: session control is not board history.

    Which window is driving is not part of the grilling, and a log that carried
    it would make the record depend on the browser. The whole cycle runs here --
    claim, refuse, take over, be superseded, take back -- and the log is measured
    before and after, with a real write in between so the counter is known to
    move when something genuinely happens.
    """
    before = len(log_entries(session_dir))
    seq_before = log.seq

    assert state(client, FIRST) == GRANTED
    assert state(client, SECOND) == REFUSED
    assert state(client, SECOND, takeover=True) == GRANTED
    assert state(client, FIRST) == SUPERSEDED
    assert state(client, FIRST, takeover=True) == GRANTED

    assert len(log_entries(session_dir)) == before, "a session-control action reached the log"
    assert log.seq == seq_before, "a session-control action moved the log's position"

    # The control against the control: a board event does move both.
    post(client, log.epoch, event("informational", key="proof", text="something happened"))
    assert len(log_entries(session_dir)) == before + 1
    assert log.seq == seq_before + 1

    # And the claim survives a board write untouched, because they are unrelated.
    assert state(client, FIRST) == GRANTED


def test_no_session_control_action_reaches_the_board_the_page_reads(
    client: TestClient, log: SessionLog
) -> None:
    """Nor does it show up in what the page renders from.

    The log is one measure; the images the page actually draws are the other, and
    a control that stayed out of the log but appeared in an image would still be
    a claim the human could see on their board.
    """
    tail = {"epoch": log.epoch, "cursor": 0}
    board_before = client.get("/state").json()
    updates_before = client.get("/updates", params=tail).json()

    state(client, FIRST)
    state(client, SECOND)
    state(client, SECOND, takeover=True)
    state(client, FIRST)

    assert client.get("/state").json() == board_before
    assert client.get("/updates", params=tail).json() == updates_before


# ---------------------------------------------------------------- the token


def test_the_session_token_names_the_directory_and_not_the_tenure(tmp_path: Path) -> None:
    """Stable across a restart, because what it scopes is.

    The page keys its read-state by this token, and read-state names log entries
    -- which survive a restart. A per-process token would discard the human's
    read markers every time the backend came back, relighting every notification
    they had already dealt with, against entries that never changed.
    """
    directory = tmp_path / "session"
    first = Claim(directory)
    second = Claim(directory)
    assert first.token == second.token
    assert first.token == session_token(directory)
    # Different sessions are different tokens, which is what keeps two of them
    # that happen to reuse a loopback port out of each other's stored state.
    assert Claim(tmp_path / "other").token != first.token


def test_the_token_rides_every_answer_because_the_page_needs_it_first(client: TestClient) -> None:
    """The page asks this before it reads anything, so this is where the token
    has to be: it scopes the page's own storage, and the page has to scope it
    before it loads a single marker."""
    for holder, expected in ((FIRST, GRANTED), (SECOND, REFUSED)):
        answer = present(client, holder)
        assert answer["state"] == expected
        assert answer["token"], "an answer with no token leaves the page nothing to key on"


def test_a_restarted_backend_hands_the_session_back_to_the_window_still_asking(
    session_dir: Path,
) -> None:
    """The claim is this process's and is deliberately not written down.

    It exists to stop two *live* windows writing to one *live* backend. A backend
    that is gone has no windows to arbitrate between, and a claim on disk would
    outlive the thing it described -- locking a human out of their own session
    after a crash, with no window anywhere to take it over from.
    """
    first_run = TestClient(create_app(SessionLog(session_dir)))
    assert state(first_run, FIRST) == GRANTED
    assert state(first_run, SECOND) == REFUSED

    second_run = TestClient(create_app(SessionLog(session_dir)))
    # Same session, same token -- so the page's read-state comes back with it.
    assert present(second_run, SECOND)["token"] == present(first_run, FIRST)["token"]
    # And a fresh arbitration: the claim did not survive, and neither did the
    # record of who had been superseded by whom.
    assert state(second_run, SECOND) == GRANTED


# ---------------------------------------------------------------- concurrency


def test_two_backends_on_different_session_directories_do_not_interfere(
    tmp_path: Path,
) -> None:
    """Concurrent sessions are separate processes, and this is what that buys.

    One process holds one session directory, so there is no shared claim, no
    shared log and no shared token -- the isolation is structural rather than
    something the claim has to enforce per session. What is measured here is that
    nothing was accidentally made global on the way.
    """
    here = TestClient(create_app(SessionLog(tmp_path / "a")))
    there = TestClient(create_app(SessionLog(tmp_path / "b")))

    assert present(here, FIRST)["token"] != present(there, FIRST)["token"]

    # A take-over in one session leaves the other's claim exactly where it was.
    assert state(here, FIRST) == GRANTED
    assert state(there, FIRST) == GRANTED
    assert state(here, SECOND, takeover=True) == GRANTED
    assert state(here, FIRST) == SUPERSEDED
    assert state(there, FIRST) == GRANTED, "a take-over reached across two sessions"

    # And the boards stay their own: a write to one is invisible in the other.
    here_epoch = here.get("/state").json()["epoch"]
    post(here, here_epoch, event("informational", key="only-here", text="over here"))
    assert here.get("/state").json()["seq"] == 1
    assert there.get("/state").json()["seq"] == 0


@pytest.mark.parametrize("word", CLAIM_STATES)
def test_every_claim_state_is_reachable_at_the_wire(word: str, tmp_path: Path) -> None:
    """The vocabulary is closed and every word in it is answered by some path.

    A state nothing can produce is a state the page renders for and no human ever
    sees -- and one it cannot produce is a page rendering nothing at all.
    """
    client = TestClient(create_app(SessionLog(tmp_path / word)))
    reached = {state(client, FIRST), state(client, SECOND)}
    reached.add(state(client, SECOND, takeover=True))
    reached.add(state(client, FIRST))
    assert word in reached
