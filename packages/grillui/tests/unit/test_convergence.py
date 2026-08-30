"""The converged answer: a thread agent's offer, and the answer that takes it.

Three claims are pinned here.

**An offer rides the turn that made it.** The proposal is read off the board the
backend projects rather than off the submission, because what the human is shown
is the projection and an offer that validated on the way in and vanished on the
way out is the failure this cannot afford to miss. Which offer is live is
position -- the thread's most recent turn -- so the liveness assertions are on
where the proposal sits in `turns`, never on a flag.

**An unusable offer is dropped and never refused.** Every drop case asserts two
things together: the prose is on the board, and the proposal is not. Asserting
only the second would pass against a backend that rejected the write and threw
away what the agent said to the human.

**Taking an offer is one entry.** The settle-and-close claims are made against
the log's own length, because "in one entry" is a statement about the log and a
board that looks right after two writes is exactly the state this refuses.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from conftest import event, post

from grillui.capture import capture
from grillui.dispatch import GRILL_MASTER, THREAD_AGENT, assemble
from grillui.drivers import declared_updates, record_reply
from grillui.log import LOG_FILE
from grillui.projector import fold
from grillui.schemas import (
    FAST_TIER,
    HEAVY_TIER,
    REASON_FOREIGN_THREAD,
    REASON_UNKNOWN_THREAD,
    DispatchContext,
)
from grillui.tiers import system_prompt

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from grillui.log import SessionLog

# ── the fixture, from a real session ──
#
# Session `spec-ia-226` -- "Spec information architecture: acceptance criteria as
# the spine" -- ran ten decisions and five side threads, and four of those threads
# converged on an answer their human then recorded. The four are here because they
# are the four shapes GUI-A66 names, and the answers are that session's verbatim:
# a fixture whose answers were written for this test would be four cases of
# whatever shape the test wanted to pass.
D2 = "d2"
D4 = "d4"
D7 = "d7"
D10 = "d10"

DECISIONS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    D2: (
        "What replaces the template's user-stories section?",
        [
            ("a", "Replace it with an identified requirements section: stable-ID statements."),
            ("b", "Drop the layer entirely. Every stated intent becomes a criterion directly."),
            ("c", "Keep user stories but give them stable IDs and drop the mandated list."),
        ],
    ),
    D4: (
        "How far does 'no untraceable code' reach, and what enforces it?",
        [
            ("a", "Trace code through tests: every criterion names its tests."),
            ("b", "Annotate at file or module level: each source unit declares its criteria."),
            ("c", "Enforce one direction only: flag criteria that no test reaches."),
        ],
    ),
    D7: (
        "What happens when a preservation requirement has no existing test?",
        [
            ("a", "Record the gap as tracked work against the prior artifact, and proceed."),
            ("b", "Block: a preservation requirement with no test is fixed upstream first."),
            ("c", "Block only on a designated critical path; record and proceed elsewhere."),
        ],
    ),
    D10: (
        "What replaces the 400-line split tripwire?",
        [
            ("a", "Split the rule in two and change the unit: slice count stays a hard rule."),
            ("b", "Keep a hard numeric tripwire but retune it against the corpus."),
            ("c", "Replace size with rigor tiers keyed to coordination complexity."),
        ],
    ),
}


class Shape:
    """One converged thread of the fixture session: what the thread was about,
    and the proposal its convergence is expressible as."""

    def __init__(
        self, name: str, thread: str, decision: str, option: str | None, text: str, because: str
    ) -> None:
        self.name = name
        self.thread = thread
        self.decision = decision
        self.option = option
        self.text = text
        self.because = because

    @property
    def proposal(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "option": self.option,
            "text": self.text,
            "because": self.because,
        }

    @property
    def answer(self) -> dict[str, Any]:
        return {"option": self.option, "text": self.text}


FOUR_SHAPES = [
    Shape(
        "an existing option, qualified to narrow what it means",
        "t-d7-13-ybbx",
        D7,
        "a",
        "Option (a) applies with a caveat: the discovered work in this case is not "
        "necessarily to cure missing ACs, only missing regression tests.  So the new "
        "work is not tasked with closing test coverage gaps for legacy code, but the "
        "newly filed work is tasked with closing that gap.",
        "The thread narrowed what the recorded gap covers.",
    ),
    Shape(
        "an existing option, qualified to add work downstream",
        "t-d2-1-9zy6",
        D2,
        "a",
        "let's also create a work item in an appropriate work track and priority to do "
        'some experiments to compare "identified requirements" against "identified '
        'requirements specified in user story format" to compare downstream impact.',
        "You accepted the option and asked for an experiment beside it.",
    ),
    Shape(
        "an answer naming its option only in its prose",
        "t-d10-22-yn9v",
        D10,
        None,
        "Split the rule in two: slice count stays a hard decomposition rule, while "
        "document size becomes a token-measured warning enforced at a 10,000-token "
        "threshold that blocks downstream work without an explicit human override. "
        "Coherence decides whether multiple outcomes require splitting, but exceeding "
        "10,000 tokens acts as a hard size gate regardless.",
        "You restated the split in your own terms and pinned the threshold.",
    ),
    Shape(
        "an answer standing on no option at all",
        "t-d4-7-5l29",
        D4,
        None,
        "We need the ability to trace both ways - from the AC to the code and from code "
        "to AC.  I think we can do this with a code comment convention (I don't want to "
        "embed it in the test name itself since a test might trace back to more than one "
        "AC.)  While this has a downside of refactoring drift, I'm willing to accept "
        "that drift risk for now, and we can come back to it later if/when it creates a "
        "problem.",
        "You asked for both directions, which none of the three options gives.",
    ),
]

# A fixture of four clean option swaps: what GUI-A66 says must fail the check.
FOUR_CLEAN_SWAPS = [
    Shape(shape.name, shape.thread, shape.decision, "a", "", shape.because) for shape in FOUR_SHAPES
]

SAID = "Then the qualification is what the answer has to carry, not the option alone."
BECAUSE = "You stated the qualification yourself."


def clean_option_swap(answer: dict[str, Any]) -> bool:
    """An answer that records an option and no text of its own."""
    return bool(answer.get("option")) and not (answer.get("text") or "").strip()


# ── building a board with anchored threads on it ──


def add_decision(client: TestClient, epoch: str, node: str) -> None:
    title, options = DECISIONS[node]
    receipt = post(
        client,
        epoch,
        event(
            "add-node",
            key=f"add-{node}",
            target=node,
            short=node,
            title=title,
            body=title,
            prereqs=[],
            options=[{"id": one, "text": text} for one, text in options],
        ),
    )[0]
    assert receipt["status"] == "accepted"


def open_thread(client: TestClient, epoch: str, thread: str, decision: str | None) -> None:
    receipt = post(
        client,
        epoch,
        event(
            "thread-created",
            actor="human",
            channel=thread,
            key=f"open-{thread}",
            decision=decision,
            kind="user",
            title=f"{decision or 'session'} — the human opened it",
            requires_action=False,
            turns=[{"who": "human", "text": SAID}],
        ),
    )[0]
    assert receipt["status"] == "accepted"


def offer(
    client: TestClient,
    epoch: str,
    thread: str,
    text: str,
    proposal: dict[str, Any] | None,
    *,
    actor: str = "thread-agent",
    key: str | None = None,
) -> dict[str, Any]:
    """One agent turn on a thread, with or without an offer riding it."""
    payload: dict[str, Any] = {"turns": [{"who": actor, "text": text}]}
    if proposal is not None:
        payload["proposed_answer"] = proposal
    return post(
        client,
        epoch,
        event(
            "thread-turn",
            actor=actor,
            channel=thread,
            key=key or f"turn-{thread}-{text[:12]}",
            **payload,
        ),
    )[0]


def answer(
    client: TestClient,
    epoch: str,
    node: str,
    given: dict[str, Any],
    *,
    from_thread: str | None = None,
    key: str = "answered",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"target": node, "answer": given}
    if from_thread is not None:
        payload["from_thread"] = from_thread
    return post(client, epoch, event("answer", actor="human", key=key, **payload))[0]


def board(client: TestClient, epoch: str) -> None:
    """The fixture session's four converged threads, each on its own decision."""
    for shape in FOUR_SHAPES:
        add_decision(client, epoch, shape.decision)
        open_thread(client, epoch, shape.thread, shape.decision)


