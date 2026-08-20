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
from conftest import handoff_doc, write_handoff

from grillui.schemas import LogEntry
from grillui.session import open_session
from grillui.tiers import (
    CONCISION_RULE,
    DEFAULT_FAST_MODEL,
    DEFAULT_HEAVY_MODEL,
    FACILITATION_MANDATE,
    FAST_MODEL_ENV,
    FAST_TIER,
    HEAVY_MODEL_ENV,
    HEAVY_TIER,
    NO_BRIEFING,
    NO_MANUFACTURE_RULE,
    ONE_TURN_RULE,
    SYSTEM_PROMPTS,
    TierConfig,
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


def test_both_model_ids_come_from_the_environment_when_it_states_them() -> None:
    """
    Given an environment naming both model ids
    When configuration is read from it
    Then both tiers take the stated ids, and each tier answers with its own.
    """
    config = TierConfig.from_env({FAST_MODEL_ENV: "vendor/fast-2", HEAVY_MODEL_ENV: "claude-x"})

    assert config.model_for(FAST_TIER) == "vendor/fast-2"
    assert config.model_for(HEAVY_TIER) == "claude-x"


def test_an_empty_setting_is_not_a_model_id() -> None:
    """
    Given an environment exporting the variables empty
    When configuration is read from it
    Then the defaults stand, rather than a session being configured to reach a
         model with no name.
    """
    config = TierConfig.from_env({FAST_MODEL_ENV: "", HEAVY_MODEL_ENV: ""})

    assert (config.fast_model, config.heavy_model) == (DEFAULT_FAST_MODEL, DEFAULT_HEAVY_MODEL)


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
    prompt = compose('{"image2": "recorded"}', "map", entries)

    assert STOP_WHEN in prompt


def test_the_assembled_prompt_carries_the_recorded_board_verbatim(entries: list[LogEntry]) -> None:
    """
    Given the bytes recorded as one dispatch's context
    When a turn's prompt is assembled from them
    Then those bytes are in the prompt unchanged, so what the model was given
         and what the audit record holds are the same thing.
    """
    recorded = '{"agent":"grill-master","image2":{"decisions":[{"id":"d1"}]}}'

    assert recorded in compose(recorded, "map", entries)


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
    prompt = compose("{}", "t-compaction", entries)

    assert "t-compaction" in prompt
    assert "Nothing has been said on this channel yet." in prompt
