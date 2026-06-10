"""Unit tests for installer.plugins.registry.

Each test pins a design decision from the F.1 spec
(docs/specs/2026-06-07-w1qls.6.1-plugin-registry-design.md). isinstance /
@runtime_checkable machinery and attribute-literal assertions are
deliberately absent — see the writing-unit-tests tautology filter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from installer.plugins.registry import UnknownPluginError, discover

_SOURCES = Path(__file__).parents[1] / "fixtures" / "sources"


@dataclass(frozen=True, slots=True)
class _FakeSpecialized:
    """Stand-in for a future specialized adapter (e.g. beads, F.4). Same
    construction shape as GenericPluginAdapter: (name, source_path)."""

    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert stub  # pragma: no cover
        return True


def test_discover_finds_the_canonical_test_plugin_fixture() -> None:
    """
    Given the committed tests/fixtures/sources/ tree
    When discover() scans it
    Then `test-plugin` is discovered with source_path pointing at its dir.

    Pins: the canonical exercise fixture exists and is discoverable.
    """
    discovered = discover(_SOURCES)
    assert "test-plugin" in discovered
    assert discovered["test-plugin"].source_path == _SOURCES / "test-plugin"


def test_discover_returns_only_plugin_directories(tmp_path: Path) -> None:
    """
    Given a plugins root with a plugin dir, a loose file, a dot-dir, and an
    underscore-dir
    When discover() scans it
    Then only the plain plugin directory is returned.

    Pins: discovery scans direct subdirectories, skipping non-directory
    entries (e.g. AGENTS.md) and `.`/`_`-prefixed directories.
    """
    (tmp_path / "myplugin").mkdir()
    (tmp_path / "notes.md").write_text("loose file")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "_scratch").mkdir()
    discovered = discover(tmp_path)
    assert set(discovered) == {"myplugin"}
    assert discovered["myplugin"].source_path == tmp_path / "myplugin"


def test_discover_dispatches_to_specialized_class_when_registered(
    tmp_path: Path,
) -> None:
    """
    Given a plugin name present in the injected `specialized` map
    When discover() builds its adapter
    Then the adapter is an instance of the specialized class, not the generic.

    Pins: the name->factory dispatch that F.4 uses to register BeadsAdapter.
    """
    (tmp_path / "beads").mkdir()
    discovered = discover(tmp_path, specialized={"beads": _FakeSpecialized})
    assert type(discovered["beads"]) is _FakeSpecialized


def test_unknown_plugin_error_exposes_structured_attributes() -> None:
    """
    When UnknownPluginError("gamma", ("alpha", "beta")) is constructed
    Then .name == "gamma" and .valid == ("alpha", "beta").

    Pins: structured-exception contract — callers assert on data, not the
    message string (mirrors UnknownToolError).
    """
    err = UnknownPluginError("gamma", ("alpha", "beta"))
    assert err.name == "gamma"
    assert err.valid == ("alpha", "beta")