def image1(client: TestClient) -> dict[str, Any]:
    state: dict[str, Any] = client.get("/state").json()["image1"]
    return state


def turns_of(client: TestClient, thread: str) -> list[dict[str, Any]]:
    threads = image1(client)["threads"]
    found = [one for one in threads if one["id"] == thread]
    assert found, f"no thread {thread!r} on the board"
    turns: list[dict[str, Any]] = found[0]["turns"]
    return turns


def decision_of(client: TestClient, node: str) -> dict[str, Any]:
    found = [one for one in image1(client)["decisions"] if one["id"] == node]
    assert found, f"no decision {node!r} on the board"
    return found[0]


def thread_of(client: TestClient, thread: str) -> dict[str, Any]:
    found = [one for one in image1(client)["threads"] if one["id"] == thread]
    assert found, f"no thread {thread!r} on the board"
    return found[0]


def seq(client: TestClient) -> int:
    position: int = client.get("/status").json()["seq"]
    return position


@pytest.fixture
def epoch(client: TestClient) -> str:
    current: str = client.get("/status").json()["epoch"]
    return current


# ---------------------------------------------------------------- GUI-A65


def test_a_proposal_riding_a_turn_records_the_prose_and_projects_onto_that_turn(
    client: TestClient, epoch: str
) -> None:
    """
    Given a decision-anchored thread whose agent has converged on its answer
    When the agent's turn carries a proposed_answer for that anchor decision
    Then the turn's prose is on the board and the proposal is projected onto
         that turn with its decision, option, text and reason.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)

    assert offer(client, epoch, shape.thread, SAID, shape.proposal)["status"] == "accepted"

    turn = turns_of(client, shape.thread)[-1]
    assert turn["text"] == SAID
    assert turn["proposal"] == shape.proposal


@pytest.mark.parametrize(
    ("case", "actor", "thread", "proposal"),
    [
        (
            "from the grill-master",
            "grill-master",
            FOUR_SHAPES[0].thread,
            FOUR_SHAPES[0].proposal,
        ),
        (
            "from a thread anchoring no decision",
            "thread-agent",
            "t-help",
            {"decision": D7, "option": "a", "text": "Take (a).", "because": BECAUSE},
        ),
        (
            "naming a decision other than the anchor",
            "thread-agent",
            FOUR_SHAPES[0].thread,
            {"decision": D2, "option": "a", "text": "Take (a).", "because": BECAUSE},
        ),
        (
            "naming an option the decision does not carry",
            "thread-agent",
            FOUR_SHAPES[0].thread,
            {"decision": D7, "option": "z", "text": "Take (z).", "because": BECAUSE},
        ),
        (
            "anchored to a decision the board never held",
            "thread-agent",
            "t-phantom",
            {"decision": "d99", "option": None, "text": "Take it.", "because": BECAUSE},
        ),
        (
            "carrying no answer text",
            "thread-agent",
            FOUR_SHAPES[0].thread,
            {"decision": D7, "option": "a", "because": BECAUSE},
        ),
    ],
)
def test_an_unusable_proposal_is_dropped_with_the_prose_still_recorded(
    client: TestClient, epoch: str, case: str, actor: str, thread: str, proposal: dict[str, Any]
) -> None:
    """
    Given a thread turn carrying a proposal this session cannot use
    When it is submitted
    Then the write is accepted, the turn's prose is on the board, and the turn
         carries no proposal.
    """
    board(client, epoch)
    open_thread(client, epoch, "t-help", None)
    open_thread(client, epoch, "t-phantom", "d99")

    receipt = offer(client, epoch, thread, SAID, proposal, actor=actor)

    assert receipt["status"] == "accepted", case
    turn = turns_of(client, thread)[-1]
    assert turn["text"] == SAID, case
    assert "proposal" not in turn, case


def test_a_dropped_proposal_appends_no_rejection(client: TestClient, epoch: str) -> None:
    """
    Given a thread turn whose proposal names a decision the thread does not anchor
    When it is submitted
    Then the log grows by exactly the turn and by no refusal beside it.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    before = seq(client)

    offer(
        client,
        epoch,
        shape.thread,
        SAID,
        {"decision": D2, "option": "a", "text": "Take (a).", "because": BECAUSE},
    )

    assert seq(client) == before + 1


