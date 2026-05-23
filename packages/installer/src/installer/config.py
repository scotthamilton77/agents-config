from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from installer.core.model import Tool
from installer.tools.registry import get_adapter, known_tools, parse_tool_name


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved installer configuration. Frozen so the engine can pass it
    freely without defensive copies. B.1 scope: only fields needed for
    tool selection. Later stories add fields as their behaviour requires."""

    home: Path
    tools: tuple[Tool, ...]


def resolve_tools(*, home: Path, override_csv: str | None) -> tuple[Tool, ...]:
    """Translate the `--tools=` CLI value into the resolved tool tuple.

    - `override_csv is None` -> auto-detect: walk known_tools(), keep
      those whose adapter reports `is_detected(home) is True`.
    - `override_csv == ""` (or whitespace-only) -> ValueError.
    - Otherwise -> split on commas, strip whitespace, validate each via
      `parse_tool_name`, dedupe preserving first occurrence, preserve
      user-supplied order.
    """
    if override_csv is None:
        return tuple(t for t in known_tools() if get_adapter(t).is_detected(home))

    if override_csv.strip() == "":
        raise ValueError("--tools= requires at least one tool")  # noqa: TRY003  # B.1 spec verbatim; dedicated subclass not justified for a single call-site

    seen: dict[Tool, None] = {}
    for raw in override_csv.split(","):
        tool = parse_tool_name(raw.strip())
        seen.setdefault(tool, None)
    return tuple(seen.keys())
