"""Who takes a channel's first-rung turn, and the Codex thread that carries the
map's.

Nothing here reaches a model or runs the real `codex` binary: the CLI is a seam,
scripted with the JSONL stream the real one prints -- including the diagnostic
items it interleaves, which is what a reader taking "the last item" would put in
the log as the agent's turn. The one place the real binary runs is the launch
probe recorded in the pull request, deliberately outside this suite.

Every claim about who took a turn is read back out of the log file's bytes. What
the log says is what the page, the capture step and a restarted process will
see; what a driver remembers is gone the moment the turn is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conftest import (
    ScriptedCli,
    ScriptedFast,
    attributions,
    document,
    handoff_doc,
    replies,
    run_turns,
    write_handoff,
)

from grillui import drivers
from grillui.dispatch import GRILL_MASTER, record_dispatch
from grillui.drivers import (
    CODEX_RESUME_FILE,
    FIRST_RUNG_RESUME_FILE,
    NOT_STARTED,
    RESUME_FILE,
    TIMED_OUT,
    CodexDriver,
    FastDriver,
    HeavyDriver,
    OpenRouterTransport,
    codex_argv,
    codex_input_tokens,
    fault_of,
    read_codex_reply,
    read_resume,
    run_claude_cli,
    run_codex_cli,
    seat_driver,
)
from grillui.escalation import in_expert_mode
from grillui.lane import AgentUnreachableError, DocumentRefusedError, Lane
from grillui.schemas import (
    EFFORT_KEY,
    FAST_TIER,
    FOLDABLE_KINDS,
    HEAVY_TIER,
    MAP_CHANNEL,
    MODEL_KEY,
    PROMPT_TOKENS_KEY,
    STATUS_PHASE_COMPOSING,
    STATUS_PHASE_TRANSFERRED,
    TIER_KEY,
    CatchUpEntry,
    DispatchContext,
    EventSubmission,
)
from grillui.session import open_session
from grillui.tiers import (
    API_BASE_ENV,
    DEFAULT_API_BASE,
    DEFAULT_FAST_MODEL,
    DEFAULT_MAP_EFFORT,
    DEFAULT_MAP_MODEL,
    DOCUMENT_FORMAT_RULE,
    MAP_EFFORT_ENV,
    MAP_MODEL_ENV,
    MAP_TRANSPORT_ENV,
    OPENROUTER_TRANSPORT,
    Seat,
    TierConfig,
    UnknownEffortError,
    UnknownTransportError,
    system_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from grillui.log import SessionLog

NODE = "d1"
THREAD = "t-compaction"
MAP_SAID = "The store decision stands; compaction is untouched."
THREAD_SAID = "Retention is what that turns on."


@dataclass
class ScriptedCodex:
    """A `codex exec` that answers to order and remembers its argv.

    It prints the stream the real CLI prints, diagnostics and all: a
    `thread.started`, an `error` item the CLI emits about its own hooks, the
    agent's message, and the turn's usage. `totals` are `input_tokens` as the
    real one reports them -- a running total for the thread, not this turn's
    prompt.
    """

    reply: str | None = None
    replies: Sequence[str] = ()
    thread_id: str | None = "thread-1"
    totals: Sequence[int] = ()
    trailing_noise: bool = False
    silent: bool = False
    calls: list[list[str]] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], directory: Path, /) -> str:
        self.calls.append(list(argv))
        self.directories.append(directory)
        turn = len(self.calls)
        lines: list[dict[str, Any]] = []
        if self.thread_id is not None:
            lines.append({"type": "thread.started", "thread_id": self.thread_id})
        lines.append({"type": "item.completed", "item": {"type": "error", "message": "a warning"}})
        lines.append({"type": "turn.started"})
        if not self.silent:
            lines.append(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": self._said(turn)},
                }
            )
        if self.trailing_noise:
            lines.append(
                {"type": "item.completed", "item": {"type": "error", "message": "a late warning"}}
            )
        if self.totals:
            total = self.totals[min(turn - 1, len(self.totals) - 1)]
            lines.append(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": total,
                        "cached_input_tokens": total // 2,
                        "output_tokens": 20,
                    },
                }
            )
        return "\n".join(json.dumps(one) for one in lines)

    def _said(self, turn: int) -> str:
        if self.replies:
            return self.replies[min(turn - 1, len(self.replies) - 1)]
        return document(text=MAP_SAID) if self.reply is None else self.reply

    def option(self, turn: int, flag: str) -> str | None:
        """What one call passed for a flag, or nothing where it passed none."""
        argv = self.calls[turn - 1]
        return argv[argv.index(flag) + 1] if flag in argv else None

    def settings(self, turn: int) -> list[str]:
        """Every `-c key=value` one call carried."""
        argv = self.calls[turn - 1]
        return [argv[index + 1] for index, one in enumerate(argv) if one == "-c"]


def briefed(session_dir: Path) -> SessionLog:
    """A session seeded from the shared handoff."""
    write_handoff(session_dir, handoff_doc())
    return open_session(session_dir)


def human(kind: str, channel: str, key: str, /, **payload: Any) -> EventSubmission:
    """One human gesture. The envelope's names are positional so a payload of
    its own may carry `kind` -- a thread's kind is not the event's."""
    return EventSubmission(
        kind=kind, actor="human", channel=channel, idempotency_key=key, payload=payload
    )


def answered(key: str, text: str) -> EventSubmission:
    return human("answer", MAP_CHANNEL, key, target=NODE, answer={"text": text})


def opened(thread: str, key: str) -> EventSubmission:
    return human(
        "thread-created",
        thread,
        key,
        decision=NODE,
        kind="mandate",
        title="Retention",
        requires_action=True,
        turns=[{"who": "human", "text": "What does never compacting cost?"}],
    )


def a_turn(log: SessionLog, driver: Any, channel: str = MAP_CHANNEL) -> None:
    """One turn on one channel, without the lane scheduling it."""
    driver.run(log, record_dispatch(log, channel=channel))


def moved_board(log: SessionLog, directory: Path, channel: str = THREAD) -> Path:
    """This channel's dispatch, carrying what moved while it was set aside.

    Written from the real one rather than built from nothing, so what the driver
    reads is the recorded shape with the one field this case turns on filled in.
    """
    context = DispatchContext.model_validate_json(
        record_dispatch(log, channel=channel).read_text(encoding="utf-8")
    )
    moved = context.model_copy(
        update={
            "catch_up": [
                CatchUpEntry(seq=2, kind="invalidate", target=NODE, why="the store went away")
            ]
        }
    )
    path = directory / "reopening-dispatch.json"
    path.write_text(moved.model_dump_json(), encoding="utf-8")
    return path


# --- GMR-A5: two seats, one rung -----------------------------------------------


def test_the_map_and_a_thread_take_the_same_rung_on_seats_configured_apart(
    session_dir: Path,
) -> None:
    """
    Given a session with nothing configured, its channels' first-rung seats and
          the drivers those seats resolve to
    When the human answers on the map and says something on a thread
    Then the map's turn is composed on the Codex transport by `gpt-5.6-luna` at
         `medium` and the thread's over OpenRouter by the hosted model at no
         effort; both name the `fast` tier; and the map is not in expert mode, so
         its transfer control reads *Transfer to expert* at first paint.
    """
    config = TierConfig.from_env({})
    assert config.seat_for(MAP_CHANNEL) == Seat("codex", DEFAULT_MAP_MODEL, DEFAULT_MAP_EFFORT)
    assert config.seat_for(THREAD) == Seat(OPENROUTER_TRANSPORT, DEFAULT_FAST_MODEL)

    log = briefed(session_dir)
    threads = seat_driver(config, config.thread_seat)
    map_seat = seat_driver(config, config.map_seat)
    assert isinstance(threads, FastDriver)
    assert isinstance(map_seat, CodexDriver)
    threads.transport = ScriptedFast(reply=THREAD_SAID)
    map_seat.cli = ScriptedCodex()

    lane = Lane(log, threads, expert=None, seats={MAP_CHANNEL: map_seat})
    run_turns(lane, opened(THREAD, "h1"))
    run_turns(lane, answered("h2", "The log is the recovery source."))

    on_thread, on_map = attributions(log)
    assert on_map == {
        TIER_KEY: FAST_TIER,
        MODEL_KEY: DEFAULT_MAP_MODEL,
        EFFORT_KEY: DEFAULT_MAP_EFFORT,
        "text": MAP_SAID,
    }
    assert on_thread == {TIER_KEY: FAST_TIER, MODEL_KEY: DEFAULT_FAST_MODEL, "text": THREAD_SAID}
    # The seat that takes no effort is recorded as having taken none: the key's
    # presence is the claim that the request carried one.
    assert EFFORT_KEY not in on_thread
    # The label itself is the page's, and `test_page` pins its two strings. What
    # the backend owns is what the label is computed from: the channel is not in
    # expert mode, and the lane named `fast` as the tier the human is waiting on,
    # so the control renders *Transfer to expert* rather than the way back.
    assert not in_expert_mode(log.entries(), MAP_CHANNEL)
    assert [
        entry.payload.get(TIER_KEY)
        for entry in log.entries()
        if entry.payload.get("phase") == STATUS_PHASE_COMPOSING and entry.channel == MAP_CHANNEL
    ] == [FAST_TIER]


def test_seating_the_map_on_the_threads_seat_moves_its_turn_and_nothing_else(
    session_dir: Path,
) -> None:
    """
    Given a session configured to seat the map channel on the threads' seat
    When the human answers on the map
    Then that turn takes the threads' transport and model, carries no effort, and
         still names the `fast` tier on the map channel.
    """
    config = TierConfig.from_env(
        {MAP_TRANSPORT_ENV: OPENROUTER_TRANSPORT, MAP_MODEL_ENV: DEFAULT_FAST_MODEL}
    )
    assert config.map_seat == config.thread_seat

    log = briefed(session_dir)
    seated = seat_driver(config, config.map_seat)
    assert isinstance(seated, FastDriver)
    seated.transport = ScriptedFast(reply=document(text=MAP_SAID))
    # The threads' driver is a different object on a different model, so a lane
    # that ignored the seating would be caught by the attribution rather than
    # passing on the two being the same instance.
    threads = seat_driver(
        TierConfig(fast_model="another/model"), Seat(OPENROUTER_TRANSPORT, "another/model")
    )
    assert isinstance(threads, FastDriver)
    threads.transport = ScriptedFast(reply=THREAD_SAID)

    lane = Lane(log, threads, expert=None, seats={MAP_CHANNEL: seated})
    run_turns(lane, answered("h1", "The log is the recovery source."))

    assert attributions(log) == [
        {TIER_KEY: FAST_TIER, MODEL_KEY: DEFAULT_FAST_MODEL, "text": MAP_SAID}
    ]


def test_an_effort_configured_on_a_seat_that_sends_none_is_not_attributed_to_it() -> None:
    """
    Given the map seated on OpenRouter with an effort left over in the environment
    When its seat is read
    Then the seat carries no effort, because that transport is sent none -- an
         attribution nobody can tell apart from one the request made.
    """
    config = TierConfig.from_env(
        {
            MAP_TRANSPORT_ENV: OPENROUTER_TRANSPORT,
            MAP_MODEL_ENV: DEFAULT_FAST_MODEL,
            MAP_EFFORT_ENV: "max",
        }
    )
    assert config.map_seat.effort is None


def test_an_effort_the_cli_would_not_take_is_refused_at_launch() -> None:
    """
    Given the map seat configured at an effort outside the closed set
    When the configuration is read
    Then it is refused while the human is still watching the launch, naming the
         key they got wrong rather than the other seat's.
    """
    with pytest.raises(UnknownEffortError) as raised:
        TierConfig.from_env({MAP_EFFORT_ENV: "medium-ish"})
    assert MAP_EFFORT_ENV in str(raised.value)


def test_a_transport_outside_the_three_is_refused_at_launch() -> None:
    """
    Given a misspelled transport
    When the configuration is read
    Then it is refused rather than resolved to whichever driver the wiring falls
         through to.
    """
    with pytest.raises(UnknownTransportError):
        TierConfig.from_env({MAP_TRANSPORT_ENV: "opnerouter"})


def test_a_seat_resolves_to_the_driver_of_its_transport() -> None:
    """
    Given each of the three transports a seat may sit on
    When a driver is asked for
    Then each gets the one that speaks it, on whichever rung it was asked for.
    """
    config = TierConfig()
    assert isinstance(seat_driver(config, Seat("codex", "m", "medium")), CodexDriver)
    assert isinstance(seat_driver(config, Seat("claude", "m", "xhigh")), HeavyDriver)
    assert isinstance(seat_driver(config, Seat(OPENROUTER_TRANSPORT, "m")), FastDriver)
    expert = seat_driver(config, config.expert_seat, tier=HEAVY_TIER)
    assert expert.tier == HEAVY_TIER


def test_a_channel_with_no_seat_of_its_own_takes_the_sessions(session_dir: Path) -> None:
    """
    Given a lane whose only seat is the map's
    When a thread takes a turn
    Then it is the session's own driver that takes it, and the map's seat is
         untouched.
    """
    log = briefed(session_dir)
    threads = FastDriver(TierConfig(), ScriptedFast(reply=THREAD_SAID))
    seated = CodexDriver(TierConfig(), ScriptedCodex())
    lane = Lane(log, threads, seats={MAP_CHANNEL: seated})

    assert lane.tier_for(THREAD, threads) is threads
    assert lane.tier_for(MAP_CHANNEL, threads) is seated


def test_a_seated_channel_still_hands_its_turn_up_to_the_one_expert(session_dir: Path) -> None:
    """
    Given a map channel seated on Codex, an expert tier, and a human who has
          transferred that channel
    When the turn is routed
    Then the expert takes it: a seat changes who sits on the first rung and never
         how many rungs there are.
    """
    log = briefed(session_dir)
    threads = FastDriver(TierConfig(), ScriptedFast())
    seated = CodexDriver(TierConfig(), ScriptedCodex())
    expert = HeavyDriver(TierConfig(), lambda _argv: json.dumps({"result": document()}))
    lane = Lane(log, threads, expert, seats={MAP_CHANNEL: seated})

    assert lane.tier_for(MAP_CHANNEL, threads) is seated
    run_turns(
        lane, human("answer", MAP_CHANNEL, "h1", target=NODE, answer={"text": "x"}, transfer=True)
    )
    assert lane.tier_for(MAP_CHANNEL, threads) is expert


# --- GMR-A11: the Codex thread ------------------------------------------------


def test_the_codex_seat_opens_a_thread_cold_and_resumes_it_thereafter(session_dir: Path) -> None:
    """
    Given a map channel on the Codex seat taking two turns
    When each turn is composed
    Then the first is `codex exec --json` and the second `codex exec resume
         <thread_id> --json`; the id comes off the `thread.started` event and is
         kept per channel; and the standing brief and the effort ride on the
         resumed turn as well as the cold one, since a resumed thread inherits
         neither.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex(thread_id="thread-7")
    driver = CodexDriver(TierConfig(), cli)

    a_turn(log, driver)
    a_turn(log, driver)

    cold, resumed = cli.calls
    assert cold[:3] == ["codex", "exec", "--json"]
    assert "resume" not in cold
    assert resumed[:5] == ["codex", "exec", "resume", "thread-7", "--json"]
    assert read_resume(session_dir, MAP_CHANNEL, CODEX_RESUME_FILE) == "thread-7"
    for turn in (1, 2):
        settings = cli.settings(turn)
        assert any(one.startswith("developer_instructions=") for one in settings), turn
        assert f'model_reasoning_effort="{DEFAULT_MAP_EFFORT}"' in settings, turn
        assert cli.option(turn, "--model") == DEFAULT_MAP_MODEL
        assert "--json" in cli.calls[turn - 1]