# ---------------------------------------------------------------- GUI-A66


def test_each_convergence_of_the_fixture_session_is_one_proposal_recording_what_it_carried(
    client: TestClient, epoch: str
) -> None:
    """
    Given the four converged threads of a real session
    When each convergence is offered as one proposal and the human takes it
    Then the decision records exactly the option and text the proposal carried.
    """
    board(client, epoch)

    for shape in FOUR_SHAPES:
        assert offer(client, epoch, shape.thread, SAID, shape.proposal)["status"] == "accepted"
        taken = answer(
            client,
            epoch,
            shape.decision,
            shape.answer,
            from_thread=shape.thread,
            key=f"take-{shape.decision}",
        )
        assert taken["status"] == "accepted", shape.name
        recorded = decision_of(client, shape.decision)["answer"]
        assert recorded == shape.answer, shape.name


def test_the_fixtures_four_shapes_are_the_four_that_occur() -> None:
    """
    Given the fixture's four converged threads
    When their recorded answers are read for shape
    Then two carry both an option and text, two carry text alone with a null
         option, and none of the four is a clean option swap.
    """
    with_option = [shape for shape in FOUR_SHAPES if shape.option is not None]
    without = [shape for shape in FOUR_SHAPES if shape.option is None]

    assert len(with_option) == 2
    assert len(without) == 2
    assert all(shape.answer["text"] for shape in FOUR_SHAPES)
    assert [shape for shape in FOUR_SHAPES if clean_option_swap(shape.answer)] == []


