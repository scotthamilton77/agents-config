"""Unit tests for installer.config.resolve_plugins.

Each test pins a design decision from the F.1 spec
(docs/specs/2026-06-07-w1qls.6.1-plugin-registry-design.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.config import resolve_plugins
from installer.plugins.registry import UnknownPluginError


def _sources_with_two_plugins(tmp_path: Path) -> Path:
    """A plugins root containing two discoverable plugin dirs: alpha, beta."""
    root = tmp_path / "plugins"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir()
    return root


def _names(adapters: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(a.name for a in adapters)  # type: ignore[attr-defined]


def test_autodetect_includes_only_plugins_with_a_home_footprint(
    tmp_path: Path,
) -> None:
    """
    Given alpha has a home footprint (~/.alpha) and beta does not
    When resolve_plugins(override_csv=None) is called
    Then only alpha is resolved.
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    (home / ".alpha").mkdir(parents=True)
    result = resolve_plugins(home=home, plugins_root=root, override_csv=None)
    assert _names(result) == ("alpha",)


def test_autodetect_empty_when_no_footprints(tmp_path: Path) -> None:
    """
    Given no plugin has a home footprint
    When resolve_plugins(override_csv=None) is called
    Then the result is empty.
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    assert resolve_plugins(home=home, plugins_root=root, override_csv=None) == ()


def test_empty_override_installs_no_plugins(tmp_path: Path) -> None:
    """
    Given an empty --plugins= value (and a whitespace-only value)
    When resolve_plugins is called
    Then the result is empty — the deliberate asymmetry with resolve_tools,
    which raises on empty --tools= (install.sh:298-300).
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    assert resolve_plugins(home=home, plugins_root=root, override_csv="") == ()
    assert resolve_plugins(home=home, plugins_root=root, override_csv="   ") == ()


def test_explicit_override_selects_named_plugins_in_order(tmp_path: Path) -> None:
    """
    When resolve_plugins(override_csv="beta,alpha") is called
    Then the result preserves the user-supplied order (beta, alpha),
    independent of any home footprint.
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    result = resolve_plugins(home=home, plugins_root=root, override_csv="beta,alpha")
    assert _names(result) == ("beta", "alpha")


def test_explicit_override_dedupes_preserving_first_occurrence(
    tmp_path: Path,
) -> None:
    """
    When resolve_plugins(override_csv="alpha, beta ,alpha") is called
    Then duplicates collapse to first occurrence and whitespace is stripped.
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    result = resolve_plugins(home=home, plugins_root=root, override_csv="alpha, beta ,alpha")
    assert _names(result) == ("alpha", "beta")


def test_unknown_plugin_name_raises_with_valid_set(tmp_path: Path) -> None:
    """
    When resolve_plugins(override_csv="gamma") names an undiscovered plugin
    Then UnknownPluginError is raised with .name and the sorted .valid set.
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    with pytest.raises(UnknownPluginError) as exc:
        resolve_plugins(home=home, plugins_root=root, override_csv="gamma")
    assert exc.value.name == "gamma"
    assert exc.value.valid == ("alpha", "beta")


def test_stray_empty_element_raises_value_error(tmp_path: Path) -> None:
    """
    When resolve_plugins(override_csv="alpha,,beta") contains a stray empty
    element among real names
    Then ValueError is raised (mirrors resolve_tools' stray-comma guard).
    """
    root = _sources_with_two_plugins(tmp_path)
    home = tmp_path / "home"
    with pytest.raises(ValueError):
        resolve_plugins(home=home, plugins_root=root, override_csv="alpha,,beta")
