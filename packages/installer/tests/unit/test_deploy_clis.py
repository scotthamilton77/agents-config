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


def test_smoke_failure_after_install_fails_run_no_entry(tmp_path: Path) -> None:
    """
    Given a fresh install whose post-install smoke fails
    When deploy_clis runs
    Then any_failed is True, err carries the smoke output, and no deployed
    entry is recorded (next run retries).

    Pins spec §6 failure surfacing / item 7.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4), bin_dir=tmp_path / "bin", tool_list={},
        shims=[None, shim],
        installs=[_OK], smokes=[CommandResult(ok=False, output="kaboom")],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed and "workcli" not in outcome.deployed
    assert any(e.channel == "err" and "kaboom" in e.message for e in io.transcript)


def test_install_ok_but_no_shim_is_failure(tmp_path: Path) -> None:
    """
    Given an install that reports ok but produces no shim
    When deploy_clis runs
    Then it is a failure (err), not a silent success.

    Pins spec §6 / item 7 (install-ok-but-no-shim).
    """
    _pkg(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4), bin_dir=tmp_path / "bin", tool_list={},
        shims=[None, None], installs=[_OK],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed


def test_one_broken_cli_does_not_block_the_other(tmp_path: Path) -> None:
    """
    Given two registry CLIs where the first reaches a genuine hard install
    failure (receipt-owned heal whose force install fails) and the second
    is a clean fresh install
    When deploy_clis runs
    Then the second still deploys and any_failed is True.

    Pins spec §6/§8: record-and-continue, exit 1 at the end / item 8.
    CLI1 path: verify (digest equal, provenance ok) -> smoke fail -> heal
    force install FAILS -> hard failure, no consent involved. CLI2: fresh
    success. Shim budgets: CLI1 = 1 (decision; failed install, no re-read),
    CLI2 = 2.
    """
    pkg2 = tmp_path / "packages" / "prgroom"
    (pkg2 / "src").mkdir(parents=True)
    (pkg2 / "pyproject.toml").write_bytes(b"[project]\n")
    spec2 = CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
    prior = _prior_with_current_digest(tmp_path)  # also creates workcli pkg
    shim1 = tmp_path / "bin" / "work"
    shim2 = tmp_path / "bin" / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4), bin_dir=tmp_path / "bin",
        tool_list={"workcli": frozenset({"work"})},
        which_map={"work": shim1, "prgroom": shim2},
        shims=[shim1, None, shim2],
        installs=[CommandResult(ok=False, output="resolver exploded"), _OK],
        smokes=[CommandResult(ok=False, output="stale"), _OK],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC, spec2), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed
    assert "prgroom" in outcome.deployed and "workcli" not in outcome.deployed
    assert any(e.channel == "err" and "resolver exploded" in e.message for e in io.transcript)


def test_dry_run_previews_every_branch_without_subprocess(tmp_path: Path) -> None:
    """
    Given each decision-table state under --dry-run
    When deploy_clis runs
    Then each reports its would-X line and never calls
    tool_install/smoke/update_shell.

    Pins spec §6 dry-run / item 6 (each branch reports would-X).
    """
    prior_current = _prior_with_current_digest(tmp_path)
    prior_stale = Receipt(
        clis=(CliReceiptEntry(name="workcli", binary="work", digest="sha256:stale"),)
    )
    shim = tmp_path / "bin" / "work"
    prov = {"workcli": frozenset({"work"})}
    cases: list[tuple[Receipt, list[Path | None], object, str]] = [
        (Receipt(), [None], {}, "would install"),
        (prior_current, [shim], prov, "would skip"),
        (prior_current, [None], {}, "would reinstall"),
        (prior_stale, [shim], prov, "would upgrade"),
        (Receipt(), [shim], {}, "would take over"),
    ]
    for prior, shims, tool_list, expected in cases:
        deploy = ScriptedCliDeploy(
            uv_version=(0, 10, 4), bin_dir=tmp_path / "bin",
            tool_list=tool_list,  # type: ignore[arg-type]
            shims=shims,
        )
        io = ScriptedIO()
        outcome = deploy_clis(
            (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
            io=io, dry_run=True, auto_yes=False,
        )
        assert not outcome.any_failed, expected
        assert any(expected in e.message for e in io.transcript), expected
        assert not any(
            t[0] in ("tool_install", "smoke", "update_shell") for t in deploy.transcript
        ), expected
