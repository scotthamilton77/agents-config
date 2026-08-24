"""What the tiers are configured as, what they are told, and what a turn is given.

The prompt checks read the shipped strings rather than a copy of them, so a rule
deleted from a prompt is a red test rather than a documentation drift nobody
notices until a session goes wrong. The configuration checks read the defaults
the package ships and the environment a caller states, so what a run is
configured with is stated by the test rather than by whatever the machine
happened to be exporting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import dispatch_context, handoff_doc, write_handoff

from grillui.dispatch import GRILL_MASTER, THREAD_AGENT
from grillui.schemas import (
    MAP_THREAD_KIND,
    DispatchContext,
    LogEntry,
    MootnessObligation,
    Thread,
    ThreadProjection,
)
from grillui.session import open_session
from grillui.tiers import (
    BOARD_LEGEND,
    CONCISION_RULE,
    CONTEXT_LIMITS,
    DEFAULT_FAST_MODEL,
    DEFAULT_HEAVY_EFFORT,
    DEFAULT_HEAVY_MODEL,
    EFFORT_LEVELS,
    ESCALATION_POLICIES,
    ESCALATION_POLICY_ENV,
    FACILITATION_MANDATE,
    FAST_CONTEXT_LIMIT_ENV,
    FAST_MODEL_ENV,
    FAST_TIER,
    FAST_TIER_MANDATE,
    GRILL_MASTER_MANDATE,
    HEAVY_CONTEXT_LIMIT_ENV,
    HEAVY_EFFORT_ENV,
    HEAVY_MODEL_ENV,
    HEAVY_TIER,
    MAP_THREAD_MANDATE,
    MOOTNESS_OBLIGATION_RULE,
    MOOTNESS_RESTING_RULE,
    MOOTNESS_RULE,
    NO_BRIEFING,
    NO_MANUFACTURE_RULE,
    ONE_TURN_RULE,
    POLICY_AUTONOMOUS,
    POLICY_GATED,
    REGISTER_RULE,
    RESHAPE_STEP,
    ROLE_PROMPTS,
    SYSTEM_PROMPTS,
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
def test_every_shipped_system_prompt_carries_the_concision_constraint(tier: str) -> None:
    """
    Given each tier's shipped system prompt
    When it is read
    Then it carries the concision constraint, with the explicit-request
         exception stated in the same breath.
    """
    prompt = SYSTEM_PROMPTS[tier]

    assert CONCISION_RULE in prompt
    assert "three sentences" in prompt
    assert "unless the human explicitly asks for detail" in prompt


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


@pytest.mark.parametrize("tier", [FAST_TIER, HEAVY_TIER])
@pytest.mark.parametrize("agent", [GRILL_MASTER, THREAD_AGENT])
def test_every_composed_brief_opens_with_its_agents_role(tier: str, agent: str) -> None:
    """
    Given the brief a driver composes for one role on one tier
    When it is read from its first byte
    Then it opens with that agent's role part, the same part on either tier.

    A role keyed to the tier is the defect this is here to catch: it puts the
    map's author under "stop short of deciding" on the one turn whose whole work
    is a ruling, and hands the sole-author line to a thread agent the moment the
    human transfers its thread.
    """
    assert system_prompt(tier, agent).startswith(ROLE_PROMPTS[agent])


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
    assert "the author of the map and the only agent that changes it" in brief
    assert "Push on the axis the posture names" in brief
    assert "leave ending the session to them" in brief
    assert RESHAPE_STEP in brief
    assert "Rule on every decision the dispatch names" in brief
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
    Then it carries the legend: the record says what happened and why, a
         question about why the board moved is answered by quoting it or by
         saying it does not say, and a pre-mark is a prediction rather than a
         dependency -- without which the agent invents a cause for a move it can
         read verbatim in front of it.
    """
    brief = system_prompt(tier, THREAD_AGENT)

    assert BOARD_LEGEND in brief
    assert "`status`, `rationale` and `history`" in brief
    assert "quoting them" in brief
    assert "never by inferring a cause" in brief
    assert "a mark, not a dependency" in brief
    assert "including a notice this thread may have been opened from" in brief


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
def test_every_shipped_system_prompt_permits_exactly_two_kinds_of_question(tier: str) -> None:
    """
    Given each tier's shipped system prompt
    When it is read for what it says about asking the human a question
    Then a turn is a reply to what the human said, exactly two kinds of question
         are permitted -- clarifying what is being asked, and raising what the
         human is not considering -- and nothing licenses a trailing
         continuation question.
    """
    prompt = SYSTEM_PROMPTS[tier]

    assert "not a prompt for their next turn" in prompt
    assert "Ask a question in two cases only" in prompt
    assert "when you cannot answer without knowing what they are actually asking" in prompt
    assert "when there is something they are not considering and should be" in prompt
    assert "No other question belongs in a reply" in prompt
    assert "asking whether there is anything else" in prompt
    # No third licence anywhere in the prompt: the habit this rule ends was
    # invited by one, and a survivor would be read as the exception.
    assert "ordinary move" not in prompt


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
def test_the_grill_master_brief_obliges_a_ruling_on_each_decision_an_answer_bears_on(
    tier: str,
) -> None:
    """
    Given the grill-master brief a driver composes for each tier
    When it is read for what an answer bearing on other decisions obliges
    Then it requires a ruling per decision -- one of the three -- carrying the
         answer as the rationale where it kills, and bars narrating a decision
         as dead instead. Without that the reply says d2 through d9 are dead
         code and the board goes on offering them on the frontier; with only one
         legal verdict it kills the ones that stand. The thread agent is not
         told this: an update from it is refused, so obliging it to send one is
         obliging it to be refused.
    """
    brief = system_prompt(tier, GRILL_MASTER)

    assert MOOTNESS_RULE in brief
    assert "bears on decisions other than the one they answered" in brief
    assert "rule on each of those in that same turn" in brief
    assert "carrying their answer as the rationale" in brief
    assert "Do not merely say that a decision is dead" in brief
    for verdict in ("invalidate", "revise", "stands"):
        assert f"`{verdict}`" in MOOTNESS_RULE
    assert MOOTNESS_RULE not in system_prompt(tier, THREAD_AGENT)


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

    assert "If the human asks you to change the map" in brief
    assert "say plainly that you cannot" in brief
    assert "folding this thread is what puts your conclusion in front of the grill-master" in brief
    assert "Agreeing to do it is a promise nothing keeps" in brief
    # And no line naming it the map's author, on either tier: a brief that both
    # refuses a map change and claims sole authorship of the map is one the
    # refusal test alone would pass.
    assert "the author of the map" not in brief
    assert "You are the grill-master" not in brief


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

    assert "d4, d5" in prompt
    assert "the export was dropped" in prompt
    assert MOOTNESS_RESTING_RULE in prompt
    assert MOOTNESS_OBLIGATION_RULE not in prompt
