"""What goes waiting, which seat weighs it, and what that seat is told.

A marked option is not the only thing that puts a decision in question. The
human's own words on an answer -- a note on an option, or an answer written
instead of one -- are judged before anything they open is offered, so each
decision such an answer opens waits on an impact task like a marked one does.

Every impact task is weighed by the expert at the task effort the configuration
resolves, never at the effort a transferred channel's expert turn runs at. And
every brief that weighs the board against a settlement opens a paragraph headed
`Backpressure:`, which is the marker the dispatch record carries for a reader to
check.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from conftest import TIMEOUT, ScriptedCli, SpyDriver, replies, run_turns

from grillui.drivers import HeavyDriver
from grillui.lane import Lane
from grillui.projector import replay
from grillui.schemas import (
    EFFORT_KEY,
    HEAVY_TIER,
    MAP_CHANNEL,
    STATUS_KIND,
    DispatchContext,
    EventSubmission,
    LogEntry,
)
from grillui.tiers import (
    HEAVY_EFFORT_ENV,
    TASK_EFFORT_ENV,
    TierConfig,
    UnknownEffortError,
    compose,
)

if TYPE_CHECKING:
    from pathlib import Path

    from grillui.log import SessionLog

MARKS_D4 = {"id": "b", "text": "Shard it", "puts_in_question": ["d4"]}
PLAIN = [{"id": "a", "text": "Keep one store"}, {"id": "c", "text": "No"}]

NOTE = "only for the audit trail, and only until the migration lands"

# The marker every brief that weighs the board opens a paragraph with.
BACKPRESSURE = "Backpressure:"


def _seed(log: SessionLog) -> None:
    """d1 is the decision answered. d2 rests on d1 alone and d6 is fogged until
    d1 settles, so an answer to d1 opens both; d3 also rests on d5, which nobody
    answers, so it stays shut. d1's option b marks d4."""
    nodes: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = [
        ("d1", [*PLAIN, MARKS_D4], {}),
        ("d2", PLAIN, {"prereqs": ["d1"]}),
        ("d3", PLAIN, {"prereqs": ["d1", "d5"]}),
        ("d4", PLAIN, {}),
        ("d5", PLAIN, {}),
        ("d6", PLAIN, {"fogUntil": "d1"}),
    ]
    for node, options, extra in nodes:
        receipt = log.submit(
            [
                EventSubmission(
                    kind="add-node",
                    actor="grill-master",
                    idempotency_key=f"seed-{node}",
                    payload={
                        "target": node,
                        "short": node,
                        "title": f"Which {node}?",
                        "body": "Decide.",
                        "prereqs": [],
                        "options": options,
                        **extra,
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def _answer(option: str | None = "a", text: str | None = None) -> EventSubmission:
    return EventSubmission(
        kind="answer",
        actor="human",
        idempotency_key=f"answer-d1-{option}-{text}",
        payload={"target": "d1", "answer": {"option": option, "text": text}},
    )


def _announcements(entries: list[LogEntry]) -> list[LogEntry]:
    """Every map turn the lane opened, hand-ups included."""
    return [
        one
        for one in entries
        if one.kind == STATUS_KIND
        and one.channel == MAP_CHANNEL
        and one.payload.get("phase") == "composing"
    ]


def _targets(announcement: LogEntry) -> list[str]:
    return [item["target"] for item in announcement.payload.get("tasks") or []]


def _waiting(log: SessionLog) -> list[str]:
    return [one.id for one in replay(log.epoch, log.entries()).decisions if one.waiting]


def _held(log: SessionLog, *answers: EventSubmission) -> tuple[SpyDriver, SpyDriver]:
    """Take answers on a lane whose first rung and expert are both held open."""
    fast, expert = SpyDriver(hold=True), SpyDriver(tier=HEAVY_TIER, hold=True)
    Lane(log, fast, expert).accept(list(answers), log.epoch)
    return fast, expert


def _release(*seats: SpyDriver) -> None:
    for seat in seats:
        seat.release.set()
    for seat in seats:
        if seat.started.is_set():
            assert seat.finished.wait(TIMEOUT)


# --- what goes waiting -----------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [_answer("a", NOTE), _answer(None, NOTE)],
    ids=["note-on-an-unmarked-option", "free-text"],
)
def test_pnd_a2_an_answer_in_the_humans_own_words_records_a_task_on_each_decision_it_opens(
    log: SessionLog, answer: EventSubmission
) -> None:
    """
    Given d2 resting on d1 alone, d6 fogged until d1 settles, and d3 resting on
         d1 and on an unanswered d5
    When the human answers d1 with a note on an unmarked option, or in their
         own words with no option
    Then one map turn opens on the expert, carrying one impact task on d2 and
         one on d6 and none on d3; d2 and d6 wait; and the first rung is never
         handed the turn.
    """
    _seed(log)
    fast, expert = _held(log, answer)
    try:
        assert expert.started.wait(TIMEOUT)
        announced = _announcements(log.entries())
        assert [one.payload["tier"] for one in announced] == [HEAVY_TIER]
        assert _targets(announced[0]) == ["d2", "d6"]
        assert _waiting(log) == ["d2", "d6"]
        assert not fast.started.is_set()
    finally:
        _release(fast, expert)


def test_pnd_a2_the_same_answer_with_no_note_and_an_unmarked_option_records_no_task(
    log: SessionLog,
) -> None:
    """
    Given the same board
    When the human takes d1's unmarked option with no note
    Then the map turn opens on the first rung carrying no task, nothing waits,
         and d2 and d6 join the frontier at once.
    """
    _seed(log)
    fast, expert = _held(log, _answer("a"))
    try:
        assert fast.started.wait(TIMEOUT)
        announced = _announcements(log.entries())
        assert [one.payload["tier"] for one in announced] == ["fast"]
        assert "tasks" not in announced[0].payload
        assert _waiting(log) == []
        frontier = replay(log.epoch, log.entries()).frontier
        assert {"d2", "d6"} <= set(frontier)
    finally:
        _release(fast, expert)


def test_pnd_a2_a_marked_answer_with_a_note_composes_one_expert_turn_listing_every_target(
    log: SessionLog,
) -> None:
    """
    Given d1's option b marking d4, and d2 and d6 that answering d1 opens
    When the human takes option b with a note
    Then exactly one map turn opens, on the expert, and its one status entry
         lists one task per target -- the marked d4 and the opened d2 and d6;
         the expert is handed the turn once and the first rung never.
    """
    _seed(log)
    fast, expert = SpyDriver(), SpyDriver(tier=HEAVY_TIER)
    lane = Lane(log, fast, expert)

    run_turns(lane, _answer("b", NOTE))

    announced = _announcements(log.entries())
    assert len(announced) == 1, [one.payload for one in announced]
    assert announced[0].payload["tier"] == HEAVY_TIER
    assert _targets(announced[0]) == ["d4", "d2", "d6"]
    assert len(expert.dispatches) == 1
    assert fast.dispatches == []


# --- which effort weighs it ------------------------------------------------


def _effort_of_reply(log: SessionLog) -> Any:
    """The effort the one agent reply on the log is attributed to."""
    (reply,) = replies(log)
    return reply.get(EFFORT_KEY)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "medium"),
        ({HEAVY_EFFORT_ENV: "max"}, "medium"),
        ({HEAVY_EFFORT_ENV: "medium", TASK_EFFORT_ENV: "low"}, "low"),
    ],
    ids=["unset", "heavy-effort-set", "task-effort-set"],
)
def test_pnd_a2_a_task_turn_runs_at_the_task_effort_and_never_at_the_heavy_effort(
    log: SessionLog, environ: dict[str, str], expected: str
) -> None:
    """
    Given an expert seat configured from the environment
    When a marked answer sends it an impact task
    Then the turn is asked for at the task effort -- medium where nothing sets
         one, whatever the heavy effort is set to -- and its attribution
         records that effort.
    """
    _seed(log)
    cli = ScriptedCli()
    lane = Lane(log, SpyDriver(), HeavyDriver(TierConfig.from_env(environ), cli))

    run_turns(lane, _answer("b"))

    assert len(cli.calls) == 1
    argv = cli.calls[0]
    assert argv[argv.index("--effort") + 1] == expected
    assert _effort_of_reply(log) == expected


