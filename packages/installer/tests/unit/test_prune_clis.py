"""Tests for the CLI prune half (spec §7, item 10)."""

import pytest

from installer.core.clis import CommandResult, ScriptedCliDeploy
from installer.core.consent import ConsentRequiredError
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.run import prune_clis

_OK = CommandResult(ok=True, output="")


def _prior(*names: str) -> Receipt:
    return Receipt(
        clis=tuple(CliReceiptEntry(name=n, binary=n[:4], digest="sha256:aa") for n in names)
    )


def test_retired_allowlisted_cli_uninstalled_with_consent() -> None:
    """
    Given a prior entry not in the registry but in RETIRED_CLIS
    When prune_clis runs with an accepting confirm
    Then uv tool uninstall fires, pruned counter increments, and the name
    lands in uninstalled_names.

    Pins spec §7 / item 10.
    """
    deploy = ScriptedCliDeploy(uninstalls=[_OK])
    io = ScriptedIO(confirms=[True])
    outcome = prune_clis(
        _prior("oldtool"),
        registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}),
        deploy=deploy,
        io=io,
        dry_run=False,
        auto_yes=False,
    )
    assert outcome.uninstalled_names == {"oldtool"}
    assert outcome.counters["cli:oldtool"].pruned == 1
    assert ("tool_uninstall", "oldtool") in deploy.transcript


def test_declined_uninstall_retains_entry() -> None:
    """
    Given a retired allowlisted entry and a declining confirm
    When prune_clis runs
    Then no uninstall fires and the name is NOT in uninstalled_names
    (retirement retried next prune).

    Pins spec §7 decline / item 10.
    """
    deploy = ScriptedCliDeploy()
    outcome = prune_clis(
        _prior("oldtool"),
        registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}),
        deploy=deploy,
        io=ScriptedIO(confirms=[False]),
        dry_run=False,
        auto_yes=False,
    )
    assert outcome.uninstalled_names == set()
    assert not any(t[0] == "tool_uninstall" for t in deploy.transcript)


def test_foreign_name_never_uninstalled_relinquished_instead() -> None:
    """
    Given a prior entry naming a tool outside CLI_PACKAGES | RETIRED_CLIS
    (e.g. a tampered receipt naming 'ruff')
    When prune_clis runs with auto_yes
    Then NO uninstall fires even under --yes; the name is warned about and
    relinquished.

    Pins spec §7 closed uninstall authority / item 10 (tampered receipt).
    """
    deploy = ScriptedCliDeploy()
    io = ScriptedIO()
    outcome = prune_clis(
        _prior("ruff"),
        registry_names=frozenset({"workcli"}),
        retired=frozenset(),
        deploy=deploy,
        io=io,
        dry_run=False,
        auto_yes=True,
    )
    assert outcome.relinquished_names == {"ruff"}
    assert outcome.uninstalled_names == set()
    assert not any(t[0] == "tool_uninstall" for t in deploy.transcript)
    assert any(e.channel == "warn" and "ruff" in e.message for e in io.transcript)


def test_uninstall_of_absent_tool_counts_as_success() -> None:
    """
    Given a retired entry whose uv uninstall fails with 'not installed'
    When prune_clis runs (auto_yes)
    Then the outcome treats it as uninstalled (desired state: absent).

    Pins spec §7 / item 10.
    """
    deploy = ScriptedCliDeploy(
        uninstalls=[CommandResult(ok=False, output="`oldtool` is not installed")]
    )
    outcome = prune_clis(
        _prior("oldtool"),
        registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}),
        deploy=deploy,
        io=ScriptedIO(),
        dry_run=False,
        auto_yes=True,
    )
    assert outcome.uninstalled_names == {"oldtool"}


def test_dry_run_previews_no_uninstall() -> None:
    """
    Given a retired allowlisted entry under --dry-run
    When prune_clis runs
    Then it reports would-uninstall and calls nothing.

    Pins spec §7 dry-run / item 10.
    """
    deploy = ScriptedCliDeploy()
    io = ScriptedIO()
    outcome = prune_clis(
        _prior("oldtool"),
        registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}),
        deploy=deploy,
        io=io,
        dry_run=True,
        auto_yes=False,
    )
    assert outcome.uninstalled_names == set()
    assert any("would uninstall" in e.message for e in io.transcript)
    assert not deploy.transcript or not any(t[0] == "tool_uninstall" for t in deploy.transcript)


def test_prune_no_tty_without_yes_raises() -> None:
    """
    Given a retired allowlisted entry on a non-interactive session without
    --yes or --dry-run
    When prune_clis reaches its consent point
    Then ConsentRequiredError raises (the caller maps it to exit 1) — the
    prune side honors the same no-TTY convention as the deploy side.

    Pins spec §7 no-TTY / item 12 (prune side).
    """
    deploy = ScriptedCliDeploy()
    with pytest.raises(ConsentRequiredError):
        prune_clis(
            _prior("oldtool"),
            registry_names=frozenset({"workcli"}),
            retired=frozenset({"oldtool"}),
            deploy=deploy,
            io=ScriptedIO(interactive=False),
            dry_run=False,
            auto_yes=False,
        )
