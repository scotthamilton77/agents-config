from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from installer.core.model import Tool
from installer.plugins.base import PluginAdapter
from installer.plugins.registry import UnknownPluginError, discover
from installer.tools.registry import get_adapter, known_tools, parse_tool_name


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved installer configuration. Frozen so the engine can pass it
    freely without defensive copies. Later stories add fields as their
    behaviour requires.

    ``auto_yes`` (G.7) carries the ``--yes`` / ``-y`` flag: it waives the
    non-interactive consent guard (``core/consent.py``) and is the intended
    scripted-install path. Defaults ``False`` so existing constructions are
    unaffected."""

    home: Path
    tools: tuple[Tool, ...]
    auto_yes: bool = False


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
        name = raw.strip()
        if not name:
            raise ValueError("--tools= contains an empty tool name (check for stray commas)")  # noqa: TRY003  # single call-site; subclass not justified
        tool = parse_tool_name(name)
        seen.setdefault(tool, None)
    return tuple(seen.keys())


def resolve_plugins(
    *, home: Path, plugins_root: Path, override_csv: str | None
) -> tuple[PluginAdapter, ...]:
    """Translate the `--plugins=` CLI value into the resolved plugin tuple.

    - `override_csv is None` -> auto-detect: discovered adapters whose
      `is_detected(home)` is True.
    - `override_csv == ""` (or whitespace-only) -> () (install no plugins).
      Deliberate asymmetry with `resolve_tools`, which raises on empty
      `--tools=`: "no plugins" is a valid choice, "no tools" is a no-op error.
      Matches scripts/install.sh's plugin-detection block, where a set
      `--plugins=` flag with an empty value yields no plugins.
    - Otherwise -> split on commas, strip whitespace, validate each via the
      discovered set, dedupe preserving first occurrence, preserve order.
    """
    discovered = discover(plugins_root)

    if override_csv is None:
        return tuple(a for a in discovered.values() if a.is_detected(home))

    if override_csv.strip() == "":
        return ()

    valid = tuple(discovered.keys())
    seen: dict[str, None] = {}
    for raw in override_csv.split(","):
        name = raw.strip()
        if not name:
            raise ValueError("--plugins= contains an empty plugin name (check for stray commas)")  # noqa: TRY003  # single call-site; subclass not justified
        if name not in discovered:
            raise UnknownPluginError(name, valid)
        seen.setdefault(name, None)
    return tuple(discovered[name] for name in seen)
