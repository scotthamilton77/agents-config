"""The grill-master's reply document, and the ruling as a first-class answer.

Two failures meet here and they are the same failure seen twice.

**A turn that said the right thing and moved nothing.** A reply naming three
decisions as dead, in prose, leaves all three on the frontier for the human to
answer -- the board never heard it. So there is no prose mode on the map
channel: every turn is a document of one shape, and a document that does not
validate is refused, retried once on the same seat, handed up once, and finally
recorded as a failure rather than shown to the human as the bytes it arrived in.

**A turn with more than one legal move.** Three rulings discharge an
obligation, not one. `invalidate` where the gesture leaves a decision no
question to ask, `revise` where it changes what it asks, `stands` where it
survives intact — and `stands` is a credited answer rather than a silence,
credited by its `why`, which the driver puts on the decision itself. A
vocabulary of one verdict presses the agent to kill work that stands.

The two are checked here together because the second is measured off the first:
coverage is read from the document's own `rulings`, so a ruling exists where it
was made rather than being inferred from what happened to be queued.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from conftest import (
    _ABSENT,
    ScriptedCli,
    ScriptedFast,
    dispatch_context,
    document,
    replies,
    run_turns,
)

from grillui.dispatch import DISPATCH_DIR, GRILL_MASTER, THREAD_AGENT, record_dispatch
from grillui.drivers import (
    FastDriver,
    HeavyDriver,
    ReplyRefusedError,
    record_reply,
    request_body,
)
from grillui.lane import DocumentRefusedError, Lane
from grillui.projector import fold
from grillui.schemas import (
    FAST_TIER,
    HEAVY_TIER,
    RULING_STANDS,
    RULINGS_KEY,
    STATUS_PHASE_ERROR,
    STOP_KEY,
    VERDICT_KEY,
    DispatchContext,
    EventSubmission,
    MootnessObligation,
    Option,
)
from grillui.tiers import (
    DOCUMENT_FORMAT_RULE,
    MOOTNESS_OBLIGATION_RULE,
    MOOTNESS_RESTING_RULE,
    TierConfig,
    compose,
    system_prompt,
)

if TYPE_CHECKING:
    from grillui.log import SessionLog

KILLED = ["d2", "d3"]
KILLING_OPTION = {"id": "b", "text": "Close it unactioned", "puts_in_question": KILLED}


# --- the board these turns are taken on --------------------------------------


def seed(log: SessionLog) -> None:
    """A board whose first decision offers an option naming the other two.

    Seeded through the appender rather than through the lane, so nothing here
    schedules a turn of its own: what these tests are about is the one turn the
    human's gesture buys.
    """
    for node, options in (
        ("d1", [{"id": "a", "text": "Build the export"}, KILLING_OPTION]),
        ("d2", [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]),
        ("d3", [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]),
    ):
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
                    },
                )
            ],
            log.epoch,
        )[0]
        assert receipt.status == "accepted"


def answer(lane: Lane, option: str = "b") -> None:
    """The human answering the first decision, and the turn it buys, run out.

    Which option they take decides which seat composes the turn, so it is the
    fixture choice every check here turns on. `b` carries the pre-mark, which
    classes the gesture as judgment and seats it on the expert directly
    (GUI-D48); `a` carries none and stays on the first rung. A check about the
    first rung's own ladder takes `a`, or there is no first-rung turn in it to
    be about.
    """
    run_turns(
        lane,
        EventSubmission(
            kind="answer",
            actor="human",
            idempotency_key="human-answer",
            payload={"target": "d1", "answer": {"option": option}},
        ),
    )


def seat(*said: str, tier: str = FAST_TIER) -> FastDriver:
    """One seat scripted to answer in order, on whichever rung it is put."""
    return FastDriver(TierConfig(), ScriptedFast(replies=said), tier=tier)


def obligations(log: SessionLog) -> list[MootnessObligation | None]:
    """The mootness obligation on each dispatch recorded so far, in order."""
    return [
        DispatchContext.model_validate_json(path.read_text(encoding="utf-8")).mootness
        for path in sorted((log.directory / DISPATCH_DIR).glob("*.json"))
    ]


def notices(log: SessionLog) -> list[str]:
    """What the backend said to the human in its own voice."""
    return [
        str(entry.payload.get("text"))
        for entry in log.entries()
        if entry.kind == "informational" and entry.actor == "backend"
    ]


def spoken(log: SessionLog) -> list[str]:
    """Every notice the grill-master itself put in front of the human, from the
    turns it took alone and from the folds alike."""
    said: list[str] = []
    for entry in log.entries():
        if entry.actor != "grill-master":
            continue
        for update in entry.payload.get("updates", [{**entry.payload, "kind": entry.kind}]):
            if isinstance(update, dict) and update.get("kind") == "informational":
                said.append(str(update.get("text")))
    return said


def errors(log: SessionLog) -> list[str]:
    return [
        str(entry.payload.get("detail"))
        for entry in log.entries()
        if entry.kind == "status" and entry.payload.get("phase") == STATUS_PHASE_ERROR
    ]


def ruling(
    decision: str, verdict: str = "stands", why: str = "it survives the answer"
) -> dict[str, str]:
    return {"decision": decision, "ruling": verdict, "why": why}


def killing(decision: str) -> dict[str, Any]:
    return {"kind": "invalidate", "target": decision, "why": "the answer subsumes it"}


# --- GMR-A2: the document validates, or nothing is recorded from it ----------


@pytest.mark.parametrize(
    ("said", "fault"),
    [
        pytest.param("d2 and d3 are dead now.", "prose", id="prose"),
        pytest.param(document(text=_ABSENT), "text", id="no-text"),
        pytest.param(document(rulings=_ABSENT), "rulings", id="no-rulings"),
        pytest.param(
            document(rulings=[ruling("d2", verdict="moot")]), "ruling", id="unknown-ruling"
        ),
        pytest.param(document(verdict="stands"), "verdict", id="unknown-key"),
    ],
)
def test_a_reply_that_is_not_the_document_is_refused_and_never_reaches_the_human(
    log: SessionLog, said: str, fault: str
) -> None:
    """
    Given a seat whose every reply is one of the ways a document can be wrong --
          prose, a missing `text`, a missing `rulings`, a ruling outside the
          three kinds, a key the shape does not carry
    When the map turn is taken
    Then the lane's error phase names the tier and the fault, and nothing the
         seat said reached the log as a notice.

    The refusal is the whole point: a reply the board cannot read must not be
    shown to the human as if the agent had spoken, and it must not be recorded
    as a turn that happened. Both halves are asserted, because either one alone
    would pass a driver that swallowed the reply silently.
    """
    only = seat(said, said, said, said)
    seed(log)

    answer(Lane(log, only))

    assert len(errors(log)) == 1, errors(log)
    assert FAST_TIER in errors(log)[0]
    assert fault in errors(log)[0]
    assert spoken(log) == []


ADRIFT = document(text="", supersedes=["p1"])


def test_a_withdrawal_with_nothing_to_ride_on_is_refused_and_retried_then_handed_up(
    log: SessionLog,
) -> None:
    """
    Given a first-rung seat withdrawing a pending item in a document that says
          nothing else, and an expert that answers properly
    When a clerical map turn is taken
    Then the first rung is asked twice with the fault quoted, the expert is
         handed the turn once, and the expert's document is what lands.

    `supersedes` rides on the turn's own entry, so a turn carrying a withdrawal
    and nothing to record it on would lose that gesture. It is caught as a fault
    in the shape rather than at the append, because that is where the seat is
    told what was wrong and gets its one retry -- and a line of `text` is
    exactly the fix a seat can make.
    """
    first = ScriptedFast(replies=[ADRIFT])
    expert = ScriptedFast(replies=[document(text="Taking that back.", supersedes=["p1"])])
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), first),
            expert=FastDriver(TierConfig(), expert, tier=HEAVY_TIER),
        ),
        option="a",
    )

    assert len(first.calls) == 2, "the seat was not given its retry"
    assert "supersedes" in first.calls[1]["prompt"]
    assert len(expert.calls) == 1
    assert spoken(log) == ["Taking that back."]
    assert errors(log) == []


def test_a_withdrawal_with_nothing_to_ride_on_ends_the_ladder_on_the_expert_seat(
    log: SessionLog,
) -> None:
    """
    Given a channel whose only seat is the expert one, withdrawing in a document
          that says nothing else
    When the map turn is taken
    Then the seat is asked twice, one backend notice reports the failure, and
         nothing the seat said reached the human.

    The ladder's terminal state, not the generic error phase: there is no rung
    above the expert, so the failure is recorded rather than handed anywhere.
    """
    only = ScriptedFast(replies=[ADRIFT])
    seed(log)

    answer(Lane(log, FastDriver(TierConfig(), only, tier=HEAVY_TIER)))

    assert len(only.calls) == 2
    said = notices(log)
    assert len(said) == 1, said
    assert HEAVY_TIER in said[0]
    assert spoken(log) == []
    assert HEAVY_TIER in errors(log)[0]


def test_recording_a_withdrawal_with_nothing_to_ride_on_refuses_rather_than_drops_it(
    log: SessionLog,
) -> None:
    """
    Given a caller recording that document directly, past the validator
    When it is recorded
    Then it raises rather than appending nothing.

    The validator catches this on every driver path, so this is the guard behind
    it: the failure it prevents is silent, and a withdrawal that vanished with
    no entry and no error is the one outcome nobody could notice.
    """
    seed(log)

    with pytest.raises(ReplyRefusedError):
        record_reply(log, FAST_TIER, "map", ADRIFT, {})


def test_the_heavy_seat_validates_what_comes_back_as_the_fast_one_does(log: SessionLog) -> None:
    """
    Given the CLI seat replying in prose on the map channel
    When a map turn is taken
    Then the turn is refused rather than recorded.

    A seat's transport asks the provider for the shape where it can; every
    driver validates what comes back regardless of what it asked for, so the
    contract does not rest on the request.
    """
    seed(log)

    with pytest.raises(DocumentRefusedError):
        HeavyDriver(TierConfig(), ScriptedCli(reply="Both are dead.")).run(
            log, record_dispatch(log)
        )

    assert spoken(log) == []


def test_a_refused_document_is_retried_once_on_the_same_seat_with_the_refusal_quoted(
    log: SessionLog,
) -> None:
    """
    Given a seat whose first reply is prose and whose second is a document
    When the map turn is taken
    Then the seat was asked twice, the second ask quoted the refusal, and the
         document it then returned is the turn.

    One retry, on the same seat: a model that lost the shape usually finds it
    again when told what was wrong, and paying an expert turn for a formatting
    slip is spending the human's waiting clock on nothing.
    """
    transport = ScriptedFast(replies=["Both are dead.", document(text="Both are dead.")])
    seed(log)

    answer(Lane(log, FastDriver(TierConfig(), transport)))

    assert len(transport.calls) == 2, "the seat was not asked again"
    assert "text" in transport.calls[1]["prompt"]
    assert transport.calls[1]["prompt"].startswith(transport.calls[0]["prompt"])
    assert spoken(log) == ["Both are dead."]
    assert errors(log) == []


def test_a_first_rung_seat_that_will_not_validate_hands_the_turn_to_the_expert_once(
    log: SessionLog,
) -> None:
    """
    Given a first-rung seat that never returns a document and an expert seat
          that does
    When a clerical map turn is taken
    Then the first rung was asked twice, the expert once, and the expert's
         document is the turn.
    """
    first = ScriptedFast(replies=["Both are dead."])
    expert = ScriptedFast(replies=[document(text="d2 and d3 both stand.")])
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), first),
            expert=FastDriver(TierConfig(), expert, tier=HEAVY_TIER),
        ),
        option="a",
    )

    assert len(first.calls) == 2
    assert len(expert.calls) == 1
    assert spoken(log) == ["d2 and d3 both stand."]
    assert errors(log) == []


def test_the_expert_seat_has_no_rung_above_it_and_the_failure_is_recorded(
    log: SessionLog,
) -> None:
    """
    Given both seats replying in prose
    When a clerical map turn is taken
    Then the first rung was asked twice and the expert twice, exactly one
         backend notice names the failure and the tier that could not be handed
         anywhere, and nothing the seats said reached the human.

    From the expert seat there is no rung above it, so the ladder ends: the
    failure is recorded rather than handed on, and the human is told a turn was
    lost rather than left watching a board that never moved.
    """
    first = ScriptedFast(replies=["Both are dead."])
    expert = ScriptedFast(replies=["Yes, dead."])
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), first),
            expert=FastDriver(TierConfig(), expert, tier=HEAVY_TIER),
        ),
        option="a",
    )

    assert (len(first.calls), len(expert.calls)) == (2, 2)
    said = notices(log)
    assert len(said) == 1, said
    assert HEAVY_TIER in said[0]
    assert spoken(log) == []
    assert HEAVY_TIER in errors(log)[0]


# --- GMR-A3: the obligation names the ids and states the three rulings -------


@pytest.mark.parametrize("cause", ["answer", "invalidate"])
def test_a_dispatch_carrying_an_obligation_names_the_ids_and_states_the_three_rulings(
    cause: str,
) -> None:
    """
    Given a dispatch carrying each of the two obligations there are
    When each prompt is composed
    Then each names its ids, quotes the gesture, and states all three rulings.

    The list is what the standing rule is not: a paragraph an agent has to
    recognise its own turn in, against a list it cannot read past. Both lists
    take the same three rulings -- a decision may die with the gesture, change
    under it, or survive it -- and a vocabulary of one verdict is what presses
    an agent to kill work that stands.
    """
    prompt = compose(
        "{}",
        dispatch_context().model_copy(
            update={
                "mootness": MootnessObligation(
                    target="d1", answer="Close it unactioned", ids=KILLED, cause=cause
                )
            }
        ),
        [],
    )

    assert "d2, d3" in prompt
    assert "Close it unactioned" in prompt
    for verdict in ("invalidate", "revise", "stands"):
        assert f"`{verdict}`" in prompt, f"{verdict} is not stated as a way out"


def test_the_two_obligation_rules_each_state_all_three_rulings() -> None:
    """The rules themselves, so a dispatch that stopped naming one is caught
    where the sentence is written rather than only where it is composed."""
    for rule in (MOOTNESS_OBLIGATION_RULE, MOOTNESS_RESTING_RULE):
        for verdict in ("invalidate", "revise", "stands"):
            assert f"`{verdict}`" in rule, f"{verdict} is not stated as a way out"


def test_ruling_stands_on_every_named_id_presses_nobody_and_renders_on_each_decision(
    log: SessionLog,
) -> None:
    """
    Given the seat the gesture's class names, ruling `stands` with a why on each
          named decision
    When the human takes the option naming them
    Then no second turn is taken, no notice is raised, one informational carries
         each why on its own decision, and both are still on the frontier.

    `stands` is a credited answer rather than a silence. What the board does
    with it is show it, on the decision it rules on, so a human reading that
    decision reads the argument for its survival.

    The seat under test is the expert one because the gesture is a judgment
    class: an answer whose option carries a live mark is composed there
    directly, and the first rung is here only to be shown untouched.
    """
    ruled = ScriptedFast(
        replies=[
            document(
                text="Both survive it.",
                rulings=[
                    ruling("d2", why="the answer fixes the contract, not what ships it"),
                    ruling("d3", why="retention is orthogonal to the export"),
                ],
            )
        ]
    )
    untouched = ScriptedFast()
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), untouched),
            expert=FastDriver(TierConfig(), ruled, tier=HEAVY_TIER),
        )
    )

    assert untouched.calls == [], "a judgment gesture was round-tripped through the first rung"
    assert len(ruled.calls) == 1, "a turn that ruled on both was followed by a second"
    assert notices(log) == []
    board = fold(log.epoch, log.entries())
    targeted = {
        item.target: item for item in board.pending if item.kind == "informational" and item.target
    }
    assert sorted(targeted) == KILLED
    assert "the answer fixes the contract, not what ships it" in "\n".join(spoken(log))
    assert "retention is orthogonal to the export" in "\n".join(spoken(log))
    assert set(KILLED) <= set(board.frontier), "a why on a decision took it off the frontier"
    assert [one[RULINGS_KEY] for one in replies(log)] == [
        [
            ruling("d2", why="the answer fixes the contract, not what ships it"),
            ruling("d3", why="retention is orthogonal to the export"),
        ]
    ]


def test_a_reply_ruling_on_one_of_two_says_so_once_and_names_only_the_other(
    log: SessionLog,
) -> None:
    """
    Given the seat the gesture's class names, ruling on only one of the two
          decisions the option named
    When the human takes that option
    Then no second turn is taken and exactly one backend notice reports the
         other decision, and only it, as not ruled on.

    Said once, because a second turn per gesture would spend an expert turn on
    every gesture for the rest of the session; and naming only what is left,
    because reporting a decision the same turn ruled on sends the human to argue
    about a verdict that was made.

    There is no rung above the seat this gesture is classed onto, so the ladder
    is terminal here rather than one that hands anything up (GUI-D45).
    """
    unused = ScriptedFast()
    ruled = ScriptedFast(
        replies=[document(text="d2 survives.", rulings=[ruling("d2", why="a different question")])]
    )
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), unused),
            expert=FastDriver(TierConfig(), ruled, tier=HEAVY_TIER),
        )
    )

    assert unused.calls == [], "a judgment gesture was round-tripped through the first rung"
    assert len(ruled.calls) == 1, "the classed seat was asked twice for one gesture"
    handed = obligations(log)[-1]
    assert handed is not None
    assert handed.ids == KILLED
    said = notices(log)
    assert len(said) == 1, said
    assert "not ruled on" in said[0]
    assert "d3" in said[0]
    assert "d2" not in said[0], "a decision the turn ruled on was reported as unruled"


@pytest.mark.parametrize(
    "said",
    [
        pytest.param(document(text="Noted."), id="a-notice-and-no-ruling"),
        pytest.param(document(text=""), id="an-empty-document"),
    ],
)
def test_the_expert_seat_raises_the_unmet_notice_directly(log: SessionLog, said: str) -> None:
    """
    Given a channel whose only seat is the expert one, replying with a document
          that rules on nothing -- once with a notice in it, once wholly empty
    When the human takes the option naming two decisions
    Then no second turn is taken and one notice names both as not ruled on.

    Coverage ends where validity does: a seat with no rung above it raises the
    notice rather than pressing itself. The empty document is the same case and
    not a failure -- every field of it is one §8.10 permits to be empty, so what
    it needs is the coverage answer rather than a transport error.
    """
    only = ScriptedFast(replies=[said])
    seed(log)

    answer(Lane(log, FastDriver(TierConfig(), only, tier=HEAVY_TIER)))

    assert len(only.calls) == 1
    assert errors(log) == []
    raised = notices(log)
    assert len(raised) == 1, raised
    assert "d2, d3" in raised[0]
    assert "not ruled on" in raised[0]


def test_an_empty_document_credits_nothing_an_earlier_turn_ruled(
    log: SessionLog,
) -> None:
    """
    Given the seat the gesture's class names, answering with a wholly empty
          document, and an earlier map turn that ruled `stands` on both
    When the human takes the option naming them
    Then one notice names both decisions as not ruled on, and no lane error is
         raised.

    The empty document is valid and therefore walks the coverage ladder, not the
    refusal one. It appends no entry at all, which is why coverage is read from
    the window this turn opened: a backward scan over the whole log would find
    whatever spoke last on the map and credit this turn with its rulings --
    discharging an obligation nobody answered, and saying nothing to the human
    about two decisions the board is still offering.
    """
    unused = ScriptedFast()
    empty = ScriptedFast(replies=[document(text="")])
    seed(log)
    # An earlier map turn that did rule on both. The empty turn appends nothing,
    # so a coverage check reading the log whole would find this entry and credit
    # the empty turn with its verdicts -- discharging an obligation nobody
    # answered. It is here to make that failure visible rather than latent.
    log.submit(
        [
            EventSubmission(
                kind="informational",
                actor="grill-master",
                idempotency_key="an-earlier-turn",
                payload={"text": "Both hold.", RULINGS_KEY: [ruling(one) for one in KILLED]},
            )
        ],
        log.epoch,
    )

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), unused),
            expert=FastDriver(TierConfig(), empty, tier=HEAVY_TIER),
        )
    )

    assert unused.calls == [], "a judgment gesture was round-tripped through the first rung"
    handed = obligations(log)[-1]
    assert handed is not None
    assert handed.ids == KILLED
    said = notices(log)
    assert len(said) == 1, said
    assert "d2, d3" in said[0], "the empty turn was credited with an earlier turn's rulings"
    assert errors(log) == []


# --- GMR-A4: a ruling is credited by what the same document carries ----------


@pytest.mark.parametrize("verdict", ["invalidate", "revise"])
def test_a_ruling_whose_document_carries_no_matching_update_is_not_credited(
    log: SessionLog, verdict: str
) -> None:
    """
    Given the seat the gesture's class names, ruling `invalidate` -- or
          `revise` -- on both named decisions while its document queues neither
          update
    When the human takes the option naming them
    Then both are reported to the human as unruled.

    Naming a decision changes nothing. A verdict that says a decision is dead
    and does not queue its death is the failure this whole slice is about, and
    crediting it on the word alone would put the check back where it started.
    """
    unused = ScriptedFast()
    said_only = ScriptedFast(
        replies=[document(text="Both are dead.", rulings=[ruling(one, verdict) for one in KILLED])]
    )
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), unused),
            expert=FastDriver(TierConfig(), said_only, tier=HEAVY_TIER),
        )
    )

    assert unused.calls == [], "a judgment gesture was round-tripped through the first rung"
    said = notices(log)
    assert len(said) == 1, said
    assert "d2, d3" in said[0], "the uncredited ruling was taken as a ruling"


def test_a_ruling_carrying_its_update_is_credited_and_the_change_waits_for_the_human(
    log: SessionLog,
) -> None:
    """
    Given the seat the gesture's class names, ruling `invalidate` on one named
          decision with the update to match, and `stands` on the other
    When the human takes the option naming both
    Then no second turn is taken, nothing is said to the human, the invalidate
         waits in their queue and the standing decision is on the frontier under
         a why of its own.
    """
    credited = ScriptedFast(
        replies=[
            document(
                text="One dies, one stands.",
                updates=[killing("d2")],
                rulings=[
                    ruling("d2", "invalidate", "subsumed by the export"),
                    ruling("d3", why="retention is untouched"),
                ],
            )
        ]
    )
    unused = ScriptedFast()
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), unused),
            expert=FastDriver(TierConfig(), credited, tier=HEAVY_TIER),
        )
    )

    assert unused.calls == [], "a judgment gesture was round-tripped through the first rung"
    assert len(credited.calls) == 1, "the classed seat was asked twice for one gesture"
    assert notices(log) == []
    board = fold(log.epoch, log.entries())
    assert [one.target for one in board.pending if one.kind == "invalidate"] == ["d2"]
    assert "d3" in board.frontier


def test_a_ruling_may_name_a_decision_the_dispatch_did_not(log: SessionLog) -> None:
    """
    Given a seat ruling on both named decisions and on a third the dispatch
          never mentioned
    When the human takes the option naming two
    Then the turn discharges, and the third decision's why is on it too.

    The check is coverage and not correctness: every id the dispatch named must
    be ruled, and a turn that saw further than the pre-marks did is not wrong
    for saying so.
    """
    only = ScriptedFast(
        replies=[
            document(
                text="All three move.",
                rulings=[ruling(one) for one in (*KILLED, "d1")],
            )
        ]
    )
    seed(log)

    answer(Lane(log, FastDriver(TierConfig(), only)))

    assert notices(log) == []
    board = fold(log.epoch, log.entries())
    assert {one.target for one in board.pending if one.kind == "informational" and one.target} == {
        "d1",
        "d2",
        "d3",
    }


# --- what the human is told, and what the shape is stated to be --------------


def test_a_turn_that_judges_the_stop_condition_met_says_so_to_the_human(
    log: SessionLog,
) -> None:
    """
    Given a seat whose document reports the stop condition met
    When the map turn is taken
    Then the reason reaches the human as a notice on the board's own lane, and
         the turn's entry carries the judgement.

    Saying so is as far as an agent goes: ending the session stays the human's
    gesture, and the notice is what they act on.
    """
    only = ScriptedFast(
        replies=[
            document(
                text="Nothing is left open.",
                stop={"met": True, "why": "every decision is settled or parked"},
            )
        ]
    )
    seed(log)

    answer(Lane(log, FastDriver(TierConfig(), only)))

    assert "every decision is settled or parked" in "\n".join(spoken(log))
    assert [one[STOP_KEY] for one in replies(log)] == [
        {"met": True, "why": "every decision is settled or parked"}
    ]


def test_the_document_rule_states_the_shape_the_turn_must_take() -> None:
    """
    Given the rule the grill-master is briefed with
    When it is read
    Then it names every key of the document and says that sending an update is
         not making the change.
    """
    for key in ("text", "updates", "supersedes", "rulings", "stop"):
        assert f"`{key}`" in DOCUMENT_FORMAT_RULE, f"{key} is not stated"
    assert "Sending an update is not making the change" in DOCUMENT_FORMAT_RULE


def test_the_fast_transport_asks_the_provider_for_the_shape_on_a_map_turn(
    log: SessionLog,
) -> None:
    """
    Given a map turn and a thread turn on the same seat
    When each request is made
    Then only the map turn asks for the document by schema, and the schema it
         sends names every key of it.

    Asking is not trusting -- the driver validates what comes back either way --
    but a provider that can be told the shape answers in it far more often, and
    a retry costs the human a second of waiting clock.
    """
    transport = ScriptedFast()
    seed(log)
    receipt = log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="human",
                channel="t-1",
                idempotency_key="open-thread",
                payload={"decision": "d2", "title": "Retention", "turns": [{"text": "Why?"}]},
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted"
    driver = FastDriver(TierConfig(), transport)

    driver.run(log, record_dispatch(log))
    driver.run(log, record_dispatch(log, channel="t-1"))

    assert [call["shaped"] for call in transport.calls] == ["True", "False"]
    asked = request_body("m", "s", "p", shaped=True)["response_format"]
    assert asked["type"] == "json_schema"
    assert sorted(asked["json_schema"]["schema"]["properties"]) == [
        "rulings",
        "stop",
        "supersedes",
        "text",
        "updates",
    ]
    assert "response_format" not in request_body("m", "s", "p")


def test_the_option_shape_says_the_grill_master_rules_on_the_mark() -> None:
    """
    Given the schema's own documentation of an option
    When it is read
    Then it says the grill-master rules on `puts_in_question`.

    Three surfaces say what the field is, and a prediction described as display
    data on one of them is how the field came to be read as a hint nobody had to
    answer for.
    """
    assert "rules on" in (Option.__doc__ or "")


def test_a_turn_on_a_thread_channel_is_not_held_to_the_document(log: SessionLog) -> None:
    """
    Given a thread agent replying in prose
    When its turn is taken
    Then it is recorded as the turn it is.

    The document is the map's contract. A thread agent authors nothing, so
    holding its turn to a shape built for authoring would refuse the ordinary
    case.
    """
    seed(log)
    receipt = log.submit(
        [
            EventSubmission(
                kind="thread-created",
                actor="human",
                channel="t-1",
                idempotency_key="open-thread",
                payload={"decision": "d2", "title": "Retention", "turns": [{"text": "Why?"}]},
            )
        ],
        log.epoch,
    )[0]
    assert receipt.status == "accepted"

    FastDriver(TierConfig(), ScriptedFast(reply="Because the log is append-only.")).run(
        log, record_dispatch(log, channel="t-1")
    )

    assert [
        entry.payload["text"]
        for entry in log.entries()
        if entry.kind == "thread-turn" and entry.actor == "thread-agent"
    ] == ["Because the log is append-only."]


def test_the_composed_prompt_carries_the_document_rule_on_the_map_and_not_a_thread() -> None:
    """
    Given the two roles
    When each standing brief is composed
    Then only the grill-master's carries the document rule.
    """
    for tier in (FAST_TIER, HEAVY_TIER):
        assert DOCUMENT_FORMAT_RULE in system_prompt(tier, GRILL_MASTER)
        assert DOCUMENT_FORMAT_RULE not in system_prompt(tier, THREAD_AGENT)


# --- Round 2: the verdict stamp is the backend's word ------------------------


def test_a_turn_cannot_stamp_its_own_update_with_a_verdict_nobody_ruled(
    log: SessionLog,
) -> None:
    """
    Given a turn whose own update wears the verdict stamp, alongside genuine
          `stands` rulings on the decisions the gesture named
    When the human takes the option naming them
    Then the recorded entry carries that update with no stamp on it, its history
         entry carries no verdict, and the notices the rulings minted still do.

    The stamp says the backend ruled. An informational payload takes any extra
    key and the document's updates are the model's own bytes, so a turn that
    wrote the key itself would put a verdict on the record that no ruling ever
    made -- and `history` is the one surface a thread agent is told to quote
    rather than reason about. So it is stripped where the model's bytes enter an
    entry, and put back only on what the driver mints.
    """
    forged = {
        "kind": "informational",
        "target": "d2",
        "text": "the vendor replied about d2",
        "why": "forged",
        VERDICT_KEY: RULING_STANDS,
    }
    ruled = ScriptedFast(
        replies=[
            document(
                text="Both survive it.",
                updates=[forged],
                rulings=[
                    ruling("d2", why="the answer fixes the contract, not what ships it"),
                    ruling("d3", why="retention is orthogonal to the export"),
                ],
            )
        ]
    )
    seed(log)

    answer(
        Lane(
            log,
            FastDriver(TierConfig(), ScriptedFast()),
            expert=FastDriver(TierConfig(), ruled, tier=HEAVY_TIER),
        )
    )

    # What the log holds: the turn's own update, stripped of the word it had no
    # business writing, and nothing else about it changed.
    written = [
        one
        for entry in log.entries()
        for one in entry.payload.get("updates", [])
        if one.get("text") == "the vendor replied about d2"
    ]
    assert len(written) == 1, "the turn's own update did not reach the log"
    assert VERDICT_KEY not in written[0], "the stamp survived into the record"
    assert written[0]["why"] == "forged", "stripping the stamp rewrote the rest of the update"

    # And what the record says: the forged one is a message, the minted one is a
    # verdict, and the other decision's ruling is untouched by any of it.
    history = fold(log.epoch, log.entries()).history
    on_d2 = [one for one in history["d2"] if one.kind == "informational"]
    assert [one.verdict for one in on_d2] == [None, RULING_STANDS]
    assert on_d2[0].why == "forged"
    assert on_d2[1].why == "the answer fixes the contract, not what ships it"
    assert [one.verdict for one in history["d3"] if one.kind == "informational"] == [RULING_STANDS]