def test_a_fixture_of_four_clean_option_swaps_fails_the_shape_check() -> None:
    """
    Given a fixture whose four cases are all clean option swaps
    When it is read for shape
    Then every case is a clean option swap, which is what the check refuses.
    """
    assert all(clean_option_swap(shape.answer) for shape in FOUR_CLEAN_SWAPS)


# ---------------------------------------------------------------- GUI-A69


def test_a_live_proposal_queues_nothing_and_holds_nothing(client: TestClient, epoch: str) -> None:
    """
    Given a live proposal on a decision-anchored thread
    When the board is read
    Then the pending queue is empty, the anchor decision is on the frontier, and
         it can still be answered with an option the proposal never named.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)

    board_now = image1(client)
    assert board_now["pending"] == []
    assert shape.decision in board_now["frontier"]

    unrelated = answer(client, epoch, shape.decision, {"option": "c", "text": ""})

    assert unrelated["status"] == "accepted"
    assert decision_of(client, shape.decision)["answer"]["option"] == "c"


def test_a_live_proposal_reaches_no_grill_master_dispatch_as_a_pending_update(
    client: TestClient, epoch: str, log: SessionLog
) -> None:
    """
    Given a live proposal on a decision-anchored thread
    When the grill-master's dispatch context is composed
    Then it carries no pending update.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)

    context = DispatchContext.model_validate_json(assemble(fold(epoch, log.entries())))

    assert context.agent == GRILL_MASTER
    assert context.image2.pending == []


def test_a_later_proposal_retires_the_earlier_by_position_and_nothing_declines_it(
    client: TestClient, epoch: str
) -> None:
    """
    Given a thread carrying two agent turns, each proposing
    When the thread is read
    Then both proposals are projected, the live one is the last turn's, and the
         log carries no entry declining the earlier.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    first = {**shape.proposal, "text": "Take (a) as written.", "because": BECAUSE}
    offer(client, epoch, shape.thread, "First reading.", first, key="turn-first")
    before = seq(client)
    offer(client, epoch, shape.thread, "Second reading.", shape.proposal, key="turn-second")

    turns = turns_of(client, shape.thread)

    assert [turn.get("proposal") for turn in turns] == [None, first, shape.proposal]
    assert turns[-1]["proposal"] == shape.proposal
    assert seq(client) == before + 1


def test_an_offer_rides_the_last_turn_of_the_entry_that_made_it(
    client: TestClient, epoch: str
) -> None:
    """
    Given one thread event saying two things and offering an answer
    When the thread is read
    Then the offer is on the second of them, which is the thread's most recent
         turn and so the one the offer is live on.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)

    receipt = post(
        client,
        epoch,
        event(
            "thread-turn",
            actor="thread-agent",
            channel=shape.thread,
            key="turn-of-two",
            turns=[
                {"who": "thread-agent", "text": "First, the constraint you named."},
                {"who": "thread-agent", "text": SAID},
            ],
            proposed_answer=shape.proposal,
        ),
    )[0]

    assert receipt["status"] == "accepted"
    turns = turns_of(client, shape.thread)
    assert [turn["text"] for turn in turns[-2:]] == ["First, the constraint you named.", SAID]
    assert "proposal" not in turns[-2]
    assert turns[-1]["proposal"] == shape.proposal


