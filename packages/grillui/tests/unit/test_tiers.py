"""What the tiers are configured as, what they are told, and what a turn is given.

The prompt checks read the shipped strings rather than a copy of them, so a rule
deleted from a prompt is a red test rather than a documentation drift nobody
notices until a session goes wrong. The configuration checks read the defaults
the package ships and the environment a caller states, so what a run is
configured with is stated by the test rather than by whatever the machine
happened to be exporting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import dispatch_context, handoff_doc, write_handoff

from grillui.dispatch import GRILL_MASTER, THREAD_AGENT
from grillui.schemas import (
    HELP_THREAD_KIND,
    MAP_THREAD_KIND,
    Decision,
    DispatchContext,
    LogEntry,
    MootnessObligation,
    Option,
    Thread,
    ThreadConclusion,
    ThreadProjection,
)
from grillui.session import open_session
from grillui.tiers import (
    BASELINE,
    BOARD_LEGEND,
    CONCISION_RULE,
    CONTEXT_LIMITS,
    CONVERGENCE_RULE,
    DEFAULT_FAST_MODEL,
    DEFAULT_HEAVY_EFFORT,
    DEFAULT_HEAVY_MODEL,
    DIALOGUE_RULE,
    DOCUMENT_FORMAT_RULE,
    EFFORT_LEVELS,
    ESCALATION_POLICIES,
    ESCALATION_POLICY_ENV,
    FACILITATION_MANDATE,
    FAST_CONTEXT_LIMIT_ENV,
    FAST_MODEL_ENV,
    FAST_TIER,
    FAST_TIER_MANDATE,
    FIELD_MEANINGS,
    GAP_RULE,
    GRILL_MASTER_MANDATE,
    HEAVY_CONTEXT_LIMIT_ENV,
    HEAVY_EFFORT_ENV,
    HEAVY_MODEL_ENV,
    HEAVY_TIER,
    HELP_THREAD_MANDATE,
    MAP_CLOSING,
    MAP_THREAD_MANDATE,
    MOOTNESS_OBLIGATION_RULE,
    MOOTNESS_RESTING_RULE,
    NO_BRIEFING,
    NO_MANUFACTURE_RULE,
    ONE_TURN_RULE,
    OPTION_REFERENCE_RULE,
    POLICY_AUTONOMOUS,
    POLICY_GATED,
    REGISTER_RULE,
    RESHAPE_STEP,
    ROLE_PROMPTS,
    RULING_CONCISION_RULE,
    SPEECH_RULE,
    SUPERSEDE_RULE,
    SYSTEM_PROMPTS,
    THREAD_CLOSING,
    THREAD_REPLY_RULE,
    TierConfig,
    UnknownTierError,
    UnreadableLimitError,
    briefing,
    compose,
    system_prompt,
)

SOURCE = Path(__file__).resolve().parents[2] / "src" / "grillui"
STOP_WHEN = "every decision is settled or parked with a named blocker"


@pytest.fixture
def entries(session_dir: Path) -> list[LogEntry]:
    write_handoff(session_dir, handoff_doc())
    return open_session(session_dir).entries()


def test_the_default_configuration_names_a_non_claude_fast_tier_and_a_claude_heavy_tier() -> None:
    """
    Given no configuration at all
    When the tiers are asked which models they are
    Then the fast tier is a non-Claude model and the heavy tier is a Claude one.
    """
    config = TierConfig()

    assert "claude" not in config.fast_model.lower()
    assert "claude" in config.heavy_model.lower()
    assert (config.fast_model, config.heavy_model) == (DEFAULT_FAST_MODEL, DEFAULT_HEAVY_MODEL)


def test_the_default_heavy_tier_is_opus_thinking_hard() -> None:
    """
    Given no configuration at all
    When the heavy tier is asked what it is
    Then it is Opus at xhigh effort -- a transfer to the expert that answers as
         fast and as cheaply as the fast tier reads to the human as a transfer
         that never happened.
    """
    config = TierConfig()

    assert config.model_for(HEAVY_TIER) == "claude-opus-5"
    assert config.heavy_effort == "xhigh"


def test_both_model_ids_and_the_heavy_effort_come_from_the_environment() -> None:
    """
    Given an environment naming both model ids and the heavy effort
    When configuration is read from it
    Then both tiers take the stated ids, each tier answers with its own, and the
         heavy tier takes the stated effort.
    """
    config = TierConfig.from_env(
        {
            FAST_MODEL_ENV: "vendor/fast-2",
            HEAVY_MODEL_ENV: "claude-x",
            HEAVY_EFFORT_ENV: "low",
        }
    )

    assert config.model_for(FAST_TIER) == "vendor/fast-2"
    assert config.model_for(HEAVY_TIER) == "claude-x"
    assert config.heavy_effort == "low"


def test_an_effort_the_cli_does_not_accept_is_refused_at_load() -> None:
    """
    Given an environment naming an effort outside the CLI's vocabulary
    When configuration is read from it
    Then it raises, naming every level the CLI does accept.

    Falling back to the default would leave the session running at an effort
    nobody asked for, with the misconfiguration invisible until the bill.
    """
    with pytest.raises(ValueError, match="enormous") as raised:
        TierConfig.from_env({HEAVY_EFFORT_ENV: "enormous"})

    assert all(level in str(raised.value) for level in EFFORT_LEVELS)


def test_the_escalation_policy_defaults_to_gated_and_comes_from_the_environment() -> None:
    """
    Given no configuration, and then an environment naming the other policy
    When each is read
    Then an unconfigured session needs the human's gesture and a configured one
         escalates itself.

    The default is the load-bearing half. A session whose owner is still learning
    what the expert tier is worth must not have that money spent on their behalf
    by a condition they never watched fire.
    """
    assert TierConfig().escalation_policy == POLICY_GATED
    assert not TierConfig().autonomous
    assert TierConfig.from_env({ESCALATION_POLICY_ENV: POLICY_AUTONOMOUS}).autonomous
    assert not TierConfig.from_env({ESCALATION_POLICY_ENV: ""}).autonomous


def test_an_escalation_policy_outside_the_two_is_refused_at_load() -> None:
    """
    Given an environment naming a policy this configuration has never heard of
    When configuration is read from it
    Then it raises, naming both policies that do exist.

    Refused rather than defaulted for the same reason the effort is, and one
    sharper: a misspelling that fell back would silently decide who is allowed to
    spend the heavy tier's money.
    """
    with pytest.raises(ValueError, match="whenever-you-like") as raised:
        TierConfig.from_env({ESCALATION_POLICY_ENV: "whenever-you-like"})

    assert all(policy in str(raised.value) for policy in ESCALATION_POLICIES)


def test_an_unknown_tier_name_is_refused_rather_than_billed_as_heavy() -> None:
    """
    Given a tier name outside the two this configuration defines
    When a model id is asked for it
    Then the answer is a refusal naming the tier, not the heavy model.

    A silent fallback would let a caller typo attribute -- and bill -- a turn to
    the heavy model.
    """
    with pytest.raises(ValueError, match="mystery"):
        TierConfig().model_for("mystery")


def test_an_empty_setting_is_not_a_model_id() -> None:
    """
    Given an environment exporting the variables empty
    When configuration is read from it
    Then the defaults stand, rather than a session being configured to reach a
         model with no name.
    """
    config = TierConfig.from_env({FAST_MODEL_ENV: "", HEAVY_MODEL_ENV: "", HEAVY_EFFORT_ENV: ""})

    assert (config.fast_model, config.heavy_model) == (DEFAULT_FAST_MODEL, DEFAULT_HEAVY_MODEL)
    assert config.heavy_effort == DEFAULT_HEAVY_EFFORT


def test_configuration_falls_back_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given no mapping handed in
    When configuration is read
    Then the process environment is what is read, so a launched backend is
         configured by the environment it was launched in.
    """
    monkeypatch.setenv(FAST_MODEL_ENV, "vendor/from-the-process")

    assert TierConfig.from_env().fast_model == "vendor/from-the-process"