def test_the_seat_is_given_no_way_to_run_a_command_or_write_anything(session_dir: Path) -> None:
    """
    Given a map channel on the Codex seat taking two turns
    When each is composed
    Then both invocations disable the CLI's two execution features and pin the
         read-only sandbox and the never-approve policy, and both run in the
         session's own directory: a turn that rules on a plan has no tool for
         the human's working tree, and a resumed turn that inherited the
         defaults would have one again.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex()
    driver = CodexDriver(TierConfig(), cli)

    a_turn(log, driver)
    a_turn(log, driver)

    for turn in (1, 2):
        settings = cli.settings(turn)
        assert "features.shell_tool=false" in settings, turn
        assert "features.unified_exec=false" in settings, turn
        assert 'sandbox_mode="read-only"' in settings, turn
        assert 'approval_policy="never"' in settings, turn
    assert cli.directories == [session_dir, session_dir]


def test_the_transport_is_asked_for_no_schema_and_told_the_directory_is_not_a_repo(
    session_dir: Path,
) -> None:
    """
    Given a map channel on the Codex seat taking a cold turn and a resumed one
    When each invocation is read
    Then neither asks the provider to shape the reply -- strict structured output
         cannot express an open update, and the closed schema it accepts empties
         every one -- and both carry `--skip-git-repo-check`, without which the
         CLI refuses the turn over a session directory that is not a repository.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex()
    driver = CodexDriver(TierConfig(), cli)

    a_turn(log, driver)
    a_turn(log, driver)

    for turn in (1, 2):
        assert "--output-schema" not in cli.calls[turn - 1], turn
        assert "--skip-git-repo-check" in cli.calls[turn - 1], turn


