"""Unit tests for installer.tools.registry.

Each test pins a design decision from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md) and the
D.1 CodexAdapter registration story.
Tautology tests — isinstance(adapter, ToolAdapter), attribute-literal
assertions like adapter.name == "claude", `@runtime_checkable` machinery
— are deliberately absent. See the writing-unit-tests skill's Tautology
Filter section."""

from __future__ import annotations

import pytest

from installer.core.model import Tool
from installer.tools import registry
from installer.tools.registry import (
    UnknownToolError,
    parse_tool_name,
)


def test_get_adapter_on_unregistered_tool_raises_key_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a Tool whose adapter is absent from the registry
    When the caller invokes get_adapter on it
    Then a KeyError is raised.

    Pins: get_adapter does not silently absorb a missing key — callers must
    validate via parse_tool_name first. Every Tool now has a registered
    adapter, so the unregistered precondition is simulated by removing one
    entry (this is also the safety net for a future Tool added to the enum
    but not wired into the registry).
    """
    reduced = {t: a for t, a in registry._REGISTRY.items() if t is not Tool.OPENCODE}
    monkeypatch.setattr(registry, "_REGISTRY", reduced)
    with pytest.raises(KeyError):
        registry.get_adapter(Tool.OPENCODE)


def test_parse_tool_name_accepts_registered_name() -> None:
    """
    Given the registry contains Tool.CLAUDE
    When parse_tool_name("claude") is called
    Then it returns Tool.CLAUDE.
    """
    assert parse_tool_name("claude") is Tool.CLAUDE


def test_parse_tool_name_accepts_codex() -> None:
    """
    Given Tool.CODEX is registered
    When parse_tool_name("codex") is called
    Then it returns Tool.CODEX.

    Pins: registry-is-truth for codex — CodexAdapter wired in the registry.
    """
    assert parse_tool_name("codex") is Tool.CODEX


def test_parse_tool_name_accepts_gemini() -> None:
    """
    Given Tool.GEMINI is registered
    When parse_tool_name("gemini") is called
    Then it returns Tool.GEMINI.

    Pins: registry-is-truth for gemini — GeminiAdapter wired in the registry.
    """
    assert parse_tool_name("gemini") is Tool.GEMINI


def test_parse_tool_name_accepts_opencode() -> None:
    """
    Given Tool.OPENCODE is registered
    When parse_tool_name("opencode") is called
    Then it returns Tool.OPENCODE.

    Pins: registry-is-truth for opencode — OpenCodeAdapter wired in the registry.
    """
    assert parse_tool_name("opencode") is Tool.OPENCODE


def test_parse_tool_name_rejects_enum_value_not_in_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a Tool enum value whose adapter is absent from the registry
    When parse_tool_name is called with that value's name
    Then UnknownToolError is raised
    And error.name is the supplied name
    And error.valid lists exactly the still-registered tool names.

    Pins: registry-is-truth — Tool enum membership alone is insufficient; the
    registry, not the enum, gates validity. Every Tool now has a registered
    adapter, so the precondition is simulated by removing one entry — this is
    the safety net for a future Tool added to the enum but never registered.
    """
    reduced = {t: a for t, a in registry._REGISTRY.items() if t is not Tool.OPENCODE}
    monkeypatch.setattr(registry, "_REGISTRY", reduced)
    with pytest.raises(UnknownToolError) as exc_info:
        registry.parse_tool_name("opencode")
    assert exc_info.value.name == "opencode"
    assert exc_info.value.valid == ("claude", "codex", "gemini")


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