def test_a_human_turn_retires_the_proposal_it_follows(client: TestClient, epoch: str) -> None:
    """
    Given a thread whose agent proposed and whose human then spoke
    When the thread is read
    Then the most recent turn is the human's and carries no proposal, while the
         agent's earlier turn still carries the one it made.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)
    offer(client, epoch, shape.thread, "Not quite.", None, actor="human", key="turn-human")

    turns = turns_of(client, shape.thread)

    assert turns[-1]["who"] == "human"
    assert "proposal" not in turns[-1]
    assert turns[-2]["proposal"] == shape.proposal


# ---------------------------------------------------------------- GUI-D33 / GUI-A68


def test_an_answer_carrying_from_thread_settles_and_closes_in_one_entry(
    client: TestClient, epoch: str
) -> None:
    """
    Given a live proposal on a decision-anchored thread
    When the human answers that decision with from_thread naming the thread
    Then the log grows by exactly one entry, the decision is settled and the
         thread is closed.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)
    before = seq(client)

    taken = answer(client, epoch, shape.decision, shape.answer, from_thread=shape.thread)

    assert taken["status"] == "accepted"
    assert seq(client) == before + 1
    assert decision_of(client, shape.decision)["status"] == "settled"
    assert thread_of(client, shape.thread)["state"] == "closed"


def test_the_terminal_result_names_the_applied_text_as_the_threads_conclusion(
    client: TestClient, epoch: str, log: SessionLog
) -> None:
    """
    Given a decision answered from its thread
    When the session's terminal result is captured from the directory alone
    Then that thread is closed and its conclusion is the answer text applied.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)
    answer(client, epoch, shape.decision, shape.answer, from_thread=shape.thread)

    result = capture(log.directory)

    closed = [one for one in result.threads if one.id == shape.thread]
    assert [one.state for one in closed] == ["closed"]
    assert closed[0].conclusion == shape.text


def test_a_thread_closed_by_a_gesture_still_concludes_nothing(
    client: TestClient, epoch: str, log: SessionLog
) -> None:
    """
    Given a thread the human closed with the ordinary close gesture
    When the terminal result is captured
    Then the thread is a closed line item whose conclusion is null.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)
    post(
        client,
        epoch,
        event("thread-close", actor="human", channel=shape.thread, key="close-it"),
    )

    result = capture(log.directory)

    closed = [one for one in result.threads if one.id == shape.thread]
    assert [one.conclusion for one in closed] == [None]


def test_an_already_settled_decision_is_re_answered_by_the_same_path(
    client: TestClient, epoch: str
) -> None:
    """
    Given a decision already settled and its thread reopened by a human turn
    When a proposal on that thread is taken
    Then the decision records the new answer and the thread closes again.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    answer(client, epoch, shape.decision, {"option": "b", "text": ""}, key="first-answer")
    offer(client, epoch, shape.thread, SAID, shape.proposal)

    taken = answer(client, epoch, shape.decision, shape.answer, from_thread=shape.thread)

    assert taken["status"] == "accepted"
    assert decision_of(client, shape.decision)["answer"] == shape.answer
    assert thread_of(client, shape.thread)["state"] == "closed"


@pytest.mark.parametrize(
    ("case", "thread", "reason"),
    [
        ("no thread of that id", "t-nobody", REASON_UNKNOWN_THREAD),
        ("a thread anchored elsewhere", FOUR_SHAPES[1].thread, REASON_FOREIGN_THREAD),
    ],
)
def test_an_answer_naming_an_unusable_thread_is_refused_and_appends_nothing(
    client: TestClient, epoch: str, case: str, thread: str, reason: str
) -> None:
    """
    Given an answer whose from_thread names no thread, or one anchored to
         another decision
    When it is submitted
    Then it is rejected with that reason and the log grows by nothing.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    before = seq(client)

    refused = answer(client, epoch, shape.decision, shape.answer, from_thread=thread)

    assert refused["status"] == "rejected", case
    assert refused["reason"] == reason, case
    assert seq(client) == before


