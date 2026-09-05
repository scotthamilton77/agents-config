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

import ast
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import (
    RACE_WINDOW,
    TIMEOUT,
    InterleavingLog,
    ScriptedCli,
    ScriptedFast,
    attributions,
    document,
    driven,
    event,
    handoff_doc,
    post,
    replies,
    write_handoff,
)

from grillui import drivers
from grillui.dispatch import GRILL_MASTER, record_dispatch
from grillui.drivers import (
    RESUME_FILE,
    FastDriver,
    HeavyDriver,
    Measurement,
    OpenRouterTransport,
    ReplyRefusedError,
    claude_argv,
    declared_updates,
    read_cli_reply,
    read_completion,
    record_reply,
    request_body,
    run_claude_cli,
    write_resume,
)
from grillui.escalation import CONDITION_COMMITMENT, CONDITION_IRREDUCIBLE, CONDITION_MULTIPLE
from grillui.lane import AgentUnreachableError, DocumentRefusedError
from grillui.log import LOG_FILE, SessionLog
from grillui.projector import fold
from grillui.schemas import (
    CONTEXT_BYTES_KEY,
    CONTEXT_LIMIT_KEY,
    EFFORT_KEY,
    FAST_TIER,
    FOLLOWED_TRANSFER_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    PROMPT_TOKENS_KEY,
    PROPOSED_ANSWER_KEY,
    RECOMMENDATION_KEY,
    STATUS_PHASE_ACCEPTED,
    TIER_KEY,
    TRANSFER_FLAG,
    EventSubmission,
    RejectedReceipt,
)
from grillui.session import open_session
from grillui.tiers import (
    API_KEY_ENV,
    BYTES_PER_TOKEN,
    CONTEXT_LIMITS,
    DEFAULT_FAST_MODEL,
    DEFAULT_HEAVY_MODEL,
    FAST_CONTEXT_LIMIT_ENV,
    FAST_MODEL_ENV,
    HEAVY_CONTEXT_LIMIT_ENV,
    HEAVY_MODEL_ENV,
    TierConfig,
    system_prompt,
)

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

    assert attributions(log) == [
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

    assert attributions(log) == [
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
         every settled decision's id, and the system prompt is the shipped brief
         for the role and tier this turn ran as -- not merely something that
         resembles one, since a driver that composed the wrong pair's brief
         would still be handing the model a shipped string.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    transport = ScriptedFast()

    take_fast_turn(log, transport)

    prompt = transport.calls[0]["prompt"]
    assert "every decision is settled or parked with a named blocker" in prompt
    assert TARGET in prompt
    assert transport.calls[0]["system"] == system_prompt(FAST_TIER, GRILL_MASTER)


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
        reply=document(text="The context I was given does not say what the retention window is.")
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


def test_the_expert_seat_takes_its_turn_in_the_session_directory(session_dir: Path) -> None:
    """
    Given a session whose expert seat takes a cold turn and then a resumed one
    When each is composed
    Then both run in the session's own directory rather than wherever the
         backend was launched: the CLI reads its working directory into the
         turn, so a seat left in the human's repository reads instruction files
         and a tree that are in no dispatch, and the record of what the turn was
         given stops being the whole of it.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    cli = ScriptedCli(session_id="chain-7")

    take_heavy_turn(log, cli)
    take_heavy_turn(log, cli)

    assert "--resume" not in cli.calls[0]
    assert "--resume" in cli.calls[1]
    assert cli.directories == [session_dir, session_dir]


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


def test_two_channels_writing_their_chains_at_once_keep_both(
    session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given two channels remembering their chains at the same moment
    When both writes run
    Then both records survive, and neither writer was inside the file while the
         other still was.

    Every channel keeps its own key in one shared file, so reading it and
    rewriting it has to be one step. Interleaved, both writers read the same map
    and the later rename drops the other channel's chain -- that channel then
    pays for a cold start nothing recorded and nobody asked for.

    The barrier is the proof, and it is meant to break: it releases only if a
    second writer got inside the file while the first was still there, which is
    exactly the interleaving that loses a chain.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    inside = threading.Barrier(2)
    overlapped = threading.Event()
    read_whole = drivers._chains

    def watched(path: Path) -> dict[str, Any]:
        chains = read_whole(path)
        try:
            inside.wait(0.25)
            overlapped.set()
        except threading.BrokenBarrierError:
            pass
        return chains

    monkeypatch.setattr(drivers, "_chains", watched)
    writers = [
        threading.Thread(target=write_resume, args=(session_dir, channel, f"{channel}-chain"))
        for channel in ("map", "t-compaction")
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(TIMEOUT)

    assert not overlapped.is_set()
    assert json.loads((session_dir / RESUME_FILE).read_text(encoding="utf-8")) == {
        "map": "map-chain",
        "t-compaction": "t-compaction-chain",
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
         asked, and the reply comes back as text beside the provider's own
         prompt count.
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": REPLY}}],
                "usage": {"prompt_tokens": 1234, "completion_tokens": 7},
            },
        )

    transport = OpenRouterTransport(
        api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert transport(model="vendor/fast", system="be brief", prompt="what now?") == (REPLY, 1234)
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


def test_the_cli_transport_returns_what_the_process_printed(tmp_path: Path) -> None:
    """
    Given a process that prints a structured turn
    When the CLI transport runs it
    Then what it printed comes back, and the reply, chain identity and prompt
         count are read out of it.
    """
    printed = json.dumps({"session_id": "chain-3", "result": REPLY, "usage": {"input_tokens": 40}})

    output = run_claude_cli([sys.executable, "-c", f"print({printed!r})"], tmp_path)

    assert read_cli_reply(output) == (REPLY, "chain-3", 40)


def test_a_cli_that_fails_or_prints_nonsense_reads_as_unreachable(tmp_path: Path) -> None:
    """
    Given a CLI that is not there, one that exits non-zero, and one that prints
          something that is not a turn
    When each is run
    Then every one of them is an unreachable tier rather than a turn that
         happened.
    """
    with pytest.raises(AgentUnreachableError):
        run_claude_cli(["/nonexistent/claude", "-p"], tmp_path)
    with pytest.raises(AgentUnreachableError):
        run_claude_cli([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
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

    driver = HeavyDriver(TierConfig(), lambda _argv, _directory: json.dumps({"result": document()}))
    driver.run(log, record_dispatch(log))

    assert replies(log)[0]["text"] == REPLY
    assert not (session_dir / RESUME_FILE).exists()


def test_the_expert_seat_is_briefed_with_its_rungs_prompt_on_every_turn(
    session_dir: Path,
) -> None:
    """
    Given a session whose expert seat takes a cold turn and then a resumed one
    When each is composed
    Then both carry this rung's standing brief as the whole system prompt: a
         resumed chain inherits nothing, so a turn briefed only on the cold one
         answers as whatever the transport last recorded.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    cli = ScriptedCli(session_id="chain-7")

    take_heavy_turn(log, cli)
    take_heavy_turn(log, cli)

    assert "--resume" not in cli.calls[0]
    assert "--resume" in cli.calls[1]
    for call in cli.calls:
        assert call[call.index("--system-prompt") + 1] == system_prompt(HEAVY_TIER, GRILL_MASTER)


@pytest.mark.parametrize("constant", ["CODEX_LEAN_SEAT", "CLAUDE_LEAN_SEAT"])
def test_each_transport_states_the_seat_ruling_in_one_sentence(constant: str) -> None:
    """
    Given a transport's seed-and-tool constant
    When the source is read
    Then the statement after it is a docstring of one sentence stating the
         ruling on what a seat is seeded with and may use.
    """
    body = ast.parse(Path(drivers.__file__).read_text(encoding="utf-8")).body
    after = [
        body[index + 1]
        for index, node in enumerate(body[:-1])
        if isinstance(node, ast.Assign)
        and any(getattr(one, "id", None) == constant for one in node.targets)
    ]

    assert len(after) == 1, f"{constant} is not assigned exactly once at module level"
    said = after[0]
    assert isinstance(said, ast.Expr) and isinstance(said.value, ast.Constant), (
        f"{constant} carries no docstring"
    )
    text = said.value.value
    assert isinstance(text, str), f"{constant} carries no docstring"
    assert text.endswith(".") and text.count(".") == 1, f"{constant} says more than one sentence"
    assert "minimal seed and no tools" in text, text


def test_the_claude_seat_is_seeded_with_the_brief_and_nothing_else() -> None:
    """
    Given a model id, an effort, a system brief, a prompt, and a cold turn and a
          resumed one
    When each argv is built
    Then it is exactly the lean invocation: the brief replaces the CLI's own
         system prompt rather than riding on top of it, no tool, settings file
         or MCP server reaches the turn, the effort is stated on both, and the
         prompt is the last argument.
    """
    seeded = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        "claude-configured",
        "--effort",
        "xhigh",
        "--system-prompt",
        "be brief",
        "--tools",
        "",
        "--setting-sources",
        "",
        "--strict-mcp-config",
    ]

    cold = claude_argv("claude-configured", "xhigh", "be brief", "what now?", None)
    resumed = claude_argv("claude-configured", "xhigh", "be brief", "what now?", "chain-2")

    assert cold == [*seeded, "what now?"]
    assert resumed == [*seeded, "--resume", "chain-2", "what now?"]
    assert "--append-system-prompt" not in cold
    assert "--append-system-prompt" not in resumed


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

    Whitespace never reaches the shape at all, so it is refused as a document
    and never recorded as something the agent said.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    with pytest.raises(DocumentRefusedError):
        take_fast_turn(log, ScriptedFast(reply="   "))

    assert replies(log) == []


def test_a_document_that_carries_nothing_records_nothing_and_fails_nothing(
    session_dir: Path,
) -> None:
    """
    Given a well-formed document with no notice, no update and no ruling
    When the turn is taken
    Then no reply is appended and no error is raised.

    §8.10 permits every field to be empty, so this is a valid turn and must not
    be raised as a transport failure -- doing so skips the ladder that owes a
    turn ruling on nothing a hand-up and then a notice. Nothing is appended
    because every entry shape here holds content; the turn stays on the record
    in its own dispatch file and in the lane's pair.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    take_fast_turn(log, ScriptedFast(reply=document(text="")))

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


def test_the_dependency_on_a_real_process_runner_is_the_one_under_test(tmp_path: Path) -> None:
    """
    Given the runner the heavy tier ships with
    When it is handed an argv that exits cleanly
    Then it returns that process's own output, so nothing in the heavy path is
         a stub the tests wrote.
    """
    assert run_claude_cli([sys.executable, "-c", "print('ok')"], tmp_path).strip() == "ok"


# --- what a turn cost, and the tier that is filling its window up ---------------


def warnings_in(log: SessionLog) -> list[str]:
    """Every context warning the backend appended, read out of the log's bytes."""
    lines = (log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return [
        entry["payload"]["text"]
        for entry in entries
        if entry["kind"] == "informational" and entry["actor"] == "backend"
    ]


def queued_warnings(log: SessionLog) -> list[Any]:
    """The context warnings the board itself is carrying.

    Picked out by their authoring entry, because a grill-master's own prose is
    an informational too and queues on the same lane -- which is the point: the
    warning reaches the human by the surface the board already has for a message
    with no decision to sit on.
    """
    entries = log.entries()
    backend = {
        entry.seq for entry in entries if entry.kind == "informational" and entry.actor == "backend"
    }
    return [one for one in fold(log.epoch, entries).pending if one.authored_at in backend]


def test_a_fast_turn_records_its_size_and_the_count_the_provider_returned(
    session_dir: Path,
) -> None:
    """
    Given a hosted model that counted the prompt it was sent
    When the fast tier takes a turn
    Then the reply entry carries the request's bytes, the provider's own count
         and the window that count is read against.
    """
    log = briefed(session_dir)
    human_turn(log, "The log, because recovery rests on it.")

    take_fast_turn(log, ScriptedFast(prompt_tokens=1234), fast_model=DEFAULT_FAST_MODEL)

    reply = replies(log)[0]
    assert reply[PROMPT_TOKENS_KEY] == 1234
    assert reply[CONTEXT_LIMIT_KEY] == CONTEXT_LIMITS[DEFAULT_FAST_MODEL]
    assert reply[CONTEXT_BYTES_KEY] > 0


def test_a_heavy_turn_records_the_whole_chain_the_cli_counted_not_this_turns_delta(
    session_dir: Path,
) -> None:
    """
    Given a CLI turn whose usage separates fresh input from what the cache
          supplied
    When the heavy tier takes it
    Then the reply entry counts all three input-side figures, because what fills
         a resumed chain's window is the conversation and not this turn's delta.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    usage = {
        "input_tokens": 300,
        "cache_creation_input_tokens": 700,
        "cache_read_input_tokens": 180_000,
        "output_tokens": 42,
    }

    take_heavy_turn(log, ScriptedCli(usage=usage), heavy_model=DEFAULT_HEAVY_MODEL)

    reply = replies(log)[0]
    assert reply[PROMPT_TOKENS_KEY] == 181_000
    assert reply[CONTEXT_LIMIT_KEY] == CONTEXT_LIMITS[DEFAULT_HEAVY_MODEL]
    assert reply[CONTEXT_BYTES_KEY] > 0


def test_a_turn_whose_provider_counted_nothing_is_recorded_in_bytes_alone(
    session_dir: Path,
) -> None:
    """
    Given providers that returned no usage at all
    When each tier takes a turn
    Then the bytes are recorded and no count is, so a reader can tell an
         estimate from a measurement by the key's absence.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    take_fast_turn(log, ScriptedFast())
    take_heavy_turn(log, ScriptedCli())

    for reply in replies(log):
        assert reply[CONTEXT_BYTES_KEY] > 0
        assert PROMPT_TOKENS_KEY not in reply


def test_an_uncounted_turn_is_estimated_from_its_bytes_and_says_so() -> None:
    """
    Given a turn nobody counted
    When its size is measured
    Then the bytes stand in at the stated ratio, and the measurement knows it
         was not counted.
    """
    estimated = Measurement("fast", context_bytes=4_000, prompt_tokens=None, limit=None)

    assert estimated.tokens == 4_000 // BYTES_PER_TOKEN
    assert not estimated.counted
    counted = Measurement("fast", context_bytes=4_000, prompt_tokens=99, limit=None)
    assert (counted.tokens, counted.counted) == (99, True)


def test_a_tier_at_three_quarters_of_its_window_warns_on_the_board_and_on_stdout(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a tier whose window the environment states as small enough to reach
    When a turn measures at three quarters of it
    Then the backend appends a notice the board carries in its pending queue --
         the same lane the page renders informationals in -- and prints one line
         naming the tier, the model, what was measured and the ceiling.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    config = TierConfig.from_env({FAST_MODEL_ENV: "vendor/unknown", FAST_CONTEXT_LIMIT_ENV: "1000"})

    FastDriver(config, ScriptedFast(prompt_tokens=750)).run(log, record_dispatch(log))

    said = warnings_in(log)
    assert len(said) == 1
    assert "750" in said[0]
    assert "1,000" in said[0]
    assert "vendor/unknown" in said[0]
    assert "'fast'" in said[0]
    # The board is where the human meets it: a notice with no decision to sit on
    # is a pending item, which is what the page's notification lane reads.
    queued = queued_warnings(log)
    assert [one.kind for one in queued] == ["informational"]
    printed = capsys.readouterr().out
    assert printed.startswith("grillui: ")
    assert said[0] in printed


def test_a_tier_just_under_the_threshold_says_nothing(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given the same small window
    When a turn measures at 74% of it
    Then nothing is appended and nothing is printed, because a warning that
         fires below its own threshold is one nobody reads.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    config = TierConfig.from_env({FAST_MODEL_ENV: "vendor/unknown", FAST_CONTEXT_LIMIT_ENV: "1000"})

    FastDriver(config, ScriptedFast(prompt_tokens=740)).run(log, record_dispatch(log))

    assert warnings_in(log) == []
    assert queued_warnings(log) == []
    assert capsys.readouterr().out == ""


def test_a_model_nothing_knows_the_window_of_warns_about_nothing(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a model absent from the table and no override for it
    When a turn measures at a size that would trip any plausible ceiling
    Then no warning is raised and the reply records that no limit is known,
         rather than recording a measurement that was found roomy.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    take_fast_turn(log, ScriptedFast(prompt_tokens=50_000_000), fast_model="vendor/unknown")

    assert warnings_in(log) == []
    assert capsys.readouterr().out == ""
    assert replies(log)[0][CONTEXT_LIMIT_KEY] is None


def test_the_shipped_limits_leave_an_ordinary_session_quiet(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given the models this package ships with and their table limits
    When both tiers take a turn on a session of the size these fixtures build
    Then neither warns, because the instrument is calibrated to fire on a
         session that is actually filling a window rather than on every one.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")

    take_fast_turn(log, ScriptedFast())
    take_heavy_turn(log, ScriptedCli())

    assert warnings_in(log) == []
    assert capsys.readouterr().out == ""
    assert [reply[CONTEXT_LIMIT_KEY] for reply in replies(log)] == [
        CONTEXT_LIMITS[DEFAULT_FAST_MODEL],
        CONTEXT_LIMITS[DEFAULT_HEAVY_MODEL],
    ]


def pressed_driver(tier: str) -> Any:
    """Either tier, configured so one scripted turn measures at its threshold."""
    if tier == FAST_TIER:
        return FastDriver(
            TierConfig.from_env({FAST_MODEL_ENV: "vendor/unknown", FAST_CONTEXT_LIMIT_ENV: "1000"}),
            ScriptedFast(prompt_tokens=750),
        )
    return HeavyDriver(
        TierConfig.from_env({HEAVY_MODEL_ENV: "vendor/unknown", HEAVY_CONTEXT_LIMIT_ENV: "1000"}),
        ScriptedCli(usage={"input_tokens": 750}),
    )


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_a_write_racing_the_reply_cannot_wedge_between_it_and_its_warning(
    session_dir: Path, capsys: pytest.CaptureFixture[str], tier: str
) -> None:
    """
    Given either tier taking a turn that measures over its window
    When another write arrives in the same instant the reply is appended
    Then the warning is still the entry directly under the reply it measured.

    The reply and the warning are two appends, and anything landing between them
    leaves the human reading a measurement filed against somebody else's turn.
    Holding the append lock across both is what closes that, and this asserts it
    rather than a lucky ordering: the racing write is let in at the one moment
    that can go wrong, from a thread of its own so it contends for the lock
    instead of re-entering it, and has to come out after the warning anyway.
    """
    # Seeded through the ordinary path, then reopened as a log that can let a
    # racer in: the directory is resumable by then, so this reads the same board
    # from the same bytes.
    briefed(session_dir)
    log = InterleavingLog(session_dir)
    human_turn(log, "The log.")
    racing: list[threading.Thread] = []

    def interleave() -> None:
        runner = threading.Thread(
            target=lambda: log.emit_status(STATUS_PHASE_ACCEPTED, "a racing write", MAP_CHANNEL),
            name="raced-write",
        )
        racing.append(runner)
        runner.start()
        # Long enough that a driver holding no lock really would let the write
        # through, so the unguarded version fails on ordering, not on timing.
        runner.join(RACE_WINDOW)

    log.hook = interleave
    pressed_driver(tier).run(log, record_dispatch(log))
    for thread in racing:
        thread.join(TIMEOUT)
        assert not thread.is_alive(), "a raced write outlived its timeout"

    entries = log.entries()
    spoken = [entry for entry in entries if entry.actor == "grill-master"]
    warned = [
        entry for entry in entries if entry.kind == "informational" and entry.actor == "backend"
    ]
    assert len(warned) == 1
    assert warned[0].seq == spoken[-1].seq + 1
    assert warned[0].payload["text"] in capsys.readouterr().out


def test_a_refused_reply_warns_about_nothing(session_dir: Path) -> None:
    """
    Given a turn that measures over its window and proposes a well-shaped
          update against a decision the board does not carry
    When it is run
    Then it raises and no warning is appended, because a turn nobody could
         record is not a turn whose size is worth telling the human about.

    The fault is one only the appender can see, so the reply is measured and
    reaches the append before it is refused -- which is the ordering this is
    about. A fault in the shape is refused a rung earlier, at the document gate,
    where the seat still has its retry.
    """
    log = briefed(session_dir)
    human_turn(log, "The log.")
    config = TierConfig.from_env({FAST_MODEL_ENV: "vendor/unknown", FAST_CONTEXT_LIMIT_ENV: "1000"})

    refused = document(
        text="Proposing this.",
        updates=[{"kind": "invalidate", "target": "d99", "why": "nothing on the board is d99"}],
    )
    with pytest.raises(ReplyRefusedError):
        FastDriver(config, ScriptedFast(reply=refused, prompt_tokens=750)).run(
            log, record_dispatch(log)
        )

    assert warnings_in(log) == []


# --- an offer the board cannot take, arriving as an offer and not as bytes -----

# The reply a fast agent actually sent on the session-scoped thread: one line,
# fence and object together, and no prose beside the offer. Kept verbatim
# because every part of it is what went wrong -- the layout the fence reader
# missed, and the decision a thread anchoring nothing has no business naming.
LIVE_ONE_LINE_OFFER = (
    '```json { "proposed_answer": { "decision": "d1", "option": "b", "text": '
    '"Close unactioned; the downstream questions fall away.", "because": "The human '
    "settled decision d1 on option b, rendering the downstream decisions d2 through d9 "
    'unnecessary." } } ```'
)

DECLARING = {
    "text": "Retention follows from the log, then.",
    "proposed_answer": {"decision": "d1", "option": "b", "text": "Forever", "because": "said so"},
}


def open_thread(log: SessionLog, thread: str, decision: str | None) -> None:
    """One thread, anchored to a decision or to none -- which is what the thread
    about the board itself is."""
    receipt = log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="human",
                channel=thread,
                idempotency_key=f"open-{thread}",
                payload={
                    "decision": decision,
                    "kind": "user",
                    "title": f"{decision or 'session'} — opened",
                    "requires_action": False,
                    "turns": [{"text": "Tell me about this."}],
                },
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted"


@pytest.mark.parametrize(
    ("layout", "reply"),
    [
        ("the object on the fence's own line", f"```json {json.dumps(DECLARING)} ```"),
        ("the object under the fence", f"```json\n{json.dumps(DECLARING)}\n```"),
        ("no fence at all", json.dumps(DECLARING)),
    ],
)
def test_a_declaring_reply_is_read_through_whatever_fence_it_arrived_in(
    layout: str, reply: str
) -> None:
    """
    Given one declaring document presented in each of the three layouts a model
         writes it in
    When the driver reads what the turn declared
    Then all three read as the same document, because where the model put its
         newlines is presentation and not what the turn said.
    """
    prose, _, _, proposal = declared_updates(reply)

    assert prose == DECLARING["text"], layout
    assert proposal == DECLARING["proposed_answer"], layout


def test_an_offer_on_a_thread_anchoring_nothing_is_a_notice_and_not_raw_bytes(
    session_dir: Path,
) -> None:
    """
    Given the session-scoped thread, which anchors no decision, and the fast
         agent replying to it with the live one-line fenced offer on `d1`
    When the turn is recorded
    Then the thread carries a line saying which decision was offered and why the
         board did not take it, the entry carries no offer, and none of the
         reply's own JSON reaches the human.
    """
    log = briefed(session_dir)
    open_thread(log, "t-help", None)
    human_turn(log, "How does this board work?", channel="t-help")

    driver = FastDriver(TierConfig(), ScriptedFast(reply=LIVE_ONE_LINE_OFFER))
    driver.run(log, record_dispatch(log, channel="t-help"))

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    said = written["payload"]["text"]
    assert PROPOSED_ANSWER_KEY not in written["payload"]
    assert "'d1'" in said
    assert "anchors no decision" in said
    assert "{" not in said
    assert PROPOSED_ANSWER_KEY not in said


def test_an_offer_on_another_decision_keeps_the_prose_and_says_why_it_was_refused(
    session_dir: Path,
) -> None:
    """
    Given a thread anchored to `d1` whose agent offers an answer to `d3`
    When the turn is recorded
    Then what the agent said to the human survives, the refusal is stated after
         it, and no offer rides the entry for the page to arm.
    """
    log = briefed(session_dir)
    open_thread(log, "t-compaction", TARGET)
    human_turn(log, "Say more about retention.", channel="t-compaction")
    offered = {"text": REPLY, "proposed_answer": {"decision": "d3", "text": "Forever"}}

    driver = FastDriver(TierConfig(), ScriptedFast(reply=json.dumps(offered)))
    driver.run(log, record_dispatch(log, channel="t-compaction"))

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    said = written["payload"]["text"]
    assert PROPOSED_ANSWER_KEY not in written["payload"]
    assert said.startswith(REPLY)
    assert "'d3'" in said
    assert "is about 'd1'" in said


def test_a_reply_the_appender_refuses_for_its_shape_surfaces_as_a_refused_reply(
    session_dir: Path,
) -> None:
    """
    Given a grill-master turn proposing an invalidation that says no why
    When the driver records it
    Then the refusal surfaces as a refused reply quoting the appender's own
         problem text, and nothing lands on the board.

    The turn produced nothing the log would take, which is what the human is
    owed the error for -- and the words are the appender's, so the agent is told
    which field it left out rather than that something went wrong.
    """
    log = briefed(session_dir)
    before = log.seq

    with pytest.raises(ReplyRefusedError) as refused:
        record_reply(
            log,
            FAST_TIER,
            MAP_CHANNEL,
            document(
                text="That decision is dead.", updates=[{"kind": "invalidate", "target": TARGET}]
            ),
            {},
        )

    assert str(refused.value) == (
        f"the {FAST_TIER!r} tier produced no reply: the appender refused it: "
        "event 0: fold sub-update 1: 'invalidate' payload: why: Field required"
    )
    assert log.seq == before
