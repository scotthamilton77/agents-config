"""The escalation conditions, one scripted transcript at a time.

Every transcript here is written by hand and every board is stated in the test,
so the recommendation is decided by what was said and what the board looks like
and by nothing else -- no model is reached, and the same transcript yields the
same condition every run.

The fourth case is the load-bearing one. A recommender that fired on anything
weighty-sounding would be a recommender that always fires, so a transcript
satisfying none of the three has to come back empty-handed.
"""

from __future__ import annotations

from grillui.escalation import (
    CONDITION_COMMITMENT,
    CONDITION_IRREDUCIBLE,
    CONDITION_MULTIPLE,
    INVALIDATE_KIND,
    REVISE_KIND,
    Turn,
    in_expert_mode,
    mootness_obligation,
    outstanding,
    recommend,
    transfer_source,
    turns_of,
)
from grillui.schemas import (
    MAP_CHANNEL,
    STATUS_PHASE_TRANSFERRED,
    TRANSFER_SOURCE_POLICY,
    Actor,
    Decision,
    Image2,
    LogEntry,
    MootnessObligation,
    Option,
    PendingUpdate,
    Thread,
)

TARGET = "d1"


def board(*dependents: str) -> Image2:
    """A board whose `d1` is depended on by the ids named, with two bystanders."""
    decisions = [
        Decision(id=TARGET, short="Store", title="Which storage?"),
        Decision(id="d2", short="Compaction", title="When is it compacted?"),
        Decision(id="d3", short="Retention", title="How long is it kept?"),
    ]
    for decision in decisions:
        if decision.id in dependents:
            decision.prereqs = [TARGET]
    return Image2(epoch="e1", seq=7, decisions=decisions)


def human(text: str, target: str | None = TARGET) -> list[Turn]:
    """One exchange ending on the human, which is the turn being judged."""
    return [
        Turn(who="grill-master", text="What does the store have to survive?"),
        Turn(who="human", text=text, target=target),
    ]


def entry(kind: str, actor: Actor, channel: str, **payload: object) -> LogEntry:
    return LogEntry(
        seq=1,
        epoch="e1",
        kind=kind,
        idempotency_key=f"k-{kind}-{channel}",
        timestamp="2026-08-18T09:00:00.000+00:00",
        actor=actor,
        channel=channel,
        payload=dict(payload),
    )


def test_a_commitment_asked_on_a_decision_with_two_dependents_names_that_condition() -> None:
    """
    Given a decision two other decisions depend on
    When the human asks for a commitment rather than another question
    Then the recommendation names the commitment condition and its evidence
         names the decisions that depend on it.
    """
    advice = recommend(board("d2", "d3"), human("Stop asking and just decide it."))

    assert advice is not None
    assert advice.condition == CONDITION_COMMITMENT
    assert "d2" in advice.evidence
    assert "d3" in advice.evidence


def test_a_commitment_on_a_decision_nothing_depends_on_is_not_escalated() -> None:
    """
    Given a decision no other decision depends on
    When the human asks for a commitment
    Then no recommendation is made: the weight the condition is about is the
         dependents, not the asking.
    """
    assert recommend(board(), human("Just decide it.")) is None


def test_a_rejected_reframing_names_the_irreducible_condition() -> None:
    """
    Given a human who has just refused the question as put back to them
    When the turn is judged
    Then the recommendation names the irreducible condition and quotes what
         they said.
    """
    advice = recommend(board(), human("You keep rewording it -- that is not the question."))

    assert advice is not None
    assert advice.condition == CONDITION_IRREDUCIBLE
    assert "not the question" in advice.evidence


def test_a_human_who_says_the_trade_off_is_what_they_cannot_resolve_escalates() -> None:
    """
    Given a human naming the trade-off itself as the thing they cannot settle
    When the turn is judged
    Then the irreducible condition is named.
    """
    advice = recommend(board(), human("The trade-off is what I cannot work out."))

    assert advice is not None
    assert advice.condition == CONDITION_IRREDUCIBLE


