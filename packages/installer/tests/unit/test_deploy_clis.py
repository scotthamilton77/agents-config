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


def test_upgrade_consent_accept_and_decline(tmp_path: Path) -> None:
    """
    Given a receipt entry with a STALE digest, shim present, provenance ok
    When deploy_clis runs with an accepting (then declining) confirm
    Then accept -> force install + updated counter; decline -> skipped and
    no install.

    Pins spec §6 upgrade row / item 4. Shim budgets: accept 2, decline 1.
    """
    pkg = _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    prior = Receipt(clis=(CliReceiptEntry(name="workcli", binary="work", digest="sha256:stale"),))

    accept = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={"workcli": frozenset({"work"})},
        which_map={"work": shim},
        shims=[shim, shim],
        installs=[_OK],
        smokes=[_OK],
    )
    io = ScriptedIO(confirms=[True])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=accept,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].updated == 1
    assert ("tool_install", str(pkg), True) in accept.transcript

    decline = ScriptedCliDeploy(
        uv_version=(0, 10, 4), bin_dir=tmp_path / "bin",
        tool_list={"workcli": frozenset({"work"})}, which_map={"work": shim},
        shims=[shim],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=decline,
        io=ScriptedIO(confirms=[False]), dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].skipped == 1
    assert not any(t[0] == "tool_install" for t in decline.transcript)


def test_takeover_triggers_all_three_evidence_forms(tmp_path: Path) -> None:
    """
    Given no receipt entry, and (a) shim present, (b) env present shimless,
    (c) tool_list None
    When deploy_clis runs with declining confirms
    Then each form prompts for takeover and no install fires on decline.

    Pins spec §6 takeover row / item 5. Case (a) leaves the shim present,
    so the reachability gate runs — which_map keeps it green; cases (b)/(c)
    end shimless, no gate.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    cases: list[dict[str, object]] = [
        {"shims": [shim], "tool_list": {}, "which_map": {"work": shim}},
        {"shims": [None], "tool_list": {"workcli": frozenset({"work"})}},
        {"shims": [None], "tool_list": None},
    ]
    for case in cases:
        deploy = ScriptedCliDeploy(
            uv_version=(0, 10, 4), bin_dir=tmp_path / "bin", **case,  # type: ignore[arg-type]
        )
        io = ScriptedIO(confirms=[False])
        outcome = deploy_clis(
            (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
            io=io, dry_run=False, auto_yes=False,
        )
        assert outcome.counters["cli:workcli"].skipped == 1, case
        assert any(e.channel == "confirm" for e in io.transcript), case
        assert not any(t[0] == "tool_install" for t in deploy.transcript), case


def test_fresh_toctou_already_exists_reroutes_to_takeover(tmp_path: Path) -> None:
    """
    Given a clean fresh decision whose non-forcing install fails (tool
    appeared concurrently)
    When deploy_clis runs with an accepting confirm
    Then a takeover consent fires and the retry uses force=True.

    Pins spec §6 fresh row TOCTOU re-route / item 18. Shim budget: 2
    (decision None + post-install re-read after the consented force
    install; the FAILED non-forcing install triggers no re-read).
    """
    pkg = _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={},
        which_map={"work": shim},
        shims=[None, shim],
        installs=[CommandResult(ok=False, output="already installed"), _OK],
        smokes=[_OK],
    )
    io = ScriptedIO(confirms=[True])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    installs = [t for t in deploy.transcript if t[0] == "tool_install"]
    assert installs == [("tool_install", str(pkg), False), ("tool_install", str(pkg), True)]
    assert outcome.counters["cli:workcli"].updated == 1


def test_stale_receipt_foreign_provenance_requires_takeover(tmp_path: Path) -> None:
    """
    Given a receipt entry but tool_list showing a DIFFERENT tool providing
    'work' (our env gone)
    When deploy_clis runs with a declining confirm
    Then no promptless heal fires — takeover consent, decline skips.

    Pins spec §6 provenance precondition / item 19.
    """
    shim = tmp_path / "bin" / "work"
    prior = _prior_with_current_digest(tmp_path)  # creates the package dir itself
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4), bin_dir=tmp_path / "bin",
        tool_list={"other-tool": frozenset({"work"})}, which_map={"work": shim},
        shims=[shim],
    )
    io = ScriptedIO(confirms=[False])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].skipped == 1
    assert not any(t[0] == "tool_install" for t in deploy.transcript)