def test_a_first_rung_claude_seat_never_shares_the_experts_chain(session_dir: Path) -> None:
    """
    Given a session that seats the map's first rung on the `claude` transport,
          with the expert seat behind it on the same channel
    When each takes a turn
    Then they resume different conversations and each is composed with its own
         rung's brief: one file keyed by channel could hold only one of the two,
         and the expert would resume the turn the first rung was having.
    """
    log = briefed(session_dir)
    config = TierConfig.from_env({MAP_TRANSPORT_ENV: "claude", MAP_MODEL_ENV: "claude-first-rung"})
    first = seat_driver(config, config.map_seat)
    expert = seat_driver(config, config.expert_seat, tier=HEAVY_TIER)
    assert isinstance(first, HeavyDriver)
    assert isinstance(expert, HeavyDriver)
    first.cli = ScriptedCli(session_id="first-rung-chain")
    expert.cli = ScriptedCli(session_id="expert-chain")

    a_turn(log, first)
    a_turn(log, expert)

    assert read_resume(session_dir, MAP_CHANNEL, FIRST_RUNG_RESUME_FILE) == "first-rung-chain"
    assert read_resume(session_dir, MAP_CHANNEL, RESUME_FILE) == "expert-chain"
    briefs = [first.cli.calls[0], expert.cli.calls[0]]
    assert briefs[0][briefs[0].index("--append-system-prompt") + 1] == system_prompt(
        FAST_TIER, GRILL_MASTER
    )
    assert briefs[1][briefs[1].index("--append-system-prompt") + 1] == system_prompt(
        HEAVY_TIER, GRILL_MASTER
    )
    assert [one[TIER_KEY] for one in attributions(log)] == [FAST_TIER, HEAVY_TIER]


