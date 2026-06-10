"""Unit tests for installer.plugins.beads.

Each test pins a coded decision from F.4 (the bead acceptance criteria and
docs/architecture/installer/installer-design.md Epic F: beads owns the
~/.beads/ destination and chmod +x on scripts). Tests for dataclass/frozen
machinery and pathlib/shutil semantics are deliberately absent — they test
stdlib, not coded decisions. See the writing-unit-tests tautology filter."""

from __future__ import annotations

from pathlib import Path

from installer.plugins.base import PluginRoute
from installer.plugins.beads import BeadsPlugin
from installer.plugins.registry import discover


def _route_by_glob(adapter: BeadsPlugin, home: Path, glob: str) -> PluginRoute:
    """Pick the single route whose glob matches; raises if not exactly one."""
    matches = [r for r in adapter.routes(home) if r.glob == glob]
    assert len(matches) == 1, f"expected one {glob!r} route, got {len(matches)}"
    return matches[0]


def test_is_detected_true_when_bd_is_on_path(tmp_path: Path) -> None:
    """
    Given a home with no ~/.beads/ directory
    But `bd` resolvable on PATH (injected probe returns a path)
    When the beads adapter is asked is_detected(home)
    Then it returns True.

    Pins: beads detection probes bd-on-PATH (install.sh:321), not just the
    home footprint the generic convention checks.
    """
    adapter = BeadsPlugin(
        name="beads",
        source_path=tmp_path / "src",
        which=lambda _cmd: "/usr/local/bin/bd",
    )
    assert adapter.is_detected(tmp_path) is True


def test_is_detected_true_when_home_footprint_exists_and_bd_absent(
    tmp_path: Path,
) -> None:
    """
    Given a home containing a ~/.beads/ directory
    But `bd` not resolvable on PATH (injected probe returns None)
    When the beads adapter is asked is_detected(home)
    Then it returns True.

    Pins: the home-footprint half of the OR (install.sh:321) — a user who has
    run beads before but lacks bd on PATH is still detected.
    """
    (tmp_path / ".beads").mkdir()
    adapter = BeadsPlugin(
        name="beads",
        source_path=tmp_path / "src",
        which=lambda _cmd: None,
    )
    assert adapter.is_detected(tmp_path) is True


def test_is_detected_false_when_neither_bd_nor_home_footprint(
    tmp_path: Path,
) -> None:
    """
    Given a home with no ~/.beads/ directory
    And `bd` not resolvable on PATH
    When the beads adapter is asked is_detected(home)
    Then it returns False.

    Pins: detection requires at least one positive probe; absent both, beads
    is not installed.
    """
    adapter = BeadsPlugin(
        name="beads",
        source_path=tmp_path / "src",
        which=lambda _cmd: None,
    )
    assert adapter.is_detected(tmp_path) is False


def test_routes_formulas_land_in_home_beads_formulas_without_exec_bit(
    tmp_path: Path,
) -> None:
    """
    Given a beads adapter with source_path <src>
    When routes(home) is consulted
    Then the formulas route reads <src>/.beads/formulas, writes
    home/.beads/formulas, globs *.toml, and is NOT executable.

    Pins AC: "Formulas land at ~/.beads/formulas/." Formulas are data, not
    scripts — no exec bit (install.sh stages them as 'toml', never chmods).
    """
    home = tmp_path / "home"
    src = tmp_path / "src"
    adapter = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    route = _route_by_glob(adapter, home, "*.toml")

    assert route.source_dir == src / ".beads" / "formulas"
    assert route.dest_dir == home / ".beads" / "formulas"
    assert route.executable is False


def test_routes_scripts_land_in_home_beads_scripts_with_exec_bit(
    tmp_path: Path,
) -> None:
    """
    Given a beads adapter with source_path <src>
    When routes(home) is consulted
    Then the scripts route reads <src>/.beads/scripts, writes
    home/.beads/scripts, globs *.sh, and IS executable.

    Pins AC: "Scripts land at ~/.beads/scripts/ with mode 0755." The exec bit
    is what distinguishes scripts from formulas (install.sh chmods +x only on
    scripts).
    """
    home = tmp_path / "home"
    src = tmp_path / "src"
    adapter = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    route = _route_by_glob(adapter, home, "*.sh")

    assert route.source_dir == src / ".beads" / "scripts"
    assert route.dest_dir == home / ".beads" / "scripts"
    assert route.executable is True


def test_registry_dispatches_beads_name_to_beads_plugin(tmp_path: Path) -> None:
    """
    Given a plugins root containing a `beads/` directory
    When discover() builds adapters using the real default _SPECIALIZED map
    Then the `beads` adapter is a BeadsPlugin (the F.4 registration).

    Pins: beads is wired into the registry's default specialized map — the
    contract F.1 reserved the slot for. Uses the real default (no injection)
    so this fails if the _SPECIALIZED entry is missing.
    """
    (tmp_path / "beads").mkdir()
    discovered = discover(tmp_path)
    assert type(discovered["beads"]) is BeadsPlugin
