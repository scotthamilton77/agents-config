"""Both tiers taking turns, offline.

Nothing here reaches a network or a model. The fast tier's transport is
exercised against a scripted HTTP server standing in a local transport, and the
heavy tier's against a scripted CLI -- and where the real process runner is
under test it runs this interpreter printing a canned line, so the runner's own
failure paths are real rather than described.

Every attribution claim is read back out of the log file's bytes rather than out
of the driver that wrote it. What the log says is what a restarted process, the
page and the capture step will see; what the driver remembers is gone the moment
the turn is.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import (
    TIMEOUT,
    ScriptedCli,
    ScriptedFast,
    driven,
    event,
    handoff_doc,
    post,
    replies,
    write_handoff,
)

from grillui.dispatch import record_dispatch
from grillui.drivers import (
    RESUME_FILE,
    FastDriver,
    HeavyDriver,
    OpenRouterTransport,
    ReplyRefusedError,
    claude_argv,
    read_cli_reply,
    read_completion,
    request_body,
    run_claude_cli,
)
from grillui.escalation import CONDITION_COMMITMENT, CONDITION_IRREDUCIBLE, CONDITION_MULTIPLE
from grillui.lane import AgentUnreachableError
from grillui.log import LOG_FILE, SessionLog
from grillui.schemas import (
    EFFORT_KEY,
    FAST_TIER,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MODEL_KEY,
    RECOMMENDATION_KEY,
    TIER_KEY,
    TRANSFER_FLAG,
    EventSubmission,
    RejectedReceipt,
)
from grillui.session import open_session
from grillui.tiers import API_KEY_ENV, TierConfig

SOURCE = Path(__file__).resolve().parents[2] / "src" / "grillui"
TARGET = "d1"
REPLY = "The log is the recovery source. Compaction is the next question."


# A third decision, so the board has two decisions depending on `d1` and three
# in total: the dependent count and the weighed-at-once count are both
# properties of the board, and a two-node board cannot exercise either.
THIRD_DECISION = {
    "id": "d3",
    "short": "Retention",
    "title": "How long is a session kept?",
    "prereqs": ["d1"],
    "body": "Say how long, or say forever.",
    "options": [{"id": "a", "text": "Thirty days"}, {"id": "b", "text": "Forever"}],
}


def briefed(session_dir: Path) -> SessionLog:
    """A session seeded from the shared handoff, with `d2` and `d3` both
    depending on `d1`."""
    document = handoff_doc()
    document["plan"]["decisions"].append(THIRD_DECISION)
    write_handoff(session_dir, document)
    return open_session(session_dir)


def human_turn(log: SessionLog, text: str, channel: str = "map", **extra: Any) -> None:
    """One human turn straight into the log, so a driver can be run on its own
    without the lane scheduling it."""
    payload: dict[str, Any] = {"target": TARGET, "answer": {"text": text}, **extra}
    receipt = log.submit(
        [
            EventSubmission(
                kind="answer" if channel == "map" else "thread-turn",
                actor="human",
                channel=channel,
                idempotency_key=f"human-{len(log.entries())}",
                payload=payload if channel == "map" else {"turns": [{"text": text}]},
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted"


def take_fast_turn(log: SessionLog, transport: ScriptedFast, **config: str) -> None:
    driver = FastDriver(TierConfig(**config), transport)
    driver.run(log, record_dispatch(log))


def take_heavy_turn(log: SessionLog, cli: ScriptedCli, **config: str) -> HeavyDriver:
    driver = HeavyDriver(TierConfig(**config), cli)
    driver.run(log, record_dispatch(log))
    return driver


# --- what a turn is, and what the log says about it ---------------------------


def test_a_fast_turn_lands_in_the_log_attributed_to_its_tier_and_model(
    session_dir: Path,
) -> None:
    """
    Given a session with a human turn waiting
    When the fast tier takes it
    Then the reply is in the log attributed to the fast tier and the configured
         model id, read from the log's own bytes.
    """
    log = briefed(session_dir)
    human_turn(log, "The log, because recovery rests on it.")

    take_fast_turn(log, ScriptedFast(), fast_model="vendor/fast-2")

    assert replies(log) == [
        {"text": REPLY, TIER_KEY: FAST_TIER, MODEL_KEY: "vendor/fast-2"},
    ]


def test_changing_the_fast_tier_id_changes_the_model_the_log_attributes(
    session_dir: Path,
) -> None:
    """
    Given two sessions configured with different fast-tier ids
    When each takes a turn
    Then each log attributes its turn to its own configured model, and each
         request was made with it.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    transport = ScriptedFast()

    take_fast_turn(log, transport, fast_model="vendor/one")
    take_fast_turn(log, transport, fast_model="vendor/two")

    assert [reply[MODEL_KEY] for reply in replies(log)] == ["vendor/one", "vendor/two"]
    assert [call["model"] for call in transport.calls] == ["vendor/one", "vendor/two"]