def test_a_refused_attempt_is_not_billed_to_the_turn_that_lands(session_dir: Path) -> None:
    """
    Given a Codex seat whose first attempt is refused and whose retry lands, on a
          thread whose reported total advances for both
    When the accepted turn is recorded
    Then it carries what it alone was given: the baseline moves on every attempt
         the provider counted, so a rejected one is not billed to the reply after
         it.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex(
        replies=["prose, not a document", document(text=MAP_SAID)], totals=[10_000, 21_000]
    )

    a_turn(log, CodexDriver(TierConfig(), cli))

    assert replies(log)[0][PROMPT_TOKENS_KEY] == 11_000


def test_a_failed_transport_names_its_category_and_publishes_no_provider_bytes() -> None:
    """
    Given a process that exits non-zero with a secret on its standard error, one
          that cannot be started, one that times out, and a stream whose only
          content is an error item carrying a secret
    When each is surfaced to the lane
    Then the human is told which of the four it was and nothing else: the status
         entry is persisted and rendered, `stderr` carries whatever the provider
         printed, an error item carries whatever it was told, and a timeout's
         argv carries the composed prompt.
    """
    here = Path(__file__).parent
    leaked = "sk-SENTINEL-TOKEN"

    with pytest.raises(AgentUnreachableError) as exited:
        run_codex_cli(
            [
                sys.executable,
                "-c",
                f"import sys; print({leaked!r}, file=sys.stderr); raise SystemExit(2)",
            ],
            here,
        )
    with pytest.raises(AgentUnreachableError) as missing:
        run_codex_cli(["/nonexistent/codex", "exec"], here)
    with pytest.raises(AgentUnreachableError) as claude:
        run_claude_cli(
            [
                sys.executable,
                "-c",
                f"import sys; print({leaked!r}, file=sys.stderr); raise SystemExit(2)",
            ]
        )

    assert "exited 2" in str(exited.value)
    assert str(missing.value).endswith(NOT_STARTED)
    assert "exited 2" in str(claude.value)
    for raised in (exited, missing, claude):
        assert leaked not in str(raised.value)
    assert fault_of(subprocess.TimeoutExpired("codex", 1.0)).endswith(TIMED_OUT)
    # The stream's own error items are the fourth case, and they are read for a
    # turn rather than for a message to publish.
    assert leaked not in str(
        read_codex_reply(
            json.dumps({"type": "item.completed", "item": {"type": "error", "message": leaked}})
        )
    )


def test_no_provider_bytes_reach_a_status_entry(session_dir: Path) -> None:
    """
    Given a Codex seat whose transport fails with a secret in what it printed
    When the lane records the failure
    Then no status entry the board renders carries it.
    """
    log = briefed(session_dir)
    leaked = "sk-SENTINEL-TOKEN"

    def exploding(_argv: Sequence[str], _directory: Path, /) -> str:
        raise AgentUnreachableError(
            FAST_TIER, fault_of(subprocess.CalledProcessError(3, "codex", stderr=leaked))
        )

    lane = Lane(log, CodexDriver(TierConfig(), exploding))
    run_turns(lane, answered("h1", "The log is the recovery source."))

    said = [json.dumps(entry.payload) for entry in log.entries()]
    assert any("exited 3" in one for one in said), "the category never reached the lane"
    assert not any(leaked in one for one in said)


def test_the_standing_brief_crosses_as_one_toml_value(session_dir: Path) -> None:
    """
    Given a standing brief carrying newlines, quotes and braces
    When it is put on the command line
    Then it is one quoted TOML string, so what the brief means does not depend on
         whether it happens to parse as TOML.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex()
    CodexDriver(TierConfig(), cli).run(log, record_dispatch(log))

    setting = next(one for one in cli.settings(1) if one.startswith("developer_instructions="))
    quoted = setting[len("developer_instructions=") :]
    assert quoted.startswith('"') and quoted.endswith('"')
    assert "grill-master" in json.loads(quoted)
    assert "\n" not in quoted