def test_no_configuration_this_package_ships_names_a_fable_model() -> None:
    """
    Given every source file the package ships
    When they are read for model ids
    Then none of them names a Fable model anywhere.
    """
    named = [
        path.name
        for path in SOURCE.glob("*.py")
        if "fable" in path.read_text(encoding="utf-8").lower()
    ]

    assert named == []


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_every_role_is_held_to_three_sentences_in_its_own_terms(tier: str, agent: str) -> None:
    """
    Given the brief composed for each role on each tier
    When it is read for how long a turn may be
    Then both are held to three sentences, and each is held to it in the terms
         of its own turn.

    The length rule survives the split; the exception does not travel with it.
    A thread agent can be asked for detail and is told so. The grill-master
    cannot -- the human has no way to ask its ruling turn for more -- so an
    exception stated to it is one it grants itself whenever it judges the turn
    to warrant it, which is every turn.
    """
    brief = system_prompt(tier, agent)

    assert "three sentences" in brief
    if agent == THREAD_AGENT:
        assert CONCISION_RULE in brief
        assert "unless the human explicitly asks for detail" in brief
        assert RULING_CONCISION_RULE not in brief
    else:
        assert RULING_CONCISION_RULE in brief
        assert CONCISION_RULE not in brief
        assert "unless the human explicitly asks for detail" not in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_neither_tiers_own_part_states_a_length_or_a_dialogue_rule(tier: str) -> None:
    """
    Given each tier's own part of the standing brief
    When it is read for how a turn is written
    Then neither the length rule nor the dialogue rule is in it: both differ by
         role, and a rule hung on the tier is inherited by whichever role runs
         there -- which is how the ruling turn came to be told to answer what
         the human just asked, on a turn where they asked nothing.
    """
    prompt = SYSTEM_PROMPTS[tier]

    assert CONCISION_RULE not in prompt
    assert RULING_CONCISION_RULE not in prompt
    assert DIALOGUE_RULE not in prompt
    assert "three sentences" not in prompt


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_every_shipped_system_prompt_carries_the_no_manufacture_rule(tier: str) -> None:
    """
    Given each tier's shipped system prompt
    When it is read
    Then it forbids asserting anything the given context does not support, and
         says what to do instead.
    """
    prompt = SYSTEM_PROMPTS[tier]

    assert NO_MANUFACTURE_RULE in prompt
    assert "say what you lack" in prompt