def test_a_turn_weighing_three_decisions_names_the_multiple_condition() -> None:
    """
    Given a turn that puts three of the board's decisions in play at once
    When it is judged
    Then the recommendation names the multiple-decisions condition and lists
         them.
    """
    advice = recommend(board(), human("Compaction and Retention both move if d1 moves."))

    assert advice is not None
    assert advice.condition == CONDITION_MULTIPLE
    assert all(one in advice.evidence for one in ("d1", "d2", "d3"))


def test_a_transcript_satisfying_no_condition_carries_no_recommendation() -> None:
    """
    Given an ordinary turn -- a question back, and an answer to it
    When it is judged
    Then nothing is recommended, because sharpening the question is the
         ordinary move and not an escalation.
    """
    assert recommend(board("d2", "d3"), human("It has to survive a crash mid-write.")) is None


def test_a_transcript_with_no_human_turn_recommends_nothing() -> None:
    """
    Given a channel on which only an agent has spoken
    When it is judged
    Then nothing is recommended: the conditions are about what the human said.
    """
    assert recommend(board("d2", "d3"), [Turn(who="grill-master", text="Just decide it.")]) is None


def test_the_agents_own_words_are_never_the_evidence() -> None:
    """
    Given an agent that has said the escalation words itself after the human's
          ordinary turn
    When the turn is judged
    Then nothing is recommended -- the recommendation is not the model's
         assessment of its own competence.
    """
    transcript = [
        Turn(who="human", text="It has to survive a crash mid-write.", target=TARGET),
        Turn(who="grill-master", text="I cannot resolve this; just decide it."),
    ]

    assert recommend(board("d2", "d3"), transcript) is None


def test_a_thread_turn_is_judged_against_the_threads_anchor_decision() -> None:
    """
    Given a thread anchored to a decision two others depend on
    When the human asks for a commitment inside that thread
    Then the anchor stands in for the target the turn does not name, and the
         commitment condition fires.
    """
    image = board("d2", "d3")
    image.threads.append(Thread(id="t1", decision=TARGET))
    transcript = [Turn(who="human", text="Just decide it.")]

    advice = recommend(image, transcript, "t1")

    assert advice is not None
    assert advice.condition == CONDITION_COMMITMENT


def test_the_transcript_is_read_from_the_log_channel_by_channel() -> None:
    """
    Given a log carrying an answer, an agent notice and a thread turn
    When one channel's transcript is read
    Then it holds that channel's turns in order, with the answer's target on
         the human's turn, and nothing another channel said.
    """
    entries = [
        entry("answer", "human", "map", target=TARGET, answer={"option": "a", "text": "the log"}),
        entry("informational", "grill-master", "map", text="Then compaction is next."),
        entry("thread-turn", "human", "t1", turns=[{"who": "human", "text": "not here"}]),
        entry("status", "backend", "map", phase="accepted", detail="ignored"),
    ]

    turns = turns_of(entries)

    assert [(turn.who, turn.text) for turn in turns] == [
        ("human", "the log"),
        ("grill-master", "Then compaction is next."),
    ]
    assert turns[0].target == TARGET
    assert [turn.text for turn in turns_of(entries, "t1")] == ["not here"]


def test_only_the_backends_own_transfer_entry_moves_a_channel() -> None:
    """
    Given a `transferred` status entry authored by an agent rather than by the
         backend, and the same entry authored by the backend
    When each channel's mode is read
    Then the agent's moves nothing and names no source, and the backend's moves
         the channel and names the policy.

    The appender already refuses a client that offers a `status` kind -- it is
    outside the submission registry -- so this entry cannot be built through the
    wire at all, and is constructed here directly. That is the point: the reader
    is not allowed to rest on the writer's gate. A reader keyed on the phase
    alone would start honouring agent-authored transfers the moment the registry
    changed, silently and in the direction that spends money.
    """
    claimed = entry("status", "grill-master", MAP_CHANNEL, phase=STATUS_PHASE_TRANSFERRED)
    authored = entry("status", "backend", MAP_CHANNEL, phase=STATUS_PHASE_TRANSFERRED)

    assert not in_expert_mode([claimed], MAP_CHANNEL)
    assert transfer_source([claimed], MAP_CHANNEL) is None
    assert in_expert_mode([authored], MAP_CHANNEL)
    assert transfer_source([authored], MAP_CHANNEL) == TRANSFER_SOURCE_POLICY


