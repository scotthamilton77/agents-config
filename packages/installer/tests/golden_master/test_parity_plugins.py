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
_FIXTURE_BASIC = _FIXTURES / "basic"
_FIXTURE_COLLISION = _FIXTURES / "collision"

_BEADS_ARGS = ["--tools=claude", "--plugins=beads", "--yes"]


@pytest.mark.xfail(
    strict=True,
    reason="Plugin routes (~/.beads/formulas + scripts) must be installed; the Python "
    "pipeline never dispatches PluginRoute.routes(). Not yet wired.",
)
def test_plugin_routes_and_clean_overlay(tmp_path: Path) -> None:
    """The fixture beads plugin ships formulas + scripts (routed to ~/.beads/,
    the script executable) and non-colliding overlay files (a command + a rule).
    Bash installs all of it; the Python port never wires plugin routes, so
    ~/.beads content is the expected divergence until routes() is dispatched."""
    result = run_parity(tmp_path, args=_BEADS_ARGS, plugins_src=_FIXTURE_BASIC)

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
