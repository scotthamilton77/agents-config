"""Golden-master plugin parity: bash vs Python with an active plugin overlay.

Real beads plugin content is archived out of ``src/plugins/``, so these
scenarios point both installers at a synthetic fixture tree (under ``fixtures/
plugins/``) via the inert ``INSTALLER_PLUGINS_SRC`` seam, reusing the ``beads``
identity both installers recognise. The fixtures exercise plugin *routes*
(``~/.beads/...``) and plugin *overlays* (tool-namespace content + merges)
without resurrecting shippable plugin files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity

pytestmark = pytest.mark.golden_master

_FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
_FIXTURE_BASIC = _FIXTURES / "basic"  # routes only (formulas + scripts)
_FIXTURE_OVERLAY = _FIXTURES / "overlay_only"  # non-colliding command + rule
_FIXTURE_COLLISION = _FIXTURES / "collision"  # overlay rule colliding with a shared rule

_BEADS_ARGS = ["--tools=claude", "--plugins=beads", "--yes"]


def test_plugin_routes(tmp_path: Path) -> None:
    """The fixture beads plugin ships formulas + an executable script, routed to
    ~/.beads/formulas and ~/.beads/scripts. Both installers place them identically,
    including the script's exec bit — the Python pipeline now dispatches
    PluginRoute.routes() through install_plugin_routes (G2)."""
    result = run_parity(tmp_path, args=_BEADS_ARGS, plugins_src=_FIXTURE_BASIC)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_plugin_clean_overlay(tmp_path: Path) -> None:
    """A plugin overlaying non-colliding files (a command + a rule, fresh names)
    into the tool namespaces must place them identically in both installers.
    Routes-free, so this pins clean-overlay parity independently of the route
    gap — the Python overlay engine already handles this path."""
    result = run_parity(tmp_path, args=_BEADS_ARGS, plugins_src=_FIXTURE_OVERLAY)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_plugin_overlay_collision_merges(tmp_path: Path) -> None:
    """The fixture beads plugin overlays a rule named ``delegation.md`` that
    collides with the shared rule of the same name. Both installers must
    append-merge the two into one file identically (overlay-merge parity); the
    fixture carries no formulas, so this isolates the merge from routes."""
    result = run_parity(tmp_path, args=_BEADS_ARGS, plugins_src=_FIXTURE_COLLISION)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
