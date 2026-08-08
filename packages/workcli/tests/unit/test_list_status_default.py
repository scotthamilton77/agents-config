"""`work list` answers every status unless the caller narrows it.

The default used to be whatever set of statuses the backend listed when it
was not asked, which is live work only: measured on this repository's own
tracker, 89 items where 277 exist. A caller reading that envelope could not
tell it from a complete listing -- the same failure the unbounded `--limit`
already closed on the row-count axis, and `search` on this one.

What the unit level can pin is the argv the adapter sends and the argv it
does not send. A scripted runner returns whatever it was scripted with, so
it can neither hide a closed row nor prove one comes back; that is the
integration suite's job (`tests/integration/test_list_status.py`).
"""

from __future__ import annotations

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult

_EMPTY = BdResult(returncode=0, stdout="[]", stderr="")


def _runner() -> ScriptedBdRunner:
    return ScriptedBdRunner(steps=[ScriptedStep(("list",), _EMPTY)])


def test_list_asks_for_every_status_when_the_caller_named_none():
    runner = _runner()

    exit_code, _, _ = run_cli_with_runner(["list"], runner)

    assert exit_code == 0
    assert runner.calls == [("list", "--json", "--all", "--limit", "0")]


def test_list_asks_for_one_status_only_when_the_caller_named_one():
    runner = _runner()

    exit_code, _, _ = run_cli_with_runner(["list", "--status", "closed"], runner)

    assert exit_code == 0
    # The caller's narrowing REPLACES the wide ask rather than riding beside
    # it: a listing carries either every status or the one that was named.
    assert runner.calls == [("list", "--json", "--status", "closed", "--limit", "0")]