def test_a_heavy_turn_is_attributed_and_says_whether_it_followed_a_transfer(
    session_dir: Path,
) -> None:
    """
    Given a human turn carrying the transfer the human activated
    When the heavy tier takes it
    Then the log attributes the turn to the heavy tier, to the configured Claude
         model, and records that it followed a transfer.
    """
    log = briefed(session_dir)
    human_turn(log, "Take this one to the expert.", **{TRANSFER_FLAG: True})

    take_heavy_turn(log, ScriptedCli(), heavy_model="claude-configured", heavy_effort="max")

    assert replies(log) == [
        {
            "text": REPLY,
            TIER_KEY: HEAVY_TIER,
            MODEL_KEY: "claude-configured",
            EFFORT_KEY: "max",
            FOLLOWED_TRANSFER_KEY: True,
        }
    ]


def test_a_heavy_turn_nobody_asked_for_does_not_claim_a_transfer(session_dir: Path) -> None:
    """
    Given a human turn carrying no transfer
    When the heavy tier takes it
    Then the log says the turn did not follow one, rather than leaving the
         question open.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    take_heavy_turn(log, ScriptedCli())

    assert replies(log)[0][FOLLOWED_TRANSFER_KEY] is False


def test_a_thread_channels_reply_lands_as_a_thread_turn_from_a_thread_agent(
    session_dir: Path,
) -> None:
    """
    Given a human turn in a side thread
    When the fast tier takes it
    Then the reply is a thread turn on that channel, authored by a thread agent
         rather than by the grill-master.
    """
    log = briefed(session_dir)
    human_turn(log, "Say more about retention.", channel="t-compaction")

    driver = FastDriver(TierConfig(), ScriptedFast())
    driver.run(log, record_dispatch(log, channel="t-compaction"))

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert (written["kind"], written["actor"], written["channel"]) == (
        "thread-turn",
        "thread-agent",
        "t-compaction",
    )


# --- the escalation recommendation on a real turn ------------------------------


@pytest.mark.parametrize(
    ("said", "condition"),
    [
        ("Stop asking and just decide it.", CONDITION_COMMITMENT),
        ("You keep rewording it -- that is not the question.", CONDITION_IRREDUCIBLE),
        ("Compaction and Retention both move if d1 moves.", CONDITION_MULTIPLE),
    ],
)
def test_a_fast_reply_names_the_condition_its_turn_met(
    session_dir: Path, said: str, condition: str
) -> None:
    """
    Given a transcript satisfying one of the escalation conditions
    When the fast tier answers it
    Then the reply in the log carries recommendation metadata naming that
         condition.
    """
    log = briefed(session_dir)
    human_turn(log, said)

    take_fast_turn(log, ScriptedFast())

    assert replies(log)[0][RECOMMENDATION_KEY]["condition"] == condition


def test_a_fast_reply_to_an_ordinary_turn_carries_no_recommendation(session_dir: Path) -> None:
    """
    Given a transcript satisfying none of the conditions
    When the fast tier answers it
    Then the reply carries no recommendation at all.
    """
    log = briefed(session_dir)
    human_turn(log, "It has to survive a crash mid-write.")

    take_fast_turn(log, ScriptedFast())

    assert RECOMMENDATION_KEY not in replies(log)[0]


def test_a_recommendation_does_not_move_the_turn_to_the_heavy_tier(session_dir: Path) -> None:
    """
    Given a turn that met a condition and was recommended for handoff
    When the next turn on that channel is taken
    Then both turns are still the fast tier's: escalation is the human's
         gesture, and no transcript takes it on their behalf.
    """
    log = briefed(session_dir)
    human_turn(log, "Stop asking and just decide it.")
    take_fast_turn(log, ScriptedFast())
    human_turn(log, "Then what about compaction?")

    take_fast_turn(log, ScriptedFast())

    written = replies(log)
    assert [reply[TIER_KEY] for reply in written] == [FAST_TIER, FAST_TIER]
    assert all(reply.get(FOLLOWED_TRANSFER_KEY) is None for reply in written)


# --- the briefing and the board reach the model --------------------------------


def test_the_turn_the_model_is_given_carries_the_briefing_and_the_board(
    session_dir: Path,
) -> None:
    """
    Given a briefed session
    When the fast tier takes a turn
    Then the prompt the model was given carries the session's stop condition and
         every settled decision's id, and the system prompt is the shipped one.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    transport = ScriptedFast()

    take_fast_turn(log, transport)

    prompt = transport.calls[0]["prompt"]
    assert "every decision is settled or parked with a named blocker" in prompt
    assert TARGET in prompt
    assert "stop short of deciding" in transport.calls[0]["system"]


