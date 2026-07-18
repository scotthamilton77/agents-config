"""The capability gate (decision 11): dispatch refuses a verb the backend's
`Capabilities` declares unsupported, before its handler ever runs.

bd's own `Capabilities` are all native (`ready`, `sync`, `supports_dep_write`),
so the rejection path can only be exercised with a stub backend, never
`BdBackend`.
"""

from __future__ import annotations

import json
from io import StringIO

from workcli import cli as cli_module
from workcli.backend import Capabilities, ReadySupport, SyncSupport
from workcli.envelope import ErrorCode
from workcli.model import DepListing, SyncResult


class _StubReadyDenyingBackend:
    """Just enough of `Backend` to prove the gate never reaches the handler."""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.UNSUPPORTED, sync=SyncSupport.NATIVE, supports_dep_write=True
        )

    def ready(self, _label: str | None) -> list[object]:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")


class _StubSyncDenyingBackend:
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.NATIVE, sync=SyncSupport.UNSUPPORTED, supports_dep_write=True
        )

    def sync(self, *, pull: bool) -> object:  # noqa: ARG002 -- stub proves the gate refuses first
        raise AssertionError("capability gate must refuse dispatch before the handler runs")


class _StubDepWriteDenyingBackend:
    """`dep list` must reach the handler; `dep add`/`dep remove` must not."""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.NATIVE, sync=SyncSupport.NATIVE, supports_dep_write=False
        )

    def dep_list(self, _item_id: str) -> DepListing:
        return DepListing(depends_on=[], dependents=[])

    def get(self, _item_id: str) -> object:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")

    def dep_mutate(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")


class _StubServerAuthoritativeSyncBackend:
    """`sync` disposition SERVER_AUTHORITATIVE: an honest no-op, `backend.sync` never called."""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.NATIVE,
            sync=SyncSupport.SERVER_AUTHORITATIVE,
            supports_dep_write=True,
        )

    def sync(self, *, pull: bool) -> SyncResult:  # noqa: ARG002
        raise AssertionError("SERVER_AUTHORITATIVE sync must never call backend.sync")


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


def test_sync_dispatch_is_refused_when_the_backend_declares_no_support(monkeypatch):
    monkeypatch.setattr(
        cli_module, "_build_backend", lambda _runner, _sleep: _StubSyncDenyingBackend()
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["sync"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == str(ErrorCode.UNSUPPORTED_CAPABILITY)


def test_dep_add_dispatch_is_refused_when_the_backend_denies_dep_write(monkeypatch):
    monkeypatch.setattr(
        cli_module, "_build_backend", lambda _runner, _sleep: _StubDepWriteDenyingBackend()
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["dep", "add", "x.1", "x.2"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == str(ErrorCode.UNSUPPORTED_CAPABILITY)


def test_dep_list_dispatch_is_allowed_when_the_backend_denies_dep_write(monkeypatch):
    monkeypatch.setattr(
        cli_module, "_build_backend", lambda _runner, _sleep: _StubDepWriteDenyingBackend()
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["dep", "list", "x.1"], out=out, err=err)

    assert exit_code == 0
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"] == {"depends_on": [], "dependents": []}


def test_sync_dispatch_is_an_honest_noop_when_the_backend_is_server_authoritative(monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "_build_backend",
        lambda _runner, _sleep: _StubServerAuthoritativeSyncBackend(),
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["sync"], out=out, err=err)

    assert exit_code == 0
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"] == {"synced": False, "mode": "noop"}
