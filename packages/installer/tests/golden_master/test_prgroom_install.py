"""install.sh prgroom-CLI install/uninstall behavior (bash installer only).

Unlike the parity suite, these scenarios assert behavior that install.sh owns
*alone*: install.py performs no prgroom step (design §7.2 makes install.sh the
sole owner of the ``uv tool install`` lifecycle). So there is nothing to compare
against — these drive install.sh directly and assert what command it decided to
hand to ``uv`` at the system boundary.

``uv`` is the system boundary here, so it is replaced by a fake stub that records
its argv to a log file and exits 0 — no real wheel build, no network, hermetic.
Marked ``golden_master`` because it spawns the bash installer (slow, no src
coverage), so it runs under ``make golden-master-installer``, not the fast gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.golden_master._runner import _BASH, _INSTALL_SH, REPO_ROOT

pytestmark = pytest.mark.golden_master

_CLAUDE_ARGS = ["--tools=claude", "--plugins=", "--yes"]
_RUN_TIMEOUT_S = 120


def _write_fake_uv(bin_dir: Path, log: Path) -> None:
    """Write a fake ``uv`` that logs its full argv and fakes ``tool list``.

    ``tool list`` prints a prgroom entry so install.sh's prune-uninstall guard
    (which greps ``uv tool list`` for an installed prgroom) sees it as present.
    Every invocation appends its argv to ``log`` and exits 0 — the stub never
    builds or fetches anything.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'if [ "$1" = "tool" ] && [ "$2" = "list" ]; then\n'
        "  printf 'prgroom v0.1.0\\n- prgroom\\n'\n"
        "fi\n"
        "exit 0\n"
    )
    uv.chmod(0o755)


def _run_install_sh(
    home: Path,
    *,
    args: list[str],
    extra_env: dict[str, str] | None = None,
    uv_dir: Path | None = None,
    path_override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run scripts/install.sh into ``home`` with a hermetic, pinned env.

    ``uv_dir`` (when given) is prepended to PATH so the fake ``uv`` there shadows
    any real uv. ``path_override`` replaces the base PATH entirely (used to run
    with uv stripped from PATH). Mirrors the parity runner's env pins (HOME /
    locale / INSTALLER_PLUGINS_SRC) so a leaked ambient value can't make a run
    non-hermetic.
    """
    path = path_override if path_override is not None else os.environ.get("PATH", "")
    if uv_dir is not None:
        path = f"{uv_dir}{os.pathsep}{path}"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": path,
        "LC_ALL": "C",
        "LANG": "C",
        "INSTALLER_PLUGINS_SRC": "",
        # These tests exercise the prgroom paths, so pin the master toggle ON —
        # otherwise a leaked ambient INSTALLER_PRGROOM=0 (the value the parity
        # harness exports) would disable the very code under test and let the
        # dry-run assertion pass for the wrong reason.
        "INSTALLER_PRGROOM": "1",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, hermetic env
        [_BASH, str(_INSTALL_SH), *args],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_S,
        check=False,
    )


def test_install_invokes_uv_tool_install_force(tmp_path: Path) -> None:
    """A normal install (uv present, package in source tree) hands
    ``tool install --force <packages/prgroom>`` to uv — the §7.2 install path."""
    if shutil.which("jq") is None:
        pytest.skip("bash installer requires jq on PATH")
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "uv.log"
    _write_fake_uv(tmp_path / "bin", log)

    result = _run_install_sh(home, args=_CLAUDE_ARGS, uv_dir=tmp_path / "bin")

    assert result.returncode == 0, result.stderr
    assert log.exists(), "fake uv was never invoked — install.sh skipped prgroom"
    invocations = log.read_text()
    assert "tool install --force" in invocations, invocations
    assert str(REPO_ROOT / "packages" / "prgroom") in invocations, invocations


def _core_tools_present(path: str) -> bool:
    """True if the bash installer's core tools all resolve under ``path``."""
    return all(shutil.which(t, path=path) is not None for t in ("bash", "jq", "git"))


