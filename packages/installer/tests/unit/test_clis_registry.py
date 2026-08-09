"""Tests for the CLI-deploy registry and source digest."""

from pathlib import Path

import pytest

from installer.core.clis import CLI_PACKAGES, RETIRED_CLIS, CliSpec, cli_source_digest


def _seed(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _package(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    _seed(pkg / "pyproject.toml", b"[project]\nname='p'\n")
    _seed(pkg / "src" / "p" / "__init__.py", b"")
    return pkg


def test_registry_is_exactly_prgroom_grind_executor_and_gitclean() -> None:
    """
    Given the shipped registry
    When CLI_PACKAGES is consulted
    Then it contains exactly prgroom->prgroom, grind->grind,
    executor->executor and gitclean->gitclean, and RETIRED_CLIS is empty.

    Pins the closed registry; pdlc/holding-place/vizsuite must NOT
    auto-deploy. Being gated by `make ci` is not what earns a place here —
    vizsuite is gated and stays off. The `work` facade is absent because it
    ships from its own repository, which owns its distribution; RETIRED_CLIS
    stays empty because uninstall authority over a binary this repo does not
    own is not this installer's to claim. gitclean earns its place by
    concluding one thing — whether a merge is proven — and reporting
    everything else with the measurement that stopped it. A caller who names a
    target authorizes that deletion outright.
    """
    assert [s.name for s in CLI_PACKAGES] == [
        "prgroom",
        "grind",
        "executor",
        "gitclean",
    ]
    by_name = {s.name: s for s in CLI_PACKAGES}
    assert by_name["prgroom"] == CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
    assert by_name["grind"] == CliSpec("grind", "packages/grind", "grind", ("--help",))
    assert by_name["executor"] == CliSpec("executor", "packages/executor", "executor", ("--help",))
    assert by_name["gitclean"] == CliSpec("gitclean", "packages/gitclean", "gitclean", ("--help",))
    assert RETIRED_CLIS == ()


def test_digest_missing_pyproject_raises(tmp_path: Path) -> None:
    """
    Given a directory without pyproject.toml
    When cli_source_digest runs
    Then it raises FileNotFoundError naming the dir.

    Pins that a registry entry at a non-package is a wiring
    bug — fail fast.
    """
    with pytest.raises(FileNotFoundError):
        cli_source_digest(tmp_path)


def test_digest_missing_lock_omitted_and_later_lock_changes_digest(tmp_path: Path) -> None:
    """
    Given a package without uv.lock
    When a uv.lock is added later
    Then the digest changes (lock participates when present, is silently
    omitted when absent).
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "uv.lock", b"lock")
    assert cli_source_digest(pkg) != before


def test_digest_ignores_tests_pycache_and_pyc(tmp_path: Path) -> None:
    """
    Given a package
    When files under tests/**, __pycache__/, or *.pyc change
    Then the digest does not change.

    Pins that docs/tests/build churn is not a reason to
    reinstall.
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "tests" / "test_x.py", b"t")
    _seed(pkg / "src" / "p" / "__pycache__" / "m.cpython-311.pyc", b"c")
    _seed(pkg / "src" / "p" / "stray.pyc", b"c")
    assert cli_source_digest(pkg) == before


def test_digest_changes_on_src_change(tmp_path: Path) -> None:
    """
    Given a package
    When a file under src/** changes
    Then the digest changes.

    Pins that src/** is deployable source.
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "src" / "p" / "__init__.py", b"changed")
    assert cli_source_digest(pkg) != before