# The words the brief leans on, each of which the seat has to be holding the
# right meaning of before it meets the rule that uses it. This list is the
# test's own rather than the module's: read off the prompt it is checking, it
# would agree with any vocabulary the prompt happened to define, including one
# that had quietly dropped half of it.
#
# Two words that were on the board's vocabulary and are no longer in the prompt
# are absent here on purpose. "gesture" was the house word for a human action
# and is now "action". "receipt" named something the seat is never shown, so the
# one sentence that used it now states the fact instead: the turn is not told
# afterwards what landed.
VOCABULARY = (
    "map",
    "decision",
    "option",
    "prereqs",
    "puts_in_question",
    "action",
    "dispatch",
    "queue",
    "pending",
    "notice",
    "grill-master",
    "thread",
    "channel",
    "stub",
    "fold",
    "seq",
    "basis",
    "frontier",
    "rationale",
    "history",
    "briefing",
    "posture",
    "stop condition",
    "stands",
    "ruling",
)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_every_composed_brief_opens_on_the_baseline_and_then_the_role(
    tier: str, agent: str
) -> None:
    """
    Given the brief a driver composes for one role on one tier
    When it is read from its first byte
    Then it opens with the baseline -- the same baseline for both roles and both
         tiers -- and the role's own part comes next.

    Two defects meet here. A brief that opens on the role opens on a sentence
    made of words the seat has not been given, so it fills them in and reasons
    from what it filled in. And a role keyed to the tier puts the map's author
    under "stop short of deciding" on the one turn whose whole work is a ruling.
    """
    brief = system_prompt(tier, agent)

    assert brief.startswith(BASELINE)
    assert brief[len(BASELINE) :].lstrip("\n").startswith(ROLE_PROMPTS[agent])


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
@pytest.mark.parametrize("term", VOCABULARY)
def test_every_term_the_brief_uses_is_defined_before_it_is_used(
    tier: str, agent: str, term: str
) -> None:
    """
    Given each term the brief leans on, on each role and each tier
    When the rendered brief is searched for it
    Then the baseline defines it on a line of its own, and no use of it anywhere
         else in the brief comes before that line.

    The reader assumed is the weakest seated model, not the strongest. Told to
    carry the `basis` on each update, a seat that has not been told what a basis
    is does not stop and ask -- it writes something plausible into the field,
    and the backend has no way to tell that from a basis it meant.
    """
    defined = f"\n- {term}: "

    assert defined in BASELINE, f"{term} has no definition"
    used = re.compile(rf"\b{re.escape(term)}s?\b")
    first = used.search(system_prompt(tier, agent))

    assert first is not None
    assert first.start() < BASELINE.index(defined) + len(defined), f"{term} is used before defined"


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_the_baseline_says_what_the_reply_is_and_when_the_seat_is_called(
    tier: str, agent: str
) -> None:
    """
    Given the baseline every role and tier opens on
    When it is read for what the seat owes and when it is asked for it
    Then it says the reply is one document whose changes the backend applies or
         queues, and it states the true condition for being called.

    Both halves were wrong by overstatement. A baseline that introduced the role
    before saying what came back left the document shape a hundred lines away
    from the sentence that needed it. And "each time the human acts" is false for
    every seat: a thread agent is not called for the human's map answers, nor for
    another thread's turns, nor when the human declines its offer by ignoring it
    -- a path this same brief describes.
    """
    brief = system_prompt(tier, agent)

    assert "Your reply is one document" in brief
    assert "applies to the board at once or puts in the human's queue" in brief
    assert "when the human does something this discussion owes a reply to" in brief
    assert "and not otherwise" in brief
    assert "each time the human acts" not in brief
    # The opening paragraph reaches for no word the glossary owes: `channel` and
    # `thread` are both defined below it, and a term used above its own line is
    # the defect the glossary exists to end.
    opening = brief[: brief.index("These words mean one thing here")]
    for term in ("channel", "thread", "grill-master"):
        assert term not in opening, term


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_the_glossary_governs_the_board_and_not_the_plan(tier: str, agent: str) -> None:
    """
    Given the glossary's claim about where its definitions hold
    When it is read against the board and the plan in the same prompt
    Then it claims the board's keys and disclaims the plan's own vocabulary, and
         the two definitions the board falsifies are stated as the board has
         them.

    The claim that every word is used as defined "in the board you are given" is
    false twice over in the same bytes. The human's plan is free to use `pending`
    for a decision waiting on an analysis task, and the board carries notices
    whose `target` is null. A seat that finds the glossary wrong about the board
    in front of it has no way to tell which other line to trust.
    """
    brief = system_prompt(tier, agent)

    assert "the board's own keys use them as defined on this list" in brief
    assert "may use some of the same words in its own sense" in brief
    assert "in the board you are given, exactly" not in brief
    # A notice is an entry, not a message: `text` is the turn's only message.
    assert "one entry of the queue that the human reads rather than applies" in brief
    assert "It is pinned to a decision where it names one in `target`" in brief
    # The queue holds notices whether they name a decision or not, which is what
    # the notice line and the informational contract both allow.
    assert "the notices you sent, pinned to a decision or not" in brief
    assert "to nothing where it does not" in brief
    # `stands` is the verdict and nothing else. Used for a notice's placement it
    # is the same word for two things in one prompt, and the reader meets the
    # wrong one first.
    assert "stands on a" not in brief
    assert "standing on a" not in brief
    assert "stands on none" not in brief
    assert "leave out stands" not in brief
    assert "still stands" not in brief
    # `notice` also names a string inside a mandate, so the line says so rather
    # than leaving the example to contradict the glossary.
    assert "a different thing under the same spelling" in brief
    # The page prints `title` as the question and `body` beneath it.
    assert "a `title` holding the question" in brief
    assert "fogged meaning it is not a real question yet" in brief
    assert (
        "- obligation section: the section of a dispatch that names the decisions you owe" in brief
    )
    assert "a `body` stating the question more fully" in brief
    # An applied invalidation obliges rulings too, so the definition covers both.
    assert "an answer the human gave, or an invalidation they applied" in brief
    assert "the board records it on the decision as `verdict`" in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_master_brief_states_the_board_effects_the_seat_cannot_see(tier: str) -> None:
    """
    Given the grill-master brief on each tier
    When it is read for what the board does with what the turn sends
    Then a queued change locks its decision and a notice does not, a dismissal
         ends a queued change as an apply does, and an unsettle is stated with
         the stale dependents it leaves.

    Each was an over- or under-claim the seat pays for. Told that anything
    waiting blocks an answer, it withholds notices to keep decisions answerable.
    Told an unsettle only returns its own decision to the frontier, it never
    sends the `resolve-stale` the decisions above it now need, and they sit
    stale for the rest of the session.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert "until they apply it or dismiss it" in brief
    assert "A decision with a change of yours waiting on it cannot be answered" in brief
    assert "A notice pinned to a decision holds nothing up" in brief
    assert "except an `elicit-alert` with `blocking` true, which locks its decision" in brief
    assert "every decision settled on top of it goes stale, transitively" in brief
    assert "judged with a `resolve-stale`" in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_reply_contract_is_the_last_thing_each_role_reads(tier: str) -> None:
    """
    Given the brief composed for each role
    When it is read from its last byte back
    Then it ends on that role's reply contract: the document shape for the
         grill-master, the offer rule for the thread agent.

    The reply contract is the last thing read and the first thing written. Put
    ahead of the role and the rules, it is a shape the seat is given before it
    has a reason to take it, and by the time it writes it is recalling the shape
    rather than reading it.
    """
    grill_master = system_prompt(tier, GRILL_MASTER)

    assert DOCUMENT_FORMAT_RULE in grill_master
    assert grill_master.index(DOCUMENT_FORMAT_RULE) > grill_master.index(RESHAPE_STEP)
    assert grill_master.index(DOCUMENT_FORMAT_RULE) > grill_master.index(REGISTER_RULE)
    assert grill_master.endswith(SUPERSEDE_RULE)
    assert system_prompt(tier, THREAD_AGENT).endswith(CONVERGENCE_RULE)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_master_is_briefed_as_the_maps_author_on_either_tier(tier: str) -> None:
    """
    Given the grill-master's brief on each tier
    When it is read for what the turn is for
    Then it names it the author of the map, carries the reshape step, and leaves
         ending the session to the human -- identically on both tiers, because
         which model takes the turn does not change what the turn is.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert GRILL_MASTER_MANDATE in brief
    assert "You write the map, and you are the only agent that changes it" in brief
    # Four things bring this turn about, and three of them are not an answer.
    # A mandate written around the answer alone leaves the seat routing a folded
    # conclusion looking for one, and reasoning from whichever it settles on.
    assert "answers a decision, applies an invalidation, folds a thread, or asks for a" in brief
    assert "Whichever of those it was, your work is the same" in brief
    assert "The sections below say which one brought this turn about" in brief
    # Scoped to agents. The human's own answers settle decisions with no reply
    # of anyone's, and the board handed to this turn already carries them -- a
    # seat reading the clause without that scope is invited to re-record them
    # as `settle` updates.
    assert "no agent's change reaches the board except through your reply" in brief
    assert "The human changes it themselves by answering" in brief
    assert "Push the human on the axis the briefing's posture names" in brief
    assert "Ending the session is theirs, not yours" in brief
    assert RESHAPE_STEP in brief
    assert "Say whether the stop condition is met" in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_facilitates_on_either_tier_and_carries_no_line_of_the_grill_masters(
    tier: str,
) -> None:
    """
    Given the thread agent's brief on each tier
    When it is read for what the turn is for
    Then it facilitates and stops short of deciding on both tiers, and carries
         no sentence of the grill-master's -- a thread agent told it authors the
         map agrees to changes it cannot make.
    """
    brief = system_prompt(tier, THREAD_AGENT)

    assert FACILITATION_MANDATE in brief
    assert "stop short of deciding" in brief
    assert "leave the decision with the human" in brief
    assert GRILL_MASTER_MANDATE not in brief
    assert RESHAPE_STEP not in brief
    assert "the author of the map" not in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_is_told_how_to_read_a_board_that_moved(tier: str) -> None:
    """
    Given the thread agent's brief on each tier
    When it is read for what the board's own fields mean
    Then it carries the legend: a question about why the board moved is
         answered by quoting the decision's `rationale` or an entry of its
         `history`, or by saying that the record does not say, and never by
         inferring a cause -- without which the agent invents a cause for a move
         it can read verbatim in front of it.

    What those fields hold is the shared glossary's, because both roles are
    handed the same board and a field defined for one seat and left blank for
    the other is the same defect twice. What stays here is the part that is
    about facilitating: quote the record, or say it is silent.
    """
    brief = system_prompt(tier, THREAD_AGENT)

    assert BOARD_LEGEND in brief
    assert "a record, not a summary" in brief
    assert "quoting the decision's `rationale` or an entry of its `history`" in brief
    assert "saying that the record does not say" in brief
    assert "Never infer a cause" in brief
    assert "includes the notice this thread may have been opened from" in brief
    for named in ("`proposed_by`", "`verdict`", "prereqs", "puts_in_question"):
        assert named in BASELINE, named
    assert BOARD_LEGEND not in system_prompt(tier, GRILL_MASTER)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_neither_tiers_own_part_briefs_a_role(tier: str) -> None:
    """
    Given each tier's own part of the standing brief
    When it is read for what the turn is for
    Then it says nothing: a tier is how a turn is taken, and the moment a
         mandate rides on it, whichever role runs on that tier inherits it.
    """
    prompt = SYSTEM_PROMPTS[tier].lower()

    assert "facilitate" not in prompt
    assert "stop short of deciding" not in prompt
    assert "grill-master" not in prompt


