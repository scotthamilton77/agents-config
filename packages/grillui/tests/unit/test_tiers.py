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

from grillui.schemas import LogEntry
from grillui.session import open_session
from grillui.tiers import (
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
    HEAVY_CONTEXT_LIMIT_ENV,
    HEAVY_EFFORT_ENV,
    HEAVY_MODEL_ENV,
    HEAVY_TIER,
    NO_BRIEFING,
    NO_MANUFACTURE_RULE,
    ONE_TURN_RULE,
    POLICY_AUTONOMOUS,
    POLICY_GATED,
    SYSTEM_PROMPTS,
    TierConfig,
    UnknownTierError,
    UnreadableLimitError,
    briefing,
    compose,
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


def test_the_fast_prompt_carries_the_facilitation_mandate_and_stops_short_of_deciding() -> None:
    """
    Given the fast tier's system prompt
    When it is read
    Then it mandates facilitation and tells the tier to stop short of deciding
         once a question crosses into reasoning or design.
    """
    prompt = SYSTEM_PROMPTS[FAST_TIER]

    assert FACILITATION_MANDATE in prompt
    assert "stop short of deciding" in prompt
    assert "leave the decision with the human" in prompt


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


def test_the_heavy_prompt_leaves_ending_the_grilling_to_the_human() -> None:
    """
    Given the heavy tier's system prompt
    When it is read
    Then it may say the stop condition is met and may not end the session.
    """
    assert "ending the grilling is theirs" in SYSTEM_PROMPTS[HEAVY_TIER]


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