def test_a_fast_turn_asked_for_a_fact_its_context_lacks_asserts_none(session_dir: Path) -> None:
    """
    Given a board that says nothing about the retention window
    When the human asks what it is and the tier answers under its rules
    Then the fact is nowhere in what the model was given, and the reply names
         the gap instead of supplying a number.
    """
    log = briefed(session_dir)
    human_turn(log, "What is the retention window in the current system?")
    transport = ScriptedFast(
        reply="The context I was given does not say what the retention window is."
    )

    take_fast_turn(log, transport)

    prompt = transport.calls[0]["prompt"]
    assert "retention window" not in prompt.replace(
        "What is the retention window in the current system?", ""
    )
    reply = replies(log)[0]["text"]
    assert "does not say" in reply
    assert not any(unit in reply for unit in ("days", "weeks", "months"))


def test_a_scripted_turn_under_the_shipped_prompt_replies_within_three_sentences(
    session_dir: Path,
) -> None:
    """
    Given the concision constraint in the system prompt the model was given
    When a turn is taken and the model answers under it
    Then what lands in the log is at most three sentences.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    transport = ScriptedFast()

    take_fast_turn(log, transport)

    assert "three sentences" in transport.calls[0]["system"]
    assert len([one for one in replies(log)[0]["text"].split(".") if one.strip()]) <= 3


# --- the heavy tier's chain ----------------------------------------------------


def test_the_first_heavy_turn_opens_a_chain_and_the_second_resumes_it(session_dir: Path) -> None:
    """
    Given a session that has never had a heavy turn
    When two heavy turns are taken
    Then the first opens a chain and the second resumes the identity the first
         came back with.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    cli = ScriptedCli(session_id="chain-7")

    take_heavy_turn(log, cli)
    take_heavy_turn(log, cli)

    assert "--resume" not in cli.calls[0]
    assert cli.calls[1][cli.calls[1].index("--resume") + 1] == "chain-7"


