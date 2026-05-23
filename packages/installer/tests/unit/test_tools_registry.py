"""Unit tests for installer.tools.registry.

Each test pins a design decision from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tautology tests — isinstance(adapter, ToolAdapter), attribute-literal
assertions like adapter.name == "claude", `@runtime_checkable` machinery
— are deliberately absent. See the writing-unit-tests skill's Tautology
Filter section."""

from __future__ import annotations

import pytest

from installer.core.model import Tool
from installer.tools.registry import (
    UnknownToolError,
    get_adapter,
    parse_tool_name,
)


def test_get_adapter_on_unregistered_tool_raises_key_error() -> None:
    """
    Given the registry contains only Tool.CLAUDE
    When the caller invokes get_adapter(Tool.OPENCODE)
    Then a KeyError is raised.

    Pins: callers must validate via parse_tool_name first.
    """
    with pytest.raises(KeyError):
        get_adapter(Tool.OPENCODE)


def test_parse_tool_name_accepts_registered_name() -> None:
    """
    Given the registry contains Tool.CLAUDE
    When parse_tool_name("claude") is called
    Then it returns Tool.CLAUDE.
    """
    assert parse_tool_name("claude") is Tool.CLAUDE


def test_parse_tool_name_rejects_enum_value_not_in_registry() -> None:
    """
    Given the registry contains only Tool.CLAUDE
    When parse_tool_name("opencode") is called
    Then UnknownToolError is raised
    And the error.name is "opencode"
    And the error.valid is ("claude",).

    Pins: registry-is-truth — Tool enum existence alone is insufficient.
    """
    with pytest.raises(UnknownToolError) as exc_info:
        parse_tool_name("opencode")
    assert exc_info.value.name == "opencode"
    assert exc_info.value.valid == ("claude",)


def test_parse_tool_name_rejects_non_enum_string() -> None:
    """
    When parse_tool_name("foo") is called
    Then UnknownToolError is raised
    And the error.name is "foo".
    """
    with pytest.raises(UnknownToolError) as exc_info:
        parse_tool_name("foo")
    assert exc_info.value.name == "foo"


def test_unknown_tool_error_exposes_structured_attributes() -> None:
    """
    When UnknownToolError("opencode", ("claude",)) is constructed
    Then the instance has .name == "opencode"
    And the instance has .valid == ("claude",).

    Pins: structured-exception contract — tests assert on data, not
    the message string.
    """
    err = UnknownToolError("opencode", ("claude",))
    assert err.name == "opencode"
    assert err.valid == ("claude",)
