"""Loader for ``installer.toml`` — the optional installer configuration.

Reads an optional ``[tools]`` table of per-tool dest-dir overrides from
``packages/installer/installer.toml`` (schema in
``docs/architecture/installer/installer-design.md`` §"Configuration —
installer.toml").

Pure: takes a ``Path``, returns parsed data. A missing file is the no-op
default (no overrides), so callers never have to guard the absent-config case.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstallerToml:
    """Parsed ``installer.toml`` contents the engine consumes.

    ``tool_dest_overrides`` maps a tool name to a dest-dir override string;
    empty unless a ``[tools]`` table declares one. It defaults empty so the
    missing-file path constructs a valid, inert config without special-casing
    at every call site.

    ``tool_dest_overrides`` is parsed and surfaced but NOT yet consumed: dest
    resolution still goes through ``adapter.dest_dir(home)`` everywhere
    (including the prune scan), so a declared override is currently inert.
    Threading the override into dest resolution is a deliberate later story —
    the schema ships now (it is documented in the design doc) so the loader is
    forward-compatible. Until a consumer lands, a ``[tools]`` ``dest`` entry has
    no runtime effect."""

    tool_dest_overrides: dict[str, str] = field(default_factory=dict)


def load_installer_toml(path: Path) -> InstallerToml:
    """Parse ``installer.toml`` at ``path``; return an ``InstallerToml``.

    A missing file yields an empty config (no overrides) with no error — absence
    of installer-level config is a valid state, not a failure. The ``[tools]``
    table is read as a flat ``{tool: dest}`` mapping from each ``<tool>.dest``
    entry; each ``dest`` must be a string.

    Raises ``ValueError`` when the file is present but type-malformed: ``tools``
    decoded to a non-table, or a ``[tools]`` ``dest`` decoded to a non-string.
    Catching these at load time turns a silent corruption into a clear
    configuration error.
    """
    if not path.is_file():
        return InstallerToml()

    # TOML is defined as UTF-8; read explicitly rather than rely on the
    # locale-dependent platform default (matches the rest of the installer).
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    tools_section = data.get("tools", {})
    if not isinstance(tools_section, dict):
        got = type(tools_section).__name__
        msg = f"installer.toml: [tools] must be a table, got {got}"
        raise ValueError(msg)  # noqa: TRY004  # ValueError is the documented config-error contract
    tool_dest_overrides: dict[str, str] = {}
    for tool, table in tools_section.items():
        if not (isinstance(table, dict) and "dest" in table):
            continue
        dest = table["dest"]
        if not isinstance(dest, str):
            got = type(dest).__name__
            msg = f"installer.toml: [tools] {tool}.dest must be a string, got {got}"
            raise ValueError(msg)  # noqa: TRY004  # ValueError is the documented config-error contract
        tool_dest_overrides[tool] = dest

    return InstallerToml(tool_dest_overrides=tool_dest_overrides)