def test_the_resume_identity_survives_a_restart(session_dir: Path) -> None:
    """
    Given a heavy turn taken by one backend process
    When that process is gone and a second one opens the same session directory
    Then the successor's first heavy turn resumes the same chain rather than
         paying for a cold one.
    """
    first = briefed(session_dir)
    human_turn(first, "The log.")
    take_heavy_turn(first, ScriptedCli(session_id="chain-9"))

    successor = open_session(session_dir)
    cli = ScriptedCli()
    take_heavy_turn(successor, cli)

    assert successor.epoch != first.epoch
    assert cli.calls[0][cli.calls[0].index("--resume") + 1] == "chain-9"


def test_two_heavy_turns_never_run_at_the_same_time(session_dir: Path) -> None:
    """
    Given two turns dispatched at once on one session
    When both reach the heavy tier
    Then one waits for the other: the resumed-turn discount lives in a cache one
         process holds, and two talking over each other forfeit it.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    cli = ScriptedCli(hold=0.05)
    driver = HeavyDriver(TierConfig(), cli)
    dispatch = record_dispatch(log)

    turns = [
        threading.Thread(target=driver.run, args=(log, dispatch), daemon=True) for _ in range(2)
    ]
    for turn in turns:
        turn.start()
    for turn in turns:
        turn.join(TIMEOUT)

    assert cli.overlapping is False
    assert len(cli.calls) == 2


def test_a_heavy_turn_is_one_invocation_that_exits(session_dir: Path) -> None:
    """
    Given one human turn
    When the heavy tier takes it
    Then exactly one CLI invocation happened, it asked for structured output,
         and nothing was left running.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    cli = ScriptedCli()

    take_heavy_turn(log, cli)

    assert len(cli.calls) == 1
    assert cli.calls[0][:4] == ["claude", "-p", "--output-format", "json"]
    assert cli._inside == 0


def test_a_torn_resume_file_costs_a_cold_start_and_not_the_turn(session_dir: Path) -> None:
    """
    Given a resume file left half-written by a killed process
    When the next heavy turn is taken
    Then it starts a cold chain and answers, rather than refusing over a cache
         file.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    (session_dir / RESUME_FILE).write_text('{"map": "chain-', encoding="utf-8")
    cli = ScriptedCli()

    take_heavy_turn(log, cli)

    assert "--resume" not in cli.calls[0]
    assert json.loads((session_dir / RESUME_FILE).read_text(encoding="utf-8")) == {"map": "chain-1"}


def test_each_channel_resumes_its_own_chain(session_dir: Path) -> None:
    """
    Given a heavy turn on the map and one in a thread
    When each is taken
    Then the two chains are remembered separately, so a thread never resumes
         into the map's conversation.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    human_turn(log, "And here?", channel="t-compaction")
    driver = HeavyDriver(TierConfig(), ScriptedCli(session_id="map-chain"))
    driver.run(log, record_dispatch(log))
    thread_driver = HeavyDriver(TierConfig(), ScriptedCli(session_id="thread-chain"))

    thread_driver.run(log, record_dispatch(log, channel="t-compaction"))

    assert json.loads((session_dir / RESUME_FILE).read_text(encoding="utf-8")) == {
        "map": "map-chain",
        "t-compaction": "thread-chain",
    }


# --- nothing polls -------------------------------------------------------------


@pytest.mark.parametrize("module", ["drivers.py", "tiers.py", "escalation.py", "lane.py"])
def test_no_shipped_driver_contains_a_polling_loop(module: str) -> None:
    """
    Given each module an agent's turn runs through
    When its source is read
    Then it holds nothing that waits for something to arrive: a turn is one
         invocation that exits.

    Read as code rather than as prose -- a module that explains why it does not
    poll still says the word, and only what it executes decides whether it
    does.
    """
    source = "\n".join(
        line.split("#")[0].lower()
        for line in (SOURCE / module).read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith(("#", '"', "'"))
    )

    assert "while true" not in source
    assert "while not" not in source
    assert "time.sleep" not in source
    assert "asyncio.sleep" not in source
    assert ".poll(" not in source


# --- the transports ------------------------------------------------------------


