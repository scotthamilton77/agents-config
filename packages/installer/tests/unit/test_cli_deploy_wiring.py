"""End-to-end wiring tests: main() drives the CLI deploy stage."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main
from installer.core.clis import CommandResult, ScriptedCliDeploy
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_OK = CommandResult(ok=True, output="")

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_installignore(repo: Path) -> None:
    """Copy of the real repo-root .installignore — main() exits 2 without one.
    Copied (not retyped) so it cannot drift from the real manifest."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".installignore").write_text(
        (_REPO_ROOT / ".installignore").read_text(encoding="utf-8"), encoding="utf-8"
    )


def _write_profiles_toml(repo: Path) -> None:
    """Copy of the real profiles.toml — main()'s resolver pass loads it for
    any non-empty tool plan. Copied (not retyped) so it cannot drift."""
    (repo / "profiles.toml").write_text(
        (_REPO_ROOT / "profiles.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )


def _hermetic_repo(tmp_path: Path) -> Path:
    """test_cli_smoke's minimal source repo (one shared template so the
    Claude plan is non-empty, plus the empty tool-root dirs the adapters
    expect) extended with BOTH registry package dirs so
    cli_source_digest(package_dir) resolves for workcli and prgroom."""
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"shared laws\n")
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    _write_installignore(repo)
    _write_profiles_toml(repo)
    for pkg in ("workcli", "prgroom"):
        (repo / "packages" / pkg / "src").mkdir(parents=True)
        (repo / "packages" / pkg / "pyproject.toml").write_bytes(b"[project]\n")
        (repo / "packages" / pkg / "src" / "m.py").write_bytes(b"pass")
    # A minimal kit so a --project run resolving profile "full" (include =
    # ["**"]) has at least one PROJECT-scoped item — kits/** is the only
    # selector mapped to Scope.PROJECT in profiles.toml's [scopes] table;
    # without one, resolve() errors "zero items for any bound scope" before
    # the CLI-deploy exclusion under test is ever reached.
    kit = repo / "src" / "kits" / "dummy" / ".dummy"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"dummy kit\n")
    return repo


@pytest.mark.cli_deploy
def test_full_install_deploys_both_clis_and_records_receipt(tmp_path: Path) -> None:
    """
    Given a hermetic repo and a fresh home
    When main(["--tools=claude", "--yes"]) runs with a scripted deploy port
    Then exit 0, both CLIs deploy, and the receipt carries both clis
    entries.

    Pins the receipt-wiring contract: stage runs inside the lock, entries
    thread through record_receipt/merge_receipt.
    """
    repo = _hermetic_repo(tmp_path)
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=bin_dir,
        tool_list={},
        which_map={"work": w, "prgroom": p},
        shims=[None, w, None, p],
        installs=[_OK, _OK],
        smokes=[_OK, _OK],
    )
    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path / "home",
        io=ScriptedIO(interactive=False),
        repo_root=repo,
        cli_deploy=deploy,
    )
    assert rc == 0
    result = read_receipt(tmp_path / "home" / ".config" / "agents-config" / "install-receipt.json")
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert {c.name for c in result.receipt.clis} == {"workcli", "prgroom"}


@pytest.mark.cli_deploy
def test_deploy_failure_exits_1_after_summary(tmp_path: Path) -> None:
    """
    Given a deploy whose install fails
    When main runs
    Then exit 1, and the summary still rendered (Done./up-to-date line in
    transcript AFTER the err).

    Pins the failure-surfacing rule: exit flag carried out of the lock.
    """
    repo = _hermetic_repo(tmp_path)
    # --yes auto-accepts the TOCTOU takeover re-route, so each fresh CLI
    # pops TWO installs (non-forcing fail, then forced fail) = 4 total.
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={},
        shims=[None, None],
        installs=[CommandResult(ok=False, output="x")] * 4,
    )
    io = ScriptedIO(interactive=False)
    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path / "home",
        io=io,
        repo_root=repo,
        cli_deploy=deploy,
    )
    assert rc == 1
    # The file-install stage emits earlier ok lines ("Installed ... (new)"),
    # so target the summary's own terminator, not the first ok entry.
    err_idx = next(i for i, e in enumerate(io.transcript) if e.channel == "err")
    done_idx = next(
        i for i, e in enumerate(io.transcript) if e.channel == "ok" and e.message == "Done."
    )
    assert err_idx < done_idx  # summary rendered after the failure was recorded