def _path_without_uv() -> str | None:
    """A PATH on which uv is absent but the installer's core tools resolve, or
    None when that can't be arranged.

    When uv is already absent, the ambient PATH already satisfies the condition —
    return it so the graceful-skip branch is exercised exactly where it matters
    most (a host with no uv), rather than skipping the test there. When uv is
    present, strip its directory; return None only if uv stays reachable via
    another entry or stripping it would also drop a core tool.
    """
    uv = shutil.which("uv")
    if uv is None:
        ambient = os.environ.get("PATH", "")
        return ambient if _core_tools_present(ambient) else None
    uv_dir = Path(uv).parent.resolve()
    kept = [
        e for e in os.environ.get("PATH", "").split(os.pathsep) if e and Path(e).resolve() != uv_dir
    ]
    reduced = os.pathsep.join(kept)
    if shutil.which("uv", path=reduced) is not None:
        return None  # uv reachable via another PATH entry — can't isolate
    if not _core_tools_present(reduced):
        return None  # core tool shared uv's dir — isolating uv would break install
    return reduced


def test_uv_absent_skips_gracefully(tmp_path: Path) -> None:
    """With uv off PATH, install.sh skips the prgroom CLI install and still exits
    0 — the §7.2 ``uv``-present guard, graceful-skip branch."""
    reduced = _path_without_uv()
    if reduced is None:
        pytest.skip("cannot isolate uv from PATH on this host")
    home = tmp_path / "home"
    home.mkdir()

    result = _run_install_sh(home, args=_CLAUDE_ARGS, path_override=reduced)

    assert result.returncode == 0, result.stderr
    # Pin the actual skip branch, not any incidental mention of "uv" — the notice
    # is "prgroom: uv not found on PATH -- skipping CLI install ...".
    assert "uv not found" in result.stdout.lower(), result.stdout
    assert not (home / ".local" / "bin" / "prgroom").exists(), (
        "no prgroom binary should be installed when uv is absent"
    )


def test_prune_uninstalls_when_package_left_source_tree(tmp_path: Path) -> None:
    """``--prune`` with the prgroom package gone from the source tree hands
    ``tool uninstall prgroom`` to uv — the §7.2 orphan-removal branch.

    The absent source tree is simulated by pointing INSTALLER_PRGROOM_SRC at a
    path that does not exist; the fake uv's ``tool list`` reports prgroom as
    installed so the uninstall guard fires."""
    if shutil.which("jq") is None:
        pytest.skip("bash installer requires jq on PATH")
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "uv.log"
    _write_fake_uv(tmp_path / "bin", log)

    result = _run_install_sh(
        home,
        args=[*_CLAUDE_ARGS, "--prune"],
        uv_dir=tmp_path / "bin",
        extra_env={"INSTALLER_PRGROOM_SRC": str(tmp_path / "no-such-prgroom")},
    )

    assert result.returncode == 0, result.stderr
    invocations = log.read_text() if log.exists() else ""
    assert "tool uninstall prgroom" in invocations, invocations
    # Source absent => install must NOT have fired.
    assert "tool install" not in invocations, invocations


def test_prune_keeps_prgroom_when_still_in_source_tree(tmp_path: Path) -> None:
    """``--prune`` while the prgroom package is still in the source tree must NOT
    uninstall it — the orphan guard's keep branch. Guards against nuking an
    installed CLI on a routine prune."""
    if shutil.which("jq") is None:
        pytest.skip("bash installer requires jq on PATH")
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "uv.log"
    _write_fake_uv(tmp_path / "bin", log)

    result = _run_install_sh(home, args=[*_CLAUDE_ARGS, "--prune"], uv_dir=tmp_path / "bin")

    assert result.returncode == 0, result.stderr
    invocations = log.read_text() if log.exists() else ""
    assert "tool uninstall" not in invocations, invocations
    # Package present => the install path still ran, proving this wasn't a no-op.
    assert "tool install --force" in invocations, invocations


def test_dry_run_does_not_invoke_uv(tmp_path: Path) -> None:
    """``--dry-run`` announces the prgroom install but invokes no uv command —
    dry-run must mutate nothing."""
    if shutil.which("jq") is None:
        pytest.skip("bash installer requires jq on PATH")
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "uv.log"
    _write_fake_uv(tmp_path / "bin", log)

    result = _run_install_sh(home, args=[*_CLAUDE_ARGS, "--dry-run"], uv_dir=tmp_path / "bin")

    assert result.returncode == 0, result.stderr
    assert not log.exists(), "dry-run must not invoke uv"