def test_an_option_taken_without_a_note_is_still_a_turn() -> None:
    """
    Given an answer carrying an option and no text
    When the transcript is read
    Then the turn says which option was taken, rather than saying nothing.
    """
    answered = entry("answer", "human", "map", target=TARGET, answer={"option": "b"})

    assert turns_of([answered])[0].text == "option b"


# ── What an answer's own option obliges the turn answering it ──

KILLING = Option(id="b", text="Close it unactioned", puts_in_question=["d2", "d3", "nowhere"])


def killing_board(**status: str) -> Image2:
    """The same three decisions, the first offering the option that kills."""
    image = board()
    image.decisions[0].options = [Option(id="a", text="Build it"), KILLING]
    for node, state in status.items():
        next(one for one in image.decisions if one.id == node).status = state  # type: ignore[assignment]
    return image


def answered(option: str = "b") -> list[LogEntry]:
    return [entry("answer", "human", MAP_CHANNEL, target=TARGET, answer={"option": option})]


def test_the_obligation_names_the_listed_decisions_the_board_is_still_offering() -> None:
    """
    Given an answer taking an option that names two decisions and one id that
          names nothing on the board, with one of the two already settled
    When the obligation is read
    Then it carries the one still being offered, the decision answered and the
         option's own text as the rationale to carry.

    An id resolving to no node is dropped rather than carried, per the pre-mark
    being a hint and not a reference: an invalidate on a decision nobody wrote is
    an update with no target. A decision already settled is dropped too -- the
    board has stopped offering it, so the human is not being asked anything.
    """
    obliged = mootness_obligation(killing_board(d2="settled"), answered())

    assert obliged is not None
    assert obliged.ids == ["d3"]
    assert obliged.target == TARGET
    assert obliged.answer == KILLING.text


def test_an_obligation_ends_with_the_turn_the_answer_bought() -> None:
    """
    Given the same answer, and then the agent's own reply to it
    When the obligation is read again
    Then there is none.

    The obligation is what one turn owes, not a standing property of the board.
    One that outlived its turn would re-fire on every later gesture -- a heavy
    turn and a notice per answer for the rest of the session, over a decision the
    human may have deliberately left alone.
    """
    spoken = entry("informational", "grill-master", MAP_CHANNEL, text="Both are dead.")

    assert mootness_obligation(killing_board(), answered()) is not None
    assert mootness_obligation(killing_board(), [*answered(), spoken]) is None
    assert mootness_obligation(killing_board(), answered(option="a")) is None


def test_a_decision_with_an_invalidate_already_waiting_is_not_outstanding() -> None:
    """
    Given an obligation on two decisions, one of which already has a proposed
          invalidate in the human's queue
    When what is still outstanding is read
    Then only the other one is.

    An agent's invalidate always waits for the human's gesture, so the decision
    it targets is still open while it waits. A check that read the status alone
    would press every turn that honoured the obligation, and ask the human to
    deal with the same withdrawal twice.
    """
    image = killing_board()
    image.pending = [
        PendingUpdate(id="p1", target="d2", kind="invalidate", superseded=False, authored_at=9),
        PendingUpdate(id="p2", target="d3", kind="invalidate", superseded=True, authored_at=9),
    ]

    obligation = MootnessObligation(target=TARGET, answer="x", ids=["d2", "d3"])

    assert outstanding(image, obligation) == ["d3"]


# ── What an invalidate the human applied owes what was resting on it ──


