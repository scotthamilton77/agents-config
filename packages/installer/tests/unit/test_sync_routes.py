"""Unit tests for installer.core.sync.sync_routes (F.4 / G2 — plugin-route install).

``sync_routes`` is the in-memory port of the bash installer's
``stage_and_install_beads`` (``scripts/install.sh:948-1124``): it walks a plugin's
``PluginRoute`` set, globs each route's ``source_dir``, and installs the matched
files at its ``dest_dir`` with the route's exec bit. Unlike the tool-file path, a
route restores a *lost* exec bit on a hash-equal skip
(``scripts/install.sh:1096``) — that restore is route-scoped, since bash carries
no general executable-file mode reconcile.

Each test pins a coded decision and drives the engine through ``ScriptedIO`` + the
real filesystem under ``tmp_path``. ``PluginRoute`` carries absolute source/dest
dirs, so a test controls both ends directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.consent import ConsentRequiredError
from installer.core.io_port import ScriptedIO
from installer.core.sync import sync_routes
from installer.plugins.base import PluginRoute

_FIXED_TS = "20260613-120000"


def _seed_file(path: Path, content: bytes, *, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)
    return path


def test_routes_install_matched_files_with_their_exec_bit(tmp_path: Path) -> None:
    """
    Given a non-exec formulas route (*.toml) and an exec scripts route (*.sh),
    each with one source file
    When sync_routes runs into fresh dests
    Then both files land at their dest_dir; the script carries an exec bit and the
    formula does not; both count as created.

    Pins AC: routes place files at ~/.beads/{formulas,scripts}; the scripts route's
    exec bit is honored (install.sh:1086 chmod +x), the formulas route's is not.
    """
    src = tmp_path / "src"
    dest_formulas = tmp_path / "home" / ".beads" / "formulas"
    dest_scripts = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "formulas" / "a.toml", b"x = 1\n")
    _seed_file(src / "scripts" / "go.sh", b"#!/bin/sh\necho hi\n", mode=0o755)
    routes = [
        PluginRoute(src / "formulas", dest_formulas, "*.toml", executable=False),
        PluginRoute(src / "scripts", dest_scripts, "*.sh", executable=True),
    ]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest_formulas / "a.toml").read_bytes() == b"x = 1\n"
    assert (dest_scripts / "go.sh").read_bytes() == b"#!/bin/sh\necho hi\n"
    assert (dest_formulas / "a.toml").stat().st_mode & 0o111 == 0
    assert (dest_scripts / "go.sh").stat().st_mode & 0o777 == 0o755
    assert counters.created == 2


def test_routes_install_only_glob_matches(tmp_path: Path) -> None:
    """
    Given a route source dir holding a matching *.toml and a non-matching README.md
    When sync_routes runs with glob *.toml
    Then only the .toml is installed; the README is left behind.

    Pins: the route glob filters the source dir (install.sh:971 `for ... *.toml`),
    so unrelated files in the plugin's route dir are not routed.
    """
    src = tmp_path / "src" / "formulas"
    dest = tmp_path / "home" / ".beads" / "formulas"
    _seed_file(src / "a.toml", b"x = 1\n")
    _seed_file(src / "README.md", b"not a formula\n")
    routes = [PluginRoute(src, dest, "*.toml", executable=False)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest / "a.toml").is_file()
    assert not (dest / "README.md").exists()
    assert counters.created == 1


def test_route_with_missing_source_dir_installs_nothing(tmp_path: Path) -> None:
    """
    Given a route whose source_dir does not exist
    When sync_routes runs
    Then nothing is installed, the dest is not created, and no error is raised.

    Pins: bash guards each plugin's route dir with `[[ -d ... ]] || continue`
    (install.sh:969,1056); a plugin without that subtree contributes no files.
    """
    src = tmp_path / "src" / "absent"
    dest = tmp_path / "home" / ".beads" / "formulas"
    routes = [PluginRoute(src, dest, "*.toml", executable=False)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert not dest.exists()
    assert (counters.created, counters.updated, counters.skipped) == (0, 0, 0)


def test_route_unchanged_script_is_skipped_but_lost_exec_bit_is_restored(
    tmp_path: Path,
) -> None:
    """
    Given an exec route whose dest already holds byte-identical content but has
    lost its exec bit (mode 0o644)
    When sync_routes runs
    Then no rewrite/backup happens (content matches), but the exec bit is restored
    to 0o755 and the item counts as skipped.

    Pins install.sh:1096 — "content matches but exec bit may have been lost;
    restore it without a full copy" — route-scoped (bash has no general reconcile).
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\n", mode=0o755)
    _seed_file(dest / "go.sh", b"#!/bin/sh\n", mode=0o644)  # same bytes, no +x
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest / "go.sh").stat().st_mode & 0o777 == 0o755  # +x restored
    assert not any(dest.glob("go.sh.backup-*"))  # content matched -> no backup
    assert (counters.skipped, counters.updated) == (1, 0)


def test_route_unchanged_nonexec_formula_is_not_chmod_executable(tmp_path: Path) -> None:
    """
    Given a non-exec route whose dest already holds byte-identical content (0o644)
    When sync_routes runs
    Then the dest stays non-executable — the +x restore is exec-route-only.

    Pins: the line-1096 restore is gated on the route's exec bit; a formula
    (executable=False) is never chmod'd +x on a skip.
    """
    src = tmp_path / "src" / "formulas"
    dest = tmp_path / "home" / ".beads" / "formulas"
    _seed_file(src / "a.toml", b"x = 1\n", mode=0o644)
    _seed_file(dest / "a.toml", b"x = 1\n", mode=0o644)
    routes = [PluginRoute(src, dest, "*.toml", executable=False)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest / "a.toml").stat().st_mode & 0o111 == 0
    assert counters.skipped == 1


