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


def test_registry_is_exactly_workcli_and_prgroom() -> None:
    """
    Given the shipped registry
    When CLI_PACKAGES is consulted
    Then it contains exactly workcli->work and prgroom->prgroom, and
    RETIRED_CLIS is empty.

    Pins the closed registry; pdlc/holding-place/vizsuite must NOT
    auto-deploy.
    """
    assert [s.name for s in CLI_PACKAGES] == ["workcli", "prgroom"]
    by_name = {s.name: s for s in CLI_PACKAGES}
    assert by_name["workcli"] == CliSpec(
        "workcli", "packages/workcli", "work", ("--protocol-version",)
    )
    assert by_name["prgroom"] == CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
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
