from __future__ import annotations

from installer.core.model import Tool
from installer.tools.base import ToolAdapter
from installer.tools.claude import ClaudeAdapter

_REGISTRY: dict[Tool, ToolAdapter] = {
    Tool.CLAUDE: ClaudeAdapter(),
}


class UnknownToolError(ValueError):
    """Raised when a CLI-supplied tool name is not in the registry.
    Structured attrs (.name, .valid) so callers and tests assert on
    data, not on the message string."""

    def __init__(self, name: str, valid: tuple[str, ...]) -> None:
        super().__init__(f"Unknown tool: {name!r} (valid: {', '.join(valid)})")
        self.name = name
        self.valid = valid


def known_tools() -> tuple[Tool, ...]:
    """Sorted tuple of registered Tool values. Drives auto-detect iteration
    and `--tools=` validation error messages."""
    return tuple(sorted(_REGISTRY.keys(), key=lambda t: t.value))


def get_adapter(tool: Tool) -> ToolAdapter:
    """Lookup. Raises KeyError on miss — callers expected to have
    validated via parse_tool_name first."""
    return _REGISTRY[tool]


def parse_tool_name(name: str) -> Tool:
    """Translate a `--tools=` CSV element to its Tool enum value. Filters
    on registry membership, not just enum membership (registry-is-truth)."""
    valid_names = tuple(t.value for t in known_tools())
    try:
        candidate = Tool(name)
    except ValueError:
        raise UnknownToolError(name, valid_names) from None
    if candidate not in _REGISTRY:
        raise UnknownToolError(name, valid_names)
    return candidate