def test_route_skips_a_directory_that_matches_the_glob(tmp_path: Path) -> None:
    """
    Given a route source dir holding a real a.toml file and a *directory* named
    sub.toml that also matches the glob
    When sync_routes runs
    Then only the file is installed; the glob-matching directory is skipped.

    Pins bash's `[[ -f "$formula" ]] || continue` (install.sh:972) — the glob can
    match a directory, and only regular files are routed.
    """
    src = tmp_path / "src" / "formulas"
    dest = tmp_path / "home" / ".beads" / "formulas"
    _seed_file(src / "a.toml", b"x = 1\n")
    (src / "sub.toml").mkdir(parents=True)  # a dir matching *.toml
    routes = [PluginRoute(src, dest, "*.toml", executable=False)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest / "a.toml").is_file()
    assert not (dest / "sub.toml").exists()
    assert counters.created == 1


def test_route_unchanged_script_with_intact_exec_bit_is_left_as_is(tmp_path: Path) -> None:
    """
    Given an exec route whose dest already holds byte-identical content AND still
    carries its exec bit (0o755)
    When sync_routes runs
    Then it is a clean skip — no rewrite, no backup, mode unchanged.

    Pins idempotent reinstall: the line-1096 restore is a no-op when the exec bit
    is intact (the `[[ -x ]]` guard is already satisfied).
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\n", mode=0o755)
    _seed_file(dest / "go.sh", b"#!/bin/sh\n", mode=0o755)
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    counters = sync_routes(routes, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (dest / "go.sh").stat().st_mode & 0o777 == 0o755
    assert not any(dest.glob("go.sh.backup-*"))
    assert (counters.skipped, counters.updated) == (1, 0)


def test_route_changed_file_is_backed_up_then_overwritten(tmp_path: Path) -> None:
    """
    Given an exec route whose dest holds DIFFERENT bytes
    When sync_routes runs with auto_yes (waiving the per-file confirm)
    Then the original is backed up under <name>.backup-<ts>, the new bytes are
    written, the exec bit is set, and the item counts as an update + backup.

    Pins: a changed route file is backed up before overwrite (install.sh:1109-1111
    backup; cp; chmod +x), matching the tool-file overwrite contract.
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\nnew\n", mode=0o755)
    _seed_file(dest / "go.sh", b"#!/bin/sh\nold\n", mode=0o755)
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    counters = sync_routes(routes, io=ScriptedIO(), auto_yes=True, timestamp=_FIXED_TS)

    assert (dest / "go.sh").read_bytes() == b"#!/bin/sh\nnew\n"
    assert (dest / "go.sh").stat().st_mode & 0o777 == 0o755
    assert (dest / f"go.sh.backup-{_FIXED_TS}").read_bytes() == b"#!/bin/sh\nold\n"
    assert (counters.updated, counters.backed_up) == (1, 1)


def test_route_dry_run_previews_without_writing(tmp_path: Path) -> None:
    """
    Given a fresh exec route and dry_run
    When sync_routes runs
    Then nothing is written to disk, but the would-be create is counted.

    Pins: dry_run previews and touches nothing, reusing the file installer's
    dry-run contract (install.sh:1083 "Would install").
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\n", mode=0o755)
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    counters = sync_routes(routes, io=ScriptedIO(), dry_run=True, timestamp=_FIXED_TS)

    assert not (dest / "go.sh").exists()
    assert counters.created == 1


def test_route_dry_run_does_not_restore_a_lost_exec_bit(tmp_path: Path) -> None:
    """
    Given an exec route whose dest holds byte-identical content but lost its exec
    bit (0o644), and dry_run
    When sync_routes runs
    Then the bit is NOT restored — a dry run mutates nothing, including mode.

    Pins the ``not dry_run`` term of the restore guard, mirroring bash's
    ``[[ "$DRY_RUN" == true ]] ||`` on the line-1096 restore (install.sh:1096).
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\n", mode=0o755)
    _seed_file(dest / "go.sh", b"#!/bin/sh\n", mode=0o644)  # same bytes, no +x
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    counters = sync_routes(routes, io=ScriptedIO(), dry_run=True, timestamp=_FIXED_TS)

    assert (dest / "go.sh").stat().st_mode & 0o111 == 0  # dry run left mode alone
    assert counters.skipped == 1


def test_route_non_interactive_without_waiver_raises_before_any_write(tmp_path: Path) -> None:
    """
    Given a non-interactive session, not dry_run and not auto_yes
    When sync_routes is asked to install a route
    Then it raises ConsentRequiredError up front — before any file lands — reusing
    the shared no-TTY guard rather than silently overwriting.

    Pins: sync_routes runs require_consent once up front, like sync_plan.
    """
    src = tmp_path / "src" / "scripts"
    dest = tmp_path / "home" / ".beads" / "scripts"
    _seed_file(src / "go.sh", b"#!/bin/sh\n", mode=0o755)
    routes = [PluginRoute(src, dest, "*.sh", executable=True)]

    with pytest.raises(ConsentRequiredError):
        sync_routes(routes, io=ScriptedIO(interactive=False), timestamp=_FIXED_TS)

    assert not (dest / "go.sh").exists()
