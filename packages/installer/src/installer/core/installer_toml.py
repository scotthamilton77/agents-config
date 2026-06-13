"""Loader for ``installer.toml`` — the structured replacement for the legacy
``scripts/prune-list`` text file.

Replaces the bash ``_load_prune_list`` (``scripts/install.sh:1471-1483``), which
read one glob per non-comment line out of ``scripts/prune-list``. The Python
installer instead reads a ``[prune] retired`` array from
``packages/installer/installer.toml`` (schema in
``docs/architecture/installer/installer-design.md`` §"Configuration —
installer.toml"). An optional ``[tools]`` table carries per-tool dest-dir
overrides.

Pure: takes a ``Path``, returns parsed data. A missing file is the no-op
default (empty prune list, no overrides) — mirroring the bash
``[[ -f "$list_file" ]] || return 0`` early-out — so callers never have to
guard the absent-config case. Glob *matching* lives in ``core/prune.py``; this
module only retains the patterns as strings.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstallerToml:
    """Parsed ``installer.toml`` contents the engine consumes.

    ``prune_globs`` are retired-path glob patterns retained verbatim (matching
    happens in ``core/prune.py``). ``tool_dest_overrides`` maps a tool name to
    a dest-dir override string; empty unless a ``[tools]`` table declares one.
    Both default empty so the missing-file path constructs a valid, inert
    config without special-casing at every call site.

    ``tool_dest_overrides`` is parsed and surfaced but NOT yet consumed: dest
    resolution still goes through ``adapter.dest_dir(home)`` everywhere
    (including the prune scan), so a declared override is currently inert.
    Threading the override into dest resolution is a deliberate later story —
    the schema ships now (it is documented in the design doc) so the loader is
    forward-compatible. Until a consumer lands, a ``[tools]`` ``dest`` entry has
    no runtime effect."""

    prune_globs: list[str] = field(default_factory=list)
    tool_dest_overrides: dict[str, str] = field(default_factory=dict)


def load_installer_toml(path: Path) -> InstallerToml:
    """Parse ``installer.toml`` at ``path``; return an ``InstallerToml``.

    A missing file yields an empty config (no prune globs, no overrides) with
    no error — absence of installer-level config is a valid state, not a
    failure. A present file with no ``[prune]`` section likewise yields an empty
    prune list; the section is optional. The ``[tools]`` table is read as a
    flat ``{tool: dest}`` mapping from each ``<tool>.dest`` entry.
    """
    if not path.is_file():
        return InstallerToml()

    data = tomllib.loads(path.read_text())

    prune_section = data.get("prune", {})
    prune_globs = list(prune_section.get("retired", []))

    tools_section = data.get("tools", {})
    tool_dest_overrides = {
        tool: table["dest"]
        for tool, table in tools_section.items()
        if isinstance(table, dict) and "dest" in table
    }

    return InstallerToml(prune_globs=prune_globs, tool_dest_overrides=tool_dest_overrides)