def test_the_fast_transport_asks_for_a_completion_and_reads_the_reply() -> None:
    """
    Given a hosted model answering one completion request
    When the transport calls it
    Then the standing brief travelled as a system message, the model id as
         asked, and the reply comes back as text.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": REPLY}}]})

    transport = OpenRouterTransport(
        api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert transport(model="vendor/fast", system="be brief", prompt="what now?") == REPLY
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer k"
    assert seen["body"] == request_body("vendor/fast", "be brief", "what now?")


def test_a_fast_transport_with_no_key_is_unreachable_rather_than_silent() -> None:
    """
    Given an environment carrying no key
    When the transport is called
    Then it says the tier could not be reached, which the lane surfaces in
         milliseconds.
    """
    transport = OpenRouterTransport(environ={API_KEY_ENV: ""})

    with pytest.raises(AgentUnreachableError):
        transport(model="vendor/fast", system="s", prompt="p")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="upstream is down"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": {"not": "text"}}}]}),
        httpx.Response(200, text="not json at all"),
    ],
)
def test_every_way_a_completion_can_fail_reads_as_unreachable(response: httpx.Response) -> None:
    """
    Given a server that errors, or answers with something that is not a reply
    When the transport is called
    Then the turn fails as unreachable rather than recording a reply nobody
         composed.
    """
    transport = OpenRouterTransport(
        api_key="k",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: response)),
    )

    with pytest.raises(AgentUnreachableError):
        transport(model="vendor/fast", system="s", prompt="p")


def test_the_transport_opens_its_own_client_when_it_was_given_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a transport configured with nothing but a key
    When it is called against a base that resolves nowhere
    Then it opens a client of its own and the failure is an unreachable tier.
    """
    monkeypatch.setenv(API_KEY_ENV, "k")
    transport = OpenRouterTransport(api_base="http://127.0.0.1:1/v1")

    with pytest.raises(AgentUnreachableError):
        transport(model="vendor/fast", system="s", prompt="p")


def test_the_cli_transport_returns_what_the_process_printed() -> None:
    """
    Given a process that prints a structured turn
    When the CLI transport runs it
    Then what it printed comes back, and the reply and chain identity are read
         out of it.
    """
    printed = json.dumps({"session_id": "chain-3", "result": REPLY})

    output = run_claude_cli([sys.executable, "-c", f"print({printed!r})"])

    assert read_cli_reply(output) == (REPLY, "chain-3")


def test_a_cli_that_fails_or_prints_nonsense_reads_as_unreachable() -> None:
    """
    Given a CLI that is not there, one that exits non-zero, and one that prints
          something that is not a turn
    When each is run
    Then every one of them is an unreachable tier rather than a turn that
         happened.
    """
    with pytest.raises(AgentUnreachableError):
        run_claude_cli(["/nonexistent/claude", "-p"])
    with pytest.raises(AgentUnreachableError):
        run_claude_cli([sys.executable, "-c", "raise SystemExit(3)"])
    with pytest.raises(AgentUnreachableError):
        read_cli_reply("not json")
    with pytest.raises(AgentUnreachableError):
        read_cli_reply(json.dumps({"session_id": "c"}))
    # A non-text result is the heavy tier's malformed completion: refused, never
    # stringified into the log as if the model said it.
    with pytest.raises(AgentUnreachableError):
        read_cli_reply(json.dumps({"result": {"content": "boxed"}, "session_id": "c"}))


