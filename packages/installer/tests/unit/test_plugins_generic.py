"""Unit tests for installer.plugins.generic.

Each test pins a design decision from the F.1 spec
(docs/specs/2026-06-07-w1qls.6.1-plugin-registry-design.md). Tests for
dataclass/frozen/slots machinery and pathlib semantics are deliberately
absent — they test stdlib, not coded decisions. See the writing-unit-tests
tautology filter."""

from __future__ import annotations

from pathlib import Path

from installer.plugins.generic import GenericPluginAdapter


def test_is_detected_true_when_home_footprint_directory_exists(
    tmp_path: Path,
) -> None:
    """
    Given a home directory containing a directory named `.myplugin`
    When the adapter for `myplugin` is asked is_detected(home)
    Then it returns True.

    Pins: the home-footprint auto-detect convention `~/.<name>/`.
    """
    (tmp_path / ".myplugin").mkdir()
    adapter = GenericPluginAdapter(name="myplugin", source_path=tmp_path / "src")
    assert adapter.is_detected(tmp_path) is True


def test_is_detected_false_when_home_footprint_absent(tmp_path: Path) -> None:
    """
    Given an empty home directory
    When the adapter for `myplugin` is asked is_detected(home)
    Then it returns False.
    """
    adapter = GenericPluginAdapter(name="myplugin", source_path=tmp_path / "src")
    assert adapter.is_detected(tmp_path) is False


def test_is_detected_false_when_footprint_is_a_file_not_a_directory(
    tmp_path: Path,
) -> None:
    """
    Given a home directory containing a *file* named `.myplugin`
    When the adapter for `myplugin` is asked is_detected(home)
    Then it returns False.

    Pins: the convention is `.is_dir()`, not `.exists()` — a config footprint
    is a directory, and a same-named stray file must not trip detection.
    """
    (tmp_path / ".myplugin").write_text("not a directory")
    adapter = GenericPluginAdapter(name="myplugin", source_path=tmp_path / "src")
    assert adapter.is_detected(tmp_path) is False


def test_generic_plugin_has_no_bespoke_routes(tmp_path: Path) -> None:
    """
    Given a generic plugin adapter
    When routes(home) is consulted
    Then it returns an empty tuple.

    Pins: a generic plugin's content installs through the per-tool namespace
    overlay (F.2), not through bespoke destination routes — only specialized
    adapters (beads) route outside a tool tree. Empty here means "no special
    routing; overlay handles me."
    """
    adapter = GenericPluginAdapter(name="myplugin", source_path=tmp_path / "src")
    assert adapter.routes(tmp_path) == ()
