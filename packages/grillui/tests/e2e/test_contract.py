"""The seats' contract, asserted from outside the code that implements it.

Every scripted call is recorded whole -- argv, working directory, whether
standard input was closed, and what the seat was briefed with -- and every
scenario reads the violations back. This file is where that check is checked.

A contract assertion nobody has watched fail is not evidence. So the shim is
also run by hand here with an argv that departs from the contract on purpose,
and the departures are read back by name; and it is run with the argv the driver
itself builds, which must come back clean. Those two together are what make
`violations == []` mean something everywhere else: the check discriminates, and
the thing it agrees with is the driver's own output rather than a copy of it.

The shims deliberately restate the contract rather than importing it. One that
called `codex_argv` to decide what `codex_argv` should produce would agree with
it by construction, and could never catch it drifting.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from conftest import decision, document, handoff, turn
from harness import SCRIPT_ENV, SHIM_DIR

from grillui.drivers import claude_argv, codex_argv
from grillui.tiers import Seat

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from harness import Session
    from playwright.sync_api import Page

PLAN = [decision("d1", "Which storage?"), decision("d2", "How is it compacted?")]
SEAT = Seat("codex", "gpt-5.6-luna", "medium")
BRIEF = "You are the grill-master."
PROMPT = "## Your turn"


def run_shim(
    name: str, argv: Sequence[str], scratch: Path, *, closed: bool = True
) -> dict[str, Any]:
    """Run one shim by hand and return the call it recorded.

    The turn it is asked for is not scripted, so it exits saying so -- which is
    fine and is the point: the call is recorded before anything is answered, so
    what it was given is on the record whether or not there was a turn to take.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 -- argv is built here, never a shell string
        [str(SHIM_DIR / name), *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        stdin=subprocess.DEVNULL if closed else subprocess.PIPE,
        env={**_environment(scratch), "PATH": f"{SHIM_DIR}:{Path(sys.executable).parent}"},
    )
    written = (scratch / f"{name}-calls.jsonl").read_text(encoding="utf-8").splitlines()
    recorded: dict[str, Any] = json.loads(written[-1])
    return recorded


def _environment(scratch: Path) -> dict[str, str]:
    return {SCRIPT_ENV: str(scratch)}


