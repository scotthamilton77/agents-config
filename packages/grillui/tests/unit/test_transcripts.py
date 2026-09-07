"""The chain a CLI turn ran on, on the log, and that chain's transcript beside it.

Nothing here reaches a CLI or a real store. Both transports answer from scripted
processes, and both stores are directories under `tmp_path` -- a test that read
the machine's own `~/.claude` or `~/.codex` would be asserting against whatever
the developer happened to have run that morning, and one that wrote there would
be leaving turns in a human's history.

What the log says is read back out of the log file's bytes, because that is what
a restarted backend, the page and the capture step will see.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conftest import TIMEOUT, ScriptedFast, document, replies
from test_drivers import briefed, human_turn

from grillui.dispatch import record_dispatch
from grillui.drivers import (
    CLAUDE_CONFIG_ENV,
    CODEX_HOME_ENV,
    CODEX_RESUME_FILE,
    RESUME_FILE,
    CodexDriver,
    FastDriver,
    HeavyDriver,
    claude_transcript,
    codex_transcript,
    copy_transcript,
    read_resume,
)
from grillui.log import TRANSCRIPT_DIR
from grillui.schemas import CHAIN_KEY, CatchUpEntry, DispatchContext
from grillui.tiers import TierConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

    from grillui.drivers import TranscriptStore
    from grillui.log import SessionLog

NODE = "d1"
KEPT = '{"type":"user","text":"what the turn read"}\n'
LATER = '{"type":"user","text":"and what the next one read"}\n'
# What a store that will not answer says, quoted back on the line the copy writes.
UNREADABLE = "the store is not readable"


# --- the seats, scripted to name the chains this file is about ----------------


@dataclass
class ChainingCli:
    """A `claude` that names a chain of its own choosing on each turn.

    The scripted chain per turn is what the resume file cannot express: a cold
    reopen drops the chain it had and the CLI answers with another, and the
    question is which one the log ends up naming. A chain of `None` is the CLI
    printing no `session_id` at all.
    """

    chains: Sequence[str | None] = ("chain-1",)
    reply: str = field(default_factory=document)
    resumed: list[str | None] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], _directory: Path, /) -> str:
        turn = len(self.resumed)
        argv = list(argv)
        self.resumed.append(argv[argv.index("--resume") + 1] if "--resume" in argv else None)
        printed: dict[str, Any] = {"result": self.reply}
        chain = self.chains[min(turn, len(self.chains) - 1)]
        if chain is not None:
            printed["session_id"] = chain
        return json.dumps(printed)


@dataclass
class ThreadingCli:
    """A `codex exec` that names a thread of its own choosing on each turn."""

    chains: Sequence[str | None] = ("thread-1",)
    reply: str = field(default_factory=document)
    resumed: list[str | None] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], _directory: Path, /) -> str:
        turn = len(self.resumed)
        argv = list(argv)
        # The argv a driver hands a transport still carries the program name, so
        # `exec resume <thread>` starts one past the front of it.
        self.resumed.append(argv[3] if argv[1:3] == ["exec", "resume"] else None)
        lines: list[dict[str, Any]] = []
        thread = self.chains[min(turn, len(self.chains) - 1)]
        if thread is not None:
            lines.append({"type": "thread.started", "thread_id": thread})
        lines.append(
            {"type": "item.completed", "item": {"type": "agent_message", "text": self.reply}}
        )
        return "\n".join(json.dumps(one) for one in lines)


def store(root: Path) -> TranscriptStore:
    """A transcript store under a temporary directory, one file per chain."""

    def locate(_directory: Path, chain: str, /) -> Path:
        return root / f"{chain}.jsonl"

    return locate


def kept(root: Path, chain: str, text: str = KEPT) -> Path:
    """A transcript already in that store."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{chain}.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def heavy(cli: Any, root: Path) -> HeavyDriver:
    """The expert seat, answering from `cli` and copying out of `root`."""
    return HeavyDriver(TierConfig(), cli, transcript=store(root))