def test_the_fast_tier_is_told_to_be_quick_and_the_heavy_one_is_not() -> None:
    """
    Given both tiers' own parts
    When they are read for what distinguishes them
    Then the fast tier is told to answer fast and the heavy tier is not -- the
         expert the human transferred to is worth the wait, and an expert
         hurried is a transfer that never happened.
    """
    assert FAST_TIER_MANDATE in SYSTEM_PROMPTS[FAST_TIER]
    assert FAST_TIER_MANDATE not in SYSTEM_PROMPTS[HEAVY_TIER]


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_every_brief_a_driver_composes_carries_the_register_rule(tier: str, agent: str) -> None:
    """
    Given the standing brief a driver composes for each role on each tier
    When it is read for what register the turn is to be written in
    Then it mandates plain sentences, the answer before the reasoning, and no
         term the decision does not need.
    """
    brief = system_prompt(tier, agent)

    assert REGISTER_RULE in brief
    assert "short, professional sentences a busy human reads once" in brief
    assert "Put the answer first and the reasoning after it" in brief
    assert "no term the decision does not need" in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_alone_permits_exactly_two_kinds_of_question(tier: str) -> None:
    """
    Given each role's brief on each tier
    When it is read for what it says about asking the human a question
    Then the thread agent's turn is a reply to what the human said, exactly two
         kinds of question are permitted -- clarifying what is being asked, and
         raising what the human is not considering -- nothing licenses a
         trailing continuation question, and none of it reaches the ruling turn.

    The rule is about a discussion, and the map's ruling turn is not one. The
    human answered a decision; they asked nothing. A turn told to answer what
    they just said, on a turn where they said only "option b", answers the
    letter instead of ruling on what it cost.
    """
    prompt = system_prompt(tier, THREAD_AGENT)

    assert DIALOGUE_RULE in prompt
    assert "not a prompt for their next turn" in prompt
    assert "Ask a question in two cases only" in prompt
    assert "when you cannot answer without knowing what they are actually asking" in prompt
    assert "when there is something they are not considering and should be" in prompt
    assert "No other question belongs in a reply" in prompt
    assert "asking whether there is anything else" in prompt
    # No third licence anywhere in the prompt: the habit this rule ends was
    # invited by one, and a survivor would be read as the exception.
    assert "ordinary move" not in prompt
    assert DIALOGUE_RULE not in system_prompt(tier, GRILL_MASTER)
    assert "Ask a question in two cases only" not in system_prompt(tier, GRILL_MASTER)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_no_shipped_prompt_tells_an_agent_to_wait_or_check_for_updates(tier: str) -> None:
    """
    Given each tier's shipped system prompt
    When it is read for anything that would have an agent spend a turn on
         transport
    Then it carries the one-turn rule and no advice to poll, wait or retry on
         an interval.
    """
    prompt = SYSTEM_PROMPTS[tier].lower()

    assert ONE_TURN_RULE in SYSTEM_PROMPTS[tier]
    assert "poll" not in prompt
    assert "every few seconds" not in prompt
    assert "until there is" not in prompt


def test_the_briefing_is_read_from_the_sessions_own_opening_entry(entries: list[LogEntry]) -> None:
    """
    Given a session seeded from a handoff
    When the briefing is read from the log
    Then all five briefing fields are in it, including the termination
         condition.
    """
    read = briefing(entries)

    assert STOP_WHEN in read
    assert "The store shape is about to be built" in read
    assert "The log is append-only" in read
    assert "no new services" in read
    assert "hard on cost and on recovery" in read


def test_the_assembled_prompt_carries_the_stop_condition(entries: list[LogEntry]) -> None:
    """
    Given a session whose briefing states when to stop
    When a turn's prompt is assembled
    Then the stop condition is in the prompt bytes -- the agent lost the
         handoff's authority, not its termination condition.
    """
    prompt = compose('{"image2": "recorded"}', dispatch_context(), entries)

    assert STOP_WHEN in prompt