def test_an_answer_without_from_thread_closes_nothing(client: TestClient, epoch: str) -> None:
    """
    Given a live proposal on a decision-anchored thread
    When the human answers the decision without naming the thread
    Then the decision settles and the thread stays open.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)
    offer(client, epoch, shape.thread, SAID, shape.proposal)

    answer(client, epoch, shape.decision, shape.answer)

    assert decision_of(client, shape.decision)["status"] == "settled"
    assert thread_of(client, shape.thread)["state"] == "open"


# ---------------------------------------------------------------- GUI-D31: the map document


@pytest.mark.parametrize(
    ("case", "document", "expected"),
    [
        (
            "a proposal alone is a declaring reply",
            {"text": SAID, "proposed_answer": {"decision": D7, "option": "a", "text": "x"}},
            {"decision": D7, "option": "a", "text": "x"},
        ),
        (
            "a proposal beside updates",
            {"text": SAID, "updates": [], "proposed_answer": {"decision": D7}},
            {"decision": D7},
        ),
        ("prose alone declares nothing", {"text": SAID}, None),
        ("a proposal that is not an object", {"text": SAID, "proposed_answer": "yes"}, None),
    ],
)
def test_a_reply_document_carrying_a_proposal_is_read_as_prose_and_an_offer(
    case: str, document: dict[str, Any], expected: dict[str, Any] | None
) -> None:
    """
    Given a map document carrying a proposed_answer beside its prose
    When the driver reads what the turn declared
    Then the prose is the document's text rather than its raw bytes, and the
         proposal is carried out beside the updates.
    """
    prose, _, _, proposal = declared_updates(json.dumps(document))

    if expected is None and "proposed_answer" not in document:
        assert prose == json.dumps(document), case
    assert proposal == expected, case


def test_a_driver_puts_the_offer_on_the_turns_own_entry(
    client: TestClient, epoch: str, log: SessionLog
) -> None:
    """
    Given a thread agent replying with a proposal beside its prose
    When the driver records the reply
    Then the log entry is that turn and carries the proposal as a payload key.
    """
    shape = FOUR_SHAPES[0]
    board(client, epoch)

    record_reply(
        log,
        FAST_TIER,
        shape.thread,
        json.dumps({"text": SAID, "proposed_answer": shape.proposal}),
        {"tier": FAST_TIER},
    )

    written = json.loads((log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert written["kind"] == "thread-turn"
    assert written["payload"]["text"] == SAID
    assert written["payload"]["proposed_answer"] == shape.proposal
    assert turns_of(client, shape.thread)[-1]["proposal"] == shape.proposal


# ---------------------------------------------------------------- GUI-A70


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_prompt_of_both_tiers_states_when_and_how_to_offer(tier: str) -> None:
    """
    Given the thread-agent system prompt a driver composes for each tier
    When it is read for what it says about offering an answer
    Then it states the convergence condition, that restating what the human
         already said is the whole of the licence, and that the offer is never
         put to the human as a question.
    """
    prompt = system_prompt(tier, THREAD_AGENT)

    assert "proposed_answer" in prompt
    assert "the human's own turns already carry the answer" in prompt
    assert "Restating what they said is the whole of the licence" in prompt
    assert "Composing an answer they have not endorsed is you deciding" in prompt
    assert "Never ask whether to write one" in prompt
    assert "One proposal per turn" in prompt
    assert "an option the decision already carries, or none" in prompt


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_masters_prompt_carries_no_offer_rule(tier: str) -> None:
    """
    Given the map-channel system prompt a driver composes for each tier
    When it is read for the offer rule
    Then it carries none: the grill-master asserts answers through the queue.
    """
    assert "proposed_answer" not in system_prompt(tier, GRILL_MASTER)