def codex(cli: Any, root: Path) -> CodexDriver:
    """A Codex seat, answering from `cli` and copying out of `root`."""
    return CodexDriver(TierConfig(), cli, transcript=store(root))


# The two CLI seats. Every claim about a chain is a claim about both: they
# differ in how the CLI reports the chain and in which file keeps it, and in
# nothing else, so a claim pinned on one of them is untested on the other.
SEATS = [
    pytest.param(heavy, ChainingCli, RESUME_FILE, ("chain-a", "chain-b"), id="claude"),
    pytest.param(codex, ThreadingCli, CODEX_RESUME_FILE, ("thread-a", "thread-b"), id="codex"),
]

SILENT_SEATS = [
    pytest.param(lambda root: heavy(ChainingCli(chains=(None,)), root), id="claude"),
    pytest.param(lambda root: codex(ThreadingCli(chains=(None,)), root), id="codex"),
]


def taken(log: SessionLog, driver: Any, dispatch: Path | None = None) -> Any:
    """One turn, and the copy it started waited out.

    Waited out here and nowhere in the backend: what a scenario needs is a
    settled directory to assert on, and what a turn needs is not to be delayed
    by one.
    """
    driver.run(log, record_dispatch(log) if dispatch is None else dispatch)
    if driver.copying is not None:
        driver.copying.join(TIMEOUT)
    return driver


def reopening(log: SessionLog, directory: Path) -> Path:
    """A dispatch carrying a board that moved, which is what opens a chain cold.

    Written from the real one rather than built from nothing, so the driver
    reads the recorded shape with the one field this case turns on filled in.
    """
    context = DispatchContext.model_validate_json(record_dispatch(log).read_text(encoding="utf-8"))
    moved = context.model_copy(
        update={"catch_up": [CatchUpEntry(seq=2, kind="invalidate", target=NODE, why="it went")]}
    )
    path = directory / "reopening-dispatch.json"
    path.write_text(moved.model_dump_json(), encoding="utf-8")
    return path


def copied(session_dir: Path, chain: str) -> Path:
    return session_dir / TRANSCRIPT_DIR / f"{chain}.jsonl"


# --- the chain on the record --------------------------------------------------