def test_the_assembled_prompt_carries_the_recorded_board_verbatim(entries: list[LogEntry]) -> None:
    """
    Given the bytes recorded as one dispatch's context
    When a turn's prompt is assembled from them
    Then those bytes are in the prompt unchanged, so what the model was given
         and what the audit record holds are the same thing.
    """
    recorded = '{"agent":"grill-master","image2":{"decisions":[{"id":"d1"}]}}'

    assert recorded in compose(recorded, dispatch_context(), entries)


def test_a_log_with_no_opening_entry_briefs_nothing_rather_than_inventing_one() -> None:
    """
    Given a log carrying no opening entry
    When the briefing is read
    Then it says there is none, rather than composing one out of defaults.
    """
    assert briefing([]) == NO_BRIEFING


def test_the_prompt_says_which_channel_it_is_and_that_nothing_has_been_said(
    entries: list[LogEntry],
) -> None:
    """
    Given a channel on which nothing has been said yet
    When a turn's prompt is assembled
    Then it names the channel and says the conversation is empty, rather than
         leaving a blank section that reads as a lost transcript.
    """
    prompt = compose("{}", dispatch_context("t-compaction"), entries)

    assert "t-compaction" in prompt
    assert "Nothing has been said on this channel yet." in prompt


# --- how much each tier's model holds -------------------------------------------


def test_each_default_model_has_a_window_the_shipped_table_knows() -> None:
    """
    Given the models this package ships with
    When each tier's limit is asked for
    Then the table answers, so a session nobody configured is still measured.
    """
    config = TierConfig()

    assert config.limit_for(FAST_TIER) == CONTEXT_LIMITS[DEFAULT_FAST_MODEL]
    assert config.limit_for(HEAVY_TIER) == CONTEXT_LIMITS[DEFAULT_HEAVY_MODEL]


def test_a_model_the_table_never_heard_of_has_no_known_window() -> None:
    """
    Given tiers configured with models absent from the table
    When each limit is asked for
    Then nothing comes back, because a window nobody knows must not be guessed
         at -- an invented ceiling warns about the wrong thing all session.
    """
    config = TierConfig(fast_model="vendor/unknown", heavy_model="vendor/also-unknown")

    assert config.limit_for(FAST_TIER) is None
    assert config.limit_for(HEAVY_TIER) is None


def test_the_environment_states_a_window_the_table_is_wrong_about() -> None:
    """
    Given per-tier overrides in the environment
    When the configuration is read from it
    Then each override wins over the table, so a window that moved is one env
         var away rather than a release away.
    """
    config = TierConfig.from_env(
        {FAST_CONTEXT_LIMIT_ENV: "4096", HEAVY_CONTEXT_LIMIT_ENV: "222222"}
    )

    assert config.limit_for(FAST_TIER) == 4096
    assert config.limit_for(HEAVY_TIER) == 222_222


def test_an_unset_override_leaves_the_table_answering() -> None:
    """
    Given an environment naming no limits
    When the configuration is read from it
    Then the overrides are absent rather than zero, which is what keeps the
         table's answer from being replaced by a window of nothing.
    """
    config = TierConfig.from_env({FAST_CONTEXT_LIMIT_ENV: ""})

    assert config.fast_context_limit is None
    assert config.limit_for(FAST_TIER) == CONTEXT_LIMITS[DEFAULT_FAST_MODEL]


def test_a_limit_that_is_not_a_count_is_refused_at_launch() -> None:
    """
    Given an override that is not a number of tokens
    When the configuration is read
    Then it raises while the human is still watching the launch, rather than
         falling back to the table the operator was overriding on purpose.
    """
    with pytest.raises(UnreadableLimitError):
        TierConfig.from_env({HEAVY_CONTEXT_LIMIT_ENV: "lots"})