def test_each_channel_keeps_its_own_thread(session_dir: Path) -> None:
    """
    Given the map and a side thread both taken on the Codex seat
    When each has had a turn
    Then each channel resumes its own conversation, because the map's and a
         thread's are not the same one.
    """
    log = briefed(session_dir)
    log.submit([opened(THREAD, "h1")], log.epoch)
    a_turn(log, CodexDriver(TierConfig(), ScriptedCodex(thread_id="map-thread")))
    a_turn(
        log,
        CodexDriver(TierConfig(), ScriptedCodex(reply=THREAD_SAID, thread_id="side-thread")),
        channel=THREAD,
    )

    kept = json.loads((session_dir / CODEX_RESUME_FILE).read_text(encoding="utf-8"))
    assert kept == {MAP_CHANNEL: "map-thread", THREAD: "side-thread"}


def test_a_turn_that_names_no_thread_is_still_a_turn(session_dir: Path) -> None:
    """
    Given a stream carrying no `thread.started`
    When the turn is taken
    Then the reply still lands and nothing is remembered to resume into.
    """
    log = briefed(session_dir)
    a_turn(log, CodexDriver(TierConfig(), ScriptedCodex(thread_id=None)))

    assert replies(log)[0]["text"] == MAP_SAID
    assert not (session_dir / CODEX_RESUME_FILE).exists()


