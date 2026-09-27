"""The capability front-matter table and its reader.

Pins two coded decisions: which tools are declared to define which capability
key, and that the user-invoked reading is strict about what counts as the flag.
"""

from __future__ import annotations

import pytest

from installer.core.capabilities import (
    CAPABILITY_SUPPORT,
    USER_INVOKED_KEY,
    is_user_invoked,
    unsupported_keys,
)
from installer.tools.registry import known_tools


def test_every_declared_supporter_is_a_known_tool() -> None:
    """A misspelled tool name would strip the key from the tool that does support
    it, silently and everywhere — the table's one failure mode with no symptom."""
    declared = {tool for tools in CAPABILITY_SUPPORT.values() for tool in tools}
    assert declared <= {tool.value for tool in known_tools()}


def test_claude_defines_every_capability_key() -> None:
    assert unsupported_keys("claude") == frozenset()


@pytest.mark.parametrize("tool", ["codex", "gemini", "opencode"])
def test_the_other_tools_define_none_of_them(tool: str) -> None:
    """The projection target for a tool with no equivalent capability is to drop
    the key, so every key is unsupported for all three."""
    assert unsupported_keys(tool) == frozenset(CAPABILITY_SUPPORT)


def test_an_unregistered_tool_name_drops_everything() -> None:
    """A tool added to the registry without an entry here ships no inert keys.
    The opposite default would ship all of them."""
    assert unsupported_keys("some-future-tool") == frozenset(CAPABILITY_SUPPORT)


def test_the_flag_is_read_only_as_a_true_boolean() -> None:
    assert is_user_invoked(f"---\n{USER_INVOKED_KEY}: true\n---\nbody\n")
    assert not is_user_invoked(f"---\n{USER_INVOKED_KEY}: false\n---\nbody\n")
    assert not is_user_invoked(f"---\n{USER_INVOKED_KEY}: yes-please\n---\nbody\n")


def test_absent_or_missing_front_matter_reads_as_model_invoked() -> None:
    """The stricter cap is the one to fall back to when nothing says otherwise."""
    assert not is_user_invoked("---\nname: a\n---\nbody\n")
    assert not is_user_invoked("# no front matter\n")