def test_a_turn_that_reports_no_chain_identity_is_still_a_turn(session_dir: Path) -> None:
    """
    Given a CLI whose output names no chain
    When the turn is taken
    Then the reply still lands and nothing is remembered to resume into.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    driver = HeavyDriver(TierConfig(), lambda _argv: json.dumps({"result": REPLY}))
    driver.run(log, record_dispatch(log))

    assert replies(log)[0]["text"] == REPLY
    assert not (session_dir / RESUME_FILE).exists()


def test_the_argv_carries_the_model_the_effort_the_prompt_and_the_standing_brief() -> None:
    """
    Given a model id, an effort, a system brief, a prompt and a chain to resume
    When the argv is built
    Then all five are on it, and the prompt is the last argument.
    """
    argv = claude_argv("claude-configured", "xhigh", "be brief", "what now?", "chain-2")

    assert argv[argv.index("--model") + 1] == "claude-configured"
    assert argv[argv.index("--effort") + 1] == "xhigh"
    assert argv[argv.index("--append-system-prompt") + 1] == "be brief"
    assert argv[argv.index("--resume") + 1] == "chain-2"
    assert argv[-1] == "what now?"


def test_a_completion_that_is_not_text_is_refused() -> None:
    """
    Given a completion whose content is not text
    When it is read
    Then it raises rather than being coerced into a reply.
    """
    with pytest.raises(TypeError):
        read_completion({"choices": [{"message": {"content": None}}]})


# --- a reply that says nothing --------------------------------------------------


def test_an_empty_completion_is_a_failed_turn_not_a_silent_one(session_dir: Path) -> None:
    """
    Given a model that answers with whitespace
    When the turn is taken
    Then it fails loudly and nothing is written into the log as a reply.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    with pytest.raises(ReplyRefusedError):
        take_fast_turn(log, ScriptedFast(reply="   "))

    assert replies(log) == []


def test_a_reply_the_appender_refuses_is_not_swallowed(session_dir: Path) -> None:
    """
    Given an appender that refuses the reply
    When a turn tries to record one
    Then the refusal surfaces, so the human gets the lane's error rather than a
         turn that appears to have happened.
    """

    class Refusing(SessionLog):
        def submit(self, batch: Any, epoch: str) -> list[Any]:  # noqa: ARG002
            return [
                RejectedReceipt(
                    idempotency_key="k", epoch=epoch, reason="unknown node id", detail="no"
                )
            ]

    log = Refusing(session_dir / "refusing")
    dispatch = record_dispatch(log)

    with pytest.raises(ReplyRefusedError, match="unknown node id"):
        FastDriver(TierConfig(), ScriptedFast()).run(log, dispatch)


# --- through the lane ------------------------------------------------------------


def test_the_lane_names_the_tier_and_the_turn_answers_the_human(session_dir: Path) -> None:
    """
    Given a backend whose tier is the fast driver
    When a human answers a decision through the write endpoint
    Then the lane names the fast tier while composing, and the reply lands in
         the log attributed to it.
    """
    log = briefed(session_dir)
    client = driven(log, FastDriver(TierConfig(), ScriptedFast()))

    receipts = post(
        client,
        log.epoch,
        event("answer", actor="human", key="a1", target=TARGET, answer={"option": "a"}),
    )

    assert receipts[0]["status"] == "accepted"
    deadline = time.monotonic() + TIMEOUT
    while not replies(log) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert replies(log)[0][TIER_KEY] == FAST_TIER
    composing = [
        entry.payload
        for entry in log.entries()
        if entry.kind == "status" and entry.payload.get("phase") == "composing"
    ]
    assert composing[0][TIER_KEY] == FAST_TIER


def test_a_tier_that_cannot_be_reached_raises_out_of_the_turn(session_dir: Path) -> None:
    """
    Given a fast tier with no key configured
    When a human turn is taken
    Then the turn raises, which is what the lane turns into an error phase in
         milliseconds rather than into silence.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    driver = FastDriver(TierConfig(), OpenRouterTransport(environ={}))

    with pytest.raises(AgentUnreachableError):
        driver.run(log, record_dispatch(log))


def test_the_dependency_on_a_real_process_runner_is_the_one_under_test() -> None:
    """
    Given the runner the heavy tier ships with
    When it is handed an argv that exits cleanly
    Then it returns that process's own output, so nothing in the heavy path is
         a stub the tests wrote.
    """
    assert run_claude_cli([sys.executable, "-c", "print('ok')"]).strip() == "ok"