def test_a_tier_this_configuration_never_heard_of_has_no_limit_to_give() -> None:
    """
    Given a tier name outside the two
    When its limit is asked for
    Then it raises rather than answering with the heavy tier's window.
    """
    with pytest.raises(UnknownTierError):
        TierConfig().limit_for("medium")


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_is_told_the_shape_its_driver_reads(tier: str) -> None:
    """
    Given the thread agent's brief on each tier
    When it is read for what to send back
    Then it says the ordinary reply is prose, that the object form exists for
         the two exceptions and carries `text` beside them, that it names both
         keys, and that anything else is recorded as the turn's prose exactly as
         written.

    The driver reads a thread reply as prose unless it is an object carrying
    `text` and one of the two keys. The grill-master's brief spends a page on a
    document shape; this seat's said only when to write one key of an object it
    was never told the rest of. A seat that fills that in with the shape it read
    about elsewhere has its JSON published to the human verbatim -- and a seat
    told the object exists for one exception guesses at the envelope for the
    other.
    """
    brief = system_prompt(tier, THREAD_AGENT)

    assert THREAD_REPLY_RULE in brief
    assert "Your reply is what you are saying to the human, as plain prose" in brief
    assert "no JSON, no markdown wrapper, no keys" in brief
    assert "send a JSON object carrying `text`, your prose, and the key that exception" in brief
    assert "`needs_to_read` for the read request, `proposed_answer` for the offer" in brief
    assert "One object may carry both" in brief
    assert "recorded as the turn's prose exactly as you wrote it" in brief
    assert THREAD_REPLY_RULE not in system_prompt(tier, GRILL_MASTER)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_prompt_bars_an_offer_on_a_thread_anchoring_nothing(tier: str) -> None:
    """
    Given the thread-agent system prompt a driver composes for each tier
    When it is read for which decision an offer may name
    Then it states that the offer is on this thread's anchor decision and never
         on another, and that a thread anchored to none takes no offer at all --
         without which the thread about the board itself is left to pick a
         decision out of the map and offer an answer nobody can take.
    """
    prompt = system_prompt(tier, THREAD_AGENT)

    assert "on this thread's anchor decision and never on any other" in prompt
    assert "a thread anchored to no decision" in prompt
    assert "takes no `proposed_answer` at all" in prompt


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_master_brief_asks_for_rulings_nowhere_but_the_obligation_section(
    tier: str,
) -> None:
    """
    Given the grill-master brief a driver composes for each tier
    When it is read for when a ruling is owed
    Then the standing brief asks for none. It names the obligation section as
         the one place rulings are asked for, states the empty list as what
         every other turn sends, and carries no paragraph describing the case
         an agent would have to recognise its own turn in.

    The paragraph is the defect, not an omission. A standing rule about answers
    that bear on other decisions is a rule every turn can read itself into, and
    the live evidence is a turn owing nothing that ruled `stands` on all five
    decisions on the board -- including two the human had already settled --
    and put each rationale on the board as a notice.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert "On every other turn `rulings` is an empty list." in brief
    assert "Where this dispatch carries no obligation section, `rulings` is an empty list." in brief
    assert "Do not rule on a decision nobody asked you about" in brief
    # The two standing paragraphs that made every turn a ruling turn, by the
    # phrases that made them one.
    assert "bears on decisions other than the one they answered" not in brief
    assert "Rule on every decision the dispatch names" not in brief
    assert "any other the answer undermines" not in brief
    # And the obligation section itself, which is not in the standing brief at
    # all: it rides the one dispatch that owes it.
    assert MOOTNESS_OBLIGATION_RULE not in brief
    assert MOOTNESS_RESTING_RULE not in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_thread_agent_brief_refuses_a_map_change_and_names_the_route_that_can(
    tier: str,
) -> None:
    """
    Given the thread-agent brief a driver composes for each tier
    When it is read for what to do when the human asks it to change the map
    Then it says plainly that it cannot, and names folding this thread as what
         puts the conclusion in front of the grill-master who acts on it --
         without which the agent agrees in prose to invalidate a run of
         decisions and emits nothing, because only the grill-master may.
    """
    brief = system_prompt(tier, THREAD_AGENT)

    # Every seat runs with no tools, so an instruction to fetch another thread's
    # body names a mechanism nothing provides. What a stub shows is all there is.
    assert "say so and say what its stub shows" in brief
    assert "You cannot read that thread's turns" in brief
    assert "read surface" not in brief
    assert "If the human asks you to change the map" in brief
    assert "to invalidate, revise, settle or unsettle a decision, or add one" in brief
    assert "say plainly that you cannot" in brief
    assert "folding this thread is what puts your conclusion in front of the grill-master" in brief
    assert "Agreeing to do it is a promise nothing keeps" not in brief
    # And no line naming it the map's author, on either tier: a brief that both
    # refuses a map change and claims sole authorship of the map is one the
    # refusal test alone would pass.
    assert "the author of the map" not in brief
    assert "You are the grill-master" not in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_master_brief_gives_the_turn_one_lane_to_the_human(tier: str) -> None:
    """
    Given the grill-master brief on each tier
    When it is read for where the turn addresses the human
    Then `text` is the one message, an `informational` is a note pinned to one
         named decision rather than a second message, a `stands` rationale is
         barred from being one, and an option is named with its decision.

    Top-level `text` and the `informational` kind were the same act described
    twice, in the same words -- "what you are saying to the human" against "what
    you are telling them" -- which left the second one open and invited a shelf
    of notices the human has to read to learn one thing. The bare option
    reference is the same failure a level down: the board offers an option `b`
    under most of its rows.

    The thread agent is not told any of this: an update from it is refused, so
    a rule about which kind to speak through is a rule about a refusal.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert SPEECH_RULE in brief
    assert "one place per turn" in brief
    assert "An `informational` update is not a second message" in brief
    assert "name that decision in its `target`" in brief
    assert "Never put the reason for a `stands` ruling in an `informational`" in brief
    # The gate takes an untargeted note and the role does not send one. Both are
    # true, and a seat left to notice the difference for itself picks one.
    assert "lists `target` as optional because the backend accepts a note that names no" in brief
    assert "you do not send one" in brief
    assert SPEECH_RULE not in system_prompt(tier, THREAD_AGENT)
    # The option rule stands on its own rather than closing the block above.
    # As a trailing clause it was read as an aside, and the live reply that
    # dropped it opened on "Option b would let an agent rewrite a target",
    # where the decision was obvious to the writer and to nobody else.
    assert OPTION_REFERENCE_RULE in brief
    assert brief.index(OPTION_REFERENCE_RULE) > brief.index(SPEECH_RULE)
    assert OPTION_REFERENCE_RULE not in SPEECH_RULE
    assert '"option b of d3", never "option b"' in brief
    assert "it holds when the decision is the one the human has just answered" in brief
    assert OPTION_REFERENCE_RULE not in system_prompt(tier, THREAD_AGENT)


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_brief_states_the_two_rules_the_gate_does_not_enforce(tier: str) -> None:
    """
    Given the grill-master brief on each tier
    When it is read for what a node and a revision have to carry
    Then it says an `add-node` carries `short` and `body`, and a `revise`
         carries at least one of the fields a revision changes.

    Both are true of the board and neither is true of the gate, which is exactly
    why they have to be in prose. The rendered contract states what the gate
    refuses an update for missing, so on both kinds it is silent here: a seat
    reading only the contract ships a node the board draws as a blank row, and a
    revision the human reads as a paragraph of disagreement over an unchanged
    question.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert "An `add-node` carries `short` and `body`" in brief
    assert "arrives as a blank row the human cannot read" in brief
    assert (
        "A `revise` carries at least one of `short`, `title`, `body`, `options` or `prereqs`"
        in brief
    )
    assert "carrying none of them is accepted and changes nothing" in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_contract_defines_every_field_it_puts_in_front_of_the_seat(tier: str) -> None:
    """
    Given the grill-master brief on each tier
    When the per-kind contract is read for the fields it shows
    Then each field whose name does not say what it holds is given a line, and
         `settle` promises only what an answer can carry.

    The optional lists are the appender's and are not trimmed to what prose has
    got round to explaining, so a field shown and left undefined is one the seat
    fills in from the shape of the word: `pcr` and `zoom` say nothing at all,
    and a seat inventing three lines for `pcr` puts them on the board. And an
    answer may be an option with no words, so a `settle` promising the human's
    words for every answer promises what half of them do not have.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    for field, said in FIELD_MEANINGS.items():
        assert f"`{field}`: {said}." in brief, field
    assert "record the answer the human gave: the option they took, their words, or both" in brief
    assert "carrying the option and the words you recorded" in brief
    assert "record the answer the human gave, in their words" not in brief


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
def test_the_grill_master_brief_gives_a_gap_a_kind_and_a_way_out_of_it(tier: str) -> None:
    """
    Given the grill-master brief on each tier
    When it is read for what to do about something nobody supplied
    Then it names `elicit-alert` as the update that says so, states its three
         fields, says that a blocking alert locks the decision, and states every
         path that lifts the lock -- the human's dismissal, the seat's own
         withdrawal, and its second alert -- naming the field a withdrawal is
         made with, since the reply contract that defines it is read later.

    "Say what you lack instead of supplying it" named no kind for the whole of
    the seat's life, so the gap was said in prose and the board never heard it.
    The unlock half matters more than it looks. A seat told that only it can
    lift the lock rations `blocking` true against a cost the human does not
    actually pay -- and a seat told the human has an exit spends it where the
    decision really cannot be answered, which is the only place it belongs.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert GAP_RULE in brief
    assert "`elicit-alert`" in brief
    assert "`blocking` true locks the decision" in brief
    assert "dismissing the alert" in brief
    assert "by withdrawing it -- naming its id in `supersedes`" in brief
    assert "the reply's list of your own pending items you take back" in brief
    # `supersedes` is defined in the reply contract, which is read after this
    # rule -- so the definition travels with the first use or the seat meets the
    # field as a bare word.
    assert brief.index(GAP_RULE) > brief.index(OPTION_REFERENCE_RULE)
    assert brief.index(GAP_RULE) < brief.index(DOCUMENT_FORMAT_RULE)
    assert "whose `text` says what they supplied" in brief
    assert "`blocking` false leaves the decision answerable" in brief
    assert "no control of theirs unlocks it" not in brief
    assert GAP_RULE not in system_prompt(tier, THREAD_AGENT)


def answered_board() -> DispatchContext:
    """A map dispatch whose board carries the decision the human just answered."""
    return DispatchContext(
        agent=GRILL_MASTER,
        channel="map",
        epoch="e",
        seq=4,
        image2=ThreadProjection(
            epoch="e",
            seq=4,
            decisions=[
                Decision(
                    id="d1",
                    short="Store shape",
                    options=[
                        Option(id="a", text="A relational store"),
                        Option(id="b", text="Append-only log"),
                    ],
                ),
                Decision(id="d2", short="Compaction", options=[Option(id="b", text="On a bound")]),
            ],
        ),
    )


def answer_entry(option: str | None = "b", note: str | None = None) -> LogEntry:
    """The human's own answer, as the log holds it."""
    return LogEntry(
        seq=4,
        epoch="e",
        kind="answer",
        idempotency_key="k:1",
        timestamp="2026-09-04T21:44:35.682+00:00",
        actor="human",
        channel="map",
        payload={"target": "d1", "answer": {"option": option, "text": note}},
    )


