"""The capability gate (decision 11): dispatch refuses a verb the backend's
`Capabilities` declares unsupported, before its handler ever runs.

bd's own `Capabilities` are all `True` (`ready`, `sync`, dep types), so the
rejection path can only be exercised with a stub backend, never `BdBackend`.
This file covers the `ready` case now, ahead of Task 5's `sync` case and any
fuller capability matrix.
"""

from __future__ import annotations

import json
from io import StringIO

from workcli import cli as cli_module
from workcli.backend import Capabilities
from workcli.envelope import ErrorCode


class _StubReadyDenyingBackend:
    """Just enough of `Backend` to prove the gate never reaches the handler."""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(supports_ready=False, supports_dep_types=True, supports_sync=True)

    def ready(self, _label: str | None) -> list[object]:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")


def test_ready_dispatch_is_refused_when_the_backend_declares_no_support(monkeypatch):
    monkeypatch.setattr(
        cli_module, "_build_backend", lambda _runner, _sleep: _StubReadyDenyingBackend()
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["ready"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == str(ErrorCode.UNSUPPORTED_CAPABILITY)