def test_the_reply_is_the_last_agent_message_and_not_the_last_item(session_dir: Path) -> None:
    """
    Given a stream whose final completed item is one of the CLI's own diagnostics
    When the reply is read
    Then the agent's message is what lands, not the diagnostic.
    """
    log = briefed(session_dir)
    a_turn(log, CodexDriver(TierConfig(), ScriptedCodex(trailing_noise=True)))

    assert replies(log)[0]["text"] == MAP_SAID


def test_a_stream_with_no_turn_still_reports_what_it_counted(session_dir: Path) -> None:
    """
    Given a stream that carries a counted total and no agent message
    When it is read
    Then the reader says there was no turn rather than raising past the total,
         and the turn that lands next is not billed for the one that did not:
         the tokens were spent either way.
    """
    assert read_codex_reply('{"type": "thread.started", "thread_id": "t"}') == (None, "t", None)
    said, thread, counted = read_codex_reply(
        "\n".join(
            [
                "not json at all",
                json.dumps({"type": "thread.started", "thread_id": 7}),
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": 1}}
                ),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": "many"}}),
            ]
        )
    )
    assert (said, thread, counted) == (None, None, None)

    log = briefed(session_dir)
    turnless = ScriptedCodex(replies=[document(text=MAP_SAID)], totals=[8_000, 15_000])
    turnless.silent = True
    driver = CodexDriver(TierConfig(), turnless)
    with pytest.raises(AgentUnreachableError):
        a_turn(log, driver)
    turnless.silent = False
    a_turn(log, driver)

    assert replies(log)[0][PROMPT_TOKENS_KEY] == 7_000


def test_a_channel_that_rotates_onto_another_thread_counts_from_nothing(
    session_dir: Path,
) -> None:
    """
    Given a channel whose next turn opens a different thread
    When that turn is measured
    Then it counts from nothing rather than subtracting the old thread's total:
         two conversations are two windows, and the difference between them is
         arithmetic about neither.
    """
    log = briefed(session_dir)
    driver = CodexDriver(TierConfig(), ScriptedCodex(thread_id="first", totals=[30_000]))
    a_turn(log, driver)
    driver.cli = ScriptedCodex(thread_id="second", totals=[9_000])
    a_turn(log, driver)

    assert [one[PROMPT_TOKENS_KEY] for one in replies(log)] == [30_000, 9_000]