def resting_board() -> Image2:
    """`d2` and `d3` resting on a `d1` that has just left the flow."""
    image = board("d2", "d3")
    image.decisions[0].status = "invalidated"
    return image


def applied(target: str = TARGET, why: str = "the export was dropped") -> list[LogEntry]:
    """The human applying the agent's invalidate, which is how one lands."""
    return [
        entry(
            "apply",
            "human",
            MAP_CHANNEL,
            pending=["p1"],
            updates=[{"kind": INVALIDATE_KIND, "target": target, "why": why}],
        )
    ]


def test_an_applied_invalidate_obliges_the_decisions_that_were_resting_on_it() -> None:
    """
    Given two decisions listing a third among their prereqs, and the human
          applying the invalidate that took that third out of the flow
    When the obligation is read
    Then it names both, quotes the invalidation as the rationale to carry, and
         says an invalidate is what made them moot.

    A dead prereq holds nothing, so the board offers those two again -- on a
    footing that has gone. Each is either dead with its prereq or standing
    without it, and saying which is a map turn's job rather than something the
    human should have to work out from a board that silently re-opened.
    """
    obliged = mootness_obligation(resting_board(), applied())

    assert obliged is not None
    assert obliged.ids == ["d2", "d3"]
    assert obliged.target == TARGET
    assert obliged.answer == "the export was dropped"
    assert obliged.cause == INVALIDATE_KIND


def test_an_invalidate_nothing_was_resting_on_obliges_nothing() -> None:
    """
    Given the same gesture on a board where no decision lists that id as a prereq
    When the obligation is read
    Then there is none.

    The ordinary case: most invalidates strand nobody, and one that did would
    cost a heavy turn and a notice for nothing.
    """
    image = board()
    image.decisions[0].status = "invalidated"

    assert mootness_obligation(image, applied()) is None


def test_a_revise_waiting_on_a_stranded_decision_discharges_the_obligation() -> None:
    """
    Given the obligation an invalidate left on two decisions, one with a queued
          `revise` and one with a queued `invalidate`
    When what is still outstanding is read
    Then neither is -- while a `revise` leaves an answer's own obligation intact.

    A decision resting on one that died may still stand without it, so revising
    its prereqs says as much about it as invalidating it does. An answer's list
    is not the same: the human's own answer killed those questions, and a revise
    there would leave the decision on the frontier to be answered.
    """
    image = resting_board()
    image.pending = [
        PendingUpdate(id="p1", target="d2", kind=REVISE_KIND, superseded=False, authored_at=9),
        PendingUpdate(id="p2", target="d3", kind=INVALIDATE_KIND, superseded=False, authored_at=9),
    ]
    left = MootnessObligation(target=TARGET, answer="x", ids=["d2", "d3"], cause=INVALIDATE_KIND)

    assert outstanding(image, left) == []
    assert outstanding(image, MootnessObligation(target=TARGET, answer="x", ids=["d2"])) == ["d2"]


def test_an_answer_owing_nothing_does_not_swallow_the_invalidates_obligation() -> None:
    """
    Given an applied invalidate and then an answer whose option names nothing,
          with the agent yet to reply to either
    When the obligation is read
    Then the invalidate's is still there, narrowed to what the answer left
         standing -- and it is gone once the agent has spoken.

    The obligation belongs to the turn the gesture bought, and one gesture per
    turn is not how a human uses the board: reading only the latest would drop
    the obligation whenever they applied a change and then answered something.
    """
    image = resting_board()
    next(one for one in image.decisions if one.id == "d2").status = "settled"
    answered = entry("answer", "human", MAP_CHANNEL, target="d2", answer={"option": "a"})
    spoken = entry("informational", "grill-master", MAP_CHANNEL, text="Noted.")

    obliged = mootness_obligation(image, [*applied(), answered])

    assert obliged is not None
    assert obliged.ids == ["d3"]
    assert obliged.cause == INVALIDATE_KIND
    assert mootness_obligation(image, [*applied(), answered, spoken]) is None
