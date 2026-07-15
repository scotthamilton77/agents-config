from __future__ import annotations

from tests.integration.fault_runner import Fault, FaultInjectingBdRunner
from workcli.adapters.bd.runner import BdResult


class _RecordingRunner:
    """A fake inner BdRunner: records calls, returns a benign ok result."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(list(args))
        return BdResult(returncode=0, stdout="[]", stderr="")


def test_delegates_until_predicate_then_injects_nonzero():
    inner = _RecordingRunner()
    runner = FaultInjectingBdRunner(
        inner, fail_when=lambda n, _argv: n == 2, fault=Fault.NONZERO_EXIT
    )
    first = runner.run(["show", "a", "--json"])
    second = runner.run(["update", "a", "--status", "closed"])

    assert first.returncode == 0  # delegated to real inner
    assert inner.calls == [["show", "a", "--json"]]  # call 2 never reached inner
    assert second.returncode != 0  # injected fault
    assert "injected" in second.stderr


def test_malformed_json_fault_is_exit_zero_garbage_stdout():
    inner = _RecordingRunner()
    runner = FaultInjectingBdRunner(
        inner, fail_when=lambda _n, argv: "--json" in argv, fault=Fault.MALFORMED_JSON
    )
    result = runner.run(["show", "a", "--json"])

    assert result.returncode == 0
    assert result.stdout == "{ this is not valid json"
    assert inner.calls == []  # faulted on the first matching call