def test_every_call_a_driven_session_makes_keeps_the_contract(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a session that takes one first-rung turn and one expert turn
    When both seats have been called
    Then neither call departs from its contract, and the facts the contract is
         made of are on the record by name: standard input closed, the Codex
         turn run in the session's own directory rather than wherever the
         backend was launched, no strict output schema asked for, both execution
         features closed off beside a read-only sandbox and a policy that
         approves nothing, and a standing brief on every invocation.
    """
    session = launcher(handoff=handoff(PLAN))
    session.script_codex(turn(document("First rung.")))
    session.script_claude(turn(document("Expert.")))
    page = board(session)

    page.click('#col-d1 [data-act="pick"][data-opt="a"]')
    session.settled()
    page.click('[data-act="transfer"][data-channel="map"]')
    page.wait_for_timeout(300)
    page.click('#col-d2 [data-act="pick"][data-opt="a"]')
    session.settled()

    codex = session.codex_calls()
    claude = session.claude_calls()
    assert len(codex) == 1 and len(claude) == 1, (codex, claude)
    for call in (*codex, *claude):
        assert call["violations"] == [], call["violations"]
        assert call["stdin_devnull"] is True, call
        assert call["brief"], "the turn carried no standing brief"

    # The working directory is the turn's rather than the caller's: the CLI
    # reads it into the turn, and a grilling is about the plan in the dispatch
    # and not about whichever repository the human started the session from.
    for call in (*codex, *claude):
        assert Path(call["cwd"]).resolve() == session.directory.resolve(), call["cwd"]
    assert "--output-schema" not in codex[0]["argv"], codex[0]["argv"]
    carried = codex[0]["argv"]
    for closure in (
        "features.shell_tool=false",
        "features.unified_exec=false",
        'sandbox_mode="read-only"',
        'approval_policy="never"',
        "notify=[]",
    ):
        assert closure in carried, f"{closure} is absent from {carried}"
    assert "--skip-git-repo-check" in carried, carried


def test_the_argv_the_driver_builds_is_the_argv_the_shims_accept(tmp_path: Path) -> None:
    """
    Given the arguments each driver composes for a turn
    When a shim is run with exactly them
    Then it finds no violation -- which is what makes a clean record elsewhere a
         statement about the driver rather than about the shim being lenient.

    This is the one place the contract's two statements are put side by side.
    Everywhere else they are kept apart on purpose.
    """
    cold = codex_argv(SEAT, BRIEF, PROMPT, None)
    resumed = codex_argv(SEAT, BRIEF, PROMPT, "thread-9")
    expert = claude_argv("claude-opus-5", "xhigh", BRIEF, PROMPT, None)

    assert run_shim("codex", cold[1:], tmp_path)["violations"] == []
    resumed_call = run_shim("codex", resumed[1:], tmp_path)
    assert resumed_call["violations"] == []
    assert resumed_call["resume"] == "thread-9", resumed_call
    assert run_shim("claude", expert[1:], tmp_path)["violations"] == []


def test_a_departure_from_the_contract_is_named_rather_than_passed_over(
    tmp_path: Path,
) -> None:
    """
    Given a Codex invocation that asks for a strict output schema, drops the
         repository check and the sandbox closures, and leaves standard input
         open
    When the shim records it
    Then every departure is named in the record, and the scenario is what fails
         on it -- a shim that exited non-zero instead would look to the backend
         like a seat that could not be reached, which walks a different ladder
         and proves the wrong thing.
    """
    broken = [
        "exec",
        "--json",
        "--model",
        "gpt-5.6-luna",
        "--output-schema",
        "/tmp/schema.json",  # noqa: S108 -- a path the shim never opens
        "-c",
        f"developer_instructions={json.dumps(BRIEF)}",
        PROMPT,
    ]
    call = run_shim("codex", broken, tmp_path, closed=False)
    said = " | ".join(call["violations"])

    assert "--output-schema is present" in said, said
    assert "--skip-git-repo-check is absent" in said, said
    assert "features.shell_tool=false is absent" in said, said
    assert 'sandbox_mode="read-only" is absent' in said, said
    assert "--ignore-user-config is absent" in said, said
    assert "project_doc_max_bytes=0 is absent" in said, said
    assert "skills.max_context_tokens=1 is absent" in said, said
    for feature in ("hooks", "apps", "plugins", "multi_agent"):
        assert f"--disable {feature} is absent" in said, said
    assert "standard input is not closed" in said, said
    assert call["stdin_devnull"] is False, call


def test_an_expert_turn_that_forgot_its_effort_or_its_lean_seat_is_named_too(
    tmp_path: Path,
) -> None:
    """
    Given an expert invocation with no effort on it, whose brief is appended to
          the CLI's own harness rather than replacing it, and which grants the
          turn the tools, the settings files and the MCP servers of whatever
          machine it runs on
    When the shim records it
    Then every departure is named. The effort is passed on every turn rather
         than only the first, because a resumed chain inherits none of it and
         would think at whatever it defaults to while the log says otherwise;
         and a seat seeded with anything beyond its brief makes the dispatch
         record a partial account of what the turn read.
    """
    call = run_shim(
        "claude",
        [
            "-p",
            "--output-format",
            "json",
            "--model",
            "claude-opus-5",
            "--append-system-prompt",
            BRIEF,
            PROMPT,
        ],
        tmp_path,
    )
    said = " | ".join(call["violations"])

    assert "--effort is absent" in said, said
    assert "--system-prompt is absent" in said, said
    assert "--append-system-prompt is present" in said, said
    assert "--tools is not passed as ''" in said, said
    assert "--setting-sources is not passed as ''" in said, said
    assert "--strict-mcp-config is absent" in said, said