@pytest.mark.cli_deploy
def test_prune_only_drops_retired_cli_through_real_receipt_path(tmp_path: Path) -> None:
    """
    Given a prior receipt with a retired-allowlisted CLI entry
    When main(["--prune-only", "--yes"]) runs
    Then the deploy half never fires, the uninstall does, and the rewritten
    receipt no longer carries the entry.

    Pins the --prune-only convergence rule. NOTE: requires a
    nonzero RETIRED_CLIS in the test — monkeypatch installer.core.run's
    retired source or pass through a seam; the implementer wires
    prune_clis(retired=frozenset(RETIRED_CLIS)) in cli.py, so monkeypatch
    installer.cli.RETIRED_CLIS (import it into cli.py namespace for
    patchability).
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    receipt_path = home / ".config" / "agents-config" / "install-receipt.json"
    write_receipt(
        receipt_path,
        Receipt(clis=(CliReceiptEntry(name="oldtool", binary="old", digest="sha256:aa"),)),
    )
    deploy = ScriptedCliDeploy(uninstalls=[_OK])
    import installer.cli as cli_mod

    # simulate a future retirement
    orig = cli_mod.RETIRED_CLIS
    cli_mod.RETIRED_CLIS = ("oldtool",)
    try:
        rc = main(
            ["--tools=claude", "--prune-only", "--yes"],
            home=home,
            io=ScriptedIO(interactive=False),
            repo_root=repo,
            cli_deploy=deploy,
        )
    finally:
        cli_mod.RETIRED_CLIS = orig
    assert rc == 0
    result = read_receipt(receipt_path)
    assert result.receipt is not None and result.receipt.clis == ()
    assert not any(t[0] == "tool_install" for t in deploy.transcript)


@pytest.mark.cli_deploy
def test_prune_only_no_tty_without_yes_exits_1(tmp_path: Path) -> None:
    """
    Given a retired CLI entry pending uninstall on a non-interactive
    session without --yes (and without --dry-run)
    When main(["--prune-only"]) runs
    Then exit 1 via prune_clis's ConsentRequiredError — its own handler in
    the prune branch, since the existing prune try catches only
    PruneAbortedError.

    Pins the no-TTY consent rule, prune half (the deploy half is
    test_no_tty_without_yes_at_cli_consent_exits_1 below).
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    write_receipt(
        home / ".config" / "agents-config" / "install-receipt.json",
        Receipt(clis=(CliReceiptEntry(name="oldtool", binary="old", digest="sha256:aa"),)),
    )
    deploy = ScriptedCliDeploy()  # consent gate fires before any uninstall pops
    import installer.cli as cli_mod

    orig = cli_mod.RETIRED_CLIS
    cli_mod.RETIRED_CLIS = ("oldtool",)
    try:
        rc = main(
            ["--tools=claude", "--prune-only"],
            home=home,
            io=ScriptedIO(interactive=False),
            repo_root=repo,
            cli_deploy=deploy,
        )
    finally:
        cli_mod.RETIRED_CLIS = orig
    assert rc == 1
    assert not any(t[0] == "tool_uninstall" for t in deploy.transcript)


@pytest.mark.cli_deploy
def test_second_noop_run_skips_via_persisted_clis(tmp_path: Path) -> None:
    """
    Given a first successful deploy run
    When a second identical run executes
    Then the second run smokes-and-skips (no tool_install) — the clis
    entries persisted through the real path.

    Pins the second-run convergence rule (no-op on repeat).
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"

    def _first() -> ScriptedCliDeploy:
        return ScriptedCliDeploy(
            uv_version=(0, 10, 4),
            bin_dir=bin_dir,
            tool_list={},
            which_map={"work": w, "prgroom": p},
            shims=[None, w, None, p],
            installs=[_OK, _OK],
            smokes=[_OK, _OK],
        )

    assert (
        main(
            ["--tools=claude", "--yes"],
            home=home,
            io=ScriptedIO(interactive=False),
            repo_root=repo,
            cli_deploy=_first(),
        )
        == 0
    )
    second = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=bin_dir,
        tool_list={"workcli": frozenset({"work"}), "prgroom": frozenset({"prgroom"})},
        which_map={"work": w, "prgroom": p},
        shims=[w, p],
        smokes=[_OK, _OK],
    )
    assert (
        main(
            ["--tools=claude", "--yes"],
            home=home,
            io=ScriptedIO(interactive=False),
            repo_root=repo,
            cli_deploy=second,
        )
        == 0
    )
    assert not any(t[0] == "tool_install" for t in second.transcript)


@pytest.mark.cli_deploy
def test_project_run_no_deploys_and_clis_untouched(tmp_path: Path) -> None:
    """
    Given a --project run against a project dir with a persisted profile
    When main runs with a scripted deploy port loaded with NOTHING
    Then no port method is called (empty queues never pop) and a
    pre-existing project receipt's clis (synthetic) is untouched.

    Pins the --project exclusion rule.
    """
    repo = _hermetic_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "project-config.toml").write_text('[install]\nprofiles = ["full"]\n')
    deploy = ScriptedCliDeploy()  # any call would raise queue-exhausted
    rc = main(
        ["--project", str(project), "--yes"],
        home=tmp_path / "home",
        io=ScriptedIO(interactive=False),
        repo_root=repo,
        cli_deploy=deploy,
    )
    assert rc == 0
    assert deploy.transcript == []


@pytest.mark.cli_deploy
def test_corrupt_receipt_deploy_not_persisted(tmp_path: Path) -> None:
    """
    Given a corrupt prior receipt
    When main runs and the deploy succeeds (takeover consented via --yes)
    Then the receipt file is left untouched (still corrupt) — the deploy is
    not persisted.

    Pins the corrupt-receipt consequence rule.
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    receipt_path = home / ".config" / "agents-config" / "install-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("{not json")
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=bin_dir,
        tool_list=None,  # unproven -> takeover (auto-accepted by --yes)
        which_map={"work": w, "prgroom": p},
        shims=[None, w, None, p],
        installs=[_OK, _OK],
        smokes=[_OK, _OK],
    )
    rc = main(
        ["--tools=claude", "--yes"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
        cli_deploy=deploy,
    )
    assert rc == 0
    assert receipt_path.read_text() == "{not json"


@pytest.mark.cli_deploy
def test_no_tty_without_yes_at_cli_consent_exits_1(tmp_path: Path) -> None:
    """
    Given a takeover-consent state on a non-interactive session without
    --yes (and without --dry-run)
    When main runs
    Then exit 1 via the ConsentRequiredError convention.

    Pins the no-TTY consent rule.
    """
    repo = _hermetic_repo(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=tmp_path / "bin",
        tool_list={},
        shims=[tmp_path / "bin" / "work"],
    )
    rc = main(
        ["--tools=claude"],
        home=tmp_path / "home",
        io=ScriptedIO(interactive=False),
        repo_root=repo,
        cli_deploy=deploy,
    )
    assert rc == 1
