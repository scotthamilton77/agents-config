"""FaultInjectingBdRunner: wrap the real runner, count .run() calls, and inject a
fault on a matched call so a fault can land MID-`work`-command (a single work
command fans out to many bd children). This is what lets the crash-recovery test
leave real partial bd state for `reconcile` to heal — a boolean env-var shim
cannot, because it faults the first child (a read) before any mutation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum

from workcli.adapters.bd.runner import BdResult, BdRunner


class Fault(Enum):
    NONZERO_EXIT = "nonzero_exit"
    MALFORMED_JSON = "malformed_json"


# fail_when receives (1-based call index, argv) and returns True to fault THIS call.
FailWhen = Callable[[int, Sequence[str]], bool]


class FaultInjectingBdRunner:
    def __init__(self, inner: BdRunner, *, fail_when: FailWhen, fault: Fault) -> None:
        self._inner = inner
        self._fail_when = fail_when
        self._fault = fault
        self._n = 0

    def run(self, args: Sequence[str]) -> BdResult:
        self._n += 1
        if self._fail_when(self._n, args):
            if self._fault is Fault.MALFORMED_JSON:
                # exit 0 + garbage stdout: the ONLY path that reaches parse.py's
                # invalid_json drift alarm (a --json read verb parses stdout).
                return BdResult(returncode=0, stdout="{ this is not valid json", stderr="")
            return BdResult(returncode=1, stdout="", stderr="injected fault (itest)")
        return self._inner.run(args)
