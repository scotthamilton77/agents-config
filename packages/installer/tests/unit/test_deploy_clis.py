"""Tests for the deploy_clis decision engine (spec §6)."""

from pathlib import Path

import pytest

from installer.core.clis import CliSpec, CommandResult, ScriptedCliDeploy
from installer.core.consent import ConsentRequiredError
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.run import deploy_clis

_SPEC = CliSpec("workcli", "packages/workcli", "work", ("--protocol-version",))
_OK = CommandResult(ok=True, output="")


def _pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "packages" / "workcli"
    (pkg / "src").mkdir(parents=True, exist_ok=True)  # idempotent: helpers layer on it
    (pkg / "pyproject.toml").write_bytes(b"[project]\n")
    (pkg / "src" / "m.py").write_bytes(b"pass")
    return pkg


def _prior_with_current_digest(tmp_path: Path) -> Receipt:
    from installer.core.clis import cli_source_digest

    digest = cli_source_digest(_pkg(tmp_path))
    return Receipt(clis=(CliReceiptEntry(name="workcli", binary="work", digest=digest),))


def test_verify_skip_smokes_and_skips(tmp_path: Path) -> None:
    """
    Given a receipt entry with the current digest, shim present, provenance
    proven, smoke passing
    When deploy_clis runs
    Then no install fires, the smoke ran against the absolute shim path,
    and the counter is skipped.

    Pins spec §6 verify row / item 1. Shim budget: 1 (decision read only —
    no install happened).
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={"workcli": frozenset({"work"})},
        which_map={"work": shim},
        shims=[shim],
        smokes=[_OK],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=True,
    )
    assert not outcome.any_failed
    assert outcome.counters["cli:workcli"].skipped == 1
    assert ("smoke", str(shim)) in deploy.transcript
    assert not any(t[0] == "tool_install" for t in deploy.transcript)


def test_verify_smoke_failure_heals_with_force(tmp_path: Path) -> None:
    """
    Given digest-equal receipt + shim present + provenance proven, but smoke
    failing
    When deploy_clis runs
    Then a force=True reinstall fires without a consent prompt, then
    re-smokes; the entry is refreshed.

    Pins spec §6 verify row heal-on-fail / item 1. Shim budget: 2 (decision
    + post-install re-read after the successful heal install).
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={"workcli": frozenset({"work"})},
        which_map={"work": shim},
        shims=[shim, shim],
        smokes=[CommandResult(ok=False, output="boom"), _OK],
        installs=[_OK],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert not outcome.any_failed
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), True) in deploy.transcript
    assert not any(e.channel == "confirm" for e in io.transcript)
    assert "workcli" in outcome.deployed


def test_heal_missing_shim_reinstalls_without_prompt(tmp_path: Path) -> None:
    """
    Given a receipt entry, shim missing, env absent entirely
    When deploy_clis runs
    Then it reinstalls without a prompt (created counter) — env absent uses
    force=False.

    Pins spec §6 heal row + provenance-absent exception / items 3, 19.
    Shim budget: 2 (decision None + post-install re-read).
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={},  # env absent entirely -> non-forcing heal
        which_map={"work": shim},
        shims=[None, shim],
        installs=[_OK],
        smokes=[_OK],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].created == 1
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), False) in deploy.transcript
    assert not any(e.channel == "confirm" for e in io.transcript)


def test_fresh_install_no_evidence_no_prompt(tmp_path: Path) -> None:
    """
    Given no receipt entry, no shim, tool_list proving the env absent
    When deploy_clis runs
    Then a force=False install fires with no prompt; created counter; entry
    recorded after smoke.

    Pins spec §6 fresh row / items 2, 18. Shim budget: 2.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={},
        which_map={"work": shim},
        shims=[None, shim],
        installs=[_OK],
        smokes=[_OK],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].created == 1
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), False) in deploy.transcript
    assert "workcli" in outcome.deployed
