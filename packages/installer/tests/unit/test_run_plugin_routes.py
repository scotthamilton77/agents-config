"""Unit tests for installer.core.run.install_plugin_routes (G2 — plugin-route dispatch).

The core bug this dispatch fixes: ``PluginRoute.routes()`` had zero call sites; ``core/run.py``
iterated only tool adapters, never plugin routes, so every Python install with the
beads plugin silently dropped all ``~/.beads`` content. ``install_plugin_routes``
is the missing dispatch — the plugin-side analog of ``install_pipeline``, driving
each active plugin's ``routes(home)`` through ``sync_routes``.

These pin the composition's end-state: real plugin adapters, the real filesystem
under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import InstallOutcome
from installer.core.run import install_plugin_routes
from installer.plugins.beads import BeadsPlugin
from installer.plugins.generic import GenericPluginAdapter

_FIXED_TS = "20260613-120000"


def _seed_beads_source(src: Path) -> None:
    formulas = src / ".beads" / "formulas"
    scripts = src / ".beads" / "scripts"
    formulas.mkdir(parents=True)
    scripts.mkdir(parents=True)
    (formulas / "f.toml").write_bytes(b"x = 1\n")
    (scripts / "s.sh").write_bytes(b"#!/bin/sh\n")


def test_install_plugin_routes_dispatches_beads_formulas_and_scripts(tmp_path: Path) -> None:
    """
    Given a BeadsPlugin whose source carries a formula and a script
    When install_plugin_routes runs
    Then the formula lands at home/.beads/formulas (non-exec) and the script at
    home/.beads/scripts (exec) — the routes are dispatched, not dropped.

    Pins the fix for the parity BLOCKER: routes(home) is now wired into the
    install pipeline (was a zero-call-site dead end).
    """
    home = tmp_path / "home"
    src = tmp_path / "plugin-src"
    _seed_beads_source(src)
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    per_plugin = install_plugin_routes([beads], home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    formula = home / ".beads" / "formulas" / "f.toml"
    script = home / ".beads" / "scripts" / "s.sh"
    assert formula.read_bytes() == b"x = 1\n"
    assert script.read_bytes() == b"#!/bin/sh\n"
    assert script.stat().st_mode & 0o111  # scripts land executable
    assert formula.stat().st_mode & 0o111 == 0  # formulas do not
    # Per-plugin bucket keyed by the plugin name (8.18 summary plumbing).
    assert per_plugin["beads"].created == 2


def test_install_plugin_routes_captures_per_plugin_outcomes(tmp_path: Path) -> None:
    """
    Given an ``outcomes_by_plugin`` accumulator and a BeadsPlugin with one formula
    and one script
    When install_plugin_routes runs
    Then the accumulator is keyed by the plugin name and holds the real per-item
    InstallOutcomes (a WRITTEN formula and a WRITTEN script, each with a sha256) —
    the data record_receipt later turns into routed-file receipt entries.

    Pins the capture branch: when the caller supplies the accumulator, each
    plugin's per-item outcomes are recorded into it (keyed by plugin.name), not
    discarded. Without this, the receipt could never carry routed-file entries
    from a real install.
    """
    home = tmp_path / "home"
    src = tmp_path / "plugin-src"
    _seed_beads_source(src)
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    outcomes_by_plugin: dict[str, list[InstallOutcome]] = {}
    install_plugin_routes(
        [beads],
        home=home,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
        outcomes_by_plugin=outcomes_by_plugin,
    )

    assert set(outcomes_by_plugin) == {"beads"}
    dests = {o.dest.name for o in outcomes_by_plugin["beads"]}
    assert dests == {"f.toml", "s.sh"}
    assert all(o.sha256 is not None for o in outcomes_by_plugin["beads"])


def test_install_plugin_routes_dry_run_collects_no_outcomes(tmp_path: Path) -> None:
    """
    Given a BeadsPlugin whose routes a real install WOULD write
    When install_plugin_routes runs with dry_run=True and an outcomes_by_plugin dict
    Then the plugin's key maps to an EMPTY list — no phantom WRITTEN outcomes.

    Same receipt-feeding boundary as the tool side: the outcome channel feeds
    record_receipt ("what happened on disk"); a dry run writes nothing, so it
    contributes nothing — the key is present but the list is empty. Fails while a
    live collector is threaded into sync_routes on a dry run.
    """
    home = tmp_path / "home"
    src = tmp_path / "plugin-src"
    _seed_beads_source(src)
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)

    outcomes_by_plugin: dict[str, list[InstallOutcome]] = {}
    install_plugin_routes(
        [beads],
        home=home,
        io=ScriptedIO(),
        dry_run=True,
        timestamp=_FIXED_TS,
        outcomes_by_plugin=outcomes_by_plugin,
    )

    assert not (home / ".beads" / "formulas" / "f.toml").exists()  # nothing hit disk
    assert outcomes_by_plugin == {"beads": []}  # key present, no phantom WRITTEN


def test_generic_plugin_contributes_no_routes(tmp_path: Path) -> None:
    """
    Given a generic plugin (routes() == ())
    When install_plugin_routes runs
    Then nothing is installed — only specialized adapters with bespoke
    destinations (beads) route content outside a tool tree.

    Pins: the dispatch is route-driven, so a routes-free plugin is a clean no-op.
    """
    home = tmp_path / "home"
    generic = GenericPluginAdapter(name="whatever", source_path=tmp_path / "src")

    per_plugin = install_plugin_routes([generic], home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert not (home / ".whatever").exists()
    # A routes-free plugin installs nothing, so it contributes an all-zero bucket
    # (still keyed by name so a verbose summary can print its block).
    assert per_plugin["whatever"].created == 0
    assert per_plugin["whatever"].updated == 0
    assert per_plugin["whatever"].skipped == 0