def test_the_prompt_states_the_humans_last_answer_with_its_decision_and_option() -> None:
    """
    Given a channel whose log carries the human's answer
    When the turn's prompt is assembled
    Then the answer is stated with the decision's id and label, the option's
         letter and its text, and their note -- rather than only as the
         transcript line "human: option b".

    A letter on its own is not an answer the seat can act on. The board carries
    an option `b` under most of its rows, so a turn given the letter and left to
    find the row is a turn that can rule on the wrong decision and stay
    internally consistent while it does.
    """
    entries = [answer_entry(note="it has to survive a crash mid-write")]

    prompt = compose("{}", answered_board(), entries)

    assert "## The human's latest answer" in prompt
    assert "Decision: d1 -- Store shape" in prompt
    assert "Option taken: b -- Append-only log" in prompt
    assert "Their note: it has to survive a crash mid-write" in prompt
    # And the transcript heading no longer promises an order the seat is not
    # given: what moved is what the catch-up section is for.
    assert ", in order" not in prompt


def test_the_answer_section_reads_the_option_off_the_board_it_was_given() -> None:
    """
    Given an answer naming an option, and then one carrying only their words
    When each prompt is assembled
    Then the first resolves the letter against that decision's own options and
         the second says there was no option, rather than either inventing a
         label.

    The section restates what the board already holds, so a decision or an
    option the board does not carry is named by what is known about it and no
    more. A label composed for a row nobody can look up would be the one line in
    the section nothing backs.
    """
    said = compose("{}", answered_board(), [answer_entry(option=None, note="neither, log it")])

    assert "Option taken: none, they answered in their own words" in said
    assert "Their note: neither, log it" in said
    assert "Option taken: b -- On a bound" not in said


def test_each_channel_closes_on_the_turn_its_role_actually_takes(
    entries: list[LogEntry],
) -> None:
    """
    Given a map dispatch answering a decision, a map dispatch routing a thread's
          conclusion, and a thread dispatch
    When each prompt is read from its last line
    Then both map turns are asked for the document in words that hold whatever
         brought them about, the thread is asked to answer what the human said,
         and neither closing reaches the other channel.

    The human asked the map nothing; they answered a decision, or applied an
    invalidation, or folded a thread, or called for a reassessment. A closing
    line telling that turn to answer the last thing they said is a
    conversational ask on a document turn, and one naming their answer is wrong
    on the three map turns no answer caused.
    """
    on_the_map = compose("{}", dispatch_context(), entries)
    routing = compose(
        "{}", dispatch_context(conclusion=ThreadConclusion(thread="t-d1", text="x")), entries
    )
    on_a_thread = compose("{}", dispatch_context("t-d1"), entries)

    assert on_the_map.endswith(MAP_CLOSING)
    assert routing.endswith(MAP_CLOSING)
    # The human folds; this turn acts on what was folded. Reusing the verb for
    # the receiving turn gives one word two actors in the same prompt.
    assert "send the updates it calls for" in routing
    assert "fold it in as updates" not in routing
    assert "the rulings named in the obligation section above" in on_the_map
    assert "an empty list where this dispatch carries no such section" in on_the_map
    # The closing holds for a turn no answer caused, so it names none.
    assert "the human's answer" not in MAP_CLOSING
    assert THREAD_CLOSING not in on_the_map

    assert on_a_thread.endswith(THREAD_CLOSING)
    assert MAP_CLOSING not in on_a_thread


def test_a_channel_with_no_answer_in_its_log_states_no_answer(entries: list[LogEntry]) -> None:
    """
    Given a thread channel the human has answered nothing on
    When the turn's prompt is assembled
    Then it carries no answer section at all, rather than one whose every field
         is "none" -- which reads as an answer that was given and then lost.
    """
    assert "## The human's latest answer" not in compose("{}", dispatch_context("t-d1"), entries)


