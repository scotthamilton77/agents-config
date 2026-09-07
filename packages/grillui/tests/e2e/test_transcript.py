"""What the expert turn read, kept where the session is.

A CLI prunes its own transcripts on a retention window, so the session
directory is the only place a turn's reads survive being looked at months
later -- and it is the thing that gets archived. The chain that produced a
reply is on the log beside it, because the file holding the chain's identity
forgets it the moment a channel is reopened cold.

The shim writes its transcript where the real CLI writes one, out of its own
statement of that layout rather than out of the driver's. The two agreeing is
the evidence; a shim that wrote wherever the driver looked would agree by
construction and would stop being evidence the moment the real layout moved.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from conftest import agent_turns, decision, document, handoff, turn
from harness import POLL, TURN_TIMEOUT

from grillui.log import TRANSCRIPT_DIR
from grillui.schemas import CHAIN_KEY

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Where does a session live?"), decision("d2", "For how long?")]
CHAIN = "chain-of-the-expert"
SAID = "The expert took this one."


def landed(path: Path) -> str:
    """The copy, once it is there.

    Waited for rather than asserted outright: the copy is deliberately off the
    turn's own clock, so the gesture the scenario made can be wholly settled
    with the copy still in flight.
    """
    deadline = time.monotonic() + TURN_TIMEOUT
    while time.monotonic() < deadline:
        if path.is_file():
            return path.read_text(encoding="utf-8")
        time.sleep(POLL)
    missing = f"no transcript copy reached {path}"
    raise AssertionError(missing)


def test_an_expert_turn_leaves_its_transcript_in_the_session_directory(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a map channel the human has moved to the expert seat
    When they answer, and the CLI answers on a chain whose transcript it kept
    Then the reply on the log names that chain, and the session directory holds
         that chain's transcript under its own name -- so the turn's reads
         outlive the CLI's retention window.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_claude(turn(document(SAID), session_id=CHAIN))
    page = board(session)

    page.click('[data-act="transfer"][data-channel="map"]')
    page.wait_for_timeout(300)
    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()

    spoke = agent_turns(session.entries())[-1]
    assert spoke.payload[CHAIN_KEY] == CHAIN, spoke.payload
    kept = landed(session.directory / TRANSCRIPT_DIR / f"{CHAIN}.jsonl")
    # What the shim wrote onto the chain's transcript is what the copy carries,
    # so the copy is that transcript rather than an empty file under its name.
    wrote = [json.loads(line) for line in kept.splitlines() if line.strip()]
    assert [one["text"] for one in wrote] == [session.claude_calls()[0]["prompt"]], wrote
