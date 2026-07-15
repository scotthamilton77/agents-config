from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import tomli_w

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
      those whose adapter reports `is_detected(home) is True`. claude's
      adapter is always-on (always selected); known_tools() sorts it first,
      so it also leads.
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


def parse_profiles_csv(csv: str) -> tuple[str, ...]:
    """Translate the ``--profiles=`` CLI value into a resolved profile-name tuple.

    Split on commas, strip whitespace, reject empty names (a stray comma such as
    ``beads-kit,`` would otherwise resolve as an unknown empty profile), and
    dedupe preserving first occurrence and user order. Mirrors ``resolve_tools``.
    Raises ``ValueError`` on an empty name. The caller only invokes this for a
    truthy ``--profiles`` value, so an all-empty value cannot reach here.
    """
    seen: dict[str, None] = {}
    for raw in csv.split(","):
        name = raw.strip()
        if not name:
            raise ValueError("--profiles contains an empty profile name (check for stray commas)")  # noqa: TRY003  # single call-site; subclass not justified
        seen.setdefault(name, None)
    return tuple(seen.keys())


def read_project_profiles(project_root: Path) -> tuple[str, ...] | None:
    """Read the persisted profile selection from ``<project_root>/project-config.toml``.

    Returns ``tuple(data["install"]["profiles"])`` when present, else ``None``
    — absence of the file or of the ``[install]`` table is a valid state (no
    persisted selection yet), not an error, mirroring ``load_installer_toml``'s
    missing-file convention. Raises ``ValueError`` on any config error: a present
    ``[install]`` table whose ``profiles`` is not a list of strings, or a file
    that exists but is unreadable/undecodable/malformed (``OSError`` and TOML/
    Unicode decode errors are normalized to ``ValueError`` so the single caller
    guard surfaces one clean diagnostic instead of a traceback).
    """
    path = project_root / "project-config.toml"
    if not path.is_file():
        return None

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # ValueError covers TOMLDecodeError + UnicodeDecodeError
        msg = f"project-config.toml could not be read: {exc}"
        raise ValueError(msg) from exc  # documented config-error contract
    install = data.get("install")
    if install is None:
        return None
    if not isinstance(install, dict):
        got = type(install).__name__
        msg = f"project-config.toml: [install] must be a table, got {got}"
        raise ValueError(msg)  # noqa: TRY004  # ValueError is the documented config-error contract

    profiles = install.get("profiles")
    if profiles is None:
        return None
    if not isinstance(profiles, list) or not all(isinstance(p, str) for p in profiles):
        msg = "project-config.toml: [install] profiles must be a list of strings"
        raise ValueError(msg)  # single call-site; subclass not justified

    return tuple(profiles)


def write_project_profiles(project_root: Path, profiles: Sequence[str]) -> None:
    """Persist ``profiles`` to ``<project_root>/project-config.toml``'s
    ``[install].profiles``, the write-side counterpart to
    ``read_project_profiles``.

    Merges into any existing file rather than clobbering it: every other
    top-level table (e.g. ``[merge-policy]``) survives untouched, and only
    the ``install.profiles`` key is set. A missing file is created fresh with
    just the ``[install]`` table.
    """
    path = project_root / "project-config.toml"
    data: dict[str, object] = {}
    if path.is_file():
        data = dict(tomllib.loads(path.read_text(encoding="utf-8")))

    existing_install = data.get("install")
    install: dict[str, object] = (
        dict(existing_install) if isinstance(existing_install, dict) else {}
    )
    install["profiles"] = list(profiles)
    data["install"] = install

    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def resolve_plugins_root(repo_root: Path, env: Mapping[str, str]) -> Path:
    """Resolve the plugin *source* root.

    Defaults to ``repo_root/src/plugins``. The ``INSTALLER_PLUGINS_SRC`` env var
    overrides it — a default-inert seam used only by the golden-master parity
    harness to point both installers at a fixture plugin tree. An unset *or
    empty* value falls back to the default, so an exported-but-empty var can
    never collapse the root to ``Path('')``.
    """
    override = env.get("INSTALLER_PLUGINS_SRC")
    return Path(override) if override else repo_root / "src" / "plugins"