def map_thread_context(kind: str = MAP_THREAD_KIND, channel: str = "t-map") -> DispatchContext:
    """A thread dispatch whose board carries the thread the turn runs on.

    The kind is a parameter because what these checks are about is the
    difference between the two threads that anchor nothing: the one about the
    map and the one about the board.
    """
    return DispatchContext(
        agent=THREAD_AGENT,
        channel=channel,
        epoch="e",
        seq=0,
        image2=ThreadProjection(
            epoch="e", seq=0, threads=[Thread(id="t-map", kind=kind, title="Ask for a map change")]
        ),
    )


def test_a_turn_on_the_map_thread_is_told_to_state_which_decisions_change_and_how(
    entries: list[LogEntry],
) -> None:
    """
    Given a dispatch for the session-level map thread
    When the turn's prompt is assembled
    Then it carries that thread's mandate: name the decisions, say what happens
         to each, and hand the statement over by folding rather than authoring
         it -- without which its agent is an ordinary side thread told only that
         it may not change the map, and the human's request reaches the
         grill-master as prose nobody can act on.
    """
    prompt = compose("{}", map_thread_context(), entries)

    assert MAP_THREAD_MANDATE in prompt
    assert "which decisions change and how" in prompt
    assert "folding it is what hands your statement to the grill-master" in prompt
    # The four verbs carry their meaning here. This seat's brief holds no update
    # contract, so a bare "unsettled" is a word it has been given nowhere.
    assert "invalidated so it stops being offered" in prompt
    assert "revised so it asks a different question" in prompt
    assert "unsettled so its answer is withdrawn and it can be answered again" in prompt
    assert "settled so it carries an answer" in prompt
    assert "added as a question the map does not carry" in prompt


def test_the_map_thread_mandate_reaches_no_other_channel(entries: list[LogEntry]) -> None:
    """
    Given the help thread, an ordinary side thread and the map channel
    When each one's prompt is assembled
    Then none carries the map thread's mandate -- it is a property of the
         channel the turn runs on, and an agent told to steer the map on a
         thread the human opened for something else steers it unasked.
    """
    assert MAP_THREAD_MANDATE not in compose("{}", map_thread_context(kind="help"), entries)
    assert MAP_THREAD_MANDATE not in compose("{}", dispatch_context("t-d1"), entries)
    assert MAP_THREAD_MANDATE not in compose("{}", dispatch_context(), entries)


def test_a_turn_on_the_help_thread_is_told_where_the_tools_own_material_is(
    entries: list[LogEntry],
) -> None:
    """
    Given a dispatch for the session's help thread
    When the turn's prompt is assembled
    Then it says that thread is about driving the board rather than about the
         plan, names `help_reference` as where the material for it is, and tells
         the turn to say so when the material does not answer the question.

    The material has always crossed inside the board bytes and nothing has ever
    pointed at it. A seat asked how a control works, with no line saying the
    answer is in front of it, describes a screen it has never seen -- and the
    human spends the next minute looking for a button that is not there.
    """
    prompt = compose("{}", map_thread_context(kind=HELP_THREAD_KIND), entries)

    assert HELP_THREAD_MANDATE in prompt
    assert "`help_reference`" in prompt
    assert "say that it does not" in prompt
    assert MAP_THREAD_MANDATE not in prompt


def test_the_help_thread_mandate_reaches_no_other_channel(entries: list[LogEntry]) -> None:
    """
    Given the map thread, an ordinary side thread and the map channel
    When each one's prompt is assembled
    Then none carries the help thread's mandate: the material it points at rides
         that one dispatch, so a turn told to answer from it anywhere else is
         told to read a key the board it was handed does not carry.
    """
    assert HELP_THREAD_MANDATE not in compose("{}", map_thread_context(), entries)
    assert HELP_THREAD_MANDATE not in compose("{}", dispatch_context("t-d1"), entries)
    assert HELP_THREAD_MANDATE not in compose("{}", dispatch_context(), entries)


def test_the_map_thread_as_another_threads_stub_mandates_nothing(
    entries: list[LogEntry],
) -> None:
    """
    Given a dispatch for one thread whose board also carries the map thread
    When that turn's prompt is assembled
    Then it carries no map mandate: a kind read off any thread on the board
         rather than off the channel this turn runs on would put the mandate on
         every turn taken for the rest of the session.
    """
    assert MAP_THREAD_MANDATE not in compose("{}", map_thread_context(channel="t-d1"), entries)


def test_a_turn_owed_invalidates_is_given_the_ids_and_the_answer_in_a_section_of_its_own(
    entries: list[LogEntry],
) -> None:
    """
    Given a grill-master dispatch carrying the obligation an answer left
    When the turn's prompt is assembled
    Then it names each decision the answer put in question, quotes the answer to
         carry as the rationale, and states the obligation in a section of its
         own -- while a dispatch carrying none says nothing about mootness.

    The standing brief already carries the rule and the fast tier reads past it:
    the live evidence is two sentences of prose against an answer that put eight
    decisions in question. A paragraph about a case is something an agent has to
    recognise its own turn in; a list of ids is not.
    """
    context = dispatch_context().model_copy(
        update={
            "mootness": MootnessObligation(
                target="d1", answer="Close it unactioned", ids=["d2", "d8"]
            )
        }
    )

    prompt = compose("{}", context, entries)

    assert "## The obligation section:" in prompt
    assert "d2, d8" in prompt
    assert "Close it unactioned" in prompt
    assert MOOTNESS_OBLIGATION_RULE in prompt
    assert MOOTNESS_OBLIGATION_RULE not in compose("{}", dispatch_context(), entries)


def test_a_turn_owed_a_verdict_on_stranded_decisions_is_told_which_gesture_stranded_them(
    entries: list[LogEntry],
) -> None:
    """
    Given a grill-master dispatch carrying the obligation an applied invalidate
          left
    When the turn's prompt is assembled
    Then it names each decision left resting on the dead prereq, quotes the
         invalidation, and states the rule that a revise discharges as well as
         an invalidate.

    The two obligations do not owe the same thing. A turn told only "propose an
    invalidate for each" would kill decisions that survive their prereq, and one
    told nothing would leave the human answering questions whose footing has
    gone -- so the section says which gesture it is about.
    """
    context = dispatch_context().model_copy(
        update={
            "mootness": MootnessObligation(
                target="d1", answer="the export was dropped", ids=["d4", "d5"], cause="invalidate"
            )
        }
    )

    prompt = compose("{}", context, entries)

    assert "## The obligation section:" in prompt
    assert "d4, d5" in prompt
    assert "the export was dropped" in prompt
    assert MOOTNESS_RESTING_RULE in prompt
    assert MOOTNESS_OBLIGATION_RULE not in prompt
