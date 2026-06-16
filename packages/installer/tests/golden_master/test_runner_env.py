"""Unit tests for the golden-master runner's environment construction.

These pin the *hermeticity* of ``_build_env`` without spawning subprocesses, so
they run in the fast suite (no ``golden_master`` marker). The key invariant:
``INSTALLER_PLUGINS_SRC`` is always pinned explicitly, so an ambient value
exported by a developer or CI runner can never leak into a default scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import _build_env


def test_build_env_pins_plugins_src_inert_against_ambient_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An INSTALLER_PLUGINS_SRC exported in the ambient environment must not bleed
    into a run that requests no fixture — the base env pins it to "" (which both
    installers treat as unset), keeping default scenarios on the real src/plugins."""
    monkeypatch.setenv("INSTALLER_PLUGINS_SRC", "/leaked/fixture/plugins")
    env = _build_env(tmp_path, None)
    assert env["INSTALLER_PLUGINS_SRC"] == ""


def test_build_env_extra_env_overrides_inert_default(tmp_path: Path) -> None:
    """When a fixture is requested via extra_env, it overrides the inert default."""
    env = _build_env(tmp_path, {"INSTALLER_PLUGINS_SRC": "/fixtures/basic"})
    assert env["INSTALLER_PLUGINS_SRC"] == "/fixtures/basic"


def test_build_env_pins_home_and_locale(tmp_path: Path) -> None:
    """HOME isolates the install; LC_ALL/LANG pin locale-sensitive sorts."""
    env = _build_env(tmp_path, None)
    assert env["HOME"] == str(tmp_path)
    assert env["LC_ALL"] == "C"
    assert env["LANG"] == "C"