def test_pnd_a2_an_expert_turn_carrying_no_task_keeps_the_heavy_effort(log: SessionLog) -> None:
    """
    Given an expert seat whose heavy effort is set
    When the expert takes the map doctor's turn, which carries no task
    Then that turn runs and is attributed at the heavy effort, not the task
         effort.
    """
    _seed(log)
    cli = ScriptedCli()
    lane = Lane(log, SpyDriver(), HeavyDriver(TierConfig.from_env({HEAVY_EFFORT_ENV: "max"}), cli))

    doctor = lane.call_doctor()
    assert doctor is not None
    doctor.join(TIMEOUT)

    argv = cli.calls[0]
    assert argv[argv.index("--effort") + 1] == "max"
    assert _effort_of_reply(log) == "max"


def test_pnd_a2_the_task_effort_defaults_to_medium_and_an_unknown_one_is_refused() -> None:
    """
    Given no task-effort setting, a valid one, and a misspelt one
    Then the first resolves to medium, the second to itself, and the third is
         refused at configuration time rather than at the first task.
    """
    assert TierConfig.from_env({}).task_effort == "medium"
    assert TierConfig.from_env({TASK_EFFORT_ENV: "high"}).task_effort == "high"
    with pytest.raises(UnknownEffortError, match=TASK_EFFORT_ENV):
        TierConfig.from_env({TASK_EFFORT_ENV: "hihg"})