def test_the_process_runs_with_stdin_closed_in_the_sessions_own_directory(
    monkeypatch: pytest.MonkeyPatch, session_dir: Path
) -> None:
    """
    Given the real process runner
    When a turn is run
    Then standard input is closed, because `codex exec` otherwise waits on a
         stream nobody is writing for as long as the session lasts; and the
         process runs in the session's directory rather than wherever the
         backend was launched, because the CLI reads its working directory into
         the turn.
    """
    seen: dict[str, Any] = {}

    def spy(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(drivers.subprocess, "run", spy)
    run_codex_cli(["codex", "exec"], session_dir)

    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["cwd"] == session_dir


def test_a_cli_that_is_not_there_or_fails_reads_as_unreachable() -> None:
    """
    Given a runner that cannot start, and one that exits non-zero
    When each is run
    Then both are an unreachable seat rather than a turn that happened.
    """
    here = Path(__file__).parent
    assert run_codex_cli([sys.executable, "-c", "print('{}')"], here).strip() == "{}"
    with pytest.raises(AgentUnreachableError):
        run_codex_cli(["/nonexistent/codex", "exec"], here)
    with pytest.raises(AgentUnreachableError):
        run_codex_cli([sys.executable, "-c", "raise SystemExit(3)"], here)


def test_a_reply_that_is_not_the_document_is_refused_after_one_retry(session_dir: Path) -> None:
    """
    Given a Codex seat that answers in prose twice
    When it takes a map turn
    Then the turn is refused with the fault named, the seat was asked again with
         the fault quoted, and none of what it said reached the log.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex(reply="I think the log is fine, really.")

    with pytest.raises(DocumentRefusedError):
        a_turn(log, CodexDriver(TierConfig(), cli))

    assert len(cli.calls) == 2
    assert "Your last reply was refused" in cli.calls[1][-1]
    assert replies(log) == []


def test_a_seat_that_finds_the_shape_on_the_retry_keeps_its_turn(session_dir: Path) -> None:
    """
    Given a Codex seat whose first reply is prose and whose second is the document
    When it takes a map turn
    Then the second turn lands, and it resumed the thread the first one opened
         rather than opening a second conversation about it.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex(replies=["prose, not a document", document(text=MAP_SAID)])

    a_turn(log, CodexDriver(TierConfig(), cli))

    assert replies(log)[0]["text"] == MAP_SAID
    assert cli.calls[1][:4] == ["codex", "exec", "resume", "thread-1"]


def test_the_turns_own_input_is_recorded_and_not_the_threads_running_total(
    session_dir: Path,
) -> None:
    """
    Given a thread whose reported `input_tokens` accumulate across turns
    When three turns are taken
    Then each records what that turn was given -- the growth in the total -- and
         not the total itself, which by the third turn is three times the
         conversation it is measuring.
    """
    log = briefed(session_dir)
    driver = CodexDriver(TierConfig(), ScriptedCodex(totals=[25_000, 52_000, 81_000]))

    for _ in range(3):
        a_turn(log, driver)

    assert [one[PROMPT_TOKENS_KEY] for one in replies(log)] == [25_000, 27_000, 29_000]


def test_a_turn_the_provider_counted_is_not_reported_as_an_estimate(session_dir: Path) -> None:
    """
    Given a turn whose usage the provider reported
    When it lands
    Then the count is what is recorded, rather than the prompt's bytes at a
         stated ratio -- and a turn reporting no usage carries no count at all.
    """
    log = briefed(session_dir)
    a_turn(log, CodexDriver(TierConfig(), ScriptedCodex(totals=[4_242])))
    a_turn(log, CodexDriver(TierConfig(), ScriptedCodex()))

    counted, uncounted = replies(log)
    assert counted[PROMPT_TOKENS_KEY] == 4_242
    assert PROMPT_TOKENS_KEY not in uncounted
    assert codex_input_tokens(None) is None
    assert codex_input_tokens({"output_tokens": 3}) is None


def test_a_total_that_did_not_grow_is_no_count_at_all(session_dir: Path) -> None:
    """
    Given a thread whose reported total went backwards
    When the turn lands
    Then no count is stated: something other than this driver moved the thread,
         and an unmeasured turn falls back to the estimate rather than to a
         number nobody can stand behind.
    """
    log = briefed(session_dir)
    driver = CodexDriver(TierConfig(), ScriptedCodex(totals=[9_000, 500]))

    a_turn(log, driver)
    a_turn(log, driver)

    first, second = replies(log)
    assert first[PROMPT_TOKENS_KEY] == 9_000
    assert PROMPT_TOKENS_KEY not in second


def test_a_thread_reopened_over_a_board_that_moved_starts_a_new_conversation(
    session_dir: Path,
) -> None:
    """
    Given a Codex seat that has a thread going on a channel
    When that channel is reopened across a board that moved while it was away
    Then the turn is opened cold and the old thread is forgotten, rather than
         resumed into a conversation that reasoned from a board that no longer
         holds.
    """
    log = briefed(session_dir)
    cli = ScriptedCodex(reply=THREAD_SAID)
    driver = CodexDriver(TierConfig(), cli)
    log.submit([opened(THREAD, "h1")], log.epoch)
    a_turn(log, driver, channel=THREAD)
    assert read_resume(session_dir, THREAD, CODEX_RESUME_FILE) == "thread-1"

    driver.run(log, moved_board(log, session_dir))

    assert "resume" not in cli.calls[1]
    assert read_resume(session_dir, THREAD, CODEX_RESUME_FILE) == "thread-1"


def test_the_seat_recommends_a_transfer_the_way_the_other_first_rung_seat_does(
    session_dir: Path,
) -> None:
    """
    Given an autonomous session whose human turn meets an escalation condition on
          the map
    When the Codex seat answers it
    Then the channel is moved to the expert, because the recommendation is a
         property of the rung and not of the transport: one only the OpenRouter
         seat made would go silent the moment a channel was seated elsewhere.
    """
    log = briefed(session_dir)
    log.submit(
        [answered("h1", "I cannot resolve this one; it is the trade-off itself.")], log.epoch
    )
    CodexDriver(TierConfig(escalation_policy="autonomous"), ScriptedCodex()).run(
        log, record_dispatch(log)
    )

    moved = [
        entry.payload.get("detail")
        for entry in log.entries()
        if entry.payload.get("phase") == STATUS_PHASE_TRANSFERRED
    ]
    assert len(moved) == 1


def test_the_format_rule_names_every_update_kind_the_backend_folds() -> None:
    """
    Given the standing brief's format rule
    When the kinds it offers are read back
    Then they are exactly the kinds the appender folds -- read off the same
         vocabulary rather than retyped, because a seat told nothing about the
         list invents a kind that is refused, and the refusal takes the whole
         turn with it.
    """
    listed = DOCUMENT_FORMAT_RULE.split("`kind` is one of ")[1].split(" and nothing else")[0]

    assert set(listed.split(", ")) == set(FOLDABLE_KINDS)


def test_a_seat_with_no_effort_asks_the_transport_for_none() -> None:
    """
    Given a Codex seat configured with no effort
    When its arguments are built
    Then nothing is said about how hard to think, rather than a default being
         invented on the seat's behalf.
    """
    argv = codex_argv(Seat("codex", "some-model"), "brief", "prompt", None)

    assert not any(one.startswith("model_reasoning_effort") for one in argv)
    assert argv[-1] == "prompt"


def test_the_openrouter_seat_asks_the_endpoint_the_session_is_configured_with() -> None:
    """
    Given an environment naming a completions endpoint
    When the threads' seat is resolved to its driver
    Then the transport that driver holds asks that endpoint, and an unset one
         leaves it asking the provider's own -- so a session pointed elsewhere
         goes through the seat every other turn goes through rather than through
         a second wiring beside it.
    """
    stated = seat_driver(
        TierConfig.from_env({API_BASE_ENV: "http://127.0.0.1:9/v1"}),
        Seat(OPENROUTER_TRANSPORT, "m"),
    )
    default = seat_driver(TierConfig.from_env({}), Seat(OPENROUTER_TRANSPORT, "m"))

    assert isinstance(stated.transport, OpenRouterTransport)
    assert stated.transport.api_base == "http://127.0.0.1:9/v1"
    assert isinstance(default.transport, OpenRouterTransport)
    assert default.transport.api_base == DEFAULT_API_BASE


def test_the_request_timeout_is_configuration_with_the_constant_as_its_default() -> None:
    from functools import partial

    from grillui import drivers
    from grillui.tiers import DEFAULT_REQUEST_TIMEOUT, REQUEST_TIMEOUT_ENV, TierConfig

    assert TierConfig.from_env({}).request_timeout == DEFAULT_REQUEST_TIMEOUT == 60.0
    config = TierConfig.from_env({REQUEST_TIMEOUT_ENV: "300"})
    assert config.request_timeout == 300.0
    codex = drivers.seat_driver(config, config.map_seat)
    heavy = drivers.seat_driver(config, config.expert_seat, tier="heavy")
    fast = drivers.seat_driver(config, config.thread_seat)
    assert isinstance(codex.cli, partial) and codex.cli.keywords == {"timeout": 300.0}  # type: ignore[attr-defined]
    assert isinstance(heavy.cli, partial) and heavy.cli.keywords == {"timeout": 300.0}  # type: ignore[attr-defined]
    assert fast.transport.timeout == 300.0  # type: ignore[attr-defined]


def test_an_unreadable_request_timeout_is_refused_at_configuration() -> None:
    import pytest

    from grillui.tiers import REQUEST_TIMEOUT_ENV, TierConfig, UnreadableLimitError

    for raw in ("soon", "0", "-5"):
        with pytest.raises(UnreadableLimitError):
            TierConfig.from_env({REQUEST_TIMEOUT_ENV: raw})