def test_a_cold_heavy_turn_records_the_chain_the_cli_opened(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a session whose expert seat has no chain open
    When it takes a turn and the CLI names the chain it opened
    Then the reply on the log carries that chain.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")

    taken(log, heavy(ChainingCli(chains=("chain-a",)), tmp_path / "store"))

    assert replies(log)[-1][CHAIN_KEY] == "chain-a"


def test_a_resumed_heavy_turn_records_the_chain_it_resumed(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given an expert seat that has already opened a chain
    When it takes a second turn on it
    Then the second reply names the same chain, and it is the one the turn
         resumed rather than one the driver remembered.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    cli = ChainingCli(chains=("chain-a",))
    driver = taken(log, heavy(cli, tmp_path / "store"))

    human_turn(log, "And what about compaction?")
    taken(log, driver)

    assert cli.resumed == [None, "chain-a"]
    assert [reply[CHAIN_KEY] for reply in replies(log)] == ["chain-a", "chain-a"]


@pytest.mark.parametrize(("seat", "scripted", "chains", "named"), SEATS)
def test_a_turn_reopened_cold_records_the_new_chain_not_the_dropped_one(
    session_dir: Path,
    tmp_path: Path,
    seat: Any,
    scripted: Any,
    chains: str,
    named: tuple[str, str],
) -> None:
    """
    Given a CLI seat holding a chain, and a dispatch whose board has moved
    When it takes that turn, dropping the chain and opening another
    Then the reply names the chain it opened, so the record survives the chain
         file forgetting the old one.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    cli = scripted(chains=named)
    driver = taken(log, seat(cli, tmp_path / "store"))

    human_turn(log, "The board moved under this one.")
    taken(log, driver, reopening(log, tmp_path))

    assert cli.resumed == [None, None]
    assert [reply[CHAIN_KEY] for reply in replies(log)] == list(named)
    assert read_resume(session_dir, "map", chains) == named[1]


def test_a_cold_codex_turn_records_the_thread_the_cli_opened(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a Codex seat with no thread open
    When it takes a turn and the CLI names the thread it started
    Then the reply on the log carries that thread.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")

    taken(log, codex(ThreadingCli(chains=("thread-a",)), tmp_path / "store"))

    assert replies(log)[-1][CHAIN_KEY] == "thread-a"


def test_a_resumed_codex_turn_records_the_thread_it_resumed(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a Codex seat that has already started a thread
    When it takes a second turn on it
    Then the second reply names the thread the turn resumed.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    cli = ThreadingCli(chains=("thread-a",))
    driver = taken(log, codex(cli, tmp_path / "store"))

    human_turn(log, "And what about compaction?")
    taken(log, driver)

    assert cli.resumed == [None, "thread-a"]
    assert [reply[CHAIN_KEY] for reply in replies(log)] == ["thread-a", "thread-a"]


@pytest.mark.parametrize("seat", SILENT_SEATS)
def test_a_cli_that_named_no_chain_records_no_chain_at_all(
    session_dir: Path, tmp_path: Path, seat: Any
) -> None:
    """
    Given a CLI that printed no chain identity
    When the turn is recorded
    Then the reply carries no chain key, rather than a null one -- the absence
         is the record that there is no conversation to point at -- and nothing
         is copied, because there is no chain to copy.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")

    driver = taken(log, seat(tmp_path / "store"))

    assert CHAIN_KEY not in replies(log)[-1]
    assert driver.copying is None


def test_a_turn_over_the_hosted_transport_names_no_chain(session_dir: Path) -> None:
    """
    Given the seat that holds no conversation open between turns
    When it takes a turn
    Then its reply carries no chain, because there is none to carry.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")

    FastDriver(TierConfig(), ScriptedFast()).run(log, record_dispatch(log))

    assert CHAIN_KEY not in replies(log)[-1]


# --- where each CLI keeps a transcript ----------------------------------------


def test_the_claude_store_looks_under_the_directory_the_process_stands_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a session directory reached through a symbolic link
    When the store is asked where that turn's transcript is
    Then it looks under the resolved directory, because that is the path the
         CLI's own process reports and encodes.
    """
    monkeypatch.setenv(CLAUDE_CONFIG_ENV, str(tmp_path / "config"))
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    found = claude_transcript(link, "chain-a")

    assert found.parent.name == str(real.resolve()).replace("/", "-")
    assert found.name == "chain-a.jsonl"
    assert found.parent.parent == tmp_path / "config" / "projects"


def test_the_claude_store_is_the_home_config_directory_when_none_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given no config directory in the environment
    When the store is asked
    Then it names the CLI's default, which is `.claude` under the home directory.
    """
    monkeypatch.delenv(CLAUDE_CONFIG_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert claude_transcript(tmp_path, "chain-a").parent.parent == tmp_path / ".claude" / "projects"


def test_the_codex_store_is_the_rollout_whose_name_carries_the_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a store holding two rollouts written on one day
    When it is asked for one thread
    Then the file named for that thread is what comes back -- the date and the
         timestamp in the name are the CLI's own clock and are matched rather
         than computed.
    """
    monkeypatch.setenv(CODEX_HOME_ENV, str(tmp_path))
    day = tmp_path / "sessions" / "2026" / "09" / "07"
    day.mkdir(parents=True)
    mine = day / "rollout-2026-09-07T08-23-13-thread-a.jsonl"
    mine.write_text(KEPT, encoding="utf-8")
    (day / "rollout-2026-09-07T08-22-44-thread-b.jsonl").write_text(LATER, encoding="utf-8")

    assert codex_transcript(tmp_path, "thread-a") == mine


def test_the_codex_store_names_where_it_looked_when_no_rollout_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a store holding no rollout for this thread
    When it is asked for one
    Then what comes back names the thread and where it was looked for, so the
         line the copy writes says something a reader can act on.
    """
    monkeypatch.setenv(CODEX_HOME_ENV, str(tmp_path))

    missing = codex_transcript(tmp_path, "thread-a")

    assert not missing.exists()
    assert "thread-a" in missing.name
    assert str(tmp_path / "sessions") in str(missing)


def test_the_codex_store_is_the_home_codex_directory_when_none_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given no Codex home in the environment
    When the store is asked
    Then it names the CLI's default, which is `.codex` under the home directory.
    """
    monkeypatch.delenv(CODEX_HOME_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert str(codex_transcript(tmp_path, "thread-a")).startswith(str(tmp_path / ".codex"))


# --- the copy in the session directory ----------------------------------------


def test_a_heavy_turns_transcript_lands_in_the_session_directory(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given an expert turn on a chain whose transcript the CLI kept
    When the turn is over
    Then the session directory holds that transcript under the chain's own name.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "chain-a")

    taken(log, heavy(ChainingCli(chains=("chain-a",)), root))

    assert copied(session_dir, "chain-a").read_text(encoding="utf-8") == KEPT


def test_a_codex_turns_rollout_lands_in_the_session_directory(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a Codex turn on a thread whose rollout the CLI kept
    When the turn is over
    Then the session directory holds that rollout under the thread's own name.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "thread-a")

    taken(log, codex(ThreadingCli(chains=("thread-a",)), root))

    assert copied(session_dir, "thread-a").read_text(encoding="utf-8") == KEPT


def test_a_later_turn_on_one_chain_replaces_the_copy_whole(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a chain whose transcript grew between two turns
    When the second turn is over
    Then the copy is the whole of the grown transcript, not the first turn's
         and not the two run together.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "chain-a")
    driver = taken(log, heavy(ChainingCli(chains=("chain-a",)), root))
    assert copied(session_dir, "chain-a").read_text(encoding="utf-8") == KEPT

    kept(root, "chain-a", KEPT + LATER)
    human_turn(log, "And what about compaction?")
    taken(log, driver)

    assert copied(session_dir, "chain-a").read_text(encoding="utf-8") == KEPT + LATER


# --- off the wait, and never a failure ----------------------------------------


def test_the_reply_is_on_the_log_before_the_copy_finishes(
    session_dir: Path, tmp_path: Path
) -> None:
    """
    Given a store that will not answer until it is let go
    When the turn is taken
    Then the reply is already on the log and the turn has returned, with the
         copy still to come -- the human waits on the answer and not on the
         bookkeeping.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "chain-a")
    gate = threading.Event()

    def slow(_directory: Path, chain: str, /) -> Path:
        assert gate.wait(TIMEOUT)
        return root / f"{chain}.jsonl"

    driver = HeavyDriver(TierConfig(), ChainingCli(chains=("chain-a",)), transcript=slow)
    driver.run(log, record_dispatch(log))

    assert replies(log)[-1][CHAIN_KEY] == "chain-a"
    assert not copied(session_dir, "chain-a").exists()
    assert driver.copying is not None
    assert driver.copying.is_alive()

    gate.set()
    driver.copying.join(TIMEOUT)
    assert copied(session_dir, "chain-a").read_text(encoding="utf-8") == KEPT


def test_the_copy_runs_on_a_thread_a_shutdown_waits_for(session_dir: Path, tmp_path: Path) -> None:
    """
    Given a turn taken on a daemon thread, which is the only kind a turn is ever
          taken on: the lane schedules every one of them that way
    When the thread taking the copy is inspected
    Then it is not a daemon, so a backend stopped in the seconds after a turn
         finishes the copy rather than being killed holding it.

    Taken on a daemon thread deliberately. A new thread inherits its creator's
    flag, so a copy started from the main thread is not a daemon whatever the
    driver does, and the guarantee would read as kept on the one path it is
    never exercised on.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "chain-a")
    driver = heavy(ChainingCli(chains=("chain-a",)), root)
    dispatch = record_dispatch(log)

    taking = threading.Thread(target=lambda: driver.run(log, dispatch), daemon=True)
    taking.start()
    taking.join(TIMEOUT)

    assert driver.copying is not None
    assert driver.copying.daemon is False
    driver.copying.join(TIMEOUT)


def test_a_transcript_that_is_not_there_costs_a_line_and_not_the_turn(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a store the CLI has already pruned this chain out of
    When the turn is taken
    Then the reply is on the log, nothing was raised, and one line on stderr
         names the chain and the path that was looked at.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"

    taken(log, heavy(ChainingCli(chains=("chain-a",)), root))

    assert replies(log)[-1][CHAIN_KEY] == "chain-a"
    said = capsys.readouterr().err.strip().splitlines()
    assert len(said) == 1
    assert "chain-a" in said[0]
    assert str(root / "chain-a.jsonl") in said[0]


def test_a_store_that_raises_costs_a_line_and_not_the_turn(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a store that raises rather than answering
    When the turn is taken
    Then the reply is on the log, nothing was raised out of the turn, and one
         line on stderr names the chain.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")

    def refuses(_directory: Path, _chain: str, /) -> Path:
        raise OSError(UNREADABLE)

    driver = HeavyDriver(TierConfig(), ChainingCli(chains=("chain-a",)), transcript=refuses)
    driver.run(log, record_dispatch(log))
    assert driver.copying is not None
    driver.copying.join(TIMEOUT)

    assert replies(log)[-1][CHAIN_KEY] == "chain-a"
    said = capsys.readouterr().err.strip().splitlines()
    assert len(said) == 1
    assert "chain-a" in said[0]
    assert UNREADABLE in said[0]
    # There is no path to name when the store never answered with one, so the
    # line says as much rather than naming something this did not look at.
    assert "nowhere" in said[0]


def test_a_destination_that_will_not_take_a_write_costs_the_turn_nothing(
    session_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a session directory where the copies cannot be put
    When the turn is taken
    Then the reply is on the log, nothing was raised, and the failure is one
         line on stderr.
    """
    log = briefed(session_dir)
    human_turn(log, "The log is the recovery source.")
    root = tmp_path / "store"
    kept(root, "chain-a")
    (session_dir / TRANSCRIPT_DIR).write_text("not a directory", encoding="utf-8")

    taken(log, heavy(ChainingCli(chains=("chain-a",)), root))

    assert replies(log)[-1][CHAIN_KEY] == "chain-a"
    said = capsys.readouterr().err.strip().splitlines()
    assert len(said) == 1
    assert "chain-a" in said[0]
    assert str(root / "chain-a.jsonl") in said[0]


def test_a_copy_that_failed_leaves_no_half_file_for_a_reader_to_find(
    session_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a transcript that reads, and a rename that will not go through
    When the copy gives up at the moment of publication
    Then the session directory holds neither a partial copy under the chain's
         name nor the scratch file the bytes went to: they are written under a
         name nothing can predict and renamed into place, so a reader sees a
         whole transcript or none.

    The failure is put at the rename because that is the only place the claim
    can be observed. A copy that fell over before it had bytes proves nothing
    about the discipline: one writing straight to the final path fails there
    too, just as cleanly, and leaves the same nothing behind.
    """
    root = tmp_path / "store"
    kept(root, "chain-a")

    def refuses(_self: Path, _target: Any) -> Path:
        raise OSError(UNREADABLE)

    monkeypatch.setattr(Path, "replace", refuses)
    copy_transcript(session_dir, "chain-a", store(root))

    assert not copied(session_dir, "chain-a").exists()
    assert list((session_dir / TRANSCRIPT_DIR).iterdir()) == []
    assert "chain-a" in capsys.readouterr().err