# --- what a brief that weighs the board is told ------------------------------


def _paragraphs(dispatch: Path) -> list[str]:
    """The composed brief for one recorded dispatch, split into paragraphs."""
    recorded = dispatch.read_text(encoding="utf-8")
    context = DispatchContext.model_validate_json(recorded)
    return compose(recorded, context, []).split("\n\n")


def _backpressure_in(dispatch: Path) -> tuple[Any, list[str]]:
    """The dispatch record's backpressure, and every brief paragraph opening on
    the marker."""
    recorded = json.loads(dispatch.read_text(encoding="utf-8"))
    return recorded.get("backpressure"), [
        one for one in _paragraphs(dispatch) if one.startswith(BACKPRESSURE)
    ]


@pytest.mark.parametrize(
    "answer",
    [_answer("b"), _answer("a", NOTE)],
    ids=["marked", "note"],
)
def test_pnd_a11_an_impact_task_dispatch_carries_a_backpressure_paragraph(
    log: SessionLog, answer: EventSubmission
) -> None:
    """
    Given an answer that starts impact tasks
    When the expert is dispatched to weigh them
    Then the dispatch record carries a paragraph opening `Backpressure:`, and
         the brief composed from it carries that paragraph once.
    """
    _seed(log)
    expert = SpyDriver(tier=HEAVY_TIER)
    run_turns(Lane(log, SpyDriver(), expert), answer)

    recorded, paragraphs = _backpressure_in(expert.dispatches[0])
    assert isinstance(recorded, str)
    assert recorded.startswith(BACKPRESSURE)
    assert paragraphs == [recorded]


def test_pnd_a11_the_doctor_dispatch_carries_a_backpressure_paragraph(log: SessionLog) -> None:
    """
    Given a board
    When the human calls the map doctor
    Then its dispatch record and its brief carry the `Backpressure:` paragraph.
    """
    _seed(log)
    expert = SpyDriver(tier=HEAVY_TIER)
    doctor = Lane(log, SpyDriver(), expert).call_doctor()
    assert doctor is not None
    doctor.join(TIMEOUT)

    recorded, paragraphs = _backpressure_in(expert.dispatches[0])
    assert isinstance(recorded, str)
    assert recorded.startswith(BACKPRESSURE)
    assert paragraphs == [recorded]


def test_pnd_a11_a_clerical_dispatch_carries_no_backpressure(log: SessionLog) -> None:
    """
    Given a board
    When the human takes an unmarked option with no note, which weighs nothing
         against a settlement
    Then neither its dispatch record nor its brief carries the marker.
    """
    _seed(log)
    fast = SpyDriver()
    run_turns(Lane(log, fast, SpyDriver(tier=HEAVY_TIER)), _answer("a"))

    recorded, paragraphs = _backpressure_in(fast.dispatches[0])
    assert recorded is None
    assert paragraphs == []
    assert BACKPRESSURE not in fast.dispatches[0].read_text(encoding="utf-8")


def test_a_brief_names_the_decisions_the_humans_own_words_opened_apart_from_the_marked_ones(
    log: SessionLog,
) -> None:
    """
    Given an answer taking d1's option b, which marks d4, with a note that opens
         d2 and d6
    When the expert is dispatched to weigh them
    Then its brief says the option names d4 alone and that the human's own
         words opened d2 and d6, which no option marked.
    """
    _seed(log)
    expert = SpyDriver(tier=HEAVY_TIER)
    run_turns(Lane(log, SpyDriver(), expert), _answer("b", NOTE))

    brief = "\n\n".join(_paragraphs(expert.dispatches[0]))
    assert "That option names d4, and the board is still offering it." in brief
    assert "Their own words open d2, d6, which no option marked" in brief
