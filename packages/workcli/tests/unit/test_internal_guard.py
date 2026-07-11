"""The E_INTERNAL envelope guard (Finding 1): everything after the
`--protocol-version`/no-verb checks -- backend construction, the capability
gate, and the handler call -- must stay inside one guarded region.

Before this fix, `_build_backend(runner, sleep)` and `backend.capabilities`
(via `missing_capability`) ran unguarded in `main()`: an exception raised
there escaped with a raw traceback and NO envelope on stdout at all,
violating "stdout is always exactly one envelope" (spec §4). This file pins
that any exception raised anywhere in that region still yields exactly one
`E_INTERNAL` envelope on stdout, a traceback on stderr, and exit code 1.
"""

from __future__ import annotations

import json
from io import StringIO

from workcli import cli as cli_module
from workcli.envelope import ErrorCode


def test_backend_construction_failure_still_yields_one_internal_envelope(monkeypatch):
    def _boom(_runner: object, _sleep: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli_module, "_build_backend", _boom)
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["show", "x"], out=out, err=err)

    assert exit_code == 1
    # Exactly one envelope: json.loads fails loudly on any extra stdout bytes.
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == str(ErrorCode.INTERNAL)
    assert envelope["error"]["message"] == "internal error"
    # The traceback lands on stderr, never stdout.
    assert "RuntimeError" in err.getvalue()
    assert "kaboom" in err.getvalue()
